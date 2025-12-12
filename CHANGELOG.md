

## v2.5.0-beta8 (2025-12-12)
*   **Hotfix**: Fixed `NameError: force_off_holiday` crash introduced in beta7. Reworked filter logic to be implicitly handled by the Planner.

## v2.5.0-beta7 (2025-12-12)
*   **Fix**: Correctly calculate "Next Event" for future days when "Only on workdays" is enabled. Attempts to find the next valid workday instead of showing weekends or phantom events.
*   **Robustness**: Now respects the specific `workdays` configuration of the Binary Workday Sensor (e.g. if Saturday is configured as a workday).

## v2.5.0-beta5 (2025-12-11)
*   **Polish**: Standardized `tau_confidence` formatting to percentage across all sensors.

## v2.5.0-beta4 (2025-12-11)
*   **Localization**: Added missing German translations for Optimal Stop configuration and sensors.

## v2.5.0-beta3 (2025-12-11)
*   **Hotfix**: Fixed `AttributeError: session_resolver` crash on startup/update.

## v2.5.0-beta2 (2025-12-11)
*   **Bugfix**: Fixed learning events being discarded if valve position drops to 0% at the exact moment of target achievement. Now uses **average** valve position over the heating duration.

## v2.5.0-beta1 (2025-12-10)

### 📉 Optimal Stop (Coast-to-Vacancy)
*   **Intelligent Shutdown**: The system can now turn off heating *before* a scheduled vacancy (e.g., leaving for work), letting the room "coast" to a stop while staying within a comfortable temperature tolerance.
*   **Cooling Analyzer**: A new self-learning component that observes how your building cools down (`tau`) to predict exactly when to stop heating.
*   **Inverted Physics**: Solves the cooling equation in reverse to maximize energy savings without engaging the "Anti-Freeze" safety too early.

### ✨ New Entities
*   `sensor.preheat_optimal_stop_time`: Displays the calculated time when heating will stop.
*   `binary_sensor.preheat_optimal_stop_active`: Indicates when the system is effectively "Coasting" (Heating OFF due to Optimal Stop).

### ⚙️ Configuration
*   **Expert Mode**: New options to enable Optimal Stop, select a Schedule Helper, and tune tolerance/max coast duration.

---

## v2.4.0 (2025-12-10)

**Initial Stable Release of Forecast Integration** 🚀

This major release transforms the preheater from a reactive to a **predictive** system. By looking ahead using `weather.get_forecasts`, it can now anticipate heat loss before it happens.

### ⛈️ Weather Forecast Integration
*   **Predictive Heating**: Duration calculation now accounts for future outdoor temperature.
*   **Risk Strategies**:
    *   **Balanced**: Accurate physics-based model.
    *   **Pessimistic (P10)**: Prioritizes comfort (assumes cold forecast).
    *   **Optimistic (P90)**: Prioritizes savings (assumes warm forecast).
*   **Smart Caching**: Efficient API usage with 30-min cache.

### 🛡️ Resilience & Engineering
*   **Deadtime V3**: New "Tangent Method" ring-buffer to detect heating lag (Totzeit).
*   **Robustness**:
    *   `CONF_ONLY_ON_WORKDAYS` option for office use-cases.
    *   **UTC Normalization** for time-zone safe calculations.
    *   **Root-Finding Solver** for non-monotonic temperature curves.
*   **Quality**: Coverage increased to 65% with new critical-path tests.

---

## v2.4.0-beta2 (2025-12-09)
*   **Fix**: Added missing import `CONF_ONLY_ON_WORKDAYS` causing Setup/Update failures.

## v2.4.0-beta1 (2025-12-09)

### ⛈️ Forecast Integration (Phase 2)
*   **Forecast-Aware Preheating**: The integration now reads future weather data via `weather.get_forecasts` to predict heat loss more accurately during the preheating window.
*   **Risk Strategies**: Choose your preferred balance between Comfort and Savings:
    *   **Balanced**: Uses Time-Weighted Integral (Trapezoidal Rule). Accurately models total thermal load.
    *   **Pessimistic (P10)**: Uses the *coldest 10%* of the forecast window. Ensures comfort even if the forecast is slightly off.
    *   **Optimistic (P90)**: Uses the *warmest 10%*. Prioritizes energy savings.
*   **Smart Caching**: Minimizes API calls by caching forecasts for 30 minutes.

### 🛠️ Improvements
*   **Robust Root Solver**: Handles non-monotonic temperature curves (e.g., warm peaks).
*   **Strict Workday Mode**: Option `CONF_ONLY_ON_WORKDAYS` to disable heating on holidays.
*   **UTC Normalization**: Prevents DST glitches.

## v2.3.0-beta1 (2025-12-08)

### 🔥 Deadtime Detection (V3)
*   **Dynamic Deadtime**: Uses a new **Ring Buffer (RAM)** and "Tangent Method" analysis to accurately detect the delay between heating start and temperature rise (Totzeit).
*   **Physics Update**: Duration calculation now accounts for Deadtime, significantly improving accuracy for **Floor Heating** and slow radiators.

### 🏗️ Heating Profiles
*   **Simplified Setup**: Removed complex technical parameters (`gain`, `buffer`, etc.) in the Zone setup.
*   **Profile Selection**: Users simply choose their system type:
    *   *Infrared / Air* (Fast)
    *   *Radiator* (Modern/Old)
    *   *Floor* (Dry/Concrete)
*   **Auto-Tuning**: Profiles provide safe defaults and constraints (Min/Max thermal mass) to prevent learning anomalies.

### ⚠️ Breaking Changes
*   **Config Flow**: The setup wizard is completely redesigned. Existing configs might show warnings or require re-configuration if expert parameters were used.
*   **Sensors**: `setpoint_sensor` entity has been removed (redundant).


## v2.2.2

- **Improvement:** Smarter Setpoint Logic: Ignores thermostat values below `comfort_min_temp` (default 19°C) and uses `comfort_fallback` or learned values instead. Fixes "cold start" issues where Eco mode was mistaken for the target.
- **Config:** Exposed `Comfort Min/Max` and `Fallback` temperatures in Expert Settings.
- **Change:** Changed default `Comfort Fallback` to 21.0°C (was 22.0°C).


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
