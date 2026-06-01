import argparse
import csv
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import zmq


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Subscribe to a GNU Radio ZMQ pub_sink stream and append noise floor estimates to noise.csv."
    )
    parser.add_argument("--zmq-endpoint", default="tcp://127.0.0.1:49301")
    parser.add_argument("--noise-csv", required=True)
    parser.add_argument("--sample-interval", type=float, default=0.5, help="Seconds between CSV rows.")
    parser.add_argument("--recv-timeout-ms", type=int, default=1000)
    return parser.parse_args()


def ensure_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["time_stamp", "noise_floor_db"])


def complex64_power_db(payload: bytes) -> float | None:
    if not payload:
        return None
    samples = np.frombuffer(payload, dtype=np.complex64)
    if samples.size == 0:
        return None
    power = float(np.mean(np.abs(samples) ** 2))
    return 10.0 * math.log10(max(power, 1e-20))


def main() -> int:
    args = parse_args()
    noise_csv = Path(args.noise_csv).resolve()
    ensure_csv(noise_csv)

    ctx = zmq.Context()
    socket = ctx.socket(zmq.SUB)
    socket.setsockopt(zmq.SUBSCRIBE, b"")
    socket.setsockopt(zmq.RCVTIMEO, args.recv_timeout_ms)
    socket.connect(args.zmq_endpoint)

    print(f"[zmq-noise] connected to {args.zmq_endpoint}")
    print(f"[zmq-noise] writing {noise_csv}")

    last_emit = 0.0
    with noise_csv.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        while True:
            try:
                payload = socket.recv()
            except zmq.Again:
                continue

            now = time.time()
            if now - last_emit < args.sample_interval:
                continue

            noise_floor_db = complex64_power_db(payload)
            if noise_floor_db is None:
                continue

            timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            writer.writerow([timestamp, round(noise_floor_db, 2)])
            handle.flush()
            last_emit = now
            print(f"[zmq-noise] wrote noise_floor_db={noise_floor_db:.2f}")


if __name__ == "__main__":
    raise SystemExit(main())
