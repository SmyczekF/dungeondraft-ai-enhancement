"""Live regression: fresh disposable map, no UI automation or process restart."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from dungeondraft_mcp.server import bridge, save_map, _wait_for_file


def export(path: Path) -> str:
    bridge.request("export_map", path=str(path), ppi=40)
    _wait_for_file(str(path))
    # A second request must remain responsive after the native render.
    assert bridge.request("ping")["pong"]
    return hashlib.sha256(path.read_bytes()).hexdigest()


def descriptor(ident: int) -> dict:
    item = bridge.request("get_element", id=ident)
    return {key: item[key] for key in ("id", "asset", "position", "rotation", "scale", "layer", "bounds")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    checks = []
    try:
        ping = bridge.request("ping")
        assert ping["protocol"] == 23
        status = bridge.request("get_status")
        assert status["map_open"] and not any(status["counts"].values()), status
        checks.append({"check": "blank_map", "active_tool": status["active_tool"]})
        assets = bridge.request("list_assets", category="Objects", search="oak", limit=1)["assets"]
        assert assets
        cx, cy = status["map_center"]
        made = bridge.request("place_object", asset=assets[0], x=cx, y=cy, scale=1.1, rotation=17)
        ident = made["id"]
        expected = descriptor(ident)
        selected = bridge.request("select_elements", ids=[ident])
        assert selected["selected"] == 1
        assert bridge.request("get_status")["active_tool"] == "SelectTool"
        bridge.request("clear_selection")
        checks.append({"check": "selection_activates_tool", "passed": True})
        initial_image = export(args.output_dir / "before-undo.png")
        for cycle in range(3):
            assert bridge.request("undo")["undone"]
            assert bridge.request("get_status")["counts"]["objects"] == 0
            if cycle == 0:
                empty_image = export(args.output_dir / "undone.png")
                assert empty_image != initial_image, "undo did not change the rendered map"
            assert bridge.request("redo")["redone"]
            assert bridge.request("get_status")["counts"]["objects"] == 1
            assert descriptor(ident) == expected, (descriptor(ident), expected)
            checks.append({"check": "object_undo_redo", "cycle": cycle + 1, "id": ident})
        restored_image = export(args.output_dir / "after-redo.png")
        assert restored_image == initial_image, "object pixels changed after native redo"
        checks.append({"check": "redo_render_matches_original", "sha256": restored_image})
        # Deleting the restored, selected object used to leave a stale search node.
        bridge.request("select_elements", ids=[ident])
        assert bridge.request("delete_element", id=ident)["deleted"]
        time.sleep(0.2)
        assert bridge.request("get_status")["counts"]["objects"] == 0
        assert bridge.request("select_elements", ids=[])["selected"] == 0
        checks.append({"check": "delete_restored_selected_object", "passed": True})
        made = bridge.request("place_object", asset=assets[0], x=cx, y=cy)
        duplicate = bridge.request("duplicate_object", id=made["id"], dx=256)
        duplicate_expected = descriptor(duplicate["id"])
        bridge.request("undo")
        bridge.request("redo")
        assert descriptor(duplicate["id"]) == duplicate_expected
        for object_id in (duplicate["id"], made["id"]):
            assert bridge.request("delete_element", id=object_id)["deleted"]
        time.sleep(0.2)
        assert not any(bridge.request("get_status")["counts"].values())
        checks.append({"check": "duplicate_undo_redo_cleanup", "passed": True})
        instance_before = bridge.request("ping")["bridge_instance"]
        saved = save_map(path=str(args.output_dir / "cleaned.dungeondraft_map"))
        assert saved["valid_native_json"]
        assert bridge.request("ping")["bridge_instance"] == instance_before
        native = json.loads(Path(saved["path"]).read_text(encoding="utf-8-sig"))
        assert not any(level["objects"] for level in native["world"]["levels"].values())
        checks.append({"check": "clean_native_save_preserves_scene", "passed": True})
        print(json.dumps({"passed": True, "checks": checks}, indent=2))
        report = {"passed": True, "checks": checks, "console_review": "required: MCP success does not prove absence of native exceptions"}
    except Exception as exc:
        report = {"passed": False, "checks": checks, "error": str(exc), "console_review": "required"}
        raise
    finally:
        (args.output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
