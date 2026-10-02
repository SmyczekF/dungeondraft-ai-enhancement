# Phase 3 review: structured encounter generation

Accepted on 2026-10-02 with Dungeondraft 1.2.0.1 / Godot 3.4.2, protocol 21,
package 0.4.0. Fresh DungeondraftConsole.exe session, manually created blank
24x17 map. Map construction used MCP tools only.

## Evidence

- Nine pure-layout tests passed: repeatability/seed variation, unit conversion,
  exact tree count/IDs, spacing, protected spaces/margins, schema rejection,
  explicit fallback, impossible density, region clipping, deep-water crossing
  requirement and building-door route connectivity.
- Fresh MCP stdio client exposed 54 tools. Schema query, deterministic dry runs,
  zero dry-run edits, stale-context rejection and replan passed.
- One high-level application executed 56 operations: base fill, two terrain
  regions, one native water polygon and 52 props (50 trees, two boulders).
  Three required routes remained connected for the configured agent footprint.
  Every tree has a stable semantic ID mapped to a unique Dungeondraft ID.
- Repeating application reused the same job and IDs without duplicates.
  `get_battlemap` returned the same manifest. Save retained 52 native objects
  and the water tree; 128471-byte native JSON validated. PNG was 1536x1088.
- Native water creation, undo/redo, overlapping restoration and mixed
  cancellation passed separately on a fresh blank map. Water geometry/colors
  were compared without ephemeral `ref` IDs. Final dry-terrain PNG matched
  its pretest hash. Ripples can vary water pixels between renders.
- Foreground console after all tests showed protocol 21 and no new errors;
  only the existing missing override tags warning. Full Godot 3 syntax passed.

## Review

Run `phase3_smoke.py --output-dir <new-directory>` using the repository Python
environment on a blank 24x17 disposable map. It leaves the forest sample open,
and writes spec, complete plan, ID manifest, native map, preview and report.
The live output is `phase3-acceptance-2026-10-02` in the task workspace.

Check the central road, shallow stream, clear encounter/entry/spawn spaces,
separated trees and two boulders. Mud uses the default swamp artwork with an
explicit warning. The exported preview currently inherits native export grid
settings; Phase 4 implements output controls. Visual appearance does not prove
reachability; the independent geometry check handles that.

See [MAP_SPEC.md](MAP_SPEC.md) for lifecycle, schema, asset rules and limits.
No arbitrary new-map creation, roofs, mounted doors or pattern-floor batch
support is implied by this milestone. Noise is omitted until an actual visual
feature needs it. Specialized forest/road tools are omitted in favor of one
validated schema; targeted named-feature revision is the next phase.

## Polygon guard follow-up

An additional live check exposed adjacent collinear backtracking that the
nonadjacent intersection check missed. The validator now rejects it before
editing. A two-operation batch accepted the rectangle during preflight and
rejected only the backtracking polygon at index 1; water and all 52 objects
remained unchanged. The diagnostic water edit was undone, restoring the
verified save checkpoint.
