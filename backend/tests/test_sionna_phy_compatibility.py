import inspect
import sys
import types
import unittest
from unittest.mock import patch

from app import sionna_service


class SionnaPhyCompatibilityTests(unittest.TestCase):
    def test_load_sionna_does_not_require_rt_subcarrier_frequencies(self):
        """Verify _load_sionna returns 6 items without rt.subcarrier_frequencies."""
        fake_mitsuba = types.ModuleType("mitsuba")
        fake_mitsuba.variant = lambda: "llvm_ad_mono_polarized"
        fake_mitsuba.set_variant = lambda variant: None

        fake_rt = types.ModuleType("sionna.rt")
        fake_rt.load_scene = object()
        fake_rt.Transmitter = object()
        fake_rt.Receiver = object()
        fake_rt.PlanarArray = object()
        fake_rt.PathSolver = object()
        fake_rt.RadioMapSolver = object()

        with patch.dict(sys.modules, {"mitsuba": fake_mitsuba, "sionna.rt": fake_rt}):
            loaded = sionna_service._load_sionna()

        self.assertEqual(len(loaded), 6)
        self.assertIs(loaded[0], fake_rt.load_scene)
        self.assertIs(loaded[-1], fake_rt.RadioMapSolver)

    def test_torch_subcarrier_frequencies_exists(self):
        """Verify _torch_subcarrier_frequencies function is callable."""
        self.assertTrue(callable(sionna_service._torch_subcarrier_frequencies))

    def test_channel_plot_generators_unpack_load_sionna_signature(self):
        """Verify channel plot generators accept _load_sionna's 6-item return signature."""
        for func in (
            sionna_service.generate_cfr_plot,
            sionna_service.generate_doppler_plot,
            sionna_service.generate_channel_response,
        ):
            source = inspect.getsource(func)
            self.assertIn("load_scene, SionnaTX, SionnaRX, PlanarArray, PathSolver, _ = _load_sionna()", source)
            self.assertNotIn("subcarrier_frequencies, _ = _load_sionna()", source)


if __name__ == "__main__":
    unittest.main()
