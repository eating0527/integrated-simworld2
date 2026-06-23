import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


class UsrpSamplingControlApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_status_reports_missing_raspi_configuration(self):
        with patch("app.usrp_ctl.get_drone_status", side_effect=RuntimeError("RASPI_HOST is required")):
            response = self.client.get("/api/usrp/sampling/status")

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertFalse(body["raspi_connected"])
        self.assertEqual(body["service_state"], "unknown")
        self.assertIn("RASPI_HOST", body["message"])

    def test_status_reports_running_service(self):
        payload = {
            "success": True,
            "raspi_connected": True,
            "session_connected": True,
            "mode": "test",
            "service_name": "drone_test.service",
            "service_state": "running",
            "message": "drone_test.service running",
            "service_messages": ["active"],
        }
        with patch("app.usrp_ctl.get_drone_status", return_value=payload):
            response = self.client.get("/api/usrp/sampling/status?mode=test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)

    def test_status_defaults_to_test_mode(self):
        payload = {
            "success": True,
            "raspi_connected": True,
            "session_connected": True,
            "mode": "test",
            "service_name": "drone_test.service",
            "service_state": "stopped",
            "message": "drone_test.service stopped",
            "service_messages": ["inactive"],
        }
        with patch("app.usrp_ctl.get_drone_status", return_value=payload) as status:
            response = self.client.get("/api/usrp/sampling/status")

        self.assertEqual(response.status_code, 200)
        status.assert_called_once_with("test")
        self.assertEqual(response.json(), payload)

    def test_status_rejects_invalid_mode_before_ssh(self):
        with patch("app.usrp_ctl.get_drone_status") as status:
            response = self.client.get("/api/usrp/sampling/status?mode=bad")

        self.assertEqual(response.status_code, 422)
        status.assert_not_called()

    def test_connect_reports_connected_session_and_service_messages(self):
        payload = {
            "success": True,
            "raspi_connected": True,
            "session_connected": True,
            "mode": "usrp",
            "service_name": "drone.service",
            "service_state": "stopped",
            "message": "RasPi connected",
            "service_messages": ["inactive"],
        }
        with patch("app.usrp_ctl.connect_raspi", return_value=payload):
            response = self.client.post("/api/usrp/sampling/connect?mode=usrp")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)

    def test_disconnect_reports_disconnected_session(self):
        payload = {
            "success": True,
            "raspi_connected": False,
            "session_connected": False,
            "mode": "test",
            "service_name": "drone_test.service",
            "service_state": "unknown",
            "message": "RasPi disconnected",
            "service_messages": [],
        }
        with patch("app.usrp_ctl.disconnect_raspi", return_value=payload):
            response = self.client.post("/api/usrp/sampling/disconnect")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)

    def test_messages_returns_service_status_and_recent_logs(self):
        payload = {
            "success": True,
            "raspi_connected": True,
            "session_connected": True,
            "mode": "test",
            "service_name": "drone_test.service",
            "service_state": "running",
            "message": "drone_test.service messages loaded",
            "service_messages": [
                "drone_test.service - Drone sampler",
                "Active: active (running)",
                "Started sampler",
            ],
        }
        with patch("app.usrp_ctl.get_drone_messages", return_value=payload):
            response = self.client.get("/api/usrp/sampling/messages?mode=test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)

    def test_start_reports_running_service(self):
        payload = {
            "success": True,
            "raspi_connected": True,
            "session_connected": True,
            "mode": "usrp",
            "service_name": "drone.service",
            "service_state": "running",
            "message": "drone.service started",
            "service_messages": ["drone.service started"],
        }
        with patch("app.usrp_ctl.start_drone_service", return_value=payload):
            response = self.client.post("/api/usrp/sampling/start?mode=usrp")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)

    def test_stop_reports_stopped_service(self):
        payload = {
            "success": True,
            "raspi_connected": True,
            "session_connected": True,
            "mode": "test",
            "service_name": "drone_test.service",
            "service_state": "stopped",
            "message": "drone_test.service stopped",
            "service_messages": ["drone_test.service stopped"],
        }
        with patch("app.usrp_ctl.stop_drone_service", return_value=payload):
            response = self.client.post("/api/usrp/sampling/stop?mode=test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)

    def test_failure_response_does_not_leak_password(self):
        secret = "super-secret-password"
        with patch.dict("os.environ", {"RASPI_PSW": secret}):
            with patch("app.usrp_ctl.start_drone_service", side_effect=RuntimeError(f"SSH failed for {secret}")):
                response = self.client.post("/api/usrp/sampling/start")

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertFalse(body["raspi_connected"])
        self.assertEqual(body["service_state"], "unknown")
        self.assertNotIn(secret, body["message"])

    def test_usrp_mode_failure_response_reports_selected_mode(self):
        with patch("app.usrp_ctl.start_drone_service", side_effect=RuntimeError("SSH timeout")):
            response = self.client.post("/api/usrp/sampling/start?mode=usrp")

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["mode"], "usrp")
        self.assertEqual(body["service_name"], "drone.service")
        self.assertEqual(body["message"], "SSH timeout")


