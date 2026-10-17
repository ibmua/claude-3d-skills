---
name: 3d-asset-making
description: "Read before making, rebuilding, upgrading or briefing a worker to make ANY 3D asset (Blender, film original, game LODs). The whole job end to end: search your libraries and reuse parts first, make generic shared parts, design for the looks its story needs (day, night, rain…), film original then game versions, and on autopilot record who made it (model + effort) and its API cost in the asset's own record so its card on the asset dashboard (127.0.0.1:8152) shows them, plus a viewer that is not white."
---

# Making a 3D asset, end to end

This file is the order of work, every rule once, what "done" means and a one-line index of the tools. Read it whole.
- Full tool usage, numbers and known limits: `references/TOOLS.md` (read the part you need).
- What a builder of one part needs: `references/BUILDER.md` (give it to builders instead of this file).
- Geometry soundness, placing parts, making it look made by a master, lower versions: skill `3d-modelling`.
- The asset dashboard (catalog, renders, three.js viewer, runs view): `dashboard/README.md`.

An asset is **delivered** only when all of "Done means" holds. Nothing in it is optional and nothing in it waits for
a person to notice.

## Order of work

In short: list every visible part and its looks, search for them cheaply with pictures, decide what to import, then
build with a few parallel builders, assemble, and iterate in measured rounds. Generated images for textures, shaders
used heavily.

1. **Read how the application consumes this kind of asset** (its loader code or contract page): root and node names,
   material names it recolors or swaps for its own shaders, userData, variants, hooks, when each version is shown.
   If the project has no contract page for the kind, write one from the code.
2. **Decide what this subject needs, from its subject and story**: which looks (day, dawn, dusk, night, rain) the
   story ever shows it in, and which versions (near, mid, far) the camera ever needs. A daytime-only prop gets no night
   look; a thing seen only up close gets no far version; a backdrop seen only far gets no near one. Write it as
   `"needs"` in `parts.json` with a `why`; every later step, render and check covers exactly those (`plan_check.py`
   follows it).
   **Parts and looks.** List every visible part and how each looks in each needed look: what is lit, what glows,
   what reflects. `BREAKDOWN.md`. Also **where it is seen from**: the distances and pixel heights at which players see
   it (the closest, the ordinary, the farthest), and its **far read** for the concept (rule "Reads as itself from
   where it is seen" below).
3. **Cheap search, with pictures** (`search.py`; a cheap model such as Haiku): your libraries first, then free
   sources online (Poly Haven CC0 first). Every candidate comes back as a **look, not just a name**: a preview picture,
   source, license, format, triangles, materials, on `search/SHEET.jpg`. The searcher only finds and shows; it never
   imports.
4. **Will it work for us?** Look at the sheet enlarged: style against the concept, scale, detail at your camera
   distances, triangle budget, materials that survive your pipeline, license. Mark each part *import*, *import +
   adapt* or *build*, with the reason. Import = download unchanged to `<out>/sources/<name>/`, record it
   (`asset_record.py --source`), derive your versions from it.
5. **Plan in numbers.** `parts.json` (schema `3d-modelling/scripts/kit3d/PARTS-SCHEMA.md`): each part's size, host or
   `free(reason)`, material class and source, night state, fate in each lower version; plus the three composition
   lists (dense clusters, rest areas, splits: `3d-modelling` "Make it look made by a master"). `plan_check.py` must
   pass. Only tools flip the flags in it.
   *(Steps 1-5 are the planning launch, steps 6-10 the modelling launch; see "Launching a modelling worker".)*
6. **Build for as long as necessary.** The asset's maker is a separate top-level worker (`claude -p`, not a subagent:
   a subagent cannot start subagents). It launches up to **5 builders, at most 2 at once** (the machine is shared),
   each owning a set of components, its own Blender bridge port and its own `components/<name>/` folders; a builder
   never touches another's, and never drives the planner's Blender. Parts are built with **kit3d** (placed by
   relation, passed by measurement), one `bridge.py step` at a time. The planner builds the host (shell, slab) first
   and gives every builder its file and the anchor names made with `k.anchor()`; a component that sits on it is built
   with the host linked in (`"host_external": true`). At assembly the planner attaches each component with
   `k.attach(..., at='anchor.<name>')` in ONE scene and runs `kit3d.check` there; `mount.*` empties are only for
   contents that are separate assets. Components are movie-grade alone (sheet, at least 2 fix rounds) before assembly.
7. **Surfaces**: shader kinds from your shared library first, then layered node materials, plus generated texture
   images for what nodes cannot paint (rules below).
8. **Assemble and iterate in rounds** (procedure below) in each needed look until the review gate holds.
9. **Game versions** (only the needed ones: `lods_all.py --lows near=GAME_near`, renders `--states day`, per `needs`)
   in one background job (`lods_all.py`), each judged by its error in pixels at its switch distance.
