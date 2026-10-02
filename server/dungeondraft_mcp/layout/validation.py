"""Structural validation against live native descriptors, independent of pixels."""

import math
from shapely.geometry import Point, box, shape, LineString
from shapely.ops import unary_union


def owned_elements(manifest):
    return [
        (fid, e)
        for fid, feature in manifest["features"].items()
        for e in feature["elements"]
    ]


def validate(plan, manifest, context, surface=None):
    live = {e["id"]: e for e in context["content"]["elements"]}
    findings, owned, actual, obstacles = [], set(), [], []
    spec = plan["spec"]
    inner = box(0, 0, spec["size"]["width"], spec["size"]["height"]).buffer(
        -spec["margin"]
    )

    def finding(code, fid, message, position=None):
        findings.append(
            {
                "severity": "error",
                "code": code,
                "feature_id": fid,
                "coordinates_tiles": position,
                "message": message,
            }
        )

    if context["content"]["size"] != [
        spec["size"]["width"] * 256,
        spec["size"]["height"] * 256,
    ]:
        finding("map_size", "size", "native dimensions differ from specification")
    if context["content"]["level_id"] != manifest["level_id"]:
        finding("level", "map", "current native level differs from manifest")
    for fid, element in owned_elements(manifest):
        ident, op = element["id"], element["operation"]
        if ident in owned:
            finding(
                "duplicate_identity",
                fid,
                "native ID is assigned to more than one semantic element",
            )
        owned.add(ident)
        descriptor = live.get(ident)
        if descriptor is None:
            finding("missing_element", fid, f"owned native element {ident} is missing")
            continue
        position = [v / 256 for v in descriptor.get("position", [0, 0])]
        if op["cmd"] == "place_object":
            if descriptor.get("kind") != "object":
                finding(
                    "element_kind", fid, "owned ID is no longer an object", position
                )
            if math.dist(descriptor.get("position", [0, 0]), [op["x"], op["y"]]) > 0.05:
                finding(
                    "position_changed",
                    fid,
                    "owned object was moved outside the plan",
                    position,
                )
            for k in ("scale", "rotation"):
                tolerance = 0.001 if k == "scale" else 0.01
                if (
                    abs(descriptor.get(k, 0) - op.get(k, 1 if k == "scale" else 0))
                    > tolerance
                ):
                    finding(
                        k + "_changed",
                        fid,
                        "owned transform differs from the plan",
                        position,
                    )
            generated = next(
                (
                    g
                    for g in plan["features"][fid].get("generated", [])
                    if g["semantic_id"] == element["semantic_id"]
                ),
                None,
            )
            if generated:
                radius = (
                    generated["visual_radius"]
                    * descriptor.get("scale", 1)
                    / generated["scale"]
                )
                footprint = Point(position).buffer(radius)
                if not inner.covers(footprint):
                    finding(
                        "bounds", fid, "visual footprint crosses map margin", position
                    )
                actual.append((fid, position, radius, footprint))
                if generated.get("blocking_radius"):
                    obstacles.append(
                        Point(position).buffer(generated["blocking_radius"])
                    )
        else:
            expected_points = op.get("points")
            points = descriptor.get("points")
            if expected_points and (
                not points
                or LineString(points).hausdorff_distance(LineString(expected_points))
                > 0.1
            ):
                finding(
                    "geometry_changed",
                    fid,
                    "owned geometry differs from plan",
                    position,
                )
        if op.get("asset") and descriptor.get("asset") != op["asset"]:
            finding(
                "asset_changed",
                fid,
                "owned artwork differs from selected asset",
                position,
            )
    protected = []
    for fid, semantic in plan["features"].items():
        geometry = semantic.get("geometry")
        if not geometry:
            continue
        g = shape(geometry)
        kind = semantic["type"]
        if kind in ("road", "stream", "entry", "spawn", "clear_area"):
            protected.append(
                g.buffer(semantic["spec"].get("clearance", 0)) if kind == "road" else g
            )
        if kind == "stream" and semantic["spec"]["depth"] == "deep":
            crossings = unary_union(
                [
                    shape(s["geometry"])
                    for s in plan["features"].values()
                    if s["type"] == "clear_area" and s["spec"]["purpose"] == "crossing"
                ]
            )
            obstacles.append(g.difference(crossings))
        if kind in ("building", "room"):
            gaps = unary_union(
                [
                    Point(d["position"]).buffer(d["width"] / 2)
                    for d in semantic["spec"]["doors"]
                ]
            )
            obstacles.append(g.boundary.difference(gaps).buffer(0.1))
    reserved = unary_union(protected)
    for index, (fid, position, radius, footprint) in enumerate(actual):
        if footprint.intersects(reserved):
            finding(
                "clearance",
                fid,
                "visual footprint enters a protected road, stream or encounter space",
                position,
            )
        for other_fid, other_position, other_radius, _ in actual[:index]:
            required = radius + other_radius + 0.05
            if fid == other_fid and plan["features"][fid]["type"] == "forest":
                required = max(required, plan["features"][fid]["spec"]["min_spacing"])
            if math.dist(position, other_position) < required - 0.001:
                finding(
                    "spacing",
                    fid,
                    f"insufficient spacing from feature {other_fid}",
                    position,
                )
    manual = []
    for ident, descriptor in live.items():
        if (
            ident not in owned
            and descriptor.get("kind") not in ("light", "text")
            and descriptor.get("bounds")
        ):
            a, b = descriptor["bounds"]
            manual.append(box(a[0] / 256, a[1] / 256, b[0] / 256, b[1] / 256))
    # Unowned content is conservatively treated as blocking; artwork alone cannot
    # identify mechanical intent.
    for fid, position, _, footprint in actual:
        if any(footprint.intersects(g) for g in manual):
            finding(
                "manual_overlap",
                fid,
                "owned footprint intersects manual content",
                position,
            )
    agent = spec["encounter"]["agent_radius"]
    free = (
        box(0, 0, spec["size"]["width"], spec["size"]["height"])
        .buffer(-agent)
        .difference(unary_union(obstacles + manual).buffer(agent))
    )
    components = (
        [free] if free.geom_type == "Polygon" else list(getattr(free, "geoms", []))
    )
    routes = []
    indexed = {f["id"]: f for f in spec["features"]}
    for start, end in spec["encounter"]["required_routes"]:
        a, b = Point(indexed[start]["position"]), Point(indexed[end]["position"])
        connected = any(c.covers(a) and c.covers(b) for c in components)
        routes.append({"from": start, "to": end, "connected": connected})
        if not connected:
            finding(
                "route_blocked",
                start,
                f"route to {end} is disconnected",
                indexed[start]["position"],
            )
    for fid, semantic in plan["features"].items():
        if semantic["type"] in ("forest", "cover", "obstacle", "hazard"):
            expected = len(semantic["generated"])
            found = sum(e["id"] in live for e in manifest["features"][fid]["elements"])
            if found != expected:
                finding(
                    "count", fid, f"expected {expected} owned objects, found {found}"
                )
    if surface and context.get("surface") != surface:
        finding(
            "terrain_changed",
            "map",
            "native terrain was painted or retextured outside the plan",
        )
    return {
        "schema_version": "battlemap_validation.v1",
        "plan_id": plan["plan_id"],
        "valid": not findings,
        "findings": findings,
        "routes": routes,
        "owned_element_count": len(owned),
        "manual_element_count": len(live) - len(owned),
        "checks": [
            "counts",
            "native IDs",
            "assets",
            "transforms",
            "bounds",
            "visual spacing",
            "protected clearances",
            "routes",
            "semantic geometry",
        ],
        "visual_review": {
            "status": "required",
            "checks": ["clipping", "readability", "artwork suitability"],
        },
        "manual_geometry_policy": "unowned element bounds except lights/text are conservative obstacles",
    }
