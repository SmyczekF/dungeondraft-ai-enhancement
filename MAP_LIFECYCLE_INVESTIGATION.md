# Map creation and external lifecycle investigation

Date: 2026-10-02. Installed Dungeondraft: 1.2.0.1.

## Findings

1. An external Windows process can launch, monitor, capture logs from, and stop Dungeondraft. Opening a saved map at process startup was already verified during Phase 1. Windows registers `Dungeondraft.exe "%1"` as the native map opener. Launch the editor directly; DungeondraftConsole.exe is a graphical launcher that requires its Start button.
2. The inspected application startup method calls `OS.GetCmdlineArgs()`, accepts exactly one application argument ending in `.dungeondraft_map`, and calls `Editor.ForceOpenMap(path)`. It contains no branch for creating a map from width/height arguments.
3. The native `NewWindow` confirmation callback checks `Master.IsEditing`. When false, it calls `Master.CreateNewMap(width, height)`. When true, it constructs `NewMapOnStart`, records dimensions and settings in `Master.MapOnStart`, and calls `Global.Restart()`.
4. `Global.Restart()` clears exporter subscriptions, sets `IsEditing=false` and `IsRestarting=true`, clears the mod manager, and reloads the current Godot scene. It does not restart the Windows process.
5. The newly loaded `Master._Ready()` executes and clears `MapOnStart`. `NewMapOnStart.Execute()` invokes native creation and applies wizard/shadow/wear settings.
6. Our earlier direct in-mod creation call bypassed this native reset sequence. This strongly supports the user's state-related hypothesis, especially for the duplicate DESIGN toolbar error. It does not establish the cause of every previously observed native crash.
7. Tool mods are loaded after a map loads, not at the welcome screen. Therefore a fresh process without a map has no bridge endpoint through which the external server can invoke native creation.

## Feasibility

| Approach | Result |
| --- | --- |
| Restart editor and open an existing native file | Feasible; startup opening already verified |
| Copy a native blank template and launch its copy | Feasible for prepared template sizes; templates must exist first |
| Restart editor and pass new-map dimensions on the command line | No such application argument handling found in this installed build |
| Reproduce native pending-request/scene-reset workflow inside bridge | Promising investigation candidate; not yet implemented or live tested |
| Invoke native New dialog controls/confirmation programmatically | Potentially possible without mouse input, but depends on private UI implementation; not a clean public creation API |

`NewMapOnStart` is a managed object implementing `IMapOnStart`, not an exposed Godot node. Its construction and the assignment of a managed request to the static `Master.MapOnStart` field are not documented GDScript mod APIs. A clean bridge entry point for that workflow remains to be established. Calling private UI handlers or injecting code would introduce implementation coupling and should not be presented as a supported solution.

## Recommended placement

The existing Python MCP server already runs outside Dungeondraft. Put process lifecycle functions there, with application path validation, save/discard handling, captured logs, and bounded readiness checks. A second MCP server or PowerShell wrapper is optional packaging, not required architecture.

Codex `config.toml` registers that MCP process; the server defines its tools. `AGENTS.md` can document the workflow but cannot provide a Dungeondraft startup API.

## Evidence and scope

- Read-only inspection of the installed managed assembly: application startup, `NewWindow` confirmation, `Global.Restart`, `Master._Ready`, and `NewMapOnStart.Execute`. Local inspection artifacts are retained outside this repository; proprietary binaries and disassembly are not distributed.
- Existing repository `API_COMPATIBILITY.md`: earlier live failure and successful save/open checks.
- No Computer Use, app restart, map modification, or new creation runtime test was performed in this investigation. A fresh-start MCP creation test cannot currently be dispatched because the bridge does not exist before the first map loads.

