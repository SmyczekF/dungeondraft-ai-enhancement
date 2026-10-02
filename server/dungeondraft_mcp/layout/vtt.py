"""Native Universal VTT export and an explicit Foundry 14 file adapter."""

import base64
import hashlib
import json
import math
import re
import struct
import time
from pathlib import Path

from shapely.geometry import LineString, Point, box, shape
from shapely.ops import unary_union

from ..bridge_client import BridgeError
from .project import write_json

NAMESPACE = "dungeondraft-mcp"
DISTANCE = 5


def image_path(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*/[A-Za-z0-9_-]+\.png", value
    ):
        raise BridgeError(
            "foundry_image_path must be a relative PNG path, e.g. maps/ambush/battlemap.png"
        )
    return value


def number(value, label):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise BridgeError("invalid native VTT number: " + label)
    return value


def coordinate(value):
    if not isinstance(value, dict) or not {"x", "y"}.issubset(value):
        raise BridgeError("invalid native VTT coordinate")
    return [number(value[k], k) for k in ("x", "y")]


def decode_native(native, spec, ppi):
    if not isinstance(native, dict):
        raise BridgeError("native VTT must be a JSON object")
    resolution = native.get("resolution", {})
    if (
        native.get("format") != 0.3
        or coordinate(resolution.get("map_origin")) != [0, 0]
        or coordinate(resolution.get("map_size"))
        != [spec["size"]["width"], spec["size"]["height"]]
        or resolution.get("pixels_per_grid") != ppi
        or native.get("environment", {}).get("baked_lighting") is not False
    ):
        raise BridgeError(
            "native VTT format, full-map resolution or unbaked lighting differs from request"
        )
    try:
        png = base64.b64decode(native["image"], validate=True)
        dimensions = struct.unpack(">II", png[16:24])
    except (KeyError, ValueError, TypeError, struct.error) as exc:
        raise BridgeError("native VTT image is not a valid embedded PNG") from exc
    expected = (spec["size"]["width"] * ppi, spec["size"]["height"] * ppi)
    if png[:8] != b"\x89PNG\r\n\x1a\n" or dimensions != expected:
        raise BridgeError("native VTT PNG dimensions differ from specification")
    return png


