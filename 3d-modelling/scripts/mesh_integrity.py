#!/usr/bin/env python3
"""Is this model one sound thing? Floating parts, cracks, and what a simplified version lost.

  mesh_integrity.py MODEL.glb [--against REFERENCE.glb] [--from-below] [--attach METERS] [--zgap METERS] [--json OUT.json]
                    [--workers N] [--backdrop NAMES|none] [--moved-places N] [--back-to-back-places N]
                    [--held-by ORIGINAL.glb [--held-tol METERS]]
                    [--seen-to near|mid|far|METERS [--family F] [--near METERS]]

Reads a binary glTF (.glb) with Python 3 and numpy, applies every node's transform (a mirrored node, one with a negative
determinant, has its faces turned the way the engine draws them, as glTF requires), and reports:

  PARTS      the model's connected pieces (triangles that share a welded corner), then which pieces TOUCH each other
             (surfaces within --attach, default 0.1 % of the model's diagonal, at least 2 mm, at most 2 cm; exact
             point-to-triangle distances). Pieces that
             touch form a body. A model of one physical thing has ONE body: every further body is FLOATING: printed
             with its size, its place and its gap to the nearest other body.
  CRACKS     open edges (an edge with one triangle) and their total length, in three kinds: on the ground (the rim of
             what stands on something), resting on another surface (a sheet ending on a wall, a T-joint: closed to
             the eye) and free. With --against, only the open length that the reference does not have at that place
             counts as NEW.
  NON-MANIFOLD  the shape's bookkeeping: edges where more than two faces meet, neighbouring faces of one part that wind
             opposite ways, zero-area faces and duplicate faces, with places. Two neighbours that wind opposite ways
             are either a face TURNED OVER (the two sheets meet at 75 degrees or more: a smooth surface or a box corner
             with one face pointing in) or a sheet FOLDED BACK on its neighbour (under 75 degrees, a lip or a fin of
             one sheet, both faces pointing out of the fold: no winding draws both sides of it, so it is counted only).
             Turned-over faces are a LOOK, not a FAULT: with a one-sided material a turned face is a hole one sees
             through, with a two-sided one it is shaded dark; but two separate sheets of one mesh meeting at an edge
             can look the same, so the eye decides. The rest is only reported: an edge of three or four faces (two
             parts sharing an edge exactly, a wall inside a shell) draws nothing wrong and only upsets simplifiers and
             booleans; a zero-area face draws nothing; a duplicate face made of its own corners blinks (FLICKER below
             counts it), one that reuses the same corners draws the same pixels twice.
  WATERTIGHT per body: closed (every edge of its parts has exactly two faces that wind opposite ways, so each part
             has an inside) or open, and the volume of its closed parts. A closed part with a NEGATIVE volume is INSIDE
             OUT: all its faces point inward, so the engine culls its outside and draws its inside (a hollow, wrongly
             lit thing): FAULT, with the places. Why a FAULT when a turned face is only a LOOK: a closed part has one
             inside, so a negative volume is never by design, and turning all its faces fixes it. Flat closed parts
             (two sheets back to back, a card) have no volume and are not judged.
  LOOKED INTO  how much of what a viewer sees from the sides and from above is the BACK of a face. A closed solid shows
             none; real models with thin parts and cards show a few percent. Above 5 % the places are printed: a
             back means the viewer looks into something: through a missing wall or an open top, at a skeleton
             without its skin, or at a single sheet from behind. A pointer to look, not a verdict.
  GAPS       pairs of parts that come within the touch distance but never meet within 0.3 mm (MESH_MEET env): a part
             hovering a few mm off its seat counts as touching above, yet shows a slit. LOOK, with the places.
  FLICKER    faces that share a plane (within --zgap, default 2 mm, counted inclusive of float noise) and overlap:
             z-fighting, which blinks as the camera moves (a decal or trim laid flush on a panel, two parts
             overlapping inside a shared wall, a duplicated face). Facing the same way and over 1 cm2 (true area in
             the plane): FAULT. Back to back: reported (blinks only on double-sided materials). Every pair is found:
             no near-coplanar pair is missed by how its normal or its plane falls on a grid.
             The back-to-back pairs are gathered into PLACES (one pair of parts, overlaps within half a meter of each
             other): summed area, pairs, how far apart, a point on the surface. All in the JSON
             (flicker.back_to_back_places, largest first); --back-to-back-places N prints the N largest. Most are two
             solids resting exactly on each other (harmless). Two faces of ONE part back to back in the same place
             (within 0.1 mm) are counted apart and their places always printed: a face and its FLIPPED COPY, which the
             duplicate count above cannot see when the copy has its own corners, is split along the other diagonal or
             is offset a little. Reported, not a FAULT: two solids of one mesh resting on each other read the same.
  AT DISTANCE  with --seen-to (owner 2026-10-14, the modern shell's "crazy jagged line"): the 2 mm FLICKER gap is right up
             close, but the depth buffer's step grows with the square of the distance: z^2 / (near * 2^24), with the
             game camera's near plane (switch.json camera.near_m, the game 0.5 m). A version is drawn out to the FAR
             end of its range: --seen-to near|mid|far reads it from switch.json (--family, default the file's
             default_family; near = near_mid high end + hysteresis, mid and far = mid_far high end + hysteresis), or
             give metres. Faces facing the same way within twice that step and overlapping over 1 cm2 are a LOOK:
             they blink at that distance in the game (train near version: 7.3 mm at 248 m; the 2.5 mm panel overlaps
             of a shell did). Fix by deleting the hidden face or joining the parts (drop both coincident faces), not by
             lifting further: at 728 m the step is 63 mm.
  AGAINST    with --against REFERENCE (the version this one was made from). Points are spread over both surfaces by
             area and each point's distance to the other surface is exact. Printed: how far this model's surface lies
             from the reference's (a part ADDED or MOVED) and the reference's from this one (the largest and the 95th
             percentile); the share of the reference's surface with nothing within 1 % of the diagonal here (LOST); and
             of that, the share that can be SEEN FROM OUTSIDE (from the sides and from above; --from-below adds the
             views from underneath, for what hangs or flies). Only the seen loss is a fault: a lower version may leave
             out what cannot be seen (floors behind a wall, undersides on the ground). The five largest lost regions
             are printed with their corners, so you can go and look.
             A GROUND OR BACKDROP in the file is left out of the comparison, and the diagonal, the tolerance and the
             point spacing are those of the rest (a car on a 200 m ground was measured every 0.7 m, with a tolerance of
             2.8 m): a part that is a flat sheet or is named like one (ground, floor, backdrop, sky, plane) AND without
             which the rest is at most a third of the file's diagonal. The line "left out" says which;
             --backdrop none compares everything, --backdrop NAMES (comma list, globs) leaves out exactly those.
             PART BY PART: every part (node) is also measured with its own points (its corners and points by area, at
             least 48 of each however small the part), exactly, both ways, up to the tolerance. Parts more than
             0.1 mm off the other file's surface are listed farthest first, with the point where they are farthest;
             a part with the same name and corners in both files gets its exact shift ("moved as one piece by
             1.000 mm along ..."). So a part moved 1 mm is found and placed (against.moved_places in the JSON;
             --moved-places N prints N, default 8). A list to read, not a verdict: against a lower version nearly
             every part is on it.

  HELD BY    with --held-by ORIGINAL (the film original this lower version was made from; --against may name another
             file, the version above). A lower version is made by dropping the faces no outside view reaches and
             simplifying the rest, so a part whose seen shell met the car only through unseen faces counts as FLOATING
             above although it sits where it sat and looks attached from every side. With this option the floating
             bodies are judged as a viewer would: does a piece hang in the air, or show a gap, that the original does not
             have? Each floating body is one of:
               HELD       it lies on the original, and the original joins it to the main body: through the original's
                          own surface used as GLUE, all of it except what is both GONE here (nothing of this version
                          within the touch distance) and SEEN FROM OUTSIDE in the original. An unseen flange is glue. A
                          collar that showed between a lamp and its post and was dropped is not: there is air now where
                          the viewer saw it. No fault.
               INHERITED  not held, but it lies on a body that floats in the original too. Said, no fault here: fix
                          the original (the original itself is never reported by this option).
               MOVED      a point of it lies farther than --held-tol from the original's surface: a lens left hanging
                          above its post, or a piece the original does not have at all (a floor sheet that is in the
                          work file but was never exported with the original). FAULT, with the distance and the place.
               NOT HELD   what joined it is gone and can be seen. FAULT, with the place of the gone surface.
             --held-tol METERS (default: the touch distance above) is at once how far a piece may lie from the original
             and how wide an opening still counts as closed: give the version's error target when it is larger, and no
             more, because air up to about twice that passes. Surfaces are joined within it but never wider than 2 % of
             the diagonal (23 cm on a car): beyond that "touching" means nothing, and the measurement does not fit in memory. Seen from outside is what simplify.py means by it: 72
             view directions from above down to 30 degrees underneath (96, all round, with --from-below), exact rays
             from the gone surface to the viewer, glass counted as a wall. Only the FLOATING verdict changes: the BODIES
             lines above are printed as always, and the fault "more separate bodies than the reference" is not raised.
             The JSON gets held_by (counts, and places of the bodies that are not held) and bodies[n].held.
             What it cannot see: air narrower than about twice --held-tol; a connector seen only through glass (glass
             is a wall) or only from a direction between the 72; a piece that lies on the original but is the wrong
             piece; and with a large --held-tol a part lifted by less than it.

Exit 0: one body, nothing new against the reference. Exit 1: a floating body, an inside-out part or a blinking face pair
(FAULT), or a pointer to go and look (LOOK: gaps, turned-over faces, with --against a lost or moved part larger than the
limits printed; right about half the time; its absence is reliable). Exit 2: the file could not be read (or numpy is
missing).

Time: the pair measurements run on up to 8 CPU cores (--workers N or MESH_WORKERS; 1 = one core); a train car
assembly (371,000 triangles, 1,971 pieces) takes about half a minute, a single car a few seconds. The results do not
depend on the number of cores. GAPS stops measuring after 240 s and says so. --held-by on a train car (369,564 triangles
in the original, 4 workers, a loaded box): near 1 min 25 s, mid 1 min 23 s, far 2 min 55 s, 2 GB at most; most of it is
the rays of SEEN FROM OUTSIDE.

What it cannot see: a part that touches but is visibly wrong (turned, scaled, the wrong part), light leaking
through a seam closer than the weld, a texture that broke, which materials are double-sided. It is the first look,
not the last: after it, open each version ALONE and LARGE and turn it.
"""
import time, json, math, struct, sys, os, re, fnmatch
from array import array
from collections import defaultdict
try:
    import numpy as np
except ImportError:                                     # pragma: no cover
    np = None

CT = {5120: ('b', 1), 5121: ('B', 1), 5122: ('h', 2), 5123: ('H', 2), 5125: ('I', 4), 5126: ('f', 4)}
NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}
INF = float('inf')
_T0 = [time.time()]


def tick(what):
    """Phase times on stderr when MESH_TIMES is set (for finding what is slow)."""
    if os.environ.get('MESH_TIMES'):
        t = time.time(); sys.stderr.write(f'  time {what}: {t - _T0[0]:.1f} s\n'); _T0[0] = t


# ---------------------------------------------------------------------------------------------------------- reading
def read_glb(path):
    with open(path, 'rb') as f:
        head = f.read(12)
        if head[:4] != b'glTF': raise ValueError('not a .glb file')
        n, _ = struct.unpack('<I4s', f.read(8)); gltf = json.loads(f.read(n)); rest = f.read()
    blob = rest[8:8 + struct.unpack('<I', rest[:4])[0]] if len(rest) >= 8 else b''
    return gltf, blob


def accessor(gltf, blob, i):
    a = gltf['accessors'][i]; code, size = CT[a['componentType']]; nc = NC[a['type']]; count = a['count']
    if 'bufferView' not in a: return [0.0] * (count * nc), nc
    bv = gltf['bufferViews'][a['bufferView']]; off = bv.get('byteOffset', 0) + a.get('byteOffset', 0); stride = bv.get('byteStride') or size * nc
    if stride == size * nc:
        out = array(code); out.frombytes(blob[off:off + count * nc * size]); vals = list(out)
    else:
        vals = []
        for k in range(count): vals.extend(struct.unpack_from('<' + code * nc, blob, off + k * stride))
    if a.get('normalized') and code != 'f':
        m = {'b': 127.0, 'B': 255.0, 'h': 32767.0, 'H': 65535.0}[code]; vals = [max(v / m, -1.0) for v in vals]
    return vals, nc


def mat_mul(a, b):
    return [sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4)]


def node_matrix(n):
    if 'matrix' in n:
        m = n['matrix']; return [m[c * 4 + r] for r in range(4) for c in range(4)]          # glTF is column-major
    t = n.get('translation', [0, 0, 0]); q = n.get('rotation', [0, 0, 0, 1]); s = n.get('scale', [1, 1, 1]); x, y, z, w = q
    r = [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
         2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
         2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]
    return [r[0] * s[0], r[1] * s[1], r[2] * s[2], t[0], r[3] * s[0], r[4] * s[1], r[5] * s[2], t[1], r[6] * s[0], r[7] * s[1], r[8] * s[2], t[2], 0, 0, 0, 1]


def det3(m):
    return (m[0] * (m[5] * m[10] - m[6] * m[9]) - m[1] * (m[4] * m[10] - m[6] * m[8]) + m[2] * (m[4] * m[9] - m[5] * m[8]))


def load(path):
    """Triangles in world space: (points (N,3), triangles (M,3), labels, label index per triangle, instanced copies,
    mirrored copies). A node (or GPU instance) whose transform has a negative determinant draws its triangles clockwise
    (glTF 2.0, 'Transformations'): its triangles are turned here so that every face points the way the engine shows it.
    2026-10-13: before, they kept their file order, and a mirrored part counted as inside out (its faces pointing in)."""
    gltf, blob = read_glb(path); P, T, lab = [], [], []; labels = {}; npts = 0; instanced = mirrored = 0
    scenes = gltf.get('scenes') or [{'nodes': list(range(len(gltf.get('nodes', []))))}]
    stack = [(i, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]) for i in scenes[gltf.get('scene', 0)].get('nodes', [])]
    while stack:
        i, parent = stack.pop(); n = gltf['nodes'][i]; m = mat_mul(parent, node_matrix(n))
        stack.extend((c, m) for c in n.get('children', []))
        if 'mesh' not in n: continue
        mats = [m]; inst = n.get('extensions', {}).get('EXT_mesh_gpu_instancing', {}).get('attributes')
        if inst:                                         # every copy is put where the engine will draw it
            get = lambda k: accessor(gltf, blob, inst[k])[0] if k in inst else None
            Tr, R, S = get('TRANSLATION'), get('ROTATION'), get('SCALE'); count = len(Tr or R or S or []) // (3 if (Tr or S) else 4) if (Tr or S) else len(R or []) // 4
            mats = [mat_mul(m, node_matrix({'translation': Tr[c * 3:c * 3 + 3] if Tr else [0, 0, 0], 'rotation': R[c * 4:c * 4 + 4] if R else [0, 0, 0, 1], 'scale': S[c * 3:c * 3 + 3] if S else [1, 1, 1]})) for c in range(count)]
            instanced += len(mats)
        mesh = gltf['meshes'][n['mesh']]
        for prim in mesh.get('primitives', []):
            if prim.get('mode', 4) != 4 or 'POSITION' not in prim.get('attributes', {}): continue
            pos = np.asarray(accessor(gltf, blob, prim['attributes']['POSITION'])[0], dtype=np.float64).reshape(-1, 3)
            idx = np.asarray(accessor(gltf, blob, prim['indices'])[0], dtype=np.int64) if 'indices' in prim else np.arange(len(pos), dtype=np.int64)
            idx = idx[:len(idx) // 3 * 3].reshape(-1, 3)
            label = n.get('name') or mesh.get('name') or f'node {i}'
            X, Y, Z = pos[:, 0], pos[:, 1], pos[:, 2]
            for c, m in enumerate(mats):
                base = npts                              # the same arithmetic, in the same order, as one point at a time
                P.append(np.stack([m[0] * X + m[1] * Y + m[2] * Z + m[3], m[4] * X + m[5] * Y + m[6] * Z + m[7], m[8] * X + m[9] * Y + m[10] * Z + m[11]], 1))
                npts += len(pos)
                t = idx + base
                if det3(m) < 0: t = t[:, [0, 2, 1]]; mirrored += 1
                T.append(t)
                tag = f'{label} #{c + 1}' if inst else label
                lab.append(np.full(len(t), labels.setdefault(tag, len(labels)), dtype=np.int32))
    P = np.concatenate(P) if P else np.zeros((0, 3)); T = np.concatenate(T) if T else np.zeros((0, 3), np.int64)
    lab = np.concatenate(lab) if lab else np.zeros(0, np.int32)
    return P, T, list(labels), lab, instanced, mirrored


def dist(a, b): return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def sq(x):
    """x ** 2 exactly as Python computes it for a float (the C library's pow, which differs from x * x in the last bit
    about once in a thousand): the distances below are bit for bit those of the one-point-at-a-time version."""
    return np.float_power(x, 2.0)


class Find:
    def __init__(self, n): self.p = list(range(n))
    def root(self, a):
        while self.p[a] != a: self.p[a] = self.p[self.p[a]]; a = self.p[a]
        return a
    def join(self, a, b):
        a, b = self.root(a), self.root(b)
        if a != b: self.p[b] = a


def bbox(points):
    xs, ys, zs = zip(*[(p[0], p[1], p[2]) for p in points]); return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


# ------------------------------------------------------------------------------------------------- geometry arrays
class Geo:
    """Per-triangle arrays the vectorised measurements gather from (world space)."""
    def __init__(self, P, T):
        self.P, self.T = P, T; a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]; self.m = len(T)
        self.ax, self.ay, self.az = (np.ascontiguousarray(a[:, k]) for k in range(3))
        self.bx, self.by, self.bz = (np.ascontiguousarray(b[:, k]) for k in range(3))
        self.cx, self.cy, self.cz = (np.ascontiguousarray(c[:, k]) for k in range(3))
        self.abx, self.aby, self.abz = self.bx - self.ax, self.by - self.ay, self.bz - self.az
        self.acx, self.acy, self.acz = self.cx - self.ax, self.cy - self.ay, self.cz - self.az
        self.bcx, self.bcy, self.bcz = self.cx - self.bx, self.cy - self.by, self.cz - self.bz
        self.V = np.stack([a, b, c], 1)
        self.mn = np.minimum(np.minimum(a, b), c); self.mx = np.maximum(np.maximum(a, b), c)


