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
