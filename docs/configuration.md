# ⚙️ Configuration Reference

## Initial Setup Wizard

When you add the integration, you will be asked for the essential entities:

| **Setting** | **Description** | **Required** |
| :--- | :--- | :--- |
| **Occupancy Sensor** | A `binary_sensor` that is **ON** when the room is in use (occupied). | ✅ Yes |
| **Climate Entity** | The thermostat itself. | ✅ Yes |
| **Temperature Sensor** | Room temperature sensor. Optional if Climate entity is accurate. | Optional |
| **Weather Entity** | `weather.*` entity for forecast logic. | Optional |
| **Enable Optimal Stop** | Activates "Coast-to-Stop" logic to save energy. | Optional |
| **Schedule Entity** | A `schedule` helper defining when the day ends. **Required** if Optimal Stop is enabled. | **Conditionally** |

---

## Detailed Settings (Configure)

After installation, click **Configure** on the integration entry to access advanced settings.

### 🏗️ Physics & Learning

*   **Heating Profile**: Select the preset that best matches your hardware to help the initial learning.
    *   *Radiator (Standard)*: Typical water-based radiators.
    *   *Floor (Concrete)*: Slow reacting implementation. High deadtime defaults.
    *   *Air Conditioning*: Fast reacting systems.
*   **Initial Gain**: Manually override the "Minutes per Degree" factor if the automatic learning starts too slow/fast. Lower = Faster heating.

### ⚠️ Risk & Buffers

*   **Risk Mode**: How aggressively should we trust the weather forecast?
    *   *Balanced (Default)*: Moderate trust.
    *   *Pessimistic*: Assumes it's colder than forecasted. Safer, but uses more energy.
    *   *Optimistic*: Assumes it's warmer. Saves energy, risk of being cold.
*   **Buffer (Minutes)**: Add extra minutes to the calculated start time just to be safe. Default: `10`.

### 🛑 Optimal Stop (Eco)

*   **Enable Optimal Stop**: Turns on the coast-to-stop calculation.
*   **Schedule Entity**: A `schedule` helper that defines your "Day". The system needs to know when the "End of Day" is to calculate when to shut off.
    *   *Tip*: Create one in Settings → Helpers → Schedule.
    *   **Note**: If Optimal Stop is enabled, this field is **mandatory**. You cannot save the configuration without it.
*   **Stop Tolerance**: How many degrees drop is acceptable during the coasting phase? Default: `0.5°C`.

### 🕐 Triggers

*   **Only on Workdays**: If checked, preheating will only activate on Mon-Fri (or days defined by your `binary_sensor.workday_sensor`).
*   **Earliest Start Time**: Prevent the heating from starting 03:00 AM if you don't wake up until 07:00.

---

## Entity Explanations

### `switch.preheat`
Is **ON** when the system determines you should be heating *right now* to hit your target. You can also toggle this switch manually to force preheating or stop it.

> **Legacy Note:** This entity was previously named `binary_sensor.preheat_active`. A deprecated alias still exists for backward compatibility but will be removed in v3.0.

### `binary_sensor.optimal_stop_active`
Is **ON** when the system calculates that you can turn **OFF** the heating early, because the residual heat will carry you to the end of the schedule.
