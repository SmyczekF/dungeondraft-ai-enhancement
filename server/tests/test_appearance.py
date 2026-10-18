"""Regression checks for appearance edits, ownership and public MCP options.

Run with: python -m unittest discover -s server/tests
Native editor behavior additionally needs a disposable Dungeondraft map.
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from dungeondraft_mcp import server
from dungeondraft_mcp.bridge_client import BridgeError
from dungeondraft_mcp.layout.planning import Planner, water_geometry
from dungeondraft_mcp.layout.validation import terrain_content
from dungeondraft_mcp.layout.project import save_project


def water():
    return {"disable_border": False, "tree": {
        "ref": 1, "polygon": "PoolVector2Array( )", "children": [{
            "ref": 2, "polygon": "PoolVector2Array( 0, 0, 256, 0, 256, 256 )",
            "is_open": False, "join": 0, "end": 0,
            "deep_color": "ff235e7a", "shallow_color": "ff5eaaa4",
            "blend_distance": 1.5, "children": [{
                "polygon": "PoolVector2Array( 10, 10, 20, 10, 20, 20 )",
                "children": [],
            }],
        }],
    }}


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.original = water()
        self.styled = copy.deepcopy(self.original)
        self.styled["disable_border"] = True
        self.styled["tree"]["ref"] = 99
        self.styled["tree"]["children"][0].update(
            deep_color="ff000055", shallow_color="ff00aaff", blend_distance=3,
        )

    def test_style_and_native_refs_leave_geometry_unchanged(self):
        self.assertEqual(water_geometry(self.original), water_geometry(self.styled))
        self.assertNotEqual(self.original, self.styled)

    def test_polygon_holes_and_unknown_fields_remain_protected(self):
        for field, value in (("polygon", "changed"), ("is_open", True),
                             ("children", []), ("future_geometry", 1)):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.styled)
                changed["tree"]["children"][0][field] = value
                self.assertNotEqual(water_geometry(self.original), water_geometry(changed))

    def test_terrain_settings_allow_legacy_snapshots_but_keep_paint_strict(self):
        old = {"terrain_sha256": "paint", "textures": ["sand"], "level_id": 1}
        new = old | {"terrain_settings": {"enabled": False, "smooth_blending": True}}
        self.assertEqual(terrain_content(old), terrain_content(new))
        for field, value in (("terrain_sha256", "painted"), ("textures", ["grass"]),
                             ("level_id", 2), ("unknown", True)):
            with self.subTest(field=field):
                self.assertNotEqual(terrain_content(old), terrain_content(new | {field: value}))

    def test_planner_accepts_style_but_rejects_geometry_changes(self):
        planner = Planner(Mock())
        planner.records["test"] = {"manifest": {"features": {}}, "plan": {}, "water": self.original}
        planner.context = Mock(return_value={"content": {"water": self.styled}})
        with patch("dungeondraft_mcp.layout.validation.validate", return_value={"valid": True, "findings": []}):
            self.assertTrue(planner.validate("test")["valid"])
        self.styled["tree"]["children"] = []
        with patch("dungeondraft_mcp.layout.validation.validate", return_value={"valid": True, "findings": []}):
            report = planner.validate("test")
            self.assertFalse(report["valid"])
            self.assertEqual(report["findings"][0]["code"], "water_changed")

    def test_unapplied_plan_still_rejects_appearance_changes(self):
        planner = Planner(Mock())
        original = {"bridge_instance": "same", "catalog_version": "same",
                    "content": {"level_id": 1}, "fingerprint": "before"}
        planner.records["test"] = {"submitted": False, "context": original}
        planner.context = Mock(return_value=original | {"fingerprint": "after-styling"})
        with self.assertRaisesRegex(BridgeError, "map changed since planning"):
            planner.apply("test")

    def test_project_saves_current_appearance_instead_of_old_ownership(self):
        planner = Mock()
        planner.validate.return_value = {"valid": True}
        planner.applied_record.return_value = {
            "plan": {"spec": {"seed": 0}, "resolved_assets": {},
                     "generator_version": "test", "geometry_runtime": "test"},
            "manifest": {}, "surface": {"terrain_sha256": "old"}, "water": self.original,
        }
        current_surface = {"terrain_sha256": "paint", "terrain_settings": {
            "enabled": False, "smooth_blending": True, "expanded_slots": False,
        }}
        planner.context.return_value = {
            "bridge_instance": "test", "surface": current_surface,
            "content": {"level_id": 1, "water": self.styled},
        }
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root = Path(directory) / "project"

            def save_native(path):
                Path(path).write_text("{}")
                return {"valid_native_json": True}

            def render_native(bridge, spec, path):
                path.write_bytes(b"test-preview")
                return {"path": str(path)}

            with patch.object(server, "save_map", side_effect=save_native), \
                 patch("dungeondraft_mcp.layout.project.render", side_effect=render_native):
                save_project(planner, "test", str(root))
            saved = json.loads((root / "ownership.json").read_text())
            self.assertEqual(saved["water"], self.styled)
            self.assertEqual(saved["surface"], current_surface)


class ToolTests(unittest.TestCase):
    def test_water_partial_update_and_default_scope(self):
        with patch.object(server, "bridge") as bridge:
            server.set_water_settings(deep_color="#235e7a", border=False)
            bridge.request.assert_called_once_with(
                "set_water_settings", deep_color="#235e7a", border=False, apply_to_existing=True,
            )

    def test_defaults_only_scope_is_explicit(self):
        with patch.object(server, "bridge") as bridge:
            server.set_water_settings(blend_distance=0, apply_to_existing=False)
            bridge.request.assert_called_once_with(
                "set_water_settings", blend_distance=0, apply_to_existing=False,
            )

    def test_terrain_false_is_not_omitted(self):
        with patch.object(server, "bridge") as bridge:
            server.set_terrain_settings(enabled=False, smooth_blending=True)
            bridge.request.assert_called_once_with(
                "set_terrain_settings", enabled=False, smooth_blending=True,
            )

    def test_getters_forward_active_floor_queries(self):
        with patch.object(server, "bridge") as bridge:
            server.get_water_settings()
            server.get_terrain_settings()
            self.assertEqual(bridge.request.call_args_list, [
                unittest.mock.call("get_water_settings"), unittest.mock.call("get_terrain_settings"),
            ])

    def test_export_preserves_omitted_options_and_forwards_false(self):
        for options in ({}, {"grid": False, "lighting": False}, {"lighting": True}):
            with self.subTest(options=options), patch.object(server, "bridge") as bridge, \
                 patch.object(server, "_wait_for_file"), patch.object(server.os, "remove"):
                bridge.request.return_value = {"exporting": False, "managed_export": False}
                server.export_map(ppi=32, **options)
                self.assertEqual(bridge.request.call_args_list[0], unittest.mock.call(
                    "export_map", path=server._EXPORT_PATH, ppi=32, **options,
                ))

    def test_bridge_rejection_is_reported(self):
        with patch.object(server, "bridge") as bridge:
            bridge.request.side_effect = BridgeError("invalid setting")
            with self.assertRaisesRegex(BridgeError, "invalid setting"):
                server.set_terrain_settings(enabled=True)

    def test_tools_are_registered_with_new_export_options(self):
        tools = {t.name: t for t in server.mcp._tool_manager.list_tools()}
        self.assertTrue({"get_water_settings", "set_water_settings", "get_terrain_settings",
                         "set_terrain_settings"}.issubset(tools))
        schema = tools["export_map"].parameters
        self.assertTrue({"ppi", "grid", "lighting"}.issubset(schema["properties"]))


if __name__ == "__main__":
    unittest.main()
