# 3D asset tools: the full reference

`SKILL.md` has the order of work, the rules and a one-line index; this file has every tool's full usage, numbers and
known limits. Every script also has `--help`. Read only the part you need:
`grep -n '^## ' ~/.claude/skills/3d-asset-making/references/TOOLS.md`.

## Conventions
- `K=~/.claude/skills/3d-asset-making/scripts`, `M=~/.claude/skills/3d-modelling/scripts`, `B=blender` (Blender 5.2;
  `BLENDER=/path/to/blender` where the scripts look one up).
- Every heavy job runs in a memory-capped scope, niced, on at most 8 threads, one Blender job of yours at a time:
  `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=8 systemd-run --user --scope -p MemoryMax=12G -p MemorySwapMax=0 nice -n 10 <cmd>`
  with Blender `-t 8` (numpy inside Blender otherwise starts a thread per core). Measure a peak with `/usr/bin/time -f %M`
  before raising the ceiling; size a parallel pool to that peak and `free -g`, leaving plenty free. On a shared box,
  nine ~8 GB python processes once filled RAM and swap and the kernel killed a film render.
  `bridge.py detach` and `lods_all.py` apply the scope themselves.
- **Stop only your own jobs, by PID or by scope unit; never by name** (`pkill blender`, `killall`, `pkill -f render`):
  a shared box runs film renders and other agents' Blender bridges under the same user.
- `MV_BLENDER_GPU=1` is passed through for launchers that hide the GPU from Blender unless asked (then Cycles renders
  on <= 8 CPU threads). A shared GPU: light use only.
- Anything over about 4 minutes goes to the background (`bridge.py detach` + `bridge.py wait`, slices of 110 s, at most 230 s).

## Progress reporter: `report.py`
```
python3 $K/report.py <run folder> <kind> "<what happened, one sentence>" \
    [--asset <key>] [--picture <path>] [--stage A|B|C] [--round N] [--luna 7] [--builder <name>] [--data '{"tris": 7159}']
```

Kinds: `start`, `plan` (breakdown written), `search` (a part searched, with its sheet), `decision` (import / adapt /
build), `component` (a component saved: picture = its thumbnail), `assembly` (the whole saved), `round` (a review
round: picture = the round sheet, the five weakest in the message), `review` (vision level: `--luna`), `export` (a
game version: tris and draws in `--data`, integrity RESULT in the message), `thumbnail`, `blocked` (what stops you),
`done` (hand-back). Report at least every checkpoint and every save; a silent hour is a fault. The page that shows
it with live API cost is the dashboard's **Runs** view, http://127.0.0.1:8152/#/runs (reads every run folder listed
under `runs` in its config that has a `progress.jsonl`; cost from the run's transcripts, its builders' included).

## Rendering: `render.py` (all renders; never write your own render script)

