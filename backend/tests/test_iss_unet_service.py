import asyncio
import json
import shutil
import sys
import types
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

    def test_result_image_urls_use_api_route(self):
        from app.iss_unet_service import result_image_url

        self.assertEqual(
            result_image_url("iss_unet_ntpu_comparison.png"),
            "/api/iss-unet/images/iss_unet_ntpu_comparison.png",
        )

    def test_result_image_urls_support_ratio_bearing_names(self):
        from app.iss_unet_service import result_image_url

        self.assertEqual(
            result_image_url("iss_unet_ntpu_ratio_50_comparison.png"),
            "/api/iss-unet/images/iss_unet_ntpu_ratio_50_comparison.png",
        )

    def test_sparse_ratio_label_formats_common_ratios(self):
        from app.iss_unet_service import sparse_ratio_label

        self.assertEqual(sparse_ratio_label(0), "ratio_0")
        self.assertEqual(sparse_ratio_label(0.2), "ratio_20")
        self.assertEqual(sparse_ratio_label(0.5), "ratio_50")
        self.assertEqual(sparse_ratio_label(1.0), "ratio_100")
        self.assertEqual(sparse_ratio_label(0.125), "ratio_12p5")

    def test_sparse_sample_zero_ratio_selects_no_samples(self):
        from app.iss_unet_service import create_sparse_sample

        iss = np.full((4, 5), -95.0, dtype=np.float32)
        building = np.zeros((4, 5), dtype=np.float32)

        sparse_mask, outdoor_mask = create_sparse_sample(iss, building, sparse_ratio=0.0)

        self.assertEqual(int(outdoor_mask.sum()), 20)
        self.assertEqual(int(sparse_mask.sum()), 0)

    def test_sparse_sample_ratio_selects_expected_count(self):
        from app.iss_unet_service import create_sparse_sample

        iss = np.full((4, 5), -95.0, dtype=np.float32)
        building = np.zeros((4, 5), dtype=np.float32)
        building[0, 0] = 10.0
        outdoor_pixels = int((building <= 3.0).sum())

        sparse_mask, _ = create_sparse_sample(iss, building, sparse_ratio=0.2)

        self.assertEqual(outdoor_pixels, 19)
        self.assertEqual(int(sparse_mask.sum()), int(outdoor_pixels * 0.2))

    def test_sparse_sample_full_ratio_selects_all_outdoor_pixels(self):
        from app.iss_unet_service import create_sparse_sample

        iss = np.full((4, 5), -95.0, dtype=np.float32)
        building = np.zeros((4, 5), dtype=np.float32)
        building[0, 0] = 10.0
        outdoor_pixels = int((building <= 3.0).sum())

        sparse_mask, _ = create_sparse_sample(iss, building, sparse_ratio=1.0)

        self.assertEqual(int(sparse_mask.sum()), outdoor_pixels)

    def test_reconstruct_request_accepts_zero_sparse_ratio(self):
        req = main.ISSUNetReconstructRequest(scene="NTPU", sparse_ratio=0.0)

        self.assertEqual(req.sparse_ratio, 0.0)

    def test_reconstruct_uses_ratio_bearing_outputs_and_render_ratio(self):
        self._write_ntpu_dataset()
        model_path = self.artifact_dir / "best_iss_reconstruction_model.pth"
        model_path.write_bytes(b"model")

        class FakeTensor:
            def float(self):
                return self

            def unsqueeze(self, _dim):
                return self

            def to(self, _device):
                return self

        class FakePrediction:
            def __getitem__(self, _key):
                return self

            def detach(self):
                return self

            def cpu(self):
                return self

            def numpy(self):
                return np.full((128, 128), 0.5, dtype=np.float32)

        class FakeNoGrad:
            def __enter__(self):
                return None

            def __exit__(self, *_args):
                return False

        fake_torch = types.SimpleNamespace(
            from_numpy=lambda _value: FakeTensor(),
            no_grad=lambda: FakeNoGrad(),
        )

        class FakeModel:
            def __call__(self, _tensor):
                return FakePrediction()

        captured = {}

        def fake_render_comparison(_arrays, _reconstructed_iss, _sparse_mask, _outdoor_mask, sparse_ratio):
            captured["sparse_ratio"] = sparse_ratio
            return b"comparison"

        from app.iss_unet_service import ISSUNetCFARParams, reconstruct_iss_unet

        with patch("app.iss_unet_service.SCENE_DIR", self.scene_dir):
            with patch("app.iss_unet_service.MODEL_ARTIFACT_PATH", model_path):
                with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
                    with patch.dict(sys.modules, {"torch": fake_torch}):
                        with patch("app.iss_unet_service._load_model", return_value=(FakeModel(), "cpu")):
                            with patch("app.iss_unet_service._render_reconstructed_png", return_value=b"reconstructed"):
                                with patch("app.iss_unet_service._render_comparison_png", side_effect=fake_render_comparison):
                                    result = reconstruct_iss_unet(
                                        "NTPU",
                                        sparse_ratio=0.5,
                                        cfar=ISSUNetCFARParams(enabled=False),
                                    )

        self.assertEqual(captured["sparse_ratio"], 0.5)
        self.assertEqual(result["images"]["comparison"], "/api/iss-unet/images/iss_unet_ntpu_ratio_50_comparison.png")
        self.assertTrue((self.output_dir / "iss_unet_ntpu_ratio_50_reconstructed.png").exists())
        self.assertTrue((self.output_dir / "iss_unet_ntpu_ratio_50_comparison.png").exists())
        self.assertTrue((self.output_dir / "iss_unet_ntpu_ratio_50_reconstructed.npy").exists())

    def test_image_endpoint_serves_generated_png_from_api_route(self):
        image_path = self.output_dir / "iss_unet_ntpu_comparison.png"
        image_path.write_bytes(b"png-bytes")

        with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
            response = asyncio.run(main.iss_unet_image_get("iss_unet_ntpu_comparison.png"))

        self.assertEqual(Path(response.path), image_path)

    def test_image_endpoint_serves_ratio_bearing_png_from_api_route(self):
        image_path = self.output_dir / "iss_unet_ntpu_ratio_50_comparison.png"
        image_path.write_bytes(b"png-bytes")

        with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
            response = asyncio.run(main.iss_unet_image_get("iss_unet_ntpu_ratio_50_comparison.png"))

        self.assertEqual(Path(response.path), image_path)

    def test_image_endpoint_rejects_path_traversal(self):
        with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
            response = asyncio.run(main.iss_unet_image_get("../secret.png"))

        self.assertEqual(response.status_code, 404)

    def test_image_endpoint_rejects_non_iss_filename(self):
        image_path = self.output_dir / "other_ntpu_ratio_50_comparison.png"
        image_path.write_bytes(b"png-bytes")

        with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
            response = asyncio.run(main.iss_unet_image_get("other_ntpu_ratio_50_comparison.png"))

        self.assertEqual(response.status_code, 404)

    def test_prepare_dataset_reuses_existing_building_height_map_and_writes_contract_files(self):
        scene_root = self.scene_dir / "NYCU"
        scene_root.mkdir(parents=True)
        scene_xml = scene_root / "NYCU.xml"
        scene_xml.write_text("<scene/>", encoding="utf-8")
        source_map = np.arange(512 * 512, dtype=np.float32).reshape(512, 512)
        np.save(scene_root / "building_height_512.npy", source_map)

        radio_maps = {
            "DSS": np.full((128, 128), -120.0, dtype=np.float32),
            "ISS": np.full((128, 128), -80.0, dtype=np.float32),
            "TSS": np.full((128, 128), -75.0, dtype=np.float32),
        }

        from app.iss_unet_dataset_service import prepare_iss_unet_dataset

        with patch("app.iss_unet_dataset_service.run_sionna_dataset_maps", return_value=radio_maps):
            result = prepare_iss_unet_dataset("nycu", scene_dir=self.scene_dir)

        data_dir = scene_root / "iss_unet_data"
        self.assertTrue(result["available"])
        self.assertEqual(result["scene"], "NYCU")
        self.assertEqual(np.load(data_dir / "building_height_128.npy").shape, (128, 128))
        np.testing.assert_array_equal(np.load(data_dir / "building_height_128.npy"), source_map[::4, ::4])
        self.assertEqual(np.load(data_dir / "sionna_dss.npy").shape, (128, 128))
        self.assertEqual(np.load(data_dir / "sionna_iss.npy").shape, (128, 128))
        self.assertEqual(np.load(data_dir / "sionna_tss.npy").shape, (128, 128))
        meta = json.loads((data_dir / "scene_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["scene"], "NYCU")
        self.assertEqual(meta["grid_res"], 128)
        self.assertEqual(meta["area_m"], 512.0)
        self.assertEqual(meta["outputs"]["iss"], "sionna_iss.npy")

    def test_dataset_status_endpoint_reports_scene_availability(self):
        scene_root = self.scene_dir / "NYCU"
        data_dir = scene_root / "iss_unet_data"
        data_dir.mkdir(parents=True)
        for name in REQUIRED_FILES:
            np.save(data_dir / name, np.zeros((128, 128), dtype=np.float32))
        (data_dir / "scene_meta.json").write_text('{"scene":"NYCU"}', encoding="utf-8")

        with patch("app.iss_unet_service.SCENE_DIR", self.scene_dir):
            response = asyncio.run(main.iss_unet_dataset_status_get(scene="nycu"))

        self.assertTrue(response["available"])
        self.assertEqual(response["scene"], "NYCU")
        self.assertEqual(response["missing_files"], [])
        self.assertTrue(response["meta_available"])

    def test_dataset_prepare_endpoint_returns_unavailable_for_missing_scene_xml(self):
        with patch("app.iss_unet_dataset_service.SCENE_DIR", self.scene_dir):
            response = asyncio.run(main.iss_unet_dataset_prepare_post(main.ISSUNetDatasetPrepareRequest(scene="T-ABCDEF1234")))

        self.assertEqual(response.status_code, 404)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error_type"], "scene_unavailable")


if __name__ == "__main__":
    unittest.main()
