"""Pure deterministic geometry/layout, independent of the editor and MCP."""

import hashlib
import json
import math
import random
from collections import Counter
from shapely.geometry import (
    Point,
    Polygon,
    LineString,
    box,
    mapping,
    shape as geometry_shape,
)
from shapely import __version__ as shapely_version, geos_version_string
from shapely.ops import unary_union
from .spec import (
    MapSpec,
    Road,
    Stream,
    TerrainRegion,
    Forest,
    Prop,
    ClearArea,
    Zone,
    Building,
)

GENERATOR_VERSION = "1.0.0"
WOXELS_PER_TILE = 256


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


class LayoutError(ValueError):
    def __init__(self, feature_id, message):
        self.feature_id = feature_id
        super().__init__(message)


def smooth(points):
    # One Chaikin subdivision, preserving endpoints and staying in the hull.
    result = [points[0]]
    for a, b in zip(points, points[1:]):
        result.extend(
            [
                [0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]],
                [0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]],
            ]
        )
    return result + [points[-1]]


def polygon(raw, fid):
    shape = Polygon(raw)
    if not shape.is_valid or shape.area < 0.01:
        raise LayoutError(fid, "polygon must be simple with positive area")
    return shape


def rings(shape, fid):
    parts = (
        [shape] if shape.geom_type == "Polygon" else list(getattr(shape, "geoms", []))
    )
    result = []
    for part in parts:
        if part.is_empty or part.area < 0.001:
            continue
        if part.geom_type != "Polygon" or part.interiors:
            raise LayoutError(
                fid, "render region requires simple polygons without holes"
            )
        ring = list(part.simplify(0.02, preserve_topology=True).exterior.coords)[:-1]
        if len(ring) > 32:
            raise LayoutError(
                fid, "render polygon exceeds 32 vertices; reduce path detail"
            )
        result.append(
            [
                [round(x * WOXELS_PER_TILE, 4), round(y * WOXELS_PER_TILE, 4)]
                for x, y in ring
            ]
        )
    if not result:
        raise LayoutError(fid, "region is empty after clipping")
    return result


class Assets:
    def __init__(self, catalog, overrides, warnings):
        self.catalog = catalog
        self.overrides = overrides
        self.warnings = warnings
        self.used = {}

    def choose(self, category, query, fid, fallback=None):
        named = self.overrides.get(query, query)
        rows = sorted(self.catalog.get(category, []), key=lambda row: row["path"])
        if named.startswith(("res://", "user://")):
            matches = [r for r in rows if r["path"] == named]
        else:
            matches = [r for r in rows if named.lower() in r["path"].lower()]
            # Prefer an exact basename/token to "dry_grass" for "grass".
            matches.sort(
                key=lambda r: (
                    r["path"].split("/")[-1].removesuffix(".png")
                    not in (named, "terrain_" + named),
                    r["path"],
                )
            )
        if not matches and fallback and named == query:
            self.warnings.append(
                {
                    "feature_id": fid,
                    "code": "asset_fallback",
                    "message": f"{query!r} unavailable; using {fallback!r}",
                }
            )
            return self.choose(category, fallback, fid)
        if not matches:
            raise LayoutError(fid, f"no loaded {category} asset for {named!r}")
        row = matches[0]
        self.used[row["path"]] = row
        return row

    def radius(self, row, scale, fid):
        size = row.get("nominal_footprint_woxels")
        if not size:
            raise LayoutError(
                fid, "object metadata has no footprint; cannot validate spacing"
            )
        return math.hypot(*size) * scale / (2 * WOXELS_PER_TILE)


