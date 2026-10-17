"""simplify.py: make a game version from the original by its ERROR IN PIXELS (or judge one that exists), not by
turning settings down until a triangle count fits. Headless Blender 5.2.

  blender -b ORIGINAL.blend --python simplify.py -- --high CAR --level far --into GAME_far --save WORK.blend
          [--family train|city-kit|building] [--px 2] [--dist M] [--budget 2100] [--exclude GLOBS]
          [--lock-from lodcmp.json --lock-label far] [--report OUT.json] [--keep-over]
  blender -b WORK.blend --python simplify.py -- --high CAR --level near --judge GAME_near [--budget 9600] [--report ..]

Method (owner via coordinator 2026-10-13, replacing "turn settings down until under the triangle count"):
1. TARGET = MAXIMUM ERROR. Each version's limit is --px (2) pixels at the CLOSEST distance the game shows it, with the
   game camera (vertical fov 40, 1080 rows: 1 px = d x 0.000674 m). Distances come from ONE file, scripts/switch.json
   (--family; per family the game's [low, full graphics] switch ranges and hysteresis, with the code they were read
   from): a version appears from the low end of its range minus the hysteresis. Trains (placements.json
   train.lodRanges near/mid [100, 240], mid/far [300, 720], hysteresis 8): near 7.5 m -> 1.0 cm (the owner's "about
   1 cm"), mid 92 m -> 12.4 cm, far 292 m -> 39 cm. City kit (the city kit KIT_LOD 24 / 70 / 6): 1.0, 2.4, 8.6 cm.
   --dist M overrides the distance for one run.
2. COLOUR-AWARE QUADRIC SIMPLIFICATION: meshoptimizer simplifyWithAttributes (zeux's official package, run in node;
   the PyPI 'meshoptimizer' is an unofficial 0.2 alpha sdist, not used) with flags ErrorAbsolute + Prune, attributes =
   vertex normal and the material's colour, MATERIAL BORDERS LOCKED (each material's vertices are split and locked
   where materials meet, so a stripe or a lamp edge never moves). The original's own UV seams are not locked: every
   version gets a fresh atlas (uvpack) and its look is baked, so old seams carry nothing; they stay seams to the
   simplifier (split vertices) and are kept consistent by it. --contact M locks vertices within M of another piece
   (off: measured, it does not stop mesh_integrity's floating bodies, which mostly come from the culling below; numbers
   in the code). Zero-area triangles are dropped. --cull-only writes the seen faces unsimplified (a diagnostic and a
   reference: what the culling alone does). Before simplifying, faces no outside view can reach are
   dropped (48 directions from each face, horizon down to -30 deg, glass counted opaque: the bake shows glass as a pane).
3. THE BUDGET IS A CEILING (--budget). When the error target needs more triangles the run STOPS (exit 3) and says
   "needs N for 2 px, budget B, over by X, mostly in <parts>"; it never cuts deeper silently. --keep-over still writes
   the collection (marked over budget) for a look.
4. A version built by a generator or by hand keeps its by-construction geometry: --judge COLL measures it with the
   same error and pixel check (exit 3 when it is over the error or the budget, with the places of the largest error).
5. PICTURE LOOP (lods_all.py drives it): render.py lodcmp --at-switch per version; regions it marks failed are given
   back with --lock-from lodcmp.json --lock-label <version>: vertices inside their boxes (grown by the target) are
   locked and the version is simplified again, at most 3 passes.
The meshopt error is its own estimate; the MEASURED distance decides: when it misses, the target handed to meshopt is
lowered (x0.7, x0.5) and then Prune is dropped, until the measured p99 is within the target (attempts in the report).
Error measured, both ways, on surface samples: original (visible faces) -> version and version -> original; the gate
is the 99th percentile of both (the max is reported: single samples on pruned specks or ambiguous nearest surfaces
would otherwise decide). Output collection --into (default GAME_<level>): '<into>.surface' (all but glass) and '<into>.glass' (glass
materials, or with --slots the materials whose game role is glass-*; a lamp lens stays on the surface), the original's
materials per face (bake.py --slots reads the roles from them), no UVs (run uvpack.py next). Writes --report
(default <blend dir>/simplify-<level>.json). Node tools: ~/.cache/3d-asset-kit/node (installed on first use).
"""
import argparse, json, math, os, sys, time, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _kit as K

ap = argparse.ArgumentParser(prog='simplify.py', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('--high', default=''); ap.add_argument('--level', required=True, choices=('near', 'mid', 'far'))
ap.add_argument('--into'); ap.add_argument('--save'); ap.add_argument('--judge')
ap.add_argument('--px', type=float, default=2.0); ap.add_argument('--dist', type=float)
ap.add_argument('--family'); ap.add_argument('--budget', type=int)
ap.add_argument('--exclude', default=''); ap.add_argument('--glass', default='*glass*'); ap.add_argument('--slots')
ap.add_argument('--lock-from'); ap.add_argument('--lock-label'); ap.add_argument('--report')
ap.add_argument('--keep-over', action='store_true'); ap.add_argument('--samples', type=int, default=30000)
ap.add_argument('--vis-cache'); ap.add_argument('--normal-weight', type=float, default=0.5); ap.add_argument('--color-weight', type=float, default=1.0)
ap.add_argument('--cull-only', action='store_true', help='diagnostic: write the seen faces of the original, not simplified')
ap.add_argument('--contact-mode', default='border', choices=('border', 'all'), help='lock contact vertices only on an open '
                'border of the seen surface (default), or every contact vertex')
ap.add_argument('--contact', type=float, help='lock vertices this close (m) to another connected piece (default 0 = off; '
                'measured on a car near: it does not prevent the floating bodies, see the docstring)')
ap.add_argument('--layers', default='auto', choices=('auto', 'off'), help='auto (default): a part LAID ON another surface and '
                'lower than --layer-k x the error target is not simplified as geometry: its outline is cut into the simplified '
                'surface under it and those triangles take its material (see LAYERS in the docstring). off = the old behaviour')
ap.add_argument('--layer-k', type=float, default=1.0, help='a laid-on part is a layer when 90 %% of it is within this x the error target of its base')
ap.add_argument('--layer-min-px', type=float, default=2.0, help='a layer smaller than this many px (square root of its seen area) is dropped, not cut in: the bake carries it')
ap.add_argument('--proud-k', type=float, default=3.0, help='a laid-on part of another slot that stands between --layer-k and this x the '
                'error target over its base is simplified at --proud-error x the target: thinner than the error it would fold. 0 = off')
ap.add_argument('--proud-error', type=float, default=0.3)
ap.add_argument('--joint-min', type=float, default=20.0, help='a joint is welded only between parts whose seen area is at least (this x the error target) squared')
ap.add_argument('--joint', type=float, default=None, help='lock open-border vertices this close (m) to the open border of ANOTHER '
                'piece (a closed joint between two sheets, e.g. nose to roof). Default 2 mm; 0 = off')
ap.add_argument('--on-top-samples', type=int, default=20000)
ap.add_argument('--coplanar', default='cut', choices=('cut', 'off'), help='cut (default): where two faces of the version lie IN one '
                'another (same plane within --coplanar-tol, same facing, overlapping: a reveal flange in the skin plane, hidden '
                'in the original under a part the version took away) the smaller triangle loses the common area, so the game '
                'draws each point once and nothing blinks (_coplanar.py). off = the old behaviour')
ap.add_argument('--coplanar-tol', type=float, default=3e-4)
A = ap.parse_args(K.script_argv())

import bpy, bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

T0 = time.time()
log = lambda *a: print('[simplify]', *a, flush=True)
SW = K.switch(A.family)                                               # scripts/switch.json: the one place
DIST = A.dist if A.dist is not None else SW['appears'][A.level]
M_PER_PX = 2 * math.tan(math.radians(SW['camera']['fov_deg']) / 2) / SW['camera']['rows']   # metres per px per metre
TARGET = A.px * DIST * M_PER_PX
log(f'{A.level}: {A.px:g} px at {DIST:g} m -> error target {TARGET * 100:.2f} cm')

# ------------------------------------------------------------------------------------------------ the original
high_colls = [bpy.data.collections.get(n) or K.die(f'no collection {n!r}') for n in K.csv(A.high)]
def _lcs(lc):
    yield lc
    for ch in lc.children: yield from _lcs(ch)
EXCL0 = {lc.name: lc.exclude for lc in _lcs(bpy.context.view_layer.layer_collection)}   # restored before --save
if high_colls: K.keep_only_collections(high_colls)
high_set = {o.name for c in high_colls for o in c.all_objects} if high_colls else None
judge_objs = set()
if A.judge:
    jo, _ = K.resolve(A.judge); judge_objs = {o.name for o in jo}
EXC = K.csv(A.exclude); GL = K.csv(A.glass)
dg = bpy.context.evaluated_depsgraph_get()
mat_names, mat_id, parts = [], {}, []
V, T, TM, TP = [], [], [], []           # vertices (world), triangles (vertex ids), triangle material id, part id
nv = 0
def mid(m):
    k = m.name if m else '-'
    if k not in mat_id: mat_id[k] = len(mat_names); mat_names.append(k)
    return mat_id[k]
for inst in dg.object_instances:
    ob = inst.object
    if ob.type != 'MESH': continue
    orig = ob.original
    top = inst.parent.original if inst.is_instance and inst.parent else orig
    if orig.name in judge_objs or top.name in judge_objs or top.name.startswith(('GAME_', 'KIT_')): continue
    if high_set is not None and top.name not in high_set and orig.name not in high_set: continue
    if orig.hide_render or top.hide_render: continue
    names = [n for n in (orig.name, top.name) if n]
    # an instanced collection is excluded by ITS name too, as export_original.py and bake.py do: a train car's
    # `--exclude C.saloon_liner` left the liner out of the original GLB but in every version (8 "floating" interior sheets
    # that the reference does not have: the last refusing gate of run proof1, 2026-10-13)
    if inst.is_instance and inst.parent and inst.parent.original.instance_type == 'COLLECTION' and inst.parent.original.instance_collection:
        names.append(inst.parent.original.instance_collection.name)
    if EXC and any(K.match(n, EXC) for n in names): continue
    me = ob.data; me.calc_loop_triangles()
    if not len(me.loop_triangles): continue
    co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
    mw = np.array(inst.matrix_world, np.float64)
    co = (co @ mw[:3, :3].T + mw[:3, 3]).astype(np.float32)
    lt = np.empty(len(me.loop_triangles) * 3, np.int32); me.loop_triangles.foreach_get('vertices', lt); lt = lt.reshape(-1, 3)
    mi = np.empty(len(me.loop_triangles), np.int32); me.loop_triangles.foreach_get('material_index', mi)
    if np.linalg.det(mw[:3, :3]) < 0: lt = lt[:, ::-1]
    slots = [mid(s.material) for s in ob.material_slots] or [mid(None)]
    V.append(co); T.append(lt + nv); TM.append(np.array(slots, np.int32)[np.clip(mi, 0, len(slots) - 1)])
    TP.append(np.full(len(lt), len(parts), np.int32)); parts.append(orig.name); nv += len(co)
if not V: K.die('nothing in the original: check --high / --exclude')
V = np.concatenate(V); T = np.concatenate(T); TM = np.concatenate(TM); TP = np.concatenate(TP)
diag = float(np.linalg.norm(V.max(0) - V.min(0)))
log(f'original: {len(parts)} parts, {len(T)} triangles, {len(mat_names)} materials, diagonal {diag:.2f} m')

def tri_geo(V_, T_):
    P = V_[T_]; N = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]); ar = np.linalg.norm(N, axis=1) / 2
    return P, N / np.maximum(2 * ar[:, None], 1e-12), ar