10. **Record, card, thumbnail, hand-back** ("Done means").

### A round (measure first, vision model second, keep the best)
In a seeded test a vision model caught 0 of 8 faults of 1-10 mm on the round sheet. Millimetre-scale geometry is
decided by numbers, never by a vision model.
1. **Checks:** `render.py round` (mesh_integrity gate, UV check, pbr_check header, advisory LOOK lines) and the kit3d
   checks. They own floating parts, slits, blinking, back-to-back faces, UVs and material classes. From round 2 on,
   before any vision call.
2. **Close-ups:** `render.py inspect <work.blend> --round --out <run>/inspect/r<n>` renders every joint of the parts
   changed since the last saved round, plus every flagged place. Read the measured stand-offs in `inspect.json` first.
3. **Your own eyes:** the round sheet as the overview, then each finding ENLARGED on its tile or close-up. Write the
   five weakest things as things seen; fix them in the components.
   **Walk this list on every enlarged picture:**
   - **Lettering and logos:** every letter inside its plate, panel or border with a margin (nothing running into or
     over a rim, frame, edge or seam); not clipped, cramped or overlapping; following its curve; centered as
     designed; not mirrored (check the back of two-faced things); spelled as the design says; and readable, or
     deliberately not, at the game's size. Fix by fitting the text to the field (size, tracking, a second line, a
     larger plate), never by letting it overflow.
   - **Parts meeting:** nothing floating, sunk into or poking through another part; no gaps where parts should touch;
     handles, steps and fixings sitting on their surface.
   - **Surfaces:** no stretched or smeared texture, no seam where a texture wraps, decals lying flat on curved faces,
     no magenta (a missing texture), no speckle or blinking.
   - **Proportion and scale:** doors, steps and handles fit a person; repeated parts evenly spaced; symmetric where
     designed; edges with a visible bevel, not razor-sharp.
   - **Light:** glass shows something (interior or reflection), metals read as metal, emissive parts lit, and the
     day/dusk/night versions agree.
   - **Far read:** in place, from the game camera at the ordinary and farthest distance (`shaderlab` `game` view or
     the project's in-place scene), by day and night, beside a person for scale: does it read as what it is, and not
     as a generic box, tile or pole? Ask the vision model neutrally "what is this object?" on the far crop; a wrong or
     vague answer is a finding for the shape or value blocks, not for detail.
4. **Questions (advisory):** `luna_review.py --make-questions inspect.json --out q.json`, then `--questions q.json
   --repeat 2 --no-level`. A fault counts only when both runs say so; then look at that close-up and the numbers and
   fix it or name it as designed. Add the look questions (`3d-modelling`, "For whoever reviews").
5. **The vision model is asked only neutral questions** about what a picture shows, which of two pictures is closer
   to the concept, and where a named problem shows more. It never sees measurements, what we changed, which picture is
   newer or what we hope. Pictures at most 720p, a fresh session per call, pairs asked twice with the order swapped
   (disagreement = tie).
6. **Versus and fixes:** `--versus rounds/ROUND-<best>.jpg --concept <concept>`; last round's five weakest as
   `--fixes fixes.json --before <last picture>`. For close-ups, render the same cameras with `inspect --from <last
   inspect.json>`.
7. **Keep the best:** `rounds.py save <asset> <n> work.blend`, then `rounds.py decide <asset> <n> --gate <round log>
   --luna <out-dir>`. A round is KEEP only when its checks pass and it wins, or ties with every named fix applied.
   Otherwise `rounds.py revert` and try a different fix. Stop after 4 rounds per stage unless `--finding` names what
   the next round fixes. The LEVEL review (`luna_review.py`, 7+ twice with clean checks) is the stop.

## Rules

### Library first, for the thing and for each of its parts
- **One index of everything you have:** the asset dashboard http://127.0.0.1:8152/ (`dashboard/`, sources in
  `config/sources.json`). Every asset folder of every project gets an entry there. Search it by name before
  modelling, then each project's own library and reuse notes, then the internet for a free model that fits (Poly
  Haven CC0 first; a short cheap-model search), only then build.
- **Per part**, the breakdown says which library asset it borrows (path) or what was searched and why nothing fits. A
  borrowed part is adapted by its parameters or a small adapter, never copied into the host and edited; an
  improvement goes into the shared part.
- **Make often-used parts generic** (seats, benches, wheels and tyres, bogies, books, windows and frames, doors,
  lamps, railings, handrails, signs): one shared, parameterized asset each, with its parameters, mount points and
  states in its record. A missing one is made generic from the start, not shaped to its first host.

