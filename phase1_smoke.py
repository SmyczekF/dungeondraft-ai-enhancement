r"""End-to-end Phase 1 check against a disposable Dungeondraft session.

Run only after loading the updated mod. This replaces the open map:

    .venv\Scripts\python.exe phase1_smoke.py --discard-current --output-dir <new-directory>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dungeondraft_mcp.server import (
    bridge,
    create_map,
    get_capabilities,
    list_asset_metadata,
    list_elements,
    save_map,
)


def one_asset(category: str, search: str) -> str:
    result = bridge.request("list_assets", category=category, search=search, limit=1)
    if not result["assets"]:
        raise RuntimeError(f"no {category} asset matching {search!r}")
    return result["assets"][0]


def run(output_dir: Path) -> dict:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RuntimeError(f"output directory must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    capabilities = get_capabilities()
    if capabilities["protocol"] != 17:
        raise RuntimeError(f"reload the forked mod; expected protocol 17, got {capabilities['protocol']}")
    required = {"create_map", "open_map", "save_map", "list_asset_metadata", "get_capabilities"}
    if not required.issubset(capabilities["commands"]):
        raise RuntimeError("bridge is missing Phase 1 commands")

    grass = one_asset("Terrain", "terrain_grass.png")
    dirt = one_asset("Terrain", "terrain_dirt.png")
    trees = bridge.request("list_assets", category="Objects", search="more_trees/oak_", limit=10)["assets"]
    if len(trees) < 2:
        raise RuntimeError("need at least two oak assets")
    metadata = list_asset_metadata(category="Objects", search="more_trees/oak_", limit=2)
    if len(metadata["assets"]) != 2 or "texture_pixels" not in metadata["assets"][0]:
        raise RuntimeError("asset metadata lacks oak texture dimensions")

    map_info = create_map(20, 16, discard_current=True)
    if map_info["size_tiles"] != [20, 16] or map_info["path"]:
        raise RuntimeError(f"new map is not blank 20x16: {map_info}")
    bridge.request("fill_terrain", slot=0, asset=grass)
    bridge.request(
        "paint_path", points=[[2560, 100], [2490, 1100], [2630, 2200], [2560, 3990]],
        slot=1, radius=160, rate=1, asset=dirt,
    )

    placed = []
    for row, y in enumerate((550, 1250, 1950, 2650, 3350)):
        for side, x in enumerate((1650, 3470)):
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

    report = {
        "capabilities": capabilities,
        "map": saved["map"],
        "assets": {"grass": grass, "dirt": dirt, "trees": trees, "oak_metadata": metadata["assets"]},
        "objects": reopened["elements"],
        "native_path": str(native_path),
        "native_bytes": native_path.stat().st_size,
        "preview_path": str(preview_path),
        "preview_bytes": preview_path.stat().st_size,
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discard-current", action="store_true", help="required: replace the open map")
    parser.add_argument("--output-dir", type=Path, required=True)
    options = parser.parse_args()
    if not options.discard_current:
        parser.error("--discard-current is required; save any open map before running")
    print(json.dumps(run(options.output_dir), indent=2))
