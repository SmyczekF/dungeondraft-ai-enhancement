# Phase 1 review: native map save/open and inspection

## Current follow-up status (2026-10-02)

**Save/history correction accepted:** the public native save-button signal,
focused rendered history regression and fresh MCP client save passed. The user
confirmed no new console errors. Save validates native JSON and keeps the editor
scene and undo history; it does not reopen automatically. There are still 45 tools.

**Creation decision:** the private prototype was tested and rejected: blank
switches passed, but populated native replacement raised cleanup/disposed-object
exceptions. It is removed. A Windows launcher opens prepared native templates;
see [CREATION_REVIEW.md](CREATION_REVIEW.md). Native startup failures remain
intermittent and have not been attributed to a root cause.
`bridge_dirty` can remain true after a verified save and needs a save-checkpoint
fix; do not use it alone as proof that changes are unsaved.

Latest review artifacts:
`C:\Users\smycz\Documents\ChatGPT\Dungeondraft\history-regression-native-save-signal-2026-10-02`.
Inspect `report.json` and the before/undone/after PNGs. The after image exactly
matches the before image. `cleaned.dungeondraft_map` contains no elements and
remains open. The entries below retain the earlier test history and limitations.


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

## Earlier live verification on 2026-10-02

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

Phase 1 follow-up ends here for review. Phase 2 adds bounded native batches and job control.

## Follow-up regression verification (2026-10-02)

The earlier MCP PASS results did not prove a clean native console. Subsequent
user console reports exposed selection initialization and object undo/redo
bugs. These are fixed in the bridge using native tool activation and native
object serialization/loading; they were not solved by listener ownership.

On a fresh user-started session, the focused `history_regression.py` verified
three object undo/redo cycles, exact ID/asset/transform/bounds, duplicate redo,
and deletion of restored selected objects. The exported PNG after redo was
byte-identical to the original; the undone image differed. The existing bridge
runner then passed 15 checks and cleaned up all six of its elements.

The user subsequently reported one boolean and two color native pointer errors.
Inspection traced a matching sequence to Dungeondraft's delayed save UI callback;
immediate automatic reopen was removed from `save_map`. Saving now validates the
file and preserves the current bridge instance. Console confirmation is pending;
this follow-up is **not accepted as console-clean yet**.

Focused artifacts before the save-contract change:
`C:\Users\smycz\Documents\ChatGPT\Dungeondraft\history-regression-2026-10-02-absolute`.
The revised live save is `save-only-2026-10-02.dungeondraft_map` in that workspace.

Review steps:

1. Open a fresh disposable blank map, then run
   `.\.venv\Scripts\python.exe .\history_regression.py --output-dir <new-directory>`.
   Inspect its PNGs and **check the Dungeondraft console** before accepting PASS.
2. Run `phase1_smoke.py` for mixed-scene reload verification. It now pauses
   before each immediate post-save reopen; wait for the save notification to
   disappear and review the console before pressing Enter.
3. Restart the client's MCP process to load the changed `save_map` schema.
   There are still 45 tools and no new `config.toml` requirements.

The private New dialog creation route is an authorized disposable experiment,
not a supported creation API. See the lifecycle investigation for its status.

## Current acceptance state after the fresh-start failure

The user's fresh manual map-creation attempt reported a native string-array
bounds fatal error before the agent ran the creation experiment. The exact
crash stage and full console trace remain pending. The temporary probe has
been removed; the active mod now contains only the committed bridge script.
Do not treat Phase 1's follow-up or the creation prototype as accepted.
First repeat manual first-map creation with this baseline. If it fails,
repeat from a fresh process with MCP disabled to isolate the cause.

Reload Mods only updates already loaded script code while preserving state;
it does not rerun startup or discover new scripts. A new startup probe requires
a full application restart by the user. No application restart or Computer Use
was performed by the agent during this crash investigation.

The subsequent run with the temporary probe removed failed with native Mono
`!klass`, a symptom also captured in the earlier no-mod control. A new fresh
console/no-mod manual first-map test is pending. The local mod configuration
has been backed up and temporarily disabled for that test; restore it afterward
as described in the lifecycle investigation. Acceptance remains pending.

The fresh-console/no-mod control subsequently succeeded with no errors reported
by the user. A matching fresh-console/MCP-enabled comparison is still needed;
one control pass does not attribute the crash or complete acceptance. Wait for
the user to close both programs before restoring the original active-mod setting.


The matching fresh-console/MCP-enabled startup then passed. On the fresh 35 x
20 map, selection began with no active tool and activated successfully; native
object history, duplicate cleanup and rendered equality passed with a clean
console reported by the user. The regression's save gate failed because
`Editor.SaveMap(false)` wrote no file within 60 seconds, without reporting a
console error. A public save-button signal entry point is staged for manual
handler reload and live validation. The regression is still incomplete overall.


The staged public save-button signal passed the next fresh-session test.
The full focused regression and MCP client save passed, and the user confirmed
the native console was clean. See the current-status section above for artifacts
and the remaining dirty-reporting and creation tasks.
