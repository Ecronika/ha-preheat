# Intelligent Preheating for Home Assistant (v2.9.1)

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

## 🚀 Quick Start (Plug & Play)

**Important:** This integration calculates the *optimal time*. You need an automation or Blueprint to actually control your thermostat!

### 1. The Easy Way (Blueprint)
Use the official **Smart Setpoint Controller** Blueprint. It connects this integration with your thermostats (TRVs) in seconds:

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint URL.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgist.github.com%2FEcronika%2F6751f92f7d5717bbe14b43e5ee36ebe7)

*   **View Discussion:** [Smart Setpoint Blueprint (Community)](https://community.home-assistant.io/t/en-16798-1-smart-setpoint-blueprint/956624)
*   **What it does:** Automatically switches between Comfort/Eco based on the `preheat` and `optimal_stop` signals.

## ✨ Features

### 🧠 Intelligence & Learning
*   **Self-Learning Physics**: Automatically calculates `Thermal Mass`, `Thermal Loss`, and `Deadtime`. Supports **Euler Simulation** for complex scenarios.
*   **The Observer**: Learns your habits to predict *when* you leave (Shadow Mode), providing "Next Departure" insights.
*   **Calendar Intelligence**: Auto-detects holidays and shifts via Calendar integration to skip preheating intelligently.
*   **🚀 Retroactive Bootstrap (New in v2.9.0)**: On first install, the system automatically scans your Home Assistant history to learn your habits instantly. No more "cold start" week!

### 🛡️ Safety & Responsiveness
*   **Frost Protection**: Heating is automatically forced ON if the temperature drops below 5°C, even if the system is disabled.
*   **⚡ Reactive Setpoints**: The system re-calculates *immediately* when you change the target temperature (0 latency).
*   **Physics Safety Net**: The thermal model is ISO 12831 validated with protection against learning instability.

### 📉 Energy Saving
*   **Optimal Stop (Coast-to-Vacancy)**: Turns off the heating early if the room stays warm enough until the schedule ends.
*   **Schedule-Free Operation**: Works with Learned Patterns alone—no Schedule Helper required.
*   **Adaptive Polling**: Sleeps (5 min updates) when idle, sprints (1 min) when active—**80% less system load**.

### 🔌 Compatibility & Control
*   **Stand-Alone**: Works with any thermostat entity. No external "Scheduler Component" required.
*   **Weather Forecast Integration**: Looks ahead at the weather forecast to adjust heating power for incoming cold fronts.
*   **🪟 Window Detection**: Pauses operation if a rapid temperature drop is detected.
*   **🔥 Heat Demand Sensor**: `binary_sensor.<zone>_heat_demand` signals when a zone needs active heat supply.

### 🔍 Transparency & Diagnostics
*   **15+ Repair Issues**: Built-in health checks alert you to stale sensors, misconfigurations, or learning problems.
*   **Decision Trace**: Provides detailed Diagnostics, Confidence scores, and "Reason" attributes so you know *why* it acted.
*   **🌎 Localized**: Available in English and German.

---

## 🚀 Quick Start

1.  **Install** via HACS (Custom Repository).
2.  **Add Integration** in Home Assistant settings.
3.  **Config**: Select your **Heating Profile**, **Climate Entity** (Thermostat), and **Occupancy Sensor**.
4.  **Done**: The system auto-scans your history and starts learning immediately!

---

**License**: MIT

