# Dungeondraft 1.2.0.1 API review

Reviewed against the installed `C:\Program Files\Dungeondraft\Dungeondraft.exe`
(Windows file and product version `1.2.0.1`) and the published
[Dungeondraft Modding API](https://megasploot.github.io/DungeondraftModdingAPI/).
The mod manifest now requires `1.2.0.1`; `dd_version` is a minimum version in
the mod format. The documented modding API does not expose the running product
version. An attempted `Global.BuildString` lookup returned null, so
`get_capabilities` reports the Godot engine version and omits the unavailable
Dungeondraft build rather than presenting `"Null"` as a version.

| Bridge use | Published API | Status |
| --- | --- | --- |
| Tool script `start()` and `Global.Editor.Toolset.CreateModTool` | [Scripting](https://megasploot.github.io/DungeondraftModdingAPI/Scripting/), [Globals](https://megasploot.github.io/DungeondraftModdingAPI/Globals/) | Signatures match |
| `Global.World.GetCurrentLevel`, `AssignNodeID`, `GetNodeByID`, `DeleteNodeByID`, `SetLevel` | [World](https://megasploot.github.io/DungeondraftModdingAPI/reference/World/) | Signatures match |
| `Level` collections and `CreateFreestandingPortal` | [Level](https://megasploot.github.io/DungeondraftModdingAPI/reference/Level/) | Signatures match |
| `Wall.AddPortal` and `RemakeLines` | [Wall](https://megasploot.github.io/DungeondraftModdingAPI/reference/Wall/) | Signatures match |
| `Global.Exporter.Start(0, ppi, path)` | [Exporter](https://megasploot.github.io/DungeondraftModdingAPI/reference/Exporter/) | Signature and PNG mode match |

The published reference describes the core API but does not establish that
every behavior of the installed 1.2.0.1 build is unchanged. Phase 0 runtime
checks verified the operations below. Phase 1 live checks verified asset
metadata, pagination, native save, reopening, and PNG export.
See [PHASE0_BASELINE.md](PHASE0_BASELINE.md) for measurements and review steps.

The [World reference](https://megasploot.github.io/DungeondraftModdingAPI/reference/World/)
defines `CurrentLevelId` as a level ID. `list_levels` now finds its array index
by matching each `Level.ID`, and reports both `current_index` and `current_id`.

The Python MCP side uses MCP Python SDK v2 and exposes 45 tools in the Phase 1
source. On the running
Dungeondraft 1.2.0.1 instance, an MCP client completed `ping` (bridge protocol
v16, Godot 3.4.2), `get_status`, `list_assets`, `place_object`, `delete_element`,
`list_elements`, `fill_terrain`, `paint_path`, `screenshot`, and `export_map`.
The grass/path/ten-tree sample exported as a 1400 x 800 PNG at 40 PPI. The
Phase 0 used wire protocol v16; Phase 1 uses v18. The SDK version is independent of the
localhost TCP protocol.

The live map contained exactly ten objects after the test, with IDs 260-269.
Terrain-painted paths are stored in terrain splat data, so `get_status.counts.paths`
stayed at zero; that count refers to drawn `Path` elements. A native map file
could not be saved or reopened through MCP during Phase 0. A manual native save
was subsequently found to contain zero objects: Dungeondraft's object serializer
skips nodes with its `preview` marker. The Phase 1 bridge clears that marker on
created objects, paths, and lights, then verifies save/reopen by default. A
2026-10-01 live retest saved ten oaks in native JSON, then reopened the map
through MCP with the same ten IDs and asset paths. The exported PNG showed the
center dirt path and five oaks on each side.

## Phase 1 API investigation

The installed 1.2.0.1 assembly exposes `Master.CreateNewMap(int, int)`,
`Master.Save(string, Action)`, and `Editor.ForceOpenMap(string)`. Their presence
does not prove they are safe from every editor state. `Master.CreateNewMap` raised
native editor exceptions when invoked from the active bridge, including a
duplicate `DESIGN` toolbar error, and the new bridge instance never started.
The `create_map` command was removed. The documented `Editor.ForceOpenMap`
successfully reopened a saved sample; the bridge releases its listener before
that scene reload. `save_map` checks native JSON without reopening.
Reopen is a separate action after the native save notification finishes.

The official [scripting lifecycle](https://megasploot.github.io/DungeondraftModdingAPI/Scripting/)
loads tool mods only after a map finishes loading. **[PLAN CHANGED]** A user
must create each new blank map in Dungeondraft. The bridge can reopen existing
native maps through MCP. The public [Editor API](https://megasploot.github.io/DungeondraftModdingAPI/reference/Editor/)
documents `ForceOpenMap`, but has no direct new-map method.

## Map reload and port ownership

Godot error 22 is `ERR_ALREADY_IN_USE`. UI New Map reproduced the port conflict
on 2026-10-02: the previous native TCP listener remained alive after Editor
replacement. The final bridge stores the native TCP_Server instance ID on
Godot's Engine singleton and stops that listener before binding a new one.
Editor metadata did not survive replacement, and resolving managed mod-script
instances produced Mono method-lookup errors. Two consecutive UI New Map
switches now returned responsive protocol 18 bridges without bind conflicts.
Reload Mods also passed. Unrelated processes owning port 8787 still cause a
logged bind failure.

Earlier loading failures included reserved locals `master` and `tool`, plus
the invalid `TYPE_POOL_VECTOR2_ARRAY` global. They were fixed to `master_node`,
`pattern_tool`, and `TYPE_VECTOR2_ARRAY`. The Godot 3 syntax gate does not check
engine global constants, so live startup remains a separate acceptance check.

Two later crashes after the listener change showed the same native fault
offset (`0x13e07ca`). This does not support treating the port handoff as a
crash fix. A subsequent manual New Map test succeeded with no mods and with
only this mod enabled, but the bridge was not listening in the latter test.
UI New Map does not call the bridge's former MCP `create_map` command, so the
manual crash reports and the MCP map-switch failure are separate observations.
The MCP path failed with native editor exceptions, while the bridge's ordinary
commands, save, and open passed after the syntax corrections.

The 2026-10-02 UI New Map test created the blank map but logged native
`System.ArgumentOutOfRangeException` in `World.get_Level` / `Prop._ExitTree`
while unloading the populated sample. The same action reproduced that error
with all mods disabled. An intermittent `GDMonoInternals::tie_managed_to_unmanaged`
fatal startup error also occurred with mods disabled; the next launch succeeded.
These findings separate native runtime failures from the fixed bridge listener
conflict; they do not establish the cause of every earlier access violation.
Use a fresh editor session after native exceptions. Patching Dungeondraft's
executable is outside this project's plan.

## Phase 1 descriptor verification

All eight descriptor kinds passed native save/reopen, exact ID/asset checks,
pagination and individual lookup on protocol 18. Patterns must be enumerated
with documented [GetShapes](https://megasploot.github.io/DungeondraftModdingAPI/reference/PatternShapes/),
since collection children are layer containers. Their public `_Texture` getter
in the installed assembly holds the shader-backed asset; Polygon2D.texture
does not. The [SelectTool enum](https://megasploot.github.io/DungeondraftModdingAPI/reference/SelectTool/)
uses 2 for free portals and 3 for mounted portals. Free-door sprite rectangles
are transformed into world space. Light bounds use Godot 3's
[Light2D offset and texture_scale](https://docs.godotengine.org/en/3.4/classes/class_light2d.html).
The expanded `phase1_smoke.py` covers two pattern shapes in one layer and both
door kinds to catch collection/count and classification regressions.

## Native creation reset investigation (2026-10-02)

Read-only inspection found that the built-in New Map callback checks
`Master.IsEditing`. For an open map it queues `NewMapOnStart` in `Master.MapOnStart`
and invokes `Global.Restart`, which reloads the scene after clearing editor/mod
state. `Master._Ready` executes the pending request. With no map open the callback
calls `Master.CreateNewMap` directly. The earlier bridge command bypassed the
native reset path; this supports a state-related explanation for the duplicate
toolbar error but does not fix populated teardown. The tested private callback
created 24x18 and 20x16 blank maps cleanly; a mixed populated replacement logged
repeated `World.get_Level` / `Prop._ExitTree` exceptions and disposed
`Toolset.Shrink`. It is rejected and removed. Startup opening of a prepared
native template passed, with the previously observed intermittent Mono startup
fatal also occurring on a preceding attempt. See
[MAP_LIFECYCLE_INVESTIGATION.md](MAP_LIFECYCLE_INVESTIGATION.md).

## Save callback boundary follow-up

A later console review reported `Attempted to convert Variant to an
unmarshallable managed type: Action` during the direct `Master.Save(path, null)`
call. The subsequent documented `Editor.SaveMap(false)` experiment produced
no native file and no console error. Its optional managed delegate argument is
not a reliable GDScript boundary in the installed build; this direct call is
not accepted.

The bridge validates the published `Editor.saveButton` and emits its
native `pressed` signal after assigning and checking `CurrentMapFile`. Native
inspection confirms its managed callback waits one frame, then calls
`SaveMap(false, null)` entirely within C#. This avoids GDScript delegate
conversion and uses public mod properties and Godot signals. No input events
or private dialog fields are involved. Live saving, the focused rendered
history regression, and a fresh MCP client save passed; the user confirmed no
new console errors. Saving preserves the scene and bridge history. See the
lifecycle investigation for the test artifacts and remaining dirty-state issue.

Automatic reopening was also removed because the native save status schedules
a delayed widget callback. The focused regression and save contract changes
are described in PHASE1_REVIEW.md. The temporary creation prototype is not a
published MCP tool and requires the user's manual fresh session before testing.
