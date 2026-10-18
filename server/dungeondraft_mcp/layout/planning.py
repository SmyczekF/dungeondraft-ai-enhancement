"""MCP planning adapter: read context, retain plans, submit one native batch."""

import copy
import re
import math
from pydantic import ValidationError
from ..bridge_client import BridgeError
from .spec import MapSpec, Forest, Prop, Road, TerrainRegion, Building
from .layout import generate, digest, LayoutError, WOXELS_PER_TILE

from .validation import is_manual_obstacle

MAX_PLANS = 64
KINDS = ("objects", "walls", "lights", "paths", "portals", "roofs", "patterns", "texts")


def normalize_native(value):
    if isinstance(value, dict):
        return {k: normalize_native(v) for k, v in value.items() if k != "ref"}
    if isinstance(value, list):
        return [normalize_native(v) for v in value]
    return value


def water_geometry(value):
    """Ownership covers polygons/topology; appearance can be styled independently.

    The full native water data still participates in stale-plan detection and
    project persistence. Ignore only known appearance fields and session refs.
    """
    if isinstance(value, dict):
        return {
            k: water_geometry(v) for k, v in value.items()
            if k not in {"ref", "deep_color", "shallow_color", "blend_distance", "disable_border"}
        }
    if isinstance(value, list):
        return [water_geometry(v) for v in value]
    return value


def water_bounds(data):
    result = []

    def visit(node):
        raw = node.get("polygon", "PoolVector2Array( )")
        match = re.fullmatch(r"PoolVector2Array\(\s*([0-9eE+.,\s-]*)\)", raw)
        if not match:
            raise BridgeError("unrecognized native water coordinates")
        values = [float(v.strip()) for v in match[1].split(",") if v.strip()]
        if len(values) % 2 or any(not math.isfinite(v) for v in values):
            raise BridgeError("invalid native water coordinates")
        if values:
            result.append(
                [
                    min(values[::2]) / WOXELS_PER_TILE,
                    min(values[1::2]) / WOXELS_PER_TILE,
                    max(values[::2]) / WOXELS_PER_TILE,
                    max(values[1::2]) / WOXELS_PER_TILE,
                ]
            )
        for child in node.get("children", []):
            visit(child)

    if data.get("tree"):
        visit(data["tree"])
    return result


def water_present(data):
    return bool(data.get("tree", {}).get("children", []))


