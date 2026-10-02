# Phase 5 — native VTT files and Foundry 14 adapter

Package **0.6.0**, bridge protocol **23**, **60 MCP tools**. Implemented on main.
The file-export milestone passed; a real Foundry 14 import remains unverified.

## What changed

`export_battlemap(plan_id, directory, foundry_image_path, ppi=None)` writes a new
folder containing:

| File | Purpose |
| --- | --- |
| `battlemap.dd2vtt` | Native Universal VTT 0.3, actual editor LOS, portals, lights and embedded PNG |
| `battlemap.png` | That exact embedded image, extracted without a second render |
| `foundry-scene.json` | Foundry 14 scene creation data, one Ground level |
| `import-foundry.js` | GM script macro: validate, check image availability, create scene retaining embedded IDs |
| `encounter.json` | Independent tile-coordinate spec, features, gameplay data and native-ID manifest |
| `validation.json` | Structural validation of the exported owned map |
| `export.json` | Completion marker, file hashes, dimensions, warnings and review status |

The map must be an applied/restored project with valid ownership, on a
single-level native map. The directory must be new and its parent must exist.
Incomplete folders remain available for recovery without a completion marker.
No client TOML changes, extra MCP server, Foundry connection or credentials are
required. All clients use the same tool and standard stdio configuration.

## Native API findings

Use the documented [Exporter.Start](https://megasploot.github.io/DungeondraftModdingAPI/reference/Exporter/)
mode **3** for Universal VTT. The native exporter writes an intermediate PNG,
embeds it, then removes that intermediate file.

The normal export dialog initializes
[World.SetSourceLevel](https://megasploot.github.io/DungeondraftModdingAPI/reference/World/).
Calling Start without that setup wrote an image but failed metadata serialization
with `Snapshot Error`. The bridge now initializes the source level and calls
`RestoreLevelsPostExport` after native completion.

[Editor.ToggleLighting](https://megasploot.github.io/DungeondraftModdingAPI/reference/Editor/)
also needs the source level when enabling lighting. An early probe restored it
after clearing the source and raised a native null exception. The corrected
ordering restores lighting first, then clears export levels. VTT images are
unbaked and native metadata reports `baked_lighting: false`. Camera, grid and
lighting are verified after completion. Status polling remains available while
MCP mutations are rejected during export.

## Foundry contract

The target is **Foundry 14**, checked against its published API on 2026-10-02
(documentation identifies current 14.368). This is a generation-specific adapter;
there is no legacy format mode. Important sources:

- [SceneData](https://foundryvtt.com/api/v14/interfaces/foundry.documents.types.SceneData.html)
  and [LevelData](https://foundryvtt.com/api/v14/interfaces/foundry.documents.types.LevelData.html):
  background belongs to a level; scene `initialLevel` refers to its embedded ID.
- [DatabaseCreateOperation](https://foundryvtt.com/api/v14/interfaces/foundry.abstract.types.DatabaseCreateOperation.html):
  `keepEmbeddedIds` preserves that relationship during creation.
- [WallData](https://foundryvtt.com/api/v14/interfaces/foundry.documents.types.WallData.html),
  [edge senses](https://foundryvtt.com/api/v14/variables/CONST.EDGE_SENSE_TYPES.html),
  [movement](https://foundryvtt.com/api/v14/variables/CONST.WALL_MOVEMENT_TYPES.html)
  and [door states](https://foundryvtt.com/api/v14/variables/CONST.WALL_DOOR_STATES.html).
- [LightData](https://foundryvtt.com/api/v14/classes/foundry.data.LightData.html),
  [GridData](https://foundryvtt.com/api/v14/interfaces/foundry.documents.types.GridData.html)
  and [minimum grid size](https://foundryvtt.com/api/v14/variables/CONST.GRID_MIN_SIZE.html).

Coordinates use one conversion:

```text
native woxels / 256 = tiles
tiles * export PPI = PNG and Foundry pixels
light radius in tiles * 5 = Foundry distance in feet
```

Full-map origin must be zero. Scene padding/shift are zero; square grid size is
PPI. Foundry 14 PPI is 20..256 (minimum grid size 20), also bounded by 16 megapixels
and 8192 pixels per side. Native crop or image-size mismatches are rejected.

Native LOS is converted into wall segments; occluders outside the image are
clipped. Native portals become normal doors with their open/closed state.
Universal VTT does not distinguish windows/secret doors: a warning requires
review. Declared tree trunks/obstacles and deep water outside crossing areas add
movement-only walls. Their radius comes from gameplay semantics, not sprite
size. Unowned artwork is not assigned invented gameplay behavior.

Native light positions, color, radius and shadow state are preserved through
conversion. Bright radius is half the dim radius; alpha is clamped native
energy times color alpha. Cookies and rendering engines are not equivalent.
Ambient lighting, door types and light appearance need Foundry review. Cover,
movement cost and encounter zones remain metadata in scene flags and
`encounter.json`; no system rules, actors or tokens are created.

## Accepted evidence

- 24 pure tests passed, including known landmark scaling, embedded level IDs,
  open/closed doors, clipping, invalid coordinates/images/paths, independent
  movement blockers, deep-water crossing gaps, and decorative lights/text not
  blocking route validation.
- Godot 3 full-script parse and Python F/E9 checks passed.
- Fresh 60-tool MCP client passed project restoration, ownership checks,
  native VTT export and protected existing-directory rejection.
- Live 24x17 map exported at 64 PPI: **1536x1088**, **406 wall segments**,
  **one door**, **one light**. 400 walls represent declared mechanical blockers;
  five native LOS segments plus one mounted door complete the count.
- Known door: center `(3,1)` tiles, bounds `(2.5,1)..(3.5,1)`, Foundry endpoints
  `[160,64,224,64]`. Light: `(3,2.2)` tiles -> approximately `(192,140.8)` pixels;
  native radius 0.6 tiles -> 3 feet, color `#ffaa55`.
- A full native editor restart retained 51 objects, the wall, mounted portal,
  light, terrain/water and ownership. Export and validation passed again.
  Captured fresh stderr was empty; stdout contained only normal startup and the
  existing missing-tags warning. The rendered PNG was inspected.

## Review / repeat

Open the saved native project and load its ownership, then run from the repo:

```powershell
.\.venv\Scripts\python.exe phase5_smoke.py --project C:\maps\project --output-dir C:\maps\export-review
```

The runner creates a new export folder, validates hashes and restored editor
state, and checks overwrite rejection. `--fixture-landmarks` additionally checks
the specific NW wall/door/light fixture above. Review native stdout/stderr after
running; the runner cannot claim console or Foundry acceptance by itself.

For a real Foundry 14 import:

1. Upload `battlemap.png` to the tool's `foundry_image_path`, e.g.
   `maps/forest-ambush/battlemap.png`, using your normal Foundry file workflow.
2. Create a **Script** macro as GM; paste `import-foundry.js` and run it once.
   It refuses other generations, validates data before creating a scene, and
   checks that the background is reachable. Repeating it creates another scene.
3. Check grid overlay against landmarks, door interaction, token movement/vision,
   Ground level background and dynamic lights. Adjust portal types/ambient light
   if needed. Inspect `flags["dungeondraft-mcp"].encounter` or `encounter.json`.

**[PLAN CHANGED] Target-runtime acceptance is pending.** This machine has Foundry
13.348, while the adapter targets 14. No Foundry upgrade or test world was
installed. File/schema/coordinate proof passed; actual 14 scene creation and
rendering are explicitly unverified. Direct API deployment remains excluded
until there is an authorized target-world workflow.
