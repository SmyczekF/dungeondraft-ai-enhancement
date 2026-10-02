import copy
import json
import tempfile
import unittest
from pathlib import Path
from dungeondraft_mcp.bridge_client import BridgeError
from dungeondraft_mcp.layout.revision import object_diff, revised_spec
from dungeondraft_mcp.layout.validation import validate
from dungeondraft_mcp.layout.project import load_project
from dungeondraft_mcp.layout.layout import generate, LayoutError
from dungeondraft_mcp.layout.spec import MapSpec
from test_layout import CATALOG, ROOT


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.plan = generate(
            MapSpec.model_validate(
                json.loads(
                    (ROOT / "examples/forest-ambush.json").read_text(encoding="utf-8")
                )
            ),
            CATALOG,
            "fixture-v1",
        )
        self.manifest = {
            "plan_id": self.plan["plan_id"],
            "level_id": 0,
            "features": {
                fid: {
                    "semantic": copy.deepcopy(s),
                    "elements": [],
                    "operation_indices": [],
                }
                for fid, s in self.plan["features"].items()
            },
        }
        native = 0
        for fid, s in self.plan["features"].items():
            if s["type"] not in ("forest", "cover", "obstacle", "hazard"):
                continue
            ops = [
                op
                for i, op in enumerate(self.plan["operations"])
                if self.plan["operation_features"][i] == fid
            ]
            for item, op in zip(s["generated"], ops):
                self.manifest["features"][fid]["elements"].append(
                    {
                        "semantic_id": item["semantic_id"],
                        "id": native,
                        "cmd": op["cmd"],
                        "operation": op,
                    }
                )
                native += 1
        self.context = {
            "content": {"size": [6144, 4352], "level_id": 0, "elements": []}
        }
        for f in self.manifest["features"].values():
            for e in f["elements"]:
                op = e["operation"]
                self.context["content"]["elements"].append(
                    {
                        "id": e["id"],
                        "kind": "object",
                        "asset": op["asset"],
                        "position": [op["x"], op["y"]],
                        "scale": op["scale"],
                        "rotation": op["rotation"],
                    }
                )

    def test_move_and_retexture_preserve_identity(self):
        changed = copy.deepcopy(self.plan)
        item = changed["features"]["boulder_west"]["generated"][0]
        item["position"] = [8.1, 9.1]
        item["asset"] = "res://Objects/alternate.png"
        operations, targets, ids = object_diff(self.manifest, changed)
        self.assertEqual(
            [op["cmd"] for op in operations], ["move_element", "modify_object"]
        )
        expected = self.manifest["features"]["boulder_west"]["elements"][0]["id"]
        self.assertEqual(ids["boulder_west"], expected)
        self.assertTrue(all(op["id"] == expected for op in operations))

    def test_shrink_deletes_only_removed_members(self):
        changed = copy.deepcopy(self.plan)
        changed["features"]["forest"]["generated"] = changed["features"]["forest"][
            "generated"
        ][:-2]
        operations, _, ids = object_diff(self.manifest, changed)
        self.assertEqual(
            [op["cmd"] for op in operations], ["delete_object", "delete_object"]
        )
        self.assertEqual(
            [op["id"] for op in operations],
            [e["id"] for e in self.manifest["features"]["forest"]["elements"][-2:]],
        )
        self.assertEqual(len(ids), 50)

    def test_invalid_replacement_and_shared_geometry(self):
        with self.assertRaises(BridgeError):
            revised_spec(self.plan, [{"id": "absent"}])
        with self.assertRaises(BridgeError):
            revised_spec(self.plan, [self.plan["features"]["stream"]["spec"]])
        with self.assertRaises(BridgeError):
            revised_spec(self.plan, [{"id": "forest", "type": "cover"}])

    def test_frozen_forest_survives_unrelated_change(self):
        spec = MapSpec.model_validate(self.plan["spec"])
        fixed = self.plan["features"]["forest"]["generated"]
        updated = generate(
            spec, CATALOG, "fixture-v1", frozen_features={"forest": fixed}
        )
        self.assertEqual(updated["features"]["forest"]["generated"], fixed)
        bad = copy.deepcopy(fixed)
        bad[0]["position"] = [12, 2]
        with self.assertRaises(LayoutError):
            generate(spec, CATALOG, "fixture-v1", frozen_features={"forest": bad})

    def test_missing_native_and_drift_report_coordinates(self):
        self.assertTrue(validate(self.plan, self.manifest, self.context)["valid"])
        damaged = copy.deepcopy(self.context)
        damaged["content"]["elements"][0]["position"] = [12 * 256, 2 * 256]
        report = validate(self.plan, self.manifest, damaged)
        self.assertFalse(report["valid"])
        self.assertTrue(
            any(
                f["code"] == "position_changed" and f["coordinates_tiles"] == [12, 2]
                for f in report["findings"]
            )
        )
        damaged["content"]["elements"].pop()
        self.assertTrue(
            any(
                f["code"] == "missing_element"
                for f in validate(self.plan, self.manifest, damaged)["findings"]
            )
        )

    def test_manual_route_obstacle_is_preserved_and_reported(self):
        damaged = copy.deepcopy(self.context)
        damaged["content"]["elements"].append(
            {"id": 999, "bounds": [[0, 3 * 256], [24 * 256, 4 * 256]]}
        )
        report = validate(self.plan, self.manifest, damaged)
        self.assertFalse(report["valid"])
        self.assertTrue(any(f["code"] == "route_blocked" for f in report["findings"]))
        self.assertEqual(report["manual_element_count"], 1)

    def test_incomplete_or_tampered_project_never_contacts_editor(self):
        class NoEditor:
            def context(self):
                raise AssertionError("must reject files before editor access")

        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(BridgeError):
                load_project(NoEditor(), root)
            Path(root, "project.json").write_text(
                json.dumps(
                    {
                        "schema_version": "battlemap_project.v1",
                        "files": {"../../private": "x"},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(BridgeError):
                load_project(NoEditor(), root)


if __name__ == "__main__":
    unittest.main()
