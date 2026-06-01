import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Watch an incoming directory for gps.csv / noise.csv bundles and replay them automatically."
    )
    parser.add_argument("--watch-dir", default="incoming")
    parser.add_argument("--python-exe", default=sys.executable)
    parser.add_argument("--replay-script", default="tools/replay_csv_to_simulator.py")
    parser.add_argument("--scene", default="NTPU")
    parser.add_argument("--devices-file", default="")
    parser.add_argument("--map-type", default="iss", choices=["sinr", "iss", "tss", "cfar"])
    parser.add_argument("--api-url", default="http://127.0.0.1:8888/api/usrp/measurement")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--stable-seconds", type=float, default=3.0)
    parser.add_argument("--auto-simulate-last", action="store_true")
    return parser.parse_args()


def _marker_path(bundle_dir: Path) -> Path:
    return bundle_dir / ".replayed"


def _error_marker_path(bundle_dir: Path) -> Path:
    return bundle_dir / ".replay_failed"


def _stable_enough(path: Path, stable_seconds: float) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age >= stable_seconds


def _iter_bundles(watch_dir: Path):
    if not watch_dir.exists():
        return []
    bundles: list[Path] = []
    for child in watch_dir.iterdir():
        if child.is_dir():
            bundles.append(child)
    return sorted(bundles)


def _build_command(args: argparse.Namespace, bundle_dir: Path) -> list[str]:
    bundle_meta_path = bundle_dir / "bundle.json"
    scene = args.scene
    devices_file = args.devices_file
    map_type = args.map_type
    auto_simulate_last = args.auto_simulate_last
    if bundle_meta_path.exists():
        try:
            meta = json.loads(bundle_meta_path.read_text(encoding="utf-8"))
            scene = meta.get("scene") or scene
            map_type = meta.get("map_type") or map_type
            auto_simulate_last = bool(meta.get("auto_simulate_last", auto_simulate_last))
            if isinstance(meta.get("devices"), list):
                embedded_devices_path = bundle_dir / "_devices.json"
                embedded_devices_path.write_text(
                    json.dumps(meta["devices"], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                devices_file = str(embedded_devices_path)
        except Exception:
            pass
    gps_csv = bundle_dir / "gps.csv"
    noise_csv = bundle_dir / "noise.csv"
    cmd = [
        args.python_exe,
        args.replay_script,
        "--api-url",
        args.api_url,
        "--scene",
        scene,
        "--gps-csv",
        str(gps_csv),
    ]
    if noise_csv.exists():
        cmd.extend(["--noise-csv", str(noise_csv)])
    if devices_file:
        cmd.extend(["--devices-file", devices_file])
    if auto_simulate_last:
        cmd.append("--auto-simulate-last")
        cmd.extend(["--map-type", map_type])
    return cmd


def _write_marker(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def process_bundle(args: argparse.Namespace, bundle_dir: Path) -> bool:
    gps_csv = bundle_dir / "gps.csv"
    noise_csv = bundle_dir / "noise.csv"
    if not gps_csv.exists() or not noise_csv.exists():
        return False
    if _marker_path(bundle_dir).exists():
        return False
    if not _stable_enough(noise_csv, args.stable_seconds):
        return False

    cmd = _build_command(args, bundle_dir)
    started_at = time.time()
    proc = subprocess.run(
        cmd,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    marker_payload = {
        "command": cmd,
        "returncode": proc.returncode,
        "started_at": started_at,
        "finished_at": time.time(),
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }
    if proc.returncode == 0:
        _write_marker(_marker_path(bundle_dir), marker_payload)
        if _error_marker_path(bundle_dir).exists():
            _error_marker_path(bundle_dir).unlink()
        print(f"[csv-watch] replayed {bundle_dir}")
        return True

    _write_marker(_error_marker_path(bundle_dir), marker_payload)
    print(f"[csv-watch] replay failed {bundle_dir}: exit={proc.returncode}", file=sys.stderr)
    return False


def main() -> int:
    args = parse_args()
    watch_dir = Path(args.watch_dir).resolve()
    watch_dir.mkdir(parents=True, exist_ok=True)
    print(f"[csv-watch] watching {watch_dir}")
    while True:
        for bundle_dir in _iter_bundles(watch_dir):
            process_bundle(args, bundle_dir)
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