def poisson(
    region, target, spacing, choices, scale, rng, assets, fid, occupied, exclusions
):
    """Bounded Bridson active-list sampling; reseed disconnected components."""
    placed = []
    active = []
    bounds = region.bounds
    attempts = 0
    max_attempts = max(2000, target * 150)
    choice = None
    radius = 0
    while len(placed) < target and attempts < max_attempts:
        if choice is None:
            choice = rng.choice(choices)
            radius = assets.radius(choice, scale, fid)
        origin = placed[rng.choice(active)]["position"] if active else None
        accepted = False
        for _ in range(30 if origin else 200):
            attempts += 1
            if attempts > max_attempts:
                break
            if origin:
                angle = rng.uniform(0, math.tau)
                distance = rng.uniform(
                    max(spacing, 2 * radius + 0.05), max(spacing, 2 * radius + 0.05) * 2
                )
                pos = [
                    origin[0] + math.cos(angle) * distance,
                    origin[1] + math.sin(angle) * distance,
                ]
            else:
                pos = [
                    rng.uniform(bounds[0], bounds[2]),
                    rng.uniform(bounds[1], bounds[3]),
                ]
            if any(
                math.dist(pos, other["position"])
                < max(spacing, radius + other["visual_radius"] + 0.05)
                for other in occupied
            ):
                continue
            footprint = Point(pos).buffer(radius, quad_segs=8)
            if not region.covers(footprint) or footprint.intersects(exclusions):
                continue
            item = {
                "position": [round(v, 6) for v in pos],
                "visual_radius": radius,
                "asset": choice["path"],
                "scale": scale,
                "rotation": round(rng.uniform(0, 360), 4),
            }
            placed.append(item)
            occupied.append(item)
            active.append(len(placed) - 1)
            choice = None
            accepted = True
            break
        if not accepted and origin:
            # Retire the seed; random reseeding reaches separate forest areas.
            active = [i for i in active if placed[i]["position"] != origin]
        elif not accepted and not origin:
            break
    return placed, attempts


