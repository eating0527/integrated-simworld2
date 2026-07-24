import json
import os
import shlex
import time
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


REMOTE_UPLOAD_HELPER = "/home/user/upload_noise_csv.py"
START_CAPTURE_BUDGET = 35.0
STOP_CAPTURE_BUDGET = 35.0
UPLOAD_CAPTURE_BUDGET = 20.0
GET_CAPTURE_BUDGET = 25.0
SSH_TIMEOUT_CAP = 12.0
COMMAND_TIMEOUT_CAP = 8.0


class UsrpControlError(RuntimeError):
    pass


class UsrpCommandTimeout(UsrpControlError):
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


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise UsrpControlError("remote operation timed out")
    return remaining


def _call_with_deadline(function, *args, deadline: float | None = None, **kwargs):
    if deadline is None:
        return function(*args, **kwargs)
    try:
        return function(*args, deadline=deadline, **kwargs)
    except TypeError as exc:
        if "deadline" not in str(exc):
            raise
        return function(*args, **kwargs)


def _session_command(client, command: str, deadline: float, input_text: str | None = None):
    stdin = stdout = stderr = None
    channel = None
    timed_out = False
    try:
        timeout = min(COMMAND_TIMEOUT_CAP, _remaining(deadline))
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        channel = stdout.channel
        if input_text is not None:
            stdin.write(input_text)
            stdin.flush()
        stdin.close()
        while not channel.exit_status_ready():
            try:
                _remaining(deadline)
            except UsrpControlError as exc:
                timed_out = True
                raise UsrpCommandTimeout("remote command timed out") from exc
            time.sleep(0.01)
        code = channel.recv_exit_status()
        return (
            code,
            _redact(stdout.read().decode("utf-8", errors="replace").strip()),
            _redact(stderr.read().decode("utf-8", errors="replace").strip()),
        )
    except UsrpCommandTimeout:
        raise
    except Exception as exc:
        raise UsrpControlError(
            _redact(f"remote command failed: {type(exc).__name__}")
        ) from exc
    finally:
        for stream in (stdin, stdout, stderr):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass
        if channel is not None:
            try:
                channel.close()
            except Exception:
                pass
        if timed_out:
            try:
                client.close()
            except Exception:
                pass


def _ssh_client(config: RaspiConfig, deadline: float | None = None):
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
            timeout=min(SSH_TIMEOUT_CAP, _remaining(deadline)) if deadline is not None else SSH_TIMEOUT_CAP,
            banner_timeout=min(SSH_TIMEOUT_CAP, _remaining(deadline)) if deadline is not None else SSH_TIMEOUT_CAP,
            auth_timeout=min(SSH_TIMEOUT_CAP, _remaining(deadline)) if deadline is not None else SSH_TIMEOUT_CAP,
            look_for_keys=False,
            allow_agent=False,
        )
    except Exception as exc:
        try:
            client.close()
        finally:
            raise UsrpControlError(_redact(f"SSH failed: {exc}")) from exc
    return client


def _run_remote(
    command: str,
    use_sudo_password: bool = False,
    deadline: float | None = None,
) -> tuple[int, str, str]:
    if deadline is not None:
        client = _ssh_client(_config_from_env(), deadline=deadline)
        try:
            remote_command = command
            if use_sudo_password:
                remote_command = f"sudo -S -p '' {command}"
            return _session_command(
                client,
                remote_command,
                deadline,
                (os.environ.get("RASPI_PSW", "") + "\n") if use_sudo_password else None,
            )
        finally:
            client.close()

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


_ORIGINAL_RUN_REMOTE = _run_remote


def _state_from_active_output(output: str, exit_code: int) -> ServiceState:
    value = output.strip().lower()
    if exit_code == 0 and value == "active":
        return "running"
    if value in {"inactive", "failed"}:
        return "stopped"
    if value == "deactivating":
        return "unknown"
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


def _service_messages(target: ServiceTarget, deadline: float | None = None) -> list[str]:
    commands = [
        f"systemctl status --no-pager -l {target.unit}",
        f"journalctl -u {target.unit} -n 20 --no-pager",
    ]
    messages: list[str] = []
    for command in commands:
        exit_code, out, err = _call_with_deadline(_run_remote, command, deadline=deadline)
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


def _run_service_control(command: str, deadline: float | None = None) -> tuple[int, str, str]:
    exit_code, out, err = _call_with_deadline(_run_remote, command, deadline=deadline)
    if exit_code != 0 and _needs_interactive_auth(out, err):
        exit_code, out, err = _call_with_deadline(
            _run_remote, command, use_sudo_password=True, deadline=deadline
        )
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


def _read_mission_state(
    mission_id: str, state_dir: str | None = None, deadline: float | None = None
) -> dict:
    path = _mission_state_path(mission_id, state_dir)
    exit_code, out, _ = _call_with_deadline(
        _run_remote, f"cat {shlex.quote(path)}", deadline=deadline
    )
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


