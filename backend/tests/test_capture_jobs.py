import asyncio
import hashlib
import importlib.util
import sys
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


class CaptureApiTests(unittest.TestCase):
    def setUp(self):
        from app import main

        self.main = main

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
        from fastapi import HTTPException

        coordinator = Mock()
        coordinator.start_usrp.side_effect = CaptureUnavailableError(
            "runtime dir missing"
        )

        with patch.object(self.main, "capture_coordinator", coordinator):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    self.main.capture_usrp_start_post(
                        self.main.CaptureStartRequest(usrp_mode="usrp")
                    )
                )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, "runtime dir missing")

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
        from fastapi.testclient import TestClient
        from app import main
        from app.capture_jobs import CaptureCoordinator, CaptureStore

        self.main = main
        self.client = TestClient(main.app)
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

    def test_noise_upload_rejects_mismatched_size_and_hash(self):
        payload = b"time_stamp,noise_floor_db\n"

        with patch.object(self.main, "INCOMING_CSV_DIR", self.root):
            with patch.object(self.main, "capture_coordinator", self.coordinator):
                response = self.client.post(
                    "/api/usrp/upload-noise-csv",
                    data={
                        "mission_id": "noise_upload",
                        "noise_size": "1",
                        "noise_sha256": "bad",
                    },
                    files={"noise_file": ("noise.csv", payload, "text/csv")},
                )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            self.coordinator.store.load("noise_upload").usrp.file,
            "upload_pending",
        )

    def test_valid_noise_upload_completes_usrp_child(self):
        payload = b"time_stamp,noise_floor_db\n2026-06-24T00:00:00, -42.0\n"

        with patch.object(self.main, "INCOMING_CSV_DIR", self.root):
            with patch.object(self.main, "capture_coordinator", self.coordinator):
                response = self.client.post(
                    "/api/usrp/upload-noise-csv",
                    data={
                        "mission_id": "noise_upload",
                        "noise_size": str(len(payload)),
                        "noise_sha256": hashlib.sha256(payload).hexdigest(),
                    },
                    files={"noise_file": ("noise.csv", payload, "text/csv")},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["capture"]["usrp"]["file"], "uploaded")
        self.assertEqual(
            (self.root / "noise_upload" / "noise.csv").read_bytes(),
            payload,
        )


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


if __name__ == "__main__":
    unittest.main()
