import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.iss_unet_service import compute_live_scene_arrays


class SionnaDeviceAdapterTests(unittest.TestCase):
    def test_live_scene_arrays_keeps_canonical_flat_devices_flat(self):
        devices = [{
            "name": "rx-0",
            "role": "rx",
            "east_m": 12.0,
            "north_m": -8.0,
            "up_m": 3.5,
        }]
        captured = {}

        def fake_compute_radio_maps(**kwargs):
            captured["devices"] = kwargs["devices"]
            values = np.zeros((2, 2), dtype=np.float32)
            return {
                "dss_dbm": values,
                "iss_dbm": values,
                "tss_dbm": values,
                "x_coords": np.array([0.0, 1.0]),
                "y_coords": np.array([0.0, 1.0]),
            }

        with patch("app.sionna_service_lite.compute_radio_maps", side_effect=fake_compute_radio_maps):
            compute_live_scene_arrays(scene_xml_path=Path("scene.xml"), devices=devices)

        self.assertEqual(captured["devices"], [{**devices[0], "power_dbm": None}])


if __name__ == "__main__":
    unittest.main()
