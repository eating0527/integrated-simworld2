from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, field_validator

from app.gps_csv import (
    GPS_CSV_COLUMNS,
    GpsCsvSchemaError,
    ensure_gps_csv,
    resume_window_expired,
    validate_gps_csv,
)
from app.device_health import Ap3Health, DeviceHealthMonitor, RaspiHealth


ConnectionState = Literal["ready", "offline", "unknown"]
ServiceState = Literal[
    "idle",
    "starting",
    "running",
    "presumed_running",
    "stopping",
    "stopped",
    "failed",
]
FileState = Literal[
    "none",
    "recording",
    "finalizing",
    "ready",
    "upload_pending",
    "uploaded",
    "failed",
]
OverallState = Literal[
    "ready",
    "starting",
    "running",
    "degraded",
    "stopping",
    "finalizing",
    "completed",
    "completed_with_warning",
    "failed",
]
CapturePhase = Literal[
    "idle",
    "preflight",
    "connecting",
    "configuring",
    "starting_service",
    "recording",
    "stopping",
    "stopping_service",
    "finalizing_file",
    "upload_pending",
    "uploading",
    "completed",
    "stopped",
    "reconciling",
    "stop_failed",
    "resume_timeout",
    "failed",
    "unknown",
]
CAPTURE_PHASES = frozenset({
    "idle", "preflight", "connecting", "configuring", "starting_service",
    "recording", "stopping", "stopping_service", "finalizing_file",
    "upload_pending", "uploading", "completed", "stopped", "reconciling",
    "stop_failed", "resume_timeout", "failed", "unknown",
})
CaptureTarget = Literal["uav", "usrp", "bind"]
UsrpMode = Literal["test", "usrp"]

# A recorder process is only considered healthy while a valid GPS row keeps
# arriving.  The five-minute resume window is deliberately longer than the
# freshness window so a short AP3/forwarding outage can be reconciled without
# creating a second mission.
GPS_FRESHNESS_THRESHOLD_SECONDS = 10.0
AP3_RESUME_WINDOW_SECONDS = 300.0


class ChildState(BaseModel):
    mission_id: str = ""
    phase: CapturePhase = "idle"
    connection: ConnectionState = "unknown"
    service: ServiceState = "idle"
    file: FileState = "none"
    error: str = ""
    path: str = ""
    pid: int | None = None
    # AP3 runtime telemetry.  These fields are persisted with capture.json so
    # a status poll or backend restart cannot lose the resume decision boundary.
    last_sample_at: str | None = None
    disconnected_at: str | None = None
    resume_deadline_at: str | None = None

    @field_validator("phase", mode="before")
    @classmethod
    def normalize_phase(cls, value: object) -> str:
        if value is None:
            return "idle"
        return value if isinstance(value, str) and value in CAPTURE_PHASES else "unknown"


class CaptureState(BaseModel):
    mission_id: str
    target: CaptureTarget
    bind: bool
    selected_usrp_mode: UsrpMode = "test"
    overall_state: OverallState = "ready"
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    # Stop All is a consumed mission command.  Persisting the request time
    # prevents a page/backend restart from presenting the original command as
    # available again while either child is still being reconciled.
    stop_requested_at: str | None = None
    uav: ChildState = Field(default_factory=ChildState)
    usrp: ChildState = Field(default_factory=ChildState)

    @field_validator("overall_state", mode="before")
    @classmethod
    def normalize_legacy_overall_state(cls, value: object) -> object:
        return "degraded" if value == "partial_failed" else value


class CaptureError(RuntimeError):
    pass


class CaptureConflictError(CaptureError):
    pass


class CaptureUnavailableError(CaptureError):
    pass


class CapturePreflightError(CaptureUnavailableError):
    """Bound Start preflight failed for one or more devices.

    ``errors`` is intentionally keyed by the stable device identifiers used by
    Device Health (``ap3`` and ``raspi``), so API consumers can present every
    unavailable dependency without parsing one combined message.
    """

    def __init__(
        self,
        errors: dict[str, str],
        *,
        conflicts: dict[str, str] | None = None,
    ):
        self.errors = {
            str(device): str(message)
            for device, message in errors.items()
            if str(message).strip()
        }
        self.device_errors = self.errors
        self.conflicts = {
            str(device): str(message)
            for device, message in (conflicts or {}).items()
            if str(message).strip()
        }
        details = "; ".join(
            f"{device}: {message}"
            for device, message in self.errors.items()
        )
        super().__init__(f"Bound capture preflight failed: {details}")


class CaptureNotFoundError(CaptureError):
    pass


