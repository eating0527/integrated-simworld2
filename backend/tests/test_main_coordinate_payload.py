import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main


class SimulateCoordinatePayloadTests(unittest.TestCase):
    def test_simulate_forwards_flat_enu_devices_to_map_generator(self):
        request = main.SimulateRequest(
            scene="NTPU",
            map_type="iss",
            devices=[
                main.DeviceIn(
                    name="rx-0",
                    role="rx",
                    enu={"east_m": 12.0, "north_m": -8.0, "up_m": 3.5},
                    power_dbm=9.0,
                )
            ],
        )

        with patch.object(main, "_resolve_sionna_scene_xml", return_value=Path("static/scenes/NTPU/NTPU.xml")):
            with patch.object(main.os, "makedirs"):
                with patch.object(main, "_run_generate_maps", return_value=b"png") as generate_maps:
                    response = asyncio.run(main.simulate(request))

        self.assertEqual(response.body, b"png")
        devices = generate_maps.call_args.args[1]
        self.assertEqual(devices, [{
            "name": "rx-0",
            "role": "rx",
            "east_m": 12.0,
            "north_m": -8.0,
            "up_m": 3.5,
            "power_dbm": 9.0,
        }])


if __name__ == "__main__":
    unittest.main()
