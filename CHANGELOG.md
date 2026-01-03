# Changelog

## v2.9.0-beta2 (2026-01-03) - Schedule-Free Optimal Stop 🏃
**Feature Update: Flexible Optimal Stop**

This release removes the strict requirement for a Schedule Entity to use "Optimal Stop" (Coasting).

### 🆕 Schedule-Free Operation
You can now enable Optimal Stop (Coasting) without configuring a Home Assistant Schedule Helper!
*   **Observer Fallback**: If no schedule is provided, the system uses the new "Departure Prediction" AI (from v2.8) to determine when you likely leave.
*   **Input Datetime**: The `schedule_entity` field now accepts `input_datetime` (timestamp) entities if you want to set a manual one-off departure time.
*   **Migration**: The "Missing Schedule" warning has been removed for users who want to rely on the AI or manual events.

---

## v2.9.0-beta1 (2026-01-03) - Heat Demand & UX Polish 🛠️
**Feature Update: Heat Demand Sensor & External Control**

This release introduces a powerful new signal for central heating control and significantly improves the "Lock Switch" user experience.

### 🔥 New: Heat Demand Sensor
A dedicated binary sensor (`binary_sensor.<zone>_heat_demand`) that tells you exactly when a zone needs active heat supply.
*   **Logic**: 3-Stage Smart Check (HVAC Action -> Valve Position -> Delta T).
*   **Hysteresis**: Prevents short-cycling with min. 5 min ON / 3 min OFF timers.
*   **Thresholds**: ON if Valve > 15% or Target - Temp > 0.4°C.
*   **Safety**: Automatically OFF if Window Open, Optimal Stop Active, or Externally Blocked.
*   *Note: Opt-In (Disabled by default). Enable via entity settings.*

### ✨ UX Improvements
*   **Refined "Lock Switch"**: Renamed to "External Inhibit / Window Sensor" and moved to the main configuration page.
*   **Expanded Compatibility**: The External Inhibit selector now accepts `binary_sensor` and `switch` entities, supporting direct integration of window contacts.
*   **Traceability**: "External Inhibit" is now a distinct blocking reason in the decision trace, separate from manual "Hold".

---

## v2.8.0 (2025-01-02) - The Autonomous Brain 🧠
**Major Release: Self-Learning Departure & Calendar Intelligence**

This milestone transforms the integration from a reactive pre-heating system into a proactive, intelligent climate manager. It now verifies your presence patterns and predicts future departures.

### 🌟 New Features
*   **The Observer (Departure Prediction)**:
    *   The system learns your departure habits (Quantile Statistics P90) to predict when you will likely leave.
    *   **Data Collection**: Currently runs in "Shadow Mode" (Observing only), visible in the `decision_trace` attribute.
*   **Calendar Intelligence**:
    *   **Auto-Discovery**: Automatically finds your `binary_sensor.workday_sensor`.
    *   **Holiday Lookahead**: Can skip preheating on specific holidays defined in a Calendar entity (e.g. `calendar.holidays`).
*   **Advanced Physics Mode**:
    *   New **Expert Option**: Choose between 'Standard' (Reliable) and 'Advanced' (Euler Simulation) physics engines.
    *   **Advanced Mode** uses dynamic weather forecasts for ultra-precise cooling prediction (Optimal Stop).
    
### 🔌 Automation Interface (Entity Spec v2.9)
*   **First-Class Sensors**: Key values are now exposed as dedicated sensors for easier automations (no more template parsing!).
    *   `sensor.<zone>_next_start_time`: When heating will begin.
    *   `sensor.<zone>_predicted_duration`: How long it will take.
    *   `sensor.<zone>_target_temperature`: The effective setpoint.
    *   `sensor.<zone>_next_session_end`: When the heating session ends.
*   **Logic Triggers**:
    *   `binary_sensor.<zone>_preheat_needed`: **Primary Trigger** -> Turns ON when `Now >= Next Start Time` (irrespective of blocks). Use this to start your boiler/thermostat.
    *   `binary_sensor.<zone>_preheat_blocked`: Turns ON if heating is prevented by Hold, Window, or Holidays.
    *   `binary_sensor.<zone>_preheat_active`: Rehabilitated as a core "Running" status entity.
