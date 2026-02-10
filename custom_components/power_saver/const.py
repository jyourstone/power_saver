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
CONF_MIN_CONSECUTIVE_HOURS = "min_consecutive_hours"
CONF_CONTROLLED_ENTITIES = "controlled_entities"
CONF_SELECTION_MODE = "selection_mode"

# Selection mode values
SELECTION_MODE_CHEAPEST = "cheapest"
SELECTION_MODE_MOST_EXPENSIVE = "most_expensive"

# Defaults
DEFAULT_MIN_HOURS = 2.5
DEFAULT_ALWAYS_CHEAP = None  # None = disabled (field left empty)
DEFAULT_ALWAYS_EXPENSIVE = None  # None = disabled (field left empty)
DEFAULT_ROLLING_WINDOW_HOURS = 24.0
DEFAULT_PRICE_SIMILARITY_PCT = None  # None = disabled (field left empty)
DEFAULT_MIN_CONSECUTIVE_HOURS = None  # None = disabled (field left empty)
DEFAULT_SELECTION_MODE = SELECTION_MODE_CHEAPEST

# Update interval in minutes
UPDATE_INTERVAL_MINUTES = 15

# Sensor states
STATE_ACTIVE = "active"
STATE_STANDBY = "standby"
STATE_OVERRIDE = "override"
