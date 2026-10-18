# Dungeondraft MCP operation notes

Read for level setup, repetitive placement, lifecycle operations and delivery. These notes reflect the examined protocol 23 bridge; **live capabilities, tool schemas and project instructions take precedence** when versions change.

## Levels and layers

- `list_levels` returns native IDs, labels and current indices. `add_level(label=...)` creates a blank level at **index 0** and leaves the old level active. It does not copy the ground. Refresh the list after each creation; resolve the desired stable ID/label to its current index before `set_level(index=...)`. IDs may be reassigned when loading a saved map.
- Create Ground and only the true upper floors/basements present in the encounter. Put secrets on their actual floor; use VTT fog of war to conceal them rather than separate secret/GM native levels or duplicate player/GM exports. Omit decorative roofs and roof levels/layers by default: unrevealed buildings will be black in the VTT. If the user explicitly requests a roof view or playable rooftop, align it with the building beneath. A new level may reorder the list; do not rely on creation order matching elevation.
- When an explicitly requested roof occupies a separate level, switching to its underlying floor exposes that interior. The examined bridge has no dedicated Compare Levels/opacity tool. If that UI setting is required, ask the user to configure it rather than resorting to computer use. Do not claim a screenshot proves a combined view unless actually inspected.
- Objects use `layer` in -1000..1000; floor patterns use native `z`. Paths use their own **0..3 layer indices**. These ranges are not interchangeable. Terrain and water have dedicated native components on each level.
- Example drawing order within a level: floor patterns below props, pier/deck floors above native water, cargo above those floors, foliage above ground details. Pick values for the scene; do not treat an old scene's numeric layers as universal architectural levels.
- For an explicitly requested roof, `add_roof` accepts a **ridge line**, not a perimeter. For a gable roof, span the full long axis and use half the short dimension plus modest eaves as `width` in woxels. Inspect coverage and alignment. Separate roofs at different orientations for an L-shaped building when appropriate.

## Placement and batches

Use `list_asset_metadata`/`list_assets` with category, substring, offset and bounded limits; discover actual paths instead of guessing them. For an asset width of 256 woxels, scale 1 spans one tile, or 5 feet at the default scale. Transparency padding can make texture size differ from its visible or mechanical footprint.

Get supported batch commands/limits from `get_capabilities.batch`. The examined version permits up to 500 operations but at most 16 terrain and 16 water operations per job, and restricts terrain brush radii within batches. Preflight rejection means no edits were accepted. Correct the payload; inspect a failed or uncertain accepted job before retrying. Retry uncertain submissions with the same key in the same bridge instance. Keep editor UI and active level unchanged during a running job.

Colorable assets may need explicit tint at creation. Inspect actual artwork rather than trusting names: a campfire log prop may need a separate flame, a hanging cage may differ from a floor cage, and a mud decoration can look like a blue pool. Use native patterns/floors, not opaque props as substitutes for rooms.

## Lifecycle and exports

- The mod initializes after a map loads. Ask the user to launch/open/create the correctly sized map when required. Do not call internal `Master.CreateNewMap`, private dialogs or disposable prototypes to bypass this dependency.
- Save before replacement. The examined bridge rejects reopening over populated levels, and native populated New Map cleanup has failed even without mods. Ask the user for a fresh editor session when needed; do not force a replacement or silently kill an application.
- `save_map` confirms native JSON. Wait for saving/exporting and native save callbacks to finish before further lifecycle changes. Bridge history is separate from native Ctrl+Z; not every operation is undo-recorded.
- Planner records are bound to one bridge instance and native level. Save supported project bundles; after restart/load, restore ownership with the supported project loader before revising/exporting the plan. Do not fabricate a planner record for arbitrary manual edits.
- Native PNG export in the examined bridge targets the active level. Inspect its contents and dimensions; it is not automatically a composite of all floors. `export_battlemap` requires a validated applied/restored **single-level** project. Multiple-level VTT scene export and automatic roof/ground compositing are not established by that tool. Preserve the levels and provide per-floor native exports or ask for the supported manual export settings.
- Respect native export bounds: 16 megapixels and 8192 pixels per side in the examined version. Choose pixels per tile from map size and verify the written PNG. A 30×30 map at 128 pixels/tile is 3840×3840 and represents 150×150 feet at 5 feet/tile.
- Deliver grid origin, resolution, per-floor alignment and gameplay notes. Treat VTT file generation and successful import into a target runtime as separate outcomes.