### Design
- **Reads as itself from where it is seen.** In one blind comparison two designs of a small kiosk tied up close; at
  18 m in place the one with a light body, a dark screen and a lit ring won both orders, the other read as "a dark
  tile on a thin pole". Unless the asset is only ever seen up close, the spec and concept art design the **far read**
  as well as the close look: from the game camera at the ordinary and the farthest distance (often 15-80 px tall),
  what does it read as? Decide it at concept time, when it is cheap: (a) a **silhouette** that names the thing (hood,
  pocket, ring, handle, not a plain slab); (b) **2-3 large value blocks** with clear contrast against its usual
  background (light body + dark insets, or the reverse), small details never carrying the identity; (c) the
  **identifying feature** (screen, lamp, sign) big enough to survive at that size, by day and as night glow. The
  concept sheet carries a small far thumbnail (and its squint/blur) next to the close view; a concept whose far
  thumbnail does not name the thing is redesigned before modelling. Checked again on the built asset in the round
  (step 3, "Far read") and by the game versions at their switch distances.
- **Film original first**, in Blender through the bridge, kept whole; game versions (near/mid/far) are made from it by
  merging and baking, never by deleting parts. Hosts (cars, platforms, rooms) export `mount.<kind>.<n>` empties for
  their contents; contents are separate assets.
- **Every look it needs** (`needs.looks`): design and render at day, dawn, dusk and night; night lights (lamps, lit
  windows and cabins, signs) as emissive masks in mixed warm/cool colors; where it stands in the weather, wet too
  (darker glossier surfaces, streaks, beads on glass, puddle/flow masks). States on one form, never separate models.
- **Light can be part of the asset.** Anything that lights itself or its surroundings carries its light as part of
  the design: (a) emitting surfaces as emissive masks with color and intensity per state (on, off, dimmed); (b) light
  sources as data on named empties `light.<kind>.<n>` (position, direction, color, intensity, range, cone, which state
  turns it on) in `asset.json` `"lights"`, so the game decides per its budget whether a source becomes a real light, a
  fake pool or nothing; (c) where the light falls on the asset or the ground near it: baked or masked light maps per
  state; (d) shared fixtures are one shared part. The film original lights itself with real Blender lights from those
  empties, so its night renders show what the game aims for. **Night glow is authored as emissive in EVERY version,
  near to far**; `light.*` empties alone do not count.
- **Effects belong to the asset too**: steam, exhaust, sparks, rain splashes and drips, dust, glow; declared like its
  lights as empties `fx.<kind>.<n>` with custom properties, drawn in the game as one GPU-animated instanced draw per
  kind. In the film original the same empties drive real effects.
- **Built to open**: a host the player looks into (a train car, a room, a station) keeps its roof and each wall as
  separate named parts (`cut.roof`, `cut.wall.left`, `cut.wall.right`, …) with a pivot or lowering path and
  closed/lowered states; the inside is finished for what the opened view shows.
- **How people and things use it**: colliders and a ground footprint; `sit.<n>`, `stand.<n>`, `grab.<n>`,
  `enter.<n>` points and clear paths; `mount.<kind>.<n>` for contents. **Moving parts**: named pivots and limits
  (doors, wipers, pantograph, bogie yaw, gates); open/shut as whole states of one form.
- **Made to be repeated**: generic parts share materials and a texture atlas so hundreds of copies instance in one
  draw; the per-copy look (color, wear, number) is data on the copy (palette masks).
- **Scale, origin, axes**: true meters, origin where it stands or mounts, +Y up on export, facing named; checked by
  the project's own asset check before the first export.

