## v2.9.1 (2026-01-14) - The Reliability Update 🛡️
**Stable Release**

This release marks the completion of the "Autonomous Engine" overhaul. It consolidates 13 beta iterations focusing on **Physics Accuracy**, **Planner Robustness**, and **Bootstrap Speed**.

### 🌟 Key Highlights
*   **Physics Fixed**: **Deadtime Learning** is now fully active. The system correctly populates its history buffer during heating, allowing it to learn the exact "Totzeit" (deadtime) of your radiators/floor heating.
*   **Planner V3**: A complete rewrite of the history management logic ("The Planner"). It is now timezone-safe, strictly typed, and self-healing (auto-prunes corrupt data).
*   **Instant Bootstrap**: Installing this version triggers a **Retroactive History Scan**. It reads your Home Assistant Recorder history to learn your habits *immediately*, eliminating the week-long "Cold Start" phase.
*   **Eco-Mode Compatible**: The prediction logic now persists your "Comfort Temperature". If you switch your thermostat to Eco/Away, the system still calculates the correct preheat time to reach *Comfort* (instead of dropping to 0 minutes).

### 🐛 Critical Fixes
*   **Optimal Stop**: Fixed a timing bug where the "Coast-to-Vacancy" stop time was calculated relative to *Arrival* instead of *Departure*.
*   **Zero Glitch**: Fixed an issue where transient sensor errors caused predicted duration to flash "0 minutes".
*   **Midnight Filter**: Solved "Unknown" sensor states by implementing smart fallbacks when the Schedule entity returns ambiguous midnight dates.

### 🧹 Beta History (Merged)
*   **beta13**: Fix Deadtime Learning (Buffer Population).
*   **beta12**: Restore Logic Gates & Fix Crash on Missing Schedule.
*   **beta11**: Target Temperature Persistence.
*   **beta6-10**: Optimal Stop Timing & Glitch Fixes.
*   **beta1-5**: Planner Refactor & Bootstrap Logic.

---

## v2.9.1-beta13
- **Fix (Critical):** Enabled Deadtime Learning by correctly populating the history buffer during preheat cycles.
  - Previously, the buffer remained empty, causing Deadtime to stick to default values (0 or 15).

## v2.9.1-beta12
- **Fix (Critical):** Resolved `LearnedDepartureProvider` crash when Schedule is missing (fallback for `potential_savings`).
- **Fix (Logic):** Restored Gate Check logic (Savings & Confidence) in Learned Provider.
- **Fix (Pattern):** Relaxed filtering to allow DST-flagged departures if they are the only data available (prevents "Unknown setpoint" errors).
- **Internal:** Comprehensive unit test fixes for Rollover, Safety, and Migration modules.

## v2.9.1-beta11 (2026-01-12) - Target Temp Persistence 🌡️

### 🐛 Fixes
*   **Target Temp / Prediction**: Fixed an issue where the `predicted_duration` would drop to 0 minutes when the room was set to **Eco/Away** mode (lowering the setpoint).
    *   **Logic**: The system now learns your **Comfort Temperature** (while Occupied) and persists it.
    *   **Behavior**: When Unoccupied (and setpoint drops), the prediction will now calculate the time required to reach your **Last Known Comfort Temperature**, ensuring you always see "Time to Comfort" instead of "Time to Eco".

---

## v2.9.1-beta10 (2026-01-12) - Repair Issue Names 🏷️

### 🐛 Fixes
*   **Repair Issues**: Added missing **Device Name** to repair issue titles (e.g., "Valve Saturated in Office", "Thermal Mass Limit in Living Room"). This makes it much easier to identify which zone is affected when multiple issues are reported.

---

## v2.9.1-beta9 (2026-01-12) - Zero Duration Glitch Fix 2 📉

### 🐛 Fixes
*   **Imoroved "Zero Duration" Fix**: Added a plausibility check. If the room is clearly too cold (> 0.5°C difference), the system will refuse to accept a "0 minutes" heating duration (which usually indicates a calculation error or data glitch) and instead hold the last valid value.

---

## v2.9.1-beta8 (2026-01-12) - Bugfix: Unbound Variable 🐛

### 🐛 Fixes
*   **Fixed UnboundLocalError 'predicted_end'**: Fixed a crash that occurred when the system tried to predict a session end in "Anchored Mode" (when a Schedule is active) but had no historical data for that day.

