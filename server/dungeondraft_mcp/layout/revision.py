"""Named-feature diffs. Existing native identities survive transforms."""

import copy
from collections import Counter
from ..bridge_client import BridgeError

PROPS = {"forest", "cover", "obstacle", "hazard"}
SURFACES = {"road", "terrain_region"}
TERRAIN_COMMANDS = {"fill_terrain", "fill_region"}


def object_diff(old_manifest, new_plan):
    operations, targets, identities = [], [], {}
    for fid, semantic in new_plan["features"].items():
        old = old_manifest["features"].get(fid, {}).get("elements", [])
        if semantic["type"] not in PROPS:
            continue
        indexed = {e["semantic_id"]: e for e in old}
        retained = set()
        for item in semantic["generated"]:
            sid = item["semantic_id"]
            desired = {
                "cmd": "place_object",
                "asset": item["asset"],
                "x": item["position"][0] * 256,
                "y": item["position"][1] * 256,
                "scale": item["scale"],
                "rotation": item["rotation"],
            }
            if sid not in indexed:
                operations.append(desired)
                targets.append([fid, sid])
                continue
            previous = indexed[sid]
            retained.add(sid)
            identities[sid] = previous["id"]
            before = previous["operation"]
            if any(before[k] != desired[k] for k in ("x", "y")):
                operations.append(
                    {
                        "cmd": "move_element",
                        "id": previous["id"],
                        "x": desired["x"],
                        "y": desired["y"],
                    }
                )
                targets.append([fid, sid])
            changes = {
                k: desired[k]
                for k in ("asset", "scale", "rotation")
                if before.get(k) != desired[k]
            }
            if changes:
                operations.append(
                    {"cmd": "modify_object", "id": previous["id"], **changes}
                )
                targets.append([fid, sid])
        for sid, previous in indexed.items():
            if sid not in retained:
                operations.append({"cmd": "delete_object", "id": previous["id"]})
                targets.append([fid, sid])
    # Deletion happens first so regenerated forests do not temporarily double.
    ordered = sorted(
        zip(operations, targets), key=lambda row: row[0]["cmd"] != "delete_object"
    )
    return [r[0] for r in ordered], [r[1] for r in ordered], identities


def revised_spec(plan, replacements):
    if not isinstance(replacements, list) or not 1 <= len(replacements) <= 64:
        raise BridgeError(
            "features must contain 1..64 complete named feature replacements"
        )
    raw = copy.deepcopy(plan["spec"])
    indexed = {f["id"]: i for i, f in enumerate(raw["features"])}
    seen = set()
    for replacement in replacements:
        fid = replacement.get("id") if isinstance(replacement, dict) else None
        if fid not in indexed or fid in seen:
            raise BridgeError("each replacement must name a different existing feature")
        old = raw["features"][indexed[fid]]
        if replacement.get("type") != old["type"]:
            raise BridgeError("revision must preserve feature type")
        if old["type"] not in PROPS | SURFACES | {"entry", "spawn", "clear_area"}:
            raise BridgeError(
                "stream/building revision is not supported: their native shared geometry needs separate ownership verification"
            )
        raw["features"][indexed[fid]] = replacement
        seen.add(fid)
    return raw, seen


def revision_summary(operations):
    return {
        "operation_count": len(operations),
        "counts": dict(Counter(o["cmd"] for o in operations)),
    }


def revised_manifest(plan, previous, job, targets, identities):
    result = copy.deepcopy(previous)
    result["plan_id"] = plan["plan_id"]
    result["job_id"] = job.get("job_id")
    for row in job.get("results", []):
        if row["cmd"] == "place_object":
            identities[targets[row["index"]][1]] = row["result"]["id"]
    for fid, semantic in plan["features"].items():
        target = result["features"][fid]
        target["semantic"] = copy.deepcopy(semantic)
        target["operation_indices"] = [
            i for i, f in enumerate(plan["operation_features"]) if f == fid
        ]
        if semantic["type"] in PROPS:
            rows = semantic["generated"]
            native = [plan["operations"][i] for i in target["operation_indices"]]
            target["elements"] = [
                {
                    "semantic_id": item["semantic_id"],
                    "id": identities[item["semantic_id"]],
                    "cmd": "place_object",
                    "operation": op,
                }
                for item, op in zip(rows, native)
            ]
    return result
