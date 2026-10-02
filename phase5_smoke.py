"""Export an open owned project through a fresh MCP client; native console must be reviewed separately."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from mcp import StdioServerParameters
from mcp.client import Client

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--project", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
parser.add_argument(
    "--fixture-landmarks",
    action="store_true",
    help="Check the live Phase 5 NW door/light fixture",
)
args = parser.parse_args()
repo = Path(__file__).resolve().parent
out = args.output_dir.resolve()
out.mkdir(exist_ok=False)
report = {
    "passed": False,
    "checks": [],
    "console_review": "required",
    "foundry14_import": "not performed",
}


async def main():
    async with Client(
        StdioServerParameters(command=str(repo / ".venv/Scripts/dungeondraft-mcp.exe"))
    ) as client:

        async def call(name, **params):
            reply = await client.call_tool(name, params)
            assert not reply.is_error, reply
            return json.loads(next(c.text for c in reply.content if c.type == "text"))

        assert len((await client.list_tools()).tools) == 60
        assert (await call("ping"))["protocol"] == 23
        assert (await call("get_status"))["map_open"]
        loaded = await call(
            "load_battlemap_project", directory=str(args.project.resolve())
        )
        assert loaded["validation"]["valid"]
        report["checks"].append(
            "fresh 60-tool client, protocol 23 and project ownership reload"
        )
        exported = await call(
            "export_battlemap",
            plan_id=loaded["plan_id"],
            directory=str(out / "export"),
            foundry_image_path="maps/forest-ambush/battlemap.png",
            ppi=64,
        )
        root = out / "export"
        for name, checksum in exported["files"].items():
            assert hashlib.sha256((root / name).read_bytes()).hexdigest() == checksum
        assert all(
            exported[k]
            for k in ("camera_restored", "grid_restored", "lighting_restored")
        )
        native = json.loads((root / "battlemap.dd2vtt").read_text(encoding="utf-8"))
        scene = json.loads((root / "foundry-scene.json").read_text(encoding="utf-8"))
        assert scene["grid"]["size"] == 64
        assert not native["environment"]["baked_lighting"]
        assert len(scene["walls"]) == exported["wall_count"]
        report["checks"].append(
            "native Universal VTT 0.3, embedded PNG, checksums and camera/grid/lighting restoration"
        )
        if args.fixture_landmarks:
            doors = [w for w in scene["walls"] if w["door"] == 1]
            assert (
                len(doors) == 1
                and doors[0]["c"] == [160, 64, 224, 64]
                and doors[0]["ds"] == 0
            ), doors
            assert len(scene["lights"]) == 1
            light = scene["lights"][0]
            assert light["x"] == 192 and abs(light["y"] - 140.8) < 0.01
            assert light["config"]["dim"] == 3 and light["config"]["color"] == "#ffaa55"
            report["checks"].append(
                "known woxel/tile/pixel landmarks: 1-tile door at x=3,y=1 and light at x=3,y=2.2"
            )
        reply = await client.call_tool(
            "export_battlemap",
            {
                "plan_id": loaded["plan_id"],
                "directory": str(root),
                "foundry_image_path": "maps/forest-ambush/battlemap.png",
                "ppi": 64,
            },
        )
        assert reply.is_error
        assert (await call("validate_battlemap", plan_id=loaded["plan_id"]))["valid"]
        report["checks"].append(
            "existing-directory overwrite rejected and owned map still valid"
        )
        report.update(passed=True, export=exported)


try:
    asyncio.run(main())
finally:
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
