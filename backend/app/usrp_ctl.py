import json
import os
import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal


ServiceMode = Literal["test", "usrp"]
ServiceState = Literal["running", "stopped", "unknown"]


@dataclass(frozen=True)
class RaspiConfig:
    host: str
    user: str
    password: str
    port: int = 22


@dataclass(frozen=True)
class ServiceTarget:
    mode: ServiceMode
    unit: str
    service_name: str


@dataclass(frozen=True)
class RemoteMission:
    mission_id: str
    api_url: str
    scene: str = "NTPU"
    map_type: str = "iss"
    work_dir: str = "/home/user/rx_sampling"
    noise_csv: str = "/home/user/rx_sampling/noise.csv"
    state_dir: str = "/var/lib/simworld/capture"
    env_file: str = "/run/simworld/usrp.env"
    run_user: str = "user"


class UsrpControlError(RuntimeError):
    pass


SERVICE_TARGETS: dict[str, ServiceTarget] = {
    "test": ServiceTarget(mode="test", unit="drone_test", service_name="drone_test.service"),
    "usrp": ServiceTarget(mode="usrp", unit="drone", service_name="drone.service"),
}

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


def _service_target(mode: str = "test") -> ServiceTarget:
    target = SERVICE_TARGETS.get(mode)
    if target is None:
        raise UsrpControlError("mode must be one of: test, usrp")
    return target


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


def _run_remote(command: str, use_sudo_password: bool = False) -> tuple[int, str, str]:
    client = _ssh_client(_config_from_env())
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
        raise UsrpControlError(_redact(f"remote command failed: {exc}")) from exc
    finally:
        client.close()


def _state_from_active_output(output: str, exit_code: int) -> ServiceState:
    value = output.strip().lower()
    if exit_code == 0 and value == "active":
        return "running"
    if value in {"inactive", "failed", "deactivating"}:
        return "stopped"
    return "unknown"


def _response(target: ServiceTarget, state: ServiceState, message: str, service_messages: list[str] | None = None) -> dict:
    return {
        "success": True,
        "raspi_connected": True,
        "session_connected": True,
        "mode": target.mode,
        "service_name": target.service_name,
        "service_state": state,
        "message": message,
        "service_messages": service_messages or [],
    }


