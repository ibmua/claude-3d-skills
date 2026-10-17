"""proportion_overlay.py: fit a camera to ONE reference view by its outline and measure where the model differs. 2-5 s.

  python3 proportion_overlay.py MODEL.blend|.glb --ref PICTURE --out OUT.jpg [--view side|34] [--crop x0,y0,x1,y1]
          [--ignore x0,y0,x1,y1 ...] [--bg-tol 14] [--ref-mask MASK.png] [--start side,front34,...] [--ortho]
          [--collection NAME] [--front +x] [--selftest]
  (the same under Blender: blender -b --factory-startup -noaudio -t 8 --python proportion_overlay.py -- ARGS)

The reference is one view of the thing on a plain background (a concept panel, a cut-out photo). --crop picks the
panel, --ignore boxes (in crop pixels) blank what is not the thing (a figure, a stand). Its outline is found by
flooding the background from the picture's border (colour within --bg-tol of the border colour; white on cream needs
about 6), or given as --ref-mask.
--view side  = start from the two side views with an orthographic camera (an elevation drawing);
--view 34    = start from the front and rear three-quarter views with a perspective camera.
Without --view or --start it tries side, front34, rear34, front, rear, top.

What the numbers mean (OUT.json; ADVISORY, "look" never "fail"):
  iou                          overlap of the model's outline with the reference's at the fitted camera (1 = same).
                               Under about 0.85 the fit or the cut-out is wrong: look at OUT.jpg first (the yellow
                               line is what was taken as the reference outline).
  reference_height_for_length_vs_model_pct : band -2..+2   after the fit one more freedom is opened, a separate
                               stretch in picture x and y; this is how much taller for its length the reference is
                               than the model. The tool's own noise is about 1 % (--selftest measures it).
                               a train car against its concept's flank elevation: -0.7 (the envelope is right).
  profile                      top and bottom outline along the length in ten bands, model minus reference, in
                               percent of the reference's height: WHERE the outline differs (roof pods, skirts).
  camera                       the fitted camera; distance is not recoverable from an outline (a side view cannot
                               give the lens).
OUT.jpg: the reference with the model outline in cyan and the reference outline in yellow; red = model outside the
reference, blue = reference outside the model. It sees outlines only: not window bands, belt lines or door positions.
"""
import sys, os, json, math, time, subprocess, tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _run  # noqa: E402
try:
    import bpy
except ImportError:
    bpy = None

GW = 240                                                   # working mask width, px
argv = _run.tool_argv()


def arg(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def args_all(name):
    return [argv[i + 1] for i, a in enumerate(argv) if a == name]


def surface_points(limit=90000):
    pts = []
    dg = bpy.context.evaluated_depsgraph_get()
    for inst in dg.object_instances:
        ob = inst.object
        if ob.type != 'MESH' or ob.name.startswith('RT_'):
            continue
        me = ob.data
        if not len(me.polygons):
            continue
        M = np.array(inst.matrix_world)
        co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
        # triangle centres and edge midpoints as well, so big faces are not empty
        lv = np.empty(len(me.loops), np.int64); me.loops.foreach_get('vertex_index', lv)
        me.calc_loop_triangles()
        tri = np.empty(len(me.loop_triangles) * 3, np.int64); me.loop_triangles.foreach_get('vertices', tri); tri = tri.reshape(-1, 3)
        a, b, c = co[tri[:, 0]], co[tri[:, 1]], co[tri[:, 2]]
        area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
        n = np.minimum(np.ceil(area / 0.0015).astype(int), 400)          # one point per ~15 cm2
        idx = np.repeat(np.arange(len(tri)), n)
        r = np.random.default_rng(1).random((len(idx), 2)); s = np.sqrt(r[:, 0:1]); t = r[:, 1:2]
        pts.append((1 - s) * a[idx] + s * (1 - t) * b[idx] + s * t * c[idx]); pts.append(co)
    P = np.concatenate(pts)
    if len(P) > limit:
        P = P[np.random.default_rng(2).choice(len(P), limit, replace=False)]
    return P


def close(m, r=2):
    """Fill the gaps between splatted points: dilate r then erode r."""
    def dil(x, k):
        o = x.copy()
        for _ in range(k):
            p = np.pad(o, 1); o = p[1:-1, 1:-1] | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
        return o
    d = dil(m, r)
    return ~dil(~d, r)


def fill_outside(m):
    """Solid outline: everything not reachable from the border through empty pixels."""
    H, W = m.shape
    out = np.zeros_like(m); out[0, :] = ~m[0, :]; out[-1, :] = ~m[-1, :]; out[:, 0] = ~m[:, 0]; out[:, -1] = ~m[:, -1]
    while True:
        p = np.pad(out, 1)
        new = (p[1:-1, 1:-1] | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]) & ~m
        if (new == out).all():
            break
        out = new
    return ~out


