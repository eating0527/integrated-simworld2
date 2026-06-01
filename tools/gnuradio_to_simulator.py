import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload GNU Radio / USRP measurement results to the simulator backend."
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8888/api/usrp/measurement")
    parser.add_argument("--scene", default="")
    parser.add_argument("--device-id", default="usrp-b210-sensor")
    parser.add_argument("--device-name", default="USRP B210 Sensor")
    parser.add_argument("--device-type", default="uav")
    parser.add_argument("--role", default="rx", choices=["rx", "tx", "jammer"])
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lon", type=float, default=None)
    parser.add_argument("--alt", type=float, default=0.0)
    parser.add_argument("--accuracy", type=float, default=1.0)
    parser.add_argument("--x", type=float, default=None)
    parser.add_argument("--y", type=float, default=None)
    parser.add_argument("--z", type=float, default=None)
    parser.add_argument("--center-freq-hz", type=float, default=None)
    parser.add_argument("--sample-rate-hz", type=float, default=None)
    parser.add_argument("--gain-db", type=float, default=None)
    parser.add_argument("--bandwidth-hz", type=float, default=None)
    parser.add_argument("--channel", type=int, default=None)
    parser.add_argument("--sample-count", type=int, default=None)
    parser.add_argument("--capture-seconds", type=float, default=None)
    parser.add_argument("--mean-power-dbfs", type=float, default=None)
    parser.add_argument("--peak-power-dbfs", type=float, default=None)
    parser.add_argument("--rms-dbfs", type=float, default=None)
    parser.add_argument("--max-iq-abs", type=float, default=None)
    parser.add_argument("--derived-power-dbm", type=float, default=None)
    parser.add_argument("--auto-simulate", action="store_true")
    parser.add_argument("--map-type", default="iss", choices=["sinr", "iss", "tss", "cfar"])
    parser.add_argument("--cell-size", type=float, default=4.0)
    parser.add_argument("--samples-per-tx", type=int, default=100000000)
    parser.add_argument("--sinr-vmin", type=float, default=-20.0)
    parser.add_argument("--sinr-vmax", type=float, default=40.0)
    parser.add_argument("--overlay-scene", action="store_true")
    parser.add_argument(
        "--devices-file",
        default="",
        help="Optional JSON file containing the full simulation devices array.",
    )
    parser.add_argument(
        "--json-file",
        default="",
        help="Optional JSON file containing a complete request payload. CLI flags override file values.",
    )
    parser.add_argument(
        "--stdin-json",
        action="store_true",
        help="Read a complete request payload from stdin as JSON. CLI flags override stdin values.",
    )
    return parser.parse_args()


def load_devices(path_value: str) -> list[dict]:
    if not path_value:
        return []
    path = Path(path_value)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("devices-file JSON must be an array")
    return data


def _load_base_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.stdin_json:
        raw = sys.stdin.read().strip()
        if not raw:
            return {}
        data = json.loads(raw)
    elif args.json_file:
        data = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
    else:
        return {}
    if not isinstance(data, dict):
        raise ValueError("base payload must be a JSON object")
    return data


