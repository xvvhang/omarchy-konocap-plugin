"""Branding/version consistency and settings migration, without a compositor."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("konocap_manager", ROOT / "manager.py")
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


class KonocapMetadataTests(unittest.TestCase):
    def test_branding_and_version_match(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())
        self.assertEqual(manifest["id"], manager.PLUGIN_ID)
        self.assertEqual(manifest["name"], "Konocap")
        version = manifest["version"]
        self.assertIn(f"VERSION {version}", (ROOT / "native/CMakeLists.txt").read_text())
        self.assertIn(f'"alec", "{version}"', (ROOT / "native/main.cpp").read_text())
        self.assertIn(f'target: "{manager.PLUGIN_ID}"', (ROOT / "Service.qml").read_text())
        self.assertIn(f"Konocap {version}", (ROOT / "README.md").read_text())
        self.assertIn(f"## {version}", (ROOT / "CHANGELOG.md").read_text())

    def settings_from(self, entries):
        Path("/tmp/opencode").mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="konocap-metadata-", dir="/tmp/opencode") as directory:
            config = Path(directory) / "omarchy/shell.json"
            config.parent.mkdir()
            config.write_text(json.dumps({"plugins": entries}))
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}):
                return manager.configured_settings()

    def test_canonical_settings_take_priority(self):
        result = self.settings_from([
            {"id": "alec.focus-titlebars", "showDuration": 10},
            {"id": "xvvhang.focus-titlebars", "showDuration": 20},
            {"id": "konochi.konocap", "showDuration": 180},
        ])
        self.assertEqual(result["showDuration"], 180)

    def test_both_legacy_settings_ids_are_supported(self):
        for plugin_id in manager.LEGACY_IDS:
            with self.subTest(plugin_id=plugin_id):
                self.assertEqual(self.settings_from([{"id": plugin_id, "hideDuration": 90}])["hideDuration"], 90)

    def test_defaults_and_bounds(self):
        self.assertEqual(manager.durations(self.settings_from([])), (180, 120))
        self.assertEqual(manager.durations({"showDuration": 999, "hideDuration": -5}), (290, 0))


if __name__ == "__main__":
    unittest.main()
