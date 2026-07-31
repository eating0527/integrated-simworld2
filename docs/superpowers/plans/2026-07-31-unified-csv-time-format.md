# Unified CSV Time Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make GPS CSV generation, GPS/noise pairing, and browser GPS replay use the noise CSV `+08:00` ISO 8601 timestamp format without breaking legacy `Z`, naive ISO, or epoch inputs.

**Architecture:** Keep backend timestamp normalization in `backend/app/iss_real.py` as the shared reader behavior. Update the AP3 GPS writer to preserve its configured timezone, keep the noise-derived GPS generator as a pass-through for exact synchronization, and make the frontend replay parser distinguish explicit timezone offsets from timezone-naive legacy timestamps.

**Tech Stack:** Python 3.12+, unittest, TypeScript, Vitest, Node Date parsing, CSV fixtures.

---

### Task 1: Lock the timestamp contract with failing tests

**Files:**
- Modify: `frontend/tests/gps-replay.test.mjs`
- Modify: `backend/tests/test_iss_unet_service.py`
- Modify: `tools/ap3_to_gps_csv.py` only after the tests fail

- [x] **Step 1: Add the frontend offset timestamp regression test**

Add a test case that passes `time_stamp,lat,lon,alt,alt_mode` rows containing `+08:00` timestamps to `parseGpsReplayCsv` and asserts every row is returned in chronological order.

- [x] **Step 2: Run the focused frontend test and verify RED**

Run:

```powershell
cd frontend
npm test -- --run tests/gps-replay.test.mjs
```

Expected: the new `+08:00` test fails because the current parser constructs invalid `+08:00Z` timestamps.

- [x] **Step 3: Add backend offset parsing coverage**

Extend the existing ISS-UNet backend tests to parse GPS and noise rows with `+08:00` and assert both timestamps normalize to the same UTC instant. Keep the existing `Z` and naive timestamp coverage unchanged.

- [x] **Step 4: Run the focused backend test and verify its result**

Run:

```powershell
cd backend
.venv\Scripts\python -m unittest tests.test_iss_unet_service
```

Expected: the new backend test passes because the backend reader already accepts explicit offsets; this confirms the backend contract before changing writers.

### Task 2: Emit canonical `+08:00` GPS timestamps

**Files:**
- Modify: `tools/ap3_to_gps_csv.py:191-194`
- Test: `backend/tests/test_iss_unet_service.py` or a focused writer test in the existing tools test location

- [x] **Step 1: Add a test for the GPS writer timestamp value**

Cover the writer’s timestamp construction with a timezone such as `timezone(timedelta(hours=8))` and assert the emitted timestamp ends with `+08:00`, has microsecond precision, and is the exact value passed to the sync payload.

- [x] **Step 2: Run the writer test and verify RED**

Run the focused test command created in Step 1. Expected: it fails because the current writer removes `tzinfo` and emits a naive timestamp.

- [x] **Step 3: Implement the minimal writer change**

Replace the naive conversion:

```python
timestamp = datetime.now(output_tz).replace(tzinfo=None).isoformat(timespec="milliseconds")
```

with:

```python
timestamp = datetime.now(output_tz).isoformat(timespec="microseconds")
```

Keep using this same `timestamp` for both `writer.writerow(...)` and `sync_client.send(...)`.

- [x] **Step 4: Run the writer test and verify GREEN**

Run the focused writer test and confirm it passes.

### Task 3: Make browser replay parse explicit offsets correctly

**Files:**
- Modify: `frontend/src/utils/gpsReplay.ts:59-64`
- Test: `frontend/tests/gps-replay.test.mjs`

- [x] **Step 1: Implement explicit-offset-aware parsing**

Keep numeric epoch parsing unchanged. For string timestamps, call `Date.parse(value)` when the value ends with `Z` or a numeric offset such as `+08:00`/`-0530`; append `Z` only when the ISO string has no timezone suffix.

- [x] **Step 2: Run the focused frontend tests and verify GREEN**

Run:

```powershell
cd frontend
npm test -- --run tests/gps-replay.test.mjs
```

Expected: offset, `Z`, naive ISO, sorting, and interval tests all pass.

- [x] **Step 3: Validate the real downloaded GPS CSV**

Run a Node/Vitest-level parser check against `C:\Users\benso\Downloads\gps_1.csv` and assert the returned point count is `193` and the first point has `altMode === 'relative'`.

### Task 4: Run affected verification and review the diff

**Files:**
- Review: `tools/ap3_to_gps_csv.py`
- Review: `frontend/src/utils/gpsReplay.ts`
- Review: `frontend/tests/gps-replay.test.mjs`
- Review: `backend/tests/test_iss_unet_service.py`
- Review: `docs/superpowers/specs/2026-07-31-unified-csv-time-format-design.md`

- [x] **Step 1: Run the full affected frontend suite**

```powershell
cd frontend
npm test -- --run
```

- [x] **Step 2: Run the full affected backend suite**

```powershell
cd backend
.venv\Scripts\python -m unittest discover -s tests
```

- [x] **Step 3: Review status and confirm unrelated changes remain untouched**

```powershell
cd D:\integrated-simworld2
git diff --check
git status --short
```

Confirm the pre-existing `frontend/package-lock.json` modification is not included in the timestamp change.
