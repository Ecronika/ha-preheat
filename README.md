# Intelligent Preheating for Home Assistant (v2.5.0)

**Turn your heating into a Predictive Smart System.**

This integration acts as a **Stand-Alone Pilot** for your heating. It learns the thermal physics of your room to control **any** thermostat intelligently, without needing complex dependencies.

*   **Goal**: Reach your target temperature *exactly* when you arrive/wake up.
*   **Goal**: Stop heating *before* you leave ("Optimal Stop"), letting the room coast to a stop to save energy.

---

## 📚 Documentation

*   [**Installation Guide**](docs/installation.md)
*   [**Configuration Reference**](docs/configuration.md)
*   [**How it Works (The Math)**](docs/how_it_works.md)
*   [**Troubleshooting & FAQ**](docs/troubleshooting.md)

---

## ✨ Features

*   🧠 **Self-Learning Physics**: Automatically calculates `Thermal Mass`, `Thermal Loss`, and `Deadtime` (Totzeit) for each room.
*   📉 **Optimal Stop (Coast-to-Vacancy)**: **[Unique]** Turns off the heating early if the room stays warm enough until the schedule ends.
*   🔌 **Stand-Alone**: Works with any thermostat entity. No external "Scheduler Component" or "Virtual Thermostat" required.
*   ⛈️ **Weather Forecast Integration**: Looks ahead at the weather forecast to adjust heating power for incoming cold fronts.
*   🪟 **Window Detection**: Pauses operation if a rapid temperature drop is detected.
*   🛡️ **Robustness**: Filters out sensor noise and ignores "low valve position" learning to ensure data quality.
*   🔍 **Transparent**: Provides detailed Diagnostics, Confidence scores, and "Reason" attributes so you know *why* it acted.
*   🌎 **Localized**: Available in English and German.

## 🧠 How it works (The Math)

The system treats your room like a physical battery. It learns two main things:
1.  **Charge Rate (Thermal Mass)**: How long does it take to raise the temperature by 1°C?
2.  **Leak Rate (Thermal Loss)**: How fast does the room lose heat to the outside?

**Simple Calculation Example:**
*   **Target**: 21°C at 07:00
*   **Current Temp**: 18°C
*   **Learned Rate**: Your room heats at **2°C per hour**.
*   **Calculation**: `(21 - 18) / 2 = 1.5 hours`.
*   **Result**: Start heating at **05:30**.

*Note: In reality, the physics engine is much smarter. It uses a differential equation solver to account for outdoor temperature, heat loss during the heat-up phase, and system latency (Deadtime).*

---

## 📦 Installation

**Prerequisites**: Just Home Assistant. No extra integrations required.

1.  **HACS**:
    *   Add this repository as a **Custom Repository** in HACS.
    *   Search for "Intelligent Preheating" and install.
    *   Restart Home Assistant.
2.  **Configuration**:
    *   Go to **Settings** -> **Devices & Services** -> **Add Integration**.
    *   Search for "Intelligent Preheating".
    *   Follow the setup wizard.

---

## ⚙️ Configuration

### Basic Setup
*   **Occupancy Sensor**: A binary sensor that indicates if the room is *IN USE*. (See "Critical Note" below).
*   **Temperature Sensor**: The accurate room temperature.
*   **Climate Entity** (Optional): The thermostat to control.
*   **Weather Entity** (Optional): For forecast-based prediction.
*   **Valve Position** (Optional): Helps the system learn only when heating is actually active.

### Expert Settings
Once added, click "Configure" on the integration entry to access:
*   **Enable Optimal Stop**: Activate the Coast-to-Stop feature.
*   **Schedule Entity**: Required for Optimal Stop to know when the heating period ends.
*   **Heating Profile**: Select your system type (e.g., *Radiator New*, *Floor Concrete*) to assist the learning algorithm.
*   **Risk Mode**: Choose between *Balanced*, *Pessimistic* (Comfort), or *Optimistic* (Savings) for weather handling.

---

## 💡 Key Concepts

### ⚠️ The Occupancy Sensor (Critical!)
This integration uses **Presence** to determining when to **STOP** preheating.
*   **ON (True)**: "User is here." -> Preheating stops, normal thermostat schedule/rules take over.
*   **OFF (False)**: "Room is empty." -> System waits for the next predicted arrival to start pre-heating.

> **Do NOT** use a simple time-scheduler (e.g., "On at 7am") as the Occupancy Sensor. This would shut down the preheater exactly when it tries to work. Use a real presence sensor or a logic helper that represents "People are present".

### 🍃 Optimal Stop (Signals, not Magic)
If enabled, the integration calculates the earliest possible shutdown time.
It exposes a **Binary Sensor** (`binary_sensor.zone_optimal_stop_active`).
*   **ON**: "You can turn off the heating now. It will stay warm."
*   **OFF**: "keep heating."

**Automation Example**:
```yaml
trigger:
  - platform: state
    entity_id: binary_sensor.office_optimal_stop_active
    to: "on"
action:
  - service: climate.set_temperature
    target:
      entity_id: climate.office
    data:
      temperature: 19 # Eco Temperature
```

---

## ❓ FAQ

**Q: Why are my physics values (Mass/Deadtime) not changing?**
A: The system filters out "noise". It only learns from "clean" heating events (Temp rise > 0.5K, Valve open). If you only maintain temperature (hysteresis), it won't change the model often. This is normal.

**Q: Does it handle Daylight Savings Time?**
A: Yes. All calculations use UTC internally. The physics (duration) remain valid regardless of how the wall clock shifts.

**Q: Can I use it for Floor Heating?**
A: Yes! Select the "Floor (Concrete)" profile. Computing `Deadtime` (delay) is specifically designed for slow floor systems.

---

**License**: MIT
