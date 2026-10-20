"""Build gridded, gridless and Foundry ZIP packages from a completed map.

Run: python -m dungeondraft_mcp.release <encounter-directory-or-map-release.json>
The optional, trusted encounter-local exporter refreshes Foundry corrections;
this module owns native grid artwork, validation, instructions and packaging.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import zipfile

from .bridge_client import BridgeError
from .editor_lifecycle import read_native
from .layout.vtt import NAMESPACE


class ReleaseError(ValueError):
    """An incomplete or inconsistent encounter must not become a release."""


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inside(root, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ReleaseError("Input paths must be relative to the encounter")
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ReleaseError("Input path escapes the encounter directory")
    return path


def png_size(data):
    if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ReleaseError("Expected a native PNG image")
    return struct.unpack(">II", data[16:24])


def load_config(path):
    path = Path(path).resolve()
    if path.is_dir():
        path /= "map-release.json"
    root = path.parent
    cfg = read_json(path)
    allowed = {"title", "slug", "native_map", "pixels_per_square", "floors", "foundry_exporter"}
    if set(cfg) - allowed or not isinstance(cfg.get("title"), str) or not cfg["title"].strip():
        raise ReleaseError("Invalid release configuration or unknown keys")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", cfg.get("slug", "")):
        raise ReleaseError("slug must use lowercase letters, digits and hyphens")
    ppi = cfg.get("pixels_per_square", 128)
    if type(ppi) is not int or not 50 <= ppi <= 256:
        raise ReleaseError("pixels_per_square must be an integer in 50..256")
    native = inside(root, cfg["native_map"])
    if native.suffix != ".dungeondraft_map" or not native.is_file():
        raise ReleaseError("native_map must identify the existing canonical native map")
    floors = cfg.get("floors")
    if not isinstance(floors, list) or not floors:
        raise ReleaseError("Configure at least one floor")
    names, labels, scenes = set(), set(), set()
    for floor in floors:
        if set(floor) != {"name", "native_label", "scene"}:
            raise ReleaseError("Each floor needs name, native_label and scene")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", floor["name"]):
            raise ReleaseError("Floor names must be filename-safe lowercase slugs")
        if not isinstance(floor["native_label"], str) or not floor["native_label"]:
            raise ReleaseError("Each floor needs its exact native label")
        scene = inside(root, floor["scene"])
        if scene.suffix != ".json" or floor["name"] in names or floor["native_label"] in labels or scene in scenes:
            raise ReleaseError("Floor names, native labels and scene files must be unique")
        names.add(floor["name"]); labels.add(floor["native_label"]); scenes.add(scene)
    if cfg.get("foundry_exporter"):
        exporter = inside(root, cfg["foundry_exporter"])
        if exporter.suffix != ".py" or not exporter.is_file():
            raise ReleaseError("foundry_exporter must be a trusted encounter-local Python file")
    cfg["pixels_per_square"] = ppi
    return root, cfg


def public_scene(source, expected_size, ppi, *, connected=False):
    """Require a standalone registered scene; keep functional wall/light data."""
    scene = copy.deepcopy(source)
    if not str(scene.get("_stats", {}).get("coreVersion", "")).startswith("14."):
        raise ReleaseError("This builder supports Foundry 14 scene exports")
    levels = scene.get("levels", [])
    if not levels or (len(levels) != 1 and not connected):
        raise ReleaseError("Supply one corrected single-level scene per floor")
    for level in levels[1:]:
        single = copy.deepcopy(source)
        single['levels'] = [level]
        single['tiles'] = []
        public_scene(single, expected_size, ppi)
    bg = levels[0]["background"]
    uri = bg.get("src", "")
    if not uri.startswith("data:image/png;base64,"):
        raise ReleaseError("Scene background must be an embedded PNG, not an external path")
    try:
        png = base64.b64decode(uri.split(",", 1)[1], validate=True)
    except ValueError as exc:
        raise ReleaseError("Invalid embedded PNG encoding") from exc
    if png_size(png) != expected_size or (scene.get("width"), scene.get("height")) != expected_size:
        raise ReleaseError("Scene/image dimensions differ from native dimensions at the requested resolution")
    grid = scene.get("grid", {})
    if grid.get("size") != ppi or grid.get("distance") != 5 or grid.get("units") != "ft" or grid.get("type") != 1:
        raise ReleaseError("Expected a square 5-foot grid at the configured pixels per square")
    if (scene.get("padding", 0) != 0 or scene.get("shiftX", 0) != 0 or scene.get("shiftY", 0) != 0
            or any(bg.get(k, v) != v for k, v in {"offsetX": 0, "offsetY": 0, "rotation": 0, "scaleX": 1, "scaleY": 1}.items())):
        raise ReleaseError("Shifted, scaled or padded scenes need explicit registration before packaging")
    if any(scene.get(k) for k in ("tokens", "notes", "sounds", "journal", "journalEntryPage", "playlist", "playlistSound", "weather")) or (scene.get('tiles') and not connected):
        raise ReleaseError("Standalone releases cannot depend on actors, journals or external media")
    for tile in scene.get('tiles', []):
        uri = tile.get('texture', {}).get('src', '')
        if not uri.startswith('data:image/png;base64,'):
            raise ReleaseError('Overhead artwork must be an embedded PNG')
        data = base64.b64decode(uri.split(',', 1)[1], validate=True)
        texture = tile['texture']
        if (png_size(data) != expected_size or tile.get('x', 0) != 0 or tile.get('y', 0) != 0
                or (tile.get('width'), tile.get('height')) != expected_size
                or tile.get('rotation', 0) != 0 or texture.get('anchorX') != 0 or texture.get('anchorY') != 0
                or texture.get('scaleX', 1) != 1 or texture.get('scaleY', 1) != 1):
            raise ReleaseError('Overhead artwork needs verified full-canvas top-left registration')
    width, height = expected_size
    for wall in scene.get("walls", []):
        c = wall.get("c", [])
        if (len(c) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in c)
                or any(not 0 <= v <= width for v in c[::2]) or any(not 0 <= v <= height for v in c[1::2])):
            raise ReleaseError("Invalid wall coordinates")
        wall["c"] = [round(v) for v in c]
        if wall["c"][:2] == wall["c"][2:]:
            raise ReleaseError("A wall collapses after integer pixel conversion")
    grid["alpha"] = 0  # No baked grid; snapping and measurement remain enabled.
    scene["thumb"] = None
    def strip_internal(value):
        if isinstance(value, dict):
            if isinstance(value.get("flags"), dict):
                value["flags"].pop(NAMESPACE, None)
            for child in value.values(): strip_internal(child)
        elif isinstance(value, list):
            for child in value: strip_internal(child)
    strip_internal(scene)
    return scene, png


def instructions(cfg, size, kind, counts):
    ppi = cfg["pixels_per_square"]
    text = f"""{cfg['title']}
{size[0]} x {size[1]} squares | 5 feet per square | {ppi} pixels per square
{size[0] * ppi} x {size[1] * ppi} pixels per floor

