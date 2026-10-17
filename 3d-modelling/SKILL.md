---
name: 3d-modelling
description: "Read before modelling, simplifying (LOD), exporting or reviewing any 3D asset. Keeps every version of a model one sound object: nothing detached or floating, no unexpected cracks or holes, no damage from simplification. Has a Python + numpy check for .glb files (floating parts, open edges, inside-out and turned faces, blinking faces, what a lower version lost) and the look-twice procedure."
---

# 3D modelling: every version is one sound thing

Written after the far version of a small lamp on a mast clamp came out with parts flying in space: look twice for
parts detached from one another, unexpected cracks, and what a simplification turns a model into.

The whole asset job (library first, generic parts, times of day, maker and API cost on the dashboard card) is skill
`3d-asset-making`. This one is about the object itself and applies in any tool.

**Default launch split**: plan with Opus at effort `xhigh`, then model in a fresh worker with Opus
at effort `low`; details in `3d-asset-making` "Launching a modelling worker".

## The failure, measured

The lamp's near version was a lens on a riser, a base, a plate held by U-bolts, a cable. The mid and far versions
were made by deleting the small parts (the seat collar, the bolts, the cable) and reducing each remaining part by
itself. Nothing closed the gaps the deleted parts had filled. Result: in the far version the red lens hangs above
its post with air between them and the plate stands apart from the base; in the mid version a cable ends in the air.
The check below counts 3 separate bodies in each version and finds 59 % of the near surface gone in the far one.
The maker and two reviewers passed it, because all of them looked at it only at the size it has in the game, where
a 3 cm gap is less than a pixel. The next person opened it in the asset dashboard, large.

Four causes, each with its rule below:

1. **A lower version was judged only small.** Small on screen hides the fault from the maker, not from the next
   person who opens the file.
2. **Parts were removed without closing what they joined.** A connector's job does not go away with its triangles.
3. **Each part was reduced alone.** Two parts that met along an edge no longer meet after each was decimated
   separately: a crack, or a gap.
4. **"It touches" was assumed, never measured.** Even the near version had parts 11 mm apart.

## Keep your place on disk

A long modelling session outlives its own memory: when the context fills, it is cut down to a summary, and whatever was
only in your thinking (the plan, the dimensions, the half-written generator) is gone. Measured on one project: sessions
cut every half hour read the same source files three times over and produced nothing for seventy minutes; sessions that
were never cut did not. You cannot see the cut coming, so work as if it were always near.

- **Before the first model call, write the plan to your progress file:** what you keep of the existing asset and what
  you replace, the main dimensions, the parts, the functions you will write, the exact commands you will run (export,
  check, pictures), the next three steps. Enough for someone with none of your memory to go on without reading the
  sources again.
- **Write code to disk a part at a time and run it.** Do not hold a whole generator in thought before the first line is
  saved. Save the scene after every step that changed it.
- **After every step, one line:** done, measured result, next.
- **Read once.** What you need from a long file goes into the progress file as a few lines; later, search for the one
  line, do not read the file again. Pictures too.
- **Start small.** Read what the brief names for your asset; a tool's code is read only when the tool surprises you.

## While modelling

### Place parts by relation (kit3d), pass them by measurement

Measured on a train car original: grab-handle roses floating 3.3 mm, marker lenses only touching,
louvres and the step tread z-fighting, 188 of 188 parts without UVs. All of them were placed by typed coordinates.

- Build every part with `kit3d` (scripts/kit3d, `import kit3d as k`): parts are PLACED BY RELATION, never by typed
  coordinates along a host's normal: `attach` (rests on / enters its host by 5 mm at the shallowest point; curved hosts
  included, `conform=` bends bases/frames/glass onto them), `span` (rails, rods, handles, springs built from their two
  ends), `lay` (decals/stripes/lettering 6 mm off, or `cut=True` inlaid flush in a pocket), `scatter` (rivets),
  `into` (a part built in place: measured, not moved), `free(reason)` / `root()`.
- Shapes come with UVs in metres; images read through UVs; every material value has a source (`ref=` fills measured
  values from the Physically Based table; unsourced numbers are tagged `inferred`).
- A part is done when `kit3d.check` PASSES (entry 2-10 mm, lift 6 mm, no unplaced part, no two faces within 2 mm,
  no back-to-back duplicates, sound UVs): the numbers decide, not a 650 px picture. A FAIL line names part, host, mm
  and place; fix the relation, never the threshold.
