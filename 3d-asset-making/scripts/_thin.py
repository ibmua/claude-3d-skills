"""_thin.py: does a version keep the original's THIN FEATURES (a stripe, a trim line, a lamp)? numpy only.

render.py lodcmp's region test asks for 1 % of the asset at dE > 25, so a broken stripe passes it (a test run near,
2026-10-13: white patches in the red stripe round the nose and torn chrome trims, 0 checks failed). This test looks at
features only: a pixel is a FEATURE when its colour stands out from its surroundings (CIE76 dE > `stand_out` against
the mean over a window of ~1/25 of the asset's width). A feature pixel of the original is KEPT when the version shows
that colour (dE < `match`) within `slack` px of the same place (the 2 px a version may be off, plus one). Lost pixels
(and, the other way round, feature pixels the version ADDS: spikes hanging under a stripe) are joined into pieces; a
piece counts when it is at least `min_px` pixels and at least `min_thick` px thick, i.e. more than a 2 px shift can
make. Glass is the known noise source (reflections move): pieces are reported with their boxes so the caller can show
them; the limits were set on a train car alone (see LODCMP LIMITS in render.py), so render.py treats the verdict as
ADVISORY unless --thin-fail is given.

  thin_features(orig_rgba, vers_rgba) -> dict(feature_px, lost_px, added_px, lost_share, added_share, pieces=[...],
                                               fail=[...])   # images: float arrays HxWx4, display sRGB 0..1, same size
"""
import numpy as np


def _lab(rgb):
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]], np.float32)
    xyz = lin @ M.T / np.array([0.9505, 1.0, 1.089], np.float32)
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1).astype(np.float32)


def _box(a, r, w=None):
    """mean over a (2r+1) square, weighted by w (the asset's own pixels), by summed-area tables"""
    def sat(x):
        s = np.zeros((x.shape[0] + 1, x.shape[1] + 1) + x.shape[2:], np.float64); s[1:, 1:] = x.cumsum(0).cumsum(1); return s
    H, W = a.shape[:2]
    y0 = np.clip(np.arange(H) - r, 0, H); y1 = np.clip(np.arange(H) + r + 1, 0, H)
    x0 = np.clip(np.arange(W) - r, 0, W); x1 = np.clip(np.arange(W) + r + 1, 0, W)
    def win(s): return s[y1][:, x1] - s[y0][:, x1] - s[y1][:, x0] + s[y0][:, x0]
    if w is None: w = np.ones((H, W), np.float32)
    n = win(sat(w.astype(np.float64)))
    m = win(sat(a * (w[..., None] if a.ndim == 3 else w)))
    return (m / np.maximum(n[..., None] if a.ndim == 3 else n, 1e-6)).astype(np.float32)


def _min_near(labA, labB, maskB, slack):
    """per pixel of A: the smallest dE to a pixel of B within `slack` px (pixels outside maskB do not count)"""
    H, W = labA.shape[:2]; best = np.full((H, W), 1e9, np.float32)
    for dy in range(-slack, slack + 1):
        for dx in range(-slack, slack + 1):
            if dy * dy + dx * dx > slack * slack + 1: continue
            sh = np.roll(labB, (dy, dx), (0, 1)); mk = np.roll(maskB, (dy, dx), (0, 1))
            d = np.sqrt(((labA - sh) ** 2).sum(-1)); d[~mk] = 1e9
            best = np.minimum(best, d)
    return best


def _erode(m, r):
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out &= np.roll(m, (dy, dx), (0, 1))
    return out


