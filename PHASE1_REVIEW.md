# Phase 1 review: native map lifecycle and inspection

## Implemented

The bridge adds `create_map`, `open_map`, `save_map`, `get_map_info`,
`get_capabilities`, `list_asset_metadata`, and `refresh_asset_catalog`.
`list_elements` supports pagination and reports visual bounds, geometry, layer,
and assets where Dungeondraft exposes them. Created objects, paths, and lights
have Dungeondraft's `preview` marker cleared so native saving can include them.

The Python `save_map` waits for parseable native JSON. By default, it reopens the
map and compares element counts. MCP map switches release the old listener
before Dungeondraft reloads the scene and bridge. UI map switches and mod
reloads transfer the listener to the newest bridge instance.

## Current verification state

Source checks cover Python syntax, tool/handler parity, and Git whitespace.
The installed Dungeondraft 1.2.0.1 assembly and disposable runtime probes
confirmed the native create, save, and open entry points. The full Phase 1
round trip remains **[RETEST]** until the updated mod is reloaded and
`phase1_smoke.py` passes.

The 2026-10-01 manual New Map attempt showed port 8787 error 22, which Godot
names `ERR_ALREADY_IN_USE`. The previous bridge opened a new listener each
time its tool script started, but only released the old one for MCP-requested
switches. The new bridge hands off its listener during UI-driven map changes
and mod reloads. Windows also recorded Dungeondraft access-violation crashes;
the port dialog alone does not prove their native cause, so a fresh manual New
Map test is still required.

Later crashes at 22:17 and 22:20 had the same native fault offset as the 22:06
and 22:07 crashes, after the listener change. The listener handoff addresses
the port conflict; it has not resolved the crash. The UI New Map action does
not invoke the bridge's MCP `create_map` handler. Before changing map-creation
code, isolate whether the crash occurs with no mods, with only this mod, or
only when another mod is enabled.

The original **MCP Bridge 0.1.0** still appears because a separate installation
exists in `C:\Program Files\Dungeondraft\mods\dungeondraft-mcp-bridge`.
Windows denied a move from that protected directory. It is absent from the
current `active_mods` list, but its listing remains until an administrator
removes that old folder.

## Live acceptance check

1. Save any map you wish to keep. Have a disposable map open in Dungeondraft.
   Dungeondraft loads tool mods only after a map opens, so this first load is
   **[PLAN CHANGED]** to a manual action per app session.
2. Fully restart Dungeondraft so the previous bridge code releases port 8787.
   Enable **Dungeondraft MCP** in Mods again if needed: its neutral mod ID is
   `DungeondraftMCP.Bridge`.
   Open a disposable map, then create a second blank map using the UI. Check
   that no port alert or crash appears. Do not enable an older MCP Bridge mod.
3. Click **Reload Mods** once. Codex will check MCP `ping` after you report back.
4. From the repository root, run
   `.\.venv\Scripts\python.exe .\phase1_smoke.py --discard-current --output-dir <new-empty-directory>`.
   The runner replaces the disposable map, discovers assets, creates a 20 × 16
   map, paints grass and a dirt path, places ten oaks, checks inspection
   pagination, saves and reopens the native map, compares exact IDs and assets,
   and exports a PNG.
5. Review `sample.dungeondraft_map`, `sample.png`, and `report.json` in that
   output directory. Check the native file has ten objects and that the PNG
   shows five trees on each side of the center path.

Codex can run step 4 after the user reports that steps 2 and 3 are done. No computer
control is required.