*   **Controls**:
    *   `switch.<zone>_enabled`: Master switch to completely disable the integration's logic.
    *   **Buttons & Services**: Dedicated `recompute` and `reset_model` buttons and services for easier management.

### 🛡️ Resilience & Safety
*   **Occupancy Debouncer**: Filters short absences (e.g. taking out trash) to ensure only true departures are recorded.
*   **Smart Rollover**: Intelligent handling of overnight sessions and late-night predictions (stops "Next Departure" from skipping to tomorrow prematurely).
*   **Save Throttling**: Protects SD cards by coalescing database writes (10s delay).
*   **Robustness**: Extensive guards against invalid detector states and timezone edge cases.
*   **UX Cleanliness**: Less clutter by default. Advanced entities (Manual Override, Buttons, Physics Internal) are now hidden by default.
*   **Dynamic UX**: `binary_sensor.optimal_stop_active` is now **automatically enabled** (even retroactively) if the feature is enabled in configuration.
*   **Cleaner IDs**: Simplified button names ("Recompute Decisions" -> "Recompute") to produce cleaner Entity IDs (`button.*_recompute`).

### 🐛 Fixes
*   **Naming 2.0 Compliance**: Full compliance with Home Assistant's Entity Naming standards. Entity IDs are generated from the System Language, while Display Names adapt to the User Language.
*   **Localization**: Fixed critical encoding issues ("Mojibake") where German umlauts were displayed incorrectly. Rebuilt translation files as ASCII-escaped JSON for universal compatibility.
*   **Startup Logic**: Fixed a bug where the "Scan History" logic was overridden by a notification reporter, preventing data collection on startup.
*   **Workday Override**: Fixed display bug where "Next Arrival" showed today's time even on holidays.
*   **Timezone Logic**: Fixed bucket selection bug where midnight in UTC caused wrong weekday stats.

---

### Beta History (v2.8.0-rc1 / beta1-4)
*   **rc2**: Final polish on Rollover Logic, DST Filtering, and Strings.
*   **rc1**: Initial Release Candidate for The Brain.
*   **beta4**: Calendar Intelligence integration.
*   **beta3**: Workday Hotfix.
*   **beta2**: Preheating Start Hotfix.
*   **beta1**: The Recorder (Session History Database).

---


## v2.8.0-beta3 (Hotfix) - 2025-01-01
**Happy New Year! - Workday Fix**

This release resolves a display issue where holidays were not correctly skipped in the "Next Arrival" prediction.

### 🐛 Fixes
*   **Holiday Lookahead**: If `only_on_workdays` is enabled and the Workday Sensor reports `off` (meaning Today is a holiday), the system now correctly starts searching for the next scheduled arrival from **tomorrow**.
    *   *Symptom*: Previously, the sensor might show today's schedule (e.g., 05:11) even on a holiday.
    *   *Fix*: Today is now explicitly skipped if it's not a workday.

## v2.8.0-beta2 (Hotfix) - 2025-12-31
**Bug Fix: Preheating Not Starting**

This release fixes a critical logic flaw where the system failed to identify a heating demand if the thermostat was in "Eco Mode" matching the configured `Minimum Comfort Temperature`.

### 🐛 Critical Fixes
*   **Target Temperature Logic**: Fixed an issue where `target_setpoint` defaulted to the current thermostat setting (e.g., 19.5°C) instead of the calculated comfort target (e.g., 21°C) when the values were close. The system now strictly enforces `Target > Min Comfort` before accepting the current thermostat setting as valid intent. This ensures preheating triggers correctly even from Eco mode.

## v2.8.0-beta1 (The Recorder) - 2025-12-31
**Initial Beta for the Autonomous Brain Update**

This version lays the foundation for fully autonomous heating by recording your actual departure habits.
**Note:** It runs in "Data Collection Mode". It records *when* you leave but does **NOT yet** change your heating schedule autonomously.

