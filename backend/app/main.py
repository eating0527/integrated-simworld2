import asyncio
import csv
import hashlib
import logging
import math
import os
import re
import json
import secrets
import time
import uuid
import shutil
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
import numpy as np

# Auto-set DRJIT_LIBLLVM_PATH before any drjit/mitsuba/sionna import
if os.name == "nt" and not os.environ.get("DRJIT_LIBLLVM_PATH"):
    for _dll in [
        r"C:\Program Files\LLVM\bin\LLVM-C.dll",
        r"C:\Program Files (x86)\LLVM\bin\LLVM-C.dll",
    ]:
        if os.path.isfile(_dll):
            os.environ["DRJIT_LIBLLVM_PATH"] = _dll
            break

from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List, Any, Literal

from fastapi import FastAPI, BackgroundTasks, UploadFile, File, WebSocket, WebSocketDisconnect, Form, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from app.capture_jobs import (
    CaptureConflictError,
    CaptureCoordinator,
    CapturePreflightError,
    CaptureNotFoundError,
    CaptureStore,
    CaptureUnavailableError,
)
from app.coordinate_frame import SceneFrame, enu_to_sionna, scene_frame_from_metadata
from app.gps_csv import GpsCsvSchemaError, append_gps_row, validate_gps_csv_bytes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 資料夾設定
# ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
REPO_ROOT = BASE_DIR.parent.parent
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None
if load_dotenv is not None:
    load_dotenv(REPO_ROOT / ".env")
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
INCOMING_CSV_DIR = REPO_ROOT / "incoming"
INCOMING_CSV_DIR.mkdir(parents=True, exist_ok=True)
capture_coordinator = CaptureCoordinator(
    CaptureStore(INCOMING_CSV_DIR),
    repo_root=REPO_ROOT,
)
GPS_SYNC_LOCK = threading.Lock()
PHOTOS_JSON = UPLOAD_DIR / "photos.json"
LOCATION_JSON = UPLOAD_DIR / "selected_locations.json"
SCENE_TASKS_JSON = UPLOAD_DIR / "scene_tasks.json"
SCENE_INDEX_JSON = UPLOAD_DIR / "scene_index.json"
TRAJECTORY_EVENTS_DIR = UPLOAD_DIR / "trajectory_events"
TRAJECTORY_EVENTS_DIR.mkdir(parents=True, exist_ok=True)
SCENE_DIR = BASE_DIR / "static" / "scenes"
GENERATED_SCENES_DIR = SCENE_DIR / "generated"
GENERATED_SCENES_DIR.mkdir(parents=True, exist_ok=True)
SCENE_TASKS_LOCK = threading.Lock()
GENERATED_SCENE_AREA_M = 512.0
BASEMAP_GENERATION_ZOOM = 18
FIXED_GENERATION_ZOOM = BASEMAP_GENERATION_ZOOM
DETAIL_BBOX_SPAN_TILES = 2.6
BUILDING_CHECK_TOTAL_TIMEOUT_SECONDS = 14.0
BUILDING_CHECK_REQUEST_TIMEOUT_SECONDS = 5.0
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
# ──────────────────────────────────────────────
# FastAPI App
# ──────────────────────────────────────────────
app = FastAPI(title="GPS Tracker API", version="1.0.0")

# CORS — 允許所有來源（也可以只填你的 cloudflare 域名）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 靜態檔案：讓前端可以直接讀取已上傳的照片
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# 靜態檔案：Sionna 模擬產生的圖片
SIMULATION_OUT_DIR = BASE_DIR / "static" / "maps"
SIMULATION_OUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/simulations", StaticFiles(directory=str(SIMULATION_OUT_DIR)), name="simulations")

# 靜態檔案：動態生成場景（Blender/blosm）
app.mount("/generated-scenes", StaticFiles(directory=str(SCENE_DIR)), name="generated-scenes")

ADB_EXE = REPO_ROOT / "tools" / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
if os.name == "nt" and not ADB_EXE.exists():
    ADB_EXE = REPO_ROOT / "tools" / "scrcpy" / "scrcpy-win64-v3.3.4" / "adb.exe"
DEFAULT_CONTROLLER_SERIAL = os.environ.get("ALIGN_CONTROLLER_SERIAL", "58e9dd83")
ADB_HOME_DIR = UPLOAD_DIR / "adb-home"
ADB_HOME_DIR.mkdir(parents=True, exist_ok=True)
FFMPEG_EXE = shutil.which("ffmpeg") or "ffmpeg"


# ──────────────────────────────────────────────
# GPS WebSocket 連線管理器
# ──────────────────────────────────────────────
class GPSConnectionManager:
    def __init__(self):
        # { deviceId: WebSocket }
        self.connections: Dict[str, WebSocket] = {}
        # { deviceId: { lat, lon, alt, accuracy, deviceName, ... } }
        self.gps_data: Dict[str, dict] = {}
        # { deviceId: deviceName }
        self.names: Dict[str, str] = {}
        # { deviceId: [{ lat, lon, alt, accuracy, timestamp, ... }] }
        self.trajectories: Dict[str, List[Dict[str, Any]]] = {}
        self.trajectory_started_at = datetime.now().isoformat()

    async def connect(self, ws: WebSocket):
        await ws.accept()

    def register(self, device_id: str, ws: WebSocket, name: str = "Unknown"):
        self.connections[device_id] = ws
        self.names[device_id] = name
        logger.info(f"✅ 裝置已註冊: {device_id[:12]} ({name})  連線數: {len(self.connections)}")

    def disconnect(self, device_id: str):
        self.connections.pop(device_id, None)
        self.gps_data.pop(device_id, None)
        self.names.pop(device_id, None)
        logger.info(f"📡 裝置斷線: {device_id[:12]}  連線數: {len(self.connections)}")

    def update_gps(self, device_id: str, data: dict):
        self.gps_data[device_id] = data
        self.record_trajectory_point(device_id, data)

    def record_trajectory_point(self, device_id: str, data: dict):
        try:
            lat = float(data["lat"])
            lon = float(data["lon"])
            alt = float(data.get("alt", 0))
        except (KeyError, TypeError, ValueError):
            return

        points = self.trajectories.setdefault(device_id, [])
        if points:
            last = points[-1]
            if (
                abs(float(last.get("lat", 0)) - lat) <= 0.000001
                and abs(float(last.get("lon", 0)) - lon) <= 0.000001
                and abs(float(last.get("alt", 0)) - alt) <= 0.1
            ):
                return

        points.append({
            "lat": lat,
            "lon": lon,
            "alt": alt,
            "accuracy": data.get("accuracy", 999),
            "timestamp": data.get("timestamp", time.time()),
            "deviceId": data.get("deviceId", device_id),
            "deviceName": data.get("deviceName") or self.names.get(device_id, ""),
            "deviceType": data.get("deviceType", "unknown"),
        })

    def snapshot_trajectory_event(self, mission_id: str = "") -> Dict[str, Any]:
        devices: List[Dict[str, Any]] = []
        for device_id, points in self.trajectories.items():
            if not points:
                continue
            devices.append({
                "deviceId": device_id,
                "deviceName": self.names.get(device_id) or points[-1].get("deviceName", ""),
                "deviceType": points[-1].get("deviceType", "unknown"),
                "pointCount": len(points),
                "startTimestamp": points[0].get("timestamp"),
                "endTimestamp": points[-1].get("timestamp"),
                "points": points,
            })

        point_count = sum(device["pointCount"] for device in devices)
        event_id = f"trajectory-{datetime.now().strftime('%Y%m%d_%H%M%S')}-{uuid.uuid4().hex[:8]}"
        safe_mission_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", mission_id.strip()) if mission_id else ""
        filename = f"{safe_mission_id + '_' if safe_mission_id else ''}{event_id}.json"
        event = {
            "id": event_id,
            "missionId": mission_id or None,
            "createdAt": datetime.now().isoformat(),
            "startedAt": self.trajectory_started_at,
            "endedAt": datetime.now().isoformat(),
            "deviceCount": len(devices),
            "pointCount": point_count,
            "devices": devices,
        }

        if point_count > 0:
            path = TRAJECTORY_EVENTS_DIR / filename
            path.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
            event["path"] = str(path)
            event["url"] = f"/uploads/trajectory_events/{filename}"

        return event

    async def broadcast(self, message: str):
        """廣播給所有已連線裝置"""
        dead: list[str] = []
        for did, ws in self.connections.items():
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(did)
        for did in dead:
            self.disconnect(did)

    async def broadcast_except(self, message: str, exclude_id: str):
        """廣播給除 exclude_id 以外的裝置"""
        dead: list[str] = []
        for did, ws in self.connections.items():
            if did == exclude_id:
                continue
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(did)
        for did in dead:
            self.disconnect(did)


gps_manager = GPSConnectionManager()


# ──────────────────────────────────────────────
# Health Check
# ──────────────────────────────────────────────
@app.get("/ping")
async def ping():
    return {"message": "pong", "connections": len(gps_manager.connections)}


def _run_adb_command(args: List[str], timeout: float = 12.0) -> subprocess.CompletedProcess[bytes]:
    if not ADB_EXE.exists():
        raise FileNotFoundError(f"adb not found: {ADB_EXE}")
    env = _adb_env()
    return subprocess.run(
        [str(ADB_EXE), *args],
        capture_output=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def _adb_env() -> Dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(ADB_HOME_DIR)
    env["USERPROFILE"] = str(ADB_HOME_DIR)
    env["ANDROID_PREFS_ROOT"] = str(ADB_HOME_DIR)
    env["ANDROID_USER_HOME"] = str(ADB_HOME_DIR)
    env["APPDATA"] = str(ADB_HOME_DIR)
    env["LOCALAPPDATA"] = str(ADB_HOME_DIR)
    if os.name == "nt" and len(ADB_HOME_DIR.drive) >= 2:
        env["HOMEDRIVE"] = ADB_HOME_DIR.drive
        env["HOMEPATH"] = "\\"
    return env


def _list_connected_adb_devices() -> list[str]:
    devices = _run_adb_command(["devices"], 8.0)
    devices_text = devices.stdout.decode("utf-8", errors="ignore")
    connected: list[str] = []
    for line in devices_text.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) >= 2 and parts[1] == "device":
            connected.append(parts[0])
    return connected


def _resolve_controller_serial(requested_serial: str | None) -> str:
    connected = _list_connected_adb_devices()
    if not connected:
        raise RuntimeError("no controller connected over adb")
    if requested_serial and requested_serial in connected:
        return requested_serial
    return connected[0]


@app.get("/api/controller-screen")
async def controller_screen(serial: str | None = Query(None)) -> Response:
    try:
        resolved_serial = await asyncio.to_thread(_resolve_controller_serial, serial or DEFAULT_CONTROLLER_SERIAL)

        capture = await asyncio.to_thread(
            _run_adb_command,
            ["-s", resolved_serial, "exec-out", "screencap", "-p"],
            15.0,
        )
        if capture.returncode != 0:
            stderr = capture.stderr.decode("utf-8", errors="ignore").strip()
            return JSONResponse(
                {"success": False, "error": stderr or "adb screencap failed"},
                status_code=500,
            )

        png_bytes = capture.stdout
        if not png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return JSONResponse(
                {"success": False, "error": "controller screen capture did not return a PNG"},
                status_code=500,
            )

        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={"Cache-Control": "no-store, max-age=0", "X-Controller-Serial": resolved_serial},
        )
    except RuntimeError as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=503)
    except subprocess.TimeoutExpired:
        return JSONResponse({"success": False, "error": "controller screen capture timed out"}, status_code=504)
    except FileNotFoundError as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)
    except Exception as exc:
        logger.exception("Controller screen capture failed")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


def _iter_controller_stream(serial: str):
    adb_env = _adb_env()
    ffmpeg_args = [
        FFMPEG_EXE,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "h264",
        "-i",
        "pipe:0",
        "-vf",
        "fps=10,scale=640:-1",
        "-an",
        "-c:v",
        "mjpeg",
        "-q:v",
        "12",
        "-f",
        "mpjpeg",
        "-boundary_tag",
        "frame",
        "pipe:1",
    ]

    # Some devices do not emit an endless screenrecord stream progressively.
    # Using very short H.264 segments keeps latency manageable while still
    # producing a browser-friendly MJPEG feed.
    while True:
        adb_args = [
            str(ADB_EXE),
            "-s",
            serial,
            "exec-out",
            "screenrecord",
            "--output-format=h264",
            "--size",
            "854x480",
            "--bit-rate",
            "2000000",
            "--time-limit",
            "1",
            "-",
        ]

        adb_proc: subprocess.Popen[bytes] | None = None
        ffmpeg_proc: subprocess.Popen[bytes] | None = None
        try:
            adb_proc = subprocess.Popen(
                adb_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=adb_env,
            )
            ffmpeg_proc = subprocess.Popen(
                ffmpeg_args,
                stdin=adb_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if adb_proc.stdout:
                adb_proc.stdout.close()

            if not ffmpeg_proc.stdout:
                raise RuntimeError("ffmpeg stdout is not available")

            while True:
                chunk = ffmpeg_proc.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            for proc in (ffmpeg_proc, adb_proc):
                if proc and proc.poll() is None:
                    proc.kill()
            for proc in (ffmpeg_proc, adb_proc):
                if proc:
                    try:
                        proc.wait(timeout=1)
                    except Exception:
                        pass


@app.get("/api/controller-stream.mjpg")
async def controller_stream(serial: str | None = Query(None)):
    try:
        resolved_serial = await asyncio.to_thread(_resolve_controller_serial, serial or DEFAULT_CONTROLLER_SERIAL)
    except RuntimeError as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=503)

    return StreamingResponse(
        _iter_controller_stream(resolved_serial),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, max-age=0", "X-Controller-Serial": resolved_serial},
    )


