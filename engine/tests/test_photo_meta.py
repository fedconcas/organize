import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from organize_gui.photo_meta import SIPS, parse_exif_date, read_meta
from organize_gui.service import EngineService
from organize_gui.store import Store

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "resources" / "images-with-exif"
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000030000000208060000009a3a4c6d"
    "0000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


class PhotoMetaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_exif_date_camera_and_gps(self):
        meta = read_meta(FIXTURES / "3.jpg", use_tools=False)
        self.assertEqual(meta["dateSource"], "taken")
        self.assertEqual(meta["dateTaken"], "2017-08-12T12:23:36")
        self.assertEqual(meta["camera"], "iPhone 6s")
        self.assertEqual((meta["width"], meta["height"]), (10, 10))
        lat, lon = meta["gps"]
        self.assertAlmostEqual(lat, 45.8806, places=3)
        self.assertAlmostEqual(lon, 10.89, places=2)

    def test_no_exif_falls_back_to_modified_date(self):
        path = self.root / "plain.png"
        path.write_bytes(PNG_1X1)
        os.utime(path, (1_600_000_000, 1_600_000_000))
        meta = read_meta(path, use_tools=False)
        self.assertEqual(meta["dateSource"], "modified")
        self.assertTrue(meta["dateTaken"].startswith("2020-09-1"))
        self.assertEqual((meta["width"], meta["height"]), (3, 2))
        self.assertIsNone(meta["gps"])
        self.assertIsNone(meta["camera"])

    def test_unparsable_exif_date_falls_back(self):
        data = (FIXTURES / "1.jpg").read_bytes().replace(b"2018:09:29 18:52:46", b"0000:00:00 00:00:00")
        path = self.root / "broken.jpg"
        path.write_bytes(data)
        meta = read_meta(path, use_tools=False)
        self.assertEqual(meta["dateSource"], "modified")
        self.assertIsNone(parse_exif_date("garbage"))
        self.assertIsNone(parse_exif_date("1800:01:01 00:00:00"))

    def test_screenshot_name_hint(self):
        path = self.root / "Screenshot 2025-06-01 at 10.00.00.png"
        path.write_bytes(PNG_1X1)
        self.assertTrue(read_meta(path, use_tools=False)["isScreenshot"])
        self.assertFalse(read_meta(FIXTURES / "1.jpg", use_tools=False)["isScreenshot"])

    @unittest.skipUnless(sys.platform == "darwin" and os.path.isfile(SIPS), "needs macOS sips")
    def test_heic_dimensions_through_sips(self):
        heic = self.root / "photo.heic"
        made = subprocess.run([SIPS, "-s", "format", "heic", str(FIXTURES / "4.jpg"), "--out", str(heic)],
                              capture_output=True, timeout=30)
        if made.returncode != 0 or not heic.exists():
            self.skipTest("this macOS cannot encode HEIC")
        meta = read_meta(heic)
        self.assertTrue(meta["width"] and meta["height"])
        self.assertIn(meta["dateSource"], {"taken", "modified"})
        self.assertIsNotNone(meta["dateTaken"])


class ByDateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "in"
        self.target = self.root / "out"
        self.source.mkdir()
        self.target.mkdir()
        shutil.copyfile(FIXTURES / "2.jpg", self.source / "camera.jpg")
        (self.source / "plain.png").write_bytes(PNG_1X1)
        os.utime(self.source / "plain.png", (1_600_000_000, 1_600_000_000))
        self.service = EngineService(self.root / "data")

    def tearDown(self):
        self.temp.cleanup()

    def profile(self, **parameters):
        return {"id": "p", "name": "Photos", "presetType": "by-date", "sourceFolders": [str(self.source)],
                "targetFolder": str(self.target), "includeSubfolders": False, "parameters": parameters,
                "schemaVersion": 1}

    def test_date_taken_is_the_default_with_modified_fallback(self):
        plan = self.service.create_plan(self.profile())
        items = {Path(item["source_path"]).name: item for item in plan["items"]}
        camera = items["camera.jpg"]
        self.assertEqual(camera["metadata"]["dateSource"], "taken")
        self.assertIn(str(Path("2018") / "04" / "camera.jpg"), camera["target_path"])
        plain = items["plain.png"]
        self.assertEqual(plain["metadata"]["dateSource"], "modified")
        self.assertIn(str(Path("2020") / "09"), plain["target_path"])
        self.assertNotIn("gps", json.dumps([item["metadata"] for item in plan["items"]]).lower())

    def test_modified_date_can_still_be_chosen(self):
        os.utime(self.source / "camera.jpg", (1_600_000_000, 1_600_000_000))
        plan = self.service.create_plan(self.profile(dateSource="modified"))
        camera = next(item for item in plan["items"] if item["source_path"].endswith("camera.jpg"))
        self.assertEqual(camera["metadata"]["dateSource"], "modified")
        self.assertIn(str(Path("2020") / "09"), camera["target_path"])

    def test_invalid_date_source_is_rejected(self):
        issues = self.service.validate(self.profile(dateSource="exif"))["issues"]
        self.assertIn("parameters.dateSource", {issue.get("field") for issue in issues})


class RemovedPresetMigrationTests(unittest.TestCase):
    def test_similar_photo_profiles_are_dropped(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "journal.db"
            db = sqlite3.connect(str(path))
            db.executescript("""
                CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
                INSERT INTO schema_migrations VALUES (2, 'then');
                CREATE TABLE profiles (profile_id TEXT PRIMARY KEY, profile_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE saved_profiles (profile_id TEXT PRIMARY KEY, profile_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL);
            """)
            for table, columns in (("profiles", "?, ?, 'a', 'a'"), ("saved_profiles", "?, ?, 'a'")):
                db.execute("INSERT INTO %s VALUES (%s)" % (table, columns),
                           ("old", json.dumps({"id": "old", "presetType": "similar-photos"})))
                db.execute("INSERT INTO %s VALUES (%s)" % (table, columns),
                           ("keep", json.dumps({"id": "keep", "presetType": "by-date"})))
            db.commit()
            db.close()
            store = Store(path)
            self.assertEqual([item["id"] for item in store.saved_profiles()], ["keep"])
            self.assertEqual(store.last_profile()["id"], "keep")
            versions = {row[0] for row in store.connection().execute("SELECT version FROM schema_migrations")}
            self.assertIn(3, versions)


if __name__ == "__main__":
    unittest.main()
