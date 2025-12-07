# Changelog

## v2.2.2

- **Improvement:** Smarter Setpoint Logic: Ignores thermostat values below `comfort_min_temp` (default 19°C) and uses `comfort_fallback` or learned values instead. Fixes "cold start" issues where Eco mode was mistaken for the target.


## v2.2.1

- **Fix:** HACS validation compliance (moved strings, added recorder dependency).
- **Fix:** Corrected internal version constant.
- **Meta:** Added LICENSE file.


## v2.2.0 (2025-12-07)

### 🛡️ Robustness & Diagnostics (Phase 1)
*   **Window Open Detection**: Automatically pauses learning and preheating if temperature drops rapidly (>0.4K in 5 min) to prevent data corruption.
*   **System Health**: Full Home Assistant **Diagnostics** integration. download internal state, physics parameters, and schedule summaries for support.
*   **Model Health Score**: New internal metric (0-100%) checking for model stability and parameter drift.

### 🧹 Polish & Quality
*   **Persistence**: `avg_error` metric is now persisted across restarts, ensuring stable health scoring.
*   **Code Quality**: Major refactoring to use strict constants (no magic strings), clean imports, and improved type safety.
*   **Stability**: Fixed incorrect `outdoor_temp` access in diagnostics and potential runtime errors.

### ⚠️ Breaking Changes / Notes
*   **Occupancy Logic**: Clarified that "Occupancy" (ON) means *User Present* -> *Stop Preheating*. Do not use a Scheduler as an Occupancy sensor.

## v2.1.0-beta (2025-12-06)

### ✨ New Features

*   **Confidence Sensor**: Added `sensor.{zone}_confidence` (0-100%) to indicate learning progress.
*   **Error Tracking**: Added `avg_error` attribute to status sensor to show model precision (in minutes).
*   **Smart Valve Logic**: Improved learning algorithm to accept low valve positions (e.g. 5%) if temperature delta is small (maintenance heating), improving support for underfloor heating.
*   **Input Validation**: Added safety checks for `buffer_minutes` (max 60) and `max_preheat_hours` (max 5) in configuration.
*   **Migration Warning**: Added a Repair Issue notification when migrating legacy v1 data to warn about potential data quality changes.

### 🐛 Bug Fixes

*   Restored accidentally removed `calculate_duration` method in physics engine.
*   Fixed duplicated logic in `update_model`.
*   Removed unused sensor states ("heating", "learning") from status sensor options.
*   Removed unused configuration strings.

### ⚙️ Under the Hood

*   Refactored `test_physics.py` to cover new confidence and smart valve logic.
*   Added `sample_count` and `confidence` to sensor attributes.
