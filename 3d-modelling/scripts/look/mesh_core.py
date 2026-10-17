"""mesh_core.py: the numpy half of mesh_look.py (no bpy here, so the tests can call and break each step).

Arrays in are one evaluated mesh instance in WORLD space; `Tally` adds instances up and writes the result dict.
The constants below are the measure's definition: change one and every number moves (the tests do exactly that).
"""
import collections, math, re
import numpy as np

TURN_DEG = 30.0      # an edge where the surface turns at least this much is a corner
WIDE_M = 0.020       # a face narrower than this across the edge is a bevel strip
PATCH_DEG = 12.0     # faces joined across gentler edges form one surface patch
SPLIT_DEG = 8.0      # corner normals further apart than this across an edge = split normals (a hard edge)
BLOBBY_DEG = 60.0    # shared normals across a turn this big between two wide faces = pillow shading
COUNT_HARD_BEVEL_BOUNDARY = True   # False = the research prototype's classes exactly (for comparing with its numbers)
CLASSES = ('razor', 'facet', 'rounded', 'blobby', 'curved')
WIDTH_BINS_MM = [0, 1, 2, 4, 8, 15, 20]
WIDTH_LABELS = ('<1', '1-2', '2-4', '4-8', '8-15', '15-20', '>=20')
REL_BINS = [0, .5, 1, 2, 4, 8, 1e9]
REL_LABELS = ('<0.5%', '0.5-1%', '1-2%', '2-4%', '4-8%', '>8%')
DECADES = [(1.0, 1e9), (0.1, 1.0), (0.01, 0.1), (0.001, 0.01), (0.0001, 0.001), (0, 0.0001)]
DECADE_LABELS = ('>1 m2', '0.1-1 m2', '100-1000 cm2', '10-100 cm2', '1-10 cm2', '<1 cm2')


def split_normals(cn, a, b, nxt, lv):
    """True per edge when the two faces do not share their corner normals at the edge's vertices."""
    va1, vb0 = lv[nxt[a]], lv[b]
    flip = vb0 == va1                                           # opposite winding (the normal case)
    nb0 = np.where(flip[:, None], cn[nxt[b]], cn[b]); nb1 = np.where(flip[:, None], cn[b], cn[nxt[b]])
    d0 = (cn[a] * nb0).sum(1); d1 = (cn[nxt[a]] * nb1).sum(1)
    return np.minimum(d0, d1) < math.cos(math.radians(SPLIT_DEG))


def flat_area(area, smooth):
    """Area of faces that are flat-shaded (use_smooth off): Bevel's Harden Normals and WeightedNormal do nothing there."""
    return float(area[~smooth].sum())


def bevel_width(a, b, nl, ls, lt, lp, area, elen, steps=8):
    """Whole width of the bevel an edge belongs to (m): from the edge, walk across the narrow quads on each side
    (edge -> the quad's opposite edge -> the next quad) and add their widths, so a 2-segment bevel reports both
    segments, not one. a, b: the two loops of each manifold edge. Triangles end the walk (a triangulated file
    reports one segment)."""
    pair = np.full(nl, -1); pair[a] = b; pair[b] = a
    off = np.arange(nl) - ls[lp]
    opp = np.where(lt[lp] == 4, ls[lp] + (off + 2) % 4, -1)        # the loop of the opposite edge in a quad
    wl = np.where(lt[lp] >= 4, area[lp], 2 * area[lp]) / np.maximum(elen, 1e-9)   # face width across each loop's edge
    narrow = wl < WIDE_M

    def walk(start):
        acc = np.zeros(len(start)); cur = start.copy(); on = narrow[cur]
        for _ in range(steps):
            acc[on] += wl[cur[on]]
            o = opp[cur]; nx = np.where(o >= 0, pair[np.maximum(o, 0)], -1)
            on = on & (nx >= 0) & narrow[np.maximum(nx, 0)]
            cur = np.where(on, nx, cur)
            if not on.any():
                break
        return acc
    return walk(a) + walk(b)


