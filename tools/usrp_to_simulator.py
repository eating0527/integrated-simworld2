import argparse
import asyncio
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

try:
    import websockets
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Missing dependency 'websockets'. Install backend requirements first: "
        "pip install -r backend/requirements.txt"
    ) from exc


def find_rx_tool(explicit_path: str | None) -> str:
    if explicit_path:
        path = Path(explicit_path)
        if path.exists():
            return str(path)
        raise FileNotFoundError(f"rx_samples_to_file not found: {path}")

    env_path = os.environ.get("UHD_RX_SAMPLES_TO_FILE")
    if env_path and Path(env_path).exists():
        return env_path

    for candidate in [
        shutil.which("rx_samples_to_file"),
        shutil.which("rx_samples_to_file.exe"),
        r"C:\Program Files\UHD\lib\uhd\examples\rx_samples_to_file.exe",
    ]:
        if candidate and Path(candidate).exists():
            return candidate

    raise FileNotFoundError(
        "Could not find rx_samples_to_file. Set --rx-tool or UHD_RX_SAMPLES_TO_FILE."
    )


def db10(value: float) -> float:
    return 10.0 * math.log10(max(value, 1e-12))


def find_uhd_bin_dir(rx_tool: str) -> str | None:
    tool_path = Path(rx_tool).resolve()
    for parent in [tool_path.parent, *tool_path.parents]:
        candidate = parent / "bin"
        if (candidate / "uhd.dll").exists():
            return str(candidate)
    return None


def capture_samples(rx_tool: str, args: argparse.Namespace) -> dict:
    with tempfile.NamedTemporaryFile(prefix="usrp_capture_", suffix=".dat", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        cmd = [
            rx_tool,
            "--args",
            args.usrp_args,
            "--file",
            str(tmp_path),
            "--type",
            "short",
            "--wirefmt",
            "sc16",
            "--nsamps",
            str(args.nsamps),
            "--rate",
            str(args.sample_rate),
            "--freq",
            str(args.center_freq),
            "--gain",
            str(args.gain),
            "--channels",
            str(args.channel),
            "--skip-lo",
        ]
        if args.bandwidth:
            cmd.extend(["--bw", str(args.bandwidth)])
        if args.antenna:
            cmd.extend(["--ant", args.antenna])
        if args.subdev:
            cmd.extend(["--subdev", args.subdev])

        env = os.environ.copy()
        uhd_bin = find_uhd_bin_dir(rx_tool)
        if uhd_bin:
            env["PATH"] = f"{uhd_bin}{os.pathsep}{env.get('PATH', '')}"

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(15, int(args.capture_timeout)),
            env=env,
            check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"rx_samples_to_file failed (exit={proc.returncode}): {detail}")

        raw = np.fromfile(tmp_path, dtype=np.int16)
        if raw.size < 2:
            raise RuntimeError("No IQ samples captured.")
        if raw.size % 2:
            raw = raw[:-1]

        iq = raw.reshape(-1, 2).astype(np.float32)
        i = iq[:, 0]
        q = iq[:, 1]
        power_linear = (i * i + q * q) / float(32767 ** 2)

        sample_count = int(power_linear.size)
        mean_power = float(power_linear.mean())
        peak_power = float(power_linear.max())
        rms = float(np.sqrt(mean_power))

        return {
            "sample_count": sample_count,
            "capture_seconds": sample_count / float(args.sample_rate),
            "mean_power_dbfs": db10(mean_power),
            "peak_power_dbfs": db10(peak_power),
            "rms_dbfs": 20.0 * math.log10(max(rms, 1e-12)),
            "max_iq_abs": float(np.sqrt(max(peak_power, 0.0))),
        }
    finally:
        tmp_path.unlink(missing_ok=True)


async def drain_incoming(ws) -> None:
    try:
        async for _ in ws:
            pass
    except Exception:
        pass


async def bridge(args: argparse.Namespace) -> None:
    rx_tool = find_rx_tool(args.rx_tool)
    sent = 0

    while True:
        try:
            async with websockets.connect(args.websocket_url) as ws:
                drain_task = asyncio.create_task(drain_incoming(ws))
                await ws.send(
                    json.dumps(
                        {
                            "type": "register-device",
                            "deviceId": args.device_id,
                            "deviceName": args.device_name,
                            "deviceType": args.device_type,
                        }
                    )
                )
                print(f"registered {args.device_name} -> {args.websocket_url}")
                print(f"capturing with {rx_tool}")

                while True:
                    started_at = time.time()
                    metrics = await asyncio.to_thread(capture_samples, rx_tool, args)
                    timestamp = time.time()

                    if args.lat is not None and args.lon is not None:
                        await ws.send(
                            json.dumps(
                                {
                                    "lat": args.lat,
                                    "lon": args.lon,
                                    "alt": args.alt,
                                    "accuracy": args.accuracy,
                                    "deviceId": args.device_id,
                                    "deviceName": args.device_name,
                                    "deviceType": args.device_type,
                                    "timestamp": timestamp,
                                }
                            )
                        )

                    summary = {
                        "type": "usrp-spectrum",
                        "deviceId": args.device_id,
                        "deviceName": args.device_name,
                        "deviceType": args.device_type,
                        "timestamp": timestamp,
                        "lat": args.lat,
                        "lon": args.lon,
                        "alt": args.alt,
                        "accuracy": args.accuracy,
                        "center_freq_hz": args.center_freq,
                        "sample_rate_hz": args.sample_rate,
                        "gain_db": args.gain,
                        "bandwidth_hz": args.bandwidth,
                        "channel": args.channel,
                        **metrics,
                    }
                    await ws.send(json.dumps(summary))
                    sent += 1

                    print(
                        f"sent #{sent}: mean={metrics['mean_power_dbfs']:.2f} dBFS "
                        f"peak={metrics['peak_power_dbfs']:.2f} dBFS "
                        f"samples={metrics['sample_count']}"
                    )

                    if args.max_messages and sent >= args.max_messages:
                        drain_task.cancel()
                        return

                    elapsed = time.time() - started_at
                    sleep_for = max(0.0, args.interval - elapsed)
                    if sleep_for:
                        await asyncio.sleep(sleep_for)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"bridge disconnected: {exc}")
            await asyncio.sleep(2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture short USRP B210 snapshots and forward RF summary metrics to the simulator WebSocket."
    )
    parser.add_argument("--websocket-url", default="ws://127.0.0.1:8888/ws/gps")
    parser.add_argument("--device-id", default="usrp-b210-sensor")
    parser.add_argument("--device-name", default="USRP B210 Sensor")
    parser.add_argument("--device-type", default="uav")
    parser.add_argument("--usrp-args", default="type=b200")
    parser.add_argument("--rx-tool", default="")
    parser.add_argument("--center-freq", type=float, default=2.45e9)
    parser.add_argument("--sample-rate", type=float, default=1e6)
    parser.add_argument("--gain", type=float, default=20.0)
    parser.add_argument("--bandwidth", type=float, default=0.0)
    parser.add_argument("--channel", type=int, default=0)
    parser.add_argument("--antenna", default="")
    parser.add_argument("--subdev", default="")
    parser.add_argument("--nsamps", type=int, default=200000)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--capture-timeout", type=float, default=20.0)
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lon", type=float, default=None)
    parser.add_argument("--alt", type=float, default=0.0)
    parser.add_argument("--accuracy", type=float, default=1.0)
    parser.add_argument("--max-messages", type=int, default=0)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(bridge(parse_args()))
