# Walk-under overhead artwork

Use for requested tree canopies, awnings and other scenery with playable ground
beneath it. Core Foundry supports elevated Tiles and occlusion; a module is not
needed for the visual effect. This is distinct from overlapping walkable floors,
automatic token elevation, collision, cover and lighting restrictions.

## Prepare the native artwork

- Ground contains terrain, paths, rocks, roots, trunks and low undergrowth.
  The overhead export contains only the canopy/awning artwork with real alpha.
  Both use identical full-map dimensions, origin, pixels per square and scale.
- Prefer independent native drawing-layer exports when supported. The examined
  bridge exports the active native level, not selected drawing layers. A clearly
  named **export-only** level is a supported alternative: keep ground and overhead
  in one canonical native map, resolve level labels/indices before each export,
  and disable terrain on the overhead level. Verify RGBA transparency; a black
  image viewer background is not proof of an opaque exported background.
- Prevent duplicated overhead artwork: the ground export must contain no baked
  canopy. Keep visible trunk/root artwork aligned beneath the matching canopy.
  Native levels used as export containers do not become extra playable floors
  in Foundry. Do not use this as a reason to add unrequested building roofs.
- Preserve the canopy ID/transform, trunk position, layer role and export hashes
  in the encounter's existing manifest. Moving planner-owned elements between
  native levels invalidates the old ownership: retain it as construction history,
  not a restorable applied record. Do not invent ownership for a layered map.

## Assemble one scene

Use the ground image as the playable level background and one or more elevated
Tiles for transparent overhead artwork. A full-map atlas works well with Radial
occlusion; separate tiles allow independent whole-canopy Fade. Avoid Fade on a
single entire-forest atlas unless fading every canopy together is intended.

**User default: retain 30% opacity while revealing a token underneath**, unless
explicitly specified otherwise. Apply this to treetops, awnings, raised decks,
upper-floor artwork and other overhead scenery that obscures a token. In the
inspected v14 Tile schema, set `occlusion.alpha: 0.30`; this means 30% visible,
not 30% transparent. Keep normal, unoccluded Tile `alpha: 1` unless separately
requested. This visual fade preserves the token's actual elevation and leaves
the overhead structure perceptible while the token is selected or otherwise
triggers occlusion. Do not lower the native artwork's opacity or change the
whole playable level's visibility to implement it.

For the inspected **Foundry 14.369**, the current Tile schema uses:

```json
{
  "name": "Tree canopies",
  "x": 0, "y": 0,
  "width": 3584, "height": 3072,
  "elevation": 15,
  "levels": ["actualGroundLevelId"],
  "rotation": 0, "alpha": 1,
  "hidden": false, "locked": true,
  "texture": {
    "src": "maps/encounter/canopy.png",
    "anchorX": 0, "anchorY": 0,
    "scaleX": 1, "scaleY": 1, "fit": "fill"
  },
  "occlusion": {"modes": [4], "alpha": 0.30},
  "restrictions": {"light": false, "weather": false}
}
```

Dimensions and elevation above are examples, not defaults for every encounter.
Use a valid document ID, the actual scene level ID and the source-image bounds.
**Tile coordinates are anchored coordinates in inspected v14.369.** BaseTile
defaults `texture.anchorX/Y` to 0.5, and the client uses those values directly
for its shape and mesh. A full-map Tile at `(0,0)` therefore needs explicit
anchors `(0,0)` to align its top-left with the background; alternatively use
the scene center with anchors `(0.5,0.5)`. Do not combine `(0,0)` with default
center anchors: the image shifts half its width/height off-map. Validate the
normalized Tile document and client transform, not just raw JSON coordinates
or an alpha composite which ignores Tile placement. Check artwork landmarks
and transformed alpha bounds against the corresponding ground locations.
Keep the tile above intended ground/token elevations and assign it to the ground
level. Choose light/weather behavior separately; leaves are not a sealed roof.
Do not add canopy-footprint movement or opaque vision walls. Only actual trunks,
rocks or other justified obstacles receive matching restrictions.

For this campaign, requested walk-under tree crowns normally sit at **15 ft**.
Inspect the current `occlusion.modes` SetField: do not copy the legacy singular
`occlusion.mode` into new v14 exports. Keep the ground background free of crowns,
and also deliver a registered flat composite for ordinary grid/gridless use.

## Walkable raised decks

A deck with usable space underneath needs two overlapping **playable Scene
Levels in the same Scene**, unlike a canopy's export-only native level. Keep
supports, ground routes and the ladder below; floorboards, furniture, office
walls and the hatch belong above. Assign guardrails and office walls only to
the upper level so they cannot block walking underneath. An elevated Tile can
show the transparent deck art from both levels, with radial occlusion below;
avoid baking a second copy into either background. In v14 a null upper
`background.src` renders no texture; its visibility can include Ground.

Use paired core Change Level regions at the actual staircase and hatch/ladder,
not a remote marker. Add matching Define Surface floors with access holes when
physical vertical restrictions are needed. Set visual occlusion separately
from floor movement/sight restrictions: an opaque floor surface must not defeat
the intended radial view of a ground token under the deck. Validate upper-token
render ordering, lower routes, hatch descent and both embedded textures. Keep
stairs above their own floor artwork when splitting native exports.

V14 modes are flags: `NONE=0`, `FADE=1`, `SURFACE=2`, `RADIAL=4`, `VISION=8`.
The examined installed **13.348** instead uses enum `RADIAL=3`, `VISION=4`.
Never transfer these numbers or v14 level fields to another generation blindly.
Check the user's intended generation when installed/runtime evidence conflicts
with the assumed export target. No deprecated `overhead=true` field is needed
in the documented modern elevation-based route.

For self-contained delivery, embed the ground and canopy image bytes only when
the target's image fields and server import sanitization support those data URIs.
The Tile image field is `texture.src`; the v14 level background is
`levels[].background.src`. Verify imported persistence for both, not only for
the background. A JSON containing ordinary relative file paths does not bundle
or upload images; hand off those assets separately if embedding is unsupported.

## Validation and honest handoff

Check decoded dimensions, alpha, image hashes, origin and tile placement. Composite
the exports for registration review, then inspect the real imported scene with a
sight-enabled, owned player token: outside/inside a canopy, under two overlapping
canopies, near its alpha edge, at intended ground elevations and after reload.
Confirm only nearby foliage occludes, paths remain passable, actual trunks block
where intended, and both embedded textures persist. Core Tile occlusion is a
visual effect; it does not implement climbing or difficult-terrain movement cost.
Keep file validation distinct from runtime import/player-view verification.

Sources checked 2026-10-19:

- [Core Tiles guide, v14.368](https://foundryvtt.com/article/tiles/)
- [V14 occlusion flags](https://foundryvtt.com/api/v14/variables/CONST.OCCLUSION_MODES.html)
- [V14 Tile schema, including levels](https://foundryvtt.com/api/v14/classes/foundry.documents.TileDocument.html#defineSchema)
- [V14 texture and tile fields](https://foundryvtt.com/api/v14/interfaces/foundry.documents.types.TileData.html)

V13 values above were checked in the installed `common/constants.mjs`; they are
not evidence of v14 compatibility. Recheck version-specific fields when changing
targets. The repository's planner exporter currently requires one native level;
it does not automatically assemble multiple native export layers into Tiles.
Use a documented encounter-local conversion when that route is unsupported.
