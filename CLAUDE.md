# CLAUDE.md — Power Saver Integration

Home Assistant custom integration that schedules appliances during cheapest (or most expensive) electricity hours using Nordpool prices.

## Post-Change Checklist

- **Always review [README.md](README.md) after any changes** to see if it needs updating to reflect the changes made (new features, config options, sensors, behavior changes, etc.)
- Update [strings.json](custom_components/power_saver/strings.json) AND [translations/en.json](custom_components/power_saver/translations/en.json) when adding/changing UI text or entities
- Update [translations/sv.json](custom_components/power_saver/translations/sv.json) for Swedish translations

## Commands

```bash
# Install test dependencies
pip install -r dev/requirements_test.txt

# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_scheduler.py

# Run with verbose output
pytest -v tests/

# Run with coverage
pytest --cov=custom_components tests/

# Local HA dev environment
docker-compose -f dev/docker-compose.yaml up
```

## Architecture

```
custom_components/power_saver/
├── __init__.py           # Entry point, platform setup
├── manifest.json         # HA integration metadata (version: 1.1.0)
├── const.py              # Constants and config keys
├── config_flow.py        # UI configuration + options flow
├── coordinator.py        # DataUpdateCoordinator, fetches prices, runs scheduler
├── scheduler.py          # Pure scheduling algorithm (no HA deps, independently testable)
├── nordpool_adapter.py   # Abstracts HACS vs native Nordpool
├── sensor.py             # Status + diagnostic sensors
├── binary_sensor.py      # Emergency mode binary sensor
├── strings.json          # English source strings (blueprint only)
└── translations/
    ├── en.json           # English runtime translations (REQUIRED)
    └── sv.json           # Swedish translations
```

### Key Components

- **scheduler.py** — Pure functions, no HA imports. Core algorithm: sort by price, activate cheapest N slots, apply thresholds/constraints. Testable in isolation.
- **coordinator.py** — `PowerSaverCoordinator` extends `DataUpdateCoordinator`. Fetches Nordpool data every 15 min, runs scheduler, controls target entities on state changes.
- **nordpool_adapter.py** — Auto-detects HACS (`raw_today` attribute) vs native HA Nordpool. Normalizes both to `[{start, end, value}]` format.
- **config_flow.py** — Single-step user flow + options flow. Auto-detects Nordpool sensor. Unique ID: `{nordpool_entity}_{slugified_name}`.

### Data Flow

1. Coordinator fetches prices from Nordpool (via adapter)
2. `scheduler.build_schedule()` computes slot activation
3. `scheduler.find_current_slot()` determines current state
4. Coordinator controls target entities (switch/input_boolean/light)
5. Sensors read from `coordinator.data` (a `PowerSaverData` dataclass)

## Code Style & Patterns

- **Async/await** throughout — all HA operations are async
- **Type hints** with `from __future__ import annotations`
- **Logging** — module-level `_LOGGER = logging.getLogger(__name__)`
- **CoordinatorEntity pattern** — all entities inherit from `CoordinatorEntity[PowerSaverCoordinator]`
- **Entity naming** — `_attr_has_entity_name = True` + `_attr_translation_key` (no hardcoded names)
- **Device grouping** — entities grouped under a logical device via `DeviceInfo`
- **Optional config fields** — `None` means disabled, handled with `vol.Optional`
- **Error handling** — defensive parsing with try/except and `_LOGGER.warning()`

## Testing

- **pytest** with `asyncio_mode = auto` (see [pytest.ini](pytest.ini))
- **pytest-homeassistant-custom-component** provides HA test fixtures
- [test_scheduler.py](tests/test_scheduler.py) — ~200 tests for pure scheduling logic (most comprehensive)
- [test_config_flow.py](tests/test_config_flow.py) — config/options flow tests
- [test_nordpool_adapter.py](tests/test_nordpool_adapter.py) — adapter tests
- [test_coordinator.py](tests/test_coordinator.py) and [test_sensor.py](tests/test_sensor.py) — stubs/partial
- Fixtures in [conftest.py](tests/conftest.py): `today_prices()`, `tomorrow_prices()`, `make_nordpool_slot()`

## Translations Gotcha

`strings.json` is **never read at runtime** by custom components. It's a source/blueprint file only. Custom components **must** have `translations/en.json` manually created — without it, `translation_key` lookups return `None`. Always update both files in sync.

## CI/CD

- **[validate.yaml](.github/workflows/validate.yaml)** — HACS + Hassfest validation on push to main, PRs, and daily
- **[release.yaml](.github/workflows/release.yaml)** — Triggered by semver tags (e.g., `1.1.0`). Auto-updates manifest version, creates GitHub release with zip, pushes version bump to main

### Release Process

1. Tag the commit: `git tag 1.1.0 && git push origin 1.1.0`
2. GitHub Actions handles the rest (manifest update, zip, release notes)

## Config Keys (const.py)

**Immutable (ConfigEntry.data):** `CONF_NORDPOOL_SENSOR`, `CONF_NORDPOOL_TYPE`, `CONF_NAME`

**Mutable (ConfigEntry.options):** `CONF_SELECTION_MODE`, `CONF_MIN_HOURS`, `CONF_ROLLING_WINDOW_HOURS`, `CONF_ALWAYS_CHEAP`, `CONF_ALWAYS_EXPENSIVE`, `CONF_PRICE_SIMILARITY_PCT`, `CONF_MIN_CONSECUTIVE_HOURS`, `CONF_CONTROLLED_ENTITIES`

## Common Tasks

### Adding a New Sensor
1. Create sensor class in `sensor.py` extending `CoordinatorEntity` + `SensorEntity`
2. Set `_attr_translation_key` and `_attr_unique_id`
3. Add entries to `strings.json`, `translations/en.json`, and `translations/sv.json`
4. Register in `async_setup_entry()`
5. Add tests
6. **Update README.md** if user-facing

### Adding a New Config Option
1. Add constant to `const.py`
2. Update schema in `config_flow.py` (`_options_schema()`)
3. Update `strings.json` + both translation files
4. Update `coordinator.py` to read and use the option
5. Add tests to `test_config_flow.py`
6. **Update README.md** configuration table
