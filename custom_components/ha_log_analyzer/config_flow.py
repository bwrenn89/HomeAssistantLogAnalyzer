"""Config flow for HA Log Analyzer."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import conversation
from homeassistant.core import callback

from .const import (
    CONF_CONVERSATION_AGENT_ID,
    CONF_LOG_FILE_PATH,
    CONF_LOG_SOURCE,
    CONF_HOME_ASSISTANT_TOKEN,
    CONF_HOME_ASSISTANT_URL,
    CONF_MAX_LOG_CHARS,
    CONF_POLL_INTERVAL_MINUTES,
    DEFAULT_HOME_ASSISTANT_URL,
    DEFAULT_LOG_FILE_PATH,
    DEFAULT_LOG_SOURCE,
    DEFAULT_MAX_LOG_CHARS,
    DEFAULT_POLL_INTERVAL_MINUTES,
    DOMAIN,
    LOG_SOURCE_API,
    LOG_SOURCE_FILE,
)


def _schema_with_defaults(
    user_input: dict[str, Any] | None = None,
    *,
    default_agent_id: str = "",
) -> vol.Schema:
    data = user_input or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_CONVERSATION_AGENT_ID,
                default=data.get(CONF_CONVERSATION_AGENT_ID, default_agent_id),
            ): str,
            vol.Required(
                CONF_LOG_SOURCE, default=data.get(CONF_LOG_SOURCE, DEFAULT_LOG_SOURCE)
            ): vol.In([LOG_SOURCE_API, LOG_SOURCE_FILE]),
            vol.Required(
                CONF_LOG_FILE_PATH, default=data.get(CONF_LOG_FILE_PATH, DEFAULT_LOG_FILE_PATH)
            ): str,
            vol.Required(
                CONF_HOME_ASSISTANT_URL,
                default=data.get(CONF_HOME_ASSISTANT_URL, DEFAULT_HOME_ASSISTANT_URL),
            ): str,
            vol.Required(
                CONF_HOME_ASSISTANT_TOKEN, default=data.get(CONF_HOME_ASSISTANT_TOKEN, "")
            ): str,
            vol.Required(
                CONF_POLL_INTERVAL_MINUTES,
                default=data.get(CONF_POLL_INTERVAL_MINUTES, DEFAULT_POLL_INTERVAL_MINUTES),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
            vol.Required(
                CONF_MAX_LOG_CHARS, default=data.get(CONF_MAX_LOG_CHARS, DEFAULT_MAX_LOG_CHARS)
            ): vol.All(vol.Coerce(int), vol.Range(min=5000, max=1000000)),
        }
    )


class HALogAnalyzerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for HA Log Analyzer."""

    VERSION = 1

    @staticmethod
    def _discover_agent_ids(hass) -> list[str]:
        ids: list[str] = []
        try:
            manager = conversation.get_agent_manager(hass)
            for info in manager.async_get_agent_info():
                ids.append(info.id)
        except Exception:
            return []
        return sorted(set(ids))

    @staticmethod
    def _pick_default_agent(agent_ids: list[str], current: str = "") -> str:
        if current:
            return current
        if not agent_ids:
            return ""
        for agent_id in agent_ids:
            if "gemini" in agent_id.lower():
                return agent_id
        return agent_ids[0]

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        agent_ids = self._discover_agent_ids(self.hass)
        if user_input is not None:
            agent_id = str(user_input.get(CONF_CONVERSATION_AGENT_ID, "")).strip()
            source = str(user_input.get(CONF_LOG_SOURCE, DEFAULT_LOG_SOURCE)).strip()
            log_file_path = str(user_input.get(CONF_LOG_FILE_PATH, "")).strip()
            ha_url = str(user_input.get(CONF_HOME_ASSISTANT_URL, "")).strip()
            ha_token = str(user_input.get(CONF_HOME_ASSISTANT_TOKEN, "")).strip()
            if agent_ids and agent_id not in agent_ids:
                errors["base"] = "unknown_agent"
            if source == LOG_SOURCE_FILE and not log_file_path:
                errors["base"] = "cannot_read_log"
            if source == LOG_SOURCE_API and (not ha_url or not ha_token):
                errors["base"] = "missing_api_config"
            elif not errors:
                return self.async_create_entry(title="HA Log Analyzer", data=user_input)

        available_agents = ", ".join(agent_ids) if agent_ids else "none discovered"
        default_agent = self._pick_default_agent(
            agent_ids, (user_input or {}).get(CONF_CONVERSATION_AGENT_ID, "")
        )
        return self.async_show_form(
            step_id="user",
            data_schema=_schema_with_defaults(user_input, default_agent_id=default_agent),
            errors=errors,
            description_placeholders={"available_agents": available_agents},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return HALogAnalyzerOptionsFlow(config_entry)


class HALogAnalyzerOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        agent_ids = HALogAnalyzerConfigFlow._discover_agent_ids(self.hass)
        if user_input is not None:
            agent_id = str(user_input.get(CONF_CONVERSATION_AGENT_ID, "")).strip()
            if agent_ids and agent_id not in agent_ids:
                return self.async_show_form(
                    step_id="init",
                    data_schema=_schema_with_defaults(
                        user_input,
                        default_agent_id=HALogAnalyzerConfigFlow._pick_default_agent(agent_ids),
                    ),
                    errors={"base": "unknown_agent"},
                    description_placeholders={
                        "available_agents": ", ".join(agent_ids) if agent_ids else "none discovered"
                    },
                )
            return self.async_create_entry(title="", data=user_input)

        current = {
            CONF_CONVERSATION_AGENT_ID: self.config_entry.options.get(
                CONF_CONVERSATION_AGENT_ID,
                self.config_entry.data.get(CONF_CONVERSATION_AGENT_ID, ""),
            ),
            CONF_LOG_FILE_PATH: self.config_entry.options.get(
                CONF_LOG_FILE_PATH, self.config_entry.data.get(CONF_LOG_FILE_PATH, DEFAULT_LOG_FILE_PATH)
            ),
            CONF_LOG_SOURCE: self.config_entry.options.get(
                CONF_LOG_SOURCE, self.config_entry.data.get(CONF_LOG_SOURCE, DEFAULT_LOG_SOURCE)
            ),
            CONF_HOME_ASSISTANT_URL: self.config_entry.options.get(
                CONF_HOME_ASSISTANT_URL,
                self.config_entry.data.get(CONF_HOME_ASSISTANT_URL, DEFAULT_HOME_ASSISTANT_URL),
            ),
            CONF_HOME_ASSISTANT_TOKEN: self.config_entry.options.get(
                CONF_HOME_ASSISTANT_TOKEN, self.config_entry.data.get(CONF_HOME_ASSISTANT_TOKEN, "")
            ),
            CONF_POLL_INTERVAL_MINUTES: self.config_entry.options.get(
                CONF_POLL_INTERVAL_MINUTES,
                self.config_entry.data.get(CONF_POLL_INTERVAL_MINUTES, DEFAULT_POLL_INTERVAL_MINUTES),
            ),
            CONF_MAX_LOG_CHARS: self.config_entry.options.get(
                CONF_MAX_LOG_CHARS, self.config_entry.data.get(CONF_MAX_LOG_CHARS, DEFAULT_MAX_LOG_CHARS)
            ),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=_schema_with_defaults(
                current,
                default_agent_id=HALogAnalyzerConfigFlow._pick_default_agent(
                    agent_ids, current.get(CONF_CONVERSATION_AGENT_ID, "")
                ),
            ),
            description_placeholders={
                "available_agents": ", ".join(agent_ids) if agent_ids else "none discovered"
            },
        )
