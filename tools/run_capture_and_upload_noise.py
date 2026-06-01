import argparse
import shlex
import subprocess
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a noise capture command, wait for noise.csv to settle, then upload it automatically."
    )
    parser.add_argument("--capture-cmd", required=True, help='Full capture command, e.g. "python noise.py"')
    parser.add_argument("--capture-workdir", default=".", help="Working directory for the capture command.")
    parser.add_argument("--noise-csv", required=True, help="Expected output noise.csv path.")
    parser.add_argument("--uploader-script", required=True, help="Path to upload_noise_csv.py.")
    parser.add_argument("--api-url", required=True, help="Laptop upload endpoint.")
    parser.add_argument("--scene", default="NTPU")
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--map-type", default="iss", choices=["sinr", "iss", "tss", "cfar"])
    parser.add_argument("--device-id", default="usrp-b210-sensor")
    parser.add_argument("--device-name", default="USRP B210 Sensor")
    parser.add_argument("--device-type", default="uav")
    parser.add_argument("--role", default="rx", choices=["rx", "tx", "jammer"])
    parser.add_argument("--devices-file", default="")
    parser.add_argument("--python-exe", default=sys.executable)
    parser.add_argument("--stable-seconds", type=float, default=5.0)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--auto-simulate-last", action="store_true")
    return parser.parse_args()


def wait_for_stable_file(path: Path, stable_seconds: float, poll_seconds: float) -> None:
    while not path.exists():
        time.sleep(poll_seconds)

    last_signature = None
    last_changed_at = time.time()
    while True:
        signature = (path.stat().st_size, path.stat().st_mtime_ns)
        now = time.time()
        if signature != last_signature:
            last_signature = signature
            last_changed_at = now
        elif now - last_changed_at >= stable_seconds:
            return
        time.sleep(poll_seconds)


def build_upload_command(args: argparse.Namespace, noise_csv: Path) -> list[str]:
    cmd = [
        args.python_exe,
        str(Path(args.uploader_script).resolve()),
        "--api-url",
        args.api_url,
        "--scene",
        args.scene,
        "--mission-id",
        args.mission_id,
        "--noise-csv",
        str(noise_csv),
        "--map-type",
        args.map_type,
        "--device-id",
        args.device_id,
        "--device-name",
        args.device_name,
        "--device-type",
        args.device_type,
        "--role",
        args.role,
    ]
    if args.devices_file:
        cmd.extend(["--devices-file", args.devices_file])
    if args.auto_simulate_last:
        cmd.append("--auto-simulate-last")
    return cmd


def main() -> int:
    args = parse_args()
    noise_csv = Path(args.noise_csv).resolve()
    capture_workdir = Path(args.capture_workdir).resolve()
    capture_cmd = shlex.split(args.capture_cmd)

    print(f"[capture-upload] starting capture: {capture_cmd}")
    proc = subprocess.run(capture_cmd, cwd=capture_workdir, check=False)
    if proc.returncode != 0:
        print(f"[capture-upload] capture failed with exit code {proc.returncode}", file=sys.stderr)
        return proc.returncode

    print(f"[capture-upload] capture finished, waiting for stable file: {noise_csv}")
    wait_for_stable_file(noise_csv, args.stable_seconds, args.poll_seconds)

    upload_cmd = build_upload_command(args, noise_csv)
    print(f"[capture-upload] uploading: {noise_csv}")
    upload_proc = subprocess.run(upload_cmd, check=False)
    if upload_proc.returncode != 0:
        print(f"[capture-upload] upload failed with exit code {upload_proc.returncode}", file=sys.stderr)
    return upload_proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
