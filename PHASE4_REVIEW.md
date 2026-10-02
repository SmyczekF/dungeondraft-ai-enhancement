# Phase 4 review

Package 0.5.0, protocol 22, 59 MCP tools. Implemented on main.

## Result

The fresh stdio acceptance client loaded a checksummed project, returned a
1008×714 native PNG as MCP image content, and restored camera/grid settings.
Structural validation reports feature IDs and tile coordinates for missing
elements, drift, artwork, bounds, spacing, protected clearances and blocked
routes. Manual element bounds are conservative obstacles. Pixel quality is
reviewed separately; structural connectivity is a geometric check.

A boulder moved and changed artwork in two operations while retaining its
native ID. All 50 unselected trees and an independent manual prop stayed intact.
The same revision replay returned its retained result. A forest shrank to 48
members; a road widened with a regenerated forest. Reversible deletion was
cancelled and restored the same native ID, artwork and transform. Native save
contained 51 objects: 48 trees, two boulders and one manual test prop.

Manual object edits survived revision. Manual terrain painting changed a native
checksum, caused a structured conflict, and prevented shared terrain replacement.
Undo restored the checksum. A complete project was saved and a second fresh MCP
process restored its ownership. Existing project directory overwrite was rejected.

Sixteen pure tests and the full Godot 3 syntax parser passed. Captured editor
stdout/stderr showed no new native exceptions, script errors or null-pointer
messages; the pre-existing missing-tags warning remained.

## Review

Run `phase4_smoke.py --project ABSOLUTE_PROJECT --output-dir NEW_DIRECTORY`
against that project's already-open native map. The test deliberately revises
the disposable map. Project directories contain:

- `project.json`: completion marker, versions, seed and file checksums.
- `spec.json`, `plan.json`, `catalog.json`: reproducible source and asset metadata.
- `manifest.json`, `ownership.json`: semantic/native IDs and surface checksums.
- `validation.json`: structural findings and separate visual review requirement.
- `map.dungeondraft_map`, `preview.png`: editable source and native rendered image.

To continue after an MCP/editor restart, open the project's native map and call
`load_battlemap_project(directory)`, then `validate_battlemap(plan_id)`.
Use `revise_battlemap` with complete named feature replacements. Default dry run
returns the diff; repeat with `dry_run=false` to apply. Retain the new plan ID.

## Scope decisions

**[PLAN CHANGED]** Native terrain is a shared splat texture, without native
per-feature terrain IDs. Road/region revisions rebuild the owned terrain palette
only if its checksum is unchanged. This repaint leaves object/water identities
intact and rejects manual terrain changes instead of overwriting them.

**[PLAN CHANGED]** Stream/building geometry revisions are excluded from this
first ownership-safe diff. Water shares one level mesh; mounted geometry has
extra memberships. Existing low-level editing remains available, but project
validation reports drift. Extending these requires explicit ownership and
rollback proof rather than automatic deletion/recreation of unrelated content.

Unselected forests remain frozen. A road conflicting with their footprints asks
for that forest to be included in the revision; regeneration is explicit.
No new client config, server or dependencies were required. Restart the MCP
client once to discover the five additional tools.

A full editor restart reopened the native project and preserved all 51 objects,
water geometry and terrain ownership checksum. Fresh adoption validated 50
owned elements and the one manual prop.
