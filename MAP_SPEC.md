# Structured maps: map_spec.v1

The specification is this project's intermediate format, not a native
Dungeondraft or Foundry file. [JSON schema](schemas/map_spec.v1.schema.json)
and [forest ambush](examples/forest-ambush.json) /
[island coast](examples/island-rescue.json) examples are committed.
`get_map_spec_schema` exposes the same strict schema to any MCP client.

## Workflow

1. Load a blank native map matching `size.width` / `size.height`.
2. Call `plan_battlemap(spec)`. Inspect `valid`, errors, warnings, counts,
   resolved artwork, route validation and semantic generated positions.
   `include_operations=true` returns the complete low-level dry run.
3. Call `apply_battlemap(plan_id)`. One native batch applies the plan and
   returns a per-feature semantic/native-ID manifest. Matching retries reuse
   its retained job. For async application use `wait=false`, inspect `get_batch`,
   then call `apply_battlemap` with the same plan ID to collect the manifest.
4. Inspect the render, validate routes, and save with `save_battlemap_project`.
   Use named revisions for targeted repairs.

`get_battlemap(plan_id)` returns the retained plan and last manifest. Up to 64
plans are retained in one MCP process; no silent eviction. A server restart
loses that cache. Plans are bound to the same editor instance, level and catalog.
Changed map content before first application requires another dry run. Leave
native UI unchanged between planning and applying: element/dirty-state checks
cannot detect every manual terrain change. Cross-instance replay is rejected.
Cancelled/failed batch keys remain terminal; they are never silently reapplied.

## Coordinates and schema

All spec positions, polygon points, widths, radii, margin and spacing use
**tiles**. The adapter converts at **256 woxels per tile**. Native low-level
tools continue to use woxels. Output `ppi` is pixels per exported tile and has
no effect on geometry. `pixelsPerGrid`, unknown fields, wrong versions/units,
nonfinite numbers and boolean numeric inputs are rejected.

Required root fields: `schema_version="map_spec.v1"`, `size`, `seed`, `features`.
Optional biome/theme are semantic labels. Every feature has a unique stable
`id` and optional independent `gameplay` (movement cost, cover,
blocks_movement, notes). Entry/spawn positions are reserved tactical zones;
their metadata does not place VTT tokens.

| Feature | Rendering / meaning |
| --- | --- |
| road | Smoothed polyline buffered to width, clipped and painted as terrain |
| stream | Buffered native water polygon; shallow is passable, deep blocks movement |
| water_region | Native water polygon for coasts/lakes; deep blocks movement except declared crossings; water remains under separately placed bridge/deck floors |
| terrain_region | Simple polygon, clipped to map; material and gameplay independent |
| forest | Bounded seeded Poisson-disk sampling; exact count or validation error |
| cover / obstacle / hazard | Object artwork; separate mechanical radius and gameplay |
| clear_area | Reserved polygon; `purpose=crossing` declares passable space in deep water; streams cut a causeway, water regions keep water under a separately placed deck |
| entry / spawn | Reserved circular zone and encounter anchor, no visual token |
| building / room | Wall boundary, explicit door gaps, terrain floor |

`encounter.required_routes` contains entry/spawn ID pairs. Connectivity uses
free-space polygon components after enlarging blockers by `agent_radius`.
It proves geometric connectivity for that footprint, not encounter balance,
line of sight or movement cost optimality. Forest trunks use a 0.2-tile blocking
radius; artwork spacing uses a larger nominal footprint. Water depth is semantic,
not inferred from the native water color.

## Determinism and assets

`server/dungeondraft_mcp/layout/spec.py` owns the strict models;
`layout.py` owns pure geometry/generation; `planning.py` adapts live discovery and
batch submission. Seeded feature RNGs derive from seed, feature ID and generator
version. Plans record resolved asset metadata, catalog version, generator version
and Shapely/GEOS versions. Identical inputs/runtime produce identical layouts.

Asset queries prefer exact terrain basenames. Explicit paths/overrides must
exist. Missing named oak/boulder/stone queries have explicit fallback rules;
`mud` falls back to swamp with a warning on the default catalog. Gameplay
movement/cover metadata remains unchanged by artwork selection. No texture
footprint means placement validation fails rather than guessing.

## Bounds and limits

Size is 8..128 tiles per axis. At most 64 features, 400 trees per forest,
500 generated operations, 16 terrain edits and 16 water edits per job.
Rendered polygons have at most 32 vertices and no holes; simplify a feature
when clipping produces unsupported detail. Four terrain materials are supported
by this adapter. A forest that cannot fit its exact count returns an error with
the achieved count and bounded attempts; it does not quietly reduce density.

Whole-map terrain/water/building plans require no existing elements or water.
For additive forest/props, set `base_material=null`. Existing manual element and
water bounds are conservatively reserved. Walkable pattern floors, explicitly
open ordinary portals, decorative lights and text are excluded from movement/
collision bounds. Shared terrain slots make arbitrary
additive painting unsafe without ownership, so that case is rejected explicitly.
Rooms use terrain floors and open wall gaps, not mounted door portals, roofs or
pattern floors. These remain available through existing low-level tools.

Changes to existing field meaning require a new explicit version. Adding
`water_region` preserves existing field meaning. Unsupported versions are
rejected. Future migrations must be intentional adapters with tests; this fork
does not silently accept old schemas or guess changed coordinate units.

## Optional VTT files

After application or project restoration, `export_battlemap` uses the native
current geometry plus semantic blockers to write Universal VTT, PNG, Foundry 14
scene/import macro and independent encounter metadata. Coordinates remain tiles
in metadata; scene coordinates are tiles times export PPI. Requires a new
absolute directory, a relative Foundry PNG path and a single-level native map.
See [PHASE5_REVIEW.md](PHASE5_REVIEW.md) for limits and import review. Successful
file export does not claim an actual Foundry 14 import.

## Scale and editable layers

The island example uses 5 feet per tile, a 35x35 (175x175 ft) coast, 10-15 ft
approaches and a 4 ft diameter connectivity agent. Gameplay height, difficult
terrain and cover are semantic rules, not a 3D simulation or automatic VTT rules.

Terrain and native water are separate components on the ground floor. Pattern
floors and object drawing layers keep huts, decking and furnishings editable.
A native `add_level` creates an independent floor for the tower's upper deck;
this is currently a low-level edit, not a multi-floor map specification. The
example specification contains the procedural core, not its later furnishings.
Shared water/building geometry revision is intentionally excluded.
