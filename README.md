# ha-coros

A [Home Assistant](https://www.home-assistant.io/) integration for [Coros](https://www.coros.com/) watches - HRV, resting heart rate, training load, VO2max, stamina, and sleep stages as sensors.

Not affiliated with or endorsed by Coros. Uses Coros's unofficial API (the same one their mobile app and Training Hub web app use), not an official partner API.

## Install

Not yet in the HACS default store (see [Roadmap](#roadmap)) - add it as a custom repository for now:

1. HACS → **⋮** → **Custom repositories**
2. Repository: `https://github.com/KoenradusXLVIII/ha-coros`, Type: **Integration**
3. Install **Coros**, restart Home Assistant
4. **Settings → Devices & Services → Add Integration → Coros**, sign in with your Coros account email/password and pick your region (EU/US/Asia)

Your password is used once during setup to obtain a session token; only that token is stored, never the password.

## Sensors

One device per Coros account:

| Sensor | Source |
|---|---|
| HRV | Nightly average RMSSD |
| Resting heart rate | |
| Training load | |
| VO2 max | |
| Stamina level | |
| Sleep duration | |
| Deep / Light / REM / Awake sleep | Sleep stage minutes |

Data refreshes every 30 minutes.

## Credits

This integration's authentication and API-fetching layer
(`custom_components/coros/api.py`, `models.py`) is adapted from
**[cygnusb/coros-mcp](https://github.com/cygnusb/coros-mcp)** (MIT
licensed) - an MCP server for AI assistants that reverse-engineered
Coros's unofficial web + mobile APIs, including the mobile API's
AES-128-CBC login scheme (key pulled from `libencrypt-lib.so` in the
Coros Android APK). That reverse-engineering work is the hard part this
integration builds on; full credit belongs there. This repo adapts it
into Home Assistant's config flow / coordinator / entity model, and drops
what a sensor integration doesn't need (the original's SQLite cache,
keyring-based token storage, and workout/schedule-management endpoints).

See [`LICENSE`](LICENSE) for the full MIT notice, including the original
project's copyright line.

## Roadmap

- [ ] Some real-world runtime before submitting to the HACS default store
- [ ] Split polling cadence (live vs. history) like other watch-brand integrations do
- [ ] Activity list / calendar entity for past workouts

## Disclaimer

Uses Coros's unofficial API. Coros can change or break it at any time
without notice - this integration may stop working until updated to match.
