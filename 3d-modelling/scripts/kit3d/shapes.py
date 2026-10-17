"""kit3d shapes: 2D outlines, solids with UVs made at creation, modifiers. Units: metres; angles in *_deg arguments.

Every solid is built in its own frame (origin at its centre unless said otherwise) and returned as an object of the
current part (kit3d.begin). Put it in place with kit3d.attach / span / lay (place.py), not with typed coordinates;
`loc=` / `rot_deg=` are for building inside a component's own frame, and a part placed that way still needs a
relation (kit3d.into) or check() lists it as unplaced. segs=None means kit3d.lod_segments(<film count>), so the same
program makes the near/mid/far versions with fewer segments.
"""
import math
import bpy, bmesh
from mathutils import Vector, Matrix, Euler

from . import const, core, uv
from .core import lod_segments, new_object, mesh_from_bm

AXES = {'X': Vector((1, 0, 0)), 'Y': Vector((0, 1, 0)), 'Z': Vector((0, 0, 1))}


# =========================================================================================== 2D outlines (u, v)
def poly_area(p):
    """Signed area of a closed 2D polygon (positive = counter-clockwise)."""
    return 0.5 * sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))


def rr_outline(w, h, r, n=None):
    """Rounded rectangle w x h (m) centred on 0, corner radius r, counter-clockwise; n segments per corner."""
    n = n or max(2, lod_segments(24) // 4)
    r = max(0.0, min(r, w / 2 - 1e-6, h / 2 - 1e-6)); pts = []
    for cx, cy, a0 in ((w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180), (w / 2 - r, -h / 2 + r, 270)):
        for k in range(n + 1):
            a = math.radians(a0 + 90 * k / n); pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def circle(r, n=None, c=(0.0, 0.0)):
    n = n or lod_segments(32)
    return [(c[0] + r * math.cos(2 * math.pi * k / n), c[1] + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def fillet(poly, r, segs=None, closed=True):
    """Round each corner of a 2D polygon by radius r (a number or one per corner)."""
    segs = segs or max(2, lod_segments(12) // 2)
    n = len(poly); out = []; rs = r if isinstance(r, (list, tuple)) else [r] * n
    for i in range(n):
        if not closed and (i == 0 or i == n - 1): out.append(tuple(poly[i])); continue
        p0, p1, p2 = Vector(poly[i - 1]), Vector(poly[i]), Vector(poly[(i + 1) % n]); ri = rs[i]
        if ri <= 0: out.append(tuple(p1)); continue
        a = (p0 - p1).normalized(); b = (p2 - p1).normalized(); ang = a.angle(b)
        if ang < 1e-3 or abs(ang - math.pi) < 1e-3: out.append(tuple(p1)); continue
        t = min(ri / math.tan(ang / 2), (p0 - p1).length * 0.49, (p2 - p1).length * 0.49); ri = t * math.tan(ang / 2)
        s = p1 + a * t; e = p1 + b * t; c = p1 + (a + b).normalized() * (ri / math.sin(ang / 2))
        a0 = math.atan2(s[1] - c[1], s[0] - c[0]); da = math.atan2(e[1] - c[1], e[0] - c[0]) - a0
        while da > math.pi: da -= 2 * math.pi
        while da < -math.pi: da += 2 * math.pi
        for k in range(segs + 1):
            aa = a0 + da * k / segs; out.append((c[0] + ri * math.cos(aa), c[1] + ri * math.sin(aa)))
    return out


def offset(poly, d):
    """Miter offset of a closed 2D polygon, d > 0 outward (either winding)."""
    n = len(poly); out = []; ccw = poly_area(poly) > 0
    for i in range(n):
        p0, p1, p2 = Vector(poly[i - 1]), Vector(poly[i]), Vector(poly[(i + 1) % n])
        e0 = p1 - p0; e1 = p2 - p1
        if e0.length < 1e-9: e0 = e1
        if e1.length < 1e-9: e1 = e0
        e0.normalize(); e1.normalize()
        n0 = Vector((e0[1], -e0[0])) if ccw else Vector((-e0[1], e0[0]))
        n1 = Vector((e1[1], -e1[0])) if ccw else Vector((-e1[1], e1[0]))
        nb = n0 + n1; nb = nb.normalized() if nb.length > 1e-6 else n0
        q = p1 + nb * (d / max(0.25, nb.dot(n0))); out.append((q[0], q[1]))
    return out


def resample(poly, step, closed=True):
    """Points along a polyline every <= step metres (keeps the corners)."""
    out = []; n = len(poly)
    for i in range(n if closed else n - 1):
        a = Vector(poly[i]); b = Vector(poly[(i + 1) % n]); k = max(1, int(math.ceil((b - a).length / step)))
        for j in range(k): out.append(tuple(a.lerp(b, j / k)))
    if not closed: out.append(tuple(poly[-1]))
    return out


def arc_pts(c, r, a0_deg, a1_deg, n=None, plane='XZ'):
    """Points of an arc of radius r around 3D centre c in a plane ('XZ', 'YZ' or 'XY')."""
    n = n or lod_segments(16); out = []
    for k in range(n + 1):
        a = math.radians(a0_deg + (a1_deg - a0_deg) * k / n); ca, sa = r * math.cos(a), r * math.sin(a)
        out.append({'XZ': (c[0] + ca, c[1], c[2] + sa), 'YZ': (c[0], c[1] + ca, c[2] + sa), 'XY': (c[0] + ca, c[1] + sa, c[2])}[plane])
    return out


def round_path(pts, r, segs=None):
    """Round the corners of a 3D polyline with radius r (so a tube bends instead of kinking thin)."""
    segs = segs or max(2, lod_segments(8)); P = [Vector(p) for p in pts]
    if len(P) < 3 or r <= 0: return P
    out = [P[0]]
    for i in range(1, len(P) - 1):
        a = (P[i - 1] - P[i]); b = (P[i + 1] - P[i]); la, lb = a.length, b.length
        if la < 1e-9 or lb < 1e-9: continue
        a /= la; b /= lb; ang = a.angle(b)
        if ang < 1e-3 or abs(ang - math.pi) < 1e-3: out.append(P[i]); continue
        t = min(r / math.tan(ang / 2), la * 0.49, lb * 0.49); rr = t * math.tan(ang / 2)
        s = P[i] + a * t; e = P[i] + b * t; c = P[i] + (a + b).normalized() * (rr / math.sin(ang / 2))
        u = (s - c).normalized(); w = (e - c).normalized(); tot = u.angle(w)
        ax = u.cross(w)
        if ax.length < 1e-9: out += [s, e]; continue
        ax.normalize()
        for k in range(segs + 1):
            out.append(c + (Matrix.Rotation(tot * k / segs, 3, ax) @ u) * rr)
    out.append(P[-1]); return out


# =========================================================================================== object finishing
def _place(o, loc, rot_deg):
    if loc is not None: o.location = loc
    if rot_deg is not None: o.rotation_euler = Euler([math.radians(a) for a in rot_deg])
    return o


def _finish(name, bm, mat, smooth=False, loc=None, rot_deg=None, flat_faces=(), recalc=True):
    if recalc: bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for f in bm.faces: f.smooth = bool(smooth)
    for f in flat_faces:
        if f.is_valid: f.smooth = False
    me = mesh_from_bm(name, bm)
    return _place(new_object(name, me, mat), loc, rot_deg)


def _loft_bm(bm, rings, closed=True, uvl=None, v_off=0.0, u_off=0.0):
    """Faces between consecutive rings of BMVerts, with metre UVs (u around, v along)."""
    pts = [[v.co for v in r] for r in rings]
    us, vs = uv.ring_coords(pts, closed, v_off)
    n = len(rings[0]); faces = []
    for i in range(len(rings) - 1):
        A, B = rings[i], rings[i + 1]
        for k in range(n if closed else n - 1):
            k2 = (k + 1) % n
            if len({A[k], A[k2], B[k2], B[k]}) < 3: continue
            vv = [A[k], A[k2], B[k2], B[k]]; uvv = [(us[i][k], vs[i]), (us[i][k + 1], vs[i]), (us[i + 1][k + 1], vs[i + 1]), (us[i + 1][k], vs[i + 1])]
            keep = []; seen = set()
            for v_, t_ in zip(vv, uvv):
                if v_ in seen: continue
                seen.add(v_); keep.append((v_, t_))
            if len(keep) < 3: continue
            try:
                f = bm.faces.new([x[0] for x in keep])
            except ValueError:
                continue
            for l, (_, t_) in zip(f.loops, keep): l[uvl].uv = (t_[0] + u_off, t_[1])
            faces.append(f)
    return faces


def _cap(bm, ring, uvl, normal_hint, band):
    try:
        f = bm.faces.new(ring)
    except ValueError:
        return None
    f.normal_update()
    if f.normal.dot(normal_hint) < 0: f.normal_flip()
    uv.cap(bm, [f], normal_hint, uvl, off=(band * uv.BAND, 0.0))
    return f


# =========================================================================================== solids
def box(name, size, mat=None, loc=None, rot_deg=None, bevel_w=0.0, bevel_segs=None, origin='center'):
    """Box of size (x, y, z) m. origin 'center' or 'bottom' (base at z=0). Box UVs in metres."""
    bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0)
    sx, sy, sz = size; dz = sz / 2 if origin == 'bottom' else 0.0
    for v in bm.verts: v.co = Vector((v.co.x * sx, v.co.y * sy, v.co.z * sz + dz))
    bm.normal_update(); uv.box(bm)
    o = _finish(name, bm, mat, loc=loc, rot_deg=rot_deg)
    if bevel_w > 0: bevel(o, bevel_w, bevel_segs)
    return o


def prism(name, outline, z0, z1, axis='Z', mat=None, caps=True, smooth=False, loc=None, rot_deg=None):
    """Extrude a closed 2D outline from z0 to z1 along axis. Outline coordinates map to (x, y) for Z, (y, z) for X,
    (x, z) for Y. Sides: u = perimeter (m), v = depth (m); caps planar in their own UV bands."""
    ax = axis.upper(); bm = bmesh.new(); uvl = uv.layer(bm)

    def P(p, d):
        return {'Z': (p[0], p[1], d), 'X': (d, p[0], p[1]), 'Y': (p[0], d, p[1])}[ax]
    a = [bm.verts.new(P(p, z0)) for p in outline]; b = [bm.verts.new(P(p, z1)) for p in outline]
    _loft_bm(bm, [a, b], True, uvl)
    flat = []
    if caps:
        flat.append(_cap(bm, list(reversed(a)), uvl, -AXES[ax] * (1 if z1 > z0 else -1), 1))
        flat.append(_cap(bm, b, uvl, AXES[ax] * (1 if z1 > z0 else -1), 2))
    return _finish(name, bm, mat, smooth, loc, rot_deg, [f for f in flat if f])


def rbox(name, size, r, axis='Z', mat=None, segs=None, loc=None, rot_deg=None, bevel_w=0.0):
    """Box of size (x, y, z) m whose edges along `axis` are rounded with radius r (a rounded-rectangle prism)."""
    sx, sy, sz = size; ax = axis.upper(); n = segs or max(2, lod_segments(16) // 4)
    w, h, d = {'Z': (sx, sy, sz), 'X': (sy, sz, sx), 'Y': (sx, sz, sy)}[ax]
    o = prism(name, rr_outline(w, h, r, n), -d / 2, d / 2, ax, mat, True, False, loc, rot_deg)
    if bevel_w > 0: bevel(o, bevel_w, 2)
    return o


def loft(name, rings, mat=None, closed=True, caps=(False, False), smooth=False, loc=None, rot_deg=None):
    """Surface through rings of 3D points (equal counts). caps close the first/last ring with a flat face."""
    bm = bmesh.new(); uvl = uv.layer(bm)
    V = [[bm.verts.new(tuple(p)) for p in r] for r in rings]
    _loft_bm(bm, V, closed, uvl)
    flat = []
    if caps[0] or caps[1]:
        c0 = sum((Vector(p) for p in rings[0]), Vector()) / len(rings[0]); c1 = sum((Vector(p) for p in rings[-1]), Vector()) / len(rings[-1])
        if caps[0]: flat.append(_cap(bm, list(reversed(V[0])), uvl, (c0 - c1), 1))
        if caps[1]: flat.append(_cap(bm, V[-1], uvl, (c1 - c0), 2))
    return _finish(name, bm, mat, smooth, loc, rot_deg, [f for f in flat if f])


def cyl(name, r, h, axis='Z', mat=None, segs=None, r2=None, caps=True, loc=None, rot_deg=None, bevel_w=0.0, origin='center'):
    """Cylinder (or cone frustum with top radius r2) of radius r, length h along axis. Smooth sides, flat caps."""
    n = segs or lod_segments(32); ax = axis.upper(); z0 = 0.0 if origin == 'bottom' else -h / 2
    rr = r if r2 is None else r2
    ring0 = [(r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n)) for k in range(n)]
    ring1 = [(rr * math.cos(2 * math.pi * k / n), rr * math.sin(2 * math.pi * k / n)) for k in range(n)]
    bm = bmesh.new(); uvl = uv.layer(bm)

    def P(p, d):
        return {'Z': (p[0], p[1], d), 'X': (d, p[0], p[1]), 'Y': (p[1], d, p[0])}[ax]
    a = [bm.verts.new(P(p, z0)) for p in ring0]; b = [bm.verts.new(P(p, z0 + h)) for p in ring1]
    _loft_bm(bm, [a, b], True, uvl)
    flat = []
    if caps:
        flat.append(_cap(bm, list(reversed(a)), uvl, -AXES[ax], 1)); flat.append(_cap(bm, b, uvl, AXES[ax], 2))
    o = _finish(name, bm, mat, True, loc, rot_deg, [f for f in flat if f])
    if bevel_w > 0: bevel(o, bevel_w, 2, angle_deg=60)
    return o


def lathe(name, profile, axis='Z', mat=None, segs=None, smooth=True, loc=None, rot_deg=None):
    """Revolve a (radius, height) profile around the local axis. Points with radius 0 close the shape at the axis
    (a pole); an open profile gives an open shell. UVs: u = arc length at that radius, v = along the profile (m)."""
    n = segs or lod_segments(48); ax = axis.upper(); bm = bmesh.new(); uvl = uv.layer(bm)

    def P(r, z, k):
        a = 2 * math.pi * k / n; x, y = r * math.cos(a), r * math.sin(a)
        return {'Z': (x, y, z), 'X': (z, x, y), 'Y': (y, z, x)}[ax]
    rows = []
    for (r, z) in profile:
        rows.append([bm.verts.new(P(r, z, 0))] * n if r < 1e-7 else [bm.verts.new(P(r, z, k)) for k in range(n)])
    s = [0.0]
    for i in range(1, len(profile)):
        s.append(s[-1] + math.hypot(profile[i][0] - profile[i - 1][0], profile[i][1] - profile[i - 1][1]))
    for i in range(len(rows) - 1):
        A, B = rows[i], rows[i + 1]; ra, rb = profile[i][0], profile[i + 1][0]
        for k in range(n):
            k2 = (k + 1) % n; vv = []; tt = []
            for v_, t_ in ((A[k], (2 * math.pi * ra * k / n, s[i])), (A[k2], (2 * math.pi * ra * (k + 1) / n, s[i])),
                           (B[k2], (2 * math.pi * rb * (k + 1) / n, s[i + 1])), (B[k], (2 * math.pi * rb * k / n, s[i + 1]))):
                if v_ in vv: continue
                vv.append(v_); tt.append(t_)
            if len(vv) < 3: continue
            try:
                f = bm.faces.new(vv)
            except ValueError:
                continue
            for l, t_ in zip(f.loops, tt): l[uvl].uv = t_
    bm.verts.ensure_lookup_table()
    return _finish(name, bm, mat, smooth, loc, rot_deg)


def frames_along(path, up=None):
    """Rotation-minimising frames (tangent, normal, binormal) along a 3D polyline."""
    P = [Vector(p) for p in path]; T = []
    for i in range(len(P)):
        t = (P[min(i + 1, len(P) - 1)] - P[max(i - 1, 0)])
        T.append(t.normalized() if t.length > 1e-12 else Vector((1, 0, 0)))
    u = Vector(up) if up is not None else (Vector((0, 0, 1)) if abs(T[0].z) < 0.9 else Vector((1, 0, 0)))
    N = [(u - T[0] * u.dot(T[0])).normalized()]
    for i in range(1, len(P)):
        n = N[-1] - T[i] * N[-1].dot(T[i]); N.append(n.normalized() if n.length > 1e-9 else N[-1])
    return P, T, N, [t.cross(n) for t, n in zip(T, N)]


def sweep(name, path, profile, mat=None, closed_profile=True, caps=True, smooth=True, up=None, miter=True, loc=None, rot_deg=None):
    """Sweep a 2D profile (x along the path normal, y along the binormal) along a 3D polyline. At corners the profile
    is stretched by 1/cos(half angle) so the wall keeps its thickness (use round_path for real bends)."""
    P, T, N, B = frames_along(path, up); bm = bmesh.new(); uvl = uv.layer(bm); rings = []
    for i, p in enumerate(P):
        k = 1.0
        if miter and 0 < i < len(P) - 1:
            a = (P[i] - P[i - 1]); b = (P[i + 1] - P[i])
            if a.length > 1e-9 and b.length > 1e-9:
                c = a.normalized().dot(b.normalized()); k = 1.0 / max(0.35, math.sqrt((1 + c) / 2))
        bend = (P[min(i + 1, len(P) - 1)] - P[i]).normalized() - (P[i] - P[max(i - 1, 0)]).normalized()
        ring = []
        for (x, y) in profile:
            q = N[i] * x + B[i] * y
            if k != 1.0 and bend.length > 1e-9:
                bd = bend.normalized(); q = q + bd * (q.dot(bd) * (k - 1))
            ring.append(bm.verts.new(p + q))
        rings.append(ring)
    _loft_bm(bm, rings, closed_profile, uvl)
    flat = []
    if caps and closed_profile:
        flat.append(_cap(bm, list(reversed(rings[0])), uvl, -T[0], 1)); flat.append(_cap(bm, rings[-1], uvl, T[-1], 2))
    return _finish(name, bm, mat, smooth, loc, rot_deg, [f for f in flat if f])


def tube(name, path, r, mat=None, segs=None, caps=True, up=None, bend_r=None):
    """Round tube of radius r along a 3D polyline; bend_r rounds its corners first (default 2.5 r)."""
    n = segs or lod_segments(16)
    pts = round_path(path, 2.5 * r if bend_r is None else bend_r) if len(path) > 2 else [Vector(p) for p in path]
    return sweep(name, pts, circle(r, n), mat, True, caps, True, up, miter=True)


def ring_solid(name, outer, inner, d0, d1, mat=None, axis='Y', place=None, smooth=False, loc=None, rot_deg=None):
    """A frame between two closed outlines with the same point count (window surround, gasket, door frame),
    from depth d0 to d1. place(u, v, d) -> 3D point maps the outlines onto a curved surface (default: the plane
    normal to `axis`, depth along it). Front/back faces planar UVs, walls perimeter x depth."""
    assert len(outer) == len(inner), 'ring_solid: outer and inner outlines need the same number of points'
    ax = axis.upper()
    if place is None:
        def place(u, v, d):
            return {'Y': Vector((u, d, v)), 'X': Vector((d, u, v)), 'Z': Vector((u, v, d))}[ax]
    bm = bmesh.new(); uvl = uv.layer(bm); n = len(outer)
    O0 = [bm.verts.new(place(u, v, d0)) for (u, v) in outer]; O1 = [bm.verts.new(place(u, v, d1)) for (u, v) in outer]
    I0 = [bm.verts.new(place(u, v, d0)) for (u, v) in inner]; I1 = [bm.verts.new(place(u, v, d1)) for (u, v) in inner]
    _loft_bm(bm, [O0, O1], True, uvl, u_off=0.0)
    _loft_bm(bm, [I1, I0], True, uvl, u_off=uv.BAND)
    for (A, B, band) in ((O0, I0, 2), (I1, O1, 3)):
        for k in range(n):
            k2 = (k + 1) % n
            try:
                f = bm.faces.new((A[k], A[k2], B[k2], B[k]))
            except ValueError:
                continue
            for l, (u, v) in zip(f.loops, (outer[k], outer[k2], inner[k2], inner[k]) if A is O0 else (inner[k], inner[k2], outer[k2], outer[k])):
                l[uvl].uv = (u + band * uv.BAND, v)
    return _finish(name, bm, mat, smooth, loc, rot_deg)


def frame(name, w, h, r, rim, depth, mat=None, axis='Y', segs=None, place=None, d0=None):
    """Rounded-rectangle picture frame (gasket, sash, architrave): opening w x h with corner radius r, rim width rim,
    depth along `axis` (centred unless d0 given)."""
    n = segs or max(2, lod_segments(24) // 4)
    outer = rr_outline(w + 2 * rim, h + 2 * rim, r + rim, n); inner = rr_outline(w, h, r, n)
    a = -depth / 2 if d0 is None else d0
    return ring_solid(name, outer, inner, a, a + depth, mat, axis, place)


def pane(name, outline, t, mat=None, axis='Y', place=None, d=0.0):
    """A flat (or, with place(), curved) sheet of thickness t: glass, a panel."""
    ax = axis.upper()
    if place is None:
        def place(u, v, dd):
            return {'Y': Vector((u, dd, v)), 'X': Vector((dd, u, v)), 'Z': Vector((u, v, dd))}[ax]
    bm = bmesh.new(); uvl = uv.layer(bm)
    f0 = [bm.verts.new(place(u, v, d + t / 2)) for (u, v) in outline]; f1 = [bm.verts.new(place(u, v, d - t / 2)) for (u, v) in outline]
    _loft_bm(bm, [f0, f1], True, uvl)
    for ring, band in ((f0, 1), (list(reversed(f1)), 2)):
        try:
            f = bm.faces.new(ring)
        except ValueError:
            continue
        pts = outline if ring is f0 else list(reversed(outline))
        for l, (u, v) in zip(f.loops, pts): l[uvl].uv = (u + band * uv.BAND, v)
    return _finish(name, bm, mat, False)


def decal(name, w, h, mat=None, max_edge=None):
    """Flat sheet w x h in the local XY plane facing +Z, subdivided so lay() can bend it over a curved host;
    UV 0..1 over the sheet (one image, CLIP extension)."""
    me_ = max_edge or const.MAX_EDGE
    nx = max(1, int(math.ceil(w / me_))); ny = max(1, int(math.ceil(h / me_)))
    bm = bmesh.new(); uvl = uv.layer(bm)
    V = [[bm.verts.new((-w / 2 + w * i / nx, -h / 2 + h * j / ny, 0.0)) for i in range(nx + 1)] for j in range(ny + 1)]
    for j in range(ny):
        for i in range(nx):
            f = bm.faces.new((V[j][i], V[j][i + 1], V[j + 1][i + 1], V[j + 1][i]))
            for l in f.loops: l[uvl].uv = ((l.vert.co.x + w / 2) / w, (l.vert.co.y + h / 2) / h)
    return _finish(name, bm, mat, False, recalc=False)


def plate(name, w, h, t, r=0.0, mat=None, bevel_w=0.0):
    """A plate w x h, thickness t (z), corner radius r: number plates, maker plates, inlays (lay cut=True)."""
    return rbox(name, (w, h, t), r, 'Z', mat, bevel_w=bevel_w) if r > 0 else box(name, (w, h, t), mat, bevel_w=bevel_w)


def gusset(name, a, b, t, mat=None):
    """Right-triangle plate hanging under a beam: the right angle at the origin, top edge a along +x, vertical edge b
    down -z, thickness t along y. Attach it by '+z' under the beam (spin_deg=180 points it along -x)."""
    return prism(name, [(0, 0), (0, -b), (a, 0)], -t / 2, t / 2, 'Y', mat)


def text_mesh(name, s, size, depth, mat=None, font=None, align='CENTER', space=1.0, bevel_frac=0.25):
    """Lettering as real geometry (exact, from code): text in the local XY plane facing +Z, extruded depth (m) total.
    font: a .ttf path (default: Noto Sans Condensed Bold if present, else Blender's built-in)."""
    import os
    cu = bpy.data.curves.new(name + '_txt', 'FONT'); cu.body = s; cu.size = size; cu.extrude = depth / 2
    cu.align_x = align; cu.align_y = 'CENTER'; cu.space_character = space
    f = font or '/usr/share/fonts/truetype/noto/NotoSans-CondensedBold.ttf'
    if os.path.exists(f):
        cu.font = bpy.data.fonts.load(f, check_existing=True)
    cu.bevel_depth = depth * bevel_frac * 0.5; cu.bevel_resolution = 1; cu.resolution_u = max(2, lod_segments(10) // 2)
    t = bpy.data.objects.new(name + '_tmp', cu); bpy.context.scene.collection.objects.link(t)
    core.update(); dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(t.evaluated_get(dg)); bpy.data.objects.remove(t); bpy.data.curves.remove(cu)
    bm = bmesh.new(); bm.from_mesh(me); bpy.data.meshes.remove(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6); uv.box(bm)
    return _finish(name, bm, mat, False)


# =========================================================================================== modifiers
def bevel(o, w=0.004, segs=None, angle_deg=35, harden=True):
    """Bevel modifier by angle (clamped, arc miters) + harden normals. segs=None: 3 at film level, fewer below,
    none at far (no bevel)."""
    segs = segs if segs is not None else {'film': 3, 'near': 2, 'mid': 1, 'far': 0}[core.lod()]
    if segs <= 0 or w <= 0: return None
    m = o.modifiers.new('bevel', 'BEVEL'); m.width = w; m.segments = segs; m.limit_method = 'ANGLE'
    m.angle_limit = math.radians(angle_deg); m.use_clamp_overlap = True; m.miter_outer = 'MITER_ARC'
    m.harden_normals = harden
    if harden:
        for p in o.data.polygons: p.use_smooth = True
    return m


def subsurf(o, levels=2):
    lv = max(0, levels - {'film': 0, 'near': 1, 'mid': 2, 'far': 2}[core.lod()])
    if lv <= 0: return None
    m = o.modifiers.new('subsurf', 'SUBSURF'); m.levels = lv; m.render_levels = lv
    return m


def smooth(o, angle_deg=None):
    """Shade smooth; with angle_deg, edges sharper than that stay sharp (Mesh.set_sharp_from_angle, Blender 4.1+)."""
    me = o.data; me.shade_smooth()
    if angle_deg is not None: me.set_sharp_from_angle(angle=math.radians(angle_deg))
    return o


def apply_mods(o):
    """Apply all modifiers into the mesh. Refuses an object in a viewport-hidden or excluded collection: the evaluated
    mesh there is silently the unmodified one (cab lesson: 3.7k triangles lost)."""
    for c in o.users_collection:
        assert not c.hide_viewport, f'apply_mods: {o.name} is in viewport-hidden collection {c.name}'
    core.update(); dg = bpy.context.evaluated_depsgraph_get(); ev = o.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
    old = o.data; o.modifiers.clear(); o.data = me
    if old.users == 0: bpy.data.meshes.remove(old)
    return o


def solidify(o, t, offset=-1.0, rim=True, apply=True):
    """Give a sheet thickness t (offset -1 inward, +1 outward). The new inner skin gets its OWN UVs (a separate band)
    and the rim gets box UVs, so no two faces share texture space (a car white-steel fault)."""
    for g in ('kit3d_shell', 'kit3d_rim'):         # BEFORE the modifier: Blender 5.2 drops a group name that does not
        if g not in o.vertex_groups: o.vertex_groups.new(name=g)      # exist yet (reads back ''), and no skin is marked
    m = o.modifiers.new('solidify', 'SOLIDIFY'); m.thickness = t; m.offset = offset; m.use_rim = rim
    m.use_even_offset = True; m.shell_vertex_group = 'kit3d_shell'; m.rim_vertex_group = 'kit3d_rim'
    if m.shell_vertex_group != 'kit3d_shell' or m.rim_vertex_group != 'kit3d_rim':
        raise RuntimeError(f'kit3d.solidify: {o.name}: Blender did not take the shell/rim vertex groups; the inner skin '
                           f'would keep the outer skin\'s UVs')
    if not apply: return m          # the groups stay: the modifier fills them when it is applied (split_shell_uv then)
    apply_mods(o)
    split_shell_uv(o)
    return o


def split_shell_uv(o):
    """After a solidify() modifier was applied: move the inner skin to its own UV band and box-project the rim, using
    the 'kit3d_shell' / 'kit3d_rim' vertex groups the modifier filled, then remove the groups. solidify(apply=True)
    calls this; with apply=False call it yourself after apply_mods()."""
    me = o.data; bm = bmesh.new(); bm.from_mesh(me); uvl = uv.layer(bm)
    dl = bm.verts.layers.deform.active
    if dl is not None:
        gi = {g.name: g.index for g in o.vertex_groups}
        sh, ri = gi.get('kit3d_shell'), gi.get('kit3d_rim')
        inner = [f for f in bm.faces if all(sh in v[dl] for v in f.verts)]; iset = set(inner)
        rimf = [f for f in bm.faces if f not in iset and any(sh in v[dl] for v in f.verts)]
        for f in inner:
            for l in f.loops: l[uvl].uv = (l[uvl].uv[0] + 6 * uv.BAND, l[uvl].uv[1])
        if rimf:
            uv.box(bm, rimf, uvl=uvl)
            for f in rimf:
                for l in f.loops: l[uvl].uv = (l[uvl].uv[0] + 7 * uv.BAND, l[uvl].uv[1])
    bm.to_mesh(me); bm.free()
    for g in ('kit3d_shell', 'kit3d_rim'):
        if g in o.vertex_groups: o.vertex_groups.remove(o.vertex_groups[g])
    return o


def join(objs, name=None):
    """Join objects into the first (materials remapped). Relations naming the joined objects move to the result."""
    objs = [core.obj(o) for o in objs if o]
    base = objs[0]
    if len(objs) > 1:
        bm = bmesh.new(); bm.from_mesh(base.data); mats = list(base.data.materials)
        for o in objs[1:]:
            tmp = o.data.copy(); tmp.transform(base.matrix_world.inverted() @ o.matrix_world)
            if (base.matrix_world.inverted() @ o.matrix_world).determinant() < 0: tmp.flip_normals()
            idx = []
            for m in tmp.materials:
                if m not in mats: mats.append(m)
                idx.append(mats.index(m))
            for p in tmp.polygons: p.material_index = idx[p.material_index] if idx else 0
            bm.from_mesh(tmp); bpy.data.meshes.remove(tmp)
        me = bpy.data.meshes.new(name or base.name); bm.to_mesh(me); bm.free()
        for m in mats: me.materials.append(m)
        old = base.data; base.data = me
        if old.users == 0: bpy.data.meshes.remove(old)
    gone = [o.name for o in objs[1:]]
    for o in objs[1:]: bpy.data.objects.remove(o, do_unlink=True)
    if name: base.name = name
    d = core.rels(); out = {}
    for k, r in d.items():
        if r['part'] in gone: r['part'] = base.name
        if r.get('host') in gone: r['host'] = base.name
        if r['part'] == r.get('host'): continue
        out[core.rel_key(r['kind'], r['part'], r.get('host', ''))] = r
    core.save_rels(out)
    return base


def boolean(o, others, op='DIFFERENCE', solver='EXACT', keep=False):
    """Apply a boolean of `o` with each of `others` now (op DIFFERENCE / UNION / INTERSECT)."""
    others = [core.obj(x) for x in others]
    for ct in others:
        m = o.modifiers.new('bool', 'BOOLEAN'); m.operation = op; m.solver = solver; m.object = ct
    for ct in others: ct.hide_viewport = False
    apply_mods(o)
    if not keep:
        for ct in others: bpy.data.objects.remove(ct, do_unlink=True)
    return o


def cut(o, cutters, keep=False):
    return boolean(o, cutters, 'DIFFERENCE', keep=keep)


def union(o, others):
    return boolean(o, others, 'UNION')