# ──────────────────────────────────────────────
# WebSocket — GPS 同步
# ──────────────────────────────────────────────
@app.websocket("/ws/gps")
async def ws_gps(ws: WebSocket):
    await gps_manager.connect(ws)
    device_id: Optional[str] = None

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            # ── 裝置註冊 ─────────────────────────────
            if msg_type == "register-device":
                device_id = msg.get("deviceId") or f"auto-{uuid.uuid4().hex[:8]}"
                name = msg.get("deviceName", "Unknown Device")
                gps_manager.register(device_id, ws, name)
                await ws.send_text(json.dumps({
                    "type": "device-registered",
                    "deviceId": device_id,
                    "deviceName": name,
                    "timestamp": time.time()
                }))
                continue

            if not device_id:
                continue

            # ── 更新裝置名稱 ──────────────────────────
            if msg_type == "update-device-name":
                new_name = msg.get("deviceName", "")
                if new_name:
                    gps_manager.names[device_id] = new_name
                    await gps_manager.broadcast(json.dumps({
                        "type": "device-name-updated",
                        "deviceId": device_id,
                        "deviceName": new_name,
                        "timestamp": time.time()
                    }))
                continue

            # ── 清除軌跡指令 ──────────────────────────
            if msg_type == "clear-path":
                await gps_manager.broadcast_except(json.dumps({
                    "type": "clear-path",
                    "deviceId": device_id,
                    "deviceName": gps_manager.names.get(device_id, ""),
                    "timestamp": time.time()
                }), device_id)
                continue

            # ── GPS 資料 ──────────────────────────────
            if msg.get("lat") is not None and msg.get("lon") is not None:
                payload = {
                    "lat": msg["lat"],
                    "lon": msg["lon"],
                    "alt": msg.get("alt", 0),
                    "accuracy": msg.get("accuracy", 999),
                    "deviceId": msg.get("deviceId", device_id),
                    "deviceName": gps_manager.names.get(device_id, msg.get("deviceName", "")),
                    "deviceType": msg.get("deviceType", "unknown"),
                    "timestamp": msg.get("timestamp", time.time())
                }
                gps_manager.update_gps(device_id, payload)
                await gps_manager.broadcast(json.dumps(payload))
                continue

            # ── 其他訊息直接廣播 ──────────────────────
            msg.setdefault("deviceId", device_id)
            msg.setdefault("deviceName", gps_manager.names.get(device_id, ""))
            await gps_manager.broadcast(json.dumps(msg))

    except WebSocketDisconnect:
        if device_id:
            # 廣播斷線事件
            await gps_manager.broadcast(json.dumps({
                "type": "device-disconnected",
                "deviceId": device_id,
                "deviceName": gps_manager.names.get(device_id, ""),
                "timestamp": datetime.now().isoformat()
            }))
            gps_manager.disconnect(device_id)
    except Exception as e:
        logger.error(f"❌ WebSocket 錯誤: {e}")
        if device_id:
            gps_manager.disconnect(device_id)


# ──────────────────────────────────────────────
# REST — 取得所有裝置 GPS
# ──────────────────────────────────────────────
@app.get("/api/gps/devices")
async def get_devices():
    result = {
        did: {**data, "deviceName": gps_manager.names.get(did, "")}
        for did, data in gps_manager.gps_data.items()
    }
    return {"devices": result, "count": len(result)}


@app.post("/api/trajectory-events/snapshot")
async def snapshot_trajectory_event(mission_id: str = ""):
    event = gps_manager.snapshot_trajectory_event(mission_id)
    return {
        "success": True,
        "saved": event.get("pointCount", 0) > 0,
        "event": event,
    }


def _trajectory_event_summary(path: Path) -> Optional[Dict[str, Any]]:
    try:
        event = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(event, dict):
            return None
        return {
            "id": event.get("id") or path.stem,
            "missionId": event.get("missionId"),
            "createdAt": event.get("createdAt"),
            "startedAt": event.get("startedAt"),
            "endedAt": event.get("endedAt"),
            "deviceCount": event.get("deviceCount", 0),
            "pointCount": event.get("pointCount", 0),
            "filename": path.name,
            "url": f"/uploads/trajectory_events/{path.name}",
        }
    except Exception:
        return None


def _read_gps_csv_trajectory(csv_path: Path) -> Optional[Dict[str, Any]]:
    mission_id = csv_path.parent.name
    digest = hashlib.sha1(csv_path.read_bytes()).hexdigest()[:12]
    event_id = f"incoming-{mission_id}-{digest}"
    points: List[Dict[str, Any]] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                lat = float(row.get("lat", ""))
                lon = float(row.get("lon", ""))
                alt = float(row.get("alt") or 0)
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(lat) and math.isfinite(lon) and math.isfinite(alt)):
                continue
            timestamp = row.get("time_stamp") or row.get("timestamp") or None
            point: Dict[str, Any] = {
                "lat": lat,
                "lon": lon,
                "alt": alt,
                "deviceId": f"incoming-{mission_id}",
                "deviceName": mission_id,
                "deviceType": "uav",
            }
            if timestamp:
                point["timestamp"] = timestamp
            points.append(point)

    if not points:
        return None

    return {
        "id": event_id,
        "missionId": mission_id,
        "source": "incoming-gps-csv",
        "sourcePath": str(csv_path.relative_to(REPO_ROOT)),
        "createdAt": datetime.fromtimestamp(csv_path.stat().st_mtime).isoformat(),
        "importedAt": datetime.now().isoformat(),
        "startedAt": points[0].get("timestamp"),
        "endedAt": points[-1].get("timestamp"),
        "deviceCount": 1,
        "pointCount": len(points),
        "devices": [
            {
                "deviceId": f"incoming-{mission_id}",
                "deviceName": mission_id,
                "deviceType": "uav",
                "pointCount": len(points),
                "startTimestamp": points[0].get("timestamp"),
                "endTimestamp": points[-1].get("timestamp"),
                "points": points,
            }
        ],
    }


def _import_incoming_gps_csv(force: bool = False) -> Dict[str, Any]:
    imported: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for csv_path in sorted(INCOMING_CSV_DIR.glob("*/gps.csv")):
        try:
            event = _read_gps_csv_trajectory(csv_path)
            if event is None:
                skipped.append({"path": str(csv_path.relative_to(REPO_ROOT)), "reason": "no valid gps points"})
                continue
            target = TRAJECTORY_EVENTS_DIR / f"{event['id']}.json"
            if target.exists() and not force:
                skipped.append({
                    "path": str(csv_path.relative_to(REPO_ROOT)),
                    "reason": "already imported",
                    "eventId": event["id"],
                    "filename": target.name,
                })
                continue
            target.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
            imported.append({
                "path": str(csv_path.relative_to(REPO_ROOT)),
                "eventId": event["id"],
                "filename": target.name,
                "pointCount": event["pointCount"],
            })
        except Exception as exc:
            logger.exception("Failed to import GPS CSV: %s", csv_path)
            errors.append({"path": str(csv_path), "error": str(exc)})

    return {
        "success": len(errors) == 0,
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "importedCount": len(imported),
        "skippedCount": len(skipped),
        "errorCount": len(errors),
    }


@app.get("/api/trajectory-events")
async def list_trajectory_events():
    events = [
        summary
        for summary in (
            _trajectory_event_summary(path)
            for path in TRAJECTORY_EVENTS_DIR.glob("*.json")
        )
        if summary is not None
    ]
    events.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
    return {"success": True, "events": events, "count": len(events)}


@app.post("/api/trajectory-events/import-incoming")
async def import_incoming_trajectory_events(force: bool = False):
    result = _import_incoming_gps_csv(force=force)
    status_code = 200 if result["success"] else 207
    return JSONResponse(result, status_code=status_code)


@app.get("/api/trajectory-events/{event_id}")
async def get_trajectory_event(event_id: str):
    safe_event_id = event_id.strip()
    for path in TRAJECTORY_EVENTS_DIR.glob("*.json"):
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if event.get("id") == safe_event_id or path.stem == safe_event_id:
            event["filename"] = path.name
            event["url"] = f"/uploads/trajectory_events/{path.name}"
            return {"success": True, "event": event}
    return JSONResponse({"success": False, "error": f"trajectory event not found: {event_id}"}, status_code=404)


