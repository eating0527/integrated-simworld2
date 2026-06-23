import os
import threading
from dataclasses import dataclass
from typing import Literal


ServiceState = Literal["running", "stopped", "unknown"]


@dataclass(frozen=True)
class RaspiConfig:
    host: str
    user: str
    password: str
    port: int = 22


class UsrpControlError(RuntimeError):
    pass


_CLIENT_LOCK = threading.Lock()
_CONNECTED_CLIENT = None


def _redact(value: str) -> str:
    password = os.environ.get("RASPI_PSW", "")
    if password:
        value = value.replace(password, "[redacted]")
    return value


def _config_from_env() -> RaspiConfig:
    host = os.environ.get("RASPI_HOST", "").strip()
    user = os.environ.get("RASPI_USER", "").strip()
    password = os.environ.get("RASPI_PSW", "")
    port_raw = os.environ.get("RASPI_PORT", "22").strip() or "22"

    missing = [
        name
        for name, value in (
            ("RASPI_HOST", host),
            ("RASPI_USER", user),
            ("RASPI_PSW", password),
        )
        if not value
    ]
    if missing:
        raise UsrpControlError(f"{', '.join(missing)} is required")

    try:
        port = int(port_raw)
    except ValueError as exc:
        raise UsrpControlError("RASPI_PORT must be an integer") from exc

    return RaspiConfig(host=host, user=user, password=password, port=port)


def _ssh_client(config: RaspiConfig):
    try:
        import paramiko
    except ImportError as exc:
        raise UsrpControlError("paramiko is required for RasPi SSH control") from exc

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=config.host,
            port=config.port,
            username=config.user,
            password=config.password,
            timeout=8,
            banner_timeout=8,
            auth_timeout=8,
            look_for_keys=False,
            allow_agent=False,
        )
    except Exception as exc:
        try:
            client.close()
        finally:
            raise UsrpControlError(_redact(f"SSH failed: {exc}")) from exc
    return client


def _close_connected_client() -> None:
    global _CONNECTED_CLIENT
    with _CLIENT_LOCK:
        if _CONNECTED_CLIENT is not None:
            try:
                _CONNECTED_CLIENT.close()
            finally:
                _CONNECTED_CLIENT = None


def _connected_client():
    global _CONNECTED_CLIENT
    with _CLIENT_LOCK:
        if _CONNECTED_CLIENT is None:
            _CONNECTED_CLIENT = _ssh_client(_config_from_env())
        return _CONNECTED_CLIENT


def _run_remote(command: str, use_sudo_password: bool = False, *, persistent: bool = True) -> tuple[int, str, str]:
    client = _connected_client() if persistent else _ssh_client(_config_from_env())
    try:
        remote_command = command
        if use_sudo_password:
            remote_command = f"sudo -S -p '' {command}"
        stdin, stdout, stderr = client.exec_command(remote_command, timeout=10)
        if use_sudo_password:
            stdin.write(os.environ.get("RASPI_PSW", "") + "\n")
            stdin.flush()
        try:
            stdin.close()
        except Exception:
            pass
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        return exit_code, _redact(out), _redact(err)
    except Exception as exc:
        if persistent:
            _close_connected_client()
        raise UsrpControlError(_redact(f"remote command failed: {exc}")) from exc
    finally:
        if not persistent:
            client.close()


def _state_from_active_output(output: str, exit_code: int) -> ServiceState:
    value = output.strip().lower()
    if exit_code == 0 and value == "active":
        return "running"
    if value in {"inactive", "failed", "deactivating"}:
        return "stopped"
    return "unknown"


def _response(state: ServiceState, message: str, service_messages: list[str] | None = None) -> dict:
    return {
        "success": True,
        "raspi_connected": True,
        "session_connected": _CONNECTED_CLIENT is not None,
        "service_state": state,
        "message": message,
        "service_messages": service_messages or [],
    }


def _service_messages() -> list[str]:
    commands = [
        "systemctl status --no-pager -l drone",
        "journalctl -u drone -n 20 --no-pager",
    ]
    messages: list[str] = []
    for command in commands:
        exit_code, out, err = _run_remote(command)
        text = out or err
        if text:
            messages.extend(line for line in text.splitlines() if line.strip())
        elif exit_code != 0:
            messages.append(f"{command} exited with {exit_code}")
    return messages[-40:]


def get_drone_status() -> dict:
    exit_code, out, err = _run_remote("systemctl is-active drone")
    state = _state_from_active_output(out, exit_code)
    if state == "running":
        return _response("running", "drone.service running", _service_messages())
    if state == "stopped":
        return _response("stopped", "drone.service stopped", _service_messages())
    detail = err or out or "drone.service status unknown"
    return _response("unknown", detail, _service_messages())


def _needs_interactive_auth(out: str, err: str) -> bool:
    text = f"{out}\n{err}".lower()
    return "interactive authentication required" in text or "authentication is required" in text


def _run_service_control(command: str) -> tuple[int, str, str]:
    exit_code, out, err = _run_remote(command)
    if exit_code != 0 and _needs_interactive_auth(out, err):
        exit_code, out, err = _run_remote(command, use_sudo_password=True)
    return exit_code, out, err


def connect_raspi() -> dict:
    _connected_client()
    status = get_drone_status()
    status["message"] = "RasPi connected"
    return status


def disconnect_raspi() -> dict:
    _close_connected_client()
    return {
        "success": True,
        "raspi_connected": False,
        "session_connected": False,
        "service_state": "unknown",
        "message": "RasPi disconnected",
        "service_messages": [],
    }


def get_drone_messages() -> dict:
    status = get_drone_status()
    status["message"] = "drone.service messages loaded"
    return status


def start_drone_service() -> dict:
    exit_code, out, err = _run_service_control("systemctl start drone")
    if exit_code != 0:
        raise UsrpControlError(err or out or "systemctl start drone failed")
    status = get_drone_status()
    status["service_state"] = "running"
    status["message"] = "drone.service started"
    return status


def stop_drone_service() -> dict:
    exit_code, out, err = _run_service_control("systemctl stop drone")
    if exit_code != 0:
        raise UsrpControlError(err or out or "systemctl stop drone failed")
    status = get_drone_status()
    status["service_state"] = "stopped"
    status["message"] = "drone.service stopped"
    return status
