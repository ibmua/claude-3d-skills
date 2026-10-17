"""Give a game version ONE non-overlapping UV atlas with a margin, at even texel density, and report the density.

  nice -n 10 blender -b FILE.blend --python uvpack.py -- --low LOW --save OUT.blend [--size 2048] [--margin-px max(4,size/128)]
        [--band near|mid|far --family F]
        [--mode auto|keep|smart] [--angle 66] [--uv NAME] [--under-weight 1.0] [--flat-px 8] [--report OUT.json]

LOW      collection or object (or OTHER.blend[:COLLECTION]); every mesh in it except glass (*glass*, custom prop
         glass=1, --glass-collection) shares the atlas. Modifiers are applied first (a mirror modifier would
         otherwise lay both halves on the same texels).
--mode   keep: keep the islands as they are, only even out their scale and repack them.
         smart: smart-project every face again (angle --angle).
         auto (default): keep good islands, smart-project only the faces of islands that overlap themselves or
         another island, or have no UV area; a mesh with no UV layer is smart-projected.
--under-weight  texel density of islands facing down (normal z < -0.5) relative to the rest (e.g. 0.4: undersides
         are rarely seen). --flat-px: faces whose material has custom prop `flat`/`flat_color` (filled with a flat
         value by bake.py) all go into one small square of this many pixels per material.
--band   near|mid|far (+ --family, scripts/switch.json): reports the median texel density against what the screen
         needs where this version is first seen (1 / (d x 0.000674) px/m at 1080 rows: train near 7.5 m 198, mid
         92 m 16, far 292 m 5; city kit mid 18 m 82, far 64 m 23); WARNING below 0.7x (standards research 2026-10-13).
--margin-px  default max(4, size/128): 16 px at 2048, 8 at 1024, 4 at 512 (bilinear at mip k reads 2^(k+1) texels).
--charts smart (default) | xatlas | auto: smart = Blender's smart project + the skyline packer below. xatlas (pip package
         `xatlas`, looked for in Blender's Python and in ~/.cache/3d-asset-kit/py<ver>; install: uv pip install --python
         <blender python> --target that folder xatlas) cuts and packs a version that has no usable UVs; auto takes it
         when it imports. NOT the default and NOT verified: on a car near (39 095 faces in ~1 500 separate pieces,
         2026-10-13) it gave no result in 7 minutes. The island count comes from the pieces, not from the chart maker:
         smart project made 8 702 islands there. Small islands therefore get a smaller margin (half their own size, at
         least 4 px, at most --margin-px): with 16 px round every bolt, 3.6 % of that atlas was used (24 px/m).
--save   where the .blend with the new UVs is written (never over the input unless it is the same path you give).

Islands are turned to their minimum-area rectangle, scaled so every island has the same texels per metre (times its
weight), then packed by a skyline bottom-left packer with 90-degree turns; the largest common scale is found by
bisection (Blender's own packer left 45 % of a train car near atlas empty on mostly rectangular islands). Half the
margin is kept at the atlas border (glTF samplers repeat). Prints and writes: islands, atlas use, texel density
(px per metre at --size: area-weighted median, min, max), and the overlap left (pixels shared by two islands; must be 0:
otherwise nothing is saved and it exits 1). Modifiers are applied BEFORE the overlap test, so a Solidify inner skin
that kept the outer skin's UVs is found and re-projected (a car white steel, 2026-10-13).
"""
import argparse, json, math, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _kit as K

