# Roadmap: planned, repeatable Dungeondraft maps

## Goal

Let Codex turn a short encounter request into a saved, editable Dungeondraft map with a few meaningful MCP calls. Code should handle asset lookup, coordinates, repeated placement, collision checks, rendering, and verification. The map specification is our own format; it is not a Dungeondraft or Foundry format.

Target workflow:

```text
request -> structured map specification -> deterministic layout
        -> validated edit plan -> batched Dungeondraft bridge calls
        -> native map save + PNG preview -> targeted corrections
        -> optional VTT export
```

The source of truth is the specification plus its seed and asset selections. Keep semantic features (cover, difficult terrain, entry points, spawn zones) separate from their visual assets. Store enough information to regenerate or revise the map without guessing from a screenshot.

## What the MCP can do today

The Python MCP server exposes **54 tools** in the Phase 3 source. They operate after Dungeondraft has loaded a map and started its mod scripts:

| Area | Existing tools |
| --- | --- |
| Connection and discovery | `ping`, `get_status`, `get_map_info`, `get_capabilities`, `list_asset_categories`, `list_assets`, `list_asset_metadata`, `refresh_asset_catalog`, `list_elements`, `get_element`, `list_levels` |
| Structured planning | `get_map_spec_schema`, `plan_battlemap`, `apply_battlemap`, `get_battlemap` |
| Native water | `draw_water`, `get_water` |
| Native batching | `apply_batch`, `get_batch`, `cancel_batch` |
| Native maps | `open_map`, `save_map` |
| Map elements | `place_object`, `draw_wall`, `draw_path`, `add_light`, `add_portal`, `add_roof`, `place_pattern`, `build_room`, `add_text` |
| Terrain and caves | `set_terrain_slot`, `fill_terrain`, `fill_region`, `paint_terrain`, `paint_path`, `dig_cave`, `clear_caves` |
| Changes and levels | `move_element`, `modify_object`, `duplicate_object`, `delete_element`, `add_level`, `set_level`, `select_elements`, `clear_selection`, `undo`, `redo` |
| View and output | `get_camera`, `set_camera`, `focus_element`, `fit_elements`, `screenshot`, `export_map` |

These tools cover tree placement and discovery, terrain paths, walls, rooms, previews, native map save/reopen, paged inspection, and basic asset metadata. A scripted client can call low-level tools repeatedly, but the model still has to coordinate each call; native batching is implemented in Phase 2. Asset tags are inferred from filenames, not curated suitability data. Element bounds are visual geometry, not collision semantics. The bridge's undo stack is independent of Dungeondraft's UI history and does not cover every command. See [PROTOCOL.md](PROTOCOL.md) for exact behavior.

## Design rules

1. **Use one coordinate convention.** Specifications use tile/grid coordinates; the adapter converts to Dungeondraft world coordinates at **256 woxels per tile**. Export PPI and a VTT's pixels per grid are separate output settings. Reject ambiguous `pixelsPerGrid` input.
2. **Make generation deterministic.** A fixed spec, seed, asset catalog version, and generator version must produce the same feature positions and choices.
3. **Preserve authorship and identity.** Give each planned feature a stable semantic ID. Track the Dungeondraft IDs created for it. Revise only generated content that the plan owns; never clear unrelated user content by default.
4. **Validate before editing.** Check spec schema, map bounds, asset availability, required clearances, and route connectivity. Return a dry-run plan and warnings before applying.
5. **Report partial progress.** Batch responses must identify successes, failures, generated IDs, and the failed operation. A timeout or failed command must not silently cause duplicates on retry.
6. **Keep low-level tools.** They remain useful for inspection, targeted fixes, and debugging; the planner should normally call higher-level tools.

## Phase 0 — Establish a live baseline

- [x] Run a live smoke test on Dungeondraft 1.2.0.1 for asset discovery, terrain fill, terrain path, object placement, screenshot, and PNG export. See [PHASE0_BASELINE.md](PHASE0_BASELINE.md).
- [x] Save/reopen the native sample through MCP after reloading the Phase 1 bridge. The 2026-10-01 live retest retained exactly ten trees in the native JSON and after MCP reopen; Phase 1 clears their `preview` marker.
- [x] Measure 10, 50, and 200 object placements with one persistent MCP session, and compare with separate MCP sessions. This establishes the current per-object cost; repeat after Phase 2 batch support is implemented.
- [x] Confirm asset paths and object IDs after save/reopen. IDs 0–9 and their oak asset paths matched before and after the live reopen.
- [x] Update [API_COMPATIBILITY.md](API_COMPATIBILITY.md) with runtime findings.

