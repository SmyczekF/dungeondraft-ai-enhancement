import unittest
from dungeondraft_mcp.bridge_client import BridgeError
from dungeondraft_mcp.layout.project import restored_level_id


class ProjectLevelTests(unittest.TestCase):
    def setUp(self):
        self.native = {
            "header": {"editor_state": {"current_level": 1}},
            "world": {"levels": {"0": {"label": "Tower"}, "1": {"label": "Ground"}}},
        }
        self.floors = {
            "current_index": 1,
            "current_id": 1,
            "levels": [
                {"index": 0, "id": 0, "label": "Tower"},
                {"index": 1, "id": 1, "label": "Ground"},
            ],
        }

    def test_regenerated_ids_bind_to_saved_floor(self):
        self.assertEqual(restored_level_id(self.native, self.floors), 1)
        self.floors["levels"][1]["id"] = 8
        self.assertEqual(restored_level_id(self.native, self.floors), 8)

    def test_wrong_active_floor_is_rejected(self):
        self.floors["current_index"] = 0
        with self.assertRaises(BridgeError):
            restored_level_id(self.native, self.floors)

    def test_reordered_or_renamed_floor_is_rejected(self):
        self.floors["levels"].reverse()
        with self.assertRaises(BridgeError):
            restored_level_id(self.native, self.floors)

    def test_missing_saved_floor_is_rejected(self):
        self.native["header"]["editor_state"]["current_level"] = 2
        with self.assertRaises(BridgeError):
            restored_level_id(self.native, self.floors)
