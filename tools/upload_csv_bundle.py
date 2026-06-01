import argparse
import json
import sys
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload a gps.csv / noise.csv bundle to the laptop backend over HTTP."
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8888/api/usrp/upload-csv-bundle")
    parser.add_argument("--scene", default="NTPU")
    parser.add_argument("--mission-id", default="")
    parser.add_argument("--gps-csv", required=True)
    parser.add_argument("--noise-csv", default="")
    parser.add_argument("--map-type", default="iss", choices=["sinr", "iss", "tss", "cfar"])
    parser.add_argument("--auto-simulate-last", action="store_true")
    parser.add_argument("--device-id", default="usrp-b210-sensor")
    parser.add_argument("--device-name", default="USRP B210 Sensor")
    parser.add_argument("--device-type", default="uav")
    parser.add_argument("--role", default="rx", choices=["rx", "tx", "jammer"])
    parser.add_argument("--devices-file", default="")
    return parser.parse_args()


def load_devices_json(path_value: str) -> str:
    if not path_value:
        return ""
    return Path(path_value).read_text(encoding="utf-8")


def build_multipart(fields: dict[str, str], files: list[tuple[str, Path]]) -> tuple[bytes, str]:
    boundary = f"----CodexBoundary{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    for field_name, path in files:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{field_name}"; filename="{path.name}"\r\n'
                    "Content-Type: text/csv\r\n\r\n"
                ).encode(),
                path.read_bytes(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def post_bundle(url: str, fields: dict[str, str], files: list[tuple[str, Path]]) -> dict:
    body, content_type = build_multipart(fields, files)
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset))


def main() -> int:
    args = parse_args()
    gps_path = Path(args.gps_csv)
    if not gps_path.exists():
        print(f"gps csv not found: {gps_path}", file=sys.stderr)
        return 1
    noise_path = Path(args.noise_csv) if args.noise_csv else None
    if noise_path is not None and not noise_path.exists():
        print(f"noise csv not found: {noise_path}", file=sys.stderr)
        return 1

    fields = {
        "scene": args.scene,
        "mission_id": args.mission_id,
        "map_type": args.map_type,
        "auto_simulate_last": "true" if args.auto_simulate_last else "false",
        "device_id": args.device_id,
        "device_name": args.device_name,
        "device_type": args.device_type,
        "role": args.role,
        "devices_json": load_devices_json(args.devices_file),
    }
    files = [("gps_file", gps_path)]
    if noise_path is not None:
        files.append(("noise_file", noise_path))

    try:
        response = post_bundle(args.api_url, fields, files)
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
