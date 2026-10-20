# D&D 2024 lighting quick guide

Use this when choosing illumination for a D&D 2024 map. Source identity and current state determine the profile; sprite size alone does not. For another edition/system, verify its own rules.

**Foundry measures both radii from the source.** Enter `Bright = bright radius` and `Dim = bright radius + additional dim distance`. A torch's additional dim distance is 20 ft; its Foundry Dim field is **40**, not 20. These are radii, not diameters. See [Foundry lighting controls](https://foundryvtt.com/article/lighting/).

## Published equipment profiles

Values in feet, verified against the official [2024 equipment rules](https://www.dndbeyond.com/sources/dnd/br-2024/equipment):

| Equipment/state | Bright | Additional dim | Foundry Bright / Dim |
| --- | ---: | ---: | ---: |
| Candle | 5 | 5 | **5 / 10** |
| Oil lamp | 15 | 30 | **15 / 45** |
| Torch | 20 | 20 | **20 / 40** |
| Hooded lantern, hood raised | 30 | 30 | **30 / 60** |
| Hooded lantern, hood lowered | 0 | 5 | **0 / 5** |
| Bullseye lantern | 60 | 60 | **60 / 120**, directional cone |

A small lantern is not a separate standard equipment profile. Choose its contents/construction explicitly:

- **Tiny candle lantern:** use the Candle profile when it houses a candle; record that equipment interpretation.
- **Small oil lantern:** a useful local default is the Oil Lamp profile, **15 / 45**. Mapping that asset to a Lamp is an encounter choice, not a separate published “small lantern” rule.
- **Actual hooded lantern:** use its published raised/lowered profile, even if the chosen sprite is small. Do not silently scale a rules item by artwork size.

## Campaign minimum for placed map fixtures

The user's map-creation preference overrides the small-equipment defaults above: ordinary lit lamps/lanterns and equivalent fixtures use at least **20 ft Bright / 40 ft total Dim** (Torch-sized illumination). This is a campaign/GM display choice, not a claim that a published Candle or Lamp has Torch statistics. Retain the RAW profile/source separately from the delivered map profile and the reason for the override. Explicitly requested weak, extinguished or special lights retain their intended state/profile.

A room with existing active lighting should have at least **dim light throughout its accessible area**, with doors closed and no borrowed exterior light. This does not require adding a lamp to an unlit room; occupancy alone is insufficient. A windowless warehouse can need carried torches, and a window-only room can be dark at night. For window-lit spaces, check daytime aperture illumination instead of imposing a new fixture. Check far corners, alcoves, adjoining rooms and walls. Extend the dim reach or add a plausible lamp/ceiling emitter when necessary; do not automatically expand bright to fill a large room. Record deliberately dark rooms/areas instead of treating accidental black patches as atmosphere. A small room may fit entirely within a 20 ft bright radius; this is consistent with the minimum, not a missing dim setting.

## Suggested mundane-fire defaults — GM rulings

The accessible 2024 equipment/vision text gives no universal mundane campfire-size table. These are practical encounter defaults, **not prescribed campfire rules**. Adventure-specific values or an explicit GM choice take precedence.

| Fire in the encounter | Bright | Additional dim | Foundry Bright / Dim | Intended use |
| --- | ---: | ---: | ---: | --- |
| Small cooking fire / modest brazier | 20 | 20 | **20 / 40** | Torch-equivalent local default. |
| Large campfire / large brazier | 30 | 30 | **30 / 60** | Larger gathering/work area. |
| Bonfire / substantial burning pile | 40 | 40 | **40 / 80** | Strong local illumination; assess its actual size. |

Embers, a smothered fire or a major blaze need a separate explicit ruling; do not automatically apply one of these rows. A mundane cooking fire is not the *Create Bonfire* spell. These profiles assign illumination only, not damage, smoke, fuel consumption or automatic hazard rules.

## Export and acceptance

Record the source/profile, bright radius, additional dim distance, Foundry total dim radius, on/off/hood state, rules citation and any GM assumption in the encounter manifest. Native artistic light ranges, brightness or flame sprites do not establish those values. Preserve the chosen radii in both new-scene exports and any current-scene patch.

Universal VTT carries one range, and the examined importer derives bright as half dim. That reproduces 20/40 but **cannot encode Lamp 15/45 correctly**. Supply explicit Foundry corrections for that profile; setting its outer range to 45 alone produces 22.5/45 in that importer. See [the export workflow](foundry-vtt.md).

Review color/animation separately. Test the bright boundary, outer dim boundary, wall interaction and hood changes using a player-view token under night/test lighting. Global daylight can mask errors. Do not reset campaign fog or rewrite token senses to hide a light configuration problem.

### Regional environmental lighting

Use [regional lighting](regional-lighting.md): core Scene Regions keep room/cave darkness separate from outdoor daylight and dim nighttime illumination. Environmental day emitters use bright-only coverage; indoor fixtures retain distinct bright/dim ranges. A scene or room darkness level near zero can make bright and dim look alike even when their radii are correct; use the interior region to provide visual separation, and test with basic vision before attributing the result to the light profile.

### Avoid excessive visual glow

Rules radii describe illumination coverage, not glow strength. Foundry's `config.alpha` is **Color Intensity**, distinct from `config.luminosity`, which controls rendered brightness. Native Dungeondraft `intensity` is not a directly interchangeable alpha. The examined adapter copied native intensity 0.9 to alpha 0.9; Universal Battlemap Importer used `0.05 * intensity`, giving 0.045 for the same source. That twentyfold increase in color intensity caused the reported washed-out fire/lantern appearance.

When preserving an existing imported map's appearance, match its known working visual settings before changing ranges. A previously verified camp example used alpha **0.045**, normal Adaptive Luminance coloration (`coloration: 1`), luminosity **0.5**, attenuation **0.5**, and neutral contrast/saturation/shadows. These are an artwork-specific reference, not a mandatory preset for future maps or a D&D rule. Preserve the chosen campaign bright/dim distances while adjusting appearance. Avoid halo, sunburst and intense animations unless requested; inspect actual Foundry rendering before claiming visual acceptance. See [Foundry's color intensity and luminosity controls](https://foundryvtt.com/article/lighting/).