ap = argparse.ArgumentParser(prog='uvpack.py', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('--low', required=True); ap.add_argument('--save', required=True)
ap.add_argument('--size', type=int, default=2048); ap.add_argument('--margin-px', type=float)
ap.add_argument('--band', choices=('near', 'mid', 'far')); ap.add_argument('--family')
ap.add_argument('--mode', default='auto', choices=('auto', 'keep', 'smart')); ap.add_argument('--angle', type=float, default=66)
ap.add_argument('--uv'); ap.add_argument('--under-weight', type=float, default=1.0); ap.add_argument('--flat-px', type=float, default=8)
ap.add_argument('--glass-collection', default=''); ap.add_argument('--report')
ap.add_argument('--charts', default='smart', choices=('auto', 'xatlas', 'smart'), help='how faces without usable UVs are cut into '
                'islands: xatlas (the chart maker game engines use; auto takes it when it can be imported) or Blender smart project')
A = ap.parse_args(K.script_argv())

import bpy, bmesh
import numpy as np
log = lambda *a: print('[uvpack]', *a, flush=True)
T0 = time.time()
S = A.size
if A.margin_px is None: A.margin_px = max(4, S // 128)   # bilinear at mip k reads 2^(k+1) texels: 16 px at 2048, 8 at 1024, 4 at 512
MARGIN = A.margin_px / S

objs, label = K.resolve(A.low)
gcol = bpy.data.collections.get(A.glass_collection) if A.glass_collection else None
gnames = {o.name for o in gcol.all_objects} if gcol else set()
objs = [o for o in objs if o.type == 'MESH' and not (o.name in gnames or K.is_glass_obj(o))]
if not objs: K.die('no surface mesh in ' + A.low)
dg = bpy.context.evaluated_depsgraph_get()
for o in objs:                                                    # apply modifiers (on this copy of the file only)
    if o.modifiers:
        me = bpy.data.meshes.new_from_object(o.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
        o.modifiers.clear(); o.data = me
    me = o.data
    if A.uv and A.uv in me.uv_layers: lay = me.uv_layers[A.uv]
    elif me.uv_layers: lay = next((u for u in me.uv_layers if u.active_render), me.uv_layers.active)
    else: lay = me.uv_layers.new(name=A.uv or 'UVMap')
    me.uv_layers.active = lay; lay.active_render = True


def is_flat(m): return bool(m and (m.get('flat') or 'flat_color' in m))


def islands(me):
    """Lists of polygon indices, UV-connected (shared vertex AND same UV), flat faces left out."""
    uv = me.uv_layers.active.data
    parent = list(range(len(me.polygons)))
    def find(a):
        while parent[a] != a: parent[a] = parent[parent[a]]; a = parent[a]
        return a
    flatm = {i for i, m in enumerate(me.materials) if is_flat(m)}
    key = {}
    for p in me.polygons:
        if p.material_index in flatm: continue
        for li in p.loop_indices:
            k = (me.loops[li].vertex_index, round(uv[li].uv[0], 5), round(uv[li].uv[1], 5))
            if k in key:
                ra, rb = find(key[k]), find(p.index)
                if ra != rb: parent[ra] = rb
            else: key[k] = p.index
    g = {}
    for p in me.polygons:
        if p.material_index in flatm: continue
        g.setdefault(find(p.index), []).append(p.index)
    return list(g.values())


def cross2(a, b): return a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]


def tri_uv_of(me, polys):
    uv = me.uv_layers.active.data; out = []
    for pi in polys:
        L = list(me.polygons[pi].loop_indices)
        for k in range(1, len(L) - 1): out.append([uv[L[0]].uv[:], uv[L[k]].uv[:], uv[L[k + 1]].uv[:]])
    return np.array(out, np.float64).reshape(-1, 3, 2)


def overlap_report(groups, R=1024, strict=True):
    """groups: [(mesh, polys)]. Returns (overlap pixels, set of bad group indices) on a grid over the UV bounds."""
    tris = [tri_uv_of(me, ps) for me, ps in groups]
    allp = np.concatenate([t.reshape(-1, 2) for t in tris if len(t)]) if any(len(t) for t in tris) else np.zeros((1, 2))
    lo = allp.min(0); span = max(float((allp.max(0) - lo).max()), 1e-9)
    owner = np.full((R, R), -1, np.int32); bad = set(); ov = 0
    for gi, t in enumerate(tris):
        if not len(t): bad.add(gi); continue
        a2 = np.abs(cross2(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])).sum()
        if a2 < 1e-12: bad.add(gi); continue
        cnt = K.raster_uv((t - lo) / span * 0.999, R, count=True)      # self-overlap: one island's triangles twice
        m = cnt > 0
        self_ov = int((cnt > 1).sum())
        other = owner[m]; hit = other[other >= 0]
        if len(hit) > 2: bad.add(gi); bad.update(set(np.unique(hit).tolist())); ov += len(hit)
        if self_ov > max(2, 0.02 * m.sum()): bad.add(gi); ov += self_ov
        owner[m & (owner < 0)] = gi
    return ov, bad


def smart(o, polys):
    me = o.data
    for x in bpy.context.view_layer.objects: x.select_set(False)
    o.hide_set(False); o.select_set(True); bpy.context.view_layer.objects.active = o
    with bpy.context.temp_override(active_object=o, object=o, selected_objects=[o], selected_editable_objects=[o]):
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(me); bm.faces.ensure_lookup_table()
        for f in bm.faces: f.select_set(f.index in polys)
        bmesh.update_edit_mesh(me)
        bpy.ops.uv.smart_project(angle_limit=math.radians(A.angle), island_margin=0.0, area_weight=0.0, scale_to_bounds=False)
        bpy.ops.object.mode_set(mode='OBJECT')


def xatlas_mod():
    try:
        import xatlas; return xatlas
    except Exception:
        pth = os.path.expanduser('~/.cache/3d-asset-kit/py%d%d' % sys.version_info[:2])
        if pth not in sys.path: sys.path.insert(0, pth)
        try:
            import xatlas; return xatlas
        except Exception: return None


def no_uvs(me):
    n = len(me.uv_layers.active.data); a = np.zeros(n * 2, np.float32); me.uv_layers.active.data.foreach_get('uv', a)
    return not np.abs(a).any()


XDONE = None
XA = xatlas_mod() if A.charts != 'smart' else None
if A.charts == 'xatlas' and XA is None: K.die('--charts xatlas: the module is not importable (see --help for the install line)')
def all_bad(me):       # a fresh UV layer is not zeros: Blender lays every face over the whole square
    if no_uvs(me): return True
    isl = islands(me); _, bad = overlap_report([(me, ps) for ps in isl]); return len(bad) >= len(isl)


if XA is not None and (A.mode == 'smart' or (A.mode == 'auto' and all(all_bad(o.data) for o in objs))) \
        and all(len(p.vertices) == 3 for o in objs for p in o.data.polygons) \
        and not any(is_flat(m) for o in objs for m in o.data.materials):
    t1 = time.time(); atlas = XA.Atlas()
    for o in objs:
        me = o.data; co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
        mw = np.array(o.matrix_world, np.float64); co = (co @ mw[:3, :3].T + mw[:3, 3]).astype(np.float32)
        idx = np.empty(len(me.loops), np.int32); me.loops.foreach_get('vertex_index', idx)
        atlas.add_mesh(co, idx.reshape(-1, 3).astype(np.uint32))
    po = XA.PackOptions(); po.padding = int(round(A.margin_px)); po.resolution = S; po.bilinear = True
    atlas.generate(chart_options=XA.ChartOptions(), pack_options=po)
    Wx, Hx = atlas.width, atlas.height; mx_ = float(max(Wx, Hx, 1))
    for i, o in enumerate(objs):
        vmap, tri, uvs = atlas[i]; me = o.data
        lv = np.empty(len(me.loops), np.int32); me.loops.foreach_get('vertex_index', lv)
        if not np.array_equal(np.asarray(vmap)[np.asarray(tri).ravel()], lv): K.die('xatlas returned another face order: use --charts smart')
        uv = np.asarray(uvs)[np.asarray(tri).ravel()] * np.array([Wx / mx_, Hx / mx_], np.float32)
        me.uv_layers.active.data.foreach_set('uv', uv.astype(np.float32).ravel())
    XDONE = dict(charts=int(atlas.chart_count), atlas_px=[int(Wx), int(Hx)], seconds=round(time.time() - t1, 1))
    log(f'xatlas: {XDONE["charts"]} charts, packed at {Wx} x {Hx} for a {S} px atlas, padding {po.padding} px, {XDONE["seconds"]} s')

redone = 0
for o in ([] if XDONE else objs):
    me = o.data
    flatm = {i for i, m in enumerate(me.materials) if is_flat(m)}
    allp = {p.index for p in me.polygons if p.material_index not in flatm}
    if A.mode == 'smart' or (A.mode == 'auto' and not any(abs(u.uv[0]) + abs(u.uv[1]) > 0 for u in me.uv_layers.active.data)):
        smart(o, allp); redone += len(allp); continue
    if A.mode == 'auto':
        isl = islands(me)
        _, bad = overlap_report([(me, ps) for ps in isl])
        badp = {pi for gi in bad for pi in isl[gi]}
        if badp:
            log(f'{o.name}: {len(bad)} of {len(isl)} islands overlap or are degenerate -> smart project {len(badp)} faces')
            smart(o, badp); redone += len(badp)

# ------------------------------------------------------------------------------------------------ gather islands
def hull(pts):
    pts = sorted(set(pts))
    if len(pts) <= 2: return pts
    cr = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cr(lo[-2], lo[-1], p) <= 0: lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cr(up[-2], up[-1], p) <= 0: up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def min_rect_angle(pts):
    h = hull(pts); best = (float('inf'), 0.0)
    for i in range(len(h)):
        (x0, y0), (x1, y1) = h[i], h[(i + 1) % len(h)]
        a = -math.atan2(y1 - y0, x1 - x0); c, s = math.cos(a), math.sin(a)
        xs = [c * x - s * y for x, y in h]; ys = [s * x + c * y for x, y in h]
        ar = (max(xs) - min(xs)) * (max(ys) - min(ys))
        if ar < best[0] - 1e-15: best = (ar, a)
    return best[1]


ISL = []        # dict(o, loops, pts (turned, at metric scale), w, h, area3d, weight)
FLATS = []      # (o, polys) per flat material
for o in objs:
    me = o.data; uv = me.uv_layers.active.data
    sc3 = abs(o.matrix_world.to_3x3().determinant()) ** (2 / 3)
    flatm = {i for i, m in enumerate(me.materials) if is_flat(m)}
    for fi in sorted(flatm):
        ps = [p.index for p in me.polygons if p.material_index == fi]
        if ps: FLATS.append((o, ps))
    nz_w = o.matrix_world.to_3x3().inverted().transposed()
    for ps in islands(me):
        if XDONE:        # xatlas packed already: keep its placing, only the numbers are gathered
            t = tri_uv_of(me, ps); uva = float(np.abs(cross2(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])).sum() / 2)
            a3 = sum(me.polygons[pi].area for pi in ps) * sc3
            ISL.append(dict(o=o, polys=ps, area3d=a3, weight=1.0, dens=math.sqrt(uva / a3) * S if a3 > 1e-14 and uva > 0 else 0.0)); continue
        loops = [li for pi in ps for li in me.polygons[pi].loop_indices]
        pts = [tuple(uv[li].uv) for li in loops]
        t = tri_uv_of(me, ps); uva = float(np.abs(cross2(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])).sum() / 2)
        a3 = sum(me.polygons[pi].area for pi in ps) * sc3
        nz = sum((nz_w @ me.polygons[pi].normal).normalized().z * me.polygons[pi].area for pi in ps) / max(1e-12, sum(me.polygons[pi].area for pi in ps))
        w = A.under_weight if nz < -0.5 else 1.0
        k = math.sqrt(a3 / uva) * w if uva > 1e-14 and a3 > 1e-14 else 1.0
        ang = min_rect_angle(pts); c, s = math.cos(ang), math.sin(ang)
        tp = [((c * x - s * y) * k, (s * x + c * y) * k) for x, y in pts]
        mx = min(p[0] for p in tp); my = min(p[1] for p in tp)
        tp = [(x - mx, y - my) for x, y in tp]
        ISL.append(dict(o=o, polys=ps, loops=loops, pts=tp, w=max(p[0] for p in tp), h=max(p[1] for p in tp), area3d=a3, weight=w))