def project(P, c, q, shape, stretch=(1.0, 1.0)):
    az, el, logd, zoom, tx, ty = q
    H, W = shape
    d = math.exp(logd)
    dirv = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])   # centre -> camera
    right = np.array([-math.sin(az), math.cos(az), 0.0]); up = np.cross(dirv, right)
    p = P - c
    z = d - p @ dirv
    x = zoom * d * (p @ right) / z * stretch[0]; y = zoom * d * (p @ up) / z * stretch[1]
    u = (W / 2 + tx + x).astype(int); v = (H / 2 + ty - y).astype(int)
    ok = (u >= 0) & (u < W) & (v >= 0) & (v < H) & (z > 0.05)
    m = np.zeros(shape, bool); m[v[ok], u[ok]] = True
    return fill_outside(close(m))


def iou(a, b):
    return float((a & b).sum()) / max(float((a | b).sum()), 1.0)


def fit(P, c, ref, starts, ortho):
    size = float(np.linalg.norm(P.max(0) - P.min(0)))
    ys, xs = np.nonzero(ref); rw = xs.max() - xs.min() + 1
    best = None
    for az0, el0 in starts:
        q = np.array([az0, el0, math.log(size * (60 if ortho else 3.0)), rw / (size * 0.9), (xs.mean() - ref.shape[1] / 2), (ys.mean() - ref.shape[0] / 2)])
        step = np.array([math.radians(12), math.radians(8), 0.0 if ortho else 0.5, 0.12 * q[3], 8.0, 8.0])
        s = iou(project(P, c, q, ref.shape), ref)
        for it in range(60):
            improved = False
            for k in range(6):
                if step[k] == 0:
                    continue
                for sg in (1, -1):
                    t = q.copy(); t[k] += sg * step[k]
                    t[1] = min(max(t[1], math.radians(-30)), math.radians(89)); t[2] = max(t[2], math.log(size * 0.8))
                    st = iou(project(P, c, t, ref.shape), ref)
                    if st > s + 1e-5:
                        q, s, improved = t, st, True
                        break
            if not improved:
                step *= 0.5
                if step[0] < math.radians(0.15):
                    break
        if best is None or s > best[1]:
            best = (q, s)
    return best


def fit_stretch(P, c, ref, q):
    best = (1.0, 1.0); s0 = s = iou(project(P, c, q, ref.shape), ref)
    step = 0.06
    while step > 0.004:
        improved = False
        for k in (0, 1):
            for sg in (1, -1):
                t = list(best); t[k] *= (1 + sg * step)
                # re-centre: let shift follow
                qq = q.copy()
                st = max(iou(project(P, c, qq + np.array([0, 0, 0, 0, dx, dy]), ref.shape, t), ref) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
                if st > s + 1e-5:
                    best, s, improved = tuple(t), st, True
                    break
        if not improved:
            step *= 0.5
    return best, s0, s


def ref_mask(Image, path, crop, ignores, tol, gw):
    im = Image.open(path).convert('RGB')
    if crop:
        im = im.crop(tuple(crop))
    sc = gw / im.width
    small = im.resize((gw, max(8, int(round(im.height * sc)))), Image.LANCZOS)
    a = np.asarray(small).astype(np.int32)
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]); bg = np.median(border, 0)
    like = np.abs(a - bg).sum(-1) < tol * 3
    # shadows of the background colour: same hue, darker
    lum = a.sum(-1) / 3.0; chroma = a - lum[..., None]; bgc = bg - bg.mean()
    like |= (np.abs(chroma - bgc).sum(-1) < tol * 1.5) & (lum > bg.mean() * 0.55) & (np.abs(bgc).sum() > 12)
    m = fill_outside(~like)
    for bx in ignores:
        x0, y0, x1, y1 = [int(round(v * sc)) for v in bx]; m[y0:y1, x0:x1] = False
    # keep the largest blob only
    lab = np.zeros(m.shape, int); best, n = None, 0
    todo = m.copy()
    while todo.any():
        y, x = np.argwhere(todo)[0]; st = [(y, x)]; todo[y, x] = False; px = []
        while st:
            cy, cx = st.pop(); px.append((cy, cx))
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < m.shape[0] and 0 <= nx < m.shape[1] and todo[ny, nx]:
                    todo[ny, nx] = False; st.append((ny, nx))
        if len(px) > n:
            n, best = len(px), px
    out = np.zeros(m.shape, bool)
    for y, x in best or []:
        out[y, x] = True
    return out, im, sc