- `MV_BLENDER_GPU=1 nice -n 10 blender -b --factory-startup -noaudio --python ~/.claude/skills/3d-asset-making/scripts/render.py -- <mode> …`
  (`python3 render.py --help` prints every option). Modes:
  - `thumb <file.blend|.glb> [--states day,dawn,dusk,night,rain]` (default: all five) → `renders/<stem>.png` (+ `-dawn`,
    `-dusk`, `-night`, `-rain`) beside the file: the dashboard thumbnail, three-quarter view, game-lit (sun + Sky
    Texture, Khronos PBR Neutral).
  - `sheet <component.blend>` → `SHEET.jpg` beside it (front34, rear34, side, top).
  - `round <assembly.blend> [--interior 2]` → `rounds/ROUND-<n>.jpg`: 6 day views, front34 + side at dusk/night/rain,
    interior views at day and night; tiles (960 px) kept in `rounds/ROUND-<n>/` for looking enlarged: the sheet is the
    overview, a finding is looked at on its tile or an `inspect` close-up. It first writes the rendered geometry
    (linked parts included) to a GLB and runs `mesh_integrity.py --from-below` on it in the background (up to 8 CPU
    cores; about half a minute on a 1,000-part train car) plus a UV check; BODIES/NON-MANIFOLD/WATERTIGHT/GAPS/
    FLICKER/RESULT go into the sheet header, and the default `--strict` exits 3 after writing the sheet on floating
    bodies, inside-out parts, FLICKER faults, GAPS or textured meshes without UVs (`--no-strict` reports only;
    `--no-integrity` skips).
  - `lodcmp --original X.blend --versions near.glb,mid.glb,far.glb [--states day,dusk,night] [--at-switch]` →
    `LODCMP.jpg` (+ `-dusk`, `-night`, `-switch`) + `lodcmp.json` beside the original: each version against the
    original from the same cameras and light state (the original's asset lights light every version), the asset
    filling the frame; per view mean dE, luminance, RGB delta, material colour and gloss (Cycles diffuse/glossy colour
    passes, day: catches a baked metallic/colour error that lighting hides) and boxed regions on a masked difference
    picture. `--at-switch` also judges each version at the distance the game shows it (game camera fov 40, 1080p;
    distances from `switch.json` by `--family`) in those true pixels. Night uses the same limits on purpose: lit
    windows are the strongest colour at distance, and versions without window glow fail. Every failing region in the
    JSON has its pixel box and its 3D place on the version (`place.gltf_xyz`, `box_gltf`, `object`) so the LOD tool can
    lock those vertices and simplify again. Exit 4 on mean dE > 10, luminance ±8 %, material colour ±10 %, gloss ±25 %
    or a region ≥ 1 % of the asset at dE > 25 (calibration in `--help`). 95-165 s for 3 versions × 3 states with
    `--at-switch` (50 views). `near.glb+bogies.glb` shows two files as one version.
  - `versions --files original.blend,near.glb,mid.glb,far.glb --dist 14,24,70` → LOD check at the game camera, true pixels.
  - `beforeafter --before X --after Y` → same camera side by side.
  Night lights come from the `light.<kind>.<n>` empties (custom properties or `asset.json` `"lights"`; with none,
  `mount.light.*` become cabin lights); rain is a wet pass on in-memory materials. The input is never saved.

### Close-ups of joints: `render.py inspect`

- `OPENBLAS_NUM_THREADS=1 blender -b --factory-startup -noaudio -t 8 --python $K/render.py -- inspect <file.blend>
  (--round [--since ROUND.blend] | --part NAMES | --relations [--parts A,B] | --from <integrity/check/inspect json> |
  --at x,y,z) [--mmpx 1] [--xray] [--isolate] [--state day|dusk|night] [--max-places 30] --out DIR` → one 1280x720 JPG
  per joint (3 tinted views, an edge-on seam view, an as-rendered tile) + inspect.json (mm/px, measured stand-offs,
  never on the pictures). `--from` an earlier inspect.json re-renders the SAME cameras (before/after). About 24
  places in 2 min, 1.8 GB.

## Blink and slit sweep in the game renderer: `sweep.mjs`

- Three.js of the game (set `THREE_DIR`, or `GAME_DIR` with `vendor/three`), its camera fov 40 / near 0.5 / far 6000,
  its lights and tone mapping, GPU: `node ~/.claude/skills/3d-asset-making/scripts/sweep.mjs <file.glb> <out dir>
  [--dist 12,30,60,100] [--elev 15,35] [--step 2]` (~5 min; Playwright via `PLAYWRIGHT_PATH`, Chromium via
  `CHROME_PATH`) → `SWEEP.jpg` (worst views with blink red / cracks cyan, charts by azimuth), `marked/`, `frames/`,
  `sweep.json`, last line `RESULT: PASS|FAULT`. Blink = two surfaces close enough for the depth test to flip (a 24-bit
  depth step is 0.4 mm at 60 m, 1.2 mm at 100 m: keep stacked surfaces ≥ 5 mm apart or cut the hidden one).
  `--selftest <dir>` re-calibrates.

## Material correctness: `pbr_check.py`, `matref.py`

- `python3 $K/pbr_check.py <file.glb> [--class-map asset.json] [--version near] [--against above.glb] [--json f]
  [--heatmap dir]` or in Blender `--python $K/pbr_check.py -- [--collection X] [--bake 32 --for-bake]` → M1-M11
  (in-between metal, white plastic, dark metal F0, lost clear coat), E1-E3 night glow, G1-G8 sides / normal maps /
  tangents / sizes, G9 occlusionTexture (INFO per material: median, p5, area below 0.5; WARN when the median is below
  0.5; R x strength, never read as metal or roughness), T1 px/m from switch.json; last line `PBR RESULT: PASS|WARN n|FAIL n`, exit 2 on ERROR.
  `python3 $K/matref.py <query>` → measured base colour / metallic / IOR (Physically Based, CC0). Classes are declared
  in asset.json `"materials"`. The toolkit runs it: bake.py pre-flight, export_game.py gate, lods_all summary,
  render.py round sheet header.

asset.json `"materials"` schema:
```
"materials": {
  "<material name or glob>": {"class": "bare_metal|metallic_paint|paint|plastic|rubber|glass|fabric|wood|stone|ceramic|leather|dielectric|dirt|decal|emissive|layered",
                              "metal": "<matref name, bare_metal only>", "ref": "<matref name>",
                              "source": "physicallybased.info | measured: ... | judged: ... | inferred",
                              "sheet": true /* real thin sheet: doubleSided allowed */}
}
```

## Blender bridge: `bridge.py`

- `python3 $K/bridge.py claim <task> <run folder>` → its own port + `mcp.json` (through your project's bridge launcher,
  see SKILL.md "Project hooks"); `python3 $K/bridge.py <port> <script.py>` runs the file in that Blender (set
  `result = {...}`) and prints JSON; `python3 $K/bridge.py release <task> <run folder>` when done. One run folder per
  parallel builder.
- `python3 $K/bridge.py step <port> <part.py> --part NAME [--thumb] [--plan parts.json] [--run DIR] [--lod L]` — one
  build step in the live Blender between `kit3d.step_begin` and `step_end`: dependents re-attached, `kit3d.check` on
  the touched parts, scene saved as `<run>/steps/<part>/<part>-vNNN.blend` (a copy), `--thumb` renders
  `<part>-vNNN.png` (Workbench, ~0.5 s), relations and flags written to parts.json, a `component` event reported.
  Prints <= 8 lines; the check JSON (`<part>-vNNN.check.json`) lists every failing place for `render.py inspect
  --from`. Exit 0 PASS, 3 check FAIL, 1 script error (it prints where to look the error up in
  `3d-modelling/references/PITFALLS-blender-5.2.md`).
- `python3 $K/bridge.py detach <name> [--dir D] [--mem 12G] -- <command ...>` — any long job (round, lods_all, a
  review, sweep) in the background, in the memory scope, nice 10, Blender gets `-t 8`: returns at once, `D/<name>.log`,
  `D/<name>.done` (JSON: exit, seconds, last lines). `python3 $K/bridge.py wait <name> [--dir D] [--max 110]` blocks up
  to 110 s by default (under the 120 s a tool call gets by default; `--max` up to 230 only with a longer call timeout)
  and prints the summary or "still running".
- A claim is an exclusive file `~/.config/blender-mcp-bridge/<port>.env`. Each builder that draws in parallel needs
  its own run folder (`<run>/builders/<name>`). Never touch a port you did not claim.

## Part-building library and plan check (in skill `3d-modelling`)

- scripts/kit3d/ — part-building library (Blender 5.2): placement by relation + kit3d.check (BVH-measured entries,
  gaps, z-fight, back-to-back, UVs; ~0.2 ms per relation).
- scripts/plan_check.py <run>/parts.json [--done] — validates the plan (dims, host/free, material sources, night state,
  LOD fates, tool-only flags with evidence).

## Asset search with pictures: `search.py`

- `python3 $K/search.py <run folder> <parts.json>` (parts: `[{part, description, look, size}]`) → cheap `claude -p`
  scouts (Haiku) look in your libraries, then Poly Haven / CC0 online, and save a picture of every candidate →
  `<run>/search/SHEET.jpg` + `results.json` + one `search` event per part. Brief: `scripts/search_brief.md` (edit it,
  not the code: list your own library folders there). ~3 min and a few cents per part.

## Review: `luna_review.py`, `rounds.py`

- **Level review**: `python3 $K/luna_review.py <new key per round> "<what it is, what is not part of it>" <pictures…>
  --glb <file.glb> [--concept <pic>] --run <run folder>` → a packet in `assets-lib/_luna-review/<key>/` for the
  project's level reviewer, prints `LEVEL n` and the REVIEW.md path, appends the `review` event with `--luna`.
- **Checks** (same script, each a fresh blind vision session, ≤720p, usage logged):
  `luna_review.py --make-questions inspect.json [--parts-json parts.json] --out q.json`;
  `luna_review.py <key> "<what it is>" <pictures…> --no-level --out-dir DIR` plus any of `--questions q.json [--repeat 2]
  [--inspect inspect.json --parts-json parts.json]` (yes/no/unclear; sets parts.json checks.inspect), `--versus
  ROUND-<best>.jpg [--concept pic]` (win/tie/lose over two mirrored calls), `--fixes fixes.json --before PIC` (applied /
  not applied / made worse / not seen / unclear); `--dry-run` writes the prompts without calling.
- **Keep the best round**: `python3 $K/rounds.py save <asset dir> <n> <work.blend>`; `rounds.py decide <asset dir> <n>
  --gate <round log|check json|pass|fail> [--luna <out-dir>] [--cap 4] [--finding "…"] [--run <run>]` → KEEP n /
  REVERT to m / FIX CHECKS (+ STOP at the cap); `rounds.py revert <asset dir> <work.blend>`; `rounds.py status`.

## Geometry check

- `mesh_integrity.py` (skill `3d-modelling`): BODIES, NON-MANIFOLD, WATERTIGHT (inside-out parts), GAPS, FLICKER. Full
  description: skill `3d-modelling`, "Look twice".

## Game versions: the toolkit

Every script has `--help`; `nice -n 10`, ≤ 8 threads (`-t 8` and `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=8`), one
Blender job at a time, and a memory ceiling on every heavy job (Conventions). `lods_all.py` runs every child that way
(`--mem 12G`, `-t --threads`, the thread env, peak per step in LODS.json). Measured peaks: bake near 2.9 GB, simplify
0.7 GB.

**The method: a version is judged by its ERROR IN PIXELS, not a triangle count.** Its limit is 2 px at the closest
distance the game shows it (game camera fov 40, 1080 rows: 1 px = d × 0.000674 m). Switch distances live in ONE file,
`$K/switch.json` (`--family`; read from your game's code; the example family `train` gives near 7.5 m 1.0 cm, mid
92 m 12.4 cm, far 292 m 39 cm). Every tool reads it (simplify, uvpack `--band`, render.py lodcmp/versions `--family`,
asset_record `--switch-family` → `lod_switch` + per-version `switch_m`/`shown_m`/`error_target_m`). The triangle
budget is a CEILING: over it the run stops and says "needs N for 2 px, budget B, over by X, mostly in <parts>"; it
never cuts deeper silently.

**Default: all of it as ONE background job**, then read one short file:
`nice -n 10 python3 $K/lods_all.py original.blend OUTDIR --key <key> --high CAR --family train [--budgets 9600,3500,2100]
[--lows near=GAME_near,…] [--source auto|simplify|given] [--slots FILE | --no-slots] [--exclude GLOBS]
[--glass-through 'mat.lens*'] [--surface-node N --glass-node N] [--original-glb GLB] [--no-lodcmp] [--no-sweep]
[--no-thumbs] [--record asset.json --model M --effort E --task T --session S] > OUTDIR/lods.log 2>&1 &`.
Per version: a `--lows` collection that EXISTS is a by-construction version (hand/generator) and is JUDGED by the same
2 px check; one that does not exist is MADE by `simplify.py`; near and mid then go through `live_version.py` (live
slots), far through uvpack → bake → export_game with every gate; then `render.py lodcmp --at-switch --states
day,dusk,night` (a simplified version whose day/dusk regions fail is simplified again with them locked, ≤ 3 passes,
capped at 1.5x the triangles; its THIN-FEATURE test, `scripts/_thin.py`, reports a broken stripe or trim line the 1 %
region test cannot see: orange = lost, green = added on the difference picture, `advisory` lines in lodcmp.json and
LODS-SUMMARY.md; ADVISORY until `--thin-fail`); `simplify.py` also cuts faces that lie in one another (`--coplanar
cut`, default; report key `coplanar`, `left` must be 0 pairs: they blink in the game), `sweep.mjs` (blink + slits in
the game's three.js), `render.py thumb` at day, dawn, dusk, night, rain; then the `versions` sheet and
`asset_record.py`. Progress in `OUTDIR/LODS.json`, result in `OUTDIR/LODS-SUMMARY.md`; exits non-zero at the FIRST
failing gate and names it. `--allow-over` continues past an error/budget miss and says so; `--allow-faults` goes on
with a REFUSED version's `.rejected.glb` for the pictures (summary says which gates, no asset.json record: for a look,
never a release); `--allow-inherited` passes integrity faults no worse than the version above's own;
`--skip-pbr-check` only with a reason. Read `LODS-SUMMARY.md` and LOOK AT `versions/VERSIONS.jpg` enlarged before
trusting a run.

**Game material slots.** Where the game drives class colours, its glass shader, night glow, lamps and rain by
MATERIAL NAME, near and mid keep one material per game role; the bake only adds what lives inside a slot (a grey
AO/wear/dirt multiplier in the colour texture; the material's colour factor is the slot's colour, which the game
replaces) plus the normal map; far may merge. A slots file maps the original's materials to roles:
`{"contract": "/abs/GAME-CONTRACT.md", "roles": {"body-<name>": ["mat.body", "mat.body_flute"], "stripe-<name>":
["mat.red"], "glass-window": ["mat.glass"], "LED-<name>": ["mat.lens*"], …}, "required": {"near": […]}, "merge": {"far":
[…]}}`, and/or your shader library's `game-slots.json`, whose slot names match originals that NAME their materials with
them. A family's default slots file and contract may be named in `switch.json`. export_game refuses when a required
slot is missing or a used name is not in the contract (a new name is a game change). Unmapped materials go into one
`<name>.baked` slot with the full baked colour. The default required role names live in `_kit.SLOT_REQUIRED`: set them
to your contract's names.

The single steps, for a fix in between:
0. `$B -b work.blend --python $K/simplify.py -- --high CAR --level far --family train --into GAME_far_auto --save
   work.blend [--budget 2100] [--slots FILE] [--lock-from lodcmp.json]` (or `--judge GAME_far` for a version that
   exists) → meshoptimizer `simplifyWithAttributes` (zeux's npm package, run in node from `~/.cache/3d-asset-kit/node`,
   installed on first use) with ErrorAbsolute + Prune at the pixel target, attributes normal + material colour,
   MATERIAL BORDERS LOCKED, faces no outside view reaches dropped first (cached per original), the measured surface
   distance (p99 both ways) decides and lowers the target when meshopt's estimate misses; report with error px, worst
   places and triangles by part. Zero-area triangles are dropped (they made validator TANGENT errors and a reimport
   mismatch). Repeated triangles (the same three vertices, back to back: a thin sheet's two sides) get their own
   vertex copies: Blender's `mesh.validate()`, which the glTF exporter runs, deletes all but one.
   **Known limit:** mesh_integrity counts FLOATING BODIES in a simplified version, most from the culling of unseen
   faces (`--cull-only` writes the seen faces unsimplified: a part's seen shell touches the rest only through faces no
   outside view reaches; judge them with `mesh_integrity --held-by`), the rest from Prune / border moves; `--contact M`
   (lock vertices within M of another piece, off by default) costs triangles and barely helps.
   **Laid-on layers (`--layers auto`, the default):** a part laid on another surface and LOWER than the error target
   cannot stay a separate surface: the simplifier may move the base by the whole target, so the base comes through
   it, or the part folds flat. Such a part leaves the simplifier; the base hidden under it comes back; its outline is
   cut into the ORIGINAL base triangles as a material seam (not locked) and the triangles under it take its material,
   so the game slot stays live by name while its relief and fine colour go to the normal map and the bake. A part is a
   layer when 85 % of its seen surface is within `--layer-k` (1) x target of a face of another part that faces it,
   that base is bigger, the base is of ANOTHER game slot (same slot: a poke-through cannot be told apart after the
   bake, so flutes on the body stay geometry), and it is neither glass nor a lamp. Pieces under `--layer-min-px` (2) px
   in area or 0.75 px in width are dropped (the bake has them). **Proud parts** (`--proud-k 3`): laid-on parts of
   another slot 1-3 x the target high are simplified on their own at `--proud-error` 0.3 x target. **Joints**
   (`--joint 0.002 --joint-min 20`): two parts that butt edge to edge with different vertices were simplified apart
   (a crack at the seam). Each rim vertex is now inserted into the other part's rim edge within 2 mm, so both rims
   share positions and stay one seam; only between parts whose seen area is at least (20 x target) squared. At the end
   vertices at one position are joined. The report has `layers` (rows: part, base, height, cut_in), `on_top` (share of
   the original's seen surface where the version shows the same slot first; low by construction for thin features at
   mid/far, not a gate) and `joint_welded`. `--layers off --joint 0` = the old behaviour.
1. `$B -b work.blend --python $K/uvpack.py -- --low GAME_near --save work.blend --size 2048 [--band near --family train]`
   → one non-overlapping atlas at even texel density, gutter max(4, size/128) px; prints px/m against what the screen
   needs where the version is first seen (WARNING below 0.7×) and the overlap (must be 0, else nothing is saved, exit
   1). Modifiers are applied first, so a Solidify inner skin that kept the outer skin's UVs is caught. A small island's
   margin is half its own longer side (4 px at least, `--margin-px` at most): a simplified version is ~1 500 separate
   pieces, and a fixed 16 px margin round every bolt left 3.6 % of the atlas in use. `--charts xatlas` (pip `xatlas`)
   is wired but NOT the default and NOT verified.
2. `$B -b work.blend --python $K/bake.py -- --low GAME_near --high CAR --out export/maps --prefix near --size 2048
   [--exclude 'C.interior_liner'] [--slots FILE --level near]` → color/rough/metal/mr/normal/emit/ao (+ slotcolor and
   `near_slots.json` with --slots) PNGs + `near_bake.json` (miss share per pass: above ~2 % raise `--max-ray`;
   index-buffer hash for export). **Ambient occlusion** (`ao`, on by default: a game without SSAO gets contact darkness
   in seams, gaps, louvres and window insets only from this map): Cycles AO bake, selected-to-active through the same
   cage, measured on the HIGH original (detail the low lacks still occludes); the low, the cage and the decal sheets
   are not occluders. `--ao-distance` default 2.5 % of the original's diagonal, 0.05-1.0 m; `--ao-samples 256`, no blur
   by default (`--ao-blur S` texel sigma, over hit texels only). Stored in R of `mr.png` = glTF ORM (R occlusion, G
   rough, B metal: one texture, one fetch); a version without rough/metal maps gets its own `<prefix>_ao.png`. The `ao`
   block of the bake json has distance, samples, median, p5, the share of texels below 0.5. Measured on a 2048 px near
   (368k high triangles, 8 threads): the AO pass 19 s of an 87 s bake, peak 2.70 GB. Realises instances with world
   transforms (mirrored mounts flipped), keeps each part's procedural texture space (TexCoord Object/Generated, Object
   Info and textures with an unlinked vector, pinned before the join), bakes layered Mix-shader materials by their
   factor, decals over the paint by alpha, clear glass as a dark pane, tinted lamps keep their tint (`--glass-through`
   drops a lens so the reflector behind it bakes), textured parts without UVs get a box UV first, padding + full fill.
   The cage is an automatic CAGE OBJECT: each low triangle's depth under the original's outer skin is measured at 7
   points and each vertex is pushed just past its deepest triangle. **Start check** (2000 samples): from the cage
   inward the first surface must face the cage; a back face first while the cage point is still under the outer skin
   (between a thickened wall's skins) on > 2 % → refused, places in `<prefix>_start_check.json`. Overlapping low UVs
   and missing image files are refused; `pbr_check.py --for-bake --bake 32` (`--class-map asset.json`) refuses
   M2/M5/M11 on the original before baking. Slot roles are read looking THROUGH glass-* panes. Slot fit (`--slot-fit
   0.12`): a slot triangle whose baked colour is not "grey × the slot colour" (an emblem, a decal) goes to the
   `.baked` slot with its full colour.
   **Self-check:** per face group (±x ±y up down) baked metal/rough/colour against the original's material of the
   surface SEEN there (first surface met coming in along the low normal; nearest surface reported as info); drift
   (metal > 0.1, ΔE > 8 with ≥ 20 plain-colour samples) = exit 1. `--verify-only --verify-maps color=…,mr=…` checks
   maps someone else baked.
3. `$B -b work.blend --python $K/export_game.py -- --low GAME_near --maps export/maps --prefix near
   --out export/<key>-near.glb --name <key>_near [--slots FILE --contract GAME-CONTRACT.md --level near]
   [--surface-node N --glass-node N] --against <original or version above>.glb` → one primitive per slot (or one
   surface) on one atlas + 1 glass draw, mount./light. empties with extras, origin kept, +Y up, surface single-sided;
   colour/MR JPEG, normal and emission PNG. When the bake json has `ao`, every surface material gets
   `occlusionTexture` = R of the same MR image (occlusion is read from a node group named `glTF Material Output`, input
   `Occlusion`, which export_game adds); `--no-ao` leaves it out (A/B looks). three.js reads it as `aoMap` (uv0): it
   darkens the hemisphere and environment light only, never the sun. JPEG note: Blender writes JPEG 4:2:0, so packed
   channels bleed into each other a little (roughness mean error about 2-3/255); a PNG ORM would be about 3x larger.
   Written to a temp file; **the final GLB only when every gate passes**: mesh_integrity (no RESULT FAULT; designed
   places in `--allow-designed FILE`), every textured primitive has its TEXCOORD, no back-to-back faces on a
   `--double-sided` surface, no bake drift, UVs and triangulation identical to the bake (tangent frames), the Khronos
   glTF-Validator (npm `gltf-validator`, no errors), a fresh reimport in an empty Blender reads back the same mesh
   objects / primitives / triangles / materials / textures, slot names vs the contract, `pbr_check.py` (incl. E1 night
   lights declared → something lit; places in `<glb>.pbr.json`); otherwise `<key>.rejected.glb` + reports, exit 1.
   Results in `<glb>.json` and `<glb>.integrity.json`. `--allow-inherited` passes integrity faults that are no worse
   than the `--against` file's own (said as `integrity_inherited`). `--skip-pbr-check` only with a reason (an OVERRIDE
   line).
4. `$B -b original.blend --python $K/export_original.py -- --out original/<key>-original.glb --collection CAR` → the
   film original WITH its look for the viewer: library kinds stay live (contract in extras), other procedural
   materials baked per mesh, one bake call per map. Collection instances made real; a mesh shared by many copies baked
   once (each copy alone when its material reads the object); modifiers applied before each atlas is unwrapped,
   overlapping atlases refused; textured parts without UVs get a box UV; same temp-file gates (TEXCOORD,
   glTF-Validator, reimport). A 500-mesh train car: about 12 min.
5. `python3 $K/asset_record.py asset.json --model claude-opus-5-5 --effort low --task T --session S [--transcript X.jsonl]
   --lod near=export/<key>-near.glb --lod mid=… --lod far=… --switch-family train --states day,night` → `made_with`
   entry (with start/end/active_minutes when known, never guessed), `time`, `lods`, `lod_switch`, `mounts`, `lights`,
   `states`, `components`, `sources`; never drops keys, never writes cost keys, rewrites only on change.

## Shader kinds: live materials as Blender + game pairs
Rule: materials stay shaders through near and mid; only far may be fully baked. How (measured on one train car): bake
only what geometry knows (a tangent normal map + a mask: R AO, G edge, B feature, A slot id) and shade each slot live
with a shared kind from the library. A kind is written ONCE (one source file) and emitted to both the Blender node
group and the GLSL (hand-written pairs drift; one source matched to albedo ΔE 0.2-2.1, rough/metal error ≤ 0.03). Name
each material with the application's slot name, append the kind's node group (`idle.<kind>@<ver>`), export with the
parameters in `extras.idle`, the mask as `occlusionTexture`, the normal as `normalTexture` and fallback factors, and
pass a pair check (Cycles under the game's own lights vs three: albedo ΔE < 2.5, rough/metal MAE < 0.03, beauty ΔE < 5,
luminance 0.9-1.1). Near has anisotropy and fine relief, mid drops them (they fade out by pixel footprint, so the
switch does not pop), far is baked. Cost measured on one GPU: 0.8× the GPU time of the baked version. A new material
need is a new kind, never a one-off procedural graph. Judge metal under a sky environment, never a studio box
(RoomEnvironment made the twin 10-17 % brighter, ΔE 9-10; the sky env ΔE 2-4.4).
Effects: empties `fx.<kind>.<n>` with custom properties, drawn by the game as one GPU-animated instanced draw per
kind (sparks, steam, drips, glow; no per-particle CPU work).

This toolkit does not ship a shader library; the dashboard has a stand-in (`dashboard/stubs/shader-library`).

## The asset record and the dashboard card
- `asset_record.py` (step 5 of the toolkit above) writes makers, time, lods, switch distances, mounts, lights, states,
  components and sources; it never writes cost keys. Cost comes from the cost writer of whoever launched the maker
  (it prices the maker's and builders' transcripts and any image-generation runs → `COST.md` per component AND each
  `asset.json`).
- Prices: a price table (the dashboard's Runs view fetches `PRICES_URL`, JSON `{"claude": {"<model id>": {"in",
  "out", "cr", "cw", "cw1h"}}}` in USD per million tokens: input, output, cache read, 5-minute and 1-hour cache write). A model missing from the table leaves the total empty and the rest in `api_cost_known_part`, naming
  what is left out.
- Dashboard: each source in `config/sources.json` scans its `root` with `glb` / `blend` globs; a nested run folder
  (e.g. `train/rebuild-*/export/`) needs its own entry. The source names its record (`madeWith`), or the project's
  `madeWithDefaults` covers it; `renders/{key}.png` goes first in `previews`. With only a `.blend` in the source (no
  `glb`), the dashboard's exporter bakes procedural materials itself (`blender/export_blend.py`, per-object 512 px CPU
  bake; slow for a large original: 800+ bakes took 40+ min).
- Thumbnail look: 1024–1280 px, three-quarter view, sun + sky, soft shadows, Khronos PBR Neutral.

## Search by hand (when `search.py` does not fit)
One call per few parts to a cheap searcher (`claude -p --model claude-haiku-5-5`). For every candidate it saves a
preview to `search/<part>/<candidate>.jpg` (the site's own thumbnail or your render) plus source/path, license,
format, triangles, materials; build `search/SHEET.jpg` (one row per part, candidates side by side). `search.py` writes
its raw answers as `search/raw-g<N>.json`.

## Known open work in the toolkit
1. Slot ID maps read as single texels draw 4 cm stairs on every slot border at 7.5 m: smooth in the game (4-texel
   majority), or keep slot borders in geometry on near, or bake the ID map at 2048 px.
2. Bake edge rounding into the near normal map (Cycles Bevel node, 30 mm).
3. A night check per version in the game light: fail when a version with windows shows no lit pixels.
4. Warn when one slot covers faces both inside and outside the shell (cabin slots are named apart from outside slots).
5. Near atlas density: 2048 px gave 50 px/m, 4096 gave 104 px/m against 198 needed at 7.5 m on a train car. Next:
   texel density by seen area, one shared texel block for tiny pieces, or a second atlas for the `.baked` slot.
6. A far version should be one closed hull (remesh the seen surface at about a quarter of the target, simplify that,
   bake everything onto it); per-part simplification leaves holes and open edges at 39 cm.
7. `export_game`'s inherited rule compares a version's NOT-HELD floating count with the reference's RAW count; it
   should compare like with like.
8. Slits at near/mid mostly come from the original's own clearances whose backing faces were culled as unseen; a
   second visibility pass from outside (rays along the game's view rings through silhouette and border edges) is the
   planned fix. Faces 0.3-5 mm apart are not cut by `--coplanar cut` (they fight beyond ~60 m).
9. `lodcmp`'s thin-feature test is advisory until it is calibrated on more assets.
10. Per-part razor / facet / flat-shaded share inside `kit3d.check` (import `look/mesh_core.py`).
