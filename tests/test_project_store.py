import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.data.project_store import ProjectStore, BUILTIN_PRESETS


class ProjectStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.user_data = self.root / "user-data"
        self.patch_app_data = mock.patch.object(
            ProjectStore, "app_data_root", return_value=self.user_data
        )
        self.patch_app_data.start()
        self.addCleanup(self.patch_app_data.stop)
        self.project = ProjectStore.create_project("Test project", self.root / "projects")
        self.addCleanup(self.temp.cleanup)

    def test_project_manifest_and_session_layout(self):
        self.assertTrue((self.project.root / "project.json").is_file())
        self.assertTrue((self.project.root / "presets" / "detector").is_dir())
        self.assertTrue((self.project.root / "media" / "sources").is_dir())
        manifest = json.loads((self.project.root / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["format"], "elutec-project")
        self.assertEqual(manifest["default_presets"]["detector"], "builtin:detector.default")

        session = self.project.create_session(
            {"roi_w": 420, "api_token": "must-not-be-saved", "save_folder": "/tmp/out"},
            source="rtsp://alice:secret@camera.example/live?token=abc&channel=1",
            display_name="Test run",
            runtime_environment={
                "os": "Linux", "architecture": "x86_64", "python_bits": 64,
                "cpu_model": "Generic CPU", "logical_cores": 8,
                "memory_total_bytes": 16 * 1024 ** 3,
                "memory_available_bytes": 8 * 1024 ** 3,
                "diagnostic_summary": {
                    "recommended_profile": "Сбалансированный",
                    "processing_p95_ms": 2.5,
                    "sample_source": "preview_frame",
                    "camera_url": "must-not-be-saved",
                },
                "hostname": "must-not-be-saved", "device_serial": "also-private",
            },
        )
        session_path = Path(session["path"])
        self.assertTrue((session_path / "session.json").is_file())
        self.assertTrue((session_path / "exports").is_dir())
        self.assertTrue((session_path / "logs").is_dir())
        data = json.loads((session_path / "session.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "running")
        self.assertEqual(data["settings_snapshot"]["roi_w"], 420)
        self.assertNotIn("api_token", data["settings_snapshot"])
        self.assertNotIn("save_folder", data["settings_snapshot"])
        self.assertEqual(data["runtime_environment"]["logical_cores"], 8)
        self.assertNotIn("hostname", data["runtime_environment"])
        self.assertNotIn("device_serial", data["runtime_environment"])
        self.assertEqual(
            data["runtime_environment"]["diagnostic_summary"]["recommended_profile"],
            "Сбалансированный",
        )
        self.assertNotIn("camera_url", data["runtime_environment"]["diagnostic_summary"])
        safe_source = json.dumps(data["source"], ensure_ascii=False)
        for secret in ("alice", "secret", "abc"):
            self.assertNotIn(secret, safe_source)

        artifact = session_path / "analysis.xlsx"
        artifact.write_bytes(b"workbook")
        finished = self.project.finish_session(
            session_path, "completed", artifacts={"excel": artifact}, extra={"record_count": 4}
        )
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["artifacts"]["excel"], "analysis.xlsx")
        self.assertEqual(finished["record_count"], 4)
        with_error = self.project.finish_session(
            session_path, "failed", error="stream failed at rtsp://alice:secret@camera.example/live?token=abc"
        )
        for secret in ("alice", "secret", "abc"):
            self.assertNotIn(secret, with_error["error"])
        self.assertEqual(len(self.project.list_sessions()), 1)

    def test_preset_libraries_are_separate_and_builtins_are_immutable(self):
        user = self.project.save_preset("detector", "Oil", {"miicam_gain": 145}, scope="user")
        project = self.project.save_preset("detector", "Oil", {"miicam_gain": 190}, scope="project")
        self.assertNotEqual(user["id"], project["id"])
        self.assertEqual(user["origin"], "user")
        self.assertEqual(project["origin"], "project")
        self.assertEqual(self.project.get_preset(user["id"])["settings"]["miicam_gain"], 145)
        self.assertEqual(self.project.get_preset(project["id"])["settings"]["miicam_gain"], 190)

        builtin = BUILTIN_PRESETS["detector"][0]
        with self.assertRaises(ValueError):
            self.project.save_preset("detector", builtin["name"], {}, scope="project")
        with self.assertRaises(PermissionError):
            self.project.delete_preset(builtin["id"])
        self.project.set_default_preset("detector", project["id"])
        self.assertEqual(self.project.get_default_preset_id("detector"), project["id"])
        self.project.delete_preset(project["id"])
        self.assertEqual(self.project.get_default_preset_id("detector"), "builtin:detector.default")

    def test_legacy_migration_preserves_changed_default_and_removes_old_config(self):
        builtin_settings = BUILTIN_PRESETS["detector"][0]["settings"]
        changed_default = dict(builtin_settings)
        changed_default["miicam_gain"] = 177
        legacy = {
            "detector_presets": {
                "По умолчанию (Default)": changed_default,
                "Lab preset": {"miicam_gain": 151},
            }
        }
        self.assertTrue(ProjectStore().migrate_legacy_detector_presets(legacy))
        self.assertNotIn("detector_presets", legacy)
        self.assertEqual(
            self.project.get_preset("builtin:detector.default")["settings"], builtin_settings
        )
        migrated = [r for r in ProjectStore().list_presets("detector") if r["origin"] == "user"]
        names = {r["name"]: r["settings"] for r in migrated}
        self.assertEqual(names["Default — пользовательская копия"]["miicam_gain"], 177)
        self.assertEqual(names["Lab preset"]["miicam_gain"], 151)

    def test_workspace_location_is_remembered(self):
        workspace = self.root / "chosen-workspace"
        ProjectStore.set_default_workspace_root(workspace)
        self.assertEqual(ProjectStore.default_workspace_root(), workspace.resolve())
        created = ProjectStore.create_project("In chosen folder")
        self.assertEqual(created.root.parent, workspace.resolve())

    def test_import_legacy_results_copies_files_without_touching_originals(self):
        source = self.root / "old-results"
        source.mkdir()
        files = {
            "analysis_20250101_120000.xlsx": b"xlsx",
            "analysis_20250101_120000_raw_rgb.csv": b"csv",
            "analysis_20250101_120000_video.mkv": b"video",
            "notes.txt": b"notes",
        }
        for name, content in files.items():
            (source / name).write_bytes(content)

        imported, summary = ProjectStore.import_legacy_folder(
            source, "Imported", workspace_root=self.root / "imports"
        )
        self.assertEqual(summary, {"sessions": 1, "unmatched": 1})
        session = imported.list_sessions()[0]
        self.assertEqual(session["status"], "imported")
        self.assertEqual(session["artifacts"]["analysis"], "analysis.xlsx")
        self.assertEqual(session["artifacts"]["raw_csv"], "raw_rgb.csv")
        self.assertEqual(session["artifacts"]["video"], "capture.mkv")
        self.assertEqual((source / "analysis_20250101_120000.xlsx").read_bytes(), b"xlsx")
        self.assertEqual((source / "notes.txt").read_bytes(), b"notes")
        self.assertEqual((imported.root / "legacy_imports" / "notes.txt").read_bytes(), b"notes")


if __name__ == "__main__":
    unittest.main()