**Exit:** A repeatable sample containing grass, a center dirt path, and exactly ten trees was produced, saved, reopened, and counted without Computer Use. The native file contained ten objects and the PNG showed the intended layout. Phase 0 was reviewed before Phase 1 began.

## Phase 1 — Complete the editor lifecycle and inspection API

- [x] Implement `open_map`, `save_map`, and `get_map_info`; verify the installed 1.2.0.1 editor can save and reopen a map through MCP.
- [REJECTED] `create_map` through the in-editor bridge. The internal `Master.CreateNewMap` call raised editor exceptions (`SelectTool.EnableTransformBox`, `Objects.RemoveFromSearchTable`, duplicate `DESIGN` toolbar) and left the bridge disconnected. The published modding API has no supported new-map method. The unsafe command was removed; native-file generation and UI simulation are not planned.
- [x] Make save destinations and overwrite explicit; wait for a complete native JSON file. **[PLAN CHANGED]** Save preserves the scene; reload verification is a separate action after the native save notification finishes. The live native file retained ten trees, and MCP reopen preserved their IDs and assets.
- [x] Implement paginated `list_elements` and descriptors with geometry, bounds, layer, and asset where exposed. All eight kinds passed live save/reopen, ID/asset checks, pagination and individual lookup. Pattern shapes are counted independently of layers; free and mounted portals are distinguished; free portal and light bounds use world coordinates.
- [x] Verify UI New Map and Reload Mods keep the bridge reachable. Fixed the reproducible port 8787 conflict by retiring the previous native listener using an Engine-owned instance ID. Two consecutive UI New Map switches and Reload Mods passed.
- [x] Add a cached asset catalog with path, category, texture dimensions, nominal object footprint, and filename-derived tags. Refresh it after asset-pack changes. Curated semantic suitability belongs to Phase 3 asset selection rules.
- [x] Add `get_capabilities` with protocol, Godot engine version, commands, active mods, and catalog version. Live asset lookup and metadata passed; the capability set is checked by the Phase 1 runner. The installed Dungeondraft product version is not exposed by the documented modding API; the manifest states the minimum supported version.
- [PLAN CHANGED] Create each new blank map manually in Dungeondraft. The official [scripting lifecycle](https://megasploot.github.io/DungeondraftModdingAPI/Scripting/) starts tool mods only after a map loads, and the tested internal new-map call is unsafe from an active mod. The bridge can reopen saved maps through MCP. The initial decision is revisited in the lifecycle investigation below; no new creation command has been accepted.

**Exit achieved (2026-10-02):** After a manual blank-map load, a client can discover assets, inspect content, edit, save a native file, and reopen it through MCP. Protocol 18 passed the expanded `phase1_smoke.py` check: ten-tree path sample, PNG export, mixed scene with every descriptor kind and two separate floor shapes, native durability, pagination, and exact IDs/assets. A fresh MCP stdio client exposed 45 tools and completed live queries. See [PHASE1_REVIEW.md](PHASE1_REVIEW.md) for proof and review steps.

**Editor limitation:** UI New Map from the populated sample also logged native `Prop._ExitTree` / `World.get_Level` exceptions with every mod disabled. An intermittent Mono startup fatal error occurred with mods disabled too. These remain Dungeondraft runtime issues; this project will not patch its executable. Start a fresh editor session for new blank maps after native exceptions. MCP `open_map` and `save_map` passed the automated workflow.

## Phase 1 follow-up — Native map creation investigation

The user proposed external process lifecycle tools. Inspection found that native
New Map resets the editor before creating a replacement map; the rejected direct
call did not. See [MAP_LIFECYCLE_INVESTIGATION.md](MAP_LIFECYCLE_INVESTIGATION.md).

- [x] Inspect installed startup argument handling and native map creation/reset flow.
- [x] Document standard stdio setup for other AI agents and require README coverage for future configuration changes.
- [x] Verify GDScript lifecycle reachability: native reset/create methods are visible, but the pending managed request is neither an exposed property nor a registered Godot class. No clean pending-request entry point found.
- [x] Test the disposable private New-dialog prototype: 24x18 and 20x16 blank creation, validation, reconnection, editing and saving passed with a clean console. Populated replacement functionally completed but raised native exceptions; see [CREATION_REVIEW.md](CREATION_REVIEW.md).
- [REJECTED] Publish private New-dialog creation. Native `World.get_Level` / `Prop._ExitTree` cleanup and disposed `Toolset.Shrink` errors fail acceptance despite reconnection. Do not patch editor internals or pre-delete content to hide this failure.
- [PLAN CHANGED] Resume after the clean baseline, complete the tests above, then remove the probe permanently from the active mod directory. Protocol 18 and the 45-tool production surface remain unchanged.
- [x] Assess external startup separately: `scripts/Start-Dungeondraft.ps1` can copy and open a prepared native map, capture logs and refuse a second editor. Fresh 20x16 startup and bridge readiness passed; one preceding attempt hit the known intermittent Mono fatal. README documents the generic shell workflow; no new client configuration is required.
- [REJECTED] Arbitrary blank dimensions through Windows startup arguments: the inspected application only handles an existing map path. Prepared templates keep their saved dimensions.

- [x] Correct selection activation and native object undo/redo; focused rendered regression and the 15-check bridge runner passed.
- [x] **[PLAN CHANGED]** Remove automatic post-save reopening, which can destroy native save UI widgets before their delayed callback completes. Keep JSON validation; reload verification is a separate step.
- [x] Confirm the public native save signal, focused history/render regression and fresh 45-tool MCP client save pass; the user confirmed no new console errors. The one-argument `Editor.SaveMap(false)` route failed silently and was replaced by the published `saveButton` signal.
- [x] Correct `bridge_dirty` with a verified save checkpoint independent of undo history. Protocol 19 / package 0.2.3 passed live save/undo/redo, irreversible deletion, edits after a save request, stale token rejection and a fresh 45-tool MCP client save. Console clean; see `save_checkpoint_regression.py`.

Creation investigation is complete: prepare new sizes manually, or start a
fresh editor with a copy of a prepared native template. Continue the roadmap
after checking live readiness. The user now authorizes autonomous test launches,
closing disposable test sessions, and Computer Use when needed for test setup.
Map construction and discovery continue through the bridge.

## Phase 2 — Batch edits in the GDScript bridge

- [x] Add a versioned `apply_batch` command taking a bounded list of validated low-level operations. Start with objects, paths, terrain, walls, lights, and portals; extend only where needed.
- [x] Preflight the whole batch: command names, required fields, coordinates, map bounds, asset paths, and per-operation limits. Return structured validation errors before any edit.
- [x] Execute large batches over successive editor frames to keep Dungeondraft responsive. Expose `job_id`, progress, completion, and cancellation; cap work per frame and request size.
- [x] Return per-operation IDs and status. Add a caller-supplied idempotency key or job lookup so retries cannot duplicate trees after an uncertain timeout.
- [x] Define an atomicity policy. Prefer a prevalidated plan plus rollback of completed reversible edits on failure; explicitly report irreversible operations and partial application if full rollback is impossible.
- [x] Add performance and crash tests for 10/50/200 object batches and mixed terrain/path/object batches. Keep the TCP protocol responsive during work.

**Exit:** One MCP request can place 50 planned trees around a road, returns all created IDs, and can be safely checked or retried.

**Exit achieved (2026-10-02):** Protocol 20 / package 0.3.0 passed native
10/50/200 jobs, idempotent replay/conflict rejection, concurrent edit rejection,
responsive queries, object and mixed cancellation, identical terrain rollback
PNG, native saving, checkpoint regression, and a fresh 48-tool stdio client.
Console clean. See [PHASE2_REVIEW.md](PHASE2_REVIEW.md).

**[PLAN CHANGED]** Portals are initially free-standing only. Mounted portal
rollback also mutates wall membership and requires its own verification before
being added. The batch does not lock native UI: `SuppressTool` stops mod updates.
MCP mutations are guarded; leave the editor UI unchanged during execution.

## Phase 3 — Structured specification and procedural layout

- [x] Define a versioned JSON schema (`map_spec.v1`) with size, grid units, seed, biome/theme, features, encounter zones, output settings, and optional asset overrides. Provide clear validation errors and a migration strategy for later schema versions.
- [x] Define semantic feature types for road, stream, terrain region, forest, building/room, cover, obstacle, hazard, entry, spawn, and clear area. Separate gameplay metadata from visual rendering parameters.
- [x] Implement a pure Python layout package that produces a deterministic, inspectable edit plan. Keep this logic outside GDScript; the bridge should execute edits, not reason about encounters.
- [x] Add bounded Poisson-disk placement for trees and rocks; spline or smoothed polyline generation for roads/streams; polygon clipping and margin checks for regions. Introduce noise only where it improves a specified visual result.
- [x] Enforce no-overlap zones, map margins, minimum spacing, and road/door/entry clearances. Validate that required routes remain connected after obstacles are placed.
- [x] Add asset selection rules with explicit fallback and warnings when a named material or biome asset is unavailable.
- [x] Expose `plan_battlemap(spec)` as a dry run and `apply_battlemap(plan_id or spec)` as the high-level edit action. Return feature IDs, warnings, counts, and a manifest that maps semantic IDs to Dungeondraft IDs.
- [PLAN CHANGED] Use the same validated feature schema for forest/road edits; do not add overlapping `add_forest` / `create_road` tool surfaces. Named-feature revision follows in Phase 4.

**Exit:** A fixed forest-ambush spec and seed produce the same road, stream, forest, cover, and clear encounter spaces on repeated runs; the model makes a handful of high-level calls rather than placing each prop.

**Exit achieved (2026-10-02):** Protocol 21 / package 0.4.0 passed nine
pure-layout tests and a fresh 54-tool stdio client. The forest ambush dry run
was repeatable, rejected changed map context, then applied 50 trees, two cover
boulders, road, native stream and muddy region in one job. Replay reused IDs;
native saving retained objects and water. Console clean; see
[PHASE3_REVIEW.md](PHASE3_REVIEW.md).

**[PLAN CHANGED]** Noise is omitted until a feature specifies a useful effect.
Current variation comes from seeded placement/rotation and artwork. Regions use
polygon intersection; roads/streams use a smoothed polyline and buffered geometry.
Water and polygon terrain batching were added using native public APIs.
Building floors use terrain rather than non-reversible floor-pattern batches.

## Phase 4 — Preview, validation, and targeted revision

- [ ] Add `render_preview` that frames the generated content and returns a reasonably sized image plus plan metadata. Retain full-resolution `export_map` for final output.
- [ ] Add structural checks for counts, assets, bounds, spacing, accessible routes, stream crossings, and semantic requirements. Report each finding with feature IDs and coordinates.
- [ ] Keep visual review as a separate step: inspect the rendered image for clipping, readability, and asset mismatch, then express changes as targeted feature revisions. Do not claim pixel analysis proves gameplay reachability.
- [ ] Implement `revise_battlemap` as a diff against the stored manifest: move/retexture/regenerate selected features, preserve unrelated manual edits, preview, and save again.
- [ ] Save the spec, seed, resolved asset catalog, generated-ID manifest, validation report, native map, and preview together in a reproducible project folder.

**Exit:** A failed placement or an ugly/blocked road can be corrected by changing named features and reapplying a small diff, without rebuilding the whole map.

## Phase 5 — Foundry VTT export (separate integration)

- [ ] Choose the target Foundry version and supported wall/light/scene schema when implementation begins; do not hardcode an unverified current format.
- [ ] Export the battlemap image plus grid size, scene dimensions, walls, doors, lights, and optional encounter metadata from the semantic specification and final Dungeondraft geometry.
- [ ] Transform coordinates from Dungeondraft woxels to exported image pixels and Foundry scene coordinates; test scale and alignment on known landmarks.
- [ ] Keep Foundry export optional. First deliver files for import; add direct Foundry API integration only if there is a clear workflow for credentials, version handling, and verification.

**Exit:** An imported scene aligns its grid, walls, doors, and lights with the rendered map, and semantic encounter data remains available independently of the image.

## First implementation slice

The immediate proof is **MCP generation of the ten-tree path sample on a manually created blank map**. Phase 1 provides save/reopen and inspection; Phase 2 adds bounded native batching. The `phase1_smoke.py` runner verifies native save/reopen, exact tree IDs/assets, pagination, and PNG export before Phase 1 is accepted.
