# Dungeondraft AI Enhancement

A workspace for building Dungeondraft maps with AI, backed by an MCP server.
The server lets an AI client inspect and edit a running Dungeondraft
map. Version 1.0.2 targets Dungeondraft 1.2.0.1 on Windows, using Godot 3.4.2
and bridge protocol 23.

The Python MCP server and bridge mod share release version **1.0.2**. The
transport protocol remains **23**: the lifecycle additions preserve its JSON
format and existing commands. MCP initialization reports server version 1.0.2;
bridge `ping` and `get_capabilities` report `bridge_version: "1.0.2"` separately
from `protocol: 23`.

Version 1.0.2 preserves connected Foundry levels, overhead Tiles and embedded
Vehicle Actors when packaging reviewed exports. It adds hash-pinned artwork
releases with Patreon copy, disables blanket global light in raw scene drafts,
and refines skills for regional lighting, water movement, visibility and map
layout. Workflow preferences are interpreted by the skills; the bridge commands
and protocol are unchanged.

The Python server communicates with the client over MCP stdio. The
Dungeondraft mod receives commands over localhost TCP at 127.0.0.1:8787.
Both components run on the same computer.

## Install

Requirements: Dungeondraft 1.2.0.1, Python 3.10 or newer, and a local MCP client.

1. In Dungeondraft's Mods settings, choose this repository's mod/ directory,
   or copy mod/dungeondraft-mcp-bridge/ into your existing mods folder.
2. Enable **Dungeondraft MCP**, mod ID DungeondraftMCP.Bridge. Disable any older
   bridge using port 8787.
3. Open or create a map after starting Dungeondraft. Tool mods load when a map
   loads; enabling the mod without loading a map is insufficient.
4. Install the Python server from the repository root:

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .\server
~~~

On macOS/Linux, use python3 and .venv/bin/python. The editor integration is
verified on Windows.

Register the installed executable by its absolute path in your MCP client:

~~~json
{
  "mcpServers": {
    "dungeondraft": {
      "command": "C:\\absolute\\path\\to\\dungeondraft-ai-enhancement\\.venv\\Scripts\\dungeondraft-mcp.exe",
      "args": []
    }
  }
}
~~~

Clients use different configuration filenames and layouts. Allow at least
120 seconds for long exports. Restart or reconnect the MCP client after
registering the server or changing tool definitions.

## Check the connection

Call ping, then get_status, then get_capabilities.

- ping must report pong and protocol 23.
- For this release, ping must also report bridge_version: "1.0.2". A different
  release version means the editor is still running an older bridge.
- get_status must report map_open: true; it also provides map size and center.
- get_capabilities reports supported commands, batch limits, engine version,
  active mods and asset catalog version.

If the connection fails, confirm that Dungeondraft is running, the mod is enabled,
a map has loaded, and port 8787 is available. The editor log should contain:

~~~text
[mcp-bridge] listening on 127.0.0.1:8787 (protocol v23)
~~~

Connection checks do not place objects or alter the map.

## Map workspace

Open the **dungeondraft-ai-enhancement repository root** as your Codex project.
The bundled skill in .agents/skills/dungeondraft-map-skill/ is then discoverable
within the repo and its subfolders. Start map requests with:

~~~text
Use $dungeondraft-map-skill to build a pirate hideout.
Save the encounter under dd-maps/pirate-hideout/.
~~~

