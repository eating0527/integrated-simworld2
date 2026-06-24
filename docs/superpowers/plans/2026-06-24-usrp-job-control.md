# USRP Job Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add frontend-controlled, independently testable UAV GPS and Raspberry Pi USRP capture jobs with optional Bind coordination, offline status recovery, and verified CSV finalization.

**Architecture:** Add one backend capture coordinator that persists mission state under `incoming/<mission_id>/capture.json`, owns the local AP3 GPS subprocess, and delegates remote USRP lifecycle operations to the existing SSH control module. Raspberry Pi remains autonomous through systemd and a mission environment/state file; frontend polls one capture status API and renders UAV and USRP connection, service, and file states independently.

**Tech Stack:** FastAPI, Pydantic, Python subprocess/JSON/pathlib, Paramiko SSH, systemd/bash, React 19, TypeScript, Vitest, Testing Library.

---

## File Structure

- Create `backend/app/capture_jobs.py`
  - Capture state types, atomic JSON persistence, AP3 process ownership, Bind orchestration, status recovery, and idempotent stop logic.
- Create `backend/tests/test_capture_jobs.py`
  - Unit tests for Bind validation, independent starts, partial failure, offline recovery, finalization, and idempotency.
- Modify `backend/app/usrp_ctl.py`
  - Replace persistent SSH session semantics with short commands and add mission-aware remote start/status/stop functions.
- Modify `backend/app/main.py`
  - Add `/api/capture/*` endpoints and route Noise upload acknowledgements into the capture coordinator.
- Modify `backend/tests/test_usrp_sampling_control.py`
  - Preserve legacy API compatibility while adapting expectations to short SSH sessions.
- Modify `tools/ap3_to_gps_csv.py`
  - Add a bounded readiness probe and signal-safe shutdown output.
- Modify `tools/pi_radio_stack.sh`
  - Read mission environment, write remote `mission.json`, finalize children on SIGTERM, and trigger one upload attempt after finalization.
- Modify `tools/upload_noise_csv.py`
  - Send file size and SHA-256 metadata used by backend acknowledgement.
- Modify `tools/watch_and_upload_noise.py`
  - Retry finalized pending files without requiring another file modification.
- Modify `tools/pi_radio_stack.service.example`
  - Document `EnvironmentFile=/run/simworld/usrp.env` and mission state paths.
- Modify `start.ps1`
  - Stop auto-starting the GPS CSV writer by default; retain explicit `-GpsCsv` legacy startup.
- Modify `frontend/src/components/ui/USRPTelemetry.tsx`
  - Replace SSH-session controls with Bind, UAV, USRP, Stop All, and three-axis status rendering.
- Modify `frontend/src/components/ui/USRPTelemetry.test.tsx`
  - Verify independent and bound controls, disabled transitions, partial failure, presumed-running, and upload-pending states.
- Modify `README.md`
  - Document new frontend workflow, Raspberry Pi unit requirements, and legacy CLI behavior.

### Task 1: Capture State Model and Atomic Persistence

**Files:**
- Create: `backend/app/capture_jobs.py`
- Create: `backend/tests/test_capture_jobs.py`

- [ ] **Step 1: Write failing persistence and aggregate-state tests**

```python
def test_store_round_trips_capture_state(tmp_path):
    store = CaptureStore(tmp_path)
    state = store.create(bind=False, selected_usrp_mode="test", target="uav")
    loaded = store.load(state.mission_id)
    assert loaded == state
    assert (tmp_path / state.mission_id / "capture.json").exists()


def test_partial_failure_does_not_stop_other_child(tmp_path):
    store = CaptureStore(tmp_path)
    state = store.create(bind=True, selected_usrp_mode="usrp", target="bind")
    state.uav.service = "running"
    state.usrp.service = "failed"
    store.save(state)
    assert store.load(state.mission_id).overall_state == "partial_failed"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
backend\.venv\Scripts\python.exe -m unittest backend.tests.test_capture_jobs -v
```

Expected: FAIL because `app.capture_jobs` does not exist.

- [ ] **Step 3: Implement focused state types and store**

Implement:

