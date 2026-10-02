# dungeondraft-mcp

An MCP server that lets Codex drive a
**running Dungeondraft instance** — place objects, draw walls, inspect the map —
through Dungeondraft's GDScript modding API.

Dungeondraft has no built-in server to talk to, so this project is **two halves**
that meet over a localhost socket:

```
Codex
      │  MCP (stdio)
      ▼
server/   ── Python MCP server  (this repo)
      │  newline-delimited JSON over TCP  (127.0.0.1:8787)
      ▼
mod/      ── Dungeondraft mod  (GDScript, runs inside DD)
      │  modding API calls
      ▼
   the open map  (Objects, Walls, Levels, …)
```

The mod opens a TCP server inside Dungeondraft and polls it every frame from the
`update(delta)` hook; the Python side exposes each capability as an MCP tool and
forwards calls as JSON. See [PROTOCOL.md](PROTOCOL.md) for the wire format.

> **Compatibility:** This version targets the installed Windows build,
> **Dungeondraft 1.2.0.1**. Documented API calls were checked against the
> published modding reference and a live 1.2.0.1 session. See
> [API_COMPATIBILITY.md](API_COMPATIBILITY.md). It exposes 54 tools across
> lifecycle, inspection, creation, terrain, editing, levels,
> selection, capture, camera, and undo.

Phase 1's live acceptance procedure and current verification status are in
[PHASE1_REVIEW.md](PHASE1_REVIEW.md).

Phase 2 batch acceptance and review steps are in [PHASE2_REVIEW.md](PHASE2_REVIEW.md).

Phase 3 structured planning is described in [MAP_SPEC.md](MAP_SPEC.md) and
[PHASE3_REVIEW.md](PHASE3_REVIEW.md).

## What the AI can do

- **Plan:** `get_map_spec_schema`, `plan_battlemap`, `apply_battlemap`,
  `get_battlemap` turn a strict tile-coordinate specification into a validated
  deterministic layout and one native batch. The manifest preserves semantic
  IDs, gameplay metadata and created editor IDs. See the
  [forest ambush example](examples/forest-ambush.json).
- **Inspect:** `get_status`, `list_levels`, `list_elements`, `get_element`,
  `get_map_info`, `get_capabilities`, `list_asset_categories`, `list_assets`,
  `list_asset_metadata` (paged paths, dimensions and filename tags).
- **Map files:** `open_map` and `save_map` manage native editable maps.
  `save_map` validates the written native JSON and preserves the open scene.
  To verify a reload, call `open_map` separately after the save notification
  disappears. Immediate scene replacement can outlive native save UI callbacks.
  Create a new blank map in Dungeondraft before the MCP edits it. The installed
  editor's internal new-map call raised native exceptions when invoked by the
  bridge, so the unsafe `create_map` command was removed. Saved maps can be
  reopened through MCP.
  On 1.2.0.1, UI New Map can log native object-cleanup exceptions even with
  all mods disabled; restart the editor before creating the next blank map
  if this happens. The bridge's separate port-conflict issue is fixed.
- **Batch:** `apply_batch`, `get_batch`, `cancel_batch` validate and execute up to
  500 reversible operations across editor frames. Matching idempotency keys
  reuse the same retained job. Cancellation restores completed edits, including
  terrain textures. Use the same key after an uncertain reply; never invent a
  replacement key. Leave the editor UI unchanged while a job runs.
