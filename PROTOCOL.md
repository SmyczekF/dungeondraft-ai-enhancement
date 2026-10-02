# Bridge wire protocol

A deliberately tiny protocol so both halves stay trivial to extend.

- **Transport:** TCP on `127.0.0.1:8787` (override the mod's `PORT` const and the
  server's `DD_BRIDGE_PORT` env var together).
- **Framing:** one JSON object per line, terminated by `\n`, UTF-8.
- **Model:** request/response. The MCP server opens a connection, writes one
  request line, reads one response line. The mod also tolerates multiple
  requests on a persistent connection.

## Request

```json
{ "cmd": "place_object", "asset": "objects/chair.png", "x": 100, "y": 200 }
```

- `cmd` (string, required) — the command name.
- `id` is a Dungeondraft element ID only for commands that operate on an
  existing element. It is not a request correlation ID.
- Everything else is command-specific parameters. The bridge processes each
  TCP request in order and does not echo a request correlation ID.

## Response

Success:

```json
{ "ok": true, "result": { "id": 42, "position": [100, 200] } }
```

Error:

```json
{ "ok": false, "error": "no map open" }
```

## Commands

Coordinates are **woxel** (world pixel) space; map center is in
`get_status -> map_center`. Every element is referenced by integer `id`
(== Dungeondraft `node_id`); create commands return it, query commands list it.
Protocol version 22 adds reversible object transforms/deletion in batches,
terrain ownership checksums and bounded grid-controlled exports. The unsafe new-map command remains absent. Dungeondraft
loads mod scripts after a map opens, so the title screen has no bridge.

### Read / query

| cmd | params | result |
| --- | --- | --- |
| `ping` | — | `{ pong, protocol, bridge_instance, engine }` |
| `get_status` | — | `{ map_open, level_id, level_count, map_size_woxels, map_center, counts{}, active_tool }` |
| `get_map_info` | — | `{ map_open, path, size_tiles?, size_woxels?, level_id?, level_count?, dirty, editor_dirty, bridge_dirty, saving, loading, bridge_instance }` |
| `get_capabilities` | — | `{ protocol, bridge_instance, engine, commands[], asset_catalog_version, asset_counts{}, active_mods[], batch{} }` |
| `list_asset_categories` | — | `{ categories[] }` |
| `list_assets` | `category="Objects"`, `search=""`, `offset=0`, `limit=100` | `{ category, catalog_version, total, matched, offset, limit, returned, assets[] }` |
| `list_asset_metadata` | `category="Objects"`, `search=""`, `offset=0`, `limit=100` | Same pagination; asset entries include `path`, `category`, `tags[]`, `texture_pixels?`, `nominal_footprint_woxels?` |
| `refresh_asset_catalog` | — | `{ asset_catalog_version }` |
| `list_elements` | `kind="objects"`, `offset=0`, `limit=200` | `{ kind, offset, limit, total, count, elements[] }` |
| `get_water` | — | `{ level_id, data }`; native water polygon tree/colors |
| `get_element` | `id` | element descriptor |
| `list_levels` | — | `{ current_index, current_id, levels[] }` |

`kind` ∈ `objects, walls, lights, paths, portals, roofs, patterns, texts`.
Descriptors include `id`, `kind`, `position`, `rotation`, `scale`, `asset?`,
`layer?`, `bounds?` as `[[minX,minY],[maxX,maxY]]`, and `points?` in world
woxels where the native element exposes them. Bounds are visual extents, not
guaranteed movement collision. `limit` is capped at 500 for elements and basic
asset paths, 200 for metadata. Metadata tags come from filenames only; texture
dimensions are pixels and an object's nominal unscaled footprint.

The asset catalog caches sorted paths per category. Reloading the mod resets it;
`refresh_asset_catalog` rebuilds it after asset pack changes. The catalog
version hashes paths and active mod IDs, so clients can invalidate selections.

`portals` includes **wall-mounted** portals (doors/windows), which live inside
each wall's `Portals` array rather than `level.Portals` — both status counts
and `list_elements` include them. Freestanding portals have `kind:"portal"`.
Patterns enumerate `PatternShapes.GetShapes()`, not its layer containers.
A wall portal describes as `{ id, kind:"wall_portal",
wall_id, position[x,y], normal[x,y], facing(deg), radius, closed, asset? }`
where `position` is the door's gap center and `normal` is the outward unit
vector (perpendicular to the wall, pointing out of the room). To route a road to
a door, draw to `position`; offset along `normal` by a tile or so to stop just
outside the threshold. `get_element` on a door id returns the same descriptor.
Text elements describe as `{ id, kind:"text", position[x,y], bounds?, text, size?,
color?, font? }` (a DD Text extends LineEdit, so it has no `scale`/`rotation`/
`asset` and is positioned by `rect_position`). Font name+size are applied
together via `SetFont` because `SetFontSize` alone doesn't stick on a fresh
node; default color is black.

### Native map lifecycle

| cmd | params | result |
| --- | --- | --- |
| `open_map` | absolute existing `.dungeondraft_map` `path`, `discard_current=false` | `{ requested_path }` |
| `save_map` | absolute `.dungeondraft_map` `path?`, `overwrite=false` | `{ requested_path, save_token }` |
| `confirm_save` (wire helper, not an MCP tool) | returned `save_token` | `{ bridge_dirty }` |

Create new blank maps in Dungeondraft. The internal `Master.CreateNewMap` call
raised editor exceptions when invoked by the mod and is not exposed. Opening a
saved map reloads the editor scene. For MCP-requested switches, the
bridge releases its TCP listener after acknowledging the request. On startup,
the new bridge retires any previous native listener using its Godot instance ID
stored on the Engine singleton. This survives Editor replacement and prevents
UI New Map from colliding with the previous bridge on port 8787. Reload Mods
also passed live testing. A bind failure caused by another process is logged
without a modal alert. The Python
`open_map` tool waits for a new `bridge_instance` and verifies the path. The Python
`save_map` waits for parseable native JSON without replacing the scene.
To check native reload durability, call `open_map` separately after the save
notification disappears and compare IDs/assets/counts. Immediate reopening
can destroy widgets still referenced by Dungeondraft's delayed save callback.
Automatic reopen and its `verify_reopen` parameter were removed rather than
adding a hardcoded delay or depending on private UI fields. Reopen clears
bridge undo history.
Use `discard_current=true` only after saving any work to retain. `dirty`
combines Dungeondraft's editor flag with edits tracked by the bridge.
`bridge_dirty` compares the current undo branch and non-recorded edit revision
with the last verified save checkpoint. The Python save tool validates native
JSON, then confirms the returned token. Edits arriving after the save request
stay dirty; stale tokens are rejected. Undo/redo can return to a saved branch
without clearing history. Non-recorded edits remain conservatively dirty until
saved. Manual UI saves do not confirm the bridge checkpoint.

Saving enters the editor's normal managed workflow through the published
`Editor.saveButton` and its native `pressed` signal. This avoids the unsupported
GDScript-to-C# Action delegate boundary without private fields or input simulation.

Dungeondraft 1.2.0.1 logged native `Prop._ExitTree` / `World.get_Level` exceptions
when UI New Map replaced the populated sample, including with all mods disabled.
The new blank map appeared, but a fresh editor session is recommended after
native exceptions. This is separate from the fixed bridge listener conflict.

### Create (each returns `{ id, ... }`)

| cmd | params |
| --- | --- |
| `place_object` | `asset`, `x?`, `y?`, `scale=1`, `rotation=0`, `sorting=0`, `color?` |
| `draw_wall` | `points[[x,y]...]`, `asset?`, `loop=false`, `shadow=true`, `type=0`, `joint=1`, `color?` |
| `draw_path` | `points[[x,y]...]`, `asset`, `layer=0`, `sorting=0`, `smoothness?`, `width?` |
| `add_light` | `x?`, `y?`, `color?`, `energy=1`, `range=1`, `shadows=true`, `asset?` |
| `add_portal` | `asset`, `x?`, `y?`, `closed=false`, `radius=64`, `mount="wall"`, `snap_max=256`, `flip=false`, `fallback_free=true`, `rotation=0` |
| `add_roof` | `points[[x,y]...]` (the RIDGE line), `asset`, `width=256`, `type=0`, `sorting=0` |
| `add_text` | `text`, `x?`, `y?`, `size?`, `color?`, `font?` |
| `place_pattern` | `asset`, `rect=[x,y,w,h]` **or** `points=[[x,y]...]`, `category="Patterns"`, `color?`, `rotation?`, `z=-100` |
| `build_room` | `rect=[x,y,w,h]` **or** `points=[[x,y]...]`, `wall_asset?`, `floor="pattern"\|"terrain"\|"none"`, `floor_asset?`, `floor_category="Simple Tiles"`, `floor_color?`, `floor_slot=1`, `wall_type=0`, `wall_joint=1` → `{ wall_id, floor_id?, points }` |

### Terrain

`fill_region` rasterizes a woxel-space rectangle or polygon into the terrain
splat image, so it fills only inside the
shape (e.g. one room's floor) rather than the whole level like `fill_terrain`.
It is undo-recorded like the other terrain ops.

| cmd | params |
| --- | --- |
| `set_terrain_slot` | `asset`, `slot=0` |
| `fill_terrain` | `slot=0`, `asset?` |
| `fill_region` | `rect=[x,y,w,h]` **or** `points=[[x,y]...]`, `slot=0`, `asset?`, `rate=1` |
| `paint_terrain` | `slot=0`, `x?`, `y?`, `radius=64`, `rate=1`, `asset?` |
| `paint_path` | `points=[[x,y]...]`, `slot=0`, `radius=96`, `rate=1`, `asset?` |
| `dig_cave` | `points=[[x,y]...]` **or** `x?`,`y?`, `radius=256`, `dig=true`, `ground_color?`, `wall_color?`, `texture?` |
| `clear_caves` | — (wipes the whole cave layer back to rock) |

### Modify / delete / levels / selection

| cmd | params |
| --- | --- |
| `move_element` | `id`, `x`, `y` |
| `modify_object` | `id`, `scale?`, `rotation?`, `color?`, `shadow?` |
| `duplicate_object` | `id`, `dx=64`, `dy=0` → `{ id }` |
| `delete_element` | `id` → `{ deleted }` |
| `add_level` | `label="Level"` → `{ id, label }` |
| `set_level` | `index` |
| `select_elements` | `ids[]` |
| `clear_selection` | — |

### Capture

The caller passes the absolute `path` the mod should write the PNG to (the MCP
server uses a temp path and reads it back as an image).

| cmd | params | result |
| --- | --- | --- |
| `screenshot` | `path` | `{ path, width, height }` — window grab, synchronous |
| `export_map` | `path`, `ppi=40` | `{ path, ppi, async }` — full-map render on a background thread; poll `path` for the file |

### Camera

The editor camera is a `Camera2D` at `Global.Camera`. Its world center is the
inherited `global_position`; `zoom` is a Camera2D factor where **larger = zoomed
out** (0.5 magnifies 2×, 2.0 shows twice as much). `set_camera`/`focus_element`/
`fit_elements` pan by writing `global_position` and keep DD's bottom-bar zoom
dropdown in sync via `SetZoomOptionByRaw`. Use these before `screenshot` to
frame what you want to inspect.

| cmd | params | result |
| --- | --- | --- |
| `get_camera` | — | `{ position[x,y], zoom, viewport_size[w,h] }` |
| `set_camera` | `x?`, `y?`, `zoom?` | camera state |
| `focus_element` | `id`, `zoom?` | `{ id, focused[x,y], camera{} }` — centers on the element (any kind) |
| `fit_elements` | `ids[]`, `pad=0.15` | `{ fit, missing[], center[x,y], bounds[[minx,miny],[maxx,maxy]], camera{} }` — frames the union of the ids' world bounds |

`focus_element`/`fit_elements` use each element's **world-space bounding rect**:
`GlobalRect` for walls/paths, the Control rect for texts, a prop's `Rect`, or a
zero-size rect at the node position as a fallback. `focus_element` centers on
the rect's midpoint; `fit_elements` frames the union of all rects.

### History

The bridge keeps its **own** undo/redo stacks (it does not use Dungeondraft's
`History.CreateCustomRecord`, which was unreliable in the previously tested
build — see notes). Supported creates (`place_object`, `draw_wall`, `draw_path`,
`add_light`, `add_portal`, `add_roof`, `add_text`, `duplicate_object`),
`move_element`, `modify_object`, the four terrain paint/fill commands and native water,
`dig_cave`, and `clear_caves` push an op; a fresh recorded edit clears the redo
stack. Terrain ops snapshot the splat image before/after;
`dig_cave` and `clear_caves` snapshot the cave `BitMap` the same way.

| cmd | params | result |
| --- | --- | --- |
| `undo` | — | `{ undone, kind?, undo_depth? }` / `{ undone: false, reason }` |
| `redo` | — | `{ redone, kind?, redo_depth? }` / `{ redone: false, reason }` |

`delete_element` is **not** reversible (it frees the node). `place_pattern`,
`build_room`, `set_terrain_slot`, levels, selection, and capture commands are
not recorded. This stack is independent of the user's Ctrl+Z in Dungeondraft.

`color` accepts `"#rrggbb"` / `"rrggbb"` or `[r,g,b]` / `[r,g,b,a]` floats 0..1.
`type` for walls: 0=auto,1=manual,2=cave; for roofs: 0=gable,1=hip,2=dormer.

## Implementation notes

- **Transport** — the mod opens a `TCP_Server` inside Dungeondraft; the modding
  sandbox on Godot 3.4.2 permits it. If a future DD/Godot version locks this
  down, the fallback is a file-watch transport: the mod polls a request file via
  `File` in `update()` and writes a response file.
- **Element ids** — every element is referenced by `node_id`, force-assigned via
  `Global.World.AssignNodeID(node)` on create/list so it resolves immediately
  with `GetNodeByID` / `DeleteNodeByID`.
- **`export_map`** — `Exporter.Start(0, ppi, path)` writes asynchronously. If DD
  chunks a very large map into multiple files, the single-path read would need
  extending.
- **`undo` / `redo`** — bridge-managed stacks, not DD's history. DD 3.4.2's
  `History.CreateCustomRecord` does not record programmatic creates, invokes
  custom `undo()` inconsistently, and never round-trips `redo()`, so the bridge
  uses its own. Create ops detach/re-attach the node (remove_child / add_child,
  keeping a reference and a stable id); transform ops restore a property
  snapshot; terrain ops restore a cloned splat image.
- **`paint_terrain` / `fill_region` / `paint_path`** — all edit the splat weight
  image directly (`CloneSplatImage` → raise the target slot's channel per pixel →
  `RestoreSplat`) rather than `Terrain.Paint(...)`, which does not modify the
  splat from a mod context. `paint_terrain` uses a soft radial falloff (a single
  circular brush); `fill_region` is a hard rect/polygon. `paint_path` rasterizes
  a continuous stroke along a polyline by measuring each pixel's distance to the
  nearest segment and applying the same smoothstep falloff once — a uniform-width
  ribbon for roads/trails, with no gaps or double-painted overlaps (the reason
  stamping many `paint_terrain` dabs reads as dotty). All three are undoable.
- **terrain splat** — `splatImage` is RGBA = weights of slots 0–3; `splatImage2`
  = slots 4–7. `set_terrain_slot` / `SetTexture(tex, slot)` swap a slot's texture
  **globally** (everywhere that slot is weighted), so to texture one region you
  assign the slot once, then raise that slot's weight only inside the region
  (what `fill_region` / `paint_terrain` do).
- **`place_pattern`** — draws a tiled-floor shape via `PatternShapes.DrawRect` /
  `DrawPolygon`, then applies the texture with `PatternShape.SetOptions(tex,
  color, rotation)` (the draw call alone leaves the shape untextured). New shapes
  land in the tool's default "Layer 100" (z 100, above the Objects node at z 0),
  so to render the floor **below** objects we set `z_as_relative = false` and an
  absolute `z_index` (default `z` = -100, between FloorShapes at -200 and Objects
  at 0). Do **not** use `PatternShapeTool.SetLayer()` on an uncreated index — it
  hard-crashes the mod (GDScript has no try/catch; valid range undocumented).
- **default tints** — `draw_wall` uses the texture's own default color when no
  `color` is given (via `WallTool.GetWallColor(tex)`), rather than
  `Color(1,1,1)` (white), which renders bleached/washed-out. Pass
  an explicit `color` to override. **`place_pattern` color caveat:** unlike walls,
  patterns have **no per-texture default** lookup — `PatternShapeTool.Color` is
  *persistent tool state that leaks across calls* (it holds whatever the previous
  `place_pattern` set). Reading it back as a "default" made every no-color call
  inherit the prior call's tint, and if it was ever left transparent (alpha ≈ 0)
  every subsequent floor rendered **invisible**. So `place_pattern` never trusts
  `tool.Color`: an explicit `color` is used verbatim; with no color it applies a
  deterministic opaque neutral tint (`DEFAULT_PATTERN_TINT`) and reports
  `used_default_tint: true` + the resolved `color`. Each call is independent.
  Pass an explicit `color` for an exact per-asset look.
- **`build_room`** — convenience composite: draws a looped wall **and** a floor
  along the **same** boundary path (so the floor meets the wall with no gap, like
  the UI's combined trace), by calling `draw_wall` + `place_pattern`/`fill_region`
  internally. `floor` = `"pattern"` / `"terrain"` / `"none"`.
- **`add_roof`** — `points` is the roof's **RIDGE line** (the peak), **not** a
  footprint to trace. `Roof.Set(points, width, type)` builds a complete,
  self-closing roof that slopes down `width` woxels perpendicular to each side of
  the ridge, with hips/gables off the ridge ends. The covered footprint = the
  ridge's bounding box expanded by `width` on every side. So **2 points already
  make a full, clean roof** (a short ridge → a near-pyramid hip). To roof a
  building W×H: ridge along the **long** axis, centered, `width` = half the
  **short** dimension; make the ridge ~`width` shorter than the long wall at each
  end so the end hips land on the short walls. (An earlier version wrongly treated
  `points` as a footprint and closed the loop — that duplicated a vertex and
  malformed the seam corner; removed. The single-`Set` ridge model has no seam.)
  `type`: 0=gable, 1=hip, 2=dormer. Roofs have **no color/tint** (the tileset
  renders at its natural color — there is no `SetColor`, unlike walls/patterns)
  and sit at z 800 (above everything). It is a create (returns an `id`), so
  `undo` reverses it.
- **`dig_cave`** — caves are a separate layer: a `CaveMesh` (a `MeshInstance2D`,
  z -300) whose open/rock state is a Godot **`BitMap`** (one bit per cell;
  `true` = open cave floor). The bridge enables the `CaveBrush` tool (the UI
  path, which wires the mesh to the level), fetches the BitMap via
  `get_Bitmap()`, sets bits along the requested woxel path (rasterized as a
  constant-width ribbon, like `paint_path`), then `SetBitmap` +
  `FinalizeMeshAndBorders` + `UpdateMesh` rebuilds the floor, the rocky wall
  border and debris — the same result as hand-painting with the Cave Brush.
  Cell mapping: `cell = floor(woxel / CellSize) + MapEdgeBuffer` (CellSize is 64
  woxels = ¼ tile). `dig=false` fills cave back to rock. `ground_color` /
  `wall_color` tint the **whole** cave system (DD applies one color globally, as
  the UI does), `texture` sets the cave floor from the `Caves` asset bank. Note:
  `SetCircle` and the `IsEmpty` flag on the mesh proved unreliable from a mod
  context (an internal grid the BitMap doesn't reflect) — editing the BitMap
  directly is the path that renders. Undo-recorded (snapshots the BitMap before
  and after, like the terrain ops). `clear_caves` wipes the whole cave layer back
  to rock in one call (native `CaveMesh.Clear()`, or zero the BitMap as a
  fallback, then rebuild) — also undoable.
- **`add_portal`** — defaults to **wall-mounted** (`Wall.AddPortal`): snaps to
  the nearest wall within `snap_max` woxels, faces along that wall segment, and
  the wall remakes its lines so the portal cuts a gap (matching manual door
  placement). `radius` is the door half-width (≈128 = a 1-tile door, ≈256 = a
  2-tile door). Pass `mount:"free"` for a freestanding portal
  (`Level.CreateFreestandingPortal`); when `mount:"wall"` and no wall is near it
  falls back to freestanding unless `fallback_free:false`. `flip` reverses the
  facing. The response `kind` is `"wall_portal"` when mounted, `"portal"` when
  freestanding.

## Native batch jobs (protocol 21, schema v1)

Wire request: `apply_batch` with `schema_version: 1`, `operations: [...]`, and
`idempotency_key`. Each operation contains `cmd` and that command's parameters.
The MCP tool supplies the schema version and waits internally by default;
`wait=false` returns immediately for polling/cancellation.

| Limit | Value |
| --- | --- |
| Operations | 1..500 |
| UTF-8 request, including newline | 1 MiB |
| Terrain operations | 16 |
| Water operations | 16 |
| Retained jobs per bridge instance | 64; never evicted silently |
| Key | 1..128 characters |
| Work per frame | Four operations or 8 ms between operations |
| Point lists | 2..32 finite pairs inside the map |

A single terrain operation can exceed the frame budget. These are scheduling
limits, not a guaranteed frame rate. This version supports `place_object`,
`draw_wall` (type 0, joint 1), `draw_path`, `add_light`, `add_portal`
(`mount=free` only), `fill_terrain`, `paint_terrain`, `paint_path`, `fill_region` (points only), and `draw_water`.
Assets must belong to the loaded category; only default lights may omit one.
Unknown fields, invalid numeric/boolean/color values, missing assets and bounds
errors return `accepted=false` plus indexed `validation_errors` before editing.
Integer parameters accept integral JSON numbers; booleans are not numbers.
Bounds validation checks anchor/point coordinates, not full sprite extents.

Accepted responses identify `job_id`, `bridge_instance`, `status`, `total`,
`processed`, `rollback_remaining`, `max_frame_ms`, and per-operation `results`
containing index, command, status and the original result (including created ID).
`get_batch(job_id, include_results=false)` gives compact progress. Terminal
statuses are `completed`, `cancelled`, `failed`, and `failed_partial`.
`cancel_batch(job_id)` requests cancellation and the MCP tool waits for rollback.
Cancelling a completed job does nothing.

Atomicity is preflight plus rollback of completed operations on failure/cancel.
Terrain snapshots include textures and both splat images when slots are expanded.
Full rollback restores the previous bridge history/redo branch and checkpoint
state. Results already undone are marked `rolled_back`; a rollback failure or
external level change yields `failed_partial`. Inspect it before further edits.
Native engine exceptions cannot be caught by GDScript; lost connectivity is an
uncertain outcome, never proof that no edits happened.

Same key plus canonically identical operations returns the retained job without
reapplying, including after completion/cancellation. A conflicting plan with the
same key is rejected. Jobs/keys are not durable across a map replacement or fresh
process, and Reload Mods is not a durable recovery mechanism. Check instance ID
before retrying. A default wait may return `wait_timed_out` after 90 seconds;
inspect the same job or retry the same key. Other MCP mutations are rejected while
a job runs. **Do not edit, switch levels, reload mods, or replace the map through
the native UI during a job.** Native `SuppressTool` also disables mod updates and
cannot provide a batch lock.

Mounted portals, rooms/floor patterns, deletion, caves, lifecycle changes and
other irreversible operations are excluded. Their existing low-level tools
remain available. Extending batches requires a validated reversible edit record.

## Native water (protocol 21)

`draw_water(points, erase=false)` takes a simple polygon of 3..32 unique finite
world-coordinate vertices inside map bounds. Repeated vertices, self
intersections, intersecting/overlapping nonadjacent edges and degenerate areas
are rejected. `erase=true` subtracts the polygon. Both are undo-recorded and
batch-supported. Water is a shared mesh per level, not an element with an ID.
The result reports `water_added` and `point_count`.

The installed build registers **`WaterMesh.Save()` with zero arguments**, unlike
the published optional-copy signature. Snapshots use that registered method and
`Load(data)` to preserve prior polygons/colors, including overlaps. Before the
first water edit, Save omits `tree`; undo erases the added polygon in that case.
Water drawing may take longer than one frame's scheduling budget. A mixed
cancellation test restored native water data and the original dry terrain PNG.

`get_water` returns native serialized data; polygons are encoded by Dungeondraft
as `PoolVector2Array(...)` strings. `ref` values are ephemeral native references,
not stable semantic IDs. The planner uses conservative bounds for preexisting
water and preserves independent gameplay metadata in its own manifest.

The structured planner is a Python MCP layer; it does not add GDScript planning
commands. See [MAP_SPEC.md](MAP_SPEC.md) for its schema/tools and lifecycle.

## Project/revision native support (protocol 22)

`get_surface_state` returns `{terrain_sha256, textures, level_id}`. SHA-256
includes both native splat images when expanded slots are active and all texture
paths. The planner records it after application and compares it before repaint.

Batch schema v1 also accepts current-level object-only `move_element`
(`id,x,y`), `modify_object` (`id,asset?,scale?,rotation?,shadow?,color?`) and
`delete_object` (`id`). Texture changes are included in transform history.
Reversible deletion snapshots the native serializer and restores a fresh Prop
with the same ID using `Objects.LoadObject`; it never reattaches a stale Prop.
General `delete_element` remains outside reversible batches.

`export_map` accepts absolute `path`, integer `ppi` 8..256 and optional boolean
`grid`. It rejects active exports and allocations above 16 megapixels or 8192
pixels per side. The public `Editor.ToggleGrid` controls visibility; native
`Master.IsExporting` determines completion and restoration. `get_export_status`
returns `{exporting,managed_export,grid}`. MCP mutations are rejected during
export. Camera restoration is performed by the native Exporter, then verified
by the Python project renderer. `get_map_info` also reports `exporting`.

Project/specification/manifest persistence and revision diffs live in Python,
not in a second native protocol. See PHASE4_REVIEW.md. No client config changed.

## Universal VTT native export (protocol 23)

`export_map` also accepts `format: "png" | "universalvtt"` (PNG default) and
optional boolean `lighting`. All inputs are checked before changing editor
state. Universal VTT uses native mode 3 and the current source level, with
`SetSourceLevel` before export and `RestoreLevelsPostExport` after completion.
If lighting is requested, its restoration happens while SourceLevel is still
valid. Clearing SourceLevel before ToggleLighting(true) caused a native null
exception in the probe and is not safe.

`get_export_status` is read-only during export and returns
`{exporting, managed_export, grid, lighting}`. It refreshes completed restoration.
The higher-level Python `export_battlemap` tool uses unbaked native VTT export,
validates JSON/image resolution and restores camera/grid/lighting. It supports
single-level owned projects and optional Foundry 14 files; see PHASE5_REVIEW.md.
Native VTT coordinates and light ranges are tiles, not woxels or pixels.