def foundry_scene(native, plan, manifest, ppi, destination):
    """All native VTT positions/ranges are tiles; scene coordinates are pixels.

    Native LOS describes vision geometry. Mechanical blocking is added separately
    from the planner, never guessed from sprite dimensions.
    """
    destination = image_path(destination)
    spec = plan["spec"]
    width, height = spec["size"]["width"], spec["size"]["height"]
    extent = box(0, 0, width, height)
    walls, lights, warnings = [], [], []

    def ident(kind, index):
        return hashlib.sha256(f"{plan['plan_id']}:{kind}:{index}".encode()).hexdigest()[
            :16
        ]

    def segments(line, source, movement_only=False, door=None):
        # Clip native occluders extending past the image without moving landmarks.
        clipped = line.intersection(extent)
        parts = (
            [clipped]
            if clipped.geom_type == "LineString"
            else list(getattr(clipped, "geoms", []))
        )
        for part in parts:
            if part.geom_type != "LineString":
                continue
            points = list(part.coords)
            for a, b in zip(points, points[1:]):
                if math.dist(a, b) < 1e-8:
                    continue
                wall = {
                    "_id": ident("wall", len(walls)),
                    "c": [round(v * ppi, 6) for v in (*a, *b)],
                    "move": 20,
                    "light": 0 if movement_only else 20,
                    "sight": 0 if movement_only else 20,
                    "sound": 0 if movement_only else 20,
                    "dir": 0,
                    "door": 1 if door is not None else 0,
                    "ds": 0 if door is None or door else 1,
                    "flags": {
                        NAMESPACE: {"source": source, "movement_only": movement_only}
                    },
                }
                walls.append(wall)
                if len(walls) > 5000:
                    raise BridgeError("Foundry export exceeds 5000 wall segments")

    for key in ("line_of_sight", "objects_line_of_sight"):
        lines = native.get(key)
        if not isinstance(lines, list) or len(lines) > 5000:
            raise BridgeError("invalid native VTT LOS list")
        for index, points in enumerate(lines):
            if not isinstance(points, list) or not 2 <= len(points) <= 16000:
                raise BridgeError("invalid native VTT polyline")
            segments(
                LineString([coordinate(p) for p in points]), f"native:{key}:{index}"
            )
    portals = native.get("portals")
    if not isinstance(portals, list) or len(portals) > 1000:
        raise BridgeError("invalid native VTT portal list")
    for index, portal in enumerate(portals):
        bounds = portal.get("bounds", [])
        if len(bounds) != 2 or not isinstance(portal.get("closed"), bool):
            raise BridgeError("invalid native VTT portal")
        segments(
            LineString([coordinate(p) for p in bounds]),
            f"native:portal:{index}",
            door=portal["closed"],
        )
    if portals:
        warnings.append(
            "Native portals are exported as ordinary doors. Universal VTT does not distinguish windows or secret doors; review their types in Foundry."
        )
    crossings = unary_union(
        [
            shape(s["geometry"])
            for s in plan["features"].values()
            if s["type"] == "clear_area" and s["spec"]["purpose"] == "crossing"
        ]
    )
    for fid, semantic in plan["features"].items():
        for item in semantic.get("generated", []):
            radius = item.get("blocking_radius", 0)
            if radius:
                # Eight edges around the declared trunk/obstacle radius.
                boundary = Point(item["position"]).buffer(radius, quad_segs=2).boundary
                segments(boundary, item["semantic_id"], movement_only=True)
        if semantic["type"] == "stream" and semantic["spec"]["depth"] == "deep":
            boundary = shape(semantic["geometry"]).difference(crossings).boundary
            parts = (
                [boundary]
                if boundary.geom_type == "LineString"
                else list(boundary.geoms)
            )
            for part in parts:
                segments(part, fid, movement_only=True)
    raw_lights = native.get("lights")
    if not isinstance(raw_lights, list) or len(raw_lights) > 1000:
        raise BridgeError("invalid native VTT lights")
    for index, light in enumerate(raw_lights):
        position = coordinate(light.get("position"))
        radius = number(light.get("range"), "light range")
        intensity = number(light.get("intensity"), "light intensity")
        color = light.get("color", "")
        if (
            not extent.covers(Point(position))
            or radius < 0
            or intensity < 0
            or not isinstance(color, str)
            or not re.fullmatch(r"[0-9a-fA-F]{8}", color)
            or not isinstance(light.get("shadows"), bool)
        ):
            raise BridgeError("invalid native VTT light properties")
        alpha = min(1, intensity * int(color[:2], 16) / 255)
        lights.append(
            {
                "_id": ident("light", index),
                "x": position[0] * ppi,
                "y": position[1] * ppi,
                "walls": light["shadows"],
                "rotation": 0,
                "config": {
                    "dim": radius * DISTANCE,
                    "bright": radius * DISTANCE / 2,
                    "color": "#" + color[2:],
                    "alpha": alpha,
                    "angle": 360,
                },
                "flags": {NAMESPACE: {"native": light}},
            }
        )
    if lights:
        warnings.append(
            "Light radius/color/shadow state are converted; brightness uses half-radius bright light and clamped alpha. Dungeondraft cookies and energy are not photometrically equivalent to Foundry lights."
        )
    level_id = ident("level", 0)
    encounter = {
        "schema_version": "battlemap_encounter.v1",
        "plan_id": plan["plan_id"],
        "units": "tiles",
        "pixels_per_grid": ppi,
        "distance_per_grid": DISTANCE,
        "grid_units": "ft",
        "spec": spec,
        "features": plan["features"],
        "manifest": manifest,
    }
    scene = {
        "name": spec["theme"],
        "active": False,
        "navigation": True,
        "tokenVision": True,
        "width": width * ppi,
        "height": height * ppi,
        "padding": 0,
        "shiftX": 0,
        "shiftY": 0,
        "grid": {
            "type": 1,
            "size": ppi,
            "distance": DISTANCE,
            "units": "ft",
            "alpha": 0 if spec["output"]["grid"] else 0.2,
        },
        "initialLevel": level_id,
        "levels": [
            {
                "_id": level_id,
                "name": "Ground",
                "elevation": {"bottom": 0, "top": 10},
                "background": {"src": destination},
            }
        ],
        "walls": walls,
        "lights": lights,
        "flags": {
            NAMESPACE: {
                "schema_version": "foundry_export.v1",
                "foundry_generation": 14,
                "encounter": encounter,
                "native_environment": native["environment"],
            }
        },
    }
    warnings.append(
        "Cover, difficult terrain and encounter zones remain semantic metadata; no game-system rules, actors or tokens are created. Ambient lighting must be reviewed in Foundry."
    )
    return scene, encounter, warnings


