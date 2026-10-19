"""Safety boundaries for editor restart and bootstrap creation (no live process)."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from dungeondraft_mcp.bridge_client import BridgeError
from dungeondraft_mcp.editor_lifecycle import EditorLifecycle, validate_bootstrap
from dungeondraft_mcp import server


def blank():
    return {"world": {"width": 20, "height": 16, "levels": {"0": {
        "cave": {"bitmap": "PoolByteArray( 0, 0 )", "entrance_bitmap": "PoolByteArray( 0, 0 )"},
        "terrain": {"splat": "PoolByteArray( 255, 0, 0, 0 )"},
        "tiles": {"cells": "PoolIntArray( -1, -1 )"},
    }}}}


class BootstrapTests(unittest.TestCase):
    def test_default_native_blank_passes(self):
        validate_bootstrap(blank())

    def test_content_hidden_from_element_counts_is_rejected(self):
        for key, value in (("water", {"tree": {"children": [1]}}),
                           ("terrain", {"splat": "PoolByteArray( 254, 1, 0, 0 )"}),
                           ("cave", {"bitmap": "PoolByteArray( 1 )"}),
                           ("tiles", {"cells": "PoolIntArray( 0 )"}),
                           ("shapes", {"polygons": [1]}), ("objects", [1]),
                           ("roofs", {"roofs": [1]})):
            with self.subTest(key=key):
                native = blank()
                native["world"]["levels"]["0"][key] = value
                with self.assertRaises(BridgeError):
                    validate_bootstrap(native)

    def test_multiple_levels_and_unreadable_surface_rejected(self):
        native = blank()
        native["world"]["levels"]["1"] = {}
        with self.assertRaises(BridgeError):
            validate_bootstrap(native)
        native = blank()
        native["world"]["levels"]["0"]["terrain"]["splat"] = "not native data"
        with self.assertRaises(BridgeError):
            validate_bootstrap(native)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / "dd-maps")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.target = self.root / "test map.dungeondraft_map"
        self.target.write_text(json.dumps(blank()))
        self.executable = self.root / "Dungeondraft.exe"
        self.executable.touch()
        self.info = {"path": str(self.target), "bridge_instance": "old", "map_open": True,
                     "size_tiles": [20, 16], "dirty": False, "process_id": 11}
        self.bridge = Mock(host="127.0.0.1", port=8787)
        self.save = Mock()
        self.lifecycle = EditorLifecycle(self.bridge, self.save)
        self.lifecycle.inspect = Mock(side_effect=lambda: dict(self.info))
        self.process = Mock(executable=self.executable)
        self.launch = Mock(pid=22)
        self.launch.poll.return_value = None
        self.patches = [patch("dungeondraft_mcp.editor_lifecycle.editor_process.editor_pids", return_value=[11]),
                        patch("dungeondraft_mcp.editor_lifecycle.sys.platform", "win32"),
                        patch("dungeondraft_mcp.editor_lifecycle.editor_process.listener_pid", return_value=11),
                        patch("dungeondraft_mcp.editor_lifecycle.editor_process.EditorProcess", return_value=self.process),
                        patch("dungeondraft_mcp.editor_lifecycle.editor_process.launch", return_value=self.launch),
                        patch.object(self.lifecycle, "_wait_ready", return_value={"ready": True})]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_save_precedes_stop_and_launch(self):
        events = []
        self.save.side_effect = lambda **kw: events.append("save")
        self.process.stop.side_effect = lambda: events.append("stop")
        with patch("dungeondraft_mcp.editor_lifecycle.editor_process.launch", side_effect=lambda *a: (events.append("launch"), self.launch)[1]):
            self.assertTrue(self.lifecycle.open(str(self.target))["ready"])
        self.assertEqual(events, ["save", "stop", "launch"])
        self.process.close.assert_called_once()

    def test_failed_save_never_stops_editor(self):
        self.save.side_effect = BridgeError("save incomplete")
        with self.assertRaisesRegex(BridgeError, "save incomplete"):
            self.lifecycle.open(str(self.target))
        self.process.stop.assert_not_called()

    def test_dirty_after_save_never_stops_editor(self):
        self.info["dirty"] = True
        with self.assertRaisesRegex(BridgeError, "unfinished"):
            self.lifecycle.open(str(self.target))
        self.process.stop.assert_not_called()

    def test_untitled_requires_save_destination_or_explicit_discard(self):
        self.info["path"] = ""
        with self.assertRaisesRegex(BridgeError, "no path"):
            self.lifecycle.open(str(self.target))
        self.process.stop.assert_not_called()
        self.lifecycle.open(str(self.target), save_current_path=str(self.root / "untitled.dungeondraft_map"))
        self.save.assert_called_once_with(path=str(self.root / "untitled.dungeondraft_map"), overwrite=False)

    def test_explicit_discard_skips_save(self):
        self.info["dirty"] = True
        self.lifecycle.open(str(self.target), discard_current=True)
        self.save.assert_not_called()
        self.process.stop.assert_called_once()

    def test_invalid_target_never_saves_or_stops(self):
        self.target.write_text("invalid json")
        with self.assertRaisesRegex(BridgeError, "Invalid native map"):
            self.lifecycle.open(str(self.target))
        self.save.assert_not_called()
        self.process.stop.assert_not_called()

    def test_unreachable_or_changed_bridge_never_stops(self):
        self.lifecycle.inspect.side_effect = BridgeError("unreachable")
        with self.assertRaises(BridgeError):
            self.lifecycle.open(str(self.target))
        self.process.stop.assert_not_called()
        self.lifecycle.inspect.side_effect = [self.info, self.info | {"bridge_instance": "another"}]
        with self.assertRaisesRegex(BridgeError, "changed during save"):
            self.lifecycle.open(str(self.target))
        self.process.stop.assert_not_called()

    def test_create_refuses_existing_destination_and_invalid_dimensions(self):
        for width, height in ((0, 16), (201, 16), (True, 16), (20.5, 16)):
            with self.subTest(size=(width, height)), self.assertRaises(BridgeError):
                self.lifecycle.create(width, height, str(self.root / "new.dungeondraft_map"))
        with self.assertRaisesRegex(BridgeError, "already exists"):
            self.lifecycle.create(20, 16, str(self.target), bootstrap_path=str(self.target))
        self.process.stop.assert_not_called()

    def test_create_rejects_populated_template_before_restart_or_destination_write(self):
        native = blank()
        native["world"]["levels"]["0"]["objects"] = [1]
        self.target.write_text(json.dumps(native))
        destination = self.root / "new.dungeondraft_map"
        with self.assertRaisesRegex(BridgeError, "contains objects"):
            self.lifecycle.create(30, 20, str(destination), bootstrap_path=str(self.target))
        self.assertFalse(destination.exists())
        self.process.stop.assert_not_called()

    def test_create_preserves_template_and_checks_saved_dimensions(self):
        before = self.target.read_bytes()
        destination = self.root / "new.dungeondraft_map"
        def save(**kwargs):
            native = blank()
            native["world"].update(width=30, height=22)
            destination.write_text(json.dumps(native))
        self.lifecycle.open = Mock(return_value=self.info)
        self.bridge.request.return_value = {"size_tiles": [30, 22]}
        self.lifecycle.inspect.return_value = self.info | {"size_tiles": [30, 22], "path": str(destination)}
        self.lifecycle.inspect.side_effect = None
        self.save.side_effect = save
        result = self.lifecycle.create(30, 22, str(destination), bootstrap_path=str(self.target))
        self.assertTrue(result["created"])
        self.assertEqual(self.target.read_bytes(), before)
        self.lifecycle.open.assert_called_once_with(str(destination), save_current_path="")

    def test_create_failure_retains_destination_and_reports_it(self):
        destination = self.root / "new.dungeondraft_map"
        self.lifecycle.open = Mock(side_effect=BridgeError("startup failed"))
        with self.assertRaisesRegex(BridgeError, "retained.*new.dungeondraft_map"):
            self.lifecycle.create(30, 22, str(destination), bootstrap_path=str(self.target))
        self.assertTrue(destination.exists())

    def test_idle_rejects_each_busy_state(self):
        for state in ("saving", "loading", "exporting", "batch_active"):
            with self.subTest(state=state), self.assertRaises(BridgeError):
                EditorLifecycle.idle({state: True})

    def test_start_without_existing_editor_uses_configured_executable(self):
        with patch("dungeondraft_mcp.editor_lifecycle.editor_process.editor_pids", return_value=[]), \
             patch.dict("os.environ", {"DD_EDITOR_EXECUTABLE": str(self.executable)}), \
             patch("dungeondraft_mcp.editor_lifecycle.editor_process.launch", return_value=self.launch) as launch:
            self.lifecycle.open(str(self.target))
        self.save.assert_not_called()
        self.process.stop.assert_not_called()
        launch.assert_called_once_with(self.executable, self.target)

    def test_readiness_rejects_stale_instance_wrong_pid_and_wrong_path(self):
        lifecycle = EditorLifecycle(self.bridge, self.save)
        for hello, info in (({"bridge_instance": "old"}, self.info),
                            ({"bridge_instance": "new"}, self.info | {"process_id": 99}),
                            ({"bridge_instance": "new"}, self.info | {"path": str(self.root / "wrong.dungeondraft_map"), "process_id": 22})):
            with self.subTest(hello=hello, info=info):
                self.bridge.request.return_value = hello
                lifecycle.inspect = Mock(return_value=info)
                with patch("dungeondraft_mcp.editor_lifecycle.time.monotonic", side_effect=[0, 0, 2]), \
                     patch("dungeondraft_mcp.editor_lifecycle.time.sleep"), \
                     self.assertRaisesRegex(BridgeError, "timed out"):
                    lifecycle._wait_ready(self.target, "old", 22, timeout=1)

    def test_readiness_accepts_new_process_path_and_dimensions(self):
        lifecycle = EditorLifecycle(self.bridge, self.save)
        self.bridge.request.return_value = {"bridge_instance": "new"}
        lifecycle.inspect = Mock(return_value=self.info | {"process_id": 22, "bridge_instance": "new"})
        self.assertTrue(lifecycle._wait_ready(self.target, "old", 22)["ready"])

    def test_startup_exit_reports_code_log_and_preserves_file(self):
        lifecycle = EditorLifecycle(self.bridge, self.save)
        lifecycle.process = Mock(returncode=42)
        lifecycle.process.poll.return_value = 42
        with self.assertRaisesRegex(BridgeError, "code 42.*Log:"):
            lifecycle._wait_ready(self.target, "old", 22)
        self.assertTrue(self.target.exists())


class PublicToolsTests(unittest.TestCase):
    def test_lifecycle_tools_forward_options(self):
        with patch.object(server, "editor") as editor:
            server.open_map("path", save_current_path="save")
            editor.open.assert_called_once_with("path", discard_current=False, save_current_path="save")
            server.create_map(30, 20, "path", bootstrap_path="blank")
            editor.create.assert_called_once_with(30, 20, "path", bootstrap_path="blank", save_current_path="")
        with patch.object(server, "bridge") as bridge:
            server.resize_map(30, 20)
            bridge.request.assert_called_once_with("resize_map", width=30, height=20)