# ──────────────────────────────────────────────
# 照片上傳
# ──────────────────────────────────────────────
def _load_photos() -> list:
    if PHOTOS_JSON.exists():
        try:
            return json.loads(PHOTOS_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_photos(photos: list):
    PHOTOS_JSON.write_text(json.dumps(photos, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json_list(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _write_json_list(path: Path, data: List[Dict[str, Any]]):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_scene_index() -> List[Dict[str, Any]]:
    return _read_json_list(SCENE_INDEX_JSON)


def _image_format(content: bytes) -> Optional[str]:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return "image/gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _safe_upload_name(name: Optional[str], image_type: str) -> str:
    stem = Path(Path((name or '').replace('\\', '/')).name).stem.strip()
    safe_stem = re.sub(r'[^A-Za-z0-9._-]+', '_', stem).strip('._')
    extension = {
        'image/jpeg': '.jpg',
        'image/png': '.png',
        'image/gif': '.gif',
        'image/webp': '.webp',
    }[image_type]
    return f'{safe_stem[:80]}{extension}' if safe_stem else ''


@app.post("/api/upload-photo")
async def upload_photo(
    photo: UploadFile = File(...),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    altitude: Optional[float] = Form(None),
    deviceId: Optional[str] = Form(None),
):
    try:
        content = await photo.read()
        if len(content) > 10 * 1024 * 1024:
            return JSONResponse({"success": False, "error": "檔案超過 10MB 限制"}, status_code=413)

        image_type = _image_format(content)
        if not content or image_type is None or photo.content_type != image_type:
            return JSONResponse({"success": False, "error": "不支援的圖片格式"}, status_code=415)

        client_name = _safe_upload_name(photo.filename, image_type)
        if not client_name:
            return JSONResponse({"success": False, "error": "無效的檔案名稱"}, status_code=400)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{ts}_{client_name}"
        path = (UPLOAD_DIR / filename).resolve()
        if path.parent != UPLOAD_DIR.resolve():
            return JSONResponse({"success": False, "error": "無效的檔案名稱"}, status_code=400)
        path.write_bytes(content)

        record = {
            "filename": filename,
            "url": f"/uploads/{filename}",
            "timestamp": ts,
            "latitude": latitude,
            "longitude": longitude,
            "altitude": altitude,
            "deviceId": deviceId,
        }

        photos = _load_photos()
        photos.insert(0, record)
        _save_photos(photos)

        # 廣播給所有 WebSocket 連線
        await gps_manager.broadcast(json.dumps({
            "type": "photo-upload",
            **record
        }))

        logger.info(f"📸 照片已儲存: {filename}  deviceId={deviceId}")
        return JSONResponse({"success": True, **record})

    except Exception:
        logger.exception("照片上傳失敗")
        return JSONResponse({"success": False, "error": "照片上傳失敗"}, status_code=500)


@app.get("/api/photo-history")
async def photo_history():
    photos = _load_photos()
    return {"success": True, "photos": photos, "count": len(photos)}


@app.delete("/api/delete-photo/{filename}")
async def delete_photo(filename: str):
    try:
        if not filename or Path(filename).name != filename or any(separator in filename for separator in ("/", "\\")):
            return JSONResponse({"success": False, "error": "無效的檔案名稱"}, status_code=400)
        photos = _load_photos()
        if not any(p.get("filename") == filename for p in photos):
            return JSONResponse({"success": False, "error": "照片不存在"}, status_code=404)
        path = (UPLOAD_DIR / filename).resolve()
        if path.parent != UPLOAD_DIR.resolve():
            return JSONResponse({"success": False, "error": "無效的檔案名稱"}, status_code=400)
        if path.exists():
            path.unlink()

        photos = [p for p in photos if p.get("filename") != filename]
        _save_photos(photos)

        await gps_manager.broadcast(json.dumps({
            "type": "photo_deleted",
            "filename": filename,
            "timestamp": datetime.now().isoformat()
        }))

        return {"success": True, "filename": filename}
    except Exception:
        logger.exception("照片刪除失敗")
        return JSONResponse({"success": False, "error": "照片刪除失敗"}, status_code=500)


# ──────────────────────────────────────────────
# 選點與場景任務 API（Phase-1: for Blender pipeline）
# ──────────────────────────────────────────────
class LocationSelectRequest(BaseModel):
    lat: float
    lon: float
    zoom: Optional[int] = None
    timestamp: Optional[str] = None
    source: str = "my_map"
    place_name: Optional[str] = None


class SceneTaskCreateRequest(BaseModel):
    location_id: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    zoom: Optional[int] = None
    place_name: Optional[str] = None
    scene_name: str = Field(default="custom_scene", min_length=1)
    auto_run: bool = True


class SceneDisplayNameRequest(BaseModel):
    display_name: str


class BuildingCheckRequest(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _latlon_to_tile_float(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def _tile_xy_to_latlon(tile_x: float, tile_y: float, zoom: int) -> tuple[float, float]:
    n = 2.0 ** zoom
    lon = tile_x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * tile_y / n)))
    lat = math.degrees(lat_rad)
    return lat, lon


def _degree_to_meter_scales(lat: float) -> tuple[float, float]:
    meters_per_deg_lat = 111320.0
    meters_per_deg_lon = meters_per_deg_lat * math.cos(math.radians(lat))
    return meters_per_deg_lat, max(1.0, meters_per_deg_lon)


def _bbox_by_center_meters(lat: float, lon: float, area_m: float) -> tuple[float, float, float, float]:
    half_m = max(1.0, float(area_m)) * 0.5
    meters_per_deg_lat, meters_per_deg_lon = _degree_to_meter_scales(lat)
    lat_delta = half_m / meters_per_deg_lat
    lon_delta = half_m / meters_per_deg_lon
    min_lat = _clamp(lat - lat_delta, -89.0, 89.0)
    max_lat = _clamp(lat + lat_delta, -89.0, 89.0)
    min_lon = _clamp(lon - lon_delta, -180.0, 180.0)
    max_lon = _clamp(lon + lon_delta, -180.0, 180.0)
    return min_lat, max_lat, min_lon, max_lon


def _bbox_by_zoom_centered(
    lat: float,
    lon: float,
    zoom: int,
    span_tiles: float = DETAIL_BBOX_SPAN_TILES,
) -> tuple[float, float, float, float]:
    z = max(0, min(19, int(zoom)))
    n = 2.0 ** z
    half_span = max(0.5, float(span_tiles) * 0.5)

    x_f, y_f = _latlon_to_tile_float(lat, lon, z)
    min_x = _clamp(x_f - half_span, 0.0, n)
    max_x = _clamp(x_f + half_span, 0.0, n)
    min_y = _clamp(y_f - half_span, 0.0, n)
    max_y = _clamp(y_f + half_span, 0.0, n)

    max_lat, min_lon = _tile_xy_to_latlon(min_x, min_y, z)
    min_lat, max_lon = _tile_xy_to_latlon(max_x, max_y, z)
    return min(min_lat, max_lat), max(min_lat, max_lat), min(min_lon, max_lon), max(min_lon, max_lon)


def _overpass_building_count_query(south: float, west: float, north: float, east: float, timeout: int) -> str:
    return f"""[out:json][timeout:{timeout}];
(
  way["building"]({south},{west},{north},{east});
  relation["building"]({south},{west},{north},{east});
);
out count;"""


def _parse_overpass_building_count(payload: Dict[str, Any]) -> int:
    for element in payload.get("elements", []):
        tags = element.get("tags", {}) if isinstance(element, dict) else {}
        if "ways" in tags or "relations" in tags:
            ways = int(tags.get("ways", 0))
            relations = int(tags.get("relations", 0))
            return ways + relations
    return 0


def _check_building_count_sync(lat: float, lon: float) -> Dict[str, Any]:
    min_lat, max_lat, min_lon, max_lon = _bbox_by_center_meters(lat, lon, GENERATED_SCENE_AREA_M)
    bbox = {
        "south": min_lat,
        "west": min_lon,
        "north": max_lat,
        "east": max_lon,
    }
    deadline = time.monotonic() + BUILDING_CHECK_TOTAL_TIMEOUT_SECONDS
    attempts = []

    for endpoint in OVERPASS_ENDPOINTS:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break

        query_timeout = max(1, int(min(BUILDING_CHECK_REQUEST_TIMEOUT_SECONDS, remaining)))
        query = _overpass_building_count_query(min_lat, min_lon, max_lat, max_lon, query_timeout)
        data = urllib.parse.urlencode({"data": query}).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=data,
            headers={"User-Agent": "integrated-sim-world/1.0"},
            method="POST",
        )

        try:
            request_timeout = max(1.0, min(BUILDING_CHECK_REQUEST_TIMEOUT_SECONDS, remaining))
            with urllib.request.urlopen(request, timeout=request_timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            building_count = _parse_overpass_building_count(payload)
            return {
                "success": True,
                "building_count": building_count,
                "has_buildings": building_count > 0,
                "zoom": BASEMAP_GENERATION_ZOOM,
                "area_m": GENERATED_SCENE_AREA_M,
                "bbox_mode": "fixed_meters",
                "bbox": bbox,
                "source": endpoint,
            }
        except urllib.error.HTTPError as exc:
            attempts.append({"source": endpoint, "error": f"HTTP {exc.code}"})
        except Exception as exc:
            attempts.append({"source": endpoint, "error": str(exc)})

    raise TimeoutError(json.dumps(attempts, ensure_ascii=False))


def _find_blender_executable() -> Optional[str]:
    env_path = os.environ.get("BLENDER_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    for candidate in [
        shutil.which("blender"),
        r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe",
    ]:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


def _get_task(task_id: str) -> Optional[Dict[str, Any]]:
    with SCENE_TASKS_LOCK:
        tasks = _read_json_list(SCENE_TASKS_JSON)
        return next((x for x in tasks if x.get("id") == task_id), None)


def _update_task(task_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    with SCENE_TASKS_LOCK:
        tasks = _read_json_list(SCENE_TASKS_JSON)
        for idx, task in enumerate(tasks):
            if task.get("id") == task_id:
                task.update(updates)
                task["updatedAt"] = datetime.now().isoformat()
                tasks[idx] = task
                _write_json_list(SCENE_TASKS_JSON, tasks)
                return task
    return None


def _is_generated_scene_key(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    key = value.upper()
    return (
        len(key) == 12
        and key.startswith("T-")
        and all(ch in "0123456789ABCDEF" for ch in key[2:])
    )


def _normalize_scene_key(value: Any) -> Optional[str]:
    if not _is_generated_scene_key(value):
        return None
    return str(value).upper()


def _generate_scene_key_locked(tasks: List[Dict[str, Any]]) -> str:
    existing = {
        key
        for key in (_normalize_scene_key(task.get("sceneKey")) for task in tasks)
        if key
    }
    if SCENE_DIR.exists():
        for scene_dir in SCENE_DIR.iterdir():
            key = _normalize_scene_key(scene_dir.name)
            if key:
                existing.add(key)

    for _ in range(20):
        scene_key = f"T-{uuid.uuid4().hex[:10].upper()}"
        if scene_key not in existing and not (SCENE_DIR / scene_key).exists():
            return scene_key

    raise RuntimeError("Unable to allocate a unique generated scene key after 20 attempts")


def _task_scene_key(task: Dict[str, Any]) -> Optional[str]:
    key = _normalize_scene_key(task.get("sceneKey"))
    if key:
        return key

    # New metadata uses snake_case. This lets old in-memory task payloads recover
    # after Blender succeeds but before task JSON is updated.
    key = _normalize_scene_key(task.get("scene_key"))
    if key:
        return key
    return None


def _infer_output_dir(task: Dict[str, Any]) -> Path:
    configured = task.get("outputDir")
    if configured:
        return Path(configured)
    scene_key = _task_scene_key(task)
    if scene_key:
        return SCENE_DIR / scene_key
    return GENERATED_SCENES_DIR / str(task.get("id", ""))


def _scene_artifact_paths(task: Dict[str, Any], output_dir: Path) -> Dict[str, Path]:
    scene_key = _task_scene_key(task)
    if scene_key:
        return {
            "glb": output_dir / f"{scene_key}.glb",
            "blend": output_dir / f"{scene_key}.blend",
            "xml": output_dir / f"{scene_key}.xml",
        }
    return {
        "glb": output_dir / "scene.glb",
        "blend": output_dir / "scene.blend",
        "xml": output_dir / "scene.xml",
    }


def _artifact_url(path: Path) -> Optional[str]:
    try:
        rel = path.resolve().relative_to(SCENE_DIR.resolve())
        return f"/generated-scenes/{rel.as_posix()}"
    except Exception:
        return None


def _scene_index_entry(task: Dict[str, Any], indexed_at: str) -> Optional[Dict[str, Any]]:
    if task.get("status") != "completed":
        return None

    scene_key = _task_scene_key(task)
    if not scene_key:
        return None

    output_dir = SCENE_DIR / scene_key
    artifact_paths = _scene_artifact_paths({**task, "sceneKey": scene_key}, output_dir)
    if not output_dir.is_dir() or not artifact_paths["glb"].is_file() or not artifact_paths["xml"].is_file():
        return None

    entry = {
        "id": task.get("id"),
        "sceneKey": scene_key,
        "sceneName": task.get("sceneName"),
        "displayName": task.get("displayName"),
        "location": task.get("location"),
        "modelUrl": task.get("modelUrl") or _artifact_url(artifact_paths["glb"]),
        "sionnaSceneXml": task.get("sionnaSceneXml") or str(artifact_paths["xml"]),
        "createdAt": task.get("createdAt"),
        "updatedAt": task.get("updatedAt"),
        "indexedAt": indexed_at,
    }
    return {key: value for key, value in entry.items() if value is not None}


def rebuild_scene_index() -> List[Dict[str, Any]]:
    indexed_at = datetime.now().isoformat()
    with SCENE_TASKS_LOCK:
        tasks = _read_json_list(SCENE_TASKS_JSON)

    scenes = [
        entry
        for entry in (_scene_index_entry(task, indexed_at) for task in tasks)
        if entry is not None
    ]
    _write_json_list(SCENE_INDEX_JSON, scenes)
    return scenes


def _scene_admin_error(token: Optional[str]) -> Optional[JSONResponse]:
    configured = os.environ.get("SCENE_ADMIN_TOKEN", "")
    if not configured:
        return JSONResponse({"success": False, "error": "Scene administration is unavailable"}, status_code=503)
    if not token or not secrets.compare_digest(token, configured):
        return JSONResponse({"success": False, "error": "Invalid scene administration token"}, status_code=403)
    return None


def _scene_task_ready(task: Dict[str, Any]) -> bool:
    if _scene_index_entry(task, datetime.now().isoformat()) is None:
        return False
    scene_dir = _generated_scene_dir(task)
    if not scene_dir:
        return False
    metadata_path = scene_dir / "scene_metadata.json"
    try:
        scene_frame_from_metadata(json.loads(metadata_path.read_text(encoding="utf-8")))
        return True
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _generated_scene_dir(task: Dict[str, Any]) -> Optional[Path]:
    scene_key = _task_scene_key(task)
    if not scene_key:
        return None
    root = SCENE_DIR.resolve()
    target = (SCENE_DIR / scene_key).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target


async def _refresh_scene_index_after_mutation() -> None:
    try:
        await asyncio.to_thread(rebuild_scene_index)
    except Exception:
        logger.exception("Scene mutation succeeded, but the generated scene index could not be refreshed")


def _reconcile_task_from_artifacts(task: Dict[str, Any]) -> Dict[str, Any]:
    """Recover task status from generated files when worker status update was interrupted."""
    task_id = str(task.get("id", ""))
    if not task_id:
        return task

    output_dir = _infer_output_dir(task)
    metadata_path = output_dir / "scene_metadata.json"
    artifact_paths = _scene_artifact_paths(task, output_dir)
    glb_path = artifact_paths["glb"]
    xml_path = artifact_paths["xml"]

    # Nothing to reconcile.
    if not metadata_path.exists() and not glb_path.exists():
        return task

    metadata = {}
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            metadata = {}

    current_status = task.get("status")
    if current_status not in {"running", "queued"}:
        return task

    inferred_status = None
    inferred_error = None
    if metadata.get("status") == "failed":
        inferred_status = "failed"
        inferred_error = metadata.get("import_error") or metadata.get("error")
    elif _task_scene_key(task):
        if metadata.get("status") == "completed" and glb_path.exists() and xml_path.exists():
            try:
                scene_frame_from_metadata(metadata)
            except ValueError:
                return task
            inferred_status = "completed"
    elif glb_path.exists() or metadata.get("status") == "completed":
        inferred_status = "completed"

    if not inferred_status:
        return task

    updates = {
        "status": inferred_status,
        "stage": "blender_generated" if inferred_status == "completed" else "blender_generation_failed",
        "note": "Recovered from generated artifacts",
        "outputDir": str(output_dir),
        "finishedAt": datetime.now().isoformat(),
    }
    scene_key = _task_scene_key(task) or _normalize_scene_key(metadata.get("scene_key"))
    if scene_key:
        updates["sceneKey"] = scene_key
        updates["modelUrl"] = _artifact_url(glb_path)
        updates["sionnaSceneXml"] = str(xml_path)
    if inferred_status == "failed":
        updates["error"] = inferred_error or "Recovered failure from scene metadata"
    else:
        updates["error"] = None

    updated = _update_task(task_id, updates)
    if inferred_status == "completed":
        rebuild_scene_index()
    return updated or task


def _run_blender_task_sync(task_id: str) -> Dict[str, Any]:
    task = _get_task(task_id)
    if not task:
        return {"success": False, "error": f"task not found: {task_id}"}

    scene_key = _task_scene_key(task)
    if not scene_key:
        return {"success": False, "error": f"task sceneKey missing: {task_id}"}

    out_dir = _infer_output_dir(task)
    artifact_paths = _scene_artifact_paths(task, out_dir)

    blender_exe = _find_blender_executable()
    if not blender_exe:
        return {
            "success": False,
            "error": "Blender not found. Set BLENDER_PATH or install Blender in default path.",
            "outputDir": str(out_dir),
            "sceneKey": scene_key,
            "modelUrl": _artifact_url(artifact_paths["glb"]),
            "sionnaSceneXml": str(artifact_paths["xml"]),
        }

    loc = task.get("location", {})
    lat = loc.get("lat")
    lon = loc.get("lon")
    zoom = loc.get("zoom")
    if lat is None or lon is None:
        return {"success": False, "error": "task location lat/lon missing"}

    out_dir.mkdir(parents=True, exist_ok=True)

    script_path = BASE_DIR / "blender_generate_scene.py"
    cmd = [
        blender_exe,
        "--background",
        "--python",
        str(script_path),
        "--",
        "--lat",
        str(lat),
        "--lon",
        str(lon),
        "--zoom",
        str(zoom if zoom is not None else BASEMAP_GENERATION_ZOOM),
        "--area-m",
        str(GENERATED_SCENE_AREA_M),
        "--scene-name",
        str(task.get("sceneName", "custom_scene")),
        "--scene-key",
        scene_key,
        "--output-dir",
        str(out_dir),
    ]

    run = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    (out_dir / "blender_stdout.log").write_text(run.stdout or "", encoding="utf-8")
    (out_dir / "blender_stderr.log").write_text(run.stderr or "", encoding="utf-8")

    if run.returncode != 0:
        err = (run.stderr or run.stdout or "Blender exited with error").strip()
        return {
            "success": False,
            "error": f"Blender failed (exit={run.returncode}): {err[:600]}",
            "outputDir": str(out_dir),
            "blenderPath": blender_exe,
            "sceneKey": scene_key,
            "modelUrl": _artifact_url(artifact_paths["glb"]),
            "sionnaSceneXml": str(artifact_paths["xml"]),
        }

    metadata_path = out_dir / "scene_metadata.json"
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            scene_frame_from_metadata(metadata)
            if metadata.get("status") == "failed":
                return {
                    "success": False,
                    "error": metadata.get("import_error") or metadata.get("error") or "Scene metadata reports failure",
                    "outputDir": str(out_dir),
                    "blenderPath": blender_exe,
                    "sceneKey": scene_key,
                    "modelUrl": _artifact_url(artifact_paths["glb"]),
                    "sionnaSceneXml": str(artifact_paths["xml"]),
                }
        except ValueError as exc:
            return {
                "success": False,
                "error": str(exc),
                "error_type": "scene_frame_invalid",
                "outputDir": str(out_dir),
                "blenderPath": blender_exe,
                "sceneKey": scene_key,
                "modelUrl": _artifact_url(artifact_paths["glb"]),
                "sionnaSceneXml": str(artifact_paths["xml"]),
            }
        except Exception:
            # If metadata can't be parsed, keep subprocess success result.
            pass

    missing_artifacts = [
        str(path)
        for path in [artifact_paths["glb"], artifact_paths["xml"]]
        if not path.exists()
    ]
    if missing_artifacts:
        return {
            "success": False,
            "error": f"Blender completed but required scene artifact(s) are missing: {', '.join(missing_artifacts)}",
            "outputDir": str(out_dir),
            "blenderPath": blender_exe,
            "sceneKey": scene_key,
            "modelUrl": _artifact_url(artifact_paths["glb"]),
            "sionnaSceneXml": str(artifact_paths["xml"]),
        }

    return {
        "success": True,
        "outputDir": str(out_dir),
        "blenderPath": blender_exe,
        "sceneKey": scene_key,
        "modelUrl": _artifact_url(artifact_paths["glb"]),
        "sionnaSceneXml": str(artifact_paths["xml"]),
    }


def _prepare_iss_unet_dataset_for_scene_task(scene_key: str) -> Dict[str, Any]:
    from app.iss_unet_dataset_service import prepare_iss_unet_dataset

    try:
        resolutions = {}
        for pixel_size_m in (1, 2, 4):
            resolutions[f"{pixel_size_m}m"] = prepare_iss_unet_dataset(
                scene_key,
                scene_dir=SCENE_DIR,
                pixel_size_m=pixel_size_m,
            )
        result = dict(resolutions["4m"])
        result["resolutions"] = resolutions
        return {
            "stage": "iss_unet_dataset_prepared",
            "note": "Blender stage completed and ISS_UNET dataset prepared",
            "issUnetDataset": result,
        }
    except Exception as exc:
        logger.exception("ISS_UNET dataset preparation failed for generated scene %s", scene_key)
        return {
            "stage": "iss_unet_dataset_failed",
            "note": "Blender stage completed but ISS_UNET dataset preparation failed",
            "issUnetDataset": {
                "available": False,
                "error": str(exc),
            },
        }


async def _process_scene_task(task_id: str):
    _update_task(
        task_id,
        {
            "status": "running",
            "stage": "running_blender_generation",
            "note": "Blender generation started",
            "startedAt": datetime.now().isoformat(),
        },
    )

    try:
        result = await asyncio.to_thread(_run_blender_task_sync, task_id)
    except Exception as exc:
        result = {"success": False, "error": str(exc)}

    if result.get("success"):
        dataset_updates = await asyncio.to_thread(
            _prepare_iss_unet_dataset_for_scene_task,
            result.get("sceneKey") or scene_key,
        )
        updates = {
            "status": "completed",
            "stage": dataset_updates["stage"],
            "note": dataset_updates["note"],
            "error": None,
            "blenderPath": result.get("blenderPath"),
            "finishedAt": datetime.now().isoformat(),
            "issUnetDataset": dataset_updates["issUnetDataset"],
        }
        for key in ("outputDir", "sceneKey", "modelUrl", "sionnaSceneXml"):
            if result.get(key) is not None:
                updates[key] = result.get(key)
        _update_task(task_id, updates)
        rebuild_scene_index()
    else:
        updates = {
            "status": "failed",
            "stage": "blender_generation_failed",
            "note": "Blender stage failed",
            "error": result.get("error"),
            "blenderPath": result.get("blenderPath"),
            "finishedAt": datetime.now().isoformat(),
        }
        for key in ("outputDir", "sceneKey", "modelUrl", "sionnaSceneXml"):
            if result.get(key) is not None:
                updates[key] = result.get(key)
        _update_task(task_id, updates)


@app.on_event("startup")
async def refresh_scene_index_on_startup():
    await asyncio.to_thread(rebuild_scene_index)


@app.post("/api/location/select")
async def select_location(req: LocationSelectRequest):
    locations = _read_json_list(LOCATION_JSON)
    location_id = f"loc-{uuid.uuid4().hex[:10]}"

    item = {
        "id": location_id,
        "lat": req.lat,
        "lon": req.lon,
        "zoom": req.zoom,
        "source": req.source,
        "place_name": req.place_name,
        "timestamp": req.timestamp or datetime.now().isoformat(),
        "createdAt": datetime.now().isoformat(),
    }

    locations.insert(0, item)
    _write_json_list(LOCATION_JSON, locations)
    return {"success": True, "location": item, "count": len(locations)}


@app.get("/api/location/latest")
async def get_latest_location():
    locations = _read_json_list(LOCATION_JSON)
    return {
        "success": True,
        "location": locations[0] if locations else None,
        "count": len(locations),
    }


@app.post("/api/buildings/check")
async def check_buildings(req: BuildingCheckRequest):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_check_building_count_sync, req.lat, req.lon),
            timeout=BUILDING_CHECK_TOTAL_TIMEOUT_SECONDS + 1.0,
        )
    except (asyncio.TimeoutError, TimeoutError) as exc:
        return JSONResponse(
            {
                "success": False,
                "error": "Building check timed out",
                "detail": str(exc),
            },
            status_code=504,
        )
    except Exception as exc:
        logger.warning("Building check failed: %s", exc)
        return JSONResponse(
            {
                "success": False,
                "error": "Building check failed",
                "detail": str(exc),
            },
            status_code=504,
        )


@app.post("/api/scene-tasks/from-location")
async def create_scene_task(req: SceneTaskCreateRequest):
    lat = req.lat
    lon = req.lon
    requested_zoom = req.zoom
    zoom = BASEMAP_GENERATION_ZOOM
    place_name = req.place_name

    if req.location_id:
        locations = _read_json_list(LOCATION_JSON)
        selected = next((x for x in locations if x.get("id") == req.location_id), None)
        if not selected:
            return JSONResponse(
                {"success": False, "error": f"location_id not found: {req.location_id}"},
                status_code=404,
            )
        lat = selected.get("lat")
        lon = selected.get("lon")
        requested_zoom = selected.get("zoom")
        zoom = BASEMAP_GENERATION_ZOOM
        place_name = selected.get("place_name")

    if lat is None or lon is None:
        return JSONResponse(
            {"success": False, "error": "lat/lon required (or provide a valid location_id)"},
            status_code=422,
        )

    with SCENE_TASKS_LOCK:
        tasks = _read_json_list(SCENE_TASKS_JSON)
        task_id = f"task-{uuid.uuid4().hex[:10]}"
        try:
            scene_key = _generate_scene_key_locked(tasks)
        except RuntimeError as exc:
            return JSONResponse({"success": False, "error": str(exc)}, status_code=500)
        output_dir = SCENE_DIR / scene_key
        model_url = f"/generated-scenes/{scene_key}/{scene_key}.glb"
        task = {
            "id": task_id,
            "sceneKey": scene_key,
            "sceneName": req.scene_name,
            "status": "queued",
            "stage": "pending_blender_generation",
            "location": {
                "lat": lat,
                "lon": lon,
                "zoom": zoom,
                "requested_zoom": requested_zoom,
                "place_name": place_name,
                "location_id": req.location_id,
            },
            "outputDir": str(output_dir),
            "modelUrl": model_url,
            "sionnaSceneXml": str(output_dir / f"{scene_key}.xml"),
            "createdAt": datetime.now().isoformat(),
            "updatedAt": datetime.now().isoformat(),
            "note": "Task created and waiting for Blender generation.",
        }
        tasks.insert(0, task)
        _write_json_list(SCENE_TASKS_JSON, tasks)

    if req.auto_run:
        asyncio.create_task(_process_scene_task(task_id))

    return {"success": True, "task": task, "count": len(tasks)}


@app.get("/api/scene-tasks")
async def list_scene_tasks():
    with SCENE_TASKS_LOCK:
        tasks = [task for task in _read_json_list(SCENE_TASKS_JSON) if task.get("status") != "deleted"]
    # Reconcile stale running/queued tasks by checking generated artifacts.
    reconciled_tasks = [
        _reconcile_task_from_artifacts(task) if task.get("status") in {"running", "queued"} else task
        for task in tasks
    ]
    return {"success": True, "tasks": reconciled_tasks, "count": len(reconciled_tasks)}


@app.get("/api/generated-scenes")
async def list_generated_scenes():
    with SCENE_TASKS_LOCK:
        tasks = {
            task.get("id"): task
            for task in _read_json_list(SCENE_TASKS_JSON)
            if task.get("status") == "completed"
        }
    scenes = []
    for cached in _read_scene_index():
        task = tasks.get(cached.get("id"))
        if not task:
            continue
        scene = {**cached}
        if task.get("displayName"):
            scene["displayName"] = task["displayName"]
        else:
            scene.pop("displayName", None)
        scenes.append(scene)
    return {"success": True, "scenes": scenes, "count": len(scenes)}


@app.post("/api/generated-scenes/refresh")
async def refresh_generated_scenes():
    scenes = await asyncio.to_thread(rebuild_scene_index)
    return {"success": True, "scenes": scenes, "count": len(scenes)}


@app.patch("/api/scene-tasks/{task_id}/display-name")
async def update_scene_display_name(
    task_id: str,
    req: SceneDisplayNameRequest,
    x_scene_admin_token: Optional[str] = Header(default=None),
):
    if error := _scene_admin_error(x_scene_admin_token):
        return error

    display_name = req.display_name.strip()
    if not display_name or len(display_name) > 80:
        return JSONResponse({"success": False, "error": "Display name must be 1-80 characters"}, status_code=422)

    task = _get_task(task_id)
    if not task:
        return JSONResponse({"success": False, "error": f"task not found: {task_id}"}, status_code=404)
    if task.get("status") != "completed" or not _scene_task_ready(task):
        return JSONResponse({"success": False, "error": "Only ready scenes can be renamed"}, status_code=409)

    updated = await asyncio.to_thread(_update_task, task_id, {"displayName": display_name})
    await _refresh_scene_index_after_mutation()
    return {"success": True, "task": updated}


@app.delete("/api/scene-tasks/{task_id}")
async def delete_scene_task(
    task_id: str,
    x_scene_admin_token: Optional[str] = Header(default=None),
):
    if error := _scene_admin_error(x_scene_admin_token):
        return error

    task = _get_task(task_id)
    if not task:
        return JSONResponse({"success": False, "error": f"task not found: {task_id}"}, status_code=404)
    if task.get("status") not in {"completed", "failed"}:
        return JSONResponse({"success": False, "error": "Only completed or failed scenes can be deleted"}, status_code=409)

    scene_dir = _generated_scene_dir(task)
    if not scene_dir:
        return JSONResponse({"success": False, "error": "Invalid generated scene path"}, status_code=409)
    try:
        if scene_dir.exists():
            await asyncio.wait_for(asyncio.to_thread(shutil.rmtree, scene_dir), timeout=30)
    except Exception as exc:
        return JSONResponse({"success": False, "error": f"Failed to delete scene data: {exc}"}, status_code=500)

    deleted_at = datetime.now().isoformat()
    updated = await asyncio.to_thread(_update_task, task_id, {
        "status": "deleted",
        "stage": "deleted",
        "deletedAt": deleted_at,
        "note": "Scene data deleted",
    })
    await _refresh_scene_index_after_mutation()
    return {"success": True, "task": updated}


@app.get("/api/scene-tasks/{task_id}")
async def get_scene_task(task_id: str):
    with SCENE_TASKS_LOCK:
        tasks = _read_json_list(SCENE_TASKS_JSON)
        task = next((x for x in tasks if x.get("id") == task_id), None)
    if not task:
        return JSONResponse({"success": False, "error": f"task not found: {task_id}"}, status_code=404)
    task = _reconcile_task_from_artifacts(task)
    return {"success": True, "task": task}


@app.get("/api/scene-tasks/{task_id}/metadata")
async def get_scene_task_metadata(task_id: str):
    """Get the scene_metadata.json from the generated scene directory"""
    task = _get_task(task_id)
    if not task:
        return JSONResponse({"success": False, "error": f"task not found: {task_id}"}, status_code=404)

    task = _reconcile_task_from_artifacts(task)
    output_dir = _infer_output_dir(task)
    if not output_dir.exists():
        return JSONResponse({"success": False, "error": f"output directory not found: {output_dir}"}, status_code=404)
    
    metadata_path = output_dir / "scene_metadata.json"
    if not metadata_path.exists():
        return JSONResponse({"success": False, "error": f"metadata file not found"}, status_code=404)
    
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        scene_frame_from_metadata(metadata)
        return {"success": True, "metadata": metadata}
    except ValueError as exc:
        return JSONResponse({"success": False, "error": str(exc), "error_type": "scene_frame_invalid"}, status_code=409)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/api/scene-tasks/{task_id}/run")
async def run_scene_task(task_id: str):
    task = _get_task(task_id)
    if not task:
        return JSONResponse({"success": False, "error": f"task not found: {task_id}"}, status_code=404)

    task = _reconcile_task_from_artifacts(task)

    if task.get("status") == "running":
        return {"success": True, "task": task, "message": "Task is already running"}

    asyncio.create_task(_process_scene_task(task_id))
    latest = _get_task(task_id)
    return {"success": True, "task": latest, "message": "Task execution started"}


# ──────────────────────────────────────────────
# Sionna 無線模擬 API
# ──────────────────────────────────────────────

from app.sionna_service import SionnaLLVMError


def _sionna_llvm_error_response(context: str, exc: Exception) -> JSONResponse:
    logger.error(f"Sionna LLVM error ({context}): {exc}")
    return JSONResponse(
        {
            "error": str(exc),
            "error_type": "llvm_missing",
        },
        status_code=503,
    )


@app.get("/api/sionna/status")
async def sionna_status():
    """Check if Sionna is installed and usable."""
    import traceback
    llvm_path = os.environ.get("DRJIT_LIBLLVM_PATH", "NOT SET")
    try:
        import sionna  # noqa: F401
        from app.sionna_service import _load_sionna
        _load_sionna()
        return {"available": True, "version": getattr(sionna, "__version__", "unknown"), "llvm_path": llvm_path}
    except SionnaLLVMError as e:
        return {
            "available": False,
            "version": getattr(sionna, "__version__", None) if "sionna" in locals() else None,
            "llvm_path": llvm_path,
            "error": str(e),
            "error_type": "llvm_missing",
            "trace": traceback.format_exc(),
        }
    except ImportError as e:
        return {"available": False, "version": None, "llvm_path": llvm_path, "error": str(e), "trace": traceback.format_exc()}


from fastapi import HTTPException
from fastapi.responses import Response

DEFAULT_POWER_DBM_BY_ROLE = {
    "tx": 80.0,
    "jammer": 80.0,
}
BUILTIN_SCENE_NAMES = {
    "ntpu": "NTPU",
    "nycu": "NYCU",
}

class ENUIn(BaseModel):
    east_m: float
    north_m: float
    up_m: float


class DeviceIn(BaseModel):
    name: str
    role: str
    enu: ENUIn
    power_dbm: Optional[float] = Field(default=None)


class BaseSionnaRequest(BaseModel):
    scene: str
    devices: List[DeviceIn]


class ISSUNetCFARRequest(BaseModel):
    enabled: bool = Field(default=True)
    guard_cells: int = Field(default=2, ge=1, le=10)
    training_cells: int = Field(default=4, ge=1, le=20)
    pfa: float = Field(default=1e-4, gt=0.0, lt=1.0)
    os_rank: float = Field(default=0.75, gt=0.0, le=1.0)
    min_threshold_dbm: float = Field(default=-50.0, ge=-140.0, le=-35.0)


class ISSUNetReconstructRequest(BaseModel):
    scene: str
    sparse_ratio: float = Field(default=0.2, ge=0.0, le=1.0)
    pixel_size_m: Literal[1, 2, 4] = Field(default=4)
    cfar: ISSUNetCFARRequest = Field(default_factory=ISSUNetCFARRequest)
    seed: int = Field(default=41)
    apply_building_mask: bool = Field(default=True)
    devices: List[DeviceIn] = Field(default_factory=list)


class ISSUNetDatasetPrepareRequest(BaseModel):
    scene: str
    bs_pos: tuple[int, int] = Field(default=(64, 64))
    jammer_positions: List[tuple[int, int]] = Field(default_factory=lambda: [(30, 30)])
    jammer_powers: List[float] = Field(default_factory=lambda: [40.0])
    bs_power: float = Field(default=40.0)
    bs_height: float = Field(default=40.0)
    jammer_height: float = Field(default=40.0)
    rx_height: float = Field(default=1.5)
    area_m: float = Field(default=512.0, gt=0.0)
    pixel_size_m: Literal[1, 2, 4] = Field(default=4)


class SINRMapRequest(BaseSionnaRequest):
    sinr_vmin: float = Field(default=-20.0)
    sinr_vmax: float = Field(default=40.0)
    cell_size: float = Field(default=2.0)
    samples_per_tx: int = Field(default=1000000)


class CaptureStartRequest(BaseModel):
    usrp_mode: Literal["test", "usrp"] = "test"
    scene: str = "NTPU"
    map_type: Literal["sinr", "iss", "tss", "cfar"] = "iss"


class GpsSyncPointRequest(BaseModel):
    mission_id: str
    time_stamp: str
    lat: float
    lon: float
    alt: float = 0.0
    alt_mode: str = "relative"
    device_id: str = "align-m4p-top-aircraft"
    device_name: str = "M4P TOP Aircraft"
    device_type: str = "uav"


def _safe_incoming_bundle_id(mission_id: str) -> str:
    bundle_id = mission_id.strip()
    if not bundle_id:
        raise ValueError("mission_id is required")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", bundle_id):
        raise ValueError("mission_id may only contain letters, numbers, underscore, dash, and dot")
    return bundle_id


def _append_gps_sync_log(bundle_dir: Path, line: str) -> None:
    log_path = bundle_dir / "gps_sync.log"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def _tail_text_file(path: Path, limit: int) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-max(1, min(limit, 500)):]


def _incoming_mission_summary(bundle_dir: Path) -> dict[str, Any] | None:
    if not bundle_dir.is_dir():
        return None
    gps_path = bundle_dir / "gps.csv"
    noise_path = bundle_dir / "noise.csv"
    log_path = bundle_dir / "gps_sync.log"
    if not (gps_path.exists() or noise_path.exists() or log_path.exists()):
        return None

    mtimes = [
        path.stat().st_mtime
        for path in (gps_path, noise_path, log_path)
        if path.exists()
    ]
    latest_mtime = max(mtimes) if mtimes else bundle_dir.stat().st_mtime
    gps_lines = _tail_text_file(gps_path, 2)
    log_lines = _tail_text_file(log_path, 1)
    return {
        "mission_id": bundle_dir.name,
        "updated_at": datetime.fromtimestamp(latest_mtime).isoformat(),
        "has_gps": gps_path.exists(),
        "has_noise": noise_path.exists(),
        "gps_size": gps_path.stat().st_size if gps_path.exists() else 0,
        "noise_size": noise_path.stat().st_size if noise_path.exists() else 0,
        "last_gps_row": gps_lines[-1] if len(gps_lines) > 1 else "",
        "last_log": log_lines[-1] if log_lines else "",
    }


def _coerce_iss_unet_pixel_size(value: Any) -> int:
    if isinstance(value, (int, float, str)):
        try:
            pixel_size = int(value)
        except (TypeError, ValueError):
            return 4
        return pixel_size if pixel_size in {1, 2, 4} else 4
    return 4


def _device_power_dbm(device: DeviceIn) -> Optional[float]:
    if device.power_dbm is not None:
        return device.power_dbm
    return DEFAULT_POWER_DBM_BY_ROLE.get(device.role)


@app.get("/api/iss-unet/status")
async def iss_unet_status_get():
    from app.iss_unet_service import iss_unet_status

    return iss_unet_status()


@app.get("/api/iss-unet/dataset/status")
async def iss_unet_dataset_status_get(scene: str = Query(...), pixel_size_m: Literal[1, 2, 4] = Query(4)):
    from app.iss_unet_service import resolve_scene_dataset

    pixel_size_m = _coerce_iss_unet_pixel_size(pixel_size_m)
    dataset = resolve_scene_dataset(scene, scene_dir=SCENE_DIR, pixel_size_m=pixel_size_m)
    return {
        "success": True,
        "scene": dataset.scene,
        "available": dataset.available,
        "data_dir": str(dataset.data_dir),
        "missing_files": dataset.missing_files,
        "meta_available": dataset.meta_path is not None,
        "grid_res": dataset.grid_res,
        "pixel_size_m": dataset.pixel_size_m,
    }


@app.post("/api/iss-unet/dataset/prepare")
async def iss_unet_dataset_prepare_post(req: ISSUNetDatasetPrepareRequest):
    from app.iss_unet_dataset_service import SceneUnavailableError, prepare_iss_unet_dataset

    try:
        result = await asyncio.to_thread(
            prepare_iss_unet_dataset,
            scene=req.scene,
            scene_dir=SCENE_DIR,
            bs_pos=req.bs_pos,
            jammer_positions=req.jammer_positions,
            jammer_powers=req.jammer_powers,
            bs_power=req.bs_power,
            bs_height=req.bs_height,
            jammer_height=req.jammer_height,
            rx_height=req.rx_height,
            area_m=req.area_m,
            pixel_size_m=req.pixel_size_m,
        )
        return result
    except SceneUnavailableError as exc:
        return JSONResponse(
            {
                "success": False,
                "error": str(exc),
                "error_type": "scene_unavailable",
            },
            status_code=404,
        )
    except ImportError as exc:
        return JSONResponse(
            {
                "success": False,
                "error": str(exc),
                "error_type": "iss_unet_dependency_missing",
            },
            status_code=503,
        )
    except Exception as exc:
        logger.exception("ISS_UNET dataset preparation failed")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.post("/api/iss-unet/reconstruct")
async def iss_unet_reconstruct_post(req: ISSUNetReconstructRequest):
    from app.iss_unet_service import ISSUNetCFARParams, reconstruct_iss_unet, resolve_scene_dataset

    dataset = resolve_scene_dataset(req.scene, scene_dir=SCENE_DIR, pixel_size_m=req.pixel_size_m)
    if not dataset.available:
        return JSONResponse(
            {
                "success": False,
                "error": "ISS_UNET dataset is missing for this scene",
                "scene": dataset.scene,
                "data_dir": str(dataset.data_dir),
                "missing_files": dataset.missing_files,
            },
            status_code=409,
        )

    cfar_params = ISSUNetCFARParams(
        enabled=req.cfar.enabled,
        guard_cells=req.cfar.guard_cells,
        training_cells=req.cfar.training_cells,
        pfa=req.cfar.pfa,
        os_rank=req.cfar.os_rank,
        min_threshold_dbm=req.cfar.min_threshold_dbm,
    )

    try:
        scene_xml = _resolve_sionna_scene_xml(req.scene) if req.devices else None
        result = await asyncio.to_thread(
            reconstruct_iss_unet,
            scene=req.scene,
            sparse_ratio=req.sparse_ratio,
            cfar=cfar_params,
            seed=req.seed,
            mode="sim",
            apply_building_mask=req.apply_building_mask,
            scene_dir=SCENE_DIR,
            devices=req.devices,
            scene_xml_path=scene_xml,
            pixel_size_m=req.pixel_size_m,
        )
        logger.info(
            "ISS_UNET completed scene=%s mode=%s aligned_noise=%s skipped_noise=%s used_samples=%s sparse_samples=%s apply_building_mask=%s",
            result.get("scene"),
            result.get("mode"),
            result.get("metrics", {}).get("aligned_noise"),
            result.get("metrics", {}).get("skipped_noise"),
            result.get("metrics", {}).get("used_samples"),
            result.get("metrics", {}).get("sparse_samples"),
            result.get("options", {}).get("apply_building_mask"),
        )
        return {"success": True, **result}
    except FileNotFoundError as exc:
        return JSONResponse(
            {
                "success": False,
                "error": str(exc),
                "error_type": "iss_unet_artifact_missing",
            },
            status_code=503,
        )
    except ImportError as exc:
        return JSONResponse(
            {
                "success": False,
                "error": str(exc),
                "error_type": "iss_unet_dependency_missing",
            },
            status_code=503,
        )
    except Exception as exc:
        logger.exception("ISS_UNET reconstruction failed")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.post("/api/iss-unet/reconstruct/upload")
async def iss_unet_reconstruct_upload_post(
    scene: str = Form(...),
    mode: Literal["sim", "gps", "gps_n"] = Form("sim"),
    sparse_ratio: float = Form(0.2),
    pixel_size_m: int = Form(4),
    seed: int = Form(41),
    cfar_enabled: bool = Form(True),
    apply_building_mask: bool = Form(True),
    filter_noise: bool = Form(True),
    devices_json: str = Form(""),
    gps_file: UploadFile | None = File(None),
    noise_file: UploadFile | None = File(None),
):
    from app.iss_unet_service import ISSUNetCFARParams, reconstruct_iss_unet, resolve_scene_dataset

    pixel_size_m = _coerce_iss_unet_pixel_size(pixel_size_m)
    dataset = resolve_scene_dataset(scene, scene_dir=SCENE_DIR, pixel_size_m=pixel_size_m)
    if not dataset.available:
        return JSONResponse(
            {
                "success": False,
                "error": "ISS_UNET dataset is missing for this scene",
                "scene": dataset.scene,
                "data_dir": str(dataset.data_dir),
                "missing_files": dataset.missing_files,
            },
            status_code=409,
        )

    gps_csv = await gps_file.read() if gps_file is not None else None
    noise_csv = await noise_file.read() if noise_file is not None else None
    devices_json_text = devices_json if isinstance(devices_json, str) else ""
    try:
        raw_devices = json.loads(devices_json_text) if devices_json_text.strip() else []
        devices = [DeviceIn.model_validate(device) for device in raw_devices]
    except json.JSONDecodeError as exc:
        return JSONResponse({"success": False, "error": f"devices_json is invalid JSON: {exc}"}, status_code=422)
    except Exception as exc:
        return JSONResponse({"success": False, "error": f"devices_json is invalid: {exc}"}, status_code=422)
    cfar_params = ISSUNetCFARParams(enabled=cfar_enabled)
    try:
        scene_xml = _resolve_sionna_scene_xml(scene) if devices else None
        result = await asyncio.to_thread(
            reconstruct_iss_unet,
            scene=scene,
            sparse_ratio=sparse_ratio,
            cfar=cfar_params,
            seed=seed,
            mode=mode,
            gps_csv=gps_csv,
            noise_csv=noise_csv,
            apply_building_mask=apply_building_mask,
            filter_noise=filter_noise,
            scene_dir=SCENE_DIR,
            devices=devices,
            scene_xml_path=scene_xml,
            pixel_size_m=pixel_size_m,
        )
        logger.info(
            "ISS_UNET upload completed scene=%s mode=%s aligned_noise=%s skipped_noise=%s used_samples=%s sparse_samples=%s apply_building_mask=%s",
            result.get("scene"),
            result.get("mode"),
            result.get("metrics", {}).get("aligned_noise"),
            result.get("metrics", {}).get("skipped_noise"),
            result.get("metrics", {}).get("used_samples"),
            result.get("metrics", {}).get("sparse_samples"),
            result.get("options", {}).get("apply_building_mask"),
        )
        return {"success": True, **result}
    except ValueError as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=422)
    except FileNotFoundError as exc:
        return JSONResponse(
            {
                "success": False,
                "error": str(exc),
                "error_type": "iss_unet_artifact_missing",
            },
            status_code=503,
        )
    except ImportError as exc:
        return JSONResponse(
            {
                "success": False,
                "error": str(exc),
                "error_type": "iss_unet_dependency_missing",
            },
            status_code=503,
        )
    except Exception as exc:
        logger.exception("ISS_UNET upload reconstruction failed")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.post("/api/iss-unet/statistics/upload")
async def iss_unet_statistics_upload_post(
    scene: str = Form(...),
    pixel_size_m: int = Form(4),
    apply_building_mask: bool = Form(True),
    filter_noise: bool = Form(True),
    devices_json: str = Form(""),
    gps_file: UploadFile | None = File(None),
    noise_file: UploadFile | None = File(None),
):
    from app.iss_unet_service import ISSUNetCFARParams, resolve_scene_dataset
    from app.iss_unet_stats_service import generate_gpsn_statistics

    pixel_size_m = _coerce_iss_unet_pixel_size(pixel_size_m)
    dataset = resolve_scene_dataset(scene, scene_dir=SCENE_DIR, pixel_size_m=pixel_size_m)
    if not dataset.available:
        return JSONResponse(
            {
                "success": False,
                "error": "ISS_UNET dataset is missing for this scene",
                "scene": dataset.scene,
                "data_dir": str(dataset.data_dir),
                "missing_files": dataset.missing_files,
            },
            status_code=409,
        )

    gps_csv = await gps_file.read() if gps_file is not None else None
    noise_csv = await noise_file.read() if noise_file is not None else None
    devices_json_text = devices_json if isinstance(devices_json, str) else ""
    try:
        raw_devices = json.loads(devices_json_text) if devices_json_text.strip() else []
        devices = [DeviceIn.model_validate(device) for device in raw_devices]
    except json.JSONDecodeError as exc:
        return JSONResponse({"success": False, "error": f"devices_json is invalid JSON: {exc}"}, status_code=422)
    except Exception as exc:
        return JSONResponse({"success": False, "error": f"devices_json is invalid: {exc}"}, status_code=422)

    try:
        scene_xml = _resolve_sionna_scene_xml(scene) if devices else None
        result = await asyncio.to_thread(
            generate_gpsn_statistics,
            scene=scene,
            cfar=ISSUNetCFARParams(enabled=True),
            mode="gps_n",
            gps_csv=gps_csv,
            noise_csv=noise_csv,
            apply_building_mask=apply_building_mask,
            filter_noise=filter_noise,
            scene_dir=SCENE_DIR,
            devices=devices,
            scene_xml_path=scene_xml,
            pixel_size_m=pixel_size_m,
        )
        return {"success": True, **result}
    except ValueError as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=422)
    except FileNotFoundError as exc:
        return JSONResponse({"success": False, "error": str(exc), "error_type": "iss_unet_artifact_missing"}, status_code=503)
    except ImportError as exc:
        return JSONResponse({"success": False, "error": str(exc), "error_type": "iss_unet_dependency_missing"}, status_code=503)
    except Exception as exc:
        logger.exception("ISS_UNET statistics generation failed")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


