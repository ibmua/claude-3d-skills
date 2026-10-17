# Building one part or one set of components: what a builder needs

For a builder (a subagent of an asset's maker, or a worker given one component). The whole asset job is
`3d-asset-making/SKILL.md`; you do not need to read it. Read this page, your brief's `DIGEST.md`, and from skill
`3d-modelling` the sections "While modelling" and "Make it look made by a master". Tool details only when a tool
surprises you: `references/TOOLS.md` (grep its headings) or `--help`.

`K=~/.claude/skills/3d-asset-making/scripts`, `M=~/.claude/skills/3d-modelling/scripts`.

## Your Blender
- You get your own headless Blender. Never use the `blender` MCP tools (they drive the planner's scene) and never touch
  a port you did not claim.
  `python3 $K/bridge.py claim <run>-<set> <output folder>/builders/<set>` prints your port (the output folder your
  brief names: scenes are bulky and go to the HDD); `python3 $K/bridge.py release <run>-<set> <same folder>` at the end.
- One component per scene: start each with an empty scene (`bridge.py claim` empties Blender's start scene: its
  answer says `"scene": "emptied ..."`; a reopened scene is kept as it is); after its last passing step copy that step's `.blend` to
  `components/<name>/<name>.blend` in the output folder your brief names. You never edit another builder's component.
- A component that sits on a host another builder owns (a window unit on the body shell) is built with that host
  LINKED into your scene from the file and anchor names (`anchor.<name>`) the planner gives you; in `parts.json` its
  host carries `"host_external": true`. You attach to the anchors; you never rebuild or move the host.

## Build each part with kit3d, one step at a time
- `import kit3d as k`: parts are PLACED BY RELATION, never by typed coordinates along a host's normal: `attach` (rests
  on or enters its host by 5 mm; `conform=` bends bases, frames and glass onto curved hosts), `span` (rails, rods,
  handles, springs from their two ends), `lay` (decals, stripes, lettering 6 mm off, or `cut=True` inlaid flush),
  `scatter` (rivets), `into` (built in place: measured, not moved), `free(reason)`, `root()`, `mirror`, `array`.
  Start from the closest script in `$M/kit3d/examples/` (14 parts; `run_all.py` builds, checks and draws each).
- Shapes come with UVs in meters. Every textured part has real UVs and no two surfaces share texture space.
- One step = one part: `python3 $K/bridge.py step <port> part.py --part NAME --thumb --plan <run folder>/parts.json`. It runs your script, re-attaches
  dependents, measures (`kit3d.check`), saves a versioned .blend and a thumbnail, flips the flags in `parts.json` and
  reports the event. You get at most 8 lines: PASS, or FAIL with part, host, millimeters and place. The PASS line
  shows `entry` (attach, span, scatter) and `into` overlaps in millimeters. Two ADVISORY lines never fail a step:
  `LOOK` (parts whose corners are razor or facet, or that are flat-shaded: fix the shading now, not at the end) and
  `FRAME` (parts that still need `k.freeze`, below).
- The plan (`parts.json`, format `$M/kit3d/PARTS-SCHEMA.md`) is written BEFORE modelling and carries, at the top level,
  the three composition lists: `"composition": {"dense_clusters": [...], "rest_areas": [...], "splits": [...]}`.
  `plan_check.py` fails a plan without them.
- **A part is done when `kit3d.check` PASSES** (entry 2-10 mm, lift 6 mm, nothing unplaced, no two faces within 2 mm,
  no back-to-back duplicates, sound UVs) and `python3 $M/plan_check.py <run folder>/parts.json` (no `--done`) passes with
  the part's `relations` and `uv` flags true. (`--done` also wants `inspect` and `lod_kept`, which no tool writes with
  evidence yet: say so in the hand-back; never set a flag by hand.) Fix the
  relation, never the threshold. The numbers decide, not a small picture.
- On a Blender error: look it up in `3d-modelling/references/PITFALLS-blender-5.2.md`; fix the cause, never delete the line.

## Upgrading an existing asset (keep what is good, replace what is not)
- Load the original's collection in your first step and take every kept object into a plan part in that same step:
  `k.adopt({'door.frame': 'frame', 'door.leaf': 'leaves', ...})` (or `k.adopt(obj, 'frame')`). Then give each its
  relation like any other part: `k.root(frame, 'root: ...')`, `k.into(leaf, seal)`, `k.attach(...)`. Never set
  `o['kit3d_part']` by hand and never edit `parts.json` to remove entries.
