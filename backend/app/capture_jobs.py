from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


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
    "partial_failed",
    "finalizing",
    "completed",
    "failed",
]
CaptureTarget = Literal["uav", "usrp", "bind"]
UsrpMode = Literal["test", "usrp"]


class ChildState(BaseModel):
    mission_id: str = ""
    connection: ConnectionState = "unknown"
    service: ServiceState = "idle"
    file: FileState = "none"
    error: str = ""
    path: str = ""
    pid: int | None = None


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
    services = {child.service for child in children}
    files = {child.file for child in children}

    failed_count = sum(
        child.service == "failed" or child.file == "failed"
        for child in children
    )
    if failed_count:
        return "failed" if failed_count == len(children) else "partial_failed"

    completed = all(
        child.service == "stopped" and child.file in {"ready", "uploaded"}
        for child in children
    )
    if completed:
        return "completed"
    if services & {"stopping"} or files & {"finalizing", "upload_pending"}:
        return "finalizing"
    if services & {"running", "presumed_running"}:
        return "running"
    if services & {"starting"}:
        return "starting"
    return "ready"


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
        if state.overall_state == "completed" and state.finished_at is None:
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
    ):
        self.store = store
        self.repo_root = Path(repo_root)
        self.run_command = run_command
        self.popen_factory = popen_factory
        self._uav_processes: dict[str, subprocess.Popen] = {}

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

    def _ap3_command(self, *extra: str) -> list[str]:
        script = self.repo_root / "tools" / "ap3_to_gps_csv.py"
        return [sys.executable, str(script), *extra]

    def preflight_uav(self) -> None:
        result = self.run_command(
            self._ap3_command("--check"),
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "AP3 is unavailable").strip()
            raise CaptureUnavailableError(detail)

    def start_uav(
        self,
        *,
        mission_id: str | None = None,
        bind: bool = False,
        selected_usrp_mode: UsrpMode = "test",
    ) -> CaptureState:
        if self._active_uav() is not None:
            raise CaptureConflictError("UAV capture is already running")
        self.preflight_uav()
        state = self.store.create(
            bind=bind,
            selected_usrp_mode=selected_usrp_mode,
            target="bind" if bind else "uav",
            mission_id=mission_id,
        )
        csv_path = self.store.root / state.mission_id / "gps.csv"
        csv_path.write_text("time_stamp,lat,lon,alt\n", encoding="utf-8")
        state.uav.connection = "ready"
        state.uav.service = "starting"
        state.uav.file = "recording"
        state.uav.path = str(csv_path)
        state.started_at = _now_iso()
        self.store.save(state)

        process = self.popen_factory(
            self._ap3_command(
                "--mission-id",
                state.mission_id,
                "--incoming-dir",
                str(self.store.root),
            ),
            cwd=self.repo_root,
        )
        self._uav_processes[state.mission_id] = process
        state.uav.pid = process.pid
        state.uav.service = "running"
        return self.store.save(state)

    def stop_uav(self, mission_id: str) -> CaptureState:
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
            with csv_path.open("r", encoding="utf-8-sig") as handle:
                header = handle.readline().strip()
        except OSError as exc:
            state.uav.service = "failed"
            state.uav.file = "failed"
            state.uav.error = str(exc)
            return self.store.save(state)
        if header != "time_stamp,lat,lon,alt":
            state.uav.service = "failed"
            state.uav.file = "failed"
            state.uav.error = "gps.csv header is invalid"
            return self.store.save(state)

        state.uav.service = "stopped"
        state.uav.file = "ready"
        state.uav.pid = None
        self._uav_processes.pop(mission_id, None)
        return self.store.save(state)
