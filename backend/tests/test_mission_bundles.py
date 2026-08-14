import json
import asyncio
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from app import main


class MissionBundleImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.incoming = self.root / "incoming"
        self.incoming.mkdir()
        self.patch_incoming = patch.object(main, "INCOMING_CSV_DIR", self.incoming)
        self.patch_incoming.start()

    def tearDown(self):
        self.patch_incoming.stop()
        self.tmp.cleanup()

    def test_headers_drive_artifact_health_without_reading_rows(self):
        mission = self.incoming / "flight-1"
        mission.mkdir()
        (mission / "gps.csv").write_text(
            "time_stamp,lat,lon,alt,alt_mode\nnot-a-row,still,not,validated,here\n",
            encoding="utf-8",
        )
        (mission / "noise.csv").write_text(
            "noise_floor_db,time_stamp,extra\nnot-a-row,not-validated,ignored\n",
            encoding="utf-8",
        )

        bundle = main._mission_bundle(mission)

        self.assertIsNotNone(bundle)
        assert bundle is not None
        self.assertEqual(bundle["labels"], ["[GPS]", "[NOISE]"])
        self.assertTrue(bundle["gps"]["healthy"])
        self.assertTrue(bundle["noise"]["healthy"])
        self.assertTrue((mission / main.BUNDLE_MANIFEST_FILENAME).exists())

    def test_metadata_only_is_listed_and_empty_directory_is_skipped(self):
        metadata = self.incoming / "metadata-only"
        metadata.mkdir()
        (metadata / "bundle.json").write_text(json.dumps({"scene": "NTPU"}), encoding="utf-8")
        empty = self.incoming / "empty"
        empty.mkdir()

        bundles, errors = main._scan_mission_bundles()

        self.assertEqual(errors, [])
        self.assertEqual([item["mission_id"] for item in bundles], ["metadata-only"])
        self.assertEqual(bundles[0]["labels"], ["[N/A]"])
        self.assertTrue(bundles[0]["metadata_only"])

    def test_manifest_sha_changes_without_touching_applied_snapshot_metadata(self):
        mission = self.incoming / "flight-2"
        mission.mkdir()
        path = mission / "gps.csv"
        path.write_text("time_stamp,lat,lon,alt,alt_mode\n1,1,1,1,relative\n", encoding="utf-8")
        first = main._mission_bundle(mission)
        path.write_text("time_stamp,lat,lon,alt,alt_mode\n2,2,2,2,relative\n", encoding="utf-8")
        second = main._mission_bundle(mission)

        assert first is not None and second is not None
        self.assertNotEqual(first["gps"]["sha256"], second["gps"]["sha256"])
        self.assertTrue(second["gps"]["changed"])
        manifest = json.loads((mission / main.BUNDLE_MANIFEST_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(manifest["artifacts"]["gps"]["sha256"], second["gps"]["sha256"])
        self.assertEqual(first["import_state"], "created")
        self.assertEqual(second["import_state"], "updated")
        self.assertEqual(main._mission_bundle(mission)["import_state"], "unchanged")

    def test_artifact_endpoint_rejects_unsafe_mission_and_kind(self):
        mission = self.incoming / "safe"
        mission.mkdir()
        (mission / "gps.csv").write_text(
            "time_stamp,lat,lon,alt,alt_mode\n",
            encoding="utf-8",
        )

        valid = asyncio.run(main.get_mission_bundle_artifact("safe", "gps"))
        unsafe_id = asyncio.run(main.get_mission_bundle_artifact("..", "gps"))
        unsafe_kind = asyncio.run(main.get_mission_bundle_artifact("safe", "../capture"))

        self.assertEqual(valid.path, mission / "gps.csv")
        self.assertEqual(unsafe_id.status_code, 404)
        self.assertEqual(unsafe_kind.status_code, 404)


if __name__ == "__main__":
    unittest.main()
