import copy
import base64
import struct
import unittest

from dungeondraft_mcp.bridge_client import BridgeError
from dungeondraft_mcp.layout.vtt import decode_native, foundry_scene, image_path
import test_revision


class VTTTests(unittest.TestCase):
    def setUp(self):
        fixture = test_revision.RevisionTests()
        fixture.setUp()
        self.plan, self.manifest = fixture.plan, fixture.manifest
        self.context = fixture.context
        self.native = {
            "format": 0.3,
            "resolution": {
                "map_origin": {"x": 0, "y": 0},
                "map_size": {"x": 24, "y": 17},
                "pixels_per_grid": 64,
            },
            "line_of_sight": [[{"x": 0, "y": 1}, {"x": 2.5, "y": 1}]],
            "objects_line_of_sight": [],
            "portals": [
                {"bounds": [{"x": 2.5, "y": 1}, {"x": 3.5, "y": 1}], "closed": True}
            ],
            "lights": [
                {
                    "position": {"x": 3, "y": 2.2},
                    "range": 0.6,
                    "intensity": 0.75,
                    "color": "ffffaa55",
                    "shadows": True,
                }
            ],
            "environment": {"baked_lighting": False, "ambient_light": "ffffffff"},
        }
        self.native["image"] = base64.b64encode(
            b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", 1536, 1088)
        ).decode()

    def scene(self, native=None):
        return foundry_scene(
            native or self.native,
            self.plan,
            self.manifest,
            64,
            "maps/ambush/battlemap.png",
        )[0]

    def test_landmarks_and_new_level_schema(self):
        scene = self.scene()
        self.assertEqual(scene["walls"][0]["c"], [0, 64, 160, 64])
        door = scene["walls"][1]
        self.assertEqual(door["c"], [160, 64, 224, 64])
        self.assertEqual((door["door"], door["ds"]), (1, 0))
        light = scene["lights"][0]
        self.assertEqual((light["x"], light["y"]), (192, 140.8))
        self.assertEqual(light["config"]["dim"], 3)
        self.assertEqual(light["config"]["color"], "#ffaa55")
        self.assertNotIn("background", scene)
        self.assertEqual(scene["initialLevel"], scene["levels"][0]["_id"])
        self.assertEqual((scene["width"], scene["height"]), (1536, 1088))

    def test_mechanical_walls_are_independent_of_vision(self):
        scene = self.scene()
        mechanical = [
            w for w in scene["walls"] if w["flags"]["dungeondraft-mcp"]["movement_only"]
        ]
        expected = (
            sum(
                bool(g.get("blocking_radius"))
                for s in self.plan["features"].values()
                for g in s.get("generated", [])
            )
            * 8
        )
        self.assertEqual(len(mechanical), expected)
        self.assertTrue(
            all(
                w["move"] == 20 and w["sight"] == 0 and w["light"] == 0
                for w in mechanical
            )
        )
        self.assertEqual(scene, self.scene())
        self.assertEqual(len({w["_id"] for w in scene["walls"]}), len(scene["walls"]))

    def test_native_image_contract(self):
        self.assertTrue(
            decode_native(self.native, self.plan["spec"], 64).startswith(b"\x89PNG")
        )
        for key, value in (
            ("format", 0.2),
            ("image", "bad-base64"),
            ("environment", {"baked_lighting": True}),
        ):
            changed = copy.deepcopy(self.native)
            changed[key] = value
            with self.assertRaises(BridgeError):
                decode_native(changed, self.plan["spec"], 64)
        changed = copy.deepcopy(self.native)
        changed["resolution"]["map_origin"]["x"] = 1
        with self.assertRaises(BridgeError):
            decode_native(changed, self.plan["spec"], 64)

    def test_open_door_and_clipping(self):
        self.native["portals"][0]["closed"] = False
        self.native["line_of_sight"][0][0]["x"] = -2
        scene = self.scene()
        self.assertEqual(scene["walls"][0]["c"][0], 0)
        self.assertEqual(scene["walls"][1]["ds"], 1)

    def test_invalid_native_geometry_rejected(self):
        for value in (True, float("nan"), float("inf"), "3"):
            changed = copy.deepcopy(self.native)
            changed["lights"][0]["position"]["x"] = value
            with self.assertRaises(BridgeError):
                self.scene(changed)
        self.native["lights"][0]["range"] = -1
        with self.assertRaises(BridgeError):
            self.scene()

    def test_safe_foundry_upload_paths(self):
        self.assertEqual(
            image_path("maps/ambush/battlemap.png"), "maps/ambush/battlemap.png"
        )
        for bad in (
            "../battlemap.png",
            "/maps/a.png",
            "https://example.com/a.png",
            "C:/maps/a.png",
            "maps/a%2fb.png",
            "maps/a.png?x",
            "maps/../a.png",
        ):
            with self.assertRaises(BridgeError):
                image_path(bad)

    def test_deep_water_preserves_crossing_gap(self):
        from shapely.geometry import box, mapping, LineString, Point

        self.plan["features"]["stream"]["spec"]["depth"] = "deep"
        self.plan["features"]["stream"]["geometry"] = mapping(box(0, 8, 24, 9))
        self.plan["features"]["crossing"] = {
            "type": "clear_area",
            "spec": {"purpose": "crossing"},
            "geometry": mapping(box(11, 7, 13, 10)),
        }
        walls = [
            w
            for w in self.scene()["walls"]
            if w["flags"]["dungeondraft-mcp"]["source"] == "stream"
        ]
        self.assertTrue(walls)
        for wall in walls:
            line = LineString([wall["c"][:2], wall["c"][2:]])
            self.assertGreater(line.distance(Point(12 * 64, 8.5 * 64)), 0)

    def test_lights_and_text_are_not_movement_obstacles(self):
        from dungeondraft_mcp.layout.validation import validate

        for i, kind in enumerate(("light", "text")):
            self.context["content"]["elements"].append(
                {"id": 1000 + i, "kind": kind, "bounds": [[0, 0], [6144, 4352]]}
            )
        report = validate(self.plan, self.manifest, self.context)
        self.assertTrue(report["valid"], report["findings"])
        self.assertEqual(report["manual_element_count"], 2)


if __name__ == "__main__":
    unittest.main()