```python
ConnectionState = Literal["ready", "offline", "unknown"]
ServiceState = Literal[
    "idle", "starting", "running", "presumed_running",
    "stopping", "stopped", "failed",
]
FileState = Literal[
    "none", "recording", "finalizing", "ready",
    "upload_pending", "uploaded", "failed",
]

class ChildState(BaseModel):
    connection: ConnectionState = "unknown"
    service: ServiceState = "idle"
    file: FileState = "none"
    error: str = ""
    path: str = ""

class CaptureState(BaseModel):
    mission_id: str
    bind: bool
    selected_usrp_mode: Literal["test", "usrp"] = "test"
    overall_state: Literal[
        "ready", "starting", "running", "partial_failed",
        "finalizing", "completed", "failed",
    ] = "ready"
    uav: ChildState = Field(default_factory=ChildState)
    usrp: ChildState = Field(default_factory=ChildState)
```

`CaptureStore.save()` must write `<capture.json>.tmp`, flush it, then use
`Path.replace()` so interrupted writes never leave partial JSON. Aggregate
state must be recalculated in one helper before every save.

- [ ] **Step 4: Run tests and verify pass**

Run the Task 1 command. Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/capture_jobs.py backend/tests/test_capture_jobs.py
git commit -m "feat(capture): add persisted job state"
```

### Task 2: Independent AP3 GPS Job Control

**Files:**
- Modify: `backend/app/capture_jobs.py`
- Modify: `backend/tests/test_capture_jobs.py`
- Modify: `tools/ap3_to_gps_csv.py`
- Modify: `start.ps1`

- [ ] **Step 1: Write failing AP3 lifecycle tests**

Cover:

```python
def test_uav_start_works_without_raspi(tmp_path):
    coordinator = coordinator_with_fake_process(tmp_path)
    state = coordinator.start_uav()
    assert state.uav.service == "running"
    assert state.uav.file == "recording"
    assert state.usrp.service == "idle"


def test_uav_stop_waits_for_process_and_marks_file_ready(tmp_path):
    coordinator = coordinator_with_fake_process(tmp_path, writes_gps=True)
    state = coordinator.start_uav()
    stopped = coordinator.stop_uav(state.mission_id)
    assert stopped.uav.service == "stopped"
    assert stopped.uav.file == "ready"


def test_second_uav_job_is_rejected(tmp_path):
    coordinator = coordinator_with_fake_process(tmp_path)
    coordinator.start_uav()
    with self.assertRaises(CaptureConflictError):
        coordinator.start_uav()
```

Use `unittest` and `unittest.mock` in the actual file to match repository
conventions; the behavioral assertions above are mandatory.

- [ ] **Step 2: Run targeted tests and verify failure**

Run:

```powershell
backend\.venv\Scripts\python.exe -m unittest backend.tests.test_capture_jobs.IndependentUavTests -v
```

Expected: FAIL because coordinator lifecycle methods do not exist.

- [ ] **Step 3: Implement AP3 process ownership**

`CaptureCoordinator.start_uav()` must:

1. reject an active UAV job;
2. call `ap3_to_gps_csv.py --check` before creating a running mission;
3. create `incoming/<mission_id>/gps.csv`;
4. launch the writer through injected `popen_factory`;
5. save PID, `running`, and `recording`.

`stop_uav()` must terminate, wait up to five seconds, kill only after timeout,
verify `gps.csv` has a header, then mark `stopped` and `ready`. Repeated stop
returns the existing terminal state.

Add to `ap3_to_gps_csv.py`:

```python
parser.add_argument("--check", action="store_true")
```

In check mode, verify an authorized ADB device and establish forwarding, then
exit `0` without opening the CSV loop.

Change `start.ps1`:

```powershell
$enableGpsCsv = $GpsCsv -and -not $NoGpsCsv
```

This keeps explicit legacy startup but makes frontend control the default.

- [ ] **Step 4: Run tests**

Run Task 2 tests and:

```powershell
backend\.venv\Scripts\python.exe .\tools\ap3_to_gps_csv.py --help
```

Expected: tests PASS and help includes `--check`.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/capture_jobs.py backend/tests/test_capture_jobs.py tools/ap3_to_gps_csv.py start.ps1
git commit -m "feat(capture): control AP3 GPS jobs"
```

### Task 3: Mission-Aware USRP SSH Control

**Files:**
- Modify: `backend/app/usrp_ctl.py`
- Modify: `backend/tests/test_usrp_sampling_control.py`
- Modify: `backend/tests/test_capture_jobs.py`

