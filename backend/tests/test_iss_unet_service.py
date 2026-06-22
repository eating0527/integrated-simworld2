import asyncio
import io
import json
import shutil
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import matplotlib.image as mpimg
import matplotlib.axes
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

    def test_dataset_resolver_uses_requested_pixel_size(self):
        data_dir = self._write_ntpu_dataset()
        shape = (256, 256)
        np.save(data_dir / "building_height_256.npy", np.zeros(shape, dtype=np.float32))
        np.save(data_dir / "sionna_dss_256.npy", np.full(shape, -100.0, dtype=np.float32))
        np.save(data_dir / "sionna_iss_256.npy", np.full(shape, -95.0, dtype=np.float32))
        np.save(data_dir / "sionna_tss_256.npy", np.full(shape, -90.0, dtype=np.float32))
        from app.iss_unet_service import resolve_scene_dataset

        dataset = resolve_scene_dataset("NTPU", scene_dir=self.scene_dir, pixel_size_m=2)

        self.assertTrue(dataset.available)
        self.assertEqual(dataset.files["building"].name, "building_height_256.npy")
        self.assertEqual(dataset.grid_res, 256)
        self.assertEqual(dataset.pixel_size_m, 2.0)

    def test_load_scene_arrays_accepts_512_resolution(self):
        data_dir = self._write_ntpu_dataset()
        shape = (512, 512)
        np.save(data_dir / "building_height_512.npy", np.zeros(shape, dtype=np.float32))
        np.save(data_dir / "sionna_dss_512.npy", np.full(shape, -100.0, dtype=np.float32))
        np.save(data_dir / "sionna_iss_512.npy", np.full(shape, -95.0, dtype=np.float32))
        np.save(data_dir / "sionna_tss_512.npy", np.full(shape, -90.0, dtype=np.float32))
        from app.iss_unet_service import load_scene_arrays, resolve_scene_dataset

        arrays = load_scene_arrays(resolve_scene_dataset("NTPU", scene_dir=self.scene_dir, pixel_size_m=1))

        self.assertEqual(arrays["building"].shape, shape)
        self.assertEqual(arrays["iss"].shape, shape)

    def test_ntpu_fallback_center_matches_frontend_origin(self):
        self._write_ntpu_dataset()
        from app.iss_real import resolve_scene_center as resolve_route_scene_center
        from app.iss_unet_service import _scene_center, resolve_scene_dataset

        dataset = resolve_scene_dataset("NTPU", scene_dir=self.scene_dir)

        self.assertEqual(_scene_center(dataset), (24.943476, 121.370054))
        self.assertEqual(resolve_route_scene_center(dataset), (24.943476, 121.370054))

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

    def test_upload_endpoint_returns_409_for_missing_dataset(self):
        from app.iss_unet_service import OUTPUT_DIR

        with patch("app.iss_unet_service.SCENE_DIR", self.scene_dir):
            with patch("app.iss_unet_service.OUTPUT_DIR", OUTPUT_DIR):
                response = asyncio.run(
                    main.iss_unet_reconstruct_upload_post(
                        scene="NYCU",
                        mode="gps",
                        sparse_ratio=0.2,
                        seed=41,
                        cfar_enabled=True,
                        apply_building_mask=True,
                        gps_file=None,
                        noise_file=None,
                    )
                )

        self.assertEqual(response.status_code, 409)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(set(payload["missing_files"]), REQUIRED_FILES)

    def test_upload_endpoint_accepts_form_pixel_size_string(self):
        data_dir = self._write_ntpu_dataset()
        shape = (512, 512)
        np.save(data_dir / "building_height_512.npy", np.zeros(shape, dtype=np.float32))
        np.save(data_dir / "sionna_dss_512.npy", np.full(shape, -100.0, dtype=np.float32))
        np.save(data_dir / "sionna_iss_512.npy", np.full(shape, -95.0, dtype=np.float32))
        np.save(data_dir / "sionna_tss_512.npy", np.full(shape, -90.0, dtype=np.float32))
        captured = {}

        def fake_reconstruct_iss_unet(**kwargs):
            captured.update(kwargs)
            return {
                "scene": "NTPU",
                "mode": "gps_n",
                "sparse_ratio": 0.2,
                "images": {"reconstructed": "/api/iss-unet/images/fake.png"},
                "metrics": {"grid_res": 512, "output_shape": [512, 512]},
                "options": {},
            }

        with patch.object(main, "SCENE_DIR", self.scene_dir):
            with patch("app.iss_unet_service.reconstruct_iss_unet", side_effect=fake_reconstruct_iss_unet):
                response_status, response_body = asyncio.run(
                    self._post_multipart_asgi(
                        "/api/iss-unet/reconstruct/upload",
                        {
                            "scene": "ntpu",
                            "mode": "gps_n",
                            "sparse_ratio": "0.2",
                            "pixel_size_m": "1",
                            "seed": "41",
                            "cfar_enabled": "true",
                            "apply_building_mask": "true",
                            "devices_json": "",
                        },
                    )
                )

        self.assertEqual(response_status, 200)
        payload = json.loads(response_body.decode("utf-8"))
        self.assertTrue(payload["success"])
        self.assertEqual(captured["pixel_size_m"], 1)

    async def _post_multipart_asgi(self, path: str, fields: dict[str, str]) -> tuple[int, bytes]:
        boundary = "----iss-unet-test-boundary"
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode("utf-8")
            )
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(chunks)
        messages: list[dict] = []
        sent = False

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)

        await main.app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode("ascii"),
                "query_string": b"",
                "headers": [
                    (b"host", b"testserver"),
                    (b"content-type", f"multipart/form-data; boundary={boundary}".encode("ascii")),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
                "client": ("127.0.0.1", 12345),
                "server": ("testserver", 80),
            },
            receive,
            send,
        )
        status = next(message["status"] for message in messages if message["type"] == "http.response.start")
        response_body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        return status, response_body

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

    def test_reconstruct_without_model_returns_clipped_sionna_map(self):
        from app.iss_unet_service import ISS_MAX_DBM, _reconstruct_without_model

        arrays = {"iss": np.array([[-200.0, -60.0], [-20.0, -35.0]], dtype=np.float32)}

        result = _reconstruct_without_model(arrays, "sim")
        expected = np.array([[-140.0, -60.0], [-20.0, -35.0]], dtype=np.float32)
        expected[expected > ISS_MAX_DBM] = ISS_MAX_DBM

        np.testing.assert_allclose(result, expected)

    def test_gpsn_rss_normalization_uses_bundle_range(self):
        from app.iss_unet_service import _denormalize_gpsn_rss, _normalize_gpsn_rss

        values = np.array([-120.0, -90.0, -52.5, -15.0, 0.0], dtype=np.float32)

        norm = _normalize_gpsn_rss(values)
        expected = np.array([0.0, 0.0, 0.5, 1.0, 1.0], dtype=np.float32)

        np.testing.assert_allclose(norm, expected)
        np.testing.assert_allclose(
            _denormalize_gpsn_rss(np.array([0.0, 0.5, 1.0], dtype=np.float32)),
            np.array([-90.0, -52.5, -15.0], dtype=np.float32),
        )

    def test_build_gpsn_unet_input_uses_expected_channel_order(self):
        from app.iss_unet_service import build_gpsn_unet_input

        sparse_values = np.full((128, 128), -90.0, dtype=np.float32)
        sparse_values[3, 4] = -52.5
        sparse_mask = np.zeros((128, 128), dtype=np.float32)
        sparse_mask[3, 4] = 1.0
        building = np.zeros((128, 128), dtype=np.float32)
        building[3, 4] = 30.0

        inputs = build_gpsn_unet_input(sparse_values, sparse_mask, building)

        self.assertEqual(inputs.shape, (3, 128, 128))
        self.assertAlmostEqual(float(inputs[0, 3, 4]), 0.5)
        self.assertAlmostEqual(float(inputs[1, 3, 4]), 1.0)
        self.assertAlmostEqual(float(inputs[2, 3, 4]), 0.5)
        self.assertAlmostEqual(float(inputs[0, 0, 0]), 0.0)

    def test_build_gpsn_unet_input_rejects_shape_mismatch(self):
        from app.iss_unet_service import build_gpsn_unet_input

        with self.assertRaisesRegex(ValueError, "same shape"):
            build_gpsn_unet_input(
                np.zeros((128, 128), dtype=np.float32),
                np.zeros((64, 64), dtype=np.float32),
                np.zeros((128, 128), dtype=np.float32),
            )

    def test_run_gpsn_unet_denormalizes_model_output(self):
        from app.iss_unet_service import _run_gpsn_unet

        class FakeModel:
            def __call__(self, tensor):
                import torch

                return torch.full((1, 1, 128, 128), 0.5, dtype=torch.float32, device=tensor.device)

        sparse_values = np.full((128, 128), -90.0, dtype=np.float32)
        sparse_mask = np.zeros((128, 128), dtype=np.float32)
        building = np.zeros((128, 128), dtype=np.float32)

        with patch("app.iss_unet_service._load_gpsn_model", return_value=(FakeModel(), "cpu"), create=True):
            result = _run_gpsn_unet(sparse_values, sparse_mask, building, "cpu")

        self.assertEqual(result.shape, (128, 128))
        self.assertAlmostEqual(float(result[0, 0]), -52.5)

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

    def test_gps_noise_mode_reports_projection_and_duplicate_metrics(self):
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
                    "2026-05-27T12:00:01Z,24.0,121.0,0",
                    "2026-05-27T12:00:02Z,24.0000359324461,121.000039446262,0",
                ]
            ),
            encoding="utf-8",
        )
        noise_path = self.root / "noise.csv"
        noise_path.write_text(
            "\n".join(
                [
                    "time_stamp,noise_floor_db",
                    "2026-05-27T12:00:00.100Z,-90.0",
                    "2026-05-27T12:00:01.100Z,-80.0",
                    "2026-05-27T12:00:02.100Z,-70.0",
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

        self.assertEqual(result.metrics["aligned_noise"], 3)
        self.assertEqual(result.metrics["valid_projected_points"], 3)
        self.assertEqual(result.metrics["used_samples"], 2)
        self.assertEqual(result.metrics["duplicate_points"], 1)
        self.assertEqual(result.metrics["valid_projected_noise_dbm"], [-90.0, -80.0, -70.0])

    def test_gpsn_artifacts_include_reconstructed_sparse_and_cfar_inputs(self):
        from app.iss_unet_service import ISSUNetCFARParams, _build_iss_unet_artifacts, resolve_scene_dataset

        data_dir = self._write_ntpu_dataset()
        (data_dir / "scene_meta.json").write_text(
            json.dumps({"center_lat": 24.0, "center_lon": 121.0, "area_m": 512.0, "grid_res": 128}),
            encoding="utf-8",
        )
        model_path = self.artifact_dir / "best_iss_reconstruction_model.pth"
        model_path.write_bytes(b"model")
        gps_csv = "\n".join(["time_stamp,lat,lon,alt", "2026-05-27T12:00:00Z,24.0,121.0,0"])
        noise_csv = "\n".join(["time_stamp,noise_floor_db", "2026-05-27T12:00:00.100Z,-75.0"])

        with patch("app.iss_unet_service.GPSN_MODEL_ARTIFACT_PATH", model_path):
            with patch("app.iss_unet_service._run_gpsn_unet", return_value=np.full((128, 128), -75.0, dtype=np.float32)):
                artifacts = _build_iss_unet_artifacts(
                    scene="NTPU",
                    sparse_ratio=0.2,
                    cfar=ISSUNetCFARParams(enabled=True),
                    seed=41,
                    device="cpu",
                    mode="gps_n",
                    gps_csv=gps_csv,
                    noise_csv=noise_csv,
                    apply_building_mask=True,
                    scene_dir=self.scene_dir,
                    devices=None,
                    scene_xml_path=None,
                )

        self.assertEqual(artifacts.dataset.scene, "NTPU")
        self.assertEqual(artifacts.mode, "gps_n")
        self.assertEqual(int(artifacts.sparse_mask.sum()), 1)
        self.assertEqual(float(artifacts.sparse_values_dbm[64, 64]), -75.0)
        self.assertEqual(tuple(artifacts.reconstructed_iss.shape), (128, 128))
        self.assertIsNotNone(artifacts.cfar_result)

    def test_reconstruct_result_enriches_cfar_clusters_with_grid_world_coordinates(self):
        from app.iss_unet_service import ISSUNetCFARParams, reconstruct_iss_unet

        data_dir = self._write_ntpu_dataset()
        (data_dir / "scene_meta.json").write_text(
            json.dumps({"center_lat": 24.0, "center_lon": 121.0, "area_m": 512.0, "grid_res": 128}),
            encoding="utf-8",
        )
        fake_cfar = {
            "detection_map": np.zeros((128, 128), dtype=np.float32),
            "threshold_map": np.full((128, 128), -80.0, dtype=np.float32),
            "detections": [{"row": 64, "col": 64, "power_dbm": -42.5}],
            "clusters": [
                {
                    "peak_pixel_row": 64,
                    "peak_pixel_col": 64,
                    "peak_power_dbm": -42.5,
                    "mean_power_dbm": -45.0,
                    "size": 9,
                }
            ],
        }

        with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
            with patch("app.iss_unet_service._cfar_detect", return_value=fake_cfar):
                result = reconstruct_iss_unet(
                    scene="NTPU",
                    sparse_ratio=0.2,
                    cfar=ISSUNetCFARParams(enabled=True),
                    seed=41,
                    device="cpu",
                    mode="sim",
                    scene_dir=self.scene_dir,
                )

        grid = result["cfar"]["grid"]
        self.assertEqual(grid["rows"], 128)
        self.assertEqual(grid["cols"], 128)
        self.assertEqual(grid["area_m"], 512.0)
        self.assertEqual(grid["pixel_size_m"], 4.0)
        self.assertEqual(grid["grid_bounds"]["min_x"], -256.0)
        self.assertEqual(grid["grid_bounds"]["max_x"], 256.0)
        self.assertEqual(grid["grid_bounds"]["min_y"], -256.0)
        self.assertEqual(grid["grid_bounds"]["max_y"], 256.0)
        cluster = result["cfar"]["clusters"][0]
        self.assertEqual(cluster["peak_pixel_row"], 64)
        self.assertEqual(cluster["peak_pixel_col"], 64)
        self.assertAlmostEqual(cluster["world_x"], 2.0)
        self.assertAlmostEqual(cluster["world_z"], 2.0)
        self.assertAlmostEqual(cluster["lat"], 24.0 - (2.0 / 111320.0))
        self.assertAlmostEqual(cluster["lon"], 121.0 + (2.0 / (111320.0 * np.cos(np.radians(24.0)))))
        overlay = result["overlay"]
        self.assertEqual(overlay["kind"], "reconstructed_iss")
        self.assertEqual(overlay["url"], f"/api/iss-unet/grids/{Path(result['files']['reconstructed_npy']).name}")
        self.assertEqual(overlay["rows"], 128)
        self.assertEqual(overlay["cols"], 128)
        self.assertEqual(overlay["area_m"], 512.0)
        self.assertEqual(overlay["width_m"], 512.0)
        self.assertEqual(overlay["height_m"], 512.0)
        self.assertEqual(overlay["grid_bounds"]["min_x"], -256.0)
        self.assertEqual(overlay["grid_bounds"]["max_x"], 256.0)
        self.assertEqual(overlay["vmin_dbm"], -90.0)
        self.assertEqual(overlay["vmax_dbm"], -15.0)

    def test_reconstruct_result_uses_grid_bounds_for_cfar_and_overlay_world_coordinates(self):
        from app.iss_unet_service import ISSUNetCFARParams, reconstruct_iss_unet

        data_dir = self._write_ntpu_dataset()
        grid_bounds = {
            "min_x": -300.0,
            "max_x": 293.0,
            "min_y": -260.0,
            "max_y": 270.0,
            "pixel_size_x_m": 593.0 / 128.0,
            "pixel_size_y_m": 530.0 / 128.0,
        }
        (data_dir / "scene_meta.json").write_text(
            json.dumps({"center_lat": 24.0, "center_lon": 121.0, "area_m": 512.0, "grid_res": 128, "grid_bounds": grid_bounds}),
            encoding="utf-8",
        )
        fake_cfar = {
            "detection_map": np.zeros((128, 128), dtype=np.float32),
            "threshold_map": np.full((128, 128), -80.0, dtype=np.float32),
            "detections": [{"row": 0, "col": 127, "power_dbm": -42.5}],
            "clusters": [
                {
                    "peak_pixel_row": 0,
                    "peak_pixel_col": 127,
                    "peak_power_dbm": -42.5,
                    "mean_power_dbm": -45.0,
                    "size": 9,
                }
            ],
        }

        with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
            with patch("app.iss_unet_service._cfar_detect", return_value=fake_cfar):
                result = reconstruct_iss_unet(
                    scene="NTPU",
                    sparse_ratio=0.2,
                    cfar=ISSUNetCFARParams(enabled=True),
                    seed=41,
                    device="cpu",
                    mode="sim",
                    scene_dir=self.scene_dir,
                )

        grid = result["cfar"]["grid"]
        self.assertEqual(grid["rows"], 128)
        self.assertEqual(grid["cols"], 128)
        self.assertEqual(grid["grid_bounds"], grid_bounds)
        self.assertAlmostEqual(grid["pixel_size_x_m"], 593.0 / 128.0)
        self.assertAlmostEqual(grid["pixel_size_y_m"], 530.0 / 128.0)
        cluster = result["cfar"]["clusters"][0]
        self.assertAlmostEqual(cluster["world_x"], 293.0 - (593.0 / 128.0) / 2.0)
        self.assertAlmostEqual(cluster["world_z"], -(270.0 - (530.0 / 128.0) / 2.0))
        self.assertEqual(result["overlay"]["grid_bounds"], grid_bounds)
        self.assertAlmostEqual(result["overlay"]["width_m"], 593.0)
        self.assertAlmostEqual(result["overlay"]["height_m"], 530.0)

    def test_grid_endpoint_returns_reconstructed_overlay_json(self):
        from app.iss_unet_service import OUTPUT_DIR

        values = np.array(
            [
                [-80.0, -70.0],
                [-60.0, -50.0],
            ],
            dtype=np.float32,
        )
        filename = "iss_unet_ntpu_ratio_20_reconstructed.npy"
        np.save(self.output_dir / filename, values)

        with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
            response = asyncio.run(main.iss_unet_grid_get(filename))

        self.assertEqual(response["success"], True)
        self.assertEqual(response["rows"], 2)
        self.assertEqual(response["cols"], 2)
        self.assertEqual(response["area_m"], 512.0)
        self.assertEqual(response["min_dbm"], -80.0)
        self.assertEqual(response["max_dbm"], -50.0)
        self.assertEqual(response["values"], [[-80.0, -70.0], [-60.0, -50.0]])

    def test_grid_endpoint_rejects_illegal_or_missing_filename(self):
        from app.iss_unet_service import OUTPUT_DIR

        with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
            invalid = asyncio.run(main.iss_unet_grid_get("../secret.npy"))
            missing = asyncio.run(main.iss_unet_grid_get("iss_unet_ntpu_ratio_20_reconstructed.npy"))

        self.assertEqual(invalid.status_code, 404)
        self.assertEqual(missing.status_code, 404)

    def test_cfar_render_uses_fixed_minus_90_to_minus_15_range(self):
        from app.iss_unet_service import _render_cfar_png

        captured = []
        original_imshow = matplotlib.axes.Axes.imshow

        def capture_imshow(axis, *args, **kwargs):
            captured.append(kwargs)
            return original_imshow(axis, *args, **kwargs)

        cfar_result = {
            "detection_map": np.zeros((4, 4), dtype=np.float32),
            "threshold_map": np.full((4, 4), -10.0, dtype=np.float32),
            "detections": [],
            "clusters": [],
        }

        with patch.object(matplotlib.axes.Axes, "imshow", new=capture_imshow):
            _render_cfar_png(
                np.full((4, 4), -20.0, dtype=np.float32),
                np.ones((4, 4), dtype=np.float32),
                np.zeros((4, 4), dtype=np.float32),
                cfar_result,
            )

        self.assertEqual(captured[0]["vmin"], -90.0)
        self.assertEqual(captured[0]["vmax"], -15.0)
        self.assertEqual(captured[3]["vmin"], -90.0)
        self.assertEqual(captured[3]["vmax"], -15.0)

    def test_iss_unet_power_panels_use_fixed_minus_90_to_minus_15_range(self):
        from app.iss_unet_service import _render_comparison_png, _render_reconstructed_png

        captured = []
        original_imshow = matplotlib.axes.Axes.imshow

        def capture_imshow(axis, *args, **kwargs):
            captured.append(kwargs)
            return original_imshow(axis, *args, **kwargs)

        arrays = {
            "building": np.zeros((4, 4), dtype=np.float32),
            "iss": np.full((4, 4), -45.0, dtype=np.float32),
        }
        reconstructed = np.full((4, 4), -50.0, dtype=np.float32)
        sparse_mask = np.ones((4, 4), dtype=np.float32)
        outdoor_mask = np.ones((4, 4), dtype=np.float32)

        with patch.object(matplotlib.axes.Axes, "imshow", new=capture_imshow):
            _render_reconstructed_png(reconstructed)
            _render_comparison_png(arrays, reconstructed, sparse_mask, outdoor_mask, 0.2)

        self.assertEqual(captured[0]["vmin"], -90.0)
        self.assertEqual(captured[0]["vmax"], -15.0)
        self.assertEqual(captured[2]["vmin"], -90.0)
        self.assertEqual(captured[2]["vmax"], -15.0)
        self.assertEqual(captured[3]["vmin"], -90.0)
        self.assertEqual(captured[3]["vmax"], -15.0)
        self.assertEqual(captured[4]["vmin"], -90.0)
        self.assertEqual(captured[4]["vmax"], -15.0)

    def test_gpsn_statistics_rows_include_ten_chinese_metrics(self):
        from app.iss_unet_service import ISSUNetArtifacts, ISSUNetCFARParams, SceneDataset
        from app.iss_unet_stats_service import build_gpsn_statistics_rows

        sparse_mask = np.zeros((4, 4), dtype=np.float32)
        sparse_mask[1, 1] = 1.0
        sparse_mask[2, 2] = 1.0
        outdoor_mask = np.ones((4, 4), dtype=np.float32)
        sparse_values = np.full((4, 4), -140.0, dtype=np.float32)
        sparse_values[1, 1] = -80.0
        sparse_values[2, 2] = -60.0
        arrays = {
            "iss": np.array(
                [
                    [-100.0, -99.0, -98.0, -97.0],
                    [-96.0, -85.0, -94.0, -93.0],
                    [-92.0, -91.0, -65.0, -89.0],
                    [-88.0, -87.0, -86.0, -84.0],
                ],
                dtype=np.float32,
            ),
            "building": np.zeros((4, 4), dtype=np.float32),
            "dss": np.full((4, 4), -110.0, dtype=np.float32),
            "tss": np.full((4, 4), -100.0, dtype=np.float32),
        }
        reconstructed = np.full((4, 4), -70.0, dtype=np.float32)
        artifacts = ISSUNetArtifacts(
            dataset=SceneDataset("NTPU", self.root, {}, []),
            mode="gps_n",
            mode_label="Noise with GPS",
            sparse_ratio=0.2,
            arrays=arrays,
            inputs=np.zeros((5, 4, 4), dtype=np.float32),
            sparse_mask=sparse_mask,
            outdoor_mask=outdoor_mask,
            sparse_values_dbm=sparse_values,
            reconstructed_iss=reconstructed,
            real_metrics={
                "aligned_noise": 3,
                "skipped_noise": 1,
                "out_of_bounds": 0,
                "indoor_filtered": 1,
                "valid_projected_points": 2,
                "duplicate_points": 0,
                "used_samples": 2,
                "valid_projected_noise_dbm": [-80.0, -60.0],
            },
            confidence_metrics={},
            model_inference=True,
            cfar_params=ISSUNetCFARParams(enabled=True),
            cfar_result={
                "clusters": [{"peak_pixel_row": 2, "peak_pixel_col": 2, "peak_power_dbm": -50.0, "mean_power_dbm": -55.0, "size": 1}],
                "detections": [],
                "detection_map": np.zeros((4, 4), dtype=np.float32),
                "threshold_map": np.zeros((4, 4), dtype=np.float32),
            },
        )

        rows = build_gpsn_statistics_rows(artifacts)

        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0]["variable"], "GPS/Noise 時間對齊率")
        self.assertEqual(rows[3]["variable"], "採樣點地圖覆蓋率")
        self.assertTrue(rows[0]["value"].endswith("%"))
        self.assertIn("室外地圖", rows[3]["meaning"])
        self.assertEqual(rows[-1]["variable"], "CFAR 熱點定位誤差")

    def test_render_gpsn_statistics_table_png_returns_png_bytes(self):
        from app.iss_unet_stats_service import render_statistics_table_png

        rows = [
            {"variable": "GPS/Noise 時間對齊率", "value": "75.00%", "meaning": "noise.csv 與 gps.csv 的時間同步品質"},
            {"variable": "有效量測率", "value": "66.67%", "meaning": "真實量測成功落在虛擬場景有效區域的比例"},
        ]

        png = render_statistics_table_png(rows)

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_gpsn_statistics_table_uses_scene_title_and_indicator_header(self):
        from app.iss_unet_stats_service import _statistics_column_labels, _statistics_table_title

        self.assertEqual(_statistics_table_title("NTPU"), "NTPU 統計資料")
        self.assertEqual(_statistics_table_title("nycu"), "NYCU 統計資料")
        self.assertEqual(_statistics_column_labels()[0], "統計指標")

    def test_save_gpsn_statistics_table_png_uses_scene_title(self):
        from app import iss_unet_stats_service

        captured = {}

        def fake_render(_rows, *, title):
            captured["title"] = title
            return b"\x89PNG\r\n\x1a\n"

        rows = [{"variable": "metric", "value": "1", "meaning": "meaning"}]
        with patch.object(iss_unet_stats_service, "OUTPUT_DIR", self.output_dir):
            with patch.object(iss_unet_stats_service, "render_statistics_table_png", side_effect=fake_render):
                path = iss_unet_stats_service.save_statistics_table_png("nycu", rows)

        self.assertEqual(captured["title"], "NYCU 統計資料")
        self.assertEqual(path.name, "iss_unet_nycu_gps_n_statistics.png")

    def test_render_gpsn_statistics_table_png_uses_paper_table_style(self):
        from app.iss_unet_stats_service import render_statistics_table_png
        from matplotlib.figure import Figure

        rows = [
            {"variable": "GPS/Noise alignment", "value": "75.00%", "meaning": "alignment rate"},
            {"variable": "Valid measurement rate", "value": "66.67%", "meaning": "valid projected samples"},
            {"variable": "Sample map coverage", "value": "12.34%", "meaning": "coverage over outdoor pixels"},
        ]

        title_positions = []
        original_text = Figure.text

        def capture_text(fig, x, y, text, *args, **kwargs):
            title_positions.append((x, y, text))
            return original_text(fig, x, y, text, *args, **kwargs)

        with patch.object(Figure, "text", new=capture_text):
            png = render_statistics_table_png(rows, title="NTPU 統計資料")
        image = mpimg.imread(io.BytesIO(png))
        rgb = image[:, :, :3]
        height = rgb.shape[0]

        cyan_tinted_pixels = (
            (rgb[:, :, 1] > rgb[:, :, 0] + 0.03)
            & (rgb[:, :, 2] > rgb[:, :, 0] + 0.03)
            & (rgb[:, :, 0] > 0.65)
        )
        top_dark_pixels = np.all(rgb[: int(height * 0.18), :, :] < 0.45, axis=2)

        self.assertEqual(title_positions[0][2], "NTPU 統計資料")
        self.assertGreater(title_positions[0][1], 0.5)
        self.assertLess(int(cyan_tinted_pixels.sum()), 100)
        self.assertGreater(int(top_dark_pixels.sum()), 100)
        self.assertLess(height, 500)

    def test_statistics_upload_endpoint_uses_uploaded_gpsn_csvs_and_returns_table_image(self):
        captured = {}

        class FakeUpload:
            def __init__(self, data: bytes):
                self.data = data

            async def read(self):
                return self.data

        def fake_generate(**kwargs):
            captured.update(kwargs)
            return {
                "scene": "NTPU",
                "mode": "gps_n",
                "statistics": {
                    "rows": [{"variable": "採樣點地圖覆蓋率", "value": "0.01%", "meaning": "採樣點覆蓋整張室外地圖的比例"}],
                },
                "images": {"statistics": "/api/iss-unet/images/iss_unet_ntpu_gps_n_statistics.png"},
                "files": {"statistics_png": str(self.output_dir / "iss_unet_ntpu_gps_n_statistics.png")},
            }

        self._write_ntpu_dataset()
        gps_bytes = b"time_stamp,lat,lon,alt\n2026-05-27T12:00:00Z,24.0,121.0,0\n"
        noise_bytes = b"time_stamp,noise_floor_db\n2026-05-27T12:00:00.100Z,-75.0\n"

        with patch("app.iss_unet_stats_service.generate_gpsn_statistics", side_effect=fake_generate):
            response = asyncio.run(
                main.iss_unet_statistics_upload_post(
                    scene="NTPU",
                    apply_building_mask=True,
                    devices_json="[]",
                    gps_file=FakeUpload(gps_bytes),
                    noise_file=FakeUpload(noise_bytes),
                )
            )

        self.assertEqual(response["success"], True)
        self.assertEqual(captured["mode"], "gps_n")
        self.assertEqual(captured["gps_csv"], gps_bytes)
        self.assertEqual(captured["noise_csv"], noise_bytes)
        self.assertEqual(response["statistics"]["rows"][0]["variable"], "採樣點地圖覆蓋率")

    def test_single_input_unet_accepts_three_channels(self):
        import torch

        from app.model_unet_single import UNet

        model = UNet(in_channels=3, out_channels=1)
        model.eval()
        with torch.no_grad():
            output = model(torch.zeros((1, 3, 128, 128), dtype=torch.float32))

        self.assertEqual(tuple(output.shape), (1, 1, 128, 128))

    def test_reconstruct_request_accepts_zero_sparse_ratio(self):
        req = main.ISSUNetReconstructRequest(scene="NTPU", sparse_ratio=0.0)

        self.assertEqual(req.sparse_ratio, 0.0)

    def test_reconstruct_request_does_not_expose_focus_sampling_points_toggle(self):
        req = main.ISSUNetReconstructRequest(scene="NTPU", focus_sampling_points=False)

        self.assertFalse(hasattr(req, "focus_sampling_points"))

    def test_reconstruct_request_accepts_devices(self):
        req = main.ISSUNetReconstructRequest(
            scene="NTPU",
            devices=[
                {
                    "name": "jam-0",
                    "role": "jammer",
                    "x": 12.0,
                    "y": 34.0,
                    "z": 56.0,
                    "power_dbm": 77.0,
                }
            ],
        )

        self.assertEqual(len(req.devices), 1)
        self.assertEqual(req.devices[0].role, "jammer")
        self.assertEqual(req.devices[0].x, 12.0)

    def test_reconstruct_endpoint_forwards_devices_for_sim(self):
        self._write_ntpu_dataset()
        from app.iss_unet_service import resolve_scene_dataset

        dataset = resolve_scene_dataset("NTPU", scene_dir=self.scene_dir)
        captured = {}

        def fake_reconstruct_iss_unet(**kwargs):
            captured.update(kwargs)
            return {
                "scene": "NTPU",
                "mode": "sim",
                "mode_label": "Sim",
                "sparse_ratio": 0.2,
                "metrics": {},
                "images": {},
                "files": {},
                "cfar": {"detections": 0, "clusters": []},
            }

        req = main.ISSUNetReconstructRequest(
            scene="NTPU",
            devices=[
                main.DeviceIn(name="jam-0", role="jammer", x=11.0, y=22.0, z=33.0, power_dbm=44.0),
            ],
        )

        with patch("app.iss_unet_service.resolve_scene_dataset", return_value=dataset):
            with patch("app.iss_unet_service.reconstruct_iss_unet", side_effect=fake_reconstruct_iss_unet):
                response = asyncio.run(main.iss_unet_reconstruct_post(req))

        self.assertEqual(response["success"], True)
        self.assertEqual(len(captured["devices"]), 1)
        self.assertEqual(captured["devices"][0].role, "jammer")
        self.assertEqual(captured["devices"][0].x, 11.0)

    def test_reconstruct_endpoint_forwards_pixel_size(self):
        self._write_ntpu_dataset()
        from app.iss_unet_service import resolve_scene_dataset

        dataset = resolve_scene_dataset("NTPU", scene_dir=self.scene_dir)
        captured = {}

        def fake_reconstruct_iss_unet(**kwargs):
            captured.update(kwargs)
            return {
                "scene": "NTPU",
                "mode": "sim",
                "mode_label": "Sim",
                "sparse_ratio": 0.2,
                "metrics": {},
                "images": {},
                "files": {},
                "cfar": {"detections": 0, "clusters": []},
            }

        req = main.ISSUNetReconstructRequest(scene="NTPU", pixel_size_m=2)

        with patch("app.iss_unet_service.resolve_scene_dataset", return_value=dataset):
            with patch("app.iss_unet_service.reconstruct_iss_unet", side_effect=fake_reconstruct_iss_unet):
                response = asyncio.run(main.iss_unet_reconstruct_post(req))

        self.assertEqual(response["success"], True)
        self.assertEqual(captured["pixel_size_m"], 2.0)

    def test_upload_endpoint_does_not_forward_focus_sampling_points_toggle(self):
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
                        gps_file=None,
                        noise_file=None,
                    )
                )

        self.assertEqual(response["success"], True)
        self.assertNotIn("focus_sampling_points", captured)

    def test_upload_endpoint_forwards_pixel_size(self):
        self._write_ntpu_dataset()
        from app.iss_unet_service import resolve_scene_dataset

        dataset = resolve_scene_dataset("NTPU", scene_dir=self.scene_dir)
        captured = {}

        def fake_reconstruct_iss_unet(**kwargs):
            captured.update(kwargs)
            return {
                "scene": "NTPU",
                "mode": "gps",
                "mode_label": "GPS",
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
                        mode="gps",
                        pixel_size_m=1,
                        gps_file=None,
                        noise_file=None,
                    )
                )

        self.assertEqual(response["success"], True)
        self.assertEqual(captured["pixel_size_m"], 1.0)

    def test_upload_endpoint_forwards_devices_for_gps_modes(self):
        self._write_ntpu_dataset()
        from app.iss_unet_service import resolve_scene_dataset

        dataset = resolve_scene_dataset("NTPU", scene_dir=self.scene_dir)
        captured = {}

        def fake_reconstruct_iss_unet(**kwargs):
            captured.update(kwargs)
            return {
                "scene": "NTPU",
                "mode": "gps",
                "mode_label": "GPS",
                "sparse_ratio": 0.2,
                "metrics": {},
                "images": {},
                "files": {},
                "cfar": {"detections": 0, "clusters": []},
            }

        devices_json = json.dumps(
            [
                {
                    "name": "jam-0",
                    "role": "jammer",
                    "x": 111.0,
                    "y": 0.0,
                    "z": 22.0,
                    "power_dbm": 55.0,
                }
            ]
        )

        with patch("app.iss_unet_service.resolve_scene_dataset", return_value=dataset):
            with patch("app.iss_unet_service.reconstruct_iss_unet", side_effect=fake_reconstruct_iss_unet):
                response = asyncio.run(
                    main.iss_unet_reconstruct_upload_post(
                        scene="NTPU",
                        mode="gps",
                        devices_json=devices_json,
                        gps_file=None,
                        noise_file=None,
                    )
                )

        self.assertEqual(response["success"], True)
        self.assertEqual(len(captured["devices"]), 1)
        self.assertEqual(captured["devices"][0].role, "jammer")
        self.assertEqual(captured["devices"][0].x, 111.0)

    def test_sim_reconstruction_does_not_load_unet_model(self):
        self._write_ntpu_dataset()
        from app.iss_unet_service import ISSUNetCFARParams, reconstruct_iss_unet

        model_path = self.artifact_dir / "legacy_model.pth"
        model_path.write_bytes(b"legacy")

        with patch("app.iss_unet_service.MODEL_ARTIFACT_PATH", model_path):
            with patch("app.iss_unet_service.SCENE_DIR", self.scene_dir):
                with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
                    with patch(
                        "app.iss_unet_service._load_model",
                        side_effect=AssertionError("UNet should not load for sim"),
                    ):
                        with patch("app.iss_unet_service._render_reconstructed_png", return_value=b"reconstructed"):
                            with patch("app.iss_unet_service._render_comparison_png", return_value=b"comparison"):
                                result = reconstruct_iss_unet(
                                    scene="NTPU",
                                    mode="sim",
                                    cfar=ISSUNetCFARParams(enabled=False),
                                )

        self.assertEqual(result["mode"], "sim")
        self.assertFalse(result["metrics"]["model_inference"])

    def test_gps_reconstruction_does_not_load_unet_model(self):
        self._write_ntpu_dataset()
        from app.iss_real import RouteSparseResult
        from app.iss_unet_service import ISSUNetCFARParams, reconstruct_iss_unet

        model_path = self.artifact_dir / "legacy_model.pth"
        model_path.write_bytes(b"legacy")
        shape = (128, 128)
        sparse_mask = np.zeros(shape, dtype=np.float32)
        sparse_mask[4, 5] = 1.0
        outdoor_mask = np.ones(shape, dtype=np.float32)
        sparse_values = np.full(shape, -140.0, dtype=np.float32)
        sparse_values[4, 5] = -60.0
        route_sample = RouteSparseResult(
            sparse_mask=sparse_mask,
            outdoor_mask=outdoor_mask,
            iss_sparse_dbm=sparse_values,
            inputs=np.zeros((5, 128, 128), dtype=np.float32),
            metrics={
                "mode": "gps",
                "route_points": 1,
                "used_samples": 1,
                "aligned_noise": 0,
                "skipped_noise": 0,
                "sample_used": False,
            },
        )

        with patch("app.iss_unet_service.MODEL_ARTIFACT_PATH", model_path):
            with patch("app.iss_unet_service.SCENE_DIR", self.scene_dir):
                with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
                    with patch("app.iss_real.create_route_sparse_sample", return_value=route_sample):
                        with patch(
                            "app.iss_unet_service._load_model",
                            side_effect=AssertionError("UNet should not load for gps"),
                        ):
                            with patch("app.iss_unet_service._render_reconstructed_png", return_value=b"reconstructed"):
                                with patch("app.iss_unet_service._render_comparison_png", return_value=b"comparison"):
                                    result = reconstruct_iss_unet(
                                        scene="NTPU",
                                        mode="gps",
                                        cfar=ISSUNetCFARParams(enabled=False),
                                    )

        self.assertEqual(result["mode"], "gps")
        self.assertFalse(result["metrics"]["model_inference"])

    def test_sim_reconstruction_uses_live_iss_when_devices_provided(self):
        self._write_ntpu_dataset()
        from app.iss_unet_service import ISSUNetCFARParams, reconstruct_iss_unet

        live_iss = np.full((128, 128), -61.0, dtype=np.float32)
        live_iss[0, 0] = -44.0
        devices = [{"name": "jam-0", "role": "jammer", "x": 1.0, "y": 2.0, "z": 3.0, "power_dbm": 77.0}]
        captured = {}

        def fake_live_scene_arrays(*, scene_xml_path, devices, cell_size, samples_per_tx, target_shape, area_m):
            captured["scene_xml_path"] = scene_xml_path
            captured["devices"] = devices
            captured["cell_size"] = cell_size
            captured["samples_per_tx"] = samples_per_tx
            captured["target_shape"] = target_shape
            captured["area_m"] = area_m
            return {"iss": live_iss}

        with patch("app.iss_unet_service.SCENE_DIR", self.scene_dir):
            with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
                with patch(
                    "app.iss_unet_service.compute_live_scene_arrays",
                    side_effect=fake_live_scene_arrays,
                    create=True,
                ):
                    with patch("app.iss_unet_service._render_reconstructed_png", return_value=b"reconstructed"):
                        with patch("app.iss_unet_service._render_comparison_png", return_value=b"comparison"):
                            result = reconstruct_iss_unet(
                                scene="NTPU",
                                mode="sim",
                                cfar=ISSUNetCFARParams(enabled=False),
                                devices=devices,
                                scene_xml_path=self.scene_dir / "NTPU" / "NTPU.xml",
                            )

        reconstructed = np.load(result["files"]["reconstructed_npy"])
        self.assertEqual(captured["scene_xml_path"], self.scene_dir / "NTPU" / "NTPU.xml")
        self.assertEqual(captured["devices"], devices)
        self.assertEqual(captured["cell_size"], 4.0)
        self.assertEqual(captured["samples_per_tx"], 100000000)
        self.assertEqual(captured["target_shape"], (128, 128))
        self.assertEqual(captured["area_m"], 512.0)
        np.testing.assert_allclose(reconstructed, live_iss)

    def test_gps_reconstruction_uses_live_iss_when_devices_provided(self):
        self._write_ntpu_dataset()
        from app.iss_real import RouteSparseResult
        from app.iss_unet_service import ISSUNetCFARParams, reconstruct_iss_unet

        shape = (128, 128)
        sparse_mask = np.zeros(shape, dtype=np.float32)
        outdoor_mask = np.ones(shape, dtype=np.float32)
        route_sample = RouteSparseResult(
            sparse_mask=sparse_mask,
            outdoor_mask=outdoor_mask,
            iss_sparse_dbm=np.full(shape, -90.0, dtype=np.float32),
            inputs=np.zeros((5, 128, 128), dtype=np.float32),
            metrics={
                "mode": "gps",
                "route_points": 1,
                "used_samples": 0,
                "aligned_noise": 0,
                "skipped_noise": 0,
                "sample_used": False,
            },
        )
        live_iss = np.full(shape, -58.0, dtype=np.float32)
        devices = [{"name": "jam-0", "role": "jammer", "x": 1.0, "y": 2.0, "z": 3.0, "power_dbm": 77.0}]
        captured = {}

        def fake_live_scene_arrays(*, scene_xml_path, devices, cell_size, samples_per_tx, target_shape, area_m):
            captured["scene_xml_path"] = scene_xml_path
            captured["devices"] = devices
            return {"iss": live_iss}

        def fake_route_sample(arrays, *args, **kwargs):
            captured["route_iss"] = arrays["iss"].copy()
            return route_sample

        with patch("app.iss_unet_service.SCENE_DIR", self.scene_dir):
            with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
                with patch("app.iss_unet_service.compute_live_scene_arrays", side_effect=fake_live_scene_arrays, create=True):
                    with patch("app.iss_real.create_route_sparse_sample", side_effect=fake_route_sample):
                        with patch("app.iss_unet_service._render_reconstructed_png", return_value=b"reconstructed"):
                            with patch("app.iss_unet_service._render_comparison_png", return_value=b"comparison"):
                                reconstruct_iss_unet(
                                    scene="NTPU",
                                    mode="gps",
                                    cfar=ISSUNetCFARParams(enabled=False),
                                    devices=devices,
                                    scene_xml_path=self.scene_dir / "NTPU" / "NTPU.xml",
                                )

        self.assertEqual(captured["scene_xml_path"], self.scene_dir / "NTPU" / "NTPU.xml")
        self.assertEqual(captured["devices"], devices)
        np.testing.assert_allclose(captured["route_iss"], live_iss)

    def test_live_radio_map_resamples_to_top_down_scene_grid(self):
        from app.iss_unet_service import _resample_live_radio_map_to_scene_grid

        values = np.full((4, 4), -100.0, dtype=np.float32)
        values[0, 1] = -40.0
        x_coords = np.array([-1.5, -0.5, 0.5, 1.5], dtype=np.float32)
        y_coords = np.array([-1.5, -0.5, 0.5, 1.5], dtype=np.float32)

        result = _resample_live_radio_map_to_scene_grid(
            values,
            x_coords=x_coords,
            y_coords=y_coords,
            target_shape=(4, 4),
            area_m=4.0,
        )

        self.assertEqual(np.unravel_index(int(np.argmax(result)), result.shape), (3, 1))
        self.assertAlmostEqual(float(result[3, 1]), -40.0)

    def test_reconstruct_uses_explicit_scene_dir_for_dataset_lookup(self):
        self._write_ntpu_dataset()
        from app.iss_unet_service import ISSUNetCFARParams, reconstruct_iss_unet

        with self.assertRaises(FileNotFoundError):
            reconstruct_iss_unet(
                scene="NYCU",
                scene_dir=self.scene_dir,
                mode="sim",
                cfar=ISSUNetCFARParams(enabled=False),
            )

    def test_gpsn_reconstruction_uses_new_gpsn_model_loader(self):
        self._write_ntpu_dataset()
        from app.iss_real import RouteSparseResult
        from app.iss_unet_service import ISSUNetCFARParams, reconstruct_iss_unet

        shape = (128, 128)
        sparse_mask = np.zeros(shape, dtype=np.float32)
        sparse_mask[10, 11] = 1.0
        outdoor_mask = np.ones(shape, dtype=np.float32)
        sparse_values = np.full(shape, -90.0, dtype=np.float32)
        sparse_values[10, 11] = -55.0
        route_sample = RouteSparseResult(
            sparse_mask=sparse_mask,
            outdoor_mask=outdoor_mask,
            iss_sparse_dbm=sparse_values,
            inputs=np.zeros((5, 128, 128), dtype=np.float32),
            metrics={
                "mode": "gps_n",
                "route_points": 1,
                "used_samples": 1,
                "aligned_noise": 1,
                "skipped_noise": 0,
                "sample_used": False,
            },
        )

        class FakeModel:
            def __call__(self, tensor):
                import torch

                return torch.full((1, 1, 128, 128), 0.5, dtype=torch.float32, device=tensor.device)

        with patch("app.iss_unet_service.SCENE_DIR", self.scene_dir):
            with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
                with patch("app.iss_real.create_route_sparse_sample", return_value=route_sample):
                    with patch(
                        "app.iss_unet_service._load_model",
                        side_effect=AssertionError("legacy UNet should not load for gps_n"),
                    ):
                        with patch(
                            "app.iss_unet_service._load_gpsn_model",
                            return_value=(FakeModel(), "cpu"),
                            create=True,
                        ):
                            with patch("app.iss_unet_service._render_reconstructed_png", return_value=b"reconstructed"):
                                with patch("app.iss_unet_service._render_comparison_png", return_value=b"comparison"):
                                    result = reconstruct_iss_unet(
                                        scene="NTPU",
                                        mode="gps_n",
                                        cfar=ISSUNetCFARParams(enabled=False),
                                    )

        self.assertEqual(result["mode"], "gps_n")
        self.assertTrue(result["metrics"]["model_inference"])

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

    def test_gps_noise_reconstruct_does_not_apply_focus_sampling_confidence(self):
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

        from app.iss_unet_service import ISSUNetCFARParams, reconstruct_iss_unet, resolve_scene_dataset

        dataset = resolve_scene_dataset("NTPU", scene_dir=self.scene_dir)

        with patch("app.iss_unet_service.SCENE_DIR", self.scene_dir):
            with patch("app.iss_unet_service.resolve_scene_dataset", return_value=dataset):
                with patch("app.iss_unet_service.GPSN_MODEL_ARTIFACT_PATH", model_path):
                    with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
                        with patch.dict(sys.modules, {"torch": fake_torch}):
                            with patch("app.iss_unet_service._load_gpsn_model", return_value=(FakeModel(), "cpu")):
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
        self.assertAlmostEqual(float(saved[64, 64]), -15.0, places=4)
        self.assertAlmostEqual(float(saved[0, 0]), -15.0, places=4)
        self.assertEqual(float(saved[0, 0]), float(captured["render_reconstructed"][0, 0]))
        self.assertEqual(float(saved[0, 0]), float(captured["render_comparison"][0, 0]))
        self.assertEqual(float(saved[0, 0]), float(captured["cfar_signal"][0, 0]))
        self.assertEqual(result["metrics"]["confidence_applied"], False)

    def test_gps_noise_reconstruct_has_no_focus_sampling_toggle(self):
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
            with patch("app.iss_unet_service.GPSN_MODEL_ARTIFACT_PATH", model_path):
                with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
                    with patch.dict(sys.modules, {"torch": fake_torch}):
                        with patch("app.iss_unet_service._load_gpsn_model", return_value=(FakeModel(), "cpu")):
                            with patch("app.iss_unet_service._render_reconstructed_png", return_value=b"reconstructed"):
                                with patch("app.iss_unet_service._render_comparison_png", return_value=b"comparison"):
                                    result = reconstruct_iss_unet(
                                        "NTPU",
                                        cfar=ISSUNetCFARParams(enabled=False),
                                        mode="gps_n",
                                        gps_csv=gps_path,
                                        noise_csv=noise_path,
                                    )

        saved = np.load(self.output_dir / "iss_unet_ntpu_gps_n_reconstructed.npy")
        self.assertAlmostEqual(float(saved[0, 0]), -15.0, places=4)
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
        self.assertEqual(meta["grid_bounds"]["min_x"], -256.0)
        self.assertEqual(meta["grid_bounds"]["max_x"], 256.0)
        self.assertEqual(meta["grid_bounds"]["pixel_size_x_m"], 4.0)
        self.assertEqual(meta["outputs"]["iss"], "sionna_iss.npy")

    def test_rasterize_building_height_from_ply_uses_mesh_footprint_not_bbox(self):
        scene_root = self.scene_dir / "CUSTOM"
        scene_root.mkdir(parents=True)
        (scene_root / "building.ply").write_text("ply placeholder", encoding="utf-8")
        scene_xml = scene_root / "CUSTOM.xml"
        scene_xml.write_text(
            """
            <scene>
              <shape type="ply" id="mesh-building">
                <string name="filename" value="building.ply"/>
              </shape>
            </scene>
            """,
            encoding="utf-8",
        )
        vertices = np.array(
            [
                [-4.0, -4.0, 0.0],
                [4.0, -4.0, 0.0],
                [-4.0, 4.0, 0.0],
                [-4.0, -4.0, 10.0],
                [4.0, -4.0, 10.0],
                [-4.0, 4.0, 10.0],
            ],
            dtype=np.float32,
        )
        faces = np.array(
            [
                [0, 1, 2],
                [3, 5, 4],
            ],
            dtype=np.int64,
        )
        fake_mesh = types.SimpleNamespace(vertices=vertices, faces=faces)
        fake_trimesh = types.SimpleNamespace(load_mesh=lambda *_args, **_kwargs: fake_mesh)

        from app.iss_unet_dataset_service import rasterize_building_height_from_ply

        with patch.dict(sys.modules, {"trimesh": fake_trimesh}):
            building_map = rasterize_building_height_from_ply(scene_xml, grid_res=8, area_m=8.0)

        self.assertEqual(building_map.shape, (8, 8))
        self.assertGreater(building_map[6, 1], 9.0)
        self.assertEqual(float(building_map[1, 6]), 0.0)

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
