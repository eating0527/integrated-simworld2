import asyncio
import hashlib
import importlib.util
from io import BytesIO
import json
import sys
import threading
import time
import types
import unittest
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch


class GpsCsvSchemaTests(unittest.TestCase):
    def setUp(self):
        repo_root = Path(__file__).resolve().parents[2]
        self.root = repo_root / ".test_tmp" / uuid.uuid4().hex
        self.root.mkdir(parents=True)

    def test_ensure_writes_canonical_header_once_for_empty_file(self):
        from app.gps_csv import GPS_CSV_HEADER, ensure_gps_csv

        path = self.root / "nested" / "gps.csv"
        path.parent.mkdir(parents=True)
        path.write_text("", encoding="utf-8")

        ensure_gps_csv(path)
        ensure_gps_csv(path)

        self.assertEqual(path.read_text(encoding="utf-8").splitlines(), [GPS_CSV_HEADER])

    def test_append_preserves_canonical_file_without_duplicate_header(self):
        from app.gps_csv import GPS_CSV_HEADER, append_gps_row

        path = self.root / "gps.csv"
        path.write_text(
            f"{GPS_CSV_HEADER}\n2026-08-12T08:00:00+00:00,24.0,121.0,10,relative",
            encoding="utf-8",
        )

        append_gps_row(
            path,
            ["2026-08-12T08:00:01+00:00", 24.1, 121.1, 11, "relative"],
        )

        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines.count(GPS_CSV_HEADER), 1)
        self.assertEqual(len(lines), 3)
        self.assertIn("2026-08-12T08:00:00+00:00,24.0,121.0,10,relative", lines)
        self.assertIn("2026-08-12T08:00:01+00:00,24.1,121.1,11,relative", lines)

    def test_append_rejects_wrong_schema_without_changing_file(self):
        from app.gps_csv import GpsCsvSchemaError, append_gps_row

        path = self.root / "gps.csv"
        original = "time_stamp,lat,lon,alt\n2026-08-12T08:00:00+00:00,24.0,121.0,10\n"
        path.write_text(original, encoding="utf-8")

        with self.assertRaises(GpsCsvSchemaError):
            append_gps_row(
                path,
                ["2026-08-12T08:00:01+00:00", 24.1, 121.1, 11, "relative"],
            )

        self.assertEqual(path.read_text(encoding="utf-8"), original)


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

    def test_partial_failure_degrades_without_stopping_other_child(self):
        from app.capture_jobs import CaptureStore

        store = CaptureStore(self.root)
        state = store.create(bind=True, selected_usrp_mode="usrp", target="bind")
        state.uav.service = "running"
        state.uav.file = "recording"
        state.usrp.service = "failed"
        state.usrp.file = "failed"

        store.save(state)
        loaded = store.load(state.mission_id)

        self.assertEqual(loaded.overall_state, "degraded")
        self.assertEqual(loaded.uav.service, "running")

    def test_lifecycle_states_follow_mission_intent(self):
        from app.capture_jobs import CaptureStore

        cases = [
            ("starting", "starting", "recording", "idle", "none"),
            ("running", "running", "recording", "running", "recording"),
            ("stopping", "stopping", "finalizing", "running", "recording"),
            ("finalizing", "stopped", "ready", "stopped", "upload_pending"),
            ("completed", "stopped", "ready", "stopped", "uploaded"),
            ("completed_with_warning", "stopped", "ready", "failed", "failed"),
            ("failed", "failed", "failed", "failed", "failed"),
        ]
        for expected, uav_service, uav_file, usrp_service, usrp_file in cases:
            with self.subTest(expected=expected):
                store = CaptureStore(self.root / expected)
                state = store.create(
                    bind=True,
                    selected_usrp_mode="usrp",
                    target="bind",
                )
                state.started_at = "2026-06-24T00:01:00+00:00"
                state.uav.service = uav_service
                state.uav.file = uav_file
                state.usrp.service = usrp_service
                state.usrp.file = usrp_file

                store.save(state)

                self.assertEqual(state.overall_state, expected)

    def test_partial_gps_result_needs_a_successful_sibling_for_warning(self):
        from app.capture_jobs import CaptureStore

        store = CaptureStore(self.root)
        state = store.create(bind=True, selected_usrp_mode="usrp", target="bind")
        state.started_at = "2026-06-24T00:01:00+00:00"
        state.uav.service = "failed"
        state.uav.file = "ready"
        state.usrp.service = "stopped"
        state.usrp.file = "uploaded"

        store.save(state)

        self.assertEqual(state.overall_state, "completed_with_warning")

        state.usrp.service = "failed"
        state.usrp.file = "ready"
        store.save(state)
        self.assertEqual(state.overall_state, "failed")

    def test_failed_noise_with_successful_gps_completes_with_warning(self):
        from app.capture_jobs import CaptureStore

        store = CaptureStore(self.root)
        state = store.create(bind=True, selected_usrp_mode="usrp", target="bind")
        state.started_at = "2026-06-24T00:01:00+00:00"
        state.uav.service = "stopped"
        state.uav.file = "ready"
        state.usrp.service = "failed"
        state.usrp.file = "failed"

        store.save(state)

        self.assertEqual(state.overall_state, "completed_with_warning")

    def test_stop_intent_with_uncertain_result_remains_stopping(self):
        from app.capture_jobs import CaptureStore

        for phase in ("stopping", "stopping_service", "stop_failed"):
            with self.subTest(phase=phase):
                store = CaptureStore(self.root / phase)
                state = store.create(
                    bind=False,
                    selected_usrp_mode="usrp",
                    target="usrp",
                )
                state.started_at = "2026-06-24T00:01:00+00:00"
                state.usrp.phase = phase
                state.usrp.connection = "offline"
                state.usrp.service = "presumed_running"
                state.usrp.file = "finalizing"

                store.save(state)

                self.assertEqual(state.overall_state, "stopping")

    def test_runtime_reconciliation_is_degraded(self):
        from app.capture_jobs import CaptureStore

        store = CaptureStore(self.root)
        state = store.create(bind=True, selected_usrp_mode="usrp", target="bind")
        state.started_at = "2026-06-24T00:01:00+00:00"
        state.uav.service = "running"
        state.uav.file = "recording"
        state.usrp.phase = "reconciling"
        state.usrp.connection = "offline"
        state.usrp.service = "presumed_running"
        state.usrp.file = "recording"

        store.save(state)

        self.assertEqual(state.overall_state, "degraded")

    def test_presumed_running_without_stop_intent_is_degraded(self):
        from app.capture_jobs import CaptureStore

        store = CaptureStore(self.root)
        state = store.create(bind=False, selected_usrp_mode="usrp", target="usrp")
        state.started_at = "2026-06-24T00:01:00+00:00"
        state.usrp.phase = "recording"
        state.usrp.connection = "offline"
        state.usrp.service = "presumed_running"
        state.usrp.file = "recording"

        store.save(state)

        self.assertEqual(state.overall_state, "degraded")

    def test_uncertain_and_offline_active_missions_are_degraded(self):
        from app.capture_jobs import CaptureStore

        store = CaptureStore(self.root)
        state = store.create(bind=True, selected_usrp_mode="usrp", target="bind")
        state.started_at = "2026-06-24T00:01:00+00:00"
        state.uav.service = "running"
        state.uav.file = "recording"
        state.usrp.connection = "offline"
        state.usrp.service = "presumed_running"
        state.usrp.file = "recording"

        store.save(state)

        self.assertEqual(state.overall_state, "degraded")

    def test_single_child_uses_the_same_terminal_contract(self):
        from app.capture_jobs import CaptureStore

        cases = [
            ("completed", "stopped", "ready", "ready"),
            ("failed", "failed", "failed", "ready"),
            ("degraded", "presumed_running", "recording", "offline"),
            ("finalizing", "stopped", "upload_pending", "ready"),
        ]
        for expected, service, file_state, connection in cases:
            with self.subTest(expected=expected):
                store = CaptureStore(self.root / f"single-{expected}")
                state = store.create(
                    bind=False,
                    selected_usrp_mode="test",
                    target="uav",
                )
                state.started_at = "2026-06-24T00:01:00+00:00"
                state.uav.connection = connection
                state.uav.service = service
                state.uav.file = file_state

                store.save(state)

                self.assertEqual(state.overall_state, expected)

    def test_terminal_state_sets_finished_at_once(self):
        from app.capture_jobs import CaptureStore

        store = CaptureStore(self.root)
        state = store.create(bind=False, selected_usrp_mode="test", target="uav")
        state.started_at = "2026-06-24T00:01:00+00:00"
        state.uav.service = "failed"
        state.uav.file = "failed"

        store.save(state)
        finished_at = state.finished_at
        store.save(state)

        self.assertIsNotNone(finished_at)
        self.assertEqual(state.finished_at, finished_at)

    def test_legacy_partial_failed_is_accepted_but_never_persisted(self):
        from app.capture_jobs import CaptureStore

        payload = {
            "mission_id": "legacy",
            "target": "bind",
            "bind": True,
            "overall_state": "partial_failed",
            "created_at": "2026-06-24T00:00:00+00:00",
            "started_at": "2026-06-24T00:01:00+00:00",
            "uav": {"service": "running", "file": "recording"},
            "usrp": {"service": "failed", "file": "failed"},
        }
        path = self.root / "legacy" / "capture.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        store = CaptureStore(self.root)

        state = store.load("legacy")

        self.assertEqual(state.overall_state, "degraded")
        store.save(state)
        saved = json.loads(path.read_text())
        self.assertEqual(saved["overall_state"], "degraded")

    def test_persisted_unknown_phase_loads_as_canonical_unknown(self):
        from app.capture_jobs import CaptureStore

        payload = {
            "mission_id": "legacy-phase",
            "target": "uav",
            "bind": False,
            "created_at": "2026-06-24T00:00:00+00:00",
            "uav": {"phase": "future_phase"},
        }
        path = self.root / "legacy-phase" / "capture.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

        state = CaptureStore(self.root).load("legacy-phase")

        self.assertEqual(state.uav.phase, "unknown")

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

    def test_terminal_success_ignores_later_health_connection_change(self):
        from app.capture_jobs import CaptureStore

        store = CaptureStore(self.root)
        state = store.create(bind=False, selected_usrp_mode="test", target="uav")
        state.started_at = "2026-06-24T00:01:00+00:00"
        state.uav.connection = "offline"
        state.uav.service = "stopped"
        state.uav.file = "ready"

        store.save(state)

        self.assertEqual(state.overall_state, "completed")


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

    def test_uav_start_and_stop_use_canonical_gps_schema(self):
        coordinator = self._coordinator()

        state = coordinator.start_uav()
        path = Path(state.uav.path)
        stopped = coordinator.stop_uav(state.mission_id)

        self.assertEqual(
            path.read_text(encoding="utf-8").splitlines()[0],
            "time_stamp,lat,lon,alt,alt_mode",
        )
        self.assertEqual(stopped.uav.service, "stopped")
        self.assertEqual(stopped.uav.file, "ready")

    def test_uav_stop_rejects_wrong_gps_schema(self):
        coordinator = self._coordinator()
        state = coordinator.start_uav()
        path = Path(state.uav.path)
        original = "time_stamp,lat,lon,alt\n2026-08-12T08:00:00+00:00,24.0,121.0,10\n"
        path.write_text(original, encoding="utf-8")

        stopped = coordinator.stop_uav(state.mission_id)

        self.assertEqual(stopped.uav.service, "failed")
        self.assertEqual(stopped.uav.file, "failed")
        self.assertIn("gps.csv header must be", stopped.uav.error)
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_second_uav_job_is_rejected(self):
        from app.capture_jobs import CaptureConflictError

        coordinator = self._coordinator()
        coordinator.start_uav()

        with self.assertRaises(CaptureConflictError):
            coordinator.start_uav()

    def test_independent_uav_rejects_bound_noise_that_is_still_unresolved(self):
        from app.capture_jobs import CaptureConflictError

        coordinator = self._coordinator()
        bound = coordinator.store.create(
            bind=True,
            selected_usrp_mode="test",
            target="bind",
            mission_id="bound-noise-active",
        )
        bound.started_at = "2026-08-12T00:00:00+00:00"
        bound.uav.service = "stopped"
        bound.uav.file = "ready"
        bound.usrp.service = "running"
        bound.usrp.file = "recording"
        coordinator.store.save(bound)

        with self.assertRaises(CaptureConflictError):
            coordinator.start_uav()

        self.run_command.assert_not_called()

    def test_independent_usrp_rejects_bound_gps_that_is_still_unresolved(self):
        from app.capture_jobs import CaptureConflictError

        coordinator = self._coordinator()
        bound = coordinator.store.create(
            bind=True,
            selected_usrp_mode="test",
            target="bind",
            mission_id="bound-gps-active",
        )
        bound.started_at = "2026-08-12T00:00:00+00:00"
        bound.uav.service = "running"
        bound.uav.file = "recording"
        bound.usrp.service = "stopped"
        bound.usrp.file = "uploaded"
        coordinator.store.save(bound)

        with self.assertRaises(CaptureConflictError):
            coordinator.start_usrp("test")

        self.run_command.assert_not_called()

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


