import asyncio
import json
import unittest
from unittest.mock import patch

from app import main


class _AsgiJsonResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class UsrpSamplingControlApiTests(unittest.TestCase):
    def _request_json(self, method: str, path: str) -> _AsgiJsonResponse:
        path_only, _, query = path.partition("?")
        messages: list[dict] = []
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path_only,
            "raw_path": path_only.encode("ascii"),
            "query_string": query.encode("ascii"),
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"content-length", b"0"),
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "app": main.app,
        }
        asyncio.run(main.app(scope, receive, send))

        start = next(
            message for message in messages if message["type"] == "http.response.start"
        )
        chunks = [
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        ]
        payload = json.loads(b"".join(chunks).decode("utf-8"))
        return _AsgiJsonResponse(start["status"], payload)

    def test_status_reports_missing_raspi_configuration(self):
        with patch("app.usrp_ctl.get_drone_status", side_effect=RuntimeError("RASPI_HOST is required")):
            response = self._request_json("GET", "/api/usrp/sampling/status")

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
            response = self._request_json("GET", "/api/usrp/sampling/status?mode=test")

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
            response = self._request_json("GET", "/api/usrp/sampling/status")

        self.assertEqual(response.status_code, 200)
        status.assert_called_once_with("test")
        self.assertEqual(response.json(), payload)

    def test_status_rejects_invalid_mode_before_ssh(self):
        with patch("app.usrp_ctl.get_drone_status") as status:
            response = self._request_json("GET", "/api/usrp/sampling/status?mode=bad")

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
            response = self._request_json("POST", "/api/usrp/sampling/connect?mode=usrp")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deprecated"])

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
            response = self._request_json("POST", "/api/usrp/sampling/disconnect")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deprecated"])

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
            response = self._request_json("GET", "/api/usrp/sampling/messages?mode=test")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deprecated"])

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
            response = self._request_json("POST", "/api/usrp/sampling/start?mode=usrp")

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
            response = self._request_json("POST", "/api/usrp/sampling/stop?mode=test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)

    def test_failure_response_does_not_leak_password(self):
        secret = "super-secret-password"
        with patch.dict("os.environ", {"RASPI_PSW": secret}):
            with patch("app.usrp_ctl.start_drone_service", side_effect=RuntimeError(f"SSH failed for {secret}")):
                response = self._request_json("POST", "/api/usrp/sampling/start")

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertFalse(body["raspi_connected"])
        self.assertEqual(body["service_state"], "unknown")
        self.assertNotIn(secret, body["message"])

    def test_usrp_mode_failure_response_reports_selected_mode(self):
        with patch("app.usrp_ctl.start_drone_service", side_effect=RuntimeError("SSH timeout")):
            response = self._request_json("POST", "/api/usrp/sampling/start?mode=usrp")

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["mode"], "usrp")
        self.assertEqual(body["service_name"], "drone.service")
        self.assertEqual(body["message"], "SSH timeout")


