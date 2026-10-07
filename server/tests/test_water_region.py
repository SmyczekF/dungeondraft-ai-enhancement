import unittest
from shapely.geometry import Polygon
from dungeondraft_mcp.layout.spec import MapSpec
from dungeondraft_mcp.layout.layout import generate, LayoutError
from dungeondraft_mcp.layout.validation import validate
from test_layout import CATALOG


class CoastTests(unittest.TestCase):
    def spec(self, crossing=True):
        features = [
            {
                "id": "sea",
                "type": "water_region",
                "region": [[6, 0], [12, 0], [12, 12], [6, 12]],
            },
            {
                "id": "pier",
                "type": "road",
                "points": [[3, 6], [10, 6]],
                "width": 1.5,
                "smooth": False,
            },
            {"id": "land", "type": "entry", "position": [3, 6], "radius": 0.5},
            {"id": "boat", "type": "spawn", "position": [10, 6], "radius": 0.5},
        ]
        if crossing:
            features.append(
                {
                    "id": "deck",
                    "type": "clear_area",
                    "purpose": "crossing",
                    "region": [[5, 4], [11, 4], [11, 8], [5, 8]],
                }
            )
        return MapSpec.model_validate(
            {
                "schema_version": "map_spec.v1",
                "size": {"width": 12, "height": 12},
                "seed": 1,
                "features": features,
                "encounter": {"required_routes": [["land", "boat"]]},
            }
        )

    def test_deep_coast_requires_crossing(self):
        with self.assertRaisesRegex(LayoutError, "crossing"):
            generate(self.spec(False), CATALOG, "test")

    def test_deck_preserves_water_and_allows_route(self):
        plan = generate(self.spec(), CATALOG, "test")
        water = next(o for o in plan["operations"] if o["cmd"] == "draw_water")
        self.assertEqual(Polygon(water["points"]).area / 256**2, 72)
        self.assertTrue(plan["validation"]["routes"][0]["connected"])
        manifest = {
            "level_id": 0,
            "features": {fid: {"elements": []} for fid in plan["features"]},
        }
        context = {
            "content": {
                "size": [3072, 3072],
                "level_id": 0,
                "elements": [
                    {
                        "id": 999,
                        "kind": "pattern",
                        "bounds": [[5 * 256, 4 * 256], [11 * 256, 8 * 256]],
                    }
                ],
            }
        }
        self.assertTrue(validate(plan, manifest, context)["valid"])
        context["content"]["elements"][0]["kind"] = "object"
        self.assertFalse(validate(plan, manifest, context)["valid"])

    def test_open_portal_policy_requires_explicit_false(self):
        from dungeondraft_mcp.layout.validation import is_manual_obstacle

        self.assertFalse(is_manual_obstacle({"kind": "portal", "closed": False}))
        self.assertTrue(is_manual_obstacle({"kind": "portal", "closed": True}))
        self.assertTrue(is_manual_obstacle({"kind": "portal"}))
        self.assertTrue(is_manual_obstacle({"kind": "object", "closed": False}))

    def test_water_region_rejects_self_intersection(self):
        raw = self.spec().model_dump(mode="json")
        raw["features"][0]["region"] = [[6, 0], [12, 12], [12, 0], [6, 12]]
        with self.assertRaisesRegex(LayoutError, "simple"):
            generate(MapSpec.model_validate(raw), CATALOG, "test")
