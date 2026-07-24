import asyncio
import hashlib
import importlib.util
from io import BytesIO
import json
import sys
import threading
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch


class CaptureStoreTests(unittest.TestCase):
    def setUp(self):
        repo_root = Path(__file__).resolve().parents[2]
        self.root = repo_root / ".test_tmp" / uuid.uuid4().hex
        self.root.mkdir(parents=True)

    def test_old_capture_json_loads_child_state_defaults(self):
        from app.capture_jobs import CaptureStore

        store = CaptureStore(self.root)
        state = store.create(bind=False, selected_usrp_mode="test", target="uav")
        path = store.path(state.mission_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        for child in (payload["uav"], payload["usrp"]):
            for key in (
                "last_attempt_at",
                "last_success_at",
                "refresh_state",
                "consecutive_failures",
                "next_retry_at",
            ):
                child.pop(key, None)
        path.write_text(json.dumps(payload), encoding="utf-8")

        loaded = store.load(state.mission_id)

        self.assertIsNone(loaded.uav.last_attempt_at)
        self.assertIsNone(loaded.uav.last_success_at)
        self.assertEqual(loaded.uav.refresh_state, "idle")
        self.assertEqual(loaded.uav.consecutive_failures, 0)
        self.assertIsNone(loaded.uav.next_retry_at)

    def test_store_round_trips_capture_state(self):
        from app.capture_jobs import CaptureStore

        store = CaptureStore(self.root)
        state = store.create(bind=False, selected_usrp_mode="test", target="uav")

        loaded = store.load(state.mission_id)

        self.assertEqual(loaded, state)
        self.assertTrue((self.root / state.mission_id / "capture.json").exists())

    def test_partial_failure_does_not_stop_other_child(self):
        from app.capture_jobs import CaptureStore

        store = CaptureStore(self.root)
        state = store.create(bind=True, selected_usrp_mode="usrp", target="bind")
        state.uav.service = "running"
        state.uav.file = "recording"
        state.usrp.service = "failed"
        state.usrp.file = "failed"

        store.save(state)
        loaded = store.load(state.mission_id)

        self.assertEqual(loaded.overall_state, "partial_failed")
        self.assertEqual(loaded.uav.service, "running")

    def test_completed_requires_terminal_children(self):
        from app.capture_jobs import CaptureStore

        store = CaptureStore(self.root)
        state = store.create(bind=True, selected_usrp_mode="test", target="bind")
        state.uav.service = "stopped"
        state.uav.file = "ready"
        state.usrp.service = "stopped"
        state.usrp.file = "uploaded"

        store.save(state)

        self.assertEqual(store.load(state.mission_id).overall_state, "completed")


class FakeProcess:
    def __init__(self, pid: int = 4321):
        self.pid = pid
        self.terminated = False
        self.killed = False

    def poll(self):
        return 0 if self.terminated or self.killed else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


class OverlapDetectingStore:
    def __init__(self, inner):
        self._inner = inner
        self._guard = threading.Lock()
        self._write_lock = threading.Lock()
        self._first_save_entered = threading.Event()
        self._release_first_save = threading.Event()
        self._second_save_attempted = threading.Event()
        self._armed = False

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def arm(self):
        with self._guard:
            self._armed = True
            self._first_save_entered.clear()
            self._release_first_save.clear()
            self._second_save_attempted.clear()

    def wait_for_first_save(self, timeout):
        return self._first_save_entered.wait(timeout)

    def wait_for_second_attempt(self, timeout):
        return self._second_save_attempted.wait(timeout)

    def release_first_save(self):
        self._release_first_save.set()

    def save(self, state):
        with self._guard:
            armed = self._armed
        if not armed:
            return self._inner.save(state)
        if not self._write_lock.acquire(blocking=False):
            self._second_save_attempted.set()
            raise AssertionError("concurrent save detected")
        try:
            if not self._first_save_entered.is_set():
                self._first_save_entered.set()
                self._release_first_save.wait()
            return self._inner.save(state)
        finally:
            self._write_lock.release()


class IndependentUavTests(unittest.TestCase):
    def setUp(self):
        repo_root = Path(__file__).resolve().parents[2]
        self.root = repo_root / ".test_tmp" / uuid.uuid4().hex
        self.root.mkdir(parents=True)

    def _coordinator(self):
        from app.capture_jobs import CaptureCoordinator, CaptureStore

        self.process = FakeProcess()
        self.run_command = Mock(return_value=Mock(returncode=0, stdout="", stderr=""))
        self.popen = Mock(return_value=self.process)
        return CaptureCoordinator(
            CaptureStore(self.root),
            repo_root=Path(__file__).resolve().parents[2],
            run_command=self.run_command,
            popen_factory=self.popen,
        )

    def test_uav_start_works_without_raspi(self):
        coordinator = self._coordinator()

        state = coordinator.start_uav()

        self.assertEqual(state.uav.service, "running")
        self.assertEqual(state.uav.file, "recording")
        self.assertEqual(state.usrp.service, "idle")
        check_command = self.run_command.call_args_list[0].args[0]
        self.assertIn("--check", check_command)

    def test_uav_stop_waits_for_process_and_marks_file_ready(self):
        coordinator = self._coordinator()
        state = coordinator.start_uav()

        stopped = coordinator.stop_uav(state.mission_id)

        self.assertTrue(self.process.terminated)
        self.assertEqual(stopped.uav.service, "stopped")
        self.assertEqual(stopped.uav.file, "ready")

    def test_second_uav_job_is_rejected(self):
        from app.capture_jobs import CaptureConflictError

        coordinator = self._coordinator()
        coordinator.start_uav()

        with self.assertRaises(CaptureConflictError):
            coordinator.start_uav()

    def test_status_marks_stale_stopping_uav_failed_after_backend_restart(self):
        from app.capture_jobs import CaptureCoordinator

        coordinator = self._coordinator()
        state = coordinator.start_uav()
        current = coordinator.store.load(state.mission_id)
        current.uav.service = "stopping"
        current.uav.file = "finalizing"
        coordinator.store.save(current)

        restarted = CaptureCoordinator(
            coordinator.store,
            repo_root=Path(__file__).resolve().parents[2],
            run_command=self.run_command,
            popen_factory=self.popen,
        )

        dashboard = restarted.status("test")

        self.assertEqual(restarted._uav_processes, {})
        self.assertEqual(dashboard.uav.mission_id, state.mission_id)
        self.assertNotEqual(dashboard.uav.service, "stopping")
        self.assertNotEqual(dashboard.uav.file, "finalizing")
        self.assertEqual(dashboard.uav.service, "failed")
        self.assertEqual(dashboard.uav.file, "failed")
        self.assertIn("owned", dashboard.uav.error.lower())
        self.assertIn("backend", dashboard.uav.error.lower())


class Ap3CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = Path(__file__).resolve().parents[2] / "tools" / "ap3_to_gps_csv.py"
        spec = importlib.util.spec_from_file_location("ap3_to_gps_csv_test", script)
        cls.module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        fake_pymavlink = types.ModuleType("pymavlink")
        fake_pymavlink.mavutil = Mock()
        with patch.dict(sys.modules, {"pymavlink": fake_pymavlink}):
            spec.loader.exec_module(cls.module)

    def test_parse_args_supports_readiness_check(self):
        with patch.object(sys, "argv", ["ap3_to_gps_csv.py", "--check"]):
            args = self.module.parse_args()

        self.assertTrue(args.check)

    def test_uses_bundled_adb(self):
        self.assertTrue(self.module.ADB.exists(), self.module.ADB)

    def test_simulator_bridge_uses_bundled_adb(self):
        script = Path(__file__).resolve().parents[2] / "tools" / "ap3_to_simulator.py"
        spec = importlib.util.spec_from_file_location("ap3_to_simulator_test", script)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        fake_pymavlink = types.ModuleType("pymavlink")
        fake_pymavlink.mavutil = Mock()
        with patch.dict(sys.modules, {"pymavlink": fake_pymavlink}):
            spec.loader.exec_module(module)

        self.assertTrue(module.ADB.exists(), module.ADB)

    def test_check_mode_forwards_authorized_device(self):
        with patch.object(self.module, "has_authorized_device", return_value=True):
            with patch.object(self.module, "run_adb_forward") as forward:
                result = self.module.check_device(local_port=15760, remote_port=5760)

        self.assertTrue(result)
        forward.assert_called_once_with(15760, 5760)

    def test_gps_csv_header_declares_altitude_mode(self):
        path = Path(__file__).resolve().parents[2] / ".test_tmp" / f"gps-{uuid.uuid4().hex}.csv"
        self.module.ensure_csv(path)
        self.assertEqual(path.read_text(encoding="utf-8").splitlines()[0], "time_stamp,lat,lon,alt,alt_mode")

    def test_simulator_payload_declares_altitude_mode(self):
        script = Path(__file__).resolve().parents[2] / "tools" / "ap3_to_simulator.py"
        spec = importlib.util.spec_from_file_location("ap3_to_simulator_payload_test", script)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        fake_pymavlink = types.ModuleType("pymavlink")
        fake_pymavlink.mavutil = Mock()
        with patch.dict(sys.modules, {"pymavlink": fake_pymavlink}):
            spec.loader.exec_module(module)

        msg = types.SimpleNamespace(lat=240000000, lon=1210000000, alt=125000, relative_alt=25000)
        payload = module.gps_payload(msg, "amsl", "device", "Device")
        self.assertEqual(payload["alt"], 125.0)
        self.assertEqual(payload["alt_mode"], "amsl")


class StartupScriptTests(unittest.TestCase):
    def test_gps_csv_requires_explicit_switch(self):
        script = (
            Path(__file__).resolve().parents[2] / "start.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("$enableGpsCsv = $GpsCsv -and -not $NoGpsCsv", script)

    def test_backend_uses_bundled_adb(self):
        from app import main

        self.assertTrue(main.ADB_EXE.exists(), main.ADB_EXE)

    def test_startup_port_check_does_not_require_admin(self):
        script = (
            Path(__file__).resolve().parents[2] / "start.ps1"
        ).read_text(encoding="utf-8")

        self.assertNotIn("Get-NetTCPConnection", script)
        self.assertIn("netstat -ano -p TCP", script)


class UsrpRecoveryTests(unittest.TestCase):
    def test_status_disconnect_reports_presumed_running(self):
        from app.capture_jobs import CaptureCoordinator, CaptureStore

        repo_root = Path(__file__).resolve().parents[2]
        root = repo_root / ".test_tmp" / uuid.uuid4().hex
        root.mkdir(parents=True)
        store = CaptureStore(root)
        state = store.create(
            bind=False,
            selected_usrp_mode="usrp",
            target="usrp",
        )
        state.usrp.connection = "ready"
        state.usrp.service = "running"
        state.usrp.file = "recording"
        store.save(state)
        backend = Mock()
        backend.get_capture_job.side_effect = RuntimeError("SSH timeout")
        coordinator = CaptureCoordinator(
            store,
            repo_root=repo_root,
            usrp_backend=backend,
        )

        recovered = coordinator.refresh_usrp(state.mission_id)

        self.assertEqual(recovered.usrp.connection, "offline")
        self.assertEqual(recovered.usrp.service, "presumed_running")
        self.assertEqual(recovered.usrp.file, "recording")


class BindCoordinatorTests(unittest.TestCase):
    def setUp(self):
        from app.capture_jobs import CaptureCoordinator, CaptureStore

        self.repo_root = Path(__file__).resolve().parents[2]
        root = self.repo_root / ".test_tmp" / uuid.uuid4().hex
        root.mkdir(parents=True)
        self.process = FakeProcess()
        self.run_command = Mock(return_value=Mock(returncode=0, stdout="", stderr=""))
        self.popen = Mock(return_value=self.process)
        self.backend = Mock()
        self.backend.RemoteMission = lambda **kwargs: kwargs
        self.backend.get_drone_status.return_value = {
            "success": True,
            "service_state": "stopped",
        }
        self.backend.start_capture_job.return_value = {
            "success": True,
            "service_state": "running",
            "mission_state": {
                "state": "running",
                "upload_state": "recording",
            },
        }
        self.backend.stop_capture_job.return_value = {
            "success": True,
            "service_state": "stopped",
            "mission_state": {
                "state": "stopped",
                "upload_state": "uploaded",
            },
        }
        self.coordinator = CaptureCoordinator(
            CaptureStore(root),
            repo_root=self.repo_root,
            run_command=self.run_command,
            popen_factory=self.popen,
            usrp_backend=self.backend,
        )

    def test_bind_start_preflights_both_before_launching(self):
        from app.capture_jobs import CaptureUnavailableError

        self.backend.get_drone_status.side_effect = RuntimeError("SSH timeout")

        with self.assertRaises(CaptureUnavailableError):
            self.coordinator.start_bind("test")

        self.popen.assert_not_called()
        self.backend.start_capture_job.assert_not_called()

    def test_bind_start_shares_mission_id(self):
        state = self.coordinator.start_bind("usrp")

        self.assertTrue(state.bind)
        self.assertEqual(state.uav.mission_id, state.mission_id)
        self.assertEqual(state.usrp.mission_id, state.mission_id)
        self.assertEqual(state.uav.service, "running")
        self.assertEqual(state.usrp.service, "running")
        remote = self.backend.start_capture_job.call_args.args[1]
        self.assertEqual(remote["work_dir"], "/home/user/rx_sampling")
        self.assertEqual(remote["noise_csv"], "/home/user/rx_sampling/noise.csv")

    def test_bind_child_failure_preserves_other_child(self):
        self.backend.start_capture_job.side_effect = RuntimeError("systemctl failed")

        state = self.coordinator.start_bind("usrp")

        self.assertEqual(state.overall_state, "partial_failed")
        self.assertEqual(state.uav.service, "running")
        self.assertEqual(state.usrp.service, "failed")

    def test_independent_usrp_launch_failure_marks_state_failed(self):
        from app.capture_jobs import CaptureUnavailableError

        self.backend.start_capture_job.side_effect = RuntimeError("systemctl failed")

        with self.assertRaises(CaptureUnavailableError):
            self.coordinator.start_usrp("usrp")

        failed = self.coordinator.store.list()[-1]
        self.assertEqual(failed.usrp.service, "failed")
        self.assertEqual(failed.usrp.file, "failed")
        self.assertIn("systemctl failed", failed.usrp.error)

    def test_stop_all_waits_for_both_finalizers(self):
        state = self.coordinator.start_bind("test")

        stopped = self.coordinator.stop_bind(state.mission_id)

        self.assertEqual(stopped.uav.file, "ready")
        self.assertEqual(stopped.usrp.file, "uploaded")
        self.assertEqual(stopped.overall_state, "completed")

    def test_idle_status_is_local_only(self):
        state = self.coordinator.status("test")

        self.assertEqual(state.uav.connection, "unknown")
        self.assertEqual(state.usrp.connection, "unknown")
        self.backend.get_drone_status.side_effect = AssertionError("hardware call")
        self.backend.get_capture_job.side_effect = AssertionError("hardware call")
        self.run_command.side_effect = AssertionError("hardware call")

        state = self.coordinator.status("test")

        self.assertEqual(state.uav.connection, "unknown")
        self.assertEqual(state.usrp.connection, "unknown")
        self.backend.get_drone_status.assert_not_called()
        self.backend.get_capture_job.assert_not_called()
        self.run_command.assert_not_called()

    def test_status_keeps_persisted_last_known_state(self):
        from app.capture_jobs import CaptureCoordinator

        state = self.coordinator.store.create(
            bind=False, selected_usrp_mode="usrp", target="usrp",
            mission_id="last_known_state",
        )
        state.usrp.service = "presumed_running"
        state.usrp.file = "recording"
        state.usrp.last_success_at = "2026-06-24T00:00:00+00:00"
        state.usrp.last_attempt_at = "2026-06-24T00:00:01+00:00"
        self.coordinator.store.save(state)

        dashboard = self.coordinator.status("usrp")

        self.assertEqual(dashboard.usrp.service, "presumed_running")
        self.assertEqual(dashboard.usrp.last_success_at, "2026-06-24T00:00:00+00:00")
        self.assertEqual(dashboard.usrp.last_attempt_at, "2026-06-24T00:00:01+00:00")
        self.backend.get_capture_job.assert_not_called()

    def test_status_merges_simultaneous_independent_jobs(self):
        uav_state = self.coordinator.start_uav()
        usrp_state = self.coordinator.start_usrp("usrp")

        dashboard = self.coordinator.status("usrp")

        self.assertNotEqual(uav_state.mission_id, usrp_state.mission_id)
        self.assertEqual(dashboard.uav.mission_id, uav_state.mission_id)
        self.assertEqual(dashboard.usrp.mission_id, usrp_state.mission_id)
        self.assertEqual(dashboard.uav.service, "running")
        self.assertEqual(dashboard.usrp.service, "running")

    def test_status_marks_lost_local_process_failed_after_backend_restart(self):
        from app.capture_jobs import CaptureCoordinator

        state = self.coordinator.start_uav()
        restarted = CaptureCoordinator(
            self.coordinator.store,
            repo_root=self.repo_root,
            run_command=self.run_command,
            popen_factory=self.popen,
            usrp_backend=self.backend,
        )

        dashboard = restarted.status("test")

        self.assertEqual(dashboard.uav.mission_id, state.mission_id)
        self.assertEqual(dashboard.uav.service, "presumed_running")

    def test_status_does_not_mark_stopping_uav_as_lost_process(self):
        state = self.coordinator.start_bind("test")
        self.backend.get_capture_job.return_value = {
            "success": True,
            "service_state": "running",
            "mission_state": {
                "state": "running",
                "upload_state": "recording",
            },
        }
        current = self.coordinator.store.load(state.mission_id)
        current.uav.service = "stopping"
        current.uav.file = "finalizing"
        self.coordinator.store.save(current)
        self.process.terminate()

        dashboard = self.coordinator.status("test")

        self.assertEqual(dashboard.uav.service, "stopping")
        self.assertEqual(dashboard.uav.file, "finalizing")
        self.assertEqual(dashboard.uav.error, "")

    def test_status_surfaces_upload_pending_without_marking_completed(self):
        state = self.coordinator.store.create(
            bind=False, selected_usrp_mode="usrp", target="usrp",
            mission_id="upload_pending_status",
        )
        state.usrp.service = "stopped"
        state.usrp.file = "upload_pending"
        self.coordinator.store.save(state)

        dashboard = self.coordinator.status("usrp")

        self.assertEqual(dashboard.usrp.service, "stopped")
        self.assertEqual(dashboard.usrp.file, "upload_pending")
        self.assertEqual(dashboard.overall_state, "finalizing")
        self.assertNotEqual(dashboard.overall_state, "completed")

    def test_stop_bind_retries_pending_upload_on_second_stop(self):
        state = self.coordinator.start_bind("usrp")
        self.backend.stop_capture_job.side_effect = [
            {
                "success": True,
                "service_state": "stopped",
                "mission_state": {
                    "state": "stopped",
                    "upload_state": "upload_pending",
                },
            },
            {
                "success": True,
                "service_state": "stopped",
                "mission_state": {
                    "state": "stopped",
                    "upload_state": "uploaded",
                },
            },
        ]

        first = self.coordinator.stop_bind(state.mission_id)
        after_first = self.coordinator.store.load(state.mission_id)
        second = self.coordinator.stop_bind(state.mission_id)
        after_second = self.coordinator.store.load(state.mission_id)

        self.assertEqual(first.usrp.service, "stopped")
        self.assertEqual(first.usrp.file, "upload_pending")
        self.assertEqual(after_first.usrp.service, "stopped")
        self.assertEqual(after_first.usrp.file, "upload_pending")
        self.assertEqual(second.usrp.file, "uploaded")
        self.assertEqual(after_second.usrp.service, "stopped")
        self.assertEqual(after_second.usrp.file, "uploaded")
        self.assertEqual(after_second.overall_state, "completed")
        self.assertEqual(self.backend.stop_capture_job.call_count, 2)

    def test_stop_bind_does_not_block_noise_upload_ack_callback(self):
        state = self.coordinator.start_bind("usrp")
        callback_done = threading.Event()
        callback_errors = []
        callback_threads = []
        noise_path = self.coordinator.store.root / state.mission_id / "noise.csv"

        def ack_callback():
            try:
                self.coordinator.ack_noise_upload(
                    state.mission_id,
                    path=noise_path,
                    size=12,
                    sha256="deadbeef",
                )
            except Exception as exc:
                callback_errors.append(exc)
            finally:
                callback_done.set()

        def stop_side_effect(mode, mission_id):
            callback_thread = threading.Thread(target=ack_callback, daemon=True)
            callback_threads.append(callback_thread)
            callback_thread.start()
            if not callback_done.wait(timeout=0.2):
                callback_errors.append(
                    AssertionError("ack callback blocked by capture lock")
                )
            return {
                "success": True,
                "service_state": "stopped",
                "mission_state": {
                    "state": "stopped",
                    "upload_state": "uploaded",
                },
            }

        self.backend.stop_capture_job.side_effect = stop_side_effect

        stopped = self.coordinator.stop_bind(state.mission_id)

        for callback_thread in callback_threads:
            callback_thread.join(timeout=1)

        self.assertEqual(callback_errors, [])
        self.assertTrue(callback_done.is_set())
        self.assertEqual(stopped.usrp.file, "uploaded")
        self.assertEqual(stopped.overall_state, "completed")

    def test_stop_bind_and_status_do_not_write_capture_state_concurrently(self):
        store = OverlapDetectingStore(self.coordinator.store)
        self.coordinator.store = store
        state = self.coordinator.start_bind("test")
        self.backend.get_capture_job.return_value = {
            "success": True,
            "service_state": "running",
            "mission_state": {
                "state": "running",
                "upload_state": "recording",
            },
        }
        store.arm()
        errors = []
        status_started = threading.Event()

        def run_stop():
            try:
                self.coordinator.stop_bind(state.mission_id)
            except Exception as exc:
                errors.append(exc)

        def run_status():
            try:
                status_started.set()
                self.coordinator.status("test")
            except Exception as exc:
                errors.append(exc)

        stop_thread = threading.Thread(target=run_stop)
        stop_thread.start()
        self.assertTrue(store.wait_for_first_save(timeout=1))

        status_thread = threading.Thread(target=run_status)
        status_thread.start()
        try:
            self.assertTrue(status_started.wait(timeout=1))
            second_attempt_observed = store.wait_for_second_attempt(timeout=1)
            self.assertTrue(second_attempt_observed or status_thread.is_alive())
        finally:
            store.release_first_save()
            stop_thread.join(timeout=1)
            status_thread.join(timeout=1)

        self.assertFalse(stop_thread.is_alive())
        self.assertFalse(status_thread.is_alive())

        self.assertEqual(errors, [])


class CaptureApiTests(unittest.TestCase):
    def setUp(self):
        from app import main

        self.main = main

    def _post_json(self, path: str, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        messages: list[dict] = []
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "app": self.main.app,
        }
        asyncio.run(self.main.app(scope, receive, send))

        start = next(
            message for message in messages if message["type"] == "http.response.start"
        )
        chunks = [
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        ]
        payload = json.loads(b"".join(chunks).decode("utf-8"))
        return start["status"], payload

    def _state(self, target="bind"):
        from app.capture_jobs import CaptureState

        return CaptureState(
            mission_id="flight_api",
            target=target,
            bind=target == "bind",
            selected_usrp_mode="usrp",
            created_at="2026-06-24T00:00:00+00:00",
        )

    def test_bind_start_uses_shared_capture_endpoint(self):
        coordinator = Mock()
        coordinator.start_bind.return_value = self._state()

        with patch.object(self.main, "capture_coordinator", coordinator):
            response = asyncio.run(
                self.main.capture_bind_start_post(
                    self.main.CaptureStartRequest(
                        usrp_mode="usrp",
                        scene="NTPU",
                        map_type="iss",
                    )
                )
            )

        self.assertEqual(response.mission_id, "flight_api")
        coordinator.start_bind.assert_called_once_with(
            "usrp",
            scene="NTPU",
            map_type="iss",
        )

    def test_bind_start_maps_unavailable_dependency_to_503(self):
        from app.capture_jobs import CaptureUnavailableError
        from fastapi import HTTPException

        coordinator = Mock()
        coordinator.start_bind.side_effect = CaptureUnavailableError("SSH timeout")

        with patch.object(self.main, "capture_coordinator", coordinator):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    self.main.capture_bind_start_post(
                        self.main.CaptureStartRequest(usrp_mode="test")
                    )
                )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, "SSH timeout")

    def test_usrp_start_maps_launch_failure_to_503(self):
        from app.capture_jobs import CaptureUnavailableError

        coordinator = Mock()
        coordinator.start_usrp.side_effect = CaptureUnavailableError(
            "runtime dir missing"
        )

        with patch.object(self.main, "capture_coordinator", coordinator):
            status_code, payload = self._post_json(
                "/api/capture/usrp/start",
                {"usrp_mode": "usrp"},
            )

        self.assertEqual(status_code, 503)
        self.assertEqual(payload, {"detail": "runtime dir missing"})

    def test_independent_and_stop_all_routes_delegate_to_coordinator(self):
        coordinator = Mock()
        coordinator.start_uav.return_value = self._state("uav")
        coordinator.start_usrp.return_value = self._state("usrp")
        coordinator.stop_uav.return_value = self._state("uav")
        coordinator.stop_usrp.return_value = self._state("usrp")
        coordinator.stop_bind.return_value = self._state("bind")

        with patch.object(self.main, "capture_coordinator", coordinator):
            self.assertEqual(
                asyncio.run(self.main.capture_uav_start_post()).mission_id,
                "flight_api",
            )
            self.assertEqual(
                asyncio.run(
                    self.main.capture_usrp_start_post(
                        self.main.CaptureStartRequest(usrp_mode="test")
                    )
                ).mission_id,
                "flight_api",
            )
            self.assertEqual(
                asyncio.run(self.main.capture_uav_stop_post("flight_api")).mission_id,
                "flight_api",
            )
            self.assertEqual(
                asyncio.run(self.main.capture_usrp_stop_post("flight_api")).mission_id,
                "flight_api",
            )
            self.assertEqual(
                asyncio.run(self.main.capture_bind_stop_post("flight_api")).mission_id,
                "flight_api",
            )

        coordinator.start_uav.assert_called_once()
        coordinator.start_usrp.assert_called_once()
        coordinator.stop_bind.assert_called_once_with("flight_api")
    def test_capture_routes_use_stage2c_timeouts(self):
        from fastapi import BackgroundTasks

        coordinator = Mock()
        coordinator.reconcile_due.return_value = []
        calls = []
        timeouts = []

        async def fake_to_thread(func, *args, **kwargs):
            calls.append((func, args, kwargs))
            return "ok"

        async def fake_wait_for(awaitable, *, timeout):
            timeouts.append(timeout)
            return await awaitable

        with patch.object(self.main, "capture_coordinator", coordinator), \
             patch.object(self.main.asyncio, "to_thread", fake_to_thread), \
             patch.object(self.main.asyncio, "wait_for", fake_wait_for):
            self.assertEqual(
                asyncio.run(self.main.capture_status_get(BackgroundTasks())),
                "ok",
            )
            self.assertEqual(asyncio.run(self.main.capture_gps_refresh_post(None)), "ok")
            self.assertEqual(asyncio.run(self.main.capture_usrp_refresh_post("mission")), "ok")
            self.assertEqual(asyncio.run(self.main.capture_uav_start_post()), "ok")
            self.assertEqual(asyncio.run(self.main.capture_uav_stop_post("mission")), "ok")
            request = self.main.CaptureStartRequest(usrp_mode="test")
            self.assertEqual(asyncio.run(self.main.capture_usrp_start_post(request)), "ok")
            self.assertEqual(asyncio.run(self.main.capture_usrp_stop_post("mission")), "ok")
            self.assertEqual(asyncio.run(self.main.capture_bind_start_post(request)), "ok")
            self.assertEqual(asyncio.run(self.main.capture_bind_stop_post("mission")), "ok")

        self.assertEqual(
            timeouts,
            [
                self.main.CAPTURE_STATUS_TIMEOUT_SECONDS,
                self.main.CAPTURE_REFRESH_TIMEOUT_SECONDS,
                self.main.CAPTURE_REFRESH_TIMEOUT_SECONDS,
                self.main.CAPTURE_OPERATION_TIMEOUT_SECONDS,
                self.main.CAPTURE_OPERATION_TIMEOUT_SECONDS,
                self.main.CAPTURE_OPERATION_TIMEOUT_SECONDS,
                self.main.CAPTURE_OPERATION_TIMEOUT_SECONDS,
                self.main.CAPTURE_OPERATION_TIMEOUT_SECONDS,
                self.main.CAPTURE_OPERATION_TIMEOUT_SECONDS,
            ],
        )

    def test_capture_status_timeout_is_safe_and_logs_only_structured_fields(self):
        from fastapi import BackgroundTasks

        coordinator = Mock()
        warnings = []

        async def fake_to_thread(func, *args, **kwargs):
            return "unobserved"

        async def fake_wait_for(awaitable, *, timeout):
            awaitable.close()
            raise asyncio.TimeoutError("RASPI_PSW=secret https://user:token@example")

        with patch.object(self.main, "capture_coordinator", coordinator), \
             patch.object(self.main.asyncio, "to_thread", fake_to_thread), \
             patch.object(self.main.asyncio, "wait_for", fake_wait_for), \
             patch.object(self.main.logger, "warning", side_effect=lambda *a, **kw: warnings.append((a, kw))):
            response = asyncio.run(self.main.capture_status_get(BackgroundTasks()))

        self.assertEqual(response.status_code, 504)
        self.assertEqual(json.loads(response.body), {"detail": "Capture operation timed out"})
        self.assertEqual(len(warnings), 1)
        self.assertEqual(
            set(warnings[0][1]["extra"]),
            {"device", "mission_id", "attempt", "last_success", "next_retry", "exception_type"},
        )
        self.assertNotIn("secret", json.dumps(warnings[0]))

    def test_refresh_routes_delegate_none_and_map_unknown_missions_to_404(self):
        from app.capture_jobs import CaptureNotFoundError
        from fastapi import HTTPException

        coordinator = Mock()
        coordinator.refresh_gps.return_value = self._state("uav")
        coordinator.refresh_usrp.return_value = self._state("usrp")

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        async def fake_wait_for(awaitable, *, timeout):
            self.assertEqual(timeout, self.main.CAPTURE_REFRESH_TIMEOUT_SECONDS)
            return await awaitable

        with patch.object(self.main, "capture_coordinator", coordinator), \
             patch.object(self.main.asyncio, "to_thread", fake_to_thread), \
             patch.object(self.main.asyncio, "wait_for", fake_wait_for):
            asyncio.run(self.main.capture_gps_refresh_post(None))
            asyncio.run(self.main.capture_usrp_refresh_post("mission"))

        coordinator.refresh_gps.assert_called_once_with(None)
        coordinator.refresh_usrp.assert_called_once_with("mission")

        for route, argument, method in (
            (self.main.capture_gps_refresh_post, None, "refresh_gps"),
            (self.main.capture_usrp_refresh_post, "missing", "refresh_usrp"),
        ):
            coordinator.reset_mock()
            getattr(coordinator, method).side_effect = CaptureNotFoundError("missing")
            with patch.object(self.main, "capture_coordinator", coordinator):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(route(argument))
            self.assertEqual(raised.exception.status_code, 404)

    def test_capture_operation_timeouts_return_safe_504(self):
        coordinator = Mock()
        routes = (
            lambda: self.main.capture_uav_start_post(),
            lambda: self.main.capture_uav_stop_post("mission"),
            lambda: self.main.capture_usrp_start_post(self.main.CaptureStartRequest(usrp_mode="test")),
            lambda: self.main.capture_usrp_stop_post("mission"),
            lambda: self.main.capture_bind_start_post(self.main.CaptureStartRequest(usrp_mode="test")),
            lambda: self.main.capture_bind_stop_post("mission"),
        )

        async def fake_to_thread(func, *args, **kwargs):
            return "unobserved"

        async def fake_wait_for(awaitable, *, timeout):
            awaitable.close()
            self.assertEqual(timeout, self.main.CAPTURE_OPERATION_TIMEOUT_SECONDS)
            raise TimeoutError("private exception")

        with patch.object(self.main, "capture_coordinator", coordinator), \
             patch.object(self.main.asyncio, "to_thread", fake_to_thread), \
             patch.object(self.main.asyncio, "wait_for", fake_wait_for):
            for route in routes:
                response = asyncio.run(route())
                self.assertEqual(response.status_code, 504)
                self.assertEqual(json.loads(response.body), {"detail": "Capture operation timed out"})

    def test_refresh_warning_uses_snapshot_fields_without_exception_text(self):
        state = self._state("usrp")
        state.usrp.last_attempt_at = "2026-06-24T00:00:01+00:00"
        state.usrp.last_success_at = "2026-06-24T00:00:00+00:00"
        state.usrp.next_retry_at = "2026-06-24T00:00:06+00:00"
        warning = Mock()

        self.main._capture_refresh_warning(
            "usrp", "mission", RuntimeError("password=https://private?token=secret"), state,
            logger=warning,
        )

        warning.warning.assert_called_once()
        fields = warning.warning.call_args.kwargs["extra"]
        self.assertEqual(fields["device"], "usrp")
        self.assertEqual(fields["mission_id"], "mission")
        self.assertEqual(fields["attempt"], state.usrp.last_attempt_at)
        self.assertEqual(fields["last_success"], state.usrp.last_success_at)
        self.assertEqual(fields["next_retry"], state.usrp.next_retry_at)
        self.assertEqual(fields["exception_type"], "RuntimeError")
        self.assertNotIn("secret", json.dumps(warning.warning.call_args))



    def setUp(self):
        from app import main
        from app.capture_jobs import CaptureCoordinator, CaptureStore

        self.main = main
        self.repo_root = Path(__file__).resolve().parents[2]
        self.root = self.repo_root / ".test_tmp" / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.coordinator = CaptureCoordinator(
            CaptureStore(self.root),
            repo_root=self.repo_root,
            usrp_backend=Mock(),
        )
        self.state = self.coordinator.store.create(
            bind=False,
            selected_usrp_mode="usrp",
            target="usrp",
            mission_id="noise_upload",
        )
        self.state.usrp.connection = "ready"
        self.state.usrp.service = "stopped"
        self.state.usrp.file = "upload_pending"
        self.coordinator.store.save(self.state)

    def _upload_noise(
        self,
        payload: bytes,
        noise_size: int,
        noise_sha256: str,
    ) -> tuple[int, dict]:
        from fastapi import UploadFile

        response = asyncio.run(
            self.main.usrp_upload_noise_csv_post(
                mission_id="noise_upload",
                noise_size=noise_size,
                noise_sha256=noise_sha256,
                noise_file=UploadFile(BytesIO(payload), filename="noise.csv"),
            )
        )
        if isinstance(response, dict):
            return 200, response
        return response.status_code, json.loads(response.body.decode("utf-8"))

    def test_noise_upload_rejects_mismatched_size_and_hash(self):
        payload = b"time_stamp,noise_floor_db\n"

        with patch.object(self.main, "INCOMING_CSV_DIR", self.root):
            with patch.object(self.main, "capture_coordinator", self.coordinator):
                status_code, response = self._upload_noise(
                    payload,
                    noise_size=1,
                    noise_sha256="bad",
                )

        self.assertEqual(status_code, 422)
        self.assertEqual(
            self.coordinator.store.load("noise_upload").usrp.file,
            "upload_pending",
        )

    def test_valid_noise_upload_completes_usrp_child(self):
        payload = b"time_stamp,noise_floor_db\n2026-06-24T00:00:00, -42.0\n"

        with patch.object(self.main, "INCOMING_CSV_DIR", self.root):
            with patch.object(self.main, "capture_coordinator", self.coordinator):
                status_code, response = self._upload_noise(
                    payload,
                    noise_size=len(payload),
                    noise_sha256=hashlib.sha256(payload).hexdigest(),
                )

        self.assertEqual(status_code, 200)
        self.assertEqual(response["capture"]["usrp"]["file"], "uploaded")
        self.assertEqual(
            (self.root / "noise_upload" / "noise.csv").read_bytes(),
            payload,
        )


