#!/usr/bin/env python3
"""look_metrics.py: numbers for what an eye judges, from the passes look_passes.py wrote (numpy + PIL, 1 s a view).

  python3 look_metrics.py DIR [--out DIR/metrics.json] [--overlay] [--length M] [--camera-set game|film] [--family NAME]

ADVISORY: a number outside its band means "look", never "fail"; the bands rest on 2 of our assets and 7 CC0 references
(none a rail vehicle) and the thresholds inside the measures were set by eye on 13 picture sets.

Per view, and averaged in `summary` (key: provisional band; our two originals; references):
  wear.base_colour_spread : >= 0.20   spread of base colour around each material's median, creases left out
                          (0 = every material one flat value). a train car 0.12, train car 0.19; references 0.25-0.41.
  wear.dark_in_cavities_corr : > 0.20  correlation of "darker than the material's median" with the AO pass: grime
                          where parts meet. 0.12 / -0.03; references up to 0.57. Weak on strongly textured materials.
  wear.dark_low_down_corr : > 0.20    the same against height: road and wheel film. 0.20 / -0.05; up to 0.61.
  materials.top[0].variation : >= 0.12  variation inside the material covering most of the picture (summary:
                          largest_material_variation). The a train car's aluminium: 0.05-0.06 over 37-52 % of the view.
  detail.rest_cells     : 0.20-0.35   share of 32 px cells of the asset with almost no luminance edges (< 2 % of
                          their pixels): calm areas. train car 0.05, a train car 0.17; ToyCar 0.32, CoffeeCart 0.26.
  detail.busy_cells     : <= 0.55     share of cells where > 20 % of pixels are edges. 0.75 / 0.66; 0.32-0.53.
  silhouette.filled.hull_breaking_features : >= 3 in the SIDE view (summary: hull_features_side); at_<D>m the same at
                          the size the asset has at the distance D where the mid / far version appears
                          (summary hull_features_side_mid : >= 2). a train car 0, train car 5; references 3-16.
  silhouette.filled.hull_fill          mask area / convex hull area; no band (0.97 and 0.95 = "a box"; refs 0.28-0.93).
  No band, pointers only: edges.light_line (share of convex creases that show a light line; moves 0.03-0.05 with
  wide bevels and depends on gloss), detail.orientation_entropy (how many directions the detail runs in; flags
  flutes), dead.share (cells with no variation at all), materials.effective_count, tonal_range_Lstar.

--overlay writes <view>-look.jpg: green = convex crease with a light line, red = convex crease without,
blue = concave crease with a dark line, magenta wash = dead cells.
--length M: the asset's length for the at-distance silhouettes (default: its longest horizontal size).
"""
import sys, os, json, math, re
import numpy as np

CELL = 32                 # px, the detail cell
DETAIL_EDGE = 2.5         # Sobel magnitude (L*) from which a pixel counts as a luminance edge
REST_DENSITY = 0.02       # a cell with a smaller share of edge pixels is a rest cell
BUSY_DENSITY = 0.20       # a cell with a larger share is a busy cell
DEAD_STD = 0.6            # high-passed L* std under which a cell is dead
NOTCH_MIN = 0.004         # a hull notch counts as a feature from this share of the hull area
CREASE_DEG = 30.0
LINE_L = 4.0              # L* a crease must stand out by to count as a light (or dark) line


def lstar(rgb8):
    c = rgb8.astype(np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    y = lin @ np.array([0.2126, 0.7152, 0.0722])
    return np.where(y > 0.008856, 116 * np.cbrt(y) - 16, 903.3 * y)


def box(a, r):
    """Box blur radius r by cumulative sums (edge-padded)."""
    k = 2 * r + 1
    p = np.pad(a, ((r, r), (r, r)), mode='edge')
    c = np.cumsum(np.cumsum(p, 0), 1); c = np.pad(c, ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def sobel(L):
    p = np.pad(L, 1, mode='edge')
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:] - p[:-2, :-2] - 2 * p[1:-1, :-2] - p[2:, :-2]) / 8
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:] - p[:-2, :-2] - 2 * p[:-2, 1:-1] - p[:-2, 2:]) / 8
    return gx, gy


