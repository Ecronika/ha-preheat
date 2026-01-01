# Intelligent Preheating for Home Assistant (v2.8.0)

**Turn your heating into a Predictive Smart System.**

This integration acts as a **Stand-Alone Pilot** for your heating. It learns the thermal physics of your room to control **any** thermostat intelligently, without needing complex dependencies.

*   **Goal**: Reach your target temperature *exactly* when you arrive/wake up.
*   **Goal**: Stop heating *before* you leave ("Optimal Stop"), letting the room coast to a stop to save energy.

---

## 📚 Documentation

Detailed documentation is available in the `docs/` folder:

*   **[Installation Guide](docs/installation.md)** (HACS & Manual)
*   **[Configuration Reference](docs/configuration.md)** (All parameters explained)
*   **[How it Works (The Math)](docs/how_it_works.md)** (Physics & Optimal Stop theory)
*   **[Troubleshooting & FAQ](docs/troubleshooting.md)** (Common issues and solutions)

---

## ✨ Features

*   🧠 **Self-Learning Physics (Advanced)**: Automatically calculates `Thermal Mass`, `Thermal Loss`, and `Deadtime` (Totzeit). Supports **Euler Simulation** for complex scenarios.
*   👁️ **The Observer**: Learns your habits to predict *when* you leave (Shadow Mode), providing "Next Departure" insights.
*   📅 **Calendar Intelligence**: Auto-detects holidays and shifts via Calendar integration to skip preheating intelligently.
*   📉 **Optimal Stop (Coast-to-Vacancy)**: Turns off the heating early if the room stays warm enough until the schedule ends.
*   🔌 **Stand-Alone**: Works with any thermostat entity. No external "Scheduler Component" or "Virtual Thermostat" required.
*   ⛈️ **Weather Forecast Integration**: Looks ahead at the weather forecast to adjust heating power for incoming cold fronts.
*   🪟 **Window Detection**: Pauses operation if a rapid temperature drop is detected.
*   🛡️ **Robustness**: Filters out sensor noise and ignores "low valve position" learning to ensure data quality.
*   🔍 **Transparent**: Provides detailed Diagnostics, Confidence scores, and "Reason" attributes so you know *why* it acted.
*   🌎 **Localized**: Available in English and German.
*   🐍 **Resilient**: Validated for Python 3.10 through 3.12 compatibility.

---

## 🚀 Quick Start

1.  **Install** via HACS (Custom Repository).
2.  **Add Integration** in Home Assistant settings.
3.  **Config**: Select your **Climate Entity** (Thermostat), **Occupancy Sensor**, and optionally a **Target Temp** helper.
4.  **Wait**: The system needs about 3-5 days of typical usage to learn your room's physics perfectly.

---

**License**: MIT