class UsrpSamplingControlUnitTests(unittest.TestCase):
    def test_service_targets_match_test_and_usrp_modes(self):
        from app import usrp_ctl

        test_target = usrp_ctl._service_target("test")
        usrp_target = usrp_ctl._service_target("usrp")

        self.assertEqual(test_target.unit, "drone_test")
        self.assertEqual(test_target.service_name, "drone_test.service")
        self.assertEqual(usrp_target.unit, "drone")
        self.assertEqual(usrp_target.service_name, "drone.service")

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

    def test_remote_mission_defaults_match_rx_sampling_contract(self):
        from app import usrp_ctl

        mission = usrp_ctl.RemoteMission(
            mission_id="flight_defaults",
            api_url="http://192.168.50.95:8888/api/usrp/upload-noise-csv",
        )

        self.assertEqual(mission.work_dir, "/home/user/rx_sampling")
        self.assertEqual(mission.noise_csv, "/home/user/rx_sampling/noise.csv")

    def test_remote_start_writes_rx_sampling_contract_before_systemctl(self):
        from app import usrp_ctl

        mission = usrp_ctl.RemoteMission(
            mission_id="flight_001",
            api_url="http://192.168.50.95:8888/api/usrp/upload-noise-csv",
        )
        commands: list[str] = []

        def fake_run(command: str, use_sudo_password: bool = False):
            commands.append(command)
            if command == "systemctl is-active drone":
                return 0, "active", ""
            if command.startswith("cat "):
                return 0, '{"mission_id":"flight_001","state":"running","upload_state":"recording"}', ""
            if command.startswith("systemctl status") or command.startswith("journalctl"):
                return 0, "Active: active (running)", ""
            return 0, "", ""

        phases: list[str] = []
        with patch.object(usrp_ctl, "_run_remote", side_effect=fake_run):
            result = usrp_ctl.start_capture_job("usrp", mission, progress=phases.append)

        self.assertEqual(phases, ["connecting", "configuring", "starting_service", "recording"])
        self.assertEqual(commands[0], "install -d /run/simworld")
        self.assertEqual(commands[1], "install -d -o user /var/lib/simworld/capture")
        self.assertEqual(commands[2], "install -d -o user /var/lib/simworld/capture/flight_001")
        self.assertIn("WORKDIR=/home/user/rx_sampling", commands[3])
        self.assertIn("NOISE_CSV=/home/user/rx_sampling/noise.csv", commands[3])
        self.assertIn("/run/simworld/usrp.env", commands[3])
        self.assertIn("/var/lib/simworld/capture/flight_001/mission.json", commands[4])
        self.assertIn('"scene":"NTPU"', commands[4])
        self.assertIn('"map_type":"iss"', commands[4])
        self.assertIn('"api_url":"http://192.168.50.95:8888/api/usrp/upload-noise-csv"', commands[4])
        self.assertEqual(commands[5], "systemctl start drone")

    def test_remote_status_combines_systemd_and_mission_json(self):
        from app import usrp_ctl

        def fake_run(command: str, use_sudo_password: bool = False):
            if command == "systemctl is-active drone_test":
                return 0, "active", ""
            if command.startswith("cat "):
                return 0, '{"mission_id":"flight_002","state":"running","upload_state":"recording"}', ""
            if command.startswith("systemctl status") or command.startswith("journalctl"):
                return 0, "Active: active (running)", ""
            return 0, "", ""

        with patch.object(usrp_ctl, "_run_remote", side_effect=fake_run):
            result = usrp_ctl.get_capture_job("test", "flight_002")

        self.assertEqual(result["service_state"], "running")
        self.assertEqual(result["mission_state"]["mission_id"], "flight_002")
        self.assertEqual(result["mission_state"]["upload_state"], "recording")

    def test_remote_stop_leaves_pending_upload_for_explicit_retry(self):
        from app import usrp_ctl

        calls: list[str] = []
        mission_path = "/var/lib/simworld/capture/flight_retry/mission.json"

        def fake_run(command: str, use_sudo_password: bool = False, timeout: float = 10):
            calls.append(command)
            if command == "systemctl stop drone":
                return 0, "", ""
            if command == "systemctl is-active drone":
                return 3, "inactive", ""
            if command == f"cat {mission_path}":
                return 0, '{"mission_id":"flight_retry","state":"upload_pending","upload_state":"upload_pending"}', ""
            if command.startswith("cat /run/simworld/usrp.env"):
                return 0, "MISSION_ID=flight_retry\nUPLOAD_API_URL=http://127.0.0.1:8888/api/usrp/upload-noise-csv\nSCENE=NTPU\nMAP_TYPE=iss\nWORKDIR=/home/user/rx_sampling\nNOISE_CSV=/home/user/rx_sampling/noise.csv", ""
            if command.startswith("systemctl status") or command.startswith("journalctl"):
                return 0, "Active: inactive", ""
            return 0, "", ""

        with patch.object(usrp_ctl, "_run_remote", side_effect=fake_run):
            result = usrp_ctl.stop_capture_job("usrp", "flight_retry")

        self.assertEqual(result["service_state"], "stopped")
        self.assertEqual(result["mission_state"]["upload_state"], "upload_pending")
        self.assertFalse(any("upload_noise_csv.py" in command for command in calls))

    def test_explicit_retry_uploads_existing_pending_mission(self):
        from app import usrp_ctl

        calls: list[str] = []
        mission_path = "/var/lib/simworld/capture/flight_retry/mission.json"
        env_path = "/run/simworld/usrp.env"

        def fake_run(command: str, use_sudo_password: bool = False):
            calls.append(command)
            if command == "systemctl stop drone":
                return 0, "", ""
            if command == "systemctl is-active drone":
                return 3, "inactive", ""
            if command == f"cat {mission_path}":
                return 0, '{"mission_id":"flight_retry","state":"stopped","upload_state":"upload_pending"}', ""
            if command == f"cat {env_path}":
                return 0, "MISSION_ID=flight_retry\nUPLOAD_API_URL=http://127.0.0.1:8888/api/usrp/upload-noise-csv\nSCENE=NTPU\nMAP_TYPE=iss\nWORKDIR=/home/user/rx_sampling\nNOISE_CSV=/home/user/rx_sampling/noise.csv", ""
            if command.startswith("cd /home/user/rx_sampling && python3 /home/user/upload_noise_csv.py "):
                return 0, "uploaded", ""
            if command.startswith("systemctl status") or command.startswith("journalctl"):
                return 0, "Active: inactive", ""
            return 0, "", ""

        with patch.object(usrp_ctl, "_run_remote", side_effect=fake_run):
            stopped = usrp_ctl.stop_capture_job("usrp", "flight_retry")
            result = usrp_ctl.retry_capture_upload("usrp", "flight_retry")

        self.assertEqual(stopped["mission_state"]["upload_state"], "upload_pending")
        self.assertEqual(result["mission_state"]["upload_state"], "uploaded")
        self.assertTrue(any("upload_noise_csv.py" in command for command in calls))

    def test_remote_stop_converts_recording_state_to_pending_upload(self):
        from app import usrp_ctl

        calls: list[str] = []
        mission_path = "/var/lib/simworld/capture/flight_recording/mission.json"
        env_path = "/run/simworld/usrp.env"

        def fake_run(command: str, use_sudo_password: bool = False):
            calls.append(command)
            if command == "systemctl stop drone":
                return 0, "", ""
            if command == "systemctl is-active drone":
                return 3, "inactive", ""
            if command == f"cat {mission_path}":
                return 0, '{"mission_id":"flight_recording","state":"starting","upload_state":"recording"}', ""
            if command == f"cat {env_path}":
                return 0, "MISSION_ID=flight_recording\nUPLOAD_API_URL=http://192.168.50.70:8888/api/usrp/upload-noise-csv\nSCENE=NTPU\nMAP_TYPE=iss\nWORKDIR=/home/user/rx_sampling\nNOISE_CSV=/home/user/rx_sampling/noise.csv", ""
            if command.startswith("cd /home/user/rx_sampling && python3 /home/user/upload_noise_csv.py "):
                return 0, "uploaded", ""
            if command.startswith("systemctl status") or command.startswith("journalctl"):
                return 0, "Active: inactive", ""
            return 0, "", ""

        with patch.object(usrp_ctl, "_run_remote", side_effect=fake_run):
            stopped = usrp_ctl.stop_capture_job("usrp", "flight_recording")
            result = usrp_ctl.retry_capture_upload("usrp", "flight_recording")

        self.assertEqual(stopped["mission_state"]["upload_state"], "upload_pending")
        self.assertEqual(result["mission_state"]["upload_state"], "uploaded")
        self.assertTrue(any("upload_noise_csv.py" in command for command in calls))

    def test_explicit_retry_write_back_failure_is_reported(self):
        from app import usrp_ctl

        mission_path = "/var/lib/simworld/capture/flight_retry/mission.json"
        env_path = "/run/simworld/usrp.env"

        def fake_run(command: str, use_sudo_password: bool = False):
            if command == "systemctl is-active drone":
                return 3, "inactive", ""
            if command == f"cat {mission_path}":
                return 0, '{"mission_id":"flight_retry","state":"stopped","upload_state":"upload_pending"}', ""
            if command == f"cat {env_path}":
                return 0, "MISSION_ID=flight_retry\nUPLOAD_API_URL=http://127.0.0.1:8888/api/usrp/upload-noise-csv\nSCENE=NTPU\nMAP_TYPE=iss\nNOISE_CSV=/home/user/rx_sampling/noise.csv", ""
            if command.startswith("cd /home/user/rx_sampling && python3 /home/user/upload_noise_csv.py "):
                return 0, "uploaded", ""
            if command.startswith("sh -c ") and mission_path in command and '"upload_state":"uploaded"' in command:
                return 1, "", "write failed"
            if command.startswith("systemctl status") or command.startswith("journalctl"):
                return 0, "Active: inactive", ""
            return 0, "", ""

        with patch.object(usrp_ctl, "_run_remote", side_effect=fake_run):
            with self.assertRaisesRegex(usrp_ctl.UsrpControlError, "write failed"):
                usrp_ctl.retry_capture_upload("usrp", "flight_retry")

    def test_remote_setup_falls_back_to_sudo_for_permission_style_failures(self):
        from app import usrp_ctl

        mission = usrp_ctl.RemoteMission(
            mission_id="flight_003",
            api_url="http://192.168.50.95:8888/api/usrp/upload-noise-csv",
        )
        cases = (
            ("install -d /run/simworld", "operation not permitted"),
            ("install -d -o user /var/lib/simworld/capture", "cannot change permissions on '/var/lib/simworld/capture'"),
            ("install -d -o user /var/lib/simworld/capture/flight_003", "cannot create directory '/var/lib/simworld/capture/flight_003'"),
        )

        for failing_command, failure in cases:
            with self.subTest(command=failing_command, failure=failure):
                calls: list[tuple[str, bool]] = []

                def fake_run(command: str, use_sudo_password: bool = False):
                    calls.append((command, use_sudo_password))
                    if command == failing_command and not use_sudo_password:
                        return 1, "", failure
                    if command == "systemctl is-active drone":
                        return 0, "active", ""
                    if command.startswith("cat "):
                        return 0, '{"mission_id":"flight_003","state":"running"}', ""
                    return 0, "", ""

                with patch.dict("os.environ", {"RASPI_PSW": "secret"}):
                    with patch.object(usrp_ctl, "_run_remote", side_effect=fake_run):
                        usrp_ctl.start_capture_job("usrp", mission)

                self.assertIn((failing_command, False), calls)
                self.assertIn((failing_command, True), calls)

    def test_each_remote_command_closes_its_ssh_client(self):
        from app import usrp_ctl

        class FakeChannel:
            def recv_exit_status(self):
                return 0

        class FakeStream:
            def __init__(self, value: bytes = b""):
                self.value = value
                self.channel = FakeChannel()

            def read(self):
                return self.value

            def close(self):
                return None

            def write(self, value):
                return None

            def flush(self):
                return None

        class FakeClient:
            def __init__(self):
                self.closed = False

            def exec_command(self, command, timeout):
                return FakeStream(), FakeStream(b"ok"), FakeStream()

            def close(self):
                self.closed = True

        client = FakeClient()
        with patch.object(usrp_ctl, "_ssh_client", return_value=client):
            with patch.object(
                usrp_ctl,
                "_config_from_env",
                return_value=usrp_ctl.RaspiConfig("host", "user", "password"),
            ):
                exit_code, out, err = usrp_ctl._run_remote("true")

        self.assertEqual((exit_code, out, err), (0, "ok", ""))
        self.assertTrue(client.closed)


if __name__ == "__main__":
    unittest.main()
