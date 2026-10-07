"""Durable project bundles and bounded native renders."""

import hashlib
import json
import struct
import tempfile
import time
import uuid
from pathlib import Path
from ..bridge_client import BridgeError
from .layout import digest

FILES = (
    "plan.json",
    "spec.json",
    "catalog.json",
    "manifest.json",
    "validation.json",
    "ownership.json",
    "map.dungeondraft_map",
    "preview.png",
)


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def render(bridge, spec, path=None, max_pixels=1024, ppi=None):
    from ..server import _wait_for_file

    size = spec["size"]
    if ppi is None:
        if (
            not isinstance(max_pixels, int)
            or isinstance(max_pixels, bool)
            or not 256 <= max_pixels <= 2048
        ):
            raise BridgeError("max_pixels must be an integer in 256..2048")
        ppi = max(8, min(128, max_pixels // max(size.values())))
    pixels = [size["width"] * ppi, size["height"] * ppi]
    if max(pixels) > 8192 or pixels[0] * pixels[1] > 16777216:
        raise BridgeError(
            "export exceeds 16 megapixels or 8192 pixels per side; reduce ppi"
        )
    target = (
        Path(path)
        if path
        else Path(tempfile.gettempdir()) / ("dd-preview-" + uuid.uuid4().hex + ".png")
    )
    if not target.is_absolute() or target.exists():
        raise BridgeError("render destination must be a new absolute PNG path")
    camera = bridge.request("get_camera")
    grid = bridge.request("get_export_status")["grid"]
    bridge.request("export_map", path=str(target), ppi=ppi, grid=spec["output"]["grid"])
    _wait_for_file(str(target))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status = bridge.request("get_export_status")
        if not status["exporting"] and not status["managed_export"]:
            break
        time.sleep(0.1)
    else:
        raise BridgeError("native exporter did not finish restoring editor state")
    if status["grid"] != grid:
        raise BridgeError(
            "native exporter did not restore the previous grid visibility"
        )
    restored = bridge.request("get_camera")
    for key in ("position", "zoom"):
        if restored.get(key) != camera.get(key):
            raise BridgeError("native exporter did not restore the camera")
    with target.open("rb") as f:
        header = f.read(24)
    if (
        header[:8] != b"\x89PNG\r\n\x1a\n"
        or list(struct.unpack(">II", header[16:24])) != pixels
    ):
        raise BridgeError(
            "native PNG size differs from full-map specification; reset native crop/export settings"
        )
    return {
        "path": str(target),
        "ppi": ppi,
        "pixels": pixels,
        "grid": spec["output"]["grid"],
        "camera_restored": True,
        "grid_restored": True,
    }


def save_project(planner, plan_id, directory):
    from ..server import save_map

    record = planner.applied_record(plan_id)
    validation = planner.validate(plan_id)
    if not validation["valid"]:
        raise BridgeError(
            "project validation failed; inspect validate_battlemap findings before saving"
        )
    root = Path(directory)
    if not root.is_absolute() or root.exists() or not root.parent.is_dir():
        raise BridgeError(
            "project directory must be a new absolute path in an existing parent"
        )
    root.mkdir()
    # project.json is the completion marker. An interrupted folder is never
    # accepted as a complete project and is retained for recovery.
    plan = record["plan"]
    native = save_map(path=str(root / "map.dungeondraft_map"))
    if not native.get("valid_native_json"):
        raise BridgeError("native project save was not confirmed")
    preview = render(planner.bridge, plan["spec"], root / "preview.png")
    context = planner.context()
    ownership = {
        "surface": record["surface"],
        "water": record["water"],
        "bridge_instance": context["bridge_instance"],
        "level_id": context["content"]["level_id"],
    }
    for name, data in {
        "plan.json": plan,
        "spec.json": plan["spec"],
        "catalog.json": plan["resolved_assets"],
        "manifest.json": record["manifest"],
        "validation.json": validation,
        "ownership.json": ownership,
    }.items():
        write_json(root / name, data)
    project = {
        "schema_version": "battlemap_project.v1",
        "plan_id": plan_id,
        "seed": plan["spec"]["seed"],
        "generator_version": plan["generator_version"],
        "geometry_runtime": plan["geometry_runtime"],
        "preview": {**preview, "path": "preview.png"},
        "files": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in FILES
        },
    }
    write_json(root / "project.json", project)
    return {
        "saved": True,
        "directory": str(root),
        "plan_id": plan_id,
        "native_map": str(root / "map.dungeondraft_map"),
        "preview": preview,
        "validation": validation,
    }


def restored_level_id(native, floors):
    """Match the saved active floor before rebinding session-local native IDs."""
    index = native["header"]["editor_state"]["current_level"]
    if type(index) is not int or index < 0 or index >= len(floors["levels"]):
        raise BridgeError("project's saved floor is unavailable")
    saved = native["world"]["levels"][str(index)]
    current = floors["levels"][index]
    if floors["current_index"] != index or current["label"] != saved["label"]:
        raise BridgeError("select the project's saved floor before restoring ownership")
    return current["id"]


def load_project(planner, directory):
    root = Path(directory)
    if not root.is_absolute():
        raise BridgeError("project directory must be absolute")
    try:
        project = json.loads((root / "project.json").read_text(encoding="utf-8"))
        if project["schema_version"] != "battlemap_project.v1" or set(
            project["files"]
        ) != set(FILES):
            raise ValueError("unsupported project version or file list")
        for name in FILES:
            path = root / name
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size > 128 * 1024 * 1024
            ):
                raise ValueError("invalid or oversized project file")
            if hashlib.sha256(path.read_bytes()).hexdigest() != project["files"][name]:
                raise ValueError("project checksum mismatch: " + name)
        plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        ownership = json.loads((root / "ownership.json").read_text(encoding="utf-8"))
        spec = json.loads((root / "spec.json").read_text(encoding="utf-8"))
        catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
        if spec != plan["spec"] or catalog != plan["resolved_assets"]:
            raise ValueError("project specification/catalog disagree with plan")
        # Hash all canonical plan data, not response-only fields.
        canonical = {
            k: v
            for k, v in plan.items()
            if k not in ("plan_id", "valid", "manifest", "job_id")
        }
        if (
            digest(canonical) != plan["plan_id"]
            or project["plan_id"] != plan["plan_id"]
            or manifest["plan_id"] != plan["plan_id"]
        ):
            raise ValueError("invalid plan identity")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BridgeError(f"project cannot be loaded: {exc}") from exc
    from .spec import MapSpec

    MapSpec.model_validate(spec)
    context = planner.context()
    # Loading adopts already-open native IDs; it never overwrites/reopens a map.
    if (
        Path(context["content"]["path"]).resolve()
        != (root / "map.dungeondraft_map").resolve()
    ):
        raise BridgeError(
            "open this project's native map before loading its planning data"
        )
    # Dungeondraft regenerates Level.ID in file order on loading. It remains
    # stable only within a session; the verified native file identifies its floor.
    native = json.loads((root / "map.dungeondraft_map").read_text(encoding="utf-8"))
    manifest["level_id"] = restored_level_id(
        native, planner.bridge.request("list_levels")
    )
    ownership["surface"]["level_id"] = manifest["level_id"]
    from .validation import validate

    report = validate(plan, manifest, context, ownership["surface"])
    if not report["valid"] or context["content"]["water"] != ownership["water"]:
        raise BridgeError(
            "project ownership does not match the open map; no planning data adopted"
        )
    planner.check_capacity(plan["plan_id"])
    manifest["bridge_instance"] = context["bridge_instance"]
    planner.records[plan["plan_id"]] = {
        "plan": canonical | {"plan_id": plan["plan_id"]},
        "manifest": manifest,
        "context": context,
        "submitted": True,
        "job_id": None,
        "imported": True,
        "surface": ownership["surface"],
        "water": ownership["water"],
    }
    return {
        "loaded": True,
        "plan_id": plan["plan_id"],
        "validation": report,
        "directory": str(root),
    }
