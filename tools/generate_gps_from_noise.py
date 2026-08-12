import argparse
import csv
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.gps_csv import GPS_CSV_COLUMNS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a gps.csv aligned to noise.csv timestamps using a fixed lat/lon/alt."
    )
    parser.add_argument("--noise-csv", required=True, help="Input noise.csv path")
    parser.add_argument("--gps-csv", required=True, help="Output gps.csv path")
    parser.add_argument("--lat", type=float, required=True, help="Fixed latitude for all rows")
    parser.add_argument("--lon", type=float, required=True, help="Fixed longitude for all rows")
    parser.add_argument("--alt", type=float, default=30.0, help="Fixed altitude for all rows")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    noise_path = Path(args.noise_csv)
    gps_path = Path(args.gps_csv)

    if not noise_path.exists():
        raise SystemExit(f"noise csv not found: {noise_path}")

    with noise_path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    if not rows:
        raise SystemExit("noise csv has no rows")
    if "time_stamp" not in (rows[0].keys() if rows else []):
        raise SystemExit("noise csv missing required column: time_stamp")

    gps_path.parent.mkdir(parents=True, exist_ok=True)
    with gps_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(GPS_CSV_COLUMNS)
        for row in rows:
            timestamp = row.get("time_stamp")
            if not timestamp:
                continue
            writer.writerow([timestamp, args.lat, args.lon, args.alt, "relative"])

    print(f"generated {gps_path} with {len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
