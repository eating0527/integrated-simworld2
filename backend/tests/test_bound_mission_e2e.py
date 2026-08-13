"""Public-operation integration checks for a complete Bound Mission.

The workflow tests in ``test_capture_jobs`` exercise individual transitions.
These tests deliberately compose the same public coordinator operations and
assert the persisted ``capture.json`` after each boundary.  Hardware is
represented by small deterministic fakes; no ADB, SSH, or network access is
required for the normal backend test suite.
"""

from __future__ import annotations

import json
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> datetime:
        self.value += timedelta(**kwargs)
        return self.value


class _Process:
    _next_pid = 4000

    def __init__(self, *, fail_terminate_once: bool = False) -> None:
        type(self)._next_pid += 1
        self.pid = type(self)._next_pid
        self._terminated = False
        self._fail_terminate_once = fail_terminate_once

    def poll(self) -> int | None:
        return 0 if self._terminated else None

    def terminate(self) -> None:
        if self._fail_terminate_once:
            self._fail_terminate_once = False
            raise RuntimeError("AP3 finalize timeout")
        self._terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        self._terminated = True


class _HealthFake:
    """Minimal health monitor seam with independently mutable devices."""

    def __init__(self) -> None:
        self.states = {"ap3": "ready", "raspi": "ready"}
        self.errors = {"ap3": "", "raspi": ""}

    def set(self, device: str, state: str, error: str = "") -> None:
        self.states[device] = state
        self.errors[device] = error

    def poll(self, *, mode: str | None = None):
        from app.device_health import HealthResult

        return {
            device: HealthResult(device, state, 0.0, self.errors[device])
            for device, state in self.states.items()
        }

    def as_dict(self):
        return {device: result.as_dict() for device, result in self.poll().items()}


class _UsrpBackendFake:
    """Deterministic USRP adapter used by the composed workflows."""

    def __init__(self) -> None:
        self.RemoteMission = lambda **kwargs: kwargs
        self.remote = None
        self.start_error: BaseException | None = None
        self.stop_results: list[object] = []
        self.upload_results: list[dict] = []
        self.upload_calls: list[str] = []

    @staticmethod
    def _mission_state(
        mission_id: str,
        *,
        state: str,
        upload_state: str,
    ) -> dict:
        return {
            "mission_id": mission_id,
            "state": state,
            "upload_state": upload_state,
        }

    def _response(
        self,
        mission_id: str,
        *,
        service_state: str,
        state: str,
        upload_state: str,
    ) -> dict:
        return {
            "success": True,
            "service_state": service_state,
            "mission_state": self._mission_state(
                mission_id,
                state=state,
                upload_state=upload_state,
            ),
        }

    def get_drone_health(self, mode: str) -> dict:
        return {"state": "ready", "service_state": "stopped"}

    def start_capture_job(self, mode: str, mission: dict, progress=None) -> dict:
        if self.start_error is not None:
            error = self.start_error
            self.start_error = None
            raise error
        if progress:
            progress("recording")
        return self._response(
            mission["mission_id"],
            service_state="running",
            state="running",
            upload_state="recording",
        )

    def get_capture_job(self, mode: str, mission_id: str) -> dict:
        if isinstance(self.remote, BaseException):
            raise self.remote
        if self.remote is not None:
            return self.remote
        return self._response(
            mission_id,
            service_state="running",
            state="running",
            upload_state="recording",
        )

    def stop_capture_job(self, mode: str, mission_id: str) -> dict:
        result = self.stop_results.pop(0) if self.stop_results else self._response(
            mission_id,
            service_state="stopped",
            state="stopped",
            upload_state="uploaded",
        )
        if isinstance(result, BaseException):
            raise result
        return result

    def _upload(self, mode: str, mission_id: str) -> dict:
        self.upload_calls.append(mode)
        if self.upload_results:
            result = self.upload_results.pop(0)
        else:
            result = {"upload_state": "uploaded"}
        return {
            "mission_state": {
                "mission_id": mission_id,
                "upload_state": result.get("upload_state", "upload_pending"),
                "state": result.get("state", "stopped"),
                **({"error": result["error"]} if result.get("error") else {}),
            },
        }

    def upload_capture_job(self, mode: str, mission_id: str) -> dict:
        return self._upload(mode, mission_id)

    def retry_capture_upload(self, mode: str, mission_id: str) -> dict:
        return self._upload(mode, mission_id)


