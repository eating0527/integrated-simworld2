import argparse
import hashlib
import json
import sys
import uuid
import urllib.error
import urllib.request
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload noise.csv only to the laptop backend. The laptop will pair it with gps.csv by mission_id."
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8888/api/usrp/upload-noise-csv")
    parser.add_argument("--scene", default="NTPU")
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--noise-csv", required=True)
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


def file_metadata(path: Path) -> dict[str, str]:
    data = path.read_bytes()
    return {
        "noise_size": str(len(data)),
        "noise_sha256": hashlib.sha256(data).hexdigest(),
    }


def build_multipart(fields: dict[str, str], file_field_name: str, file_path: Path) -> tuple[bytes, str]:
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
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{file_field_name}"; filename="{file_path.name}"\r\n'
                "Content-Type: text/csv\r\n\r\n"
            ).encode(),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def post_noise(url: str, fields: dict[str, str], noise_csv_path: Path) -> dict:
    body, content_type = build_multipart(fields, "noise_file", noise_csv_path)
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
    noise_path = Path(args.noise_csv)
    if not noise_path.exists():
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
        **file_metadata(noise_path),
    }
    try:
        response = post_noise(args.api_url, fields, noise_path)
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