- Work in steps: `3d-asset-making/scripts/bridge.py step <port> part.py --part NAME --thumb` (one part, <= 8 lines back, versioned .blend,
  thumb, parts.json flags). Plan first in parts.json (kit3d/PARTS-SCHEMA.md) and run plan_check.py; only tools flip
  its flags.
- On a Blender error: look it up in references/PITFALLS-blender-5.2.md; fix the cause, never delete the line.
- Examples: `scripts/kit3d/examples/` (14 parts; `run_all.py` builds, checks and draws each) — copy the closest one.

### Rules that hold in any tool

- **Everything is held by something.** A part touches or enters what carries it. Let a part enter its seat by a few
  millimetres instead of resting exactly on it: exact contact turns into a gap after any rounding, export or
  reduction, and into flicker where two faces share a plane.
- **No slits: parts that belong together meet.** A roof a few mm above its wall, a bogie hovering under the body, a trim
  strip short of its panel: light shows through and the part reads as stuck on. Let one part enter the other a few mm
  (never exactly flush: that blinks, below); a gap that is designed (a door seam, a shadow line) is drawn on purpose and
  named in `NOTES.md`. `mesh_integrity.py` GAPS lists every pair of parts that comes within the touch distance yet never
  meets within 0.3 mm, with size and place: close each or name it as designed in the hand-back. Watch the LOD and bake
  steps: they open slits that the original did not have.
- **No blinking: never two surfaces in one place** (it is visible only when scanned for from several angles).
  Z-fighting: two faces sharing a plane
  and overlapping, so the depth buffer orders them differently from frame to frame. Where it comes from: a decal, stripe,
  plate or trim laid flush on a panel; two parts overlapping inside a shared wall or end; a duplicated face; a bake
  that merged an inner and an outer skin; a far LOD shell over a near one. Prevent it: lift an applied layer clear of
  its base by more than the depth step where the version is drawn FARTHEST (see the next bullet), or cut the base under
  it; delete the face that is hidden, join overlapping parts with a boolean or let one sink a few mm INTO the other (an
  entering part is fine; a coplanar one is not). **Check it twice:** `mesh_integrity.py`
  FLICKER (overlapping faces in any orientation that lie within 2 mm of each other where they overlap; over 1 cm2
  facing the same way is a FAULT) on every version, and by eye a
  **sweep**: in the game's renderer with the game camera's near/far, turn the model in small steps (a few degrees) at
  its closest and usual distances and compare neighbouring frames; one still never shows it, since the blink depends
  on the angle and the distance. **Back-to-back faces blink too when the material is double-sided** (a train car's near
  version: 80 back-to-back pairs, 4.1 m², bands across the end door): a closed wall exports
  single-sided, or the hidden inner skin is deleted; `doubleSided` only for real single sheets (glass, flags).
- **The depth step grows with the square of the distance, and a version is drawn out to the far end of its range**
  (a train shell showed a jagged blinking line along its end walls). Step = z² / (near · 2^24), near = the game
  camera's near plane (`3d-asset-making/scripts/switch.json` camera.near_m, 0.5 m in the example): 0.06 mm at 7.5 m, 1.2 mm at 100 m, **7.3 mm at 248 m** (a train's near version on full graphics),
  63 mm at 728 m (mid). The shell was built from panels that overlap their neighbours by 2.5 mm (`shell_parts.py`
  OVER): `end.gangway` and `shell.lower` share 577 cm² within 15 mm across each end face. That passes the 2 mm check
  and blinks as a jagged line from about 100 m on. So, from the first part:
  - **one skin is one surface.** Panels of one skin butt edge to edge (or are one mesh with the seam drawn as a
    groove, 8-12 mm wide and 6-10 mm deep); they never overlap in the skin's own plane. Where two parts must overlap,
    delete the faces the overlap hides (two solids side by side: drop BOTH coinciding faces, below). Lifting further
    does not scale: no lift survives 728 m;
  - **nothing hides a few mm behind a surface** (the visor sat 3.5 mm behind the nose over 201 cm²): delete what is
    covered, or recess it well past the step;
  - **check at the far end:** `mesh_integrity.py --seen-to near|mid|far --family F` adds an AT DISTANCE line with the
    places (`render.py round` runs it with `near`; advisory there, since a 6 mm decal lift reaches it beyond ~160 m).
    The 2 mm FLICKER stays the strict gate.
  - **Cycles never shows z-fighting** (exact rays), and a viewer with a tiny near plane shows far too much of it
    (a viewer once had a near plane of 0.9 mm). A blink seen in one viewer only: first read that viewer's near
    plane (`window.__glbCheck.clip` in the asset dashboard), then judge the model with `--seen-to`.