def _capture_error(exc: Exception):
    if isinstance(exc, CaptureNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, CaptureConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, CapturePreflightError):
        raise HTTPException(
            status_code=409 if exc.conflicts and len(exc.conflicts) == len(exc.errors) else 503,
            detail={
                "error_type": "capture_preflight_failed",
                "message": str(exc),
                "errors": dict(exc.errors),
                "preflight_errors": dict(exc.errors),
                "conflicts": dict(exc.conflicts),
                "devices": [
                    {"device": device, "error": message}
                    for device, message in exc.errors.items()
                ],
            },
        ) from exc
    if isinstance(exc, CaptureUnavailableError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    raise exc


async def _capture_call(fn, *args, **kwargs):
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), timeout=30)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail='capture operation timed out; status is being reconciled') from exc


@app.get("/api/capture/status")
async def capture_status_get(usrp_mode: Literal["test", "usrp"] = Query("test")):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(capture_coordinator.status_payload, usrp_mode),
            timeout=30,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="capture status timed out; state is being reconciled",
        ) from exc
    except Exception as exc:
        _capture_error(exc)


@app.get("/api/capture/health")
async def capture_health_get(usrp_mode: Literal["test", "usrp"] = Query("test")):
    """Return mission-independent AP3/Raspberry Pi readiness."""
    try:
        return {
            "device_health": await asyncio.wait_for(
                asyncio.to_thread(capture_coordinator.health_status, usrp_mode),
                timeout=15,
            ),
        }
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="device health probe timed out") from exc
    except Exception as exc:
        _capture_error(exc)