class Ap3FreshnessTests(unittest.TestCase):
    def setUp(self):
        from app.capture_jobs import CaptureCoordinator, CaptureStore
        from app.device_health import HealthResult

        self.repo_root = Path(__file__).resolve().parents[2]
        self.root = self.repo_root / ".test_tmp" / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.now = [datetime(2026, 8, 12, 0, 0, tzinfo=timezone.utc)]
        self.process = FakeProcess()
        self.run_command = Mock(return_value=Mock(returncode=0, stdout="", stderr=""))
        self.health = Mock()
        self.health.poll.return_value = {
            "ap3": HealthResult("ap3", "ready", 0.0, ""),
            "raspi": HealthResult("raspi", "ready", 0.0, ""),
        }
        self.coordinator = CaptureCoordinator(
            CaptureStore(self.root),
            repo_root=self.repo_root,
            run_command=self.run_command,
            popen_factory=Mock(return_value=self.process),
            health_monitor=self.health,
            clock=lambda: self.now[0],
            resume_window_seconds=300,
        )

    def test_successful_sample_persists_last_sample_time(self):
        state = self.coordinator.start_uav()

        self.coordinator.record_gps_sample(state.mission_id, "2026-08-12T00:00:01Z")

        saved = self.coordinator.store.load(state.mission_id)
        self.assertEqual(saved.uav.last_sample_at, "2026-08-12T00:00:01+00:00")
        self.assertIsNone(saved.uav.disconnected_at)
        self.assertIsNone(saved.uav.resume_deadline_at)

    def test_status_snapshot_cannot_overwrite_concurrent_gps_sample(self):
        class BlockingListStore:
            def __init__(self, inner):
                self.inner = inner
                self.entered = threading.Event()
                self.release = threading.Event()

            def __getattr__(self, name):
                return getattr(self.inner, name)

            def list(self):
                # Capture the status snapshot before waiting; a pre-fix status
                # implementation could then release the lock and save this
                # stale object after record_gps_sample had persisted its row.
                states = self.inner.list()
                self.entered.set()
                self.release.wait(timeout=1)
                return states

        state = self.coordinator.store.create(
            bind=True,
            selected_usrp_mode="test",
            target="bind",
            mission_id="status_sample_race",
        )
        state.started_at = "2026-08-11T23:59:00+00:00"
        state.uav.connection = "ready"
        state.uav.service = "running"
        state.uav.file = "recording"
        state.uav.phase = "recording"
        state.uav.path = str(self.root / state.mission_id / "gps.csv")
        state.uav.last_sample_at = "2026-08-11T23:59:00+00:00"
        state.usrp.connection = "ready"
        state.usrp.service = "stopped"
        state.usrp.file = "uploaded"
        state.usrp.phase = "completed"
        self.coordinator.store.save(state)
        self.coordinator._uav_processes[state.mission_id] = self.process
        wrapped = BlockingListStore(self.coordinator.store)
        self.coordinator.store = wrapped
        status_result: list[object] = []
        sample_result: list[object] = []

        status_thread = threading.Thread(
            target=lambda: status_result.append(self.coordinator.status("test")),
        )
        status_thread.start()
        self.assertTrue(wrapped.entered.wait(timeout=1))

        sample_thread = threading.Thread(
            target=lambda: sample_result.append(
                self.coordinator.record_gps_sample(
                    state.mission_id,
                    "2026-08-12T00:00:01Z",
                )
            ),
        )
        sample_thread.start()
        # status() owns the coordinator lock while list() is blocked; the GPS
        # write must wait instead of racing an old status snapshot.
        sample_thread.join(timeout=0.05)
        self.assertTrue(sample_thread.is_alive())

        wrapped.release.set()
        status_thread.join(timeout=1)
        sample_thread.join(timeout=1)
        self.assertFalse(status_thread.is_alive())
        self.assertFalse(sample_thread.is_alive())
        self.assertEqual(len(status_result), 1)
        self.assertEqual(len(sample_result), 1)
        saved = self.coordinator.store.load(state.mission_id)
        self.assertEqual(saved.uav.last_sample_at, "2026-08-12T00:00:01+00:00")

    def test_healthy_recorder_without_gps_rows_remains_running(self):
        state = self.coordinator.start_uav()
        self.now[0] += timedelta(seconds=11)

        dashboard = self.coordinator.status("test")

        self.assertEqual(dashboard.mission_id, state.mission_id)
        self.assertEqual(dashboard.uav.connection, "ready")
        self.assertEqual(dashboard.uav.service, "running")
        self.assertEqual(dashboard.uav.phase, "recording")
        self.assertEqual(dashboard.uav.file, "recording")
        self.assertIsNone(dashboard.uav.disconnected_at)
        self.assertIsNone(dashboard.uav.resume_deadline_at)
        self.assertEqual(dashboard.usrp.connection, "ready")
        self.assertEqual(dashboard.usrp.service, "idle")
        self.assertEqual(dashboard.usrp.phase, "idle")

    def test_ap3_health_loss_still_reconciles_without_gps_rows(self):
        from app.device_health import HealthResult

        state = self.coordinator.start_uav()
        self.health.poll.return_value = {
            "ap3": HealthResult("ap3", "offline", 0.0, "USB disconnected"),
            "raspi": HealthResult("raspi", "ready", 0.0, ""),
        }

        dashboard = self.coordinator.status("test")

        self.assertEqual(dashboard.mission_id, state.mission_id)
        self.assertEqual(dashboard.uav.connection, "offline")
        self.assertEqual(dashboard.uav.service, "presumed_running")
        self.assertEqual(dashboard.uav.phase, "reconciling")
        self.assertEqual(dashboard.uav.error, "AP3 connection is offline")

    def test_bound_ap3_stale_keeps_usrp_child_unchanged(self):
        from app.capture_jobs import CaptureCoordinator, CaptureStore
        from app.device_health import HealthResult

        backend = Mock()
        store = CaptureStore(self.root / "bound")
        coordinator = CaptureCoordinator(
            store,
            repo_root=self.repo_root,
            usrp_backend=backend,
            health_monitor=self.health,
            clock=lambda: self.now[0],
            resume_window_seconds=300,
        )
        state = store.create(
            bind=True,
            selected_usrp_mode="usrp",
            target="bind",
            mission_id="bound_stale",
        )
        state.started_at = self.now[0].isoformat()
        state.uav.connection = "ready"
        state.uav.service = "running"
        state.uav.file = "recording"
        state.uav.phase = "recording"
        state.uav.path = str(store.root / state.mission_id / "gps.csv")
        state.usrp.connection = "ready"
        state.usrp.service = "running"
        state.usrp.file = "recording"
        state.usrp.phase = "recording"
        store.save(state)
        coordinator._uav_processes[state.mission_id] = self.process
        backend.get_capture_job.return_value = {
            "service_state": "running",
            "mission_state": {
                "mission_id": state.mission_id,
                "state": "running",
                "upload_state": "recording",
            },
        }
        self.health.poll.return_value = {
            "ap3": HealthResult("ap3", "offline", 0.0, "USB disconnected"),
            "raspi": HealthResult("raspi", "ready", 0.0, ""),
        }
        before = (
            state.usrp.mission_id,
            state.usrp.service,
            state.usrp.file,
        )
        dashboard = coordinator.status("usrp")
        after = (
            dashboard.usrp.mission_id,
            dashboard.usrp.service,
            dashboard.usrp.file,
        )

        self.assertEqual(dashboard.uav.connection, "offline")
        self.assertEqual(dashboard.uav.phase, "reconciling")
        self.assertEqual(after, before)
        self.assertEqual(dashboard.usrp.mission_id, state.mission_id)
        self.assertEqual(dashboard.overall_state, "degraded")

    def test_fresh_sample_does_not_resume_health_reconciling_independent_child(self):
        state = self.coordinator.start_uav()
        from app.device_health import HealthResult

        self.now[0] += timedelta(seconds=11)
        self.health.poll.return_value = {
            "ap3": HealthResult("ap3", "offline", 0.0, "USB disconnected"),
            "raspi": HealthResult("raspi", "ready", 0.0, ""),
        }
        degraded = self.coordinator.status("test")
        self.assertEqual(degraded.uav.phase, "reconciling")
        deadline = degraded.uav.resume_deadline_at

        self.now[0] += timedelta(seconds=1)
        observed = self.coordinator.record_gps_sample(
            state.mission_id,
            self.now[0].isoformat(),
        )

        self.assertEqual(observed.mission_id, state.mission_id)
        self.assertEqual(observed.uav.service, "presumed_running")
        self.assertEqual(observed.uav.phase, "reconciling")
        self.assertEqual(observed.uav.connection, "offline")
        self.assertEqual(observed.uav.last_sample_at, "2026-08-12T00:00:12+00:00")
        self.assertEqual(observed.uav.resume_deadline_at, deadline)
        self.assertEqual(len(self.coordinator.store.list()), 1)

    def test_fresh_sample_and_live_process_remain_running(self):
        state = self.coordinator.start_uav()
        self.coordinator.record_gps_sample(state.mission_id, "2026-08-12T00:00:01Z")
        self.now[0] += timedelta(seconds=5)

        dashboard = self.coordinator.status("test")

        self.assertEqual(dashboard.uav.service, "running")
        self.assertEqual(dashboard.uav.phase, "recording")
        self.assertEqual(dashboard.uav.connection, "ready")
        self.assertEqual(dashboard.uav.last_sample_at, "2026-08-12T00:00:01+00:00")

    def test_process_death_marks_failed_phase(self):
        state = self.coordinator.start_uav()
        self.process.terminated = True

        dashboard = self.coordinator.status("test")

        self.assertEqual(dashboard.mission_id, state.mission_id)
        self.assertEqual(dashboard.uav.service, "failed")
        self.assertEqual(dashboard.uav.file, "failed")
        self.assertEqual(dashboard.uav.phase, "failed")

    def test_stale_gps_rows_do_not_create_resume_deadline(self):
        state = self.coordinator.start_uav()
        gps_path = Path(state.uav.path)
        gps_path.write_text(
            "time_stamp,lat,lon,alt,alt_mode\n"
            "2026-08-12T00:00:00+00:00,24.0,121.0,10,relative\n",
            encoding="utf-8",
        )
        self.coordinator.record_gps_sample(state.mission_id, "2026-08-12T00:00:00Z")
        self.now[0] += timedelta(seconds=11)
        healthy = self.coordinator.status("test")
        self.assertEqual(healthy.uav.service, "running")
        self.assertEqual(healthy.uav.phase, "recording")
        self.assertIsNone(healthy.uav.resume_deadline_at)
        self.now[0] += timedelta(seconds=301)

        still_healthy = self.coordinator.status("test")

        self.assertEqual(still_healthy.uav.service, "running")
        self.assertEqual(still_healthy.uav.phase, "recording")
        self.assertEqual(still_healthy.uav.file, "recording")
        self.assertIsNone(still_healthy.uav.resume_deadline_at)


