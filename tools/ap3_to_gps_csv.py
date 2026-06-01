import argparse
import csv
import subprocess
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

from pymavlink import mavutil


ROOT = Path(__file__).resolve().parents[1]
ADB = ROOT / "tools" / "platform-tools" / "adb.exe"


def run_adb_forward(local_port: int, remote_port: int) -> None:
    if not ADB.exists():
        raise FileNotFoundError(f"adb not found: {ADB}")
    subprocess.run([str(ADB), "forward", f"tcp:{local_port}", f"tcp:{remote_port}"], check=True)


def has_authorized_device() -> bool:
    if not ADB.exists():
        return False
    proc = subprocess.run([str(ADB), "devices"], check=True, capture_output=True, text=True)
    return any(line.strip().endswith("\tdevice") for line in proc.stdout.splitlines()[1:])


def wait_for_device(poll_interval: float = 2.0) -> None:
    while not has_authorized_device():
        print("waiting for authorized ADB device...")
        time.sleep(poll_interval)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write AP3 GPS telemetry into incoming/<mission_id>/gps.csv for later pairing with noise.csv."
    )
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--incoming-dir", default=str(ROOT / "incoming"))
    parser.add_argument("--mavlink-url", default="", help="Direct MAVLink URL. If omitted, adb forward is used.")
    parser.add_argument("--local-port", type=int, default=15760)
    parser.add_argument("--remote-port", type=int, default=5760)
    parser.add_argument("--altitude", choices=["relative", "amsl"], default="relative")
    parser.add_argument("--flush-every", type=int, default=1)
    parser.add_argument("--max-messages", type=int, default=0)
    parser.add_argument("--utc-offset-hours", type=float, default=8.0)
    return parser.parse_args()


def resolve_mavlink_url(args: argparse.Namespace) -> str:
    if args.mavlink_url:
        return args.mavlink_url
    wait_for_device()
    run_adb_forward(args.local_port, args.remote_port)
    return f"tcp:127.0.0.1:{args.local_port}"


def ensure_csv(csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if not csv_path.exists():
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["time_stamp", "lat", "lon", "alt"])


def main() -> int:
    args = parse_args()
    mav_url = resolve_mavlink_url(args)
    bundle_dir = Path(args.incoming_dir) / args.mission_id
    csv_path = bundle_dir / "gps.csv"
    ensure_csv(csv_path)
    output_tz = timezone(timedelta(hours=args.utc_offset_hours))

    mav = mavutil.mavlink_connection(mav_url, source_system=255)
    print(f"writing GPS CSV to {csv_path}")
    print(f"reading AP3 MAVLink from {mav_url}")

    written = 0
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        while True:
            msg = mav.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=2)
            if msg is None:
                continue
            lat = msg.lat / 1e7
            lon = msg.lon / 1e7
            amsl_alt = msg.alt / 1000.0
            rel_alt = msg.relative_alt / 1000.0
            alt = rel_alt if args.altitude == "relative" else amsl_alt
            timestamp = datetime.now(output_tz).isoformat(timespec="milliseconds")
            writer.writerow([timestamp, lat, lon, alt])
            written += 1
            if written % max(1, args.flush_every) == 0:
                handle.flush()
            print(f"wrote #{written}: lat={lat:.7f} lon={lon:.7f} alt={alt:.2f}m")
            if args.max_messages and written >= args.max_messages:
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
