# Phase 1 review: native map lifecycle and inspection

## Implemented

The bridge adds `create_map`, `open_map`, `save_map`, `get_map_info`,
`get_capabilities`, `list_asset_metadata`, and `refresh_asset_catalog`.
`list_elements` supports pagination and reports visual bounds, geometry, layer,
and assets where Dungeondraft exposes them. Created objects, paths, and lights
have Dungeondraft's `preview` marker cleared so native saving can include them.

The Python `save_map` waits for parseable native JSON. By default, it reopens the
map and compares element counts. Map creation and opening release the old
listener before Dungeondraft reloads the scene and bridge.

## Current verification state

Source checks cover Python syntax, tool/handler parity, and Git whitespace.
The installed Dungeondraft 1.2.0.1 assembly and disposable runtime probes
confirmed the native create, save, and open entry points. The full Phase 1
round trip remains **[RETEST]** until the updated mod is reloaded and
`phase1_smoke.py` passes.

## Live acceptance check

1. Save any map you wish to keep. Have a disposable map open in Dungeondraft.
   Dungeondraft loads tool mods only after a map opens, so this first load is
   **[PLAN CHANGED]** to a manual action per app session.
2. Click **Reload Mods** once. Do not use an older MCP Bridge mod on port 8787.
3. From the repository root, run
   `.\.venv\Scripts\python.exe .\phase1_smoke.py --discard-current --output-dir <new-empty-directory>`.
   The runner replaces the disposable map, discovers assets, creates a 20 × 16
   map, paints grass and a dirt path, places ten oaks, checks inspection
   pagination, saves and reopens the native map, compares exact IDs and assets,
   and exports a PNG.
4. Review `sample.dungeondraft_map`, `sample.png`, and `report.json` in that
   output directory. Check the native file has ten objects and that the PNG
   shows five trees on each side of the center path.

Codex can run step 3 after the user reports that step 2 is done. No computer
control is required.