def _parser_defaults() -> dict[str, Any]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://127.0.0.1:8888/api/usrp/measurement")
    parser.add_argument("--scene", default="")
    parser.add_argument("--device-id", default="usrp-b210-sensor")
    parser.add_argument("--device-name", default="USRP B210 Sensor")
    parser.add_argument("--device-type", default="uav")
    parser.add_argument("--role", default="rx")
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lon", type=float, default=None)
    parser.add_argument("--alt", type=float, default=0.0)
    parser.add_argument("--accuracy", type=float, default=1.0)
    parser.add_argument("--x", type=float, default=None)
    parser.add_argument("--y", type=float, default=None)
    parser.add_argument("--z", type=float, default=None)
    parser.add_argument("--center-freq-hz", type=float, default=None)
    parser.add_argument("--sample-rate-hz", type=float, default=None)
    parser.add_argument("--gain-db", type=float, default=None)
    parser.add_argument("--bandwidth-hz", type=float, default=None)
    parser.add_argument("--channel", type=int, default=None)
    parser.add_argument("--sample-count", type=int, default=None)
    parser.add_argument("--capture-seconds", type=float, default=None)
    parser.add_argument("--mean-power-dbfs", type=float, default=None)
    parser.add_argument("--peak-power-dbfs", type=float, default=None)
    parser.add_argument("--rms-dbfs", type=float, default=None)
    parser.add_argument("--max-iq-abs", type=float, default=None)
    parser.add_argument("--derived-power-dbm", type=float, default=None)
    parser.add_argument("--auto-simulate", action="store_true")
    parser.add_argument("--map-type", default="iss")
    parser.add_argument("--cell-size", type=float, default=4.0)
    parser.add_argument("--samples-per-tx", type=int, default=100000000)
    parser.add_argument("--sinr-vmin", type=float, default=-20.0)
    parser.add_argument("--sinr-vmax", type=float, default=40.0)
    parser.add_argument("--overlay-scene", action="store_true")
    parser.add_argument("--devices-file", default="")
    parser.add_argument("--json-file", default="")
    parser.add_argument("--stdin-json", action="store_true")
    return vars(parser.parse_args([]))


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload = _load_base_payload(args)
    defaults = _parser_defaults()
    cli_values = {
        "scene": args.scene or None,
        "device_id": args.device_id,
        "device_name": args.device_name,
        "device_type": args.device_type,
        "role": args.role,
        "lat": args.lat,
        "lon": args.lon,
        "alt": args.alt,
        "accuracy": args.accuracy,
        "x": args.x,
        "y": args.y,
        "z": args.z,
        "center_freq_hz": args.center_freq_hz,
        "sample_rate_hz": args.sample_rate_hz,
        "gain_db": args.gain_db,
        "bandwidth_hz": args.bandwidth_hz,
        "channel": args.channel,
        "sample_count": args.sample_count,
        "capture_seconds": args.capture_seconds,
        "mean_power_dbfs": args.mean_power_dbfs,
        "peak_power_dbfs": args.peak_power_dbfs,
        "rms_dbfs": args.rms_dbfs,
        "max_iq_abs": args.max_iq_abs,
        "derived_power_dbm": args.derived_power_dbm,
        "auto_simulate": args.auto_simulate,
        "map_type": args.map_type,
        "cell_size": args.cell_size,
        "samples_per_tx": args.samples_per_tx,
        "sinr_vmin": args.sinr_vmin,
        "sinr_vmax": args.sinr_vmax,
        "overlay_scene": args.overlay_scene,
    }
    default_key_map = {
        "scene": "scene",
        "device_id": "device_id",
        "device_name": "device_name",
        "device_type": "device_type",
        "role": "role",
        "lat": "lat",
        "lon": "lon",
        "alt": "alt",
        "accuracy": "accuracy",
        "x": "x",
        "y": "y",
        "z": "z",
        "center_freq_hz": "center_freq_hz",
        "sample_rate_hz": "sample_rate_hz",
        "gain_db": "gain_db",
        "bandwidth_hz": "bandwidth_hz",
        "channel": "channel",
        "sample_count": "sample_count",
        "capture_seconds": "capture_seconds",
        "mean_power_dbfs": "mean_power_dbfs",
        "peak_power_dbfs": "peak_power_dbfs",
        "rms_dbfs": "rms_dbfs",
        "max_iq_abs": "max_iq_abs",
        "derived_power_dbm": "derived_power_dbm",
        "auto_simulate": "auto_simulate",
        "map_type": "map_type",
        "cell_size": "cell_size",
        "samples_per_tx": "samples_per_tx",
        "sinr_vmin": "sinr_vmin",
        "sinr_vmax": "sinr_vmax",
        "overlay_scene": "overlay_scene",
    }
    for key, value in cli_values.items():
        default_value = defaults[default_key_map[key]]
        if value != default_value or key not in payload:
            payload[key] = value
    if args.devices_file:
        payload["devices"] = load_devices(args.devices_file)
    elif "devices" not in payload:
        payload["devices"] = []
    return payload


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset))


def send_measurement(payload: dict[str, Any], api_url: str = "http://127.0.0.1:8888/api/usrp/measurement") -> dict[str, Any]:
    return post_json(api_url, payload)


def main() -> int:
    args = parse_args()
    payload = build_payload(args)
    try:
        response = post_json(args.api_url, payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        print(body or f"HTTP {exc.code}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