All map output belongs in **dd-maps/<encounter-slug>/**, resolved from the Git
repository root even when working in a nested folder. Keep the native map,
current floor PNGs, concept preview, play notes and layout manifest together.
Project bundles and optional VTT exports also stay inside that encounter folder.
Keep one canonical native map per encounter; revise it and replace current
exports in place. Create backups or numbered versions only when requested.
An explicit user destination overrides this default.

The Python package, executable and MCP connection are still named
dungeondraft-mcp; dungeondraft-ai-enhancement is the repository/workspace name.

## Workflow preferences

Copy [map-workflow.example.json](map-workflow.example.json) to
`map-workflow.json` at the repository root for first-time setup, then edit the
local file to choose the workflow for both bundled skills. `map-workflow.json`
is Git-ignored; only the example is shared. Preserve an existing local file when
updating the repository. Agents read the same local file from nested working
directories and user-wide skill installations. Explicit instructions in the
current task override these defaults; this file is read by the agent through
the skills, not automatically by the Python server.

~~~json
{
  "automatic_open_maps": true,
  "automatic_concept_approval": false,
  "automatic_exports": true,
  "reasoning": true,
  "enhancing": true,
  "export_to_foundry": false
}
~~~

| Setting | `true` | `false` |
| --- | --- | --- |
| `automatic_open_maps` | Perform necessary map creation/opening/reopening and editor startup/restart through lifecycle tools. | Present the concrete lifecycle action and wait for approval, unless that action is already explicitly approved. |
| `automatic_concept_approval` | After generating, showing and reviewing a concept, continue construction without a separate approval reply. | **Default:** ask the developer to approve the displayed concept and wait before creating or populating its native map. |
| `automatic_exports` | Generate final files included in the requested workflow after map review. | Show the reviewed map and proposed final exports, then wait for approval unless those exports are already explicitly approved. Internal review renders and preservation saves still run. |
| `reasoning` | Include concise design/export rationale in the existing handoff and notes. | Omit extra rationale; retain planning and verification. |
| `enhancing` | Include a readable tactical feature by default, omitting it only when it clearly does not fit; add fitting exploratory/decorative details. | Build the requested functional place without unsolicited extras. |
| `export_to_foundry` | Include Foundry file delivery by default, using supported Foundry 14 unless another target is established. | Export to Foundry only on request or an established session requirement. |

All values must be JSON booleans (`true`/`false`), not strings. A missing local
file or key uses the defaults shown above; the example is a setup template,
not an override of local preferences. Invalid values/unknown keys are reported;
continue clearly authorized work and resolve only the affected preference before
acting on uncertain scope. The flags retain save/preservation checks, valid
dimensions, mandatory visual correction and file validation. They do not
authorize discarding unrelated maps, uploads, publishing, installing modules or
changes to an unrelated live Foundry world. `enhancing` does not expand an
existing-map export request into a redesign. An image-only request overrides
automatic Foundry delivery.

The concept checkpoint applies to each new or materially replaced concept;
a general request to build a map is not approval of an unseen image. Silence
or elapsed time never counts as approval. A concept already approved for the
same design needs no repeat approval, and routine revisions/export of an
existing map need no new concept. With automatic concept approval enabled,
the preview and its visual review are still required. Explicitly requested
approval always takes precedence. Combine ready lifecycle/export questions
when useful, but never treat one automation flag as enabling another.

The legacy `fully_automatic` setting is removed. To migrate a local file, remove
that key, set missing `automatic_open_maps` and `automatic_exports` to its old
boolean value, and set missing `automatic_concept_approval` to `false`.
Preserve existing granular values and all other preferences; the old value
must never imply concept approval.

Routine map opening/creation uses the lifecycle tools below. If initial ping
fails, a single controlled lifecycle call can launch a closed editor; the
controller refuses to stop an existing editor with an unreachable bridge.
Ask for manual startup only after the tool reports a setup/action it cannot
perform. Startup failures are inspected before another attempt.

## Tools and map workflow

The tools' MCP descriptions and input schemas are the
parameter reference; call get_map_spec_schema for the generated planning schema.

- Inspect map state, floors, elements and available assets.
- Place and edit objects, walls, paths, doors, lights, roofs, text and floor patterns.
- Paint terrain, draw native water and carve caves.
- Work with separate native floors and persistent drawing layers.
- Frame the camera, capture screenshots and export full-map images.
- Submit reversible batches and use the bridge's own undo/redo history.
- Plan encounters, validate routes, save project bundles and revise named features.
- Export optional Universal VTT and Foundry 14 files.

For a complete encounter:

1. For a new map, plan and show the concept, then apply the concept approval
   checkpoint before create_map with a blank template and suitable dimensions.
   For an existing map, use open_map when needed. Honor automatic_open_maps
   before either lifecycle action.
2. Discover assets using list_asset_categories, list_assets or list_asset_metadata.
3. Call plan_battlemap with a specification in tiles. Review errors, warnings,
   resolved artwork and route checks before calling apply_battlemap.
4. Leave the editor UI unchanged while plans or batches are being applied.
   Reuse the same batch idempotency key after an uncertain reply; retain job and
   plan IDs.
5. Inspect the actual map with renders, screenshots and camera tools. Route
   validation does not establish visual quality.
6. Save the native map with save_map. Use save_battlemap_project when planner
   ownership, specifications and semantic IDs must survive a server restart.
7. Apply automatic_exports, then export and inspect the final artwork for every
   playable floor. Internal review renders do not require final-export approval.

Low-level coordinates use **256 woxels per tile**. Planning specifications use
tiles. Export pixels per tile are a separate setting. Native floor IDs and list
indices are different; resolve them with list_levels after loading a map.
Drawing layers control order within a floor and do not create another floor.

## Build map download packages

For a completed encounter, run one command from the repository root:

~~~powershell
.\.venv\Scripts\python.exe -m dungeondraft_mcp.release .\dd-maps\my-encounter
~~~

The builder reads that encounter's `map-release.json`, preserves/opens its
canonical native map with the existing lifecycle tools, optionally refreshes
its corrected Foundry export, and writes three separate downloads in `release/`:

| Download | Contents |
| --- | --- |
| `<slug>-gridded.zip` | Native PNGs with visible grids, one per floor, plus setup instructions. |
| `<slug>-gridless.zip` | Gridless PNGs from the exact embedded Foundry backgrounds, plus setup instructions. |
| `<slug>-foundry.zip` | Corrected Foundry 14 scenes with embedded artwork, walls, doors, lights and Regions; connected levels stay in one scene, with import/play instructions. |

`RELEASE-NOTES.txt` contains a package summary and installation instructions.
Loose image folders are provided for inspection; `build.json` records source
and package hashes. Recipients do not need the native `.dungeondraft_map`,
`.dd2vtt`, concept, manifests, asset catalogs or Python scripts. Asset-pack
files are not part of these downloads. This command creates local files.

For already reviewed exports, `map-release.json` can instead use `artwork`,
`scene`, `export_metadata`, `readme` and `patreon_readme`, as in the current
`dd-maps/` encounters. Each artwork entry names its playable `levels`, all
contributing `native_labels`, gridded/gridless PNG paths and their SHA-256 hashes.
The same command then packages those files offline, checking native/scene export
hashes and all artwork hashes. It keeps one connected scene with its real core
levels, movement/lighting regions and embedded overhead Tiles; it does not split
connected stairs into separate scenes. Flat component artwork is shipped as its
reviewed composite. An optional `actor` includes a hash-verified, self-contained
Vehicle Actor. Package READMEs describe the actual map mechanics and import
steps; `PATREON-README.md` provides the English post title and description.

Generated local map downloads and Patreon copy are indexed in
`dd-maps/PATREON-README.md`; generated map content is Git-ignored and is not
distributed with this source repository. Prepared artwork configuration pins
the reviewed images: after changing a map, refresh
its corrected export, visually check the artwork, then update those hashes.

Create this small configuration once per encounter (the map skill should keep
it with the final map). Paths are relative to the encounter, and `native_label`
must match the editor's floor label exactly; floor IDs may change after loading.
For multiple floors, add a row and corrected scene JSON for each playable floor.

~~~json
{
  "title": "Example Encounter",
  "slug": "my-encounter",
  "native_map": "map.dungeondraft_map",
  "pixels_per_square": 128,
  "foundry_exporter": "export-foundry.py",
  "floors": [
    {"name": "ground-floor", "native_label": "Ground", "scene": "foundry/foundry-scene.json"}
  ]
}
~~~

`foundry_exporter` is an optional **trusted encounter-local Python script**,
executed with `--capture`. It owns map-specific corrections such as cave walls,
windows, secret doors and locks, and must write `foundry/export.json` with
`native_sha256` and either `scene_sha256` or per-floor `scene_sha256` entries
under `floors`. If omitted, the builder packages the existing corrected scenes
only when their hashes still match. Raw adapter output must first be finalized
with the export skill; this builder does not infer secret doors from artwork.

The legacy native-capture build format supports embedded-PNG Foundry 14 scenes, square grids
at 5 feet per square, and one scene per floor. It validates dimensions, origin,
resolution and source hashes, rejects stale/shifted scenes, and excludes internal
ownership flags from public JSON. It does not create actors, automate terrain
costs or stairs, or verify a live Foundry import. Existing ZIPs are replaced only
after export and file validation finish; unrelated encounter files are preserved.
The explicit command authorizes its configured build steps. Agents must still
honor the workflow's concept/lifecycle/final-export checkpoints before running it.

For image-only use, select the original PNG as your VTT background, use the
documented pixels per square (128 here) and 5-foot distance, and keep its dimensions
and origin unchanged. A gridded PNG normally needs the VTT's visible overlay hidden
to avoid double grid lines; keep its mechanical grid for snapping/measurement.
For prepared Foundry scenes, use the JSON import below rather than importing an
image or raw `.dd2vtt`. See the [official scene guide](https://foundryvtt.com/article/scenes/).

## Import into Foundry VTT

**Recommended: import the completed `foundry-scene.json` with Foundry's built-in
Import Data command.** Use the Foundry 14 export delivered under
`dd-maps/<encounter-slug>/foundry/`. The Foundry export skill prepares a
self-contained JSON with the background image, grid, configured walls, doors
and lighting together. No importer module, script macro or separate background
selection is needed for that completed export. Raw adapter output initially
references a separate PNG; it must be finalized with the Foundry export skill
to provide this single-file experience.

### Import the JSON map

1. Open the **Scenes** tab in Foundry's right sidebar (the folded-map icon).
2. Click **Create Scene**, enter a name, and create it. If Scene Configuration
   opens, click **Save Changes** to return to the Scenes list.
3. **Right-click the new scene in the Scenes list** and choose **Import Data**.
   Import is in this context menu, not in the Scene Configuration window.
4. Select the map's **`foundry-scene.json`**, then click **Import**. The embedded
   background and scene settings are imported together.
5. Right-click the imported scene and choose **View Scene**.
6. Optionally, right-click the same scene again and choose **Regenerate
   Thumbnail Image** (or **Generate Thumbnail Image**, depending on the version)
   to refresh its preview in the Scenes list.

Import as a GM with file-upload permission so Foundry can save the embedded
image. Import Data replaces the selected scene's data, so use a new empty
scene to preserve tokens or other work in an existing scene. The scene name
can change to the name stored in the JSON. See Foundry's official
[scene import and context-menu documentation](https://foundryvtt.com/article/scenes/).

The `.dungeondraft_map` file is the editable Dungeondraft source; a standalone
PNG is artwork only. Neither is the complete Foundry scene import. If the
background is missing after importing an older, path-based JSON, select/upload
the PNG in Scene Configuration, or request a finalized self-contained export.

### Universal Battlemap Importer: available, but discouraged for these exports

[Dungeondraft's official VTT Integrations guidance](https://dungeondraft.net/)
links to [Universal Battlemap Importer](https://foundryvtt.com/packages/dd-import/)
for importing its Universal VTT (`.dd2vtt`) exports. That route remains usable
for ordinary native Dungeondraft maps; follow the
[importer's documentation](https://github.com/moo-man/FVTT-DD-Import) if you
intentionally choose it.

**We discourage that route when a completed Foundry scene JSON is supplied.**
The examined importer reconstructs basic walls, doors and lights from generic
Universal VTT data instead of using our finished Foundry settings. It does not
transfer the additional movement-only cage walls, Limited/terrain rock and
tent walls, one-way cliff restrictions, cage locks or the prepared local
daylight emitters and regional illumination setup. Finished mixed scenes use
core darkness regions to separate outdoor ambiance from rooms and caves;
the raw adapter leaves global light disabled until that setup is prepared.
The importer's
single light range is converted to bright
light at half the total dim radius, so pairs such as an oil lamp's 15/45 ft
cannot be reproduced exactly. Basic walls/doors and image import can still
work while these extra behaviors are missing.

Use **`foundry-scene.json` through Import Data** for the complete prepared map.
The supplied `.dd2vtt` is a limited alternative, not an additional import step.
These limits describe the examined format/importer route, not limitations of
Foundry itself. See the
[Foundry export reference](.agents/skills/dungeondraft-foundry-export/references/foundry-vtt.md)
for conversion details and verification checks.

## Water, terrain and export settings

These controls affect the active native floor and are exposed by bridge
protocol 23. Check get_capabilities for their command names; older protocol-23
bridges may not include them. Reload the mod and reconnect the MCP server after
updating. Both setters participate in bridge undo/redo and reversible batches.

| Tool | Settings |
| --- | --- |
| get_water_settings | Drawing defaults, existing region styles, border visibility and floor ID |
| set_water_settings | deep_color, shallow_color, blend_distance, border, apply_to_existing |
| get_terrain_settings | enabled, smooth_blending, expanded_slots (read only), floor ID |
| set_terrain_settings | enabled, smooth_blending |
| export_map | ppi, grid and lighting; omitted visibility options retain editor settings |

For example, set_water_settings(deep_color="#235e7a",
shallow_color="#5eaaa4", blend_distance=1.5, border=true) updates all existing
filled water regions and future drawing defaults. It preserves polygon
coordinates, holes and other topology. Omitted fields retain their values.
Colors accept six hexadecimal RGB digits, optionally prefixed with #. The
region data returned by get_water_settings uses native AARRGGBB strings;
drawing defaults use #RRGGBB. Blend distance accepts 0..10 in native slider
units, rather than pixels or feet.

apply_to_existing=false changes only future drawing defaults (except border,
which always applies to the whole floor). Defaults are session state; native
maps persist the colors/blending of regions actually drawn. Reapply desired
defaults after reopening before drawing additional water.

set_terrain_settings(enabled=false) matches the Terrain Brush's Enabled option
and preserves paint/textures. It does not activate or deactivate a toolbar
tool. smooth_blending=true enables native terrain blending. Both persist in
the native map. Texture selection/painting remains available through the
existing terrain tools; arbitrary terrain RGB tint is not provided.

For clean ship artwork, disable terrain and use export_map(grid=false,
lighting=false). Export restores the previous grid and lighting switches.
Terrain visibility remains as explicitly set until you change it or undo.
Inspect the PNG alpha to verify transparency.
On Dungeondraft 1.2.0.1, water over disabled terrain renders black. Use this
transparent-export workflow for props/ships without water; keep terrain enabled
when rendering ocean or river maps.

## Editor lifecycle (Windows)

Version 1.0.0 adds automatic map creation and resizing, and replaces the public
open-map workflow with verified process restarts:

| MCP tool | Behavior |
| --- | --- |
| `open_map(path, discard_current=False, save_current_path="")` | Save the current map and launch the requested native file in a fresh editor process; also starts a closed editor. |
| `reopen_map()` | Save and reopen the current named map in a fresh process. |
| `resize_map(width, height)` | Resize a blank single-level map to integer tile dimensions in 1..200; clears history and needs a subsequent save. |
| `create_map(width, height, path, bootstrap_path="", save_current_path="")` | Copy a blank template to a new native path, launch it, resize and save it, then verify readiness and dimensions. |

Set `DD_BOOTSTRAP_MAP` in the MCP server environment to an absolute blank native
file to use `create_map(width, height, path)` with three arguments. Alternatively,
pass `bootstrap_path` each time. The destination directory must already exist.
For example, these are MCP tool calls after configuring the bootstrap:

~~~text
create_map(width=30, height=22, path="C:/maps/encounter/map.dungeondraft_map")
reopen_map()
~~~

After upgrading, restart the Python MCP server to discover the new tools and
restart Dungeondraft with a map loaded to activate the new bridge version.
On Windows, stop the active MCP server before reinstalling the Python package
to refresh installed version metadata; its running console executable is locked.

`open_map(path)` saves the current map, stops only the process identified as the
local bridge listener, launches Dungeondraft with the target native file and
waits for the new process, bridge instance, path and dimensions. `reopen_map()`
does the same for the current named map. This avoids the unsafe populated-scene
teardown in Dungeondraft 1.2.0.1. After verifying the save and idle state, the
controller terminates that process through its Windows kernel handle; it does
not use native scene replacement or stop every process with the same name.
Active batches/exports and unfinished saves prevent restart. For an untitled
map supply a new `save_current_path`; `discard_current=True` explicitly skips
saving and should only be used when discarding that map is intended.

`create_map(width, height, path, bootstrap_path=...)` copies a blank native map
to a **new** destination, preserves/saves the current map, launches the copy,
resizes it and verifies the native save. Configure `DD_BOOTSTRAP_MAP` to omit the
template argument. Prepare that template once by saving a blank map in
`dd-maps/<bootstrap-slug>/`. It must contain one level, default unpainted terrain,
and no elements, water, caves, tiles or building shapes. Direct `resize_map`
supports only those blank maps, accepts 1..200 tiles per side and clears history.
Save after direct resizing. Creating encounter artwork still starts with the
skill's concept preview; disposable lifecycle tests do not require concept art.

With no running editor, set `DD_EDITOR_EXECUTABLE` if the executable is outside
`C:/Program Files/Dungeondraft/Dungeondraft.exe`. With a reachable bridge the
controller discovers the executable from its process. If an editor is running
but its bridge is unreachable, enable MCP Bridge and load a map manually;
the controller leaves that process alone. Lifecycle currently supports only a
local Windows editor. Startup failures retain the target file and leave a
launched editor running for inspection; do not blindly repeat a timed-out call.
The current startup output is stored beside the native map as `.editor.log`;
startup errors report the exit code and log path.

Release verification passed 33 automated regression tests and live checks of
opening, reopening populated maps, resizing blank maps, creating requested
dimensions, startup from a closed editor, and water-color refresh without
reopening. Invalid dimensions and populated/painted resize attempts were rejected.
One editor process exited during startup in the live tests; subsequent starts
passed, but the cause remains unresolved. Startup failures are reported without
automatic retries; inspect the retained map and startup log before retrying.

## Operational limits

- The low-level bridge open_map still rejects populated native replacement.
  The public Python open_map uses the verified save/restart workflow above.
  Populated-map resizing remains unsupported.
- save_map validates native JSON without reopening the scene. Wait for native
  save/export completion before other lifecycle operations.
  bridge_dirty reflects the bridge's verified save checkpoint; UI saving
  alone does not establish that checkpoint.
- Planner records belong to an editor instance and floor. After restarting,
  open the saved bundle's native map and use load_battlemap_project.
  Manual terrain painting and water geometry edits can conflict with planner
  ownership. Water colors/borders/blending and terrain visibility/smooth
  blending can be styled independently; stale, unapplied plans still detect
  appearance changes. Saved projects retain the current appearance.
- revise_battlemap replaces complete named features. Review its default dry
  run and retain the new plan ID.
- Native exports are limited to 16 megapixels and 8192 pixels per side. Wait for
  completion before editing.
- For transparent assets, call set_terrain_settings(enabled=false), then
  export_map(grid=false, lighting=false). PNG output alone does not guarantee
  transparency: inspect alpha, and check for water or other background artwork.
- Water drawing defaults are session settings. Existing filled regions retain
  their own colors and blending in the native map. Use set_water_settings with
  its default apply_to_existing=true to restyle existing water; inspect
  get_water_settings and a fresh render to verify the result.
- export_battlemap requires a validated applied/restored project on a
  single-level map and a new output directory. Supply the intended relative
  Foundry PNG path. It writes files; it does not import a Foundry scene.
- PNGs contain artwork. Configure VTT walls, doors, lighting, transitions and
  encounter mechanics in the target runtime.
- Bridge undo/redo is independent of Dungeondraft's Ctrl+Z.
  delete_element, place_pattern and build_room are not undo-recorded.

## Configuration and protocol

DD_BRIDGE_HOST defaults to 127.0.0.1; DD_BRIDGE_PORT defaults to 8787.
Set these in the Python server's environment only if you also change the mod's
matching HOST and PORT constants.

The local bridge exchanges UTF-8 JSON objects separated by newlines. A request
contains cmd and its parameters. Successful replies contain
{"ok": true, "result": ...}; failures contain
{"ok": false, "error": "..."}. Element id values identify native elements,
not request correlation IDs.

## Dungeondraft map skill

The bundled [Dungeondraft map skill](.agents/skills/dungeondraft-map-skill/SKILL.md)
covers encounter design, concept previews, native construction, visual review
and final floor exports. Copy the entire folder, including references/ and agents/.

Foundry delivery is an optional companion workflow in
[Dungeondraft to Foundry VTT](.agents/skills/dungeondraft-foundry-export/SKILL.md).
Use it later with an existing map, or combine both skills when creating a map
for Foundry. It covers export routes, walls, doors, windows, lighting, import
corrections and player-view checks. Ordinary map creation needs only the map
skill; no Foundry choice is required. Install the companion folder separately
if using these skills outside this repository.

~~~text
Use $dungeondraft-foundry-export to export my existing map for Foundry VTT 14.
~~~

~~~text
Use $dungeondraft-map-skill and $dungeondraft-foundry-export to build a pirate
hideout and prepare its Foundry VTT export.
~~~

### Codex discovery and use

The skill is stored in .agents/skills/dungeondraft-map-skill/, so Codex can
discover it when working in this repository or one of its subdirectories.
Codex checks .agents/skills along the path from the working directory up to
the repository root; it does not recursively search unrelated nested folders.

Registering the MCP server does not install its repository skills globally.
To use this skill from a separate maps workspace, install it in your user
skill directory or that map project's .agents/skills/ directory.

Run this from the repository root in PowerShell for user-wide installation:

~~~powershell
$skillRoot = Join-Path $env:USERPROFILE '.agents\skills'
$skillTarget = Join-Path $skillRoot 'dungeondraft-map-skill'
if (Test-Path -LiteralPath $skillTarget) {
    throw 'Skill already installed. Review that copy before replacing it.'
}
New-Item -ItemType Directory -Path $skillRoot -Force | Out-Null
Copy-Item -LiteralPath '.\.agents\skills\dungeondraft-map-skill' -Destination $skillTarget -Recurse
~~~

For project-only installation, use the same commands with $skillRoot set to
the absolute path of that project's .agents/skills directory.
Keep one installed copy; check for an existing installation before copying.

Codex detects local skill changes automatically; restart it if the skill does
not appear. It can select a discovered skill when its description matches the
request. Explicitly name it for predictable activation:

~~~text
Use $dungeondraft-map-skill to create a 30 by 30 square pirate hideout,
with 5 feet per square and separate playable floors.
~~~

In Codex CLI or the IDE extension, /skills or the $ skill selector can also
show available skills. See the [official skill documentation](https://learn.chatgpt.com/docs/build-skills)
for discovery locations and invocation behavior.

### Required capabilities

The skill supplies instructions; it does not start Dungeondraft, register the
MCP server or provide image generation. Complete the MCP setup above and load
a map with MCP Bridge enabled before native editing. New maps require access
to image generation for the concept preview; if unavailable, the skill asks
how to proceed. Install the skill on the computer/environment running the agent.

Other agents can follow SKILL.md and its references when given file access and
the Dungeondraft MCP tools; their skill installation and discovery rules differ.

## Repository contents and maintenance

~~~text
mod/dungeondraft-mcp-bridge/    Dungeondraft mod and command handlers
server/dungeondraft_mcp/       Python MCP server, planner and project/export logic
server/pyproject.toml          Dependencies, package metadata and executable entrypoint
.agents/skills/dungeondraft-map-skill/ Map-making skill, references and agent metadata
dd-maps/                      Encounter maps and their final output
.venv/                        Local installed runtime; ignored by Git
AGENTS.md                     Instructions for agents operating the bridge
LICENSE                       MIT license
~~~

The schema is generated from the Python models. Historical phase reports,
review screenshots, smoke scripts, demos and test fixtures are not runtime
dependencies and are not part of this checkout.

Changes to existing mod handlers require Reload Mods or an editor restart.
Reload Mods does not rerun startup: new script files, startup initialization or
instance state require a fresh editor launch and first-map load. Python MCP tool
definitions require an MCP server restart. Editable installs need no reinstall
after ordinary source edits.

Godot 3 GDScript has no try/catch. Validate native API inputs; unhandled handler
errors can stop the bridge. Parse the full script with a Godot 3-compatible
parser before reloading changed GDScript.

Run the Python regression checks from the repository root:

~~~powershell
.\.venv\Scripts\python.exe -m unittest discover -s server/tests -v
~~~

These check tool schemas, option forwarding and project ownership/persistence.
They do not replace native rendering, undo/redo and save/reopen checks in a
disposable Dungeondraft map.

Maintained by Filip Smyczek. Forked from Brandon Florian's MIT-licensed
Dungeondraft MCP project; the original copyright notice remains in [LICENSE](LICENSE).
Built against the [Dungeondraft Modding API](https://megasploot.github.io/DungeondraftModdingAPI/).

## Roadmap

Development priorities:

- **Stronger skill and MCP alignment:** Keep the skill's workflows, tool schemas
  and live capabilities in sync. Improve capability discovery, actionable errors
  and recovery so agents can reliably complete the full map-building workflow.
- **Direct Foundry VTT delivery:** Extend export toward ready-to-use Foundry
  scenes with aligned floors, walls, doors, lighting and encounter metadata.
  Verify imports in the target Foundry version and reduce manual scene setup.
- **Greater agent autonomy:** Support reliable application startup, blank-map
  creation, map sizing, floor setup, saving and export through supported tools.
  Handle routine steps and recoverable failures with fewer user interventions;
  ask for input when a meaningful user decision is needed.
- **More believable maps:** Improve proportions, building layouts, furnishings,
  terrain transitions, coastlines and readable elevation. Make routes, access,
  infrastructure and asset placement fit the setting and encounter.
- **RPG-system adaptation:** Adapt scale, creature footprints, movement, cover,
  visibility and encounter features to the requested RPG system and edition.
  Use verified rules where available and distinguish them from GM suggestions.
- **Better iteration and quality checks:** Strengthen whole-map and room-scale
  visual review, route and clearance checks, floor alignment and final-export
  inspection. Use the findings to revise the canonical map and improve the skill
  through practical map-making experience.
