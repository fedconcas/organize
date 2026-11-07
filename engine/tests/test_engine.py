import os
import sys
import tempfile
import unittest
import zipfile
import json
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from organize_gui.errors import EngineError
from organize_gui.service import EngineService
from organize.__version__ import __version__ as organize_version


class EngineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "下载"
        self.target = self.root / "整理{资料}$"
        self.source.mkdir()
        self.target.mkdir()
        self.service = EngineService(self.root / "data")

    def tearDown(self):
        self.temp.cleanup()

    def profile(self, preset="by-type"):
        return {
            "id": "test-profile",
            "name": "测试方案",
            "presetType": preset,
            "sourceFolders": [str(self.source)],
            "targetFolder": str(self.target),
            "includeSubfolders": True,
            "parameters": {"categories": ["documents", "images", "other"], "olderThanDays": 90},
            "schemaVersion": 1,
        }

    def test_plan_execute_history_and_undo(self):
        source_file = self.source / "合同 预算.pdf"
        source_file.write_bytes(b"contract")
        plan = self.service.create_plan(self.profile())
        self.assertEqual(plan["summary"]["selected"], 1)
        item = plan["items"][0]
        self.assertIn("整理{资料}$", item["target_path"])

        result = self.service.execute(plan["plan_id"])
        self.assertEqual(result["status"], "completed")
        self.assertFalse(source_file.exists())
        moved = Path(item["target_path"])
        self.assertTrue(moved.exists())

        history = self.service.history()
        self.assertEqual(len(history), 1)
        preview = self.service.undo_preview(result["runId"])
        self.assertEqual(preview["items"][0]["state"], "ready")
        undone = self.service.undo(
            result["runId"], [preview["items"][0]["operationId"]]
        )
        self.assertEqual(undone["restored"], 1)
        self.assertTrue(source_file.exists())

    def test_version_and_plan_use_v3_core(self):
        source_file = self.source / "v3.pdf"
        source_file.write_bytes(b"v3")
        self.assertEqual(self.service.version()["organize"], organize_version)
        plan = self.service.create_plan(self.profile())
        self.assertEqual(plan["items"][0]["metadata"]["organizeCore"], organize_version)

    def test_target_conflict_is_renamed_during_planning(self):
        source_file = self.source / "报价单.pdf"
        source_file.write_text("new", encoding="utf-8")
        existing_dir = self.target / "Documents"
        existing_dir.mkdir()
        (existing_dir / "报价单.pdf").write_text("old", encoding="utf-8")
        plan = self.service.create_plan(self.profile())
        item = plan["items"][0]
        self.assertTrue(item["target_path"].endswith("报价单 2.pdf"))
        self.assertEqual(item["warning_code"], "TARGET_CONFLICT")

    def test_new_target_after_preview_invalidates_plan(self):
        source_file = self.source / "a.pdf"
        source_file.write_text("a", encoding="utf-8")
        plan = self.service.create_plan(self.profile())
        destination = Path(plan["items"][0]["target_path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("race", encoding="utf-8")
        with self.assertRaises(EngineError) as caught:
            self.service.execute(plan["plan_id"])
        self.assertEqual(caught.exception.code, "PLAN_CHANGED")
        self.assertTrue(source_file.exists())

    def test_temporary_download_is_skipped(self):
        (self.source / "movie.mp4.crdownload").write_bytes(b"partial")
        plan = self.service.create_plan(self.profile())
        self.assertEqual(plan["summary"]["skip"], 1)
        self.assertFalse(plan["items"][0]["selected"])

    def test_duplicate_groups_require_a_choice(self):
        (self.source / "a.bin").write_bytes(b"same payload")
        (self.source / "b.bin").write_bytes(b"same payload")
        profile = self.profile("duplicates")
        profile["parameters"] = {"minimumBytes": 0}
        plan = self.service.create_plan(profile)
        self.assertEqual(plan["summary"]["groups"], 1)
        self.assertEqual(plan["summary"]["selected"], 0)
        self.assertTrue(any(item["metadata"]["recommendedKeep"] for item in plan["items"]))

    def test_quarantine_can_be_restored(self):
        installer = self.source / "旧安装包.dmg"
        installer.write_bytes(b"installer")
        old = (datetime.now(timezone.utc) - timedelta(days=120)).timestamp()
        os.utime(installer, (old, old))
        plan = self.service.create_plan(self.profile("old-installers"))
        result = self.service.execute(plan["plan_id"])
        quarantined = self.service.quarantine()
        self.assertEqual(result["success"], 1)
        self.assertEqual(len(quarantined), 1)
        self.assertFalse(installer.exists())

        restored = self.service.restore_quarantine(
            [quarantined[0]["quarantine_id"]]
        )
        self.assertEqual(restored["restored"], 1)
        self.assertTrue(installer.exists())
        self.assertEqual(self.service.quarantine(), [])

    def test_changed_file_is_not_undone(self):
        source_file = self.source / "a.pdf"
        source_file.write_text("before", encoding="utf-8")
        plan = self.service.create_plan(self.profile())
        result = self.service.execute(plan["plan_id"])
        moved = Path(plan["items"][0]["target_path"])
        moved.write_text("changed", encoding="utf-8")
        preview = self.service.undo_preview(result["runId"])
        self.assertEqual(preview["items"][0]["state"], "changed")
        undone = self.service.undo(
            result["runId"], [preview["items"][0]["operationId"]]
        )
        self.assertEqual(undone["restored"], 0)
        self.assertEqual(undone["failed"], 1)
        self.assertTrue(moved.exists())

    def test_diagnostics_export_is_local_and_complete(self):
        archive = self.root / "organize-diagnostics.zip"
        result = self.service.export_diagnostics(str(archive))
        self.assertEqual(result["path"], str(archive))
        with zipfile.ZipFile(str(archive)) as bundle:
            self.assertIn("diagnostics.json", bundle.namelist())
            contents = bundle.read("diagnostics.json").decode("utf-8")
            self.assertIn('"integrity": "ok"', contents)

    def custom_profile(self):
        profile = self.profile()
        profile["parameters"] = {
            "typeRules": [{"id": "work", "name": "工作资料", "folderName": "我的资料",
                           "extensions": [".PDF", "md"], "enabled": True}],
            "unmatchedAction": "keep", "otherFolder": "杂项",
        }
        return profile

    def test_custom_rules_and_unmatched_keep(self):
        (self.source / "notes.PDF").write_bytes(b"pdf")
        (self.source / "keep.bin").write_bytes(b"untouched")
        plan = self.service.create_plan(self.custom_profile())
        self.assertEqual(plan["summary"]["selected"], 1)
        self.assertEqual(plan["summary"]["skip"], 1)
        move = next(item for item in plan["items"] if item["selected"])
        self.assertEqual(Path(move["target_path"]).parent.name, "我的资料")
        self.service.execute(plan["plan_id"])
        self.assertTrue((self.source / "keep.bin").exists())

    def test_unmatched_other_folder_and_disabled_rule(self):
        (self.source / "notes.pdf").write_bytes(b"pdf")
        profile = self.custom_profile()
        profile["parameters"]["typeRules"][0]["enabled"] = False
        profile["parameters"]["unmatchedAction"] = "other"
        plan = self.service.create_plan(profile)
        self.assertEqual(Path(plan["items"][0]["target_path"]).parent.name, "杂项")

    def test_rule_validation_blocks_duplicate_extensions_and_path_escape(self):
        profile = self.custom_profile()
        profile["parameters"]["typeRules"].append({"id": "second", "name": "重复",
            "folderName": "../越界", "extensions": ["pdf"], "enabled": True})
        codes = {issue["code"] for issue in self.service.validate(profile)["issues"]}
        self.assertIn("DUPLICATE_EXTENSION", codes)
        self.assertIn("INVALID_RULE_FOLDER", codes)
        with self.assertRaises(EngineError):
            self.service.create_plan(profile)

    def test_sources_need_not_be_downloads_and_overlapping_sources_deduplicate(self):
        extra = self.root / "项目资料"
        nested = extra / "子目录"
        nested.mkdir(parents=True)
        (nested / "source.pdf").write_bytes(b"one")
        profile = self.profile()
        profile["sourceFolders"] = [str(extra), str(nested), str(extra)]
        plan = self.service.create_plan(profile)
        self.assertEqual(plan["summary"]["selected"], 1)
        self.assertTrue(plan["items"][0]["source_path"].startswith(str(extra)))

    def test_saved_profiles_and_last_profile_survive_restart(self):
        profile = self.custom_profile()
        self.service.save_profile(profile)
        self.service.create_plan(profile)
        restarted = EngineService(self.root / "data")
        self.assertEqual(restarted.saved_profiles(), [profile])
        self.assertEqual(restarted.initialize()["lastProfile"], profile)
        restarted.store.delete_named_profile(profile["id"])
        self.assertEqual(restarted.saved_profiles(), [])
        self.assertEqual(restarted.initialize()["lastProfile"], profile)

    def test_settings_validation_is_atomic_and_persistent(self):
        with self.assertRaises(EngineError):
            self.service.update_settings({"theme": "light", "retentionDays": 1})
        self.assertEqual(self.service.settings()["theme"], "system")
        self.service.update_settings({"theme": "light", "retentionDays": 7,
                                      "defaultTargetFolder": str(self.target), "historyLimit": 10})
        restarted = EngineService(self.root / "data")
        self.assertEqual(restarted.settings()["defaultTargetFolder"], str(self.target))
        self.assertEqual(restarted.executor.retention_days, 7)

    def test_quarantine_location_change_invalidates_old_plans(self):
        installer = self.source / "old.dmg"
        installer.write_bytes(b"installer")
        old = (datetime.now(timezone.utc) - timedelta(days=120)).timestamp()
        os.utime(installer, (old, old))
        plan = self.service.create_plan(self.profile("old-installers"))
        new_root = self.root / "新隔离区"
        new_root.mkdir()
        self.service.update_settings({"quarantineFolder": str(new_root), "retentionDays": 7})
        with self.assertRaises(EngineError):
            self.service.execute(plan["plan_id"])
        new_plan = self.service.create_plan(self.profile("old-installers"))
        self.assertTrue(new_plan["items"][0]["target_path"].startswith(str(new_root)))
        self.service.execute(new_plan["plan_id"])
        item = self.service.quarantine()[0]
        delta = datetime.fromisoformat(item["retention_until"]) - datetime.fromisoformat(item["quarantined_at"])
        self.assertEqual(delta.days, 7)

    def test_selection_summary_and_undoable_count(self):
        for name in ["a.pdf", "b.pdf"]:
            (self.source / name).write_bytes(b"abc")
        plan = self.service.create_plan(self.profile())
        selected = self.service.select_plan_items(plan["plan_id"], [plan["items"][0]["item_id"]])
        self.assertEqual(selected["summary"]["selectedBytes"], 3)
        self.assertEqual(selected["summary"]["move"], 1)
        result = self.service.execute(plan["plan_id"])
        self.assertEqual(self.service.history()[0]["undoable_count"], 1)
        preview = self.service.undo_preview(result["runId"])
        self.service.undo(result["runId"], [preview["items"][0]["operationId"]])
        self.assertEqual(self.service.history()[0]["undoable_count"], 0)

    def test_real_progress_and_skipped_journal(self):
        (self.source / "a.pdf").write_bytes(b"abc")
        (self.source / "b.pdf").write_bytes(b"defg")
        plan = self.service.create_plan(self.profile())
        events = []
        with patch("organize_gui.executor.same_fingerprint", side_effect=[False, True]):
            result = self.service.execute(plan["plan_id"], events.append)
        self.assertEqual((result["success"], result["skipped"], result["failed"]), (1, 1, 0))
        progress = [event for event in events if event["type"] == "item"]
        self.assertEqual(progress[-1]["index"], 2)
        self.assertEqual(progress[-1]["skipped"], 1)
        ops = self.service.history_detail(result["runId"])["operations"]
        self.assertEqual([op["state"] for op in ops], ["skipped", "applied"])
        self.assertEqual(result["successBytes"], plan["items"][1]["size"])

    def test_diagnostic_export_redacts_external_paths_and_logs(self):
        logs = self.service.data_dir / "logs"
        logs.mkdir()
        (logs / "engine.log").write_text("Failure at /Volumes/Private Disk/personal file.pdf\n", encoding="utf-8")
        output = self.root / "redacted.zip"
        self.service.export_diagnostics(str(output))
        with zipfile.ZipFile(str(output)) as bundle:
            manifest = json.loads(bundle.read("diagnostics.json"))
            self.assertEqual(manifest["settings"]["defaultTargetFolder"], "~[Path hidden]")
            self.assertNotIn("Private", bundle.read("logs/engine.log").decode())


if __name__ == "__main__":
    unittest.main()
