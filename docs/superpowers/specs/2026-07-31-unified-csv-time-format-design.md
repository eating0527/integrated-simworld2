# Unified GPS/Noise/Replay CSV Time Format

## Goal

Use the existing `noise.csv` timestamp format as the canonical format for GPS CSV output, noise/GPS pairing, and browser GPS replay:

```text
YYYY-MM-DDTHH:mm:ss.ssssss+08:00
```

The system must preserve the timezone offset instead of emitting a naive local timestamp. Readers remain backward-compatible with UTC `Z`, offset timestamps, timezone-naive ISO timestamps, and epoch timestamps where already supported.

## Current problem

`tools/ap3_to_gps_csv.py` creates a local timestamp and removes its timezone before writing `gps.csv`. The browser parser in `frontend/src/utils/gpsReplay.ts` appends `Z` to every timestamp that does not already end in `Z`. A valid offset timestamp such as `2026-07-31T15:54:32.481+08:00` therefore becomes the invalid `2026-07-31T15:54:32.481+08:00Z`, causing every replay row to be discarded.

## Design

1. GPS writer
   - Keep the configured output timezone on the `datetime` value.
   - Emit `datetime.now(output_tz).isoformat(timespec="microseconds")`, producing an explicit offset such as `+08:00`.
   - Send the exact same string to the GPS sync API and write it to the local GPS CSV.

2. GPS generated from noise
   - Continue copying `time_stamp` values from `noise.csv` unchanged so generated GPS rows are exactly time-aligned.

3. Browser replay parser
   - Parse timestamps with an explicit `Z` or numeric offset directly.
   - Append `Z` only for timezone-naive ISO timestamps, preserving compatibility with existing legacy CSV files.
   - Keep numeric epoch parsing unchanged.

4. Backend readers and payloads
   - Keep the existing backend ISO parser, which already normalizes offset and `Z` timestamps to UTC for comparison.
   - Add regression coverage for both GPS and noise parsing with `+08:00`, plus the existing `Z` behavior.

## Non-goals

- Do not change the noise value filter (`< -1 dB`).
- Do not change GPS/noise matching tolerance or scene coordinate filtering.
- Do not convert stored CSV values to UTC `Z`; canonical output remains the local `+08:00` representation used by `noise.csv`.

## Verification

- Frontend parser returns all rows from `gps_1.csv` with `+08:00` timestamps.
- Frontend parser still accepts `Z` and timezone-naive legacy timestamps.
- Backend parses offset timestamps consistently for GPS and noise.
- GPS writer output includes `+08:00` and uses the same value for CSV and sync payload.
- Existing frontend and backend affected tests pass.
