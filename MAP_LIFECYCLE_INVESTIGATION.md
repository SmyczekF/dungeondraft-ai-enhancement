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