def generate(spec: MapSpec, catalog: dict, catalog_version: str, manual_bounds=()):
    warnings = []
    operations = []
    semantics = {}
    slots = {}
    features = {}
    assets = Assets(catalog, spec.asset_overrides, warnings)
    bounds = box(0, 0, spec.size.width, spec.size.height)
    inner = bounds.buffer(-spec.margin)
    clear = []
    road_clear = []
    water = []
    building_shapes = []
    obstacles = []
    occupied = []
    manual = [box(*r) for r in manual_bounds]

    def emit(fid, op):
        features.setdefault(fid, []).append(len(operations))
        operations.append(op)

    def terrain(fid, material, shape=None):
        fallback = "swamp" if material == "mud" else None
        row = assets.choose("Terrain", material, fid, fallback)
        if row["path"] not in slots:
            if len(slots) >= 4:
                raise LayoutError(
                    fid,
                    "plan needs more than four terrain materials; reduce the palette",
                )
            slots[row["path"]] = len(slots)
        op = {"slot": slots[row["path"]], "asset": row["path"]}
        if shape is None:
            emit(fid, {"cmd": "fill_terrain", **op})
        else:
            for ring in rings(shape, fid):
                emit(fid, {"cmd": "fill_region", "points": ring, **op})

    # All protected spaces are collected before any prop generation.
    for f in spec.features:
        semantics[f.id] = {
            "type": f.type,
            "gameplay": f.gameplay.model_dump(mode="json"),
            "spec": f.model_dump(mode="json"),
            "generated": [],
        }
        if isinstance(f, (Road, Stream)):
            if any(not bounds.covers(Point(p)) for p in f.points) or any(
                a == b for a, b in zip(f.points, f.points[1:])
            ):
                raise LayoutError(
                    f.id,
                    "path points must be inside the map and consecutive points must differ",
                )
            line = LineString(smooth(f.points) if f.smooth else f.points)
            if not line.is_simple:
                raise LayoutError(f.id, "path must not intersect itself")
            shape = line.buffer(f.width / 2, quad_segs=2).intersection(bounds)
            semantics[f.id]["geometry"] = mapping(shape)
            if isinstance(f, Road):
                road_clear.append(shape.buffer(f.clearance))
            else:
                water.append((f, shape))
        elif isinstance(f, (Forest, TerrainRegion, ClearArea, Building)):
            shape = polygon(f.region, f.id).intersection(
                inner if isinstance(f, Forest) else bounds
            )
            if shape.is_empty:
                raise LayoutError(f.id, "region is outside the map")
            semantics[f.id]["geometry"] = mapping(shape)
            if isinstance(f, ClearArea):
                clear.append(shape)
            if isinstance(f, Building):
                building_shapes.append(shape)
        elif isinstance(f, Zone):
            shape = Point(f.position).buffer(f.radius)
            if not bounds.covers(shape):
                raise LayoutError(f.id, "encounter zone extends beyond map bounds")
            clear.append(shape)
            semantics[f.id]["geometry"] = mapping(shape)

    protected = unary_union(
        clear + road_clear + building_shapes + [g for _, g in water] + manual
    )
    crossings = unary_union(
        [
            polygon(f.region, f.id)
            for f in spec.features
            if isinstance(f, ClearArea) and f.purpose == "crossing"
        ]
    )
    if spec.base_material is not None:
        terrain("base", spec.base_material)
    for f in spec.features:
        geometry = semantics[f.id].get("geometry")
        if isinstance(f, Road):
            terrain(f.id, f.material, geometry_shape(geometry))
        elif isinstance(f, TerrainRegion):
            terrain(f.id, f.material, polygon(f.region, f.id).intersection(bounds))
        elif isinstance(f, Building):
            shape = polygon(f.region, f.id)
            if not inner.covers(shape):
                raise LayoutError(f.id, "building must fit inside map margin")
            row = assets.choose("Walls", f.wall_asset, f.id, "stone")
            gaps = []
            for door in f.doors:
                if shape.boundary.distance(Point(door.position)) > 1e-5:
                    raise LayoutError(f.id, "door center must lie on building boundary")
                gaps.append(Point(door.position).buffer(door.width / 2))
                clear.append(Point(door.position).buffer(door.width / 2 + 0.75))
            wall = shape.boundary.difference(unary_union(gaps))
            walls = [wall] if wall.geom_type == "LineString" else list(wall.geoms)
            for path in walls:
                points = list(path.coords)
                closed = points[0] == points[-1]
                if closed:
                    points = points[:-1]
                if len(points) > 32:
                    raise LayoutError(f.id, "wall exceeds native point limit")
                emit(
                    f.id,
                    {
                        "cmd": "draw_wall",
                        "asset": row["path"],
                        "points": [
                            [x * WOXELS_PER_TILE, y * WOXELS_PER_TILE]
                            for x, y in points
                        ],
                        "loop": closed,
                    },
                )
            terrain(f.id, f.floor_material, shape)
            obstacles.append(wall.buffer(0.1))

    # Door clearance was added during building geometry generation.
    protected = unary_union([protected] + clear)
    for f, shape in water:
        if f.depth == "deep":
            obstacles.append(shape.difference(crossings))
            if (
                shape.intersection(unary_union(road_clear)).difference(crossings).area
                > 0.01
            ):
                raise LayoutError(
                    f.id,
                    "deep stream intersects a road without a declared crossing area",
                )
        for ring in rings(shape.difference(crossings), f.id):
            emit(f.id, {"cmd": "draw_water", "points": ring})
    prop_protected = unary_union(clear + road_clear + [g for _, g in water] + manual)
    for f in spec.features:
        if not isinstance(f, Prop):
            continue
        row = assets.choose("Objects", f.asset, f.id, "boulder")
        radius = max(f.radius, assets.radius(row, f.scale, f.id))
        shape = Point(f.position).buffer(radius)
        if not inner.covers(shape):
            raise LayoutError(f.id, "prop footprint extends beyond map margin")
        if shape.intersects(prop_protected):
            raise LayoutError(
                f.id,
                "prop overlaps road, water, encounter clearance, or manual content",
            )
        if any(shape.intersects(g) for g in obstacles):
            raise LayoutError(f.id, "prop overlaps another blocking feature")
        if any(
            math.dist(f.position, p["position"]) < radius + p["visual_radius"] + 0.05
            for p in occupied
        ):
            raise LayoutError(f.id, "prop footprints overlap")
        item = {
            "semantic_id": f.id,
            "position": f.position,
            "visual_radius": radius,
            "asset": row["path"],
            "scale": f.scale,
            "rotation": f.rotation,
            "blocking_radius": f.radius if f.gameplay.blocks_movement else 0,
        }
        occupied.append(item)
        semantics[f.id]["generated"].append(item)
        emit(
            f.id,
            {
                "cmd": "place_object",
                "asset": row["path"],
                "x": f.position[0] * WOXELS_PER_TILE,
                "y": f.position[1] * WOXELS_PER_TILE,
                "scale": f.scale,
                "rotation": f.rotation,
            },
        )
        if f.gameplay.blocks_movement:
            obstacles.append(Point(f.position).buffer(f.radius))
    for f in spec.features:
        if not isinstance(f, Forest):
            continue
        choices = [
            assets.choose("Objects", query, f.id, "oak") for query in f.tree_types
        ]
        region = polygon(f.region, f.id).intersection(inner)
        rng = random.Random(int(digest([spec.seed, f.id, GENERATOR_VERSION])[:16], 16))
        placed, attempts = poisson(
            region,
            f.count,
            f.min_spacing,
            choices,
            f.scale,
            rng,
            assets,
            f.id,
            occupied,
            protected,
        )
        if len(placed) != f.count:
            raise LayoutError(
                f.id,
                f"forest fits {len(placed)}/{f.count} trees after {attempts} bounded attempts; reduce count/scale or enlarge its region",
            )
        for i, item in enumerate(placed):
            item["semantic_id"] = f"{f.id}/{i:04d}"
            item["blocking_radius"] = 0.2
            semantics[f.id]["generated"].append(item)
            emit(
                f.id,
                {
                    "cmd": "place_object",
                    "asset": item["asset"],
                    "x": item["position"][0] * WOXELS_PER_TILE,
                    "y": item["position"][1] * WOXELS_PER_TILE,
                    "scale": item["scale"],
                    "rotation": item["rotation"],
                },
            )
            obstacles.append(Point(item["position"]).buffer(0.2))
    free = bounds.buffer(-spec.encounter.agent_radius).difference(
        unary_union(obstacles + manual).buffer(spec.encounter.agent_radius)
    )
    components = (
        [free] if free.geom_type == "Polygon" else list(getattr(free, "geoms", []))
    )
    routes = []
    indexed = {f.id: f for f in spec.features}
    for start, end in spec.encounter.required_routes:
        a, b = Point(indexed[start].position), Point(indexed[end].position)
        connected = any(
            component.covers(a) and component.covers(b) for component in components
        )
        routes.append({"from": start, "to": end, "connected": connected})
        if not connected:
            raise LayoutError(
                start,
                f"route to {end!r} is blocked for agent radius {spec.encounter.agent_radius}",
            )
    if len(operations) > 500:
        raise LayoutError("plan", "plan exceeds 500 native operations")
    if sum(op["cmd"] in ("fill_terrain", "fill_region") for op in operations) > 16:
        raise LayoutError("plan", "plan exceeds 16 terrain operations")
    if sum(op["cmd"] == "draw_water" for op in operations) > 16:
        raise LayoutError("plan", "plan exceeds 16 water operations")
    plan = {
        "schema_version": "battlemap_plan.v1",
        "generator_version": GENERATOR_VERSION,
        "geometry_runtime": {"shapely": shapely_version, "geos": geos_version_string},
        "spec": spec.model_dump(mode="json"),
        "catalog_version": catalog_version,
        "resolved_assets": assets.used,
        "operations": operations,
        "operation_features": [
            fid
            for i in range(len(operations))
            for fid, indices in features.items()
            if i in indices
        ],
        "features": semantics,
        "warnings": warnings,
        "validation": {
            "valid": True,
            "routes": routes,
            "checks": [
                "geometry",
                "bounds",
                "asset availability",
                "nominal visual spacing",
                "road/door/encounter clearances",
                "route connectivity",
            ],
        },
        "counts": dict(Counter(op["cmd"] for op in operations)),
    }
    plan["plan_id"] = digest(plan)
    return plan
