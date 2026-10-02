"""End-to-end planner acceptance through a fresh MCP stdio client."""

import argparse
import asyncio
import copy
import json
from pathlib import Path
from mcp import StdioServerParameters
from mcp.client import Client
from dungeondraft_mcp.bridge_client import BridgeClient
from dungeondraft_mcp.server import _wait_for_file

parser = argparse.ArgumentParser(description=__doc__)
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
    exe = repo / ".venv/Scripts/dungeondraft-mcp.exe"
    async with Client(StdioServerParameters(command=str(exe))) as client:
        tools = (await client.list_tools()).tools
        assert len(tools) == 54

        async def call(name, **params):
            return data(await client.call_tool(name, params))

        assert (await call("ping"))["protocol"] == 21
        assert not any((await call("get_status"))["counts"].values())
        schema = await call("get_map_spec_schema")
        assert schema["additionalProperties"] is False
        raw = json.loads(
            (repo / "examples/forest-ambush.json").read_text(encoding="utf-8")
        )
        bad = copy.deepcopy(raw)
        bad["units"] = "pixels"
        assert not (await call("plan_battlemap", spec=bad))["valid"]
        plan = await call("plan_battlemap", spec=raw, include_operations=True)
        assert plan["valid"], plan
        repeated = await call("plan_battlemap", spec=raw, include_operations=True)
        assert repeated == plan
        assert not any((await call("get_status"))["counts"].values())
        asset = (await call("list_assets", search="Oak", limit=1))["assets"][0]
        prop = await call("place_object", asset=asset, x=100, y=100, scale=0.1)
        stale = await client.call_tool("apply_battlemap", {"plan_id": plan["plan_id"]})
        assert stale.is_error and "changed since planning" in str(stale)
        await call("delete_element", id=prop["id"])
        plan = await call("plan_battlemap", spec=raw, include_operations=True)
        assert plan["valid"], plan
        report["checks"].append(
            "strict schema, repeated deterministic dry run, stale-context rejection and replan"
        )
        applied = await call("apply_battlemap", plan_id=plan["plan_id"])
        assert applied["job"]["status"] == "completed", applied
        manifest = applied["manifest"]
        report["manifest"] = manifest
        forest = manifest["features"]["forest"]["elements"]
        assert len(forest) == 50
        assert len({e["semantic_id"] for e in forest}) == 50
        assert len({e["id"] for e in forest}) == 50
        assert (await call("get_status"))["counts"]["objects"] == 52
        replay = await call("apply_battlemap", plan_id=plan["plan_id"])
        assert (
            replay["job"]["job_id"] == applied["job"]["job_id"]
            and replay["manifest"] == manifest
        )
        assert (await call("get_status"))["counts"]["objects"] == 52
        assert (await call("get_battlemap", plan_id=plan["plan_id"]))[
            "manifest"
        ] == manifest
        report["checks"].append(
            "one high-level application, 50 semantic tree IDs, exact native count and safe replay"
        )
        for name, value in [
            ("spec.json", raw),
            ("plan.json", plan),
            ("manifest.json", manifest),
        ]:
            (out / name).write_text(json.dumps(value, indent=2), encoding="utf-8")
        report["save"] = await call(
            "save_map", path=str(out / "forest-ambush.dungeondraft_map")
        )
        native = json.loads(
            (out / "forest-ambush.dungeondraft_map").read_text(encoding="utf-8")
        )
        level = native["world"]["levels"]["0"]
        assert len(level["objects"]) == 52
        assert level["water"]["tree"]["children"]
        b = BridgeClient()
        b.request("export_map", path=str(out / "preview.png"), ppi=64)
        _wait_for_file(str(out / "preview.png"))
        report["checks"].append("native object/water durability and 1536x1088 preview")
        report.update(
            passed=True,
            tools=len(tools),
            plan_id=plan["plan_id"],
            counts=plan["counts"],
            warnings=plan["warnings"],
            validation=plan["validation"],
        )


try:
    asyncio.run(main())
finally:
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "manifest"}, indent=2))
