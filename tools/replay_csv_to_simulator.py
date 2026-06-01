import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gnuradio_to_simulator import send_measurement


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay GPS/noise CSV samples into the simulator measurement API."
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8888/api/usrp/measurement")
    parser.add_argument("--scene", default="NTPU")
    parser.add_argument("--gps-csv", default="backend/app/sample/gps.csv")
    parser.add_argument("--noise-csv", default="")
    parser.add_argument("--device-id", default="usrp-b210-sensor")
    parser.add_argument("--device-name", default="USRP B210 Sensor")
    parser.add_argument("--device-type", default="uav")
    parser.add_argument("--role", default="rx", choices=["rx", "tx", "jammer"])
    parser.add_argument("--center-freq-hz", type=float, default=2.45e9)
    parser.add_argument("--sample-rate-hz", type=float, default=1e6)
    parser.add_argument("--gain-db", type=float, default=20.0)
    parser.add_argument("--sample-count", type=int, default=200000)
    parser.add_argument("--accuracy", type=float, default=1.0)
    parser.add_argument("--devices-file", default="")
    parser.add_argument("--map-type", default="iss", choices=["sinr", "iss", "tss", "cfar"])
    parser.add_argument("--auto-simulate-last", action="store_true")
    parser.add_argument("--overlay-scene", action="store_true")
    parser.add_argument("--replay-delay", type=float, default=0.0)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def _parse_time(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _read_csv(path: str) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_devices(path_value: str) -> list[dict[str, Any]]:
    if not path_value:
        return []
    return json.loads(Path(path_value).read_text(encoding="utf-8"))


def load_gps_points(path: str) -> list[dict[str, Any]]:
    rows = _read_csv(path)
    points = []
    for row in rows:
        if not row.get("time_stamp"):
            continue
        points.append(
            {
                "time_stamp": _parse_time(row["time_stamp"]),
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "alt": float(row["alt"]),
            }
        )
    points.sort(key=lambda item: item["time_stamp"])
    return points


def load_noise_points(path: str) -> list[dict[str, Any]]:
    if not path:
        return []
    rows = _read_csv(path)
    points = []
    for row in rows:
        if not row.get("time_stamp"):
            continue
        points.append(
            {
                "time_stamp": _parse_time(row["time_stamp"]),
                "noise_floor_db": float(row["noise_floor_db"]),
            }
        )
    points.sort(key=lambda item: item["time_stamp"])
    return points


def align_noise_to_gps(
    gps_points: list[dict[str, Any]],
    noise_points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not noise_points:
        return [{**gps, "noise_floor_db": None} for gps in gps_points]

    aligned: list[dict[str, Any]] = []
    gps_index = 0
    for noise in noise_points:
        while gps_index + 1 < len(gps_points) and gps_points[gps_index + 1]["time_stamp"] <= noise["time_stamp"]:
            gps_index += 1
        if not gps_points or gps_points[gps_index]["time_stamp"] > noise["time_stamp"]:
            continue
        delta = (noise["time_stamp"] - gps_points[gps_index]["time_stamp"]).total_seconds()
        if delta >= 1.0:
            continue
        aligned.append({**gps_points[gps_index], "noise_floor_db": noise["noise_floor_db"]})
    return aligned if aligned else [{**gps, "noise_floor_db": None} for gps in gps_points]


def main() -> int:
    args = parse_args()
    gps_points = load_gps_points(args.gps_csv)
    noise_points = load_noise_points(args.noise_csv)
    replay_points = align_noise_to_gps(gps_points, noise_points)
    if args.limit > 0:
        replay_points = replay_points[:args.limit]
    devices = load_devices(args.devices_file)

    total = len(replay_points)
    for index, point in enumerate(replay_points, start=1):
        auto_simulate = bool(args.auto_simulate_last and index == total)
        payload = {
            "scene": args.scene,
            "device_id": args.device_id,
            "device_name": args.device_name,
            "device_type": args.device_type,
            "role": args.role,
            "lat": point["lat"],
            "lon": point["lon"],
            "alt": point["alt"],
            "accuracy": args.accuracy,
            "timestamp": point["time_stamp"].timestamp(),
            "center_freq_hz": args.center_freq_hz,
            "sample_rate_hz": args.sample_rate_hz,
            "gain_db": args.gain_db,
            "sample_count": args.sample_count,
            "capture_seconds": args.sample_count / args.sample_rate_hz,
            "mean_power_dbfs": point["noise_floor_db"],
            "peak_power_dbfs": point["noise_floor_db"],
            "derived_power_dbm": point["noise_floor_db"],
            "auto_simulate": auto_simulate,
            "map_type": args.map_type,
            "overlay_scene": args.overlay_scene,
            "devices": devices,
        }
        response = send_measurement(payload, api_url=args.api_url)
        print(json.dumps({"index": index, "total": total, "response": response}, ensure_ascii=False))
        if args.replay_delay > 0 and index < total:
            time.sleep(args.replay_delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