def skyline(rects):
    order = sorted(range(len(rects)), key=lambda i: (-max(rects[i]), -min(rects[i])))
    sky = [[0.0, 0.0, 1.0]]; out = [None] * len(rects); eps = 1e-12
    for i in order:
        w0, h0 = rects[i]; best = None
        for turned in (False, True):
            w, h = (h0, w0) if turned else (w0, h0)
            if w > 1 + eps or h > 1 + eps: continue
            for j in range(len(sky)):
                x = sky[j][0]
                if x + w > 1 + eps: break
                y = 0.0
                for s in sky[j:]:
                    if s[0] >= x + w - eps: break
                    y = max(y, s[1])
                if y + h > 1 + eps: continue
                cand = (y + h, x, turned, w, h, y)
                if best is None or cand[:2] < best[:2]: best = cand
        if best is None: return None
        top, x, turned, w, h, y = best; out[i] = (x, y, turned)
        res = []
        for sx, sy, sw in sky:
            ex = sx + sw
            if ex <= x + eps or sx >= x + w - eps: res.append([sx, sy, sw]); continue
            if sx < x - eps: res.append([sx, sy, x - sx])
            if ex > x + w + eps: res.append([x + w, sy, ex - (x + w)])
        res.append([x, y + h, w]); res.sort(key=lambda s: s[0]); merged = [res[0]]
        for s in res[1:]:
            if abs(s[1] - merged[-1][1]) < eps: merged[-1][2] += s[2]
            else: merged.append(s)
        sky = merged
    return out