@app.post("/api/capture/uav/start")
async def capture_uav_start_post():
    try:
        return await _capture_call(capture_coordinator.start_uav)
    except Exception as exc:
        _capture_error(exc)


@app.post("/api/capture/uav/stop")
async def capture_uav_stop_post(mission_id: str = Query(...)):
    try:
        return await _capture_call(capture_coordinator.stop_uav, mission_id)
    except Exception as exc:
        _capture_error(exc)


@app.post("/api/capture/usrp/start")
async def capture_usrp_start_post(req: CaptureStartRequest):
    try:
        return await _capture_call(
            capture_coordinator.start_usrp,
            req.usrp_mode,
            scene=req.scene,
            map_type=req.map_type,
        )
    except Exception as exc:
        _capture_error(exc)


@app.post("/api/capture/usrp/upload/retry")
async def capture_usrp_retry_upload_post(mission_id: str = Query(...), background_tasks: BackgroundTasks = None):
    try:
        if background_tasks is not None:
            background_tasks.add_task(capture_coordinator.retry_usrp_upload, mission_id)
            return await _capture_call(capture_coordinator.store.load, mission_id)
        return await _capture_call(capture_coordinator.retry_usrp_upload, mission_id)
    except Exception as exc:
        _capture_error(exc)


@app.post("/api/capture/usrp/stop")
async def capture_usrp_stop_post(mission_id: str = Query(...), background_tasks: BackgroundTasks = None):
    try:
        result = await _capture_call(capture_coordinator.stop_usrp, mission_id)
        if background_tasks is not None and result.usrp.file == "upload_pending":
            background_tasks.add_task(capture_coordinator.retry_usrp_upload, mission_id)
        return result
    except Exception as exc:
        _capture_error(exc)


