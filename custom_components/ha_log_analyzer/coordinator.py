"""Data update coordinator and issue registry."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import ClientError
from homeassistant.components.system_log import DOMAIN as SYSTEM_LOG_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_CONVERSATION_AGENT_ID,
    CONF_HOME_ASSISTANT_TOKEN,
    CONF_HOME_ASSISTANT_URL,
    CONF_LOG_FILE_PATH,
    CONF_LOG_SOURCE,
    CONF_MAX_LOG_CHARS,
    CONF_POLL_INTERVAL_MINUTES,
    DEFAULT_LOG_SOURCE,
    DOMAIN,
    LOG_SOURCE_API,
    LOG_SOURCE_FILE,
    LOG_SOURCE_SYSTEM_LOG,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .gemini import PROMPT, normalize_issues_from_text

MAX_PROMPT_CHARS = 12000
MAX_SYSTEM_LOG_EXCEPTION_CHARS = 1200
MAX_SYSTEM_LOG_MESSAGE_CHARS = 400
MIN_LOG_CHARS = 300


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(issue: dict[str, str]) -> str:
    source = (
        f"{issue.get('title', '').strip().lower()}|"
        f"{issue.get('signature_hint', '').strip().lower()}|"
        f"{issue.get('description', '').strip().lower()[:180]}"
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


async def _fetch_logs_via_api(hass: HomeAssistant, ha_url: str, token: str) -> str:
    session = async_get_clientsession(hass)
    url = f"{ha_url.rstrip('/')}/api/error_log"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with session.get(url, headers=headers, timeout=30) as response:
            response.raise_for_status()
            return await response.text()
    except ClientError as exc:
        raise RuntimeError(f"Failed to pull logs from Home Assistant API: {exc}") from exc


def _fetch_logs_from_system_log(hass: HomeAssistant) -> str:
    handler = hass.data.get(SYSTEM_LOG_DOMAIN)
    if handler is None or not hasattr(handler, "records"):
        raise RuntimeError(
            "system_log is not available. Enable the System Log integration or choose another log source."
        )

    try:
        rows = handler.records.to_list()
    except Exception as exc:
        raise RuntimeError(f"Failed to read system_log records: {exc}") from exc

    lines: list[str] = []
    for row in rows:
        messages = row.get("message", [])
        message_text = " | ".join(messages) if isinstance(messages, list) else str(messages)
        if len(message_text) > MAX_SYSTEM_LOG_MESSAGE_CHARS:
            message_text = message_text[:MAX_SYSTEM_LOG_MESSAGE_CHARS] + "... [truncated]"
        lines.append(
            f"[{row.get('level', 'UNKNOWN')}] "
            f"{row.get('name', 'unknown')}: {message_text}"
        )
        if row.get("exception"):
            exception_text = str(row["exception"])
            if len(exception_text) > MAX_SYSTEM_LOG_EXCEPTION_CHARS:
                exception_text = (
                    exception_text[:MAX_SYSTEM_LOG_EXCEPTION_CHARS] + "... [truncated]"
                )
            lines.append(exception_text)
    return "\n".join(lines)


def _clip_for_conversation(logs: str, requested_log_chars: int) -> str:
    allowed_log_chars = max(
        MIN_LOG_CHARS, min(requested_log_chars, MAX_PROMPT_CHARS - len(PROMPT) - 100)
    )
    clipped = logs[-allowed_log_chars:]
    if len(clipped) > allowed_log_chars:
        clipped = clipped[-allowed_log_chars:]
    return clipped


def _is_text_too_long_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "text_query too long" in msg or "invalid_assistconfig" in msg


class HALogAnalyzerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate log analysis updates and persistent issue state."""

    def __init__(self, hass: HomeAssistant, config_entry) -> None:
        self.hass = hass
        self.config_entry = config_entry
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.issues: dict[str, dict[str, Any]] = {}
        self.last_run: str | None = None
        self.last_error: str | None = None

        super().__init__(
            hass,
            logger=hass.data[DOMAIN]["logger"],
            name=DOMAIN,
            update_interval=None,  # set dynamically from options
        )

    @property
    def merged_config(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_load(self) -> None:
        stored = await self.store.async_load()
        if isinstance(stored, dict):
            self.issues = stored.get("issues", {})
            self.last_run = stored.get("last_run")
            self.last_error = stored.get("last_error")

    async def async_save(self) -> None:
        await self.store.async_save(
            {"issues": self.issues, "last_run": self.last_run, "last_error": self.last_error}
        )

    async def async_refresh_interval(self) -> None:
        from datetime import timedelta

        interval = int(self.merged_config.get(CONF_POLL_INTERVAL_MINUTES, 15))
        self.update_interval = timedelta(minutes=max(1, interval))

    async def async_run_analysis_now(self) -> dict[str, int]:
        await self.async_request_refresh()
        return {
            "created": self.data.get("created", 0),
            "updated": self.data.get("updated", 0),
            "open_count": self.data.get("open_count", 0),
        }

    async def _async_update_data(self) -> dict[str, Any]:
        await self.async_refresh_interval()
        cfg = self.merged_config
        agent_id = str(cfg.get(CONF_CONVERSATION_AGENT_ID, "")).strip()
        log_source = str(cfg.get(CONF_LOG_SOURCE, DEFAULT_LOG_SOURCE)).strip()
        log_file_path = str(cfg.get(CONF_LOG_FILE_PATH, "")).strip()
        ha_url = str(cfg.get(CONF_HOME_ASSISTANT_URL, "")).strip()
        ha_token = str(cfg.get(CONF_HOME_ASSISTANT_TOKEN, "")).strip()
        max_chars = int(cfg.get(CONF_MAX_LOG_CHARS, 6000))

        if not agent_id:
            raise UpdateFailed("Conversation agent ID is missing.")

        try:
            if log_source == LOG_SOURCE_SYSTEM_LOG:
                logs = _fetch_logs_from_system_log(self.hass)
            elif log_source == LOG_SOURCE_API:
                if not ha_url or not ha_token:
                    raise RuntimeError("HA API source requires URL and token.")
                logs = await _fetch_logs_via_api(self.hass, ha_url=ha_url, token=ha_token)
            elif log_source == LOG_SOURCE_FILE:
                if not log_file_path:
                    raise RuntimeError("Log file source requires log_file_path.")
                logs = await self.hass.async_add_executor_job(
                    lambda: Path(log_file_path).read_text(encoding="utf-8", errors="replace")
                )
            else:
                raise RuntimeError(f"Unsupported log source: {log_source}")
        except (OSError, RuntimeError) as exc:
            self.last_error = str(exc)
            await self.async_save()
            raise UpdateFailed(self.last_error) from exc

        initial_chars = max(MIN_LOG_CHARS, max_chars)
        retry_sizes = [initial_chars, 3000, 1800, 1000, 600, 400, MIN_LOG_CHARS]
        seen_sizes: set[int] = set()
        issues: list[dict[str, str]] | None = None
        last_exc: Exception | None = None

        for size in retry_sizes:
            if size in seen_sizes:
                continue
            seen_sizes.add(size)
            clipped_logs = _clip_for_conversation(logs, size)
            prompt = f"{PROMPT}\n\nHome Assistant logs:\n\n{clipped_logs}"
            try:
                result = await self.hass.services.async_call(
                    "conversation",
                    "process",
                    {"agent_id": agent_id, "text": prompt},
                    blocking=True,
                    return_response=True,
                )
                response_text = (
                    result.get("response", {})
                    .get("speech", {})
                    .get("plain", {})
                    .get("speech", "")
                )
                if not response_text:
                    response_text = (
                        result.get("response", {})
                        .get("speech", {})
                        .get("speech", "")
                    )
                if not response_text:
                    raise RuntimeError("Conversation agent returned an empty response.")
                issues = normalize_issues_from_text(response_text)
                break
            except Exception as exc:
                last_exc = exc
                if _is_text_too_long_error(exc):
                    continue
                self.last_error = str(exc)
                await self.async_save()
                raise UpdateFailed(self.last_error) from exc

        if issues is None:
            if last_exc is None:
                last_exc = RuntimeError("Conversation analysis failed with unknown error.")
            self.last_error = str(last_exc)
            await self.async_save()
            raise UpdateFailed(self.last_error) from last_exc

        now = _now_iso()
        created = 0
        updated = 0
        for issue in issues:
            fp = _fingerprint(issue)
            existing = self.issues.get(fp)
            if existing:
                existing["title"] = issue["title"]
                existing["severity"] = issue["severity"]
                existing["description"] = issue["description"]
                existing["suggested_fix"] = issue["suggested_fix"]
                existing["signature_hint"] = issue["signature_hint"]
                existing["last_seen"] = now
                existing["occurrences"] = int(existing.get("occurrences", 0)) + 1
                existing["status"] = "open"
                updated += 1
            else:
                self.issues[fp] = {
                    "fingerprint": fp,
                    "title": issue["title"],
                    "severity": issue["severity"],
                    "description": issue["description"],
                    "suggested_fix": issue["suggested_fix"],
                    "signature_hint": issue["signature_hint"],
                    "status": "open",
                    "first_seen": now,
                    "last_seen": now,
                    "occurrences": 1,
                }
                created += 1

        self.last_run = now
        self.last_error = None
        await self.async_save()

        open_count = sum(1 for issue in self.issues.values() if issue.get("status") == "open")
        return {
            "open_count": open_count,
            "created": created,
            "updated": updated,
            "last_run": self.last_run,
            "last_error": self.last_error,
            "issues": deepcopy(self.issues),
        }

    async def async_set_issue_status(self, fingerprint: str, status: str) -> bool:
        issue = self.issues.get(fingerprint)
        if not issue:
            return False
        issue["status"] = status
        await self.async_save()
        self.async_set_updated_data(
            {
                **(self.data or {}),
                "open_count": sum(
                    1 for row in self.issues.values() if row.get("status", "open") == "open"
                ),
                "issues": deepcopy(self.issues),
            }
        )
        return True
