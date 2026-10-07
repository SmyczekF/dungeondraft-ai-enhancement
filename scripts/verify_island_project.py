"""Verify the saved island example in an already running disposable editor.

Usage: python scripts/verify_island_project.py --project C:/maps/final-project --output C:/maps/review
Never starts/stops the editor, saves over a project, or changes map content.
"""

import argparse
import asyncio
import base64
import json
import sys
from pathlib import Path

from mcp import StdioServerParameters
from mcp.client import Client
from shapely.geometry import Point, box
from shapely.ops import unary_union


async def verify(project: Path, output: Path):
    root = Path(__file__).resolve().parents[1]
    command = (
        root
        / ".venv"
        / (
            "Scripts/dungeondraft-mcp.exe"
            if sys.platform == "win32"
            else "bin/dungeondraft-mcp"
        )
    )
    report = {}
    output.mkdir(parents=True, exist_ok=False)
    async with Client(StdioServerParameters(command=str(command))) as client:

        async def call(name, **params):
            result = await client.call_tool(name, params)
            if result.is_error:
                raise RuntimeError(name + ": " + str(result))
            value = json.loads(next(c.text for c in result.content if c.type == "text"))
            report.setdefault(name, []).append(value)
            return value

        async def capture(name, tool_name, **params):
            result = await client.call_tool(tool_name, params)
            if result.is_error:
                raise RuntimeError(str(result))
            content = next(c for c in result.content if c.type == "image")
            (output / name).write_bytes(base64.b64decode(content.data))

        assert (await call("ping"))["protocol"] == 23
        start = await call("get_status")
        assert start["map_open"] and start["map_size_woxels"] == [8960, 8960]
        floors = await call("list_levels")
        ground = next(f for f in floors["levels"] if f["label"] == "Ground")
        upper = next(f for f in floors["levels"] if f["label"] == "Watchtower +10 ft")
        assert len(floors["levels"]) == 2
        await call("set_level", index=ground["index"])
        loaded = await call("load_battlemap_project", directory=str(project))
        plan_id = loaded["plan_id"]
        assert loaded["validation"]["valid"], loaded
        status = await call("get_status")
        assert status["level_id"] == ground["id"]
        assert status["counts"] == dict(
            objects=56,
            walls=10,
            lights=1,
            paths=7,
            portals=5,
            roofs=0,
            patterns=4,
            texts=0,
        ), status
        patterns = (await call("list_elements", kind="patterns", limit=200))["elements"]
        assert sorted(p["layer"] for p in patterns) == [-100, -100, -100, 100]
        objects = (await call("list_elements", kind="objects", limit=200))["elements"]
        assert {p["layer"] for p in objects} == {0, 20, 200}
        assert sum("palm" in p.get("asset", "") for p in objects) == 24
        portals = (await call("list_elements", kind="portals", limit=200))["elements"]
        assert sorted(p["closed"] for p in portals) == [False, False, False, True, True]
        await call("set_camera", x=4480, y=4480, zoom=8)
        await capture("ground.png", "export_map", ppi=96)
        await call("render_preview", plan_id=plan_id, max_pixels=2048)
        # Populated native teardown must reject before replacing the current scene.
        before = await call("get_map_info")
        rejected = await client.call_tool(
            "open_map",
            dict(path=str(project / "map.dungeondraft_map"), discard_current=True),
        )
        assert rejected.is_error
        after = await call("get_map_info")
        assert (
            before["path"] == after["path"]
            and before["bridge_instance"] == after["bridge_instance"]
        )
        report["populated_reopen_rejected"] = True
        await call("set_level", index=upper["index"])
        status = await call("get_status")
        assert status["level_id"] == upper["id"]
        assert status["counts"] == dict(
            objects=4,
            walls=1,
            lights=0,
            paths=0,
            portals=0,
            roofs=0,
            patterns=4,
            texts=0,
        ), status
        patterns = (await call("list_elements", kind="patterns", limit=200))["elements"]
        assert all(p["layer"] == -100 for p in patterns)
        objects = (await call("list_elements", kind="objects", limit=200))["elements"]
        assert all(p["layer"] == 20 for p in objects)
        # Independent upper route check: 4 ft diameter between hatch landing and lookouts.
        # Outside the deck is not walkable; the stair object is the transition, not cover.
        cover = [
            box(
                e["bounds"][0][0] / 256,
                e["bounds"][0][1] / 256,
                e["bounds"][1][0] / 256,
                e["bounds"][1][1] / 256,
            )
            for e in objects
            if "/stairs/" not in e["asset"] and "flag_stand" not in e["asset"]
        ]
        platform = unary_union(
            [
                box(17, 13, 21, 13.7),
                box(18.4, 13.7, 21, 15.7),
                box(17, 15.7, 21, 18),
                box(17, 13.7, 17.4, 15.7),
            ]
        )
        free = platform.buffer(-0.4).difference(unary_union(cover).buffer(0.4))
        components = [free] if free.geom_type == "Polygon" else list(free.geoms)
        routes = [[(19, 15.7), (19.2, 14.9)], [(19, 15.7), (19.2, 17)]]
        report["upper_routes"] = [
            any(c.covers(Point(a)) and c.covers(Point(b)) for c in components)
            for a, b in routes
        ]
        assert all(report["upper_routes"]), report["upper_routes"]
        await call("fit_elements", ids=[e["id"] for e in objects], pad=0.5)
        await capture("watchtower-editor.png", "screenshot")
        await capture("upper.png", "export_map", ppi=96)
        # A ground plan cannot validate while the upper floor is selected.
        wrong_floor = await call("validate_battlemap", plan_id=plan_id)
        assert not wrong_floor["valid"] and any(
            f["code"] == "level" for f in wrong_floor["findings"]
        )
        await call("set_level", index=ground["index"])
        final = await call("validate_battlemap", plan_id=plan_id)
        assert final["valid"] and all(r["connected"] for r in final["routes"]), final
        await call("set_camera", x=4480, y=4480, zoom=8)
        report.update(
            passed=True,
            plan_id=plan_id,
            tile_feet=5,
            scope="Saved native floors, stable session ownership, layer persistence, door states, ground/upper routes, PNG exports and populated-open guard. Pixel and Foundry runtime reviews are separate.",
        )
    (output / "acceptance.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print("PASS: island project", plan_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(verify(args.project.resolve(), args.output.resolve()))