class BoundMissionE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        from app.capture_jobs import CaptureCoordinator, CaptureStore

        self.repo_root = Path(__file__).resolve().parents[2]
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.clock = _Clock(datetime(2026, 8, 13, tzinfo=timezone.utc))
        self.health = _HealthFake()
        self.backend = _UsrpBackendFake()
        self.processes: list[_Process] = []

        def popen(*args, **kwargs):
            process = _Process()
            self.processes.append(process)
            return process

        self.popen = popen
        self.run = Mock(return_value=Mock(returncode=0, stdout="", stderr=""))
        self.coordinator = CaptureCoordinator(
            CaptureStore(self.root),
            repo_root=self.repo_root,
            run_command=self.run,
            popen_factory=self.popen,
            usrp_backend=self.backend,
            health_monitor=self.health,
            clock=self.clock,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _new_coordinator(self, *, backend=None, health=None):
        from app.capture_jobs import CaptureCoordinator, CaptureStore

        return CaptureCoordinator(
            CaptureStore(self.root),
            repo_root=self.repo_root,
            run_command=self.run,
            popen_factory=self.popen,
            usrp_backend=backend or self.backend,
            health_monitor=health or self.health,
            clock=self.clock,
        )

    def _append(
        self,
        state,
        at: datetime,
        *,
        lat: float = 24.943,
        coordinator=None,
    ) -> None:
        from app.gps_csv import append_gps_row

        path = Path(state.uav.path)
        (coordinator or self.coordinator).record_gps_sample(
            state.mission_id,
            at,
            write_sample=lambda: append_gps_row(
                path,
                [at.isoformat(), lat, 121.37, 12.5, "relative"],
            ),
        )

    def _wait_for(self, predicate, timeout: float = 1.5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.005)
        self.fail("timed out waiting for background capture state")

    def test_both_ready_shared_running_stop_all_and_uploaded_completion(self) -> None:
        health = self.coordinator.health_status("usrp")
        self.assertEqual(health["ap3"]["state"], "ready")
        self.assertEqual(health["raspi"]["state"], "ready")

        state = self.coordinator.start_bind("usrp")

        self.assertEqual(state.overall_state, "running")
        self.assertEqual(state.uav.mission_id, state.mission_id)
        self.assertEqual(state.usrp.mission_id, state.mission_id)
        self.assertEqual(len(self.coordinator.store.list()), 1)

        stopped = self.coordinator.stop_bind(state.mission_id)
        persisted = self.coordinator.store.load(state.mission_id)

        self.assertEqual(stopped.overall_state, "completed")
        self.assertEqual(persisted.overall_state, "completed")
        self.assertEqual(persisted.uav.file, "ready")
        self.assertEqual(persisted.usrp.file, "uploaded")
        self.assertIsNotNone(persisted.stop_requested_at)
        payload = json.loads(self.coordinator.store.path(state.mission_id).read_text())
        self.assertEqual(payload["mission_id"], state.mission_id)
        self.assertEqual(payload["uav"]["mission_id"], payload["usrp"]["mission_id"])

    def test_launch_failure_keeps_sibling_and_shared_mission_degraded(self) -> None:
        def fail_popen(*args, **kwargs):
            raise RuntimeError("AP3 recorder failed")

        self.coordinator.popen_factory = fail_popen
        state = self.coordinator.start_bind("usrp")
        persisted = self.coordinator.store.load(state.mission_id)

        self.assertEqual(len(self.coordinator.store.list()), 1)
        self.assertEqual(persisted.uav.mission_id, persisted.usrp.mission_id)
        self.assertEqual(persisted.uav.service, "failed")
        self.assertEqual(persisted.usrp.service, "running")
        self.assertEqual(persisted.overall_state, "degraded")

    def test_usrp_launch_failure_keeps_ap3_and_shared_mission_degraded(self) -> None:
        self.backend.start_error = RuntimeError("USRP service failed to start")

        state = self.coordinator.start_bind("usrp")
        persisted = self.coordinator.store.load(state.mission_id)

        self.assertEqual(len(self.coordinator.store.list()), 1)
        self.assertEqual(persisted.uav.mission_id, persisted.usrp.mission_id)
        self.assertEqual(persisted.uav.service, "running")
        self.assertEqual(persisted.uav.file, "recording")
        self.assertEqual(persisted.usrp.service, "failed")
        self.assertEqual(persisted.usrp.file, "failed")
        self.assertEqual(persisted.overall_state, "degraded")

    def test_raspi_offline_preserves_ap3_then_reconciles_same_mission(self) -> None:
        state = self.coordinator.start_bind("usrp")
        self._append(state, self.clock.value)
        self.health.set("raspi", "offline", "SSH disconnected")
        self.backend.remote = RuntimeError("SSH disconnected")

        degraded = self.coordinator.status("usrp")

        self.assertEqual(degraded.mission_id, state.mission_id)
        self.assertEqual(degraded.overall_state, "degraded")
        self.assertEqual(degraded.usrp.connection, "offline")
        self.assertEqual(degraded.usrp.service, "presumed_running")
        self.assertEqual(degraded.uav.service, "running")
        self.assertEqual(degraded.uav.mission_id, state.mission_id)

        self.health.set("raspi", "ready")
        self.backend.remote = {
            "service_state": "running",
            "mission_state": {
                "mission_id": state.mission_id,
                "state": "running",
                "upload_state": "recording",
            },
        }
        recovered = self.coordinator.status("usrp")

        self.assertEqual(recovered.overall_state, "running")
        self.assertEqual(recovered.usrp.connection, "ready")
        self.assertEqual(recovered.usrp.service, "running")
        self.assertEqual(recovered.uav.mission_id, recovered.usrp.mission_id)

    def test_ap3_freshness_resume_appends_without_new_mission(self) -> None:
        state = self.coordinator.start_bind("usrp")
        first = self.clock.value
        self._append(state, first)
        self.clock.advance(seconds=11)
        self.health.set("ap3", "offline", "GPS link unavailable")

        degraded = self.coordinator.status("usrp")
        self.assertEqual(degraded.uav.phase, "reconciling")
        self.assertEqual(degraded.usrp.service, "running")

        self.health.set("ap3", "ready")
        resumed_at = first + timedelta(seconds=300)
        restarted = self._new_coordinator()
        restored = restarted.store.load(state.mission_id)
        self.assertEqual(restored.uav.phase, "reconciling")
        resumed = restarted.resume_uav(state.mission_id, recovered_at=resumed_at)
        restarted.record_gps_sample(
            state.mission_id,
            resumed_at,
            write_sample=lambda: self._append_row(restored, resumed_at),
        )
        path = Path(state.uav.path)
        lines = path.read_text(encoding="utf-8").splitlines()

        self.assertIsNotNone(resumed)
        self.assertEqual(resumed.uav.mission_id, state.mission_id)
        self.assertEqual(resumed.uav.path, restored.uav.path)
        self.assertEqual(resumed.uav.service, "running")
        self.assertEqual(resumed.overall_state, "running")
        self.assertEqual(lines.count("time_stamp,lat,lon,alt,alt_mode"), 1)
        self.assertEqual(len(lines), 3)
        self.assertEqual(len(restarted.store.list()), 1)

    def _append_row(self, state, at: datetime) -> None:
        from app.gps_csv import append_gps_row

        append_gps_row(
            Path(state.uav.path),
            [at.isoformat(), 24.944, 121.371, 12.5, "relative"],
        )

    def test_resume_timeout_keeps_partial_gps_and_noise_completes_with_warning(self) -> None:
        state = self.coordinator.start_bind("usrp")
        first = self.clock.value
        self._append(state, first)
        self.clock.advance(seconds=11)
        self.health.set("ap3", "offline", "USB disconnected")
        self.coordinator.status("usrp")

        timeout = self.coordinator.resume_uav(
            state.mission_id,
            recovered_at=first + timedelta(seconds=301),
        )
        self.assertEqual(timeout.uav.phase, "resume_timeout")
        self.assertEqual(timeout.uav.service, "failed")
        self.assertEqual(timeout.uav.file, "ready")
        self.assertIn("partial GPS", timeout.uav.error)

        completed = self.coordinator.stop_bind(state.mission_id)

        self.assertEqual(completed.overall_state, "completed_with_warning")
        self.assertEqual(completed.uav.mission_id, completed.usrp.mission_id)
        self.assertEqual(completed.usrp.file, "uploaded")
        self.assertIn("partial GPS", completed.uav.error)

    def test_stop_failure_restart_then_retry_reaches_terminal_completion(self) -> None:
        self.backend.stop_results = [RuntimeError("Raspberry Pi stop timeout")]
        state = self.coordinator.start_bind("usrp")

        first = self.coordinator.stop_bind(state.mission_id)

        self.assertEqual(first.overall_state, "stopping")
        self.assertEqual(first.uav.phase, "stopped")
        self.assertEqual(first.uav.service, "stopped")
        self.assertEqual(first.usrp.phase, "stop_failed")
        self.assertEqual(first.usrp.service, "presumed_running")

        restarted_backend = _UsrpBackendFake()
        restarted = self._new_coordinator(backend=restarted_backend)
        restored = restarted.store.load(state.mission_id)
        self.assertEqual(restored.usrp.phase, "stop_failed")
        self.assertEqual(restored.uav.service, "stopped")

        retried = restarted.retry_stop_usrp(state.mission_id)

        self.assertEqual(retried.usrp.phase, "stopped")
        self.assertEqual(retried.usrp.service, "stopped")
        self.assertEqual(retried.usrp.file, "uploaded")
        self.assertEqual(retried.overall_state, "completed")

    def test_upload_retries_survive_restart_and_manual_retry_completes_mission(self) -> None:
        from app.capture_jobs import _parse_timestamp

        state = self.coordinator.start_bind("usrp")
        self.backend.stop_results = [{
            "success": True,
            "service_state": "stopped",
            "mission_state": {
                "mission_id": state.mission_id,
                "state": "stopped",
                "upload_state": "upload_pending",
            },
        }]
        # The first item is the immediate upload; the next three failures are
        # dispatched by the public retry scheduler at +5, +15, and +30 sec.
        self.backend.upload_results = [
            {"upload_state": "upload_pending", "error": "network down"},
            {"upload_state": "upload_pending", "error": "network down"},
            {"upload_state": "upload_pending", "error": "network down"},
            {"upload_state": "upload_pending", "error": "network down"},
        ]
        stopped = self.coordinator.stop_bind(state.mission_id)
        self._wait_for(
            lambda: self.coordinator.store.load(state.mission_id).usrp.upload_retry_state == "waiting"
        )
        waiting = self.coordinator.store.load(state.mission_id)
        self.assertEqual(stopped.mission_id, state.mission_id)
        self.assertEqual(self.backend.upload_calls, ["usrp"])
        self.assertEqual(waiting.usrp.upload_retry_attempt, 1)
        self.assertEqual(waiting.overall_state, "finalizing")
        self.assertEqual(
            _parse_timestamp(waiting.usrp.upload_retry_next_attempt_at),
            self.clock.value + timedelta(seconds=5),
        )

        self.clock.advance(seconds=5)
        self.assertEqual(self.coordinator.process_upload_retries(), 1)
        self._wait_for(
            lambda: self.coordinator.store.load(state.mission_id).usrp.upload_retry_state == "waiting"
        )
        retry_2 = self.coordinator.store.load(state.mission_id)
        self.assertEqual(self.backend.upload_calls, ["usrp", "usrp"])
        self.assertEqual(retry_2.usrp.upload_retry_attempt, 2)
        self.assertEqual(
            _parse_timestamp(retry_2.usrp.upload_retry_next_attempt_at),
            self.clock.value + timedelta(seconds=15),
        )

        self.clock.advance(seconds=15)
        self.assertEqual(self.coordinator.process_upload_retries(), 1)
        self._wait_for(
            lambda: self.coordinator.store.load(state.mission_id).usrp.upload_retry_state == "waiting"
            and self.coordinator.store.load(state.mission_id).usrp.upload_retry_attempt == 3
        )
        retry_3 = self.coordinator.store.load(state.mission_id)
        self.assertEqual(self.backend.upload_calls, ["usrp", "usrp", "usrp"])
        self.assertEqual(
            _parse_timestamp(retry_3.usrp.upload_retry_next_attempt_at),
            self.clock.value + timedelta(seconds=30),
        )

        self.clock.advance(seconds=30)
        self.assertEqual(self.coordinator.process_upload_retries(), 1)
        self._wait_for(
            lambda: self.coordinator.store.load(state.mission_id).usrp.upload_retry_state == "exhausted"
        )
        exhausted = self.coordinator.store.load(state.mission_id)
        self.assertEqual(self.backend.upload_calls, ["usrp", "usrp", "usrp", "usrp"])
        self.assertEqual(exhausted.usrp.upload_retry_attempt, 3)
        self.assertEqual(exhausted.usrp.file, "upload_pending")
        self.assertEqual(exhausted.overall_state, "finalizing")

        # Rebuild the coordinator from capture.json, then recover with the
        # public Manual Retry operation without resetting automatic history.
        restarted_backend = _UsrpBackendFake()
        restarted_backend.upload_results = [{"upload_state": "uploaded"}]
        restarted = self._new_coordinator(backend=restarted_backend)
        restored = restarted.store.load(state.mission_id)
        self.assertEqual(restored.usrp.upload_retry_state, "exhausted")
        self.assertEqual(restored.usrp.upload_retry_attempt, 3)
        self.assertEqual(restored.usrp.file, "upload_pending")
        manual = restarted.retry_usrp_upload(state.mission_id)
        self._wait_for(
            lambda: restarted.store.load(state.mission_id).usrp.file == "uploaded"
        )
        self.assertEqual(manual.usrp.upload_state, "running")
        final = restarted.store.load(state.mission_id)
        self.assertEqual(restarted_backend.upload_calls, ["usrp"])
        self.assertEqual(final.usrp.upload_retry_attempt, 3)
        self.assertEqual(final.overall_state, "completed")


if __name__ == "__main__":
    unittest.main()
