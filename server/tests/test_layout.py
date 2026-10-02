import copy
import json
import math
import unittest
from pathlib import Path
from pydantic import ValidationError
from shapely.geometry import Point, shape
from dungeondraft_mcp.layout.spec import MapSpec
from dungeondraft_mcp.layout.layout import generate, LayoutError

ROOT = Path(__file__).resolve().parents[2]
CATALOG = {
    category: [
        {"path": f"res://{category}/{name}.png", "nominal_footprint_woxels": [256, 256]}
        for name in names
    ]
    for category, names in {
        "Terrain": ["terrain_grass", "terrain_dirt", "terrain_swamp", "terrain_gravel"],
        "Objects": ["oak", "boulder"],
        "Walls": ["stone"],
    }.items()
}


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(
            (ROOT / "examples/forest-ambush.json").read_text(encoding="utf-8")
        )

    def plan(self, raw=None):
        return generate(MapSpec.model_validate(raw or self.raw), CATALOG, "fixture-v1")

    def test_repeatability_and_world_conversion(self):
        first = self.plan()
        self.assertEqual(first, self.plan())
        forest = first["features"]["forest"]["generated"]
        self.assertEqual(len(forest), 50)
        operations = first["operations"]
        ids = [i["semantic_id"] for i in forest]
        self.assertEqual(len(set(ids)), 50)
        for item in forest:
            op = next(
                op
                for op in operations
                if op["cmd"] == "place_object"
                and op["x"] == item["position"][0] * 256
                and op["y"] == item["position"][1] * 256
            )
            self.assertEqual(op["asset"], item["asset"])
            for other in forest:
                if other is not item:
                    self.assertGreaterEqual(
                        math.dist(item["position"], other["position"]), 1.3 - 1e-5
                    )
        self.assertEqual(first["counts"]["draw_water"], 1)
        self.assertEqual(first["warnings"][0]["code"], "asset_fallback")
        self.assertTrue(all(r["connected"] for r in first["validation"]["routes"]))
        changed = copy.deepcopy(self.raw)
        changed["seed"] += 1
        self.assertNotEqual(
            first["features"]["forest"]["generated"],
            self.plan(changed)["features"]["forest"]["generated"],
        )

    def test_protected_clearances_and_margins(self):
        plan = self.plan()
        protected = [
            shape(plan["features"][fid]["geometry"])
            for fid in [
                "road",
                "stream",
                "arena",
                "party",
                "north",
                "goblins_west",
                "goblins_east",
            ]
        ]
        for item in plan["features"]["forest"]["generated"]:
            disk = Point(item["position"]).buffer(item["visual_radius"])
            self.assertTrue(all(not disk.intersects(region) for region in protected))
            self.assertGreaterEqual(disk.bounds[0], 0.25)
            self.assertLessEqual(disk.bounds[2], 23.75)

    def test_schema_rejects_ambiguous_nonfinite_and_unknown(self):
        for key, value in [
            ("units", "pixels"),
            ("pixelsPerGrid", 128),
            ("seed", True),
            ("schema_version", "map_spec.v2"),
        ]:
            raw = copy.deepcopy(self.raw)
            raw[key] = value
            with self.assertRaises(ValidationError):
                MapSpec.model_validate(raw)
        raw = copy.deepcopy(self.raw)
        raw["features"][0]["points"][0][0] = float("nan")
        with self.assertRaises(ValidationError):
            MapSpec.model_validate(raw)
        raw = copy.deepcopy(self.raw)
        raw["features"][0]["points"][0][0] = True
        with self.assertRaises(ValidationError):
            MapSpec.model_validate(raw)

    def test_duplicate_ids_and_invalid_routes(self):
        raw = copy.deepcopy(self.raw)
        raw["features"][1]["id"] = "road"
        with self.assertRaises(ValidationError):
            MapSpec.model_validate(raw)
        raw = copy.deepcopy(self.raw)
        raw["encounter"]["required_routes"] = [["road", "party"]]
        with self.assertRaises(ValidationError):
            MapSpec.model_validate(raw)

    def test_impossible_density_and_asset_override_fail(self):
        raw = copy.deepcopy(self.raw)
        raw["features"][-1]["count"] = 400
        raw["features"][-1]["scale"] = 3
        with self.assertRaises(LayoutError):
            self.plan(raw)
        raw = copy.deepcopy(self.raw)
        raw["asset_overrides"] = {"oak": "res://missing.png"}
        with self.assertRaises(LayoutError):
            self.plan(raw)

    def test_deep_stream_requires_crossing(self):
        raw = copy.deepcopy(self.raw)
        raw["features"][1]["depth"] = "deep"
        with self.assertRaisesRegex(LayoutError, "crossing"):
            self.plan(raw)

    def test_region_clipping_and_invalid_polygon(self):
        raw = copy.deepcopy(self.raw)
        raw["features"][2]["region"] = [[-1, 7], [3, 7], [3, 9], [-1, 9]]
        plan = self.plan(raw)
        for index, fid in enumerate(plan["operation_features"]):
            if fid == "mud":
                self.assertTrue(
                    all(p[0] >= 0 for p in plan["operations"][index]["points"])
                )
        raw = copy.deepcopy(self.raw)
        raw["features"][2]["region"] = [[1, 1], [4, 4], [1, 4], [4, 1]]
        with self.assertRaises(LayoutError):
            self.plan(raw)

    def test_building_door_connectivity(self):
        raw = {
            "schema_version": "map_spec.v1",
            "size": {"width": 12, "height": 10},
            "seed": 1,
            "features": [
                {
                    "id": "room",
                    "type": "room",
                    "region": [[1, 1], [5, 1], [5, 5], [1, 5]],
                    "doors": [{"position": [5, 3]}],
                },
                {"id": "inside", "type": "entry", "position": [3, 3], "radius": 0.5},
                {"id": "outside", "type": "spawn", "position": [7, 3], "radius": 0.5},
            ],
            "encounter": {"required_routes": [["inside", "outside"]]},
        }
        plan = self.plan(raw)
        self.assertTrue(plan["validation"]["routes"][0]["connected"])
        raw["features"][0]["doors"] = []
        with self.assertRaisesRegex(LayoutError, "blocked"):
            self.plan(raw)

    def test_exported_schema_matches_models(self):
        expected = json.loads(
            (ROOT / "schemas/map_spec.v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(expected, MapSpec.model_json_schema())


if __name__ == "__main__":
    unittest.main()