CHOOSE YOUR DOWNLOAD
Gridded: PNG artwork with visible grid lines. No VTT walls or lights.
Gridless: PNG artwork without grid lines. Recommended for your own VTT setup.
Foundry: corrected Foundry VTT 14 scene JSON files with embedded gridless images.
You do not need Dungeondraft, MCP Bridge or our build scripts to use these downloads.

"""
    if kind != "foundry":
        return text + f"""IMAGE / VTT SETUP
1. Extract this ZIP and upload the PNG for your chosen floor to your VTT.
2. Use the original image dimensions. Set a square grid to {ppi} pixels and 5 feet.
3. Keep image offset at 0,0 and verify alignment against two distant landmarks.
4. For the gridded PNG, hide the VTT's visible grid overlay to avoid double lines;
   retain its square grid for snapping and measurement. For gridless artwork,
   show or hide the overlay as you prefer.
PNG files contain no working doors, walls, lights, fog or movement automation.
Use the separate Foundry download if you want the prepared scenes.
Each floor uses the same image size and origin. Printing at one inch per square
requires setting physical print scale; PNG resolution alone does not set it.
"""
    floor_list = "\n".join(f"- {cfg['slug']}-{f['name']}.json" for f in cfg["floors"])
    return text + f"""FOUNDRY VTT 14 INSTALLATION (GM)
1. Extract this ZIP. Create and save a new empty Scene in your Foundry world.
2. Right-click its entry in the Scenes sidebar, then choose Import Data.
3. Select the JSON for that floor and click Import. Import overwrites that scene,
   so do not select an existing campaign scene you need to preserve.
4. Choose View Scene. The embedded background is included; no separate image
   upload, Universal Battlemap Importer, script macro or content module is needed.
   The importing GM needs permission to upload files for image persistence.
5. Repeat with a separate empty Scene for each additional floor:
{floor_list}
6. Optionally right-click the scene entry and Regenerate Thumbnail Image.

