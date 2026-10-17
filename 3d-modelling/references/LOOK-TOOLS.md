# Look tools: measuring what makes a model read as "computer made"

Tools: `~/.claude/skills/3d-modelling/scripts/look/`. Run them at every round, beside the integrity check.
They are **advisory**: a number outside its band means "look here", never "fail". The bands rest on two train cars
(A and B below) and 7 CC0 references, none of them a rail vehicle; re-set them once ten or more accepted and rejected
assets of yours have been measured. Why they are measured and not asked: a vision
reviewer answered "yes" 12 times of 12 to the edge question whatever the bevel, and picked the unbevelled model in
both A/B orders.

## One command

```bash
python3 ~/.claude/skills/3d-modelling/scripts/look/look.py FILE.blend --out DIR            # or FILE.glb
python3 ~/.claude/skills/3d-modelling/scripts/look/look.py FILE.blend --out DIR --camera-set film
python3 ~/.claude/skills/3d-modelling/scripts/look/look.py FILE.blend --out DIR \
        --reference CONCEPT.png --reference-view side --reference-crop 1040,95,1525,350 --reference-bg-tol 6
```

Options: `--family train|building|city-kit` (default train), `--collection NAME`, `--body REGEX`, `--front +x`,
`--views front34,side,rear34`, `--mesh-only` (3 s, no render), `--overlay` (marked pictures), `--json`.
From Python: `import look; r = look.run(path, out_dir)` returns what `DIR/look.json` holds (`r['lines']`,
`r['result']`, `r['outside']`, `r['measures']`). Exit code 0 whatever the result, 2 when a tool broke.
It never saves its input. About 25-35 s for a 270-370k triangle original (mesh 3 s, picture pass 16-29 s on a
shared GPU at 32 samples, metrics 3 s); peak 1.6-1.8 GB. Blender runs `-b --factory-startup -noaudio -t 8` under
`nice 10` in a 12 GB memory scope.

## Reading the output

At most 10 lines. One line per measure outside its band, then the result:

```
LOOK razor_share 0.1661 (band <= 0.02) gangway_bellows x9, window_sash x14, door_frame x4
LOOK body_bevel_mm 6.9 (band >= 7.6) body_shell, faceted, = 1.4 px at 7.5 m
LOOK rest_cells 0.047 (band 0.2-0.35) lowest: side view 0.015
RESULT LOOK 9
```

`LOOK <measure> <value> (band <band>) <where>`: the where is the parts carrying most of it (mesh measures, with
their instance counts) or the view with the worst value (picture measures). `RESULT OK` = everything inside.
`LOOK textures missing: n` first means the picture and every colour number are wrong (a copy of a `.blend` with
relative texture links must sit at the same folder depth as the original). Put the lines in the hand-back and say
for each one what you changed or why it stays (a deliberately flat-shaded part, a naturally busy asset).

## The measures

| Measure | Band | What it is | Two train cars (A / B); references |
|---|---|---|---|
| `razor_share` | <= 0.02 | Corner length (weighted by turn angle) that is a hard edge between two wide faces: it can never catch a highlight | 0.17 / 0.08; 0 |
| `facet_share` | <= 0.02 | A bevel that is there but shades flat, or whose boundary against the face is a hard edge | 0.59 / 0.10; 0 |
| `flat_shaded_area` | <= 0.05 | Surface area with flat shading | 0.74 / 0.17; 0 |
| `body_bevel_mm` | >= 1.5 px at the nearest camera (game: 7.6 mm) | Whole bevel width, all segments, on the shell (the largest single part; `--body` names another) | 6.9 / 6.5 mm = 1.4 / 1.3 px |
| `base_colour_spread` | >= 0.20 | Spread of base colour inside a material; 0 = each material one flat value | 0.19 / 0.12; 0.25-0.41 |
| `dark_in_cavities` | >= 0.20 | Correlation of "darker than its material" with occlusion: grime where parts meet | -0.03 / 0.12; up to 0.57 |
| `dark_low_down` | >= 0.20 | The same against height: road and wheel film | -0.05 / 0.20; up to 0.61 |
| `largest_material_variation` | >= 0.12 | Variation inside the material covering most of the picture | 0.34 / 0.06 (aluminium over 52 %) |
| `rest_cells` | 0.20-0.35 | Share of 32 px picture cells of the asset with almost no detail: calm areas | 0.05 / 0.17; 0.26-0.32 |
| `busy_cells` | <= 0.55 | Share of cells dense with detail | 0.75 / 0.66; 0.32-0.53 |
| `hull_features_side` | >= 3 | Things that break the convex outline in the side view | 5 / 0; 3-16 |
| `hull_features_side_mid` | >= 2 | The same at the size the asset has where its mid version appears | 3 / 1 |
| `proportion_error_pct` | -2 .. +2 | With `--reference`: how much taller for its length the reference is than the model | car B vs its concept flank: -0.7 to -1.5 |