- **Variants of one asset never stand at one origin in one file** (four
  class shells stacked in one `.blend` read as black dashes and a frosted roof in every viewer, and
  the checker counted 3.5 M blinking pairs). Put each variant in its own file, or its own collection placed side by
  side (1.25 × its width apart) and listed as variants in the asset's record. The asset dashboard spreads such
  collections for display, but the next tool will not.
- **Every textured part has a real UV map, and its look must survive the game export** (a car's guide tyres: what
  looked like blinking was not two faces). The tyre read `rubber.png` through Texture
  Coordinate > Object and ran it through Mix/Math (colour), Map Range (roughness) and Bump (normal). Cycles renders that
  fine, but glTF has none of those nodes: unless the export bakes the graph, it writes the raw photo as colour,
  roughness AND normal map, with `texCoord -1` because the mesh had no UVs (268 component meshes of one car had none).
  The result is per-pixel speckle that shimmers with the view, and shiny silver "rubber". So: unwrap every textured
  part when you make it (components above all: one without UVs breaks every asset that uses it), and never let two
  surfaces share texture space (Solidify gives the inner skin the outer skin's UVs: in any bake the last face wins, so
  a car's steel took the inner wall's metallic 0 and turned white; unwrap the inner skin apart); expect any graph beyond
  image → Principled to be baked; and check the game version, not the film render. Tell blinking from speckle:
  blinking is patches that swap with the angle; speckle is grain over the whole part at every angle. The dashboard
  exporter (`export_blend.py`) now unpacks collection instances, bakes such graphs once per shared mesh,
  and refuses to publish a textured primitive without UVs.
- **Model the connection, not only the two things.** A lamp has a seat, a bracket has bolts or a weld, a cable has
  both ends in something, a sign has its fixings. If you would not know how to build it, it is not finished.
- **What is separate by design is declared.** A bird over a roof, a banner between two posts, a hanging lamp on a
  thin wire that the far version drops: list each in the asset's record with the reason. Everything not on that
  list must be attached.
- **Closed where it would be closed.** A wall has thickness, a box has all the sides one can see, a tube has ends
  or enters something. An open edge is fine where nothing can ever look (the underside of a ground slab) and is a
  fault anywhere else.
- **An open edge on a solid that has no hole is usually a T-joint.** A cap or face triangulated across a side that
  carries extra points (the stepped section of a row of seats) gives slivers and edges that meet in the middle of
  their neighbour. Triangulate such faces with the points on straight sides kept as corners (a constrained
  Delaunay; in Blender `mathutils.geometry.delaunay_2d_cdt`), then check again.

## Make it look made by a master

Measured on two sound train originals that read as "computer made": body bevels of 3 mm (0.6 px at the
nearest camera), 74 % flat-shaded, razor window sashes, one metal value over half the picture, even detail, a box outline.

- **Size every edge for the screen.** 1 px = distance x 0.000674 m (5 mm at 7.5 m, 22 mm at the 33 m chase camera);
  an edge reads from about 1.5 px. Primary corners (roof to side, side to end, nose): the real radius, never under
  60 mm. Secondary parts 0.2-2 m (door leaves, frames, housings, boxes, steps): 12-25 mm, 2 segments. Small parts
  (handles, brackets, hinges): 3-6 mm or 3-4 % of the part, 1 segment. Bolts and rivets: none.
- **Shade bevels round.** Smooth-shade the mesh, then Bevel (limit ANGLE 30 deg) with EITHER Harden Normals OR a
  WeightedNormal modifier after it, never both with Keep Sharp: in Blender 5.2 Harden Normals marks the bevel's
  boundary edges sharp, and WeightedNormal with Keep Sharp then splits the normals there (a 1-segment bevel becomes a
  flat chamfer, 99.8 % facet on a test cube; a 2-segment bevel gets a hard break against the face; one train
  shell had 136 m of this). `look.py` facet_share catches it. On flat-shaded faces neither does anything. A bevel's
  width is the WHOLE bevel across, all segments. Bevel at final size: a part scaled along one axis on its mount gets
  stretched bevels. Clamp Overlap shrinks bevels on thin parts without saying so. Never bevel everything with
  2 segments (doubles the triangles): follow the tiers. Lower versions keep the bevel in the normal map (30 mm on
  frame and door edges reads at 7.5 and 33 m; 15 mm vanishes at 33 m) or as a 1-segment chamfer with weighted normals;
  a split-normal razor edge survives in no version.