class ReconcileStage2BTests(BindCoordinatorTests):
    def test_reconcile_retry_schedule_uses_injected_clock(self):
        from datetime import datetime, timedelta, timezone

        state = self.coordinator.store.create(bind=False, selected_usrp_mode="usrp", target="usrp", mission_id="retry_schedule")
        clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        self.coordinator.now = lambda: clock[0]
        self.backend.get_capture_job.side_effect = RuntimeError("offline")
        expected = [5, 10, 20, 30, 30]
        for delay in expected:
            self.coordinator.reconcile_usrp(state.mission_id, force=True)
            current = self.coordinator.store.load(state.mission_id)
            due = datetime.fromisoformat(current.usrp.next_retry_at)
            self.assertEqual((due - clock[0]).total_seconds(), delay)
            calls = self.backend.get_capture_job.call_count
            clock[0] = due - timedelta(seconds=1)
            self.coordinator.reconcile_usrp(state.mission_id)
            self.assertEqual(self.backend.get_capture_job.call_count, calls)
            clock[0] = due
        self.backend.get_capture_job.side_effect = None
        self.backend.get_capture_job.return_value = {"service_state": "running", "mission_state": {"upload_state": "recording"}}
        self.coordinator.reconcile_usrp(state.mission_id)
        current = self.coordinator.store.load(state.mission_id)
        self.assertEqual(current.usrp.consecutive_failures, 0)
        self.assertIsNone(current.usrp.next_retry_at)
        self.assertEqual(current.usrp.refresh_state, "idle")
        self.assertEqual(current.usrp.last_success_at, clock[0].isoformat())

    def test_reconcile_offline_preserves_active_file_phases(self):
        state = self.coordinator.store.create(bind=False, selected_usrp_mode="usrp", target="usrp", mission_id="offline_active")
        self.backend.get_capture_job.side_effect = RuntimeError("offline")
        for phase in ("recording", "finalizing", "upload_pending"):
            current = self.coordinator.store.load(state.mission_id)
            current.usrp.service = "presumed_running"
            current.usrp.file = phase
            self.coordinator.store.save(current)
            result = self.coordinator.reconcile_usrp(state.mission_id, force=True)
            self.assertEqual(result.usrp.service, "presumed_running")
            self.assertEqual(result.usrp.file, phase)
            self.assertEqual(result.usrp.connection, "offline")

    def test_force_reconcile_second_call_returns_promptly(self):
        import time
        entered = threading.Event()
        release = threading.Event()
        self.backend.get_capture_job.side_effect = lambda *args: (entered.set(), release.wait(2), {"service_state": "running"})[2]
        state = self.coordinator.store.create(bind=False, selected_usrp_mode="usrp", target="usrp", mission_id="force_once")
        state.target = "usrp"
        self.coordinator.store.save(state)
        first = threading.Thread(target=self.coordinator.reconcile_usrp, args=(state.mission_id,), kwargs={"force": True})
        first.start(); self.assertTrue(entered.wait(1))
        started = time.monotonic(); snapshot = self.coordinator.reconcile_usrp(state.mission_id, force=True); elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.5); self.assertEqual(snapshot.usrp.refresh_state, "checking")
        release.set(); first.join(2)
        self.assertEqual(self.backend.get_capture_job.call_count, 1)

    def test_reconcile_remote_call_does_not_hold_main_lock(self):
        entered = threading.Event(); release = threading.Event()
        self.backend.get_capture_job.side_effect = lambda *args: (entered.set(), release.wait(2), {"service_state": "running"})[2]
        state = self.coordinator.store.create(bind=False, selected_usrp_mode="usrp", target="usrp", mission_id="nonblocking")
        thread = threading.Thread(target=self.coordinator.reconcile_usrp, args=(state.mission_id,), kwargs={"force": True}); thread.start(); self.assertTrue(entered.wait(1))
        done = threading.Event()
        threading.Thread(target=lambda: (self.coordinator.status(), done.set())).start()
        self.assertTrue(done.wait(1)); release.set(); thread.join(2)

    def test_stale_reconcile_cannot_overwrite_stop_or_upload_ack(self):
        entered = threading.Event(); release = threading.Event()
        self.backend.get_capture_job.side_effect = lambda *args: (entered.set(), release.wait(2), {"service_state": "running", "mission_state": {"upload_state": "recording"}})[2]
        state = self.coordinator.store.create(bind=False, selected_usrp_mode="usrp", target="usrp", mission_id="stale_ops")
        state.usrp.service = "running"; state.usrp.file = "recording"; self.coordinator.store.save(state)
        thread = threading.Thread(target=self.coordinator.reconcile_usrp, args=(state.mission_id,), kwargs={"force": True}); thread.start(); self.assertTrue(entered.wait(1))
        self.coordinator.ack_noise_upload(state.mission_id, path=Path("uploaded.csv"), size=1, sha256="x")
        release.set(); thread.join(2)
        current = self.coordinator.store.load(state.mission_id)
        self.assertEqual((current.usrp.service, current.usrp.file), ("stopped", "uploaded"))


    @classmethod
    def setUpClass(cls):
        script = Path(__file__).resolve().parents[2] / "tools" / "upload_noise_csv.py"
        spec = importlib.util.spec_from_file_location("upload_noise_csv_test", script)
        cls.module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(cls.module)

    def test_file_metadata_returns_size_and_sha256(self):
        repo_root = Path(__file__).resolve().parents[2]
        path = repo_root / ".test_tmp" / f"{uuid.uuid4().hex}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = b"time_stamp,noise_floor_db\n"
        path.write_bytes(data)

        metadata = self.module.file_metadata(path)

        self.assertEqual(metadata["noise_size"], str(len(data)))
        self.assertEqual(
            metadata["noise_sha256"],
            hashlib.sha256(data).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