if not XDONE:
    FP = A.flat_px / S
    area = sum(d['w'] * d['h'] for d in ISL) or 1.0
    hi = math.sqrt(1.0 / area); lo = 0.0; best = None
    # an island's margin: half its own longer side, at least 4 px, at most --margin-px (a 3 px bolt needs no 16 px moat)
    mg = lambda d, sc: min(MARGIN, max(4.0 / S, 0.5 * max(d['w'], d['h']) * sc))
    for _ in range(24):
        sc = (lo + hi) / 2
        rects = [(d['w'] * sc + mg(d, sc), d['h'] * sc + mg(d, sc)) for d in ISL] + [(FP + MARGIN, FP + MARGIN)] * len(FLATS)
        r = skyline(rects)
        if r is None: hi = sc
        else: lo = sc; best = (sc, r)
    if best is None: K.die('islands do not fit even at the smallest scale (too many flat squares or margin too wide)')
    sc, place = best
    for d, (x, y, turned) in zip(ISL, place):
        uv = d['o'].data.uv_layers.active.data; W, H = d['w'] * sc, d['h'] * sc
        for li, (u, v) in zip(d['loops'], d['pts']):
            u, v = u * sc, v * sc
            if turned: u, v = H - v, u
            uv[li].uv = (x + mg(d, sc) / 2 + u, y + mg(d, sc) / 2 + v)
    for (o, ps), (x, y, _) in zip(FLATS, place[len(ISL):]):
        uv = o.data.uv_layers.active.data; c = [(0, 0), (1, 0), (1, 1), (0, 1)]
        for pi in ps:
            for k, li in enumerate(o.data.polygons[pi].loop_indices):
                uv[li].uv = (x + MARGIN / 2 + c[k % 4][0] * FP, y + MARGIN / 2 + c[k % 4][1] * FP)

