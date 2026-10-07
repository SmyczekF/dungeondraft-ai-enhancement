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
   map must load after starting the app. Create new blank dimensions manually,
   or start an existing native template with the external launcher. The bridge
   can open saved maps from an empty current map.

If both aren't true, calls fail (connection refused, or `"no map open"`).
**Verify first:** call `ping` (expect `pong` + protocol version 23), then
`get_status` (expect `map_open: true` and a `map_center`). If `ping` fails, the
mod isn't loaded or DD isn't running — ask the user to start it; don't retry
blindly.

## Working with the map

- `export_battlemap` writes optional Universal VTT / Foundry 14 files only.
  It requires a validated applied/restored project on a single-level map and
  a new directory. Supply the intended relative Foundry PNG path. Native images
  are unbaked; review door types/ambient lighting and perform target-runtime
  import separately. File export does not prove a Foundry scene was imported.
- Use `render_preview` and `validate_battlemap` after applying a plan. Pixel
  review and structural connectivity are separate checks. Save reproducible
  bundles with `save_battlemap_project`. After restarting MCP/editor, open the
  bundle native map and restore ownership with `load_battlemap_project`.
- `revise_battlemap` accepts complete named feature replacements; default dry
  run returns the diff. Retain the new plan ID. Manual terrain changes cause
  ownership conflicts. Water/building shared geometry is currently excluded.
- Exports are bounded to 16 megapixels / 8192 pixels per side. Wait for native
  export completion before editing; VTT exports restore grid, lighting and camera.


- Prefer `plan_battlemap` then `apply_battlemap` for complete encounters. Specs
  use tiles, while low-level operations use woxels. Inspect warnings and
  validation before applying. Keep the returned semantic/native-ID manifest.
  Plans are retained by the MCP server process and tied to one editor instance
  and level. Native editor UI should remain unchanged between plan and apply.


- Prefer `apply_batch` for repetitive placement. Check `get_capabilities.batch`
  for supported commands and limits. Use a stable idempotency key and retain
  the returned job ID; jobs are scoped to the current bridge instance.
  Leave the native editor UI unchanged until completion or cancellation.
  `SuppressTool` also disables mod updates; never use it to lock a batch.


- Coordinates are **woxel** (world-pixel) space; get `map_center` from
  `get_status`. There are 256 woxels per tile.
- Drawing layers are distinct from native floors. Objects use `layer` in
  -1000..1000; pattern `z` sets its persistent native parent layer. Put room
  floors below objects and pier cargo above its deck. `add_level` inserts a blank
  floor at index 0, keeping the previous floor active; use its returned index
  with `set_level`. `level_id` is the native ID, `level_index` is the list index.
  IDs are stable during a session but regenerated on file load. Project loading
  matches the saved floor and checks geometry before adopting its new ID.
  Undo/redo on another floor is rejected; return to the edit's original floor.
- Every element has an integer `id`; create calls return it, `list_elements` /
  `get_element` report it. Feed ids back into move/modify/delete.
- Discover assets with `list_assets` or `list_asset_metadata` (category,
  substring search, offset, limit); list categories with `list_asset_categories`.
- Use `get_capabilities` before planning edits. It reports commands, the live
  Godot engine version, active mods and catalog version. `refresh_asset_catalog`
  rebuilds the cache after asset packs change.
- `open_map` requires an empty current map across every floor and
  `discard_current=true`. Populated replacement raises native cleanup exceptions
  on 1.2.0.1 and is rejected. Save and restart using the external launcher for
  a populated map. `save_map` validates the written native JSON and preserves
  bridge undo history. For an empty-map reopen, wait until the save notification
  disappears; immediate reopening can leave native callbacks pointing at freed
  widgets.
  `bridge_dirty` compares bridge edit state with the last verified MCP save.
  Undo/redo preserves the save checkpoint; non-recorded edits stay conservatively
  dirty until saved. UI saving alone does not confirm a bridge checkpoint.
  Do not call Dungeondraft's internal
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

- **Mod** (`mod/.../mcp_bridge.gd`, GDScript): Reload Mods recompiles already
  loaded scripts while preserving instance state; it does not rerun `start()`.
  Use it for changes to existing handlers. Newly added script files, startup
  initialization, and new instance state need a fresh Dungeondraft launch and
  first-map load (a prepared native template can be launched externally).
  Follow session authorization for starting/closing disposable apps; ask when
  it is missing. Do not assume a
  new startup probe ran just because Reload Mods was clicked.
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