AT THE TABLE
The scene includes {counts['walls']} wall segments, {counts['doors']} ordinary doors,
{counts['secrets']} secret doors and {counts['lights']} lights across its floors.
Keep the imported image scale, dimensions, origin and grid unchanged.
The grid overlay starts hidden, but square snapping and measurement remain active.
Place a token with vision and the correct player ownership; test as that player.
Check door states, secret entrances, fog of war and light boundaries before play.
Prepared regional lighting separates outdoor ambiance from enclosed spaces.
Where included, daytime emitters provide bright light and the outdoor baseline
remains dim at night; enclosed rooms/caves use their own darkness regions and
local fixtures. Check regional coverage and day/night activation before play.
The GM adjudicates difficult terrain and cover; ordinary loose props have no
automatic movement penalty. Stone secret-door artwork does not animate on opening.
For separate-floor scenes, move/copy tokens between the matching stair landings;
automatic stairs, actors, encounters and teleport modules are not included.

COMPATIBILITY
Prepared for Foundry VTT 14. File checks do not establish a successful runtime
import; test the scene in your world before your session. Earlier Foundry versions
and other VTTs should use the gridless image and their own wall/light setup.
This is a scene download, not an installable Foundry module or full game world.
Import guide: https://foundryvtt.com/article/scenes/
"""


def handshake(editor):
    hello = editor.ping()
    status = editor.get_status()
    caps = editor.get_capabilities()
    if hello.get("protocol") != 23 or caps.get("protocol") != 23 or not status.get("map_open"):
        raise ReleaseError("Build requires bridge protocol 23 and an open map")
    info = editor.get_map_info()
    if any(info.get(k) for k in ("saving", "loading", "exporting", "batch_active")):
        raise ReleaseError("Editor is busy; finish the existing operation first")
    return info


def write_zip(path, files):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name, data in files.items():
            z.writestr(name, data)
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None or set(z.namelist()) != set(files):
            raise ReleaseError("ZIP validation failed")


def build_release(config_path, editor=None):
    config = Path(config_path).resolve()
    if config.is_dir():
        config /= 'map-release.json'
    if 'artwork' in read_json(config):
        from .release_prepared import build_prepared_release
        return build_prepared_release(config)
    root, cfg = load_config(config_path)
    native = inside(root, cfg["native_map"])
    world = read_native(native)["world"]
    size = (world["width"], world["height"])
    expected = tuple(v * cfg["pixels_per_square"] for v in size)
    if max(expected) > 8192 or math.prod(expected) > 16_000_000:
        raise ReleaseError("Requested resolution exceeds native export limits")
    if editor is None:
        from . import server as editor
    info = handshake(editor)
    if Path(info["path"]).resolve() != native:
        editor.open_map(str(native))  # Existing lifecycle preserves the named current map.
        info = handshake(editor)
    if Path(info["path"]).resolve() != native:
        raise ReleaseError("The configured canonical map is not loaded")
    levels = editor.list_levels()["levels"]
    original = next(l["label"] for l in levels if l["index"] == editor.get_status()["level_index"])
    try:
        if info.get("dirty"):
            editor.save_map()
        if cfg.get("foundry_exporter"):
            print("Refreshing corrected Foundry scenes...", flush=True)
            subprocess.run([sys.executable, "-B", str(inside(root, cfg["foundry_exporter"])), "--capture"],
                           cwd=root, check=True, timeout=300)
        meta = read_json(root / "foundry/export.json")
        native_hash = digest(native.read_bytes())
        if meta.get("native_sha256") != native_hash:
            raise ReleaseError("Foundry export is stale or missing its native SHA-256; refresh the corrected exporter")
        levels = editor.list_levels()["levels"]
        labels = [l["label"] for l in levels]
        if len(set(labels)) != len(labels):
            raise ReleaseError("Native floor labels must be unique")
        if set(labels) != {f["native_label"] for f in cfg["floors"]}:
            raise ReleaseError("Release floors must exactly cover the native map's labeled floors")
        output = inside(root, "release")
        output.mkdir(exist_ok=True)
        counts = dict(walls=0, doors=0, secrets=0, lights=0)
        files = {k: {} for k in ("gridded", "gridless", "foundry")}
        source_hashes = {}
        with tempfile.TemporaryDirectory(prefix=".release-", dir=root) as temporary:
            stage = Path(temporary)
            for floor in cfg["floors"]:
                source_path = inside(root, floor["scene"])
                source_data = source_path.read_bytes()
                entries = list(meta.get("floors", {}).values()) or [meta]
                if not any(e.get("scene_sha256") == digest(source_data) for e in entries):
                    raise ReleaseError(f"Scene hash does not match export metadata: {floor['scene']}")
                scene, gridless = public_scene(json.loads(source_data), expected, cfg["pixels_per_square"])
                current = next(l for l in editor.list_levels()["levels"] if l["label"] == floor["native_label"])
                editor.set_level(index=current["index"])
                grid_path = stage / "gridded.png"
                previous_path = editor._EXPORT_PATH
                try:
                    editor._EXPORT_PATH = str(grid_path)
                    print(f"Exporting gridded floor: {floor['name']}", flush=True)
                    editor.export_map(ppi=cfg["pixels_per_square"], grid=True, lighting=False)
                finally:
                    editor._EXPORT_PATH = previous_path
                gridded = grid_path.read_bytes()
                if png_size(gridded) != expected or gridded == gridless:
                    raise ReleaseError("Native grid export is missing, unchanged or misregistered")
                stem = f"{cfg['slug']}-{floor['name']}"
                files["gridded"][stem + ".png"] = gridded
                files["gridless"][stem + ".png"] = gridless
                files["foundry"][stem + ".json"] = json.dumps(scene, ensure_ascii=False, indent=2).encode("utf8")
                source_hashes[floor["scene"]] = digest(source_data)
                counts["walls"] += len(scene.get("walls", []))
                counts["doors"] += sum(w.get("door") == 1 for w in scene.get("walls", []))
                counts["secrets"] += sum(w.get("door") == 2 for w in scene.get("walls", []))
                counts["lights"] += len(scene.get("lights", []))
            if digest(native.read_bytes()) != native_hash or editor.get_map_info().get("dirty"):
                raise ReleaseError("Map changed during the build; finish edits and rebuild")
            for name, expected_hash in source_hashes.items():
                if digest(inside(root, name).read_bytes()) != expected_hash:
                    raise ReleaseError("A Foundry scene changed during packaging")
            artifacts = {}
            for kind, content in files.items():
                content["READ-ME.txt"] = instructions(cfg, size, kind, counts).encode("utf8")
                name = f"{cfg['slug']}-{kind}.zip"
                write_zip(stage / name, content)
                artifacts[name] = digest((stage / name).read_bytes())
            floor_word = "floor" if len(cfg["floors"]) == 1 else "floors"
            secret_note = f" Includes {counts['secrets']} secret doors." if counts["secrets"] else ""
            release_notes = f"""{cfg['title']} — Battlemap Pack

