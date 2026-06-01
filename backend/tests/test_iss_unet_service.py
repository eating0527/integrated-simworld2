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

    def test_confidence_weighting_keeps_sparse_pixel_and_suppresses_far_pixels(self):
        from app.iss_unet_service import ISS_MIN_DBM, apply_noise_confidence_weighting

        reconstructed = np.full((16, 16), -40.0, dtype=np.float32)
        sparse_mask = np.zeros((16, 16), dtype=np.float32)
        sparse_mask[8, 8] = 1.0
        outdoor_mask = np.ones((16, 16), dtype=np.float32)

        weighted, stats = apply_noise_confidence_weighting(reconstructed, sparse_mask, outdoor_mask, sigma_px=2.0)

        self.assertAlmostEqual(float(weighted[8, 8]), -40.0, places=4)
        self.assertLess(float(weighted[0, 0]), -139.0)
        self.assertEqual(stats["confidence_applied"], True)
        self.assertEqual(stats["confidence_pixels_gt_0_5"], 9)
        self.assertGreater(stats["confidence_mean_outdoor"], 0.0)
        self.assertEqual(stats["confidence_background_dbm"], ISS_MIN_DBM)

    def test_confidence_weighting_without_sparse_points_returns_background(self):
        from app.iss_unet_service import ISS_MIN_DBM, apply_noise_confidence_weighting

        reconstructed = np.full((8, 8), -40.0, dtype=np.float32)
        sparse_mask = np.zeros((8, 8), dtype=np.float32)
        outdoor_mask = np.ones((8, 8), dtype=np.float32)

        weighted, stats = apply_noise_confidence_weighting(reconstructed, sparse_mask, outdoor_mask)

        np.testing.assert_array_equal(weighted, np.full((8, 8), ISS_MIN_DBM, dtype=np.float32))
        self.assertEqual(stats["confidence_applied"], True)
        self.assertEqual(stats["confidence_pixels_gt_0_5"], 0)
        self.assertEqual(stats["confidence_mean_outdoor"], 0.0)

    def test_real_sample_csv_files_exist_with_required_columns(self):
        from app.iss_real import SAMPLE_GPS_PATH, SAMPLE_NOISE_PATH, parse_gps_csv, parse_noise_csv

        gps_points = parse_gps_csv(SAMPLE_GPS_PATH)
        noise_points = parse_noise_csv(SAMPLE_NOISE_PATH)

        self.assertGreater(len(gps_points), 0)
        self.assertGreater(len(noise_points), 0)
        self.assertTrue({"time_stamp", "lat", "lon", "alt"}.issubset(gps_points[0].raw_columns))
        self.assertTrue({"time_stamp", "noise_floor_db"}.issubset(noise_points[0].raw_columns))

    def test_align_noise_to_most_recent_gps_within_one_second(self):
        from app.iss_real import align_noise_to_gps, parse_gps_csv, parse_noise_csv

        gps_path = self.root / "gps.csv"
        noise_path = self.root / "noise.csv"
        gps_path.write_text(
            "\n".join(
                [
                    "time_stamp,lat,lon,alt",
                    "2026-05-27T12:00:00.000Z,24.0,121.0,10",
                    "2026-05-27T12:00:00.800Z,24.1,121.1,11",
                    "2026-05-27T12:00:02.000Z,24.2,121.2,12",
                ]
            ),
            encoding="utf-8",
        )
        noise_path.write_text(
            "\n".join(
                [
                    "time_stamp,noise_floor_db",
                    "2026-05-27T12:00:00.900Z,-88.5",
                    "2026-05-27T12:00:01.900Z,-77.0",
                ]
            ),
            encoding="utf-8",
        )

        aligned, skipped = align_noise_to_gps(parse_gps_csv(gps_path), parse_noise_csv(noise_path))

        self.assertEqual(skipped, 1)
        self.assertEqual(len(aligned), 1)
        self.assertAlmostEqual(aligned[0].lat, 24.1)
        self.assertAlmostEqual(aligned[0].noise_floor_db, -88.5)

    def test_gps_mode_route_sparse_uses_simulated_iss_and_filters_blocked_pixels(self):
        from app.iss_real import create_route_sparse_sample, parse_gps_csv
        from app.iss_unet_service import resolve_scene_dataset

        data_dir = self._write_ntpu_dataset()
        meta = {
            "center_lat": 24.0,
            "center_lon": 121.0,
            "area_m": 512.0,
            "grid_res": 128,
        }
        (data_dir / "scene_meta.json").write_text(json.dumps(meta), encoding="utf-8")
        iss = np.full((128, 128), -100.0, dtype=np.float32)
        iss[64, 64] = -81.0
        iss[63, 65] = -72.0
        np.save(data_dir / "sionna_iss.npy", iss)
        building = np.zeros((128, 128), dtype=np.float32)
        building[64, 62] = 9.0
        np.save(data_dir / "building_height_128.npy", building)
        gps_path = self.root / "gps.csv"
        gps_path.write_text(
            "\n".join(
                [
                    "time_stamp,lat,lon,alt",
                    "2026-05-27T12:00:00Z,24.0,121.0,0",
                    "2026-05-27T12:00:01Z,24.0000359324461,121.000039446262,0",
                    "2026-05-27T12:00:02Z,24.0,120.999960553738,0",
                ]
            ),
            encoding="utf-8",
        )
        arrays = {
            "building": building,
            "dss": np.full((128, 128), -110.0, dtype=np.float32),
            "iss": iss,
            "tss": np.full((128, 128), -90.0, dtype=np.float32),
        }

        result = create_route_sparse_sample(
            arrays,
            resolve_scene_dataset("NTPU", scene_dir=self.scene_dir),
            mode="gps",
            gps_points=parse_gps_csv(gps_path),
        )

        self.assertEqual(int(result.sparse_mask.sum()), 2)
        self.assertAlmostEqual(float(result.iss_sparse_dbm[64, 64]), -81.0)
        self.assertAlmostEqual(float(result.iss_sparse_dbm[63, 65]), -72.0)
        self.assertEqual(float(result.sparse_mask[64, 62]), 0.0)
        self.assertEqual(result.metrics["route_points"], 3)
        self.assertEqual(result.metrics["used_samples"], 2)

    def test_gps_noise_mode_route_sparse_uses_aligned_noise_values(self):
        from app.iss_real import create_route_sparse_sample, parse_gps_csv, parse_noise_csv
        from app.iss_unet_service import resolve_scene_dataset

        data_dir = self._write_ntpu_dataset()
        (data_dir / "scene_meta.json").write_text(
            json.dumps({"center_lat": 24.0, "center_lon": 121.0, "area_m": 512.0, "grid_res": 128}),
            encoding="utf-8",
        )
        gps_path = self.root / "gps.csv"
        gps_path.write_text(
            "\n".join(
                [
                    "time_stamp,lat,lon,alt",
                    "2026-05-27T12:00:00Z,24.0,121.0,0",
                    "2026-05-27T12:00:01Z,24.0000359324461,121.000039446262,0",
                ]
            ),
            encoding="utf-8",
        )
        noise_path = self.root / "noise.csv"
        noise_path.write_text(
            "\n".join(
                [
                    "time_stamp,noise_floor_db",
                    "2026-05-27T12:00:00.500Z,-87.25",
                    "2026-05-27T12:00:01.100Z,-66.5",
                ]
            ),
            encoding="utf-8",
        )
        arrays = {
            "building": np.zeros((128, 128), dtype=np.float32),
            "dss": np.full((128, 128), -110.0, dtype=np.float32),
            "iss": np.full((128, 128), -100.0, dtype=np.float32),
            "tss": np.full((128, 128), -90.0, dtype=np.float32),
        }

        result = create_route_sparse_sample(
            arrays,
            resolve_scene_dataset("NTPU", scene_dir=self.scene_dir),
            mode="gps_n",
            gps_points=parse_gps_csv(gps_path),
            noise_points=parse_noise_csv(noise_path),
        )

        self.assertEqual(int(result.sparse_mask.sum()), 2)
        self.assertAlmostEqual(float(result.iss_sparse_dbm[64, 64]), -87.25)
        self.assertAlmostEqual(float(result.iss_sparse_dbm[63, 65]), -66.5)
        self.assertEqual(result.metrics["aligned_noise"], 2)
        self.assertEqual(result.metrics["skipped_noise"], 0)

    def test_reconstruct_request_accepts_zero_sparse_ratio(self):
        req = main.ISSUNetReconstructRequest(scene="NTPU", sparse_ratio=0.0)

        self.assertEqual(req.sparse_ratio, 0.0)

    def test_reconstruct_request_accepts_focus_sampling_points_toggle(self):
        req = main.ISSUNetReconstructRequest(scene="NTPU", focus_sampling_points=False)

        self.assertEqual(req.focus_sampling_points, False)

    def test_upload_endpoint_forwards_focus_sampling_points_toggle(self):
        self._write_ntpu_dataset()
        from app.iss_unet_service import resolve_scene_dataset

        dataset = resolve_scene_dataset("NTPU", scene_dir=self.scene_dir)
        captured = {}

        def fake_reconstruct_iss_unet(**kwargs):
            captured.update(kwargs)
            return {
                "scene": "NTPU",
                "mode": "gps_n",
                "mode_label": "Noise with GPS",
                "sparse_ratio": 0.2,
                "metrics": {},
                "images": {},
                "files": {},
                "cfar": {"detections": 0, "clusters": []},
            }

        with patch("app.iss_unet_service.resolve_scene_dataset", return_value=dataset):
            with patch("app.iss_unet_service.reconstruct_iss_unet", side_effect=fake_reconstruct_iss_unet):
                response = asyncio.run(
                    main.iss_unet_reconstruct_upload_post(
                        scene="NTPU",
                        mode="gps_n",
                        focus_sampling_points=False,
                        gps_file=None,
                        noise_file=None,
                    )
                )

        self.assertEqual(response["success"], True)
        self.assertEqual(captured["focus_sampling_points"], False)

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

    def test_gps_noise_reconstruct_applies_confidence_before_outputs_and_cfar(self):
        data_dir = self._write_ntpu_dataset()
        (data_dir / "scene_meta.json").write_text(
            json.dumps({"center_lat": 24.0, "center_lon": 121.0, "area_m": 512.0, "grid_res": 128}),
            encoding="utf-8",
        )
        model_path = self.artifact_dir / "best_iss_reconstruction_model.pth"
        model_path.write_bytes(b"model")
        gps_path = self.root / "gps.csv"
        gps_path.write_text(
            "\n".join(
                [
                    "time_stamp,lat,lon,alt",
                    "2026-05-27T12:00:00Z,24.0,121.0,0",
                ]
            ),
            encoding="utf-8",
        )
        noise_path = self.root / "noise.csv"
        noise_path.write_text(
            "\n".join(
                [
                    "time_stamp,noise_floor_db",
                    "2026-05-27T12:00:00.500Z,-70.0",
                ]
            ),
            encoding="utf-8",
        )

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
                return np.ones((128, 128), dtype=np.float32)

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

        def fake_render_reconstructed(reconstructed_iss, mode_label="Sim"):
            captured["render_reconstructed"] = reconstructed_iss.copy()
            return b"reconstructed"

        def fake_render_comparison(_arrays, reconstructed_iss, _sparse_mask, _outdoor_mask, _sparse_ratio, **_kwargs):
            captured["render_comparison"] = reconstructed_iss.copy()
            return b"comparison"

        def fake_cfar_detect(signal_map, _outdoor_mask, _params):
            captured["cfar_signal"] = signal_map.copy()
            return {"detection_map": np.zeros((128, 128), dtype=np.float32), "threshold_map": np.zeros((128, 128), dtype=np.float32), "clusters": [], "detections": []}

        from app.iss_unet_service import ISSUNetCFARParams, ISS_MIN_DBM, reconstruct_iss_unet, resolve_scene_dataset

        dataset = resolve_scene_dataset("NTPU", scene_dir=self.scene_dir)

        with patch("app.iss_unet_service.SCENE_DIR", self.scene_dir):
            with patch("app.iss_unet_service.resolve_scene_dataset", return_value=dataset):
                with patch("app.iss_unet_service.MODEL_ARTIFACT_PATH", model_path):
                    with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
                        with patch.dict(sys.modules, {"torch": fake_torch}):
                            with patch("app.iss_unet_service._load_model", return_value=(FakeModel(), "cpu")):
                                with patch("app.iss_unet_service._render_reconstructed_png", side_effect=fake_render_reconstructed):
                                    with patch("app.iss_unet_service._render_comparison_png", side_effect=fake_render_comparison):
                                        with patch("app.iss_unet_service._cfar_detect", side_effect=fake_cfar_detect):
                                            result = reconstruct_iss_unet(
                                                "NTPU",
                                                cfar=ISSUNetCFARParams(enabled=True),
                                                mode="gps_n",
                                                gps_csv=gps_path,
                                                noise_csv=noise_path,
                                            )

        saved = np.load(self.output_dir / "iss_unet_ntpu_gps_n_reconstructed.npy")
        self.assertAlmostEqual(float(saved[64, 64]), -35.0, places=4)
        self.assertLess(float(saved[0, 0]), -139.9)
        self.assertEqual(float(saved[0, 0]), float(captured["render_reconstructed"][0, 0]))
        self.assertEqual(float(saved[0, 0]), float(captured["render_comparison"][0, 0]))
        self.assertEqual(float(saved[0, 0]), float(captured["cfar_signal"][0, 0]))
        self.assertEqual(result["metrics"]["confidence_applied"], True)
        self.assertEqual(result["metrics"]["confidence_sigma_px"], 8.0)
        self.assertEqual(result["metrics"]["confidence_background_dbm"], ISS_MIN_DBM)

    def test_gps_noise_reconstruct_can_disable_confidence_weighting(self):
        data_dir = self._write_ntpu_dataset()
        (data_dir / "scene_meta.json").write_text(
            json.dumps({"center_lat": 24.0, "center_lon": 121.0, "area_m": 512.0, "grid_res": 128}),
            encoding="utf-8",
        )
        model_path = self.artifact_dir / "best_iss_reconstruction_model.pth"
        model_path.write_bytes(b"model")
        gps_path = self.root / "gps.csv"
        gps_path.write_text(
            "time_stamp,lat,lon,alt\n2026-05-27T12:00:00Z,24.0,121.0,0",
            encoding="utf-8",
        )
        noise_path = self.root / "noise.csv"
        noise_path.write_text(
            "time_stamp,noise_floor_db\n2026-05-27T12:00:00.500Z,-70.0",
            encoding="utf-8",
        )

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
                return np.ones((128, 128), dtype=np.float32)

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

        from app.iss_unet_service import ISSUNetCFARParams, reconstruct_iss_unet, resolve_scene_dataset

        dataset = resolve_scene_dataset("NTPU", scene_dir=self.scene_dir)

        with patch("app.iss_unet_service.resolve_scene_dataset", return_value=dataset):
            with patch("app.iss_unet_service.MODEL_ARTIFACT_PATH", model_path):
                with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
                    with patch.dict(sys.modules, {"torch": fake_torch}):
                        with patch("app.iss_unet_service._load_model", return_value=(FakeModel(), "cpu")):
                            with patch("app.iss_unet_service._render_reconstructed_png", return_value=b"reconstructed"):
                                with patch("app.iss_unet_service._render_comparison_png", return_value=b"comparison"):
                                    result = reconstruct_iss_unet(
                                        "NTPU",
                                        cfar=ISSUNetCFARParams(enabled=False),
                                        mode="gps_n",
                                        gps_csv=gps_path,
                                        noise_csv=noise_path,
                                        focus_sampling_points=False,
                                    )

        saved = np.load(self.output_dir / "iss_unet_ntpu_gps_n_reconstructed.npy")
        self.assertAlmostEqual(float(saved[0, 0]), -35.0, places=4)
        self.assertEqual(result["metrics"]["confidence_applied"], False)

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