def edges(co, lv, le, ls, lt, cn, smooth):
    """co (nv,3) world positions, lv/le loop -> vertex/edge, ls/lt polygon loop start/total, cn (nl,3) world corner
    normals (unit), smooth (npoly,) bool. Returns per manifold edge: length L, turn (rad), split, wmin (m, the
    narrower face across the edge), convex, the two faces fa/fb; plus per-polygon area and totals."""
    nl, npoly = len(lv), len(ls)
    lp = np.repeat(np.arange(npoly), lt)                        # loop -> polygon
    nxt = np.arange(nl) + 1; nxt[ls + lt - 1] = ls              # loop -> next loop in its polygon
    p0, p1 = co[lv], co[lv[nxt]]
    pn = np.zeros((npoly, 3)); np.add.at(pn, lp, np.cross(p0, p1))      # Newell normal, world space
    area = 0.5 * np.linalg.norm(pn, axis=1); pn /= np.maximum(2 * area[:, None], 1e-18)
    elen = np.linalg.norm(p1 - p0, axis=1)
    order = np.argsort(le, kind='stable'); es = le[order]       # pair the two loops of every manifold edge
    first = np.r_[True, es[1:] != es[:-1]]; cnt = np.diff(np.r_[np.nonzero(first)[0], len(es)])
    start = np.nonzero(first)[0][cnt == 2]
    a, b = order[start], order[start + 1]
    fa, fb = lp[a], lp[b]
    ok = fa != fb
    a, b, fa, fb = a[ok], b[ok], fa[ok], fb[ok]
    L = elen[a]
    turn = np.arccos(np.clip((pn[fa] * pn[fb]).sum(1), -1, 1))
    cen = np.zeros((npoly, 3)); np.add.at(cen, lp, p0); cen /= lt[:, None]
    convex = ((cen[fb] - cen[fa]) * pn[fa]).sum(1) < 0          # the other face's centre lies behind this face
    quad = lt >= 4
    wa = np.where(quad[fa], area[fa], 2 * area[fa]) / np.maximum(L, 1e-9)
    wb = np.where(quad[fb], area[fb], 2 * area[fb]) / np.maximum(L, 1e-9)
    wfull = bevel_width(a, b, nl, ls, lt, lp, area, elen)
    return dict(L=L, turn=turn, split=split_normals(cn, a, b, nxt, lv), wmin=np.minimum(wa, wb), wfull=wfull, convex=convex,
                fa=fa, fb=fb, area=area, npoly=npoly, flat_area=flat_area(area, smooth), all_area=float(area.sum()),
                tris=int((lt - 2).sum()), lo=co.min(0), hi=co.max(0))


def classify(r):
    """Corner class masks per edge (see mesh_look.py --help for what each class looks like)."""
    T, B = math.radians(TURN_DEG), math.radians(BLOBBY_DEG)
    c = r['turn'] >= T
    narrow = r['wmin'] < WIDE_M
    k = {'razor': c & r['split'] & ~narrow, 'facet': c & r['split'] & narrow, 'rounded': c & ~r['split'] & narrow,
         'blobby': c & ~r['split'] & ~narrow & (r['turn'] >= B), 'curved': c & ~r['split'] & ~narrow & (r['turn'] < B)}
    # gentler turns on narrow smooth strips belong to rounded corners too (a 3-segment fillet turns 30 deg a step)
    soft = (~c) & (r['turn'] >= math.radians(PATCH_DEG)) & narrow
    k['rounded'] = k['rounded'] | (soft & ~r['split'])
    if COUNT_HARD_BEVEL_BOUNDARY:
        # the same gentle turn with SPLIT normals: a bevel whose boundary against the face is a hard edge (what
        # Bevel's Harden Normals followed by WeightedNormal with Keep Sharp gives in Blender 5.2). The research
        # prototype counted these nowhere, so a 2-segment bevel built that way read as 100 % rounded.
        k['facet'] = k['facet'] | (soft & r['split'])
    return k


def patches(r):
    """Union faces across edges that turn < PATCH_DEG -> areas of the surface patches."""
    par = np.arange(r['npoly'])

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    m = r['turn'] < math.radians(PATCH_DEG)
    for x, y in zip(r['fa'][m].tolist(), r['fb'][m].tolist()):
        rx, ry = find(x), find(y)
        if rx != ry:
            par[ry] = rx
    roots = np.array([find(i) for i in range(r['npoly'])])
    out = np.zeros(r['npoly']); np.add.at(out, roots, r['area'])
    return out[out > 0]