P, N, AR = tri_geo(V, T)
TREE = BVHTree.FromPolygons(V.tolist(), T.tolist(), epsilon=0.0)

# ------------------------------------------------------------------------------------------------ outside visibility
g = (1 + 5 ** 0.5) / 2
D = []
for i in range(96):
    z = 1 - 2 * (i + 0.5) / 96; r = math.sqrt(max(0, 1 - z * z)); a = 2 * math.pi * i / g
    if z >= -0.5: D.append(Vector((r * math.cos(a), r * math.sin(a), z)))
far_ = 2 * diag
def visible(t, tree=None):
    tree = tree or TREE
    c = P[t].mean(0); pts = [c] + ([P[t][k] * 0.8 + c * 0.2 for k in range(3)] if AR[t] > 0.0025 else [])
    n = Vector(N[t].tolist())
    for p in pts:
        pv = Vector(p.tolist())
        for d in D:
            s_ = 1.0 if d.dot(n) >= 0 else -1.0
            if tree.ray_cast(pv + n * (1e-4 * s_) + d * 1e-4, d, far_)[0] is None: return True
    return False
t1 = time.time()
import hashlib
VKEY = hashlib.sha1(V.tobytes() + T.tobytes() + repr(sorted(mat_names)).encode()).hexdigest()[:16]
VIS = None
if A.vis_cache and os.path.exists(A.vis_cache):
    zc = np.load(A.vis_cache)
    if str(zc['key']) == VKEY and len(zc['vis']) == len(T): VIS = zc['vis']; log(f'outside visibility from {A.vis_cache}')
if VIS is None:
    VIS = np.array([visible(t) for t in range(len(T))])
    if A.vis_cache: np.savez(A.vis_cache, key=VKEY, vis=VIS)
log(f'outside visibility: {VIS.sum()} of {len(T)} triangles seen ({VIS.mean():.0%}), {time.time() - t1:.0f} s, {len(D)} directions')
VT = np.where(VIS)[0]
VTREE = BVHTree.FromPolygons(V.tolist(), T[VT].tolist(), epsilon=0.0)
MTREE = [VTREE]      # what "version -> original" is measured against (the seen faces, plus bases uncovered under layers)
FULLTREE = BVHTree.FromPolygons(V.tolist(), T.tolist(), epsilon=0.0)   # a version face lying on a HIDDEN original face is no error (2026-10-13 an old-TV prop: an exact copy of the original failed at 1.5 cm)

def samples(P_, AR_, n, seed):
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(P_), size=n, p=AR_ / AR_.sum())
    a, b = rng.random(n), rng.random(n); f = a + b > 1; a[f], b[f] = 1 - a[f], 1 - b[f]
    return P_[pick, 0] * (1 - a - b)[:, None] + P_[pick, 1] * a[:, None] + P_[pick, 2] * b[:, None], pick