def uav_accepts_gps_sample(child: ChildState) -> bool:
    return not (
        child.service in {"stopping", "stopped", "failed"}
        or child.phase
        in {"stopping", "stopping_service", "finalizing_file", "stopped", "completed", "resume_timeout", "failed"}
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(value: object) -> datetime | None:
    """Parse recorder timestamps while accepting legacy naive CSV values."""

    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _mission_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"mission_{stamp}_{uuid.uuid4().hex[:6]}"


def _selected_children(state: CaptureState) -> list[ChildState]:
    if state.target == "uav":
        return [state.uav]
    if state.target == "usrp":
        return [state.usrp]
    return [state.uav, state.usrp]


_UNRESOLVED_PHASES = frozenset({
    "stopping",
    "stopping_service",
    "finalizing_file",
    "upload_pending",
    "uploading",
    "reconciling",
    "stop_failed",
})

_REMOTE_RUNNING_STATES = frozenset({"running", "recording"})
_REMOTE_FINALIZING_STATES = frozenset({"finalizing", "finalizing_file", "uploading"})
_REMOTE_STOPPED_STATES = frozenset({"stopped", "completed", "complete"})
_REMOTE_FAILED_STATES = frozenset({"failed", "error"})


def _child_unresolved(child: ChildState) -> bool:
    """Return whether a child still owns active or unfinished work."""

    return (
        child.service in {"starting", "running", "presumed_running", "stopping"}
        or child.file in {"finalizing", "upload_pending"}
        or child.phase in _UNRESOLVED_PHASES
    )


def _aggregate_state(state: CaptureState) -> OverallState:
    children = _selected_children(state)
    terminal = all(child.service in {"stopped", "failed"} for child in children)
    successful = [
        child.service == "stopped" and child.file in {"ready", "uploaded"}
        for child in children
    ]
    pending = any(child.file in {"finalizing", "upload_pending"} for child in children)
    uncertain = any(child.service == "presumed_running" for child in children)
    fault = any(
        child.service == "failed"
        or child.file == "failed"
        or child.connection == "offline"
        or child.phase in {"reconciling", "resume_timeout", "stop_failed"}
        for child in children
    )

    stop_intent = any(
        child.service == "stopping"
        or child.phase
        in {"stopping", "stopping_service", "stop_failed"}
        for child in children
    )

    if stop_intent:
        return "stopping"
    if pending:
        return "finalizing"
    if terminal:
        if all(successful):
            return "completed"
        if any(successful):
            return "completed_with_warning"
        return "failed"
    if fault or uncertain:
        return "degraded"
    if all(
        child.service == "running" and child.file == "recording"
        for child in children
    ):
        return "running"
    if any(child.service == "starting" for child in children):
        return "starting"
    if state.started_at is None and all(
        child.service == "idle" and child.file == "none"
        for child in children
    ):
        return "ready"
    return "degraded"


class CaptureStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        *,
        bind: bool,
        selected_usrp_mode: UsrpMode,
        target: CaptureTarget,
        mission_id: str | None = None,
    ) -> CaptureState:
        next_mission_id = mission_id or _mission_id()
        state = CaptureState(
            mission_id=next_mission_id,
            target=target,
            bind=bind,
            selected_usrp_mode=selected_usrp_mode,
            created_at=_now_iso(),
        )
        if target in {"uav", "bind"}:
            state.uav.mission_id = next_mission_id
        if target in {"usrp", "bind"}:
            state.usrp.mission_id = next_mission_id
        self.save(state)
        return state

    def path(self, mission_id: str) -> Path:
        return self.root / mission_id / "capture.json"

    def load(self, mission_id: str) -> CaptureState:
        path = self.path(mission_id)
        if not path.exists():
            raise CaptureNotFoundError(f"capture mission not found: {mission_id}")
        return CaptureState.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[CaptureState]:
        states: list[CaptureState] = []
        for path in self.root.glob("*/capture.json"):
            try:
                states.append(
                    CaptureState.model_validate_json(path.read_text(encoding="utf-8"))
                )
            except Exception:
                continue
        return sorted(states, key=lambda item: item.created_at)

    def save(self, state: CaptureState) -> CaptureState:
        state.overall_state = _aggregate_state(state)
        if (
            state.overall_state
            in {"completed", "completed_with_warning", "failed"}
            and state.finished_at is None
        ):
            state.finished_at = _now_iso()

        path = self.path(state.mission_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".json.tmp")
        payload = json.dumps(
            state.model_dump(),
            ensure_ascii=False,
            indent=2,
        )
        with temp_path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
        return state