- **Compose the detail before modelling.** Write three lists in the plan: 3-5 clusters where detail is dense and
  functional (cab front, each doorway, bogies with underfloor gear, roof equipment); the rest areas that stay plain
  (upper side band, roof field, nose crown); the splits, 70/30 not 50/50 (belt line, window band against pier, two
  or three panel widths). A repeated pattern (flutes, planks, rivet rows) covers at most a third of a face and is
  interrupted by something that has a job. Count your arrays: evenness is what code produces by default.
- **Break the outline.** Things that stand proud and have a function (roof pods, vents, horn, collector, underfloor
  boxes below the skirt, coupler, lamps, steps, handrails), each at least 2 px where it must read: 12 cm at the 92 m
  switch, 40 cm at 292 m. Enlarge decorative mass only; doors, people and functional sizes stay real.
- **Functional detail at real size.** Doors 1.9-2.1 m, handles 25-35 mm tube, steps 16-30 cm deep. A seam is drawn
  8-12 mm wide and 6-10 mm deep with a bevelled lip (a real 4 mm gap is under a pixel). Fixings where the eye goes
  (door hardware, lamp rings), not in rows over everything. Lettering on a plate is a texture: spend triangles
  where the camera looks (33,432 were in a maker's plate, none in the nose crown; read `mesh_look.py` repetition).
- **Something has happened to it, quietly.** Four masks, computed at the ASSEMBLY in world space and baked (their
  nodes are Cycles-only): cavity (Ambient Occlusion node, 12 cm) = grime where parts meet, which is also the contact
  shadow the game cannot draw; low (bottom 0.9 m, broken by noise) = wheel and road film, densest at the bogies;
  streaks (noise stretched along Z on vertical faces) under gutter ends, window corners, door heads; edge
  (1 - dot(Bevel-node normal, true normal), broken by fine noise) only where a hand, foot or door reaches. Dirt
  darkens and dulls; touch polishes. About half of photographic strength, warm tones, no chipping to bare metal.
  The shared implementation is the shader library's `wear_layer` (ends every opaque kind; cavity grime, low road
  film, runs, touched-edge polish; mask R and G baked once per assembly with `library/wear_mask.py`): `grime`
  0.2-0.35, `runs` 0.3-0.5, `polish` 0.5-0.8 only on slots a hand, foot or door reaches; set `paint.worn`'s older
  `wear` to 0 (it chips to bare metal). First version: the runs still read as even bars, not rain runs.
- **No large area of one value.** The biggest material varies by at least 12 % inside itself: per-panel value
  (+-3-5 %) and roughness (+-0.05) jitter, a soft roughness noise. Three gloss tiers: matte (canvas, rubber, grime),
  satin (paint, brushed metal: most of the area, roughness 0.4-0.55), glossy (glass, lamps, chrome accents under 5 %).
- **Restraint: "more real" is not "better for the game".** Measured twice (blind vision-model pairs in both
  orders): an upgraded train door won "more real, built and used" 4 of 4 but "ship in a warm,
  miniature-look game" only 8 of 12, falling as hardware and dirt were added; an upgraded platform lamp won "real" 4 of
  4 and LOST "ship" 1 to 3 ("clean silhouette, calm smooth housing, fewer visible parts"). Until the project says which
  question decides (the default is "ship"): add what explains the object (how it opens, mounts, seals, lights) and
  rounds its edges; keep big surfaces calm; do not add rows of slots, fasteners or streaks for their own sake; wear at
  half of what looks right up close. Ask both questions and report both.
