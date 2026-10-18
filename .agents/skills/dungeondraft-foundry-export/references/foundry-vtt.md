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

## Tactical scenery and visibility

Inspect the actual current artwork at token scale before tracing props. Assign restrictions from material, apparent height, access and encounter use; do not apply every option to every map. Keep concise contours inside visible material, omit guy ropes/shadows and preserve doors, tent flaps, ramps and routes. Record feature IDs, tile endpoints, senses, direction and initial door state in the encounter's existing manifest.

| Feature | Useful core Foundry configuration | Review / limitation |
| --- | --- | --- |
| Bars, cage, iron gate | Movement Normal; sight/light/sound None. Split out a real gate segment and choose its initial lock state. | No overlapping solid wall across the gate. Seeing through bars does not automate attacks or cover. |
| Large boulder / solid outcrop | A simple closed contour: Movement Normal, Sight Limited; often Light Limited, Sound None. | A ray passes one Limited boundary and stops at the next, keeping the near surface visible and hiding space beyond the far boundary. Avoid separate overlapping contours inside one rock cluster; use a coherent outer contour. Small/low stones may warrant no wall. |
| Opaque tent canopy that should remain visible | Limited sight around the canvas perimeter; choose light transmission separately. Normal movement along fabric, with an open gap or operable flap matching the art. Sound usually passes. | This approximates the exterior as a visible solid obstacle; a token inside one Limited contour can see out through one boundary. If playable, concealed interiors matter, use normal fabric walls with a separate roof/overhead solution instead and verify target-version occlusion. An open flap intentionally admits sight. |
| Curtain or thin opaque screen | Sight Normal, movement None; light/sound according to material. | An ethereal wall is a useful starting point; it does not impose a movement cost. |
| Low cliff / ledge | Where justified, a one-direction Sight Normal line on the lip, with its clear side facing the high ground. Choose movement separately; an additional movement-only line can prevent ordinary walking across it. | Core direction is a 2D approximation, not automatic token-height, flying or climbing logic. Annotate height and preserve the ramp/access. Test both sides and endpoints. |

Terrain Walls (Limited perception) are generally simpler than four inward-blocking one-way edges around each boulder. Those directional contours can also work, but every edge must face correctly and concave/overlapping outlines need particular care. Keep objects visible by tracing their physical perimeter, not by adding an invisible buffer behind them. Limited restrictions also interact with other Limited walls farther along a ray, so test multiple obstacles and the inside of any accessible contour.

**A distance threshold is not a fixed shadow depth.** Proximity/Reverse Proximity compare the viewer/light source's distance to the wall; attenuation varies the distance that sight/light penetrates as that source moves. Setting a threshold to 5 or 10 ft does not create a fixed 5 or 10 ft strip hidden behind a rock or a height-aware cliff. Direction affects all configured restrictions on that segment. Do not promise core 3D behavior or install an elevation/cover module without a requested, version-compatible workflow. Cover, climbing, difficult terrain and low-wall sight exceptions remain GM/system rules unless explicitly implemented.

