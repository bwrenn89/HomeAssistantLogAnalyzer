# HA Log Analyzer (HACS Integration)

This repository is a Home Assistant custom integration (for HACS), not a standalone app.

It analyzes your Home Assistant log file using your existing Home Assistant Gemini conversation agent, tracks deduplicated issues, and exposes unresolved issue counts in Home Assistant.

## Features

- Configurable polling interval (minutes).
- Gemini-powered log analysis via Home Assistant conversation agent.
- Built-in issue tracking with:
  - `open` / `resolved` status
  - occurrence count
  - first seen / last seen timestamps
  - suggested fix from Gemini
- Duplicate prevention via stable issue fingerprinting.
- Home Assistant services to run analysis now, resolve, and reopen issues.

## Install with HACS

1. In HACS, add this repository as a **custom repository** of type **Integration**.
2. Install **HA Log Analyzer** from HACS.
3. Restart Home Assistant.
4. Go to **Settings -> Devices & Services -> Add Integration** and add **HA Log Analyzer**.

## Configuration

During config flow, provide:

- `Conversation agent ID` (helper included: available IDs are auto-discovered and shown during setup/options)
- `Log source`:
  - `system_log` (recommended): reads Home Assistant's internal System Log records (no URL/token needed)
  - `ha_api`: fetches logs from `/api/error_log`
  - `file`: reads local file path
- `Home Assistant URL` + `Long-lived access token` (only required for `ha_api`)
- `Log file path` (used only for `file` source, default `/config/home-assistant.log`)
- `Poll interval (minutes)`
- `Max characters sent to agent` (keep this small; default is optimized to avoid Gemini "text_query too long" errors)

You can change these later in **Integration Options**.

## Entities

- Sensor: `sensor.ha_log_analyzer_unresolved_issues`
  - state: unresolved (`open`) issue count
  - attributes include full issue list, last run, and last error

## Services

- `ha_log_analyzer.run_analysis`
  - Runs analysis immediately.
- `ha_log_analyzer.resolve_issue`
  - Field: `fingerprint`
- `ha_log_analyzer.reopen_issue`
  - Field: `fingerprint`

You can get fingerprints from the sensor attributes (`issues` list).

## Deduplication

Each Gemini issue is fingerprinted using normalized title + signature hint + description prefix.

- Existing fingerprint: issue is updated and `occurrences` is incremented.
- New fingerprint: new issue is created.

## Notes

- This integration reads a local log file path from inside Home Assistant.
- For Home Assistant OS in VirtualBox, `/config/home-assistant.log` is usually correct.
- This integration does not call Gemini directly; it uses Home Assistant's `conversation.process` service with your configured agent.
- If your HA instance does not expose a local log file in File Editor, use `system_log` (or `ha_api`) log source.
