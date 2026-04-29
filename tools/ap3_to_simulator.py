import argparse
import asyncio
import json
import subprocess
import time
from pathlib import Path

import websockets
from pymavlink import mavutil


ROOT = Path(__file__).resolve().parents[1]
ADB = ROOT / "tools" / "platform-tools" / "adb.exe"


def run_adb_forward(local_port: int, remote_port: int) -> None:
    if not ADB.exists():
        raise FileNotFoundError(f"adb not found: {ADB}")

    subprocess.run(
        [str(ADB), "forward", f"tcp:{local_port}", f"tcp:{remote_port}"],
        check=True,
    )


def gps_payload(msg, altitude_mode: str, device_id: str, device_name: str) -> dict:
    lat = msg.lat / 1e7
    lon = msg.lon / 1e7
    amsl_alt = msg.alt / 1000.0
    rel_alt = msg.relative_alt / 1000.0
    alt = rel_alt if altitude_mode == "relative" else amsl_alt

    return {
        "lat": lat,
        "lon": lon,
        "alt": alt,
        "accuracy": 1.0,
        "deviceId": device_id,
        "deviceName": device_name,
        "deviceType": "uav",
        "timestamp": time.time(),
    }


async def bridge(args: argparse.Namespace) -> None:
    if args.mavlink_url:
        mav_url = args.mavlink_url
    else:
        run_adb_forward(args.local_port, args.remote_port)
        mav_url = f"tcp:127.0.0.1:{args.local_port}"

    mav = mavutil.mavlink_connection(mav_url, source_system=255)

    sent = 0
    async with websockets.connect(args.websocket_url) as ws:
        drain_task = asyncio.create_task(drain_incoming(ws))
        await ws.send(
            json.dumps(
                {
                    "type": "register-device",
                    "deviceId": args.device_id,
                    "deviceName": args.device_name,
                    "deviceType": "uav",
                }
            )
        )
        print(f"registered {args.device_name} -> {args.websocket_url}")
        print(f"reading AP3 MAVLink from {mav_url}")

        while True:
            msg = await asyncio.to_thread(
                mav.recv_match,
                type="GLOBAL_POSITION_INT",
                blocking=True,
                timeout=2,
            )
            if msg is None:
                continue

            payload = gps_payload(msg, args.altitude, args.device_id, args.device_name)
            await ws.send(json.dumps(payload))
            sent += 1

            print(
                f"sent #{sent}: lat={payload['lat']:.7f} "
                f"lon={payload['lon']:.7f} alt={payload['alt']:.2f}m"
            )

            if args.max_messages and sent >= args.max_messages:
                drain_task.cancel()
                return


async def drain_incoming(ws) -> None:
    """Keep the server-to-client queue drained; this bridge only needs to send."""
    try:
        async for _ in ws:
            pass
    except Exception:
        pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Forward ALIGN AP3 MAVLink GPS telemetry to the simulator WebSocket."
    )
    parser.add_argument(
        "--websocket-url",
        default="wss://backend.simworld.website/ws/gps",
        help="Simulator GPS WebSocket URL.",
    )
    parser.add_argument("--device-id", default="align-m4p-top-aircraft")
    parser.add_argument("--device-name", default="M4P TOP Aircraft")
    parser.add_argument("--local-port", type=int, default=15760)
    parser.add_argument("--remote-port", type=int, default=5760)
    parser.add_argument(
        "--mavlink-url",
        default="",
        help="Direct MAVLink URL, e.g. tcp:192.168.50.137:5760. If omitted, adb forward is used.",
    )
    parser.add_argument(
        "--altitude",
        choices=["relative", "amsl"],
        default="relative",
        help="relative uses takeoff/home-relative altitude; amsl uses GPS altitude above mean sea level.",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=0,
        help="Stop after this many GPS updates. 0 means run until Ctrl+C.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(bridge(parse_args()))