- The first step FAILS on purpose: it is the baseline (the original's unplaced parts, missing UVs, coplanar faces).
  Write its numbers down as "before". An object you did not adopt fails as `unplaced` with the adopt hint and is
  named on the step's `plan` line; it is never written into `parts.json` as a part of its own.
- A part you rebuild keeps its object names, its material names, the origin and the mount; `k.begin(part)` clears
  what that part's script made last time, so adopt kept objects into parts whose scripts do not rebuild them.
  New parts may be built into the original's collection (`k.begin('bracket', coll='LP_original')`): there `begin`
  clears only objects tagged with that part, the kept originals stay.
- **Seat what only touches.** An original that looks right usually fails in bulk (a lamp post: FAIL 113, of which
  slit 86, back-to-back 11, gap 4), because its parts rest ON each other. After the baseline run `k.seat()`: every
  kept object whose `into` fails gets the vertices that lie on its host moved 3 mm into the host (the visible shape
  does not change) and is measured again. Read the line it returns:
  `re-hosted` = the part did not touch the host you declared and now hangs on the mesh it touches (check the list);
  `thin host` = the host is under 4.4 mm thick there, so nothing can enter it 2 mm: `k.seat(names, thin='force')`
  grows the host's far side when that side is out of sight (inside a closed housing), else seat the part on a
  thicker host, `k.seat(part, host)`; `left` = a real gap, or a part that touches only what hangs on it: name its real
  host. On the lamp this took FAIL 113 to FAIL 11 in one step; what stays are faults inside the original's own meshes
  (doubled faces, a plate 1 mm proud of its neighbor): each FAIL line now says the gap, both normals and what to do.
- **Redoing a cut or a seat on a kept mesh:** `k.restore(obj_or_list, '<source>.blend')` first. It takes the mesh back
  from the source file and keeps THIS file's materials. Never reload kept objects with `bpy.data.libraries.load`: the
  load brings copies of their materials (`X.001`) and of their parent, your material edits then go to copies no
  object uses, and no picture changes. `kit3d.check` names that state in a `MATERIALS` line: act on it at once.
- `into` reads how far the part's deepest point is from the host's NEAREST skin, so a vertex 2.8 mm inside a 3.1 mm
  pocket floor reads 0.3 mm. A slit on a thin host says so in its FAIL line.
- A feature you cut INTO a kept part (slots, a pocket) is not a part: plan it as
  `{"part": "fins", "feature_of": "head", "how": "...", "lod": {...}}` (`kit3d/PARTS-SCHEMA.md`).
- A step that touches many parts (a seat step, the final step): give `bridge.py step --part` any one of them; the
  step measures every part it touched and its `plan` line lists them all.
- A brief that asks for things that leave the kept envelope (a wider pad, fins standing on the lid): the envelope
  wins. Make them inside it (cut in, on a hidden face) or leave them out, and say so first in the hand-back.
- `k.mirror(parts, names=[...])` takes the copies' names as a list in the order of `parts`, or `{original: new}`.
- A kept object's material: keep its measured color. When the brief names a material the file contradicts (brief
  "aluminium", file the measured stainless color), keep the file's as the default, put the brief's in the file as a
  one-swap variant, and say so first in the hand-back.

## Every part in the asset's frame: `k.freeze`
- The shared shader kinds read OBJECT coordinates (grime rises to an object Z, brushing runs along object X).
  `k.attach`, `k.lay`, `k.mirror` and `k.array` leave a part in a frame of its own. After placing such a part call
  `k.freeze(part)` (or `k.freeze()` for every object of the current part): its mesh takes the placement and the
  object sits at the origin. The relation stays measured, a changed host still carries the part along, and anchors
  that other parts' scripts give in its own frame (`k.on('+z', x=..)`) still land where they did.
- Never apply a transform by hand (`mesh.transform`, Apply in the UI): the relation keeps the old axis and the check
  then measures along the wrong one, sometimes without failing.

