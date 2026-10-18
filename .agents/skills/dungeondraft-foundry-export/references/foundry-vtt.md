# Foundry VTT export routes and acceptance

Use for Foundry-targeted maps. Repository findings below reflect the protocol 23 bridge and `server/dungeondraft_mcp/layout/vtt.py` examined on 2026-10-18. Recheck live schemas and target-version documentation when these change. No live Foundry import was verified during this review.

## Choose the delivery route

- Establish Foundry generation, game system, intended square scale, playable floors and available runtime access. Use existing context before asking. These skill instructions do not authorize installing modules, uploading to a server or changing an existing world; use the authorization provided by the actual map/import request.
- **Repository adapter:** `export_battlemap` writes a native `.dd2vtt`, PNG, Foundry **14** scene JSON, GM import macro, encounter semantics, validation and completion manifest. It requires an applied/restored, validated planner project and exactly one native level. It does not connect to Foundry. Preserve planner ownership with a project bundle when needed; do not invent ownership for an arbitrary native map.
- **Universal VTT route:** native `.dd2vtt` can instead be imported with [Universal Battlemap Importer](https://foundryvtt.com/packages/dd-import/) (`dd-import`). Check its compatibility for the installed Foundry generation before selecting it; consult the [maintainer's instructions](https://github.com/moo-man/FVTT-DD-Import). This is an alternative import route, not an extra import to run on top of the adapter's scene. Portals and lighting still need review.
- **Multiple floors or unsupported projects:** preserve true native floors and aligned per-floor artwork. Use supported native VTT export only where live capabilities establish its floor scope, otherwise hand off explicit per-floor setup. The repository adapter does not assemble a multi-floor Foundry scene, stairs or transitions. Agree a target-version workflow before promising automatic multi-floor delivery; do not assume a particular module is required or installed.

## Design data that artwork cannot carry

Record exceptions in the encounter's existing DM notes/layout manifest, keyed by native/semantic ID where available and by floor plus tile coordinates/endpoints. Include desired behavior and export correction, rather than a separate per-edit journal.

| Feature | Intended Foundry behavior / data to retain |
| --- | --- |
| Solid boundary | Movement, sight, light and sound restrictions; connected endpoints at joins. |
| Ordinary door | Opening endpoints, open/closed/locked state, access and optional sound/animation. An open door must not retain an overlapping solid wall. |
| Secret door | Secret type and initial state; its interaction control must stay hidden from players. Keep discovery information in DM notes. |
| Window | Choose transparent movement-only blocking or proximity-based vision; record thresholds, light/sound behavior and whether it can open or be traversed. A window sprite is insufficient. |
| Terrain or curtain | Distinguish limited perception, movement-only blocking and sight/light-only blocking. Do not make every prop opaque. |
| Light | Floor, position, bright and dim radii in scene distance units, color, wall interaction, initial state and any required animation or direction. |
| Elevation / hazard | Heights, crossings and floor destinations; specify movement constraints separately from cover or difficult terrain. |

Foundry's [wall documentation](https://foundryvtt.com/article/walls/) describes independent restrictions, door states, secret controls and proximity windows. Choose the behavior that fits the encounter; do not equate all windows with doors.

Use native `draw_wall`, `add_portal` and `add_light` only as supported by current schemas. For a portal intended to cut a structural opening, use wall mounting and verify that it attached and cut the correct gap; disable free-placement fallback where failure should be explicit. Discover portal assets first. Native `closed` controls light blocking; it does not encode a Foundry lock or secret-door type.

Keep blocking geometry economical and navigable. Join endpoints precisely, preserve doorway clearance and avoid tracing every decorative irregularity. Inspect object occluders as well as structural walls. Foundry's [content creation guide](https://foundryvtt.com/article/content-creation-guide/) explains wall placement, performance and why GM dragging is insufficient to test passage.

## Scale and lighting contract

- Record image dimensions, pixels per square, distance per square, grid type, origin and floor alignment. Coordinates convert as `pixels = woxels / 256 * pixels_per_square` before any scene offset. Image DPI metadata is not grid size. Verify the target's grid constraints; prefer at least 50 pixels per square for Foundry, normally 100–128 where the export budget permits. The bridge accepts 20–256, but acceptance there does not prove runtime compatibility. Respect 8192 pixels per side and 16 megapixels.
- The current adapter hardcodes a square grid at **5 ft per square**, zero padding/shift and a Ground level spanning 0–10 ft. Other scales or elevations need an explicitly supported conversion and review; changing grid distance alone also leaves imported light radii wrong. Do not crop, rescale or shift the background independently of its walls/lights. See [scene configuration](https://foundryvtt.com/article/scenes/).
- Export with lighting unbaked for dynamic Foundry lighting; retain visible fixtures in the art. Place native lights at those fixtures. Dungeondraft `range` is a radius scale, not a feet value. The adapter converts native exported ranges to feet, makes the bright radius half the dim radius, uses 360-degree emission and approximates intensity. Record any different intended radii or effects for correction.
- Review scene darkness/global illumination, token vision and fog exploration together. A daylight exterior and a dark interior need intentional illumination boundaries. Baked shadows or dark artwork do not establish mechanical visibility. Set and test bright/dim radii, wall occlusion and activation using [Foundry lighting controls](https://foundryvtt.com/article/lighting/); do not promise native light-cookie parity.

## Export and import handoff

1. Save and visually review the native map; validate the applied/restored project. For adapter delivery use gridless output. Choose `foundry_image_path` as a relative uploaded PNG path, such as `maps/ambush/battlemap.png`, not a Windows disk path.
2. `export_battlemap(plan_id, directory, foundry_image_path, ppi)` needs a **new absolute directory in an existing parent**, inside the encounter directory. Never overwrite a completed bundle or blindly retry into an incomplete directory. For revisions, inspect and replace only the identified generated VTT directory when authorized, preserving the canonical native map and any project bundle; otherwise report the directory conflict. Do not create numbered history folders by default.
3. Wait for completion. Inspect `export.json`, file hashes/counts, warnings and the actual PNG. Retain `encounter.json`, `validation.json`, `foundry-scene.json`, `import-foundry.js` and `battlemap.dd2vtt` together. Current conversion makes **all native portals ordinary doors**; restore window behavior, secret type and locks from the notes. Native LOS becomes normal blocking walls; planner blocking radii and deep-water boundaries add movement-only walls. Review whether those barriers fit the intended encounter, including swimming and crossings. Cover, difficult terrain and zones remain metadata; actors, tokens, game-system automation and ambient sound are not created.
4. For the adapter route, upload the PNG to the declared Foundry path, then run the generated script as a GM in Foundry 14, or hand those steps to the user if runtime access is unavailable. The macro creates and views a new scene; rerunning it creates another scene rather than updating one. For revisions, resolve which existing scene is to be updated before importing again. Do not both run the macro and import the same data through another importer.

## Acceptance in the target runtime

After import, inspect and correct the actual scene before describing it as verified:

- Check the background resolves and at least two distant landmarks align with walls, openings and lights; measure a known tile distance. Check all floor origins if there are multiple floors.
- Test a representative owned, sight-enabled token as a player with intended vision settings and fresh/unexplored fog. Check sealed rooms and secrets remain concealed. GM overview alone is insufficient; GM dragging can bypass movement restrictions. Do not reset an existing campaign's exploration just to test; use an appropriate fresh test scene/user.
- Traverse intended routes and crossings. Exercise doors closed, open and locked; verify secret controls and window visibility from near/far and both sides. Look for light leaks, duplicate/overlapping walls and accidental blocked stairs.
- Check lights on/off, bright/dim boundaries and wall occlusion under the intended scene illumination; check any required floor transitions and elevation behavior. Configure any agreed system automation separately and test it.

Deliver the exact bundle/native paths, target generation, scale, corrections made and remaining manual items. Distinguish **files exported**, **scene imported** and **runtime behavior verified**. If Foundry access is unavailable, report that limitation and the pending checks; do not label the bundle seamless or runtime-verified.
