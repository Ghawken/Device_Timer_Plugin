# Device Timer Plugin

Device Timer tracks how long a selected Indigo device has been ON across multiple rolling windows, and also provides day-based totals and counts of ON-events. It exposes both numeric minute totals and human-friendly text strings for easy use in Control Pages and triggers.

## What it does

- Tracks ON time for a target device across rolling windows (24h → 3 weeks).
- Tracks ON time for Today (midnight → now) and Yesterday (previous midnight → midnight).
- Counts OFF→ON transitions for Today and Yesterday.
- Publishes human-friendly text for all windows and day totals (for Control Pages).
- Persists displayed values across plugin restarts by reading current device states at startup and continuing from there.
- Logs midnight rollovers with yesterday’s final totals and counts.

## Features

- Rolling windows: 24h, 48h, 72h, 96h, 5d, 6d, 1w, 2w, 3w
- Day totals: Today and Yesterday
- ON-event counts: Today and Yesterday
- Text variants for all time windows and day totals
- 15 second refresh cadence
- Prunes history older than the longest window (3 weeks)

## Installation

1. Download or clone this plugin repository.
2. Double-click the devicetimer.indigoPlugin bundle to install 
3. Enable the plugin in Indigo.

## Creating a Device Timer

1. In Indigo, create a new device.
2. Type: Device Timer (custom device from this plugin).
3. Configure:
   - Device to track: choose the target device whose ON time you want to measure.
4. Save the device.

The device’s default display state is timeon_today_text (readable “X hours and Y mins”).

## States exposed

All numeric time values are reported in minutes with 1 decimal place.

- Rolling ON time (minutes, numeric):
  - timeon_24hours
  - timeon_48hours
  - timeon_72hours
  - timeon_96hours
  - timeon_5days
  - timeon_6days
  - timeon_1week
  - timeon_2weeks
  - timeon_3weeks
- Rolling ON time (text, human-friendly):
  - timeon_24hours_text
  - timeon_48hours_text
  - timeon_72hours_text
  - timeon_96hours_text
  - timeon_5days_text
  - timeon_6days_text
  - timeon_1week_text
  - timeon_2weeks_text
  - timeon_3weeks_text
- Day-bounded ON time (minutes, numeric):
  - timeon_today
  - timeon_yesterday
- Day-bounded ON time (text, human-friendly):
  - timeon_today_text
  - timeon_yesterday_text
- ON-event counts (OFF→ON transitions):
  - oncount_today
  - oncount_yesterday
- Target metadata:
  - target_device_id
  - target_device_name
  - target_on_state

Tip: Use the “Control Page Label” names from Devices.xml to drop these onto Control Pages, or use the text variants directly.

## How values are calculated

- The plugin maintains ON/OFF intervals in memory and recomputes totals every 15 seconds.
- Rolling windows sum overlap with [now - window, now] and are reported in minutes (1 decimal place).
- Today = overlap with [local midnight today, now].
- Yesterday = overlap with [local midnight yesterday, local midnight today].
- ON-event counts increment when the target device transitions from OFF to ON.

Retention:
- Old intervals are pruned beyond the longest window (3 weeks) to bound memory use.

## Midnight rollover and restart behavior

Midnight rollover:
- At local midnight:
  - The plugin logs a summary line for each timer with yesterday’s final totals and ON-event counts.
  - Yesterday is “locked” to that final value for the new day so it remains constant until the next midnight.
  - Today resets to 0.0 minutes and 0 ON events (and begins accumulating again).

Restart:
- On startup, the plugin reads the current device states for:
  - Rolling windows (timeon_* windows)
  - Day totals (timeon_today, timeon_yesterday)
  - ON-event counts (oncount_today, oncount_yesterday)
- It uses those as baselines and continues accumulating from there so values do not visibly reset after a restart.
- Notes:
  - Rolling windows will continue from their displayed values. Because the plugin can’t reconstruct pre-restart interval edges, decay for rolling windows across a restart won’t resume until new time accumulates (this is expected and keeps the display stable).
  - Today/Yesterday and their counts continue from the current device states read on startup.

## Using in Control Pages and Triggers

- Control Pages:
  - Use the “text” states (e.g., timeon_today_text or timeon_24hours_text) for a readable “X hours and Y mins” format.
  - Use the numeric minute states for graphs or numeric displays with formatting.
- Triggers and Conditions:
  - Create “Device State Changed” triggers on any of the states above.
  - Example: Notify if timeon_24hours exceeds a threshold (minutes) or if oncount_today reaches a certain number.

## Logging

- Plugin menu: Preferences allow setting Event Log and File Log levels and toggling debug.
- Midnight rollover logging:
  - One summary line per timer showing final Yesterday minutes and ON-event count.
- The plugin also updates target metadata and interval openings at debug level.

## Known limitations

- Rolling-window accuracy across restarts:
  - Windows continue from the last displayed value; decay (roll-off) across a restart only resumes as new time accumulates since interval edges aren’t persisted.
- Day totals and counts persist by reading current device state values at startup. If external edits to those states occur, the plugin will treat them as the new baseline.

## Tips

- Thresholds: Remember numeric states are minutes. For 2 hours, use 120.0.
- For compact Control Page displays use the text states; for precise numeric comparisons use the minute states.

## Support

Open an issue in the repository with details and any relevant Event Log snippets.