# ⚙️ Configuration Reference

## Initial Setup Wizard

When you add the integration, you will be asked for the essential entities:

| Field | Description | Required |
| :--- | :--- | :--- |
| **Occupancy Sensor** | A `binary_sensor` that is **ON** when the room is in use (occupied) and **OFF** when empty. This is the master trigger for learning and scheduling. | ✅ Yes |
| **Climate Entity** | The thermostat itself. Used to read target temp and valve positions. This is now the primary source of truth. | ✅ Yes |
| **Temperature Sensor** | A `sensor` measuring the current room temperature. Optional if your Climate entity reports accurate room temperature (`current_temperature`). | Optional |
| **Target Setpoint** | Read directly from the Climate entity. Only needed if you don't use a Climate entity (deprecated setup). | Optional |
| **Weather Entity** | A `weather.*` entity for forecast-based adjustments. | Optional |

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
*   **Buffer (Minutes)**: Add extra minutes to the calculated start time just to be safe. Default: `0`.

### 🛑 Optimal Stop (Eco)

*   **Enable Optimal Stop**: Turns on the coast-to-stop calculation.
*   **Schedule Entity**: A `schedule` or `binary_sensor` that defines your "Day". The system needs to know when the "End of Day" is to calculate when to shut off.
*   **Stop Tolerance**: How many degrees drop is acceptable during the coasting phase? Default: `0.5°C`.

### 🕐 Triggers

*   **Only on Workdays**: If checked, preheating will only activate on Mon-Fri (or days defined by your `binary_sensor.workday_sensor`).
*   **Earliest Start Time**: Prevent the heating from starting 03:00 AM if you don't wake up until 07:00.

---

## Entity Explanations

### `binary_sensor.preheat_active`
Is **ON** when the system thinks you should be heating *right now* to hit your target. You can use this in automations to switch your thermostat to "Comfort".

### `binary_sensor.optimal_stop_active`
Is **ON** when the system calculates that you can turn **OFF** the heating early, because the residual heat will carry you to the end of the schedule.
