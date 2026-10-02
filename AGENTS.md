# dungeondraft-mcp

An MCP server that drives a **running Dungeondraft instance** over a localhost
socket. Two halves: a Python MCP server (`server/`) and a GDScript mod
(`mod/`) that runs inside Dungeondraft. See [README.md](README.md) for the
architecture and [PROTOCOL.md](PROTOCOL.md) for every command + implementation
notes.

## Before you call any tool

The tools talk to a live Dungeondraft, not this repo. They only work when:

1. **Dungeondraft is running** with the forked **MCP Bridge mod enabled**, and
2. **a map is open**. Dungeondraft loads tool mods only after a map loads, so a
   human must open or create a map after starting the app. New blank maps are
   also created manually; the bridge can reopen saved maps.

If both aren't true, calls fail (connection refused, or `"no map open"`).
**Verify first:** call `ping` (expect `pong` + protocol version 18), then
`get_status` (expect `map_open: true` and a `map_center`). If `ping` fails, the
mod isn't loaded or DD isn't running — ask the user to start it; don't retry
blindly.

## Working with the map

- Coordinates are **woxel** (world-pixel) space; get `map_center` from
  `get_status`. There are 256 woxels per tile.
- Every element has an integer `id`; create calls return it, `list_elements` /
  `get_element` report it. Feed ids back into move/modify/delete.
- Discover assets with `list_assets` or `list_asset_metadata` (category,
  substring search, offset, limit); list categories with `list_asset_categories`.
- Use `get_capabilities` before planning edits. It reports commands, the live
  Godot engine version, active mods and catalog version. `refresh_asset_catalog`
  rebuilds the cache after asset packs change.
- `open_map` replaces the current map only with `discard_current=true`. Save
  first if needed. `save_map` reopens by default to verify native durability,
  which clears the bridge undo history. Do not call Dungeondraft's internal
  `Master.CreateNewMap` from the mod; it failed during a live map switch.
- The bridge retires a previous native listener using an instance ID stored
  on Godot's Engine singleton. Keep transport ownership outside Editor/World,
  which are replaced on New Map. Do not store managed mod-script references.
- Dungeondraft 1.2.0.1 also logged native `Prop._ExitTree` exceptions during
  UI New Map with all mods disabled. Use a fresh editor session for new blank
  maps if this occurs; the bridge cannot repair Dungeondraft's native cleanup.
- **Look at your work**: `screenshot` (current view) and the camera tools
  (`set_camera`, `focus_element`, `fit_elements`) return/aim the view so you can
  inspect what you built and iterate. Use them.
- The bridge keeps its **own** `undo` / `redo` stacks (independent of DD's
  Ctrl+Z). `delete_element`, `place_pattern`, and `build_room` are not
  undo-recorded.

## Editing the bridge itself

If you change code (not just drive the map), the two halves reload differently:

- **Mod** (`mod/.../mcp_bridge.gd`, GDScript): reload the mod inside Dungeondraft
  (keeps the current map). Changing an existing handler needs only this.
- **Server** (`server/dungeondraft_mcp/server.py`): new/changed `@mcp.tool()`
  definitions need a **Codex MCP server restart**. Restart Codex after changing
  the Python server; adding a new tool needs both the mod and server reloaded.
  Editable installs do not need reinstalling after source edits.
- GDScript on Godot 3.4.2 has **no try/catch**: an unhandled runtime error in a
  handler crashes the mod and kills the bridge (full DD restart). Validate
  inputs before calling DD API methods.
- Parse the full bridge script as Godot 3 GDScript before asking for a mod
  reload. `master` and `tool` are reserved identifiers; using either as a
  local variable kept the entire Phase 1 script from loading. The
  `.github/workflows/gdscript.yml` CI check runs the same parser on pushes and
  pull requests that change GDScript. That syntax parser does not validate
  Godot's global constants; `TYPE_VECTOR2_ARRAY` is the Godot 3 name.
