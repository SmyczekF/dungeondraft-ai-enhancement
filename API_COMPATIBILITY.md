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
checks have now verified the specific operations below. Commands outside this
list, including native map lifecycle (which is not implemented), remain
unverified. See [PHASE0_BASELINE.md](PHASE0_BASELINE.md) for measurements and
review steps.

The [World reference](https://megasploot.github.io/DungeondraftModdingAPI/reference/World/)
defines `CurrentLevelId` as a level ID. `list_levels` now finds its array index
by matching each `Level.ID`, and reports both `current_index` and `current_id`.

The Python MCP side uses MCP Python SDK v2 and exposes 39 tools. On the running
Dungeondraft 1.2.0.1 instance, an MCP client completed `ping` (bridge protocol
v16, Godot 3.4.2), `get_status`, `list_assets`, `place_object`, `delete_element`,
`list_elements`, `fill_terrain`, `paint_path`, `screenshot`, and `export_map`.
The grass/path/ten-tree sample exported as a 1400 x 800 PNG at 40 PPI. The
bridge wire protocol remains v16; the SDK version is independent of the
localhost TCP protocol.

The live map contained exactly ten objects after the test, with IDs 260-269.
Terrain-painted paths are stored in terrain splat data, so `get_status.counts.paths`
stayed at zero; that count refers to drawn `Path` elements. A native map file
could not be saved or reopened through MCP because there are no map lifecycle
commands yet. The live editor content is therefore not a durable test artifact.