def gini(x):
    x = np.sort(np.asarray(x, float)); n = len(x)
    if n == 0 or x.sum() == 0:
        return 0.0
    return float((2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum()))


def hull(mask):
    """Convex hull of a mask's pixel corners -> (area in px, hull points)."""
    ys, xs = np.nonzero(mask)
    pts = set()
    for y in np.unique(ys):                                 # leftmost / rightmost per row is enough for the hull
        r = xs[ys == y]
        pts.update(((int(r.min()), int(y)), (int(r.max()) + 1, int(y)), (int(r.min()), int(y) + 1), (int(r.max()) + 1, int(y) + 1)))
    pts = sorted(pts)

    def half(ps):
        h = []
        for p in ps:
            while len(h) >= 2 and (h[-1][0] - h[-2][0]) * (p[1] - h[-2][1]) - (h[-1][1] - h[-2][1]) * (p[0] - h[-2][0]) <= 0:
                h.pop()
            h.append(p)
        return h
    h = half(pts)[:-1] + half(pts[::-1])[:-1]
    a = 0.0
    for i in range(len(h)):
        x0, y0 = h[i]; x1, y1 = h[(i + 1) % len(h)]
        a += x0 * y1 - x1 * y0
    return abs(a) / 2, h


def hull_mask(shape, h):
    """Rasterise the convex polygon h (list of (x, y))."""
    H, W = shape
    yy, xx = np.mgrid[0:H, 0:W]; cx, cy = xx + 0.5, yy + 0.5
    inside = np.ones(shape, bool)
    s = sum(h[i][0] * h[(i + 1) % len(h)][1] - h[(i + 1) % len(h)][0] * h[i][1] for i in range(len(h)))
    sign = 1 if s > 0 else -1
    for i in range(len(h)):
        x0, y0 = h[i]; x1, y1 = h[(i + 1) % len(h)]
        inside &= sign * ((x1 - x0) * (cy - y0) - (y1 - y0) * (cx - x0)) >= 0
    return inside


def components(grid):
    """4-connected components of a small boolean grid -> list of sizes."""
    g = grid.copy(); H, W = g.shape; out = []
    for y, x in zip(*np.nonzero(g)):
        if not g[y, x]:
            continue
        n, st = 0, [(y, x)]; g[y, x] = False
        while st:
            a, b = st.pop(); n += 1
            for c, d in ((a + 1, b), (a - 1, b), (a, b + 1), (a, b - 1)):
                if 0 <= c < H and 0 <= d < W and g[c, d]:
                    g[c, d] = False; st.append((c, d))
        out.append(n)
    return out


def silhouette(mask, scale=1):
    """Outline measures of a mask, optionally shrunk `scale` times first (the asset further away)."""
    if scale > 1:
        H, W = mask.shape; h, w = H // scale, W // scale
        m = mask[:h * scale, :w * scale].reshape(h, scale, w, scale).mean((1, 3)) >= 0.5
    else:
        m = mask
    area = int(m.sum())
    if area < 12:
        return dict(px=area)
    p = np.pad(m, 1)
    per = int((m & ~(p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:])).sum())
    ha, h = hull(m)
    notch = hull_mask(m.shape, h) & ~m
    comps = [c for c in components(notch) if c >= NOTCH_MIN * ha]
    ys, xs = np.nonzero(m)
    return dict(px=area, width_px=int(xs.max() - xs.min() + 1), hull_fill=round(area / max(ha, 1), 4),
                compactness=round(per * per / (4 * math.pi * area), 2), hull_breaking_features=len(comps),
                notch_share=round(float(notch.sum()) / max(ha, 1), 4))