class Ap3CaptureResumeTests(unittest.TestCase):
    def setUp(self):
        from app.capture_jobs import CaptureCoordinator, CaptureStore
        from app.device_health import HealthResult

        self.repo_root = Path(__file__).resolve().parents[2]
        self.root = self.repo_root / ".test_tmp" / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.now = [datetime(2026, 8, 12, 0, 5, tzinfo=timezone.utc)]
        self.process = FakeProcess()
        self.popen = Mock(return_value=self.process)
        self.run_command = Mock(return_value=Mock(returncode=0, stdout="", stderr=""))
        self.health = Mock()
        self.health.poll.return_value = {
            "ap3": HealthResult("ap3", "ready", 0.0, ""),
            "raspi": HealthResult("raspi", "ready", 0.0, ""),
        }
        self.store = CaptureStore(self.root)
        self.coordinator = CaptureCoordinator(
            self.store,
            repo_root=self.repo_root,
            run_command=self.run_command,
            popen_factory=self.popen,
            health_monitor=self.health,
            clock=lambda: self.now[0],
        )

    def _bound_reconciling(self, *, mission_id="resume_mission"):
        from app.gps_csv import GPS_CSV_HEADER

        state = self.store.create(
            bind=True,
            selected_usrp_mode="usrp",
            target="bind",
            mission_id=mission_id,
        )
        path = self.store.root / mission_id / "gps.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"{GPS_CSV_HEADER}\n"
            "2026-08-12T00:00:00+00:00,24.0,121.0,10,relative\n",
            encoding="utf-8",
        )
        state.started_at = "2026-08-12T00:00:00+00:00"
        state.uav.path = str(path)
        state.uav.connection = "offline"
        state.uav.service = "presumed_running"
        state.uav.file = "recording"
        state.uav.phase = "reconciling"
        state.uav.last_sample_at = "2026-08-12T00:00:00+00:00"
        state.uav.disconnected_at = "2026-08-12T00:00:11+00:00"
        state.uav.resume_deadline_at = "2026-08-12T00:05:00+00:00"
        state.usrp.connection = "ready"
        state.usrp.service = "running"
        state.usrp.file = "recording"
        state.usrp.phase = "recording"
        self.store.save(state)
        self.coordinator._uav_processes[state.mission_id] = self.process
        return state, path

    def test_resume_accepts_299_and_exactly_300_seconds(self):
        for seconds in (299, 300):
            with self.subTest(seconds=seconds):
                state, _ = self._bound_reconciling(mission_id=f"resume_{seconds}")
                resumed = self.coordinator.resume_uav(
                    state.mission_id,
                    recovered_at=datetime(2026, 8, 12, tzinfo=timezone.utc) + timedelta(seconds=seconds),
                )

                self.assertEqual(resumed.uav.mission_id, state.mission_id)
                self.assertEqual(resumed.uav.service, "running")
                self.assertEqual(resumed.uav.phase, "recording")
                self.assertEqual(resumed.uav.file, "recording")
                self.assertEqual(resumed.uav.connection, "ready")

    def test_resume_timeout_at_301_keeps_partial_file_and_usrp_running(self):
        state, path = self._bound_reconciling()
        write_sample = Mock()

        timed_out = self.coordinator.record_gps_sample(
            state.mission_id,
            "2026-08-12T00:05:01Z",
            write_sample,
        )

        self.assertEqual(timed_out.uav.service, "failed")
        self.assertEqual(timed_out.uav.phase, "resume_timeout")
        self.assertEqual(timed_out.uav.file, "ready")
        self.assertIn("partial", timed_out.uav.error.lower())
        self.assertEqual(timed_out.usrp.service, "running")
        self.assertEqual(timed_out.usrp.file, "recording")
        self.assertEqual(path.read_text(encoding="utf-8").count("GPS"), 0)
        self.assertTrue(self.process.terminated)
        write_sample.assert_not_called()

    def test_resume_appends_same_mission_without_second_header(self):
        state, path = self._bound_reconciling()
        original = path.read_text(encoding="utf-8")
        path.write_text(
            original + "2026-08-12T00:04:59+00:00,24.1,121.1,11,relative\n",
            encoding="utf-8",
        )

        resumed = self.coordinator.resume_uav(
            state.mission_id,
            recovered_at="2026-08-12T00:04:59Z",
        )

        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(resumed.mission_id, state.mission_id)
        self.assertEqual(lines.count("time_stamp,lat,lon,alt,alt_mode"), 1)
        self.assertEqual(len(lines), 3)
        self.assertIn("2026-08-12T00:00:00+00:00", lines[1])
        self.assertIn("2026-08-12T00:04:59+00:00", lines[2])

    def test_resume_rejects_invalid_schema_without_launching_or_changing_file(self):
        state, path = self._bound_reconciling()
        original = "time_stamp,lat,lon,alt\n2026-08-12T00:00:00+00:00,24.0,121.0,10\n"
        path.write_text(original, encoding="utf-8")
        self.popen.reset_mock()

        rejected = self.coordinator.resume_uav(
            state.mission_id,
            recovered_at="2026-08-12T00:01:00Z",
        )

        self.assertEqual(rejected.uav.service, "failed")
        self.assertEqual(rejected.uav.phase, "failed")
        self.assertEqual(rejected.uav.file, "failed")
        self.assertIn("gps.csv header must be", rejected.uav.error)
        self.assertEqual(path.read_text(encoding="utf-8"), original)
        self.popen.assert_not_called()

    def test_dead_recorder_resume_relaunches_same_mission_after_restart(self):
        state, _ = self._bound_reconciling(mission_id="restart_resume")
        restarted_process = FakeProcess(pid=9876)
        restarted_popen = Mock(return_value=restarted_process)
        from app.capture_jobs import CaptureCoordinator

        restarted = CaptureCoordinator(
            self.store,
            repo_root=self.repo_root,
            run_command=self.run_command,
            popen_factory=restarted_popen,
            health_monitor=self.health,
            clock=lambda: self.now[0],
        )

        resumed = restarted.resume_uav(state.mission_id, recovered_at="2026-08-12T00:04:59Z")

        self.assertEqual(resumed.mission_id, state.mission_id)
        self.assertEqual(resumed.uav.service, "running")
        self.assertEqual(resumed.uav.pid, 9876)
        command = restarted_popen.call_args.args[0]
        self.assertIn("--mission-id", command)
        self.assertIn(state.mission_id, command)

    def test_recorder_timeout_exit_finalizes_partial_without_prior_status_poll(self):
        state, path = self._bound_reconciling(mission_id="process_timeout")
        state.uav.phase = "recording"
        state.uav.connection = "ready"
        state.uav.service = "running"
        state.uav.disconnected_at = None
        self.store.save(state)
        self.process.poll = Mock(return_value=2)

        timed_out = self.coordinator.status("test")

        self.assertEqual(timed_out.uav.phase, "resume_timeout")
        self.assertEqual(timed_out.uav.service, "failed")
        self.assertEqual(timed_out.uav.file, "ready")
        self.assertEqual(timed_out.usrp.service, "running")
        self.assertTrue(path.exists())

    def test_bound_recovery_sample_triggers_resume_but_stop_wins_race(self):
        state, path = self._bound_reconciling(mission_id="sample_resume")
        path.write_text(
            path.read_text(encoding="utf-8")
            + "2026-08-12T00:04:59+00:00,24.1,121.1,11,relative\n",
            encoding="utf-8",
        )

        resumed = self.coordinator.record_gps_sample(
            state.mission_id,
            "2026-08-12T00:04:59Z",
        )
        self.assertEqual(resumed.uav.service, "running")
        self.assertEqual(resumed.uav.mission_id, state.mission_id)

        stopped = self.coordinator.stop_uav(state.mission_id)
        self.assertEqual(stopped.uav.service, "stopped")
        self.popen.reset_mock()
        after_stop = self.coordinator.resume_uav(
            state.mission_id,
            recovered_at="2026-08-12T00:05:00Z",
        )
        self.assertEqual(after_stop.uav.service, "stopped")
        self.popen.assert_not_called()
        write_sample = Mock()
        self.coordinator.record_gps_sample(
            state.mission_id,
            "2026-08-12T00:05:00Z",
            write_sample,
        )
        write_sample.assert_not_called()


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

    def test_resume_gap_is_inclusive_at_300_seconds(self):
        previous = datetime(2026, 8, 12, tzinfo=timezone.utc)

        self.assertFalse(
            self.module.resume_window_expired(previous, previous + timedelta(seconds=300), 300)
        )
        self.assertTrue(
            self.module.resume_window_expired(previous, previous + timedelta(seconds=301), 300)
        )

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


class GpsGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = Path(__file__).resolve().parents[2] / "tools" / "generate_gps_from_noise.py"
        spec = importlib.util.spec_from_file_location("generate_gps_from_noise_test", script)
        cls.module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(cls.module)

    def test_generator_writes_canonical_schema(self):
        repo_root = Path(__file__).resolve().parents[2]
        root = repo_root / ".test_tmp" / uuid.uuid4().hex
        root.mkdir(parents=True)
        noise_path = root / "noise.csv"
        gps_path = root / "gps.csv"
        noise_path.write_text(
            "time_stamp,noise_floor_db\n2026-08-12T08:00:00+00:00,-80\n",
            encoding="utf-8",
        )

        with patch.object(
            sys,
            "argv",
            [
                "generate_gps_from_noise.py",
                "--noise-csv",
                str(noise_path),
                "--gps-csv",
                str(gps_path),
                "--lat",
                "24.0",
                "--lon",
                "121.0",
            ],
        ):
            self.assertEqual(self.module.main(), 0)

        self.assertEqual(
            gps_path.read_text(encoding="utf-8").splitlines(),
            [
                "time_stamp,lat,lon,alt,alt_mode",
                "2026-08-12T08:00:00+00:00,24.0,121.0,30.0,relative",
            ],
        )


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

    def test_reconcile_remote_upload_pending_preserves_mission_and_phase(self):
        from app.capture_jobs import CaptureCoordinator, CaptureStore

        repo_root = Path(__file__).resolve().parents[2]
        root = repo_root / ".test_tmp" / uuid.uuid4().hex
        root.mkdir(parents=True)
        store = CaptureStore(root)
        state = store.create(
            bind=False,
            selected_usrp_mode="usrp",
            target="usrp",
            mission_id="mission_reconcile_pending",
        )
        state.started_at = "2026-08-12T00:00:00+00:00"
        state.usrp.connection = "offline"
        state.usrp.service = "presumed_running"
        state.usrp.file = "recording"
        state.usrp.phase = "reconciling"
        store.save(state)
        backend = Mock()
        backend.get_capture_job.return_value = {
            "service_state": "stopped",
            "mission_state": {
                "mission_id": state.mission_id,
                "state": "stopped",
                "upload_state": "upload_pending",
            },
        }
        coordinator = CaptureCoordinator(
            store,
            repo_root=repo_root,
            usrp_backend=backend,
        )

        reconciled = coordinator.refresh_usrp(state.mission_id)

        self.assertEqual(reconciled.mission_id, state.mission_id)
        self.assertEqual(reconciled.usrp.mission_id, state.mission_id)
        self.assertEqual(reconciled.usrp.connection, "ready")
        self.assertEqual(reconciled.usrp.service, "stopped")
        self.assertEqual(reconciled.usrp.file, "upload_pending")
        self.assertEqual(reconciled.usrp.phase, "upload_pending")
        self.assertEqual(reconciled.overall_state, "finalizing")
        self.assertEqual(len(store.list()), 1)

    def test_reconcile_remote_states_keeps_child_outcomes_distinct(self):
        from app.capture_jobs import CaptureCoordinator, CaptureStore

        repo_root = Path(__file__).resolve().parents[2]
        cases = [
            (
                "stopped",
                {"state": "stopped", "upload_state": "uploaded"},
                "stopped",
                "uploaded",
                "completed",
            ),
            (
                "stopped_pending",
                {"state": "stopped", "upload_state": "recording"},
                "stopped",
                "upload_pending",
                "upload_pending",
            ),
            (
                "failed",
                {"state": "failed", "upload_state": "failed"},
                "failed",
                "failed",
                "failed",
            ),
            (
                "stopped_unknown_upload",
                {"state": "stopped"},
                "stopped",
                "upload_pending",
                "upload_pending",
            ),
            (
                "finalizing",
                {"state": "finalizing", "upload_state": "finalizing"},
                "presumed_running",
                "finalizing",
                "finalizing_file",
            ),
        ]
        for name, mission_state, service, file_state, phase in cases:
            with self.subTest(name=name):
                root = repo_root / ".test_tmp" / uuid.uuid4().hex
                root.mkdir(parents=True)
                store = CaptureStore(root)
                state = store.create(
                    bind=False,
                    selected_usrp_mode="usrp",
                    target="usrp",
                    mission_id=f"mission_reconcile_{name}",
                )
                state.started_at = "2026-08-12T00:00:00+00:00"
                state.usrp.service = "presumed_running"
                state.usrp.file = "recording"
                state.usrp.phase = "reconciling"
                store.save(state)
                backend = Mock()
                backend.get_capture_job.return_value = {
                    "service_state": "stopped" if name != "finalizing" else "unknown",
                    "mission_state": {"mission_id": state.mission_id, **mission_state},
                }
                coordinator = CaptureCoordinator(store, repo_root=repo_root, usrp_backend=backend)

                reconciled = coordinator.reconcile_usrp(state.mission_id)

                self.assertEqual(reconciled.usrp.service, service)
                self.assertEqual(reconciled.usrp.file, file_state)
                self.assertEqual(reconciled.usrp.phase, phase)

    def test_reconcile_requires_matching_mission_state_and_keeps_running_failure_uncertain(self):
        from app.capture_jobs import CaptureCoordinator, CaptureStore

        repo_root = Path(__file__).resolve().parents[2]
        root = repo_root / ".test_tmp" / uuid.uuid4().hex
        root.mkdir(parents=True)
        store = CaptureStore(root)
        state = store.create(
            bind=False,
            selected_usrp_mode="usrp",
            target="usrp",
            mission_id="mission_reconcile_evidence",
        )
        state.started_at = "2026-08-12T00:00:00+00:00"
        state.usrp.service = "presumed_running"
        state.usrp.file = "recording"
        state.usrp.phase = "reconciling"
        store.save(state)
        backend = Mock()
        backend.get_capture_job.return_value = {
            "service_state": "running",
            "mission_state": {
                "mission_id": state.mission_id,
                "state": "failed",
                "upload_state": "failed",
            },
        }
        coordinator = CaptureCoordinator(store, repo_root=repo_root, usrp_backend=backend)

        uncertain = coordinator.reconcile_usrp(state.mission_id)

        self.assertEqual(uncertain.usrp.service, "presumed_running")
        self.assertEqual(uncertain.usrp.phase, "reconciling")
        self.assertEqual(uncertain.overall_state, "degraded")

        backend.get_capture_job.return_value = {
            "service_state": "stopped",
            "mission_state": {"state": "stopped", "upload_state": "uploaded"},
        }
        missing = coordinator.reconcile_usrp(state.mission_id)
        self.assertEqual(missing.usrp.connection, "offline")
        self.assertEqual(missing.usrp.service, "presumed_running")
        self.assertEqual(missing.usrp.phase, "reconciling")


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
        self.health_probe = Mock(return_value={
            "state": "ready",
            "service_state": "stopped",
        })
        self.backend.get_drone_health = lambda mode: self.health_probe(mode)
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

        self.health_probe.side_effect = RuntimeError("SSH timeout")

        with self.assertRaises(CaptureUnavailableError):
            self.coordinator.start_bind("test")

        self.popen.assert_not_called()
        self.backend.start_capture_job.assert_not_called()

    def test_bind_preflight_reports_each_device_without_creating_mission(self):
        from app.capture_jobs import CapturePreflightError

        self.run_command.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="AP3 USB disconnected",
        )
        self.health_probe.side_effect = RuntimeError("SSH timeout")

        with self.assertRaises(CapturePreflightError) as raised:
            self.coordinator.start_bind("test")

        self.assertEqual(
            raised.exception.errors,
            {
                "ap3": "AP3 USB disconnected",
                "raspi": "SSH timeout",
            },
        )
        self.assertEqual(self.coordinator.store.list(), [])
        self.popen.assert_not_called()
        self.backend.start_capture_job.assert_not_called()

    def test_bind_ap3_preflight_failure_reports_only_ap3_without_mission(self):
        from app.capture_jobs import CapturePreflightError

        self.run_command.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="AP3 forwarding unavailable",
        )

        with self.assertRaises(CapturePreflightError) as raised:
            self.coordinator.start_bind("test")

        self.assertEqual(raised.exception.errors, {"ap3": "AP3 forwarding unavailable"})
        self.assertEqual(self.coordinator.store.list(), [])
        self.popen.assert_not_called()
        self.backend.start_capture_job.assert_not_called()

    def test_bind_persists_shared_mission_before_either_launch(self):
        observed = []

        def launch_uav(*args, **kwargs):
            mission_id = args[0][args[0].index("--mission-id") + 1]
            observed.append(self.coordinator.store.path(mission_id).exists())
            return FakeProcess()

        self.popen.side_effect = launch_uav

        def launch_usrp(mode, mission, **kwargs):
            observed.append(self.coordinator.store.path(mission["mission_id"]).exists())
            return {
                "success": True,
                "service_state": "running",
                "mission_state": {"state": "running", "upload_state": "recording"},
            }

        self.backend.start_capture_job.side_effect = launch_usrp
        state = self.coordinator.start_bind("test")

        self.assertEqual(observed, [True, True])
        self.assertEqual(state.uav.mission_id, state.usrp.mission_id)

    def test_bind_ap3_launch_failure_keeps_usrp_recording(self):
        self.popen.side_effect = RuntimeError("adb recorder failed")

        state = self.coordinator.start_bind("usrp")

        self.assertEqual(state.overall_state, "degraded")
        self.assertEqual(state.uav.service, "failed")
        self.assertEqual(state.usrp.service, "running")
        self.assertEqual(len(self.coordinator.store.list()), 1)
        self.backend.start_capture_job.assert_called_once()

    def test_bind_rejects_unresolved_upload_before_creating_new_mission(self):
        from app.capture_jobs import CaptureConflictError

        old = self.coordinator.store.create(
            bind=False,
            selected_usrp_mode="usrp",
            target="usrp",
            mission_id="pending-upload",
        )
        old.started_at = "2026-08-12T00:00:00+00:00"
        old.usrp.service = "stopped"
        old.usrp.file = "upload_pending"
        self.coordinator.store.save(old)

        with self.assertRaises(CaptureConflictError):
            self.coordinator.start_bind("usrp")

    def test_bind_rejects_independent_upload_retry_before_creating_new_mission(self):
        from app.capture_jobs import CaptureConflictError

        old = self.coordinator.store.create(
            bind=False,
            selected_usrp_mode="usrp",
            target="usrp",
            mission_id="retrying-upload",
        )
        old.started_at = "2026-08-12T00:00:00+00:00"
        old.usrp.service = "stopped"
        old.usrp.file = "ready"
        old.usrp.upload_retry_state = "waiting"
        self.coordinator.store.save(old)

        self.assertEqual(old.overall_state, "finalizing")

        with self.assertRaises(CaptureConflictError):
            self.coordinator.start_bind("usrp")

        self.assertEqual(len(self.coordinator.store.list()), 1)

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
        self.health_probe.assert_called_with("usrp")
        self.backend.get_drone_status.assert_not_called()

    def test_bind_child_failure_preserves_other_child(self):
        self.backend.start_capture_job.side_effect = RuntimeError("systemctl failed")

        state = self.coordinator.start_bind("usrp")

        self.assertEqual(state.overall_state, "degraded")
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

    def test_independent_uav_then_usrp_can_run_concurrently(self):
        uav = self.coordinator.start_uav()
        usrp = self.coordinator.start_usrp("test")

        self.assertNotEqual(uav.mission_id, usrp.mission_id)
        self.assertEqual(uav.uav.service, "running")
        self.assertEqual(usrp.usrp.service, "running")

    def test_independent_usrp_then_uav_can_run_concurrently(self):
        usrp = self.coordinator.start_usrp("test")
        uav = self.coordinator.start_uav()

        self.assertNotEqual(usrp.mission_id, uav.mission_id)
        self.assertEqual(usrp.usrp.service, "running")
        self.assertEqual(uav.uav.service, "running")

    def test_stop_all_waits_for_both_finalizers(self):
        state = self.coordinator.start_bind("test")
        self.backend.stop_capture_job.return_value["mission_state"]["mission_id"] = state.mission_id

        stopped = self.coordinator.stop_bind(state.mission_id)

        self.assertEqual(stopped.uav.file, "ready")
        self.assertEqual(stopped.usrp.file, "uploaded")
        self.assertEqual(stopped.overall_state, "completed")

    def test_stop_all_starts_children_concurrently_and_persists_request(self):
        state = self.coordinator.start_bind("test")
        started = {"uav": threading.Event(), "usrp": threading.Event()}
        release = threading.Event()
        errors = []

        def attempt(name):
            started[name].set()
            other = "usrp" if name == "uav" else "uav"
            if not started[other].wait(timeout=1):
                errors.append(f"{name} started before {other}")
            release.wait(timeout=1)
            return self.coordinator.store.load(state.mission_id)

        with (
            patch.object(self.coordinator, "stop_uav", side_effect=lambda mission_id: attempt("uav")),
            patch.object(self.coordinator, "stop_usrp", side_effect=lambda mission_id: attempt("usrp")),
        ):
            result = []
            worker = threading.Thread(
                target=lambda: result.append(self.coordinator.stop_bind(state.mission_id)),
            )
            worker.start()
            self.assertTrue(started["uav"].wait(timeout=1))
            self.assertTrue(started["usrp"].wait(timeout=1))
            release.set()
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(result), 1)
        self.assertIsNotNone(self.coordinator.store.load(state.mission_id).stop_requested_at)

    def test_stop_all_isolates_child_exception(self):
        state = self.coordinator.start_bind("test")
        self.backend.stop_capture_job.return_value["mission_state"]["mission_id"] = state.mission_id
        usrp_attempted = threading.Event()
        stop_usrp_original = self.coordinator.stop_usrp

        def fail_uav(_mission_id):
            raise RuntimeError("AP3 finalize timeout")

        def stop_usrp(mission_id):
            usrp_attempted.set()
            return stop_usrp_original(mission_id)

        with (
            patch.object(self.coordinator, "stop_uav", side_effect=fail_uav),
            patch.object(self.coordinator, "stop_usrp", side_effect=stop_usrp),
        ):
            stopped = self.coordinator.stop_bind(state.mission_id)

        self.assertTrue(usrp_attempted.is_set())
        self.assertEqual(stopped.uav.service, "presumed_running")
        self.assertEqual(stopped.uav.phase, "stop_failed")
        self.assertIn("AP3 finalize timeout", stopped.uav.error)
        self.assertEqual(stopped.usrp.service, "stopped")
        self.assertEqual(stopped.usrp.file, "uploaded")

    def test_stop_all_intent_survives_restart_without_reissuing_stops(self):
        from app.capture_jobs import CaptureCoordinator

        state = self.coordinator.start_bind("test")
        self.backend.stop_capture_job.return_value["mission_state"]["mission_id"] = state.mission_id
        stopped = self.coordinator.stop_bind(state.mission_id)
        restarted = CaptureCoordinator(
            self.coordinator.store,
            repo_root=self.repo_root,
            run_command=self.run_command,
            popen_factory=self.popen,
            usrp_backend=self.backend,
        )

        with (
            patch.object(restarted, "stop_uav") as stop_uav,
            patch.object(restarted, "stop_usrp") as stop_usrp,
        ):
            restored = restarted.stop_bind(state.mission_id)

        self.assertEqual(restored.stop_requested_at, stopped.stop_requested_at)
        stop_uav.assert_not_called()
        stop_usrp.assert_not_called()

    def test_usrp_stop_rejects_mismatched_remote_mission(self):
        state = self.coordinator.start_usrp("usrp")
        self.backend.stop_capture_job.return_value = {
            "success": True,
            "service_state": "stopped",
            "mission_state": {
                "mission_id": "another-mission",
                "state": "stopped",
                "upload_state": "uploaded",
            },
        }

        stopped = self.coordinator.stop_usrp(state.mission_id)

        self.assertEqual(stopped.usrp.service, "presumed_running")
        self.assertEqual(stopped.usrp.phase, "stop_failed")
        self.assertNotEqual(stopped.overall_state, "completed")

    def test_usrp_stop_rejects_result_without_mission_id(self):
        state = self.coordinator.start_usrp("usrp")
        self.backend.stop_capture_job.return_value = {
            "success": True,
            "service_state": "stopped",
            "mission_state": {"state": "stopped", "upload_state": "uploaded"},
        }

        stopped = self.coordinator.stop_usrp(state.mission_id)

        self.assertEqual(stopped.usrp.service, "presumed_running")
        self.assertEqual(stopped.usrp.phase, "stop_failed")
        self.assertNotEqual(stopped.overall_state, "completed")

    def test_usrp_stop_keeps_failed_upload_pending(self):
        state = self.coordinator.start_usrp("usrp")
        self.backend.stop_capture_job.return_value = {
            "success": True,
            "service_state": "stopped",
            "mission_state": {
                "mission_id": state.mission_id,
                "state": "stopped",
                "upload_state": "failed",
                "error": "upload timeout",
            },
        }

        stopped = self.coordinator.stop_usrp(state.mission_id)

        self.assertEqual(stopped.usrp.service, "stopped")
        self.assertEqual(stopped.usrp.file, "upload_pending")
        self.assertEqual(stopped.usrp.phase, "upload_pending")
        self.assertIn("upload timeout", stopped.usrp.error)
        self.assertEqual(stopped.overall_state, "finalizing")

    def test_usrp_stop_failure_records_stop_intent(self):
        state = self.coordinator.start_usrp("usrp")
        self.backend.stop_capture_job.side_effect = RuntimeError("SSH timeout")

        stopped = self.coordinator.stop_usrp(state.mission_id)

        self.assertEqual(stopped.usrp.phase, "stop_failed")
        self.assertEqual(stopped.usrp.service, "presumed_running")
        self.assertEqual(stopped.usrp.connection, "offline")
        self.assertEqual(stopped.overall_state, "stopping")

    def test_retry_stop_only_retries_failed_uav_child(self):
        state = self.coordinator.start_bind("test")
        state.stop_requested_at = "2026-08-12T00:00:00+00:00"
        state.uav.service = "presumed_running"
        state.uav.file = "finalizing"
        state.uav.phase = "stop_failed"
        state.uav.error = "AP3 finalize timeout"
        state.usrp.service = "stopped"
        state.usrp.file = "uploaded"
        state.usrp.phase = "completed"
        self.coordinator.store.save(state)

        retried = self.coordinator.retry_stop_uav(state.mission_id)

        self.assertEqual(retried.uav.service, "stopped")
        self.assertEqual(retried.uav.file, "ready")
        self.assertEqual(retried.uav.phase, "stopped")
        self.assertEqual(retried.usrp.service, "stopped")
        self.assertEqual(retried.overall_state, "completed")
        self.backend.stop_capture_job.assert_not_called()

    def test_retry_stop_retries_usrp_with_original_mission_id(self):
        state = self.coordinator.start_bind("test")
        state.stop_requested_at = "2026-08-12T00:00:00+00:00"
        state.usrp.connection = "ready"
        state.usrp.service = "presumed_running"
        state.usrp.file = "finalizing"
        state.usrp.phase = "stop_failed"
        self.coordinator.store.save(state)
        self.backend.stop_capture_job.return_value = {
            "success": True,
            "service_state": "stopped",
            "mission_state": {
                "mission_id": state.mission_id,
                "state": "stopped",
                "upload_state": "uploaded",
            },
        }

        retried = self.coordinator.retry_stop_usrp(state.mission_id)

        self.assertEqual(retried.usrp.service, "stopped")
        self.assertEqual(retried.usrp.file, "uploaded")
        self.assertEqual(retried.usrp.phase, "stopped")
        self.backend.stop_capture_job.assert_called_once_with("test", state.mission_id)
        self.assertEqual(retried.uav.service, "running")

    def test_retry_usrp_stop_failure_keeps_error_and_sibling_running(self):
        state = self.coordinator.start_bind("test")
        state.stop_requested_at = "2026-08-12T00:00:00+00:00"
        state.usrp.connection = "ready"
        state.usrp.service = "presumed_running"
        state.usrp.file = "finalizing"
        state.usrp.phase = "stop_failed"
        state.usrp.error = "first stop timed out"
        self.coordinator.store.save(state)
        self.backend.stop_capture_job.side_effect = RuntimeError("SSH timeout again")

        retried = self.coordinator.retry_stop_usrp(state.mission_id)

        self.assertEqual(retried.usrp.service, "presumed_running")
        self.assertEqual(retried.usrp.phase, "stop_failed")
        self.assertIn("SSH timeout again", retried.usrp.error)
        self.assertEqual(retried.uav.service, "running")
        self.assertEqual(retried.uav.file, "recording")

    def test_retry_uav_stop_requires_process_ownership_after_restart(self):
        state = self.coordinator.start_bind("test")
        state.stop_requested_at = "2026-08-12T00:00:00+00:00"
        state.uav.service = "presumed_running"
        state.uav.file = "finalizing"
        state.uav.phase = "stop_failed"
        state.uav.error = "AP3 finalize timeout"
        self.coordinator.store.save(state)

        from app.capture_jobs import CaptureCoordinator, CaptureConflictError
        restarted = CaptureCoordinator(
            self.coordinator.store,
            repo_root=self.repo_root,
            run_command=self.run_command,
            popen_factory=self.popen,
            usrp_backend=self.backend,
        )
        with self.assertRaises(CaptureConflictError):
            restarted.retry_stop_uav(state.mission_id)

        restored = restarted.store.load(state.mission_id)
        self.assertEqual(restored.uav.phase, "stop_failed")
        self.assertEqual(restored.uav.service, "presumed_running")
        self.assertEqual(restored.usrp.service, "running")

    def test_retry_stop_rejects_general_launch_failure(self):
        state = self.coordinator.start_bind("test")
        state.uav.service = "failed"
        state.uav.file = "failed"
        state.uav.phase = "failed"
        self.coordinator.store.save(state)

        from app.capture_jobs import CaptureConflictError
        with self.assertRaises(CaptureConflictError):
            self.coordinator.retry_stop_uav(state.mission_id)
        self.backend.stop_capture_job.assert_not_called()

    def test_idle_status_reports_independent_readiness(self):
        state = self.coordinator.status("test")

        self.assertEqual(state.uav.connection, "ready")
        self.assertEqual(state.usrp.connection, "ready")
        self.health_probe.assert_called_with("test")

    def test_status_merges_simultaneous_independent_jobs(self):
        uav_state = self.coordinator.start_uav()
        usrp_state = self.coordinator.start_usrp("usrp")
        self.backend.get_capture_job.return_value = {
            "service_state": "running",
            "mission_state": {
                "mission_id": usrp_state.mission_id,
                "state": "running",
                "upload_state": "recording",
            },
        }

        dashboard = self.coordinator.status("usrp")

        self.assertNotEqual(uav_state.mission_id, usrp_state.mission_id)
        self.assertEqual(dashboard.uav.mission_id, uav_state.mission_id)
        self.assertEqual(dashboard.usrp.mission_id, usrp_state.mission_id)
        self.assertEqual(dashboard.uav.service, "running")
        self.assertEqual(dashboard.usrp.service, "running")

    def test_status_payload_projects_terminal_history_as_clean_idle_panel(self):
        state = self.coordinator.store.create(
            bind=False,
            selected_usrp_mode="test",
            target="uav",
            mission_id="gps_terminal_12345",
        )
        state.started_at = "2026-08-13T16:00:00+00:00"
        state.uav.service = "stopped"
        state.uav.file = "ready"
        state.uav.phase = "stopped"
        self.coordinator.store.save(state)

        payload = self.coordinator.status_payload("test")

        self.assertEqual(payload["control_mode"], "independent")
        self.assertIsNone(payload["active"])
        self.assertEqual(payload["mission_id"], "")
        self.assertEqual(payload["uav"]["phase"], "idle")
        self.assertEqual(payload["uav"]["file"], "none")
        self.assertEqual(
            payload["history"]["gps"],
            {"started_at": "2026-08-13T16:00:00+00:00", "mission_id": "gps_terminal_12345"},
        )
        self.assertIsNone(payload["history"]["noise"])

    def test_status_payload_restores_unresolved_independent_noise_projection(self):
        state = self.coordinator.store.create(
            bind=False,
            selected_usrp_mode="usrp",
            target="usrp",
            mission_id="noise_active_12345",
        )
        state.started_at = "2026-08-13T17:00:00+00:00"
        state.usrp.service = "running"
        state.usrp.file = "recording"
        state.usrp.phase = "recording"
        self.coordinator.store.save(state)
        self.backend.get_capture_job.return_value = {
            "service_state": "running",
            "mission_state": {
                "mission_id": state.mission_id,
                "state": "running",
                "upload_state": "recording",
            },
        }

        payload = self.coordinator.status_payload("usrp")

        self.assertEqual(payload["control_mode"], "independent")
        self.assertIsNotNone(payload["active"])
        self.assertEqual(payload["active"]["mission_id"], state.mission_id)
        self.assertEqual(payload["usrp"]["service"], "running")
        self.assertEqual(payload["uav"]["service"], "idle")

    def test_status_payload_projects_ready_idle_sibling_for_independent_gps(self):
        gps = self.coordinator.start_uav()

        payload = self.coordinator.status_payload("test")

        self.assertEqual(payload["uav"]["mission_id"], gps.mission_id)
        self.assertEqual(payload["uav"]["service"], "running")
        self.assertEqual(payload["usrp"]["mission_id"], "")
        self.assertEqual(payload["usrp"]["connection"], "ready")
        self.assertEqual(payload["usrp"]["service"], "idle")
        self.assertEqual(payload["usrp"]["file"], "none")
        self.assertEqual(payload["usrp"]["phase"], "idle")

    def test_status_payload_projects_ready_idle_sibling_for_independent_noise(self):
        noise = self.coordinator.start_usrp("usrp")
        self.backend.get_capture_job.return_value = {
            "service_state": "running",
            "mission_state": {
                "mission_id": noise.mission_id,
                "state": "running",
                "upload_state": "recording",
            },
        }

        payload = self.coordinator.status_payload("usrp")

        self.assertEqual(payload["usrp"]["mission_id"], noise.mission_id)
        self.assertEqual(payload["usrp"]["service"], "running")
        self.assertEqual(payload["uav"]["mission_id"], "")
        self.assertEqual(payload["uav"]["connection"], "ready")
        self.assertEqual(payload["uav"]["service"], "idle")
        self.assertEqual(payload["uav"]["file"], "none")
        self.assertEqual(payload["uav"]["phase"], "idle")

    def test_status_payload_merges_unresolved_independent_children(self):
        gps = self.coordinator.start_uav()
        noise = self.coordinator.start_usrp("test")
        self.backend.get_capture_job.return_value = {
            "service_state": "running",
            "mission_state": {
                "mission_id": noise.mission_id,
                "state": "running",
                "upload_state": "recording",
            },
        }

        payload = self.coordinator.status_payload("test")

        self.assertEqual(payload["control_mode"], "independent")
        self.assertIsNotNone(payload["active"])
        self.assertEqual(payload["uav"]["mission_id"], gps.mission_id)
        self.assertEqual(payload["usrp"]["mission_id"], noise.mission_id)
        self.assertEqual(payload["uav"]["service"], "running")
        self.assertEqual(payload["usrp"]["service"], "running")

    def test_bound_history_is_shared_between_gps_and_noise(self):
        state = self.coordinator.store.create(
            bind=True,
            selected_usrp_mode="test",
            target="bind",
            mission_id="bound_shared_12345",
        )
        state.started_at = "2026-08-13T18:00:00+00:00"
        state.uav.service = "stopped"
        state.uav.file = "ready"
        state.uav.phase = "stopped"
        state.usrp.service = "failed"
        state.usrp.file = "failed"
        state.usrp.phase = "failed"
        self.coordinator.store.save(state)

        payload = self.coordinator.status_payload("test")

        expected = {
            "started_at": "2026-08-13T18:00:00+00:00",
            "mission_id": "bound_shared_12345",
        }
        self.assertEqual(payload["history"]["gps"], expected)
        self.assertEqual(payload["history"]["noise"], expected)

    def test_independent_noise_start_is_allowed_while_gps_is_running(self):
        gps = self.coordinator.start_uav()

        noise = self.coordinator.start_usrp("usrp")

        self.assertNotEqual(gps.mission_id, noise.mission_id)
        self.assertEqual(gps.uav.service, "running")
        self.assertEqual(noise.usrp.service, "running")

    def test_independent_gps_start_is_allowed_while_noise_is_running(self):
        noise = self.coordinator.start_usrp("usrp")

        gps = self.coordinator.start_uav()

        self.assertNotEqual(gps.mission_id, noise.mission_id)
        self.assertEqual(gps.uav.service, "running")
        self.assertEqual(noise.usrp.service, "running")

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
                "mission_id": state.mission_id,
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
                "mission_id": state.mission_id,
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
        for _ in range(20):
            if self.coordinator.store.load(state.mission_id).usrp.upload_state != "running":
                break
            time.sleep(0.01)
        after_first = self.coordinator.store.load(state.mission_id)
        # Manual Retry is available only after the finite automatic schedule
        # is exhausted; preserve the historical manual-success assertions by
        # moving this fixture to that terminal automatic state.
        after_first.usrp.upload_retry_mode = "automatic"
        after_first.usrp.upload_retry_state = "exhausted"
        after_first.usrp.upload_retry_attempt = 3
        after_first.usrp.upload_retry_max_attempts = 3
        after_first.usrp.upload_retry_next_attempt_at = None
        self.coordinator.store.save(after_first)
        second = self.coordinator.retry_usrp_upload(state.mission_id)
        for _ in range(20):
            if self.coordinator.store.load(state.mission_id).usrp.file == "uploaded":
                break
            time.sleep(0.01)
        after_second = self.coordinator.store.load(state.mission_id)

        self.assertEqual(first.usrp.service, "stopped")
        self.assertEqual(first.usrp.file, "upload_pending")
        self.assertEqual(after_first.usrp.file, "upload_pending")
        self.assertEqual(second.usrp.upload_state, "running")
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
                    "mission_id": mission_id,
                    "state": "stopped",
                    "upload_state": "upload_pending",
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
        self.backend.stop_capture_job.return_value["mission_state"]["mission_id"] = state.mission_id
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

    def test_capture_status_endpoint_bounds_coordinator_probe(self):
        from fastapi import HTTPException

        coordinator = Mock()
        timeout_calls: list[float | None] = []

        async def fail_wait(awaitable, timeout):
            timeout_calls.append(timeout)
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            raise asyncio.TimeoutError

        with patch.object(self.main, "capture_coordinator", coordinator):
            with patch.object(self.main.asyncio, "wait_for", side_effect=fail_wait):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(self.main.capture_status_get("usrp"))

        self.assertEqual(raised.exception.status_code, 504)
        self.assertIn("capture status timed out", raised.exception.detail)
        self.assertEqual(timeout_calls, [30])

    def test_capture_status_endpoint_returns_coordinator_snapshot(self):
        coordinator = Mock()
        payload = {
            "mission_id": "mission_status_api",
            "target": "usrp",
            "bind": False,
            "overall_state": "degraded",
            "device_health": {
                "raspi": {"state": "offline", "stale": False},
            },
        }
        coordinator.status_payload.return_value = payload

        with patch.object(self.main, "capture_coordinator", coordinator):
            result = asyncio.run(self.main.capture_status_get("usrp"))

        self.assertEqual(result, payload)
        coordinator.status_payload.assert_called_once_with("usrp")

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

    def test_bind_start_maps_structured_preflight_errors(self):
        from app.capture_jobs import CapturePreflightError
        from fastapi import HTTPException

        coordinator = Mock()
        coordinator.start_bind.side_effect = CapturePreflightError(
            {"ap3": "USB disconnected", "raspi": "SSH timeout"}
        )

        with patch.object(self.main, "capture_coordinator", coordinator):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    self.main.capture_bind_start_post(
                        self.main.CaptureStartRequest(usrp_mode="test")
                    )
                )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(
            raised.exception.detail["errors"],
            {"ap3": "USB disconnected", "raspi": "SSH timeout"},
        )

    def test_bind_start_maps_ap3_only_preflight_error(self):
        from app.capture_jobs import CapturePreflightError
        from fastapi import HTTPException

        coordinator = Mock()
        coordinator.start_bind.side_effect = CapturePreflightError(
            {"ap3": "Forwarding unavailable"}
        )

        with patch.object(self.main, "capture_coordinator", coordinator):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    self.main.capture_bind_start_post(
                        self.main.CaptureStartRequest(usrp_mode="test")
                    )
                )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail["errors"], {"ap3": "Forwarding unavailable"})

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
        coordinator.retry_stop_uav.return_value = self._state("uav")
        coordinator.retry_stop_usrp.return_value = self._state("usrp")

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
                asyncio.run(self.main.capture_uav_retry_stop_post("flight_api")).mission_id,
                "flight_api",
            )
            coordinator.resume_uav.return_value = self._state("bind")
            self.assertEqual(
                asyncio.run(self.main.capture_uav_resume_post("flight_api")).mission_id,
                "flight_api",
            )
            self.assertEqual(
                asyncio.run(self.main.capture_usrp_stop_post("flight_api")).mission_id,
                "flight_api",
            )
            self.assertEqual(
                asyncio.run(self.main.capture_usrp_retry_stop_post("flight_api")).mission_id,
                "flight_api",
            )
            self.assertEqual(
                asyncio.run(self.main.capture_bind_stop_post("flight_api")).mission_id,
                "flight_api",
            )

        coordinator.start_uav.assert_called_once()
        coordinator.start_usrp.assert_called_once()
        coordinator.resume_uav.assert_called_once_with("flight_api")
        coordinator.stop_bind.assert_called_once_with("flight_api")
        coordinator.retry_stop_uav.assert_called_once_with("flight_api")
        coordinator.retry_stop_usrp.assert_called_once_with("flight_api")


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

    def test_usrp_stop_starts_immediate_background_upload(self):
        started = threading.Event()
        release = threading.Event()

        current = self.coordinator.store.load("noise_upload")
        current.usrp.service = "running"
        current.usrp.file = "recording"
        self.coordinator.store.save(current)
        self.coordinator.usrp_backend.stop_capture_job.return_value = {
            "service_state": "stopped",
            "mission_state": {
                "mission_id": "noise_upload",
                "state": "stopped",
                "upload_state": "upload_pending",
            },
        }

        def upload(mode, mission_id):
            started.set()
            release.wait(timeout=1)
            return {
                "mission_state": {
                    "mission_id": mission_id,
                    "upload_state": "uploaded",
                },
            }

        self.coordinator.usrp_backend.upload_capture_job.side_effect = upload
        result = self.coordinator.stop_usrp("noise_upload")

        self.assertEqual(result.usrp.file, "upload_pending")
        self.assertEqual(result.usrp.upload_state, "running")
        self.assertTrue(started.wait(timeout=1))
        release.set()
        for _ in range(20):
            if self.coordinator.store.load("noise_upload").usrp.file == "uploaded":
                break
            time.sleep(0.01)
        completed = self.coordinator.store.load("noise_upload")
        self.assertEqual(completed.usrp.file, "uploaded")
        self.assertEqual(completed.usrp.upload_state, "success")

    def test_usrp_status_reconciles_orphaned_upload_job(self):
        current = self.coordinator.store.load("noise_upload")
        current.usrp.upload_state = "running"
        current.usrp.upload_mode = "automatic"
        current.usrp.upload_job_id = "orphaned"
        self.coordinator.store.save(current)
        self.coordinator.usrp_backend.get_capture_job.return_value = {
            "service_state": "stopped",
            "mission_state": {
                "mission_id": "noise_upload",
                "state": "stopped",
                "upload_state": "uploaded",
            },
        }

        reconciled = self.coordinator.reconcile_usrp("noise_upload")

        self.assertEqual(reconciled.usrp.file, "uploaded")
        self.assertEqual(reconciled.usrp.upload_state, "success")
        self.assertIsNone(reconciled.usrp.upload_job_id)

    def test_failed_automatic_uploads_follow_persisted_5_15_30_schedule(self):
        from app.capture_jobs import _parse_timestamp

        now = [datetime(2026, 8, 13, tzinfo=timezone.utc)]
        self.coordinator._clock = lambda: now[0]
        current = self.coordinator.store.load("noise_upload")
        current.usrp.service = "running"
        current.usrp.file = "recording"
        self.coordinator.store.save(current)
        self.coordinator.usrp_backend.stop_capture_job.return_value = {
            "service_state": "stopped",
            "mission_state": {
                "mission_id": "noise_upload",
                "state": "stopped",
                "upload_state": "upload_pending",
            },
        }
        calls: list[str] = []

        def fail_upload(mode, mission_id):
            calls.append(mode)
            return {
                "mission_state": {
                    "mission_id": mission_id,
                    "upload_state": "upload_pending",
                    "error": "network down",
                },
            }

        self.coordinator.usrp_backend.upload_capture_job.side_effect = fail_upload
        result = self.coordinator.stop_usrp("noise_upload")
        self.assertEqual(result.usrp.upload_retry_state, "running")
        for _ in range(50):
            if self.coordinator.store.load("noise_upload").usrp.upload_retry_state == "waiting":
                break
            time.sleep(0.01)
        waiting = self.coordinator.store.load("noise_upload")
        self.assertEqual(calls, ["usrp"])
        self.assertEqual(waiting.usrp.upload_retry_attempt, 1)
        self.assertEqual(waiting.usrp.upload_retry_state, "waiting")
        self.assertEqual(
            _parse_timestamp(waiting.usrp.upload_retry_next_attempt_at),
            now[0] + timedelta(seconds=5),
        )

        now[0] += timedelta(seconds=5)
        self.assertEqual(self.coordinator.process_upload_retries(), 1)
        for _ in range(50):
            if self.coordinator.store.load("noise_upload").usrp.upload_retry_attempt == 2:
                break
            time.sleep(0.01)
        second = self.coordinator.store.load("noise_upload")
        self.assertEqual(calls, ["usrp", "usrp"])
        self.assertEqual(
            _parse_timestamp(second.usrp.upload_retry_next_attempt_at),
            now[0] + timedelta(seconds=15),
        )

        now[0] += timedelta(seconds=15)
        self.assertEqual(self.coordinator.process_upload_retries(), 1)
        for _ in range(50):
            if self.coordinator.store.load("noise_upload").usrp.upload_retry_attempt == 3:
                break
            time.sleep(0.01)
        third = self.coordinator.store.load("noise_upload")
        self.assertEqual(calls, ["usrp", "usrp", "usrp"])
        self.assertEqual(
            _parse_timestamp(third.usrp.upload_retry_next_attempt_at),
            now[0] + timedelta(seconds=30),
        )

        now[0] += timedelta(seconds=30)
        self.assertEqual(self.coordinator.process_upload_retries(), 1)
        for _ in range(50):
            if self.coordinator.store.load("noise_upload").usrp.upload_retry_state == "exhausted":
                break
            time.sleep(0.01)
        exhausted = self.coordinator.store.load("noise_upload")
        self.assertEqual(calls, ["usrp", "usrp", "usrp", "usrp"])
        self.assertEqual(exhausted.usrp.upload_retry_state, "exhausted")
        self.assertEqual(exhausted.usrp.upload_retry_attempt, 3)
        self.assertEqual(exhausted.usrp.file, "upload_pending")

    def test_due_retry_restores_after_backend_restart_without_resetting_attempt(self):
        from app.capture_jobs import _iso

        now = [datetime(2026, 8, 13, tzinfo=timezone.utc)]
        current = self.coordinator.store.load("noise_upload")
        current.usrp.upload_retry_mode = "automatic"
        current.usrp.upload_retry_state = "waiting"
        current.usrp.upload_retry_attempt = 2
        current.usrp.upload_retry_max_attempts = 3
        current.usrp.upload_retry_next_attempt_at = _iso(now[0])
        current.usrp.file = "upload_pending"
        current.usrp.phase = "upload_pending"
        current.usrp.service = "stopped"
        self.coordinator.store.save(current)

        restarted_backend = Mock()
        restarted_backend.upload_capture_job.return_value = {
            "mission_state": {
                "mission_id": "noise_upload",
                "upload_state": "uploaded",
            },
        }
        from app.capture_jobs import CaptureCoordinator, CaptureStore

        restarted = CaptureCoordinator(
            CaptureStore(self.root),
            repo_root=self.repo_root,
            usrp_backend=restarted_backend,
            clock=lambda: now[0],
        )
        self.assertEqual(restarted.process_upload_retries(), 1)
        for _ in range(50):
            if restarted.store.load("noise_upload").usrp.file == "uploaded":
                break
            time.sleep(0.01)
        loaded = restarted.store.load("noise_upload")
        restarted_backend.upload_capture_job.assert_called_once_with("usrp", "noise_upload")
        self.assertEqual(loaded.usrp.file, "uploaded")
        self.assertEqual(loaded.usrp.upload_retry_state, "success")
        self.assertEqual(loaded.usrp.upload_retry_attempt, 2)

    def test_running_retry_restores_to_next_waiting_slot_after_backend_restart(self):
        from app.capture_jobs import CaptureCoordinator, CaptureStore, _iso, _parse_timestamp

        now = datetime(2026, 8, 13, tzinfo=timezone.utc)
        current = self.coordinator.store.load("noise_upload")
        current.usrp.service = "stopped"
        current.usrp.file = "upload_pending"
        current.usrp.phase = "upload_pending"
        current.usrp.upload_state = "running"
        current.usrp.upload_mode = "automatic"
        current.usrp.upload_job_id = "lost-worker"
        current.usrp.upload_retry_mode = "automatic"
        current.usrp.upload_retry_state = "running"
        current.usrp.upload_retry_attempt = 1
        current.usrp.upload_retry_max_attempts = 3
        current.usrp.upload_retry_active_started_at = _iso(now)
        self.coordinator.store.save(current)

        restarted = CaptureCoordinator(
            CaptureStore(self.root),
            repo_root=self.repo_root,
            usrp_backend=Mock(),
            clock=lambda: now,
        )
        self.assertEqual(restarted.process_upload_retries(), 0)
        recovered = restarted.store.load("noise_upload")
        self.assertEqual(recovered.usrp.upload_retry_state, "waiting")
        self.assertEqual(recovered.usrp.upload_retry_attempt, 2)
        self.assertEqual(
            _parse_timestamp(recovered.usrp.upload_retry_next_attempt_at),
            now + timedelta(seconds=15),
        )
        # Repeated startup/status ticks must not consume another attempt or
        # create a duplicate upload while the restored schedule is waiting.
        self.assertEqual(restarted.process_upload_retries(), 0)
        stable = restarted.store.load("noise_upload")
        self.assertEqual(stable.usrp.upload_retry_attempt, 2)
        self.assertEqual(stable.usrp.upload_retry_state, "waiting")

    def test_due_retry_dispatch_does_not_overlap_an_existing_upload_job(self):
        from app.capture_jobs import _iso

        now = datetime(2026, 8, 13, tzinfo=timezone.utc)
        current = self.coordinator.store.load("noise_upload")
        current.usrp.service = "stopped"
        current.usrp.file = "upload_pending"
        current.usrp.phase = "upload_pending"
        current.usrp.upload_retry_mode = "automatic"
        current.usrp.upload_retry_state = "waiting"
        current.usrp.upload_retry_attempt = 1
        current.usrp.upload_retry_max_attempts = 3
        current.usrp.upload_retry_next_attempt_at = _iso(now)
        self.coordinator.store.save(current)

        started = threading.Event()
        release = threading.Event()

        def upload(mode, mission_id):
            started.set()
            release.wait(timeout=1)
            return {
                "mission_state": {
                    "mission_id": mission_id,
                    "upload_state": "uploaded",
                },
            }

        self.coordinator._clock = lambda: now
        self.coordinator.usrp_backend.upload_capture_job.side_effect = upload
        self.assertEqual(self.coordinator.process_upload_retries(), 1)
        self.assertTrue(started.wait(timeout=1))
        self.assertEqual(self.coordinator.process_upload_retries(), 0)
        self.coordinator.usrp_backend.upload_capture_job.assert_called_once_with(
            "usrp", "noise_upload"
        )
        release.set()
        for _ in range(50):
            if self.coordinator.store.load("noise_upload").usrp.file == "uploaded":
                break
            time.sleep(0.01)
        self.assertEqual(self.coordinator.store.load("noise_upload").usrp.file, "uploaded")

    def test_manual_retry_is_noop_while_automatic_retry_waits_or_runs(self):
        from app.capture_jobs import _iso

        now = datetime(2026, 8, 13, tzinfo=timezone.utc)
        current = self.coordinator.store.load("noise_upload")
        current.usrp.service = "stopped"
        current.usrp.file = "upload_pending"
        current.usrp.phase = "upload_pending"
        current.usrp.upload_retry_mode = "automatic"
        current.usrp.upload_retry_state = "waiting"
        current.usrp.upload_retry_attempt = 1
        current.usrp.upload_retry_max_attempts = 3
        current.usrp.upload_retry_next_attempt_at = _iso(now + timedelta(seconds=5))
        self.coordinator.store.save(current)

        waiting = self.coordinator.retry_usrp_upload("noise_upload")
        self.assertEqual(waiting.usrp.upload_retry_state, "waiting")
        self.coordinator.usrp_backend.retry_capture_upload.assert_not_called()

        current = self.coordinator.store.load("noise_upload")
        current.usrp.upload_state = "running"
        current.usrp.upload_mode = "automatic"
        current.usrp.upload_retry_state = "running"
        current.usrp.upload_retry_active_started_at = _iso(now)
        current.usrp.upload_job_id = "automatic-worker"
        self.coordinator.store.save(current)
        running = self.coordinator.retry_usrp_upload("noise_upload")
        self.assertEqual(running.usrp.upload_retry_state, "running")
        self.coordinator.usrp_backend.retry_capture_upload.assert_not_called()

    def test_manual_retry_does_not_reset_automatic_history_after_exhaustion(self):
        current = self.coordinator.store.load("noise_upload")
        current.usrp.upload_retry_mode = "automatic"
        current.usrp.upload_retry_state = "exhausted"
        current.usrp.upload_retry_attempt = 3
        current.usrp.upload_retry_max_attempts = 3
        current.usrp.file = "upload_pending"
        current.usrp.phase = "upload_pending"
        current.usrp.service = "stopped"
        self.coordinator.store.save(current)
        self.coordinator.usrp_backend.retry_capture_upload.return_value = {
            "mission_state": {
                "mission_id": "noise_upload",
                "upload_state": "upload_pending",
                "error": "still offline",
            },
        }

        self.coordinator.retry_usrp_upload("noise_upload")
        for _ in range(50):
            if self.coordinator.store.load("noise_upload").usrp.upload_state == "failure":
                break
            time.sleep(0.01)
        failed = self.coordinator.store.load("noise_upload")
        self.assertEqual(failed.usrp.upload_retry_attempt, 3)
        self.assertEqual(failed.usrp.upload_retry_state, "exhausted")
        self.assertEqual(failed.usrp.file, "upload_pending")

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

    def test_sync_gps_point_rejects_wrong_schema_without_appending(self):
        bundle = self.root / "flight_bad"
        bundle.mkdir(parents=True)
        gps_path = bundle / "gps.csv"
        original = "time_stamp,lat,lon,alt\n2026-08-12T08:00:00+00:00,24.0,121.0,10\n"
        gps_path.write_text(original, encoding="utf-8")
        point = self.main.GpsSyncPointRequest(
            mission_id="flight_bad",
            time_stamp="2026-08-12T08:00:01+00:00",
            lat=24.1,
            lon=121.1,
            alt=11,
        )

        with patch.object(self.main, "INCOMING_CSV_DIR", self.root):
            response = asyncio.run(self.main.usrp_sync_gps_point_post(point))

        self.assertEqual(response.status_code, 422)
        self.assertEqual(gps_path.read_text(encoding="utf-8"), original)
        self.assertFalse((bundle / "gps_sync.log").exists())

    def test_sync_rejects_recovery_row_after_resume_deadline(self):
        from app.capture_jobs import CaptureCoordinator, CaptureStore
        from app.gps_csv import GPS_CSV_HEADER

        store = CaptureStore(self.root)
        state = store.create(
            bind=True,
            selected_usrp_mode="usrp",
            target="bind",
            mission_id="flight_expired",
        )
        bundle = self.root / state.mission_id
        gps_path = bundle / "gps.csv"
        original = (
            f"{GPS_CSV_HEADER}\n"
            "2026-08-12T00:00:00+00:00,24.0,121.0,10,relative\n"
        )
        gps_path.write_text(original, encoding="utf-8")
        state.started_at = "2026-08-12T00:00:00+00:00"
        state.uav.path = str(gps_path)
        state.uav.connection = "offline"
        state.uav.service = "presumed_running"
        state.uav.file = "recording"
        state.uav.phase = "reconciling"
        state.uav.last_sample_at = "2026-08-12T00:00:00+00:00"
        state.uav.disconnected_at = "2026-08-12T00:00:11+00:00"
        state.uav.resume_deadline_at = "2026-08-12T00:05:00+00:00"
        state.usrp.service = "running"
        state.usrp.file = "recording"
        store.save(state)
        coordinator = CaptureCoordinator(store, repo_root=self.repo_root)
        coordinator._uav_processes[state.mission_id] = FakeProcess()
        point = self.main.GpsSyncPointRequest(
            mission_id=state.mission_id,
            time_stamp="2026-08-12T00:05:01+00:00",
            lat=24.1,
            lon=121.1,
            alt=11,
        )

        with (
            patch.object(self.main, "INCOMING_CSV_DIR", self.root),
            patch.object(self.main, "capture_coordinator", coordinator),
            patch.object(self.main.gps_manager, "update_gps") as update_gps,
            patch.object(self.main.gps_manager, "broadcast", new=AsyncMock()) as broadcast,
        ):
            response = asyncio.run(self.main.usrp_sync_gps_point_post(point))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(gps_path.read_text(encoding="utf-8"), original)
        self.assertFalse((bundle / "gps_sync.log").exists())
        self.assertEqual(store.load(state.mission_id).uav.phase, "resume_timeout")
        update_gps.assert_not_called()
        broadcast.assert_not_awaited()

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


class GpsUploadTests(unittest.TestCase):
    def setUp(self):
        from app import main

        self.main = main
        repo_root = Path(__file__).resolve().parents[2]
        self.root = repo_root / ".test_tmp" / uuid.uuid4().hex
        self.root.mkdir(parents=True)

    def test_gps_upload_rejects_wrong_schema_without_replacing_existing_file(self):
        from fastapi import UploadFile

        bundle = self.root / "flight_upload"
        bundle.mkdir(parents=True)
        gps_path = bundle / "gps.csv"
        original = b"time_stamp,lat,lon,alt,alt_mode\n2026-08-12T08:00:00+00:00,24.0,121.0,10,relative\n"
        gps_path.write_bytes(original)
        invalid = b"time_stamp,lat,lon,alt\n2026-08-12T08:00:01+00:00,24.1,121.1,11\n"

        with patch.object(self.main, "INCOMING_CSV_DIR", self.root):
            response = asyncio.run(
                self.main.usrp_upload_gps_csv_post(
                    mission_id="flight_upload",
                    gps_file=UploadFile(BytesIO(invalid), filename="gps.csv"),
                )
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(gps_path.read_bytes(), original)


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
