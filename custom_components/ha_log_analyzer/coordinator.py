"""Data update coordinator and issue registry."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_CONVERSATION_AGENT_ID,
    CONF_LOG_FILE_PATH,
    CONF_MAX_LOG_CHARS,
    CONF_POLL_INTERVAL_MINUTES,
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .gemini import PROMPT, normalize_issues_from_text


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(issue: dict[str, str]) -> str:
    source = (
        f"{issue.get('title', '').strip().lower()}|"
        f"{issue.get('signature_hint', '').strip().lower()}|"
        f"{issue.get('description', '').strip().lower()[:180]}"
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


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
        log_file_path = str(cfg.get(CONF_LOG_FILE_PATH, "")).strip()
        max_chars = int(cfg.get(CONF_MAX_LOG_CHARS, 120000))

        if not agent_id:
            raise UpdateFailed("Conversation agent ID is missing.")
        if not log_file_path:
            raise UpdateFailed("Log file path is missing.")

        try:
            logs = await self.hass.async_add_executor_job(
                lambda: Path(log_file_path).read_text(encoding="utf-8", errors="replace")
            )
        except OSError as exc:
            self.last_error = f"Failed to read log file: {exc}"
            await self.async_save()
            raise UpdateFailed(self.last_error) from exc

        logs = logs[-max_chars:]
        prompt = f"{PROMPT}\n\nHome Assistant logs:\n\n{logs}"

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
        except Exception as exc:
            self.last_error = str(exc)
            await self.async_save()
            raise UpdateFailed(self.last_error) from exc

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