### 🌟 New Features
*   **Session State Machine**: A new "Occupancy Debouncer" (Default: 15min) intelligently filters out short absences (e.g., taking out trash) to determine true "Session Ends".
*   **Departure History**: The system now records your daily departure times into a persistent, privacy-focused history database.
*   **Expert Config**: Added `occupancy_debounce_minutes` setting (Expert Mode) to tune the sensitivity of the departure detection.

### 🔧 Technical Changes
*   **Persistence**: Implemented "Safe Container" storage (Key `888`) for departure history, ensuring forward compatibility with v3.0.
*   **Resilience**: Added "Save Throttling" (10s) to protect SD cards from frequent writes during flapping occupancy.
*   **Safety**: Fixed race conditions in the debounce logic to prevent data loss during short return intervals.

## v2.7.4 (2025-12-24) - Debugging Polish
**Transparency Update**

### 🔨 Improvements
- **Debug Visibility**: Added an explicit DEBUG log entry (`Preheat BLOCKED by Workday Sensor`) when the Workday Sensor override is active. This helps verify that the "Holiday Skipping" logic is working correctly in the logs.

## v2.7.3 (2025-12-24) - Critical Hotfix
**Bug Fix Release**

### 🐛 Fixes
- **NameError Loop**: Fixed a crash (`name 'CONF_WORKDAY_SENSOR' is not defined`) caused by an incorrect variable reference in the v2.7.2 update. The Workday logic now loads the correct configuration constant.

## v2.7.2 (2025-12-24) - Autonomous Engine Polish
**Release Candidate for Autonomous Features (v3)**

This release finalizes the "Departure Logic" and "Optimal Stop" integration, ensuring robust behavior in all edge cases.

### 🐛 Critical Fixes
- **Workday Sensor Loophole**: Fixed a bug where preheating could start on holidays/weekends even if `Only on workdays` was enabled. The system now strictly checks the sensor state before actuating.
- **Manual Hold Override**: Activating the `Preheat Hold` switch now immediately disables the "Optimal Stop" feature, resetting any "coasting" state. This ensures manual control always takes precedence.

### 🔨 Improvements
- **Effective Departure Trace**: The `decision_trace` now explicitly shows the "Effective Departure" time and its source (`Schedule` vs `AI`), making it easy to see who is in control.
- **Timeline Logic**: "Optimal Stop" and "Next Departure" calculations are now strictly tied to the *effective* session, preventing ghost events when the schedule is off.
- **Lovelace Debug Card**: Updated the "Autonomous Engine Cockpit" template with improved visualization and ISO-standard timestamps.

## v2.7.1 (2025-12-23) - Physics Hotfix
**Critical Release targeting Model Stability**

### 🐛 Fixes
- **Physics Core**: Removed incorrect scaling factor (`loss_scaler`) that effectively penalized the heat loss model based on internal temperature lift. The model now strictly follows linear superposition (Duration = Deadtime + Mass*dIn + Loss*dOut).
- **Learning Stability**: Implemented "Dual Gradient Clipping". Parameter updates are now capped at **5% relative change** (or a fixed absolute max) per session. This completely solves the "Gradient Explosion" issue where small temperature updates caused wild swings in model parameters.
- **Input Guards**: The model now rejects noise (`< 0.3K`) and dampens learning for small updates (`< 0.8K`), protecting the learned Thermal Mass from corruption during maintenance heating.

### 🛡️ Smart Migration
- This update includes a **Smart Migration** logic. When you update:
    - Your **Thermal Mass** (heating speed) data is **preserved**.
    - Your **Insulation/Loss Factor** is **reset** to defaults (since the old values were calibrated to the broken scaler).
    - A **Repair Issue** ("Thermal Model Recalibration") will appear to inform you of this one-time reset. No action is required from you.

## v2.7.0-beta5
*   **Fix**: Corrected missing translation for the "Preheat Hold" switch (displayed as `switch.xxx_none`). It is now correctly labeled as **"Vorheizen blockieren (Hold)"**.

## v2.7.0-beta4
*   **Improvement**: Exposed internal "Detected Patterns" (V3 Clusters) to the sensor attributes. The "Autonomous Engine Cockpit" card can now visualize exactly which time clusters the AI has learned and how they are weighted.

