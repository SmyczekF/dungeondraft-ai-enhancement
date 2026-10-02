r"""End-to-end Phase 1 check against an open, blank disposable map.

Create a blank map of at least 20 x 16 tiles manually, then run:

    .venv\Scripts\python.exe phase1_smoke.py --output-dir <new-directory>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dungeondraft_mcp.server import (
    bridge,
    get_capabilities,
    list_asset_metadata,
    list_elements,
    open_map,
    save_map,
)


def one_asset(category: str, search: str) -> str:
    result = bridge.request("list_assets", category=category, search=search, limit=1)
    if not result["assets"]:
        raise RuntimeError(f"no {category} asset matching {search!r}")
    return result["assets"][0]


def verify_inspection(output_dir: Path, sample_path: Path) -> dict:
    """Check each descriptor kind and native durability on a mixed scene."""
    wall = bridge.request("draw_wall", points=[[1000, 1000], [2200, 1000],
                          [2200, 2200], [1000, 2200]], asset=one_asset("Walls", ""), loop=True)
    bridge.request("draw_path", points=[[1000, 2500], [1600, 2600], [2200, 2500]],
                   asset=one_asset("Paths", ""))
    bridge.request("add_light", x=1500, y=1500, energy=1.5)
    portal_asset = one_asset("Portals", "")
    mounted = bridge.request("add_portal", asset=portal_asset, x=1600, y=1000,
                             mount="wall", fallback_free=False)
    free = bridge.request("add_portal", asset=portal_asset, x=2500, y=1000, mount="free")
    bridge.request("add_roof", points=[[1300, 1600], [1900, 1600]], width=600,
                   asset=one_asset("Roofs", ""))
    floor_asset = one_asset("Simple Tiles", "")
    floor_ids = []
    for rect in ([1000, 1000, 1200, 1200], [2500, 3000, 300, 300]):
        floor_ids.append(bridge.request("place_pattern", rect=rect, asset=floor_asset,
                                        category="Simple Tiles")["id"])
    bridge.request("add_text", text="Phase 1 inspection", x=1000, y=3000, size=32)
    kinds = ("objects", "walls", "paths", "lights", "portals", "roofs", "patterns", "texts")
    before = {kind: list_elements(kind=kind, limit=500) for kind in kinds}
    counts = bridge.request("get_status")["counts"]
    if any(counts[kind] != before[kind]["total"] for kind in kinds):
        raise RuntimeError("status counts disagree with element inspection")
    if before["patterns"]["total"] != 2:
        raise RuntimeError("pattern count must count shapes, not layer containers")
    mixed_path = output_dir / "mixed.dungeondraft_map"
    saved = save_map(path=str(mixed_path))
    after = {kind: list_elements(kind=kind, limit=500) for kind in kinds}
    for kind in kinds:
        expected = {(item["id"], item.get("asset")) for item in before[kind]["elements"]}
        actual = {(item["id"], item.get("asset")) for item in after[kind]["elements"]}
        if before[kind]["total"] != after[kind]["total"] or expected != actual:
            raise RuntimeError(f"{kind} IDs/assets changed after save/reopen")
        page = list_elements(kind=kind, offset=1, limit=1)
        if page["total"] != after[kind]["total"] or page["elements"] != after[kind]["elements"][1:2]:
            raise RuntimeError(f"{kind} pagination failed")
        for item in after[kind]["elements"]:
            if item["kind"] == "unknown" or "bounds" not in item:
                raise RuntimeError(f"{kind} descriptor lacks type/bounds: {item}")
            if kind != "texts" and ("asset" not in item or "layer" not in item):
                raise RuntimeError(f"{kind} descriptor lacks asset/layer: {item}")
            if bridge.request("get_element", id=item["id"]) != item:
                raise RuntimeError(f"get_element disagrees with list_elements for {item['id']}")
    portals = {item["id"]: item for item in after["portals"]["elements"]}
    if portals[mounted["id"]].get("wall_id") != wall["id"] or portals[free["id"]]["kind"] != "portal":
        raise RuntimeError("mounted and free portal descriptors are confused")
    free_bounds = portals[free["id"]]["bounds"]
    if not (free_bounds[0][0] <= 2500 <= free_bounds[1][0]
            and free_bounds[0][1] <= 1000 <= free_bounds[1][1]):
        raise RuntimeError("free portal bounds are not in world coordinates")
    light_bounds = after["lights"]["elements"][0]["bounds"]
    if light_bounds[0][0] >= light_bounds[1][0] or light_bounds[0][1] >= light_bounds[1][1]:
        raise RuntimeError("light texture bounds have no area")
    if {item["id"] for item in after["patterns"]["elements"]} != set(floor_ids):
        raise RuntimeError("pattern descriptors do not reference the created shapes")
    open_map(str(sample_path), discard_current=True)
    return {"saved": saved, "elements": after}


def run(output_dir: Path) -> dict:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RuntimeError(f"output directory must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    bridge.request("ping")
    status = bridge.request("get_status")
    capabilities = get_capabilities()
    if capabilities["protocol"] != 18:
        raise RuntimeError(f"reload the forked mod; expected protocol 18, got {capabilities['protocol']}")
    required = {"open_map", "save_map", "list_asset_metadata", "get_capabilities"}
    if not required.issubset(capabilities["commands"]):
        raise RuntimeError("bridge is missing Phase 1 commands")
    if "create_map" in capabilities["commands"]:
        raise RuntimeError("unsafe create_map command is still exposed; reload the forked mod")

    map_info = bridge.request("get_map_info")
    if not map_info["map_open"] or any(status["counts"].values()):
        raise RuntimeError("open a blank disposable map before running this check")
    width, height = map_info["size_woxels"]
    if width < 5120 or height < 4096:
        raise RuntimeError("disposable map must be at least 20 x 16 tiles")

    grass = one_asset("Terrain", "terrain_grass.png")
    dirt = one_asset("Terrain", "terrain_dirt.png")
    trees = bridge.request("list_assets", category="Objects", search="more_trees/oak_", limit=10)["assets"]
    if len(trees) < 2:
        raise RuntimeError("need at least two oak assets")
    metadata = list_asset_metadata(category="Objects", search="more_trees/oak_", limit=2)
    if len(metadata["assets"]) != 2 or "texture_pixels" not in metadata["assets"][0]:
        raise RuntimeError("asset metadata lacks oak texture dimensions")

    bridge.request("fill_terrain", slot=0, asset=grass)
    center = width // 2
    bridge.request(
        "paint_path", points=[[center, 100], [center - 70, height // 3],
                              [center + 70, 2 * height // 3], [center, height - 100]],
        slot=1, radius=160, rate=1, asset=dirt,
    )

    placed = []
    for row in range(5):
        y = round(height * (0.15 + row * 0.175))
        for side, x in enumerate((round(width * 0.33), round(width * 0.67))):
            asset = trees[(row + side) % len(trees)]
            made = bridge.request("place_object", asset=asset, x=x, y=y)
            placed.append({"id": made["id"], "asset": asset, "position": [x, y]})

    page0 = list_elements(kind="objects", offset=0, limit=5)
    page1 = list_elements(kind="objects", offset=5, limit=5)
    if page0["total"] != 10 or page1["total"] != 10 or page0["count"] != 5 or page1["count"] != 5:
        raise RuntimeError("object pagination failed before save")
    if any("bounds" not in item or "layer" not in item for item in page0["elements"]):
        raise RuntimeError("object descriptors lack bounds or layer")

    native_path = output_dir / "sample.dungeondraft_map"
    saved = save_map(path=str(native_path), verify_reopen=True)
    level_data = next(iter(json.loads(native_path.read_text(encoding="utf-8-sig"))["world"]["levels"].values()))
    if len(level_data["objects"]) != 10:
        raise RuntimeError(f"native file contains {len(level_data['objects'])} trees, expected 10")

    reopened = list_elements(kind="objects", offset=0, limit=20)
    expected = {(item["id"], item["asset"]) for item in placed}
    actual = {(item["id"], item.get("asset")) for item in reopened["elements"]}
    if reopened["total"] != 10 or actual != expected:
        raise RuntimeError(f"reopened objects differ: expected={expected}, actual={actual}")

    preview_path = output_dir / "sample.png"
    bridge.request("export_map", path=str(preview_path), ppi=40)
    from dungeondraft_mcp.server import _wait_for_file
    _wait_for_file(str(preview_path))

    inspection = verify_inspection(output_dir, native_path)

    report = {
        "capabilities": capabilities,
        "map": saved["map"],
        "assets": {"grass": grass, "dirt": dirt, "trees": trees, "oak_metadata": metadata["assets"]},
        "objects": reopened["elements"],
        "native_path": str(native_path),
        "native_bytes": native_path.stat().st_size,
        "preview_path": str(preview_path),
        "preview_bytes": preview_path.stat().st_size,
        "inspection": inspection,
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    options = parser.parse_args()
    print(json.dumps(run(options.output_dir), indent=2))