- [ ] **Step 1: Write failing short-session and recovery tests**

Required cases:

```python
def test_status_disconnect_reports_presumed_running():
    # Last persisted state is running; SSH status raises timeout.
    assert recovered.usrp.connection == "offline"
    assert recovered.usrp.service == "presumed_running"


def test_remote_start_writes_mission_env_before_systemctl():
    start_remote_job("usrp", mission)
    assert commands == [
        "install -d ...",
        "write /run/simworld/usrp.env ...",
        "systemctl start drone",
    ]


def test_remote_stop_is_idempotent():
    first = stop_remote_job("usrp", mission_id)
    second = stop_remote_job("usrp", mission_id)
    assert second["mission_id"] == first["mission_id"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
backend\.venv\Scripts\python.exe -m unittest backend.tests.test_usrp_sampling_control backend.tests.test_capture_jobs -v
```

Expected: FAIL on missing mission-aware methods.

- [ ] **Step 3: Replace persistent SSH ownership**

Remove `_CONNECTED_CLIENT`, `_connected_client()`, explicit connect/disconnect
state, and persistent session assumptions. Every `_run_remote()` call creates
and closes one Paramiko client.

Add:

```python
def start_capture_job(mode: ServiceMode, mission: RemoteMission) -> dict: ...
def get_capture_job(mode: ServiceMode, mission_id: str) -> dict: ...
def stop_capture_job(mode: ServiceMode, mission_id: str) -> dict: ...
```

`RemoteMission` includes mission id, API URL, scene, map type, remote work
directory, CSV path, and optional devices file. Values written to the remote
environment file must be shell-quoted with `shlex.quote`.

Remote status must combine:

- `systemctl is-active <unit>`
- `cat <remote-state-dir>/<mission_id>/mission.json`

Legacy `get_drone_status()`, `start_drone_service()`, and
`stop_drone_service()` remain as wrappers during migration.

- [ ] **Step 4: Run tests**

Run Task 3 command. Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/usrp_ctl.py backend/tests/test_usrp_sampling_control.py backend/tests/test_capture_jobs.py
git commit -m "refactor(usrp): use mission-aware SSH commands"
```

### Task 4: Bind Orchestration and Capture API

**Files:**
- Modify: `backend/app/capture_jobs.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_capture_jobs.py`

- [ ] **Step 1: Write failing API tests**

Required cases:

```python
def test_bind_start_requires_both_dependencies():
    response = client.post("/api/capture/bind/start", json={"usrp_mode": "test"})
    assert response.status_code == 409


def test_bind_start_shares_mission_id():
    response = client.post("/api/capture/bind/start", json={"usrp_mode": "usrp"})
    body = response.json()
    assert body["uav"]["mission_id"] == body["mission_id"]
    assert body["usrp"]["mission_id"] == body["mission_id"]


def test_bind_child_failure_preserves_other_child():
    # USRP start fails after UAV starts.
    assert body["overall_state"] == "partial_failed"
    assert body["uav"]["service"] == "running"


def test_stop_all_waits_for_both_finalizers():
    response = client.post(f"/api/capture/bind/stop?mission_id={mission_id}")
    assert response.json()["overall_state"] == "completed"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
backend\.venv\Scripts\python.exe -m unittest backend.tests.test_capture_jobs.CaptureApiTests -v
```

Expected: FAIL with route not found.

- [ ] **Step 3: Implement coordinator API**

Add Pydantic request:

```python
class CaptureStartRequest(BaseModel):
    usrp_mode: Literal["test", "usrp"] = "test"
    scene: str = "NTPU"
    map_type: Literal["sinr", "iss", "tss", "cfar"] = "iss"