class Planner:
    def __init__(self, bridge):
        self.bridge = bridge
        self.records = {}

    def context(self):
        ping = self.bridge.request("ping")
        if ping["protocol"] != 23:
            raise BridgeError("planner requires bridge protocol 23")
        status = self.bridge.request("get_status")
        if not status["map_open"]:
            raise BridgeError("load a map before planning")
        info = self.bridge.request("get_map_info")
        if any(info.get(k) for k in ("saving", "loading", "exporting")):
            raise BridgeError(
                "editor is busy saving/loading/exporting; wait before project operations"
            )
        capabilities = self.bridge.request("get_capabilities")
        elements = []
        for kind, count in status["counts"].items():
            if count > 1000:
                raise BridgeError(
                    "planner supports at most 1000 existing elements per kind"
                )
            for offset in range(0, count, 200):
                elements.extend(
                    self.bridge.request(
                        "list_elements", kind=kind, offset=offset, limit=200
                    )["elements"]
                )
        water = self.bridge.request("get_water")["data"]
        surface = self.bridge.request("get_surface_state")
        content = {
            "elements": elements,
            "water": normalize_native(water),
            "surface": surface,
            "level_id": status["level_id"],
            "size": status["map_size_woxels"],
            "path": info["path"],
            "bridge_dirty": info["bridge_dirty"],
            "editor_dirty": info["editor_dirty"],
        }
        return {
            "surface": surface,
            "bridge_instance": ping["bridge_instance"],
            "catalog_version": capabilities["asset_catalog_version"],
            "fingerprint": digest(content),
            "content": content,
            "has_content": bool(elements) or water_present(water),
        }

    def catalog(self, spec):
        queries = set()
        if spec.base_material is not None:
            queries.add(("Terrain", spec.base_material))
        for f in spec.features:
            if isinstance(f, Forest):
                queries.update(("Objects", q) for q in f.tree_types)
                queries.add(("Objects", "oak"))
            if isinstance(f, Prop):
                queries.update([("Objects", f.asset), ("Objects", "boulder")])
            if isinstance(f, (Road, TerrainRegion)):
                queries.add(("Terrain", f.material))
            if isinstance(f, Building):
                queries.update(
                    [
                        ("Walls", f.wall_asset),
                        ("Walls", "stone"),
                        ("Terrain", f.floor_material),
                    ]
                )
        if ("Terrain", "mud") in queries:
            queries.add(("Terrain", "swamp"))
        rows = {}
        for category, query in sorted(queries):
            search = spec.asset_overrides.get(query, query)
            reply = self.bridge.request(
                "list_asset_metadata", category=category, search=search, limit=200
            )
            if reply["matched"] > 200:
                raise BridgeError(
                    f"asset query {query!r} is too broad; use a specific name or path"
                )
            rows.setdefault(category, {})
            for row in reply["assets"]:
                rows[category][row["path"]] = row
        return {k: list(v.values()) for k, v in rows.items()}

    def plan(self, raw, include_operations=False):
        try:
            spec = MapSpec.model_validate(raw)
        except ValidationError as exc:
            return {
                "valid": False,
                "schema_version": "map_spec.v1",
                "errors": [
                    {"path": list(e["loc"]), "type": e["type"], "message": e["msg"]}
                    for e in exc.errors(include_url=False, include_context=False)
                ],
            }
        context = self.context()
        if [
            spec.size.width * WOXELS_PER_TILE,
            spec.size.height * WOXELS_PER_TILE,
        ] != context["content"]["size"]:
            return {
                "valid": False,
                "errors": [
                    {
                        "feature_id": "size",
                        "message": "spec size must match the currently open map; prepare a native template for another size",
                    }
                ],
            }
        manual = water_bounds(context["content"]["water"])
        for e in context["content"]["elements"]:
            if not is_manual_obstacle(e):
                continue
            if e.get("bounds"):
                a, b = e["bounds"]
                manual.append(
                    [
                        a[0] / WOXELS_PER_TILE,
                        a[1] / WOXELS_PER_TILE,
                        b[0] / WOXELS_PER_TILE,
                        b[1] / WOXELS_PER_TILE,
                    ]
                )
            elif e.get("position"):
                x, y = e["position"]
                manual.append(
                    [
                        x / WOXELS_PER_TILE - 0.5,
                        y / WOXELS_PER_TILE - 0.5,
                        x / WOXELS_PER_TILE + 0.5,
                        y / WOXELS_PER_TILE + 0.5,
                    ]
                )
            else:
                raise BridgeError(
                    "an existing element has no bounds; cannot safely plan around it"
                )
        try:
            plan = generate(
                spec, self.catalog(spec), context["catalog_version"], manual
            )
        except LayoutError as exc:
            return {
                "valid": False,
                "errors": [{"feature_id": exc.feature_id, "message": str(exc)}],
            }
        if context["has_content"] and any(
            op["cmd"] != "place_object" for op in plan["operations"]
        ):
            return {
                "valid": False,
                "errors": [
                    {
                        "feature_id": "map",
                        "message": "terrain, water and buildings require a map without existing elements/water; use base_material=null for additive forest/prop plans",
                    }
                ],
            }
        plan_id = plan["plan_id"]
        if plan_id not in self.records:
            if len(self.records) >= MAX_PLANS:
                raise BridgeError(
                    "64 plans retained; export needed project data before restarting the MCP server"
                )
            self.records[plan_id] = {
                "plan": plan,
                "context": context,
                "submitted": False,
                "job_id": None,
                "manifest": None,
            }
        elif not self.records[plan_id]["submitted"]:
            self.records[plan_id]["context"] = context
        return self.describe(plan_id, include_operations)

    def describe(self, plan_id, include_operations=False):
        record = self.record(plan_id)
        result = copy.deepcopy(record["plan"])
        if not include_operations:
            result.pop("operations")
        result.update(
            valid=True,
            job_id=record["job_id"],
            manifest=copy.deepcopy(record["manifest"]),
        )
        return result

    def record(self, plan_id):
        if plan_id not in self.records:
            raise BridgeError(
                "plan is not retained in this MCP process; plan again before editing"
            )
        return self.records[plan_id]

    def apply(self, plan_id, wait=True):
        from ..server import apply_batch, _wait_for_batch

        record = self.record(plan_id)
        if record.get("imported"):
            raise BridgeError(
                "this applied/imported plan cannot be created again; use revise_battlemap"
            )
        context = self.context()
        if context["bridge_instance"] != record["context"]["bridge_instance"]:
            raise BridgeError(
                "bridge instance changed; this plan cannot be replayed safely"
            )
        if context["content"]["level_id"] != record["context"]["content"]["level_id"]:
            raise BridgeError(
                "level changed; return to the planned level before retrying"
            )
        if context["catalog_version"] != record["context"]["catalog_version"]:
            raise BridgeError("asset catalog changed; plan again")
        if (
            not record["submitted"]
            and context["fingerprint"] != record["context"]["fingerprint"]
        ):
            raise BridgeError("map changed since planning; plan again before applying")
        record["submitted"] = True
        job = apply_batch(record["plan"]["operations"], "plan:" + plan_id, wait=False)
        if not job.get("accepted"):
            record["submitted"] = False
            return job
        record["job_id"] = job["job_id"]
        if wait:
            job = _wait_for_batch(job, 90)
        if job["status"] == "completed" and record["manifest"] is None:
            record["manifest"] = self.manifest(record["plan"], job, record["context"])
            current = self.context()
            record["surface"] = current["surface"]
            record["water"] = current["content"]["water"]
        return {
            "plan_id": plan_id,
            "job": job,
            "manifest": copy.deepcopy(record["manifest"]),
            "warnings": record["plan"]["warnings"],
        }

    def manifest(self, plan, job, context):
        result = {
            "schema_version": "battlemap_manifest.v1",
            "plan_id": plan["plan_id"],
            "bridge_instance": context["bridge_instance"],
            "level_id": context["content"]["level_id"],
            "job_id": job["job_id"],
            "features": {},
        }
        for fid, semantic in plan["features"].items():
            result["features"][fid] = {
                "semantic": copy.deepcopy(semantic),
                "elements": [],
                "operation_indices": [],
            }
        result["features"].setdefault(
            "base",
            {"semantic": {"type": "base"}, "elements": [], "operation_indices": []},
        )
        counters = {}
        for row in job["results"]:
            fid = plan["operation_features"][row["index"]]
            target = result["features"][fid]
            target["operation_indices"].append(row["index"])
            if "id" not in row["result"]:
                continue
            index = counters.get(fid, 0)
            counters[fid] = index + 1
            generated = target["semantic"].get("generated", [])
            semantic_id = (
                generated[index]["semantic_id"]
                if row["cmd"] == "place_object" and index < len(generated)
                else f"{fid}/{row['cmd']}/{index:04d}"
            )
            target["elements"].append(
                {
                    "semantic_id": semantic_id,
                    "id": row["result"]["id"],
                    "cmd": row["cmd"],
                    "operation": plan["operations"][row["index"]],
                }
            )
        return result

    def check_capacity(self, plan_id):
        if plan_id not in self.records and len(self.records) >= MAX_PLANS:
            raise BridgeError("64 plans retained; save projects before restarting MCP")

    def applied_record(self, plan_id):
        record = self.record(plan_id)
        if not record.get("manifest"):
            raise BridgeError(
                "apply this plan to completion before using project tools"
            )
        if record.get("superseded"):
            raise BridgeError("plan was superseded by revision " + record["superseded"])
        return record

    def validate(self, plan_id):
        from .validation import validate

        record = self.applied_record(plan_id)
        context = self.context()
        report = validate(
            record["plan"], record["manifest"], context, record.get("surface")
        )
        if water_geometry(context["content"]["water"]) != water_geometry(record.get(
            "water", context["content"]["water"]
        )):
            report["findings"].append(
                {
                    "severity": "error",
                    "code": "water_changed",
                    "feature_id": "map",
                    "coordinates_tiles": None,
                    "message": "native water geometry differs from project ownership snapshot",
                }
            )
            report["valid"] = False
        return report

    def revise(self, plan_id, replacements, dry_run=True):
        from .revision import (
            revised_spec,
            object_diff,
            revised_manifest,
            revision_summary,
            TERRAIN_COMMANDS,
        )
        from .validation import owned_elements
        from ..server import apply_batch

        record = self.record(plan_id)
        if not record.get("manifest"):
            raise BridgeError("apply plan first")
        # Replays use the same native job even if current map now reflects it.
        key = digest([plan_id, replacements])
        pending = record.get("revision")
        if (
            pending
            and pending["key"] != key
            and pending.get("submitted")
            and pending.get("terminal_status") not in ("cancelled", "failed")
        ):
            raise BridgeError(
                "a different revision is unresolved; inspect/retry it before starting another"
            )
        if pending and pending["key"] == key and pending.get("completed"):
            return copy.deepcopy(pending["result"])
        if not pending or pending["key"] != key:
            if record.get("superseded"):
                raise BridgeError("use the current revision plan ID")
            report = self.validate(plan_id)
            if not report["valid"]:
                return {"valid": False, "validation": report}
            raw, selected = revised_spec(record["plan"], replacements)
            try:
                spec = MapSpec.model_validate(raw)
            except ValidationError as exc:
                return {
                    "valid": False,
                    "errors": [
                        {"path": list(e["loc"]), "message": e["msg"]}
                        for e in exc.errors(include_context=False)
                    ],
                }
            context = self.context()
            ids = {e["id"] for _, e in owned_elements(record["manifest"])}
            manual = []
            for descriptor in context["content"]["elements"]:
                if descriptor["id"] not in ids and is_manual_obstacle(descriptor):
                    if not descriptor.get("bounds"):
                        raise BridgeError(
                            "manual element lacks bounds; cannot revise safely"
                        )
                    a, b = descriptor["bounds"]
                    manual.append([a[0] / 256, a[1] / 256, b[0] / 256, b[1] / 256])
            frozen = {
                fid: s["generated"]
                for fid, s in record["plan"]["features"].items()
                if s["type"] == "forest" and fid not in selected
            }
            try:
                plan = generate(
                    spec, self.catalog(spec), context["catalog_version"], manual, frozen
                )
            except LayoutError as exc:
                return {
                    "valid": False,
                    "errors": [{"feature_id": exc.feature_id, "message": str(exc)}],
                }
            for fid, semantic in record["plan"]["features"].items():
                if semantic["type"] in ("building", "room", "stream", "water_region") and digest(
                    semantic
                ) != digest(plan["features"][fid]):
                    raise BridgeError(
                        "revision would change unselected shared water/building geometry"
                    )
            old_terrain = [
                o for o in record["plan"]["operations"] if o["cmd"] in TERRAIN_COMMANDS
            ]
            new_terrain = [
                o for o in plan["operations"] if o["cmd"] in TERRAIN_COMMANDS
            ]
            operations, targets, identities = object_diff(record["manifest"], plan)
            if old_terrain != new_terrain:
                if spec.base_material is None:
                    raise BridgeError(
                        "terrain revision requires an owned base material"
                    )
                operations = new_terrain + operations
                targets = [["base", None] for _ in new_terrain] + targets
            if len(operations) > 500:
                raise BridgeError("revision diff exceeds 500 native operations")
            self.check_capacity(plan["plan_id"])
            pending = {
                "key": key,
                "plan": plan,
                "operations": operations,
                "targets": targets,
                "identities": identities,
                "context": context,
                "submitted": False,
            }
            record["revision"] = pending
        result = {
            "valid": True,
            "base_plan_id": plan_id,
            "plan_id": pending["plan"]["plan_id"],
            "diff": revision_summary(pending["operations"]),
            "operations": copy.deepcopy(pending["operations"]),
            "warnings": pending["plan"]["warnings"],
            "validation": pending["plan"]["validation"],
        }
        if dry_run:
            return result
        context = self.context()
        if (
            context["bridge_instance"] != pending["context"]["bridge_instance"]
            or context["content"]["level_id"]
            != pending["context"]["content"]["level_id"]
        ):
            raise BridgeError(
                "editor instance or level changed; reload project before revising"
            )
        if (
            not pending["submitted"]
            and context["fingerprint"] != pending["context"]["fingerprint"]
        ):
            record.pop("revision", None)
            raise BridgeError("map changed since revision dry run; revise again")
        if pending["operations"]:
            pending["submitted"] = True
            job = apply_batch(pending["operations"], "revision:" + key)
            if not job.get("accepted"):
                pending["submitted"] = False
                return {**result, "job": job}
            if job["status"] != "completed":
                pending["terminal_status"] = job["status"]
                return {
                    **result,
                    "job": job,
                    "message": "retry this same revision to inspect its retained result",
                }
        else:
            job = {"status": "completed", "job_id": None, "results": []}
        plan = pending["plan"]
        manifest = revised_manifest(
            plan, record["manifest"], job, pending["targets"], pending["identities"]
        )
        current = self.context()
        self.records[plan["plan_id"]] = {
            "plan": plan,
            "context": current,
            "manifest": manifest,
            "submitted": True,
            "job_id": job["job_id"],
            "imported": True,
            "surface": current["surface"],
            "water": current["content"]["water"],
        }
        result.update(applied=True, job=job, manifest=manifest)
        pending.update(completed=True, result=copy.deepcopy(result))
        if plan["plan_id"] != plan_id:
            record["superseded"] = plan["plan_id"]
        return result