def measure(LV, LT):
    """Surface distance both ways: original's visible faces -> version and version -> original's visible faces."""
    ltree = BVHTree.FromPolygons(LV.tolist(), LT.tolist(), epsilon=0.0)
    LP, LN_, LAR = tri_geo(LV, LT)
    so, po = samples(P[VT], AR[VT], A.samples, 1)
    sl, _ = samples(LP, LAR, A.samples, 2)
    d_ov = np.array([ltree.find_nearest(Vector(p.tolist()))[3] or 0.0 for p in so])
    d_vo = np.array([min(MTREE[0].find_nearest(Vector(p.tolist()))[3] or 0.0, FULLTREE.find_nearest(Vector(p.tolist()))[3] or 0.0) for p in sl])
    st = lambda d: dict(p50=round(float(np.percentile(d, 50)), 4), p95=round(float(np.percentile(d, 95)), 4),
                        p99=round(float(np.percentile(d, 99)), 4), max=round(float(d.max()), 4))
    worst = np.argsort(-d_ov)[:max(1, len(d_ov) // 200)]          # the worst 0.5 % of original samples, by part
    where = {}
    for i in worst:
        nm = parts[TP[VT[po[i]]]]; w_ = where.setdefault(nm, [0, 0.0, None]); w_[0] += 1
        if d_ov[i] > w_[1]: w_[1] = float(d_ov[i]); w_[2] = [round(float(x), 2) for x in so[i]]
    places = sorted(([nm, c, round(dm, 4), at] for nm, (c, dm, at) in where.items()), key=lambda x: -x[1])[:8]
    wv = np.argsort(-d_vo)[:3]   # the version's own worst places (it was silent: the list named original parts only)
    places += [['version', 1, round(float(d_vo[i]), 4), [round(float(x), 2) for x in sl[i]]] for i in wv if d_vo[i] > 0.5 * DIST * M_PER_PX]
    e99 = max(np.percentile(d_ov, 99), np.percentile(d_vo, 99))
    return dict(original_to_version=st(d_ov), version_to_original=st(d_vo), error_p99_m=round(float(e99), 4),
                error_p99_px=round(float(e99 / (DIST * M_PER_PX)), 2), worst_places=places)

report = dict(tool='3d-asset-making/scripts/simplify.py', when=time.strftime('%Y-%m-%d %H:%M:%S %z'), source=bpy.data.filepath,
              level=A.level, px=A.px, distance_m=DIST, m_per_px_at_distance=round(DIST * M_PER_PX, 5), target_m=round(TARGET, 4),
              family=SW['family'], switch=dict(near_mid=SW['near_mid'], mid_far=SW['mid_far'], hysteresis=SW['hysteresis'],
              source=SW['source']), budget=A.budget, original=dict(parts=len(parts), triangles=int(len(T)),
              visible_triangles=int(VIS.sum()), materials=len(mat_names)))
rp = A.report or os.path.join(os.path.dirname(bpy.data.filepath) or '.', f'simplify-{A.level}.json')
def finish(code, msg):
    report.update(seconds=round(time.time() - T0, 1), verdict=msg, exit=code)
    with open(rp, 'w') as f: json.dump(report, f, indent=1)
    log(msg); log('report', rp); sys.exit(code)

# ------------------------------------------------------------------------------------------------ judge mode
if A.judge:
    jo, _ = K.resolve(A.judge); LV, LT = [], []; n0 = 0
    for o in jo:
        if o.type != 'MESH': continue
        me = o.evaluated_get(dg).to_mesh(); me.calc_loop_triangles()
        co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
        mw = np.array(o.matrix_world, np.float64); co = co @ mw[:3, :3].T + mw[:3, 3]
        lt = np.empty(len(me.loop_triangles) * 3, np.int32); me.loop_triangles.foreach_get('vertices', lt)
        LV.append(co); LT.append(lt.reshape(-1, 3) + n0); n0 += len(co); o.evaluated_get(dg).to_mesh_clear()
    LV = np.concatenate(LV).astype(np.float32); LT = np.concatenate(LT)
    m = measure(LV, LT); report.update(mode='judge', version=A.judge, triangles=int(len(LT)), error=m)
    over_err = m['error_p99_m'] > TARGET; over_b = A.budget is not None and len(LT) > A.budget
    msg = (f'{A.judge}: {len(LT)} triangles, error p99 {m["error_p99_m"] * 100:.2f} cm = {m["error_p99_px"]} px at {DIST:g} m '
           f'(target {TARGET * 100:.2f} cm = {A.px:g} px)' + (f', budget {A.budget}' if A.budget else ''))
    if over_err: msg += f'; OVER THE ERROR: largest at {m["worst_places"][:4]}'
    if over_b: msg += f'; OVER THE BUDGET by {len(LT) - A.budget}'
    finish(3 if (over_err or over_b) else 0, ('FAIL ' if (over_err or over_b) else 'ok ') + msg)


# ------------------------------------------------------------------------------------------------ laid-on layers
# LAYERS (2026-10-13, a train car's stripe). A part laid on a surface and LOWER than the error target cannot stay
# a separate surface in this version: the simplifier may move the base by the whole target, so the base comes through
# the layer (measured on a test run near, target 10.1 mm: stripe band 1.5-7.5 mm over the skin, 5 % of it covered by skin;
# window surrounds 17 % covered and 22 % folded away). Such a part is taken OUT of the simplifier input; the base under
# it (hidden until now, so culled) is put back; after simplifying, the layer's outline is cut into the base triangles
# and the triangles under it take the layer's material. The material name (= the game slot) stays live on near and
# mid; the layer's relief and fine colour go to the normal map and the bake. A part is a layer when: 90 % of its seen
# surface is within --layer-k x target of ANOTHER part, the surface under it faces the same way (an outside surface,
# not a liner behind the skin), that base part is bigger than it, and it is neither glass nor a lamp (lamps keep their
# geometry, the contract needs them on every version). A layer smaller than --layer-min-px px is dropped (the bake has it).
TPV = TP[VT]; AREA_P = np.bincount(TP, AR, minlength=len(parts)); AREA_PV = np.bincount(TPV, AR[VT], minlength=len(parts))
LAYER = np.zeros(len(parts), bool); IMPR = np.zeros(len(parts), bool); layer_rows = []
RID = np.arange(len(mat_names))               # per material: the id of its game slot
UNC = np.zeros(len(T), bool); IMPT = np.zeros(len(T), bool)       # IMPT: layer triangles that are cut in
R_LAY = A.layer_k * TARGET; R_PROUD = max(A.proud_k, A.layer_k) * TARGET; PROUD = np.zeros(len(parts), bool)
if A.layers == 'auto' and not A.cull_only:
    t2 = time.time()
    _SLn = K.load_slots(A.slots) if A.slots else None
    def _never(n):
        if _SLn is not None:
            r_ = K.slot_role(n, _SLn, A.level) or ''
            return 'glass-' in r_ or 'LED-' in r_
        m_ = bpy.data.materials.get(n)
        return bool(K.match(n, GL) or (m_ is not None and m_.node_tree and any(K.is_glass_principled(x) for x in m_.node_tree.nodes if x.type == 'BSDF_PRINCIPLED')))
    NEVER = np.array([_never(n) for n in mat_names])
    # what the game can tell apart: the slot (role) a material goes to; every unmapped material shares the one '.baked'
    # slot, whose colour is baked from the original whatever the triangle under it is. Without --slots: the material.
    _rl = [((K.slot_role(n, _SLn, A.level) or '~baked') if _SLn is not None else n) for n in mat_names]
    RID[:] = np.unique(_rl, return_inverse=True)[1]
    never_part = np.zeros(len(parts), bool); never_part[np.unique(TP[NEVER[TM]])] = True
    order = np.argsort(TPV, kind='stable'); bounds = np.searchsorted(TPV[order], np.arange(len(parts) + 1))
    rng = np.random.default_rng(7); base_of = {}
    for pi in range(len(parts)):
        tv = VT[order[bounds[pi]:bounds[pi + 1]]]
        if not len(tv) or never_part[pi]: continue
        NS = 60; pk = tv[rng.choice(len(tv), size=NS, p=AR[tv] / AR[tv].sum())]
        a_, b_ = rng.random(NS), rng.random(NS); f_ = a_ + b_ > 1; a_[f_], b_[f_] = 1 - a_[f_], 1 - b_[f_]
        sp = P[pk, 0] * (1 - a_ - b_)[:, None] + P[pk, 1] * a_[:, None] + P[pk, 2] * b_[:, None]
        hs = []; far_n = 0; far3 = 0; below = 0; bases = {}; other = 0
        for i_ in range(NS):
            # what it lies on, and how high: six rays from the sample (in and out along its normal: a train car's
            # stripe beads are inside out; and four along the surface: a side wall's base is beside it), each to the
            # first face of ANOTHER part that faces the ray; the nearest of the six. (A range search around the sample
            # returns every triangle within reach: minutes per version at the mid and far targets.)
            sv = Vector(sp[i_].tolist()); nn = N[pk[i_]].astype(np.float64); base = None
            t1_ = np.cross(nn, (1.0, 0, 0) if abs(nn[0]) < 0.9 else (0, 1.0, 0)); t1_ /= max(np.linalg.norm(t1_), 1e-12); t2_ = np.cross(nn, t1_)
            for dv in (-nn, nn, t1_, -t1_, t2_, -t2_):
                d_ = Vector(dv.tolist()); cur = sv + d_ * 1e-6; left = R_PROUD if base is None else min(R_PROUD, base[0])
                for _ in range(6):
                    h = TREE.ray_cast(cur, d_, left)
                    if h[0] is None: break
                    ti = h[2]; dist_ = (h[0] - sv).length
                    if TP[ti] != pi and float(N[ti] @ dv) < -0.3:
                        if base is None or dist_ < base[0]: base = (dist_, ti)
                        break
                    cur = h[0] + d_ * 1e-6; left = (R_PROUD if base is None else min(R_PROUD, base[0])) - dist_
                    if left <= 0: break
            if base is None: far3 += 1
            if base is None or base[0] > R_LAY: far_n += 1
            else: hs.append(base[0])
            if far3 > NS * 0.15: break                   # stands higher than 3 x the target: plain geometry
            if base is not None and not NEVER[TM[base[1]]]:
                below += 1; bp = int(TP[base[1]]); bases[bp] = bases.get(bp, 0) + 1; other += int(RID[TM[base[1]]] != RID[TM[pk[i_]]])
        if os.environ.get('LAYER_DEBUG') and K.match(parts[pi], K.csv(os.environ['LAYER_DEBUG'])):
            log('  debug', parts[pi], dict(far=far_n, far3=far3, below=below, other=other, hits=len(hs), base=parts[max(bases, key=bases.get)] if bases else None))
        if far3 > NS * 0.15 or below < 0.5 * NS: continue    # laid ON a surface: under most of it another part faces it
        if other < 0.75 * below: continue    # on a base of its own slot: a poke-through cannot be told apart, it stays geometry
        if far_n > NS * 0.15:                # higher than the target (up to 3 x): it stays geometry, simplified finer (see PROUD)
            if A.proud_k > 0 and AREA_P[max(bases, key=bases.get)] > AREA_P[pi]: PROUD[pi] = True
            continue
        base_of[pi] = (max(bases, key=bases.get), float(np.percentile(hs, 90)) if hs else 0.0)
    # a layer's base must be bigger than it (no two parts are each other's layer)
    for pi, (bp, h90) in base_of.items():
        if AREA_P[bp] > AREA_P[pi]: LAYER[pi] = True
    min_side = A.layer_min_px * DIST * M_PER_PX
    # connected pieces of the layer parts (a row of rivets is one part, many pieces): a piece smaller than
    # --layer-min-px px is not cut in
    lt_ = np.where(LAYER[TP])[0]
    if len(lt_):
        lab = np.arange(len(V)); Tl = T[lt_]
        for _ in range(500):
            m_ = np.minimum(np.minimum(lab[Tl[:, 0]], lab[Tl[:, 1]]), lab[Tl[:, 2]]); new = lab.copy()
            for k in range(3): np.minimum.at(new, Tl[:, k], m_)
            new = new[new]
            if np.array_equal(new, lab): break
            lab = new
        cl = lab[T[lt_, 0]]; carea = np.bincount(cl, AR[lt_] * VIS[lt_], minlength=len(V))
        # ... and narrower than 0.75 px (seen area / its longest extent) is not cut in either: a 5 mm plate border, lettering.
        # (A long line under 1 px wide still shows: a train car's 16 cm stripe is 0.8 px at the far distance.)
        cen_ = P[lt_].mean(1); ucl, icl = np.unique(cl, return_inverse=True); cdiag = np.zeros(len(V))
        lo_ = np.full((len(ucl), 3), 1e9); hi_ = np.full((len(ucl), 3), -1e9)
        np.minimum.at(lo_, icl, P[lt_].min(1)); np.maximum.at(hi_, icl, P[lt_].max(1)); cdiag[ucl] = np.linalg.norm(hi_ - lo_, axis=1)
        IMPT[lt_] = (carea[cl] >= min_side ** 2) & (carea[cl] >= 0.75 * DIST * M_PER_PX * cdiag[cl])
    for pi in np.where(LAYER)[0]:
        IMPR[pi] = bool(IMPT[TP == pi].any())
        layer_rows.append(dict(part=parts[pi], base=parts[base_of[pi][0]], height_p90_mm=round(base_of[pi][1] * 1000, 1),
                               seen_area_m2=round(float(AREA_PV[pi]), 4), cut_in=bool(IMPR[pi])))
    lay_t = LAYER[TP]
    if lay_t.any():
        BT = np.where(~lay_t)[0]; BTREE = BVHTree.FromPolygons(V.tolist(), T[BT].tolist(), epsilon=0.0)
        LAYT = np.where(lay_t)[0]; LAYTREE = BVHTree.FromPolygons(V.tolist(), T[LAYT].tolist(), epsilon=0.0)
        # bases hidden only by a layer come back: unseen, not a layer, a layer face within reach, seen once layers are gone
        cen = P.mean(1)
        for t in np.where(~VIS & ~lay_t)[0]:
            if LAYTREE.find_nearest(Vector(cen[t].tolist()), 2 * R_LAY + 0.002)[0] is None: continue
            if visible(t, BTREE): UNC[t] = True
        MTREE[0] = BVHTree.FromPolygons(V.tolist(), T[np.where(VIS | UNC)[0]].tolist(), epsilon=0.0)
    by_name = {}
    for r_ in layer_rows:
        k_ = r_['part'].split('.')[0] + ('' if r_['cut_in'] else ' (dropped: under %g px)' % A.layer_min_px); by_name[k_] = by_name.get(k_, 0) + 1
    log(f'layers: {int(LAYER.sum())} of {len(parts)} parts are laid on a surface and lower than {R_LAY * 1000:.1f} mm '
        f'({int(IMPR.sum())} cut into their base, {int(lay_t.sum())} triangles leave the simplifier, {int(UNC.sum())} hidden base '
        f'triangles come back), {time.time() - t2:.0f} s: ' + ', '.join(f'{k_} x{v_}' for k_, v_ in sorted(by_name.items(), key=lambda x: -x[1])[:14]))
report['layers'] = dict(mode=A.layers, k=A.layer_k, reach_m=round(R_LAY, 5), parts=int(LAYER.sum()), cut_in=int(IMPR.sum()),
                        base_triangles_back=int(UNC.sum()), rows=sorted(layer_rows, key=lambda r: -r['seen_area_m2'])[:200])
ST = np.where((VIS | UNC) & ~LAYER[TP])[0]            # what the simplifier gets

def on_top(LV_, LT_, LM_):
    """What the version shows where the original shows material M, looking in along the original's normal (only samples
    that ARE on top in the original): right = a triangle of the same GAME SLOT (role; the material without --slots) is
    the first thing met. Per material of the original."""
    vt = BVHTree.FromPolygons(LV_.tolist(), LT_.tolist(), epsilon=0.0)
    so, po = samples(P[VT], AR[VT], A.on_top_samples, 5); reach = 3 * TARGET; res = {}
    for p_, i_ in zip(so, po):
        t = VT[i_]; n = Vector(N[t].tolist()); o = Vector(p_.tolist()) + n * reach
        h0 = TREE.ray_cast(o, -n, 2 * reach)
        if h0[0] is None or RID[TM[h0[2]]] != RID[TM[t]]: continue
        r_ = res.setdefault(int(TM[t]), [0, 0]); r_[0] += 1
        h1 = vt.ray_cast(o, -n, 2 * reach)
        if h1[0] is not None and RID[LM_[h1[2]]] == RID[TM[t]]: r_[1] += 1
    rows = {mat_names[k_]: dict(samples=n_, right=round(ok_ / n_, 4)) for k_, (n_, ok_) in res.items() if n_ >= 20}
    tot = sum(v_[0] for v_ in res.values()) or 1
    return dict(right=round(sum(v_[1] for v_ in res.values()) / tot, 4), by_material=rows,
                worst=sorted(((k_, v_['right'], v_['samples']) for k_, v_ in rows.items()), key=lambda x: x[1])[:6])

# ------------------------------------------------------------------------------------------------ cut the layers in
def imprint(LV, LT, LM, LPart):
    """Cut each layer's outline into the simplified base and give the triangles under it the layer's material.
    Works on welded positions, so both sides of a material seam are split at the same point (no T-junction)."""
    t2 = time.time()
    it = np.where(IMPT)[0]

    ITREE = BVHTree.FromPolygons(V.tolist(), T[it].tolist(), epsilon=0.0); imat = TM[it]
    R1 = 1.2 * TARGET; R2 = 1.2 * TARGET + R_LAY; LMIN = TARGET
    _, wid = np.unique(np.round(LV.astype(np.float64) / 1e-5).astype(np.int64), axis=0, return_inverse=True); wid = wid.ravel()
    nw = int(wid.max()) + 1
    WP = np.zeros((nw, 3)); WP[wid] = LV
    Pt = LV[LT].astype(np.float64); fn = np.cross(Pt[:, 1] - Pt[:, 0], Pt[:, 2] - Pt[:, 0])
    WN = np.zeros((nw, 3))
    for k in range(3): np.add.at(WN, wid[LT[:, k]], fn)
    WN /= np.maximum(np.linalg.norm(WN, axis=1, keepdims=True), 1e-20)
    WP = [tuple(x) for x in WP]; WN = [tuple(x) for x in WN]            # grow as lists
    LVl = [tuple(x) for x in LV.astype(np.float64)]; widl = wid.tolist()
    tris = LT.tolist(); tmat = LM.tolist(); tpart = LPart.tolist(); tmat0 = LM.tolist()
    def cover(p, n):
        """material id of the OUTERMOST layer face over p (looking out along n), -1 = none. Below p the search stops
        at the back of the wall p is on, so a layer on the other side of a thin wall is not taken."""
        pv = Vector(p); nv_ = Vector(n); lim = R1; cur = pv; left = R1
        for _ in range(4):
            h = BTREE.ray_cast(cur, -nv_, left)
            if h[0] is None: break
            if float(N[BT[h[2]]] @ np.array(n)) < -0.3: lim = (h[0] - pv).length; break
            adv = (h[0] - cur).length + 1e-6; cur = h[0] - nv_ * 1e-6; left -= adv
            if left <= 0: break
        cur = pv - nv_ * lim; left = lim + R2; last = -1
        for _ in range(12):
            h = ITREE.ray_cast(cur, nv_, left)
            if h[0] is None: break
            last = h[2]; adv = (h[0] - cur).length + 1e-6; cur = h[0] + nv_ * 1e-6; left -= adv
            if left <= 0: break
        if last >= 0: last_part[0] = int(TP[it[last]])
        return -1 if last < 0 else int(imat[last])
    last_part = [-1]; tally = {}
    cv = {}                                    # weld id -> cover
    def cov_w(w):
        c = cv.get(w)
        if c is None: c = cv[w] = cover(WP[w], WN[w])
        return c
    def lerp(a, b, t_):
        p = tuple(WP[a][k] + (WP[b][k] - WP[a][k]) * t_ for k in range(3))
        n = [WN[a][k] + (WN[b][k] - WN[a][k]) * t_ for k in range(3)]; l_ = math.sqrt(sum(x * x for x in n)) or 1.0
        return p, tuple(x / l_ for x in n)
    def elen(a, b): return math.dist(WP[a], WP[b])
    # the zone: version triangles a layer lies over (samples on the layers' seen faces, nearest version triangle)
    vtree = BVHTree.FromPolygons([list(x) for x in LVl], tris, epsilon=0.0)
    iv = it[VIS[it]]
    if not len(iv): iv = it
    ns = int(min(400000, max(2000, AR[iv].sum() / (0.5 * TARGET) ** 2)))
    sp, _ = samples(P[iv], AR[iv], ns, 9)
    zone = set()
    for p_ in sp:
        h = vtree.find_nearest(Vector(p_.tolist()), R1 + R2)
        if h[0] is not None: zone.add(h[2])
    zone = [i in zone for i in range(len(tris))]
    def tri_area(i, j, k):
        a_, b_, c_ = LVl[i], LVl[j], LVl[k]
        u = (b_[0] - a_[0], b_[1] - a_[1], b_[2] - a_[2]); v = (c_[0] - a_[0], c_[1] - a_[1], c_[2] - a_[2])
        return 0.5 * math.sqrt((u[1] * v[2] - u[2] * v[1]) ** 2 + (u[2] * v[0] - u[0] * v[2]) ** 2 + (u[0] * v[1] - u[1] * v[0]) ** 2)
    def ears(poly):
        """a convex polygon that may have points in line: clip the best-shaped ear until three are left"""
        poly = list(poly); out = []
        while len(poly) > 3:
            best = None
            for i in range(len(poly)):
                a_, b_, c_ = poly[i - 1], poly[i], poly[(i + 1) % len(poly)]; ar = tri_area(a_, b_, c_)
                q = ar / (math.dist(LVl[a_], LVl[c_]) ** 2 + 1e-18)
                if best is None or q > best[0]: best = (q, i, ar)
            if best[2] <= 1e-12: return out                       # everything left is in one line
            i = best[1]; out.append((poly[i - 1], poly[i], poly[(i + 1) % len(poly)])); poly.pop(i)
        if tri_area(*poly) > 1e-12: out.append(tuple(poly))
        return out
    def split_all(marks):
        """marks: {(wa, wb) with wa < wb: sorted [t along wa -> wb]}. Every zone triangle with marked edges is cut:
        each stretch of its rim between two marks that holds a corner is cut off along the chord between those marks
        (a stripe crossing a triangle leaves corner piece, stripe quad, far piece), the middle is triangulated."""
        nonlocal tris, tmat, tpart, zone, tmat0
        newv = {}; neww = {}
        def edge_pts(i, j):
            a, b = widl[i], widl[j]; kk = (a, b) if a < b else (b, a); ts = marks.get(kk)
            if not ts: return []
            out = []
            for t_ in (ts if a < b else ts[::-1]):
                wk = (kk, t_)
                if wk not in neww:
                    p, n = lerp(kk[0], kk[1], t_); neww[wk] = len(WP); WP.append(p); WN.append(n)
                vk = ((i, j) if i < j else (j, i), t_)
                if vk not in newv:
                    newv[vk] = len(LVl); LVl.append(WP[neww[wk]]); widl.append(neww[wk])
                out.append(newv[vk])
            return out
        nt, nm, npart, nz, nm0 = [], [], [], [], []
        for ti, (a, b, c) in enumerate(tris):
            sub = None
            if zone[ti]:
                e = [edge_pts(a, b), edge_pts(b, c), edge_pts(c, a)]; nx = len(e[0]) + len(e[1]) + len(e[2])
                if nx:
                    ring = [(a, True)] + [(x, False) for x in e[0]] + [(b, True)] + [(x, False) for x in e[1]] + [(c, True)] + [(x, False) for x in e[2]]
                    if nx == 1:
                        ix = next(i for i, r_ in enumerate(ring) if not r_[1]); x = ring[ix][0]
                        rest = [r_[0] for r_ in ring[ix + 1:] + ring[:ix]]            # the three corners, in order
                        sub = [(x, rest[0], rest[1]), (x, rest[1], rest[2])]
                    else:
                        xi = [i for i, r_ in enumerate(ring) if not r_[1]]; sub = []; core = []; n_ = len(ring)
                        for q, i0 in enumerate(xi):
                            i1 = xi[(q + 1) % len(xi)]; run = []; i = i0
                            while True:
                                run.append(ring[i][0])
                                if i == i1 and len(run) > 1: break
                                i = (i + 1) % n_
                            core.append(ring[i0][0])
                            if len(run) > 2: sub += ears(run)                           # a corner piece
                        if len(core) > 2: sub += ears(core)
                        sub = [s_ for s_ in sub if tri_area(*s_) > 1e-12]
            if sub is None:
                nt.append((a, b, c)); nm.append(tmat[ti]); npart.append(tpart[ti]); nz.append(zone[ti]); nm0.append(tmat0[ti]); continue
            for s_ in sub: nt.append(tuple(s_)); nm.append(tmat[ti]); npart.append(tpart[ti]); nz.append(True); nm0.append(tmat0[ti])
        tris, tmat, tpart, zone, tmat0 = nt, nm, npart, nz, nm0
    def eff(vals, own):                    # what the game would tell apart: the slot over the point, the triangle's own where bare
        o_ = int(RID[own]); return [int(RID[v]) if v >= 0 else o_ for v in vals]
    scan_cache = {}
    def scan(a, b):
        """cover at steps of LMIN along a welded edge (a < b) -> (values, ts)"""
        kk = (a, b)
        if kk not in scan_cache:
            L = elen(a, b); k_ = int(min(256, max(1, math.ceil(L / LMIN))))
            ts = [i / k_ for i in range(k_ + 1)]; vals = [cov_w(a)] + [cover(*lerp(a, b, t_)) for t_ in ts[1:-1]] + [cov_w(b)]
            scan_cache[kk] = (vals, ts)
        return scan_cache[kk]
    cross_cache = {}
    def crossings(kk, own):
        """where the slot changes along welded edge kk for a triangle of material own: sorted [t]"""
        ck = (kk, int(RID[own]))
        if ck in cross_cache: return cross_cache[ck]
        vals, ts = scan(*kk); ev = eff(vals, own); L = elen(*kk); out = []
        if L < 0.002: cross_cache[ck] = out; return out         # an edge under 2 mm is not cut: its triangle takes the majority's slot
        for i in range(len(ev) - 1):
            if ev[i] == ev[i + 1]: continue
            lo, hi = ts[i], ts[i + 1]
            for _ in range(10):
                mt = (lo + hi) / 2
                if eff([cover(*lerp(kk[0], kk[1], mt))], own)[0] == ev[i]: lo = mt
                else: hi = mt
            t_ = (lo + hi) / 2
            if min(t_, 1 - t_) * L > max(0.0005, 0.02 * L) and (not out or (t_ - out[-1]) * L > 0.0005): out.append(t_)
        cross_cache[ck] = out; return out
    rounds = 0
    for rounds in range(1, 7):
        marks = {}
        for ti, (a, b, c) in enumerate(tris):
            if not zone[ti]: continue
            w = (widl[a], widl[b], widl[c])
            if len(set(w)) < 3: continue
            es = [(w[0], w[1]) if w[0] < w[1] else (w[1], w[0]), (w[1], w[2]) if w[1] < w[2] else (w[2], w[1]), (w[2], w[0]) if w[2] < w[0] else (w[0], w[2])]
            got = False
            for kk in es:
                cr = crossings(kk, tmat[ti])
                if cr:
                    got = True
                    if kk not in marks or len(cr) > len(marks[kk]): marks[kk] = cr
            if not got:
                ls = [elen(*kk) for kk in es]
                if max(ls) > 2 * LMIN:                               # an outline wholly inside the triangle?
                    c0 = eff([cov_w(w[0])], tmat[ti])[0]; g = int(min(8, max(3, math.ceil(max(ls) / (2 * LMIN))))); inside = False
                    for i in range(1, g):
                        for j in range(1, g - i):
                            u_, v_ = i / g, j / g; w_ = 1 - u_ - v_
                            p = tuple(WP[w[0]][k] * w_ + WP[w[1]][k] * u_ + WP[w[2]][k] * v_ for k in range(3))
                            n = [WN[w[0]][k] * w_ + WN[w[1]][k] * u_ + WN[w[2]][k] * v_ for k in range(3)]; l_ = math.sqrt(sum(x * x for x in n)) or 1.0
                            if eff([cover(p, tuple(x / l_ for x in n))], tmat[ti])[0] != c0: inside = True; break
                        if inside: break
                    if inside:
                        kk = es[int(np.argmax(ls))]; marks.setdefault(kk, [0.5])
        if not marks: break
        split_all(marks); scan_cache.clear(); cross_cache.clear()
    # materials: what lies over each zone triangle (centre and three points towards the corners, majority)
    n_tag = 0
    for ti, (a, b, c) in enumerate(tris):
        if not zone[ti]: continue
        w = (widl[a], widl[b], widl[c]); votes = {}
        for wa, wb, wc in ((1 / 3, 1 / 3, 1 / 3), (0.6, 0.2, 0.2), (0.2, 0.6, 0.2), (0.2, 0.2, 0.6)):
            p = tuple(WP[w[0]][k] * wa + WP[w[1]][k] * wb + WP[w[2]][k] * wc for k in range(3))
            n = [WN[w[0]][k] * wa + WN[w[1]][k] * wb + WN[w[2]][k] * wc for k in range(3)]; l_ = math.sqrt(sum(x * x for x in n)) or 1.0
            cc = cover(p, tuple(x / l_ for x in n)); votes[cc] = votes.get(cc, 0) + (1.5 if wa == 1 / 3 else 1)
        best_ = max(votes, key=votes.get)
        if best_ >= 0 and RID[best_] != RID[tmat[ti]]:
            tmat[ti] = best_; n_tag += 1; nm_ = parts[last_part[0]].split('.')[0] if last_part[0] >= 0 else '?'; tally[nm_] = tally.get(nm_, 0) + 1
    LV2 = np.array(LVl, np.float32); LT2 = np.array(tris, np.int32)
    q_ = LV2[LT2]; ar_ = np.linalg.norm(np.cross(q_[:, 1] - q_[:, 0], q_[:, 2] - q_[:, 0]), axis=1) / 2
    ok_ = ar_ > 1e-10
    info = dict(triangles_before=int(len(LT)), triangles_after=int(ok_.sum()), retagged=n_tag, zone_triangles=int(sum(zone)),
                refine_rounds=rounds, seconds=round(time.time() - t2, 1),
                retagged_by_layer=dict(sorted(tally.items(), key=lambda x: -x[1])[:20]))
    return LV2, LT2[ok_], np.array(tmat, LM.dtype)[ok_], np.array(tpart, LPart.dtype)[ok_], info, np.array(tmat0, LM.dtype)[ok_]

# The cut is made BEFORE simplifying, on the original's own triangles: the outline becomes a seam between two materials
# (not locked: only borders the original has are locked), and meshoptimizer then simplifies along it like any other
# seam. (Cutting the simplified base instead made 2-5 new triangles for every base triangle an outline crossed: near
# went from 31 787 to 64 617.)
S_T = T[ST]; S_M = TM[ST]; S_P = TP[ST]; S_M0 = S_M.copy(); NV0 = len(V)
if IMPT.any():
    V2, S_T, S_M, S_P, imp_info, S_M0 = imprint(V, S_T.astype(np.int32), S_M, S_P)
    V = V2; report['layers']['imprint'] = imp_info
    log(f'layers cut in: {imp_info["triangles_before"]} -> {imp_info["triangles_after"]} triangles before simplifying, {imp_info["retagged"]} took a '
        f'layer\'s material, {imp_info["refine_rounds"]} rounds, {imp_info["seconds"]} s; by layer {imp_info["retagged_by_layer"]}')
_, S_N, S_AR = tri_geo(V, S_T)
# ------------------------------------------------------------------------------------------------ build the simplifier input
# visible triangles only (less the layers, plus the bases under them); one vertex per (original vertex, material) so
# material regions are separate index islands
VTi = S_T; VM = S_M
key = VTi.astype(np.int64) * len(mat_names) + VM[:, None]
uk, inv = np.unique(key.ravel(), return_inverse=True)
IDX = inv.reshape(-1, 3).astype(np.uint32)
src_v = (uk // len(mat_names)).astype(np.int64); src_m = (uk % len(mat_names)).astype(np.int32)
POS = V[src_v].astype(np.float32)
vn = np.zeros((len(uk), 3), np.float64)
for k in range(3): np.add.at(vn, IDX[:, k], S_N * S_AR[:, None])
vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)
def mat_colour(nm):
    m = bpy.data.materials.get(nm)
    if m and m.node_tree:
        p = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if p is not None and not p.inputs['Base Color'].is_linked: return list(p.inputs['Base Color'].default_value)[:3]
    return list(m.diffuse_color)[:3] if m else [0.5, 0.5, 0.5]
MC = np.array([mat_colour(n) for n in mat_names], np.float32)
vpart = np.zeros(len(V), np.int32)
for k in range(3): vpart[T[:, k]] = TP
for k in range(3): vpart[S_T[:, k]] = S_P
ATTR = np.concatenate([vn.astype(np.float32), MC[src_m]], 1).astype(np.float32)
# lock: vertices whose original vertex carries more than one material (a material border)
_k0 = np.unique(S_T.astype(np.int64).ravel() * len(mat_names) + np.repeat(S_M0, 3))
cnt = np.bincount(_k0 // len(mat_names), minlength=len(V)); LOCK = (cnt[src_v] > 1).astype(np.uint8)
# lamps: with --slots, every vertex of a material whose game role is LED-ivory is locked. The game lights that slot at
# night and the contract requires it on every version; a test run far (39 cm target) pruned every lamp face (export refused:
# LED-ivory missing). Lamps are a few dozen triangles.
n_lamp = 0
if A.slots:
    _SLl = K.load_slots(A.slots)
    lampm = np.array(['LED-ivory' in (K.slot_role(n, _SLl, A.level) or '') for n in mat_names])
    if lampm.any():
        lv_ = lampm[src_m] & (LOCK == 0); n_lamp = int(lv_.sum()); LOCK[lv_] = 1
# PROUD: laid-on parts of another slot standing 1-3 x the target over their base (a train car's chrome nose whiskers,
# 6-25 mm at a 10 mm target: a test run near folded or covered a quarter of them) are simplified on their own at
# --proud-error x the target (0.3): a part thinner than the error has no shape left at the full error. (Locking every
# vertex of them instead cost near 14 000 triangles.)
if PROUD.any():
    report['layers']['proud'] = sorted({parts[i] for i in np.where(PROUD)[0]})[:80]
    log(f'proud parts simplified at {A.proud_error:g} x the target: {int(PROUD.sum())} parts: ' + ', '.join(sorted({parts[i].split(".")[0] for i in np.where(PROUD)[0]})[:14]))
# joints (--joint M, default 2 mm): where two PARTS meet edge to edge with different vertices (a train car's nose
# shell and carbody shell are two closed solids that butt at x = 3.05 with 370 and 228 ring vertices, 65 shared; their
# end caps are never seen, so the culling leaves two open rims there) the simplifier moves each rim on its own: a test run
# mid (12.4 cm target) opened a crack at the nose-roof joint. Each open-border vertex within M of an open border EDGE
# of another part is inserted into that edge at its own exact position, so both rims carry the same positions and
# meshoptimizer (which joins equal positions) simplifies them as one closed seam. Nothing is locked (locking them cost
# near 7 000 triangles), no vertex moves, a rim bends by at most M. Only between BIG parts (--joint-min: seen area of
# both at least (20 x target) squared): welding every part to its neighbours took mid from 4 364 to 12 114 triangles
# (small parts could no longer be pruned, and a position shared by three rims is locked by the simplifier).
JT_TOL = 0.002 if A.joint is None else A.joint
n_joint = 0
if JT_TOL > 0 and not A.cull_only:
    t2 = time.time(); TV_ = S_T
    E_ = np.sort(np.concatenate([TV_[:, [0, 1]], TV_[:, [1, 2]], TV_[:, [2, 0]]]), 1)
    Ek = E_[:, 0].astype(np.int64) * len(V) + E_[:, 1]; uE, iE, cE = np.unique(Ek, return_inverse=True, return_counts=True)
    bedge = (cE[iE] == 1).reshape(3, -1).T                       # per triangle, per edge k (k -> k+1): open
    btri = np.where(bedge.any(1))[0]
    if len(btri):
        JTREE = BVHTree.FromPolygons(POS.tolist(), IDX[btri].tolist(), epsilon=0.0)
        tpart_ = S_P; ins = {}; JBIG = AREA_PV >= (A.joint_min * TARGET) ** 2                                  # (triangle, edge k) -> [(t, vertex to copy)]
        bvs = np.unique(np.concatenate([IDX[btri][:, k][bedge[btri][:, k] | bedge[btri][:, (k + 2) % 3]] for k in range(3)]))
        P64 = POS.astype(np.float64)
        for u in bvs:
            pu = vpart[src_v[u]]; p = P64[u]; done = set()
            for hit in JTREE.find_nearest_range(Vector(p.tolist()), JT_TOL):
                if hit[2] is None: continue
                bt = int(btri[hit[2]])
                if tpart_[bt] == pu or not (JBIG[pu] and JBIG[tpart_[bt]]): continue
                for k in range(3):
                    if not bedge[bt, k]: continue
                    a_, b_ = int(IDX[bt, k]), int(IDX[bt, (k + 1) % 3]); ab = P64[b_] - P64[a_]; l2 = float(ab @ ab)
                    if l2 < 1e-16: continue
                    t_ = float((p - P64[a_]) @ ab) / l2
                    if not (0 < t_ < 1): continue
                    q = P64[a_] + ab * t_
                    if np.linalg.norm(p - q) > JT_TOL or min(np.linalg.norm(p - P64[a_]), np.linalg.norm(p - P64[b_])) < 1e-6: continue
                    if (bt, k) in done: continue
                    done.add((bt, k)); ins.setdefault((bt, k), []).append((t_, int(u)))
        if ins:
            newP, newA, newsv, newsm = [], [], [], []; nb = len(POS); tri_new = {}
            by_tri = {}
            for (bt, k), lst in ins.items(): by_tri.setdefault(bt, {})[k] = sorted(lst)
            for bt, eds in by_tri.items():
                cur = [tuple(int(x) for x in IDX[bt])]; orig = cur[0]
                for k, lst in eds.items():
                    a_, b_ = orig[k], orig[(k + 1) % 3]
                    # the sub-triangle that still owns edge a_ -> b_
                    ix = next(i for i, tr in enumerate(cur) if a_ in tr and b_ in tr)
                    tr = cur.pop(ix); c_ = next(x for x in tr if x != a_ and x != b_); chain = [a_]
                    for t_, u in lst:
                        w = float(t_); newP.append(POS[u]); newA.append(np.concatenate([ATTR[a_, :3] * (1 - w) + ATTR[b_, :3] * w, ATTR[a_, 3:]]))
                        newsv.append(src_v[a_]); newsm.append(src_m[a_]); chain.append(nb); nb += 1
                    chain.append(b_)
                    # keep the winding of tr: a_ -> b_ is its direction along edge k
                    cur += [(chain[i], chain[i + 1], c_) for i in range(len(chain) - 1)]
                    n_joint += len(lst)
                tri_new[bt] = cur
            keep = np.ones(len(IDX), bool); keep[list(tri_new)] = False
            IDX = np.concatenate([IDX[keep], np.array([t for v_ in tri_new.values() for t in v_], np.uint32)])
            POS = np.concatenate([POS, np.array(newP, np.float32)]); ATTR = np.concatenate([ATTR, np.array(newA, np.float32)]).astype(np.float32)
            src_v = np.concatenate([src_v, np.array(newsv, src_v.dtype)]); src_m = np.concatenate([src_m, np.array(newsm, src_m.dtype)])
            LOCK = np.concatenate([LOCK, np.zeros(len(newP), np.uint8)])
    log(f'joints: {n_joint} vertices put into the open border of a neighbouring part within {JT_TOL * 1000:.1f} mm (rims share positions), {time.time() - t2:.0f} s')
lock_boxes = []
if A.lock_from:
    lj = json.load(open(A.lock_from)); lab = A.lock_label or A.level
    for vlab, vr in (lj.get('results') or {}).items():
        if lab not in vlab: continue
        for grp in ('switch', 'filled'):
            for key_, rr in (vr.get(grp) or {}).items():
                if key_ == 'night': continue        # night is a known fail of the renders (no game glow): never locked on
                items = rr.values() if grp == 'filled' else [rr]
                for r_ in items:
                    if not isinstance(r_, dict) or not r_.get('fail'): continue
                    for b in r_.get('blobs', []):
                        bb = (b.get('place') or {}).get('box_blender')
                        if bb: lock_boxes.append(bb)
    for lo_, hi_ in lock_boxes:
        lo_ = np.array(lo_) - TARGET * 2; hi_ = np.array(hi_) + TARGET * 2
        LOCK[np.all((POS >= lo_) & (POS <= hi_), 1)] = 1
# contacts (--contact M, off by default): a vertex within M of ANOTHER connected piece of the original's seen surface is
# locked. Measured 2026-10-13 on a car near (mesh_integrity floating bodies; original 2): seen faces only, not simplified
# 78; simplified 123 (18 992 tris); contact 0.5 mm 121 (23 398); 2 mm 120 (29 807); 2 mm all vertices 121 (38 139);
# 11.4 mm 66 (49 212). So most floating bodies come from the CULLING (a part's seen shell touches the rest only through
# faces no outside view reaches) and the rest from Prune / border moves; locking contacts costs triangles and does not
# fix it. Exactly coincident positions (< 1 um) are left to meshoptimizer, which keeps position seams itself.
CT_TOL = A.contact if A.contact is not None else 0.0
n_contact = 0
if CT_TOL > 0:
    t2 = time.time(); lab = np.arange(len(V)); T_ = np.concatenate([T, S_T])
    for _ in range(500):                       # connected pieces: min-label propagation with pointer jumping
        m_ = np.minimum(np.minimum(lab[T_[:, 0]], lab[T_[:, 1]]), lab[T_[:, 2]]); new = lab.copy()
        for k in range(3): np.minimum.at(new, T_[:, k], m_)
        new = new[new]
        if np.array_equal(new, lab): break
        lab = new
    tlab = lab[S_T[:, 0]]; vlab = lab[src_v]; CTREE = BVHTree.FromPolygons(V.tolist(), S_T.tolist(), epsilon=0.0)
    cand = LOCK == 0
    if A.contact_mode == 'border':      # an open edge of the seen surface (a sheet's rim, a cut left by the culling)
        TV_ = S_T; E_ = np.sort(np.concatenate([TV_[:, [0, 1]], TV_[:, [1, 2]], TV_[:, [2, 0]]]), 1)
        uE, cE = np.unique(E_, axis=0, return_counts=True); bv = np.zeros(len(V), bool); bv[uE[cE == 1].ravel()] = True
        cand &= bv[src_v]
    for u in np.where(cand)[0]:
        for hit in CTREE.find_nearest_range(Vector(POS[u].tolist()), CT_TOL):
            if hit[2] is not None and hit[3] > 1e-6 and tlab[hit[2]] != vlab[u]:
                LOCK[u] = 1; n_contact += 1; break
    log(f'contacts ({A.contact_mode}): {n_contact} vertices within {CT_TOL * 1000:.1f} mm of another piece locked '
        f'({len(np.unique(lab[S_T[:, 0]]))} seen pieces), {time.time() - t2:.0f} s')
log(f'simplifier input: {len(IDX)} triangles, {len(POS)} vertices, {int(LOCK.sum())} locked '
    f'({len(lock_boxes)} lodcmp boxes, {n_contact} contacts, {n_lamp} lamp vertices, {n_joint} joint vertices welded in)')

# ------------------------------------------------------------------------------------------------ meshoptimizer (node)
nd = K.node_dir() or K.die('meshoptimizer unavailable: needs node + npm (KIT_NODE_DIR)')
JS = r"""
const fs = require('fs'); const [dir, tmp, target, wn, wc, flags] = process.argv.slice(1);
const rd = (f, T) => { const b = fs.readFileSync(tmp + '/' + f); return new T(new Uint8Array(b).buffer); };
import(dir + '/node_modules/meshoptimizer/index.js').then(async (M) => {
  const S = M.MeshoptSimplifier; await S.ready;
  const idx = rd('idx.bin', Uint32Array), pos = rd('pos.bin', Float32Array), attr = rd('attr.bin', Float32Array);
  const lock = rd('lock.bin', Uint8Array);
  const w = [+wn, +wn, +wn, +wc, +wc, +wc];
  const [res, err] = S.simplifyWithAttributes(idx, pos, 3, attr, 6, w, lock, 0, +target, flags.split(','));
  fs.writeFileSync(tmp + '/out.bin', Buffer.from(res.buffer, res.byteOffset, res.byteLength));
  console.log(JSON.stringify({ indices: res.length, error: err }));
}).catch(e => { console.log(JSON.stringify({ error_text: String(e) })); process.exit(1); });
"""
IDX_ALL = lambda: IDX
def meshopt(target, flags, IDX=None):
    IDX = IDX_ALL() if IDX is None else IDX
    with tempfile.TemporaryDirectory() as td:
        IDX.tofile(os.path.join(td, 'idx.bin')); POS.tofile(os.path.join(td, 'pos.bin'))
        ATTR.tofile(os.path.join(td, 'attr.bin')); LOCK.tofile(os.path.join(td, 'lock.bin'))
        r = subprocess.run(['node', '-e', JS, nd, td, str(target), str(A.normal_weight * target), str(A.color_weight * target),
                            ','.join(flags)], capture_output=True, text=True)
        try: mo = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception: K.die('meshoptimizer gave nothing: ' + (r.stdout + r.stderr)[-600:])
        if 'error_text' in mo: K.die('meshoptimizer: ' + mo['error_text'])
        return np.fromfile(os.path.join(td, 'out.bin'), np.uint32).reshape(-1, 3), mo['error']
# the meshopt error is its own estimate; the MEASURED surface distance decides. When it misses the target (a pruned
# part that stood proud, a quadric that underestimates), the target given to meshopt is lowered and, last, Prune is
# dropped: the first attempt whose measured p99 is within the target wins (fewest triangles among those that pass).
attempts = []
for f_, fl in ((1.0, ['ErrorAbsolute', 'Prune']), (0.7, ['ErrorAbsolute', 'Prune']), (0.5, ['ErrorAbsolute', 'Prune']),
               (1.0, ['ErrorAbsolute']), (0.6, ['ErrorAbsolute']), (0.35, ['ErrorAbsolute'])):
    t1 = time.time()
    if A.cull_only: OUT, err = IDX.copy(), 0.0
    else:
        pr_ = PROUD[vpart[src_v[IDX[:, 0]]]]
        if pr_.any() and (~pr_).any():
            OUT, err = meshopt(TARGET * f_, fl, np.ascontiguousarray(IDX[~pr_]))
            o2, e2 = meshopt(TARGET * f_ * A.proud_error, fl, np.ascontiguousarray(IDX[pr_])); OUT = np.concatenate([OUT, o2])
        else: OUT, err = meshopt(TARGET * f_, fl, IDX)
    q_ = POS[OUT]; ar_ = np.linalg.norm(np.cross(q_[:, 1] - q_[:, 0], q_[:, 2] - q_[:, 0]), axis=1) / 2
    OUT = OUT[ar_ > 1e-10]       # zero-area triangles (two split copies of one position): the glTF reimport drops them,
                                 # their tangents are not unit (validator errors) -- a test run near had 12
    used = np.unique(OUT); remap = np.full(len(POS), -1, np.int64); remap[used] = np.arange(len(used))
    LV_ = POS[used]; LT_ = remap[OUT].astype(np.int32)
    m_ = measure(LV_, LT_)
    attempts.append(dict(target_factor=f_, flags=fl, triangles=int(len(LT_)), meshopt_error_m=round(float(err), 5),
                         p99_m=m_['error_p99_m'], seconds=round(time.time() - t1, 1)))
    log(f'meshoptimizer x{f_} {"+".join(fl)}: {len(IDX)} -> {len(LT_)} triangles, its error {err * 100:.2f} cm, '
        f'measured p99 {m_["error_p99_m"] * 100:.2f} cm')
    best = (OUT, used, LV_, LT_, m_, err)
    if A.cull_only or m_["error_p99_m"] <= TARGET * 1.05: break
OUT, used, LV, LT, m, err = best
LMv = src_m[used]; LM = LMv[LT[:, 0]]
LPart = vpart[src_v[used]][LT[:, 0]]

# one vertex per position: the simplifier works on one vertex per (original vertex, material) and parts never shared
# vertices, so every material border and every joint was a mesh border. uvpack's smart projection then made an island
# of every scrap (a test run near: 5 163 islands for 18 778 faces, 16 px of margin round each, 11 % of the atlas used, 42.5
# px/m) and mesh_integrity counted the pieces. Zero-area triangles made by the join are dropped.
_n0 = len(LV); _, _first, _inv = np.unique(LV, axis=0, return_index=True, return_inverse=True)
LV = LV[_first]; LT = _inv.ravel()[LT].astype(np.int32)
_ok = (LT[:, 0] != LT[:, 1]) & (LT[:, 1] != LT[:, 2]) & (LT[:, 0] != LT[:, 2]); LT, LM, LPart = LT[_ok], LM[_ok], LPart[_ok]
log(f'joined {_n0 - len(LV)} vertices that sat at one position ({_n0} -> {len(LV)})')
report['welded_vertices'] = int(_n0 - len(LV))
# faces that lie in one another (the original hides them under a surround or behind a closed door leaf; the version
# uncovers them and the game's depth test picks either per pixel: sweep.mjs blink 65 / 120 px on a train car's near /
# mid, 2026-10-13). After simplifying and joining, so what is cut is what the game would draw.
import _coplanar
if A.coplanar == 'cut':
    _cp = dict(pairs=0, overlap_m2=0.0, cut_triangles=0, pieces=0, rounds=0)
    for _r in range(3):                    # a cut piece can still lie in a third triangle: at most 3 rounds
        _, _, _ar = tri_geo(LV, LT); _ma = np.bincount(LM, weights=_ar, minlength=len(mat_names))
        LV, LT, _src, _ci = _coplanar.cut(LV, LT, A.coplanar_tol, pri=-_ma[LM])     # the rarer material is the detail: it stays
        if not _ci['pairs']: break
        LM, LPart = LM[_src], LPart[_src]
        for k_ in ('pairs', 'cut_triangles', 'pieces'): _cp[k_] += _ci[k_]
        _cp['overlap_m2'] = round(_cp['overlap_m2'] + _ci['overlap_m2'], 6); _cp['rounds'] += 1
    _cp['left'] = _coplanar.overlap(LV, LT, A.coplanar_tol) if _cp['pairs'] else dict(pairs=0, area_m2=0.0)
    log(f'faces lying in one another: {_cp["pairs"]} pairs, {_cp["overlap_m2"] * 1e4:.0f} cm2 drawn twice; {_cp["cut_triangles"]} triangles cut '
        f'into {_cp["pieces"]} ({_cp["rounds"]} rounds); left {_cp["left"]["pairs"]} pairs, {_cp["left"]["area_m2"] * 1e4:.1f} cm2')
else:
    _cp = dict(off=True, left=_coplanar.overlap(LV, LT, A.coplanar_tol))
    log(f'faces lying in one another (--coplanar off): {_cp["left"]["pairs"]} pairs, {_cp["left"]["area_m2"] * 1e4:.0f} cm2 drawn twice: these blink in the game')
report['coplanar'] = _cp
OT = on_top(LV, LT, LM); report['on_top'] = OT
log(f'on top: {OT["right"]:.1%} of the original\'s seen surface shows the same material in the version; worst ' +
    ', '.join(f'{k_} {r_:.0%} ({n_})' for k_, r_, n_ in OT['worst'][:5]))
# triangles over the same three vertices (a back-to-back pair of a thin sheet; a train car original has 5 968): Blender's
# mesh.validate(), which the glTF exporter calls, deletes all but one (a test run near: 12 triangles lost, reimport mismatch)
# and their shared corners got zero tangents (19 glTF-Validator errors). Each repeat gets its own vertex copies.
LT = LT.copy(); _, first_, inv_ = np.unique(np.sort(LT, 1), axis=0, return_index=True, return_inverse=True)
rep_ = np.where(first_[inv_.ravel()] != np.arange(len(LT)))[0]
if len(rep_):
    ex_ = LT[rep_].ravel(); LT[rep_] = (len(LV) + np.arange(len(ex_))).reshape(-1, 3); LV = np.concatenate([LV, LV[ex_]])
    log(f'{len(rep_)} repeated triangles (same three vertices, back to back) given their own vertices')
report.update(mode='simplify', triangles=int(len(LT)), meshopt_error_m=round(float(err), 5), error=m, attempts=attempts,
              locked_vertices=int(LOCK.sum()), lock_boxes=len(lock_boxes), contact_locked=n_contact, proud_parts=int(PROUD.sum()), joint_welded=n_joint, joint_tol_m=JT_TOL, repeated_split=int(len(rep_)),
              contact_tol_m=round(CT_TOL, 5))
per_part = np.bincount(LPart, minlength=len(parts))
top = [(parts[i], int(per_part[i])) for i in np.argsort(-per_part)[:6] if per_part[i]]
report['triangles_by_part'] = top
over_err = m['error_p99_m'] > TARGET * 1.05
over_b = A.budget is not None and len(LT) > A.budget
msg = (f'{A.level}: needs {len(LT)} triangles for {A.px:g} px at {DIST:g} m (target {TARGET * 100:.2f} cm; measured p99 '
       f'{m["error_p99_m"] * 100:.2f} cm = {m["error_p99_px"]} px, max {max(m["original_to_version"]["max"], m["version_to_original"]["max"]) * 100:.1f} cm)')
if over_b: msg = (f'OVER BUDGET {msg}, budget {A.budget}, over by {len(LT) - A.budget} ({len(LT) / A.budget - 1:.0%}), mostly in '
                  + ', '.join(f'{n} {c}' for n, c in top[:4]))
if over_err: msg += f'; the simplifier missed the target: largest at {m["worst_places"][:3]}'
if (over_b or over_err) and not A.keep_over: finish(3, msg)

# ------------------------------------------------------------------------------------------------ the version collection
into = A.into or f'GAME_{A.level}'
old = bpy.data.collections.get(into)
if old:
    for o in list(old.all_objects): bpy.data.objects.remove(o)
    bpy.data.collections.remove(old)
col = bpy.data.collections.new(into); bpy.context.scene.collection.children.link(col)
if A.slots:      # with game slots, glass is what the slots call glass-*; a lamp lens (LED-ivory) stays on the surface
    SLm = K.load_slots(A.slots)
    glassm = np.array([('glass-' in (K.slot_role(n, SLm, A.level) or '')) for n in mat_names])
else:
    glassm = np.array([K.match(n, GL) or (bpy.data.materials.get(n) is not None and any(
        K.is_glass_principled(x) for x in (bpy.data.materials[n].node_tree.nodes if bpy.data.materials[n].node_tree else [])
        if x.type == 'BSDF_PRINCIPLED')) for n in mat_names])
made = []
for label, sel in (('surface', ~glassm[LM]), ('glass', glassm[LM])):
    if not sel.any(): continue
    tt = LT[sel]; uu = np.unique(tt); rm = np.full(len(LV), -1, np.int64); rm[uu] = np.arange(len(uu))
    me = bpy.data.meshes.new(f'{into}.{label}')
    me.from_pydata(LV[uu].tolist(), [], rm[tt].tolist())
    ids = sorted(set(LM[sel].tolist()))
    for i in ids: me.materials.append(bpy.data.materials.get(mat_names[i]))
    me.polygons.foreach_set('material_index', np.array([ids.index(x) for x in LM[sel]], np.int32)); me.update()
    o = bpy.data.objects.new(f'{into}.{label}', me); col.objects.link(o)
    if label == 'glass': o['glass'] = True
    made.append(dict(object=o.name, triangles=int(sel.sum()), materials=[mat_names[i] for i in ids]))
report['objects'] = made; report['collection'] = into; report['over'] = bool(over_b or over_err)
if A.save:
    for lc in _lcs(bpy.context.view_layer.layer_collection):
        if lc.name in EXCL0: lc.exclude = EXCL0[lc.name]
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(A.save), copy=False)
    report['saved'] = os.path.abspath(A.save)
finish(3 if (over_b or over_err) else 0, ('KEPT ' if (over_b or over_err) else 'ok ') + msg)