### Materials and surfaces
- **Every material declares what it IS before it gets numbers** ("looks white, but has some steel" is a question for
  the design, not a value to guess): a class in `asset.json` `"materials"` (or a live shader kind, or kit3d `ref=`).
  Take it from the design (era table, brief, references); when they disagree, ask.
  - `bare_metal` = metallic 1 with the measured reflection color (`matref.py stainless|alu|brass`), often anisotropic
    when brushed; never 0.3-0.9.
  - `metallic_paint` keeps an in-between metallic ONLY under a clear coat >= 0.5; else it reads as white plastic
    (Cycles' sky reflections can hide this; the game view does not).
  - paint, plastic, rubber, wood, fabric, dirt, wear = metallic 0; dark rubber Y >= .02, no albedo above Y .9.
  - Opaque surfaces are single-sided; only declared `"sheet": true` materials may be doubleSided.
  - Normal maps: PNG, blue > 0.5, unit length, mesh exported with TANGENT.
  - Game versions carry baked ambient occlusion when the game has no SSAO: `bake.py` bakes color, rough, metal,
    normal, emit and **ao** by default, ao from the HIGH original into R of the ORM image, which `export_game.py` writes
    as `occlusionTexture` (three.js `aoMap`). Never multiply AO into the base colour (that darkens the sun too). Detail
    and numbers: `references/TOOLS.md` step 2.
  - `pbr_check.py` runs before bake and on every exported version; FAIL refuses the file.
- **Animated or glowing surfaces** (screens, signs, lamps, water, glowing glass) and any surface whose look is a
  shader: design them in `DESIGN.md` first (where they're seen and at how many pixels, states, a storyboard as a loop,
  emission levels, glow without bloom), then prototype them in the Shader Lab (`shaderlab/README.md`: spec + GLSL,
  headless sheets, a game-size view and real-speed clips; the game ships the same `surface.js`).
- **Every number names its source**: "physicallybased.info", "measured: <how>", "judged: <why>", the project's spec,
  or `inferred` (a guess, a WARN to resolve). In `NOTES.md` and `asset.json`, for material values, budgets and
  distances alike. Typical bad values are unmarked guesses (a steel metallic of 0.55; a switch distance the game never
  uses).
- **Judge materials in the game's lighting and the dashboard viewer, not only in Cycles**; metal under a sky
  environment, never a studio box (a RoomEnvironment made a twin 10-17 % brighter).
- **No baking, except low-quality versions or a deliberate, written plan; the modeller owns this.** The maker, not a
  later reviewer, designs every surface as a material the viewer and game can draw live:
  - a library kind carries the STANDARD record `idle` = `{"kind": "<kind>@<ver>", "slot", "p"}`
    (`_kit.idle_record`). A private name the tools cannot read makes every tool see "unknown group" and bake the
    whole asset;
  - other surfaces are glTF-direct: a Principled fed by constants and UV image textures (an image times a constant is
    folded by the exporter); a look that needs more is a new library kind, not a one-off graph;
  - read the exporter's lines after EVERY export: `library-kind materials stay live` must list every kind, and
    `0 meshes have materials glTF cannot carry`. A bake is refused unless `--bake-ok "<reason>"` names the plan (far
    version, a deliberate atlas), and the reason goes into `asset.json` and NOTES.md;
  - look at the viewer card with the ✨ live switch on: worn paint shows its grime and its satin response, not a
    frozen picture.
- **Materials stay shaders through near and mid; only far may be fully baked.** Bake only what geometry knows (a
  tangent normal map + a mask: R AO, G edge, B feature, A slot id) and shade each slot live with a shared kind from
  the library. A kind is written ONCE in your shader library and emitted to both the Blender node group (named
  `idle.<kind>@<ver>`) and the game GLSL; a new material need is a new kind there, never a one-off graph. Name each
  material with the application's slot name. A pair check (Cycles against the game renderer) is the gate. How, with
  numbers: `references/TOOLS.md` "Shader kinds". This toolkit does not ship a shader library; without one, use
  glTF-direct materials.
- **Surfaces, not flat colors**: shader networks and image textures (paint over primer, wear, grime by height and
  cavity, roughness break-up, normal detail, decals). A face left one flat color is named and justified in `NOTES.md`.
- **Generated texture images** (for example gpt-image through Codex): ONE element per image, decals on real
  transparency and trimmed, tiles checked for seams, exact lettering drawn in code, every placement done by your own
  code.
- **Every textured part has real UVs; no two surfaces share texture space; a part's look survives export** (detail
  in `3d-modelling`).

