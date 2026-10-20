# Regional lighting: preferred Foundry core workflow

Use this for finished scenes with outdoor space and enclosed rooms/caves. The campaign preference is **bright outdoors by day, at least dim outdoors at night, and no accidental unlit corners in buildings with existing active lighting**. Darkness in a cellar, sealed unlit building, deep dungeon or special encounter can be intentional; record it. This is a playability preference, not a universal claim about real night or D&D RAW.

## Core mechanism and v14 setup

Use core **Scene Regions** with **Adjust Darkness Level**. They can exclude interiors from global illumination while preserving local lights and token sight; no lighting module is required. The examined installed Foundry **14.369** has `adjustDarknessLevel` system fields `mode` and `modifier`: `OVERRIDE=0`, `BRIGHTEN=1`, `DARKEN=2`. BRIGHTEN computes `sceneDarkness * (1 - modifier)`; OVERRIDE uses the modifier itself. Recheck target schemas on other versions.

A supported example for mixed outdoor/indoor maps:

- Global dim baseline: `environment.globalLight.enabled=true`, `bright=false`, neutral appearance and `darkness={min:0,max:0.95}`. This is **dim**, not blanket bright illumination.
- Outdoor region: polygon covering exposed space, with holes matching all enclosed room/cave footprints; `adjustDarknessLevel` with `{mode:1,modifier:0.1}`. Outdoors then ranges from 0 to 0.9 even when the scene darkness slider reaches 1, remaining within the dim baseline's activation range.
- Sealed/windowless regions: precise footprints for unlit rooms/caves, no wall-based restriction on the region shape; `{mode:0,modifier:1}`. Local darkness 1 is above the global-light maximum, excluding environmental illumination. Local lamp/fire lights can still illuminate these areas. Region level IDs and elevation spans must match the playable floor. Preserve existing unrelated regions.
- These numeric values are a matched separation example, not a new universal threshold. Ensure `maximum outdoor local darkness <= global-light maximum < unlit interior local darkness`. Do not blindly use the obsolete 0.8 default, enable global light without exclusions, or force GI off when a verified regional setup is available. A raw adapter scene can keep GI off until regional boundaries are prepared.

### Rooms with actual windows

A room with transparent windows should receive indirect daytime light even where point-light rays produce harsh wedges. Give that room its own **DARKEN** region, e.g. `{mode:2,modifier:0.7}`, instead of the sealed-room OVERRIDE. Core computes `1 - (1 - sceneDarkness) * 0.3`: local darkness is 0.7 by day and 1 at full night. With the matched global dim maximum 0.95, this supplies a diffuse **dim daytime floor** through genuine windows while removing that floor at night. Exterior daylight emitters at the actual apertures add direct bright light. This represents window-borne indirect light; it is not an invented lamp.

Use this only where the artwork and transparent window geometry provide real daylight access. With no fixture, the room can correctly become dark at night and need a carried torch. Sealed rooms, shuttered/opaque windows, deep caves and secret chambers retain the excluding OVERRIDE setup unless a separate light source is intended. Record which openings justify each region; if their availability changes (e.g. opaque shutters), update the regional daylight assumption too. Do not make all rooms daylit simply because they are occupied.

Use non-overlapping exterior/room footprints or explicit exterior holes to avoid behavior-order dependence. Trace actual enclosure boundaries, including closed door segments, without adding new movement/sight barriers. Deep caves and secret rooms must be excluded too. GI itself does not spill through doors; the following emitters provide that behavior.

## Daylight, openings and night

