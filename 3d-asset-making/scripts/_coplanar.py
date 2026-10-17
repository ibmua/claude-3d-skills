"""_coplanar.py: faces that lie IN one another (same plane, same facing, overlapping), found and cut apart. numpy only.

Why (2026-10-13, a train car): the film original has parts whose faces lie exactly in another part's face: a window
reveal's flange in the skin plane (z = 1.400, a 16 mm strip under every window), a door reveal in the skin's door jamb
(x = -1.600). In the original they never show: a surround 9 mm over them or the closed door leaf covers both. A game
version takes the cover away (the surround is cut into its base as a material region; the leaf's edge moves by the
error target), both faces are then in view at one depth, and the depth test picks either per pixel: sweep.mjs blink
65 px (near, window sills) and 120 px (mid, door jamb) at 12 m, where a depth step is 0.02 mm, so only faces that
truly coincide can fight there.

  overlap(V, T, tol)  -> {'pairs', 'area_m2', 'places'}: same-facing triangle pairs within tol of one plane that cover
                         one another (their common area), largest places first. A measurement; changes nothing.
  cut(V, T, tol, pri) -> V2, T2, src, info: of each such pair one triangle loses the common area (cut along the other's
                         edges, the rest re-triangulated; corners on its own plane), so every point of the overlap is
                         drawn once. Kept whole: the triangle with the higher pri[t] (simplify.py gives the rarer
                         material the higher one: a trim flange lying in the body skin stays trim), else the larger
                         one, else the earlier one: one order over all triangles, so three faces deep never leave a
                         hole. src[k] = the input triangle that
                         output triangle k came from (carry materials and parts with it). No surface is lost: the area
                         drawn after equals the area of the union.
Not touched: faces back to back (a thin sheet), faces more than tol apart (default 0.3 mm: stacked surfaces 0.3-5 mm
apart still fight beyond ~60 m and are a modelling matter: keep them 5 mm apart or cut the hidden one), faces that share
an edge. A cut leaves corners on the loser's neighbours' edges (T-corners); the winner lies under them.
"""
import numpy as np

TOL = 3e-4          # m: faces this close to one plane count as lying in one another (mesh_integrity's meet distance)
MIN_AREA = 2e-6     # m2: a common area under 2 mm2, or narrower than 0.1 mm, is a shared border, not an overlap
MIN_WIDTH = 1e-4


def _geo(V, T):
    P = V[T].astype(np.float64); N = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]); a2 = np.linalg.norm(N, axis=1)
    return P, N / np.maximum(a2[:, None], 1e-30), a2 / 2


def _area(poly):
    if len(poly) < 3: return 0.0
    x = np.array([p[0] for p in poly]); y = np.array([p[1] for p in poly])
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _perim(poly):
    return float(sum(np.hypot(poly[k][0] - poly[k - 1][0], poly[k][1] - poly[k - 1][1]) for k in range(len(poly))))


def _clip(poly, a, b, inside):
    """the part of a convex polygon left of a->b (inside) or right of it"""
    out = []; n = len(poly)
    if n < 3: return out
    ex, ey = b[0] - a[0], b[1] - a[1]
    d = [(ex * (p[1] - a[1]) - ey * (p[0] - a[0])) * (1.0 if inside else -1.0) for p in poly]
    for k in range(n):
        p, q, dp, dq = poly[k], poly[(k + 1) % n], d[k], d[(k + 1) % n]
        if dp >= 0: out.append(p)
        if (dp > 0 and dq < 0) or (dp < 0 and dq > 0):
            t = dp / (dp - dq); out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
    return out


def _minus(poly, W):
    """convex poly minus triangle W (counter-clockwise): the pieces outside W, and the common part"""
    out = []; rest = poly
    for k in range(3):
        o = _clip(rest, W[k], W[(k + 1) % 3], False)
        if len(o) >= 3 and _area(o) > 1e-12: out.append(o)
        rest = _clip(rest, W[k], W[(k + 1) % 3], True)
        if len(rest) < 3: return out, []
    return out, rest


def _real(poly):
    a = abs(_area(poly))
    return a > MIN_AREA and a / max(_perim(poly), 1e-12) > MIN_WIDTH / 2


def _basis(n):
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(n, a); u /= np.linalg.norm(u); return u, np.cross(n, u)


