"""Save, restart by native file argument, and wait for the intended map."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import time
from threading import RLock

from .bridge_client import BridgeError
from . import editor_process


def native_path(path: str, *, must_exist: bool = False) -> Path:
    target = Path(path)
    if not target.is_absolute() or target.suffix.lower() != ".dungeondraft_map":
        raise BridgeError("path must be an absolute .dungeondraft_map file")
    target = target.resolve()
    if must_exist and not target.is_file():
        raise BridgeError(f"map file does not exist: {target}")
    if not target.parent.is_dir():
        raise BridgeError(f"destination directory does not exist: {target.parent}")
    return target


def read_native(path: Path) -> dict:
    try:
        native = json.loads(path.read_text(encoding="utf-8-sig"))
        world = native["world"]
        if not isinstance(world["levels"], dict) or not world["levels"]:
            raise ValueError("missing levels")
        if any(type(world[k]) is not int or not 1 <= world[k] <= 200 for k in ("width", "height")):
            raise ValueError("invalid dimensions")
        return native
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BridgeError(f"Invalid native map {path}: {exc}") from exc


def validate_bootstrap(native: dict) -> None:
    levels = native["world"]["levels"]
    if len(levels) != 1:
        raise BridgeError("Bootstrap must contain one blank level")
    level = next(iter(levels.values()))
    for key in ("objects", "walls", "portals", "paths", "patterns", "lights", "texts", "materials"):
        if level.get(key):
            raise BridgeError(f"Bootstrap contains {key}")
    if (level.get("roofs", {}).get("roofs") or "tree" in level.get("water", {}) or
            any(level.get("shapes", {}).get(k) for k in ("polygons", "walls"))):
        raise BridgeError("Bootstrap contains roofs, water or building shapes")
    pools = [(level.get("cave", {}).get(k), (0,)) for k in ("bitmap", "entrance_bitmap")]
    pools += [(level.get("terrain", {}).get("splat"), (255, 0, 0, 0)),
              (level.get("tiles", {}).get("cells"), (-1,))]
    for value, expected in pools:
        if not isinstance(value, str) or not re.fullmatch(r"Pool(?:Byte|Int)Array\(\s*[-\d,\s]*\)", value):
            raise BridgeError("Bootstrap has unreadable surface data")
        numbers = tuple(int(n) for n in re.findall(r"-?\d+", value))
        if not numbers or len(numbers) % len(expected) or any(n != expected[i % len(expected)] for i, n in enumerate(numbers)):
            raise BridgeError("Bootstrap contains terrain, cave or tile painting")
    if level.get("terrain", {}).get("expand_slots"):
        raise BridgeError("Bootstrap requires the default four terrain slots")


class EditorLifecycle:
    def __init__(self, bridge, save):
        self.bridge = bridge
        self.save = save
        self.lock = RLock()
        self.process = None

    @staticmethod
    def idle(info):
        if any(info.get(k) for k in ("saving", "loading", "exporting", "batch_active")):
            raise BridgeError("Editor is busy; wait for save/load/export/batch completion")

    def inspect(self):
        hello = self.bridge.request("ping")
        status = self.bridge.request("get_status")
        capabilities = self.bridge.request("get_capabilities")
        if not hello.get("pong") or hello.get("protocol") != 23 or capabilities.get("protocol") != 23:
            raise BridgeError("Editor lifecycle requires bridge protocol 23")
        if not status.get("map_open"):
            raise BridgeError("Bridge has no open map")
        info = self.bridge.request("get_map_info")
        self.idle(info)
        return info

    def _wait_ready(self, target, previous_instance, pid, timeout=90):
        deadline = time.monotonic() + timeout
        last_error = "bridge has not become ready"
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise BridgeError(f"Dungeondraft exited during startup (code {self.process.returncode}) "
                                  f"for {target}; file retained. Log: {target.with_suffix('.editor.log')}")
            try:
                hello = self.bridge.request("ping")
                if hello.get("bridge_instance") == previous_instance:
                    last_error = "previous bridge is still active"
                else:
                    info = self.inspect()
                    actual = Path(info.get("path", "")).resolve()
                    owner = info.get("process_id") or editor_process.listener_pid(self.bridge.port)
                    if owner == pid and actual == target and info.get("bridge_instance") != previous_instance:
                        expected = read_native(target)["world"]
                        if info.get("size_tiles") == [expected["width"], expected["height"]]:
                            return {**info, "process_id": pid, "ready": True}
                    last_error = f"unexpected process, path or dimensions: {info}"
            except BridgeError as exc:
                last_error = str(exc)
            time.sleep(0.4)
        raise BridgeError(f"Editor readiness timed out for {target} (PID {pid}): {last_error}. "
                          "The launched editor was left running; inspect it before retrying.")

    def open(self, path, *, discard_current=False, save_current_path=""):
        with self.lock:
            if self.bridge.host not in ("127.0.0.1", "localhost") or sys.platform != "win32":
                raise BridgeError("Editor lifecycle requires a local Windows bridge")
            target = native_path(path, must_exist=True)
            read_native(target)  # validate before saving or stopping anything
            pids = editor_process.editor_pids()
            previous = ""
            executable = Path(os.environ.get("DD_EDITOR_EXECUTABLE", "") or
                              Path(os.environ.get("ProgramFiles", "C:/Program Files")) /
                              "Dungeondraft" / "Dungeondraft.exe")
            if pids:
                info = self.inspect()  # unreachable bridge: do not stop any process
                previous = info["bridge_instance"]
                pid = info.get("process_id") or editor_process.listener_pid(self.bridge.port)
                if pid not in pids:
                    raise BridgeError("Bridge listener is not an identified editor process")
                process = editor_process.EditorProcess(pid)
                try:
                    executable = process.executable
                    if not discard_current:
                        destination = save_current_path or info.get("path", "")
                        if not destination:
                            raise BridgeError("Current map has no path; supply save_current_path or explicit discard_current")
                        self.save(path=destination, overwrite=not bool(save_current_path))
                    current = self.inspect()
                    if current["bridge_instance"] != previous:
                        raise BridgeError("Bridge changed during save; editor was left running")
                    if not discard_current and current.get("dirty"):
                        raise BridgeError("Map changed or native save is unfinished; editor was left running")
                    if editor_process.listener_pid(self.bridge.port) != pid:
                        raise BridgeError("Bridge process changed before restart")
                    process.stop()
                finally:
                    process.close()
            if executable.name.lower() != "dungeondraft.exe" or not executable.is_file():
                raise BridgeError("Set DD_EDITOR_EXECUTABLE to the installed Dungeondraft.exe")
            self.process = editor_process.launch(executable, target)
            return self._wait_ready(target, previous, self.process.pid)

    def create(self, width, height, path, *, bootstrap_path="", save_current_path=""):
        with self.lock:
            if any(type(n) is not int or not 1 <= n <= 200 for n in (width, height)):
                raise BridgeError("width and height must be integer tile counts in 1..200")
            target = native_path(path)
            if target.exists():
                raise BridgeError(f"New map destination already exists: {target}")
            source = bootstrap_path or os.environ.get("DD_BOOTSTRAP_MAP", "")
            if not source:
                raise BridgeError("Supply bootstrap_path or DD_BOOTSTRAP_MAP: an existing blank native map")
            template = native_path(source, must_exist=True)
            validate_bootstrap(read_native(template))
            # Exclusive creation: a failed/retried operation never overwrites work.
            with target.open("xb") as output:
                output.write(template.read_bytes())
            try:
                opened = self.open(str(target), save_current_path=save_current_path)
                result = self.bridge.request("resize_map", width=width, height=height)
                if result.get("size_tiles") != [width, height]:
                    raise BridgeError(f"Resize did not reach requested dimensions: {result}")
                self.save(path=str(target), overwrite=True)
                info = self.inspect()
                native = read_native(target)["world"]
                if (info.get("bridge_instance") != opened.get("bridge_instance") or
                        Path(info.get("path", "")).resolve() != target or info.get("dirty") or
                        info.get("size_tiles") != [width, height] or
                        [native["width"], native["height"]] != [width, height]):
                    raise BridgeError("Saved map identity, clean state or dimensions do not match the created map")
                return {**info, "ready": True, "created": True, "valid_native_json": True}
            except Exception as exc:
                raise BridgeError(f"create_map incomplete; retained {target}: {exc}") from exc
