import unittest

from app.coordinate_frame import (
    SceneFrame,
    enu_to_grid,
    enu_to_sionna,
    enu_to_three,
    gps_to_enu,
    grid_to_enu,
    scene_frame_from_metadata,
)


class CoordinateFrameTests(unittest.TestCase):
    def setUp(self):
        self.frame = SceneFrame(
            frame_id="scene-test",
            origin_lat=24.0,
            origin_lon=121.0,
            origin_alt_m=100.0,
        )

    def test_origin_and_axis_directions_are_stable(self):
        self.assertEqual(gps_to_enu(24.0, 121.0, 100.0, self.frame), (0.0, 0.0, 0.0))
        self.assertEqual(enu_to_three(10.0, 20.0, 30.0), (10.0, 30.0, -20.0))
        self.assertEqual(enu_to_sionna(10.0, 20.0, 30.0), (10.0, 20.0, 30.0))

    def test_altitude_modes_are_explicit(self):
        self.assertEqual(gps_to_enu(24.0, 121.0, 125.0, self.frame, "amsl"), (0.0, 0.0, 25.0))
        self.assertEqual(gps_to_enu(24.0, 121.0, 25.0, self.frame, "relative"), (0.0, 0.0, 25.0))

    def test_grid_round_trip_uses_north_to_south_rows(self):
        row, col = enu_to_grid(2.0, 254.0, 0.0, self.frame)
        self.assertEqual((row, col), (0, 64))
        east, north, up = grid_to_enu(row, col, self.frame)
        self.assertEqual((east, north, up), (2.0, 254.0, 0.0))

    def test_out_of_extent_is_not_clamped(self):
        result = enu_to_grid(300.0, 0.0, 0.0, self.frame)
        self.assertFalse(result.inside_extent)
        self.assertIsNone(result.row)
        self.assertIsNone(result.col)

    def test_inclusive_south_west_edges_clamp_to_last_grid_cell(self):
        result = enu_to_grid(-256.0, -256.0, 0.0, self.frame)
        self.assertEqual((result.row, result.col), (127, 0))
        self.assertTrue(result.inside_extent)

    def test_old_metadata_without_frame_is_rejected(self):
        with self.assertRaises(ValueError):
            scene_frame_from_metadata({"scene": "NTPU"})


if __name__ == "__main__":
    unittest.main()