---

## v2.9.1-beta7 (2026-01-12) - Predicted Duration Stability 📉

### 🐛 Fixes
*   **Fixed "Predicted Duration" dropping to 0**: During transient sensor unavailability (e.g., sensor update glitches), the predicted duration would momentarily drop to 0, ruining statistics graphs. The system now persists the last known valid duration and uses it during these short outages.

---

## v2.9.1-beta6 (2026-01-12) - Critical: Fix Optimal Stop Timing ⏰

### 🐛 Critical Fixes
*   **Fixed Optimal Stop using wrong session end**: The `OptimalStopManager` was receiving `next_event` (the next **ARRIVAL** time, e.g., 17:00) instead of `effective_departure` (the **DEPARTURE** time, e.g., 07:30). This caused the "Optimaler Abschaltzeitpunkt" sensor to show times that made no sense relative to the actual session end.

---

## v2.9.1-beta5 (2026-01-11) - AI Fallback after Midnight Filter 🌙

### 🐛 Fixes
*   **Fixed "Next Session End" showing Unknown**: After filtering midnight dates, the system now falls back to the AI prediction (`learned_decision.session_end`) instead of showing "Unknown". This ensures the sensor shows the next learned departure (e.g., "Mittwoch 14:26") when the Schedule entity returns an invalid date-only value.

---

## v2.9.1-beta4 (2026-01-11) - Midnight Filter 🌙

## v2.9.1-beta3 (2026-01-11) - Faster Bootstrap ⚡

### ⚡ Improvements
*   **Reduced Bootstrap Delay**: History scan now starts after 30 seconds (was 5 minutes).
*   **User Feedback**: Added INFO log message: `[Zone Name] History scan will start in 30 seconds...`

---

## v2.9.1-beta2 (2026-01-11) - Bootstrap Fix 🔧

### 🐛 Fixes
*   **Fixed Bootstrap Order Bug**: The retroactive history scan timer was being scheduled *before* loading `bootstrap_done` from storage. This caused the timer to always be scheduled (even for existing zones where bootstrap was already done). Now the order is correct:
    1. Load `bootstrap_done` from storage
    2. Check for sparse data and reset flag if needed
    3. Schedule timer only if `bootstrap_done` is still `False`

---

## v2.9.1-beta1 (2026-01-11) - The Planner Refactor 🔧

**Major Reliability & Robustness Update for the Planner Module**

### 🔧 Planner Refactoring (9 Rounds of Polish)
*   **Robust History Loading**: Complete overhaul with key normalization, container-key handling (`999`/`888`), per-item parsing with granular error handling, and type validation.
*   **Legacy Phase-Out**: v2 history is now **read-only** (no longer written). Full migration to v3 format in progress.
*   **TZ Safety**: All public methods now ensure `now` is timezone-aware via `dt_util.as_local()`.
*   **Debounce Active**: Both Arrival and Departure recording now use debounce to prevent history noise.
*   **Pruning Improvements**:
    *   Global pruning (Age + Count) for all history types.
    *   Sorting before FIFO prune ensures chronological order.
    *   Empty keys are deleted to keep persistence clean.
*   **Input Validation**:
    *   v3 minutes range validated (0-1439).
    *   Departure date validated as ISO format.
    *   Departure minutes cast to int (no in-place mutation).
*   **Pattern Result Consistency**: `last_pattern_result` now uses actual blended `prediction_minute` in Hybrid phase.
*   **Centralized Constants**: `MIN_POINTS_FOR_V3` and `FULL_V3_POINTS` moved to `const.py`.

### 🐛 Fixes
*   Fixed DST detection logging (now `debug` level, marked as "Best Effort / Diagnostic Only").
*   Fixed potential `last_pattern_result` inconsistency when no candidates are generated.

---

## v2.9.0 (2026-01-11) - The Clean Code Release 🧹
**Major Maintenance & Feature Update**

This version combines the feature set of the planned v2.9.0 with immediate stability and architectural fixes.

