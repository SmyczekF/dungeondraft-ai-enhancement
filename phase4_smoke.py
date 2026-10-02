"""Phase 4 acceptance against an open, saved project through fresh MCP stdio."""

import argparse
import asyncio
import copy
import json
from pathlib import Path
from mcp import StdioServerParameters
from mcp.client import Client
from dungeondraft_mcp.bridge_client import BridgeClient
from dungeondraft_mcp.server import _wait_for_batch

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--project", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
args = parser.parse_args()
out = args.output_dir.resolve()
out.mkdir(exist_ok=False)
repo = Path(__file__).resolve().parent
report = {"passed": False, "checks": [], "console_review": "required"}


def data(reply):
    assert not reply.is_error, reply
    return json.loads(next(c.text for c in reply.content if c.type == "text"))


async def main():
    async with Client(
        StdioServerParameters(command=str(repo / ".venv/Scripts/dungeondraft-mcp.exe"))
    ) as client:

        async def call(name, **params):
            return data(await client.call_tool(name, params))

        tools = (await client.list_tools()).tools
        assert len(tools) == 59, len(tools)
        assert (await call("ping"))["protocol"] == 22
        assert (await call("get_status"))["map_open"]
        loaded = await call(
            "load_battlemap_project", directory=str(args.project.resolve())
        )
        current = loaded["plan_id"]
        assert loaded["validation"]["valid"]
        initial = await call("get_battlemap", plan_id=current, include_operations=True)
        preview = await client.call_tool("render_preview", {"plan_id": current})
        assert not preview.is_error, preview
        assert any(c.type == "image" for c in preview.content), preview
        meta = json.loads(next(c.text for c in preview.content if c.type == "text"))
        assert max(meta["preview"]["pixels"]) <= 1024
        assert meta["preview"]["camera_restored"] and meta["preview"]["grid_restored"]
        report["checks"].append(
            "fresh 59-tool client, project ownership reload, structural validation and native PNG content with restored camera/grid"
        )
        native = BridgeClient()
        manual = (
            await call(
                "place_object",
                asset=initial["manifest"]["features"]["boulder_west"]["elements"][0][
                    "operation"
                ]["asset"],
                x=160,
                y=160,
                scale=0.08,
            )
        )["id"]
        manual_before = await call("get_element", id=manual)
        before = await call("list_elements", kind="objects", limit=200)
        feature = copy.deepcopy(initial["features"]["boulder_west"]["spec"])
        feature["position"] = [8.15, 9.1]
        feature["rotation"] = 23.0
        assets = await call(
            "list_asset_metadata", category="Objects", search="boulder", limit=200
        )
        alternatives = [
            row["path"]
            for row in assets["assets"]
            if row["path"] != feature["asset"]
            and row["path"]
            != initial["features"]["boulder_west"]["generated"][0]["asset"]
        ]
        if alternatives:
            feature["asset"] = alternatives[0]
        dry = await call("revise_battlemap", plan_id=current, features=[feature])
        assert dry["valid"], dry
        assert dry["diff"]["operation_count"] <= 2, dry["diff"]
        assert before == (await call("list_elements", kind="objects", limit=200))
        applied = await call(
            "revise_battlemap", plan_id=current, features=[feature], dry_run=False
        )
        assert applied["applied"] and applied["job"]["status"] == "completed", applied
        replay = await call(
            "revise_battlemap", plan_id=current, features=[feature], dry_run=False
        )
        assert applied == replay
        new = applied["plan_id"]
        assert (
            applied["manifest"]["features"]["boulder_west"]["elements"][0]["id"]
            == initial["manifest"]["features"]["boulder_west"]["elements"][0]["id"]
        )
        assert (
            applied["manifest"]["features"]["forest"]["elements"]
            == initial["manifest"]["features"]["forest"]["elements"]
        )
        assert (await call("validate_battlemap", plan_id=new))["valid"]
        assert manual_before == (await call("get_element", id=manual))
        report["checks"].append(
            "two-operation boulder movement/retexture, stable IDs, idempotent revision, all 50 unselected trees and manual prop preserved"
        )
        # Reversible deletion rollback: cancel a job after deletion plus some creates.
        victim = initial["manifest"]["features"]["forest"]["elements"][0]["id"]
        victim_before = await call("get_element", id=victim)
        op = {
            "cmd": "place_object",
            "asset": manual_before["asset"],
            "x": 300,
            "y": 300,
            "scale": 0.05,
        }
        job = native.request(
            "apply_batch",
            schema_version=1,
            idempotency_key="phase4-delete-cancel",
            operations=[{"cmd": "delete_object", "id": victim}] + [op] * 200,
        )
        job = _wait_for_batch(native.request("cancel_batch", job_id=job["job_id"]), 90)
        assert job["status"] == "cancelled", job
        assert victim_before == (await call("get_element", id=victim))
        report["checks"].append(
            "reversible native deletion restored identical ID/artwork/transform during batch cancellation"
        )
        # Drift is a structured finding, not silently overwritten.
        await call("move_element", id=manual, x=180, y=160)
        assert (await call("validate_battlemap", plan_id=new))["valid"]
        await call("move_element", id=manual, x=160, y=160)
        owned = applied["manifest"]["features"]["boulder_west"]["elements"][0]["id"]
        actual = await call("get_element", id=owned)
        await call(
            "move_element",
            id=owned,
            x=actual["position"][0] + 64,
            y=actual["position"][1],
        )
        drift = await call("validate_battlemap", plan_id=new)
        assert not drift["valid"] and any(
            f["code"] == "position_changed" for f in drift["findings"]
        )
        await call("undo")
        assert (await call("validate_battlemap", plan_id=new))["valid"]
        # Forest shrink should only delete the last two semantic members.
        forest = copy.deepcopy(initial["features"]["forest"]["spec"])
        forest["count"] = 48
        shrunk = await call(
            "revise_battlemap", plan_id=new, features=[forest], dry_run=False
        )
        assert shrunk.get("applied"), shrunk
        new = shrunk["plan_id"]
        assert len(shrunk["manifest"]["features"]["forest"]["elements"]) == 48
        assert (await call("get_status"))["counts"]["objects"] == 51
        assert manual_before == (await call("get_element", id=manual))
        assert (await call("validate_battlemap", plan_id=new))["valid"]
        report["checks"].append(
            "structured owned-edit finding, reversible recovery, forest shrink and manual edit preservation"
        )
        # Road repaint keeps all object IDs; explicitly allow forest regeneration.
        state = await call("get_battlemap", plan_id=new)
        road = copy.deepcopy(state["features"]["road"]["spec"])
        road["width"] = 2.2
        widened = await call(
            "revise_battlemap", plan_id=new, features=[road, forest], dry_run=False
        )
        assert widened.get("applied"), widened
        new = widened["plan_id"]
        assert widened["diff"]["counts"]["fill_terrain"] == 1
        assert manual_before == (await call("get_element", id=manual))
        assert (await call("validate_battlemap", plan_id=new))["valid"]
        # A manual terrain edit must prevent shared-surface replacement.
        surface = native.request("get_surface_state")
        native.request("paint_terrain", slot=1, x=300, y=300, radius=70, rate=1.0)
        drift = await call("validate_battlemap", plan_id=new)
        assert not drift["valid"] and any(
            f["code"] == "terrain_changed" for f in drift["findings"]
        )
        refused = await call("revise_battlemap", plan_id=new, features=[road])
        assert not refused["valid"]
        native.request("undo")
        assert native.request("get_surface_state") == surface
        assert (await call("validate_battlemap", plan_id=new))["valid"]
        report["checks"].append(
            "owned road repaint, manual prop preserved, manual terrain checksum conflict rejected before editing"
        )
        saved = await call(
            "save_battlemap_project", plan_id=new, directory=str(out / "project")
        )
        assert saved["saved"]
        report["project"] = saved["directory"]
        report["plan_id"] = new
        report["manual_id"] = manual
        native_json = json.loads(
            (out / "project/map.dungeondraft_map").read_text(encoding="utf-8")
        )
        assert len(native_json["world"]["levels"]["0"]["objects"]) == 51
        duplicate = await client.call_tool(
            "save_battlemap_project",
            {"plan_id": new, "directory": str(out / "project")},
        )
        assert duplicate.is_error
        report["checks"].append(
            "complete checksummed project with 51 native objects; existing directory overwrite rejected"
        )
    async with Client(
        StdioServerParameters(command=str(repo / ".venv/Scripts/dungeondraft-mcp.exe"))
    ) as client:
        loaded = data(
            await client.call_tool(
                "load_battlemap_project", {"directory": str(out / "project")}
            )
        )
        assert loaded["loaded"] and loaded["validation"]["manual_element_count"] == 1
        report["checks"].append(
            "second fresh MCP process restored project ownership and identified unowned manual content"
        )
    report["passed"] = True


try:
    asyncio.run(main())
finally:
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
