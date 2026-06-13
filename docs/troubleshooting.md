# 🔧 Troubleshooting

## Common Issues

### "The system never turns on!"

1.  **Check Occupancy**: Is your occupancy sensor currently `OFF`? The system only pre-heats if it thinks the room is currently *empty* but *will be occupied soon*. If you are already there (`ON`), it assumes the normal thermostat is running and does nothing.
2.  **Check Target Temp**: Is the target setpoint higher than the current temperature?
3.  **Check "Frost Protection"**: If the room is below 5°C, the system will force-start regardless of other settings.
4.  **Check Schedule-Free / House Hub Confidence**: If you are running a schedule-free configuration (no Schedule Helper selected), the zone will only start preheating autonomously once the **House Arrival Hub** has registered enough arrival history and reached sufficient confidence (>= 70% confidence). Until then, it will wait. Check that the **"Preheat System"** configuration entry exists and is active.

### "It starts too late / The room is cold."
*   **Solution**: Increase the **Buffer** in the configuration options.
*   The system *will* learn from this mistake. If it misses the target, the next day's prediction will be more aggressive.

### "It starts way too early!"
*   Check your **Heating Profile**. Did you select "Floor Heating" for a radiator? Floor heating profiles assume massive delays (3+ hours).
*   Check the **Outdoor Temperature**. If `weather_entity` is missing or reporting wrong values (e.g., -20°C), the system might panic and over-heat.

---

## 🛠️ Repair Issues (Diagnostics)

The integration includes 15+ built-in health checks that appear as "Repair Issues" in your Home Assistant **Settings → Repairs** dashboard.

*   **Stale Sensor**: Warning if your temperature sensor hasn't updated in >6 hours.
*   **Physics Railing**: Alert if the learning model has hit its limits.
*   **Zombie Schedule**: Error if your Schedule Helper has no events.
*   **Forecast Missing**: Warning if weather data is unavailable in Advanced Mode.

> [!TIP]
> Check the Repairs dashboard if the integration isn't behaving as expected!

---

## Diagnostics Download

Intelligent Preheating supports Home Assistant **Diagnostics**.

1.  Go to **Settings** → **Devices & Services**.
2.  Click on the 3 dots (**...**) next to the integration.
3.  Click **Download Diagnostics**.

This JSON file contains the internal state of the Physics Engine:
*   `mass_factor`: The learned heating speed.
*   `avg_error`: How accurate were the last predictions?
*   `next_arrival`: When does it think you come home?

## Debug Logging

If you need to report a bug, please enable debug logging:

```yaml
logger:
  default: warning
  logs:
    custom_components.preheat: debug
```

### "Analyze History" / Retroactive Bootstrap

The system **automatically scans** your Home Assistant Recorder history on first install. You should see learned sessions within 5 minutes of installation.

*   If it shows 0 sessions, check that your **Occupancy Sensor** has history in the Recorder (at least 7 days).
*   You can manually trigger a rescan using the **"Analyze History"** button.

---

## 🎛️ "Autonomous Engine Cockpit" Card Compatibility

If you are using the original "Autonomous Engine Cockpit" card template shared in the community forums (Post 5), note that it will crash with an `UndefinedError: 'dict object' has no attribute 'schedule'` error.

To resolve this:
*   Replace your Lovelace card template with the updated, defensive diagnostics template provided in the repository: [preheat_diagnostics_card.yaml](docs/diagnostics/preheat_diagnostics_card.yaml).
*   This updated card is provided **exclusively as a diagnostic/debugging tool** and not as an active feature.
*   **v2.11.1 Reality**: Optimal Stop and Shadow Savings metrics are fully active. Pattern Confidence and predicted arrival windows are sourced directly from the **House Arrival Hub** ("Preheat System" configuration entry).
