"""Constants for HANSA Connect BLE."""

from datetime import timedelta

DOMAIN = "hansa_ble"
MANUFACTURER = "HANSA"

CONF_TYPE_CODE = "type_code"

UPDATE_INTERVAL = timedelta(minutes=15)
DEFAULT_FLUSH_SECONDS = 30
MAX_FLUSH_SECONDS = 600

SERVICE_FLUSH = "flush"
ATTR_DURATION = "duration"

BLUETOOTH_MODES = {0: "always_on", 1: "after_usage", 2: "after_boot", 3: "ir_off"}
APP_CONTROL_MODES = {0: "all_allowed", 1: "open_disabled", 2: "all_disabled"}
