import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from app.main import CFRAdvancedParams, CFRPlotRequest, sionna_cfr_plot_post


DEVICES = [
    {
        "name": "tx-0",
        "role": "tx",
        "x": -75,
        "y": 0,
        "z": 75,
        "power_dbm": 60,
    },
    {
        "name": "rx-0",
        "role": "rx",
        "x": -30,
        "y": 10,
        "z": 175,
        "power_dbm": None,
    },
]


class CFRAdvancedParamsTests(unittest.TestCase):
    def test_request_uses_default_advanced_values_when_omitted(self):
        req = CFRPlotRequest(scene="NTPU", modulation="qpsk", devices=DEVICES)

        self.assertEqual(req.advanced.constellation_batch_size, 1)
        self.assertEqual(req.advanced.ofdm_subcarriers, 76)
        self.assertEqual(req.advanced.subcarrier_spacing_hz, 30000)
        self.assertEqual(req.advanced.ebn0_db, 20)
        self.assertEqual(req.advanced.ray_tracing_max_depth, 10)

    def test_request_accepts_custom_advanced_values(self):
        req = CFRPlotRequest(
            scene="NTPU",
            modulation="16qam",
            devices=DEVICES,
            advanced={
                "constellation_batch_size": 50,
                "ofdm_subcarriers": 256,
                "subcarrier_spacing_hz": 60000,
                "ebn0_db": 12,
                "ray_tracing_max_depth": 5,
            },
        )

        self.assertEqual(req.advanced.constellation_batch_size, 50)
        self.assertEqual(req.advanced.ofdm_subcarriers, 256)
        self.assertEqual(req.advanced.subcarrier_spacing_hz, 60000)
        self.assertEqual(req.advanced.ebn0_db, 12)
        self.assertEqual(req.advanced.ray_tracing_max_depth, 5)

    def test_advanced_values_are_bounded(self):
        invalid_payloads = [
            {"constellation_batch_size": 0},
            {"constellation_batch_size": 101},
            {"ofdm_subcarriers": 15},
            {"ofdm_subcarriers": 1025},
            {"subcarrier_spacing_hz": 999},
            {"subcarrier_spacing_hz": 240001},
            {"ebn0_db": -1},
            {"ebn0_db": 61},
            {"ray_tracing_max_depth": 0},
            {"ray_tracing_max_depth": 11},
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    CFRAdvancedParams(**payload)

    def test_cfr_endpoint_forwards_advanced_values(self):
        req = CFRPlotRequest(
            scene="NTPU",
            modulation="qpsk",
            devices=DEVICES,
            advanced={
                "constellation_batch_size": 10,
                "ofdm_subcarriers": 128,
                "subcarrier_spacing_hz": 45000,
                "ebn0_db": 18,
                "ray_tracing_max_depth": 3,
            },
        )

        with patch("app.sionna_service.generate_cfr_plot", new_callable=AsyncMock) as mock_generate:
            with patch("app.main.os.path.isfile", return_value=True):
                with patch("app.main.FileResponse", return_value=object()):
                    with patch("app.main._resolve_sionna_scene_xml", return_value=Path("static/scenes/NTPU/NTPU.xml")):
                        asyncio.run(sionna_cfr_plot_post(req))

        mock_generate.assert_awaited_once()
        kwargs = mock_generate.await_args.kwargs
        self.assertEqual(kwargs["constellation_batch_size"], 10)
        self.assertEqual(kwargs["ofdm_subcarriers"], 128)
        self.assertEqual(kwargs["subcarrier_spacing_hz"], 45000)
        self.assertEqual(kwargs["ebn0_db"], 18)
        self.assertEqual(kwargs["ray_tracing_max_depth"], 3)
        self.assertTrue(kwargs["output_path"].replace("\\", "/").endswith("/static/maps/ntpu/cfr_plot.png"))


if __name__ == "__main__":
    unittest.main()
