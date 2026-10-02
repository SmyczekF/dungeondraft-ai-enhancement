# Phase 0 live baseline (Dungeondraft 1.2.0.1)

Run on 2026-10-01 with the installed Dungeondraft 1.2.0.1, MCP bridge protocol 16, Godot 3.4.2, and the Codex-registered Python MCP server. The map open in the editor was 35 x 20 tiles (8960 x 5120 woxels). The [baseline runner](phase0_baseline.py) used a single MCP stdio session; the current `BridgeClient` opened one TCP connection for each tool call.

## Result

The MCP discovered oak, grass, and dirt assets; filled the map with grass; painted a dirt terrain path down its center; placed ten oak objects; listed those ten IDs; captured a screenshot; and exported the full map at 40 PPI. [Open the exported preview](examples/phase0-sample.png). The final `get_status` reported `objects: 10` and zero drawn path elements. The dirt route is terrain paint, so it is not counted among drawn `Path` objects.

Temporary benchmark props were deleted after each measurement. The live sample objects had IDs 260-269. These are session IDs, not stable semantic IDs. The Phase 0 bridge could not save through MCP. A later manual native save exposed a persistence defect: the saved map had zero objects although the live editor and PNG showed ten trees. Dungeondraft skips objects marked `preview` during save; the Phase 1 bridge clears that marker. A 2026-10-01 live retest saved and reopened ten trees with matching IDs and assets.

| Temporary trees | Place time | Mean per `place_object` | Delete time |
| ---: | ---: | ---: | ---: |
| 10 | 0.268 s | 26.8 ms | 0.285 s |
| 50 | 1.433 s | 28.7 ms | 1.450 s |
| 200 | 5.534 s | 27.7 ms | 5.235 s |

These are one-run measurements on this PC, not a performance guarantee. For comparison, ten separate MCP server sessions, each placing and deleting one temporary tree, took 13.969 s total (1.397 s per session pair). One persistent MCP session handled the ten-place/ten-delete test in 0.553 s. Most of the separate-session cost is process/session setup, while the current per-object editor cost still accumulates. Phase 2 should repeat these measurements after native batching is added.

## Verification and limits

- **Passed:** Bridge connection and protocol; map status; asset discovery; 10/50/200 object creation and cleanup counts; grass fill; terrain path; exact ten-tree object list; screenshot; 1400 x 800 PNG export.
- **Passed native save/reopen:** the Phase 1 bridge cleared Dungeondraft's `preview` marker, saved ten trees in native JSON, and reopened the map through MCP.
- **Passed IDs and assets after reopen:** IDs 0–9 and their oak asset paths matched before and after reopening in the live retest.
- **Not covered:** wall, roof, portal, cave, undo, multi-level, large-map, and Foundry behavior. Do not infer those from this baseline.

## Review

1. Open [the exported PNG](examples/phase0-sample.png) and check the center dirt path, grass field, and five oak trees on each side.
2. Treat the PNG as visual evidence only. The Phase 0 native file omitted the objects and is not a valid editable sample.
3. Read the tool/bridge behavior notes in [PROTOCOL.md](PROTOCOL.md) and the runtime scope in [API_COMPATIBILITY.md](API_COMPATIBILITY.md).
4. To repeat the measurements, open a **disposable blank map** in Dungeondraft with the MCP mod enabled, then run `\.venv\Scripts\python.exe .\phase0_baseline.py --output-dir <output-directory>` from the repository root. The runner refuses a map with existing elements, cleans benchmark props, and leaves the final ten-tree sample open.

Phase 1 implements open/save and the persistence correction. Its live save/reopen test closed the Phase 0 durability retests. New blank maps are created manually in Dungeondraft.