def _service_messages(target: ServiceTarget) -> list[str]:
    commands = [
        f"systemctl status --no-pager -l {target.unit}",
        f"journalctl -u {target.unit} -n 20 --no-pager",
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


def get_drone_status(mode: str = "test") -> dict:
    target = _service_target(mode)
    exit_code, out, err = _run_remote(f"systemctl is-active {target.unit}")
    state = _state_from_active_output(out, exit_code)
    if state == "running":
        return _response(target, "running", f"{target.service_name} running", _service_messages(target))
    if state == "stopped":
        return _response(target, "stopped", f"{target.service_name} stopped", _service_messages(target))
    detail = err or out or f"{target.service_name} status unknown"
    return _response(target, "unknown", detail, _service_messages(target))


def _needs_interactive_auth(out: str, err: str) -> bool:
    text = f"{out}\n{err}".lower()
    return (
        "interactive authentication required" in text
        or "authentication is required" in text
        or "permission denied" in text
        or "operation not permitted" in text
        or "cannot change permissions" in text
        or "cannot create directory" in text
    )


def _run_service_control(command: str) -> tuple[int, str, str]:
    exit_code, out, err = _run_remote(command)
    if exit_code != 0 and _needs_interactive_auth(out, err):
        exit_code, out, err = _run_remote(command, use_sudo_password=True)
    return exit_code, out, err


def connect_raspi(mode: str = "test") -> dict:
    status = get_drone_status(mode)
    status["message"] = "RasPi connected"
    return status


def disconnect_raspi() -> dict:
    target = _service_target("test")
    return {
        "success": True,
        "raspi_connected": False,
        "session_connected": False,
        "mode": target.mode,
        "service_name": target.service_name,
        "service_state": "unknown",
        "message": "RasPi disconnected",
        "service_messages": [],
    }


def get_drone_messages(mode: str = "test") -> dict:
    status = get_drone_status(mode)
    status["message"] = f"{status['service_name']} messages loaded"
    return status


def start_drone_service(mode: str = "test") -> dict:
    target = _service_target(mode)
    exit_code, out, err = _run_service_control(f"systemctl start {target.unit}")
    if exit_code != 0:
        raise UsrpControlError(err or out or f"systemctl start {target.unit} failed")
    status = get_drone_status(mode)
    status["service_state"] = "running"
    status["message"] = f"{target.service_name} started"
    return status


def stop_drone_service(mode: str = "test") -> dict:
    target = _service_target(mode)
    exit_code, out, err = _run_service_control(f"systemctl stop {target.unit}")
    if exit_code != 0:
        raise UsrpControlError(err or out or f"systemctl stop {target.unit} failed")
    status = get_drone_status(mode)
    status["service_state"] = "stopped"
    status["message"] = f"{target.service_name} stopped"
    return status


def _mission_state_path(mission: RemoteMission | str, state_dir: str | None = None) -> str:
    if isinstance(mission, RemoteMission):
        return f"{mission.state_dir.rstrip('/')}/{mission.mission_id}/mission.json"
    root = (state_dir or os.environ.get("RASPI_STATE_DIR", "/var/lib/simworld/capture")).rstrip("/")
    return f"{root}/{mission}/mission.json"


def _read_mission_state(mission_id: str, state_dir: str | None = None) -> dict:
    path = _mission_state_path(mission_id, state_dir)
    exit_code, out, _ = _run_remote(f"cat {shlex.quote(path)}")
    if exit_code != 0 or not out:
        return {}
    try:
        value = json.loads(out)
    except json.JSONDecodeError as exc:
        raise UsrpControlError(f"invalid remote mission state: {exc}") from exc
    return value if isinstance(value, dict) else {}


def _mission_environment(mission: RemoteMission) -> str:
    values = {
        "MISSION_ID": mission.mission_id,
        "MISSION_STATE_DIR": mission.state_dir,
        "UPLOAD_API_URL": mission.api_url,
        "SCENE": mission.scene,
        "MAP_TYPE": mission.map_type,
        "WORKDIR": mission.work_dir,
        "NOISE_CSV": mission.noise_csv,
    }
    lines = [f"{key}={value}" for key, value in values.items()]
    printf_args = " ".join(shlex.quote(line) for line in lines)
    script = f"printf '%s\\n' {printf_args} > {shlex.quote(mission.env_file)}"
    return f"sh -c {shlex.quote(script)}"


def get_capture_job(mode: str, mission_id: str, state_dir: str | None = None) -> dict:
    status = get_drone_status(mode)
    status["mission_id"] = mission_id
    status["mission_state"] = _read_mission_state(mission_id, state_dir)
    return status


def start_capture_job(mode: str, mission: RemoteMission) -> dict:
    target = _service_target(mode)
    runtime_dir = str(PurePosixPath(mission.env_file).parent)
    mission_dir = str(PurePosixPath(mission.state_dir) / mission.mission_id)
    for command in (
        f"install -d {shlex.quote(runtime_dir)}",
        f"install -d -o {shlex.quote(mission.run_user)} {shlex.quote(mission.state_dir)}",
        f"install -d -o {shlex.quote(mission.run_user)} {shlex.quote(mission_dir)}",
        _mission_environment(mission),
        f"systemctl start {target.unit}",
    ):
        exit_code, out, err = _run_service_control(command)
        if exit_code != 0:
            raise UsrpControlError(err or out or f"{command} failed")
    status = get_capture_job(mode, mission.mission_id, mission.state_dir)
    status["message"] = f"{target.service_name} started"
    return status


def stop_capture_job(mode: str, mission_id: str, state_dir: str | None = None) -> dict:
    target = _service_target(mode)
    exit_code, out, err = _run_service_control(f"systemctl stop {target.unit}")
    if exit_code != 0:
        raise UsrpControlError(err or out or f"systemctl stop {target.unit} failed")
    status = get_capture_job(mode, mission_id, state_dir)
    status["message"] = f"{target.service_name} stopped"
    return status