def profiles(ref, mod):
    """Top and bottom outline along the length, both masks, in percent of the reference's height."""
    ys, xs = np.nonzero(ref); x0, x1 = xs.min(), xs.max(); h = ys.max() - ys.min() + 1
    cols = np.linspace(x0, x1, 11).astype(int)
    rows = []
    for a, b in zip(cols[:-1], cols[1:]):
        def ext(m):
            sub = m[:, a:b + 1]; yy = np.nonzero(sub.any(1))[0]
            return (int(yy.min()), int(yy.max())) if len(yy) else (None, None)
        (rt, rb), (mt, mb) = ext(ref), ext(mod)
        rows.append(dict(along='%d-%d%%' % (round(100 * (a - x0) / (x1 - x0)), round(100 * (b - x0) / (x1 - x0))),
                         top_model_minus_ref_pct=None if None in (rt, mt) else round(100 * (rt - mt) / h, 1),
                         bottom_model_minus_ref_pct=None if None in (rb, mb) else round(100 * (mb - rb) / h, 1)))
    return rows


def blender_half():
    """Load the model through the shared render.py, write its surface points, hand over to plain python3 (PIL)."""
    import io, contextlib
    src = os.path.abspath(argv[0]); out = os.path.abspath(arg('--out'))
    real_argv = sys.argv; sys.argv = real_argv[:real_argv.index('--') + 1]
    sys.path.insert(0, _run.KIT)
    with contextlib.redirect_stdout(io.StringIO()):
        import render as R
    sys.argv = real_argv
    A = R.parse(['thumb', src, '--front=' + arg('--front', '+x')] + (['--collection', arg('--collection')] if arg('--collection') else []))
    A.hide_globs = []; A.sky = 'auto'
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.app.handlers.save_pre.append(R.refuse_save)
    R.load(src, A, 'RT_asset_0'); bpy.context.view_layer.update()
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    d = tempfile.mkdtemp(prefix='overlay-', dir=os.path.dirname(out))
    f = os.path.join(d, 'points.npz')
    np.savez(f, P=surface_points().astype(np.float32), views=json.dumps({k: list(v[:2]) for k, v in R.VIEWS.items()}),
             front_az=R.FRONT_AZ[A.front])
    rc = subprocess.call(['python3', os.path.abspath(__file__)] + argv + ['--points', f])
    os.remove(f); os.rmdir(d)
    return rc