class CaptureCoordinator:
    def __init__(
        self,
        store: CaptureStore,
        *,
        repo_root: Path,
        run_command=subprocess.run,
        popen_factory=subprocess.Popen,
        usrp_backend=None,
        health_monitor=None,
        gps_freshness_seconds: float = GPS_FRESHNESS_THRESHOLD_SECONDS,
        resume_window_seconds: float = AP3_RESUME_WINDOW_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ):
        self.store = store
        self.repo_root = Path(repo_root)
        self.run_command = run_command
        self.popen_factory = popen_factory
        if usrp_backend is None:
            from app import usrp_ctl

            usrp_backend = usrp_ctl
        self.usrp_backend = usrp_backend
        self._lock = threading.RLock()
        self._uav_processes: dict[str, subprocess.Popen] = {}
        self._health_mode: UsrpMode = "test"
        self.gps_freshness_seconds = max(0.0, float(gps_freshness_seconds))
        self.resume_window_seconds = max(0.0, float(resume_window_seconds))
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        if health_monitor is not None:
            self.health_monitor = health_monitor
        else:
            self.health_monitor = DeviceHealthMonitor(
                ap3=Ap3Health(probe=self._health_ap3_probe),
                raspi=RaspiHealth(probe=self._health_raspi_probe),
            )

    def _health_ap3_probe(self):
        self.preflight_uav()
        return True

    def _health_raspi_probe(self):
        probe = getattr(self.usrp_backend, "get_drone_health", None)
        if (
            not callable(probe)
            or getattr(probe, "__module__", "") == "unittest.mock"
        ):
            return {
                "state": "unknown",
                "error": "Raspberry Pi lightweight health probe is unavailable",
            }
        result = probe(self._health_mode)
        if not isinstance(result, dict):
            return {
                "state": "unknown",
                "error": "Raspberry Pi health result is invalid",
            }
        state = result.get("state")
        if state in {"offline", "unknown"} or result.get("stale"):
            return {
                "state": "unknown" if result.get("stale") else state,
                "error": result.get("error") or result.get("message") or "Raspberry Pi health is unavailable",
                "stale": bool(result.get("stale")),
            }
        if state == "ready" or result.get("service_state") in {"running", "stopped"}:
            return {"state": "ready", "message": "Raspberry Pi reachable"}
        return {"state": "unknown", "error": "Raspberry Pi health result is unknown"}

    def _active_uav(self) -> CaptureState | None:
        for state in reversed(self.store.list()):
            if state.target not in {"uav", "bind"}:
                continue
            if _child_unresolved(state.uav):
                return state
        return None

    def _active_usrp(self) -> CaptureState | None:
        for state in reversed(self.store.list()):
            if state.target not in {"usrp", "bind"}:
                continue
            if _child_unresolved(state.usrp):
                return state
        return None

    def _ap3_command(self, *extra: str) -> list[str]:
        script = self.repo_root / "tools" / "ap3_to_gps_csv.py"
        return [sys.executable, str(script), *extra]

    def preflight_uav(self) -> None:
        try:
            result = self.run_command(
                self._ap3_command("--check"),
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except subprocess.TimeoutExpired as exc:
            raise CaptureUnavailableError("AP3 readiness check timeout") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "AP3 is unavailable").strip()
            raise CaptureUnavailableError(detail)

    def preflight_usrp(self, mode: UsrpMode) -> None:
        probe = getattr(self.usrp_backend, "get_drone_health", None)
        try:
            if callable(probe) and getattr(probe, "__module__", "") != "unittest.mock":
                status = probe(mode)
            else:
                # Older adapters may not expose the lightweight probe yet. In
                # that case the status adapter remains the compatibility seam;
                # production usrp_ctl always provides get_drone_health.
                status = self.usrp_backend.get_drone_status(mode)
        except Exception as exc:
            raise CaptureUnavailableError(str(exc)) from exc
        if not isinstance(status, dict):
            raise CaptureUnavailableError("Raspberry Pi readiness result is invalid")
        if status.get("service_state") == "running":
            raise CaptureConflictError(f"{mode} capture service is already running")
        if status.get("success") is False:
            detail = status.get("message") or status.get("error") or "Raspberry Pi is unavailable"
            raise CaptureUnavailableError(str(detail))
        if status.get("raspi_connected") is False or status.get("session_connected") is False:
            detail = status.get("message") or status.get("error") or "Raspberry Pi is unavailable"
            raise CaptureUnavailableError(str(detail))
        service_state = status.get("service_state")
        if service_state not in {"stopped", "idle"}:
            detail = status.get("message") or status.get("error") or (
                f"Raspberry Pi service state is {service_state or 'unknown'}"
            )
            raise CaptureUnavailableError(str(detail))

    def _preflight_bind(self, mode: UsrpMode) -> None:
        """Run both Bound Start checks and report all failures together."""

        errors: dict[str, str] = {}
        conflicts: dict[str, str] = {}
        checks = (
            ("ap3", self.preflight_uav),
            ("raspi", lambda: self.preflight_usrp(mode)),
        )
        for device, check in checks:
            try:
                check()
            except CaptureConflictError as exc:
                message = str(exc) or f"{device} capture is already running"
                errors[device] = message
                conflicts[device] = message
            except Exception as exc:
                errors[device] = str(exc) or f"{device} preflight failed"
        if errors:
            raise CapturePreflightError(errors, conflicts=conflicts)

    def health_status(self, mode: UsrpMode = "test") -> dict[str, dict]:
        with self._lock:
            self._health_mode = mode
            return {
                name: result.as_dict()
                for name, result in self.health_monitor.poll(mode=mode).items()
            }

    def status_payload(self, mode: UsrpMode = "test") -> dict:
        with self._lock:
            state = self.status(mode)
            return {
                **state.model_dump(),
                "device_health": self.health_monitor.as_dict(),
            }

    def _launch_uav(self, state: CaptureState) -> CaptureState:
        csv_path = self.store.root / state.mission_id / "gps.csv"
        ensure_gps_csv(csv_path)
        state.uav.connection = "ready"
        state.uav.phase = "starting_service"
        state.uav.service = "starting"
        state.uav.file = "recording"
        state.uav.path = str(csv_path)
        # A resume must keep the original mission start timestamp.  Ordinary
        # start creates it exactly once, while an append-only resume only
        # changes the child phase and process ownership.
        state.started_at = state.started_at or _iso(self._clock_now())
        self.store.save(state)

        sync_args: list[str] = []
        sync_api_url = os.environ.get("GPS_SYNC_API_URL", "").strip()
        if sync_api_url:
            sync_args = [
                "--sync-api-url",
                sync_api_url,
                "--sync-device-id",
                os.environ.get("GPS_SYNC_DEVICE_ID", "align-m4p-top-aircraft"),
                "--sync-device-name",
                os.environ.get("GPS_SYNC_DEVICE_NAME", "M4P TOP Aircraft"),
                "--sync-device-type",
                os.environ.get("GPS_SYNC_DEVICE_TYPE", "uav"),
            ]

        process = self.popen_factory(
            self._ap3_command(
                "--mission-id",
                state.mission_id,
                "--incoming-dir",
                str(self.store.root),
                "--resume-window-seconds",
                str(self.resume_window_seconds),
                *sync_args,
            ),
            cwd=self.repo_root,
        )
        self._uav_processes[state.mission_id] = process
        state.uav.pid = process.pid
        state.uav.phase = "recording"
        state.uav.service = "running"
        return self.store.save(state)

    def _remote_mission(
        self,
        state: CaptureState,
        *,
        scene: str,
        map_type: str,
    ):
        api_url = os.environ.get(
            "USRP_UPLOAD_API_URLS",
            "",
        ).strip() or os.environ.get(
            "USRP_UPLOAD_API_URL",
            "http://127.0.0.1:8888/api/usrp/upload-noise-csv",
        )
        return self.usrp_backend.RemoteMission(
            mission_id=state.mission_id,
            api_url=api_url,
            scene=scene,
            map_type=map_type,
            work_dir=os.environ.get(
                "USRP_REMOTE_WORK_DIR",
                "/home/user/rx_sampling",
            ),
            noise_csv=os.environ.get(
                "USRP_REMOTE_NOISE_CSV",
                "/home/user/rx_sampling/noise.csv",
            ),
            run_user=os.environ.get("RASPI_USER", "user"),
        )

    def _save_usrp_phase(self, mission_id: str, phase: str) -> None:
        with self._lock:
            state = self.store.load(mission_id)
            state.usrp.phase = phase
            if phase == "recording":
                state.usrp.service = "running"
                state.usrp.file = "recording"
            elif phase == "starting_service":
                state.usrp.service = "starting"
            self.store.save(state)

    def _clock_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _gps_last_sample(self, path: Path) -> datetime | None:
        """Read the last parseable GPS timestamp without changing the file."""

        if not path.exists() or not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if tuple(reader.fieldnames or ()) != GPS_CSV_COLUMNS:
                    return None
                last: datetime | None = None
                for row in reader:
                    parsed = _parse_timestamp(row.get("time_stamp"))
                    if parsed is not None:
                        last = parsed
                return last
        except (OSError, UnicodeError, csv.Error):
            return None

    def _refresh_uav_sample_metadata(self, state: CaptureState) -> datetime | None:
        """Synchronise persisted AP3 freshness metadata with the canonical CSV."""

        path = Path(state.uav.path) if state.uav.path else self.store.root / state.mission_id / "gps.csv"
        latest = self._gps_last_sample(path)
        if latest is None:
            return _parse_timestamp(state.uav.last_sample_at)
        previous = _parse_timestamp(state.uav.last_sample_at)
        if previous is None or latest > previous:
            state.uav.last_sample_at = _iso(latest)
            return latest
        return previous

    def record_gps_sample(
        self,
        mission_id: str,
        sample_at: str | datetime,
        write_sample: Callable[[], None] | None = None,
    ) -> CaptureState | None:
        """Persist a successful GPS write for an existing mission.

        The GPS sync endpoint also serves missions that are not managed by the
        coordinator.  Those calls simply return ``None``; managed missions
        update the same locked ``capture.json`` used by status polling.
        """

        parsed = sample_at if isinstance(sample_at, datetime) else _parse_timestamp(sample_at)
        if parsed is None:
            raise CaptureError("GPS sample timestamp is invalid")
        with self._lock:
            try:
                state = self.store.load(mission_id)
            except CaptureNotFoundError:
                if write_sample is not None:
                    write_sample()
                return None
            if state.target not in {"uav", "bind"} or state.uav.service == "idle":
                if write_sample is not None:
                    write_sample()
                return state
            if not uav_accepts_gps_sample(state.uav):
                return state
            # The sync callback is the first positive reconnection evidence
            # available to a bound mission.  Evaluate the gap against the
            # persisted *previous* row before updating last_sample_at; the
            # incoming row may already have been appended to gps.csv by the
            # API handler.
            if (
                state.bind
                and state.uav.phase == "reconciling"
                and state.uav.service in {"presumed_running", "running", "starting"}
            ):
                state = self._resume_uav_locked(
                    state,
                    recovered_at=parsed,
                    incoming_sample=True,
                )
                if state.uav.phase == "resume_timeout" or state.uav.service == "failed":
                    return state
            if write_sample is not None:
                write_sample()
            previous = _parse_timestamp(state.uav.last_sample_at)
            if previous is None or parsed > previous:
                state.uav.last_sample_at = _iso(parsed)
            return self.store.save(state)

    def _mark_uav_freshness(self, state: CaptureState, health: Any | None = None) -> CaptureState:
        """Reconcile a live recorder against AP3 health and GPS freshness."""

        child = state.uav
        if child.service not in {"starting", "running", "presumed_running"}:
            return state
        now = self._clock_now()
        latest = self._refresh_uav_sample_metadata(state)
        age: float | None = None
        if latest is not None:
            age = max(0.0, (now - latest).total_seconds())
        elif state.started_at:
            started = _parse_timestamp(state.started_at)
            if started is not None:
                age = max(0.0, (now - started).total_seconds())

        health_state = getattr(health, "state", None)
        health_stale = bool(getattr(health, "stale", False))
        if isinstance(health, dict):
            health_state = health.get("state")
            health_stale = bool(health.get("stale", False))
        health_bad = bool(health is not None and (health_state != "ready" or health_stale))
        stale = health_bad or (age is not None and age > self.gps_freshness_seconds)
        if not stale:
            return state

        if child.disconnected_at is None:
            child.disconnected_at = _iso(now)
        if _parse_timestamp(child.resume_deadline_at) is None:
            # The resume boundary is anchored to the last valid row, not to
            # the first stale poll.  If no row was ever written, started_at is
            # the only persisted evidence available for the same decision.
            base = latest or _parse_timestamp(state.started_at) or now
            child.resume_deadline_at = _iso(
                base + timedelta(seconds=self.resume_window_seconds)
            )
        child.connection = "offline"
        child.service = "presumed_running"
        child.file = "recording"
        child.phase = "reconciling"
        child.error = "GPS sample is stale" if not health_bad else "AP3 connection is offline"
        return state

    def _terminate_uav_process(self, mission_id: str) -> None:
        """Best-effort termination used when a resume window is closed."""

        process = self._uav_processes.get(mission_id)
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        finally:
            self._uav_processes.pop(mission_id, None)

    def _uav_partial_rows(self, path: Path) -> int:
        """Count rows with parseable timestamps in a validated GPS file."""

        if not path.exists() or not path.is_file():
            return 0
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if tuple(reader.fieldnames or ()) != GPS_CSV_COLUMNS:
                    return 0
                return sum(
                    1
                    for row in reader
                    if _parse_timestamp(row.get("time_stamp")) is not None
                )
        except (OSError, UnicodeError, csv.Error):
            return 0

    def _resume_timeout_locked(
        self,
        state: CaptureState,
        *,
        path: Path,
    ) -> CaptureState:
        """Finalize a recoverable AP3 child as a Partial GPS Result."""

        self._terminate_uav_process(state.mission_id)
        child = state.uav
        rows = self._uav_partial_rows(path)
        child.service = "failed"
        child.phase = "resume_timeout"
        child.file = "ready" if rows else "failed"
        child.pid = None
        child.error = (
            "AP3 Resume Timeout; partial GPS file available"
            if rows
            else "AP3 Resume Timeout; no valid GPS rows available"
        )
        return self.store.save(state)

    def _resume_reject_locked(
        self,
        state: CaptureState,
        *,
        error: str,
    ) -> CaptureState:
        """Fail an unsafe resume without changing the existing GPS file."""

        self._terminate_uav_process(state.mission_id)
        state.uav.service = "failed"
        state.uav.file = "failed"
        state.uav.phase = "failed"
        state.uav.pid = None
        state.uav.error = error
        return self.store.save(state)

    def _resume_uav_locked(
        self,
        state: CaptureState,
        *,
        recovered_at: datetime | None = None,
        incoming_sample: bool = False,
    ) -> CaptureState:
        """Resume one existing bound AP3 child under the coordinator lock."""

        child = state.uav
        # AP3 Capture Resume belongs to the existing Bound Mission.  A
        # standalone UAV capture keeps the ticket-06 reconciling behaviour and
        # must never be guessed into a replacement or resumed mission.
        if (
            not state.bind
            or state.target not in {"bind", "uav"}
            or state.overall_state
            in {"stopping", "finalizing", "completed", "completed_with_warning", "failed"}
            or child.service in {"stopping", "stopped", "failed"}
            or child.phase in {"stopping", "stopping_service", "finalizing_file", "stop_failed", "resume_timeout"}
        ):
            return state
        if child.service not in {"presumed_running", "running", "starting"} and child.phase != "reconciling":
            return state

        path = Path(child.path) if child.path else self.store.root / state.mission_id / "gps.csv"
        try:
            # Validate before spawning or changing any recorder state.  This
            # keeps a malformed existing file byte-for-byte intact.
            validate_gps_csv(path)
        except (OSError, GpsCsvSchemaError) as exc:
            return self._resume_reject_locked(state, error=str(exc))

        persisted_sample = _parse_timestamp(child.last_sample_at)
        file_sample = self._gps_last_sample(path)
        # The canonical file is the source of truth for rows that survived a
        # backend restart.  A recorder can flush a row before the callback
        # persists ``last_sample_at``; never discard that newer evidence.
        previous = (
            persisted_sample
            if incoming_sample and persisted_sample is not None
            else file_sample or persisted_sample
        )
        if (
            not incoming_sample
            and
            file_sample is not None
            and (persisted_sample is None or file_sample > persisted_sample)
        ):
            child.last_sample_at = _iso(file_sample)
            persisted_deadline = _parse_timestamp(child.resume_deadline_at)
            if persisted_deadline is None or (
                persisted_sample is not None
                and persisted_deadline <= persisted_sample + timedelta(seconds=self.resume_window_seconds)
            ):
                child.resume_deadline_at = _iso(
                    file_sample + timedelta(seconds=self.resume_window_seconds)
                )
        observed = recovered_at or self._clock_now()
        deadline = _parse_timestamp(child.resume_deadline_at)
        if deadline is None:
            base = previous or _parse_timestamp(state.started_at) or observed
            deadline = base + timedelta(seconds=self.resume_window_seconds)
            child.resume_deadline_at = _iso(deadline)
        if previous is not None and observed < previous:
            return state
        if resume_window_expired(previous, observed, self.resume_window_seconds) or observed > deadline:
            return self._resume_timeout_locked(state, path=path)

        process = self._uav_processes.get(state.mission_id)
        process_alive = False
        if process is not None:
            try:
                process_alive = process.poll() is None
            except Exception:
                process_alive = False
        if process_alive:
            child.connection = "ready"
            child.service = "running"
            child.file = "recording"
            child.phase = "recording"
            child.error = ""
            child.pid = process.pid
            child.disconnected_at = None
            child.resume_deadline_at = None
            return self.store.save(state)

        try:
            # The recorder opens this same canonical path in append mode.  No
            # new mission is created and no prior rows/header are truncated.
            resumed = self._launch_uav(state)
        except Exception as exc:
            return self._resume_reject_locked(state, error=f"AP3 resume failed: {exc}")
        resumed.uav.connection = "ready"
        resumed.uav.service = "running"
        resumed.uav.file = "recording"
        resumed.uav.phase = "recording"
        resumed.uav.error = ""
        resumed.uav.disconnected_at = None
        resumed.uav.resume_deadline_at = None
        return self.store.save(resumed)

    def resume_uav(
        self,
        mission_id: str,
        recovered_at: str | datetime | None = None,
    ) -> CaptureState:
        """Public AP3 Capture Resume operation for an existing Bound Mission.

        ``recovered_at`` is the reconnection or first valid recovery sample
        timestamp.  The comparison is inclusive at the five-minute boundary;
        a later recovery is finalized as a Partial GPS Result.
        """

        parsed = recovered_at if isinstance(recovered_at, datetime) else _parse_timestamp(recovered_at)
        if recovered_at is not None and parsed is None:
            raise CaptureError("AP3 resume timestamp is invalid")
        with self._lock:
            state = self.store.load(mission_id)
            return self._resume_uav_locked(state, recovered_at=parsed)

    def _launch_usrp(
        self,
        state: CaptureState,
        *,
        scene: str,
        map_type: str,
    ) -> CaptureState:
        state.usrp.connection = "ready"
        state.usrp.phase = "starting_service"
        state.usrp.service = "starting"
        state.usrp.file = "recording"
        state.started_at = state.started_at or _now_iso()
        self.store.save(state)
        remote = self.usrp_backend.start_capture_job(
            state.selected_usrp_mode,
            self._remote_mission(state, scene=scene, map_type=map_type),
            progress=lambda phase: self._save_usrp_phase(state.mission_id, phase),
        )
        state.usrp.service = (
            "running" if remote.get("service_state") == "running" else "starting"
        )
        mission_state = remote.get("mission_state") or {}
        if mission_state.get("upload_state") == "recording":
            state.usrp.file = "recording"
        if state.usrp.service == "running":
            state.usrp.phase = "recording"
        return self.store.save(state)

    def start_uav(
        self,
        *,
        mission_id: str | None = None,
        bind: bool = False,
        selected_usrp_mode: UsrpMode = "test",
    ) -> CaptureState:
        with self._lock:
            if self._active_uav() is not None:
                raise CaptureConflictError("UAV capture is already running")
            self.preflight_uav()
            state = self.store.create(
                bind=bind,
                selected_usrp_mode=selected_usrp_mode,
                target="bind" if bind else "uav",
                mission_id=mission_id,
            )
            return self._launch_uav(state)

    def start_usrp(
        self,
        mode: UsrpMode,
        *,
        mission_id: str | None = None,
        bind: bool = False,
        scene: str = "NTPU",
        map_type: str = "iss",
    ) -> CaptureState:
        with self._lock:
            if self._active_usrp() is not None:
                raise CaptureConflictError("USRP capture is already running")
            self.preflight_usrp(mode)
            state = self.store.create(
                bind=bind,
                selected_usrp_mode=mode,
                target="bind" if bind else "usrp",
                mission_id=mission_id,
            )
            try:
                return self._launch_usrp(state, scene=scene, map_type=map_type)
            except Exception as exc:
                state.usrp.service = "failed"
                state.usrp.file = "failed"
                state.usrp.error = str(exc)
                self.store.save(state)
                raise CaptureUnavailableError(str(exc)) from exc

    def start_bind(
        self,
        mode: UsrpMode,
        *,
        scene: str = "NTPU",
        map_type: str = "iss",
    ) -> CaptureState:
        with self._lock:
            if self._active_uav() is not None or self._active_usrp() is not None:
                raise CaptureConflictError("a capture job is already running")
            self._preflight_bind(mode)
            state = self.store.create(
                bind=True,
                selected_usrp_mode=mode,
                target="bind",
            )
            try:
                state = self._launch_uav(state)
            except Exception as exc:
                state.uav.service = "failed"
                state.uav.file = "failed"
                state.uav.phase = "failed"
                state.uav.error = str(exc)
                self.store.save(state)
            try:
                state = self._launch_usrp(state, scene=scene, map_type=map_type)
            except Exception as exc:
                state.usrp.service = "failed"
                state.usrp.file = "failed"
                state.usrp.phase = "failed"
                state.usrp.error = str(exc)
                self.store.save(state)
            return self.store.load(state.mission_id)

    def stop_uav(self, mission_id: str) -> CaptureState:
        """Stop and finalize AP3 without holding the coordinator lock.

        Process termination and CSV validation are blocking operations.  The
        mission is first persisted as stopping, then the work runs outside
        ``self._lock`` so a bound USRP stop can begin at the same time.  All
        result writes reload the latest snapshot under the lock, preserving
        concurrent GPS/upload callbacks.
        """
        with self._lock:
            state = self.store.load(mission_id)
            # Resume Timeout is a terminal AP3 outcome for this mission.  Do
            # not turn its Partial GPS Result back into a successful stopped
            # child merely because a late Stop/status request arrived.
            if state.uav.phase == "resume_timeout" and state.uav.service == "failed":
                return state
            if state.uav.service == "stopped" and state.uav.file == "ready":
                return state

            process = self._uav_processes.get(mission_id)
            csv_path = Path(state.uav.path) if state.uav.path else (
                self.store.root / mission_id / "gps.csv"
            )
            state.uav.phase = "stopping"
            state.uav.service = "stopping"
            state.uav.file = "finalizing"
            self.store.save(state)

        # Keep all potentially blocking process/file work outside the lock so
        # the sibling USRP stop can make progress independently.
        process_error: Exception | None = None
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        except Exception as exc:
            process_error = exc

        validation_error: Exception | None = None
        if process_error is None:
            try:
                validate_gps_csv(csv_path)
            except (OSError, GpsCsvSchemaError) as exc:
                validation_error = exc

        with self._lock:
            state = self.store.load(mission_id)
            child = state.uav
            if process_error is not None:
                # A local process that could not be proven stopped remains an
                # unresolved stop.  Do not fabricate a terminal result.
                return self._mark_uav_stop_failure_locked(
                    state,
                    str(process_error or "AP3 process stop timed out"),
                )
            if validation_error is not None:
                # The process is known to have exited, but the artifact could
                # not be validated.  Keep any valid rows on disk and expose a
                # failed AP3 child rather than claiming a clean stop.
                child.service = "failed"
                child.file = "failed"
                child.phase = "failed"
                child.pid = None
                child.error = str(validation_error)
                self._uav_processes.pop(mission_id, None)
                return self.store.save(state)

            child.service = "stopped"
            child.file = "ready"
            child.phase = "stopped"
            child.pid = None
            child.error = ""
            self._uav_processes.pop(mission_id, None)
            return self.store.save(state)

    def _mark_uav_stop_failure_locked(
        self,
        state: CaptureState,
        error: str,
    ) -> CaptureState:
        """Persist an unresolved AP3 stop without claiming completion."""

        child = state.uav
        child.connection = "unknown"
        child.service = "presumed_running"
        child.file = "finalizing"
        child.phase = "stop_failed"
        child.error = error or "AP3 stop failed"
        return self.store.save(state)

    def _reconcile_usrp_remote(
        self,
        state: CaptureState,
        remote: dict,
    ) -> CaptureState:
        """Apply one adapter snapshot without creating or controlling a mission.

        The adapter reads the mission identified by ``state.mission_id``.  A
        mismatched identity is not safe evidence for this child and is treated
        like a lost control-plane connection by the caller.
        """

        mission_state = remote.get("mission_state")
        if not isinstance(mission_state, dict) or not mission_state:
            raise CaptureError("remote mission state is unavailable")
        remote_mission_id = mission_state.get("mission_id")
        if str(remote_mission_id or "") != state.mission_id:
            raise CaptureError("remote mission state belongs to another mission")

        service_state = str(remote.get("service_state") or "unknown").lower()
        remote_state = str(
            mission_state.get("state")
            or mission_state.get("phase")
            or ""
        ).lower()
        upload_state = str(mission_state.get("upload_state") or "").lower()

        state.usrp.connection = "ready"
        state.usrp.error = ""

        if remote_state in _REMOTE_FAILED_STATES or upload_state == "failed":
            if service_state != "stopped":
                state.usrp.service = "presumed_running"
                state.usrp.file = "failed"
                state.usrp.phase = "reconciling"
                state.usrp.error = "remote failure reported while service may still be running"
                return state
            state.usrp.service = "failed"
            state.usrp.file = "failed"
            state.usrp.phase = "failed"
            return state

        if upload_state == "upload_pending" or remote_state == "upload_pending":
            state.usrp.service = "stopped" if service_state == "stopped" else "presumed_running"
            state.usrp.file = "upload_pending"
            state.usrp.phase = "upload_pending"
            return state

        if upload_state == "uploaded":
            if service_state != "stopped":
                state.usrp.service = "presumed_running"
                state.usrp.file = "uploaded"
                state.usrp.phase = "reconciling"
                return state
            state.usrp.service = "stopped"
            state.usrp.file = "uploaded"
            state.usrp.phase = "completed"
            return state

        if remote_state in _REMOTE_FINALIZING_STATES or upload_state in {
            "finalizing",
            "uploading",
        }:
            state.usrp.service = "stopped" if service_state == "stopped" else "presumed_running"
            state.usrp.file = "finalizing"
            state.usrp.phase = "finalizing_file"
            return state

        if remote_state in _REMOTE_STOPPED_STATES:
            if service_state != "stopped":
                state.usrp.service = "presumed_running"
                state.usrp.phase = "reconciling"
                state.usrp.file = (
                    "uploaded" if upload_state == "uploaded" else "upload_pending"
                )
                return state
            state.usrp.service = "stopped"
            state.usrp.file = "upload_pending"
            state.usrp.phase = "upload_pending"
            return state

        if remote_state in _REMOTE_RUNNING_STATES or upload_state == "recording":
            if service_state == "running":
                state.usrp.service = "running"
                state.usrp.file = "recording"
                state.usrp.phase = "recording"
            elif service_state == "stopped":
                # The mission metadata claims activity while systemd says it
                # is stopped.  Keep the child uncertain instead of fabricating
                # a clean stop or restarting the service.
                state.usrp.service = "presumed_running"
                state.usrp.file = "recording"
                state.usrp.phase = "reconciling"
            else:
                state.usrp.service = "presumed_running"
                state.usrp.file = "recording"
                state.usrp.phase = "reconciling"
            return state

        if service_state == "stopped":
            state.usrp.service = "stopped"
            state.usrp.file = "upload_pending"
            state.usrp.phase = "upload_pending"
            return state

        raise CaptureError("remote mission state is unknown")

    def reconcile_usrp(self, mission_id: str) -> CaptureState:
        """Read and reconcile one existing USRP mission by its original ID."""

        with self._lock:
            state = self.store.load(mission_id)
            mode = state.selected_usrp_mode

        try:
            remote = self.usrp_backend.get_capture_job(mode, mission_id)
            if not isinstance(remote, dict):
                raise CaptureError("remote USRP status is invalid")
            with self._lock:
                state = self.store.load(mission_id)
                return self.store.save(self._reconcile_usrp_remote(state, remote))
        except Exception as exc:
            with self._lock:
                state = self.store.load(mission_id)
                current_service = state.usrp.service
                state.usrp.connection = "offline"
                if current_service in {"starting", "running", "presumed_running", "stopping"}:
                    state.usrp.service = "presumed_running"
                    if state.usrp.file == "none":
                        state.usrp.file = "recording"
                    if state.usrp.phase not in {
                        "stopping",
                        "stopping_service",
                        "stop_failed",
                    }:
                        state.usrp.phase = "reconciling"
                state.usrp.error = str(exc) or "Raspberry Pi status unavailable"
                return self.store.save(state)

    def refresh_usrp(self, mission_id: str) -> CaptureState:
        """Backward-compatible public alias for runtime reconciliation."""

        return self.reconcile_usrp(mission_id)

    def status(self, mode: UsrpMode = "test") -> CaptureState:
        with self._lock:
            # Read the mission snapshot under the same coordinator lock used by
            # GPS sample updates and persistence.  Reading first and locking
            # later lets an old snapshot overwrite a freshly persisted
            # ``last_sample_at`` during runtime status reconciliation.
            states = self.store.list()
            self._health_mode = mode
            health = self.health_monitor.poll(mode=mode)
            uav_state = next(
                (item for item in reversed(states) if item.target in {"uav", "bind"}),
                None,
            )
            usrp_state = next(
                (item for item in reversed(states) if item.target in {"usrp", "bind"}),
                None,
            )

            if uav_state and uav_state.uav.service in {
                "starting",
                "running",
                "presumed_running",
            }:
                previous_sample = _parse_timestamp(uav_state.uav.last_sample_at)
                was_reconciling = uav_state.uav.phase == "reconciling"
                had_disconnect = uav_state.uav.disconnected_at is not None
                was_offline = uav_state.uav.connection == "offline"
                process = self._uav_processes.get(uav_state.mission_id)
                process_alive = False
                if process is not None:
                    try:
                        process_alive = process.poll() is None
                    except Exception:
                        process_alive = False
                resumable_without_process = (
                    uav_state.bind
                    and uav_state.uav.phase == "reconciling"
                )
                process_code = None
                if process is not None and not process_alive:
                    try:
                        process_code = process.poll()
                    except Exception:
                        process_code = None
                if process_code == 2 and uav_state.bind:
                    path = (
                        Path(uav_state.uav.path)
                        if uav_state.uav.path
                        else self.store.root / uav_state.mission_id / "gps.csv"
                    )
                    uav_state = self._resume_timeout_locked(uav_state, path=path)
                elif not process_alive and not resumable_without_process:
                    uav_state.uav.connection = "offline"
                    uav_state.uav.service = "failed"
                    uav_state.uav.file = "failed"
                    uav_state.uav.phase = "failed"
                    uav_state.uav.error = "UAV capture process is no longer owned by the backend"
                    self.store.save(uav_state)
                else:
                    # A live subprocess alone is not proof of a healthy AP3
                    # capture.  Require a recent valid GPS row and preserve a
                    # recoverable reconciling state during the resume window.
                    uav_health = health.get("ap3")
                    refreshed = self._mark_uav_freshness(uav_state, uav_health)
                    latest_sample = _parse_timestamp(refreshed.uav.last_sample_at)
                    if (
                        refreshed.bind
                        and refreshed.uav.phase == "reconciling"
                        and latest_sample is not None
                        and (previous_sample is None or latest_sample > previous_sample)
                    ):
                        # A newly persisted row is positive reconnection
                        # evidence.  Resume against the original mission and
                        # path; the helper decides whether the process can be
                        # reused or must be relaunched in append mode.
                        refreshed = self._resume_uav_locked(
                            refreshed,
                            recovered_at=latest_sample,
                        )
                    elif (
                        refreshed.bind
                        and was_reconciling
                        and had_disconnect
                        and was_offline
                        and (
                            getattr(uav_health, "state", None)
                            if not isinstance(uav_health, dict)
                            else uav_health.get("state")
                        ) == "ready"
                    ):
                        # A ready AP3 health result after a persisted offline
                        # observation is the other allowed reconnection
                        # confirmation when no recovery row has arrived yet.
                        refreshed = self._resume_uav_locked(refreshed)
                    if refreshed.uav.phase in {"reconciling", "resume_timeout"} or refreshed.uav.last_sample_at:
                        self.store.save(refreshed)
            elif (
                uav_state
                and uav_state.uav.service == "stopping"
                and uav_state.mission_id not in self._uav_processes
            ):
                uav_state.uav.connection = "offline"
                uav_state.uav.service = "failed"
                uav_state.uav.file = "failed"
                uav_state.uav.phase = "failed"
                uav_state.uav.error = (
                    "UAV stop/finalization path is no longer safely owned by the backend"
                )
                self.store.save(uav_state)

            if usrp_state and usrp_state.usrp.service in {
                "starting",
                "running",
                "presumed_running",
                "stopping",
            }:
                usrp_state = self.reconcile_usrp(usrp_state.mission_id)

            same_mission = bool(
                uav_state
                and usrp_state
                and uav_state.mission_id == usrp_state.mission_id
            )
            if same_mission:
                state = self.store.load(uav_state.mission_id)
            else:
                state = CaptureState(
                    mission_id="",
                    target="bind",
                    bind=False,
                    selected_usrp_mode=(
                        usrp_state.selected_usrp_mode if usrp_state else mode
                    ),
                    created_at=_now_iso(),
                    uav=(
                        uav_state.uav.model_copy(deep=True)
                        if uav_state
                        else ChildState()
                    ),
                    usrp=(
                        usrp_state.usrp.model_copy(deep=True)
                        if usrp_state
                        else ChildState()
                    ),
                )
                state.overall_state = _aggregate_state(state)

            uav_active = state.uav.service in {
                "starting",
                "running",
                "presumed_running",
                "stopping",
            }
            usrp_active = state.usrp.service in {
                "starting",
                "running",
                "presumed_running",
                "stopping",
            }
            # Device Health is a current projection. Only an idle, never-started
            # child may borrow its connection/error for legacy dashboard fields;
            # terminal mission child results remain immutable historical truth.
            if not uav_active and state.uav.service == "idle" and state.started_at is None:
                result = health.get("ap3")
                if result is not None:
                    state.uav.connection = result.state
                    state.uav.error = result.error
            if not usrp_active and state.usrp.service == "idle" and state.started_at is None:
                result = health.get("raspi")
                if result is not None:
                    state.selected_usrp_mode = mode
                    state.usrp.connection = result.state
                    state.usrp.error = result.error
            if same_mission and state.mission_id:
                if state.overall_state in {"completed", "completed_with_warning", "failed"}:
                    return state
                return self.store.save(state)
            return state

    def _mark_usrp_stop_failure_locked(
        self,
        state: CaptureState,
        error: str,
        *,
        connection: ConnectionState = "unknown",
    ) -> CaptureState:
        """Persist an unresolved USRP stop without claiming completion."""

        child = state.usrp
        child.connection = connection
        child.service = "presumed_running"
        child.file = "finalizing"
        child.phase = "stop_failed"
        child.error = error or "USRP stop result is unknown"
        return self.store.save(state)

    def _apply_usrp_stop_result_locked(
        self,
        state: CaptureState,
        remote: object,
    ) -> CaptureState:
        """Apply a stop response only when it positively identifies a stop.

        A successful SSH call is not itself evidence that the remote process
        stopped.  Require a matching (or legacy-omitted) mission state and a
        terminal remote state before transitioning to ``stopped``.
        """

        if not isinstance(remote, dict):
            return self._mark_usrp_stop_failure_locked(
                state,
                "USRP stop result is invalid",
            )
        mission_state = remote.get("mission_state")
        if not isinstance(mission_state, dict) or not mission_state:
            return self._mark_usrp_stop_failure_locked(
                state,
                "USRP stop result does not include mission state",
            )
        remote_mission_id = mission_state.get("mission_id")
        if str(remote_mission_id or "") != state.mission_id:
            return self._mark_usrp_stop_failure_locked(
                state,
                "USRP stop result does not identify the requested mission",
            )
        service_state = str(remote.get("service_state") or "unknown").lower()
        remote_state = str(
            mission_state.get("state")
            or mission_state.get("phase")
            or ""
        ).lower()
        upload_state = str(mission_state.get("upload_state") or "").lower()
        child = state.usrp

        if service_state != "stopped":
            return self._mark_usrp_stop_failure_locked(
                state,
                "USRP remote service state is not confirmed stopped",
            )
        if child.file == "uploaded":
            # A callback may have persisted newer upload evidence while the
            # remote stop request was in flight.  Never downgrade it with the
            # older response snapshot.
            child.connection = "ready"
            child.service = "stopped"
            child.phase = "completed"
            child.error = ""
            return self.store.save(state)
        if remote_state in _REMOTE_FAILED_STATES:
            child.connection = "ready"
            child.service = "failed"
            child.file = "failed"
            child.phase = "failed"
            child.error = str(
                mission_state.get("error")
                or mission_state.get("message")
                or "USRP finalization failed"
            )
            return self.store.save(state)
        if upload_state == "failed":
            child.connection = "ready"
            child.service = "stopped"
            child.file = "upload_pending"
            child.phase = "upload_pending"
            child.error = str(
                mission_state.get("error")
                or mission_state.get("message")
                or "USRP upload failed"
            )
            return self.store.save(state)
        if remote_state in _REMOTE_FINALIZING_STATES or upload_state in {"finalizing", "uploading"}:
            child.connection = "ready"
            child.service = "stopped"
            child.file = "finalizing"
            child.phase = "finalizing_file"
            child.error = ""
            return self.store.save(state)
        if remote_state not in _REMOTE_STOPPED_STATES:
            return self._mark_usrp_stop_failure_locked(
                state,
                "USRP remote mission state is unknown",
            )

        child.connection = "ready"
        child.service = "stopped"
        child.file = "uploaded" if upload_state == "uploaded" else "upload_pending"
        child.phase = "stopped" if child.file == "uploaded" else "upload_pending"
        child.error = ""
        return self.store.save(state)

    def stop_usrp(self, mission_id: str) -> CaptureState:
        with self._lock:
            state = self.store.load(mission_id)
            if state.usrp.service == "stopped":
                return state
            state.usrp.phase = "stopping"
            state.usrp.service = "stopping"
            state.usrp.file = "finalizing"
            self.store.save(state)
            selected_usrp_mode = state.selected_usrp_mode
        try:
            remote = self.usrp_backend.stop_capture_job(selected_usrp_mode, mission_id)
        except Exception as exc:
            with self._lock:
                state = self.store.load(mission_id)
                return self._mark_usrp_stop_failure_locked(
                    state,
                    str(exc),
                    connection="offline",
                )

        with self._lock:
            state = self.store.load(mission_id)
            return self._apply_usrp_stop_result_locked(state, remote)

    def retry_usrp_upload(self, mission_id: str) -> CaptureState:
        with self._lock:
            state = self.store.load(mission_id)
            mode = state.selected_usrp_mode
        try:
            remote = self.usrp_backend.retry_capture_upload(mode, mission_id)
            with self._lock:
                state = self.store.load(mission_id)
                state.usrp.connection = "ready"
                state.usrp.service = "stopped"
                state.usrp.file = "uploaded" if (remote.get("mission_state") or {}).get("upload_state") == "uploaded" else "upload_pending"
                state.usrp.error = "" if state.usrp.file == "uploaded" else "upload retry failed"
                return self.store.save(state)
        except Exception as exc:
            with self._lock:
                state = self.store.load(mission_id)
                state.usrp.file = "upload_pending"
                state.usrp.error = str(exc)
                return self.store.save(state)

    def stop_bind(self, mission_id: str) -> CaptureState:
        """Best-effort Stop All for the selected children.

        The request is persisted before either child operation starts.  Each
        stop runs in its own worker and its result/exception is isolated; a
        slow or failed AP3 finalize therefore cannot prevent the USRP remote
        stop from being attempted (or vice versa).
        """

        with self._lock:
            state = self.store.load(mission_id)
            # Stop All is intentionally one-shot.  Retry Stop is represented
            # by the individual child controls and must not re-issue a stop to
            # an already terminal sibling after a restart.
            if state.stop_requested_at is not None:
                return state
            state.stop_requested_at = _iso(self._clock_now())
            needs_uav_stop = state.uav.service not in {"idle", "stopped", "failed"}
            needs_usrp_stop = state.usrp.service not in {"idle", "stopped", "failed"}
            self.store.save(state)

        operations: dict[str, Callable[[str], CaptureState]] = {}
        if needs_uav_stop:
            operations["uav"] = self.stop_uav
        if needs_usrp_stop:
            operations["usrp"] = self.stop_usrp

        def run_child_stop(name: str, operation: Callable[[str], CaptureState]) -> None:
            try:
                operation(mission_id)
            except Exception as exc:
                # A patched/legacy adapter may raise before persisting its
                # result.  Record an explicit unresolved child so Stop All
                # remains consumed without hiding a possibly-running service.
                with self._lock:
                    current = self.store.load(mission_id)
                    if name == "usrp":
                        self._mark_usrp_stop_failure_locked(
                            current,
                            str(exc),
                            connection="unknown",
                        )
                    else:
                        self._mark_uav_stop_failure_locked(current, str(exc))

        # Submitting both before waiting is the important contract here.  The
        # coordinator lock is only held by each child for short state writes;
        # blocking hardware/process work occurs outside it.
        with ThreadPoolExecutor(max_workers=max(1, len(operations))) as pool:
            futures = [
                pool.submit(run_child_stop, name, operation)
                for name, operation in operations.items()
            ]
            for future in futures:
                future.result()

        with self._lock:
            return self.store.load(mission_id)

    def ack_noise_upload(
        self,
        mission_id: str,
        *,
        path: Path,
        size: int,
        sha256: str,
    ) -> CaptureState:
        with self._lock:
            state = self.store.load(mission_id)
            state.usrp.path = str(path)
            state.usrp.service = "stopped"
            state.usrp.file = "uploaded"
            state.usrp.error = ""
            return self.store.save(state)