No band, in `look.json` `info`: `edge_light_line` (share of convex creases showing a light line; weak, moves 0.03-0.05
with wide bevels and depends on gloss), `orientation_entropy` (flags flutes), `dead_share`, `hull_fill` (0.97 = a box),
`materials_effective`, `tonal_range`, `strip_width_median_mm`, `triangles`. `mesh.json` also has shape sizes by decade
and triangle repetition (misplaced budget: 33,432 triangles sat in one car's maker's plate).

Each tool's `--help` gives the exact definition: `mesh_look.py`, `look_passes.py`, `look_metrics.py`,
`proportion_overlay.py`, `look.py`. Definitions live as constants at the top of `mesh_core.py` and `look_metrics.py`;
bands and their fixes in `bands.py`.

## Camera pixel sizes it assumes

From ONE file, `~/.claude/skills/3d-asset-making/scripts/switch.json` (camera fov 40 deg, 1080 rows, so
1 px = distance x 0.000674 m; per family the nearest look `near_m` and the switch ranges with their hysteresis):

| Camera set | Nearest look | Body bevel band (1.5 px) | Outline re-measured at |
|---|---|---|---|
| `game`, family train | 7.5 m = 5.1 mm a pixel | >= 7.6 mm | 92 m (62 mm a pixel) and 292 m (197 mm a pixel) |
| `game`, family city-kit | 7.5 m | >= 7.6 mm | 18 m and 64 m |
| `film` | the picture pass scaled to a 1920 px frame (a 10 m car: about 5.8 mm a pixel) | 1.5 px of that | full size only |

"An edge reads from about 1.5 px" and "a thing on the outline reads from about 2 px" are derived from pixel size, no
source states them. No camera table exists for film shots, so the film set is a derived stand-in: say so when quoting it.

## Fixing the usual causes

- **`razor_share` high.** Parts with no bevel at all (window sashes, door frames, bellows). Add a Bevel
  modifier with limit ANGLE 30 deg, sized by tier: primary corners the real radius and never under 60 mm; parts
  0.2-2 m 12-25 mm in 2 segments; parts under 0.2 m 3-6 mm in 1 segment; bolts and rivets none.
- **`facet_share` high, cause 1: flat shading.** The bevel is there but the mesh is flat-shaded (`flat_shaded_area`
  names the parts). Shade smooth.
- **`facet_share` high, cause 2: Harden Normals plus WeightedNormal with Keep Sharp.** Measured in Blender 5.2.2: the
  Bevel modifier's Harden Normals marks the bevel's boundary edges sharp, so a WeightedNormal with Keep Sharp after
  it splits the normals there. A 1-segment bevel becomes a flat chamfer (facet 99.8 %); a 2-segment bevel is round in
  the middle with a hard break against the face (136 m of it on one body shell). Use ONE of them:
  Harden Normals alone (the big faces stay exactly flat) or WeightedNormal alone (0.2-0.7 deg off). Plain smooth
  shading with neither bulges the big faces by 15-29 deg.