def export_battlemap(planner, plan_id, directory, foundry_image_path, ppi=None):
    destination = image_path(foundry_image_path)
    record = planner.applied_record(plan_id)
    validation = planner.validate(plan_id)
    if not validation["valid"]:
        raise BridgeError(
            "battlemap validation failed; inspect findings before exporting"
        )
    plan, bridge = record["plan"], planner.bridge
    ppi = plan["spec"]["output"]["ppi"] if ppi is None else ppi
    if isinstance(ppi, bool) or not isinstance(ppi, int) or not 20 <= ppi <= 256:
        raise BridgeError("Foundry 14 export ppi must be an integer in 20..256")
    size = plan["spec"]["size"]
    pixels = [size["width"] * ppi, size["height"] * ppi]
    if max(pixels) > 8192 or pixels[0] * pixels[1] > 16777216:
        raise BridgeError(
            "export exceeds 16 megapixels or 8192 pixels per side; reduce ppi"
        )
    if bridge.request("get_status")["level_count"] != 1:
        raise BridgeError("Foundry file export supports single-level native maps only")
    root = Path(directory)
    if not root.is_absolute() or root.exists() or not root.parent.is_dir():
        raise BridgeError(
            "export directory must be a new absolute path in an existing parent"
        )
    root.mkdir()
    context = planner.context()
    camera = bridge.request("get_camera")
    state = bridge.request("get_export_status")
    native_path = root / "battlemap.dd2vtt"
    bridge.request(
        "export_map",
        path=str(native_path),
        ppi=ppi,
        format="universalvtt",
        grid=plan["spec"]["output"]["grid"],
        lighting=False,
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status = bridge.request("get_export_status")
        if (
            native_path.exists()
            and not status["exporting"]
            and not status["managed_export"]
        ):
            break
        time.sleep(0.1)
    else:
        raise BridgeError(
            "native VTT export did not complete; incomplete directory retained"
        )
    if any(status[k] != state[k] for k in ("grid", "lighting")):
        raise BridgeError("export did not restore grid/lighting state")
    restored = bridge.request("get_camera")
    if any(restored.get(k) != camera.get(k) for k in ("position", "zoom")):
        raise BridgeError("export did not restore camera")
    if native_path.stat().st_size > 128 * 1024 * 1024:
        raise BridgeError("native VTT file exceeds 128 MiB")
    try:
        native = json.loads(native_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BridgeError("native VTT file is incomplete or invalid") from exc
    png = decode_native(native, plan["spec"], ppi)
    scene, encounter, warnings = foundry_scene(
        native, plan, record["manifest"], ppi, destination
    )
    if planner.context()["fingerprint"] != context["fingerprint"]:
        raise BridgeError("map changed during export; no completion marker written")
    (root / "battlemap.png").write_bytes(png)
    write_json(root / "foundry-scene.json", scene)
    write_json(root / "encounter.json", encounter)
    write_json(root / "validation.json", validation)
    # Explicit user-executed import; no server, credentials or private Foundry API.
    macro = """// Upload battlemap.png to the background path first. Run as GM in Foundry 14.
if (!game.user.isGM || game.release.generation !== 14) throw new Error("Requires a GM in Foundry 14");
const data = %s;
const candidate = new CONFIG.Scene.documentClass(data, {strict: true});
candidate.validate({strict: true});
if (candidate.invalid) throw new Error("Scene schema validation failed");
const response = await fetch(data.levels[0].background.src, {method: "HEAD"});
if (!response.ok) throw new Error("Upload the battlemap PNG to the configured background path first");
const scene = await Scene.create(candidate.toObject(), {keepEmbeddedIds: true});
await scene.view();
ui.notifications.info("Dungeondraft scene imported. Review grid, doors and lighting.");
""" % json.dumps(scene, ensure_ascii=False, allow_nan=False)
    (root / "import-foundry.js").write_text(macro, encoding="utf-8")
    names = (
        "battlemap.dd2vtt",
        "battlemap.png",
        "foundry-scene.json",
        "encounter.json",
        "validation.json",
        "import-foundry.js",
    )
    result = {
        "schema_version": "battlemap_export.v1",
        "exported": True,
        "plan_id": plan_id,
        "directory": str(root),
        "foundry_generation": 14,
        "foundry_image_path": destination,
        "ppi": ppi,
        "pixels": pixels,
        "wall_count": len(scene["walls"]),
        "light_count": len(scene["lights"]),
        "door_count": sum(w["door"] == 1 for w in scene["walls"]),
        "warnings": warnings,
        "camera_restored": True,
        "grid_restored": True,
        "lighting_restored": True,
        "foundry_import": "requires target-runtime review; files exported, no scene imported",
        "files": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in names
        },
    }
    write_json(root / "export.json", result)
    return result
