import os
import re
import shutil
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PiRadioStackContractTests(unittest.TestCase):
    def test_rx_only_defaults_do_not_start_tx_or_jammer(self):
        stack = (ROOT / "tools" / "pi_radio_stack.sh").read_text(encoding="utf-8")
        usrp_unit = (ROOT / "tools" / "pi_radio_stack.service.example").read_text(
            encoding="utf-8"
        )
        test_unit = (
            ROOT / "tools" / "pi_radio_stack.test.service.example"
        ).read_text(encoding="utf-8")

        self.assertEqual(
            self._started_roles(stack, usrp_unit),
            ["rx"],
        )
        self.assertEqual(
            self._started_roles(stack, test_unit),
            ["rx"],
        )

    def test_shell_contract_covers_rx_only_and_finalize_without_bash(self):
        stack = (ROOT / "tools" / "pi_radio_stack.sh").read_text(encoding="utf-8")

        contract = self._shell_contract(stack)

        self.assertEqual(contract["default_started_roles"], ["rx"])
        self.assertEqual(
            contract["finalize_missing_noise"],
            ('write_state "failed" "failed" "failed" "noise.csv is missing or empty"', 1),
        )
        self.assertEqual(
            contract["finalize_copy_failure"],
            ('write_state "failed" "failed" "failed" "failed to copy noise.csv"', 1),
        )
        self.assertEqual(contract["finalize_upload_states"], [])

    def test_shell_startup_plan_defaults_to_rx_only_without_bash(self):
        stack = (ROOT / "tools" / "pi_radio_stack.sh").read_text(encoding="utf-8")

        self.assertEqual(
            self._startup_commands(stack, {}),
            [("rx", "${PYTHON_BIN}", "${RX_SCRIPT}")],
        )

    def test_stack_tracks_rx_only_mission_contract(self):
        stack = (ROOT / "tools" / "pi_radio_stack.sh").read_text(encoding="utf-8")

        self.assertIn('MISSION_ID="${MISSION_ID:?MISSION_ID is required}"', stack)
        self.assertIn('MISSION_STATE_DIR="${MISSION_STATE_DIR:-/var/lib/simworld/capture}"', stack)
        self.assertIn('RX_SCRIPT="${RX_SCRIPT:?RX_SCRIPT is required}"', stack)
        self.assertIn('START_TX="${START_TX:-0}"', stack)
        self.assertIn('START_JAMMER="${START_JAMMER:-0}"', stack)
        self.assertIn('cp "${NOISE_CSV}" "${MISSION_NOISE_CSV}"', stack)
        self.assertIn('write_state "recording" "running"', stack)
        self.assertIn('write_state "finalizing_file"', stack)
        self.assertIn('write_state "upload_pending"', stack)
        self.assertNotIn('write_state "${final_state}" "uploaded"', stack)
        self.assertNotIn("chan_est_rx.py", stack)
        self.assertNotIn("chan_est_tx.py", stack)
        self.assertNotIn("noise.py", stack)

    def test_service_examples_match_usrp_and_test_modes(self):
        usrp_unit = (ROOT / "tools" / "pi_radio_stack.service.example").read_text(
            encoding="utf-8"
        )
        test_unit = (
            ROOT / "tools" / "pi_radio_stack.test.service.example"
        ).read_text(encoding="utf-8")

        self.assertIn("Environment=MODE=usrp", usrp_unit)
        self.assertIn("RX_SCRIPT=/home/user/rx_sampling/rx_no_gui.py", usrp_unit)
        self.assertIn("START_TX=0", usrp_unit)
        self.assertIn("START_JAMMER=0", usrp_unit)
        self.assertIn("EnvironmentFile=-/run/simworld/usrp.env", usrp_unit)
        self.assertIn("KillMode=control-group", usrp_unit)
        self.assertIn("TimeoutStopSec=20s", usrp_unit)
        self.assertIn("Restart=no", usrp_unit)

        self.assertIn("Environment=MODE=test", test_unit)
        self.assertIn(
            "RX_SCRIPT=/home/user/rx_sampling/rx_no_gui_test.py", test_unit
        )
        self.assertIn("START_TX=0", test_unit)
        self.assertIn("START_JAMMER=0", test_unit)
        self.assertIn("EnvironmentFile=-/run/simworld/usrp.env", test_unit)
        self.assertIn("KillMode=control-group", test_unit)
        self.assertIn("TimeoutStopSec=20s", test_unit)
        self.assertIn("Restart=no", test_unit)

    def test_finalize_keeps_mission_noise_copy_and_marks_upload_pending(self):
        bash = self._find_bash()
        if not bash:
            self.skipTest("bash is required for shell contract execution")
        bash_probe = self._probe_bash(bash)
        if bash_probe.returncode != 0:
            self.skipTest(
                f"bash is not usable in this environment: {bash} :: "
                f"{bash_probe.stderr.strip() or bash_probe.stdout.strip()}"
            )

        tmpdir = ROOT / "tmp_pi_stack_test"
        shutil.rmtree(tmpdir, ignore_errors=True)
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            mission_dir = tmpdir / "state"
            noise_csv = tmpdir / "noise.csv"
            upload_log = tmpdir / "upload.log"
            rx_script = tmpdir / "rx.py"
            upload_helper = tmpdir / "upload_fail.py"

            noise_csv.write_text("noise-data\n", encoding="utf-8")
            rx_script.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
            upload_helper.write_text(
                textwrap.dedent(
                    """
                    import os
                    import sys
                    from pathlib import Path

                    log_path = Path(os.environ["UPLOAD_LOG"])
                    with log_path.open("a", encoding="utf-8") as handle:
                        handle.write("upload\\n")
                    sys.exit(1)
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            mission_id = "mission_001"
            env = os.environ.copy()
            env.update(
                {
                    "MISSION_ID": mission_id,
                    "MISSION_STATE_DIR": self._bash_path(mission_dir),
                    "WORKDIR": self._bash_path(tmpdir),
                    "PYTHON_BIN": self._bash_path(Path(sys.executable)),
                    "RX_SCRIPT": self._bash_path(rx_script),
                    "NOISE_UPLOAD_HELPER": self._bash_path(upload_helper),
                    "NOISE_CSV": self._bash_path(noise_csv),
                    "UPLOAD_API_URL": "http://example.test/upload",
                    "UPLOAD_LOG": str(upload_log),
                }
            )

            completed = subprocess.run(
                [bash, self._bash_path(ROOT / "tools" / "pi_radio_stack.sh")],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            mission_path = mission_dir / mission_id
            mission_state = mission_path / "mission.json"
            self.assertTrue((mission_path / "noise.csv").exists())
            self.assertIn('"upload_state": "upload_pending"', mission_state.read_text(encoding="utf-8"))
            self.assertFalse(upload_log.exists())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_bash_probe_captures_windows_root_cause_when_unusable(self):
        bash = self._find_bash()
        if not bash:
            self.skipTest("no bash candidate found on this machine")

        bash_probe = self._probe_bash(bash)
        if bash_probe.returncode == 0:
            self.skipTest(f"bash is usable in this environment: {bash}")

        probe_text = f"{bash_probe.stdout}\n{bash_probe.stderr}"
        self.assertRegex(
            probe_text,
            r"(Win32 error 5|couldn't create signal pipe|CreateFileMapping)",
        )

    @staticmethod
    def _bash_path(path: Path) -> str:
        raw = str(path)
        if os.name != "nt":
            return raw
        drive, tail = os.path.splitdrive(raw)
        tail = tail.replace("\\", "/")
        if drive:
            return f"/{drive[0].lower()}{tail}"
        return tail

    @staticmethod
    def _find_bash() -> str | None:
        candidates = [
            Path(r"C:\Program Files\Git\bin\bash.exe"),
            Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
            Path(r"C:\Program Files (x86)\Git\bin\bash.exe"),
            Path(r"C:\Program Files (x86)\Git\usr\bin\bash.exe"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        bash = shutil.which("bash")
        if bash and "System32\\bash.exe" not in bash:
            return bash
        return None

    @staticmethod
    def _probe_bash(bash: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [bash, "-lc", "true"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )

    @staticmethod
    def _shell_contract(stack: str) -> dict[str, object]:
        return {
            "default_started_roles": PiRadioStackContractTests._started_roles(stack, ""),
            "default_startup_commands": PiRadioStackContractTests._startup_commands(
                stack, {}
            ),
            "finalize_missing_noise": (
                'write_state "failed" "failed" "failed" "noise.csv is missing or empty"',
                stack.count('write_state "failed" "failed" "failed" "noise.csv is missing or empty"'),
            ),
            "finalize_copy_failure": (
                'write_state "failed" "failed" "failed" "failed to copy noise.csv"',
                stack.count('write_state "failed" "failed" "failed" "failed to copy noise.csv"'),
            ),
            "finalize_upload_states": re.findall(
                r'write_state "\$\{final_state\}" "(?:uploaded|upload_pending)" "\$\{JOB_ERROR\}"',
                stack,
            ),
        }

    @staticmethod
    def _startup_commands(stack: str, env: dict[str, str]) -> list[tuple[str, str, str]]:
        commands = [("rx", "${PYTHON_BIN}", "${RX_SCRIPT}")]
        for role in ("TX", "JAMMER"):
            if PiRadioStackContractTests._role_enabled(stack, role, env):
                commands.append((role.lower(), "${PYTHON_BIN}", f"${{{role}_SCRIPT}}"))
        return commands

    @staticmethod
    def _started_roles(stack: str, unit: str) -> list[str]:
        env = {}
        for line in unit.splitlines():
            if not line.startswith("Environment="):
                continue
            payload = line.removeprefix("Environment=")
            if "=" not in payload:
                continue
            key, value = payload.split("=", 1)
            env[key] = value

        started = ["rx"]
        if PiRadioStackContractTests._role_enabled(stack, "TX", env):
            started.append("tx")
        if PiRadioStackContractTests._role_enabled(stack, "JAMMER", env):
            started.append("jammer")
        return started

    @staticmethod
    def _role_enabled(stack: str, role: str, env: dict[str, str]) -> bool:
        match = re.search(
            rf'{role}_SCRIPT="\$\{{{role}_SCRIPT:-[^}}]+\}}".*?'
            rf'START_{role}="\$\{{START_{role}:-([^}}]+)\}}".*?'
            rf'if \[\[ "\$\{{START_{role}\}}" == "1" \]\]; then\s+'
            rf'start_bg "{role.lower()}" "\$\{{PYTHON_BIN\}}" "\$\{{{role}_SCRIPT\}}"',
            stack,
            re.DOTALL,
        )
        if not match:
            raise AssertionError(f"missing {role} gate in wrapper")
        return env.get(f"START_{role}", match.group(1)) == "1"


if __name__ == "__main__":
    unittest.main()
