"""Map release acceptance: complete packages, registration and stale-input rejection."""
import base64
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib

from dungeondraft_mcp.layout.vtt import NAMESPACE
from dungeondraft_mcp.release import ReleaseError, build_release, digest, load_config, public_scene


def png(color=0):
    def chunk(kind, value):
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 128, 128, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\0" + bytes([color]) * 384) * 128)) + chunk(b"IEND", b""))


class Editor:
    _EXPORT_PATH = "unused.png"

    def __init__(self, native, labels):
        self.native, self.labels, self.active = native, labels, 0
        self.calls, self.selected, self.exports = [], [], []
        self.mutate = False
        self.save_changes = False

    def ping(self):
        self.calls.append("ping"); return {"protocol": 23}

    def get_status(self):
        self.calls.append("status"); return {"map_open": True, "level_index": self.active}

    def get_capabilities(self):
        self.calls.append("capabilities"); return {"protocol": 23}

    def get_map_info(self):
        return {"path": str(self.native), "dirty": False}

    def save_map(self):
        if self.save_changes:
            self.native.write_text(self.native.read_text() + " ")

    def list_levels(self):
        return {"levels": [{"label": label, "id": 99 - i * 7, "index": i} for i, label in enumerate(self.labels)]}

    def set_level(self, index):
        self.active = index; self.selected.append(index)

    def export_map(self, **kwargs):
        self.exports.append(kwargs)
        Path(self._EXPORT_PATH).write_bytes(png(200))
        if self.mutate:
            self.native.write_text(self.native.read_text() + " ")


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.native = self.root / "map.dungeondraft_map"
        self.native.write_text(json.dumps({"world": {"width": 1, "height": 1, "levels": {"0": {"label": "Ground"}}}}))
        self.scene = {"_stats": {"coreVersion": "14.368"}, "width": 128, "height": 128,
                      "levels": [{"background": {"src": "data:image/png;base64," + base64.b64encode(png()).decode()}}],
                      "grid": {"type": 1, "size": 128, "distance": 5, "units": "ft"}, "padding": 0,
                      "flags": {NAMESPACE: {"canonical_native": "C:/private/map", "runtime_verified": False}},
                      "walls": [{"_id": "wall", "c": [0, 64, 128, 64], "move": 20, "sight": 20, "door": 2, "ds": 0,
                                 "flags": {NAMESPACE: {"native_id": 10}}}], "lights": []}
        (self.root / "foundry").mkdir()
        self.scene_path = self.root / "foundry/foundry-scene.json"
        self.scene_path.write_text(json.dumps(self.scene))
        self.meta = {"native_sha256": digest(self.native.read_bytes()), "scene_sha256": digest(self.scene_path.read_bytes())}
        (self.root / "foundry/export.json").write_text(json.dumps(self.meta))
        self.cfg = {"title": "Test Cove", "slug": "test-cove", "native_map": self.native.name,
                    "pixels_per_square": 128, "floors": [{"name": "ground", "native_label": "Ground", "scene": "foundry/foundry-scene.json"}]}
        self.editor = Editor(self.native, ["Ground"])

    def config(self):
        (self.root / "map-release.json").write_text(json.dumps(self.cfg))
        return self.root

    def test_three_minimal_downloads_and_instructions_preserve_secret(self):
        output = build_release(self.config(), self.editor)
        self.assertEqual(self.editor.calls[:3], ["ping", "status", "capabilities"])
        for kind, suffix in [("gridded", "png"), ("gridless", "png"), ("foundry", "json")]:
            with zipfile.ZipFile(output / f"test-cove-{kind}.zip") as z:
                self.assertEqual(set(z.namelist()), {"READ-ME.txt", f"test-cove-ground.{suffix}"})
                self.assertIn("5 feet", z.read("READ-ME.txt").decode())
                if kind == "foundry":
                    scene = json.loads(z.read("test-cove-ground.json"))
                    self.assertEqual(scene["walls"][0]["door"], 2)
                    self.assertNotIn(NAMESPACE, scene["flags"])
                    self.assertNotIn(NAMESPACE, scene["walls"][0]["flags"])
        self.assertEqual(self.editor.exports, [{"ppi": 128, "grid": True, "lighting": False}])
        self.assertIn("Import Data", (output / "RELEASE-NOTES.txt").read_text())

    def test_stale_native_rejected_before_export_or_overwriting_release(self):
        self.native.write_text(self.native.read_text() + " ")
        output = self.root / "release"; output.mkdir()
        existing = output / "test-cove-foundry.zip"; existing.write_bytes(b"previous release")
        with self.assertRaisesRegex(ReleaseError, "stale"):
            build_release(self.config(), self.editor)
        self.assertEqual(existing.read_bytes(), b"previous release")
        self.assertFalse(self.editor.exports)

    def test_modified_scene_is_not_silently_published(self):
        self.scene_path.write_text(self.scene_path.read_text() + " ")
        with self.assertRaisesRegex(ReleaseError, "Scene hash"):
            build_release(self.config(), self.editor)

    def test_edit_during_export_rejects_build(self):
        self.editor.mutate = True
        with self.assertRaisesRegex(ReleaseError, "Map changed"):
            build_release(self.config(), self.editor)
        self.assertFalse(list((self.root / "release").glob("*.zip")))

    def test_path_escape_rejected(self):
        self.cfg["floors"][0]["scene"] = "../private.json"
        with self.assertRaisesRegex(ReleaseError, "escapes"):
            load_config(self.config())

    def test_public_scene_rejects_external_image_shift_and_wrong_grid(self):
        for change in [lambda s: s["levels"][0]["background"].update(src="C:/private/image.png"),
                       lambda s: s.update(shiftX=1), lambda s: s["grid"].update(size=100)]:
            with self.subTest(change=change):
                scene = json.loads(json.dumps(self.scene)); change(scene)
                with self.assertRaises(ReleaseError): public_scene(scene, (128, 128), 128)

    def test_two_floors_use_current_labels_and_restore_active_floor(self):
        upper = self.root / "foundry/upper.json"; upper.write_bytes(self.scene_path.read_bytes())
        self.cfg["floors"].append({"name": "upper", "native_label": "Upper", "scene": "foundry/upper.json"})
        self.editor.labels.append("Upper")
        build_release(self.config(), self.editor)
        self.assertEqual(self.editor.selected, [0, 1, 0])
        with zipfile.ZipFile(self.root / "release/test-cove-foundry.zip") as z:
            self.assertEqual(len(z.namelist()), 3)

    def test_uncaptured_native_floor_rejected(self):
        self.editor.labels.append("Upper")
        with self.assertRaisesRegex(ReleaseError, "exactly cover"):
            build_release(self.config(), self.editor)

    def test_cached_clean_export_does_not_get_invalidated_by_resaving(self):
        self.editor.save_changes = True
        original_hash = digest(self.native.read_bytes())
        build_release(self.config(), self.editor)
        self.assertEqual(digest(self.native.read_bytes()), original_hash)

    def test_failed_exporter_restores_floor_without_publishing(self):
        self.editor.labels.append("Upper")
        self.cfg["foundry_exporter"] = "export-foundry.py"
        (self.root / "export-foundry.py").write_text("# trusted local exporter")
        def failed(*args, **kwargs):
            self.editor.active = 1
            raise subprocess.CalledProcessError(1, args[0])
        with patch("dungeondraft_mcp.release.subprocess.run", side_effect=failed):
            with self.assertRaises(subprocess.CalledProcessError):
                build_release(self.config(), self.editor)
        self.assertEqual(self.editor.active, 0)
        self.assertFalse((self.root / "release").exists())


if __name__ == "__main__":
    unittest.main()