### 🧹 Config Flow Refactor & Stability
*   **Deep Cleaning**: Massive cleanup of the internal configuration logic. removed unused imports and centralized settings.
*   **Climate Locking**: To prevent "Zombie Entities" (Unique ID collisions), the `Climate Entity` is now **locked** in the "Reconfigure" dialog.
*   **Safe Merging**: The Options flow now safely merges new settings with existing overrides.
*   **V4 Migration**: Automatically cleans up "Legacy" storage data (null values) during startup.
*   **Unique ID Upgrade**: New installations prefer the stable `Registry ID`.

### 🐛 Fixes
*   **Service Reliability**: Improved robustness for `recompute` calls.
*   **Encoding**: Fixed `°C` display issues.
*   **Repair Issues**: 
    *   Added missing zone names to titles.
    *   Fixed "Stale Sensor" false positives for Climate entities (now uses `last_updated`).
    *   Relaxed "Max Duration" warning (added 30m buffer & schedule check).
    *   Fixed "Unknown" state for Next Session End sensor (improved day rollover logic).
*   **Config Flow**: Restored "Max Preheat Duration" setting to allow user overrides.

### � Key Features (from original v2.9.0)
*   **Simplified Configuration**: Smart defaults based on Heating Profile.
*   **Reactive Diagnostics**: 15+ built-in health checks (Stale Sensors, Valve Saturation, etc.).
*   **Multi-Modal Learning**: Different logic for Weekdays vs Weekends vs Holidays.
*   **Anti-Flapping**: Better detection for short departures (e.g. taking out trash).

---

**Major Feature Release**

This release transforms Intelligent Preheating from a "power user" tool into a polished, smart appliance-grade integration. It introduces massive improvements in usability, safety, and intelligence.

### 🧹 UX & Usability (Massive Cleanup)
*   **Simplified Configuration**: We've removed ~70% of the complex "Expert" settings. The system now automatically tunes itself based on your selected **Heating Profile** (Radiators vs Floor Heating) and environment.
*   **Smart Defaults**: Features like "Max Coast Duration" and "Physics Parameters" are now auto-determined, preventing common configuration errors.
*   **Reactive Diagnostics**: The integration now includes 15+ built-in health checks (Repair Issues) that will alert you to:
    *   **Stale Sensors**: Warning if your temperature sensors stop updating (>6h).
    *   **Configuration Errors**: Alerting on missing entities or invalid physics.
    *   **Zombie State**: Detecting if learning has stalled.
    *   *Repair issues explicitly name the Zone, making multi-zone troubleshooting much easier.*

### 🛡️ Safety & Responsiveness
*   **Frost Protection**: Heating is now *forced* ON if Operative Temperature drops below 5.0°C, ensuring pipes don't freeze even if the integration is effectively disabled.
*   **Reactive Setpoints**: The system now re-calculates logic *immediately* when you change the target temperature or thermostat state (0 latency response).
*   **Physics Safety Net**: The thermal model is now ISO 12831 validated. We've added a "Safety Net" that prevents the learning model from becoming unstable (e.g. learning impossible physics values).
*   **Entity Cleanup**: Internal debug entities are now hidden by default to keep your dashboard clean.

### 🧠 Intelligence Upgrades
*   **Retroactive Bootstrap (New!)**: When you install this secure version, it will **automatically scan your Home Assistant history** (Recorder) to learn your habits instantly. No more "Cold Start" week!
*   **Schedule-Free Operation**: You no longer need a strict Schedule Helper. The system can now operate purely on **Learned Patterns** (Observer Mode) or manual Input Datetimes.
*   **Smart Multi-Modal Planner**:
    *   **Multiple Shifts**: Supports complex days (Lunch breaks, Split shifts).
    *   **Smart Departure**: Logic uses "Clustering" to predict when you will leave, even if your schedule varies.
*   **Anti-Flapping**: Short absences (bathroom breaks, trash runs < 15min) are no longer recorded as "New Arrivals", significantly improving data quality.

### ⚡ Performance
*   **Adaptive Polling**: The integration now "sleeps" (5min updates) when idle and "sprint" (1min updates) when active, reducing database writes and CPU load by ~80%.

### 🩹 Major Bugfixes
*   **Weather Fallback**: Significantly improved compatibility with weather providers (PirateWeather, etc.) by implementing smart fallback (Hourly -> Daily) and interpolation.
*   **Timezone Logic**: Fixed multiple edge cases with Midnight Wrapping and Timezone handling.




---

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