## Materials
- Declare what each material IS before giving it numbers (kit3d `ref=` fills measured values and records the source):
  bare metal = metallic 1 with the measured color (`python3 $K/matref.py stainless`); metallic paint = in-between
  metallic only under a clear coat >= 0.5; paint, plastic, rubber, wood, fabric, dirt = metallic 0.
- A number without a source is marked `inferred`. Opaque surfaces are single-sided.
- Use a shared shader kind from the project's library before writing a node graph; never a one-off procedural graph
  for something the library has (the brief names the library: its README lists the kinds and their parameters; append
  `idle.<kind>@1` from `<kind>/<kind>.blend`). When the library has no kind for a surface (a tread plate, say): one
  small graph on the nearest kind's values with the same mask, `pbr_check.py`
  must pass on it (no dirt mixed into the metal value), and the missing kind is named in the hand-back.
- The wear mask of a component, one step (when your library has a mask tool): `$B -b --factory-startup -noaudio -t 8 <component.blend> --python
  <library>/mask_atlas.py -- --collection C.<name> --exclude glass --size 2048 --bake <out>/tex/<name>-mask.png --save`
  (in a memory scope, on a COPY of the built scene). It keeps kit3d's meter UVs as layer `UVm`, makes the 0..1 atlas
  the kinds' `Mask` reads in `UVMap`, cuts frames and seals into strips, packs, and bakes R (AO 12 cm plus the
  crevice pass: shallow joints, spread 6 cm) and G (convex edges). A material that tiles an image in meters reads
  `UVm` by name. Start `grime` at 0.35. The mask of a component is a preview: the assembly bakes it again.
- Night: anything that glows is emissive on the part itself, with its `light.<kind>.<n>` empty where it lights
  something. Day, dusk, night and rain are states of one form.
- Who owns the glow of a component (`pbr_check.py` E1 "night lights declared ... no material emits"): the part that
  carries the glass or the lamp. A component with panes sets its own glass kind's `glow` (`glass.window`, 1.0 unless
  the brief says otherwise): the game lights windows by the glass material, so the pane is where it lives. The
  assembly owns the room behind it (`light.saloon.<n>` empties, the interior) and never adds a second glowing pane
  behind a component's glass. A component with nothing that can glow (a vent, a handrail) cannot answer E1: say so in
  the hand-back and leave it for the assembly; never add emission to pass a check.
- `render.py` night and dusk switch the kinds' night on (`idle_night` 1 and 0.4): a pane with `glow` shows lit in
  every night picture. Never hand-make a preview copy with emission added.