### Game versions
- **A live part must look right where its program does not run** (a TV's glow card once showed in the viewer as a
  huge opaque slab, its screen as one flat colour). Bake each program's fallback with `shaderlab/lab.mjs fallback SPEC
  --out shaders/fallback --t <a telling moment>` and export with `export_game.py --live GLOBS --live-fallback
  shaders/fallback`: a screen carries a still of its picture as emission, a glow card a soft alpha falloff (glTF has
  no additive). Then look at the plain GLB (a lab spec with no programs) from the front AND from behind. Turn shadows
  off on blended cards in the game.
- **Near and mid are LIVE by default; the TOOL does it, not a recipe.** `lods_all.py` makes near and mid with
  `live_version.py`: every low face takes the original material it shows (rays back along the face normal), library
  kinds stay live shaders (`idle.<kind>` group, the version's own wear mask + normal map wired in), plain constants
  stay constants, printed images are projected onto the low's UVs, and only the tangent normal map + wear mask are
  baked; then `export_original.py` (no bake allowed), `mesh_integrity --against` and `pbr_check`. Far still bakes.
  Options: `--merge` (fold tiny slots per level), `--no-normal` (a part whose normals the low cannot follow). Baking
  near/mid needs `--baked-near-mid "<the plan>"`, said in the summary. `plan_check --done` refuses a baked near/mid
  anyway.
- **A library kind is recognised by its WIRING.** A material whose Surface comes straight from an
  `idle.<kind>@<ver>` group IS that kind; its unlinked group inputs are the params. The `idle` property is optional
  (designers who wired the groups right but wrote no record otherwise get every exporter baking them, alpha-blended
  and see-through in the viewer). Mirrored in `_kit.idle_record` and the dashboard's `export_blend.py`.
- **Only `export_game.py` writes into `export/`** (except the live near/mid above, written by `lods_all.py` via
  `export_original.py` with the same validator + reimport gates). A game GLB written with a raw
  `bpy.ops.export_scene.gltf` skips the geometry gate, and coplanar faces then blink in the viewer. The dashboard lists
  everything in `export/`, so a file there is seen as delivered. Drafts and experiments go to `work/`. A screen, decal
  or label laid on a body never shares its plane: recess it (the body's face is cut away under it) or make it the
  body's own face with its own material.
- **A version is judged by its ERROR IN PIXELS, not a triangle count**: at most 2 px at the closest distance the game
  shows it (fov 40, 1080 rows: 1 px = distance x 0.000674 m), shape AND color. Switch distances live in ONE file,
  `scripts/switch.json` (put your game's numbers there; the example family `train`: near from 7.5 m, mid from 92 m,
  far from 292 m = about 1 / 12 / 39 cm). The triangle budget is a CEILING: over it the run stops and says "needs N
  for 2 px, budget B, mostly in <parts>"; it never cuts deeper silently.
- **The game drives looks by material name** where a contract says so (class colors, glass shader, night glow, lamps,
  rain): near and mid keep one material per game role (a slot); the bake adds only what lives inside a slot; far may
  merge. A new slot name is a game change. One baked material per asset fits none of it.
- **The game versions look like the original**: checked in numbers and pictures by `render.py lodcmp` at the switch
  distances, day, dusk and night. All of it runs as ONE background job (`lods_all.py`); read its summary.
- **Every export is validated twice** before it replaces the previous file: the official glTF validator and a fresh
  reimport whose counts (meshes, triangles, materials, textures) match the scene.
- **A version that fails a check is not published.** The export tools write `.rejected.glb` instead; overrides
  (`--allow-*`, `--skip-*`) need a reason and are printed as OVERRIDE lines.

### Record who made it, what it cost and how long it took (autopilot, not memory)
- **The asset's own record** (`asset.json`): `made_with` is a LIST, one entry per model that worked on it: `model`
  (the exact id, e.g. `claude-opus-5-5`, never "opus": entries are keyed on it), `effort`, `label`, `task`,
  `session`, `start`, `end`, `active_minutes` (gaps over 10 min count as idle), `api_cost` {`usd`, `basis:
  "api_equivalent"`, `tokens`, `calls`, `via`}; `maker_label`, `maker_count`; top-level `api_cost` {`usd`} = the
  total, **empty when any maker is unpriced**, then `api_cost_known_part` {`usd`, `leaves_out`}; top-level `time`
  {first_start, last_end, active_minutes_total}. Prices come from a price table (the dashboard reads `PRICES_URL`).
  Never estimate cost or time.
- **Who writes it: whoever launched the maker.** A project task system may, but only for makers it can see. A
  subagent, a `claude -p` or a Codex run started by a lead is invisible to it: the lead runs a writer that prices the
  maker's transcript (→ `COST.md` per component AND each `asset.json`). Start it at launch, re-run it at every
  check-in and at hand-back; a limit-stopped worker's cost counts.
- Every session that worked counts: searchers and each builder are entries of their own (each model once with its
  summed cost; `COST.md` splits by session and component). A side file is detail only: a cost that is not in the
  asset's record is not recorded. Maker entry from the FIRST export; a later upgrader appends, never replaces.
- **Group sessions are findable**: every record made in one session or task names it the same way
  (`made_with[].task`, `generation.cost_group`), so the dashboard groups them and shows the group's cost and time.
- **Every external AI call is logged** with its usage, including failed and empty attempts (`luna_review.py` writes
  one usage record per call).
- **Where it came from**: every imported or borrowed part in `asset.json` `"sources"` (path or URL, license, author,
  what we changed), so the license travels with the asset.

### Report as you go, and make it visible
- **Every checkpoint and every save is reported**: one `report.py` line per event into the run folder's
  `progress.jsonl` (kinds `start plan search decision component assembly round review export thumbnail blocked
  done`); a silent hour is a fault. Shown with live API cost at http://127.0.0.1:8152/#/runs.
- **Save a thumbnail every time you save an asset, assembly or component**: `render.py thumb` right after the file is
  written → `renders/<key>.png` (+ `-dawn`, `-dusk`, `-night`, `-rain`), three-quarter view, lit like the game, not
  clay. Without it the dashboard shows a flat grey render. A component sheet is an extra, not the thumbnail.
- **The dashboard must scan its folder**: a nested run folder needs its own entry in `config/sources.json`, with
  `renders/{key}.png` first in `previews` and its record named (`madeWith`).
- **The 3D viewer needs materials**: a GLB exported with `export_materials='NONE'` shows white. Export the original
  GLB with its look (`export_original.py`), or give the dashboard source only the `.blend` so its exporter bakes.
- **The viewer GLB must look like the Cycles render**: open the card next to `renders/<key>.png` before calling it
  delivered. A known failure: empty atlas texels made opaque baked materials BLEND (three.js draws BLEND without depth
  writes, so a white shell painted over a reader pad) and a large glyph was baked at 32 px. Both are fixed in
  `export_original.py`; any `alphaMode BLEND` on a non-glass material (pbr_check G8) in a viewer GLB is this bug, so
  re-export with the current tool.
  **Re-export the viewer GLB after ANY change to its input** (original, bake twin, materials) and read the per-mesh
  `atlas coverage … -> OPAQUE/BLEND` lines: a stale viewer GLB shows faults that were fixed hours ago.
  Also look at the BACK in the viewer: an unused material slot named in the design (a material with 0 faces while
  another part carries the wrong one) is a mis-assigned part; check face counts per material against the parts list.
  **Library kinds are never baked for a viewer GLB either**: `export_original.py` and the dashboard's
  `export_blend.py` write the library contract (extras.idle + fallback factors + mask as occlusion;
  `_kit.kinds_to_contract`) and the dashboard viewer draws the kind's GLSL live with the library's three.js binder
  (✨/🖼 switch). Only OTHER node groups are lifted to a top-level Principled and baked (`_kit.lift_groups`;
  `channel()` alone reads a group as flat grey, `UNKNOWN …:GROUP`).
- **Seen where the player sees it**: pictures through the game's camera at its closest, its usual and the switch
  distances, day and night (`render.py versions`, `lodcmp --at-switch`; in the game's own three.js: `sweep.mjs`
  frames, or the Shader Lab). The film original is the target, the game view is the test: a change that helps in
  Cycles may be invisible there (`3d-modelling` "How a game asset is judged").
- **Notes for the next maker**: `NOTES.md` with what was borrowed, what was built and why, flat-color exceptions, open
  faults; the previous version kept read-only before a rebuild.

### Work economically
Measured on two builders: output tokens were 3-4 % of the cost; the money is context size times turns, and about 95 %
of wall time was the model idle while Blender ran. None of this is a reason to work smaller or rougher.
- **Never let your cache expire.** A subagent's prompt cache may live only 5 minutes (a top-level `claude -p` on a
  subscription: 1 hour, so the same rule at about 50 minutes). A longer tool call or wait rebuilds the whole context
  on the next turn: 7 such waits added 31-37 % to two builders' costs. Start anything over about 4 minutes in the
  background (`bridge.py detach`), wait in slices of at most 240 s (`bridge.py wait`) and build the next part
  meanwhile.
- **Look at pictures outside your context.** 58 and 83 images stayed in two builders' contexts (26 % of one's cost).
  Review a round as ONE sheet at most 1280 px wide plus named crops or close-ups where a finding needs them; pass
  sheets to `luna_review.py` or a throwaway vision call and read back text.
- **Start lean.** Docs read whole in the first turns are paid on every later turn. Read the brief's `DIGEST.md` and
  `PROGRESS.md`; open other docs only at the part you need. Each stage may be a fresh session resuming from
  `PROGRESS.md`.
- **Game versions in one background job** (that phase was 50-63 % of each builder's cost when driven by hand).
- **Stop at the gate.** After a level of 7+ twice with clean checks, another round needs a named finding to fix.

### Launching a modelling worker (lead)
- **Default: two phases, two launches.** Unless a run names other models/efforts:
  1. **Planning: `claude-opus-5-5` at effort `xhigh`**, steps 1-5 of "Order of work" (contract, `BREAKDOWN.md`,
     search sheet, import/build decisions, `parts.json` with `plan_check.py` passing). It writes `PROGRESS.md` and the
     modelling brief (components, builders, ports, commands) and stops; it builds no geometry.
  2. **Modelling: a fresh `claude-opus-5-5` worker at effort `low`**, steps 6-10, started from `parts.json` +
     `PROGRESS.md` (never by resuming the planner's thread). Its builders also run Opus at `low`.
  `claude -p --model claude-opus-5-5 --effort xhigh …` then `… --effort low …`. Both makers go in `made_with` with
  their own effort and `task` (`plan` / `model`). Compare a different arm only as a separate, labelled run.
- **Who may build geometry**: a cheap model (Haiku) searches and checks only; models, game versions and shaders are
  built by Opus or a model you choose on purpose. (A cheap-model far version shipped with 2 floating parts and a
  half-open box, never checked.)
- Brief as an expert with the whole job, the bar, the materials and pitfalls; judge by finished work, not thinking:
  "short reasoning, many actions; render, look enlarged, fix the five weakest, repeat". Measured: Opus at medium
  effort with that brief reached level 7/7 for $29 where a max-effort repair reached 6/5 for about $58; built from
  components: level 7 in 6 rounds for $33.
- Give it this skill by name, its bridge port, its run folder (`PROGRESS.md` first, one line per step), the output
  folder, the builder model and effort; builders get `references/BUILDER.md`. Keep a read-only copy of the previous
  version before a rebuild. The machine's shared-use rules (memory scope, never kill by name) go INTO the brief.
- The maker's transcript and its builders' (`<session>/subagents/*.jsonl`) are what the cost writer prices.

## When it looks wrong: symptom, cause, fix
| Symptom | Cause | Fix |
|---|---|---|
| Grain or speckle over a whole part, at every angle | a textured mesh without UVs, or a node graph glTF cannot hold exported raw (image as color, roughness AND normal) | unwrap every textured part; bake graphs (the exporter does, components included) |
| Metal reads as white plastic | inner and outer skins share texture space (a live Solidify copies UVs), so the bake writes the inner value over the outer; or a half-metal value with no clear coat | apply modifiers before unwrap/bake, unwrap apart; declare the class (`pbr_check.py` M1/M2) |
| Patches that blink as the view turns | two faces in one plane, or back-to-back faces with a double-sided material | lift or delete one, single-sided closed walls (`mesh_integrity` FLICKER, `sweep.mjs`) |
| A jagged dashed line along a panel joint, worse from far away | panels of one skin overlapping a few mm, inside the depth step at the version's farthest distance (or a viewer with a tiny near plane) | one skin = one surface, delete hidden faces (`mesh_integrity --seen-to near` AT DISTANCE; 3d-modelling "depth step") |
| A part hovers | stacked parts placed apart instead of entering each other | kit3d `attach` / `span` (enter about 5 mm; angled parts from their two end points, never a rotated primitive) |
| A thin line of light between parts | parts that should meet stop 1-10 mm short | close or name it as designed (`mesh_integrity` GAPS, `render.py inspect`) |
| A game version shows dark boxes or loses a feature | reduction cut a feature (roof windows) or the bake rays hit the wrong surface | error-bounded, color-aware reduction; `render.py lodcmp` at the switch distance, day/dusk/night |
| Night versions are dark | glow was only real lights in the original; nothing emissive in the version | author emissive in every version (`pbr_check.py` E1) |
| A decal or emblem turns into a flat block in a game version | it sat inside a recolored slot, which keeps only a grey multiplier | bake.py slot fit moves it to the `.baked` slot; or give it its own material |
| An export loses triangles or gets zero tangents | Blender's glTF exporter runs `mesh.validate()`, which deletes back-to-back duplicate faces | delete the hidden side in the original; `simplify.py` splits repeated triangles |
| Reads as "computer made" though every check passes | razor or sub-pixel edges, flat shading, even detail, one value over large areas, brand new | `3d-modelling` "Make it look made by a master"; `look.py` |
| Magenta textures after opening a copy | the .blend was opened through a symlink or moved, relative links broke | open via `realpath`; keep copies at the same folder depth |

## Done means

1. Library searched for the thing and each part; borrowed parts named with their source and license; generic parts
   made generic.
2. Plan in `parts.json`; `plan_check.py` passes with `relations` and `uv` true for every part (`--done` also wants
   `inspect` and `lod_kept`, which no tool writes with evidence yet: report them as not written); every part passes
   `kit3d.check` (or is declared `free` with a reason).
3. Film original whole; the needed versions (`needs.versions`) from it; each passes `mesh_integrity.py` and was looked
   at large; mounts listed.
4. Every needed look (`needs.looks`) rendered and reviewed; lights that belong to it are designed and declared
   (emissive per state in every version, `light.<kind>.<n>` data, light on itself); effects declared.
4b. **It reads as itself at play distance** (unless only ever seen up close): an in-place picture from the game camera
   at the ordinary and farthest distance, in its needed looks, is in the hand-back, with what it reads as.
5. Materials: every class declared, every number sourced, `pbr_check.py` PASS (warnings explained) on the original and
   every version.
6. The look was measured (`look.py`): the numbers are in the hand-back, every LOOK line fixed or explained.
7. **The game versions look like the original** (a near version once baked white, metallic 0.23 against the
   original's 0.55): `render.py lodcmp` exit 0 at the switch distances, and a `render.py versions` sheet.
8. **A version that fails the check is not published.** `mesh_integrity.py` RESULT FAULT on any version means fix it
   first; the export tools refuse to write it and the dashboard card shows the fault.
9. **No slits, no blinking, no speckle**: GAPS and FLICKER clean on every version, designed seams named; every textured
   mesh has a UV map (no textured primitive without `TEXCOORD_0`); `sweep.mjs` RESULT PASS in the game renderer.
10. The asset's record has `made_with` (model, effort, label, start, end, active minutes) and the API cost per maker
    and in total (or the known part with what it leaves out), and its sources.
10b. **Its web export carries real materials, or it is a movie asset.** `asset.json` `"purpose"`: `"game"` (default)
    or `"movie"` (films only; movie-GRADE game assets are still "game"). A game asset needs
    `original/export/<key>.glb` from `export_original.py`, newer than its `.blend`, not refused, with 0 baked meshes or
    a declared `--bake-ok` plan, plus its game versions. A movie asset needs neither and has no lower-poly versions.
    `plan_check.py --done` enforces it.
11. **Its card on http://127.0.0.1:8152/ shows the maker and the price, and the 3D viewer shows it in color.** Open it
    and look (or `curl -s 'http://127.0.0.1:8152/api/catalog' | jq '.items[] | select(.id|test("<key>")) | .made_with'`).
    From a machine where the dashboard cannot be reached, say "card not verified" and name the record's path.
12. Progress reported at every checkpoint and save; a lit thumbnail `renders/<key>.png` (and state variants) saved
    after every save.
13. Hand-back names the card link, costs, rounds, review levels, the check and look numbers and an honest list of
    what still looks weak.

## Tools (one line each; full usage in `references/TOOLS.md`, every script has `--help`)
`K=~/.claude/skills/3d-asset-making/scripts`, `M=~/.claude/skills/3d-modelling/scripts`. Use them; do not improvise.
Every heavy run goes in the memory scope (TOOLS.md "Conventions").
- `$K/render.py` — ALL renders: `thumb`, `sheet`, `round` (with the geometry gate), `inspect` (joint close-ups at
  1 mm/px), `lodcmp` (versions against the original), `versions`, `beforeafter`.
- `$K/bridge.py` — a Blender of your own: `claim` / `release`, `<port> script.py`, `step` (one kit3d part: run, check,
  save, thumb), `detach` / `wait` for long jobs.
- `$M/kit3d/` — the part-building library: place by relation (`attach`, `span`, `lay`, `scatter`, `into`),
  `check()`. `$M/plan_check.py` — validates `parts.json`. Examples `$M/kit3d/examples/`.
- `$M/mesh_integrity.py` — floating bodies, gaps, blinking, inside-out and turned faces, what a lower version lost.
- `$M/look/look.py` — advisory LOOK lines: edge sizes in pixels, flat shading, color spread, calm and busy areas,
  outline; `3d-modelling/references/LOOK-TOOLS.md`.
- `$K/pbr_check.py`, `$K/matref.py` — material correctness (PASS/WARN/FAIL) and measured reference values.
- `~/.claude/skills/3d-asset-making/shaderlab/lab.mjs` — Shader Lab: `render SPEC.json` (sheets, game-size view, clip;
  exit 2 on a GLSL error) and `serve SPEC.json` (live page with sliders). Method and spec: `shaderlab/README.md`.
- `$K/luna_review.py` — the LEVEL review, yes/no questions, versus, fixes (blind vision calls, usage logged).
  `$K/rounds.py` — save / decide / revert: keep the best round.
- `$K/search.py` — library and web search with a picture of every candidate.
- `$K/report.py` — progress events for the Runs view.
- `$K/live_version.py` — a near/mid version with live slots (called by `lods_all.py`; standalone: see its header).
- `$K/lods_all.py` — game versions end to end in one background job (`simplify.py`, `uvpack.py`, `live_version.py`
  for near/mid, `bake.py` for far, `export_game.py` with every gate, then lodcmp, sweep, thumbs, versions sheet,
  record). `$K/switch.json` — the one place for switch distances. `$K/export_original.py` — the film original with its
  look for the viewer.
- `$K/sweep.mjs` — blink and slit sweep in the game's own three.js renderer.
- `$K/asset_record.py` — the asset's record (makers, time, lods, switch distances, sources). `$K/glbstat.py` —
  triangles, draws, materials, textures, extents of a GLB.

## Project hooks (what your project supplies)
The toolkit runs on its own for modelling, checks, renders, game versions and the dashboard. A few parts call into a
project's own tools; point them at yours or leave those parts out:
- `bridge.py claim` starts a headless Blender with the Blender MCP add-on through `$ASSET_OPS/opus_dispatch.py`
  (`blender_bridge(task, folder)` → writes `blender-port` and `mcp.json`). Any launcher that serves the add-on's JSON
  socket on a 127.0.0.1 port works; `bridge.py <port> script.py`, `step`, `detach` and `wait` need only the port.
- `luna_review.py` calls a vision model through `judge.py` in `$ASSET_PROJECT/docs/concepts/tools` (`judge.room`,
  `judge.luna`) with the Codex logins in `$CODEX_HOMES` (colon-separated), and its LEVEL review through
  `$ASSET_OPS/luna_assets.py`. The questions, versus and fixes modes need only `judge.py`.
- A shader library (kinds as Blender node groups `idle.<kind>@<ver>` + GLSL twins, `game-slots.json`, a pair check):
  the dashboard has a stand-in under `dashboard/stubs/`.
- `switch.json` and your game's material contract: put your game's numbers and slot names there.
- Every project keeps a contract page per asset kind (how the game consumes it) and a rules page for asset runs; give
  both to every maker.
