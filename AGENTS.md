# Dungeondraft AI Enhancement

This repository is a map-creation workspace containing the Python MCP server and Dungeondraft bridge mod. See README.md for installation, supported workflows and operational limits.

## Workspace and map output

- For map work, use .agents/skills/dungeondraft-map-skill/SKILL.md.
- Read map-workflow.json at the resolved Git root before map/export work, even
  from nested directories. These booleans select the skill workflow; explicit
  user instructions take precedence. See README.md#workflow-preferences.
- map-workflow.json is local and Git-ignored; map-workflow.example.json is the
  tracked setup template. Never replace local preferences with example values.
  If the local file is absent, use skill defaults or initialize it from the
  example without overwriting an existing file.
- fully_automatic enables routine creation, opening, restarting, saving and
  requested export without repeated permission questions. reasoning controls
  concise design rationale; enhancing controls optional additions; neither
  disables correctness or visual review. export_to_foundry adds Foundry file
  delivery by default; false still allows an explicit Foundry request.
- Resolve the Git repository root and save map output in dd-maps/<encounter-slug>/.
  This rule applies from nested working directories too. Explicit user destinations override it.
- Keep each encounter's native map, current floor exports, concept preview, notes,
  layout manifest and any project/VTT bundle inside that encounter directory.
- Keep one canonical native map per encounter. Revise it and replace current
  exports in place; do not create backups, old versions or per-edit journals unless requested.

## Before live operations

- For a reachable bridge, call ping, then get_status, then get_capabilities.
- Require protocol 23 and map_open=true before map edits. A failed initial ping
  does not itself require manual startup: use one authorized open_map/create_map
  call with a known native file/bootstrap. The lifecycle controller can start a
  closed editor and refuses to stop a running editor with an unreachable bridge.
  After success, repeat the handshake; after failure inspect the reported state
  and request only the specific setup/input that tools cannot handle. Do not
  retry blindly or ask the user to open/restart a map that lifecycle can manage.
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
- Python open_map/reopen_map save and restart only the identified local editor
  process; readiness checks the new instance, PID, native path and dimensions.
  The low-level bridge open_map guard still rejects populated scene replacement.
- create_map launches a blank native bootstrap, resizes and saves a new path.
  resize_map is limited to blank single-level maps; it clears history. Preserve
  untitled work with save_current_path and never discard unrelated work.
- Wait for save/export completion before reopening or editing. Exports are
  bounded to 16 megapixels and 8192 pixels per side.
- VTT export requires a validated single-level project and a new directory.
  File export does not prove runtime import or configured walls/lighting.
- Bridge undo/redo is independent of native Ctrl+Z. delete_element,
  place_pattern and build_room are not undo-recorded.

## Runtime maintenance

- Keep runtime code and documentation concise; put map output only in dd-maps/.
  Do not add phase journals, review artifacts or ad hoc smoke scripts to the repo.
- Mod handler edits need Reload Mods; new scripts/startup state need a fresh
  editor launch and map load. Reload Mods does not rerun start().
- Python tool definition changes need an MCP server restart. Editable installs
  need no reinstall after source edits.
- Parse the full bridge as Godot 3 GDScript before reloading changed scripts.
  Godot 3 has no try/catch; master/tool are reserved and TYPE_VECTOR2_ARRAY is
  the Godot 3 constant. Validate inputs before native API calls.
- Keep transport ownership outside replaceable Editor/World nodes. Do not call
  private Master.CreateNewMap; native populated-map cleanup is unsafe on 1.2.0.1.
