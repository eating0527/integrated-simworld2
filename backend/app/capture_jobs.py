from __future__ import annotations

import json
import os
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
        return CaptureState.model_validate_json(
            self.path(mission_id).read_text(encoding="utf-8")
        )

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