def _mission_metadata(mission: RemoteMission, *, state: str, upload_state: str) -> dict[str, str]:
    return {
        "mission_id": mission.mission_id,
        "state": state,
        "upload_state": upload_state,
        "noise_csv": mission.noise_csv,
        "scene": mission.scene,
        "map_type": mission.map_type,
        "api_url": mission.api_url,
    }


def _write_remote_mission_state(
    mission: RemoteMission, payload: dict, deadline: float | None = None
) -> tuple[int, str, str]:
    path = _mission_state_path(mission)
    directory = str(PurePosixPath(path).parent)
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    script = (
        f"mkdir -p {shlex.quote(directory)} && "
        f"printf '%s\\n' {shlex.quote(compact)} > {shlex.quote(path)}"
    )
    return _run_service_control(f"sh -c {shlex.quote(script)}", deadline=deadline)


def _persist_remote_mission_state(
    mission: RemoteMission, payload: dict, deadline: float | None = None
) -> None:
    exit_code, out, err = _write_remote_mission_state(mission, payload, deadline=deadline)
    if exit_code != 0:
        raise UsrpControlError(err or out or "failed to write remote mission state")


def _read_remote_env(path: str, deadline: float | None = None) -> dict[str, str]:
    exit_code, out, _ = _call_with_deadline(
        _run_remote, f"cat {shlex.quote(path)}", deadline=deadline
    )
    if exit_code != 0 or not out:
        return {}
    values: dict[str, str] = {}
    for line in out.splitlines():
        key, sep, value = line.partition("=")
        if sep and key:
            values[key] = value
    return values


def _repair_mission_state(
    mission_id: str,
    mission_state: dict,
    state_dir: str | None = None,
    deadline: float | None = None,
) -> dict:
    env = _read_remote_env("/run/simworld/usrp.env", deadline=deadline)
    merged = dict(mission_state)
    merged.setdefault("mission_id", env.get("MISSION_ID", mission_id))
    merged.setdefault("noise_csv", env.get("NOISE_CSV", "/home/user/rx_sampling/noise.csv"))
    merged.setdefault("scene", env.get("SCENE", "NTPU"))
    merged.setdefault("map_type", env.get("MAP_TYPE", "iss"))
    merged.setdefault("api_url", env.get("UPLOAD_API_URL", ""))
    path = _mission_state_path(mission_id, state_dir)
    mission = RemoteMission(
        mission_id=merged["mission_id"],
        api_url=merged["api_url"],
        scene=merged["scene"],
        map_type=merged["map_type"],
        noise_csv=merged["noise_csv"],
        work_dir=str(PurePosixPath(merged["noise_csv"]).parent),
        state_dir=str(PurePosixPath(path).parent.parent),
    )
    _write_remote_mission_state(mission, merged, deadline=deadline)
    return merged


def _remote_upload_command(mission_state: dict) -> str:
    noise_csv = mission_state["noise_csv"]
    work_dir = str(PurePosixPath(noise_csv).parent)
    parts = [
        "python3",
        REMOTE_UPLOAD_HELPER,
        "--mission-id",
        mission_state["mission_id"],
        "--noise-csv",
        noise_csv,
        "--api-url",
        mission_state["api_url"],
    ]
    scene = mission_state.get("scene")
    map_type = mission_state.get("map_type")
    if scene:
        parts.extend(["--scene", scene])
    if map_type:
        parts.extend(["--map-type", map_type])
    command = " ".join(shlex.quote(part) for part in parts)
    return f"cd {shlex.quote(work_dir)} && {command}"


def _get_capture_job(
    mode: str, mission_id: str, state_dir: str | None = None, deadline: float | None = None
) -> dict:
    target = _service_target(mode)
    if deadline is None:
        deadline = time.monotonic() + GET_CAPTURE_BUDGET
    if _run_remote is not _ORIGINAL_RUN_REMOTE:
        service_code, service_out, service_err = _call_with_deadline(
            _run_remote, f"systemctl is-active {target.unit}", deadline=deadline
        )
        mission_code, mission_out, _ = _call_with_deadline(
            _run_remote,
            f"cat {shlex.quote(_mission_state_path(mission_id, state_dir))}",
            deadline=deadline,
        )
        try:
            mission_state = json.loads(mission_out) if mission_code == 0 and mission_out else {}
        except json.JSONDecodeError as exc:
            raise UsrpControlError(f"invalid remote mission state: {exc}") from exc
        status = _response(
            target,
            _state_from_active_output(service_out, service_code),
            f"{target.service_name} status",
        )
        status["mission_id"] = mission_id
        status["mission_state"] = mission_state
        return status

    client = _ssh_client(_config_from_env(), deadline=deadline)
    try:
        service_code, service_out, _ = _session_command(
            client, f"systemctl is-active {target.unit}", deadline
        )
        mission_code, mission_out, _ = _session_command(
            client,
            f"cat {shlex.quote(_mission_state_path(mission_id, state_dir))}",
            deadline,
        )
        try:
            mission_state = json.loads(mission_out) if mission_code == 0 and mission_out else {}
        except json.JSONDecodeError as exc:
            raise UsrpControlError(f"invalid remote mission state: {exc}") from exc
        status = _response(
            target,
            _state_from_active_output(service_out, service_code),
            f"{target.service_name} status",
        )
        status["mission_id"] = mission_id
        status["mission_state"] = mission_state
        return status
    finally:
        client.close()


