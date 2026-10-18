# Dungeondraft AI Enhancement

A workspace for building Dungeondraft maps with AI, backed by an MCP server.
The server lets an AI client inspect and edit a running Dungeondraft
map. Version 0.7.1 targets Dungeondraft 1.2.0.1 on Windows, using Godot 3.4.2
and bridge protocol 23.

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

## Tools and map workflow

The server exposes 60 tools. Their MCP descriptions and input schemas are the
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

1. Load a map with suitable dimensions.
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
7. Export and inspect the final artwork for every playable floor.

Low-level coordinates use **256 woxels per tile**. Planning specifications use
tiles. Export pixels per tile are a separate setting. Native floor IDs and list
indices are different; resolve them with list_levels after loading a map.
Drawing layers control order within a floor and do not create another floor.

## Operational limits

- A populated map cannot be replaced through open_map on Dungeondraft 1.2.0.1.
  Save and close the editor, then launch it with the intended map. open_map
  requires an empty current map across all floors and discard_current=true.
  Arbitrary new dimensions require native creation or a prepared template.
- save_map validates native JSON without reopening the scene. Before an
  empty-map reopen, wait for the native save notification to disappear.
  bridge_dirty reflects the bridge's verified save checkpoint; UI saving
  alone does not establish that checkpoint.
- Planner records belong to an editor instance and floor. After restarting,
  open the saved bundle's native map and use load_battlemap_project.
  Manual terrain/water edits can conflict with planner ownership.
- revise_battlemap replaces complete named features. Review its default dry
  run and retain the new plan ID.
- Native exports are limited to 16 megapixels and 8192 pixels per side. Wait for
  completion before editing.
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
