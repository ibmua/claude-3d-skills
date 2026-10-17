# parts.json: the plan in numbers, with acceptance flags only tools flip

One file per asset (or per builder's share of it), in the run folder: `<run>/parts.json`. The builder writes the plan
BEFORE modelling; tools add what they measure. Read by `plan_check.py` (validates), `kit3d` (records relations,
flips `relations` / `uv`), `render.py inspect` (`inspect`), the LOD tools (`lod_kept`), `luna_review.py --questions`
(asks about the parts and their states). Units: metres. This file is the one definition of the format.

```json
{
 "asset": "tram-cab-a",
 "composition": {
  "dense_clusters": ["cab front: lamps, wipers, coupler, steps (z 0.4-2.1)", "each doorway: handles, lock, kick plate"],
  "rest_areas": ["upper side band", "roof field", "nose crown"],
  "splits": ["side height: skirt 0.25 / window band 0.30 / upper band 0.45 (no two equal)"]
 },
 "parts": [
  {
   "part": "roof.vent",
   "dims_m": [0.62, 0.40, 0.13],
   "host": "roof.shell",
   "relations": [{"kind": "attach", "at": "top", "by": "bottom"}],
   "material": {"ref": "physicallybased:Aluminum", "rough": 0.35, "rough_src": "judged: brushed, aged"},
   "states": ["day", "dusk", "night: unlit, catches the cab glow", "rain: wet sheen"],
   "lod": {"near": "keep", "mid": "keep, louvres as texture", "far": "merge into roof shell"},
   "checks": {"relations": false, "uv": false, "inspect": false, "lod_kept": false}
  },
  {"part": "pigeon", "dims_m": [0.3, 0.1, 0.2], "free": "a bird on the roof, flies off; dropped at mid",
   "material": {"src": "judged: grey feathers"}, "states": "as host",
   "lod": {"near": "keep", "mid": "drop", "far": "drop"},
   "checks": {"relations": false, "uv": false, "inspect": false, "lod_kept": false}}
 ]
}
```

| field | who writes | rule (plan_check fails the part otherwise) |
|---|---|---|
| `composition` (top level) | builder, BEFORE modelling | the three composition lists of `3d-modelling` "Compose the detail before modelling": `dense_clusters` (3-5 for an asset, fewer for one component: where detail is dense and functional, with heights), `rest_areas` (what stays plain), `splits` (the uneven divisions, 70/30 not 50/50, with numbers). Each a non-empty list of sentences. A builder's share of an asset may point at the asset's plan: `"composition": {"see": "/abs/parts.json"}`. plan_check fails the PLAN without it (a `plan:` line) |
| `part` | builder | unique name; the `kit3d.begin(part)` name; its objects carry `o['kit3d_part']` |
| `dims_m` | builder | 3 positive numbers (bounding box x, y, z in its own frame) |
| `host` | builder | the part it rests on / enters (another `part`, or an outside name with `host_external: true`) ... |
| `free` | builder | ... OR a reason it is held by nothing (`root` parts: `"free": "root: the car body"`) |
| `relations` | builder plans, kit3d overwrites | planned: `[{"kind": "attach"/"span"/"lay"/"into", ...}]`. After a build step kit3d writes the measured list (`kind, part, host, plan_host, at, by, embed / lift / cut, measured {entry_min_mm ...}`) and keeps the plan under `relations_planned` |
| `material` | builder | an object or a list of them; each value has a source: `ref` (a measured reference, e.g. `physicallybased:<name>`), `src` (one source for all), or `<key>_src` per value; an explicit `"inferred"` is allowed and counted |
| `states` | builder | list (or `"as host"`): what it does in each look of the plan's `needs.looks` (night, if needed: `"night: windows glow 2700K"`, `"night: unlit"`) |
| `lod` | builder | the versions in the plan's `needs.versions` (of `near`, `mid`, `far`): each starts with `keep`, `merge into <part>`, `texture`, `emissive band`, `normal map`, `card`, `simplify` or `drop` (+ free text) |
| `checks` | TOOLS ONLY | `relations` (kit3d.check: every relation measured in range, no unplaced/coplanar/back-to-back), `uv` (kit3d.check: textured meshes have sound UVs), `inspect` (render.py inspect close-ups looked at), `lod_kept` (lodcmp / lods_all: the part survives in each game version as its `lod` says) |
| `evidence` | TOOLS ONLY | per true flag: `{"tool", "at", "file", "ok"}`; plan_check opens `file` and confirms the part passed there |

A feature made IN another part (cooling slots cut into a kept housing, a pocket, an engraved seam) has no objects of
its own, so it cannot be a part. Plan it as a feature entry in the same `parts` list:

```json
{"part": "fins", "feature_of": "head", "how": "42 slots 3 x 81 mm cut into the kept lid over the LED bay, drafted, lip chamfer 1 mm",
 "lod": {"near": "keep", "mid": "normal map", "far": "drop"}}
```

| field | rule |
|---|---|
| `feature_of` | the part it is made in (a `part` of this plan). The entry then needs no `dims_m`, `host`, `material`, `states` or `checks`: the part it is cut into carries the flags, and kit3d writes nothing into the entry |
| `how` | how it is made in that part, with numbers |
| `lod` | `near`, `mid`, `far` fates as for a part (a cut usually becomes `normal map` or `drop`) |

When a planned part turns into a feature while building (the envelope leaves no room for it to stand proud), change
its entry to this form; never delete it from the plan.

Upgrading an existing asset: the kept objects join plan parts with `kit3d.adopt(obj, part)` (or `{name: part}`), then
get their relation (`root`, `into`, `attach`). Kept parts that only touch their host: `kit3d.seat()` moves each contact
3 mm into its host without changing the look and declares `into`; `kit3d.restore(obj, source.blend)` takes a kept mesh
back before a cut or a seat is redone (never reload kept objects by hand: the load brings copies of their materials). `bridge.py step` writes only plan parts into this file: an object that
kit3d did not make and nobody adopted fails the step as `unplaced` and is named on the step's `plan` line, never added
here as a part of its own. A part that IS built but missing from the plan is still added with `added_by: kit3d` and
fails plan_check as "built but not planned".

Tools write through `kit3d/plan.py` (`record()`, `set_flag(path, part, flag, ok, tool, file)`) with a lock and an
atomic replace. A flag set true by hand has no evidence and fails `plan_check.py`.

## Plan level: `needs`
`"needs": {"looks": [...], "versions": [...], "why": "..."}`: the looks (day/dawn/dusk/night/rain) and versions
(near/mid/far, `[]` = none) this subject's story calls for, decided first. `plan_check.py` asks
parts for exactly those; a plan without it is checked for night + near/mid/far.