A {size[0]} x {size[1]} square battlemap, with {len(cfg['floors'])} playable {floor_word}.
Scale: 5 feet per square; {cfg['pixels_per_square']} pixels per square.

Choose your download:
- {cfg['slug']}-gridded.zip — PNG artwork with visible square grids.
- {cfg['slug']}-gridless.zip — clean PNG artwork for your own VTT setup.
- {cfg['slug']}-foundry.zip — Foundry VTT 14 scenes with embedded images,
  walls, doors and lighting.{secret_note}

All downloads include setup instructions. You do not need Dungeondraft.
For Foundry, extract the ZIP, create/save an empty Scene, right-click its entry
in Scenes, choose Import Data and select the floor's JSON. Repeat per floor.
No importer module is required. Use the gridless PNGs for other VTTs or earlier
Foundry versions; those images do not include working walls or lights.

The Foundry files have passed file consistency checks; runtime import and player
vision still need a check in your world before play. Difficult terrain and
cover are adjudicated by the GM; automatic stairs and actors are not included.
"""
            (stage / "RELEASE-NOTES.txt").write_text(release_notes, encoding="utf8")
            manifest = {"title": cfg["title"], "native_sha256": native_hash,
                        "source_scene_sha256": source_hashes, "artifacts": artifacts,
                        "counts": counts, "runtime_verified": False}
            (stage / "build.json").write_text(json.dumps(manifest, indent=2), encoding="utf8")
            # Keep inspectable images beside the ZIPs; only explicit ZIP members are shipped.
            for kind in ("gridded", "gridless"):
                image_output = inside(root, f"release/{kind}")
                image_output.mkdir(exist_ok=True)
                for name, data in files[kind].items():
                    (stage / name).write_bytes(data)
                    os.replace(stage / name, image_output / name)
            for name in [*artifacts, "RELEASE-NOTES.txt", "build.json"]:
                os.replace(stage / name, output / name)
    finally:
        try:
            state = editor.get_map_info()
            if not any(state.get(k) for k in ("saving", "loading", "exporting", "batch_active")):
                current = next((l for l in editor.list_levels()["levels"] if l["label"] == original), None)
                if current:
                    editor.set_level(index=current["index"])
        except BridgeError as exc:
            print(f"Could not restore the editor floor: {exc}", file=sys.stderr)
    print(f"Release ready: {output}", flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("encounter", type=Path, help="Encounter directory or its map-release.json")
    args = parser.parse_args()
    try:
        build_release(args.encounter)
    except (ReleaseError, BridgeError, OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Release build failed: {exc}\n")


if __name__ == "__main__":
    main()