# ------------------------------------------------------------------------------------------------ report
# every island got the same UV length per metre (its weight) before the common scale sc: px/m = weight * sc * size
dens = sorted(((d['dens'] if XDONE else d['weight'] * sc * S), d['area3d']) for d in ISL)
tot = sum(a for _, a in dens) or 1; acc = 0; med = dens[0][0] if dens else 0
for v, a in dens:
    acc += a
    if acc >= tot / 2: med = v; break
# overlap after packing, on the real 0..1 frame at the atlas size (pixels shared by two islands)
owner = np.full((S, S), -1, np.int32); ov = 0
for gi, d in enumerate(ISL):
    m = K.raster_uv(tri_uv_of(d['o'].data, d['polys']), S)
    ov += int((owner[m] >= 0).sum()); owner[m & (owner < 0)] = gi
used = float((owner >= 0).mean())
rep = dict(tool='3d-asset-making/scripts/uvpack.py', file=bpy.data.filepath, saved=os.path.abspath(A.save), low=A.low,
           objects=[o.name for o in objs], mode=A.mode, charts='xatlas' if XDONE else 'smart', xatlas=XDONE, smart_projected_faces=redone, islands=len(ISL),
           flat_squares=len(FLATS), size=S, margin_px=A.margin_px, atlas_texels_used=round(used, 4),
           texel_density_px_per_m=dict(median=round(med, 1), min=round(dens[0][0], 1) if dens else 0,
                                       max=round(dens[-1][0], 1) if dens else 0, note='at --size; undersides x --under-weight'),
           overlap_px=ov, seconds=round(time.time() - T0, 1))
if A.band:      # texels per metre against what the screen shows at the closest distance this version is seen
    sw = K.switch(A.family); need = 1.0 / sw['m_per_px'][A.band]
    rep['density_need'] = dict(band=A.band, family=sw['family'], distance_m=sw['appears'][A.band], need_px_per_m=round(need, 1),
                               ratio=round(med / need, 2), warn=med < 0.7 * need)
    if med < 0.7 * need:
        log(f'WARNING: median {med:.1f} px/m is {med / need:.2f}x of the {need:.0f} px/m a {A.band} version needs at '
            f'{sw["appears"][A.band]:g} m (1080 rows): raise --size or give the faces seen most more room')
log(json.dumps(rep))
if A.report:
    with open(A.report, 'w') as f: json.dump(rep, f, indent=1)
if ov:
    log(f'FAULT: {ov} texels are shared by two islands: not saved (a bake would let the last face win)'); sys.exit(1)
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(A.save), copy=True)
log('saved', A.save)
