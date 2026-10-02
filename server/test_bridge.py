#!/usr/bin/env python3
"""Per-command validator for the Dungeondraft bridge — no MCP involved.

Run with Dungeondraft open (mod enabled, a disposable map loaded). It exercises
basic element edits and prints PASS/FAIL per command, so you can see what
works on your Dungeondraft version. It builds a small throwaway scene near the
map center (a room of walls, an object, a light, a path) and then deletes what
it created.

    python test_bridge.py
"""

import sys

from dungeondraft_mcp.bridge_client import BridgeClient, BridgeError

bridge = BridgeClient()
created_ids: list[int] = []
passed = 0
failed = 0


def check(label, fn):
    global passed, failed
    try:
        result = fn()
        print(f"  PASS  {label:18} -> {result}")
        passed += 1
        return result
    except BridgeError as exc:
        print(f"  FAIL  {label:18} -> {exc}")
        failed += 1
        return None


def first_asset(category, search=""):
    res = bridge.request("list_assets", category=category, search=search, limit=1)
    assets = res.get("assets") or []
    return assets[0] if assets else None


def object_ids():
    ids = set()
    offset = 0
    while True:
        page = bridge.request("list_elements", kind="objects", offset=offset, limit=500)
        ids.update(el["id"] for el in page["elements"])
        offset += page["count"]
        if offset >= page["total"]:
            return ids


def main() -> int:
    try:
        status = bridge.request("ping")
    except BridgeError as exc:
        print("Cannot reach the bridge:", exc, file=sys.stderr)
        return 1
    print("Bridge reachable:", status, "\n")

    cx, cy = 6400, 6400
    st = check("get_status", lambda: bridge.request("get_status"))
    if st and st.get("map_center"):
        cx, cy = st["map_center"]

    check("list_categories", lambda: bridge.request("list_asset_categories"))

    obj_asset = first_asset("Objects")
    wall_asset = first_asset("Walls")
    path_asset = first_asset("Paths")

    # --- create ---
    obj = check("place_object", lambda: bridge.request("place_object", asset=obj_asset, x=cx, y=cy))
    if obj:
        created_ids.append(obj["id"])

    room = [[cx - 200, cy - 200], [cx + 200, cy - 200], [cx + 200, cy + 200], [cx - 200, cy + 200]]
    wall = check("draw_wall", lambda: bridge.request("draw_wall", points=room, asset=wall_asset or "", loop=True))
    if wall:
        created_ids.append(wall["id"])

    if path_asset:
        path = check("draw_path", lambda: bridge.request(
            "draw_path", points=[[cx - 300, cy], [cx, cy - 50], [cx + 300, cy]], asset=path_asset))
        if path:
            created_ids.append(path["id"])
    else:
        print("  SKIP  draw_path          -> no Paths assets")

    light = check("add_light", lambda: bridge.request("add_light", x=cx, y=cy, energy=1.5))
    if light:
        created_ids.append(light["id"])

    # --- query / modify ---
    check("list_elements", lambda: bridge.request("list_elements", kind="objects", limit=5))
    if obj:
        check("get_element", lambda: bridge.request("get_element", id=obj["id"]))
        check("move_element", lambda: bridge.request("move_element", id=obj["id"], x=cx + 80, y=cy + 80))
        check("modify_object", lambda: bridge.request("modify_object", id=obj["id"], scale=1.5, rotation=45))
        dup = check("duplicate_object", lambda: bridge.request("duplicate_object", id=obj["id"], dx=120))
        if dup:
            created_ids.append(dup["id"])

    check("list_levels", lambda: bridge.request("list_levels"))
    if created_ids:
        check("select_elements", lambda: bridge.request("select_elements", ids=created_ids))
        check("clear_selection", lambda: bridge.request("clear_selection"))

    # --- undo / redo round trip: place an object, undo it, redo it ---
    def undo_round_trip():
        existing_ids = object_ids()
        before = bridge.request("get_status")["counts"]["objects"]
        made = bridge.request("place_object", asset=obj_asset, x=cx - 200, y=cy)
        created_ids.append(made["id"])
        after_create = bridge.request("get_status")["counts"]["objects"]
        bridge.request("undo")
        after_undo = bridge.request("get_status")["counts"]["objects"]
        bridge.request("redo")
        after_redo = bridge.request("get_status")["counts"]["objects"]
        # Redo can allocate a new ID; never add preexisting map objects to cleanup.
        for ident in object_ids() - existing_ids:
            if ident not in created_ids:
                created_ids.append(ident)
        if not (after_create == before + 1 and after_undo == before and after_redo == before + 1):
            raise BridgeError(f"counts before={before} create={after_create} undo={after_undo} redo={after_redo}")
        return f"object count {before}->{after_create} undo->{after_undo} redo->{after_redo}"

    check("undo/redo", undo_round_trip)

    # --- cleanup: delete everything we made ---
    deleted = 0
    for eid in created_ids:
        try:
            if bridge.request("delete_element", id=eid).get("deleted"):
                deleted += 1
        except BridgeError:
            pass
    print(f"\nCleaned up {deleted}/{len(created_ids)} created elements.")
    print(f"\n{passed} passed, {failed} failed.")
    print("(Terrain / portal / roof / text commands aren't auto-tested here to avoid "
          "messing up your map — try them by hand once the basics pass.)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