def pt_tri_v(G, px, py, pz, t, exact):
    """The exact distance from points to triangles (closest point on the triangle, after Ericson), one pair per entry.
    The regions are tested in the order of the scalar version. `exact`: the squares inside its dist() are Python's
    (sq); otherwise x * x, which can differ in the last bit (used to find the nearest, then recomputed exactly)."""
    s2 = sq if exact else (lambda x: x * x)
    abx, aby, abz = G.abx[t], G.aby[t], G.abz[t]; acx, acy, acz = G.acx[t], G.acy[t], G.acz[t]
    ax, ay, az = G.ax[t], G.ay[t], G.az[t]
    apx, apy, apz = px - ax, py - ay, pz - az
    d1 = abx * apx + aby * apy + abz * apz; d2 = acx * apx + acy * apy + acz * apz
    out = np.empty(len(t)); todo = np.ones(len(t), bool)
    def put(mask, f):
        k = np.nonzero(mask)[0]
        if len(k): out[k] = f(k)
        todo[k] = False
    put((d1 <= 0) & (d2 <= 0), lambda k: np.sqrt(apx[k] * apx[k] + apy[k] * apy[k] + apz[k] * apz[k]))
    bpx, bpy, bpz = px - G.bx[t], py - G.by[t], pz - G.bz[t]
    d3 = abx * bpx + aby * bpy + abz * bpz; d4 = acx * bpx + acy * bpy + acz * bpz
    put(todo & (d3 >= 0) & (d4 <= d3), lambda k: np.sqrt(bpx[k] * bpx[k] + bpy[k] * bpy[k] + bpz[k] * bpz[k]))
    vc = d1 * d4 - d3 * d2
    def edge_ab(k):
        den = d1[k] - d3[k]; v = np.where(d1[k] != d3[k], d1[k] / np.where(den == 0, 1.0, den), 0.0)
        return np.sqrt(s2(px[k] - (ax[k] + abx[k] * v)) + s2(py[k] - (ay[k] + aby[k] * v)) + s2(pz[k] - (az[k] + abz[k] * v)))
    put(todo & (vc <= 0) & (d1 >= 0) & (d3 <= 0), edge_ab)
    cpx, cpy, cpz = px - G.cx[t], py - G.cy[t], pz - G.cz[t]
    d5 = abx * cpx + aby * cpy + abz * cpz; d6 = acx * cpx + acy * cpy + acz * cpz
    put(todo & (d6 >= 0) & (d5 <= d6), lambda k: np.sqrt(cpx[k] * cpx[k] + cpy[k] * cpy[k] + cpz[k] * cpz[k]))
    vb = d5 * d2 - d1 * d6
    def edge_ac(k):
        den = d2[k] - d6[k]; w = np.where(d2[k] != d6[k], d2[k] / np.where(den == 0, 1.0, den), 0.0)
        return np.sqrt(s2(px[k] - (ax[k] + acx[k] * w)) + s2(py[k] - (ay[k] + acy[k] * w)) + s2(pz[k] - (az[k] + acz[k] * w)))
    put(todo & (vb <= 0) & (d2 >= 0) & (d6 <= 0), edge_ac)
    va = d3 * d6 - d5 * d4; e43 = d4 - d3; e56 = d5 - d6
    def edge_bc(k):
        den = e43[k] + e56[k]; w = np.where(den != 0, e43[k] / np.where(den == 0, 1.0, den), 0.0); tk = t[k]
        return np.sqrt(s2(px[k] - (G.bx[tk] + G.bcx[tk] * w)) + s2(py[k] - (G.by[tk] + G.bcy[tk] * w)) + s2(pz[k] - (G.bz[tk] + G.bcz[tk] * w)))
    put(todo & (va <= 0) & (e43 >= 0) & (e56 >= 0), edge_bc)
    den = va + vb + vc
    def flat(k):
        tk = t[k]; p = (px[k], py[k], pz[k])
        da = np.sqrt(s2(p[0] - ax[k]) + s2(p[1] - ay[k]) + s2(p[2] - az[k]))
        db = np.sqrt(s2(p[0] - G.bx[tk]) + s2(p[1] - G.by[tk]) + s2(p[2] - G.bz[tk]))
        dc = np.sqrt(s2(p[0] - G.cx[tk]) + s2(p[1] - G.cy[tk]) + s2(p[2] - G.cz[tk]))
        return np.minimum(np.minimum(da, db), dc)
    put(todo & (den == 0), flat)
    def inner(k):
        v = vb[k] / den[k]; w = vc[k] / den[k]
        return np.sqrt(s2(px[k] - (ax[k] + abx[k] * v + acx[k] * w)) + s2(py[k] - (ay[k] + aby[k] * v + acy[k] * w)) + s2(pz[k] - (az[k] + abz[k] * v + acz[k] * w)))
    put(todo.copy(), inner)
    return out


def nearest_to_set(G, Q, S, r, stop=None):
    """For each point of Q (K,3): the exact distance to the nearest triangle of the list S when it is within r, else
    infinity (a triangle whose box lies farther than r on an axis is skipped, as before). With `stop`: the points are
    taken in order, in slices, and the work ends after the first slice holding a distance within `stop` (the rest stay
    infinity): enough for "the first point that touches"."""
    K = len(Q); out = np.full(K, INF)
    if not K or not len(S): return out
    lx, ly, lz = G.mn[S, 0] - r, G.mn[S, 1] - r, G.mn[S, 2] - r; hx, hy, hz = G.mx[S, 0] + r, G.mx[S, 1] + r, G.mx[S, 2] + r
    mnS, mxS = G.mn[S], G.mx[S]
    step = max(1, (200_000 if stop is not None else 1_500_000) // len(S))
    for s in range(0, K, step):
        q = Q[s:s + step]; qlo, qhi = q.min(0), q.max(0)
        loc = np.flatnonzero((hx >= qlo[0]) & (lx <= qhi[0]) & (hy >= qlo[1]) & (ly <= qhi[1]) & (hz >= qlo[2]) & (lz <= qhi[2]))
        if not len(loc): continue                        # only the triangles whose reach meets this slice's box
        x, y, z = q[:, 0:1], q[:, 1:2], q[:, 2:3]
        qi, ti = np.nonzero((x >= lx[loc]) & (x <= hx[loc]) & (y >= ly[loc]) & (y <= hy[loc]) & (z >= lz[loc]) & (z <= hz[loc]))
        if not len(qi): continue
        ti = loc[ti]
        # prune: a triangle whose box lies farther from the point than the exact distance to the triangle with the
        # nearest box cannot be the nearest (the result is unchanged; only fewer distances are computed)
        px, py, pz = q[qi, 0], q[qi, 1], q[qi, 2]; mn, mx = mnS[ti], mxS[ti]
        gx = np.maximum(np.maximum(mn[:, 0] - px, px - mx[:, 0]), 0); gy = np.maximum(np.maximum(mn[:, 1] - py, py - mx[:, 1]), 0); gz = np.maximum(np.maximum(mn[:, 2] - pz, pz - mx[:, 2]), 0)
        lb = np.sqrt(gx * gx + gy * gy + gz * gz)
        starts = np.flatnonzero(np.r_[True, qi[1:] != qi[:-1]]); seg = np.cumsum(np.r_[False, qi[1:] != qi[:-1]])
        mlb = np.minimum.reduceat(lb, starts); at = np.flatnonzero(lb == mlb[seg])
        first = at[np.r_[True, seg[at][1:] != seg[at][:-1]]]          # per point, the (first) pair with the nearest box
        ub = pt_tri_v(G, px[first], py[first], pz[first], S[ti[first]], False)
        keep = np.flatnonzero(lb <= ub[seg] * (1 + 1e-9) + 1e-12)
        qi, ti, seg, px, py, pz = qi[keep], ti[keep], seg[keep], px[keep], py[keep], pz[keep]
        t = S[ti]; df = pt_tri_v(G, px, py, pz, t, False)
        starts = np.flatnonzero(np.r_[True, seg[1:] != seg[:-1]]); sg2 = np.cumsum(np.r_[False, seg[1:] != seg[:-1]])
        mins = np.minimum.reduceat(df, starts)
        cand = np.flatnonzero(df <= mins[sg2] * (1 + 1e-12) + 1e-300)          # only these can be the exact nearest
        de = pt_tri_v(G, px[cand], py[cand], pz[cand], t[cand], True)
        best = np.full(len(starts), INF); np.minimum.at(best, sg2[cand], de)
        res = np.where(best <= r, best, INF); out[s + qi[starts]] = res
        if stop is not None and (res <= stop).any(): break
    return out


# ------------------------------------------------------------------------------------------- points on triangles
_TPL = {}


def template(n):
    """(u, v, w) of the even grid on a triangle cut n times, in the order of the nested loops (u, then v)."""
    if n not in _TPL:
        u = np.concatenate([np.full(n + 1 - i, i) for i in range(n + 1)]).astype(np.float64)
        v = np.concatenate([np.arange(n + 1 - i) for i in range(n + 1)]).astype(np.float64)
        _TPL[n] = (u, v, n - u - v)
    return _TPL[n]


def tri_points_v(A, B, C, step, cap):
    """Points no farther apart than `step` on each triangle (A, B, C: (S,3)), at most `cap` cuts per side; in order,
    triangle after triangle, and bit for bit the points of the scalar version. Returns (points (K,3), triangle of each)."""
    S = len(A)
    if not S: return np.zeros((0, 3)), np.zeros(0, np.int64)
    dab = np.sqrt(sq(A[:, 0] - B[:, 0]) + sq(A[:, 1] - B[:, 1]) + sq(A[:, 2] - B[:, 2]))
    dbc = np.sqrt(sq(B[:, 0] - C[:, 0]) + sq(B[:, 1] - C[:, 1]) + sq(B[:, 2] - C[:, 2]))
    dac = np.sqrt(sq(A[:, 0] - C[:, 0]) + sq(A[:, 1] - C[:, 1]) + sq(A[:, 2] - C[:, 2]))
    n = (np.minimum(np.floor(np.maximum(np.maximum(dab, dbc), dac) / step), cap) + 1).astype(np.int64); n = np.minimum(n, cap)
    cnt = (n + 1) * (n + 2) // 2; rep = np.repeat(np.arange(S), cnt); tot = int(cnt.sum())
    local = np.arange(tot) - np.repeat(np.cumsum(cnt) - cnt, cnt)
    U = np.empty(tot); V = np.empty(tot); W = np.empty(tot); nr = n[rep]
    for k in np.unique(n).tolist():
        sel = np.flatnonzero(nr == k); u, v, w = template(k); j = local[sel]; U[sel] = u[j]; V[sel] = v[j]; W[sel] = w[j]
    nf = nr.astype(np.float64)
    pts = np.stack([(A[rep, q] * U + B[rep, q] * V + C[rep, q] * W) / nf for q in range(3)], 1)
    return pts, rep


def clip_poly(poly, lo, hi):
    """A flat polygon cut to an axis-aligned box."""
    for k in range(3):
        for sign, bound in ((1, lo[k]), (-1, hi[k])):
            if not poly: return poly
            out = []; prev = poly[-1]; pin = sign * (prev[k] - bound) >= 0
            for cur in poly:
                cin = sign * (cur[k] - bound) >= 0
                if cin != pin:
                    t = (bound - prev[k]) / (cur[k] - prev[k]); out.append((prev[0] + (cur[0] - prev[0]) * t, prev[1] + (cur[1] - prev[1]) * t, prev[2] + (cur[2] - prev[2]) * t))
                if cin: out.append(cur)
                prev, pin = cur, cin
            poly = out
    return poly


def points_in_v(G, ids, lo, hi, step):
    """Points no farther apart than `step` on the part of the triangles `ids` that lies inside the box (a large triangle
    is cut to the box first, so a ground slab is sampled as finely as a bolt)."""
    if not len(ids): return np.zeros((0, 3))
    mn, mx = G.mn[ids], G.mx[ids]
    skip = (mx[:, 0] < lo[0]) | (mn[:, 0] > hi[0]) | (mx[:, 1] < lo[1]) | (mn[:, 1] > hi[1]) | (mx[:, 2] < lo[2]) | (mn[:, 2] > hi[2])
    ins = (mn[:, 0] >= lo[0]) & (mx[:, 0] <= hi[0]) & (mn[:, 1] >= lo[1]) & (mx[:, 1] <= hi[1]) & (mn[:, 2] >= lo[2]) & (mx[:, 2] <= hi[2])
    keep = np.flatnonzero(~skip)
    if not len(keep): return np.zeros((0, 3))
    if ins[keep].all():
        V = G.V[ids[keep]]; A, B, C = V[:, 0], V[:, 1], V[:, 2]
    else:
        tri = []
        for t, inside in zip(G.V[ids[keep]].tolist(), ins[keep].tolist()):
            if inside: tri.append(t); continue
            poly = clip_poly([tuple(t[0]), tuple(t[1]), tuple(t[2])], lo, hi)
            for n in range(1, len(poly) - 1): tri.append((poly[0], poly[n], poly[n + 1]))
        if not tri: return np.zeros((0, 3))
        V = np.asarray(tri, dtype=np.float64); A, B, C = V[:, 0], V[:, 1], V[:, 2]
    return tri_points_v(A, B, C, step, 64)[0]


# ----------------------------------------------------------------------------------------------- the cell index
class Index:
    """Every triangle filed under the cells its box (grown by `grow`) covers and under its piece, so "how far is this
    point from that piece" is asked of a handful of triangles. Triangles covering very many cells (over 400) are kept in
    a short list per piece. The cells are those of the scalar version (same size, same order of first use)."""
    def __init__(self, G, tp, lo, hi, grow=0.0, cells=None):
        M = G.m; n = cells or max(16, min(72, int(round(M ** (1 / 3) * 1.5)))); self.lo = lo
        self.c = c = max(max(hi[k] - lo[k] for k in range(3)) / n, 1e-9); e = grow
        lo3 = np.array(lo)
        c0 = np.floor((G.mn - e - lo3) / c).astype(np.int64); c1 = np.floor((G.mx + e - lo3) / c).astype(np.int64)
        span = c1 - c0 + 1; ncell = span[:, 0] * span[:, 1] * span[:, 2]
        bigm = ncell > 400; tp = np.asarray(tp)
        self.big = {}
        for t in np.flatnonzero(bigm).tolist(): self.big.setdefault(int(tp[t]), []).append(t)
        self.big = {k: np.array(v, dtype=np.int64) for k, v in self.big.items()}
        small = np.flatnonzero(~bigm); cnt = ncell[small]
        et = np.repeat(small, cnt); j = np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt)
        sy, sz = span[et, 1], span[et, 2]
        ex = c0[et, 0] + j // (sy * sz); ey = c0[et, 1] + (j // sz) % sy; ez = c0[et, 2] + j % sz
        self.o = (int(ex.min()) if len(ex) else 0, int(ey.min()) if len(ey) else 0, int(ez.min()) if len(ez) else 0)
        self.ny = int(ey.max()) - self.o[1] + 1 if len(ey) else 1; self.nz = int(ez.max()) - self.o[2] + 1 if len(ez) else 1
        code = ((ex - self.o[0]) * self.ny + (ey - self.o[1])) * self.nz + (ez - self.o[2]); ep = tp[et]
        self.ent_t, self.ent_code, self.ent_piece = et, code, ep
        # per (piece, cell): the triangles in order
        o = np.lexsort((et, code, ep)); sp, sc, st = ep[o], code[o], et[o]
        b = np.r_[True, (sp[1:] != sp[:-1]) | (sc[1:] != sc[:-1])] if len(sp) else np.zeros(0, bool)
        gs = np.flatnonzero(b); ge = np.r_[gs[1:], len(sp)]
        self.g_t, self.g_start, self.g_end, self.g_code, self.g_piece = st, gs, ge, sc[gs], sp[gs]
        np_ = int(tp.max()) + 1 if len(tp) else 0
        self.p_first = np.searchsorted(self.g_piece, np.arange(np_)); self.p_last = np.searchsorted(self.g_piece, np.arange(np_), 'right')
        # per cell: all triangles (any piece), for "does anything else lie within reach of this point"
        o2 = np.lexsort((et, code)); self.c_t = et[o2]; cc = code[o2]
        b2 = np.r_[True, cc[1:] != cc[:-1]] if len(cc) else np.zeros(0, bool)
        self.c_start = np.flatnonzero(b2); self.c_end = np.r_[self.c_start[1:], len(cc)]; self.c_code = cc[self.c_start]
        self.all_big = np.flatnonzero(bigm)

    def decode(self, code):
        x = code // (self.ny * self.nz) + self.o[0]; y = (code // self.nz) % self.ny + self.o[1]; z = code % self.nz + self.o[2]
        return x, y, z

    def cells_in_first_use_order(self):
        """(cell code, sorted pieces in it) for every cell with two or more pieces, cells in the order the scalar
        version first filed a triangle there."""
        if not len(self.ent_code): return []
        u, first = np.unique(self.ent_code, return_index=True)
        cp = np.unique(np.stack([self.g_code, self.g_piece], 1), axis=0) if len(self.g_code) else np.zeros((0, 2), np.int64)
        cs = np.searchsorted(cp[:, 0], u); ce = np.searchsorted(cp[:, 0], u, 'right'); many = np.flatnonzero(ce - cs >= 2)
        order = many[np.argsort(first[many], kind='stable')]
        return [cp[cs[i]:ce[i], 1].tolist() for i in order.tolist()]

    def piece_cells(self, a):
        s, e = self.p_first[a], self.p_last[a]; return self.g_code[s:e], self.g_start[s:e], self.g_end[s:e]


# ----------------------------------------------------------------------------------------- pieces: do they touch
W = {}                                                   # the state a measuring process works on (set before forking)


def touch_v(ta, tb, lo, hi, attach):
    """The smallest distance between two lists of triangles inside a box. Points on the first, exact distances to the
    triangles of the second, then finer looks round the eight nearest points; ends at once when a point lies within
    `attach` (returning a distance within it). Infinity: the two do not come within about a twelfth of the box of each
    other. Point for point the measurement of the scalar version."""
    G = W['G']
    size = max(hi[k] - lo[k] for k in range(3)) or attach; step = max(size / 12, attach / 4); best = INF; boxes = [(lo, hi)]
    while True:
        r = attach + 1.5 * step; Qs = [points_in_v(G, ta, blo, bhi, step) for blo, bhi in boxes]
        Q = np.concatenate(Qs) if len(Qs) > 1 else Qs[0]
        D = nearest_to_set(G, Q, tb, r, attach)
        hit = np.flatnonzero(D <= attach)
        if len(hit): return float(D[hit[0]])
        fin = np.flatnonzero(D < INF)
        if len(fin): best = min(best, float(D[fin].min()))
        if not len(fin) or step <= attach / 4: return best
        top = fin[np.argsort(D[fin], kind='stable')[:8]]
        boxes = [((q[0] - step, q[1] - step, q[2] - step), (q[0] + step, q[1] + step, q[2] + step)) for q in Q[top].tolist()]
        step = max(step / 4, attach / 4)


def pieces_gap(a, b, lo, hi, attach):
    """The smallest distance between two pieces inside the box where their boxes meet, looked for only in the cells of
    the index that both have triangles in (nowhere else can they be within `attach`), then against very large triangles.
    A value within `attach` means "they touch" (not necessarily the smallest)."""
    ix, PT = W['ix'], W['ptris']; best = INF; c = ix.c; o = ix.lo
    ca, sa, ea = ix.piece_cells(a); cb, sb, eb = ix.piece_cells(b)
    common, ia, ib = np.intersect1d(ca, cb, assume_unique=True, return_indices=True)
    for code, i, j in zip(common.tolist(), ia.tolist(), ib.tolist()):
        cell = ix.decode(code)
        blo = tuple(max(lo[k], o[k] + cell[k] * c - attach) for k in range(3)); bhi = tuple(min(hi[k], o[k] + (cell[k] + 1) * c + attach) for k in range(3))
        if any(blo[k] > bhi[k] for k in range(3)): continue
        ga, gb = ix.g_t[sa[i]:ea[i]], ix.g_t[sb[j]:eb[j]]
        d = touch_v(gb, ga, blo, bhi, attach) if len(ga) > len(gb) else touch_v(ga, gb, blo, bhi, attach)
        if d < best: best = d
        if best <= attach: return best
    for x, y in ((a, b), (b, a)):                        # a ground slab's huge triangles: points on the other piece
        if x in ix.big:
            d = touch_v(PT[y], ix.big[x], lo, hi, attach)
            if d < best: best = d
            if best <= attach: return best
    return best


def _pair_job(job):
    i, a, b, lo, hi, thr = job
    return i, pieces_gap(a, b, lo, hi, thr)


