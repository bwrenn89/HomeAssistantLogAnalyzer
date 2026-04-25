"""Constants for the HA Log Analyzer integration."""

from homeassistant.const import Platform

DOMAIN = "ha_log_analyzer"
PLATFORMS = [Platform.SENSOR]

CONF_CONVERSATION_AGENT_ID = "conversation_agent_id"
CONF_LOG_SOURCE = "log_source"
CONF_LOG_FILE_PATH = "log_file_path"
CONF_HOME_ASSISTANT_URL = "home_assistant_url"
CONF_HOME_ASSISTANT_TOKEN = "home_assistant_token"
CONF_POLL_INTERVAL_MINUTES = "poll_interval_minutes"
CONF_MAX_LOG_CHARS = "max_log_chars"

LOG_SOURCE_API = "ha_api"
LOG_SOURCE_FILE = "file"
DEFAULT_LOG_SOURCE = LOG_SOURCE_API
DEFAULT_LOG_FILE_PATH = "/config/home-assistant.log"
DEFAULT_HOME_ASSISTANT_URL = "http://homeassistant.local:8123"
DEFAULT_POLL_INTERVAL_MINUTES = 15
DEFAULT_MAX_LOG_CHARS = 120000

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_issues"

SERVICE_RUN_ANALYSIS = "run_analysis"
SERVICE_RESOLVE_ISSUE = "resolve_issue"
SERVICE_REOPEN_ISSUE = "reopen_issue"