- **Create:** `place_object`, `draw_wall`, `draw_path`, `add_light`,
  `add_portal`, `add_roof`, `add_text`, `place_pattern` (tiled floor shapes —
  wood planks, tile, brick — rendered below objects), `build_room` (a wall loop
  + matching floor on one shared path, like the UI's combined trace).
- **Water:** `draw_water` adds or erases native water polygons; `get_water`
  inspects their native serialized geometry/colors. Water and polygon terrain
  regions are supported in reversible batches.
- **Terrain:** `set_terrain_slot`, `fill_terrain` (whole level), `fill_region`
  (a rect/polygon, e.g. one room's floor), `paint_terrain` (a soft brush),
  `paint_path` (a smooth continuous stroke along a polyline — roads/trails).
- **Caves:** `dig_cave` carves caverns/tunnels along a path (the Cave Brush —
  dig open floor out of rock, with auto rocky walls + debris; `dig=false` fills
  back; optional ground/wall tints), `clear_caves` wipes the whole cave layer.
- **Edit:** `move_element`, `modify_object`, `duplicate_object`,
  `delete_element`, `select_elements`, `clear_selection`.
- **Levels:** `add_level`, `set_level`.
- **See:** `screenshot` (current window) and `export_map` (clean full-map
  render) return images, so the model can look at its own work and iterate.
- **Camera:** `get_camera`, `set_camera`, `focus_element` (center on one
  element), `fit_elements` (frame a group) — point the view before a
  `screenshot` to inspect specific spots like a door cut into a wall.
- **Undo:** the bridge keeps its own undo/redo stacks for supported creates,
  move / modify, terrain, and cave edits (independent of Dungeondraft's Ctrl+Z).
  `delete_element`, `place_pattern`, and `build_room` are not undo-recorded.

Every element is referenced by an integer `id`; create and list calls return
ids you feed back into edit calls. Coordinates are woxel (pixel) space — call
`get_status` for `map_center`. Discover assets with `list_assets`.

## Setup

**Prerequisites:** [Dungeondraft](https://dungeondraft.net/) **1.2.0.1**,
Python **3.10+**, and Codex on the same computer. The examples below use
PowerShell on Windows.

### 1. Install the mod into Dungeondraft

1. In Dungeondraft's title screen, open **Mods** and note (or set) your mods
   folder.
2. Set the Mods folder to this repository's `mod/` directory, or copy
   `mod/dungeondraft-mcp-bridge/` into your existing Mods folder.
3. Enable **Dungeondraft MCP** (mod ID
   `DungeondraftMCP.Bridge`) and disable any older MCP Bridge mod using port
   8787, then open or create a map. If you enabled this fork before the mod ID
   changed, enable it again in Dungeondraft's Mods screen.

On load you should see in the Dungeondraft log:

```
[mcp-bridge] listening on 127.0.0.1:8787 (protocol v21)
```

### 2. Install the MCP server

Install into a dedicated virtual environment. Run from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .\server
```

This installs the `dungeondraft_mcp` package and creates the
`.venv\Scripts\dungeondraft-mcp.exe` entrypoint. On macOS/Linux, use
`python3 -m venv .venv` and `.venv/bin/python -m pip install -e ./server`.

### 3. Verify the bridge works

With Dungeondraft open and a map loaded, run the bridge smoke test. It makes
temporary objects near the map center, prints PASS/FAIL, then removes them. Run
it on a disposable map: a failed test may leave objects behind.

```powershell
.\.venv\Scripts\python.exe .\server\test_bridge.py
```

If it cannot connect, confirm the mod is enabled, a map is open, and the log
shows the `listening` line. Port 8787 must be available on loopback.

For the Phase 1 acceptance check, create a blank disposable map at least
20 x 16 tiles and run:

```powershell
.\.venv\Scripts\python.exe .\phase1_smoke.py --output-dir <new-empty-directory>
```

It saves a ten-tree path sample, exports PNG, verifies every element descriptor
kind in a separate mixed map, and restores the sample. Review `report.json`,
`sample.png`, and both native map files in that output directory.

To *see* something get built (a small furnished room left on the map, rather
than a self-cleaning test), run
`.\.venv\Scripts\python.exe .\server\demo_build.py`.

### 4. Connect Codex

Register the installed entrypoint by its **absolute path**:

```powershell
$server = (Resolve-Path .\.venv\Scripts\dungeondraft-mcp.exe).Path
codex mcp add dungeondraft -- $server
codex mcp list
```

Alternatively, add this to `~/.codex/config.toml`, replacing the command with
your actual absolute path (TOML single quotes preserve Windows backslashes):

```toml
[mcp_servers.dungeondraft]
command = 'C:\absolute\path\to\dungeondraft-mcp\.venv\Scripts\dungeondraft-mcp.exe'
tool_timeout_sec = 120
```

Restart Codex after adding the server, then check `/mcp` in Codex. The longer
tool timeout allows full-map exports to finish. Ask Codex things like
*"what's the status of my Dungeondraft map?"* or
*"list some object assets and drop a chair in the middle of the map."*

### Other AI agents and MCP clients

The Python server uses standard MCP over **stdio**. Other local MCP clients can
use the same installed entrypoint; Codex is not required by the server or mod.
Register an absolute executable path in your client's MCP settings. For clients
that use an `mcpServers` JSON object, the equivalent Windows configuration is:

```json
{
  "mcpServers": {
    "dungeondraft": {
      "command": "C:\\absolute\\path\\to\\dungeondraft-mcp\\.venv\\Scripts\\dungeondraft-mcp.exe",
      "args": []
    }
  }
}
```

Configuration filenames and timeout settings vary by client. Allow at least
120 seconds for long exports using your client's tool timeout setting. On
macOS/Linux use the absolute `.venv/bin/dungeondraft-mcp` path; this release's
editor integration is verified only on Windows. Restart or reconnect the MCP
server after registering it or changing tool definitions.

`AGENTS.md` contains usage instructions for agents that support that filename.
For other agents, provide the connection checks and map workflow in their own
instruction mechanism. Instructions do not install tools or start the editor.

### Map creation and application startup

The Python MCP server already runs **outside Dungeondraft**. No additional
Codex TOML settings or second MCP server are needed for the Windows launcher.
Other agents can run the same PowerShell command through their shell tool.

Prepare a blank native map once for each size you need. With the editor closed,
launch a fresh copy (run from the repository root):

```powershell
.\scripts\Start-Dungeondraft.ps1 -MapPath 'C:\maps\blank-30x25.dungeondraft_map' -CopyTo 'C:\maps\encounter.dungeondraft_map' -LogDirectory 'C:\maps\encounter-logs' -ShowWindow
```

`CopyTo` must be new, its parent must exist, and `LogDirectory` must be new or
empty. Both are optional; without `CopyTo` the source map is opened directly.
Use `-ExecutablePath` for a nonstandard installation. The script refuses to
launch while Dungeondraft is running and never closes or kills another instance.
`-ShowWindow` explicitly shows the interactive editor; otherwise it requests a
hidden window. Logs capture stdout/stderr without DungeondraftConsole's Start
button. After launch, verify MCP `ping` and `get_status` before editing.

Startup from a saved template passed on Windows 1.2.0.1; an earlier attempt hit
an intermittent native Mono fatal error. Process launch alone is not readiness,
and the script does not retry crashes automatically. Templates retain their
original dimensions, settings and asset-pack dependencies. New arbitrary sizes
still require manual native creation; no width/height startup arguments exist
in the inspected build.

**[REJECTED]** The private New-dialog prototype created two blank maps cleanly,
but replacement of a populated map raised repeated native object-cleanup
exceptions and a disposed Toolset error. It is removed and is not a tool.
See [CREATION_REVIEW.md](CREATION_REVIEW.md) for test evidence and the decision.

## Configuration

These env vars configure the **Python server** (set them where the MCP client
launches it). The defaults match the mod, so you only need them if you change
the mod's `HOST` / `PORT` consts in `mcp_bridge.gd` — both halves must agree.

| Env var | Default | Purpose |
| --- | --- | --- |
| `DD_BRIDGE_HOST` | `127.0.0.1` | host the server connects to |
| `DD_BRIDGE_PORT` | `8787` | port the server connects to (match the mod's `PORT`) |

## Extending

Adding a capability is symmetric — one handler on each side:

1. **Mod** (`mod/.../scripts/tools/mcp_bridge.gd`): add a `case` to the `match`
   in `_safe_dispatch()` and a `_my_command(req)` function returning
   `_ok(...)` / `_err(...)`.
2. **Server** (`server/dungeondraft_mcp/server.py`): add an `@mcp.tool()` that
   calls `bridge.request("my_command", ...)`.

The mod manifest requires Dungeondraft `1.2.0.1`. Its `dd_version` field is
the minimum accepted version, and this project no longer targets older builds.

### Dev loop (read this before iterating on the mod)

Two things will bite you if you don't know them up front:

- **Editing the mod and the server are different reload paths.** GDScript
  changes in `mcp_bridge.gd` take effect when you **reload the mod inside
  Dungeondraft** (or restart DD). New or changed `@mcp.tool()` definitions in
  `server.py` only appear after the **MCP server process restarts** — restart
  Codex after changing tool definitions.
  The install is editable (`pip install -e`), so you never reinstall; you just
  cycle the process. Adding a *new tool* needs **both** reloads (mod for the
  handler, server for the tool registration); changing an *existing* handler's
  behavior needs only the mod reload.

- **There's no live `eval`/introspect command**, so probing a running node's
  properties needs a mod reload. When a DD API behaves unexpectedly (e.g. a
  setter that doesn't stick), a quick way to diagnose it is to **return
  intermediate state in the response** — stash before/after values in a debug
  field — so one reload shows where a value changes.

## Layout

```
mod/dungeondraft-mcp-bridge/   the Dungeondraft mod (copy into DD's mods folder)
  mcp_bridge.ddmod             manifest
  scripts/tools/mcp_bridge.gd  TCP server + command handlers
server/                        the Python MCP server
  dungeondraft_mcp/server.py   MCP tool definitions
  dungeondraft_mcp/bridge_client.py  TCP/JSON client
  test_bridge.py               standalone per-command smoke test
  demo_build.py                builds a visible sample room and leaves it
PROTOCOL.md                    wire protocol + implementation notes
AGENTS.md                      Codex agent instructions
API_COMPATIBILITY.md           installed-version and API audit
```

## Credits

Maintained by **Filip Smyczek**. Forked from Brandon Florian's MIT-licensed
Dungeondraft MCP project; his original copyright notice remains in [LICENSE](LICENSE).
Built against the [Dungeondraft Modding API](https://megasploot.github.io/DungeondraftModdingAPI/).
Engine is Godot 3.4.2, so the GDScript uses Godot 3 networking class names.

## License

[MIT](LICENSE).
