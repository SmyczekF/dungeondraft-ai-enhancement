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
every behavior of the installed 1.2.0.1 build is unchanged. The installed
program was not running with a map open during this review, so GDScript
handlers, asset loading, screenshots, export timing, undo, and Dungeondraft
1.2.0.1 runtime behavior remain unverified. Run `server/test_bridge.py` on a
disposable map after enabling the mod, then check the commands that the smoke
test intentionally skips.

The [World reference](https://megasploot.github.io/DungeondraftModdingAPI/reference/World/)
defines `CurrentLevelId` as a level ID. `list_levels` now finds its array index
by matching each `Level.ID`, and reports both `current_index` and `current_id`.

The Python MCP side was migrated to the current MCP Python SDK v2 and its 39
tools were registered successfully without connecting to Dungeondraft. The
bridge wire protocol remains v16; the SDK version is independent of the
localhost TCP protocol.
