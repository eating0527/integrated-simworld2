import logging
import os
import json
import time
import uuid
import shutil
import subprocess
import threading

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
from typing import Dict, Optional, List, Any

from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 資料夾設定
# ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
PHOTOS_JSON = UPLOAD_DIR / "photos.json"
LOCATION_JSON = UPLOAD_DIR / "selected_locations.json"
SCENE_TASKS_JSON = UPLOAD_DIR / "scene_tasks.json"
SCENE_DIR = BASE_DIR / "static" / "scenes"
GENERATED_SCENES_DIR = SCENE_DIR / "generated"
GENERATED_SCENES_DIR.mkdir(parents=True, exist_ok=True)
SCENE_TASKS_LOCK = threading.Lock()
FIXED_GENERATION_ZOOM = 17

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
SIMULATION_OUT_DIR = BASE_DIR / "static" / "images"
SIMULATION_OUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/simulations", StaticFiles(directory=str(SIMULATION_OUT_DIR)), name="simulations")

# 靜態檔案：動態生成場景（Blender/blosm）
app.mount("/generated-scenes", StaticFiles(directory=str(SCENE_DIR)), name="generated-scenes")


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

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{ts}_{photo.filename}"
        (UPLOAD_DIR / filename).write_bytes(content)

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

    except Exception as e:
        logger.error(f"❌ 照片上傳失敗: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.get("/api/photo-history")
async def photo_history():
    photos = _load_photos()
    return {"success": True, "photos": photos, "count": len(photos)}


@app.delete("/api/delete-photo/{filename}")
async def delete_photo(filename: str):
    try:
        path = UPLOAD_DIR / filename
        if path.exists():
            path.unlink()

        photos = [p for p in _load_photos() if p.get("filename") != filename]
        _save_photos(photos)

        await gps_manager.broadcast(json.dumps({
            "type": "photo_deleted",
            "filename": filename,
            "timestamp": datetime.now().isoformat()
        }))

        return {"success": True, "filename": filename}
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


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


def _find_blender_executable() -> Optional[str]:
    env_path = os.environ.get("BLENDER_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    for candidate in [
        shutil.which("blender"),
        r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
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
        str(zoom if zoom is not None else 16),
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
        updates = {
            "status": "completed",
            "stage": "blender_generated",
            "note": "Blender stage completed",
            "error": None,
            "blenderPath": result.get("blenderPath"),
            "finishedAt": datetime.now().isoformat(),
        }
        for key in ("outputDir", "sceneKey", "modelUrl", "sionnaSceneXml"):
            if result.get(key) is not None:
                updates[key] = result.get(key)
        _update_task(task_id, updates)
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


@app.post("/api/scene-tasks/from-location")
async def create_scene_task(req: SceneTaskCreateRequest):
    lat = req.lat
    lon = req.lon
    requested_zoom = req.zoom
    zoom = FIXED_GENERATION_ZOOM
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
        zoom = FIXED_GENERATION_ZOOM
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
        tasks = _read_json_list(SCENE_TASKS_JSON)
    # Reconcile stale running/queued tasks by checking generated artifacts.
    reconciled_tasks = [
        _reconcile_task_from_artifacts(task) if task.get("status") in {"running", "queued"} else task
        for task in tasks
    ]
    return {"success": True, "tasks": reconciled_tasks, "count": len(reconciled_tasks)}


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
        return {"success": True, "metadata": metadata}
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


@app.get("/api/sionna/sinr-map")
async def sionna_sinr_map(
    sinr_vmin: float = Query(default=-20.0, description="SINR 色階下限 (dB)"),
    sinr_vmax: float = Query(default=40.0,  description="SINR 色階上限 (dB)"),
    cell_size: float = Query(default=2.0,   description="採樣格子大小 (m)"),
    samples_per_tx: int = Query(default=100000000, description="每個 TX 的採樣數"),
):
    """Generate SINR coverage map and return the PNG."""
    try:
        from app.sionna_service import generate_sinr_map, SINR_MAP_PATH
        await generate_sinr_map(
            sinr_vmin=sinr_vmin,
            sinr_vmax=sinr_vmax,
            cell_size=cell_size,
            samples_per_tx=samples_per_tx,
        )
        if not os.path.isfile(SINR_MAP_PATH):
            return JSONResponse({"error": "圖檔生成失敗，請查看後端 log"}, status_code=500)
        return FileResponse(SINR_MAP_PATH, media_type="image/png", filename="sinr_map.png")
    except SionnaLLVMError as e:
        return _sionna_llvm_error_response("sinr-map", e)
    except ImportError as e:
        logger.error(f"Sionna ImportError (sinr-map): {e}")
        return JSONResponse({"error": "Sionna 未安裝，請先執行 pip install sionna"}, status_code=503)


@app.get("/api/sionna/cfr-plot")
async def sionna_cfr_plot():
    """Generate Channel Frequency Response plot and return the PNG."""
    try:
        from app.sionna_service import generate_cfr_plot, CFR_PLOT_PATH
        await generate_cfr_plot()
        if not os.path.isfile(CFR_PLOT_PATH):
            return JSONResponse({"error": "圖檔生成失敗，請查看後端 log"}, status_code=500)
        return FileResponse(CFR_PLOT_PATH, media_type="image/png", filename="cfr_plot.png")
    except SionnaLLVMError as e:
        return _sionna_llvm_error_response("cfr-plot", e)
    except ImportError:
        return JSONResponse({"error": "Sionna 未安裝，請先執行 pip install sionna"}, status_code=503)
    except Exception as e:
        logger.error(f"CFR plot error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/sionna/doppler")
async def sionna_doppler():
    """Generate Delay-Doppler plot and return the PNG."""
    try:
        from app.sionna_service import generate_doppler_plot, DOPPLER_PLOT_PATH
        await generate_doppler_plot()
        if not os.path.isfile(DOPPLER_PLOT_PATH):
            return JSONResponse({"error": "圖檔生成失敗，請查看後端 log"}, status_code=500)
        return FileResponse(DOPPLER_PLOT_PATH, media_type="image/png", filename="doppler_plot.png")
    except SionnaLLVMError as e:
        return _sionna_llvm_error_response("doppler", e)
    except ImportError:
        return JSONResponse({"error": "Sionna 未安裝，請先執行 pip install sionna"}, status_code=503)
    except Exception as e:
        logger.error(f"Doppler plot error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/sionna/channel-response")
async def sionna_channel_response():
    """Generate Channel Impulse Response plot and return the PNG."""
    try:
        from app.sionna_service import generate_channel_response, CHANNEL_RESP_PATH
        await generate_channel_response()
        if not os.path.isfile(CHANNEL_RESP_PATH):
            return JSONResponse({"error": "圖檔生成失敗，請查看後端 log"}, status_code=500)
        return FileResponse(CHANNEL_RESP_PATH, media_type="image/png", filename="channel_response.png")
    except SionnaLLVMError as e:
        return _sionna_llvm_error_response("channel-response", e)
    except ImportError:
        return JSONResponse({"error": "Sionna 未安裝，請先執行 pip install sionna"}, status_code=503)
    except Exception as e:
        logger.error(f"Channel response error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
import asyncio
from fastapi import HTTPException
from fastapi.responses import Response

DEFAULT_POWER_DBM_BY_ROLE = {
    "tx": 80.0,
    "jammer": 80.0,
}

class DeviceIn(BaseModel):
    name: str
    role: str
    x: float
    y: float
    z: float
    power_dbm: Optional[float] = Field(default=None)


def _device_power_dbm(device: DeviceIn) -> Optional[float]:
    if device.power_dbm is not None:
        return device.power_dbm
    return DEFAULT_POWER_DBM_BY_ROLE.get(device.role)

class SimulateRequest(BaseModel):
    scene: str
    map_type: str
    cell_size: float = Field(default=4.0, gt=0)
    samples_per_tx: int = Field(default=100000000, ge=10000)
    overlay_scene: bool = Field(default=False)
    devices: List[DeviceIn]

@app.post("/api/simulate")
async def simulate(req: SimulateRequest):
    # Determine the absolute path for the XML properly from this main.py file
    scene_name = req.scene.upper()
    scene_xml = BASE_DIR / "static" / "scenes" / scene_name / f"{scene_name}.xml"
    
    if not scene_xml.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Scene XML not found: {scene_xml}",
        )

    output_dir = str(BASE_DIR / "static" / "maps" / req.scene.lower())
    os.makedirs(output_dir, exist_ok=True)

    devices_dicts = []
    for d in req.devices:
        power_dbm = _device_power_dbm(d)
        device_payload = {
            "name": d.name,
            "role": d.role,
            "x": d.x,
            "y": d.y,
            "z": d.z,
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
        overlay_scene=overlay_scene,
    )
