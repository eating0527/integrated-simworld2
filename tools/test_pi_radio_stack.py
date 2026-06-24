import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PiRadioStackContractTests(unittest.TestCase):
    def test_stack_tracks_mission_and_finalization_states(self):
        stack = (ROOT / "tools" / "pi_radio_stack.sh").read_text(encoding="utf-8")

        self.assertIn('MISSION_ID="${MISSION_ID:?MISSION_ID is required}"', stack)
        self.assertIn('MISSION_STATE_DIR="${MISSION_STATE_DIR:-/var/lib/simworld/capture}"', stack)
        self.assertIn('write_state "running"', stack)
        self.assertIn('write_state "finalizing"', stack)
        self.assertIn('write_state "${final_state}" "upload_pending"', stack)
        self.assertIn('write_state "${final_state}" "uploaded"', stack)

    def test_service_loads_runtime_environment_and_allows_finalization(self):
        unit = (
            ROOT / "tools" / "pi_radio_stack.service.example"
        ).read_text(encoding="utf-8")

        self.assertIn("EnvironmentFile=-/run/simworld/usrp.env", unit)
        self.assertIn("KillMode=control-group", unit)
        self.assertIn("TimeoutStopSec=0", unit)
        self.assertIn("Restart=no", unit)


if __name__ == "__main__":
    unittest.main()
