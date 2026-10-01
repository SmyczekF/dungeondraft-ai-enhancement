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

The Python MCP server exposes **39 tools**. They operate on a map already open in a running Dungeondraft instance:

| Area | Existing tools |
| --- | --- |
| Connection and discovery | `ping`, `get_status`, `list_asset_categories`, `list_assets`, `list_elements`, `get_element`, `list_levels` |
| Map elements | `place_object`, `draw_wall`, `draw_path`, `add_light`, `add_portal`, `add_roof`, `place_pattern`, `build_room`, `add_text` |
| Terrain and caves | `set_terrain_slot`, `fill_terrain`, `fill_region`, `paint_terrain`, `paint_path`, `dig_cave`, `clear_caves` |
| Changes and levels | `move_element`, `modify_object`, `duplicate_object`, `delete_element`, `add_level`, `set_level`, `select_elements`, `clear_selection`, `undo`, `redo` |
| View and output | `get_camera`, `set_camera`, `focus_element`, `fit_elements`, `screenshot`, `export_map` |

These tools already cover tree placement and discovery, terrain paths, walls, rooms, and previews. A single scripted MCP client can call them repeatedly without mouse input, but the model still has to coordinate each call. `export_map` returns a PNG image; it does **not** save a native `.dungeondraft_map` file. There is no MCP command to create/open/save a map or apply a batch of objects. `list_assets` gives paths but no footprint, tags, or suitability information. `list_elements` has a limit and descriptors do not provide full geometry for reliable collision checks. The bridge's undo stack is independent of Dungeondraft's UI history and does not cover every command. See [PROTOCOL.md](PROTOCOL.md) for exact command behavior.

## Design rules

1. **Use one coordinate convention.** Specifications use tile/grid coordinates; the adapter converts to Dungeondraft world coordinates at **256 woxels per tile**. Export PPI and a VTT's pixels per grid are separate output settings. Reject ambiguous `pixelsPerGrid` input.
2. **Make generation deterministic.** A fixed spec, seed, asset catalog version, and generator version must produce the same feature positions and choices.
3. **Preserve authorship and identity.** Give each planned feature a stable semantic ID. Track the Dungeondraft IDs created for it. Revise only generated content that the plan owns; never clear unrelated user content by default.
4. **Validate before editing.** Check spec schema, map bounds, asset availability, required clearances, and route connectivity. Return a dry-run plan and warnings before applying.
5. **Report partial progress.** Batch responses must identify successes, failures, generated IDs, and the failed operation. A timeout or failed command must not silently cause duplicates on retry.
6. **Keep low-level tools.** They remain useful for inspection, targeted fixes, and debugging; the planner should normally call higher-level tools.

## Phase 0 — Establish a live baseline

- [ ] Run a disposable-map smoke test on Dungeondraft 1.2.0.1 for asset discovery, terrain fill, terrain path, object placement, screenshot, PNG export, and reopening the saved native map.
- [ ] Record actual output and latency for 10, 50, and 200 object placements; compare individual calls with one persistent client connection. This sets a useful batch size rather than guessing.
- [ ] Confirm that asset paths and object IDs survive save/reopen, and document any tool behavior that changes after reload.
- [ ] Update [API_COMPATIBILITY.md](API_COMPATIBILITY.md) with runtime findings. The current file is primarily an API signature review.

**Exit:** A repeatable sample containing a grass field, a center dirt path, and exactly ten trees can be produced, saved, reopened, and counted without Computer Use.

## Phase 1 — Complete the editor lifecycle and inspection API

- [ ] Add `create_map`, `open_map`, `save_map`, and `get_map_info` through the bridge after verifying the relevant Dungeondraft 1.2.0.1 API calls in a disposable session. Include dimensions, active level, native path, and dirty state where available.
- [ ] Make save operations explicit about destination, overwrite behavior, completion, and errors. Verify that the file exists and reopens cleanly before reporting success.
- [ ] Add paginated `list_elements` and geometry/bounds queries for paths, walls, objects, portals, roofs, and patterns. Include layer and asset data needed for collision and audit.
- [ ] Add asset metadata/catalog support: category, path, dimensions/footprint where available, and curated semantic tags. Cache the catalog; invalidate it when mods or asset packs change.
- [ ] Add `get_capabilities` with bridge protocol, Dungeondraft version, available commands, and asset catalog version so a planner can preflight rather than infer support.

**Exit:** A client can create or open a map, discover usable tree and path assets, inspect existing content, make edits, save the native file, and reopen it using MCP alone.

## Phase 2 — Batch edits in the GDScript bridge

- [ ] Add a versioned `apply_batch` command taking a bounded list of validated low-level operations. Start with objects, paths, terrain, walls, lights, and portals; extend only where needed.
- [ ] Preflight the whole batch: command names, required fields, coordinates, map bounds, asset paths, and per-operation limits. Return structured validation errors before any edit.
- [ ] Execute large batches over successive editor frames to keep Dungeondraft responsive. Expose `job_id`, progress, completion, and cancellation; cap work per frame and request size.
- [ ] Return per-operation IDs and status. Add a caller-supplied idempotency key or job lookup so retries cannot duplicate trees after an uncertain timeout.
- [ ] Define an atomicity policy. Prefer a prevalidated plan plus rollback of completed reversible edits on failure; explicitly report irreversible operations and partial application if full rollback is impossible.
- [ ] Add performance and crash tests for 10/50/200 object batches and mixed terrain/path/object batches. Keep the TCP protocol responsive during work.

**Exit:** One MCP request can place 50 planned trees around a road, returns all created IDs, and can be safely checked or retried.

## Phase 3 — Structured specification and procedural layout

- [ ] Define a versioned JSON schema (`map_spec.v1`) with size, grid units, seed, biome/theme, features, encounter zones, output settings, and optional asset overrides. Provide clear validation errors and a migration strategy for later schema versions.
- [ ] Define semantic feature types for road, stream, terrain region, forest, building/room, cover, obstacle, hazard, entry, spawn, and clear area. Separate gameplay metadata from visual rendering parameters.
- [ ] Implement a pure Python layout package that produces a deterministic, inspectable edit plan. Keep this logic outside GDScript; the bridge should execute edits, not reason about encounters.
- [ ] Add bounded Poisson-disk placement for trees and rocks; spline or smoothed polyline generation for roads/streams; polygon clipping and margin checks for regions. Introduce noise only where it improves a specified visual result.
- [ ] Enforce no-overlap zones, map margins, minimum spacing, and road/door/entry clearances. Validate that required routes remain connected after obstacles are placed.
- [ ] Add asset selection rules with explicit fallback and warnings when a named material or biome asset is unavailable.
- [ ] Expose `plan_battlemap(spec)` as a dry run and `apply_battlemap(plan_id or spec)` as the high-level edit action. Return feature IDs, warnings, counts, and a manifest that maps semantic IDs to Dungeondraft IDs.
- [ ] Add focused helpers only for common iterative edits, such as `add_forest` or `create_road`; avoid multiple overlapping APIs for the same operation.

**Exit:** A fixed forest-ambush spec and seed produce the same road, stream, forest, cover, and clear encounter spaces on repeated runs; the model makes a handful of high-level calls rather than placing each prop.

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

The first coding milestone should be narrow: **MCP-only creation of the ten-tree path sample**. Implement native map create/save, richer asset inspection where needed, and one bounded `place_objects_batch` or `apply_batch` operation. Then verify the saved map by reopening it and checking exact counts and a PNG preview. This gives us the unattended editor workflow before building the general planner or Foundry exporter.
