# Foundry VTT export routes and acceptance

Use for Foundry-targeted maps. Repository findings below reflect the protocol 23 bridge and `server/dungeondraft_mcp/layout/vtt.py` examined on 2026-10-18. Recheck live schemas and target-version documentation when these change. No live Foundry import was verified during this review.

For map recipients, the README's [Import into Foundry VTT](../../../../README.md#import-into-foundry-vtt) section is the user-facing guide: which file to choose, the exact Scenes-list import steps, optional thumbnail generation, and why the Universal VTT alternative is discouraged for these prepared exports. Include those steps in each encounter's handoff.

## Choose the delivery route

- Read the working project's root `map-workflow.json` through the skill. Enter this route for a requested export or `export_to_foundry=true`; false never cancels an explicit export request. `automatic_open_maps` controls lifecycle checkpoints and `automatic_exports` controls final file generation. Neither overrides the new-map concept checkpoint (`automatic_concept_approval=false` by default) or authorizes unrelated world mutations.
- Establish game system, intended square scale, playable floors and available runtime access from context. Default an unspecified Foundry generation to the supported adapter's Foundry 14; clarify only conflicts or missing input that change delivery. Load the canonical map with `open_map` and restore saved ownership when the selected route requires a planner project; do not ask for manual opening by default. Exported-file inspection needs no editor. These instructions do not authorize installing modules, uploading to a server or changing an existing world; use the authorization provided by the actual map/import request.
- **Repository adapter:** `export_battlemap` writes a native `.dd2vtt`, PNG, Foundry **14** scene JSON, GM import macro, encounter semantics, validation and completion manifest. It requires an applied/restored, validated planner project and exactly one native level. It does not connect to Foundry. Preserve planner ownership with a project bundle when needed; do not invent ownership for an arbitrary native map.
- **Universal VTT route (discouraged for our completed Foundry exports):** [Dungeondraft's official VTT Integrations guidance](https://dungeondraft.net/) links to [Universal Battlemap Importer](https://foundryvtt.com/packages/dd-import/) (`dd-import`) for native `.dd2vtt` files. This remains a valid alternative for basic native maps, but the examined importer does not transfer our Foundry-specific movement-only, Limited or directional wall settings, locks, the prepared regions and environmental-light setup or every bright/dim pair. Prefer the completed scene JSON when it is supplied. If the user intentionally chooses Universal VTT, check target-generation compatibility and consult the [maintainer's instructions](https://github.com/moo-man/FVTT-DD-Import); describe the missing behaviors explicitly. This is an alternative route, not an extra import to run on top of the completed scene.
- **Multiple floors or unsupported projects:** preserve true native floors and aligned per-floor artwork. Use supported native VTT export only where live capabilities establish its floor scope, otherwise hand off explicit per-floor setup. The repository adapter does not assemble a multi-floor Foundry scene, stairs or transitions. Agree a target-version workflow before promising automatic multi-floor delivery; do not assume a particular module is required or installed.

## Design data that artwork cannot carry

Record exceptions in the encounter's existing DM notes/layout manifest, keyed by native/semantic ID where available and by floor plus tile coordinates/endpoints. Include desired behavior and export correction, rather than a separate per-edit journal.

| Feature | Intended Foundry behavior / data to retain |
| --- | --- |
| Solid boundary | Movement, sight, light and sound restrictions; connected endpoints at joins. |
| Ordinary door | Opening endpoints, open/closed/locked state, access and optional sound/animation. An open door must not retain an overlapping solid wall. |
| Secret door | Closed Secret type at every exposed entrance, including exterior escape mouths. Disguise the artwork and test sight/movement from both sides; fog alone does not hide an opening in explored ground. Keep discovery clues in DM notes. |
| Window | Choose transparent movement-only blocking or proximity-based vision; record thresholds, light/sound behavior and whether it can open or be traversed. For an ordinary transparent window in Foundry 14, use `move=20`, `sight=0`, `light=0`, `door=0`. Verify that no overlapping solid wall still blocks its opening, including rays through the aperture. A window sprite is insufficient. |
| Difficult terrain | Distinct texture/material and fitting low clutter; retain exact region bounds in notes/metadata. Rubble clusters do not need collision or sight walls, and artwork alone does not automate movement cost. |
| Terrain or curtain | Distinguish limited perception, movement-only blocking and sight/light-only blocking. Do not make every prop opaque. |
| Light | Floor, position, bright and dim radii in scene distance units, color, wall interaction, initial state and any required animation or direction. |
| Elevation / hazard | Heights, crossings and floor destinations; specify movement constraints separately from cover or difficult terrain. |

Foundry's [wall documentation](https://foundryvtt.com/article/walls/) describes independent restrictions, door states, secret controls and proximity windows. Choose the behavior that fits the encounter; do not equate all windows with doors.

Use native `draw_wall`, `add_portal` and `add_light` only as supported by current schemas. For a portal intended to cut a structural opening, use wall mounting and verify that it attached and cut the correct gap; disable free-placement fallback where failure should be explicit. Discover portal assets first. Native `closed` controls light blocking; it does not encode a Foundry lock or secret-door type.

Keep blocking geometry economical and navigable. Join endpoints precisely, preserve doorway clearance and avoid tracing every decorative irregularity. Inspect object occluders as well as structural walls. Foundry's [content creation guide](https://foundryvtt.com/article/content-creation-guide/) explains wall placement, performance and why GM dragging is insufficient to test passage.

## Tactical scenery and visibility

Default to no prop walls: beds, desks, tables, barrels and small stones normally allow token movement and sight. The GM can adjudicate difficult terrain without collision geometry. Add movement restrictions only when passage is logically impossible; assess sight separately from actual height, size and opacity. A tall oven or huge boulder may occlude, while low furniture need not. If uncertain, add neither collision nor vision blocking.

Inspect the actual current artwork at token scale before tracing justified obstacles. Assign restrictions from material, apparent height, access and encounter use; do not apply every option to every map. Keep concise contours inside visible material, omit guy ropes/shadows and preserve doors, tent flaps, ramps and routes. Record feature IDs, tile endpoints, senses, direction and initial door state in the encounter's existing manifest.

| Feature | Useful core Foundry configuration | Review / limitation |
| --- | --- | --- |
| Bars, cage, iron gate | Movement Normal; sight/light/sound None. Split out a real gate segment and choose its initial lock state. | No overlapping solid wall across the gate. Seeing through bars does not automate attacks or cover. |
| Large boulder / solid outcrop | A simple closed contour: Movement Normal, Sight Limited; often Light Limited, Sound None. | A ray passes one Limited boundary and stops at the next, keeping the near surface visible and hiding space beyond the far boundary. Avoid separate overlapping contours inside one rock cluster; use a coherent outer contour. Small/low stones normally need no wall; omit uncertain restrictions. |
| Opaque tent canopy that should remain visible | Limited sight around the canvas perimeter; choose light transmission separately. Normal movement along fabric, with an open gap or operable flap matching the art. Sound usually passes. | This approximates the exterior as a visible solid obstacle; a token inside one Limited contour can see out through one boundary. If playable, concealed interiors matter, use normal fabric walls with a separate roof/overhead solution instead and verify target-version occlusion. An open flap intentionally admits sight. |
| Curtain or thin opaque screen | Sight Normal, movement None; light/sound according to material. | An ethereal wall is a useful starting point; it does not impose a movement cost. |
| Low cliff / ledge | Where justified, a one-direction Sight Normal line on the lip, with its clear side facing the high ground. Choose movement separately; an additional movement-only line can prevent ordinary walking across it. | Core direction is a 2D approximation, not automatic token-height, flying or climbing logic. Annotate height and preserve the ramp/access. Test both sides and endpoints. |

Terrain Walls (Limited perception) are generally simpler than four inward-blocking one-way edges around each boulder. Those directional contours can also work, but every edge must face correctly and concave/overlapping outlines need particular care. Keep objects visible by tracing their physical perimeter, not by adding an invisible buffer behind them. Limited restrictions also interact with other Limited walls farther along a ray, so test multiple obstacles and the inside of any accessible contour.

**A distance threshold is not a fixed shadow depth.** Proximity/Reverse Proximity compare the viewer/light source's distance to the wall; attenuation varies the distance that sight/light penetrates as that source moves. Setting a threshold to 5 or 10 ft does not create a fixed 5 or 10 ft strip hidden behind a rock or a height-aware cliff. Direction affects all configured restrictions on that segment. Do not promise core 3D behavior or install an elevation/cover module without a requested, version-compatible workflow. Cover, climbing, difficult terrain and low-wall sight exceptions remain GM/system rules unless explicitly implemented.

See the official [wall behavior guide](https://foundryvtt.com/article/walls/), [v14 WallData schema](https://foundryvtt.com/api/v14/interfaces/foundry.documents.types.WallData.html) and [threshold schema](https://foundryvtt.com/api/v14/interfaces/foundry.documents.types.WallThresholdData.html). In the inspected v14 schema, `c` is four **integer** canvas pixels; movement is None/Normal (0/20), senses None/Limited/Normal/Proximity/Reverse Proximity (0/10/20/30/40), and direction Both/Left/Right (0/1/2). Confirm direction using target-version geometry or runtime tests instead of guessing from screen axes. Assign walls to the intended v14 level.

### Preserve semantics through import

For observation windbreaks or defensive apertures, explicitly decide which side
can see out. Core direction affects **all configured restrictions** on a wall.
When the structure blocks walking both ways but permits outward sight/light,
use a bidirectional movement-only segment plus a coincident directional
sight/light segment. Do not leave another opaque segment across it. Determine
the clear side from actual endpoints and an interior sample, then test opposing
origins and the ends. Use Proximity for an aperture that can be seen through
only from nearby (often 5–10 ft when appropriate); do not add that distance limit
to an open lookout view that should work throughout the yard. Reverse Proximity
has the opposite distance condition. These are 2D approximations, not automatic
height or cover rules. Ordinary windows remain transparent from both sides
unless the construction specifically supports a different behavior.

For **nearby-only outward sight with an opaque outside**, a clear-sided
directional wall alone is insufficient: the clear side bypasses its threshold.
Use a bidirectional movement wall with Sight Proximity and a separate
directional Sight Normal wall which is clear from inside. Near inside viewers
pass both perception checks; far inside viewers fail Proximity, and outside
viewers fail the directional wall at any distance. Choose light independently.
Store thresholds in scene distance units and test the target's token-radius
adjustment, near/far origins on both sides and the intended observation point.

### Water and movement actions

Coastal seas should support swimming rather than behave as ordinary dry ground.
Make a core **Modify Movement Cost** region over actual water, subtracting land,
islands, piers and other dry platforms. Assign the intended scene level and a
water-surface elevation ceiling so high tokens and upper decks are unaffected.
Do not make swimming impossible with an invisible solid shoreline wall.

For inspected Foundry 14.369 + dnd5e 6.0.6, use `difficulties` such as
`{"walk":2,"swim":1,"fly":1}`. The walking entry handles costly wading/GM
override; the user selects **Swim** for deep water. Dnd5e itself adds movement
cost when the actor lacks a swimming speed. Setting swim to 2 as well would
penalize natural swimmers and stack extra cost for others. Core Regions do not
force/select movement actions: state that limitation, and verify ruler action,
actors with/without swim speed, flight and any water-walking exception. Do not
describe a movement multiplier as forced swimming or automated drowning.

Check actual cost resolution before using `null` as an impassable action. The
inspected core terrain-effect multiplication coerces null to zero; treating it
as an infinite cost would create free movement. Preserve separate shallow-water
or flooded-footing rulings when the artwork represents wading, not deep sea.

Native Universal VTT LOS and the examined importer do not carry arbitrary independent sense restrictions, directions or locks. Only props that actually warrant restrictions need explicit Foundry geometry. Keep these corrections in Foundry scene JSON/macros and retain them in the encounter manifest; do not claim the unchanged `.dd2vtt` includes them. Reinspect importer support when it changes.

When the user wants to import/re-import the finished map, put all corrections directly in the delivered Foundry scene JSON and hand off that file with its image. Standard Universal Battlemap Importer cannot preserve all these semantics; use Foundry's scene **Import Data** for the complete scene. Retain a truthful `_stats.coreVersion` matching the target schema: the inspected v14 importer treats missing version metadata as pre-v10 and runs migrations that can replace level data.

For the user's preferred single-file delivery, embed the background bytes as a supported image data URI in the v14 level's `background.src`. The inspected v14 `FilePathField` accepts an image data URI; the server's `sanitizeFilePathField` extracts and persists its bytes on update when the importing user has file-upload permission. Validate both behaviors for the target build before relying on them. Prefer a lossless WebP at unchanged pixel dimensions, check decoded pixel equality against the canonical export and check total payload size against the server's limits. Ordinary path-based scene JSON contains only a reference and does not upload the image; never describe that route as a self-contained import. Keep embedded payloads out of diagnostic output and human-readable metadata.

If an update must preserve existing world changes, an idempotent **current-scene patch** is an optional alternative. Use stable per-feature source flags; create/update only owned additions, preserve current door states, and never delete unrelated walls or replace the background. Standalone macros should use the `world` scope for `getFlag`/`setFlag`/`unsetFlag` state (for example an undo record); those helpers reject an invented or inactive module scope. Validate the target version, map registration, grid scale, image dimensions and chosen level before mutation. Transform coordinates with the actual scene/image origin and scale, including importer padding/shift; WebP conversion alone is not a coordinate change. Refuse cropped, stretched or manually transformed backgrounds unless their registration is established. A dry-run summary/preview and a rollback of owned additions make the correction reviewable.

## Scale and lighting contract

- Record image dimensions, pixels per square, distance per square, grid type, origin and floor alignment. Coordinates convert as `pixels = woxels / 256 * pixels_per_square` before any scene offset. Image DPI metadata is not grid size. Verify the target's grid constraints; prefer at least 50 pixels per square for Foundry, normally 100–128 where the export budget permits. The bridge accepts 20–256, but acceptance there does not prove runtime compatibility. Respect 8192 pixels per side and 16 megapixels.
- The current adapter hardcodes a square grid at **5 ft per square**, zero padding/shift and a Ground level spanning 0–10 ft. Other scales or elevations need an explicitly supported conversion and review; changing grid distance alone also leaves imported light radii wrong. Do not crop, rescale or shift the background independently of its walls/lights. See [scene configuration](https://foundryvtt.com/article/scenes/).
- Export with lighting unbaked for dynamic Foundry lighting. Retain visible table/wall fixtures and place native lights at them; omit ceiling-fixture artwork from the playable floor while retaining its emitter, following the user preference. Dungeondraft `range` is a radius scale, not a feet value. The adapter converts native exported ranges to feet, makes the bright radius half the dim radius, uses 360-degree emission and approximates intensity. Native `intensity` copied directly to Foundry color alpha can greatly amplify the glow compared with an existing import: check the lighting guide's **Avoid excessive visual glow** section, preserve known working appearance settings and correct these in the completed scene. Record any different intended radii or effects for correction.
- Use core **Scene Regions / Adjust Darkness Level** to separate exterior light from rooms and underground areas, following [regional lighting](regional-lighting.md). Completed scenes need outdoor bright daylight, a dim nighttime baseline and sensible coverage wherever a fixture/window actually supplies light. Window-lit rooms can use a daytime dim floor; sealed unlit rooms and caves stay excluded. Raw adapter GI-off output is only a safe draft, not the finished lighting policy. Record regional parameters, source profiles and intentional darkness in all scene/import payloads.
- Review scene darkness/global illumination, token vision and fog exploration together. A daylight exterior and a dark interior need intentional illumination boundaries. Baked shadows or dark artwork do not establish mechanical visibility. Set and test bright/dim radii, wall occlusion and activation using [Foundry lighting controls](https://foundryvtt.com/article/lighting/); do not promise native light-cookie parity.

### Regional illumination and shadow control

Use [regional lighting](regional-lighting.md) for the preferred core mechanism, exact v14 fields, day/night coverage, doorway/window emitters and minimum interior illumination. It replaces the former GI-off/dense-point-light approach. Global light is acceptable only with verified interior/cave exclusions; never illuminate underground areas as an accidental consequence of an outdoor baseline.

### Rules-based light radii (D&D 2024)

Read the [lighting quick guide](dnd-2024-lighting.md) when choosing sources or reviewing imported illumination. It provides published equipment profiles, explicit GM defaults for fire sizes and the conversion from additional dim distance to Foundry's total dim radius. Source identity/state must be established; do not infer rules from sprite size, native `range`, alpha or a generic half-bright conversion. Apply the campaign minimum for map fixtures separately, clearly distinguishing it from the published equipment values. Retain the rule citation and any assumptions with each light, correct both new-scene data and current-scene patches, and verify the resulting boundaries in player view. Universal VTT's single radius cannot encode every bright/dim pair.

## Export and import handoff

1. Save and visually review the native map; validate the applied/restored project. If `automatic_exports=false`, present the concrete deliverables and wait for approval unless that export is already explicitly approved; internal review renders are still allowed. For adapter delivery use gridless output. The adapter initially requires `foundry_image_path` as a relative PNG path, such as `maps/ambush/battlemap.png`, not a Windows disk path. For single-file delivery, replace that reference in the completed scene JSON with the validated embedded background and update the completion manifest to describe the actual delivery.
2. `export_battlemap(plan_id, directory, foundry_image_path, ppi)` needs a **new absolute directory in an existing parent**, inside the encounter directory. Never overwrite a completed bundle or blindly retry into an incomplete directory. For revisions, inspect and replace only the identified generated VTT directory when authorized, preserving the canonical native map and any project bundle; otherwise report the directory conflict. Do not create numbered history folders by default.
3. Wait for completion. Inspect `export.json`, file hashes/counts, warnings and the actual PNG. Retain `encounter.json`, `validation.json`, `foundry-scene.json`, `import-foundry.js` and `battlemap.dd2vtt` together. Current conversion makes **all native portals ordinary doors**; restore window behavior, secret type and locks from the notes. Native LOS becomes normal blocking walls; planner blocking radii and deep-water boundaries add movement-only walls. Review whether those barriers fit the intended encounter, including swimming and crossings. Cover, difficult terrain and zones remain metadata; actors, tokens, game-system automation and ambient sound are not created.
4. For the preferred self-contained route, open the **Scenes** sidebar, click **Create Scene**, enter a name and create/save it. Right-click that scene's **entry in the Scenes list**, choose **Import Data**, select `foundry-scene.json` and click **Import**. The embedded background is handled during GM import; separately uploaded artwork is needed only for path-based exports. Choose **View Scene** afterward. Optionally right-click the same entry and choose **Regenerate Thumbnail Image** (or **Generate Thumbnail Image** in versions using that label) to refresh the preview. Include these exact steps in the handoff and link the [official scene documentation](https://foundryvtt.com/article/scenes/). Import Data overwrites the selected scene, so use a new empty scene unless replacement is intended. The generated GM script remains an optional scene-creation route; it creates another scene each run. Choose one import route.

## Acceptance in the target runtime

After import, inspect and correct the actual scene before describing it as verified:

- Check the background resolves and at least two distant landmarks align with walls, openings and lights; measure a known tile distance. Check all floor origins if there are multiple floors.
- Test a representative owned, sight-enabled token as a player with intended vision settings and fresh/unexplored fog. Check sealed rooms and secrets remain concealed. GM overview alone is insufficient; GM dragging can bypass movement restrictions. Do not reset an existing campaign's exploration just to test; use an appropriate fresh test scene/user.
- Traverse intended routes and crossings. Exercise doors closed, open and locked; verify secret controls and window visibility from near/far and both sides. Look for light leaks, duplicate/overlapping walls and accidental blocked stairs.
- Inspect terrain-wall objects from opposing sides: the rock/canopy should remain visible while a token behind its far side is hidden. Check any tent opening and inside view, nearby Limited obstacles, and walkable gaps at token scale. For directional ledges, test low-to-high and high-to-low sight, access around the ends, and the documented climbing/flying exceptions. These checks supplement structural geometry validation.
- Check lights on/off, bright/dim boundaries and wall occlusion under the intended scene illumination; check any required floor transitions and elevation behavior. Configure any agreed system automation separately and test it.

Deliver the exact bundle/native paths, target generation, scale, corrections made and remaining manual items. Distinguish **files exported**, **scene imported** and **runtime behavior verified**. If Foundry access is unavailable, report that limitation and the pending checks; do not label the bundle seamless or runtime-verified.