@app.post("/api/capture/bind/start")
async def capture_bind_start_post(req: CaptureStartRequest):
    try:
        return await _capture_call(
            capture_coordinator.start_bind,
            req.usrp_mode,
            scene=req.scene,
            map_type=req.map_type,
        )
    except Exception as exc:
        _capture_error(exc)


@app.post("/api/capture/bind/stop")
async def capture_bind_stop_post(mission_id: str = Query(...)):
    try:
        return await _capture_call(capture_coordinator.stop_bind, mission_id)
    except Exception as exc:
        _capture_error(exc)


def _usrp_sampling_error_response(exc: Exception, mode: Literal["test", "usrp"] = "test") -> JSONResponse:
    message = str(exc)
    password = os.environ.get("RASPI_PSW", "")
    if password:
        message = message.replace(password, "[redacted]")
    service_name = "drone.service" if mode == "usrp" else "drone_test.service"
    return JSONResponse(
        {
            "success": False,
            "raspi_connected": False,
            "session_connected": False,
            "mode": mode,
            "service_name": service_name,
            "service_state": "unknown",
            "message": message or "RasPi sampling control failed",
            "service_messages": [],
        },
        status_code=503,
    )


@app.get("/api/usrp/sampling/status")
async def usrp_sampling_status_get(mode: Literal["test", "usrp"] = Query("test")):
    try:
        from app import usrp_ctl

        return await asyncio.to_thread(usrp_ctl.get_drone_status, mode)
    except Exception as exc:
        return _usrp_sampling_error_response(exc, mode)