def _pieces(mask, min_px, min_thick):
    """connected pieces (8-neighbour) of at least min_px pixels that survive an erosion to min_thick"""
    H, W = mask.shape; lab = np.zeros((H, W), np.int32); out = []; n = 0
    core = _erode(mask, max(0, (min_thick - 1) // 2)) if min_thick > 1 else mask
    ys, xs = np.nonzero(mask)
    for y, x in zip(ys.tolist(), xs.tolist()):
        if lab[y, x]: continue
        n += 1; st = [(y, x)]; lab[y, x] = n; px = []
        while st:
            cy, cx = st.pop(); px.append((cy, cx))
            for yy in (cy - 1, cy, cy + 1):
                for xx in (cx - 1, cx, cx + 1):
                    if 0 <= yy < H and 0 <= xx < W and mask[yy, xx] and not lab[yy, xx]:
                        lab[yy, xx] = n; st.append((yy, xx))
        if len(px) < min_px: continue
        py = np.array([p[0] for p in px]); pxx = np.array([p[1] for p in px])
        if not core[py, pxx].any(): continue
        out.append(dict(px=len(px), box_px=[int(pxx.min()), int(py.min()), int(pxx.max()) + 1, int(py.max()) + 1]))
    out.sort(key=lambda b: -b['px'])
    return out


def thin_features(o, v, stand_out=18.0, match=14.0, slack=3, min_px=None, min_thick=3, window=None, max_piece_share=0.0004,
                  max_lost=0.12, max_added=0.12):
    """o, v: HxWx4 float (display sRGB, alpha), top row first or last (both the same). See the module text."""
    mo, mv = o[..., 3] > 0.5, v[..., 3] > 0.5
    n = int((mo & mv).sum())
    if n < 50: return dict(error='version and original do not overlap on screen')
    lo, lv = _lab(o[..., :3]), _lab(v[..., :3])
    xs = np.nonzero(mo.any(0))[0]; width = int(xs.max() - xs.min() + 1) if len(xs) else o.shape[1]
    r = int(window or max(4, round(width / 50)))
    def feat(lab, m):
        d = np.sqrt(((lab - _box(lab, r, m.astype(np.float32))) ** 2).sum(-1)); return (d > stand_out) & m
    fo, fv = feat(lo, mo), feat(lv, mv)
    lost = fo & (_min_near(lo, lv, mv, slack) > match)
    added = fv & (_min_near(lv, lo, mo, slack) > match)
    if min_px is None: min_px = max(12, int(round(max_piece_share * n)))
    pl = _pieces(lost, min_px, min_thick); pa = _pieces(added, min_px, min_thick)
    nf = max(1, int(fo.sum())); nfv = max(1, int(fv.sum()))
    res = dict(feature_px=int(fo.sum()), feature_share=float(fo.sum()) / n, lost_px=int(lost.sum()), added_px=int(added.sum()),
               lost_share=float(lost.sum()) / nf, added_share=float(added.sum()) / nfv, window_px=r, slack_px=slack,
               min_piece_px=min_px, lost_pieces=pl[:8], added_pieces=pa[:8], lost_piece_px=int(sum(p['px'] for p in pl)),
               added_piece_px=int(sum(p['px'] for p in pa)))
    why = []
    if pl: why.append('%d broken piece(s) of a thin feature, largest %d px at x %d-%d y %d-%d' % (
        len(pl), pl[0]['px'], pl[0]['box_px'][0], pl[0]['box_px'][2], pl[0]['box_px'][1], pl[0]['box_px'][3]))
    if pa: why.append('%d piece(s) the original does not have, largest %d px at x %d-%d y %d-%d' % (
        len(pa), pa[0]['px'], pa[0]['box_px'][0], pa[0]['box_px'][2], pa[0]['box_px'][1], pa[0]['box_px'][3]))
    if res['lost_share'] > max_lost: why.append('%.0f %% of the feature pixels lost (limit %.0f %%)' % (res['lost_share'] * 100, max_lost * 100))
    if res['added_share'] > max_added: why.append('%.0f %% of the version\'s feature pixels are new (limit %.0f %%)' % (res['added_share'] * 100, max_added * 100))
    res['fail'] = why; res['lost_mask'] = lost; res['added_mask'] = added
    return res
