import argparse
import csv
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta, timezone


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.gps_csv import ensure_gps_csv, open_gps_csv_for_append


ADB = ROOT / "tools" / "platform-tools" / "adb.exe"
if not ADB.exists():
    ADB = ROOT / "tools" / "scrcpy" / "scrcpy-win64-v3.3.4" / "adb.exe"


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


def check_device(local_port: int, remote_port: int) -> bool:
    if not has_authorized_device():
        return False
    run_adb_forward(local_port, remote_port)
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write AP3 GPS telemetry into incoming/<mission_id>/gps.csv for later pairing with noise.csv."
    )
    parser.add_argument("--mission-id", default="")
    parser.add_argument("--check", action="store_true", help="Check AP3 USB/ADB readiness and exit.")
    parser.add_argument("--incoming-dir", default=str(ROOT / "incoming"))
    parser.add_argument("--mavlink-url", default="", help="Direct MAVLink URL. If omitted, adb forward is used.")
    parser.add_argument("--local-port", type=int, default=15760)
    parser.add_argument("--remote-port", type=int, default=5760)
    parser.add_argument("--altitude", choices=["relative", "amsl"], default="relative")
    parser.add_argument("--flush-every", type=int, default=1)
    parser.add_argument("--max-messages", type=int, default=0)
    parser.add_argument("--utc-offset-hours", type=float, default=8.0)
    parser.add_argument("--sync-api-url", default="", help="Optional B laptop endpoint, e.g. http://192.168.1.20:8888/api/usrp/sync-gps-point.")
    parser.add_argument("--sync-device-id", default="align-m4p-top-aircraft")
    parser.add_argument("--sync-device-name", default="M4P TOP Aircraft")
    parser.add_argument("--sync-device-type", default="uav")
    parser.add_argument("--sync-timeout", type=float, default=2.0)
    parser.add_argument("--sync-log-every", type=float, default=5.0)
    return parser.parse_args()


def resolve_mavlink_url(args: argparse.Namespace) -> str:
    if args.mavlink_url:
        return args.mavlink_url
    wait_for_device()
    run_adb_forward(args.local_port, args.remote_port)
    return f"tcp:127.0.0.1:{args.local_port}"


def ensure_csv(csv_path: Path) -> None:
    ensure_gps_csv(csv_path)


def format_csv_timestamp(timestamp: datetime) -> str:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("CSV timestamp must be timezone-aware")
    return timestamp.isoformat(timespec="microseconds")


class GpsSyncClient:
    def __init__(
        self,
        *,
        api_url: str,
        mission_id: str,
        device_id: str,
        device_name: str,
        device_type: str,
        timeout: float,
        log_every: float,
    ):
        self.api_url = api_url.strip()
        self.mission_id = mission_id
        self.device_id = device_id
        self.device_name = device_name
        self.device_type = device_type
        self.timeout = timeout
        self.log_every = max(1.0, log_every)
        self._last_error_log = 0.0
        self._sent = 0
        self._failed = 0

    def send(self, *, timestamp: str, lat: float, lon: float, alt: float, alt_mode: str) -> None:
        if not self.api_url:
            return
        payload = {
            "mission_id": self.mission_id,
            "time_stamp": timestamp,
            "lat": lat,
            "lon": lon,
            "alt": alt,
            "alt_mode": alt_mode,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "device_type": self.device_type,
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.api_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "integrated-simworld-gps-sync/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                if response.status >= 400:
                    raise RuntimeError(f"HTTP {response.status}")
            self._sent += 1
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
            self._failed += 1
            now = time.monotonic()
            if now - self._last_error_log >= self.log_every:
                self._last_error_log = now
                print(
                    f"gps sync warning: failed={self._failed} sent={self._sent} error={exc}",
                    flush=True,
                )


def main() -> int:
    args = parse_args()
    if args.check:
        return 0 if check_device(args.local_port, args.remote_port) else 1
    if not args.mission_id:
        raise SystemExit("--mission-id is required unless --check is used")

    from pymavlink import mavutil

    bundle_dir = Path(args.incoming_dir) / args.mission_id
    csv_path = bundle_dir / "gps.csv"
    mav_url = resolve_mavlink_url(args)
    output_tz = timezone(timedelta(hours=args.utc_offset_hours))
    sync_client = GpsSyncClient(
        api_url=args.sync_api_url,
        mission_id=args.mission_id,
        device_id=args.sync_device_id,
        device_name=args.sync_device_name,
        device_type=args.sync_device_type,
        timeout=args.sync_timeout,
        log_every=args.sync_log_every,
    )

    print(f"writing GPS CSV to {csv_path}")
    print(f"reading AP3 MAVLink from {mav_url}")
    if args.sync_api_url:
        print(f"syncing GPS points to {args.sync_api_url}")

    written = 0
    with open_gps_csv_for_append(csv_path) as handle:
        writer = csv.writer(handle)
        while True:
            mav = mavutil.mavlink_connection(mav_url, source_system=255)
            try:
                while True:
                    try:
                        msg = mav.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=2)
                    except TypeError as exc:
                        print(f"mavlink parse error, reconnecting: {exc}")
                        break
                    if msg is None:
                        continue
                    lat = msg.lat / 1e7
                    lon = msg.lon / 1e7
                    amsl_alt = msg.alt / 1000.0
                    rel_alt = msg.relative_alt / 1000.0
                    alt = rel_alt if args.altitude == "relative" else amsl_alt
                    timestamp = format_csv_timestamp(datetime.now(output_tz))
                    writer.writerow([timestamp, lat, lon, alt, args.altitude])
                    sync_client.send(
                        timestamp=timestamp,
                        lat=lat,
                        lon=lon,
                        alt=alt,
                        alt_mode=args.altitude,
                    )
                    written += 1
                    if written % max(1, args.flush_every) == 0:
                        handle.flush()
                    print(f"wrote #{written}: lat={lat:.7f} lon={lon:.7f} alt={alt:.2f}m")
                    if args.max_messages and written >= args.max_messages:
                        return 0
            finally:
                mav.close()
            time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
