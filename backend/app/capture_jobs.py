from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.gps_csv import GpsCsvSchemaError, ensure_gps_csv, validate_gps_csv
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


class ChildState(BaseModel):
    mission_id: str = ""
    phase: CapturePhase = "idle"
    connection: ConnectionState = "unknown"
    service: ServiceState = "idle"
    file: FileState = "none"
    error: str = ""
    path: str = ""
    pid: int | None = None

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


class CaptureNotFoundError(CaptureError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mission_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"mission_{stamp}_{uuid.uuid4().hex[:6]}"


def _selected_children(state: CaptureState) -> list[ChildState]:
    if state.target == "uav":
        return [state.uav]
    if state.target == "usrp":
        return [state.usrp]
    return [state.uav, state.usrp]


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
            if state.uav.service in {
                "starting",
                "running",
                "presumed_running",
                "stopping",
            }:
                return state
        return None

    def _active_usrp(self) -> CaptureState | None:
        for state in reversed(self.store.list()):
            if state.target not in {"usrp", "bind"}:
                continue
            if state.usrp.service in {
                "starting",
                "running",
                "presumed_running",
                "stopping",
            }:
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
        try:
            status = self.usrp_backend.get_drone_status(mode)
        except Exception as exc:
            raise CaptureUnavailableError(str(exc)) from exc
        if status.get("service_state") == "running":
            raise CaptureConflictError(f"{mode} capture service is already running")

    def health_status(self, mode: UsrpMode = "test") -> dict[str, dict]:
        with self._lock:
            self._health_mode = mode
            return {
                name: result.as_dict()
                for name, result in self.health_monitor.poll(mode=mode).items()
            }

    def status_payload(self, mode: UsrpMode = "test") -> dict:
        state = self.status(mode)
        return {
            **state.model_dump(),
            "device_health": self.health_monitor.as_dict(),
        }

    def _launch_uav(self, state: CaptureState) -> CaptureState:
        csv_path = self.store.root / state.mission_id / "gps.csv"
        ensure_gps_csv(csv_path)
        state.uav.connection = "ready"
        state.uav.service = "starting"
        state.uav.file = "recording"
        state.uav.path = str(csv_path)
        state.started_at = state.started_at or _now_iso()
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
                *sync_args,
            ),
            cwd=self.repo_root,
        )
        self._uav_processes[state.mission_id] = process
        state.uav.pid = process.pid
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

    def _launch_usrp(
        self,
        state: CaptureState,
        *,
        scene: str,
        map_type: str,
    ) -> CaptureState:
        state.usrp.connection = "ready"
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
            self.preflight_uav()
            self.preflight_usrp(mode)
            state = self.store.create(
                bind=True,
                selected_usrp_mode=mode,
                target="bind",
            )
            try:
                state = self._launch_uav(state)
            except Exception as exc:
                state.uav.connection = "offline"
                state.uav.service = "failed"
                state.uav.file = "failed"
                state.uav.error = str(exc)
                self.store.save(state)
            try:
                state = self._launch_usrp(state, scene=scene, map_type=map_type)
            except Exception as exc:
                state.usrp.connection = "offline"
                state.usrp.service = "failed"
                state.usrp.file = "failed"
                state.usrp.error = str(exc)
                self.store.save(state)
            return self.store.load(state.mission_id)

    def stop_uav(self, mission_id: str) -> CaptureState:
        with self._lock:
            state = self.store.load(mission_id)
            if state.uav.service == "stopped" and state.uav.file == "ready":
                return state

            process = self._uav_processes.get(mission_id)
            state.uav.service = "stopping"
            state.uav.file = "finalizing"
            self.store.save(state)
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)

            csv_path = Path(state.uav.path)
            try:
                validate_gps_csv(csv_path)
            except (OSError, GpsCsvSchemaError) as exc:
                state.uav.service = "failed"
                state.uav.file = "failed"
                state.uav.error = str(exc)
                return self.store.save(state)

            state.uav.service = "stopped"
            state.uav.file = "ready"
            state.uav.pid = None
            self._uav_processes.pop(mission_id, None)
            return self.store.save(state)

    def refresh_usrp(self, mission_id: str) -> CaptureState:
        with self._lock:
            state = self.store.load(mission_id)
            try:
                remote = self.usrp_backend.get_capture_job(
                    state.selected_usrp_mode,
                    mission_id,
                )
            except Exception as exc:
                state.usrp.connection = "offline"
                if state.usrp.service in {"starting", "running", "presumed_running"}:
                    state.usrp.service = "presumed_running"
                state.usrp.error = str(exc)
                return self.store.save(state)

            state.usrp.connection = "ready"
            state.usrp.error = ""
            service_state = remote.get("service_state", "unknown")
            if service_state in {"running", "stopped"}:
                state.usrp.service = service_state
            mission_state = remote.get("mission_state") or {}
            remote_state = mission_state.get("state")
            if remote_state == "failed":
                state.usrp.service = "failed"
            upload_state = mission_state.get("upload_state")
            if upload_state in {
                "recording",
                "finalizing",
                "upload_pending",
                "uploaded",
                "failed",
            }:
                state.usrp.file = upload_state
            return self.store.save(state)

    def status(self, mode: UsrpMode = "test") -> CaptureState:
        states = self.store.list()
        with self._lock:
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
                process = self._uav_processes.get(uav_state.mission_id)
                if process is None or process.poll() is not None:
                    uav_state.uav.connection = "offline"
                    uav_state.uav.service = "failed"
                    uav_state.uav.file = "failed"
                    uav_state.uav.error = "UAV capture process is no longer owned by the backend"
                    self.store.save(uav_state)
            elif (
                uav_state
                and uav_state.uav.service == "stopping"
                and uav_state.mission_id not in self._uav_processes
            ):
                uav_state.uav.connection = "offline"
                uav_state.uav.service = "failed"
                uav_state.uav.file = "failed"
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
                usrp_state = self.refresh_usrp(usrp_state.mission_id)

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

    def stop_usrp(self, mission_id: str) -> CaptureState:
        with self._lock:
            state = self.store.load(mission_id)
            if state.usrp.service == "stopped" and state.usrp.file == "uploaded":
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
                state.usrp.connection = "offline"
                state.usrp.service = "presumed_running"
                state.usrp.phase = "stop_failed"
                state.usrp.error = str(exc)
                return self.store.save(state)

        with self._lock:
            state = self.store.load(mission_id)
            state.usrp.connection = "ready"
            state.usrp.service = "stopped"
            state.usrp.phase = "stopped"
            mission_state = remote.get("mission_state") or {}
            upload_state = mission_state.get("upload_state")
            state.usrp.file = "uploaded" if upload_state == "uploaded" else "upload_pending"
            state.usrp.error = ""
            return self.store.save(state)

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
        with self._lock:
            state = self.store.load(mission_id)
            needs_uav_stop = state.uav.service not in {"idle", "stopped", "failed"}
        if needs_uav_stop:
            self.stop_uav(mission_id)
        with self._lock:
            state = self.store.load(mission_id)
            needs_usrp_stop = state.usrp.service not in {"idle", "stopped", "failed"}
            needs_usrp_retry = state.usrp.service == "stopped" and state.usrp.file == "upload_pending"
        if needs_usrp_stop:
            self.stop_usrp(mission_id)
        elif needs_usrp_retry:
            self.retry_usrp_upload(mission_id)
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
