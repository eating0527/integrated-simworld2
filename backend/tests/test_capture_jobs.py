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
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch


class CaptureStoreTests(unittest.TestCase):
    def setUp(self):
        repo_root = Path(__file__).resolve().parents[2]
        self.root = repo_root / ".test_tmp" / uuid.uuid4().hex
        self.root.mkdir(parents=True)

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

    def test_uav_start_passes_optional_gps_sync_endpoint(self):
        coordinator = self._coordinator()

        with patch.dict(
            "os.environ",
            {
                "GPS_SYNC_API_URL": "http://192.168.1.20:8888/api/usrp/sync-gps-point",
                "GPS_SYNC_DEVICE_ID": "ap3-a",
                "GPS_SYNC_DEVICE_NAME": "AP3 A",
            },
        ):
            coordinator.start_uav()

        command = self.popen.call_args.args[0]
        self.assertIn("--sync-api-url", command)
        self.assertIn("http://192.168.1.20:8888/api/usrp/sync-gps-point", command)
        self.assertIn("--sync-device-id", command)
        self.assertIn("ap3-a", command)
        self.assertIn("--sync-device-name", command)
        self.assertIn("AP3 A", command)

    def test_usrp_remote_mission_prefers_multi_upload_urls(self):
        coordinator = self._coordinator()
        state = coordinator.store.create(
            bind=False,
            selected_usrp_mode="usrp",
            target="usrp",
            mission_id="noise_multi",
        )

        with patch.dict(
            "os.environ",
            {
                "USRP_UPLOAD_API_URL": "http://a.local:8888/api/usrp/upload-noise-csv",
                "USRP_UPLOAD_API_URLS": "http://a.local:8888/api/usrp/upload-noise-csv,https://backend.simworld.website/api/usrp/upload-noise-csv",
            },
        ):
            mission = coordinator._remote_mission(state, scene="NTPU", map_type="iss")

        self.assertEqual(
            mission.api_url,
            "http://a.local:8888/api/usrp/upload-noise-csv,https://backend.simworld.website/api/usrp/upload-noise-csv",
        )

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

    def test_format_csv_timestamp_preserves_noise_timezone_format(self):
        timestamp = datetime(2026, 7, 31, 15, 54, 32, 481000, tzinfo=timezone(timedelta(hours=8)))

        formatted = self.module.format_csv_timestamp(timestamp)

        self.assertEqual(formatted, "2026-07-31T15:54:32.481000+08:00")

    def test_gps_sync_client_posts_json_payload(self):
        response = Mock()
        response.__enter__ = Mock(return_value=Mock(status=200))
        response.__exit__ = Mock(return_value=None)
        client = self.module.GpsSyncClient(
            api_url="http://192.168.1.20:8888/api/usrp/sync-gps-point",
            mission_id="flight_sync",
            device_id="ap3-a",
            device_name="AP3 A",
            device_type="uav",
            timeout=2.0,
            log_every=5.0,
        )

        with patch.object(self.module.urllib.request, "urlopen", return_value=response) as urlopen:
            client.send(
                timestamp="2026-07-29T10:00:00.000",
                lat=24.943476,
                lon=121.370054,
                alt=12.5,
                alt_mode="relative",
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "http://192.168.1.20:8888/api/usrp/sync-gps-point")
        self.assertEqual(payload["mission_id"], "flight_sync")
        self.assertEqual(payload["device_id"], "ap3-a")
        self.assertEqual(payload["lat"], 24.943476)

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

    def test_startup_noap3_queries_incoming_missions(self):
        script = (
            Path(__file__).resolve().parents[2] / "start.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("function Show-IncomingMissionSummary", script)
        self.assertIn("/api/usrp/gps-sync/missions?limit=5", script)
        self.assertIn("if ($NoAP3)", script)


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

    def test_idle_status_reports_independent_readiness(self):
        state = self.coordinator.status("test")

        self.assertEqual(state.uav.connection, "ready")
        self.assertEqual(state.usrp.connection, "ready")
        self.backend.get_drone_status.assert_called_with("test")

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
        self.assertEqual(dashboard.uav.service, "failed")
        self.assertIn("process", dashboard.uav.error.lower())

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
        state = self.coordinator.start_usrp("usrp")
        self.backend.get_capture_job.return_value = {
            "success": True,
            "service_state": "stopped",
            "mission_state": {
                "state": "stopped",
                "upload_state": "upload_pending",
            },
        }

        dashboard = self.coordinator.status("usrp")

        self.assertEqual(dashboard.usrp.service, "stopped")
        self.assertEqual(dashboard.usrp.file, "upload_pending")
        self.assertEqual(dashboard.overall_state, "finalizing")
        self.assertNotEqual(dashboard.overall_state, "completed")

    def test_stop_bind_leaves_pending_upload_for_explicit_retry(self):
        state = self.coordinator.start_bind("usrp")
        self.backend.stop_capture_job.return_value = {
            "success": True,
            "service_state": "stopped",
            "mission_state": {
                "state": "stopped",
                "upload_state": "upload_pending",
            },
        }
        self.backend.retry_capture_upload.return_value = {
            "success": True,
            "service_state": "stopped",
            "mission_state": {
                "state": "stopped",
                "upload_state": "uploaded",
            },
        }

        first = self.coordinator.stop_bind(state.mission_id)
        after_first = self.coordinator.store.load(state.mission_id)
        second = self.coordinator.retry_usrp_upload(state.mission_id)
        after_second = self.coordinator.store.load(state.mission_id)

        self.assertEqual(first.usrp.service, "stopped")
        self.assertEqual(first.usrp.file, "upload_pending")
        self.assertEqual(after_first.usrp.file, "upload_pending")
        self.assertEqual(second.usrp.file, "uploaded")
        self.assertEqual(after_second.usrp.service, "stopped")
        self.assertEqual(after_second.usrp.file, "uploaded")
        self.assertEqual(after_second.overall_state, "completed")
        self.backend.stop_capture_job.assert_called_once_with("usrp", state.mission_id)
        self.backend.retry_capture_upload.assert_called_once_with("usrp", state.mission_id)

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


class NoiseUploadTests(unittest.TestCase):
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


class GpsSyncTests(unittest.TestCase):
    def setUp(self):
        from app import main

        self.main = main
        self.repo_root = Path(__file__).resolve().parents[2]
        self.root = self.repo_root / ".test_tmp" / uuid.uuid4().hex
        self.root.mkdir(parents=True)

    def test_sync_gps_point_appends_csv_and_log(self):
        point = self.main.GpsSyncPointRequest(
            mission_id="flight_sync",
            time_stamp="2026-07-29T10:00:00.000",
            lat=24.943476,
            lon=121.370054,
            alt=12.5,
            alt_mode="relative",
            device_id="ap3-a",
            device_name="AP3 A",
        )

        with patch.object(self.main, "INCOMING_CSV_DIR", self.root):
            response = asyncio.run(self.main.usrp_sync_gps_point_post(point))
            logs = asyncio.run(self.main.usrp_gps_sync_logs_get("flight_sync", limit=100))

        self.assertTrue(response["success"])
        csv_lines = (self.root / "flight_sync" / "gps.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(csv_lines[0], "time_stamp,lat,lon,alt,alt_mode")
        self.assertIn("2026-07-29T10:00:00.000,24.943476,121.370054,12.5,relative", csv_lines[1])
        self.assertEqual(logs["count"], 1)
        self.assertIn("mission=flight_sync", logs["lines"][0])
        self.assertIn("device=ap3-a", logs["lines"][0])

    def test_sync_gps_point_rejects_unsafe_mission_id(self):
        point = self.main.GpsSyncPointRequest(
            mission_id="../bad",
            time_stamp="2026-07-29T10:00:00.000",
            lat=24.0,
            lon=121.0,
        )

        response = asyncio.run(self.main.usrp_sync_gps_point_post(point))

        self.assertEqual(response.status_code, 422)

    def test_sync_missions_lists_recent_incoming_data(self):
        bundle = self.root / "flight_visible"
        bundle.mkdir(parents=True)
        (bundle / "gps.csv").write_text(
            "time_stamp,lat,lon,alt,alt_mode\n2026-07-29T10:00:00.000,24.0,121.0,10,relative\n",
            encoding="utf-8",
        )
        (bundle / "noise.csv").write_text("time_stamp,noise_floor_db\n", encoding="utf-8")
        (bundle / "gps_sync.log").write_text(
            "2026-07-29T10:00:01 mission=flight_visible device=ap3-a lat=24.0000000 lon=121.0000000 alt=10.00\n",
            encoding="utf-8",
        )

        with patch.object(self.main, "INCOMING_CSV_DIR", self.root):
            response = asyncio.run(self.main.usrp_gps_sync_missions_get(limit=10))

        self.assertTrue(response["success"])
        self.assertEqual(response["missions"][0]["mission_id"], "flight_visible")
        self.assertTrue(response["missions"][0]["has_gps"])
        self.assertTrue(response["missions"][0]["has_noise"])
        self.assertIn("mission=flight_visible", response["missions"][0]["last_log"])


class NoiseUploaderTests(unittest.TestCase):
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

    def test_parse_upload_urls_dedupes_comma_separated_values(self):
        urls = self.module.parse_upload_urls(
            "http://a/upload, https://b/upload",
            "http://a/upload",
        )

        self.assertEqual(urls, ["http://a/upload", "https://b/upload"])


if __name__ == "__main__":
    unittest.main()