def _pairs(V, T, tol):
    """candidate pairs (i, j, common area), i < j: same facing, one plane within tol, common area real"""
    P, N, AR = _geo(V, T)
    ok = AR > MIN_AREA / 4
    D = (N * P[:, 0]).sum(1)
    lo = P.min(1) - tol; hi = P.max(1) + tol
    # welded vertex ids: triangles sharing an edge are neighbours, not an overlap
    _, wi = np.unique(np.round(V / 1e-6).astype(np.int64), axis=0, return_inverse=True); WT = wi.ravel()[T]
    qn, qd = 2e-3, 4 * tol
    cand = set()
    for sn in (0.0, 0.5):
        for sd in (0.0, 0.5):
            key = np.concatenate([np.floor(N / qn + sn), np.floor(D / qd + sd)[:, None]], 1).astype(np.int64)
            key[~ok] = np.iinfo(np.int64).min
            _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True); inv = inv.ravel()
            order = np.argsort(inv, kind='stable'); starts = np.concatenate([[0], np.cumsum(cnt)])
            for b in np.nonzero(cnt > 1)[0]:
                ids = order[starts[b]:starts[b + 1]]
                if not ok[ids[0]]: continue
                L, H = lo[ids], hi[ids]
                for a in range(len(ids) - 1):
                    m = (L[a + 1:] <= H[a]).all(1) & (H[a + 1:] >= L[a]).all(1)
                    for j in ids[a + 1:][m]:
                        i = ids[a]; cand.add((int(min(i, j)), int(max(i, j))))
    out = []
    for i, j in sorted(cand):
        if N[i] @ N[j] < 0.9999 or abs((P[j] - P[i, 0]) @ N[i]).max() > tol: continue
        if len(set(WT[i].tolist()) & set(WT[j].tolist())) >= 2: continue
        u, v = _basis(N[i]); o = P[i, 0]
        A = [(float((p - o) @ u), float((p - o) @ v)) for p in P[i]]; B = [(float((p - o) @ u), float((p - o) @ v)) for p in P[j]]
        if _area(B) < 0: B = B[::-1]
        if _area(A) < 0: A = A[::-1]
        _, common = _minus(A, B)
        if common and _real(common): out.append((i, j, abs(_area(common))))
    return out, (P, N, AR)


def overlap(V, T, tol=TOL, cell=0.3):
    V = np.asarray(V, np.float64); T = np.asarray(T, np.int64)
    pr, (P, N, AR) = _pairs(V, T, tol)
    places = {}
    for i, j, a in pr:
        k = tuple(np.round(((P[i].mean(0) + P[j].mean(0)) / 2) / cell).astype(int)); places[k] = places.get(k, 0.0) + a
    return dict(pairs=len(pr), area_m2=round(float(sum(a for _, _, a in pr)), 6), tol_m=tol,
                places=[dict(centre=[round(c * cell, 2) for c in k], area_m2=round(a, 6)) for k, a in sorted(places.items(), key=lambda x: -x[1])[:12]])


def cut(V, T, tol=TOL, pri=None):
    V = np.asarray(V); T = np.asarray(T); Vd = V.astype(np.float64)
    pr, (P, N, AR) = _pairs(Vd, T.astype(np.int64), tol)
    info = dict(pairs=len(pr), overlap_m2=round(float(sum(a for _, _, a in pr)), 6), tol_m=tol, cut_triangles=0, pieces=0, new_vertices=0)
    if not pr: return V, T, np.arange(len(T)), info
    rank = lambda t: (float(pri[t]) if pri is not None else 0.0, AR[t], -t)      # one order over all triangles
    cutters = {}
    for i, j, _ in pr:
        lose, win = (i, j) if rank(i) < rank(j) else (j, i); cutters.setdefault(lose, []).append(win)
    newV, newT, newS = [], [], []; nv = len(V); gone = np.zeros(len(T), bool)
    for t, wins in cutters.items():
        u, v = _basis(N[t]); o = P[t, 0]
        to2 = lambda p: (float((p - o) @ u), float((p - o) @ v))
        own = [to2(p) for p in P[t]]; flip = _area(own) < 0
        polys = [own[::-1] if flip else own]
        for w in wins:
            W = [to2(p) for p in P[w]]
            if _area(W) < 0: W = W[::-1]
            nxt = []
            for poly in polys: nxt += _minus(poly, W)[0]
            polys = nxt
        gone[t] = True; info['cut_triangles'] += 1
        for poly in polys:
            if abs(_area(poly)) < 1e-9: continue
            ids = []
            for p in poly:
                k = next((c for c in range(3) if abs(p[0] - own[c][0]) < 1e-9 and abs(p[1] - own[c][1]) < 1e-9), None)
                if k is not None: ids.append(int(T[t, k]))
                else: newV.append(o + p[0] * u + p[1] * v); ids.append(nv); nv += 1
            for k in range(1, len(ids) - 1):
                tri = (ids[0], ids[k], ids[k + 1]) if not flip else (ids[0], ids[k + 1], ids[k])
                newT.append(tri); newS.append(t)
    keep = np.nonzero(~gone)[0]
    V2 = np.concatenate([V, np.array(newV, V.dtype).reshape(-1, 3)]) if newV else V
    T2 = np.concatenate([T[keep], np.array(newT, T.dtype).reshape(-1, 3)]) if newT else T[keep]
    src = np.concatenate([keep, np.array(newS, np.int64)]) if newS else keep
    info['pieces'] = len(newT); info['new_vertices'] = len(newV)
    return V2, T2, src, info