- **Measure, do not eyeball, at every round** (about 35 s; a 650 px tile and a vision reviewer both miss these):
  `python3 scripts/look/look.py <file.blend|.glb> --out DIR [--reference PIC --reference-view side|34]` prints one
  `LOOK <measure> <value> (band ...) <where>` line per measure outside its band, then `RESULT LOOK n` or `RESULT OK`
  (`render.py round` runs it and puts the lines in the sheet header). Bands for the game camera, family train:
  razor_share <= 0.02 of corner length, facet_share <= 0.02, flat_shaded_area <= 0.05, body_bevel_mm >= 7.6 (1.5 px at
  7.5 m), base_colour_spread >= 0.2, dark_in_cavities and dark_low_down >= 0.2, largest_material_variation >= 0.12,
  rest_cells 0.2-0.35, busy_cells <= 0.55, hull_features_side >= 3 (>= 2 at the 92 m size), proportion_error_pct
  within 2 with a reference. ADVISORY: the bands rest on 2 train cars and 7 CC0 references; a line is a reason to
  look at the place named and to fix it or say in the hand-back why it stays. How each is computed and the usual
  fixes: `references/LOOK-TOOLS.md`.

## How a game asset is judged: in the game's renderer

Measured on one train car (a near version with live shader slots) in a headless copy of a game's renderer: 27 single
changes, 298 blind vision-model pairs asked in both orders. What won: lit windows at night
(unlit lost every pair, 0-10 and 0-12), see-through glass with a cabin behind it (flat dark panes lost 0-19-9), a warm
half-saturated sky as the reflection (the game's job), smooth slot borders, calmer streaks. Not concluded: rivets,
seams, panel jitter, baked AO, wear amount (their test versions were stand-ins). One car, not the game itself.

In the game's renderer, not in Cycles: 7.5 m, 33 m and 92 m, day and night, next to the control.
1. Windows are see-through and there is a cabin behind them (floor, far wall, seat backs, ceiling). Cabin slots are never shared with outside parts.
2. Every version has lit windows at night, mid and far too. Check the night picture of each version.
3. A lit pane shows a room, not one flat colour.
4. Mirror metal (metallic 1, roughness under about 0.15) will show the ground and sky. Choose it on purpose, and judge metal under the sky reflection, not the studio one.
5. Keep streaks and blotches quiet: start `metal.brushed` at `streak` 0.3.
6. Round frame and door edges 30 mm in the near normal map (2.5 px at 7.5 m, 2 px at 33 m; 15 mm vanishes at 33 m). Measure it; a vision model cannot see it.
7. Do not spend time on rivet rows or extra seams for game versions yet (0.3 % of pixels at 7.5 m, nothing beyond).
8. Per-panel value changes follow the real panel seams or are left out.
9. Asking a vision reviewer: "more real" and "ship in a warm miniature-look game" disagree on wear, streaks and
   reflections (the dirtier picture is "more real", the calmer one is the one to ship). Say which you ask. Always both
   orders: the reviewer picked the first picture 478 times against 248.

## Making the lower versions

- **How much to remove is set by what a player could see, not by a triangle count.**
  Each version may change the picture by about 2 px at the distance where it appears (game camera fov 40, 1080p:
  1 px = distance x 0.000674 m). The distances come from ONE file, `~/.claude/skills/3d-asset-making/scripts/switch.json`
  (read from the game's code; in the example `train` family: near seen from 7.5 m, mid from 92 m, far from 292 m, so
  about 1 cm, 12 cm and 39 cm; the `city-kit` family: 1.0 / 2.4 / 8.6 cm); never take them from memory or from another document. That
  covers shape AND colour: simplify with UVs, normals and colours weighed, material borders and texture seams locked;
  removed bumps live on in a normal map; colour detail under 2 px may go. Judge by rendering the original and the
  version at the switch distance, by day, dusk and night (`render.py lodcmp`), lock where a region fails and redo.
  The triangle/draw budget is a ceiling: over it, report where and why, never cut deeper silently.

- **Each version is derived from the one above and is a whole object by itself.** Original, then near, then mid,
  then far. Not "the same file with things switched off".
- **A model that comes out of a program gets its lower versions from the same program:** the same construction with
  fewer stations and with parts merged into one shell (a row of seats becomes one stepped solid, sixty panels one
  ring). That is a derivation too, and it cannot crack the way a reduced mesh does. Reducing the finished mesh is
  the fallback for what was sculpted or imported.
- **Remove by merging, never by deleting alone.** When a part goes, in the same step make what it joined meet:
  stretch the neighbour into the gap, or fuse the neighbours into one shell. Dropping a collar means the lens now
  sits on the riser. Dropping the bolts means the plate is one piece with the base. Dropping a cable means dropping
  all of it, not leaving half.
- **Two solids built side by side become one by dropping BOTH faces where they coincide.** Those faces lie inside
  the union and are never seen; without them the two shells share their border edges and are one piece. Exact, and
  cheaper than a boolean.
- **Reduce joined parts together.** Join them (or lock the shared border) before decimating, so that both sides
  keep the same edge. Check the borders after: this is where cracks come from.
- **Never hand over the output of an automatic reduction unseen.** After any decimate, remesh, weld, limited
  dissolve or bake-to-low step: run the check and look (next section) before anything else is built on it.
- **A far version of a small thing is one fused shell.** A handful of closed convex forms that enter each other,
  or a single hull, with the colours carried by vertex colour or a tiny texture. If it has more than one body,
  something is floating. Example (a mast's far version made by a cheap model, never checked): the red section and the
  hex cap were separate boxes stacked 9 mm apart (2 floating bodies) and the red box had lost three of its sides (12 %
  open edge length: from below it is a half shell). Stacked parts ENTER each other by a few mm; a box keeps all its
  faces unless nothing can ever see that side (the viewer and the game orbit, so "behind" and "underneath" are seen).
- **Keep the silhouette's supports.** What disappears first in a reduction is what is thin: legs, posts, struts,
  ties, rails. Without them the top floats. Thin supports are kept thicker or merged into a card or a solid web,
  not dropped.

## Look twice

Once as the game shows it. Once as a person with a viewer shows it: alone and large.

1. **The check, on every version** (`scripts/mesh_integrity.py`, Python 3 with numpy, any `.glb`):

   ```
   python3 ~/.claude/skills/3d-modelling/scripts/mesh_integrity.py thing.near.glb --seen-to near --family train
   python3 ~/.claude/skills/3d-modelling/scripts/mesh_integrity.py thing.mid.glb --against thing.near.glb
   python3 ~/.claude/skills/3d-modelling/scripts/mesh_integrity.py thing.far.glb --against thing.near.glb
   ```

   It welds the corners, finds the connected pieces, then which pieces touch (surfaces within 0.1 % of the
   diagonal, at least 2 mm and at most 2 cm, measured exactly; `--attach METERS` to change). Pieces that touch form a body. **One body is the pass.** Each further
   body is printed as FLOATING with its size, its place and its gap. With `--against` it spreads points over both
   surfaces by area and measures each exactly against the other: what here stands where the reference has nothing
   (moved or added); how much of the reference's surface has nothing near it here (LOST); how much of that loss can
   be SEEN FROM OUTSIDE, from the sides and from above (`--from-below` adds the views from underneath, for what
   hangs or flies); where the five largest lost regions are; and how much open edge length is new. A floating body
   is a FAULT. What the comparison finds (more than 15 % of the seen surface with nothing near it, or a part
   standing where the reference has nothing) is printed as LOOK: a pointer, not a verdict. Checked blind by eye on
   thirty pairs: when the line is absent the version had lost nothing that shows (17 of 17); when it is present it
   was a real fault about half the time (a dropped part, an opening filled solid, a crumpled surface) and otherwise
   a coarser but acceptable shape (a twelve-sided drum made seven-sided, fewer leaf clumps, six of seven wires
   dropped). No tolerance separates the two; your eye does: open both files large at the regions listed and say
   which it is. A lower version may leave out what nobody can see (floors behind a wall, undersides on the ground).
   Exit 1 on a FAULT or a LOOK. On up to 8 cores (`--workers N`; the result does not depend on it): a few seconds
   for one car, about half a minute for a 371,000-triangle train car assembly (5.5 min on one core).
   It also sorts the open edges (on the ground: the rim of what stands on something; resting on another surface:
   a sheet that ends on a wall, closed to the eye; free) and says how much of what a viewer sees from the sides and
   from above is the BACK of a face (LOOKED INTO). A closed solid shows none; thin parts and cards give a few
   percent by nature. Above 5 % it prints the places: a back means the viewer looks into something: through a
   missing wall or an open top, at a skeleton without its skin, at a sheet from behind. A pointer, not a verdict
   (by eye on 27 models: under 5 % none was looked into, 5 to 20 % two of eight, above 20 % three of four). In the hand-back, say for the free open edges and for every place of backs what they are and why
   they are allowed.
   `--against` between two rounds of ONE version finds small moves too: a ground or backdrop in
   the file (a flat sheet, or named ground/floor/backdrop/sky/plane, without which the rest is at most a third of
   the diagonal) is left out and named in a "left out" line, so tolerance and point spacing follow the model
   (`--backdrop none` or `--backdrop NAMES` to change); and PART BY PART every node is measured with its own points
   and listed when more than 0.1 mm off, farthest first, with the place and, for a part with the same corners in
   both files, the exact shift ("moved as one piece by 1.000 mm along ..."). A list to read, not a verdict: against
   a lower version nearly every part is on it. `--moved-places N` prints more; `against.moved_places` in the JSON.
   FLICKER's back-to-back pairs now have places (`flicker.back_to_back_places` in the JSON, `--back-to-back-places
   N` to print): most are two solids resting exactly on each other; two faces of ONE part back to back within
   0.1 mm are printed always as "flipped copy": a duplicated, turned-over face that the duplicate count cannot see
   when it has its own corners or the other diagonal. Delete the copy, or say which two solids of one mesh meet
   there. `render.py inspect --from` reads all three lists.
   A LOWER VERSION is checked against the film original as well:
   `python3 ~/.claude/skills/3d-modelling/scripts/mesh_integrity.py thing.near.glb --against thing.original.glb --held-by thing.original.glb`
   Dropping the faces no outside view reaches leaves parts whose seen shell met the rest only through unseen faces:
   BODIES counts them as FLOATING although they sit where they sat. With --held-by each one is judged as a viewer
   would: HELD (it lies on the original, and what joins it there is still here or was never seen from outside: no
   fault), INHERITED (it floats in the original too: fix the original), MOVED (it lies farther than --held-tol from
   the original, or the original does not have it: FAULT) or NOT HELD (what joined it is gone and shows air: FAULT).
   --held-tol defaults to the touch distance; give the version's error target only when the version really moved
   (a mid at 12 cm), never a far's 39 cm: air up to about twice the tolerance passes. Glass counts as a wall, and
   the 72 view directions stand 8 degrees apart. A MOVED piece 14 cm and more off usually means the original GLB
   lacks something the work file has: look at a cross-section before blaming the simplifier.
   NON-MANIFOLD and WATERTIGHT: per body, closed or open and the volume of its closed parts. A closed
   part with a negative volume is INSIDE OUT (all faces point in; the engine draws its inside): FAULT, turn its
   faces. A face turned over against its neighbours (they wind opposite ways and meet at 75 degrees or more) is a
   LOOK, since two separate sheets can meet like that: recalculate the normals outside, or say why it is so. Sheets
   folded back at under 75 degrees (a lip, a one-sheet fin), edges of three or more faces, zero-area and duplicate
   faces are counted only. A mirrored node (negative scale) has its faces turned the way the engine draws them,
   as glTF requires, so a mirrored copy is neither inside out nor counted differently from its baked twin.
   Fix until one body, or until every remaining body is on the declared list.
2. **Every version alone, filling the frame, turned.** At least four sides and one from above, on a plain ground,
   by day. Not beside the building it belongs to, not at its game distance. Look for: air between two parts; a
   part that ends in nothing; a part hanging beside its neighbour; light or background showing through a body; a
   face missing; an edge that splits when the view turns.
3. **The versions in a row, same camera, same large size.** Original, near, mid, far side by side from two
   directions. What was there on the left and is gone on the right: say for each how its gap was closed.
4. **Then at the game's distances**, as the project's own rule asks. That view answers "does it read as the same
   thing from afar"; it cannot answer "is it sound".
5. **Write it down per version**, in the hand-back: bodies (1, or the declared ones), the check's last line, parts
   removed against the version above and how each gap was closed, new open edges and why they are allowed.

If the tool and your eye disagree, believe neither yet: a body the tool calls floating may be a wire you declared;
a model the tool passes may have a part that touches but is turned the wrong way or stands in the wrong place.

**And a third look, where the application switches versions.** A lower version can be whole and still be a different
thing: a roof that became a plain disc because its ridge lines were dropped, galleries much darker than in the
version above, trees of another shape, a part that glows at night because it was put into a material that glows.
None of these is a detached part and no large look at one version alone shows them. So, before hand-back:

- **Find out when each version is really shown.** Run the application's own switch rule for THIS asset's size and
  quality settings (written in `switch.json`, above); do not take the distances from memory. A rule that measures from the object's centre shows the
  far version of a 300 m building from 140 m off its wall: then the "far" version must stand a near look, or the
  rule must change (say which, and to whom).
- **Put both sides of every switch side by side at that distance,** same camera, same light, day and night, in the
  application's own renderer as well as in the modelling tool's, with the version above as the yardstick. What
  changes when the eye goes from one tile to the next is what a player sees pop.

## What the check cannot see

A part that touches but is wrong (rotated, mirrored, the wrong size); a seam tighter than the weld that still
leaks light at a grazing angle; a texture or vertex colour that broke; a part correctly attached to a host that is not in the file (give the host, or
declare it); what a material slot DOES (a slot may glow at night, get wet in rain or sway in wind: a part put into it for its colour inherits that); a skinned model as the game poses it (the check measures the rest shape, and says so; a skinned version
against an unskinned one cannot be compared by it at all). It is the first look, not the last.

## For whoever reviews

Give the reviewer the large views of every version, the row of versions, and the check's output. A reviewer fails
any detached or floating part and any unexpected hole **whatever the game's distance**, names the part and the
view, and does not accept "not visible in play" as an answer: a far version is opened in viewers, zoomed in
screenshots and reused closer than planned.

Millimeter-scale geometry is decided by the checks and by close-ups with measured stand-offs
(`3d-asset-making/scripts/render.py inspect`, 1 mm/px), never by a vision reviewer: in a seeded test (8
faults of 1-10 mm) the reviewer caught 0 of 8 on the round sheet. A vision reviewer is asked about the look:

### Look questions (vision reviewer; tested in 29 calls)

Give three pictures at most 960x720: three-quarter view, side view, one enlarged crop of a doorway. Answers are
exactly yes / no / unclear plus at most 8 words on where. Ask each set twice in separate calls; count an answer
only when both agree.

1. Does the whole model look brand new, with no sign at all of use or weather?              (want: no)
2. Is there darker grime gathered in seams, joints and inner corners where parts meet?       (want: yes)
3. Are the body sides divided by visible panel seams or joints?                              (want: yes)
4. Do the window panes show an interior or reflections, rather than flat black or grey?      (want: yes)
5. Are there at least three clearly different materials, in both colour and shininess?       (want: yes)
6. Do handles, steps and doors look sized for an adult person (a door about 2 m high)?        (want: yes)
7. On the crop alone: Can you see individual fixings (rivets, bolts or screws) in this crop? (want: yes)
8. Does any lettering or logo touch, cross or run past the edge of the plate or panel it is on? (want: no; added
   after a works plate whose text ran over its rim, not yet tested on seeded faults; give a crop of each plate or
   sign)

Between rounds, as a pair, in TWO calls with the order swapped (previous round = A then B; then B then A), same
cameras, three-quarter view and crop of each; answers A / B / same / unclear; count only when both orders agree:

8. Which looks more like a real, built and used object and less like a clean computer model?
9. Which would you ship in a warm, miniature-look game (real proportions, slightly soft edges, matte materials)?

Do NOT ask a vision reviewer about edge highlights or sharp edges, whether detail is evenly spread, whether anything
breaks the outline, whether repeated elements are identical, or large areas without break-up: the answers did not
change with the model (edge questions: yes 12 of 12 whatever the bevel, and the wrong model chosen in both A/B
orders). Those are measured (`mesh_look.py`, `look_metrics.py`) and the numbers go to the reviewer as facts.

## Tools in this skill
`M=~/.claude/skills/3d-modelling/scripts`. Every heavy run in a memory scope (`systemd-run --user --scope -p
MemoryMax=12G -p MemorySwapMax=0 nice -n 10 <cmd>`, Blender `-t 8`, `OPENBLAS_NUM_THREADS=1`).
- `$M/kit3d/` — the part-building library (Blender 5.2): placement by relation + `kit3d.check` (BVH-measured entries,
  gaps, z-fight, back-to-back, UVs; about 0.2 ms per relation). The one `parts.json` definition:
  `$M/kit3d/PARTS-SCHEMA.md`. Examples: `$M/kit3d/examples/` (14 parts, `run_all.py`).
- `$M/plan_check.py <run>/parts.json [--done]` — validates the plan (dims, host or free, material sources, night
  state, LOD fates, tool-only flags with evidence).
- `$M/mesh_integrity.py` — the check of "Look twice".
- `$M/look/look.py` — the look measures (advisory LOOK lines); `references/LOOK-TOOLS.md`.
- `references/PITFALLS-blender-5.2.md` — Blender 5.2 errors and their causes: look an error up, never delete the line.
- Steps in a live Blender, close-ups, renders, reviews: skill `3d-asset-making` (`bridge.py step`, `render.py`).
