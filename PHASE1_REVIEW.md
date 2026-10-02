# Phase 1 review: native map save/open and inspection

## Delivered

Protocol 18 / package 0.2.2 exposes 45 MCP tools. `create_map` was removed:
Dungeondraft's internal new-map call failed from an active mod. Create new
blank maps in Dungeondraft; MCP can then edit, save, export and reopen them.

The bridge provides `open_map`, `save_map`, `get_map_info`, `get_capabilities`,
`list_asset_metadata`, and `refresh_asset_catalog`. Paged inspection covers
objects, walls, paths, lights, portals, roofs, patterns and texts. Descriptors
report geometry, world bounds, layer and assets where applicable.

Phase 1 corrections:

- Clear Dungeondraft's `preview` marker on created objects, paths and lights,
  so native saving includes them.
- Enumerate actual pattern shapes using `GetShapes()`, rather than their
  layer containers. Read their public `_Texture` property, which holds the
  shader texture in the installed 1.2.0.1 assembly.
- Include mounted doors in status counts; distinguish free and mounted portals
  using the published selectable enum and `IsFreestanding`/`WallID`.
- Transform free-door sprite bounds to world space and derive light bounds
  from the Godot 3 Light2D texture, offset and texture scale.
- Retire the previous native TCP listener at startup. Its instance ID is stored
  on Engine, which survives Editor replacement. UI New Map no longer causes
  the bridge's port 8787 conflict. Scene-local metadata did not survive replacement;
  managed mod-script ownership was unreliable in this Mono build.
- Fix the basic test runner to clean up only its own objects after undo/redo.
- Report an empty path for an unsaved map; omit the unavailable Dungeondraft
  product version instead of reporting `"Null"`. Capabilities report Godot's version.

## Live verification on 2026-10-02

Installed editor: Dungeondraft 1.2.0.1, Godot 3.4.2, MCP bridge protocol 18.

- `server/test_bridge.py`: **15 passed, 0 failed**. Cleanup retained all ten
  preexisting sample trees and their IDs.
- Expanded `phase1_smoke.py`: **passed** on a blank 35 x 20 map. The native
  sample contains exactly ten editable oaks; save/reopen retained IDs and assets.
  Its PNG is 1400 x 800 at 40 PPI and was visually inspected.
- Mixed native scene: ten trees, one wall, one drawn path, one light, one
  mounted door, one free door, one roof, **two floor shapes**, and one text.
  Every kind passed ID/asset durability, bounds, pagination and `get_element`
  agreement after native save/reopen. Status counts matched inspection.
- Fresh MCP stdio client: handshake, **45 tools**, live ping/status/capabilities
  passed; `create_map` is absent from the tool schema.
- Six rejection checks passed: implicit map replacement, implicit overwrite,
  relative save path, missing map file, invalid element kind, and invalid
  pagination. They preserved the current map. Asset catalog refresh retained
  the same catalog version for unchanged assets.
- Two consecutive UI New Map switches: new blank maps appeared, the bridge
  remained reachable with new instance IDs, and no bind conflict occurred.
- Reload Mods: edited handler loaded and live queries continued to work.
- Full Godot 3 `gdparse` syntax gate passed for the final bridge source.

Local proof artifacts are in
`C:\Users\smycz\Documents\ChatGPT\Dungeondraft\phase1-final-2026-10-02`:
`sample.dungeondraft_map`, `sample.png`, `mixed.dungeondraft_map`, `report.json`.
They are review outputs, not committed repository fixtures.

## Remaining editor limitation

UI New Map replacing a populated map logged `System.ArgumentOutOfRangeException`
in native `World.get_Level` / `Prop._ExitTree`. The same sample and UI action
reproduced that exception with **all mods disabled**; the blank map still
appeared. An intermittent `GDMonoInternals::tie_managed_to_unmanaged` fatal
startup error also occurred with mods disabled and the next launch succeeded.
These observations do not establish the cause of every earlier crash.

The bridge cannot repair Dungeondraft's native runtime. After native exceptions,
restart the editor before making a new blank map. MCP save/open passed the
final acceptance workflow. The unsafe in-mod `Master.CreateNewMap` remains
**[REJECTED]**, with manual blank-map creation **[PLAN CHANGED]** in the roadmap.

The original mod configuration was restored byte-for-byte after isolation.
Dungeondraft is left open on the saved ten-tree sample with the MCP enabled.
The editable Python install was refreshed from stale 0.1.0 metadata to 0.2.2;
its rebuilt executable passed the MCP stdio check.

## How to review

1. Inspect `sample.png`, then open `sample.dungeondraft_map`. Expect grass,
   a center dirt path, and five editable oaks on each side.
2. Open `mixed.dungeondraft_map` to inspect the added wall, doors, floor shapes,
   roof, drawn path, light and text. `report.json` contains their descriptors.
3. To repeat acceptance, start Dungeondraft with **Dungeondraft MCP** enabled,
   create a disposable blank map at least 20 x 16 tiles, and run from the repo:

   ```powershell
   .\.venv\Scripts\python.exe .\phase1_smoke.py --output-dir <new-empty-directory>
   ```

   The script leaves the saved ten-tree sample open after checking the mixed scene.
4. Restart Codex's MCP server or Codex to load the revised Python tool schema.
   The mod source is already in Dungeondraft's configured development directory;
   no manual copying is required on this PC.

Phase 1 ends here for review. Phase 2 adds bounded native batches and job control.