@app.post("/api/usrp/sampling/connect")
async def usrp_sampling_connect_post(mode: Literal["test", "usrp"] = Query("test")):
    try:
        from app import usrp_ctl

        result = await asyncio.to_thread(usrp_ctl.connect_raspi, mode)
        return {**result, "deprecated": True}
    except Exception as exc:
        return _usrp_sampling_error_response(exc, mode)


@app.post("/api/usrp/sampling/disconnect")
async def usrp_sampling_disconnect_post():
    try:
        from app import usrp_ctl

        result = await asyncio.to_thread(usrp_ctl.disconnect_raspi)
        return {**result, "deprecated": True}
    except Exception as exc:
        return _usrp_sampling_error_response(exc)


@app.get("/api/usrp/sampling/messages")
async def usrp_sampling_messages_get(mode: Literal["test", "usrp"] = Query("test")):
    try:
        from app import usrp_ctl

        result = await asyncio.to_thread(usrp_ctl.get_drone_messages, mode)
        return {**result, "deprecated": True}
    except Exception as exc:
        return _usrp_sampling_error_response(exc, mode)


@app.post("/api/usrp/sampling/start")
async def usrp_sampling_start_post(mode: Literal["test", "usrp"] = Query("test")):
    try:
        from app import usrp_ctl

        return await asyncio.to_thread(usrp_ctl.start_drone_service, mode)
    except Exception as exc:
        return _usrp_sampling_error_response(exc, mode)


@app.post("/api/usrp/sampling/stop")
async def usrp_sampling_stop_post(mode: Literal["test", "usrp"] = Query("test")):
    try:
        from app import usrp_ctl

        return await asyncio.to_thread(usrp_ctl.stop_drone_service, mode)
    except Exception as exc:
        return _usrp_sampling_error_response(exc, mode)


def _merge_bundle_metadata(bundle_dir: Path, updates: dict[str, Any]) -> dict[str, Any]:
    metadata_path = bundle_dir / "bundle.json"
    existing: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            existing = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    merged = {**existing, **updates}
    metadata_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


@app.post("/api/usrp/upload-gps-csv")
async def usrp_upload_gps_csv_post(
    scene: str = Form("NTPU"),
    mission_id: str = Form(""),
    map_type: Literal["sinr", "iss", "tss", "cfar"] = Form("iss"),
    auto_simulate_last: bool = Form(True),
    device_id: str = Form("align-m4p-top-aircraft"),
    device_name: str = Form("M4P TOP Aircraft"),
    device_type: str = Form("uav"),
    role: Literal["rx", "tx", "jammer"] = Form("rx"),
    devices_json: str = Form(""),
    gps_file: UploadFile = File(...),
):
    if not gps_file.filename:
        return JSONResponse({"success": False, "error": "gps_file filename is required"}, status_code=422)

    gps_data = await gps_file.read()
    try:
        validate_gps_csv_bytes(gps_data)
    except GpsCsvSchemaError as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=422)

    bundle_id = mission_id.strip() or f"mission_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    bundle_dir = INCOMING_CSV_DIR / bundle_id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "gps.csv").write_bytes(gps_data)

    updates: dict[str, Any] = {
        "scene": scene,
        "mission_id": bundle_id,
        "map_type": map_type,
        "auto_simulate_last": auto_simulate_last,
        "device_id": device_id,
        "device_name": device_name,
        "device_type": device_type,
        "role": role,
        "received_gps_at": datetime.now().isoformat(),
        "gps_filename": gps_file.filename,
    }
    devices_payload = devices_json if isinstance(devices_json, str) else ""
    if devices_payload.strip():
        try:
            updates["devices"] = json.loads(devices_payload)
        except json.JSONDecodeError as exc:
            return JSONResponse({"success": False, "error": f"devices_json is invalid JSON: {exc}"}, status_code=422)

    metadata = _merge_bundle_metadata(bundle_dir, updates)
    return {
        "success": True,
        "mission_id": bundle_id,
        "bundle_dir": str(bundle_dir),
        "watch_dir": str(INCOMING_CSV_DIR),
        "metadata": metadata,
    }


@app.post("/api/usrp/sync-gps-point")
async def usrp_sync_gps_point_post(point: GpsSyncPointRequest):
    try:
        bundle_id = _safe_incoming_bundle_id(point.mission_id)
    except ValueError as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=422)
    if not (
        math.isfinite(point.lat)
        and math.isfinite(point.lon)
        and math.isfinite(point.alt)
    ):
        return JSONResponse({"success": False, "error": "lat, lon, and alt must be finite numbers"}, status_code=422)

    bundle_dir = INCOMING_CSV_DIR / bundle_id
    csv_path = bundle_dir / "gps.csv"
    payload = {
        "type": "gps",
        "deviceId": point.device_id,
        "deviceName": point.device_name,
        "deviceType": point.device_type,
        "lat": point.lat,
        "lon": point.lon,
        "alt": point.alt,
        "timestamp": point.time_stamp,
        "missionId": bundle_id,
    }

    with GPS_SYNC_LOCK:
        try:
            append_gps_row(
                csv_path,
                [point.time_stamp, point.lat, point.lon, point.alt, point.alt_mode],
            )
        except GpsCsvSchemaError as exc:
            return JSONResponse({"success": False, "error": str(exc)}, status_code=422)
        log_line = (
            f"{datetime.now().isoformat()} mission={bundle_id} "
            f"device={point.device_id} lat={point.lat:.7f} lon={point.lon:.7f} alt={point.alt:.2f}"
        )
        _append_gps_sync_log(bundle_dir, log_line)

    # Keep managed AP3 mission metadata in the coordinator's atomic state
    # store.  GPS sync also supports standalone incoming bundles, so a missing
    # capture mission is intentionally harmless.
    try:
        await asyncio.to_thread(
            capture_coordinator.record_gps_sample,
            bundle_id,
            point.time_stamp,
        )
    except Exception as exc:
        logger.warning("GPS sample persisted to CSV but mission freshness update failed: %s", exc)

    gps_manager.names[point.device_id] = point.device_name
    gps_manager.update_gps(point.device_id, payload)
    await gps_manager.broadcast(json.dumps(payload, ensure_ascii=False))
    logger.info("GPS sync point received: %s", log_line)

    return {
        "success": True,
        "mission_id": bundle_id,
        "gps_csv": str(csv_path),
        "log": log_line,
    }


@app.get("/api/usrp/gps-sync/logs")
async def usrp_gps_sync_logs_get(
    mission_id: str = Query(...),
    limit: int = Query(100, ge=1, le=500),
):
    try:
        bundle_id = _safe_incoming_bundle_id(mission_id)
    except ValueError as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=422)

    bundle_dir = INCOMING_CSV_DIR / bundle_id
    csv_path = bundle_dir / "gps.csv"
    log_path = bundle_dir / "gps_sync.log"
    lines = _tail_text_file(log_path, limit)
    return {
        "success": True,
        "mission_id": bundle_id,
        "gps_csv": str(csv_path),
        "log_path": str(log_path),
        "lines": lines,
        "count": len(lines),
    }


@app.get("/api/usrp/gps-sync/missions")
async def usrp_gps_sync_missions_get(limit: int = Query(20, ge=1, le=200)):
    missions = [
        summary
        for summary in (
            _incoming_mission_summary(path)
            for path in INCOMING_CSV_DIR.iterdir()
        )
        if summary is not None
    ]
    missions.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return {
        "success": True,
        "missions": missions[:limit],
        "count": min(len(missions), limit),
        "total": len(missions),
    }


@app.post("/api/usrp/upload-noise-csv")
async def usrp_upload_noise_csv_post(
    scene: str = Form("NTPU"),
    mission_id: str = Form(""),
    map_type: Literal["sinr", "iss", "tss", "cfar"] = Form("iss"),
    auto_simulate_last: bool = Form(True),
    device_id: str = Form("usrp-b210-sensor"),
    device_name: str = Form("USRP B210 Sensor"),
    device_type: str = Form("uav"),
    role: Literal["rx", "tx", "jammer"] = Form("rx"),
    devices_json: str = Form(""),
    noise_size: int = Form(...),
    noise_sha256: str = Form(...),
    noise_file: UploadFile = File(...),
):
    scene_value = scene if isinstance(scene, str) else "NTPU"
    mission_id_value = mission_id if isinstance(mission_id, str) else ""
    map_type_value = map_type if isinstance(map_type, str) else "iss"
    auto_simulate_last_value = (
        auto_simulate_last if isinstance(auto_simulate_last, bool) else True
    )
    device_id_value = device_id if isinstance(device_id, str) else "usrp-b210-sensor"
    device_name_value = (
        device_name if isinstance(device_name, str) else "USRP B210 Sensor"
    )
    device_type_value = device_type if isinstance(device_type, str) else "uav"
    role_value = role if isinstance(role, str) else "rx"
    devices_payload = devices_json if isinstance(devices_json, str) else ""

    if not noise_file.filename:
        return JSONResponse({"success": False, "error": "noise_file filename is required"}, status_code=422)

    bundle_id = mission_id_value.strip()
    if not bundle_id:
        return JSONResponse({"success": False, "error": "mission_id is required"}, status_code=422)
    noise_bytes = await noise_file.read()
    actual_sha256 = hashlib.sha256(noise_bytes).hexdigest()
    if noise_size != len(noise_bytes) or noise_sha256.lower() != actual_sha256:
        return JSONResponse(
            {
                "success": False,
                "error": "noise file size or sha256 mismatch",
                "actual_size": len(noise_bytes),
                "actual_sha256": actual_sha256,
            },
            status_code=422,
        )
    bundle_dir = INCOMING_CSV_DIR / bundle_id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    noise_path = bundle_dir / "noise.csv"
    temp_path = noise_path.with_suffix(".csv.tmp")
    temp_path.write_bytes(noise_bytes)
    temp_path.replace(noise_path)

    updates: dict[str, Any] = {
        "scene": scene_value,
        "mission_id": bundle_id,
        "map_type": map_type_value,
        "auto_simulate_last": auto_simulate_last_value,
        "device_id": device_id_value,
        "device_name": device_name_value,
        "device_type": device_type_value,
        "role": role_value,
        "received_noise_at": datetime.now().isoformat(),
        "noise_filename": noise_file.filename,
    }
    if devices_payload.strip():
        try:
            updates["devices"] = json.loads(devices_payload)
        except json.JSONDecodeError as exc:
            return JSONResponse({"success": False, "error": f"devices_json is invalid JSON: {exc}"}, status_code=422)

    metadata = _merge_bundle_metadata(bundle_dir, updates)
    capture = None
    try:
        capture = capture_coordinator.ack_noise_upload(
            bundle_id,
            path=noise_path,
            size=len(noise_bytes),
            sha256=actual_sha256,
        )
    except CaptureNotFoundError:
        pass
    return {
        "success": True,
        "mission_id": bundle_id,
        "bundle_dir": str(bundle_dir),
        "watch_dir": str(INCOMING_CSV_DIR),
        "metadata": metadata,
        "capture": capture.model_dump() if capture is not None else None,
    }


@app.get("/api/iss-unet/maps/{scene}/{filename}")
@app.get("/api/iss-unet/images/{filename}")
async def iss_unet_image_get(filename: str, scene: str | None = None):
    from app.iss_unet_service import output_dir_for_scene, scene_id_from_result_filename

    valid_iss_unet_image = re.fullmatch(
        r"iss_unet_[A-Za-z0-9_-]+(?:_res(?:128|256|512))?(?:(?:_ratio_[0-9]+(?:p[0-9]+)?)|(?:_gps(?:_n)?))?_(?:reconstructed|comparison|cfar|statistics)\.png",
        filename,
    )
    if "/" in filename or "\\" in filename or not valid_iss_unet_image:
        return JSONResponse({"success": False, "error": "Image not found"}, status_code=404)

    image_path = output_dir_for_scene(scene or scene_id_from_result_filename(filename)) / filename
    if not image_path.exists():
        return JSONResponse({"success": False, "error": "Image not found"}, status_code=404)

    return FileResponse(image_path, media_type="image/png", filename=filename)