class UsrpSamplingControlUnitTests(unittest.TestCase):
    def test_start_test_mode_falls_back_to_sudo_when_systemctl_needs_authentication(self):
        from app import usrp_ctl

        calls: list[tuple[str, bool]] = []

        def fake_run(command: str, use_sudo_password: bool = False):
            calls.append((command, use_sudo_password))
            if command == "systemctl start drone_test" and not use_sudo_password:
                return 1, "", "Interactive authentication required."
            if command == "systemctl start drone_test" and use_sudo_password:
                return 0, "", ""
            if command == "systemctl is-active drone_test":
                return 0, "active", ""
            if command == "systemctl status --no-pager -l drone_test":
                return 0, "Active: active (running)", ""
            if command == "journalctl -u drone_test -n 20 --no-pager":
                return 0, "Active: active (running)", ""
            return 0, "", ""

        with patch.dict("os.environ", {"RASPI_PSW": "secret"}):
            with patch.object(usrp_ctl, "_run_remote", side_effect=fake_run):
                response = usrp_ctl.start_drone_service("test")

        self.assertEqual(response["service_state"], "running")
        self.assertEqual(response["mode"], "test")
        self.assertEqual(response["service_name"], "drone_test.service")
        self.assertIn(("systemctl start drone_test", False), calls)
        self.assertIn(("systemctl start drone_test", True), calls)

    def test_stop_usrp_mode_falls_back_to_sudo_when_systemctl_needs_authentication(self):
        from app import usrp_ctl

        calls: list[tuple[str, bool]] = []

        def fake_run(command: str, use_sudo_password: bool = False):
            calls.append((command, use_sudo_password))
            if command == "systemctl stop drone" and not use_sudo_password:
                return 1, "", "Interactive authentication required."
            if command == "systemctl stop drone" and use_sudo_password:
                return 0, "", ""
            if command == "systemctl is-active drone":
                return 3, "inactive", ""
            if command.startswith("systemctl status") or command.startswith("journalctl"):
                return 0, "Active: inactive", ""
            return 0, "", ""

        with patch.dict("os.environ", {"RASPI_PSW": "secret"}):
            with patch.object(usrp_ctl, "_run_remote", side_effect=fake_run):
                response = usrp_ctl.stop_drone_service("usrp")

        self.assertEqual(response["service_state"], "stopped")
        self.assertEqual(response["mode"], "usrp")
        self.assertEqual(response["service_name"], "drone.service")
        self.assertIn(("systemctl stop drone", False), calls)
        self.assertIn(("systemctl stop drone", True), calls)

    def test_invalid_mode_does_not_run_remote_command(self):
        from app import usrp_ctl

        with patch.object(usrp_ctl, "_run_remote") as run_remote:
            with self.assertRaises(usrp_ctl.UsrpControlError):
                usrp_ctl.get_drone_status("bad")

        run_remote.assert_not_called()


if __name__ == "__main__":
    unittest.main()