def measure(jobs, workers, deadline=None):
    """{job index: distance} for every job, on up to `workers` processes (fork: they share the geometry). Jobs are handed
    out largest first. With a deadline (time.time() value), what is not measured by then is left out."""
    out = {}
    if not jobs: return out
    jobs = sorted(jobs, key=lambda j: -W['cost'](j[1], j[2]))
    if workers <= 1 or len(jobs) < 8:
        for j in jobs:
            if deadline and time.time() > deadline: break
            i, d = _pair_job(j); out[i] = d
        return out
    import multiprocessing as mp
    pool = mp.get_context('fork').Pool(workers)
    try:
        for i, d in pool.imap_unordered(_pair_job, jobs, chunksize=1):
            out[i] = d
            if deadline and time.time() > deadline: break
    finally:
        pool.terminate(); pool.join()
    return out


def workers_wanted(n=None):
    if n is None: n = int(os.environ.get('MESH_WORKERS', '0') or 0) or min(8, os.cpu_count() or 1)
    return max(1, min(8, n))


def tri_area(G, t=None):
    """Each triangle's area, as the scalar version computes it."""
    s = slice(None) if t is None else t
    ux, uy, uz = G.abx[s], G.aby[s], G.abz[s]; vx, vy, vz = G.acx[s], G.acy[s], G.acz[s]
    return 0.5 * np.sqrt(np.maximum(0.0, sq(uy * vz - uz * vy) + sq(uz * vx - ux * vz) + sq(ux * vy - uy * vx)))


