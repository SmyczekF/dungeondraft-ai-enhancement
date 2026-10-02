# Creation follow-up review

Date: 2026-10-02. Dungeondraft 1.2.0.1 / Godot 3.4.2.

## Acceptance and decision

| Test | Functional result | Native console | Decision |
| --- | --- | --- | --- |
| Blank 35x20 -> 24x18 | Dimensions, zero elements, reconnection; same process | Clean (user reviewed) | Prototype check passed |
| Blank 24x18 -> 20x16 | Repeatability and new bridge instance | Clean (user reviewed) | Prototype check passed |
| Edit/render/save after creation | Selection, three object undo/redo cycles, exact PNG restoration, valid native save | Clean (user reviewed) | Prototype check passed |
| Populated mixed map -> 24x17 | Correct blank map, new instance, valid native dimensions | Repeated Prop cleanup and disposed Toolset exceptions | Failed acceptance |
| Windows native-template startup | First attempt crashed; second opened copied 20x16 map with zero elements and protocol 18 | First: native Mono !klass fatal; second: empty stderr | Useful template workflow, native startup limitation retained |

**[REJECTED]** The private New-dialog creation command is not shipped. The
callback follows the real native reset workflow, but populated teardown still
raises native exceptions. It also couples to private controls. No direct creation
fallback, native-file dimension rewriting, injected code, or pre-deletion of
content is used to hide those failures. The active mod contains only the
production bridge; protocol 18 and 45 MCP tools remain unchanged.

**[PLAN CHANGED]** Prepare native blank templates for required sizes once.
Use `scripts/Start-Dungeondraft.ps1` to open a new copy in a fresh editor, then
check ping/status and perform map generation through MCP. Arbitrary new sizes
remain a manual native action. The launcher is a shell helper, not an MCP tool;
no Codex configuration changes are required. It does not automatically retry or
close another process. Native startup may fail independently of the bridge.

## Review evidence

Local artifacts (not distributed):
`C:/Users/smycz/Documents/ChatGPT/Dungeondraft/`.

- `creation-prototype-24x18-2026-10-02.json`
- `creation-prototype-20x16-2026-10-02.json`
- `creation-prototype-populated-2026-10-02.json` (functional checks passed, acceptance failed)
- `history-after-native-creation-2026-10-02/report.json` and before/undo/redo PNGs
- `creation-prototype-24x17-2026-10-02.dungeondraft_map`
- `external-launch-2026-10-02.dungeondraft_map`
- `external-launch-logs-2026-10-02/` (fatal) and `external-launch-logs-second-2026-10-02/` (successful)

Review the launcher and README usage. Its running-editor refusal and syntax
passed; launch/readiness were tested separately. A returned PID does not prove
the map loaded. The created template copy had the expected path, dimensions,
one level and empty counts. The rejected integration draft was never applied.

Next: saved-edit checkpoint correction and Phase 2 native batching. The earlier
intermittent startup-fatal root cause remains unknown; it is not a roadmap gate
for map editing in a verified responsive session.
