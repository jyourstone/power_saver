"""Constants for the Power Saver integration."""

DOMAIN = "power_saver"

# Config entry data keys (immutable after creation)
CONF_NORDPOOL_SENSOR = "nordpool_sensor"
CONF_NORDPOOL_TYPE = "nordpool_type"
CONF_NAME = "name"

# Nordpool sensor types
NORDPOOL_TYPE_HACS = "hacs"
NORDPOOL_TYPE_NATIVE = "native"

# Options keys (changeable via options flow)
CONF_MIN_HOURS = "min_hours"
CONF_ALWAYS_CHEAP = "always_cheap_price"
CONF_ALWAYS_EXPENSIVE = "always_expensive_price"
CONF_ROLLING_WINDOW_HOURS = "rolling_window_hours"
CONF_PRICE_SIMILARITY_PCT = "price_similarity_pct"
CONF_CONTROLLED_ENTITIES = "controlled_entities"

# Defaults
DEFAULT_MIN_HOURS = 2.5
DEFAULT_ALWAYS_CHEAP = 0.0
DEFAULT_ALWAYS_EXPENSIVE = 0.0  # 0 = disabled
DEFAULT_ROLLING_WINDOW_HOURS = 24.0
DEFAULT_PRICE_SIMILARITY_PCT = 0.0  # 0 = disabled

# Update interval in minutes
UPDATE_INTERVAL_MINUTES = 15

# Sensor states
STATE_ACTIVE = "active"
STATE_STANDBY = "standby"
