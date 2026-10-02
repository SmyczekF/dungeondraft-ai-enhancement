# Phase 2 review: native batch edits

Accepted on 2026-10-02 with Dungeondraft 1.2.0.1 / Godot 3.4.2, protocol 20,
package 0.3.0. The editor was started through DungeondraftConsole.exe, then
loaded a blank 24x17 disposable map. All map edits used the bridge.

## Results

| Trees | Phase 0 individual requests | Native batch, internal polling |
| ---: | ---: | ---: |
| 10 | 0.268 s | 0.184 s |
| 50 | 1.433 s | 0.268 s |
| 200 | 5.534 s | 0.951 s |

One run on this PC; different map sizes and warmed assets. Timing is not a
performance guarantee. The batch reduces model calls to one; editor placement
cost remains. Maximum object execution slice was 2.348 ms in this run. Terrain
painting can exceed the 8 ms scheduling budget within a single operation.

Passed full preflight with indexed errors and zero changes; all returned IDs;
same-key replay without duplication; conflicting-key rejection; responsive ping
and progress; concurrent MCP edit rejection; object cancellation (20 completed
operations rolled back); mixed terrain/wall/path/light/free-portal cancellation
(21 operations rolled back). Before/after terrain PNGs were byte-identical:
`f0b4b2f480c95582e916658208f21e054708363fdc261161850a50352ab044fd`.

The sample contains 50 trees flanking a dirt road, plus wall/path/light/free portal.
Native sample save: 128483 bytes, valid JSON. Cleanup save: 111960 bytes.
Save checkpoint regression passed after batching. A fresh stdio MCP client
exposed 48 tools, applied/retried a batch, cleaned it, and saved the same scene.
Console screenshots showed no new script/native exceptions, only the preexisting
missing override tags warning. Full Godot 3 syntax parse passed.

## Review / reproduce

Run `phase2_smoke.py --output-dir <new-directory>` with the repository virtual
environment on a disposable blank map. It writes `report.json`, `sample.png`,
`sample.dungeondraft_map`, cancellation previews, and a cleaned native map.
Keep DungeondraftConsole.exe visible and inspect native errors after the run.
The script cannot detect every native exception through bridge responses.

Local reviewed output: `phase2-acceptance-v3-2026-10-02` in the task workspace.
Open `sample.png` to inspect the road and tree layout. The acceptance sample is
a batch proof, not a finished tactical map; deterministic spacing is Phase 3.

## Scope

Jobs are retained only in the current bridge instance, limited to 64. Keep the
same key after uncertainty; don't retry across a new instance blindly. Leave
native UI unchanged during execution. Only the documented reversible subset
is allowed. Mounted portals and irreversible operations are excluded.
Expanded terrain-slot restoration uses the API but has not been tested live.
Cancellation exercises the rollback path; forced native engine faults are not
recoverable or injected as an acceptance test.