## v2.7.0-beta3
*   **Improvement**: The `decision_trace` attribute now includes a `session_count` field, exposing the number of learned arrival sessions for the current weekday. This helps users understand the "Data Maturity" and why the Autonomous Engine might be blocked (Requires >3 sessions).

## v2.7.0-beta2
*   **Fix**: Fixed a bug where the "Missing Schedule" repair issue persisted even after disabling "Optimal Stop". The issue is now correctly removed when the feature is turned off.

## v2.7.0-beta1
*   **Fix**: Added missing translation context variables (`name`, `entry_id`) for the "Missing Schedule" repair issue, fixing a generated error in Home Assistant logs.

## v2.7.0-beta0
**Initial Beta for Shadow Mode & Autonomous Engine**

*   **Shadow Mode**: Introduces the foundational "Shadow Mode" where the autonomous engine runs in the background. It calculates predictions and decisions but **does not** control the thermostat.
*   **Decision Trace**: New `decision_trace` attribute on the status sensor provides detailed insight into the engine's decision-making process (e.g., why it would have started/stopped heating).
*   **Zero Risk**: This version collects data and learns your home's behavior (session lengths, cooling rates) without interfering with your existing schedules/automations.

## v2.6.0 (2025-12-20)
**Official Stable Release of Optimal Stop & Context Intelligence**

This release introduces the "Optimal Stop" energy-saving feature, intelligent schedule detection for shift-workers, and a modernized configuration experience.

### ⚠️ Upgrade Notes / Behavior Changes
- **Optimal Stop Requirement**: If you enable "Optimal Stop", you **must** now provide a `schedule` entity (Helper). The configuration will enforce this.
- **Legacy Sensors**: The `binary_sensor.preheat_active` is deprecated and disabled by default. Please use `switch.preheat` (state) or `sensor.status` (attributes) instead.
- **Configuration Storage**: Internal storage has been refactored to strictly separate Hardware (Sensors) from Behavior (Options). Migration is automatic, but downgrading to <2.5.0 requires a backup.

### 🌟 New Features
- **Optimal Stop (Coast-to-Vacancy)**: The system can now turn off heating *early* (coasting to a stop) if a scheduled absence is approaching. Requires a Schedule Helper.
- **Smart Shift-Work Detection**: The new v3 Planner detects complex patterns (e.g. alternating early/late shifts) and weekend-skipping logic.
- **Reconfigure Dialog**: You can now change core hardware sensors (like changing a thermostat) via the "Reconfigure" button without deleting the integration.

### 🔨 Improvements
- **Robust Config Flow**: Validation is now stricter and preserves your input if errors occur.
- **Better Diagnostics**: Added "Repair Issues" for missing weather entities or insufficient heating duration.
- **Internationalization**: Full English and German translations for all new features and errors.

### 🐛 Fixes
- Fixed an oscillation loop where "Eco Mode" changes were interpreted as User Overrides.
- Fixed `ImportError` on Python 3.10 systems.
- Fixed data corruption issues with legacy `None` values in storage.

---

### Beta History (v2.6.0-beta1 to beta44)

## v2.6.0-beta44
- **Translation**: Added missing German translations for `preheat_active` (Legacy Sensor) and `weather_setup_failed` (Repair Issue).

## v2.6.0-beta43
- **Translation**: Added missing German translation for the "Reconfiguration Successful" message.

## v2.6.0-beta42
- **UX Fix**: Fixed an issue where the Setup Wizard would reset all fields if the "Optimal Stop" validation failed. Now, your entered data is preserved.
- **Translation**: Added missing German translation for the "Schedule Entity Required" error message.

## v2.6.0-beta41
- **UX Improvement**: Refined "Optimal Stop" setup. `Schedule Entity` is now clearly labeled and strictly required when Optimal Stop is enabled.
- **Config Flow**: Added validation to prevent enabling Optimal Stop without a schedule. Moved schedule selection out of "Expert Mode".
- **Documentation**: Updated configuration guide to reflect these changes.

## v2.6.0-beta40
- **Flow Refactor**: Enforced strict separation between **Reconfigure** (Hardware/Sensors only) and **Configure** (Tuning/Options). Removed duplication of Time/Profile settings from the Reconfigure dialog.

