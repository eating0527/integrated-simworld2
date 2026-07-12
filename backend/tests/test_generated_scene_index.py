import json
import asyncio
import math
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app import main
from app import blender_generate_scene
from app.coordinate_frame import SceneFrame


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

    def test_fixed_meter_bbox_is_512m_at_25n_and_independent_of_zoom(self):
        lat = 25.0
        lon = 121.0

        bbox_main = main._bbox_by_center_meters(lat, lon, 512.0)
        bbox_blender = blender_generate_scene._bbox_by_center_meters(lat, lon, 512.0)
        zoom_bbox = main._bbox_by_zoom_centered(lat, lon, 17, 2.6)

        self.assertEqual(bbox_main, bbox_blender)
        min_lat, max_lat, min_lon, max_lon = bbox_main
        meters_per_deg_lat, meters_per_deg_lon = main._degree_to_meter_scales(lat)
        width_m = (max_lon - min_lon) * meters_per_deg_lon
        height_m = (max_lat - min_lat) * meters_per_deg_lat
        zoom_width_m = (zoom_bbox[3] - zoom_bbox[2]) * meters_per_deg_lon

        self.assertTrue(math.isclose(width_m, 512.0, rel_tol=0.0, abs_tol=1.0))
        self.assertTrue(math.isclose(height_m, 512.0, rel_tol=0.0, abs_tol=1.0))
        self.assertFalse(math.isclose(zoom_width_m, 512.0, rel_tol=0.0, abs_tol=10.0))

    def test_building_count_uses_fixed_meter_bbox_metadata(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({
                    "elements": [
                        {"tags": {"ways": "3", "relations": "1"}},
                    ],
                }).encode("utf-8")

        def fake_urlopen(request, timeout):
            body = request.data.decode("utf-8")
            captured["query"] = body
            captured["timeout"] = timeout
            return FakeResponse()

        with patch.object(main, "OVERPASS_ENDPOINTS", ["https://example.test/overpass"]):
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                result = main._check_building_count_sync(25.0, 121.0)

        bbox = result["bbox"]
        meters_per_deg_lat, meters_per_deg_lon = main._degree_to_meter_scales(25.0)
        self.assertEqual(result["building_count"], 4)
        self.assertEqual(result["zoom"], main.BASEMAP_GENERATION_ZOOM)
        self.assertEqual(result["bbox_mode"], "fixed_meters")
        self.assertEqual(result["area_m"], 512.0)
        self.assertTrue(math.isclose((bbox["east"] - bbox["west"]) * meters_per_deg_lon, 512.0, abs_tol=1.0))
        self.assertTrue(math.isclose((bbox["north"] - bbox["south"]) * meters_per_deg_lat, 512.0, abs_tol=1.0))
        self.assertIn(str(bbox["south"]), captured["query"])
        self.assertIn(str(bbox["east"]), captured["query"])

    def test_blender_command_uses_basemap_zoom_and_area_m(self):
        task = _task("task-ok", "T-AAAAAAAAAA", status="queued")
        task["location"]["lat"] = 25.0
        task["location"]["lon"] = 121.0
        task["location"]["zoom"] = main.BASEMAP_GENERATION_ZOOM
        task["location"]["requested_zoom"] = 15
        task["outputDir"] = str(self.scene_dir / "T-AAAAAAAAAA")
        self._write_tasks([task])
        captured = {}

        def fake_run(cmd, capture_output, text, timeout):
            captured["cmd"] = cmd
            out_dir = Path(task["outputDir"])
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "T-AAAAAAAAAA.glb").write_bytes(b"glb")
            (out_dir / "T-AAAAAAAAAA.xml").write_text("<scene />", encoding="utf-8")
            (out_dir / "scene_metadata.json").write_text(
                json.dumps({"status": "completed", "frame": SceneFrame(
                    frame_id="scene-test", origin_lat=25.0, origin_lon=121.0, origin_alt_m=0.0
                ).to_dict()}),
                encoding="utf-8",
            )

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        with patch.object(main, "_find_blender_executable", return_value="blender.exe"):
            with patch("subprocess.run", side_effect=fake_run):
                result = main._run_blender_task_sync("task-ok")

        cmd = captured["cmd"]
        self.assertTrue(result["success"])
        self.assertEqual(cmd[cmd.index("--zoom") + 1], str(main.BASEMAP_GENERATION_ZOOM))
        self.assertEqual(cmd[cmd.index("--area-m") + 1], "512.0")

    def test_blender_parse_args_accepts_area_m(self):
        args = blender_generate_scene.parse_args([
            "--lat", "25.0",
            "--lon", "121.0",
            "--zoom", "18",
            "--area-m", "512.0",
            "--output-dir", str(self.root),
        ])

        self.assertEqual(args.area_m, 512.0)

    def test_blender_scene_metadata_uses_fixed_scene_frame(self):
        frame = blender_generate_scene.scene_frame_metadata("T-AAAAAAAAAA", 25.0, 121.0)

        self.assertEqual(frame["frame_id"], "scene-t-aaaaaaaaaa")
        self.assertEqual(frame["extent"], {
            "min_e": -256.0, "max_e": 256.0, "min_n": -256.0, "max_n": 256.0,
        })
        self.assertEqual(frame["grid"], {
            "rows": 128, "cols": 128, "pixel_size_e_m": 4.0, "pixel_size_n_m": 4.0,
        })
        self.assertEqual(frame["display_margin_m"], 32.0)

    def test_basemap_size_stays_fixed_despite_imported_blender_bounds(self):
        width, height, mode = blender_generate_scene._basemap_size_for_imported_bounds(
            area_m=512.0,
            imported_width=593.45,
            imported_height=591.24,
        )

        self.assertEqual(width, 512.0)
        self.assertEqual(height, 512.0)
        self.assertEqual(mode, "fixed_area")

    def test_blender_unit_plane_scale_matches_target_size(self):
        scale_x, scale_y = blender_generate_scene._plane_scale_for_unit_size(593.45, 591.24)

        self.assertEqual(scale_x, 593.45)
        self.assertEqual(scale_y, 591.24)


if __name__ == "__main__":
    unittest.main()