Sources: [Dungeondraft scripting lifecycle](https://megasploot.github.io/DungeondraftModdingAPI/Scripting/), [Editor API](https://megasploot.github.io/DungeondraftModdingAPI/reference/Editor/), [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli), [AGENTS.md instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

## Follow-up: live reachability and regression diagnosis

The read-only GDScript probe confirmed that `CreateNewMap` and `Global.Restart`
are callable, but `Master.MapOnStart` is not an exposed property and
`ClassDB.class_exists("NewMapOnStart")` is false. The managed pending request
cannot be constructed through this inspected Godot interface. The New dialog
does expose private width/height widgets and its confirmation callback.
The user authorized a disposable prototype of that route only. Runtime
validation is pending a manual mod reload; this is not a published MCP tool.

Live retesting also exposed two bridge bugs independently of map creation:

- `SelectTool.EnableTransformBox(true)` requires widgets initialized by the
  native tool activation lifecycle. The bridge now uses documented
  `Toolset.Quickswitch("SelectTool")` before selecting elements.
- Detaching and reattaching an existing `Prop` for undo/redo does not restore
  its native search-table registration and recreates its render children.
  Object creation undo now saves native data and retires the old node; redo
  uses `Objects.LoadObject` to restore a fresh node with the same ID.
  Deletion deselects the node first.

Three reported native pointer errors after the functional regression have a
strong code-level explanation: `Infobar.OnSaveEnd` schedules a callback two
seconds later that changes one visibility flag and two colors. Automatically
reopening immediately after file creation can free those widgets before the
callback. The reported native call signatures match those three operations.
This attribution still needs console confirmation from the revised live save.

**[PLAN CHANGED]** `save_map` validates complete native JSON and keeps the
current scene. Automatic reopening and `verify_reopen` were removed. A separate
`open_map` call can verify reload durability after the native save notification
finishes. We have not added a fixed delay or a private UI completion probe to
the production save tool. `phase1_smoke.py` explicitly pauses for human console
and save-notification review before its two reopen checks.

The revised live save wrote a valid 187,130-byte blank native file, kept the
same bridge instance, and preserved empty element counts. No new client config
settings or application lifecycle tools were added.

## Fresh-start crash while preparing the prototype (2026-10-02)

The user reported a native `CowData<wchar_t>::get` fatal error: index 12,
size 11. Windows Application event 1000 confirms a fresh Dungeondraft 1.2.0.1
process (PID 16416) crashed at 10:17:43, exception `0x80000003`, executable
offset `0x8ad68e`. The recent Mono logs are empty and the Windows event has no
calling stack. The complete console context and exact first-map stage are
still needed; the failure has not been attributed to a specific bridge call.

No prototype creation request was sent by the agent. The uncommitted probe was
present in the active mod folder during the reported startup. Its `start()`
only starts a diagnostic listener; the private New callback requires a later
explicit disposable-map request. Thus this is not a failed test of that
callback, and does not prove that route works or fails.

The probe and generated reachability report were archived outside the repository
and removed from the active mod folder. Only the committed `mcp_bridge.gd`
remains. **[PLAN CHANGED]** Suspend creation experimentation until a manual
first-map load succeeds with that baseline and the console is reviewed.
If it still fails, isolate the published bridge from a fresh run with the MCP
disabled before changing production code. The missing override-tags warning
has not been established as the cause.

Further native inspection explains the unsuccessful earlier probe reload:
`ModManager.Reload` reloads existing scripts with `keep_state=true`, without
calling `start()` or discovering newly added script files. Source-only handler
changes can reload; new startup logic must be tested in a fresh process.
This corrects the earlier instruction to load the new listener through Reload
Mods. It does not explain the native bounds failure.

## Second baseline failure and no-mod control (2026-10-02)

With the temporary probe removed, the user reported a different fatal error:
`Condition "!klass" is true` in `GDMonoInternals::tie_managed_to_unmanaged`.
Windows event 1000 records fresh editor PID 26412 crashing at 10:29:22 with
exception `0x80000003`, executable offset `0x45cdcf`. Its Mono log is empty.
The console launcher was still PID 9212, started at 09:07:10; the editor itself
was new. Restarting the launcher clears the captured output but is not yet a
proven fix.

The identical fatal text exists in the earlier `phase1-no-mod-error.log`
control with all mods disabled. That proves this symptom can occur without
MCP; it does not establish the root cause of this particular crash or exclude
additional bridge faults.

The editor is closed. Active mods were temporarily changed from MCP only to
`active_mods=[]`, with the original configuration preserved byte-for-byte in
`C:\Users\smycz\Documents\ChatGPT\Dungeondraft\crash-2026-10-02\config-before-mono-isolation.ini`.
The user was asked to close the old launcher, start a fresh console launcher,
and manually create one blank map. The result is pending. Restore that backup
after the control test; the disabled setting is an investigation state on this
PC, not a project distribution change. A mod discovery line is not proof that
the mod is enabled. No application was started or stopped by the agent.

### No-mod control result

The user restarted the console launcher and reported successful manual blank-map
creation with no new console errors. The fresh editor is PID 9740, started at
10:33:20; the new console launcher is PID 7972, started at 10:33:19. The saved
configuration still shows `active_mods=[]`.

This is one successful control with two changed conditions (fresh launcher,
MCP disabled), not proof of a particular cause or fix. The next comparison is
the same fresh-launch/manual-first-map workflow with the original MCP setting
restored. The user has been asked to close both programs before restoration,
so the running editor cannot overwrite restored settings on exit. Restoration
and the MCP-enabled comparison are pending. Preserve other newly saved editor
preferences when restoring the original active-mod line from the backup.

The user subsequently closed both applications. The original MCP-only active-mod
line was restored from the backup and read back successfully. All other current
editor preferences were verified unchanged. The temporary prototype remains
absent. The user has been asked to repeat the fresh-console first-map test with
MCP enabled and leave the disposable map open; that comparison remains pending.

### Matching MCP-enabled control and save regression

The user-created fresh 35 x 20 map with MCP enabled succeeded without new console
errors. Editor PID 26048 and console PID 10604 are fresh. Live protocol 18 ping,
map status and inspection passed. The regression started with no active tool;
selection activated SelectTool correctly. Three object undo/redo cycles,
duplicate restoration, selected-object deletion and rendered equality passed.
The user confirmed a clean console after these operations. The recreated PNG
matches the original SHA-256
`7a6a13fccb466f2ee523bfd71712b3e0f0cac0ee593c955612f650306b11bf52`.

Saving through `Editor.SaveMap(false)` failed silently: no native file appeared
within 60 seconds and the console showed no new error. The bridge stayed alive
on the same instance, with zero remaining objects. Therefore the one-argument
save call is not accepted, despite the published documentation. The installed
managed method declares an additional Action argument; the precise silent-failure
mechanism has not been established.

A narrow alternative is staged for manual handler reload: validate the
published `Editor.saveButton`, then emit its public `pressed` signal after
setting the explicit native path. This enters the normal native managed save
flow without passing a delegate across the GDScript boundary. It uses no mouse
or keyboard input and no private dialog fields. Runtime save validation is
pending; it must succeed and remain console-clean before acceptance.

References: [published Editor properties](https://megasploot.github.io/DungeondraftModdingAPI/reference/Editor/)
and [Godot 3.4 BaseButton signal](https://docs.godotengine.org/en/3.4/classes/class_basebutton.html#signals).


### Save signal accepted; creation experiment still pending

The user restarted the editor, created a blank 35 x 20 map, reloaded mods and
reported no startup errors. Live protocol 18 ping and status passed on editor
PID 25848. The public save signal wrote a valid 187,130-byte native file without
changing the bridge instance. `history_regression.py` then passed selection
from no active tool, three object undo/redo cycles, exact descriptor restoration,
duplicate cleanup, selected-object deletion, rendered equality and native saving
without scene replacement. A fresh MCP stdio client exposed 45 tools and saved
the current native file successfully; `verify_reopen` is absent from its schema.
The user confirmed no new console errors after all of those tests.

Artifacts are in
`C:\Users\smycz\Documents\ChatGPT\Dungeondraft\history-regression-native-save-signal-2026-10-02`:
`report.json`, `before-undo.png`, `undone.png`, `after-redo.png`, and
`cleaned.dungeondraft_map`. The map remains open with zero elements.

This accepts the save entry point and history fixes, not a native startup-crash
fix. Both no-mod and MCP-enabled fresh launches have now passed, and the precise
cause of the earlier native fatal errors remains unclassified. The temporary
creation probe is absent; no private New callback has been tested.

A verified follow-up gap remains: `get_map_info` still reports
`bridge_dirty=true` after the saved bridge edits. Saving preserves the undo
stack, and the current flag is only cleared by a reload. Track a verified save
checkpoint independently of undo history before treating this field as an
accurate unsaved-changes indicator. No new client configuration is required.

## Final creation decision (2026-10-02)

The private callback was finally dispatched. Blank 35x20 -> 24x18 -> 20x16
switches passed, rejected invalid requests without switching, reconnected with
new bridge instance IDs, and retained the same Windows process. Editing,
selection, three undo/redo cycles, byte-identical render restoration and native
saving passed on the created map. The user confirmed clean console output.

The next fresh-session test populated all eight kinds: ten trees, one wall,
one path, one light, mounted/free portals, roof, pattern and text; two trees were
selected. Replacement produced and saved a correctly sized blank 24x17 file,
but the user reported repeated `ArgumentOutOfRangeException` in
`World.get_Level -> Prop._ExitTree`, `Node ID 10 does not exist`, and
`ObjectDisposedException` in `Toolset.Shrink`. Functional reconnection is not
acceptance. **[REJECTED]** Shipping this private creation adapter. The probe is
removed; no protocol/tool changes or editor patches are accepted.

An external fresh-process launch of a copy of the saved blank 20x16 template
was tested with stdout/stderr capture. The first launch hit native `!klass`
startup fatal; a second fresh launch opened the exact path and exposed protocol
18, zero elements and the correct dimensions with empty stderr. The launcher
is useful for prepared templates but cannot guarantee native startup reliability
or create dimensions. It does not kill other instances or retry automatically.
See [CREATION_REVIEW.md](CREATION_REVIEW.md) and README for the accepted workflow.

## Verified save checkpoint (2026-10-02)

Protocol 19 / package 0.2.3 keeps 45 MCP tools. The native save request captures
the current bridge undo-branch identity and non-recorded edit revision. After
native JSON validation, the Python client confirms that save token. Undo/redo
can return to the saved state without clearing history; later edits remain
dirty, and non-recorded deletion cannot be erased by undoing a different edit.
Stale confirmations fail. Manual UI saves are not checkpoint confirmation.
`save_checkpoint_regression.py` passed all live transitions and scene preservation;
a fresh MCP client saved successfully. DungeondraftConsole showed the protocol
19 listener with no script/runtime errors after testing. The test left a saved
empty disposable map. Native editor dirty state remains independently reported.