## v2.6.0-beta39
- **Translation**: Added German translations for the "Reconfigure" dialog.

## v2.6.0-beta38
- **Translation**: Added missing translation keys for the new "Reconfigure" dialog.

## v2.6.0-beta37
- **Feature**: Added "Reconfigure" button support. Users can now change Core Entities (Occupancy, Climate, etc.) via the "Reconfigure" button in the Integrations dashboard.

## v2.6.0-beta36
- **Hotfix**: Fixed `AttributeError` by renaming internal config entry storage to avoid collision with read-only property in `OptionsFlow`.

## v2.6.0-beta35
- **Hotfix**: Fixed critical `TypeError` when opening Options Flow. Added missing `__init__` method to `PreheatingOptionsFlow`.

## v2.6.0-beta34
- **Config Flow Modernization**: Major refactor of the configuration flow (strict core/options separation, robust migration v1->v3, safe merging of expert options).
- **Internationalization**: Full i18n support for all selectors and error messages (keys added to strings.json).
- **Validation Consistency**: Aligned UI limits with backend validation (120 min buffer, 12h duration).
- **Inertia Compensation**: Added logic to account for the "Latent Heat" (Nachlaufzeit) of radiators.

## v2.6.0-beta33
- **Inertia Compensation**: Added logic to account for the "Latent Heat" (Nachlaufzeit) of radiators. The "Optimal Stop" calculation now adds the system's `deadtime` (default 15-30min depending on profile) to the coast duration. This allows the system to shut off earlier, anticipating that the radiator will continue to heat the room for a while after the valve closes.

## v2.6.0-beta32
- **Optimal Stop Stability**: Increased the tolerance for user-override detection from 0.1K to 0.5K. This prevents the "Optimal Stop" feature from aborting prematurely if the thermostat reports small fluctuations in the setpoint (e.g., electronic noise or internal adjustments).

## v2.6.0-beta31
- **Oscillation Fix**: Fixed a feedback loop in the "Optimal Stop" feature. Previously, if an external automation lowered the thermostat setpoint (e.g., Eco Mode) *after* Optimal Stop activated, the integration interpreted this as a user override and reset itself, causing an On/Off loop. Now, setpoint *decreases* are correctly ignored, while *increases* (user demand) still trigger a reset.

## v2.6.0-beta30
- **Learning Fix**: Resolved an issue where the system would stop learning if the user arrived early (during the preheat phase). Now, partial preheating sessions are correctly analyzed by the physics model, provided there is enough data (at least 0.2K rise). This allows the system to auto-correct "Too Late" starts.

## v2.6.0-beta29
- **Resilience**: Added robust checks for the Weather entity. If the weather service is not ready at startup, Preheat will wait gracefully instead of crashing.
- **Diagnostic Issue**: If the weather configuration remains broken for > 5 minutes, a Repair Issue is created (asking the user to check config) and auto-resolved when fixed.
- **Logs**: Improved "Window Open" logging (Downgraded to INFO, added Zone Name) to reduce alarm fatigue.
- **Fix**: Multiple critical bugfixes for `ImportError` and `NameError` caused by the aggressive code cleanup in beta23.

## v2.6.0-beta23
- **Diagnostic Upgrade**: Added a "Repair Issue" warning if the calculated heating duration exceeds your configured Maximum Duration logic.
- **Learning Fix**: Preheating that times out (reaches Max Duration) now correctly triggers learning (teaching the model that heating was slower than expected), instead of just aborting.
- **Code Cleanup**: Massive cleanup of internal code (removed unused constants, dead code branches, and duplicate imports).
- **Docs**: Documentation structure finalized in `docs/` folder.

## v2.6.0-beta22 (2025-12-14)
*   **Test Suite**: Added a comprehensive `test_resilience.py` ensuring that legacy data corruption or missing configuration defaults will not crash the integration.
*   **Compatibility**: Fixed `ImportError` on Python 3.10 systems due to missing `typing.override` (feature only available in 3.12+).
*   **Stability**: The test suite now validates that all integration modules can be imported and initialized successfully before release.

