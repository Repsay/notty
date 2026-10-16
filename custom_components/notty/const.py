from homeassistant.const import CONF_ACCESS_TOKEN, CONF_PASSWORD

__all__ = ["CONF_ACCESS_TOKEN", "CONF_PASSWORD"]

# This is a configuration field name, never a credential value.
CONF_REFRESH_TOKEN = "refresh_token"  # ruff: ignore[hardcoded-password-string]

DOMAIN = "notty"
CONFIG_ENTRY_VERSION = 3
CONF_EMAIL = "email"
CONF_VERIFICATION_CODE = "verification_code"
CONF_USER_ID = "user_id"
CONF_FIREBASE_API_KEY = "firebase_api_key"
CONF_REGION_CODE = "region_code"
DEFAULT_REGION_CODE = "NL"
DEFAULT_SCAN_INTERVAL = 60
PLATFORMS = ["sensor", "binary_sensor", "button", "switch", "select", "time", "number", "update"]