def fit_half():
    from PIL import Image
    t0 = time.time()
    src = os.path.abspath(argv[0]); out = os.path.abspath(arg('--out'))
    z = np.load(arg('--points')); P = z['P'].astype(np.float64); c = (P.min(0) + P.max(0)) / 2
    V = json.loads(str(z['views'])); faz = float(z['front_az'])
    view = arg('--view')
    truth = None
    if '--selftest' in argv:
        name = (arg('--start') or ('side' if view == 'side' else 'front34')).split(',')[0]
        az, el = math.radians(V[name][0] + faz + 7.0), math.radians(V[name][1] + 4.0)
        size = float(np.linalg.norm(P.max(0) - P.min(0)))
        truth = np.array([az, el, math.log(size * 2.2), GW * 0.8 / size, 5.0, -3.0])
        ref = project(P, c, truth, (GW * 3 // 4, GW)); im = Image.fromarray((ref * 255).astype(np.uint8)).convert('RGB'); sc = 1.0
    elif arg('--ref-mask'):
        mk = Image.open(arg('--ref-mask')).convert('L'); sc = GW / mk.width
        ref = np.asarray(mk.resize((GW, int(mk.height * sc)))) > 127; im = Image.open(arg('--ref')).convert('RGB')
    else:
        crop = [int(x) for x in arg('--crop').split(',')] if arg('--crop') else None
        ref, im, sc = ref_mask(Image, arg('--ref'), crop, [[float(x) for x in s.split(',')] for s in args_all('--ignore')], float(arg('--bg-tol', 14)), GW)
    if not ref.any():
        print('OVERLAY ERROR no outline found in the reference (try --bg-tol or --ref-mask)'); return 2
    names = arg('--start').split(',') if arg('--start') else {'side': ['side'], '34': ['front34', 'rear34']}.get(view, ['side', 'front34', 'rear34', 'front', 'rear', 'top'])
    starts = [(math.radians(V[n][0] + faz + off), math.radians(V[n][1])) for n in names for off in ((0, 180) if n == 'side' else (0,))]
    ortho = '--ortho' in argv or (view == 'side' and truth is None)
    q, s = fit(P, c, ref, starts, ortho)
    stretch, s0, s1 = fit_stretch(P, c, ref, q)
    mod = project(P, c, q, ref.shape)
    res = dict(model=src, reference=arg('--ref'), iou=round(s, 4), iou_with_stretch=round(s1, 4),
               stretch_x=round(stretch[0], 4), stretch_y=round(stretch[1], 4),
               reference_height_for_length_vs_model_pct=round(100 * (stretch[1] / stretch[0] - 1), 1),
               camera=dict(azimuth_deg=round(math.degrees(q[0]) % 360, 2), elevation_deg=round(math.degrees(q[1]), 2),
                           distance_m=round(math.exp(q[2]), 2), zoom_px_per_m_at_centre=round(q[3] / sc, 3),
                           shift_px=[round(q[4] / sc, 1), round(q[5] / sc, 1)], look_at=[round(float(x), 3) for x in c], ortho=ortho),
               profile=profiles(ref, mod), seconds=round(time.time() - t0, 1))
    if truth is not None:
        res['selftest'] = dict(azimuth_error_deg=round(math.degrees(abs(q[0] - truth[0])), 2), elevation_error_deg=round(math.degrees(abs(q[1] - truth[1])), 2),
                               distance_ratio=round(math.exp(q[2] - truth[2]), 3), zoom_ratio=round(q[3] / truth[3], 4))
    big = im.copy(); W, H = big.size
    up = lambda m: np.asarray(Image.fromarray((m * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR)) > 127
    M, Rf = up(mod), up(ref)
    a = np.asarray(big).astype(np.float32)
    a[M & ~Rf] = a[M & ~Rf] * 0.45 + np.array([255, 40, 40]) * 0.55
    a[Rf & ~M] = a[Rf & ~M] * 0.45 + np.array([40, 90, 255]) * 0.55
    p = np.pad(M, 2); edge = M & ~(p[4:, 2:-2] & p[:-4, 2:-2] & p[2:-2, 4:] & p[2:-2, :-4])
    a[edge] = [0, 230, 230]
    p = np.pad(Rf, 1); redge = Rf & ~(p[2:, 1:-1] & p[:-2, 1:-1] & p[1:-1, 2:] & p[1:-1, :-2])
    a[redge] = [255, 220, 0]                               # what was taken as the reference outline
    o = Image.fromarray(a.clip(0, 255).astype(np.uint8))
    if o.width > 1280:
        o = o.resize((1280, int(o.height * 1280 / o.width)), Image.LANCZOS)
    o.save(out, quality=90)
    with open(os.path.splitext(out)[0] + '.json', 'w') as f:
        json.dump(res, f, indent=1)
    print('OVERLAY', json.dumps({k: v for k, v in res.items() if k != 'profile'}), flush=True)
    return 0


if __name__ == '__main__':
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__); sys.exit(0)
    try:
        if bpy is not None:
            sys.exit(blender_half())
        if '--points' in argv:
            sys.exit(fit_half())
        rc, keep = _run.blender('proportion_overlay.py', argv)
        print('\n'.join(keep)); sys.exit(rc)
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc(); sys.exit(2)