## v2.6.0-beta21 (2025-12-14)
*   **Fix**: Added missing imports for the default values introduced in beta20. This resolves the `NameError: name 'DEFAULT_STOP_TOLERANCE' is not defined`.

## v2.6.0-beta20 (2025-12-14)
*   **Fix**: Resolved the *actual* cause of the "Update failed" error. It was due to missing default values for the new "Optimal Stop" configuration settings (added in v2.5). Older installations without these settings were passing `None` values, causing a crash during calculation.

## v2.6.0-beta19 (2025-12-14)
*   **Syntax Fix**: Removed a duplicated line in `physics.py` that caused an `IndentationError` in beta18. Apologies for the noise!

## v2.6.0-beta18 (2025-12-14)
*   **Deep Fix**: Addressed a persistent "Data Corruption" issue where stored Null values were bypassing safety checks. Both loading and logic layers now strictly enforce numeric types, preventing `NoneType` crashes even with corrupted legacy data.

## v2.6.0-beta17 (2025-12-14)
*   **Syntax Fix**: Removed a duplicate `if data:` line that caused an `IndentationError` in beta16.

## v2.6.0-beta16 (2025-12-14)
*   **Fix**: Added robust guards against `NoneType` errors during setup. If stored data is corrupted or contains null values for physics parameters, the system now safely falls back to defaults instead of crashing with an `unsupported operand` error.

## v2.6.0-beta15 (2025-12-14)
*   **Critical Fix**: Fixed Unavailable entities (Status, Confidence) caused by an accidental code deletion in beta14. Everything is back to normal now.

## v2.6.0-beta14 (2025-12-14)
*   **Physics Refinement**: Improved prediction accuracy for small temperature differences. The "Cold Wall Effect" (heat loss compensation) now scales dynamically with the heating amount. This prevents implausibly long duration predictions for minor temperature adjustments (e.g. < 1°C).

## v2.6.0-beta13 (2025-12-14)
*   **Fix**: Corrected physics calculation where `Predicted Duration` could be high (e.g. 70+ mins) even if the room was already warmer than the target temperature. This was due to the thermal loss factor (compensating for outside cold) being applied even when no heating was required. Now, if the room is warm enough, duration is strictly 0.

## v2.6.0-beta12 (2025-12-14)
*   **Critical Fix**: Fixed an `AttributeError` in `PreheatPlanner` where core prediction methods were briefly missing in beta10/11. The integration is now fully functional and safe again.

## v2.6.0-beta11 (2025-12-14)
*   **Legacy Compatibility**: Improved downgrade protection for versions older than 2.5 (e.g. 2.4/2.2). Newer v3 data is now sequestered in a container key (`999`) preventing `ValueError` crashes in older versions that strictly expect integer storage keys.

## v2.6.0-beta10 (2025-12-14)
*   **Downgrade Safety**: Refactored data storage to ensure backward compatibility with v2.5.0. Legacy history data is now strictly written to standard keys (0-6) as integers, while new v3 data is stored in separate keys (`v3_0`-`v3_6`). This prevents crashes if downgrading to the stable version.
*   **Note**: If you removed the now-optional `Temperature Sensor` in v2.6, you **must re-add it** before downgrading to v2.5, as the old version requires it.

## v2.6.0-beta9 (2025-12-14)
*   **Documentation**: Fully translated all sensor attributes (e.g. `Geplanter Start`, `Muster-Typ`, `Modell-Konfidenz`) in the German translation. No more English attributes in Lovelace cards.

## v2.6.0-beta8 (2025-12-14)
*   **Documentation**: Updated translation strings (German/English) to correctly reflect mandatory vs. optional fields in the config flow. `Thermostat` is now labeled as "Required" / "Pflicht".

## v2.6.0-beta7 (2025-12-14)
*   **UX Consistency**: Ensured that the Initial Setup dialog matches the "Reconfigure" dialog (Non-Expert) exactly. Added `Weather Entity` back to the initial setup screen as an optional but recommended setting (helps with outdoor temperature data).

