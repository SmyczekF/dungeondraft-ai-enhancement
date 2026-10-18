# Dungeondraft MCP

This repository contains the runtime Python MCP server and Dungeondraft bridge
mod. See README.md for installation, supported workflows and operational limits.

## Before live operations

- Call ping, then get_status, then get_capabilities.
- Require protocol 23 and map_open=true. If ping fails, request that the user
  start Dungeondraft with MCP Bridge enabled and load a map; do not retry blindly.
- These tools edit a live map. Inspect existing content before changing it.
- Coordinates are woxels, 256 per tile; planning specifications use tiles.
- Discover assets before placement. Feed returned element IDs into edits.
- Native floor IDs differ from list indices and can change after loading.
  Drawing layers are distinct from floors.

## Map edits

- Prefer plan_battlemap/apply_battlemap for complete encounters.
- Review warnings before applying. Keep plan IDs and semantic/native manifests.
- Use apply_batch for repetitive supported operations; check capability limits,
  reuse stable idempotency keys and retain job IDs. Leave editor UI unchanged
  until completion/cancellation. Never use SuppressTool to lock a batch.
- Inspect whole maps and local details with renders, screenshots and camera
  tools. Visual quality and structural connectivity are separate checks.
- Save native maps. Use project bundles when planner ownership must survive a
  restart; reopen the bundle native map before load_battlemap_project.
- Manual terrain/water edits can invalidate ownership. Named revisions replace
  complete features; inspect the default dry run and retain the new plan ID.
- open_map only replaces an empty map with discard_current=true. For populated
  maps, save and restart the editor with the intended native file.
- Wait for save/export completion before reopening or editing. Exports are
  bounded to 16 megapixels and 8192 pixels per side.
- VTT export requires a validated single-level project and a new directory.
  File export does not prove runtime import or configured walls/lighting.
- Bridge undo/redo is independent of native Ctrl+Z. delete_element,
  place_pattern and build_room are not undo-recorded.

## Runtime maintenance

- Keep this checkout focused on runtime files and concise current documentation.
  Do not add phase journals, review artifacts, sample maps or ad hoc smoke scripts.
- Mod handler edits need Reload Mods; new scripts/startup state need a fresh
  editor launch and map load. Reload Mods does not rerun start().
- Python tool definition changes need an MCP server restart. Editable installs
  need no reinstall after source edits.
- Parse the full bridge as Godot 3 GDScript before reloading changed scripts.
  Godot 3 has no try/catch; master/tool are reserved and TYPE_VECTOR2_ARRAY is
  the Godot 3 constant. Validate inputs before native API calls.
- Keep transport ownership outside replaceable Editor/World nodes. Do not call
  private Master.CreateNewMap; native populated-map cleanup is unsafe on 1.2.0.1.
