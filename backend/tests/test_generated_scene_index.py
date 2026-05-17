import json
import asyncio
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app import main


def _task(
    task_id: str,
    scene_key: str,
    status: str = "completed",
) -> dict:
    return {
        "id": task_id,
        "sceneKey": scene_key,
        "sceneName": f"Scene {scene_key}",
        "status": status,
        "location": {"lat": 24.1, "lon": 121.1, "place_name": "Campus"},
        "modelUrl": f"/generated-scenes/{scene_key}/{scene_key}.glb",
        "sionnaSceneXml": f"static/scenes/{scene_key}/{scene_key}.xml",
        "createdAt": "2026-05-14T10:00:00",
        "updatedAt": "2026-05-14T10:05:00",
        "extra": "not indexed",
    }


def _write_scene(scene_dir: Path, scene_key: str, glb: bool = True, xml: bool = True) -> None:
    target = scene_dir / scene_key
    target.mkdir(parents=True, exist_ok=True)
    if glb:
        (target / f"{scene_key}.glb").write_bytes(b"glb")
    if xml:
        (target / f"{scene_key}.xml").write_text("<scene />", encoding="utf-8")


class GeneratedSceneIndexTests(unittest.TestCase):
    def setUp(self):
        root = Path.cwd() / ".test_tmp" / f"scene-index-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.upload_dir = root / "uploads"
        self.scene_dir = root / "scenes"
        self.upload_dir.mkdir()
        self.scene_dir.mkdir()
        self.tasks_json = self.upload_dir / "scene_tasks.json"
        self.index_json = self.upload_dir / "scene_index.json"

        self.patches = [
            patch.object(main, "SCENE_TASKS_JSON", self.tasks_json),
            patch.object(main, "SCENE_INDEX_JSON", self.index_json),
            patch.object(main, "SCENE_DIR", self.scene_dir),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def _write_tasks(self, tasks: list[dict]) -> None:
        self.tasks_json.write_text(json.dumps(tasks), encoding="utf-8")

    def test_rebuild_indexes_only_completed_tasks_with_glb_and_xml(self):
        available = _task("task-ok", "T-AAAAAAAAAA")
        missing_glb = _task("task-no-glb", "T-BBBBBBBBBB")
        missing_xml = _task("task-no-xml", "T-CCCCCCCCCC")
        queued = _task("task-queued", "T-DDDDDDDDDD", status="queued")
        failed = _task("task-failed", "T-EEEEEEEEEE", status="failed")
        missing_folder = _task("task-no-folder", "T-FFFFFFFFFF")
        running = _task("task-running", "T-9999999999", status="running")
        self._write_tasks([available, missing_glb, missing_xml, queued, failed, missing_folder, running])
        _write_scene(self.scene_dir, "T-AAAAAAAAAA")
        _write_scene(self.scene_dir, "T-BBBBBBBBBB", glb=False)
        _write_scene(self.scene_dir, "T-CCCCCCCCCC", xml=False)
        _write_scene(self.scene_dir, "T-DDDDDDDDDD")
        _write_scene(self.scene_dir, "T-EEEEEEEEEE")
        _write_scene(self.scene_dir, "T-9999999999")

        scenes = main.rebuild_scene_index()

        self.assertEqual([scene["id"] for scene in scenes], ["task-ok"])
        self.assertEqual(scenes[0]["sceneKey"], "T-AAAAAAAAAA")
        self.assertEqual(scenes[0]["modelUrl"], "/generated-scenes/T-AAAAAAAAAA/T-AAAAAAAAAA.glb")
        self.assertIn("indexedAt", scenes[0])
        self.assertNotIn("extra", scenes[0])
        self.assertEqual(json.loads(self.index_json.read_text(encoding="utf-8")), scenes)

    def test_get_generated_scenes_returns_cached_index(self):
        cached = [_task("task-ok", "T-AAAAAAAAAA")]
        self.index_json.write_text(json.dumps(cached), encoding="utf-8")

        response = asyncio.run(main.list_generated_scenes())

        self.assertEqual(response, {"success": True, "scenes": cached, "count": 1})

    def test_refresh_generated_scenes_rebuilds_and_returns_available_scenes(self):
        task = _task("task-ok", "T-AAAAAAAAAA")
        self._write_tasks([task])
        _write_scene(self.scene_dir, "T-AAAAAAAAAA")
        self.index_json.write_text("[]", encoding="utf-8")

        response = asyncio.run(main.refresh_generated_scenes())

        self.assertTrue(response["success"])
        self.assertEqual(response["count"], 1)
        self.assertEqual(response["scenes"][0]["id"], "task-ok")
        self.assertEqual(json.loads(self.index_json.read_text(encoding="utf-8")), response["scenes"])

    def test_completed_scene_task_prepares_iss_unet_dataset(self):
        task = _task("task-ok", "T-AAAAAAAAAA", status="running")
        task["outputDir"] = str(self.scene_dir / "T-AAAAAAAAAA")
        self._write_tasks([task])
        _write_scene(self.scene_dir, "T-AAAAAAAAAA")

        prepare_calls = []

        def fake_prepare(scene, scene_dir):
            prepare_calls.append((scene, scene_dir))
            return {"available": True}

        with patch.object(main, "_run_blender_task_sync", return_value={
            "success": True,
            "outputDir": str(self.scene_dir / "T-AAAAAAAAAA"),
            "sceneKey": "T-AAAAAAAAAA",
            "modelUrl": "/generated-scenes/T-AAAAAAAAAA/T-AAAAAAAAAA.glb",
            "sionnaSceneXml": str(self.scene_dir / "T-AAAAAAAAAA" / "T-AAAAAAAAAA.xml"),
        }):
            with patch("app.iss_unet_dataset_service.prepare_iss_unet_dataset", side_effect=fake_prepare):
                asyncio.run(main._process_scene_task("task-ok"))

        updated = json.loads(self.tasks_json.read_text(encoding="utf-8"))[0]
        self.assertEqual(prepare_calls, [("T-AAAAAAAAAA", self.scene_dir)])
        self.assertEqual(updated["status"], "completed")
        self.assertEqual(updated["stage"], "iss_unet_dataset_prepared")
        self.assertTrue(updated["issUnetDataset"]["available"])

    def test_completed_scene_task_records_dataset_prepare_failure_without_crashing(self):
        task = _task("task-ok", "T-AAAAAAAAAA", status="running")
        task["outputDir"] = str(self.scene_dir / "T-AAAAAAAAAA")
        self._write_tasks([task])
        _write_scene(self.scene_dir, "T-AAAAAAAAAA")

        with patch.object(main, "_run_blender_task_sync", return_value={
            "success": True,
            "outputDir": str(self.scene_dir / "T-AAAAAAAAAA"),
            "sceneKey": "T-AAAAAAAAAA",
            "modelUrl": "/generated-scenes/T-AAAAAAAAAA/T-AAAAAAAAAA.glb",
            "sionnaSceneXml": str(self.scene_dir / "T-AAAAAAAAAA" / "T-AAAAAAAAAA.xml"),
        }):
            with patch("app.iss_unet_dataset_service.prepare_iss_unet_dataset", side_effect=RuntimeError("Sionna unavailable")):
                asyncio.run(main._process_scene_task("task-ok"))

        updated = json.loads(self.tasks_json.read_text(encoding="utf-8"))[0]
        self.assertEqual(updated["status"], "completed")
        self.assertEqual(updated["stage"], "iss_unet_dataset_failed")
        self.assertEqual(updated["issUnetDataset"]["available"], False)
        self.assertIn("Sionna unavailable", updated["issUnetDataset"]["error"])


if __name__ == "__main__":
    unittest.main()