## v2.6.0-beta6 (2025-12-14)
*   **UX Improvement**: Reorganized the configuration to be cleaner (Phase 2 Cleanup).
*   **Change**: `Climate Entity` is now **Required**. It acts as the central control unit.
*   **Change**: `Temperature Sensor` is now **Optional**. If not set, the temperature from the Climate entity is used.
*   **Change**: Important settings like `Arrival Window` and `Optimal Stop` are now visible on the main configuration page/tab, moving out of the "Expert" shadow.

## v2.6.0-beta5 (2025-12-13)
*   **Improvement**: Increased "Analyze History" lookback window from 28 to 90 days. We now try to learn from up to 3 months of past data if your recorder settings allow it.

## v2.6.0-beta4 (2025-12-13)
*   **Improvement**: Lowered the threshold for v3 pattern recognition from 4 to 3 events. This allows the new logic to kick in immediately if you use "Analyze History" (which typically provides 3-4 weeks of data).

## v2.6.0-beta3 (2025-12-13)
*   **Fix**: Fixed empty Sensor Attributes (Pattern type=none) during legacy fallback (Phase 1).
*   **Fix**: Fixed empty Schedule Summary list by correctly falling back to v2 data when v3 data is sparse.

## v2.6.0-beta2 (2025-12-13)
*   **Fix**: Critical fix for data migration. Restored loading of legacy arrival timestamps which were being reset in beta1.
*   **Improvement**: Reduced log level of "Workday sensor unavailable" from Warning to Info during startup.

## v2.6.0-beta1 (2025-12-13)

### 🗓️ Multi-Modal Clustering (Shift Work Support)
*   **Intelligent Pattern Recognition**: The system now detects complex schedules beyond simple weekly repetitions.
    *   **Shift Work**: Automatically Identifies alternating shifts (e.g., Early/Late week rotation).
    *   **Multi-Mode**: Can distinguish between "Early Shift" and "Late Shift" arrival clusters on the same weekday.
*   **Confidence & Stability**: New sensor attributes `pattern_confidence` and `pattern_stability` provide insight into how predictable your schedule is.
*   **Adaptive Migration**: Seamlessly transitions from the old v2 logic to the new v3 engine as it gathers date-aware history.

---

## v2.5.0 (2025-12-12)

**Official Stable Release of Optimal Stop & Context Intelligence** 📉🧠

This release focuses on **saving energy** by knowing when to stop, not just when to start. It introduces the "Coast-to-Stop" feature and intelligent calendar handling.

### 📉 Optimal Stop (Coast-to-Vacancy)
*   **Intelligent Shutdown**: The system can now turn off heating *before* a scheduled vacancy (e.g., leaving for work), letting the room "coast" to a stop while staying within a comfortable temperature tolerance.
*   **Sensors**: Added `sensor.preheat_optimal_stop_time` and `binary_sensor.optimal_stop_active`.
*   **Config**: New "Expert Mode" settings to enable this feature and tune tolerance.
*   **Physics**: A new self-learning component observes how your building cools down (`tau`) to maximize savings without risking comfort.

### 🧠 Workday & Schedule Intelligence
*   **Smart Lookahead**: The planner now scans up to 7 days into the future to find the next valid event, skipping weekends if `Only on workdays` is enabled.
*   **Sensor Integration**: Respects the specific configuration of your `binary_sensor.workday_sensor` (e.g., handles custom workdays like Saturday).
*   **Robustness**: Fallback logic ensures operation even if the Workday sensor is unavailable.

### 🩺 Diagnostics & Health
*   **Health Score**: New `health_score` attribute on the status sensor (0-100%) gives instant feedback on model quality.
*   **Transparency**: Detailed attributes for `stop_reason`, `tau_confidence`, and `savings_minutes`.

### 🌍 Localization
*   **German**: Added full German translations for all new features and configuration options.

---

### Beta Cycle History (v2.5.0-beta1 to beta9)
*   **beta9**: Exposed `health_score` in status sensor.
*   **beta8**: Hotfix for `NameError` crash in workday logic.
*   **beta7**: Fixed "Next Event" logic to correctly skip weekends/holidays.
*   **beta4-5**: Localization updates & formatting polish.
*   **beta2-3**: Fixes for valve position averaging and startup crashes.
*   **beta1**: Initial Optimal Stop implementation.

---
