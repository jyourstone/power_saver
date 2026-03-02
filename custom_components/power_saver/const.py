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
CONF_STRATEGY = "strategy"
CONF_HOURS_PER_PERIOD = "hours_per_period"
CONF_MIN_HOURS_ON = "min_hours_on"
CONF_ALWAYS_CHEAP = "always_cheap_price"
CONF_ALWAYS_EXPENSIVE = "always_expensive_price"
CONF_PRICE_SIMILARITY_PCT = "price_similarity_pct"
CONF_MIN_CONSECUTIVE_HOURS = "min_consecutive_hours"
CONF_CONTROLLED_ENTITIES = "controlled_entities"
CONF_SELECTION_MODE = "selection_mode"
CONF_EXCLUDE_FROM = "exclude_from"
CONF_EXCLUDE_UNTIL = "exclude_until"

# Lowest Price strategy options
CONF_PERIOD_FROM = "period_from"
CONF_PERIOD_TO = "period_to"

# Minimum Runtime strategy options
CONF_ROLLING_WINDOW = "rolling_window"

# Strategy values
STRATEGY_LOWEST_PRICE = "lowest_price"
STRATEGY_MINIMUM_RUNTIME = "minimum_runtime"

# Selection mode values
SELECTION_MODE_CHEAPEST = "cheapest"
SELECTION_MODE_MOST_EXPENSIVE = "most_expensive"

# Defaults
DEFAULT_STRATEGY = STRATEGY_LOWEST_PRICE
DEFAULT_HOURS_PER_PERIOD = 2.5
DEFAULT_MIN_HOURS_ON = 4.0
DEFAULT_ALWAYS_CHEAP = None  # None = disabled (field left empty)
DEFAULT_ALWAYS_EXPENSIVE = None  # None = disabled (field left empty)
DEFAULT_PRICE_SIMILARITY_PCT = None  # None = disabled (field left empty)
DEFAULT_MIN_CONSECUTIVE_HOURS = None  # None = disabled (field left empty)
DEFAULT_SELECTION_MODE = SELECTION_MODE_CHEAPEST
DEFAULT_PERIOD_FROM = "00:00"
DEFAULT_PERIOD_TO = "00:00"
DEFAULT_ROLLING_WINDOW = 28.0

# Update interval in minutes
UPDATE_INTERVAL_MINUTES = 15

# Sensor states
STATE_ACTIVE = "active"
STATE_STANDBY = "standby"
STATE_EXCLUDED = "excluded"
STATE_FORCED_ON = "forced_on"
STATE_FORCED_OFF = "forced_off"