See the official [wall behavior guide](https://foundryvtt.com/article/walls/), [v14 WallData schema](https://foundryvtt.com/api/v14/interfaces/foundry.documents.types.WallData.html) and [threshold schema](https://foundryvtt.com/api/v14/interfaces/foundry.documents.types.WallThresholdData.html). In the inspected v14 schema, `c` is four **integer** canvas pixels; movement is None/Normal (0/20), senses None/Limited/Normal/Proximity/Reverse Proximity (0/10/20/30/40), and direction Both/Left/Right (0/1/2). Confirm direction using target-version geometry or runtime tests instead of guessing from screen axes. Assign walls to the intended v14 level.

### Preserve semantics through import

Native Universal VTT LOS and the examined importer do not carry arbitrary independent sense restrictions, directions or locks. Decorative props need explicit Foundry geometry. Keep these corrections in Foundry scene JSON/macros and retain them in the encounter manifest; do not claim the unchanged `.dd2vtt` includes them. Reinspect importer support when it changes.

When the user wants to import/re-import the finished map, put all corrections directly in the delivered Foundry scene JSON and hand off that file with its image. Standard Universal Battlemap Importer cannot preserve all these semantics; use Foundry's scene **Import Data** for the complete scene. Retain a truthful `_stats.coreVersion` matching the target schema: the inspected v14 importer treats missing version metadata as pre-v10 and runs migrations that can replace level data.

If an update must preserve existing world changes, an idempotent **current-scene patch** is an optional alternative. Use stable per-feature source flags; create/update only owned additions, preserve current door states, and never delete unrelated walls or replace the background. Standalone macros should use the `world` scope for `getFlag`/`setFlag`/`unsetFlag` state (for example an undo record); those helpers reject an invented or inactive module scope. Validate the target version, map registration, grid scale, image dimensions and chosen level before mutation. Transform coordinates with the actual scene/image origin and scale, including importer padding/shift; WebP conversion alone is not a coordinate change. Refuse cropped, stretched or manually transformed backgrounds unless their registration is established. A dry-run summary/preview and a rollback of owned additions make the correction reviewable.

## Scale and lighting contract

- Record image dimensions, pixels per square, distance per square, grid type, origin and floor alignment. Coordinates convert as `pixels = woxels / 256 * pixels_per_square` before any scene offset. Image DPI metadata is not grid size. Verify the target's grid constraints; prefer at least 50 pixels per square for Foundry, normally 100–128 where the export budget permits. The bridge accepts 20–256, but acceptance there does not prove runtime compatibility. Respect 8192 pixels per side and 16 megapixels.
- The current adapter hardcodes a square grid at **5 ft per square**, zero padding/shift and a Ground level spanning 0–10 ft. Other scales or elevations need an explicitly supported conversion and review; changing grid distance alone also leaves imported light radii wrong. Do not crop, rescale or shift the background independently of its walls/lights. See [scene configuration](https://foundryvtt.com/article/scenes/).
- Export with lighting unbaked for dynamic Foundry lighting; retain visible fixtures in the art. Place native lights at those fixtures. Dungeondraft `range` is a radius scale, not a feet value. The adapter converts native exported ranges to feet, makes the bright radius half the dim radius, uses 360-degree emission and approximates intensity. Record any different intended radii or effects for correction.
- Always deliver global illumination **enabled**, with a darkness threshold of **0.8**, as the user's default for every Foundry map. In v14 the fields are `environment.globalLight.enabled: true` and `environment.globalLight.darkness.max: 0.8`; retain the range minimum of 0. Apply these settings to the complete scene JSON and any alternate scene-creation payload, and record them in encounter metadata. Override only when the user explicitly requests different settings.
- Review scene darkness/global illumination, token vision and fog exploration together. A daylight exterior and a dark interior need intentional illumination boundaries. Baked shadows or dark artwork do not establish mechanical visibility. Set and test bright/dim radii, wall occlusion and activation using [Foundry lighting controls](https://foundryvtt.com/article/lighting/); do not promise native light-cookie parity.

### Rules-based light radii (D&D 2024)

Read the [lighting quick guide](dnd-2024-lighting.md) when choosing sources or reviewing imported illumination. It provides published equipment profiles, explicit GM defaults for fire sizes and the conversion from additional dim distance to Foundry's total dim radius. Source identity/state must be established; do not infer rules from sprite size, native `range`, alpha or a generic half-bright conversion. Retain the rule citation and any assumptions with each light, correct both new-scene data and current-scene patches, and verify the resulting boundaries in player view. Universal VTT's single radius cannot encode every bright/dim pair.

## Export and import handoff

1. Save and visually review the native map; validate the applied/restored project. For adapter delivery use gridless output. Choose `foundry_image_path` as a relative uploaded PNG path, such as `maps/ambush/battlemap.png`, not a Windows disk path.
2. `export_battlemap(plan_id, directory, foundry_image_path, ppi)` needs a **new absolute directory in an existing parent**, inside the encounter directory. Never overwrite a completed bundle or blindly retry into an incomplete directory. For revisions, inspect and replace only the identified generated VTT directory when authorized, preserving the canonical native map and any project bundle; otherwise report the directory conflict. Do not create numbered history folders by default.
3. Wait for completion. Inspect `export.json`, file hashes/counts, warnings and the actual PNG. Retain `encounter.json`, `validation.json`, `foundry-scene.json`, `import-foundry.js` and `battlemap.dd2vtt` together. Current conversion makes **all native portals ordinary doors**; restore window behavior, secret type and locks from the notes. Native LOS becomes normal blocking walls; planner blocking radii and deep-water boundaries add movement-only walls. Review whether those barriers fit the intended encounter, including swimming and crossings. Cover, difficult terrain and zones remain metadata; actors, tokens, game-system automation and ambient sound are not created.
4. For the adapter route, upload the PNG to the declared Foundry path, create an empty scene, then right-click that scene in the Scenes directory and choose **Import Data** with the completed scene JSON. Hand those steps to the user when they are performing the import. Import Data overwrites the selected scene, so use a new empty scene unless replacement is intended. The generated GM script remains an optional scene-creation route; it creates another scene each run. Choose one import route.

## Acceptance in the target runtime

After import, inspect and correct the actual scene before describing it as verified:

- Check the background resolves and at least two distant landmarks align with walls, openings and lights; measure a known tile distance. Check all floor origins if there are multiple floors.
- Test a representative owned, sight-enabled token as a player with intended vision settings and fresh/unexplored fog. Check sealed rooms and secrets remain concealed. GM overview alone is insufficient; GM dragging can bypass movement restrictions. Do not reset an existing campaign's exploration just to test; use an appropriate fresh test scene/user.
- Traverse intended routes and crossings. Exercise doors closed, open and locked; verify secret controls and window visibility from near/far and both sides. Look for light leaks, duplicate/overlapping walls and accidental blocked stairs.
- Inspect terrain-wall objects from opposing sides: the rock/canopy should remain visible while a token behind its far side is hidden. Check any tent opening and inside view, nearby Limited obstacles, and walkable gaps at token scale. For directional ledges, test low-to-high and high-to-low sight, access around the ends, and the documented climbing/flying exceptions. These checks supplement structural geometry validation.
- Check lights on/off, bright/dim boundaries and wall occlusion under the intended scene illumination; check any required floor transitions and elevation behavior. Configure any agreed system automation separately and test it.

Deliver the exact bundle/native paths, target generation, scale, corrections made and remaining manual items. Distinguish **files exported**, **scene imported** and **runtime behavior verified**. If Foundry access is unavailable, report that limitation and the pending checks; do not label the bundle seamless or runtime-verified.
