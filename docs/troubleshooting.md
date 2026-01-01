# 🔧 Troubleshooting

## Common Issues

### "The system never turns on!"

1.  **Check Occupancy**: Is your occupancy sensor currently `OFF`? The system only pre-heats if it thinks the room is currently *empty* but *will be occupied soon*. If you are already there (`ON`), it assumes the normal thermostat is running and does nothing.
2.  **Check Target Temp**: Is the target setpoint higher than the current temperature?
3.  **Check "Don't start if warm"**: In the settings, there is an option "Don't preheat if room > 20°C".

### "It starts too late / The room is cold."
*   **Solution**: Increase the **initial gain** in the configuration options manually.
*   **Solution**: Add a **Buffer** of 15-30 minutes in the settings.
*   The system *will* learn from this mistake. If it misses the target, the next day's prediction will be more aggressive.

### "It starts way too early!"
*   Check your **Heating Profile**. Did you select "Floor Heating" for a radiator? Floor heating profiles assume massive delays (3+ hours).
*   Check the **Outdoor Temperature**. If `weather_entity` is missing or reporting wrong values (e.g., -20°C), the system might panic and over-heat.

---

## Diagnostics

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

### Why does "Analyze History" show 0 sessions?
*   The "Recorder" feature (v2.8.0) starts fresh. It does not import old data from Home Assistant's general history to avoid corruption.
*   It takes **7 days** to have at least one data point for every weekday.
*   Wait a few days, and the numbers will grow automatically.

