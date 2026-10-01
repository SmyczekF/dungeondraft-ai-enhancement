r"""Measure the live MCP and build the Phase 0 sample on the open map.

Run from the repository venv with a disposable map open in Dungeondraft:

    .venv\Scripts\python.exe phase0_baseline.py --output-dir <directory>

Temporary benchmark objects are deleted. The final ten-tree sample remains
open in the editor; the bridge cannot save a native map yet.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
from pathlib import Path
import sys
from time import perf_counter

from mcp import StdioServerParameters
from mcp.client import Client


async def call(client: Client, name: str, **args):
    result = await client.call_tool(name, args)
    if result.is_error:
        detail = result.content[0].text if result.content else "unknown error"
        raise RuntimeError(f"{name}: {detail}")
    if not result.content or result.content[0].type != "text":
        raise RuntimeError(f"{name}: expected a JSON text result")
    return json.loads(result.content[0].text)


async def save_image(client: Client, name: str, path: Path, **args):
    result = await client.call_tool(name, args)
    if result.is_error:
        detail = result.content[0].text if result.content else "unknown error"
        raise RuntimeError(f"{name}: {detail}")
    images = [block for block in result.content if block.type == "image"]
    if len(images) != 1:
        raise RuntimeError(f"{name}: expected one image, got {len(images)}")
    path.write_bytes(base64.b64decode(images[0].data))
    return {"path": str(path), "bytes": path.stat().st_size, "mime": images[0].mime_type}


async def benchmark(client: Client, asset: str, count: int):
    ids = []
    placed_seconds = None
    deleted_seconds = None
    before = (await call(client, "get_status"))["counts"]["objects"]
    try:
        start = perf_counter()
        for index in range(count):
            x = 1200 + (index % 20) * 170
            y = 600 + (index // 20) * 170
            made = await call(client, "place_object", asset=asset, x=x, y=y)
            ids.append(made["id"])
        placed_seconds = perf_counter() - start
        after = (await call(client, "get_status"))["counts"]["objects"]
        if after != before + count:
            raise RuntimeError(f"placed {count} objects but count changed {before}->{after}")
    finally:
        start = perf_counter()
        for element_id in ids:
            await call(client, "delete_element", id=element_id)
        deleted_seconds = perf_counter() - start
    final = (await call(client, "get_status"))["counts"]["objects"]
    if final != before:
        raise RuntimeError(f"benchmark cleanup left {final - before} objects")
    return {
        "count": count,
        "placement_seconds": round(placed_seconds, 3),
        "placement_ms_per_call": round(1000 * placed_seconds / count, 1),
        "cleanup_seconds": round(deleted_seconds, 3),
        "transport": "one persistent MCP stdio session; bridge opens one TCP connection per tool call",
    }


async def build_sample(client: Client):
    status = await call(client, "get_status")
    if status["counts"]["objects"] != 0:
        raise RuntimeError("sample requires zero existing objects; refusing to add duplicate trees")
    grass = (await call(client, "list_assets", category="Terrain", search="terrain_grass.png"))["assets"][0]
    dirt = (await call(client, "list_assets", category="Terrain", search="terrain_dirt.png"))["assets"][0]
    oaks = (await call(client, "list_assets", category="Objects", search="more_trees/oak_", limit=20))["assets"]
    if len(oaks) < 2:
        raise RuntimeError("expected at least two oak assets")

    await call(client, "fill_terrain", slot=0, asset=grass)
    path_points = [[4480, 300], [4420, 1250], [4520, 2200], [4460, 3250], [4480, 4820]]
    await call(client, "paint_path", points=path_points, slot=1, radius=220, rate=1, asset=dirt)

    trees = []
    for row, y in enumerate((700, 1550, 2400, 3250, 4100)):
        for side, x in enumerate((3500 + (row % 2) * 130, 5350 - (row % 2) * 120)):
            asset = oaks[(row + side) % len(oaks)]
            made = await call(
                client, "place_object", asset=asset, x=x, y=y,
                scale=(0.85, 1.0, 1.1)[(row + side) % 3], rotation=(row * 17 + side * 29) % 360,
            )
            trees.append({"id": made["id"], "asset": asset, "x": x, "y": y})
    objects = (await call(client, "list_elements", kind="objects", limit=20))["elements"]
    found = {element["id"] for element in objects}
    expected = {tree["id"] for tree in trees}
    if found != expected:
        raise RuntimeError(f"sample object IDs do not match: expected {expected}, found {found}")
    return {"grass": grass, "dirt": dirt, "path_points": path_points, "trees": trees}


async def main(output_dir: Path, capture_only: bool):
    output_dir.mkdir(parents=True, exist_ok=True)
    server = Path(sys.executable).with_name("dungeondraft-mcp.exe")
    if not server.is_file():
        raise RuntimeError(f"MCP entrypoint missing: {server}")
    params = StdioServerParameters(command=str(server))
    async with Client(params) as client:
        ping = await call(client, "ping")
        status = await call(client, "get_status")
        if not status.get("map_open"):
            raise RuntimeError("open a disposable map in Dungeondraft first")
        if capture_only:
            if status["counts"]["objects"] != 10:
                raise RuntimeError("capture-only requires exactly ten existing objects")
            report_path = output_dir / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
            report["ping"] = ping
            report["sample_objects"] = (await call(client, "list_elements", kind="objects", limit=20))["elements"]
        else:
            if any(status["counts"].values()):
                raise RuntimeError("map has elements; refusing to run baseline on a nonempty map")
            asset_result = await call(client, "list_assets", category="Objects", search="more_trees/oak_", limit=10)
            if not asset_result["assets"]:
                raise RuntimeError("oak tree assets unavailable")
            report = {"ping": ping, "initial_status": status, "asset_discovery": asset_result, "benchmarks": []}
            for count in (10, 50, 200):
                print(f"Benchmarking {count} placements...", flush=True)
                result = await benchmark(client, asset_result["assets"][0], count)
                report["benchmarks"].append(result)
                print(json.dumps(result), flush=True)
            print("Building ten-tree sample...", flush=True)
            report["sample"] = await build_sample(client)
        report["final_status"] = await call(client, "get_status")
        (output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["screenshot"] = await save_image(client, "screenshot", output_dir / "screenshot.png")
        report["export"] = await save_image(client, "export_map", output_dir / "sample-map.png", ppi=40)
        (output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote {output_dir / 'report.json'}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--capture-only", action="store_true", help="capture an existing ten-object sample")
    options = parser.parse_args()
    asyncio.run(main(options.output_dir, options.capture_only))
