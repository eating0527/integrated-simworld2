import asyncio
import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app import main


REQUIRED_FILES = {
    "building_height_128.npy",
    "sionna_dss.npy",
    "sionna_iss.npy",
    "sionna_tss.npy",
}


class ISSUNetServiceTests(unittest.TestCase):
    def setUp(self):
        root = Path.cwd() / ".test_tmp" / f"iss-unet-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.scene_dir = root / "scenes"
        self.artifact_dir = root / "model_artifacts"
        self.output_dir = root / "images"
        self.scene_dir.mkdir()
        self.artifact_dir.mkdir()
        self.output_dir.mkdir()

        self.patches = [
            patch.object(main, "SCENE_DIR", self.scene_dir),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def _write_ntpu_dataset(self):
        data_dir = self.scene_dir / "NTPU" / "iss_unet_data"
        data_dir.mkdir(parents=True)
        shape = (128, 128)
        np.save(data_dir / "building_height_128.npy", np.zeros(shape, dtype=np.float32))
        np.save(data_dir / "sionna_dss.npy", np.full(shape, -100.0, dtype=np.float32))
        np.save(data_dir / "sionna_iss.npy", np.full(shape, -95.0, dtype=np.float32))
        np.save(data_dir / "sionna_tss.npy", np.full(shape, -90.0, dtype=np.float32))
        (data_dir / "scene_meta.json").write_text("{}", encoding="utf-8")
        return data_dir

    def test_dataset_resolver_finds_ntpu_required_files(self):
        self._write_ntpu_dataset()
        from app.iss_unet_service import resolve_scene_dataset

        dataset = resolve_scene_dataset("NTPU", scene_dir=self.scene_dir)

        self.assertTrue(dataset.available)
        self.assertEqual({path.name for path in dataset.files.values()}, REQUIRED_FILES)
        self.assertEqual(dataset.scene, "NTPU")

    def test_dataset_resolver_reports_missing_files_for_nycu(self):
        from app.iss_unet_service import resolve_scene_dataset

        dataset = resolve_scene_dataset("NYCU", scene_dir=self.scene_dir)

        self.assertFalse(dataset.available)
        self.assertEqual(set(dataset.missing_files), REQUIRED_FILES)

    def test_status_reports_unavailable_when_model_artifact_missing(self):
        self._write_ntpu_dataset()
        from app.iss_unet_service import MODEL_ARTIFACT_PATH, OUTPUT_DIR, iss_unet_status

        with patch("app.iss_unet_service.SCENE_DIR", self.scene_dir):
            with patch("app.iss_unet_service.MODEL_ARTIFACT_PATH", self.artifact_dir / MODEL_ARTIFACT_PATH.name):
                with patch("app.iss_unet_service.OUTPUT_DIR", OUTPUT_DIR):
                    status = iss_unet_status()

        self.assertFalse(status["available"])
        self.assertFalse(status["model"]["available"])
        self.assertTrue(status["datasets"]["NTPU"]["available"])

    def test_reconstruct_endpoint_returns_409_for_missing_dataset(self):
        from app.iss_unet_service import OUTPUT_DIR

        with patch("app.iss_unet_service.SCENE_DIR", self.scene_dir):
            with patch("app.iss_unet_service.OUTPUT_DIR", OUTPUT_DIR):
                response = asyncio.run(
                    main.iss_unet_reconstruct_post(
                        main.ISSUNetReconstructRequest(scene="NYCU", sparse_ratio=0.2)
                    )
                )

        self.assertEqual(response.status_code, 409)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(set(payload["missing_files"]), REQUIRED_FILES)


if __name__ == "__main__":
    unittest.main()
