"""Konstanten der HM-REST-Integration."""

DOMAIN = "hmrest"
ENTITY_PREFIX = "homematic"

CONF_API_KEY = "api_key"
CONF_SSL = "ssl"
CONF_VIRTUAL_REMOTES = "include_virtual_remotes"
CONF_SCAN_MINUTES = "device_scan_minutes"
CONF_SYSVARS = "include_sysvars"
CONF_SYSVAR_SECONDS = "sysvar_poll_seconds"

DEFAULT_PORT = 8099
DEFAULT_SCAN_MINUTES = 10
DEFAULT_SYSVAR_SECONDS = 30

PLATFORMS = [
    "binary_sensor",
    "button",
    "climate",
    "cover",
    "event",
    "light",
    "number",
    "select",
    "sensor",
    "switch",
    "text",
]

# Virtuelle Fernbedienungen der CCU (viele Tasten-Kanäle, meist nicht gewünscht)
VIRTUAL_REMOTE_TYPES = {"HM-RCV-50", "HMW-RCV-50", "HmIP-RCV-50", "HmIP-RCV-1"}

KEYPRESS_EVENT = "homematic_keypress"