- An asset with a night property of its OWN (a lamp's `lp_night`): give `--night-prop lp_night` (and `--wet-prop
  lp_wet`) to `render.py`; it gets the same values as `idle_night`. Better: make new materials read `idle_night`.
  A lamp's light on the ground and inside its optic comes from `light.<kind>.<n>` empties; an area light may be a
  rectangle (`type` AREA, `size` 0.12, `size_y` 0.47: one light for a long optic), a spot's edge is `blend` (0-1).

## Make it look made, not generated (the short form; the full rules are in `3d-modelling`)
- Size every edge for the screen: 1 px = distance x 0.000674 m. Primary corners at their real radius (never under
  60 mm), secondary parts 12-25 mm with 2 segments, small parts 3-6 mm with 1 segment. Smooth shading + Bevel (angle 30)
  with Harden Normals OR a WeightedNormal after it, never both with Keep Sharp (Blender 5.2 then makes hard-edged
  bevels); a flat-shaded or razor-edged part reads as computer made.
- Dense, functional detail in a few places; calm areas between; nothing evenly spread. Real sizes for what a hand or
  foot uses. Seams drawn 8-12 mm wide so they survive the camera distance.
- Restraint: add what explains the object and round its edges, keep big surfaces calm; no rows of slots, fasteners or
  streaks for their own sake (two upgraded props won "more real" and lost or split "ship in a warm miniature game").
- No large area of one value: per-panel value and roughness jitter; the shared wear layer, quiet.
- Measure it: `python3 $M/look/look.py <component.blend> --out <dir> --family component --collection C.<name>` prints
  LOOK lines (advisory; `--family component` drops the two outline measures a part flush in its host cannot meet; a
  whole asset uses its own family; a pole, post, mast or sign uses `--family pole`, which also drops the body bevel
  and the calm-cell share a thin round thing cannot meet). Always name the collection. Without it look.py picks the
  kit3d-tagged objects, or the whole file without stage collections and Blender's start Cube, and its first line
  says what it measured and what it left out: read that line. Fix or explain each LOOK line.

## Check, look, hand back
- `B=blender`; `MV_BLENDER_GPU=1 OPENBLAS_NUM_THREADS=1 systemd-run --user --scope -q -p MemoryMax=12G
  -p MemorySwapMax=0 nice -n 10 $B -b --factory-startup -noaudio -t 8 --python $K/render.py -- sheet <component.blend>` →
  `SHEET.jpg` (the same form for `thumb` and `inspect`; plain `python3 render.py` only prints `--help`). `thumb` after
  every save. Look at each view ENLARGED,
  write the five weakest things as things seen, fix them, repeat: at least 2 fix rounds per component.
- A part that faces one way (a door on the +y flank): give `--front +y` (the side it faces) to `sheet`, `beforeafter`
  and `versions`, else the camera may stand behind it. Write a negative side as `--front=-y` (`look.py` also takes `--front -y`). Before/after at game size:
  `render.py versions --files before/x.blend,after/x.blend --dist 7.5,33 --front +y` (`--labels before,after` names
  the columns when the file names do not).
- **A tall or long asset needs close-ups.** A 3.7 m lamp on a 1280 px tile is 2.9 mm a pixel and a tenth of the frame:
  its head, door and base cannot be judged there. Besides the whole-asset sheet make one sheet per region the brief
  names: `sheet <file> --region 'LP_head*,LP_optic*'` (object name globs) or `--focus=x,y,z,radius` (meters), the same
  for `beforeafter`. Or `--hide` the long part (`--hide 'LP_column.tube'`) so only the region is framed. `inspect --at` gives tinted joint views, not a look picture.
- Material check of a `.blend`: `python3 $K/pbr_check.py <file.blend> --collection C.<name> --bake 64` (it starts
  Blender itself). Without `--bake` an input driven by nodes is not measured and its rules are not judged (an `INFO M0
  ... not measured` line): a result without `--bake` is not a pass for those materials.
- A vision review (`luna_review.py`) uses the Codex login your brief names (`CODEX_HOMES`); say which login you used.
- Every picture mode also writes its tiles WITHOUT labels in a folder named like the picture (`--out X.jpg` →
  `X/<view>-<state>.png`, `X/before-...png`, `X/after-...png`): same camera, no text. A blind judge gets those, never
  a crop of the labelled sheet.
- For a joint you doubt: `render.py inspect <file.blend> --part NAME --out <dir>` (close-ups at 1 mm/px with the measured
  stand-off in `inspect.json`).
- Hand-back: components with paths, the last `kit3d.check` and `plan_check` lines, look numbers, what is `free` and
  why, materials with sources, what still looks weak. Honest, with absolute paths.

## Working on a shared box, economically
- Every heavy job in a memory scope: `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=8 systemd-run --user --scope -p
  MemoryMax=12G -p MemorySwapMax=0 nice -n 10 <cmd>`, Blender `-t 8`, one Blender job at a time. `bridge.py step` and
  `bridge.py detach` do this for you.
- **Stop only your own jobs, by PID or by scope unit; never by name** (`pkill blender`, `killall`, `pkill -f render`):
  a shared box runs film renders and other agents' Blender bridges under the same user.
- Your prompt cache lives 5 minutes. Anything over about 4 minutes: `python3 $K/bridge.py detach <name> -- <cmd>`, build
  the next part, then `python3 $K/bridge.py wait <name>` (returns within 110 s, under the 120 s a tool call gets by
  default; "still running" = call it again; `--max` up to 230 only with a longer call timeout).
- Output goes under the folder your brief names. If that folder cannot be made, use one beside it that can, and say
  so first in the hand-back.
- Keep pictures out of your context: one sheet at most 1280 px wide plus the crops a finding needs.
- Report every save: `python3 $K/report.py <run folder> component "<one sentence>" --builder <name> --picture <thumb>`
  (`bridge.py step` reports into the folder its plan is in). Keep `PROGRESS.md` in your builder folder current: done, measured result, next.
- Quality first: never work smaller or rougher to save memory, time or usage. If something is short, say so and stop.
