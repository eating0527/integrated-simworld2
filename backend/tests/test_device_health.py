import asyncio
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
            def poll(self):
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