@app.get("/api/iss-unet/maps/{scene}/grids/{filename}")
@app.get("/api/iss-unet/grids/{filename}")
async def iss_unet_grid_get(filename: str, scene: str | None = None):
    from app.iss_unet_service import DEFAULT_SCENE_AREA_M, output_dir_for_scene, scene_id_from_result_filename

    valid_grid = re.fullmatch(
        r"iss_unet_[A-Za-z0-9_-]+(?:_res(?:128|256|512))?(?:(?:_ratio_[0-9]+(?:p[0-9]+)?)|(?:_gps(?:_n)?))?_reconstructed\.npy",
        filename,
    )
    if "/" in filename or "\\" in filename or not valid_grid:
        return JSONResponse({"success": False, "error": "Grid not found"}, status_code=404)

    scene_name = (scene or scene_id_from_result_filename(filename)).lower()
    grid_path = output_dir_for_scene(scene_name) / filename
    if not grid_path.exists():
        return JSONResponse({"success": False, "error": "Grid not found"}, status_code=404)

    try:
        values = np.load(grid_path).astype(np.float32)
    except Exception:
        return JSONResponse({"success": False, "error": "Grid not found"}, status_code=404)

    if values.ndim != 2:
        return JSONResponse({"success": False, "error": "Grid not found"}, status_code=404)

    scene_match = re.match(
        r"iss_unet_([A-Za-z0-9_-]+?)(?:_res(?:128|256|512))?(?:(?:_ratio_[0-9]+(?:p[0-9]+)?)|(?:_gps(?:_n)?))?_reconstructed\.npy",
        filename,
    )
    scene_name = scene.upper() if scene else (scene_match.group(1).upper() if scene_match else "")
    scene_meta_path = SCENE_DIR / scene_name / "iss_unet_data" / "scene_meta.json"
    area_m = DEFAULT_SCENE_AREA_M
    if scene_meta_path.exists():
        try:
            meta = json.loads(scene_meta_path.read_text(encoding="utf-8"))
            parsed_area = float(meta.get("area_m", DEFAULT_SCENE_AREA_M))
            if np.isfinite(parsed_area) and parsed_area > 0:
                area_m = parsed_area
        except Exception:
            area_m = DEFAULT_SCENE_AREA_M

    return {
        "success": True,
        "rows": int(values.shape[0]),
        "cols": int(values.shape[1]),
        "area_m": float(area_m),
        "min_dbm": float(np.min(values)),
        "max_dbm": float(np.max(values)),
        "values": values.tolist(),
    }


class CFRAdvancedParams(BaseModel):
    constellation_batch_size: int = Field(default=1, ge=1, le=100)
    ofdm_subcarriers: int = Field(default=76, ge=16, le=1024)
    subcarrier_spacing_hz: float = Field(default=30000.0, ge=1000.0, le=240000.0)
    ebn0_db: float = Field(default=20.0, ge=0.0, le=60.0)
    ray_tracing_max_depth: int = Field(default=10, ge=1, le=10)


class CFRPlotRequest(BaseModel):
    scene: str
    modulation: Literal["qpsk", "16qam"] = "qpsk"
    devices: List[DeviceIn]
    advanced: CFRAdvancedParams = Field(default_factory=CFRAdvancedParams)


def _resolve_scene_name(scene: str) -> str:
    scene_id = scene.strip()
    if not scene_id:
        raise HTTPException(status_code=422, detail="scene is required")
    if any(part in scene_id for part in ("/", "\\", "..")):
        raise HTTPException(status_code=422, detail=f"Invalid scene id: {scene_id}")

    return BUILTIN_SCENE_NAMES.get(scene_id.lower(), scene_id.upper())


def _resolve_sionna_scene_xml(scene: str) -> Path:
    scene_name = _resolve_scene_name(scene)
    scene_xml = BASE_DIR / "static" / "scenes" / scene_name / f"{scene_name}.xml"
    if not scene_xml.exists():
        raise HTTPException(status_code=404, detail=f"Scene XML not found: {scene_xml}")
    return scene_xml


def _sionna_device_config(devices: List[DeviceIn]) -> tuple[List[tuple], tuple]:
    rx_devices = [d for d in devices if d.role == "rx"]
    tx_devices = [d for d in devices if d.role == "tx"]
    jammer_devices = [d for d in devices if d.role == "jammer"]

    if not rx_devices:
        raise HTTPException(status_code=422, detail="CFR requires one RX device")
    if not tx_devices:
        raise HTTPException(status_code=422, detail="CFR requires at least one TX device")

    tx_list = []
    for d in tx_devices:
        power_dbm = _device_power_dbm(d)
        position = enu_to_sionna(d.enu.east_m, d.enu.north_m, d.enu.up_m)
        tx_list.append((
            d.name,
            list(position),
            [0.0, 0.0, 0.0],
            "desired",
            power_dbm if power_dbm is not None else DEFAULT_POWER_DBM_BY_ROLE["tx"],
        ))
    for d in jammer_devices:
        power_dbm = _device_power_dbm(d)
        position = enu_to_sionna(d.enu.east_m, d.enu.north_m, d.enu.up_m)
        tx_list.append((
            d.name,
            list(position),
            [0.0, 0.0, 0.0],
            "jammer",
            power_dbm if power_dbm is not None else DEFAULT_POWER_DBM_BY_ROLE["jammer"],
        ))

    rx = rx_devices[0]
    return tx_list, (rx.name, list(enu_to_sionna(rx.enu.east_m, rx.enu.north_m, rx.enu.up_m)))


@app.post("/api/sionna/cfr-plot")
async def sionna_cfr_plot_post(req: CFRPlotRequest):
    """Generate CFR plot using current scene/devices and modulation."""
    try:
        from app.sionna_service import generate_cfr_plot, output_path_for_scene

        scene_xml = _resolve_sionna_scene_xml(req.scene)
        scene_xml_path = Path(scene_xml)
        scene_name = scene_xml_path.parent.name
        output_path = output_path_for_scene(scene_name, "cfr_plot.png")
        tx_list, rx_config = _sionna_device_config(req.devices)
        advanced = req.advanced
        await generate_cfr_plot(
            scene_xml=str(scene_xml_path),
            scene_name=scene_name,
            output_path=output_path,
            tx_list=tx_list,
            rx_config=rx_config,
            modulation=req.modulation,
            constellation_batch_size=advanced.constellation_batch_size,
            ofdm_subcarriers=advanced.ofdm_subcarriers,
            subcarrier_spacing_hz=advanced.subcarrier_spacing_hz,
            ebn0_db=advanced.ebn0_db,
            ray_tracing_max_depth=advanced.ray_tracing_max_depth,
        )
        if not os.path.isfile(output_path):
            return JSONResponse({"error": "CFR plot generation failed; see server logs"}, status_code=500)
        return FileResponse(output_path, media_type="image/png", filename="cfr_plot.png")
    except HTTPException:
        raise
    except SionnaLLVMError as e:
        return _sionna_llvm_error_response("cfr-plot", e)
    except ImportError:
        return JSONResponse({"error": "Sionna ?芸?鋆?隢??瑁? pip install sionna"}, status_code=503)
    except Exception as e:
        logger.exception("CFR plot error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/sionna/sinr-map")
async def sionna_sinr_map_post(req: SINRMapRequest):
    try:
        from app.sionna_service import generate_sinr_map, output_path_for_scene

        scene_xml = _resolve_sionna_scene_xml(req.scene)
        scene_name = scene_xml.parent.name
        output_path = output_path_for_scene(scene_name, "sinr_map.png")
        tx_list, rx_config = _sionna_device_config(req.devices)

        await generate_sinr_map(
            tx_list=tx_list,
            rx_config=rx_config,
            scene_xml=str(scene_xml),
            scene_name=scene_name,
            output_path=output_path,
            sinr_vmin=req.sinr_vmin,
            sinr_vmax=req.sinr_vmax,
            cell_size=req.cell_size,
            samples_per_tx=req.samples_per_tx,
        )
        if not os.path.isfile(output_path):
            return JSONResponse({"error": "SINR map generation failed; see server logs"}, status_code=500)
        return FileResponse(output_path, media_type="image/png", filename="sinr_map.png")
    except HTTPException:
        raise
    except SionnaLLVMError as e:
        return _sionna_llvm_error_response("sinr-map", e)
    except ImportError:
        return JSONResponse({"error": "Sionna 未安裝，請先執行 pip install sionna"}, status_code=503)
    except Exception as e:
        logger.exception("SINR map error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/sionna/doppler")
async def sionna_doppler_post(req: BaseSionnaRequest):
    try:
        from app.sionna_service import generate_doppler_plot, output_path_for_scene

        scene_xml = _resolve_sionna_scene_xml(req.scene)
        scene_name = scene_xml.parent.name
        output_path = output_path_for_scene(scene_name, "doppler_plot.png")
        tx_list, rx_config = _sionna_device_config(req.devices)

        await generate_doppler_plot(
            tx_list=tx_list,
            rx_config=rx_config,
            scene_xml=str(scene_xml),
            scene_name=scene_name,
            output_path=output_path,
        )
        if not os.path.isfile(output_path):
            return JSONResponse({"error": "Doppler plot generation failed; see server logs"}, status_code=500)
        return FileResponse(output_path, media_type="image/png", filename="doppler_plot.png")
    except HTTPException:
        raise
    except SionnaLLVMError as e:
        return _sionna_llvm_error_response("doppler", e)
    except ImportError:
        return JSONResponse({"error": "Sionna 未安裝，請先執行 pip install sionna"}, status_code=503)
    except Exception as e:
        logger.exception("Doppler plot error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/sionna/channel-response")
async def sionna_channel_response_post(req: BaseSionnaRequest):
    try:
        from app.sionna_service import generate_channel_response, output_path_for_scene

        scene_xml = _resolve_sionna_scene_xml(req.scene)
        scene_name = scene_xml.parent.name
        output_path = output_path_for_scene(scene_name, "channel_response.png")
        tx_list, rx_config = _sionna_device_config(req.devices)

        await generate_channel_response(
            tx_list=tx_list,
            rx_config=rx_config,
            scene_xml=str(scene_xml),
            scene_name=scene_name,
            output_path=output_path,
        )
        if not os.path.isfile(output_path):
            return JSONResponse({"error": "Channel response generation failed; see server logs"}, status_code=500)
        return FileResponse(output_path, media_type="image/png", filename="channel_response.png")
    except HTTPException:
        raise
    except SionnaLLVMError as e:
        return _sionna_llvm_error_response("channel-response", e)
    except ImportError:
        return JSONResponse({"error": "Sionna 未安裝，請先執行 pip install sionna"}, status_code=503)
    except Exception as e:
        logger.exception("Channel response error")
        return JSONResponse({"error": str(e)}, status_code=500)


class SimulateRequest(BaseModel):
    scene: str
    map_type: str
    cell_size: float = Field(default=4.0, gt=0)
    samples_per_tx: int = Field(default=1000000, ge=10000)
    sinr_vmin: float = Field(default=-20.0)
    sinr_vmax: float = Field(default=40.0)
    overlay_scene: bool = Field(default=False)
    devices: List[DeviceIn]


@app.post("/api/simulate")
async def simulate(req: SimulateRequest):
    scene_xml = _resolve_sionna_scene_xml(req.scene)

    output_dir = str(BASE_DIR / "static" / "maps" / scene_xml.parent.name.lower())
    os.makedirs(output_dir, exist_ok=True)

    if not any(d.role == "rx" for d in req.devices):
        raise HTTPException(status_code=422, detail="At least one RX device is required.")
    if req.map_type == "sinr" and not any(d.role == "tx" for d in req.devices):
        raise HTTPException(status_code=422, detail="At least one TX device is required for a SINR map.")

    devices_dicts = []
    for d in req.devices:
        power_dbm = _device_power_dbm(d)
        device_payload = {
            "name": d.name,
            "role": d.role,
            "east_m": d.enu.east_m,
            "north_m": d.enu.north_m,
            "up_m": d.enu.up_m,
        }
        if power_dbm is not None:
            device_payload["power_dbm"] = power_dbm
        devices_dicts.append(device_payload)

    logger.info(
        "Simulation request: scene=%s, map_type=%s, devices=%d, overlay_scene=%s",
        req.scene, req.map_type, len(devices_dicts), req.overlay_scene,
    )

    try:
        loop = asyncio.get_event_loop()

        image_bytes: bytes = await loop.run_in_executor(
            None,
            _run_generate_maps,
            str(scene_xml),
            devices_dicts,
            output_dir,
            req.scene,
            req.map_type,
            req.cell_size,
            req.samples_per_tx,
            req.sinr_vmin,
            req.sinr_vmax,
            req.overlay_scene,
        )
    except Exception as exc:
        logger.exception("Simulation failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return Response(
        content=image_bytes,
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="{req.map_type}_map.png"'},
    )

def _run_generate_maps(
    scene_xml: str,
    devices: list,
    output_dir: str,
    scene_name: str,
    map_type: str,
    cell_size: float,
    samples_per_tx: int,
    sinr_vmin: float,
    sinr_vmax: float,
    overlay_scene: bool,
) -> bytes:
    from app.sionna_service_lite import generate_maps
    return generate_maps(
        scene_xml_path=scene_xml,
        devices=devices,
        output_dir=output_dir,
        scene_name=scene_name,
        map_type=map_type,
        cell_size=cell_size,
        samples_per_tx=samples_per_tx,
        sinr_vmin=sinr_vmin,
        sinr_vmax=sinr_vmax,
        overlay_scene=overlay_scene,
    )