- Start with a few broad, wall-constrained **bright-only** daytime emitters (`dim=0`). Four exposed positions near the map corners can suit a small outdoor map. A 300 ft bright radius is a useful map-scale example, not a fixed rule. Choose enough reach to avoid radial rings inside the playable area and add sources only where coverage/occlusion needs them. All emitters use `vision=false`; preserve genuine wall, rock and token-sight restrictions.
- Place a daylight emitter immediately **outside** each relevant door/window/cave mouth, centered at the aperture with a small verified outward offset. Use broad reach, often the same 300 ft example; walls and door state, not a short radial cutoff, should shape entering light. Closed opaque doors block it; opening one can legitimately brighten the room and mask a lamp's dim zone. A large radius cannot by itself create physical bounce light or soft shadows. Do not invent windows absent from the map.
- Restrict these environmental bright emitters to daylight, e.g. scene darkness 0-0.6, while leaving the global dim baseline available at night. Core v14 AmbientLight activation uses **scene darkness**, whereas region shading/global-light inclusion use local darkness. Night should have subdued cool ambiance and dim mechanical illumination outdoors, never accidental complete darkness under this campaign default. Torches/lanterns can still create bright pools at night.
- Keep environmental sources neutral by day, restrained by night, with no unrequested animation or strong color. Do not use decorative color alpha as illumination strength. Preserve wall constraints; avoid opaque contours around low furniture/clutter. The regional dim baseline fills accidental exterior black wedges and, where actual windows justify it, indoor daytime wedges without erasing physical visibility.

## Minimum interior illumination

**Coverage is conditional on an actual light source. Do not add lamps merely because a building is occupied or to make every building visible.** An unlit, windowless warehouse/room can correctly be dark; characters can bring torches. Window-lit rooms need sensible daytime coverage from the actual apertures, but may be dark at night without a lamp. Check coverage in the intended source state (lamp on, daylight/window available); a closed-door fixture test applies only to fixture-lit rooms. Do not invent fixtures or windows unless the user requests them or the established design includes them. Natural darkness in an unlit room is not an accidental coverage defect.

- Ordinary lit map fixtures use at least **20 ft bright / 40 ft total dim**, the user's Torch-sized campaign minimum. Retain the published equipment profile separately; a candle-lantern upgrade is a GM override, not RAW. Explicit weak/off/special lighting requests take precedence.
- For rooms with active fixtures, close the doors and verify **every accessible part has at least dim light**. Extend the dim radius or add a plausible wall/table/ceiling emitter for large rooms, alcoves and partitions. Do not brighten a large room entirely merely to meet minimum coverage. Ceiling fixtures may keep only their emitter, following the existing artwork preference.
- Use a nonzero interior darkness region so that dim differs visibly from bright even during daytime. At darkness 0, core illumination colors can converge. In a small room, the 20 ft bright radius can legitimately cover most/all of the room; it does not mean the dim field is missing.
- Truly unlit interiors, sealed cellars, deep caves and intentionally dark corners are explicit exceptions with location/reason in encounter notes. Never depend on an open exterior door to meet a room's minimum fixture-light coverage.

## Acceptance and reproducibility

Validate the scene **and behavior system schemas** for the target version. Record region footprints, levels, mode/modifier values, global baseline, light source roles, on/off ranges, bright/dim radii, fixture overrides and dark exceptions in the encounter manifest. Keep the complete JSON, optional creation script and relevant current-scene patches consistent; a tactical-walls-only patch does not install a regional lighting setup.

Check day/night with doors closed/open; confirm dim remains outdoors at scene darkness 1, sealed/windowless unlit rooms/caves stay excluded from GI, window-lit rooms receive daytime dim fill but lose it at night, and rooms with active fixtures meet their dim coverage without exterior help. Test fixture bright/dim boundaries using basic token vision, then intended character senses; darkvision can change the apparent light level. Inspect real player views at entrances, far corners and behind structures. Do not reset campaign fog or rewrite token senses to conceal lighting mistakes.

Geometric coverage, core formula tests and schema round trips are offline evidence only. They do not establish successful import or shader/player-view appearance. State runtime checks that remain pending.

Sources: [Foundry Scene Regions](https://foundryvtt.com/article/scene-regions/), [lighting controls](https://foundryvtt.com/article/lighting/), and the examined installed v14.369 region behavior, global source, illumination shader and visibility code.
