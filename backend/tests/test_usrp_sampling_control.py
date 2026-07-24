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

        with patch.object(usrp_ctl, "_run_remote", side_effect=fake_run):
            result = usrp_ctl.start_capture_job("usrp", mission)

        self.assertEqual(result["mission_id"], "flight_001")
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
        env_path = "/run/simworld/usrp.env"

        def fake_run(command: str, use_sudo_password: bool = False):
            calls.append(command)
            if command == "systemctl stop drone":
                return 0, "", ""
            if command == "systemctl is-active drone":
                return 3, "inactive", ""
            if command == f"cat {mission_path}":
                return 0, '{"mission_id":"flight_retry","state":"upload_pending","upload_state":"upload_pending"}', ""
            if command == f"cat {env_path}":
                return 0, "MISSION_ID=flight_retry\nUPLOAD_API_URL=http://127.0.0.1:8888/api/usrp/upload-noise-csv\nSCENE=NTPU\nMAP_TYPE=iss\nWORKDIR=/home/user/rx_sampling\nNOISE_CSV=/home/user/rx_sampling/noise.csv", ""
            if command.startswith("sh -c "):
                return 0, "", ""
            if command.startswith("systemctl status") or command.startswith("journalctl"):
                return 0, "Active: inactive", ""
            return 0, "", ""

        with patch.object(usrp_ctl, "_run_remote", side_effect=fake_run):
            result = usrp_ctl.stop_capture_job("usrp", "flight_retry")

        self.assertEqual(result["service_state"], "stopped")
        self.assertEqual(result["mission_state"]["upload_state"], "upload_pending")
        self.assertFalse(any("upload_noise_csv.py" in command for command in calls))

    def test_remote_stop_does_not_upload_when_upload_state_is_pending(self):
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
                return (
                    0,
                    '{"mission_id":"flight_retry","state":"stopped","upload_state":"upload_pending"}',
                    "",
                )
            if command == f"cat {env_path}":
                return (
                    0,
                    "MISSION_ID=flight_retry\nUPLOAD_API_URL=http://127.0.0.1:8888/api/usrp/upload-noise-csv\nSCENE=NTPU\nMAP_TYPE=iss\nWORKDIR=/home/user/rx_sampling\nNOISE_CSV=/home/user/rx_sampling/noise.csv",
                    "",
                )
            if command.startswith("cd /home/user/rx_sampling && python3 /home/user/upload_noise_csv.py "):
                return 0, "uploaded", ""
            if command.startswith("systemctl status") or command.startswith("journalctl"):
                return 0, "Active: inactive", ""
            return 0, "", ""

        with patch.object(usrp_ctl, "_run_remote", side_effect=fake_run):
            result = usrp_ctl.stop_capture_job("usrp", "flight_retry")

        self.assertEqual(result["service_state"], "stopped")
        self.assertFalse(any("upload_noise_csv.py" in command for command in calls))

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
            result = usrp_ctl.stop_capture_job("usrp", "flight_recording")

        self.assertEqual(result["mission_state"]["upload_state"], "upload_pending")
        self.assertFalse(any("upload_noise_csv.py" in command for command in calls))

    def test_remote_stop_raises_when_retry_write_back_fails(self):
        from app import usrp_ctl

        mission_path = "/var/lib/simworld/capture/flight_retry/mission.json"
        env_path = "/run/simworld/usrp.env"

        def fake_run(command: str, use_sudo_password: bool = False):
            if command == "systemctl stop drone":
                return 0, "", ""
            if command == "systemctl is-active drone":
                return 3, "inactive", ""
            if command == f"cat {mission_path}":
                return (
                    0,
                    '{"mission_id":"flight_retry","state":"stopped","upload_state":"upload_pending"}',
                    "",
                )
            if command == f"cat {env_path}":
                return (
                    0,
                    "MISSION_ID=flight_retry\nUPLOAD_API_URL=http://127.0.0.1:8888/api/usrp/upload-noise-csv\nSCENE=NTPU\nMAP_TYPE=iss\nNOISE_CSV=/home/user/rx_sampling/noise.csv",
                    "",
                )
            if command.startswith("cd /home/user/rx_sampling && python3 /home/user/upload_noise_csv.py "):
                return 0, "uploaded", ""
            if command.startswith("sh -c ") and mission_path in command and '"upload_state":"uploaded"' in command:
                return 1, "", "write failed"
            if command.startswith("systemctl status") or command.startswith("journalctl"):
                return 0, "Active: inactive", ""
            return 0, "", ""

        with patch.object(usrp_ctl, "_run_remote", side_effect=fake_run):
            result = usrp_ctl.stop_capture_job("usrp", "flight_retry")

        self.assertEqual(result["mission_state"]["upload_state"], "upload_pending")

    def test_retry_capture_upload_uses_separate_upload_operation(self):
        from app import usrp_ctl

        calls: list[str] = []
        mission_path = "/var/lib/simworld/capture/retry/mission.json"

        def fake_run(command: str, use_sudo_password: bool = False):
            calls.append(command)
            if command == "systemctl is-active drone":
                return 3, "inactive", ""
            if command == f"cat {mission_path}":
                return 0, '{"mission_id":"retry","state":"stopped","upload_state":"upload_pending","noise_csv":"/home/user/rx_sampling/noise.csv","api_url":"http://upload"}', ""
            if command.startswith("cd /home/user/rx_sampling && python3"):
                return 0, "uploaded", ""
            return 0, "", ""

        with patch.object(usrp_ctl, "_run_remote", side_effect=fake_run):
            result = usrp_ctl.retry_capture_upload("usrp", "retry")

        self.assertEqual(result["mission_state"]["upload_state"], "uploaded")
        self.assertTrue(any("upload_noise_csv.py" in command for command in calls))

    def test_capture_operation_budgets_are_named(self):
        from app import usrp_ctl

        self.assertEqual(usrp_ctl.START_CAPTURE_BUDGET, 35.0)
        self.assertEqual(usrp_ctl.STOP_CAPTURE_BUDGET, 35.0)
        self.assertEqual(usrp_ctl.UPLOAD_CAPTURE_BUDGET, 20.0)

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

    def test_compound_status_uses_one_session_and_two_commands(self):
        from app import usrp_ctl

        class Channel:
            def __init__(self):
                self.closed = False

            def exit_status_ready(self):
                return True

            def recv_exit_status(self):
                return 0

            def close(self):
                self.closed = True

        class Stream:
            def __init__(self, value=b""):
                self.channel = Channel()
                self.value = value
                self.closed = False
            def read(self):
                return self.value
            def close(self):
                self.closed = True

        class Client:
            def __init__(self):
                self.commands = []
                self.closed = False
            def exec_command(self, command, timeout):
                self.commands.append((command, timeout))
                value = b"active" if len(self.commands) == 1 else b'{"state":"running"}'
                return Stream(), Stream(value), Stream()
            def close(self):
                self.closed = True

        client = Client()
        with patch.object(usrp_ctl, "_config_from_env", return_value=usrp_ctl.RaspiConfig("h", "u", "p")):
            with patch.object(usrp_ctl, "_ssh_client", return_value=client) as connect:
                result = usrp_ctl.get_capture_job("usrp", "m1")
        self.assertEqual(result["service_state"], "running")
        self.assertEqual(len(client.commands), 2)
        self.assertEqual(connect.call_count, 1)
        self.assertTrue(client.closed)
        self.assertTrue(all(timeout <= 8 for _, timeout in client.commands))

    def test_compound_status_rejects_malformed_mission_json_and_closes(self):
        from app import usrp_ctl

        class Channel:
            def exit_status_ready(self):
                return True

            def recv_exit_status(self):
                return 0

            def close(self):
                return None

        class Stream:
            def __init__(self, value=b""):
                self.channel = Channel()
                self.value = value
                self.closed = False

            def read(self):
                return self.value

            def close(self):
                self.closed = True

        class Client:
            def __init__(self):
                self.closed = False
                self.called = False

            def exec_command(self, command, timeout):
                value = b"active" if not self.called else b"{bad"
                self.called = True
                return Stream(), Stream(value), Stream()

            def close(self):
                self.closed = True
        client = Client()
        with patch.object(usrp_ctl, "_config_from_env", return_value=usrp_ctl.RaspiConfig("h", "u", "secret")):
            with patch.object(usrp_ctl, "_ssh_client", return_value=client):
                with self.assertRaises(usrp_ctl.UsrpControlError):
                    usrp_ctl.get_capture_job("usrp", "m1")
        self.assertTrue(client.closed)

    def test_compound_status_uses_remaining_budget_for_second_command(self):
        from app import usrp_ctl

        class Channel:
            def __init__(self, ready_after=0):
                self.ready_after = ready_after
                self.checks = 0
                self.closed = False

            def exit_status_ready(self):
                self.checks += 1
                return self.checks > self.ready_after

            def recv_exit_status(self):
                return 0

            def close(self):
                self.closed = True

        class Stream:
            def __init__(self, value, channel):
                self.value = value
                self.channel = channel

            def read(self):
                return self.value

            def close(self):
                return None

        class Client:
            def __init__(self):
                self.calls = []
                self.channels = []
                self.closed = False

            def exec_command(self, command, timeout):
                self.calls.append((command, timeout))
                channel = Channel(1 if len(self.calls) == 1 else 0)
                self.channels.append(channel)
                value = b"active" if len(self.calls) == 1 else b'{"state":"running"}'
                return Stream(b"", channel), Stream(value, channel), Stream(b"", channel)

            def close(self):
                self.closed = True

        client = Client()
        clock = iter((0.0, 1.0, 10.0, 20.0))
        with patch.object(usrp_ctl, "time") as fake_time:
            fake_time.monotonic.side_effect = clock
            fake_time.sleep.return_value = None
            with patch.object(usrp_ctl, "_config_from_env", return_value=usrp_ctl.RaspiConfig("h", "u", "p")):
                with patch.object(usrp_ctl, "_ssh_client", return_value=client):
                    result = usrp_ctl.get_capture_job("usrp", "m1")

        self.assertEqual(result["mission_state"], {"state": "running"})
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[0][1], usrp_ctl.COMMAND_TIMEOUT_CAP)
        self.assertEqual(client.calls[1][1], 5.0)
        self.assertTrue(client.closed)

    def test_compound_status_timeout_closes_channel_and_skips_second_command(self):
        from app import usrp_ctl

        class Channel:
            def __init__(self):
                self.closed = False

            def exit_status_ready(self):
                return False

            def recv_exit_status(self):
                return 0

            def close(self):
                self.closed = True

        class Stream:
            def __init__(self, channel):
                self.channel = channel

            def read(self):
                return b"active"

            def close(self):
                return None

        class Client:
            def __init__(self):
                self.commands = 0
                self.channel = Channel()
                self.closed = False

            def exec_command(self, command, timeout):
                self.commands += 1
                return Stream(self.channel), Stream(self.channel), Stream(self.channel)

            def close(self):
                self.closed = True

        client = Client()
        with patch.object(usrp_ctl, "time") as fake_time:
            fake_time.monotonic.side_effect = (0.0, 1.0, 26.0)
            with patch.object(usrp_ctl, "_config_from_env", return_value=usrp_ctl.RaspiConfig("h", "u", "p")):
                with patch.object(usrp_ctl, "_ssh_client", return_value=client):
                    with self.assertRaises(usrp_ctl.UsrpCommandTimeout):
                        usrp_ctl.get_capture_job("usrp", "m1")

        self.assertEqual(client.commands, 1)
        self.assertTrue(client.channel.closed)
        self.assertTrue(client.closed)

    def test_compound_status_does_not_run_diagnostics(self):
        from app import usrp_ctl
        commands = []
        class Channel:
            def exit_status_ready(self):
                return True

            def recv_exit_status(self):
                return 0

            def close(self):
                return None
        class Stream:
            def __init__(self, value): self.channel, self.value = Channel(), value
            def read(self): return self.value
            def close(self): pass
        class Client:
            def exec_command(self, command, timeout):
                commands.append(command)
                return Stream(b""), Stream(b"active" if len(commands) == 1 else b"{}"), Stream(b"")
            def close(self): pass
        with patch.object(usrp_ctl, "_config_from_env", return_value=usrp_ctl.RaspiConfig("h", "u", "p")):
            with patch.object(usrp_ctl, "_ssh_client", return_value=Client()):
                usrp_ctl.get_capture_job("usrp", "m1")
        self.assertEqual(commands, ["systemctl is-active drone", "cat /var/lib/simworld/capture/m1/mission.json"])

    def test_deactivating_service_is_unknown(self):
        from app import usrp_ctl
        with patch.object(usrp_ctl, "_run_remote", side_effect=[(3, "deactivating", ""), (0, "{}", "")]):
            result = usrp_ctl.get_capture_job("usrp", "m1")
        self.assertEqual(result["service_state"], "unknown")

    def test_compound_command_errors_are_redacted(self):
        from app import usrp_ctl
        class Client:
            def exec_command(self, command, timeout): raise RuntimeError("secret-password")
            def close(self): pass
        with patch.object(usrp_ctl, "_config_from_env", return_value=usrp_ctl.RaspiConfig("h", "u", "secret-password")):
            with patch.object(usrp_ctl, "_ssh_client", return_value=Client()):
                with self.assertRaises(usrp_ctl.UsrpControlError) as caught:
                    usrp_ctl.get_capture_job("usrp", "m1")
        self.assertNotIn("secret-password", str(caught.exception))

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
