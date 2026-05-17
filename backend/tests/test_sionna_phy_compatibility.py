import sys
import types
import unittest
from unittest.mock import patch

import torch

from app import sionna_service


class SionnaPhyCompatibilityTests(unittest.TestCase):
    def test_torch_subcarrier_frequencies_uses_phy_channel_function(self):
        fake_channel = types.ModuleType("sionna.phy.channel")
        calls = []

        def fake_subcarrier_frequencies(num_subcarriers, subcarrier_spacing):
            calls.append((num_subcarriers, subcarrier_spacing))
            return torch.tensor([-15_000.0, 0.0, 15_000.0])

        fake_channel.subcarrier_frequencies = fake_subcarrier_frequencies

        with patch.dict(sys.modules, {"sionna.phy.channel": fake_channel}):
            freqs = sionna_service._torch_subcarrier_frequencies(3, 15_000.0, torch.device("cpu"))

        self.assertEqual(calls, [(3, 15_000.0)])
        self.assertTrue(torch.is_tensor(freqs))
        self.assertEqual(freqs.device.type, "cpu")
        self.assertEqual(freqs.dtype, torch.float32)

    def test_load_sionna_does_not_require_rt_subcarrier_frequencies(self):
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


if __name__ == "__main__":
    unittest.main()
