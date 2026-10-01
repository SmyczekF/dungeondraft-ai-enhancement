# Dungeondraft 1.2.0.1 API review

Reviewed against the installed `C:\Program Files\Dungeondraft\Dungeondraft.exe`
(Windows file and product version `1.2.0.1`) and the published
[Dungeondraft Modding API](https://megasploot.github.io/DungeondraftModdingAPI/).
The mod manifest now requires `1.2.0.1`; `dd_version` is a minimum version in
the mod format.

| Bridge use | Published API | Status |
| --- | --- | --- |
| Tool script `start()` and `Global.Editor.Toolset.CreateModTool` | [Scripting](https://megasploot.github.io/DungeondraftModdingAPI/Scripting/), [Globals](https://megasploot.github.io/DungeondraftModdingAPI/Globals/) | Signatures match |
| `Global.World.GetCurrentLevel`, `AssignNodeID`, `GetNodeByID`, `DeleteNodeByID`, `SetLevel` | [World](https://megasploot.github.io/DungeondraftModdingAPI/reference/World/) | Signatures match |
| `Level` collections and `CreateFreestandingPortal` | [Level](https://megasploot.github.io/DungeondraftModdingAPI/reference/Level/) | Signatures match |
| `Wall.AddPortal` and `RemakeLines` | [Wall](https://megasploot.github.io/DungeondraftModdingAPI/reference/Wall/) | Signatures match |
| `Global.Exporter.Start(0, ppi, path)` | [Exporter](https://megasploot.github.io/DungeondraftModdingAPI/reference/Exporter/) | Signature and PNG mode match |

The published reference describes the core API but does not establish that
every behavior of the installed 1.2.0.1 build is unchanged. Phase 0 runtime
checks verified the operations below. Phase 1 lifecycle, catalog, and geometry
commands are implemented but still require a live reload and integration test.
See [PHASE0_BASELINE.md](PHASE0_BASELINE.md) for measurements and review steps.

The [World reference](https://megasploot.github.io/DungeondraftModdingAPI/reference/World/)
defines `CurrentLevelId` as a level ID. `list_levels` now finds its array index
by matching each `Level.ID`, and reports both `current_index` and `current_id`.

The Python MCP side uses MCP Python SDK v2 and exposes 46 tools in the Phase 1
source. On the running
Dungeondraft 1.2.0.1 instance, an MCP client completed `ping` (bridge protocol
v16, Godot 3.4.2), `get_status`, `list_assets`, `place_object`, `delete_element`,
`list_elements`, `fill_terrain`, `paint_path`, `screenshot`, and `export_map`.
The grass/path/ten-tree sample exported as a 1400 x 800 PNG at 40 PPI. The
bridge wire protocol remains v16; the SDK version is independent of the
localhost TCP protocol.

The live map contained exactly ten objects after the test, with IDs 260-269.
Terrain-painted paths are stored in terrain splat data, so `get_status.counts.paths`
stayed at zero; that count refers to drawn `Path` elements. A native map file
could not be saved or reopened through MCP during Phase 0. A manual native save
was subsequently found to contain zero objects: Dungeondraft's object serializer
skips nodes with its `preview` marker. The Phase 1 bridge clears that marker on
created objects, paths, and lights, then verifies save/reopen by default. This
fix is **pending a live durability retest**. The Phase 0 live editor content and
PNG alone do not prove native persistence.

## Phase 1 API investigation

The installed 1.2.0.1 assembly exposes `Master.CreateNewMap(int, int)`,
`Master.Save(string, Action)`, and `Editor.ForceOpenMap(string)`. A disposable
runtime probe confirmed those native methods can be called from a mod. The
bridge now schedules create/open after acknowledging the socket request and
releases its listener before Dungeondraft reloads the mod. The Python tool waits
for a new bridge instance and checks the requested size or path. `save_map`
checks native JSON, then reopens and compares element counts by default.

The official [scripting lifecycle](https://megasploot.github.io/DungeondraftModdingAPI/Scripting/)
loads tool mods only after a map finishes loading. **[PLAN CHANGED]** A user must
open or create the first map after launching Dungeondraft; subsequent map
creation and opening can use MCP once the bridge is active. This is an app
startup constraint, not an unimplemented bridge command.