def samples_v(G, step, cap=400000):
    """Points on every triangle no farther apart than `step` (an even grid; few per triangle on big models)."""
    per = max(1, cap // max(1, G.m)); return tri_points_v(G.V[:, 0], G.V[:, 1], G.V[:, 2], step, max(1, int(math.sqrt(2 * per))))


def nearest_point_dist(mine, others, cap):
    """min over the points `mine` of the distance to the nearest of `others`, or `cap` if that is larger (exact)."""
    if not len(mine) or not len(others): return cap
    lo, hi = mine.min(0), mine.max(0); r = cap / 64
    while True:
        r = min(r * 2, cap)
        sel = others[np.all((others >= lo - r) & (others <= hi + r), 1)]
        best = INF
        if len(sel):
            step = max(1, 2_000_000 // len(mine)); fast = INF
            for s in range(0, len(sel), step):
                o = sel[s:s + step]; d2 = (mine[:, None, 0] - o[None, :, 0]) ** 2 + (mine[:, None, 1] - o[None, :, 1]) ** 2 + (mine[:, None, 2] - o[None, :, 2]) ** 2
                fast = min(fast, float(np.sqrt(d2.min())))
            for s in range(0, len(sel), step):            # the exact value (Python's squares) for the near ones only
                o = sel[s:s + step]; dx = mine[:, None, 0] - o[None, :, 0]; dy = mine[:, None, 1] - o[None, :, 1]; dz = mine[:, None, 2] - o[None, :, 2]
                f = np.sqrt(dx * dx + dy * dy + dz * dz); i, j = np.nonzero(f <= fast * (1 + 1e-12) + 1e-300)
                if len(i): best = min(best, float(np.sqrt(sq(dx[i, j]) + sq(dy[i, j]) + sq(dz[i, j])).min()))
        if best <= r or r >= cap: return min(best, cap)


def analyse(path, attach=None, workers=None, bodies_only=False):
    P, T, labels, tlab, instanced, mirrored = load(path)
    if not len(T): raise ValueError('no triangles')
    return analyse_geo(P, T, labels, tlab, instanced, mirrored, path, attach, workers, bodies_only)


def analyse_geo(P, T, labels, tlab, instanced, mirrored, path, attach=None, workers=None, bodies_only=False):
    """The analysis of triangles already in world space. `bodies_only` (for --held-by): pieces and bodies as always, but
    the GAPS pass and each floating body's gap to its nearest neighbour are left out (nobody reads them there)."""
    nw = workers_wanted(workers)
    lo = tuple(P.min(0).tolist()); hi = tuple(P.max(0).tolist()); diag = dist(lo, hi) or 1.0; weld = max(diag * 1e-6, 1e-6)
    attach = attach if attach is not None else min(0.02, max(0.002, diag * 0.001))    # 2 mm on a lamp, never more than 2 cm on a stadium
    keys = np.rint(P / weld).astype(np.int64)
    _, first, inv = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    rank = np.empty(len(first), np.int64); rank[np.argsort(first, kind='stable')] = np.arange(len(first)); vid = rank[inv.ravel()]
    wt = vid[T]; G = Geo(P, T)
    uf = Find(len(first))
    for a, b, c in wt.tolist(): uf.join(a, b); uf.join(a, c)
    roots = np.array([uf.root(a) for a in wt[:, 0].tolist()], dtype=np.int64)
    pieces, tp = np.unique(roots, return_inverse=True); tp = tp.ravel(); npc = len(pieces)
    o = np.argsort(tp, kind='stable'); bounds = np.searchsorted(tp[o], np.arange(npc + 1))
    ptris = [o[bounds[q]:bounds[q + 1]] for q in range(npc)]
    pmn = np.minimum.reduceat(G.mn[o], bounds[:-1]); pmx = np.maximum.reduceat(G.mx[o], bounds[:-1])
    pb = {q: (tuple(pmn[q].tolist()), tuple(pmx[q].tolist())) for q in range(npc)}
    porder = np.argsort([int(p[0]) for p in ptris], kind='stable').tolist()      # pieces in the order of their first triangle
    # which pieces touch: only pieces with triangles in the same cell of the index are measured (two triangles within
    # `attach` of each other always share a cell, because each is filed under its box grown by `attach`), small pairs first
    tick('load, weld, pieces'); ix = Index(G, tp, lo, hi, attach); pairs = set(); tick('cell index')
    near = lambda o, q: all(pb[o][0][k] - attach <= pb[q][1][k] and pb[o][1][k] + attach >= pb[q][0][k] for k in range(3))
    for ps in ix.cells_in_first_use_order():
        for n, o_ in enumerate(ps):
            for q in ps[n + 1:]:
                if near(o_, q): pairs.add((o_, q))
    for o_ in ix.big:                                    # a piece with a very large triangle (a ground slab) is paired by its box
        for q in porder:
            if q != o_ and near(o_, q): pairs.add((min(o_, q), max(o_, q)))
    pairs = list(pairs); body = Find(npc); near_miss = {}; budget = 400000
    pairs.sort(key=lambda ab: len(ptris[ab[0]]) + len(ptris[ab[1]]))
    W.clear(); W.update(G=G, ix=ix, ptris=ptris, cost=lambda a, b: len(ptris[a]) + len(ptris[b]))
    box = lambda a, b, e: (tuple(max(pb[a][0][k], pb[b][0][k]) - e for k in range(3)), tuple(min(pb[a][1][k], pb[b][1][k]) + e for k in range(3)))
    # Each pair is measured once at `attach` (on all cores), and that one number serves both passes below.
    tick(f'{len(pairs)} pairs listed'); dA = measure([(i, a, b) + box(a, b, attach) + (attach,) for i, (a, b) in enumerate(pairs)], nw); tick('pairs measured at attach')
    for i, (a, b) in enumerate(pairs):
        if body.root(a) == body.root(b): continue
        if budget <= 0: break
        budget -= 1; d = dA[i]
        if d <= attach: body.join(a, b)
        elif d < INF: near_miss[(a, b)] = d
    # GAPS (owner 2026-10-12 22:37: "tiny gaps between things that shouldn't have any gaps between them"): `attach` counts
    # parts a few mm apart as touching, so a roof hovering 3 mm over its wall passed. Every pair of pieces that comes
    # within `attach` is measured again against `meet` (0.3 mm): closer = they meet (rest on, or enter, each other);
    # between the two = a visible slit that light shows through.
    meet = float(os.environ.get('MESH_MEET', '0.0003')); gaps = []; budget2 = 20000; t0 = time.time()
    todo = []
    for i, (a, b) in enumerate(pairs):
        if budget2 <= 0: break
        budget2 -= 1
        if dA[i] <= attach and not bodies_only: todo.append(i)
    dM = measure([(i, pairs[i][0], pairs[i][1]) + box(pairs[i][0], pairs[i][1], attach) + (meet,) for i in todo], nw, t0 + 240)
    timed_out = len(dM) < len(todo); tick(f'{len(todo)} touching pairs measured at meet')
    for i in todo:
        if i not in dM: continue
        a, b = pairs[i]; d = dM[i]
        if meet < d <= attach:
            (al, ah), (bl, bh) = pb[a], pb[b]; c = [(max(al[k], bl[k]) + min(ah[k], bh[k])) / 2 for k in range(3)]
            gaps.append({'gap_m': d, 'centre': c, 'names': sorted({labels[tlab[ptris[a][0]]], labels[tlab[ptris[b][0]]]}),
                         'sizes_m': [dist(al, ah), dist(bl, bh)]})
    gaps.sort(key=lambda g: -min(g['sizes_m']) * g['gap_m'])
    # bodies, in the order of their first triangle
    broot = np.array([body.root(q) for q in range(npc)], dtype=np.int64); tb_ = broot[tp]
    ur, firstt = np.unique(tb_, return_index=True); border = ur[np.argsort(firstt, kind='stable')]
    area = tri_area(G); info = []
    ob = np.argsort(tb_, kind='stable'); bs = np.searchsorted(tb_[ob], ur); be = np.searchsorted(tb_[ob], ur, 'right'); pos_of = {int(r): k for k, r in enumerate(ur.tolist())}
    for r in border.tolist():
        k = pos_of[r]; ts = ob[bs[k]:be[k]]
        blo, bhi = tuple(G.mn[ts].min(0).tolist()), tuple(G.mx[ts].max(0).tolist())
        info.append({'triangles': len(ts), 'area_m2': sum(area[ts].tolist()), 'min': blo, 'max': bhi, 'size_m': dist(blo, bhi),
                     'names': sorted({labels[x] for x in set(tlab[ts].tolist())})[:6], 'root': r})
    info.sort(key=lambda b: -b['area_m2']); by_root = {b['root']: n for n, b in enumerate(info)}
    step = diag / 150
    if len(info) > 1 and not bodies_only:                # the gap from each floating body to the nearest other body
        miss = defaultdict(lambda: INF)
        for (a, b), d in near_miss.items():
            ra, rb = by_root[body.root(a)], by_root[body.root(b)]
            if ra != rb: miss[ra] = min(miss[ra], d); miss[rb] = min(miss[rb], d)
        sm = sbody = None
        for n, b in enumerate(info[1:13], 1):
            if miss[n] < INF: b['gap_m'] = miss[n]; continue
            if sm is None:
                sm, st = samples_v(G, step, 60000); bidx = np.array([by_root[int(r)] for r in broot.tolist()], dtype=np.int64); sbody = bidx[tp[st]]
            mine = sm[sbody == n]; mine = mine[::max(1, len(mine) // 300)]
            cellsz = max(step * 2, diag / 40)                # Grid.nearest of the scalar version: at most 10 cells (a quarter
            b['gap_m'] = nearest_point_dist(mine, sm[sbody != n], min(diag, 10 * cellsz))   # of the diagonal reads "at least")
    tick('bodies and their gaps')
    E = np.stack([wt[:, [0, 1]], wt[:, [1, 2]], wt[:, [0, 2]]], 1).reshape(-1, 2); E.sort(1)
    nv = len(first); code = E[:, 0] * nv + E[:, 1]
    ue, ef, einv, ecount = np.unique(code, return_index=True, return_inverse=True, return_counts=True)
    eo = np.argsort(ef, kind='stable'); ea, eb = ue[eo] // nv, ue[eo] % nv; en = ecount[eo]; etri = ef[eo] // 3
    pos = np.empty((len(first), 3)); pos[rank] = P[first]          # each welded corner at its first point
    real = ea != eb; openm = real & (en == 1)
    elen = np.sqrt(sq(pos[ea, 0] - pos[eb, 0]) + sq(pos[ea, 1] - pos[eb, 1]) + sq(pos[ea, 2] - pos[eb, 2]))
    oa, ob_, ot = ea[openm], eb[openm], etri[openm]
    open_len = sum(elen[openm].tolist()); all_len = sum(elen[real].tolist()) or 1.0
    pa, pbb = pos[oa], pos[ob_]; tick('open edges')
    return {'file': path, 'triangles': len(T), 'diagonal_m': diag, 'attach_m': attach, 'pieces': npc, 'bodies': info,
            'open_edges': int(openm.sum()), 'open_length_m': open_len, 'open_share': open_len / all_len, 'instanced_nodes': instanced,
            'mirrored_nodes': mirrored, 'gaps': gaps[:40], 'gap_count': len(gaps), 'meet_m': meet,
            'gap_pairs_unmeasured': budget2 <= 0 or timed_out, 'skinned': len(read_glb(path)[0].get('skins', [])) if path else 0, 'pairs_unmeasured': budget <= 0,
            '_G': G, '_P': P, '_T': T, '_labels': labels, '_tlab': tlab, '_wt': wt, '_tp': tp, '_ix': ix, '_pos': pos, '_body_of_piece': [by_root[int(r)] for r in broot.tolist()],
            '_open_a': pa, '_open_b': pbb, '_open_tri': ot, '_open_len': elen[openm], '_step': step}


# --------------------------------------------------------------------------------------------- points by area
def area_points(G, h, cap=250000, owner=False):
    """Points spread by AREA: one for every h*h of a triangle's area, placed evenly inside it (a slab 100 m wide gets
    inner points; a thousand tiny triangles get no more than their area deserves). One exception: a long thin triangle
    (a rail, a strut, a cable: longer than `h`, less than an eighth as high) gets a point every 2 h of its length, so
    what is thin is not absent. `h` grows until the whole model fits in `cap` points; returns (points, the h used[, owner])."""
    A, B, C = G.V[:, 0], G.V[:, 1], G.V[:, 2]
    ux, uy, uz = B[:, 0] - A[:, 0], B[:, 1] - A[:, 1], B[:, 2] - A[:, 2]; vx, vy, vz = C[:, 0] - A[:, 0], C[:, 1] - A[:, 1], C[:, 2] - A[:, 2]
    ar = 0.5 * np.sqrt(sq(uy * vz - uz * vy) + sq(uz * vx - ux * vz) + sq(ux * vy - uy * vx))
    lg = np.maximum(np.maximum(np.sqrt(sq(A[:, 0] - B[:, 0]) + sq(A[:, 1] - B[:, 1]) + sq(A[:, 2] - B[:, 2])),
                               np.sqrt(sq(B[:, 0] - C[:, 0]) + sq(B[:, 1] - C[:, 1]) + sq(B[:, 2] - C[:, 2]))),
                    np.sqrt(sq(A[:, 0] - C[:, 0]) + sq(A[:, 1] - C[:, 1]) + sq(A[:, 2] - C[:, 2])))
    thin = lg * lg > 16 * ar
    def want(h): return np.where((lg >= h) & thin, np.maximum(ar / (h * h), lg / (2 * h)), ar / (h * h))
    while sum(want(h).tolist()) > cap: h *= 1.12
    w = want(h); n = np.floor(w).astype(np.int64); t = np.arange(G.m, dtype=np.int64)
    n += ((t * 2654435761) % 1000003) / 1000003.0 < w - n                 # the fraction of a point, kept with the chance it deserves
    A1, A2 = 0.7548776662466927, 0.5698402909980532                         # an even, repeatable spread (the R2 sequence), folded into the triangle
    rep = np.repeat(t, n); q = np.arange(int(n.sum())) - np.repeat(np.cumsum(n) - n, n)
    u = np.mod(1 / 3 + q * A1, 1.0); v = np.mod(1 / 3 + q * A2, 1.0); f = u + v > 1.0
    u = np.where(f, 1.0 - u, u); v = np.where(f, 1.0 - v, v); m = 1.0 - u - v
    out = np.stack([A[rep, k] * m + B[rep, k] * u + C[rep, k] * v for k in range(3)], 1)
    return (out, h, rep) if owner else (out, h)


def view_dirs(below):
    """The 17 directions (level and from above; y is up), or 26 with `below`, each with its screen axes u, v."""
    out = []
    for d in [(x, y, z) for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1) if (x, y, z) != (0, 0, 0) and (below or y <= 0)]:
        n = math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2); d = (d[0] / n, d[1] / n, d[2] / n)
        a = (1.0, 0.0, 0.0) if abs(d[0]) < 0.9 else (0.0, 1.0, 0.0)
        u = (d[1] * a[2] - d[2] * a[1], d[2] * a[0] - d[0] * a[2], d[0] * a[1] - d[1] * a[0]); n = math.sqrt(u[0] ** 2 + u[1] ** 2 + u[2] ** 2); u = (u[0] / n, u[1] / n, u[2] / n)
        v = (d[1] * u[2] - d[2] * u[1], d[2] * u[0] - d[0] * u[2], d[0] * u[1] - d[1] * u[0]); out.append((d, u, v))
    return out


def screen(q, d, u, v, g):
    """Cell keys (one int per point) and depth of points q seen along d."""
    kx = np.floor((q[:, 0] * u[0] + q[:, 1] * u[1] + q[:, 2] * u[2]) / g).astype(np.int64)
    ky = np.floor((q[:, 0] * v[0] + q[:, 1] * v[1] + q[:, 2] * v[2]) / g).astype(np.int64)
    return kx * 4294967296 + ky, q[:, 0] * d[0] + q[:, 1] * d[1] + q[:, 2] * d[2]


def seen_from_outside(points, test, h, below=False):
    """For each point of `test`: can it be seen from outside the cloud `points` (the same surface, spread by area every `h`)?
    A depth map of the cloud from 17 directions (level and from above: what stands on the ground is not seen from below;
    `below=True` adds the nine from underneath, for what hangs or flies), cells of 2.5 h: a point is seen from a direction when nothing of the cloud
    lies more than a cell nearer to the viewer in its cell. Coarse on purpose: a floor behind a facade is hidden, the roof
    and the walls are seen. What looks out through an opening wider than a cell counts as seen."""
    g = 2.5 * h; seen = np.zeros(len(test), bool)
    for d, u, v in view_dirs(below):
        k, z = screen(points, d, u, v, g); uk, inv = np.unique(k, return_inverse=True); zmin = np.full(len(uk), INF); np.minimum.at(zmin, inv.ravel(), z)
        kt, zt = screen(test, d, u, v, g); j = np.searchsorted(uk, kt); jj = np.minimum(j, max(len(uk) - 1, 0))
        found = (j < len(uk)) & (uk[jj] == kt) if len(uk) else np.zeros(len(kt), bool)
        seen |= zt <= np.where(found, zmin[jj], 1e30) + g
    return seen.tolist()


def regions(points, c, total):
    """Points joined into regions when they are neighbours on a grid of `c` (the 26 neighbouring cells), each with its
    share of `total` and its box; largest first. The grid cells are visited as the scalar version visits them."""
    cells = defaultdict(list)
    for q in points: cells[(int(math.floor(q[0] / c)), int(math.floor(q[1] / c)), int(math.floor(q[2] / c)))].append(q)
    out = []; todo = set(cells)
    while todo:
        st = [todo.pop()]; got = []
        while st:
            k3 = st.pop(); got += cells[k3]
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        nb = (k3[0] + dx, k3[1] + dy, k3[2] + dz)
                        if nb in todo: todo.discard(nb); st.append(nb)
        blo, bhi = bbox(got); out.append({'share': len(got) / max(1, total), 'min': blo, 'max': bhi})
    out.sort(key=lambda r: -r['share'])
    return out


def looked_into(m, below=False):
    """How much of what a viewer sees from outside is the BACK of a face. A closed solid shows only fronts. A back means
    the viewer is looking INTO something: through a missing wall, an open top, a skeleton with no skin, or at a
    single sheet from behind. With a one-sided material nothing is drawn there (one sees straight through); with a
    two-sided one the inside is drawn. Either way it is where to look.

    Seventeen directions (level and from above; `below` adds nine from underneath). For each, a depth map of points
    spread by area, cells of 2.5 point spacings: a cell counts as a back when no front-facing point lies within one
    cell's depth of its nearest point (so a thin slab with both faces is a front)."""
    G = m['_G']; cloud, h, owner = area_points(G, m['diagonal_m'] / 400, owner=True); g = 2.5 * h
    nx, ny, nz = G.aby * G.acz - G.abz * G.acy, G.abz * G.acx - G.abx * G.acz, G.abx * G.acy - G.aby * G.acx
    L = np.sqrt(nx * nx + ny * ny + nz * nz); L = np.where(L == 0, 1.0, L); nrm = np.stack([nx / L, ny / L, nz / L], 1)[owner]
    cells_all = cells_back = 0; worst = (0.0, None); back_pts = []
    for d, u, v in view_dirs(below):
        f = nrm[:, 0] * d[0] + nrm[:, 1] * d[1] + nrm[:, 2] * d[2]
        keep = np.flatnonzero(~((-0.25 < f) & (f < 0.25)))                # a face seen edge-on shows no area to this viewer
        k, z = screen(cloud[keep], d, u, v, g); fr = f[keep] < 0
        uk, inv = np.unique(k, return_inverse=True); inv = inv.ravel()
        zf = np.full(len(uk), INF); np.minimum.at(zf, inv[fr], z[fr])
        bk = np.flatnonzero(~fr); za = np.full(len(uk), INF); np.minimum.at(za, inv[bk], z[bk])
        hasb = np.zeros(len(uk), bool); hasb[inv[bk]] = True
        zfront = np.where(np.isinf(zf), 1e30, zf)
        backc = np.flatnonzero(hasb & (zfront > za + g))                    # a back nearer than any front by more than a cell
        # each back cell's nearest back point (the first one at that depth), cells in the order of their first back point
        at = bk[z[bk] == za[inv[bk]]]; firstat = np.full(len(uk), len(z)); np.minimum.at(firstat, inv[at], at)
        firstany = np.full(len(uk), len(z)); np.minimum.at(firstany, inv[bk], bk)
        backc = backc[np.argsort(firstany[backc], kind='stable')]
        cells_all += len(uk); cells_back += len(backc); back_pts += cloud[keep][firstat[backc]].tolist()
        if len(uk) and len(backc) / len(uk) > worst[0]: worst = (len(backc) / len(uk), d)
    c = max(g * 3, m['diagonal_m'] / 20); places = regions(back_pts, c, len(back_pts))
    return {'back_share': cells_back / max(1, cells_all), 'worst_direction_share': worst[0], 'worst_direction': worst[1], 'places': places[:5], 'place_count': len(places)}


def open_kinds(m):
    """The open edge length in three kinds. ON THE GROUND: at the model's lowest level, the rim of a thing that stands on
    something. RESTING ON A SURFACE: the edge lies on (within the attach distance of) another triangle, as a sheet that
    ends on a wall or a T-joint does: closed to the eye. FREE: neither. Whether a free edge is a crack one can look
    into is not decided here (a rim can be seen while its opening faces the ground): `looked_into` answers that."""
    A, B, own = m['_open_a'], m['_open_b'], m['_open_tri']
    if not len(A): return None
    G, ix = m['_G'], m['_ix']; P = m['_P']; lo = tuple(P.min(0).tolist()); hi = tuple(P.max(0).tolist())
    floor = lo[1] + max(m['attach_m'], (hi[1] - lo[1]) * 0.002); att = m['attach_m']; step = m['diagonal_m'] / 160
    L = m['_open_len']; ground = np.maximum(A[:, 1], B[:, 1]) <= floor
    k = np.maximum(1, np.minimum(40, np.floor(L / step).astype(np.int64) + 1)); k[ground] = 0
    e = np.repeat(np.arange(len(A)), k); q = np.arange(int(k.sum())) - np.repeat(np.cumsum(k) - k, k)
    t = (q + 0.5) / k[e]; Q = np.stack([A[e, j] + (B[e, j] - A[e, j]) * t for j in range(3)], 1)
    rest = rests_v(G, ix, Q, own[e], att, lo)
    contrib = L[e] / k[e]
    acc = lambda x: float(np.cumsum(x)[-1]) if len(x) else 0.0            # added one by one, in order, as before
    return {'ground_m': acc(L[ground]), 'resting_m': acc(contrib[rest]), 'free_m': acc(contrib[~rest])}


def rests_v(G, ix, Q, own, att, lo):
    """For each point: does a triangle other than `own` lie within `att` of it (the 27 cells round it, then the very
    large triangles)?"""
    out = np.zeros(len(Q), bool)
    if not len(Q): return out
    c0 = ix.c; cell = np.floor((Q - np.array(lo)) / c0).astype(np.int64)
    for dx in ((-1, 0, 1) if len(ix.c_code) else ()):       # no small triangles at all (a few big faces): only the big ones
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                x, y, z = cell[:, 0] + dx - ix.o[0], cell[:, 1] + dy - ix.o[1], cell[:, 2] + dz - ix.o[2]
                okc = (x >= 0) & (y >= 0) & (y < ix.ny) & (z >= 0) & (z < ix.nz) & ~out
                code = (x * ix.ny + y) * ix.nz + z; j = np.searchsorted(ix.c_code, code); jj = np.minimum(j, len(ix.c_code) - 1)
                hit = np.flatnonzero(okc & (j < len(ix.c_code)) & (ix.c_code[jj] == code))
                if not len(hit): continue
                s, e = ix.c_start[jj[hit]], ix.c_end[jj[hit]]; n = e - s
                pi = np.repeat(hit, n); ti = ix.c_t[np.repeat(s, n) + (np.arange(int(n.sum())) - np.repeat(np.cumsum(n) - n, n))]
                ok = ti != own[pi]; q = Q[pi]
                ok &= (G.mn[ti, 0] - att <= q[:, 0]) & (q[:, 0] <= G.mx[ti, 0] + att) & (G.mn[ti, 1] - att <= q[:, 1]) & (q[:, 1] <= G.mx[ti, 1] + att) & (G.mn[ti, 2] - att <= q[:, 2]) & (q[:, 2] <= G.mx[ti, 2] + att)
                pi, ti = pi[ok], ti[ok]
                if len(pi): out[pi[pt_tri_v(G, Q[pi, 0], Q[pi, 1], Q[pi, 2], ti, True) <= att]] = True
    if len(ix.all_big):
        for t in ix.all_big.tolist():
            idx = np.flatnonzero(~out & (own != t))
            if len(idx): out[idx[pt_tri_v(G, Q[idx, 0], Q[idx, 1], Q[idx, 2], np.full(len(idx), t), True) <= att]] = True
    return out


# --------------------------------------------------------------------------------------------- non-manifold, solids
def non_manifold(m):
    """Edges where more than two faces meet; neighbouring faces of one part (one mesh) that wind opposite ways; zero-area
    faces; duplicate faces; and per piece: closed or open, signed volume. Welded corners, as everywhere above."""
    G, wt, tp, labels, tlab = m['_G'], m['_wt'], m['_tp'], m['_labels'], m['_tlab']; pos = m['_pos']; M = len(wt)
    two = 2 * tri_area(G)
    zero = (two < 2e-8) | (wt[:, 0] == wt[:, 1]) | (wt[:, 1] == wt[:, 2]) | (wt[:, 0] == wt[:, 2])
    good = np.flatnonzero(~zero)
    # duplicates: the same three welded corners
    srt = np.sort(wt[good], 1); key = np.ascontiguousarray(srt).view([('', srt.dtype)] * 3).ravel()
    _, dfirst, dinv, dcnt = np.unique(key, return_index=True, return_inverse=True, return_counts=True); dinv = dinv.ravel()
    isdup = dcnt[dinv] > 1; extra = np.ones(len(good), bool); extra[dfirst] = False; dupx = good[isdup & extra]   # second and later copies
    rot = lambda w: np.where((w[:, 0] < w[:, 1]) & (w[:, 0] < w[:, 2]), 0, np.where(w[:, 1] < w[:, 2], 1, 2))
    def canon(w):                                        # the corners turned so the smallest comes first (keeps the winding)
        r = rot(w); return np.stack([w[np.arange(len(w)), r], w[np.arange(len(w)), (r + 1) % 3], w[np.arange(len(w)), (r + 2) % 3]], 1)
    cf = canon(wt[good]); same_dup = isdup & extra & np.all(cf == cf[dfirst[dinv]], 1)
    # directed edges of the faces that count (non-degenerate, first copy of a duplicate)
    use = good[~(isdup & extra)]; w = wt[use]
    da = np.concatenate([w[:, 0], w[:, 1], w[:, 2]]); db = np.concatenate([w[:, 1], w[:, 2], w[:, 0]]); dt = np.tile(use, 3)
    nv = len(pos); lo_, hi_ = np.minimum(da, db), np.maximum(da, db); code = lo_ * nv + hi_; fwd = da < db
    o = np.argsort(code, kind='stable'); code, fwd, dt = code[o], fwd[o], dt[o]
    st = np.flatnonzero(np.r_[True, code[1:] != code[:-1]]); en = np.r_[st[1:], len(code)]; cnt = en - st
    many = cnt > 2
    pair = cnt == 2; s2 = st[pair]
    flip = fwd[s2] == fwd[s2 + 1]                       # both faces walk the edge the same way: one is turned over
    same_part = tlab[dt[s2]] == tlab[dt[s2 + 1]]
    flipm = flip & same_part
    # turned over or folded? For two faces that wind opposite ways the dot of their normals is the cosine of the angle
    # between the two sheets. Near 180 degrees (a smooth surface, dot near -1) down to a right angle (a box corner, dot
    # 0): one face of a continuous surface is turned over. Under 75 degrees (dot above cos 75): the sheet folds back on
    # its neighbour (a lip, a fin of one sheet: a car's roof lip at 67 degrees, both sheets facing out); no winding
    # draws both of its sides, so turning a face would not help: counted, not pointed at.
    f1, f2 = dt[s2][flipm], dt[s2 + 1][flipm]
    nrm = lambda t: (lambda c: c / np.maximum(np.linalg.norm(c, axis=1), 1e-300)[:, None])(np.cross(G.V[t, 1] - G.V[t, 0], G.V[t, 2] - G.V[t, 0]))
    turned = np.einsum('ij,ij->i', nrm(f1), nrm(f2)) <= math.cos(math.radians(75))
    fe = code[s2][flipm][turned]; fa, fb = fe // nv, fe % nv
    flip_mid = (pos[fa] + pos[fb]) / 2; flip_lab = tlab[f1[turned]]
    # per piece: closed = every edge of it has two faces winding opposite ways (and no open edge, no edge of 3+)
    gflip = np.zeros(len(st), bool); gflip[np.flatnonzero(pair)[flip]] = True
    bad_edge_tri = dt[np.repeat((cnt != 2) | gflip, cnt)]             # faces on an open edge, an edge of 3+, or a turned edge
    npc = int(tp.max()) + 1; badp = np.zeros(npc, bool); badp[tp[bad_edge_tri]] = True
    hasf = np.zeros(npc, bool); hasf[tp[use]] = True; closed = hasf & ~badp
    # signed volume per piece about its own box centre (a tetrahedron per face); area per piece for the flatness test
    pmn = np.full((npc, 3), INF); pmx = np.full((npc, 3), -INF); np.minimum.at(pmn, tp, G.mn); np.maximum.at(pmx, tp, G.mx)
    cen = (pmn + pmx) / 2; cu = cen[tp[use]]
    A, B, C = G.V[use, 0] - cu, G.V[use, 1] - cu, G.V[use, 2] - cu
    vol6 = np.einsum('ij,ij->i', A, np.cross(B, C)); vol = np.zeros(npc); np.add.at(vol, tp[use], vol6 / 6)
    par = np.zeros(npc); np.add.at(par, tp[use], two[use] / 2)
    solid = closed & (np.abs(vol) > 1e-4 * par ** 1.5)   # a closed part with a real inside (not two sheets back to back)
    inside_out = np.flatnonzero(solid & (vol < 0))
    res = {'edges_over_two_faces': int(many.sum()), 'flipped_edges': int(flipm.sum()), 'flipped_parts': len(set(tlab[f1].tolist())),
           'turned_edges': int(turned.sum()), 'turned_parts': len(set(flip_lab.tolist())), 'folded_edges': int((~turned).sum()),
           'zero_area_faces': int(zero.sum()), 'duplicate_faces': int(len(dupx)), 'duplicate_same_facing': int(same_dup.sum()),
           'pieces_closed': int(closed.sum()), 'pieces_solid': int(solid.sum()), 'inside_out_parts': int(len(inside_out))}
    # places: turned edges grouped per part, then by neighbourhood
    fp = []
    for L in sorted(set(flip_lab.tolist())):
        sel = flip_lab == L
        for rg in regions(flip_mid[sel].tolist(), m['diagonal_m'] / 20, int(sel.sum())):
            fp.append({'edges': round(rg['share'] * int(sel.sum())), 'centre': [(rg['min'][k] + rg['max'][k]) / 2 for k in range(3)], 'min': rg['min'], 'max': rg['max'], 'name': labels[L]})
    fp.sort(key=lambda p: -p['edges']); res['turned_places'] = fp[:8]
    dp = []
    for t in dupx[:200].tolist():
        dp.append({'centre': ((G.V[t, 0] + G.V[t, 1] + G.V[t, 2]) / 3).tolist(), 'area_m2': float(two[t] / 2), 'name': labels[tlab[t]]})
    dp.sort(key=lambda p: -p['area_m2']); res['duplicate_places'] = dp[:5]
    io = []
    for q in inside_out.tolist():
        ts = np.flatnonzero(tp == q)
        io.append({'volume_m3': float(vol[q]), 'size_m': dist(pmn[q].tolist(), pmx[q].tolist()), 'centre': cen[q].tolist(), 'min': pmn[q].tolist(), 'max': pmx[q].tolist(),
                   'names': sorted({labels[x] for x in set(tlab[ts].tolist())})[:4]})
    io.sort(key=lambda p: p['volume_m3']); res['inside_out_places'] = io[:8]
    # per body
    bop = np.array(m['_body_of_piece'], dtype=np.int64); nb = len(m['bodies'])
    per = []
    for n in range(nb):
        ps = np.flatnonzero((bop == n) & hasf)
        per.append({'pieces': int(len(ps)), 'closed_pieces': int(closed[ps].sum()), 'closed': bool(len(ps) and closed[ps].all()),
                    'volume_m3': float(vol[ps[closed[ps]]].sum()), 'inside_out': int(np.isin(ps, inside_out).sum())})
    res['bodies'] = per
    return res


# ------------------------------------------------------------------------------------------------------- flicker
def clip_half(poly, cnt, f):
    """Polygons (P,W,2) with `cnt` corners cut to the half-plane where the linear function f >= 0 (Sutherland-Hodgman,
    vectorised over the polygons); f(poly) gives its value at every corner."""
    Pn, Wd = poly.shape[:2]; col = np.arange(Wd)[None, :]; fu = f(poly)
    valid = col < cnt[:, None]; nxt = np.where(col + 1 < cnt[:, None], col + 1, 0)
    fv = np.take_along_axis(fu, nxt, 1); vv = np.take_along_axis(poly, nxt[:, :, None], 1)
    ein = valid & (fu >= 0); ecut = valid & ((fu >= 0) != (fv >= 0)) & (fu != fv)
    ne = ein.astype(np.int64) + ecut; off = np.cumsum(ne, 1) - ne; ncnt = ne.sum(1); Wn = max(1, int(ncnt.max()) if Pn else 1)
    new = np.zeros((Pn, Wn, 2))
    r, c = np.nonzero(ein); new[r, off[r, c]] = poly[r, c]
    r, c = np.nonzero(ecut); w = fu[r, c] / (fu[r, c] - fv[r, c]); new[r, off[r, c] + ein[r, c]] = poly[r, c] + w[:, None] * (vv[r, c] - poly[r, c])
    return new, ncnt


def shoelace(poly, cnt):
    """Signed area and centroid of polygons (P,W,2) with `cnt` corners."""
    Wd = poly.shape[1]; col = np.arange(Wd)[None, :]; valid = col < cnt[:, None]; nxt = np.where(col + 1 < cnt[:, None], col + 1, 0)
    x, y = poly[:, :, 0], poly[:, :, 1]; xn, yn = np.take_along_axis(x, nxt, 1), np.take_along_axis(y, nxt, 1)
    cr = np.where(valid, x * yn - xn * y, 0.0); a2 = cr.sum(1) / 2
    with np.errstate(invalid='ignore', divide='ignore'):
        cx = np.where(valid, (x + xn) * cr, 0).sum(1) / (6 * a2); cy = np.where(valid, (y + yn) * cr, 0).sum(1) / (6 * a2)
    return np.where(cnt >= 3, a2, 0.0), cx, cy


def dense_ids(key):
    """Rows of small integers (N,k) -> 0..groups-1, equal rows equal ids (one int64 per row when the ranges fit)."""
    lo = key.min(0); span = key.max(0) - lo + 1
    if float(np.prod(span.astype(np.float64))) < 2 ** 62:
        code = np.zeros(len(key), np.int64)
        for c in range(key.shape[1]): code = code * int(span[c]) + (key[:, c] - lo[c])
        return np.unique(code, return_inverse=True)[1].ravel()
    kb = np.ascontiguousarray(key).view([('', key.dtype)] * key.shape[1]).ravel(); return np.unique(kb, return_inverse=True)[1].ravel()


def flicker_candidates(G, ok, nu, d, dd, lo, diag):
    """Pairs of triangles (lower id first, each pair once) that may blink: normals within ~1.4 degrees (either way round)
    and boxes within 2 dd. Each triangle is filed under every key its tolerances reach: the cell of its (sign-canonical)
    normal, every block of space its box touches, and the cell of its plane offset measured from that block's centre (so
    the offset's slack is set by the block, not by how far the model sits from the origin). Within a key the triangles
    are swept along an axis in their plane."""
    hn = math.sqrt(2 - 2 * 0.9997) / 2 + 1e-9                          # half the largest normal difference of a pair
    S = max(0.25, diag / 50); slack = dd + 2 * hn * S * math.sqrt(3) / 2  # how far apart two offsets in one block can be
    W = 2 * slack; lo = np.asarray(lo, dtype=np.float64)
    gdir = np.array([3.0, 2.0, 1.0]) / math.sqrt(14.0); pr = nu @ gdir
    keys, tris = [], []
    for s, sel in ((1.0, pr >= -0.03), (-1.0, pr < 0.03)):           # a normal near the sign plane is filed both ways
        i = np.flatnonzero(sel); t = ok[i]; nc = nu[i] * s
        n0 = np.floor((nc - hn) / 0.05 + 0.5).astype(np.int64); n1 = np.floor((nc + hn) / 0.05 + 0.5).astype(np.int64)
        b0 = np.floor((G.mn[t] - 2 * dd - lo) / S).astype(np.int64); b1 = np.floor((G.mx[t] + 2 * dd - lo) / S).astype(np.int64)
        span = b1 - b0 + 1; nb = span[:, 0] * span[:, 1] * span[:, 2]
        e = np.repeat(np.arange(len(i)), nb); j = np.arange(int(nb.sum())) - np.repeat(np.cumsum(nb) - nb, nb)
        sy, sz = span[e, 1], span[e, 2]
        bx = b0[e, 0] + j // (sy * sz); by = b0[e, 1] + (j // sz) % sy; bz = b0[e, 2] + j % sz
        cb = lo + (np.stack([bx, by, bz], 1) + 0.5) * S
        dc = s * (d[i][e] - np.einsum('ij,ij->i', nu[i][e], cb))       # canonical offset seen from the block's centre
        o0 = np.floor((dc - slack / 2) / W).astype(np.int64); o1 = np.floor((dc + slack / 2) / W).astype(np.int64)
        for combo in range(16):                                      # every normal and offset cell the tolerances reach
            off = [(combo >> k) & 1 for k in range(4)]
            c = np.stack([n0[e, 0] + off[0], n0[e, 1] + off[1], n0[e, 2] + off[2]], 1); oc = o0 + off[3]
            keep = np.all(c <= n1[e], 1) & (oc <= o1)
            if keep.any():
                keys.append(np.stack([c[keep, 0], c[keep, 1], c[keep, 2], bx[keep], by[keep], bz[keep], oc[keep]], 1)); tris.append(t[e[keep]])
    key = np.concatenate(keys); tri = np.concatenate(tris)
    gid = dense_ids(key)
    ax = (np.argmax(np.abs(key[:, :3]), 1) + 1) % 3                  # sweep along an axis that lies in the plane
    smin = G.mn[tri, ax] - dd; smax = G.mx[tri, ax] + dd
    o = np.lexsort((smin, gid)); gid, smin, smax, tri = gid[o], smin[o], smax[o], tri[o]
    base = float(smin.min()); R = float(smax.max() - base) + 1.0
    gk = gid * (2 * R) + (smin - base); end = np.searchsorted(gk, gid * (2 * R) + (smax - base), 'right')
    n = np.maximum(end - np.arange(len(gk)) - 1, 0); cum = np.cumsum(n); out = []
    s0 = 0
    while s0 < len(gk):                                              # in slices of about 4 million candidate pairs
        s1 = int(np.searchsorted(cum, (cum[s0 - 1] if s0 else 0) + 4_000_000, 'right')); s1 = max(s1, s0 + 1)
        nn = n[s0:s1]; I = np.repeat(np.arange(s0, s1), nn); J = I + 1 + (np.arange(int(nn.sum())) - np.repeat(np.cumsum(nn) - nn, nn))
        sel = (gid[I] == gid[J]) & (tri[I] != tri[J]); I, J = I[sel], J[sel]
        ta, tb = np.minimum(tri[I], tri[J]), np.maximum(tri[I], tri[J])
        sel = np.all(G.mn[ta] <= G.mx[tb] + 2 * dd, 1) & np.all(G.mn[tb] <= G.mx[ta] + 2 * dd, 1)   # 2 dd: along an axis the gap is up to sqrt(3) dd
        out.append(np.unique(ta[sel] * G.m + tb[sel])); s0 = s1
    pc = np.unique(np.concatenate(out)) if out else np.zeros(0, np.int64)
    return pc // G.m, pc % G.m


SAME_PLACE = 0.0001                                      # two faces of one part this close, back to back: a face and its flipped copy


def pair_places(ta, ov, c3, sepm, la, lb, dup, labels, cell=0.5):
    """Overlapping face pairs gathered into places: the pairs of one pair of parts whose overlaps are neighbours on a grid
    of `cell` meters (the 26 neighbouring cells). Per place: the summed overlap, the number of pairs, the centre of its
    largest overlap (a point on the surface, for a camera), the box of the overlaps' centres, the smallest distance
    between the two faces, and how much of it is a face with its flipped copy (`dup`). Largest first."""
    if not len(ta): return []
    key = np.concatenate([np.stack([la, lb], 1), np.floor(c3 / cell).astype(np.int64)], 1)
    uk, inv = np.unique(key, axis=0, return_inverse=True); inv = inv.ravel()
    at = {tuple(k): n for n, k in enumerate(uk.tolist())}; uf = Find(len(uk))
    for (a, b, x, y, z), n in at.items():
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    o = at.get((a, b, x + dx, y + dy, z + dz))
                    if o is not None and o > n: uf.join(n, o)
    grp = np.array([uf.root(n) for n in range(len(uk))], dtype=np.int64)[inv]
    o = np.lexsort((ta, -ov, grp)); st = np.flatnonzero(np.r_[True, grp[o][1:] != grp[o][:-1]]); out = []
    for s, e in zip(st.tolist(), np.r_[st[1:], len(o)].tolist()):
        k = o[s:e]; big = k[0]; dk = k[dup[k]]
        out.append({'overlap_m2': float(ov[k].sum()), 'pairs': int(len(k)), 'largest_m2': float(ov[big]), 'centre': c3[big].tolist(),
                    'min': c3[k].min(0).tolist(), 'max': c3[k].max(0).tolist(), 'apart_m': float(sepm[k].min()),
                    'names': sorted({labels[la[big]], labels[lb[big]]}), 'one_part': bool(la[big] == lb[big]),
                    'flipped_duplicate_pairs': int(len(dk)), 'flipped_duplicate_m2': float(ov[dk].sum())})
    out.sort(key=lambda p: (-p['overlap_m2'], p['centre']))
    return out


def flicker(m, gap):
    """Faces that share a plane and overlap: the depth buffer cannot order them, so they blink as the camera moves
    (z-fighting; owner 2026-10-12 22:35: "sometimes I get blinking sides on assets"). Two triangles (of different draws,
    or of one draw with no shared corner) whose normals are within ~1.4 degrees, that overlap and lie within `gap` of each
    other over more than 1 mm2 (true area, in the plane; plus the weld tolerance, so float noise in an export does not
    decide a pair laid exactly `gap` apart). The area counted is that band: all of the overlap for parallel faces, the
    strip along the crossing for faces at a slight angle. Facing the
    same way = blinks always; back to back = blinks only where the material is double-sided.

    2026-10-13: every such pair is found, and only those. The first version filed each triangle in one cell of normal and
    plane offset and looked in two neighbouring offsets only: it missed pairs whose normals fell either side of a cell
    edge, pairs whose normal's sign was decided by float noise (-0.0 against +0.0), and pairs already passed over while
    scanning a neighbouring cell; it compared plane offsets measured from the world origin (two faces at 0.8 degrees,
    4.6 m from the origin and 15 mm apart counted as one plane; the count changed when the model moved); and it measured
    the overlap in a projection (too small on a sloping face). Now each triangle is filed in every cell of normal and
    offset its tolerance reaches, the candidates are swept along the plane and deduplicated, and the gap and the area are
    measured on the overlap itself."""
    G, T = m['_G'], m['_T']; labels, tlab = m['_labels'], m['_tlab']
    tol = max(m['diagonal_m'] * 1e-6, 1e-6); dd = gap + tol
    nx, ny, nz = G.aby * G.acz - G.abz * G.acy, G.abz * G.acx - G.abx * G.acz, G.abx * G.acy - G.aby * G.acx
    l = np.sqrt(nx * nx + ny * ny + nz * nz); ok = np.flatnonzero(l >= 2e-8)
    nu = np.stack([nx[ok] / l[ok], ny[ok] / l[ok], nz[ok] / l[ok]], 1); d = nu[:, 0] * G.ax[ok] + nu[:, 1] * G.ay[ok] + nu[:, 2] * G.az[ok]
    ta, tb = flicker_candidates(G, ok, nu, d, dd, m['_P'].min(0), m['diagonal_m'])
    inv = np.full(G.m, -1); inv[ok] = np.arange(len(ok)); ia, ib = inv[ta], inv[tb]
    dot = np.einsum('ij,ij->i', nu[ia], nu[ib])
    sel = (np.abs(dot) >= 0.9997) & ~(T[ta][:, :, None] == T[tb][:, None, :]).any((1, 2))   # no shared corner of one draw
    ta, tb, ia, ib, dot = ta[sel], tb[sel], ia[sel], ib[sel], dot[sel]
    ov = np.zeros(0); c3 = np.zeros((0, 3))
    if len(ta):
        dom = np.argmax(np.abs(nu[ia]), 1); a0 = (dom + 1) % 3; a1 = (dom + 2) % 3; r = np.arange(len(ta))
        coord = lambda V, k: np.take_along_axis(V, np.repeat(k[:, None, None], 3, 1), 2)[:, :, 0]
        Va, Vb = G.V[ta], G.V[tb]; pa = np.stack([coord(Va, a0), coord(Va, a1)], 2); pb = np.stack([coord(Vb, a0), coord(Vb, a1)], 2)
        keep = np.zeros(len(ta), bool); ov = np.zeros(len(ta)); c3 = np.zeros((len(ta), 3))
        for s0 in range(0, len(ta), 100000):
            k = np.arange(s0, min(s0 + 100000, len(ta))); A2, B2 = pa[k], pb[k]; rk = np.arange(len(k))
            na, nb = nu[ia[k]], nu[ib[k]]; nd = na[rk, dom[k]]
            sg = np.where(((B2[:, 0, 0] * B2[:, 1, 1] - B2[:, 1, 0] * B2[:, 0, 1]) + (B2[:, 1, 0] * B2[:, 2, 1] - B2[:, 2, 0] * B2[:, 1, 1]) + (B2[:, 2, 0] * B2[:, 0, 1] - B2[:, 0, 0] * B2[:, 2, 1])) > 0, 1.0, -1.0)
            poly, cnt = A2.copy(), np.full(len(k), 3)
            for q in range(3):                           # the first face cut to the second (both seen along the first's normal)
                e0, e1 = B2[:, q], B2[:, (q + 1) % 3]
                poly, cnt = clip_half(poly, cnt, lambda pl: sg[:, None] * ((e1[:, None, 0] - e0[:, None, 0]) * (pl[:, :, 1] - e0[:, None, 1]) - (e1[:, None, 1] - e0[:, None, 1]) * (pl[:, :, 0] - e0[:, None, 0])))
            # the distance from the second face's plane of a point of the overlap (lifted onto the first face's plane) is
            # linear in the overlap's coordinates: keep the band where it is within the gap (all of it for parallel faces)
            al = nb[rk, a0[k]] - nb[rk, dom[k]] * na[rk, a0[k]] / nd; be = nb[rk, a1[k]] - nb[rk, dom[k]] * na[rk, a1[k]] / nd
            ga = nb[rk, dom[k]] * d[ia[k]] / nd - d[ib[k]]
            sep = lambda pl: al[:, None] * pl[:, :, 0] + be[:, None] * pl[:, :, 1] + ga[:, None]
            poly, cnt = clip_half(poly, cnt, lambda pl: dd - sep(pl)); poly, cnt = clip_half(poly, cnt, lambda pl: sep(pl) + dd)
            a2, cx, cy = shoelace(poly, cnt)
            area = np.abs(a2) / np.abs(nd)                # the projection shrinks a sloping face by |n_dom|
            keep[k] = area > 1e-6; ov[k] = area
            with np.errstate(invalid='ignore'):
                c3[k, a0[k]] = cx; c3[k, a1[k]] = cy; c3[k, dom[k]] = (d[ia[k]] - na[rk, a0[k]] * cx - na[rk, a1[k]] * cy) / nd
        ta, tb, dot, ov, c3 = ta[keep], tb[keep], dot[keep], ov[keep], c3[keep]
        sepm = np.abs(np.einsum('ij,ij->i', nu[inv[tb]], c3) - d[inv[tb]])     # how far apart the two faces are at the overlap's centre
    else:
        dot = np.zeros(0); sepm = np.zeros(0)
    same = dot > 0; back = ~same
    # Back-to-back pairs gathered into PLACES (2026-10-13: they were counted and never placed, so a copied, flipped face
    # could not be found). Most back-to-back pairs are harmless: two solids resting exactly on each other. The ones that
    # are a face and its flipped copy lie in the SAME place (within SAME_PLACE) and belong to ONE part: counted apart.
    la, lb = np.minimum(tlab[ta], tlab[tb]), np.maximum(tlab[ta], tlab[tb])
    dup = back & (la == lb) & (sepm <= SAME_PLACE + tol)
    bplaces = pair_places(ta[back], ov[back], c3[back], sepm[back], la[back], lb[back], dup[back], labels)
    order = np.lexsort((-tb[same], -ta[same], -ov[same])) if same.any() else np.zeros(0, np.int64)
    places = []
    for k in order[:8].tolist():
        sa, sb = ta[same][k], tb[same][k]
        places.append({'overlap_m2': float(ov[same][k]), 'centre': c3[same][k].tolist(), 'names': sorted({labels[tlab[sa]], labels[tlab[sb]]})})
    return {'gap_m': gap, 'same_facing_pairs': int(same.sum()), 'same_facing_m2': float(ov[same].sum()),
            'largest_same_m2': float(ov[same].max()) if same.any() else 0, 'back_to_back_pairs': int(back.sum()),
            'back_to_back_m2': float(ov[back].sum()), 'places': places,
            'back_to_back_places': bplaces[:40], 'back_to_back_place_count': len(bplaces),
            'flipped_duplicate_pairs': int(dup.sum()), 'flipped_duplicate_m2': float(ov[dup].sum()), 'same_place_m': SAME_PLACE,
            'flipped_duplicate_places': sorted((p for p in bplaces if p['flipped_duplicate_pairs']), key=lambda p: -p['flipped_duplicate_m2'])[:8]}


# ------------------------------------------------------------------------------------------------------- against
def against(model, ref, below=False, backdrop=None, workers=None):
    """Surface distances both ways, lost parts and new open edges of `model` measured against `ref`.

    Points are spread over each surface by AREA (one about every `h` meters) and each point's distance to the OTHER
    surface is exact (point to triangle). 2026-10-12: the first version measured point to thinned corner points, and on
    a stadium with a wall face 25 m tall reported 12 m where the true distance was 1.5 m. What remains unseen: a lost
    part smaller than `h` (`resolution_m`).

    2026-10-13 (2): the two files are compared WITHOUT their ground or backdrop (`subject`), and a second pass measures
    every part with its own points (`parts_moved`). Before, a 200 m ground under a car set the point spacing to 0.7 m
    and the tolerance to 2.8 m, put nearly all 20,000 points on the ground, and eight parts moved 1 to 8 mm read as
    "up to 6 mm, 95 % within 0" with no place. With no ground in the file the first pass gives the numbers it gave."""
    sm, sr = subject(model, backdrop), subject(ref, backdrop)                # each file without its ground / backdrop
    diag = sr['diagonal_m']; tol = diag * 0.01; far = max(tol * 8, diag * 0.1)
    pm, hm = area_points(sm['G'], diag / 400); pr, hr = area_points(sr['G'], diag / 400)
    for x in (sm, sr): x['ix'] = Index(x['G'], np.zeros(x['G'].m, np.int64), x['lo'], x['hi'])
    def side(src, x):
        sub = src[::max(1, len(src) // 20000)]; raw = reach(x['G'], x['ix'], sub, tol / 4, far)
        ds = sorted(raw.tolist()); return ds[-1], ds[int(len(ds) * 0.95)], raw.tolist(), sub
    here_max, here_p95, _, _ = side(pm, sr); ref_max, ref_p95, raw, sub = side(pr, sm); tick('against: surfaces by area')
    parts = parts_moved(sm, sr, tol, workers); tick('against: part by part')
    here_max = max(here_max, parts['this_max_m']); ref_max = max(ref_max, parts['reference_max_m'])
    lost_share = sum(1 for d in raw if d > tol) / max(1, len(raw))           # area-even points: a share of points is a share of surface
    out = seen_from_outside(pr, sub, max(hm, hr), below); n_out = sum(out) or 1     # a lower version rightly leaves out what cannot be seen (a design decision)
    lost_seen = sum(1 for d, o in zip(raw, out) if o and d > tol) / n_out
    ladder = [(k, sum(1 for d, o in zip(raw, out) if o and d > diag * k) / n_out) for k in (0.01, 0.02, 0.03, 0.05, 0.08)]   # the same loss at wider tolerances
    # Where the seen loss is: lost points joined when they are neighbours on a grid of 4 h, the largest five regions.
    lost_pts = [q for q, d, o in zip(sub.tolist(), raw, out) if o and d > tol]
    rg = [{'share_of_seen': r_['share'], 'min': r_['min'], 'max': r_['max']} for r_ in regions(lost_pts, 4 * max(hm, hr), n_out)]
    tol2 = tol * 2; ra, rb = ref['_open_a'], ref['_open_b']
    new_open = 0
    if len(model['_open_len']):
        mid = (model['_open_a'] + model['_open_b']) / 2
        if len(ra):
            rmid = (ra + rb) / 2; near_ = nearest_point_each(mid, rmid, tol2)
            new = near_ > tol
        else:
            new = np.ones(len(mid), bool)
        new_open = sum(model['_open_len'][new].tolist())
    return {'reference': ref['file'], 'diagonal_m': diag, 'left_out': sm['left_out'], 'reference_left_out': sr['left_out'],
            'parts_measured': parts['parts'], 'part_points': parts['points'], 'part_floor_m': parts['floor_m'], 'part_reach_m': tol,
            'moved_parts': parts['moved'], 'moved_places': parts['places'][:40],
            'tolerance_m': tol, 'resolution_m': max(hm, hr), 'this_from_reference_max_m': here_max, 'this_from_reference_p95_m': here_p95,
            'reference_from_this_max_m': ref_max, 'reference_from_this_p95_m': ref_p95, 'reference_surface_lost_share': lost_share,
            'reference_seen_share': sum(out) / max(1, len(out)), 'reference_seen_lost_share': lost_seen, 'seen_lost_by_tolerance': ladder, 'lost_regions': rg[:5], 'lost_region_count': len(rg), 'new_open_length_m': new_open}


BACKDROP = re.compile(r'ground|floor|backdrop|background|sky|cyclorama|shadow.?catcher|plane', re.I)


def subject(m, spec=None):
    """The model without its ground or backdrop, for the comparison: {'G', 'tlab' (the part of each triangle), 'lo', 'hi',
    'diagonal_m', 'left_out'}. A part (a node of the file) is left out when the rest of the file is at most a THIRD of the
    diagonal without it AND it is either a flat sheet (thinner than 2 % of its length, at least a quarter as wide as
    long: a ground slab, a backdrop wall) or named like one (ground, floor, backdrop, sky, plane ...). Both conditions,
    so a mast that carries a small lamp stays (not a sheet), and so does a stadium's floor slab (the rest is not small
    beside it). `spec`: 'none' = leave nothing out; a comma list of names or globs = leave out exactly those. With
    nothing left out the geometry and its box are the model's own, so the numbers are those of a file without ground."""
    G, tlab, labels = m['_G'], m['_tlab'], m['_labels']; keep = np.ones(G.m, bool); out = []
    nl = len(labels); lmn = np.full((nl, 3), INF); lmx = np.full((nl, 3), -INF); np.minimum.at(lmn, tlab, G.mn); np.maximum.at(lmx, tlab, G.mx)
    size = np.sqrt(((lmx - lmn) ** 2).sum(1)); size[~np.isfinite(size)] = -1.0
    def drop(L, why): keep[tlab == L] = False; out.append({'name': labels[L], 'size_m': float(size[L]), 'why': why}); size[L] = -1.0
    if spec and spec != 'none':
        for L, name in enumerate(labels):
            if size[L] >= 0 and any(fnmatch.fnmatchcase(name, pat) for pat in spec.split(',')): drop(L, 'named with --backdrop')
    elif not spec:
        for _ in range(8):
            L = int(np.argmax(size)); rest = keep & (tlab != L)
            if size[L] <= 0 or not rest.any(): break
            full = float(np.linalg.norm(G.mx[keep].max(0) - G.mn[keep].min(0))); small = float(np.linalg.norm(G.mx[rest].max(0) - G.mn[rest].min(0)))
            e = np.sort(lmx[L] - lmn[L]); sheet = e[0] <= 0.02 * e[2] and e[1] >= 0.25 * e[2]; named = bool(BACKDROP.search(labels[L]))
            if small * 3 > full or not (sheet or named): break
            drop(L, 'a flat sheet' if sheet else 'named like a backdrop')
    if not out or not keep.any():
        P = m['_P']; return {'G': G, 'tlab': tlab, 'labels': labels, 'lo': tuple(P.min(0).tolist()), 'hi': tuple(P.max(0).tolist()), 'diagonal_m': m['diagonal_m'], 'left_out': []}
    Gs = Geo(m['_P'], m['_T'][keep]); lo, hi = tuple(Gs.mn.min(0).tolist()), tuple(Gs.mx.max(0).tolist())
    return {'G': Gs, 'tlab': tlab[keep], 'labels': labels, 'lo': lo, 'hi': hi, 'diagonal_m': dist(lo, hi) or 1.0, 'left_out': out}


def reach(G, ix, Q, r, far):
    """The exact distance from each point to the surface, looked for within r, then 3 r, ... up to `far` (the value of
    points with nothing that near: "at least far")."""
    raw = np.full(len(Q), np.nan); left = np.arange(len(Q))
    while len(left):
        d = index_dist_sliced(G, ix, Q[left], r); got = d < INF; raw[left[got]] = d[got]; left = left[~got]
        if r >= far: raw[left] = far; break
        r = min(r * 3, far)
    return raw


def index_dist_sliced(G, ix, Q, r, room=3_000_000):
    """index_dist, the points taken in slices so that the candidate pairs of one slice stay near `room` (the answer per
    point is the same; before, one call held every pair of 20,000 points at once: 5.7 GB on a car on a 200 m ground)."""
    if not len(Q): return np.full(0, INF)
    span = np.floor((Q + r - np.array(ix.lo)) / ix.c).astype(np.int64) - np.floor((Q - r - np.array(ix.lo)) / ix.c).astype(np.int64) + 1
    cost = span[:, 0] * span[:, 1] * span[:, 2] * (len(ix.c_t) / max(1, len(ix.c_code))) + len(ix.all_big) + 1
    cut = np.r_[0, np.flatnonzero(np.diff(np.floor(np.cumsum(cost) / room))) + 1, len(Q)]
    return np.concatenate([index_dist(G, ix, Q[a:b], r) for a, b in zip(cut[:-1].tolist(), cut[1:].tolist()) if b > a])


def _reach_job(job):
    k, a, b, r, far = job; x = W['side'][k]
    return k, a, reach(x['G'], x['ix'], W['pts'][k][a:b], r, far)


def part_points(x, area_budget=60000, corner_budget=40000, least=48):
    """Each part's own points: (points, part of each). By area, `area_budget` over the whole model but at least `least`
    per part however small it is (so a bolt is measured as surely as a wall: the point spacing follows the part), and
    the part's corners (every one of a small part, a share of `corner_budget` for a large one, at least `least`): a rod
    slid along its own axis moves no surface point off the surface, but its end corners move."""
    G, tlab = x['G'], x['tlab']; nl = int(tlab.max()) + 1; ar = tri_area(G)
    pa = np.zeros(nl); np.add.at(pa, tlab, ar); tot = float(pa.sum()) or 1.0
    w = ar * np.maximum(least / np.maximum(pa, 1e-300), area_budget / tot)[tlab]
    n = np.floor(w).astype(np.int64); t = np.arange(G.m, dtype=np.int64); n += ((t * 2654435761) % 1000003) / 1000003.0 < w - n
    A1, A2 = 0.7548776662466927, 0.5698402909980532                         # the spread of area_points (the R2 sequence)
    rep = np.repeat(t, n); q = np.arange(int(n.sum())) - np.repeat(np.cumsum(n) - n, n)
    u = np.mod(1 / 3 + q * A1, 1.0); v = np.mod(1 / 3 + q * A2, 1.0); f = u + v > 1.0
    u = np.where(f, 1.0 - u, u); v = np.where(f, 1.0 - v, v); k = 1.0 - u - v
    pts = np.stack([G.V[rep, 0, c] * k + G.V[rep, 1, c] * u + G.V[rep, 2, c] * v for c in range(3)], 1)
    nv = len(G.P); lv = np.unique(np.repeat(tlab.astype(np.int64), 3) * nv + G.T.ravel()); L, V = lv // nv, lv % nv
    st = np.searchsorted(L, np.arange(nl)); cnt = np.searchsorted(L, np.arange(nl), 'right') - st
    want = np.minimum(cnt, np.maximum(least, corner_budget * cnt / max(1, len(lv)))).astype(np.float64)
    j = np.arange(len(lv)) - st[L]; step = want[L] / np.maximum(cnt[L], 1); pick = np.floor((j + 1) * step) > np.floor(j * step)
    return np.concatenate([pts, G.P[V[pick]]]), np.concatenate([tlab[rep].astype(np.int64), L[pick]]), (L, V, st, cnt)


def parts_moved(sm, sr, tol, workers=None):
    """Part by part (a part = a node of the file): how far each part's own points lie from the OTHER file's surface, both
    ways, exactly, looked for up to `tol`. Parts farther than the floor (0.1 mm plus the weld) are listed, farthest first,
    each with the point where it is farthest. A part with the same name and the same corners in both files also gets
    the exact shift of its corners (a move of 1 mm reads 1.000 mm, along which direction), also when it slid along
    its own surface."""
    floor = 1e-4 + max(sr['diagonal_m'] * 1e-6, 1e-6); sides = (sm, sr); pts = []; lab = []; corners = []
    for x in sides: p, l, c = part_points(x); pts.append(p); lab.append(l); corners.append(c)
    r0 = max(tol / 32, floor * 4); D = [np.empty(len(pts[0])), np.empty(len(pts[1]))]
    jobs = [(k, a, min(a + 4000, len(pts[k])), min(r0, tol), tol) for k in (0, 1) for a in range(0, len(pts[k]), 4000)]
    W['side'] = (sr, sm); W['pts'] = pts; nw = workers_wanted(workers)   # points of this file against the reference, and back
    if nw <= 1 or len(jobs) < 8:
        for j in jobs: k, a, d = _reach_job(j); D[k][a:a + len(d)] = d
    else:
        import multiprocessing as mp
        pool = mp.get_context('fork').Pool(nw)
        try:
            for k, a, d in pool.imap_unordered(_reach_job, jobs, chunksize=1): D[k][a:a + len(d)] = d
        finally:
            pool.terminate(); pool.join()
    found = {}
    for k, (x, tag) in enumerate(zip(sides, ('this', 'reference'))):
        nl = len(x['labels']); mx = np.zeros(nl); np.maximum.at(mx, lab[k], D[k]); npt = np.bincount(lab[k], minlength=nl); off = np.bincount(lab[k][D[k] > floor], minlength=nl)
        o = np.lexsort((-D[k], lab[k])); first = o[np.searchsorted(lab[k][o], np.arange(nl))[npt > 0]]     # each part's farthest point
        lmn = np.full((nl, 3), INF); lmx = np.full((nl, 3), -INF); np.minimum.at(lmn, x['tlab'], x['G'].mn); np.maximum.at(lmx, x['tlab'], x['G'].mx)
        x['pbox'] = (lmn, lmx)
        for L, i in zip(np.flatnonzero(npt > 0).tolist(), first.tolist()):
            if mx[L] <= floor: continue
            e = found.setdefault(x['labels'][L], {'name': x['labels'][L], 'names': [x['labels'][L]], 'distance_m': 0.0})
            e[tag + '_distance_m'] = float(mx[L]); e[tag + '_points_off_share'] = float(off[L] / npt[L])
            if mx[L] > e['distance_m']: e.update(distance_m=float(mx[L]), centre=pts[k][i].tolist(), min=lmn[L].tolist(), max=lmx[L].tolist(), side=tag)
    # the same part in both files, corner for corner: its exact shift
    at_m = {n: L for L, n in enumerate(sm['labels'])}; at_r = {n: L for L, n in enumerate(sr['labels'])}
    (Lm, Vm, sm_, cm), (Lr, Vr, sr_, cr) = corners
    for name, a in at_m.items():
        b = at_r.get(name)
        if b is None or a >= len(cm) or b >= len(cr) or not cm[a] or cm[a] != cr[b]: continue
        dl = sm['G'].P[Vm[sm_[a]:sm_[a] + cm[a]]] - sr['G'].P[Vr[sr_[b]:sr_[b] + cr[b]]]; mean = dl.mean(0); sh = float(np.linalg.norm(mean))
        if sh <= floor / 4 or float(np.abs(dl - mean).max()) > max(floor / 4, sh * 0.02): continue     # not moved, or not as one piece
        e = found.setdefault(name, {'name': name, 'names': [name], 'distance_m': 0.0, 'side': 'this', 'centre': ((sm['pbox'][0][a] + sm['pbox'][1][a]) / 2).tolist(),
                                    'min': sm['pbox'][0][a].tolist(), 'max': sm['pbox'][1][a].tolist()})
        e['shift_m'] = sh; e['shift'] = mean.tolist()
    for name, e in found.items():
        e['only_in'] = 'this' if name not in at_r else 'reference' if name not in at_m else None
        e['at_least'] = bool(e['distance_m'] >= tol)
    places = sorted(found.values(), key=lambda e: (-max(e['distance_m'], e.get('shift_m', 0.0)), -dist(e['min'], e['max']), e['name']))   # farthest first; of equals, the larger part
    return {'places': places, 'moved': len(places), 'parts': [int(len(np.unique(l))) for l in lab], 'points': [len(p) for p in pts], 'floor_m': floor,
            'this_max_m': float(D[0].max()) if len(D[0]) else 0.0, 'reference_max_m': float(D[1].max()) if len(D[1]) else 0.0}


def index_dist(G, ix, Q, r, which=None):
    """Exact distance from each point to the nearest triangle of the model (all pieces) when within r, else infinity:
    the triangles filed in the cells the point's reach covers, and the very large ones. `which` (an int array, one per
    point) receives the nearest triangle."""
    out = np.full(len(Q), INF)
    if not len(Q): return out
    c, lo = ix.c, np.array(ix.lo); x0 = np.floor((Q - r - lo) / c).astype(np.int64); x1 = np.floor((Q + r - lo) / c).astype(np.int64)
    span = x1 - x0 + 1; ncell = span[:, 0] * span[:, 1] * span[:, 2]
    pi = np.repeat(np.arange(len(Q)), ncell); j = np.arange(int(ncell.sum())) - np.repeat(np.cumsum(ncell) - ncell, ncell)
    sy, sz = span[pi, 1], span[pi, 2]
    cx = x0[pi, 0] + j // (sy * sz) - ix.o[0]; cy = x0[pi, 1] + (j // sz) % sy - ix.o[1]; cz = x0[pi, 2] + j % sz - ix.o[2]
    okc = (cx >= 0) & (cy >= 0) & (cy < ix.ny) & (cz >= 0) & (cz < ix.nz)
    code = (cx * ix.ny + cy) * ix.nz + cz; k = np.searchsorted(ix.c_code, code); kk = np.minimum(k, max(len(ix.c_code) - 1, 0))
    hit = np.flatnonzero(okc & (k < len(ix.c_code)) & (ix.c_code[kk] == code)) if len(ix.c_code) else np.zeros(0, np.int64)
    s, e = ix.c_start[kk[hit]], ix.c_end[kk[hit]]; n = e - s
    if int(n.sum()) > 8_000_000 and len(Q) > 1:           # points in very full cells: in two halves (the same answers; 12 GB
        h = len(Q) // 2; w = (None, None) if which is None else (which[:h], which[h:])     # were held at once on a culled car)
        return np.concatenate([index_dist(G, ix, Q[:h], r, w[0]), index_dist(G, ix, Q[h:], r, w[1])])
    P_ = np.repeat(pi[hit], n); T_ = ix.c_t[np.repeat(s, n) + (np.arange(int(n.sum())) - np.repeat(np.cumsum(n) - n, n))]
    if len(ix.all_big):
        P_ = np.concatenate([P_, np.repeat(np.arange(len(Q)), len(ix.all_big))]); T_ = np.concatenate([T_, np.tile(ix.all_big, len(Q))])
    if not len(P_): return out
    ok = np.ones(len(P_), bool)                          # the boxes first (cheap), then each pair once: the same pairs as before
    for k in range(3): qk = Q[P_, k]; ok &= (qk >= G.mn[T_, k] - r) & (qk <= G.mx[T_, k] + r)
    P_, T_ = P_[ok], T_[ok]
    if not len(P_): return out
    pc = np.unique(P_ * G.m + T_); P_, T_ = pc // G.m, pc % G.m
    dd = pt_tri_v(G, Q[P_, 0], Q[P_, 1], Q[P_, 2], T_, True); np.minimum.at(out, P_, dd)
    if which is not None:                                # the triangle that is nearest (pairs are sorted by point, then triangle)
        o = np.lexsort((T_, dd, P_)); f = o[np.r_[True, P_[o][1:] != P_[o][:-1]]]; ok = dd[f] <= r; which[P_[f][ok]] = T_[f][ok]
    return np.where(out <= r, out, INF)


def index_nearest(G, ix, Q, r, room=3_000_000):
    """(distance, triangle) of the nearest triangle within r for each point (infinity and -1: none), in slices."""
    D = np.full(len(Q), INF); Wh = np.full(len(Q), -1, np.int64)
    if not len(Q): return D, Wh
    span = np.floor((Q + r - np.array(ix.lo)) / ix.c).astype(np.int64) - np.floor((Q - r - np.array(ix.lo)) / ix.c).astype(np.int64) + 1
    cost = span[:, 0] * span[:, 1] * span[:, 2] * (len(ix.c_t) / max(1, len(ix.c_code))) + len(ix.all_big) + 1
    cut = np.r_[0, np.flatnonzero(np.diff(np.floor(np.cumsum(cost) / room))) + 1, len(Q)]
    for a, b in zip(cut[:-1].tolist(), cut[1:].tolist()):
        if b > a: w = np.full(b - a, -1, np.int64); D[a:b] = index_dist(G, ix, Q[a:b], r, w); Wh[a:b] = w
    return D, Wh


def nearest_point_each(A, B, cap):
    """For each point of A: the distance to the nearest point of B, or `cap` if none is nearer (a grid of `cap`)."""
    out = np.full(len(A), cap)
    if not len(A) or not len(B): return out
    kb = np.floor(B / cap).astype(np.int64); ka = np.floor(A / cap).astype(np.int64)
    enc = lambda k: (k[:, 0] * 2097152 + k[:, 1]) * 2097152 + k[:, 2]
    eb = enc(kb); o = np.argsort(eb, kind='stable'); eb, Bs = eb[o], B[o]
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                e = enc(ka + np.array([dx, dy, dz])); s = np.searchsorted(eb, e); t = np.searchsorted(eb, e, 'right'); n = t - s
                pi = np.repeat(np.arange(len(A)), n); bj = np.repeat(s, n) + (np.arange(int(n.sum())) - np.repeat(np.cumsum(n) - n, n))
                if len(pi):
                    dd = np.sqrt(sq(A[pi, 0] - Bs[bj, 0]) + sq(A[pi, 1] - Bs[bj, 1]) + sq(A[pi, 2] - Bs[bj, 2])); np.minimum.at(out, pi, dd)
    return out


# ----------------------------------------------------------------------------------------- held by the original
def outside_dirs(below=False):
    """The directions a viewer stands in, as simplify.py (skill 3d-asset-making) takes them when it drops the faces no
    outside view reaches: 96 spread evenly over the sphere, those from more than 30 degrees underneath left out (72);
    `below` keeps all 96. So what the culling dropped as unseen is unseen here too. y is up."""
    g = (1 + 5 ** 0.5) / 2; out = []
    for i in range(96):
        z = 1 - 2 * (i + 0.5) / 96; r = math.sqrt(max(0.0, 1 - z * z)); a = 2 * math.pi * i / g
        if below or z >= -0.5: out.append((r * math.cos(a), z, -r * math.sin(a)))
    return out


def ray_hits(G, O, D, t):
    """Does ray k (from O[k] along D[k]) cross triangle t[k]? Either side counts; a hair of slack at the edges so that no
    ray slips between two triangles that share an edge."""
    e1x, e1y, e1z = G.abx[t], G.aby[t], G.abz[t]; e2x, e2y, e2z = G.acx[t], G.acy[t], G.acz[t]
    dx, dy, dz = D[:, 0], D[:, 1], D[:, 2]
    hx, hy, hz = dy * e2z - dz * e2y, dz * e2x - dx * e2z, dx * e2y - dy * e2x
    a = e1x * hx + e1y * hy + e1z * hz; ok = a != 0; f = 1.0 / np.where(ok, a, 1.0)
    sx, sy, sz = O[:, 0] - G.ax[t], O[:, 1] - G.ay[t], O[:, 2] - G.az[t]
    u = f * (sx * hx + sy * hy + sz * hz)
    qx, qy, qz = sy * e1z - sz * e1y, sz * e1x - sx * e1z, sx * e1y - sy * e1x
    v = f * (dx * qx + dy * qy + dz * qz); w = f * (e2x * qx + e2y * qy + e2z * qz)
    return ok & (u >= -1e-7) & (v >= -1e-7) & (u + v <= 1 + 1e-7) & (w > 0)


def rays_free(G, ix, O, D, room=1_500_000):
    """For each ray: True when it leaves the model without crossing any triangle. The rays walk the cells of the index
    one cell at a time, all together (each triangle is filed under every cell its box covers, so a ray meets every
    triangle it could cross); a ray that is stopped leaves the walk. The very large triangles are tried last, on the rays left."""
    n = len(O); free = np.ones(n, bool)
    if not n: return free
    def big():                                           # the very large triangles, for the rays that got through the cells
        for t in ix.all_big.tolist():
            k = np.flatnonzero(free)
            if len(k): free[k[ray_hits(G, O[k], D[k], np.full(len(k), t))]] = False
        return free
    if not len(ix.c_code): return big()
    lo = np.array(ix.lo); c = ix.c; og = np.array(ix.o); top = np.array([int(ix.c_code[-1] // (ix.ny * ix.nz)), ix.ny - 1, ix.nz - 1])
    cell = np.floor((O - lo) / c).astype(np.int64) - og; step = np.where(D > 0, 1, -1)
    with np.errstate(divide='ignore', invalid='ignore'):
        tmax = np.where(D != 0, ((cell + og + (D > 0)) * c + lo - O) / np.where(D != 0, D, 1.0), INF); tdel = np.where(D != 0, c / np.maximum(np.abs(D), 1e-300), INF)
    act = np.flatnonzero(free)
    while len(act):
        cc = cell[act]; st = step[act]
        act = act[~(((cc < 0) & (st < 0)) | ((cc > top) & (st > 0))).any(1)]       # past the last cell, going away: out
        if not len(act): break
        cc = cell[act]; code = (cc[:, 0] * ix.ny + cc[:, 1]) * ix.nz + cc[:, 2]
        j = np.searchsorted(ix.c_code, code); jj = np.minimum(j, len(ix.c_code) - 1)
        hit = np.flatnonzero(((cc >= 0) & (cc <= top)).all(1) & (ix.c_code[jj] == code))
        if len(hit):
            s, cnt = ix.c_start[jj[hit]], ix.c_end[jj[hit]] - ix.c_start[jj[hit]]; stopped = np.zeros(len(act), bool)
            cut = np.r_[0, np.flatnonzero(np.diff(np.floor(np.cumsum(cnt) / room))) + 1, len(hit)]
            for a_, b_ in zip(cut[:-1].tolist(), cut[1:].tolist()):
                if b_ <= a_: continue
                nn = cnt[a_:b_]; ri = np.repeat(hit[a_:b_], nn); ti = ix.c_t[np.repeat(s[a_:b_], nn) + (np.arange(int(nn.sum())) - np.repeat(np.cumsum(nn) - nn, nn))]
                keep = ~stopped[ri]; ri, ti = ri[keep], ti[keep]         # rays stopped in an earlier slice are not tried again
                r_ = act[ri]; stopped[ri[ray_hits(G, O[r_], D[r_], ti)]] = True
            free[act[stopped]] = False; act = act[~stopped]
        ax = np.argmin(tmax[act], 1); cell[act, ax] += step[act, ax]; tmax[act, ax] += tdel[act, ax]
    return big()


def split_tris(V, n):
    """Each triangle V[k] (3 corners) cut into n[k] * n[k] equal ones: (their corners (K,3,3), the triangle each is of)."""
    out = [np.zeros((0, 3, 3))]; src = [np.zeros(0, np.int64)]
    for q in np.unique(n).tolist():
        k = np.flatnonzero(n == q); i, j = np.meshgrid(np.arange(q), np.arange(q), indexing='ij'); up = i + j <= q - 1; dn = i + j <= q - 2
        I = np.concatenate([np.stack([i[up], i[up] + 1, i[up]], 1), np.stack([i[dn] + 1, i[dn] + 1, i[dn]], 1)]).astype(np.float64)
        J = np.concatenate([np.stack([j[up], j[up], j[up] + 1], 1), np.stack([j[dn], j[dn] + 1, j[dn] + 1], 1)]).astype(np.float64)
        A, B, C = V[k, 0][:, None, None, :], V[k, 1][:, None, None, :], V[k, 2][:, None, None, :]
        out.append(((A * (q - I - J)[None, :, :, None] + B * I[None, :, :, None] + C * J[None, :, :, None]) / q).reshape(-1, 3, 3)); src.append(np.repeat(k, q * q))
    return np.concatenate(out), np.concatenate(src)


def fan(fn, jobs, nw):
    """fn over the jobs on up to nw processes (fork: they share W), results in any order."""
    if nw <= 1 or len(jobs) < 2: return [fn(j) for j in jobs]
    import multiprocessing as mp
    pool = mp.get_context('fork').Pool(min(nw, len(jobs)))
    try: return list(pool.imap_unordered(fn, jobs, chunksize=1))
    finally: pool.terminate(); pool.join()


def _near_job(job):
    key, a, b, r, which = job; x = W['hb'][key]; Q = W['hb'][key + '_pts'][a:b]
    if which: return (a,) + index_nearest(x['_G'], x['_ix'], Q, r)
    return a, index_dist_sliced(x['_G'], x['_ix'], Q, r), None


def near_all(key, n, r, nw, which=False, per=20000):
    """Distances (and nearest triangles) of W['hb'][key + '_pts'] to the surface of the analysis W['hb'][key], within r."""
    D = np.full(n, INF); Wh = np.full(n, -1, np.int64)
    for a, d, w in fan(_near_job, [(key, a, min(a + per, n), r, which) for a in range(0, n, per)], nw):
        D[a:a + len(d)] = d
        if w is not None: Wh[a:a + len(w)] = w
    return D, Wh


def _coarse_job(k):
    """One view direction: which test points are plainly covered there (False) and which may be seen (True). A depth
    map of the original's surface points in cells of `g`; a point is plainly covered when its cell and the eight round
    it all hold surface clearly nearer to the viewer (by more than a cell, and more the more the point's own face slopes
    away from the view, so a face never covers itself). Bars and openings narrower than the three cells do not cover."""
    S = W['hb']; d = S['dirs'][k]; g = S['g']
    a = (1.0, 0.0, 0.0) if abs(d[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = (d[1] * a[2] - d[2] * a[1], d[2] * a[0] - d[0] * a[2], d[0] * a[1] - d[1] * a[0]); n = math.sqrt(u[0] ** 2 + u[1] ** 2 + u[2] ** 2); u = (u[0] / n, u[1] / n, u[2] / n)
    v = (d[1] * u[2] - d[2] * u[1], d[2] * u[0] - d[0] * u[2], d[0] * u[1] - d[1] * u[0])
    kc, zc = screen(S['cloud'], d, u, v, g); zc = -zc                           # depth: smaller is nearer the viewer
    o = np.argsort(kc, kind='stable'); ks = kc[o]; st = np.flatnonzero(np.r_[True, ks[1:] != ks[:-1]]); uk = ks[st]; zmin = np.minimum.reduceat(zc[o], st)
    kt, zt = screen(S['test'], d, u, v, g); zt = -zt
    cosn = np.abs(S['nrm'] @ np.array(d)); tan = np.sqrt(np.maximum(0.0, 1 - cosn * cosn)) / np.maximum(cosn, 1e-9)
    lim = zt - g * (1.0 + 3.0 * tan); covered = cosn >= 0.2
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            key = kt + dx * 4294967296 + dy; j = np.searchsorted(uk, key); jj = np.minimum(j, len(uk) - 1)
            covered &= (uk[jj] == key) & (zmin[jj] < lim)
    return k, np.packbits(~covered)


def _seen_job(job):
    """The rays of the points a..b, in rounds: each point first tries the open direction its face looks most squarely
    into (the likeliest way out, so a seen point is done after a ray or two), then the next; a point is out of the
    rounds as soon as one ray gets away."""
    a, b = job; S = W['hb']; x = S['o']; Q = S['test'][a:b]; N = S['nrm'][a:b]; seen = np.zeros(b - a, bool); rays = 0; e = S['lift']
    Dm = np.array(S['dirs']); dot = N @ Dm.T; score = np.where(S['maybe'][:, a:b].T, np.abs(dot), -1.0)
    order = np.argsort(-score, 1, kind='stable'); left = S['maybe'][:, a:b].sum(0)
    def cast(i, k):
        d = Dm[k]; sg = np.where(dot[i, k] >= 0, 1.0, -1.0)
        O = Q[i] + N[i] * (e * sg)[:, None] + d * e                             # just off the face, on the viewer's side (as simplify.py)
        return rays_free(x['_G'], S['rix'], O, d)
    for rnd in range(min(3, len(Dm))):
        i = np.flatnonzero(~seen & (left > rnd))
        if not len(i): break
        seen[i[cast(i, order[i, rnd])]] = True; rays += len(i)
    # the points still in doubt (nearly all of them unseen): every direction left, together (the walk costs per step, not per ray)
    i = np.flatnonzero(~seen & (left > 3)); n = left[i] - 3; pi = np.repeat(i, n); rk = 3 + np.arange(int(n.sum())) - np.repeat(np.cumsum(n) - n, n)
    for c in range(0, len(pi), 200000):
        p = pi[c:c + 200000]; free = cast(p, order[p, rk[c:c + 200000]]); seen[p[free]] = True; rays += len(p)
    return a, seen, rays


def seen_exact(o, Q, N, below=False, workers=None):
    """For each point Q (with its face's normal N) on the surface of the analysed model `o`: can any outside viewer see
    it? (seen, rays cast). A viewer in each direction of `outside_dirs`; glass is a wall (as in simplify.py). First the
    depth maps of `_coarse_job` strike the directions in which the point is plainly covered; in every other direction a
    ray is sent from the point to the viewer and tested against every triangle on its way (exact); one ray that gets
    out makes the point seen."""
    nw = workers_wanted(workers); G = o['_G']; dirs = outside_dirs(below); K = len(dirs)
    if not len(Q): return np.zeros(0, bool), 0
    cloud, h = area_points(G, o['diagonal_m'] / 800, cap=1_000_000)
    P = o['_P']; rix = Index(G, np.zeros(G.m, np.int64), tuple(P.min(0).tolist()), tuple(P.max(0).tolist()), 0.0, max(72, min(400, int(G.m ** (1 / 3) * 6))))
    # (the rays walk their own, finer cells, up to 400 a side: in the 72 of the pieces' index a ray met thousands of bolt
    # triangles per cell; measured on the car, 15,070 points: 113 s there, 22 s here, the same 6,412 seen)
    W['hb'].update(o=o, rix=rix, cloud=cloud, test=Q, nrm=N, dirs=dirs, g=2 * h,
                   lift=max(o['diagonal_m'] * 2e-6, min(1e-4, o['diagonal_m'] * 2e-5)))
    maybe = np.zeros((K, len(Q)), bool)
    for k, bits in fan(_coarse_job, list(range(K)), nw): maybe[k] = np.unpackbits(bits, count=len(Q)).astype(bool)
    W['hb']['maybe'] = maybe; seen = np.zeros(len(Q), bool); rays = 0
    for a, s, r in fan(_seen_job, [(a, min(a + 8000, len(Q))) for a in range(0, len(Q), 8000)], nw): seen[a:a + len(s)] = s; rays += r
    for k in ('cloud', 'test', 'nrm', 'maybe', 'rix'): W['hb'].pop(k, None)
    return seen, rays


def held_by(m, o, tol=None, below=False, workers=None):
    """Is each floating body of the version `m` held in `o`, the original it was made from? (--held-by)

    A lower version is made by dropping what no outside view reaches and simplifying the rest. A part whose seen shell
    met the rest only through unseen faces then counts as floating, although it sits where it sat and looks attached
    from every side. The question here is the viewer's: does a piece hang in the air, or show a gap, that the original
    does not have? For every floating body:
      MOVED      a point of it lies farther than `tol` from the original's surface: it is not where the original has
                 anything (a lens left hanging above its post, an added piece). FAULT.
      HELD       it joins the version's main body through GLUE: the original's own triangles, all of them except those
                 that are both GONE here (no surface of the version within the touch distance) and SEEN FROM OUTSIDE in
                 the original. A flange inside a box is glue: nobody could see how the lid is held, and it sits where it
                 sat. A collar that showed between lamp and post and was dropped is not: where it was there is now air
                 one can see. The bodies of (version + glue) are found by the same measurement as BODIES.
      INHERITED  not held, but it lies on a body that floats in the original too: the original's fault, said, no FAULT.
      NOT HELD   the rest: what joined it is gone and shows. FAULT.
    The original is never itself reported. `tol` (default: the touch distance) is at once how far a piece may lie from
    the original and how wide an opening counts as closed, so give the version's error target and no more."""
    t0 = time.time(); nw = workers_wanted(workers); att = m['attach_m']; tol = att if tol is None else tol
    mG, oG = m['_G'], o['_G']; nb = len(m['bodies']); diag = o['diagonal_m']
    touch = min(max(att, tol), max(att, 0.02 * diag))     # surfaces join within the tolerance, but never wider than 2 % of the diagonal
    #                                                       (a far version's 39 cm error target as a touch distance held 12 GB and says nothing)
    out = {'original': o['file'], 'original_triangles': o['triangles'], 'original_bodies': len(o['bodies']), 'tolerance_m': tol, 'touch_m': touch,
           'directions': len(outside_dirs(below)), 'floating_before': nb - 1, 'held': 0, 'inherited': 0, 'moved': 0, 'floating': 0, 'places': []}
    if nb == 1: out['seconds'] = time.time() - t0; return out
    vb = np.asarray(m['_body_of_piece'], np.int64)[m['_tp']]                     # the body of each triangle of the version
    # 1. every body's own points against the original: how far off, and on which body of the original
    pts, lab, _ = part_points({'G': mG, 'tlab': vb}); W['hb'] = {'o': o, 'o_pts': pts, 'm': m}
    D, Wh = near_all('o', len(pts), touch, nw, True); far = max(27 * touch, 0.1 * diag); r = touch
    left = np.flatnonzero(np.isinf(D) & (lab != 0))
    while len(left) and r < far:                          # the points that are off: how far (up to `far`: "at least")
        r = min(r * 3, far); d = index_dist_sliced(oG, o['_ix'], pts[left], r); got = d < INF; D[left[got]] = d[got]; left = left[~got]
    Df = np.where(np.isinf(D), far, D); off = np.zeros(nb); np.maximum.at(off, lab, Df)
    oo = np.lexsort((-Df, lab)); worst = pts[oo[np.searchsorted(lab[oo], np.arange(nb))]]            # each body's farthest point
    ob = np.asarray(o['_body_of_piece'], np.int64)[o['_tp']]; on = np.full(nb, -1, np.int64); ok = Wh >= 0
    pair, cnt = np.unique(lab[ok] * len(o['bodies']) + ob[Wh[ok]], return_counts=True)
    for p, c in sorted(zip(pair.tolist(), cnt.tolist()), key=lambda pc: pc[1]): on[p // len(o['bodies'])] = p % len(o['bodies'])   # the most frequent last
    tick('held by: the bodies against the original')
    # 2. glue: the original's triangles, without those gone here AND seen from outside
    ap, h, owner = area_points(oG, max(touch, diag / 800), owner=True); M = oG.m
    op = np.concatenate([oG.V.mean(1), ap]); own = np.concatenate([np.arange(M, dtype=np.int64), owner])
    W['hb']['m_pts'] = op; gone = np.isinf(near_all('m', len(op), touch, nw)[0]); npt = np.bincount(own, minlength=M)
    nx, ny, nz = oG.aby * oG.acz - oG.abz * oG.acy, oG.abz * oG.acx - oG.abx * oG.acz, oG.abx * oG.acy - oG.aby * oG.acx
    L = np.sqrt(nx * nx + ny * ny + nz * nz); L = np.where(L == 0, 1.0, L); nrm = np.stack([nx / L, ny / L, nz / L], 1)
    # A large triangle is seldom gone and seen as a whole (a wall behind a cupboard, a flange half inside its seat): each
    # one with a point gone is cut into small ones (sides of about two touch distances; coarser when they would be more
    # than 300,000), and each small one is judged by its own middle.
    e = oG.V - np.roll(oG.V, 1, 1); lg = np.sqrt((e * e).sum(2)).max(1); has = np.bincount(own[gone], minlength=M) > 0; side = max(2 * touch, h)
    while True:
        cand = np.flatnonzero(has & (lg > side)); cuts = np.minimum(64, np.ceil(lg[cand] / side)).astype(np.int64)
        if int((cuts * cuts).sum()) <= 300000: break
        side *= 1.15
    big = np.zeros(M, bool); big[cand] = True; SV, src = split_tris(oG.V[cand], cuts); sc = SV.mean(1)
    W['hb']['m_pts'] = sc; sgone = np.flatnonzero(np.isinf(near_all('m', len(sc), touch, nw)[0])); gi = np.flatnonzero(gone & ~big[own])
    tick('held by: what of the original is gone here')
    seen, rays = seen_exact(o, np.concatenate([op[gi], sc[sgone]]), np.concatenate([nrm[own[gi]], nrm[cand[src[sgone]]]]), below, nw); tick('held by: seen from outside')
    airp = gi[seen[:len(gi)]]; air = (np.bincount(own[airp], minlength=M) * 2 >= npt) & ~big         # a small triangle: half its points or more
    sair = np.zeros(len(sc), bool); sair[sgone[seen[len(gi):]]] = True; keep = ~air & ~big
    # 3. the bodies of version + glue
    nvp = len(m['_P']); nvt = len(m['_T']); nop = len(o['_P']); cutp = SV[~sair].reshape(-1, 3)
    c = analyse_geo(np.concatenate([m['_P'], o['_P'], cutp]), np.concatenate([m['_T'], o['_T'][keep] + nvp, np.arange(len(cutp), dtype=np.int64).reshape(-1, 3) + nvp + nop]),
                    ['version', 'original'], np.r_[np.zeros(nvt, np.int32), np.ones(int(keep.sum()) + len(cutp) // 3, np.int32)], 0, 0, None, touch, nw, True)
    cb = np.asarray(c['_body_of_piece'], np.int64)[c['_tp']][:nvt]; main = int(np.bincount(cb[vb == 0]).argmax())
    held = np.zeros(nb, bool); np.logical_or.at(held, vb, cb == main); tick('held by: bodies of version + glue')
    A = np.concatenate([op[airp], sc[sair]]); pad = max(5 * touch, 0.02)
    for n, b in enumerate(m['bodies']):
        if n == 0: continue
        st = 'moved' if off[n] > tol else 'held' if held[n] else 'inherited' if on[n] >= 0 and on[n] != on[0] else 'floating'
        b['held'] = st; b['off_original_m'] = float(off[n]); out[st] += 1
        if st == 'held': continue
        e = {'body': n, 'status': st, 'triangles': b['triangles'], 'size_m': b['size_m'], 'min': b['min'], 'max': b['max'],
             'centre': [(b['min'][k] + b['max'][k]) / 2 for k in range(3)], 'names': b['names'], 'off_original_m': float(off[n]),
             'at_least': bool(off[n] >= far), 'farthest_point': worst[n].tolist(), 'original_body': int(on[n])}
        if st == 'floating' and len(A):
            near = A[np.all((A >= np.array(b['min']) - pad) & (A <= np.array(b['max']) + pad), 1)]
            e['gone_seen_points'] = len(near)
            if len(near): e['gone_seen_centre'] = near.mean(0).tolist()
        out['places'].append(e)
    out.update(glue_triangles=int(keep.sum()) + int((~sair).sum()), air_triangles=int(air.sum()) + int(sair.sum()), triangles_cut=int(len(cand)), cut_side_m=float(side),
               points=len(op) + len(sc), points_gone=int(len(gi) + len(sgone)), points_gone_seen=int(len(A)),
               rays=int(rays), point_spacing_m=float(h), pairs_unmeasured=bool(c.get('pairs_unmeasured')), seconds=time.time() - t0)
    W.pop('hb', None)
    return out


# ---------------------------------------------------------------------------------------------------------- report
def seen_to(arg, family=None, near=None):
    """How far a version is drawn and the depth buffer's step there (24-bit, standard depth): z^2 / (near * 2^24).
    `arg` is near|mid|far (read from the 3d-asset-making skill's switch.json) or metres."""
    sw = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '3d-asset-making', 'scripts', 'switch.json')))
    fam = family or sw['default_family']; fr = sw['families'][fam]
    if arg in ('near', 'mid', 'far'):
        z = (fr['near_mid'][1] if arg == 'near' else fr['mid_far'][1]) + fr['hysteresis']; why = f'{fam} {arg} version drawn to'
    else: z = float(arg); why = 'seen to'
    n = float(near) if near else float(sw['camera'].get('near_m', 0.5))
    return {'distance_m': z, 'near_m': n, 'step_m': z * z / (n * 2 ** 24), 'why': why}


def main():
    a = sys.argv[1:]
    if not a or a[0] in ('-h', '--help'): print(__doc__); return 0
    if np is None: print('cannot run: mesh_integrity.py needs numpy (apt install python3-numpy, or pip install numpy)'); return 2
    opt = lambda k: a[a.index(k) + 1] if k in a else None
    nw = int(opt('--workers')) if opt('--workers') else None
    try:
        m = analyse(a[0], float(opt('--attach')) if opt('--attach') else None, nw); r = analyse(opt('--against'), m['attach_m'], nw) if opt('--against') else None
        orig = None
        if opt('--held-by'):                             # the original: the reference itself when it is the same file
            orig = r if r and os.path.realpath(opt('--against')) == os.path.realpath(opt('--held-by')) else analyse(opt('--held-by'), m['attach_m'], nw, True)
    except Exception as ex:
        print(f'cannot read: {ex}'); return 2
    bad = []; look = []; f = lambda v: f'{v:.3f}'
    print(f'{os.path.basename(a[0])}: {m["triangles"]} triangles, diagonal {f(m["diagonal_m"])} m, {m["pieces"]} connected pieces, parts count as touching within {m["attach_m"] * 1000:.1f} mm')
    b0 = m['bodies'][0]; print(f'  BODIES: {len(m["bodies"])}' + ('  (one sound thing)' if len(m['bodies']) == 1 else f'  <== {len(m["bodies"]) - 1} FLOATING'))
    for n, b in enumerate(m['bodies'][1:], 1):
        c = [(b['min'][k] + b['max'][k]) / 2 for k in range(3)]
        print(f'    floating {n}: {b["triangles"]} triangles, {f(b["size_m"])} m across, centre ({f(c[0])}, {f(c[1])}, {f(c[2])}), gap to the nearest other part {f(b.get("gap_m", 0))} m, from {", ".join(b["names"])}')
    hb = None
    if orig:
        tick('the original'); hb = held_by(m, orig, float(opt('--held-tol')) if opt('--held-tol') else None, '--from-below' in a, nw)
        print(f'  HELD BY {os.path.basename(hb["original"])} ({hb["original_triangles"]} triangles, {hb["original_bodies"]} bodies; a piece may lie up to {hb["tolerance_m"] * 1000:.1f} mm from it, surfaces join within {hb["touch_m"] * 1000:.1f} mm; '
              f'seen from outside: {hb["directions"]} view directions): of the {hb["floating_before"]} floating, {hb["held"]} HELD in the original (they sit on it, and what joins them to the rest there is still here or was never seen), '
              f'{hb["inherited"]} INHERITED (they float in the original too), {hb["moved"]} MOVED off the original or not in it, {hb["floating"]} NOT HELD (what joined them is gone and shows)')
        k = defaultdict(int); word = {'moved': 'moved', 'floating': 'not held', 'inherited': 'inherited'}
        for e in hb['places']:
            k[e['status']] += 1; c = e['centre']; q = e['farthest_point']
            if k[e['status']] > 12: continue
            print(f'    {word[e["status"]]} {k[e["status"]]} (floating {e["body"]}): {e["triangles"]} triangles, {f(e["size_m"])} m across, centre ({f(c[0])}, {f(c[1])}, {f(c[2])}), from {", ".join(e["names"])}'
                  + (f': {"at least " if e["at_least"] else "up to "}{e["off_original_m"] * 1000:.1f} mm off the original\'s surface at ({f(q[0])}, {f(q[1])}, {f(q[2])})' if e['status'] == 'moved' else '')
                  + (f': floats in the original too (its body {e["original_body"] + 1} there)' if e['status'] == 'inherited' else '')
                  + (f': on the original within {e["off_original_m"] * 1000:.1f} mm, but ' + (f'the original\'s surface round it that is gone here was seen from outside ({e["gone_seen_points"]} points of it, centred ({f(e["gone_seen_centre"][0])}, {f(e["gone_seen_centre"][1])}, {f(e["gone_seen_centre"][2])}))' if e.get('gone_seen_points') else 'nothing of the original joins it to the main body') if e['status'] == 'floating' else ''))
        for st in ('moved', 'floating', 'inherited'):
            if k[st] > 12: print(f'    ... and {k[st] - 12} more {word[st]} (all in the JSON: held_by.places)')
        if hb.get('pairs_unmeasured'): print('    WARNING: too many pairs of pieces to measure them all; some pieces may be counted as not held that are')
        if hb['moved'] + hb['floating']: bad.append(f'{hb["moved"] + hb["floating"]} floating part(s) the original does not hold ({hb["moved"]} moved off it or not in it, {hb["floating"]} whose joining surface is gone and shows)')
    elif len(m['bodies']) > 1: bad.append(f'{len(m["bodies"]) - 1} floating part(s)')
    print(f'  OPEN EDGES: {m["open_edges"]} edges, {f(m["open_length_m"])} m, {m["open_share"] * 100:.1f} % of all edge length')
    ok = open_kinds(m) if m['open_edges'] else None; tick('open edge kinds')
    if ok: print(f'    of them: on the ground {f(ok["ground_m"])} m (the rim of what stands on something), resting on another surface {f(ok["resting_m"])} m (a sheet ending on a wall, a T-joint: closed to the eye), free {f(ok["free_m"])} m (whether one can look into them: next line)')
    nm = non_manifold(m); tick('non-manifold')
    fold = f'{nm["folded_edges"]} where a sheet folds back on its neighbour at under 75 degrees, counted only'
    turn = f'{nm["turned_edges"]} with a face turned over, in {nm["turned_parts"]} part' + ('s' if nm['turned_parts'] != 1 else '')
    print(f'  NON-MANIFOLD: {nm["edges_over_two_faces"]} edges where more than two faces meet, {nm["flipped_edges"]} edges where two faces of one part wind opposite ways'
          + (' (' + ', '.join(([turn] if nm['turned_edges'] else []) + ([fold] if nm['folded_edges'] else [])) + ')' if nm['flipped_edges'] else '')
          + f', {nm["zero_area_faces"]} zero-area faces, {nm["duplicate_faces"]} duplicate faces' + (f' ({nm["duplicate_same_facing"]} facing the same way)' if nm['duplicate_faces'] else ''))
    for n, p in enumerate(nm['turned_places'][:5], 1):
        print(f'      turned over, place {n}: {p["edges"]} edges, from ({f(p["min"][0])}, {f(p["min"][1])}, {f(p["min"][2])}) to ({f(p["max"][0])}, {f(p["max"][1])}, {f(p["max"][2])}), in {p["name"]}')
    for n, p in enumerate(nm['duplicate_places'][:3], 1):
        print(f'      duplicate, place {n}: {p["area_m2"] * 1e4:.2f} cm2 at ({f(p["centre"][0])}, {f(p["centre"][1])}, {f(p["centre"][2])}), in {p["name"]}')
    if nm['turned_edges']: look.append(f'{nm["turned_edges"]} edges in {nm["turned_parts"]} part(s) where a face is turned over against its neighbours: it shows its back (a hole with a one-sided material, dark with a two-sided one); recalculate the normals outside, unless two separate sheets meet there by design')
    bodies_nm = nm['bodies']; nclosed = sum(1 for b in bodies_nm if b['closed'])
    print(f'  WATERTIGHT: {nclosed} of {len(bodies_nm)} bodies closed; {nm["pieces_closed"]} of {m["pieces"]} pieces are closed (every edge has two faces winding opposite ways), {nm["pieces_solid"]} with an inside'
          + (f', {nm["inside_out_parts"]} of them INSIDE OUT (negative volume)' if nm['inside_out_parts'] else ''))
    for n, b in enumerate(bodies_nm[:8]):
        name = 'body 1 (the main one)' if n == 0 else f'body {n + 1} (floating {n})'
        print(f'      {name}: ' + ('closed' if b['closed'] else f'open ({b["closed_pieces"]} of {b["pieces"]} pieces closed)') + f', volume of its closed pieces {b["volume_m3"]:.4g} m3'
              + (f', {b["inside_out"]} inside out' if b['inside_out'] else ''))
    for n, p in enumerate(nm['inside_out_places'][:5], 1):
        print(f'      inside out, place {n}: {p["volume_m3"]:.4g} m3, {f(p["size_m"])} m across, centre ({f(p["centre"][0])}, {f(p["centre"][1])}, {f(p["centre"][2])}), from {", ".join(p["names"])}')
    if nm['inside_out_parts']: bad.append(f'{nm["inside_out_parts"]} closed part(s) inside out (faces pointing in: the engine shows their inside); flip their normals')
    li = looked_into(m, '--from-below' in a); wd = li['worst_direction']; tick('looked into')
    print(f'  LOOKED INTO: {li["back_share"] * 100:.1f} % of what a viewer sees from outside (the sides and above) is the BACK of a face' + (f'; from the worst side {li["worst_direction_share"] * 100:.0f} % (looking along {wd[0]:+.1f}, {wd[1]:+.1f}, {wd[2]:+.1f})' if wd else '') + ('. LOOK at the places below: a back is the inside of a shell seen through a missing wall or an open top, a skeleton without its skin, a single sheet from behind, or a face turned inside out (reversed winding; ' + ('this model has NO open edges, so that is what these are: a one-sided material does not draw them' if not m['open_edges'] else 'likely where the model has no open edge nearby') + '). A pointer, not a verdict (by eye on 27 models: under 5 % none was looked into, 5 to 20 % two of eight, above 20 % three of four; thin things and cards give a few percent by nature)' if li['back_share'] > 0.05 else ''))
    for n, pl in enumerate(li['places'] if li['back_share'] > 0.05 else [], 1): print(f'      backs seen, place {n} of {li["place_count"]}: {pl["share"] * 100:.0f} % of them, from ({f(pl["min"][0])}, {f(pl["min"][1])}, {f(pl["min"][2])}) to ({f(pl["max"][0])}, {f(pl["max"][1])}, {f(pl["max"][2])})')
    gp = m['gaps']
    print(f'  GAPS (parts within {m["attach_m"] * 1000:.1f} mm of each other that do not meet within {m["meet_m"] * 1000:.1f} mm: a slit light shows through): {m["gap_count"]} pairs' + (' (not all pairs measured: time/pair budget)' if m.get('gap_pairs_unmeasured') else ''))
    for n, g in enumerate(gp[:8], 1): print(f'      gap {n}: {g["gap_m"] * 1000:.1f} mm near ({f(g["centre"][0])}, {f(g["centre"][1])}, {f(g["centre"][2])}), between {" / ".join(g["names"])}')
    if gp: look.append(f'{m["gap_count"]} pairs of parts stop short of each other by {min(g["gap_m"] for g in gp) * 1000:.1f}-{max(g["gap_m"] for g in gp) * 1000:.1f} mm: close each (let one enter the other a few mm) unless the gap is designed (a door seam), and say which in the hand-back')
    fl = flicker(m, float(opt('--zgap')) if opt('--zgap') else 0.002); res_fl = fl; tick('flicker')
    print(f'  FLICKER (z-fighting: faces sharing a plane within {fl["gap_m"] * 1000:.1f} mm and overlapping): {fl["same_facing_pairs"]} pairs facing the same way, {fl["same_facing_m2"] * 1e4:.1f} cm2'
          + (f' (largest {fl["largest_same_m2"] * 1e4:.1f} cm2)' if fl['same_facing_pairs'] else '') + f'; back to back {fl["back_to_back_pairs"]} pairs, {fl["back_to_back_m2"] * 1e4:.1f} cm2 (blink only where the material is double-sided)'
          + (f' in {fl["back_to_back_place_count"]} places (--back-to-back-places N prints the largest; all are in the JSON)' if fl['back_to_back_pairs'] else '')
          + (f'; of them {fl["flipped_duplicate_pairs"]} pairs, {fl["flipped_duplicate_m2"] * 1e4:.1f} cm2 are two faces of ONE part in the same place (within {fl["same_place_m"] * 1000:.1f} mm): a face and its FLIPPED COPY (delete the copy), or two solids of one mesh resting exactly on each other' if fl['flipped_duplicate_pairs'] else ''))
    for n, pl in enumerate(fl['places'], 1): print(f'      blinks, place {n}: {pl["overlap_m2"] * 1e4:.2f} cm2 at ({f(pl["centre"][0])}, {f(pl["centre"][1])}, {f(pl["centre"][2])}), {" / ".join(pl["names"])}')
    for n, pl in enumerate(fl['flipped_duplicate_places'][:3], 1): print(f'      flipped copy, place {n}: {pl["flipped_duplicate_m2"] * 1e4:.2f} cm2 in {pl["flipped_duplicate_pairs"]} pairs at ({f(pl["centre"][0])}, {f(pl["centre"][1])}, {f(pl["centre"][2])}), in {" / ".join(pl["names"])}')
    nb2b = int(opt('--back-to-back-places') or 0)
    for n, pl in enumerate(fl['back_to_back_places'][:nb2b], 1):
        print(f'      back to back, place {n} of {fl["back_to_back_place_count"]}: {pl["overlap_m2"] * 1e4:.2f} cm2 in {pl["pairs"]} pairs, {pl["apart_m"] * 1000:.2f} mm apart, at ({f(pl["centre"][0])}, {f(pl["centre"][1])}, {f(pl["centre"][2])}), {" / ".join(pl["names"])}' + (' (one part)' if pl['one_part'] else ''))
    if fl['largest_same_m2'] > 1e-4: bad.append(f'{fl["same_facing_pairs"]} overlapping coplanar face pairs (z-fighting: they blink in the game); lift one surface clear by more than the depth precision at the game camera, or delete/merge the hidden one')
    elif fl['same_facing_pairs']: look.append(f'{fl["same_facing_pairs"]} small coplanar overlaps (under 1 cm2 each) that may blink up close')
    if opt('--seen-to'):                                  # the depth step where this version is drawn farthest away
        st = seen_to(opt('--seen-to'), opt('--family'), opt('--near'))
        fd = flicker(m, max(fl['gap_m'], 2 * st['step_m'])); fd.update(st); res_fd = fd; tick('flicker at distance')
        print(f'  AT DISTANCE ({st["why"]}: {st["distance_m"]:.0f} m, near plane {st["near_m"]} m, depth step {st["step_m"] * 1000:.1f} mm; faces within {fd["gap_m"] * 1000:.1f} mm): {fd["same_facing_pairs"]} pairs facing the same way, {fd["same_facing_m2"] * 1e4:.1f} cm2'
              + (f' (largest {fd["largest_same_m2"] * 1e4:.1f} cm2)' if fd['same_facing_pairs'] else ''))
        for n, pl in enumerate(fd['places'][:5], 1): print(f'      blinks at distance, place {n}: {pl["overlap_m2"] * 1e4:.2f} cm2 at ({f(pl["centre"][0])}, {f(pl["centre"][1])}, {f(pl["centre"][2])}), {" / ".join(pl["names"])}')
        if fd['largest_same_m2'] > 1e-4: look.append(f'{fd["same_facing_pairs"]} face pairs lie within the depth step at {st["distance_m"]:.0f} m (they blink there in the game): delete the hidden face or join the parts')
    if m.get('pairs_unmeasured'): print('  WARNING: too many pairs of pieces to measure them all; some pieces may be counted as floating that are not')
    if m.get('skinned'): print('  NOTE: this model is skinned (it has bones): everything here is measured in its REST shape, not as the game poses it')
    if m['instanced_nodes']: print(f'  NOTE: {m["instanced_nodes"]} GPU-instanced copies are counted in place (each copy is checked like any other part)')
    if m['mirrored_nodes']: print(f'  NOTE: {m["mirrored_nodes"]} mirrored copies (a transform with a negative determinant): their faces are turned the way the engine draws them')
    res = {k: v for k, v in m.items() if not k.startswith('_')}
    if ok: res['open_kinds'] = ok
    res['non_manifold'] = nm; res['looked_into'] = li; res['flicker'] = res_fl
    if opt('--seen-to'): res['flicker_at_distance'] = res_fd
    if hb: res['held_by'] = hb
    if r:
        g = against(m, r, '--from-below' in a, opt('--backdrop'), nw); res['against'] = g; d = g['diagonal_m']; tick('against')
        print(f'  AGAINST {os.path.basename(g["reference"])} ({r["triangles"]} triangles, {len(r["bodies"])} bodies): this surface lies up to {f(g["this_from_reference_max_m"])} m from the reference ({g["this_from_reference_max_m"] / d * 100:.1f} % of the diagonal; 95 % within {f(g["this_from_reference_p95_m"])} m)')
        print(f'    the reference lies up to {f(g["reference_from_this_max_m"])} m from this one (95 % within {f(g["reference_from_this_p95_m"])} m); {g["reference_surface_lost_share"] * 100:.1f} % of the reference\'s surface has nothing within {f(g["tolerance_m"])} m here (LOST)')
        print(f'    new open edge length not in the reference: {f(g["new_open_length_m"])} m')
        for tag, lo_ in (('this file', g['left_out']), ('the reference', g['reference_left_out'])):
            if lo_: print(f'    left out of the comparison in {tag} as ground or backdrop: ' + ', '.join(f'{x["name"]} ({x["size_m"]:.1f} m across, {x["why"]})' for x in lo_) + f'; what is compared is {f(d)} m across, and every share, tolerance and spacing here is of that (--backdrop none to compare everything, --backdrop NAMES to choose)')
        nmv = int(opt('--moved-places') or 8)
        print(f'    PART BY PART ({g["parts_measured"][0]} parts here, {g["parts_measured"][1]} in the reference, each measured with its own points, {g["part_points"][0]} and {g["part_points"][1]} in all; exact distances, looked for up to {f(g["part_reach_m"])} m): {g["moved_parts"]} parts lie more than {g["part_floor_m"] * 1000:.2f} mm from the other file\'s surface or have moved' + (f' (the {nmv} farthest below; --moved-places N for more, 40 in the JSON)' if g['moved_parts'] > nmv else ''))
        for n, e in enumerate(g['moved_places'][:nmv], 1):
            c = e['centre']; sh = e.get('shift')
            print(f'      part {n}: {e["name"]}, ' + ('at least ' if e['at_least'] else '') + f'{e["distance_m"] * 1000:.2f} mm off at ({f(c[0])}, {f(c[1])}, {f(c[2])})'
                  + (f', moved as one piece by {e["shift_m"] * 1000:.3f} mm along ({sh[0] / e["shift_m"]:+.2f}, {sh[1] / e["shift_m"]:+.2f}, {sh[2] / e["shift_m"]:+.2f})' if sh else '')
                  + (' (the reference\'s part: nothing of this file at its place)' if e.get('side') == 'reference' and not sh and not e['only_in'] else '')
                  + (f' (only in {"this file" if e["only_in"] == "this" else "the reference"})' if e['only_in'] else ''))
        print(f'    (distances are exact, from points spread by area about every {f(g["resolution_m"])} m; a lost part smaller than that can be missed)')
        if len(m['bodies']) > len(r['bodies']) and not hb: bad.append(f'{len(m["bodies"]) - len(r["bodies"])} more separate bodies than the reference')
        rest = bool(m.get('skinned')) != bool(r.get('skinned'))               # one posed by bones and the other not: their rest shapes are not the same thing
        if rest: print('    NOTE: one of the two is skinned and the other is not: the two rest shapes need not coincide, so LOST and MOVED below prove nothing; compare them posed, in pictures')
        if not rest and g['this_from_reference_max_m'] > max(0.03 * d, g['tolerance_m'] * 3): look.append('a part here stands where the reference has nothing (moved or added)')
        print(f'    of what can be seen from outside in the reference ({g["reference_seen_share"] * 100:.0f} % of its surface): {g["reference_seen_lost_share"] * 100:.1f} % is LOST here; the rest of the loss is hidden inside (floors behind a wall), which a lower version may leave out')
        for n, rg in enumerate(g['lost_regions'], 1):
            print(f'      lost region {n} of {g["lost_region_count"]}: {rg["share_of_seen"] * 100:.1f} % of the seen surface, from ({f(rg["min"][0])}, {f(rg["min"][1])}, {f(rg["min"][2])}) to ({f(rg["max"][0])}, {f(rg["max"][1])}, {f(rg["max"][2])})')
        if not rest and g['reference_seen_lost_share'] > 0.15: look.append(f'{g["reference_seen_lost_share"] * 100:.0f} % of what the reference shows from outside has nothing near it here')
    if look: print('  LOOK: ' + '; '.join(look) + '. This is a pointer, not a verdict: checked by eye on thirty pairs, such a line was a real fault about half the time (a dropped part, a filled opening, a crumpled surface) and otherwise a coarser but acceptable shape (a twelve-sided drum made seven-sided, fewer leaf clumps, six of seven wires dropped). Open both files large at the regions listed and decide; say which in the hand-back. When this line is absent, the same thirty say the version lost nothing that shows.')
    print('  RESULT: ' + ('FAULT: ' + '; '.join(bad) if bad else 'one body, but LOOK at what the comparison points to (above)' if look else 'sound by this check' + (f', with {hb["inherited"]} floating part(s) INHERITED from the original (fix them there)' if hb and hb['inherited'] else '') + '; now look at it alone, large, from all sides'))
    if opt('--json'): json.dump(res, open(opt('--json'), 'w'), indent=1)
    return 1 if bad or look else 0


if __name__ == '__main__': sys.exit(main())
