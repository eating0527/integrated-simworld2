import asyncio
import threading
import time
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch


class DeviceHealthTests(unittest.TestCase):
    def test_health_api_delegates_without_mission_state_mutation(self):
        from app import main

        coordinator = Mock()
        coordinator.health_status.return_value = {
            "ap3": {"device": "ap3", "state": "offline", "checked_at": "2026-08-12T00:00:00+00:00"},
            "raspi": {"device": "raspi", "state": "ready", "checked_at": "2026-08-12T00:00:00+00:00"},
        }

        with patch.object(main, "capture_coordinator", coordinator):
            response = asyncio.run(main.capture_health_get("usrp"))

        self.assertEqual(response["device_health"]["ap3"]["state"], "offline")
        coordinator.health_status.assert_called_once_with("usrp")

    def test_missing_lightweight_raspi_probe_is_unknown_without_diagnostics_fallback(self):
        from app.capture_jobs import CaptureCoordinator, CaptureStore

        backend = Mock()
        backend.get_drone_status.return_value = {
            "success": True,
            "service_state": "stopped",
        }
        coordinator = CaptureCoordinator(
            CaptureStore(Path(__file__).resolve().parents[2] / ".test_tmp" / f"no-health-{uuid.uuid4().hex}"),
            repo_root=Path(__file__).resolve().parents[2],
            run_command=Mock(return_value=Mock(returncode=0, stdout="", stderr="")),
            usrp_backend=backend,
        )

        health = coordinator.health_status("usrp")

        self.assertEqual(health["raspi"]["state"], "unknown")
        backend.get_drone_status.assert_not_called()

    def test_ap3_probe_requires_authorized_adb_and_forwarding(self):
        from app.device_health import Ap3Health

        run = Mock(side_effect=[
            Mock(returncode=0, stdout="List of devices attached\nap3-1\tdevice\n", stderr=""),
            Mock(returncode=0, stdout="", stderr=""),
        ])
        health = Ap3Health(run=run, adb="adb.exe", clock=lambda: 100.0)

        result = health.check()

        self.assertEqual(result.state, "ready")
        self.assertEqual(run.call_count, 2)
        self.assertIn("devices", run.call_args_list[0].args[0])
        self.assertIn("forward", run.call_args_list[1].args[0])

    def test_ap3_probe_reports_offline_without_forwarding(self):
        from app.device_health import Ap3Health

        run = Mock(return_value=Mock(returncode=0, stdout="List of devices attached\n", stderr=""))
        result = Ap3Health(run=run, adb="adb.exe", clock=lambda: 100.0).check()

        self.assertEqual(result.state, "offline")
        self.assertIn("AP3", result.error)
        self.assertEqual(run.call_count, 1)

    def test_raspi_probe_uses_lightweight_service_probe(self):
        from app.device_health import RaspiHealth

        probe = Mock(return_value={"service_state": "stopped"})
        result = RaspiHealth(probe=probe, clock=lambda: 100.0).check()

        self.assertEqual(result.state, "ready")
        probe.assert_called_once()

    def test_raspi_probe_reports_fake_ssh_failure_as_offline(self):
        from app.device_health import RaspiHealth

        probe = Mock(side_effect=OSError("SSH connection refused"))
        result = RaspiHealth(probe=probe, clock=lambda: 100.0).check()

        self.assertEqual(result.state, "offline")
        self.assertIn("connection refused", result.error)

    def test_offline_to_ready_recovery_resets_backoff(self):
        from app.device_health import DeviceHealthMonitor, HealthResult

        now = [0.0]
        ap3 = Mock(check=Mock(return_value=HealthResult("ap3", "ready", 0.0, "")))
        raspi = Mock()
        raspi.check.side_effect = [
            HealthResult("raspi", "offline", 0.0, "SSH down"),
            HealthResult("raspi", "ready", 5.0, ""),
            HealthResult("raspi", "offline", 15.0, "SSH down"),
        ]
        monitor = DeviceHealthMonitor(ap3=ap3, raspi=raspi, clock=lambda: now[0])

        first = monitor.poll(mode="test")["raspi"]
        now[0] = 5.0
        recovered = monitor.poll(mode="test")["raspi"]
        now[0] = 15.0
        after_recovery_failure = monitor.poll(mode="test")["raspi"]

        self.assertEqual(first.retry_delay, 5.0)
        self.assertEqual(recovered.state, "ready")
        self.assertEqual(recovered.retry_delay, 10.0)
        self.assertEqual(after_recovery_failure.retry_delay, 5.0)

    def test_raspi_health_cache_is_separate_for_each_mode(self):
        from app.capture_jobs import CaptureCoordinator, CaptureStore

        class Backend:
            def __init__(self):
                self.modes = []

            def get_drone_health(self, mode):
                self.modes.append(mode)
                return {"state": "ready", "service_state": "stopped"}

        backend = Backend()
        coordinator = CaptureCoordinator(
            CaptureStore(Path(__file__).resolve().parents[2] / ".test_tmp" / f"mode-cache-{uuid.uuid4().hex}"),
            repo_root=Path(__file__).resolve().parents[2],
            run_command=Mock(return_value=Mock(returncode=0, stdout="", stderr="")),
            usrp_backend=backend,
        )

        coordinator.health_status("test")
        coordinator.health_status("usrp")

        self.assertEqual(backend.modes, ["test", "usrp"])

    def test_status_payload_keeps_health_snapshot_in_requested_mode(self):
        from app.capture_jobs import CaptureCoordinator, CaptureStore
        from app.device_health import HealthResult

        class ModeHealth:
            def __init__(self):
                self.mode = None
                self.snapshot_started = threading.Event()
                self.release_snapshot = threading.Event()
                self.usrp_poll_started = threading.Event()

            def poll(self, *, mode=None, **_kwargs):
                self.mode = mode
                if mode == "usrp":
                    self.usrp_poll_started.set()
                result = HealthResult("raspi", "ready", 100.0, f"mode={mode}")
                return {"ap3": result, "raspi": result}

            def as_dict(self):
                self.snapshot_started.set()
                self.release_snapshot.wait(timeout=1.0)
                return {
                    "ap3": HealthResult("ap3", "ready", 100.0, f"mode={self.mode}").as_dict(),
                    "raspi": HealthResult("raspi", "ready", 100.0, f"mode={self.mode}").as_dict(),
                }

        root = Path(__file__).resolve().parents[2] / ".test_tmp" / f"health-mode-race-{uuid.uuid4().hex}"
        health = ModeHealth()
        coordinator = CaptureCoordinator(
            CaptureStore(root),
            repo_root=Path(__file__).resolve().parents[2],
            health_monitor=health,
        )
        payload = {}
        second_started = threading.Event()

        first = threading.Thread(target=lambda: payload.update(coordinator.status_payload("test")))
        first.start()
        self.assertTrue(health.snapshot_started.wait(timeout=1.0))

        def request_other_mode():
            second_started.set()
            coordinator.health_status("usrp")

        second = threading.Thread(target=request_other_mode)
        second.start()
        self.assertTrue(second_started.wait(timeout=1.0))
        self.assertFalse(health.usrp_poll_started.wait(timeout=1.0))
        health.release_snapshot.set()

        first.join(timeout=1.0)
        second.join(timeout=1.0)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(payload["device_health"]["raspi"]["error"], "mode=test")

    def test_monitor_uses_ready_ten_second_and_offline_capped_backoff(self):
        from app.device_health import DeviceHealthMonitor, HealthResult

        now = [0.0]
        ap3 = Mock()
        ap3.check.side_effect = [
            HealthResult("ap3", "offline", 0.0, "USB disconnected"),
            HealthResult("ap3", "offline", 5.0, "USB disconnected"),
            HealthResult("ap3", "offline", 15.0, "USB disconnected"),
            HealthResult("ap3", "offline", 35.0, "USB disconnected"),
            HealthResult("ap3", "offline", 65.0, "USB disconnected"),
        ]
        raspi = Mock()
        raspi.check.return_value = HealthResult("raspi", "ready", 0.0, "")
        monitor = DeviceHealthMonitor(ap3=ap3, raspi=raspi, clock=lambda: now[0])

        monitor.poll()
        self.assertEqual(ap3.check.call_count, 1)
        now[0] = 4.9
        monitor.poll()
        self.assertEqual(ap3.check.call_count, 1)
        now[0] = 5.0
        monitor.poll()
        self.assertEqual(ap3.check.call_count, 2)
        now[0] = 15.0
        monitor.poll()
        self.assertEqual(ap3.check.call_count, 3)
        now[0] = 35.0
        monitor.poll()
        self.assertEqual(ap3.check.call_count, 4)
        now[0] = 64.9
        monitor.poll()
        self.assertEqual(ap3.check.call_count, 4)
        now[0] = 65.0
        monitor.poll()
        self.assertEqual(ap3.check.call_count, 5)

    def test_timeout_is_unknown_and_never_ready(self):
        from app.device_health import DeviceHealthMonitor, HealthResult

        def slow():
            time.sleep(0.05)
            return HealthResult("ap3", "ready", 0.0, "")

        ap3 = Mock(check=slow)
        raspi = Mock(check=lambda: HealthResult("raspi", "ready", 0.0, ""))
        monitor = DeviceHealthMonitor(ap3=ap3, raspi=raspi, timeout=0.001)

        result = monitor.poll()["ap3"]

        self.assertNotEqual(result.state, "ready")
        self.assertTrue(result.stale)
        self.assertIn("timeout", result.error.lower())

    def test_stale_results_are_unknown(self):
        from app.device_health import DeviceHealthMonitor, HealthResult

        now = [0.0]
        ap3 = Mock(check=Mock(return_value=HealthResult("ap3", "ready", 0.0, "")))
        raspi = Mock(check=Mock(return_value=HealthResult("raspi", "ready", 0.0, "")))
        monitor = DeviceHealthMonitor(ap3=ap3, raspi=raspi, clock=lambda: now[0])

        monitor.poll()
        now[0] = 11.0
        result = monitor.snapshot()["ap3"]

        self.assertEqual(result.state, "unknown")
        self.assertTrue(result.stale)

    def test_health_change_does_not_rewrite_terminal_mission_child(self):
        from app.device_health import HealthResult
        from app.capture_jobs import CaptureCoordinator, CaptureStore

        class FakeHealth:
            def poll(self, **_kwargs):
                return {
                    "ap3": HealthResult("ap3", "offline", 100.0, "USB disconnected"),
                    "raspi": HealthResult("raspi", "ready", 100.0, ""),
                }

            def as_dict(self):
                return {name: result.as_dict() for name, result in self.poll().items()}

        root = Path(__file__).resolve().parents[2] / ".test_tmp" / f"health-history-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        store = CaptureStore(root)
        state = store.create(bind=True, selected_usrp_mode="usrp", target="bind", mission_id="history")
        state.started_at = "2026-08-12T00:00:00+00:00"
        state.uav.connection = "ready"
        state.uav.service = "stopped"
        state.uav.file = "ready"
        state.usrp.connection = "ready"
        state.usrp.service = "stopped"
        state.usrp.file = "uploaded"
        store.save(state)
        coordinator = CaptureCoordinator(
            store,
            repo_root=Path(__file__).resolve().parents[2],
            health_monitor=FakeHealth(),
        )

        payload = coordinator.status_payload("usrp")

        self.assertEqual(payload["overall_state"], "completed")
        self.assertEqual(payload["uav"]["connection"], "ready")
        self.assertEqual(payload["device_health"]["ap3"]["state"], "offline")
        self.assertEqual(store.load("history").uav.connection, "ready")


if __name__ == "__main__":
    unittest.main()