def part_key(name):
    """door_leaf.003 and door_leaf_12 are the same part."""
    return re.sub(r'[._]?\d+$', '', name)


class Tally:
    """Add up instances (add), then result() -> the mesh half of look.json."""

    def __init__(self):
        self.classes = collections.OrderedDict((k, 0.0) for k in CLASSES)
        self.convex = dict.fromkeys(CLASSES, 0.0)
        self.width_hist = np.zeros(len(WIDTH_BINS_MM)); self.rel_hist = np.zeros(6); self.full_hist = np.zeros(len(WIDTH_BINS_MM))
        self.widths, self.weights = [], []
        self.patch_areas = []
        self.parts = collections.defaultdict(lambda: dict.fromkeys(list(CLASSES) + ['tris', 'n', 'ww', 'w', 'fw', 'flat', 'area', 'wround', 'span'], 0.0))
        self.mesh_tris = collections.Counter()
        self.flat = [0.0, 0.0]; self.tris = 0; self.inst = 0
        self.lo = np.full(3, 1e9); self.hi = np.full(3, -1e9)

    def add(self, part_name, mesh_name, r):
        self.inst += 1; self.tris += r['tris']
        self.lo = np.minimum(self.lo, r['lo']); self.hi = np.maximum(self.hi, r['hi'])
        self.mesh_tris[mesh_name] += r['tris']
        size = float(np.sort(r['hi'] - r['lo'])[1])             # the part's middle dimension
        w = r['L'] * r['turn']                                  # weight: metres of edge x radians turned
        k = classify(r)
        p = self.parts[part_key(part_name)]
        for n_, m in k.items():
            s = float(w[m].sum()); self.classes[n_] += s; self.convex[n_] += float(w[m & r['convex']].sum()); p[n_] += s
        p['tris'] += r['tris']; p['n'] += 1; p['span'] = max(p['span'], r['all_area']); p['flat'] += r['flat_area']; p['area'] += r['all_area']
        self.flat[0] += r['flat_area']; self.flat[1] += r['all_area']
        m = k['rounded'] | k['facet']
        if m.any():
            wm = r['wmin'][m] * 1000
            p['ww'] += float((wm * w[m]).sum()); p['w'] += float(w[m].sum()); p['wround'] += float(w[k['rounded']].sum())
            p['fw'] += float((r['wfull'][m] * 1000 * w[m]).sum())
            self.full_hist += np.histogram(r['wfull'][m] * 1000, bins=WIDTH_BINS_MM + [1e9], weights=w[m])[0]
            self.widths.append(wm); self.weights.append(w[m])
            self.width_hist += np.histogram(wm, bins=WIDTH_BINS_MM + [1e9], weights=w[m])[0]
            self.rel_hist += np.histogram(100 * r['wmin'][m] / max(size, 1e-6), bins=REL_BINS, weights=w[m])[0]
        self.patch_areas.append(patches(r))

    def body(self, pattern=None):
        """The part whose bevel is 'the body bevel': the part with the largest single instance by surface area
        (the shell), or the largest part matching `pattern`. bevel_mm 0 = that part
        has no bevel strip at all; bevel_mm is the whole bevel (all its
        segments), strip_mm one segment (what the research prototype reported). candidates: the three largest parts, so a wrong pick is visible."""
        rx = re.compile(pattern, re.I) if pattern else None
        cand = sorted(((v['span'], v['area'], k, v) for k, v in self.parts.items() if (rx.search(k) if rx else True)),
                      key=lambda c: (-round(c[0], 2), -c[1]))
        if not cand:
            return None

        def row(c):
            v = c[3]
            return dict(part=c[2], largest_instance_m2=round(c[0], 2), area_m2=round(c[1], 2), bevel_mm=round(v['fw'] / v['w'], 1) if v['w'] else 0.0,
                        strip_mm=round(v['ww'] / v['w'], 1) if v['w'] else 0.0,
                        shading=('rounded' if v['wround'] >= 0.5 * v['w'] else 'faceted') if v['w'] else 'none')
        return dict(row(cand[0]), candidates=[row(c) for c in cand[:3]])

    def result(self, top=15, body=None):
        cl = self.classes
        tot = sum(cl.values()) or 1.0
        pa = np.concatenate(self.patch_areas) if self.patch_areas else np.zeros(1)
        ps = max(float(pa.sum()), 1e-12)
        shape = {DECADE_LABELS[i]: dict(count=int(((pa >= a) & (pa < b)).sum()), area_share=round(float(pa[(pa >= a) & (pa < b)].sum() / ps), 4))
                 for i, (a, b) in enumerate(DECADES)}
        allc = lambda v: sum(v[c] for c in CLASSES)
        med = None
        if self.widths:
            wm, ww = np.concatenate(self.widths), np.concatenate(self.weights)
            o = np.argsort(wm); cs = np.cumsum(ww[o]); med = round(float(wm[o][np.searchsorted(cs, cs[-1] / 2)]), 1)
        soft = cl['rounded'] + cl['facet']
        return dict(
            instances=self.inst, triangles=int(self.tris), size_m=[round(float(x), 3) for x in (self.hi - self.lo)] if self.inst else [0, 0, 0],
            corners_share={k: round(v / tot, 4) for k, v in cl.items()},
            corners_convex_share={k: round(self.convex[k] / max(cl[k], 1e-12), 3) for k in cl},
            corner_turn_metres=round(tot, 1),
            soft_edge_share=round(soft / max(soft + cl['razor'] + cl['blobby'], 1e-12), 4),
            strip_width_mm_share={WIDTH_LABELS[i]: round(float(x / max(self.width_hist.sum(), 1e-12)), 4) for i, x in enumerate(self.width_hist)},
            strip_width_vs_part_share={REL_LABELS[i]: round(float(x / max(self.rel_hist.sum(), 1e-12)), 4) for i, x in enumerate(self.rel_hist)},
            strip_width_median_mm=med, body_bevel=self.body(body),
            bevel_width_mm_share={WIDTH_LABELS[i]: round(float(x / max(self.full_hist.sum(), 1e-12)), 4) for i, x in enumerate(self.full_hist)},
            patches=dict(count=int(len(pa)), total_area_m2=round(float(pa.sum()), 2), largest_m2=[round(float(x), 3) for x in np.sort(pa)[::-1][:5]],
                         largest_share=round(float(pa.max() / ps), 4), by_size=shape),
            repetition=dict(meshes=len(self.mesh_tris), top=[(k, int(v), round(v / max(self.tris, 1), 3)) for k, v in self.mesh_tris.most_common(5)]),
            flat_shaded_area_share=round(self.flat[0] / max(self.flat[1], 1e-12), 4),
            parts_by_corner_length=[dict(part=k, instances=int(v['n']), tris=int(v['tris']), corner_m=round(allc(v), 1),
                                         flat_shaded=round(v['flat'] / max(v['area'], 1e-12), 2), mean_strip_mm=round(v['ww'] / v['w'], 1) if v['w'] else None,
                                         **{c: round(v[c] / max(allc(v), 1e-12), 2) for c in CLASSES})
                                    for k, v in sorted(self.parts.items(), key=lambda kv: -allc(kv[1]))[:top]],
            razor_by_part=[dict(part=k, instances=int(v['n']), tris=int(v['tris']), razor_m=round(v['razor'], 2),
                                razor_share_of_part=round(v['razor'] / max(allc(v), 1e-12), 3))
                           for k, v in sorted(self.parts.items(), key=lambda kv: -kv[1]['razor'])[:top]],
            facet_by_part=[dict(part=k, instances=int(v['n']), facet_m=round(v['facet'], 2))
                           for k, v in sorted(self.parts.items(), key=lambda kv: -kv[1]['facet'])[:5] if v['facet'] > 0],
            flat_by_part=[dict(part=k, instances=int(v['n']), flat_m2=round(v['flat'], 2))
                          for k, v in sorted(self.parts.items(), key=lambda kv: -kv[1]['flat'])[:5] if v['flat'] > 0])