- **`body_bevel_mm` low.** The number is the whole bevel across (a 4 mm OFFSET bevel in 2 segments on a square corner
  measures about 6.5 mm). Widen it to the band; Clamp Overlap shrinks bevels on thin parts without saying so, and a
  part scaled along one axis on its mount has stretched bevels, so read the result back here.
- **`base_colour_spread`, `dark_in_cavities`, `dark_low_down` low.** Nothing has happened to the surface. Use the
  shader library's wear layer (next section). On strongly textured materials (varnished wood) the two
  correlations stay weak whatever is done: say so instead of chasing them.
- **`largest_material_variation` low.** One value over a third of the picture or more. Per-panel value jitter of
  3-5 % and roughness +-0.05, a soft roughness noise; three gloss tiers (matte, satin for most of the area, glossy
  accents under 5 %).
- **`rest_cells` low, `busy_cells` high.** Detail spread evenly, which is what arrays produce. Before modelling write
  three lists: 3-5 clusters where detail is dense and functional, the rest areas that stay plain (upper side band,
  roof field, nose crown), the splits (70/30, not 50/50). A repeated pattern covers at most a third of a face.
- **`hull_features_side` low.** A box outline. Functional things that stand proud: roof pods and vents, horn,
  collector, underfloor boxes below the skirt, coupler, lamps, steps, handrails; each at least 2 px where it must
  read (12 cm at 92 m, 40 cm at 292 m). Enlarge decorative mass only.
- **`proportion_error_pct` outside +-2.** Open `overlay.jpg`: yellow is what was taken as the reference outline (a
  white car on cream needs `--reference-bg-tol 6`), red the model outside it, blue the reference outside the model.
  The fit's own noise is about 1 %, and the two flanks of a near-symmetric car fit almost equally (0.9455 against
  0.9457), giving -0.7 or -1.5 on the same pair. It sees outlines only.

## Wear: the recipe, and where it lives

A what-if study settled the recipe: four masks, about half of photographic strength, warm,
no chipping to bare metal. Keep it as ONE layer in your shader library, written once and emitted to Blender nodes and
to the game's GLSL, never as a second copy per asset (it is not part of this toolkit).

1. **Cavity grime**: mask R (ambient occlusion, rays 12 cm). Dirt where parts meet; it is also the contact shadow
   the game cannot draw.
2. **Low road film**: below `grime_height` (0.9 m above the rail), broken by low noise.
3. **Runs**: vertical streaks on upright faces (`runs`).
4. **Touched-edge polish**: mask G (convex edge), only on the slots a hand, foot or door reaches (`polish`): lighter
   and glossier, never metal.

The Ambient Occlusion and Bevel shader nodes exist in Cycles only and never reach glTF: bake R and G once per
ASSEMBLY, in world space, with your library's mask baker (every other part of the assembly occludes; baked per
component the grime restarts at every component boundary). Values for a warm, miniature-look game: `grime` 0.2-0.35, `runs` 0.3-0.5,
`polish` 0.5-0.8 on touched slots and 0 elsewhere, `wear` (paint.worn's chipping to bare metal) 0.

## Limits

- Bands: 2 assets and 7 references; thresholds inside the picture measures were set by eye on 13 picture sets.
- Picture numbers repeat to about +-0.003 between runs (GPU sampling). The pass itself gives a spread of 0.01 on a
  material of one value.
- On a triangulated file (GLB) the bevel walk stops at one segment, so a multi-segment bevel reads narrower.
- The body pick (largest single instance by area) can pick a floor or a liner on other asset kinds: check
  `mesh.json` `body_bevel.candidates`, name it with `--body`.
- The picture pass needs Cycles (base colour, AO and index passes) and imports the shared `render.py` for the
  reviewers' light and cameras: when `render.py` changes its light, these numbers move with it.
- Nothing is judged in the game renderer.