```

Add routes:

```text
GET  /api/capture/status
POST /api/capture/uav/start
POST /api/capture/uav/stop
POST /api/capture/usrp/start
POST /api/capture/usrp/stop
POST /api/capture/bind/start
POST /api/capture/bind/stop
```

Map conflicts to HTTP 409, unavailable dependencies to 503, and invalid
mission IDs to 404. `bind/start` preflights both dependencies before launching
either child. If launch fails after one child starts, preserve that child and
return `partial_failed`.

- [ ] **Step 4: Run backend tests**

Run:

```powershell
backend\.venv\Scripts\python.exe -m unittest backend.tests.test_capture_jobs backend.tests.test_usrp_sampling_control -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/capture_jobs.py backend/app/main.py backend/tests/test_capture_jobs.py
git commit -m "feat(api): add bound capture controls"
```

### Task 5: Verified Noise Upload and Retry Contract

**Files:**
- Modify: `backend/app/capture_jobs.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_capture_jobs.py`
- Modify: `tools/upload_noise_csv.py`
- Modify: `tools/watch_and_upload_noise.py`

- [ ] **Step 1: Write failing acknowledgement tests**

Cover:

```python
def test_noise_upload_requires_matching_size_and_hash():
    response = upload_noise(mission_id, data, declared_size=1, declared_sha256="bad")
    assert response.status_code == 422


def test_valid_noise_upload_completes_usrp_child():
    response = upload_noise(
        mission_id,
        data,
        declared_size=len(data),
        declared_sha256=sha256(data).hexdigest(),
    )
    assert response.json()["capture"]["usrp"]["file"] == "uploaded"


def test_failed_upload_remains_pending():
    state = coordinator.stop_usrp(mission_id)
    assert state.usrp.file == "upload_pending"
    assert state.usrp.service == "stopped"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
backend\.venv\Scripts\python.exe -m unittest backend.tests.test_capture_jobs.NoiseUploadTests -v
```

Expected: FAIL because upload verification is absent.

- [ ] **Step 3: Implement one verified upload path**

Extend the existing Noise endpoint with required fields:

```text
mission_id
noise_size
noise_sha256
noise_file
```

Read bytes once, verify size and SHA-256, atomically write
`incoming/<mission_id>/noise.csv`, then call
`capture_coordinator.ack_noise_upload(...)`.

`upload_noise_csv.py` calculates metadata:

```python
data = noise_path.read_bytes()
fields["noise_size"] = str(len(data))
fields["noise_sha256"] = hashlib.sha256(data).hexdigest()
```

`watch_and_upload_noise.py` must retry whenever the saved signature is not
acknowledged; failed calls do not update the state file.

- [ ] **Step 4: Run tests and CLI checks**

Run:

```powershell
backend\.venv\Scripts\python.exe -m unittest backend.tests.test_capture_jobs.NoiseUploadTests -v
backend\.venv\Scripts\python.exe .\tools\upload_noise_csv.py --help
```

Expected: PASS and CLI help remains valid.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/capture_jobs.py backend/app/main.py backend/tests/test_capture_jobs.py tools/upload_noise_csv.py tools/watch_and_upload_noise.py
git commit -m "feat(usrp): verify noise CSV delivery"
```

### Task 6: Raspberry Pi Finalization Contract

**Files:**
- Modify: `tools/pi_radio_stack.sh`
- Modify: `tools/pi_radio_stack.service.example`
- Create: `tools/test_pi_radio_stack.py`

- [ ] **Step 1: Write a failing shell-contract test**

The Python test reads the shell and service files and asserts they include:

```python
assert "MISSION_ID" in stack
assert "MISSION_STATE_DIR" in stack
assert "finalizing" in stack
assert "upload_pending" in stack
assert "EnvironmentFile=/run/simworld/usrp.env" in unit
```

It also runs the stack with fake child commands and verifies SIGTERM writes a
terminal `mission.json` before invoking the fake uploader.

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
backend\.venv\Scripts\python.exe .\tools\test_pi_radio_stack.py
```

Expected: FAIL because mission finalization is absent.

- [ ] **Step 3: Implement signal-safe finalization**

The stack script must:

- require `MISSION_ID`;
- create `$MISSION_STATE_DIR/$MISSION_ID`;
- atomically write `mission.json`;
- update states `starting`, `running`, `finalizing`, `upload_pending`, and
  `uploaded`/`failed`;
- on EXIT/INT/TERM, terminate children, wait for them, verify Noise CSV, then
  run the uploader once;
- never restart capture after reboot merely because an interrupted mission
  exists.

The service example must include:

```ini
EnvironmentFile=-/run/simworld/usrp.env
KillMode=control-group
TimeoutStopSec=30
```

- [ ] **Step 4: Run contract test**

Run Task 6 test. Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add tools/pi_radio_stack.sh tools/pi_radio_stack.service.example tools/test_pi_radio_stack.py
git commit -m "feat(usrp): finalize remote capture jobs"
```

