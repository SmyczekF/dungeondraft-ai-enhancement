# Full map acceptance: island prisoner rescue

Date: 2026-10-07. Package/mod 0.7.0, protocol 23, 60 MCP tools.
Tested Windows Dungeondraft 1.2.0.1 / Godot 3.4.2 custom Mono, default artwork.
This is an encounter workflow acceptance and focused regression pass, not an
assertion that every low-level command, asset pack or Foundry runtime was tested.

## Playable result

35x35 tiles, 5 feet per tile: 175x175 ft of island coast. The ground floor has
24 palms, three hard-cover boulders, three village buildings, two 10x15 ft
prison pens with four cage props, doors, bunks, a map table, fire, cart, pier
cargo, two boats and a raised rock terrace. The road is about 11 ft wide and
the pier 52.5x15 ft. The terrace and independent watchtower deck are +10 ft.
Loose sand is difficult terrain; water outside the visible pier requires a
swimming/boat ruling. Height, cover and environmental rules remain DM metadata.

| Editable component | Native location |
| --- | --- |
| Grass/sand/gravel/dirt | Ground terrain, separate from water |
| Coast | Ground native WaterMesh; continues under the pier |
| Palms/boulders | Object layer 0 |
| Cliff and rope details | Paths layers 1 and 2 |
| Room floors | Pattern layer -100 |
| Ground furnishings/cages/boats | Object layer 20 |
| Wooden pier | Pattern layer 100 |
| Pier cargo | Object layer 200 |
| Upper tower | Separate native floor, four -100 floor shapes around a stair hatch, four layer-20 props |

The procedural core is committed in [examples/island-rescue.json](examples/island-rescue.json).
It does not automatically place the subsequent furnishings, cliffs, deck or
upper floor. Native map and artwork renders are local deliverables rather than
redistributed copies of Dungeondraft's default artwork.

## Bugs found and repaired

1. Added `water_region` polygons for island coasts/lakes. Water stays under a
   declared deck crossing; deep-water mechanics are retained separately.
2. Walkable pattern floors and explicitly open ordinary portals no longer
   falsely block routes. Unknown portal states remain conservative. Native
   Closed is a light-block flag mapped to ordinary door state; windows need review.
3. Persistent object layers now maintain native search-table buckets and survive
   batch placement, layer modification, duplicate, undo/redo, saving and reload.
4. Pattern floors use public PatternShape.SetLayer. Temporary node z offsets
   previously looked correct but reloaded above furnishings because Save reads
   the parent layer. Room floors now remain below furniture and cargo above deck.
5. `add_level` reports the inserted index and updates native floor options.
   `set_level` supplies the managed optional argument explicitly and verifies
   the switch. Previously it could report success while leaving the old floor active.
6. Floor ID and index are distinguished. Undo/redo reject the wrong floor.
   Dungeondraft regenerates floor IDs on file loading; project restoration matches
   the checksummed native file's active floor index/label before rebinding ID
   metadata, then still checks terrain hashes, water and every owned element.
7. PNG exports isolate the active native floor and wait for native restoration.
8. Populated `open_map` is rejected before mutation. A prior test reopened the
   map but produced native Prop._ExitTree exceptions. Fresh file-argument launches
   with captured stdout/stderr passed; the private creation prototype remains rejected.

## Verification evidence

- 32 pure tests: layout, revisions, VTT, coast geometry and restored floor identity.
- Full Godot 3 GDScript parser and Python syntax/static checks.
- Real stdio MCP clients exercised discovery, planning, applying, revisions,
  batching, replay, object layers, history, duplicate, selection, floor creation,
  switching, previews, PNG, native saves, project restores and VTT file export.
- Layer regression: 200 -> 250 -> undo 200 -> redo 250; duplicate retained 250.
  A matching batch retry reused its job; invalid layer 1001 was rejected.
- Ground after reload: 56 objects, 10 walls, one light, seven paths, five portals,
  four floor shapes. Three doors open and two prison gates closed. Pattern
  layers [-100,-100,-100,100]; object layers {0,20,200}.
- Upper after reload: four objects, one perimeter wall, four floor shapes and
  no ground content. Ground checksum/ownership remained valid after switching.
- Four required ground routes and two upper circulation routes passed with
  agent radius 0.4 tiles: 4 ft total diameter. This does not prove reachability
  for larger creatures, cage-interior rescue, sight lines or encounter balance.
- Final ground and upper PNGs were visually reviewed after a fresh native reload.
  Native stderr was empty, with no script errors/exceptions in captured stdout;
  the preexisting missing override-tags warning remains unrelated.
- Ground-only Universal VTT and Foundry 14 files use 96 px per 5 ft tile.
  Multi-floor VTT export was rejected without creating an output directory.

## Repeat the saved-map check

Start the completed native project map in a fresh editor using
`scripts/Start-Dungeondraft.ps1`, then from this repository run:

```powershell
.\.venv\Scripts\python.exe scripts/verify_island_project.py --project 'C:\maps\final-project' --output 'C:\maps\new-review'
```

The output directory must be new. The script checks the named island floors,
restores the ground plan, verifies persisted layers and route connectivity,
exports both floors, rejects a populated reopen, and leaves the ground selected.
It changes the camera/active floor, not map content. Inspect its acceptance JSON,
images and the native captured console logs. Restart the Codex MCP server to
load the new Python tool parameters; editable source alone does not refresh
an already-running MCP process.

## Remaining gaps / decisions

- **[PLAN CHANGED]** Arbitrary fresh-map dimensions still need manual native
  creation or a prepared template. The external launcher opens saved templates
  without computer input. It does not invent unsupported startup dimensions.
- **[PLAN CHANGED]** Populated in-process file replacement is rejected. Save and
  start a fresh editor with the file instead; bridge code cannot repair native teardown.
- **[PLAN CHANGED]** Multi-floor native editing and per-floor PNG work, but
  map_spec.v1 planning is scoped to one native floor. The tower is a low-level
  addition with separately reviewed circulation. Gray space outside its platform
  is not a walkable upper surface; no transparent overlay is claimed.
- **[PLAN CHANGED]** VTT transfer remains single-level. Ground files were exported
  before adding the upper floor. Foundry 14 runtime import, vision and movement
  remain unverified; a file export is not a completed runtime integration.
- Water/building shared-geometry revision and mechanical inference for arbitrary
  manual decorations remain excluded. Explicit gameplay semantics and DM rulings
  are required for cover, vertical movement, tide, doors and cage rescue.