def get_capture_job(mode: str, mission_id: str, state_dir: str | None = None) -> dict:
    return _get_capture_job(mode, mission_id, state_dir)


def _capture_mission_from_state(
    mission_state: dict, state_dir: str | None = None
) -> RemoteMission:
    return RemoteMission(
        mission_id=mission_state["mission_id"],
        api_url=mission_state["api_url"],
        scene=mission_state.get("scene", "NTPU"),
        map_type=mission_state.get("map_type", "iss"),
        noise_csv=mission_state["noise_csv"],
        work_dir=str(PurePosixPath(mission_state["noise_csv"]).parent),
        state_dir=(state_dir or os.environ.get("RASPI_STATE_DIR", "/var/lib/simworld/capture")),
    )


def start_capture_job(mode: str, mission: RemoteMission) -> dict:
    target = _service_target(mode)
    deadline = time.monotonic() + START_CAPTURE_BUDGET
    runtime_dir = str(PurePosixPath(mission.env_file).parent)
    mission_dir = str(PurePosixPath(mission.state_dir) / mission.mission_id)
    for command in (
        f"install -d {shlex.quote(runtime_dir)}",
        f"install -d -o {shlex.quote(mission.run_user)} {shlex.quote(mission.state_dir)}",
        f"install -d -o {shlex.quote(mission.run_user)} {shlex.quote(mission_dir)}",
        _mission_environment(mission),
        _write_remote_mission_state.__name__,
        f"systemctl start {target.unit}",
    ):
        if command == _write_remote_mission_state.__name__:
            exit_code, out, err = _write_remote_mission_state(
                mission,
                _mission_metadata(mission, state="starting", upload_state="recording"),
                deadline=deadline,
            )
        else:
            exit_code, out, err = _run_service_control(command, deadline=deadline)
        if exit_code != 0:
            raise UsrpControlError(err or out or f"{command} failed")
    status = _get_capture_job(mode, mission.mission_id, mission.state_dir, deadline)
    status["message"] = f"{target.service_name} started"
    return status


def stop_capture_job(mode: str, mission_id: str, state_dir: str | None = None) -> dict:
    target = _service_target(mode)
    deadline = time.monotonic() + STOP_CAPTURE_BUDGET
    exit_code, out, err = _run_service_control(f"systemctl stop {target.unit}", deadline=deadline)
    if exit_code != 0:
        raise UsrpControlError(err or out or f"systemctl stop {target.unit} failed")
    status = _get_capture_job(mode, mission_id, state_dir, deadline)
    mission_state = status.get("mission_state") or {}
    pending = mission_state.get("upload_state") in {
        "recording", "finalizing", "upload_pending"
    } or mission_state.get("state") == "upload_pending"
    if status.get("service_state") == "stopped" and pending:
        mission_state = _repair_mission_state(
            mission_id, mission_state, state_dir, deadline=deadline
        )
        mission_state["state"] = "stopped"
        mission_state["upload_state"] = "upload_pending"
        _persist_remote_mission_state(
            _capture_mission_from_state(mission_state, state_dir),
            mission_state,
            deadline=deadline,
        )
        status["mission_state"] = mission_state
    status["message"] = f"{target.service_name} stopped"
    return status


def retry_capture_upload(
    mode: str, mission_id: str, state_dir: str | None = None
) -> dict:
    target = _service_target(mode)
    deadline = time.monotonic() + UPLOAD_CAPTURE_BUDGET
    status = _get_capture_job(mode, mission_id, state_dir, deadline)
    mission_state = status.get("mission_state") or {}
    if not mission_state:
        raise UsrpControlError("mission state is unavailable")
    mission_state = _repair_mission_state(
        mission_id, mission_state, state_dir, deadline=deadline
    )
    exit_code, out, err = _run_service_control(
        _remote_upload_command(mission_state), deadline=deadline
    )
    if exit_code == 0:
        mission_state["state"] = "stopped"
        mission_state["upload_state"] = "uploaded"
    elif mission_state.get("state") != "failed":
        mission_state["state"] = "stopped"
        mission_state["upload_state"] = "upload_pending"
    _persist_remote_mission_state(
        _capture_mission_from_state(mission_state, state_dir),
        mission_state,
        deadline=deadline,
    )
    status["mission_state"] = mission_state
    status["message"] = f"{target.service_name} upload retried"
    return status