### Task 7: Frontend Bind and Dual Status Controls

**Files:**
- Modify: `frontend/src/components/ui/USRPTelemetry.tsx`
- Modify: `frontend/src/components/ui/USRPTelemetry.test.tsx`

- [ ] **Step 1: Write failing UI tests**

Required user-visible assertions:

```typescript
expect(screen.getByRole('switch', { name: 'Bind services' }))
  .toHaveAttribute('aria-checked', 'false');
expect(screen.getByRole('button', { name: 'Start UAV' })).toBeEnabled();
expect(screen.getByRole('button', { name: 'Start USRP' })).toBeEnabled();
```

Additional tests:

- Bind OFF starts UAV without a RasPi-ready status.
- Bind OFF starts USRP without a UAV-ready status.
- Bind ON calls `/api/capture/bind/start` only when both are ready.
- Running either child disables the Bind switch.
- Running USRP disables Test／USRP mode switching.
- Offline last-known-running renders `Presumed running`.
- `upload_pending` renders `Pending upload`, not `Completed`.
- Bind ON exposes individual Stop and Stop All.

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
Set-Location frontend
npm test -- src/components/ui/USRPTelemetry.test.tsx
```

Expected: FAIL because capture controls do not exist.

- [ ] **Step 3: Implement minimal polling UI**

Use one `CaptureStatus` type matching backend JSON. Poll:

```text
GET /api/capture/status
```

every two seconds while either child is active or finalizing; otherwise only
load on mount and after actions.

Render two sections:

```text
UAV / AP3 GPS
  Connection
  Service
  File

RasPi / USRP Noise
  Connection
  Service
  File
```

Bind uses a button with `role="switch"` and defaults to false in component
state. Action mapping:

```text
Bind OFF Start UAV  -> /api/capture/uav/start
Bind OFF Start USRP -> /api/capture/usrp/start
Bind ON Start       -> /api/capture/bind/start
Stop UAV            -> /api/capture/uav/stop
Stop USRP           -> /api/capture/usrp/stop
Stop All            -> /api/capture/bind/stop
```

Keep the existing spectrum metric display below capture controls.

- [ ] **Step 4: Run focused UI tests**

Run Task 7 command. Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/ui/USRPTelemetry.tsx frontend/src/components/ui/USRPTelemetry.test.tsx
git commit -m "feat(ui): add bound capture controls"
```

### Task 8: Documentation, Compatibility, and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_usrp_sampling_control.py`

- [ ] **Step 1: Add compatibility tests**

Verify legacy `/api/usrp/sampling/status`, `/start`, and `/stop` remain callable
and delegate to the shared USRP implementation. Mark `/connect`, `/disconnect`,
and `/messages` responses with:

```json
{"deprecated": true}
```

No legacy route may own separate SSH session state.

- [ ] **Step 2: Run compatibility tests and verify expected failures**

Run:

```powershell
backend\.venv\Scripts\python.exe -m unittest backend.tests.test_usrp_sampling_control -v
```

Expected: FAIL until deprecation fields and delegation are implemented.

- [ ] **Step 3: Complete compatibility and README**

README must document:

- Bind OFF independent testing;
- Bind ON readiness requirement and shared mission ID;
- separate UAV and USRP status meanings;
- `presumed_running`;
- Stop completion and `upload_pending`;
- Raspberry Pi service installation/update;
- explicit `start.ps1 -GpsCsv` as legacy auto-start behavior.

- [ ] **Step 4: Run full verification**

Run:

```powershell
backend\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
backend\.venv\Scripts\python.exe .\tools\test_pi_radio_stack.py
Set-Location frontend
npm test
npm run build
```

Expected: all backend tests PASS, shell contract PASS, all frontend tests PASS,
and production build exits `0`.

- [ ] **Step 5: Inspect final diff**

Run:

```powershell
Set-Location ..
git diff --check
git status --short
```

Expected: no whitespace errors; only intended files modified.

- [ ] **Step 6: Commit**

```powershell
git add README.md backend/app/main.py backend/tests/test_usrp_sampling_control.py
git commit -m "docs(usrp): document capture workflow"
```