def cells(det, mask, cell):
    """Per cell: share of its asset pixels that are `det` (nan where under 60 % of the cell is asset), and that test."""
    h, w = (det.shape[0] // cell) * cell, (det.shape[1] // cell) * cell
    dm = det[:h, :w].reshape(h // cell, cell, w // cell, cell).sum((1, 3)).astype(float)
    mm = mask[:h, :w].reshape(h // cell, cell, w // cell, cell).sum((1, 3)).astype(float)
    ok = mm >= 0.6 * cell * cell
    return np.where(ok, dm / np.maximum(mm, 1), np.nan), ok


def detail(L, mask):
    """Where the picture's detail sits. Returns (numbers, cell-ok grid, edge strength, inner mask)."""
    gx, gy = sobel(L); E = np.hypot(gx, gy)
    inner = mask & np.roll(mask, 2, 0) & np.roll(mask, -2, 0) & np.roll(mask, 2, 1) & np.roll(mask, -2, 1)
    det = (E > DETAIL_EDGE) & inner
    dens, okc = cells(det, inner, CELL)
    dv = dens[okc]
    ang = (np.arctan2(gy, gx) % math.pi)[det]; wgt = E[det]
    hist = np.histogram(ang, bins=8, range=(0, math.pi), weights=wgt)[0]; hp = hist / max(hist.sum(), 1e-9)
    ent = float(-(hp[hp > 0] * np.log(hp[hp > 0])).sum() / math.log(8))
    H, W = L.shape; h4, w4 = H // 4 * 4, W // 4 * 4            # the same at 1/4 size (the mid distance)
    L4 = L[:h4, :w4].reshape(h4 // 4, 4, w4 // 4, 4).mean((1, 3)); m4 = inner[:h4, :w4].reshape(h4 // 4, 4, w4 // 4, 4).mean((1, 3)) > 0.9
    g4x, g4y = sobel(L4); det4 = (np.hypot(g4x, g4y) > DETAIL_EDGE) & m4
    d4, ok4 = cells(det4, m4, CELL // 4)
    out = dict(cells=int(okc.sum()), mean_density=round(float(dv.mean()) if len(dv) else 0, 4),
               rest_cells=round(float((dv < REST_DENSITY).mean()) if len(dv) else 0, 3),
               busy_cells=round(float((dv > BUSY_DENSITY).mean()) if len(dv) else 0, 3), gini=round(gini(dv), 3),
               orientation_entropy=round(ent, 3), top_direction_share=round(float(hp.max()), 3),
               mid_mean_density=round(float(d4[ok4].mean()) if ok4.any() else 0, 4), mid_gini=round(gini(d4[ok4]), 3))
    return out, okc


def dead(L, okc):
    """Cells with no visible variation at all. Returns (numbers, dead grid, high-passed L*)."""
    H, W = L.shape
    hp_L = L - box(L, 8)
    v = box(hp_L * hp_L, 8)
    h, w = (H // CELL) * CELL, (W // CELL) * CELL
    sd = np.sqrt(v[:h, :w].reshape(h // CELL, CELL, w // CELL, CELL).mean((1, 3)))
    dd = okc & (sd < DEAD_STD)
    comps = components(dd); ncell = max(int(okc.sum()), 1)
    return dict(share=round(dd.sum() / ncell, 3), largest_region=round(max(comps) / ncell if comps else 0, 3),
                regions=len(comps), median_cell_std_Lstar=round(float(np.median(sd[okc])) if okc.any() else 0, 2)), dd, hp_L


def creases(N, P, mask, L, mpp):
    """Creases from the normal pass and whether the picture shows them. Returns (numbers, masks for the overlay)."""
    H, W = mask.shape
    nn = N / np.maximum(np.linalg.norm(N, axis=-1, keepdims=True), 1e-9)
    S = 2                                                  # compare pixels 2 apart, the crease is between them
    cv = np.zeros((H, W), bool); cc = np.zeros((H, W), bool); axis_of = np.zeros((H, W), np.int8)
    for ax in (0, 1):
        sl_a = (slice(None), slice(0, W - S)) if ax == 1 else (slice(0, H - S), slice(None))
        sl_b = (slice(None), slice(S, W)) if ax == 1 else (slice(S, H), slice(None))
        sl_m = (slice(None), slice(S // 2, W - S // 2)) if ax == 1 else (slice(S // 2, H - S // 2), slice(None))
        both = mask[sl_a] & mask[sl_b]
        cosang = (nn[sl_a] * nn[sl_b]).sum(-1)
        dP = P[sl_b] - P[sl_a]
        cont = np.linalg.norm(dP, axis=-1) < 5 * S * mpp
        turn = both & cont & (cosang < math.cos(math.radians(CREASE_DEG)))
        conv = ((nn[sl_b] - nn[sl_a]) * dP).sum(-1) > 0
        cv[sl_m] |= turn & conv; cc[sl_m] |= turn & ~conv
        axis_of[sl_m] = np.where(turn, ax + 1, axis_of[sl_m])

    def cross(off):
        """L sampled `off` px across the crease (along the axis the crease was found on)."""
        a = np.roll(L, -off, axis=1); b = np.roll(L, -off, axis=0)
        ma = np.roll(mask, -off, axis=1); mb = np.roll(mask, -off, axis=0)
        return np.where(axis_of == 2, a, b), np.where(axis_of == 2, ma, mb)
    centre = np.stack([cross(o)[0] for o in (-1, 0, 1)])
    side_a = np.stack([cross(o)[0] for o in (-6, -5, -4)]).mean(0); ok_a = cross(-6)[1]
    side_b = np.stack([cross(o)[0] for o in (4, 5, 6)]).mean(0); ok_b = cross(6)[1]
    d_light = centre.max(0) - np.maximum(side_a, side_b); d_dark = centre.min(0) - np.minimum(side_a, side_b)
    valid = ok_a & ok_b
    cvv, ccv = cv & valid, cc & valid
    light = cvv & (d_light >= LINE_L); dark_cc = ccv & (d_dark <= -LINE_L)
    step = cvv & ~light & (np.abs(side_a - side_b) >= LINE_L)
    nothing = cvv & ~light & ~step
    n = max(int(cvv.sum()), 1)
    out = dict(convex_px=int(cvv.sum()), convex_share_of_asset=round(cvv.sum() / max(mask.sum(), 1), 4),
               light_line=round(light.sum() / n, 3), tone_step_only=round(step.sum() / n, 3), invisible=round(nothing.sum() / n, 3),
               median_gain_Lstar=round(float(np.median(d_light[cvv])) if cvv.any() else 0, 2),
               concave_px=int(ccv.sum()), concave_dark_line=round(dark_cc.sum() / max(int(ccv.sum()), 1), 3))
    return out, dict(cv=cv, cc=cc, light=light, step=step, nothing=nothing, dark_cc=dark_cc)


def base_luma(dif, glo):
    """Base colour whatever the metalness (diffuse colour + glossy colour passes), as luminance."""
    return (dif + glo) @ np.array([0.2126, 0.7152, 0.0722], np.float32)


def materials(aY, mat, mask, names, crease, L, hp_L):
    """Per material: share of the picture and variation of its base colour. Returns (numbers, residual, its mask):
    residual = (base luma - the material's median) / median per pixel, outside creases."""
    raw_ids, inv = np.unique(mat.astype(int), return_inverse=True)
    base = [re.sub(r'\.\d{3}$', '', names.get(str(i), str(i))) for i in raw_ids]       # one material linked from many libraries
    uniq = sorted(set(base)); remap = np.array([uniq.index(b) for b in base])
    mat = remap[inv].reshape(mat.shape); names = {str(i): u for i, u in enumerate(uniq)}
    ids, counts = np.unique(mat[mask].astype(int), return_counts=True)
    share = counts / counts.sum(); order = np.argsort(-share)
    mats = []
    resid = np.zeros(mask.shape, np.float32); rmask = np.zeros(mask.shape, bool)
    for i in order[:8]:
        m = mask & (mat.astype(int) == ids[i])
        vals = aY[m]; med = float(np.median(vals))
        if med > 1e-4:
            resid[m] = (aY[m] - med) / med; rmask |= m & ~crease
        mats.append(dict(material=names.get(str(ids[i]), str(ids[i])), share=round(float(share[i]), 3),
                         base_luma=round(med, 3), variation=round(float(np.std(vals) / max(med, 1e-4)), 3),
                         picture_std_Lstar=round(float(np.std(hp_L[m])), 2)))
    Lm = L[mask]
    out = dict(effective_count=round(float(np.exp(-(share * np.log(share)).sum())), 2), largest_share=round(float(share.max()), 3),
               tonal_range_Lstar=round(float(np.percentile(Lm, 95) - np.percentile(Lm, 5)), 1), top=mats[:6])
    return out, resid, rmask


def spread(resid, rmask):
    """Spread of base colour inside materials: std of the residual (outliers beyond +-0.9 left out)."""
    rm = rmask & (np.abs(resid) < 0.9)
    return (round(float(np.std(resid[rm])), 4) if rm.any() else 0.0), rm


def wear(resid, rmask, ao, height, convex):
    """Where the base colour departs from flat: against cavity (AO pass), height and nearness to a convex crease."""
    s, rm = spread(resid, rmask)
    out = dict(base_colour_spread=s)
    if rm.sum() > 500:
        def corr(a, b):
            a = a - a.mean(); b = b - b.mean()
            d = math.sqrt(float((a * a).sum() * (b * b).sum()))
            return round(float((a * b).sum() / d), 3) if d > 0 else 0.0
        near_edge = box(convex.astype(np.float64), 3) > 0
        out['dark_in_cavities_corr'] = corr(resid[rm], ao[rm])          # > 0: darker where occluded
        out['dark_low_down_corr'] = corr(resid[rm], height[rm])         # > 0: darker toward the bottom
        e, f = rm & near_edge, rm & ~near_edge
        out['edge_minus_field'] = round(float(resid[e].mean() - resid[f].mean()), 4) if e.sum() > 50 else None
    return out


def view_metrics(z, meta, png, length_m=None, distances=(), overlay_path=None):
    """z: the pass arrays of one view (normal, position, obj, mat, diffcol, glosscol, ao), top row first."""
    H, W = png.shape[:2]
    N, P, obj, mat = z['normal'], z['position'], z['obj'][..., 0], z['mat'][..., 0]
    ao = z['ao'].mean(-1)
    mask = obj > 0.5
    L = lstar(png)
    out = dict(view=meta['view'], asset_px=int(mask.sum()))
    dpx = np.linalg.norm(P[:, 1:] - P[:, :-1], axis=-1)[mask[:, 1:] & mask[:, :-1]]
    mpp = float(np.median(dpx)) if len(dpx) else 0.01
    out['mm_per_px'] = round(mpp * 1000, 1)
    out['edges'], cr = creases(N, P, mask, L, mpp)
    out['detail'], okc = detail(L, mask)
    out['dead'], dd, hp_L = dead(L, okc)
    width_px = float(np.ptp(np.nonzero(mask)[1]) + 1) if mask.any() else 1
    sil = {'filled': silhouette(mask)}
    if length_m:
        k = meta.get('m_per_px_per_m', 0.000674)
        for dist in distances:
            target = length_m / (dist * k)                 # px the asset's length takes on the game screen there
            sc_ = max(1, int(round(width_px / target)))
            sil['at_%dm' % dist] = dict(scale_down=sc_, **silhouette(mask, sc_))
    out['silhouette'] = sil
    out['materials'], resid, rmask = materials(base_luma(z['diffcol'], z['glosscol']), mat, mask, meta.get('mat_names', {}),
                                               cr['cv'] | cr['cc'], L, hp_L)
    out['wear'] = wear(resid, rmask, ao, P[..., 2], cr['cv'])
    if overlay_path:
        from PIL import Image
        im = png.astype(np.float32)
        dm = np.kron(dd, np.ones((CELL, CELL), bool)); dm = np.pad(dm, ((0, H - dm.shape[0]), (0, W - dm.shape[1])))
        im[dm] = im[dm] * 0.6 + np.array([255, 0, 255]) * 0.4
        fat = lambda m: m | np.roll(m, 1, 0) | np.roll(m, 1, 1)
        im[fat(cr['nothing'] | cr['step'])] = [255, 40, 40]; im[fat(cr['light'])] = [40, 230, 60]; im[fat(cr['dark_cc'])] = [60, 120, 255]
        Image.fromarray(im.clip(0, 255).astype(np.uint8)).save(overlay_path, quality=88)
    return out


def summary(V):
    mean = lambda f: round(float(np.mean([f(v) for v in V])), 3)
    s = dict(
        edge_light_line=mean(lambda v: v['edges']['light_line']), edge_invisible=mean(lambda v: v['edges']['invisible']),
        concave_dark_line=mean(lambda v: v['edges']['concave_dark_line']),
        detail_density=mean(lambda v: v['detail']['mean_density']), detail_gini=mean(lambda v: v['detail']['gini']),
        rest_cells=mean(lambda v: v['detail']['rest_cells']), busy_cells=mean(lambda v: v['detail']['busy_cells']),
        orientation_entropy=mean(lambda v: v['detail']['orientation_entropy']),
        dead_share=mean(lambda v: v['dead']['share']), dead_largest=mean(lambda v: v['dead']['largest_region']),
        hull_fill=mean(lambda v: v['silhouette']['filled']['hull_fill']),
        hull_features=mean(lambda v: v['silhouette']['filled']['hull_breaking_features']),
        materials_effective=mean(lambda v: v['materials']['effective_count']), tonal_range=mean(lambda v: v['materials']['tonal_range_Lstar']),
        base_colour_spread=mean(lambda v: v['wear']['base_colour_spread']),
        dark_in_cavities=mean(lambda v: v['wear'].get('dark_in_cavities_corr') or 0),
        dark_low_down=mean(lambda v: v['wear'].get('dark_low_down_corr') or 0),
        edge_minus_field=mean(lambda v: v['wear'].get('edge_minus_field') or 0),
        largest_material_variation=mean(lambda v: v['materials']['top'][0]['variation']))
    side = next((v for v in V if v['view'].startswith('side')), None)
    if side:
        s['hull_features_side'] = side['silhouette']['filled']['hull_breaking_features']
        at = sorted((k for k in side['silhouette'] if k.startswith('at_')), key=lambda k: int(k[3:-1]))
        if at and 'hull_breaking_features' in side['silhouette'][at[0]]:
            s['hull_features_side_mid'] = side['silhouette'][at[0]]['hull_breaking_features']
            s['hull_features_side_mid_at'] = at[0]
    return s


def measure_dir(d, length_m=None, distances=(), overlay=False):
    """Every <view>.npz + <view>.png in d -> dict(dir, views, summary)."""
    from PIL import Image
    views = []
    for f in sorted(x for x in os.listdir(d) if x.endswith('.npz')):
        path = os.path.join(d, f)
        z = np.load(path, allow_pickle=False)
        meta = json.loads(str(z['meta']))
        png = np.asarray(Image.open(path[:-4] + '.png').convert('RGB'))
        ln = length_m or max(abs(meta['bounds_hi'][0] - meta['bounds_lo'][0]), abs(meta['bounds_hi'][1] - meta['bounds_lo'][1]))
        views.append(view_metrics(z, meta, png, ln, distances, path[:-4] + '-look.jpg' if overlay else None))
        views[-1]['length_m'] = round(float(ln), 3)
    return dict(dir=os.path.abspath(d), views=views, summary=summary(views))


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__); return 0
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import bands
    get = lambda k, dflt=None: argv[argv.index(k) + 1] if k in argv else dflt
    d = argv[0]
    cam = bands.camera(get('--camera-set', 'game'), get('--family'))
    res = measure_dir(d, float(get('--length')) if get('--length') else None, cam['silhouette_distances_m'], '--overlay' in argv)
    res['camera'] = cam
    with open(get('--out', os.path.join(d, 'metrics.json')), 'w') as f:
        f.write(json.dumps(res, indent=1) + '\n')
    print('LOOK_METRICS', json.dumps(res['summary']))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
