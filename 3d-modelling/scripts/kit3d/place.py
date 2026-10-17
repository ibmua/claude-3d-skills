"""kit3d placement by relation (R1): attach / span / lay / into / scatter / free / root, anchors, mirror, array,
reattach. Every call records its relation in the scene (scene['kit3d_rel']) with what it needs to be measured and
replayed; nothing here asks for a typed coordinate along a host's normal.

ANCHORS on a host (`at=`), all resolved on the host's REAL surface (curved hosts included):
  'top' 'bottom' '+x' '-x' '+y' '-y' '+z' '-z'   centre of that face of the host's own bounding box, then a ray along
                                                 the face's inward normal onto the surface (host-local frame)
  ('+y', u, v)                                   the same at fractions u, v (0..1) across that face (u, v = the two
                                                 other axes in x, y, z order)
  on('+y', x=1.2, z=1.5)                         the same at host-local coordinates for the two in-plane axes
  (x, y, z) / Vector                             a world point: the closest point of the host surface, its normal
  'anchor.<name>'                                an empty: its world position, its local +Z = the surface's outward
                                                 normal (make one with kit3d.anchor())
PART side (`by=`): a face of the part's own bounding box ('-z' = its bottom, '-y' = its back ...), 'anchor.<name>'
  (an empty whose +Z points out of the part's mounting face, toward the host), or ((x, y, z), (nx, ny, nz)) local.
ORIENTATION with align=True: the part's mounting face turns to face the host. A part mounted by its bottom or top
  (plates, decals, lettering drawn in their XY plane): on a wall its local +Y is up and +X reads left to right seen
  from outside; on a roof or floor it keeps its own axes. Any other part: on a wall its local +Z stays up, on a roof
  its local +Z runs along world +X. Change with up=(world vector) and spin_deg=.
"""
import json, math
import bpy, bmesh
import numpy as np
from mathutils import Vector, Matrix

from . import const, core
from .core import obj, vec

FACE = {'top': (2, 1.0), 'bottom': (2, -1.0), '+x': (0, 1.0), '-x': (0, -1.0), '+y': (1, 1.0), '-y': (1, -1.0),
        '+z': (2, 1.0), '-z': (2, -1.0)}
OPP = {'top': 'bottom', 'bottom': 'top', '+x': '-x', '-x': '+x', '+y': '-y', '-y': '+y', '+z': '-z', '-z': '+z'}
X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))


def on(face, x=None, y=None, z=None, u=None, v=None):
    """Anchor on a face of the host at host-local coordinates (metres) and/or fractions u, v (0..1)."""
    if face not in FACE: raise ValueError(f'kit3d.on: face {face!r} not in {list(FACE)}')
    return {'face': face, 'x': x, 'y': y, 'z': z, 'u': u, 'v': v}


# ============================================================================================ geometry helpers
SMOOTH_COS = 0.7    # faces meeting at more than ~45 deg are a hard edge: their normals are not blended across it


def _adj(g):
    """Vertex -> incident triangles of a Geo (CSR arrays, lazy, cached per Geo)."""
    key = ('adj', g.name, len(g.v))
    c = _VN.get(key)
    if c is not None and c[0] is g: return c[1]
    flat = g.t.ravel(); order = np.argsort(flat, kind='stable')
    res = (order // 3, np.searchsorted(flat[order], np.arange(len(g.v) + 1)))
    _VN[key] = (g, res)
    if len(_VN) > 512: _VN.clear()
    return res


_VN = {}


def _corner_normal(g, vi, fn):
    tri_of, st = _adj(g); ts = tri_of[st[vi]:st[vi + 1]]
    nn = g.n[ts]; ok = nn @ fn > SMOOTH_COS
    w = (nn[ok] * g.a[ts][ok, None]).sum(0)
    ln = float(np.linalg.norm(w))
    return w / ln if ln > 1e-20 else fn


def surface_normal(g, tri, p):
    """Outward normal of Geo g at point p on triangle tri: vertex normals interpolated across smooth curvature
    (a curved roof) but not across hard edges (> ~45 deg), so the top of a box is +z right up to its rim."""
    ids = g.t[tri]; a, b, c = (Vector(g.v[i]) for i in ids); fn = g.n[tri]
    w = _bary(Vector(p), a, b, c)
    n = Vector(sum(_corner_normal(g, int(i), fn) * wi for i, wi in zip(ids, w)))
    if n.length < 1e-9 or n.dot(Vector(fn)) < 0.3: return Vector(fn)
    return n.normalized()


def _bary(p, a, b, c):
    v0, v1, v2 = b - a, c - a, p - a
    d00, d01, d11, d20, d21 = v0.dot(v0), v0.dot(v1), v1.dot(v1), v2.dot(v0), v2.dot(v1)
    den = d00 * d11 - d01 * d01
    if abs(den) < 1e-30: return (1 / 3, 1 / 3, 1 / 3)
    v = (d11 * d20 - d01 * d21) / den; w = (d00 * d21 - d01 * d20) / den
    return (1 - v - w, v, w)


_JIT = ((0.0, 0.0), (1.3e-5, 0.7e-5), (-0.9e-5, 1.1e-5), (0.4e-5, -1.4e-5))


def ray(bvh, o, d, dist):
    """BVHTree.ray_cast that does not miss a ray passing exactly through a shared edge or vertex (a ray down the
    centre line of a subdivided plate misses both triangles in float32): retried with 10-um side offsets."""
    r = bvh.ray_cast(o, d, dist)
    if r[0] is not None: return r
    u = d.orthogonal().normalized(); w = d.cross(u)
    for a, b in _JIT[1:]:
        r = bvh.ray_cast(o + u * a + w * b, d, dist)
        if r[0] is not None: return r
    return r


def depth_along(g, p, n, reach=0.25):
    """Signed depth of point p under the host surface measured along the line p + t*n (n = outward): > 0 inside the
    host by that much, < 0 a gap of that much above the surface, None if the line meets no host surface within
    `reach`. The surface is the first crossing coming in from outside (p + n*reach)."""
    bvh = g.bvh
    if bvh is None: return None
    p = Vector(p); n = Vector(n).normalized(); o = p + n * reach; d = -n; travelled = 0.0; lim = 2 * reach
    for _ in range(6):
        loc, nor, idx, dist = ray(bvh, o, d, lim - travelled)
        if loc is None: return None
        travelled += dist
        if nor.dot(n) > 0:              # an outward-facing surface met from outside: the host's skin
            return (loc - p).dot(n)
        o = loc + d * 1e-6; travelled += 1e-6
    return None


def surface_hit(g, p, n, reach=0.25):
    """(point, triangle) where the line p + t*n first meets the host's outward skin coming in from outside (the
    surface depth_along measures to), or None."""
    bvh = g.bvh
    if bvh is None: return None
    p = Vector(p); n = Vector(n).normalized(); o = p + n * reach; d = -n; travelled = 0.0; lim = 2 * reach
    for _ in range(6):
        loc, nor, idx, dist = ray(bvh, o, d, lim - travelled)
        if loc is None: return None
        travelled += dist
        if nor.dot(n) > 0: return loc, idx
        o = loc + d * 1e-6; travelled += 1e-6
    return None


def wall_below(g, s, n, reach=0.3):
    """Thickness of the host wall under surface point s (distance to the next inward-facing crossing along -n)."""
    bvh = g.bvh; o = Vector(s) - Vector(n) * 1e-5
    loc, nor, idx, dist = ray(bvh, o, -Vector(n), reach)
    if loc is None or nor.dot(Vector(n)) > 0: return None
    return dist + 1e-5


# ============================================================================================ anchors
def frame_of(o):
    """The matrix freeze() applied into the mesh of o (None when it was not frozen): mesh now = F @ mesh as built, so
    F also takes a point of the part's own (built) frame to where it is in the object's frame now."""
    f = o.get('kit3d_frame')
    return Matrix([list(f[i * 4:i * 4 + 4]) for i in range(4)]) if f is not None else None


def _local_box(o, F=None):
    """Bounding box in the object's own frame; with F (frame_of) in the frame the part was built in."""
    lv = core.local_verts(o)
    if not len(lv): raise ValueError(f'kit3d: {o.name} has no geometry')
    if F is not None:
        Fi = np.array(F.inverted()); lv = lv @ Fi[:3, :3].T + Fi[:3, 3]
    return Vector(lv.min(0)), Vector(lv.max(0))


def resolve(host, at):
    """(surface point, outward normal, triangle index) of anchor `at` on `host`, in world space."""
    h = obj(host); g = core.geo(h)
    if g.bvh is None: raise ValueError(f'kit3d: host {h.name} has no surface')
    if isinstance(at, str) and at.startswith('anchor.'):
        e = obj(at); m = e.matrix_world
        return m.translation.copy(), (m.to_3x3() @ Z).normalized(), None
    if isinstance(at, str) and at in FACE: at = on(at)
    if isinstance(at, (tuple, list)) and len(at) == 3 and isinstance(at[0], str):
        at = on(at[0], u=at[1], v=at[2])
    if isinstance(at, dict):
        F = frame_of(h)                    # identity unless freeze() moved the host's placement into its mesh
        ax, sg = FACE[at['face']]; lo, hi = _local_box(h, F)
        q = (lo + hi) / 2; others = [i for i in range(3) if i != ax]
        for i, key in zip(others, ('u', 'v')):
            nm = 'xyz'[i]
            if at.get(nm) is not None: q[i] = at[nm]
            elif at.get(key) is not None: q[i] = lo[i] + (hi[i] - lo[i]) * at[key]
        size = (hi - lo).length
        q[ax] = (hi[ax] if sg > 0 else lo[ax]) + sg * (0.02 + 0.01 * size)
        M = h.matrix_world @ F if F is not None else h.matrix_world; dl = Vector((0, 0, 0)); dl[ax] = -sg
        o = M @ q; dw = (M.to_3x3() @ dl).normalized()
        loc, nor, idx, dist = ray(g.bvh, o, dw, (hi - lo)[ax] + 0.05 + 0.02 * size)
        if loc is None:
            raise ValueError(f'kit3d: no surface of {h.name} at {at} (ray along {at["face"]} inward missed: a hole, '
                             f'or outside the host)')
        n = surface_normal(g, idx, loc)
        if n.dot(-dw) < 0: n = -n
        return loc, n, idx
    p = vec(at)
    loc, nor, idx, dist = g.bvh.find_nearest(p)
    if loc is None: raise ValueError(f'kit3d: nothing of {h.name} near {tuple(p)}')
    return loc, surface_normal(g, idx, loc), idx


def anchor(host, name, at, normal=None):
    """Make 'anchor.<name>': an empty on the host surface at `at` (any anchor form), +Z along the surface normal (or
    `normal`), parented to the host so it moves with it. Parts then attach to 'anchor.<name>'."""
    h = obj(host); p, n, _ = resolve(h, at)
    if normal is not None: n = vec(normal).normalized()
    nm = name if name.startswith('anchor.') else 'anchor.' + name
    e = bpy.data.objects.get(nm)
    if e is None:
        e = bpy.data.objects.new(nm, None); core.current_coll().objects.link(e)
    e.empty_display_type = 'SINGLE_ARROW'; e.empty_display_size = 0.1
    e.parent = h; e.matrix_parent_inverse = h.matrix_world.inverted()
    r = n.to_track_quat('Z', 'Y').to_matrix().to_4x4(); e.matrix_world = Matrix.Translation(p) @ r
    e['kit3d_anchor'] = h.name
    return e


def _part_side(p, by, lv):
    """(local mounting point, local out axis a) for by-spec on part p with local verts lv."""
    if isinstance(by, str) and by.startswith('anchor.'):
        e = obj(by); M = p.matrix_world.inverted() @ e.matrix_world
        return M.translation.copy(), -(M.to_3x3() @ Z).normalized()
    if isinstance(by, (tuple, list)) and len(by) == 2 and not isinstance(by[0], (int, float)):
        return vec(by[0]), -vec(by[1]).normalized()
    if by not in FACE: raise ValueError(f'kit3d: by={by!r}: a face name, anchor.<name> or (point, normal)')
    ax, sg = FACE[by]; lo, hi = Vector(lv.min(0)), Vector(lv.max(0)); c = (lo + hi) / 2
    c[ax] = lo[ax] if sg < 0 else hi[ax]
    a = Vector((0, 0, 0)); a[ax] = -sg
    return c, a


def _default_by(at):
    """The part's face that meets the host when by= is not given: the opposite of the host face named in `at`
    (under a beam -> the part's top), else its bottom."""
    f = at if isinstance(at, str) else (at.get('face') if isinstance(at, dict) else None)
    return OPP.get(f, '-z')


def _rotation(a, n, up=None, spin_deg=0.0, ref=None):
    """3x3 rotation taking local out-axis a to world normal n, keeping the orientation rule of the module doc."""
    a = Vector(a).normalized(); n = Vector(n).normalized()
    flat = abs(a.z) >= 0.9                          # a plate / decal / lettering drawn in its XY plane
    rl = Vector(ref) if ref is not None else (Y if flat else Z)
    rl = rl - a * rl.dot(a)
    if rl.length < 1e-6: rl = Y - a * Y.dot(a)
    rl.normalize()
    u = Vector(up) if up is not None else (Z if abs(n.z) < 0.9 else (Y if flat and ref is None else X))
    rw = u - n * u.dot(n)
    if rw.length < 1e-6: rw = (Y if abs(n.y) < 0.9 else X) - n * (Y if abs(n.y) < 0.9 else X).dot(n)
    rw.normalize()
    if spin_deg: rw = Matrix.Rotation(math.radians(spin_deg), 3, n) @ rw
    L = Matrix((a, rl, a.cross(rl))).transposed(); W = Matrix((n, rw, n.cross(rw))).transposed()
    return W @ L.transposed()


def foot_band(ext):
    """How far above its lowest point a part's mounting side reaches: 2 mm (3 % of tall parts), at most a quarter
    of a small part's height (a 5 mm rivet: 1.25 mm, so its 2 mm shoulder is not mistaken for its base)."""
    return max(0.0005, min(max(0.002, 0.03 * ext), 0.25 * ext))


def _footprint(lv, a, band=None, tris=None):
    """Points of the mounting side, local: vertices within `band` of the lowest along -a, plus points spread over
    the faces lying there (so a flange whose corners overhang its host still has footprint over it)."""
    h = lv @ np.array(a)
    ext = float(h.max() - h.min()) if len(h) else 0.0
    b = band if band is not None else foot_band(ext)
    m = h <= h.min() + b; sel = lv[m]
    if tris is not None and len(tris):
        tt = tris[m[tris].all(1)]
        if len(tt):
            P = lv[tt]; C = P.mean(1)
            extra = [C] + [C + 0.75 * (P[:, k] - C) for k in range(3)]
            sel = np.concatenate([sel] + extra)
    if len(sel) > 600:
        sel = sel[np.linspace(0, len(sel) - 1, 600).astype(int)]
    return sel, h.min(), ext


def _scale_of(p):
    s = p.matrix_world.to_scale()
    if min(s) <= 0 or p.matrix_world.determinant() <= 0:
        raise ValueError(f'kit3d: {p.name} has a mirroring (negative) scale; use kit3d.mirror(), not scale -1 '
                         f'(a mirrored mount bakes inside-out: a car lesson)')
    return s


def auto_embed(embed, height):
    """embed=None -> EMBED (5 mm); a part under ~7 mm tall (5 mm would bury 70 % of it) gets 45 % of its height,
    at least ENTRY_MIN + 0.5 mm (a 5 mm rivet head: 2.5 mm)."""
    if embed is not None: return embed
    if height >= const.EMBED / 0.7: return const.EMBED          # 5 mm buries < 70 % of it
    return round(min(const.EMBED, max(const.ENTRY_MIN + 0.0005, 0.45 * height)), 5)


def _fit(part, g, s, n, R, pb, foot, scale, embed, reach):
    """Translation putting local point pb at surface point s with rotation R, then moved along n so that the
    shallowest footprint point is `embed` inside the host (negative embed = lifted that much)."""
    S = Matrix.Diagonal(scale)
    RS = R @ S
    t = s - RS @ pb - n * embed
    depths = []
    for f in foot:
        w = RS @ Vector(f) + t
        d = depth_along(g, w, n, reach)
        if d is not None: depths.append(d)
    if depths:
        t = t + n * (min(depths) - embed)
    return t, len(depths), len(foot)


def _set_world(part, R, t, scale):
    M = Matrix.Translation(t) @ R.to_4x4() @ Matrix.Diagonal(scale).to_4x4()
    part.matrix_world = M
    core.update()


def _src_mesh(part, store):
    """Keep (store=True) or restore the unbent mesh of a part that attach(conform=)/lay() bends."""
    nm = 'kit3d_src:' + part.name
    me = bpy.data.meshes.get(nm)
    if store:
        if me is None:
            me = part.data.copy(); me.name = nm; me.use_fake_user = True
        return me
    if me is not None and part.type == 'MESH':
        old = part.data; part.data = me.copy(); part.data.name = part.name
        if old.users == 0: bpy.data.meshes.remove(old)
    return me


def _conform(part, g, n_rigid, a_local, base_h, band, embed, lift_mode=False):
    """Bend the part's mesh near its mounting side onto the host: vertices within `band` above the mounting plane
    move so the surface keeps them `embed` deep (or `-embed` = lifted) at every point, fading out over the band."""
    me = part.data; M = part.matrix_world; Mi = M.inverted(); R3 = M.to_3x3()
    a = Vector(a_local)
    for v in me.vertices:
        h = v.co.dot(a) - base_h
        if h > 2 * band and not lift_mode: continue
        w = M @ v.co
        if lift_mode:
            loc, nor, idx, dist = g.bvh.find_nearest(w)
            if loc is None: continue
            ns = surface_normal(g, idx, loc)
            if ns.dot(n_rigid) < 0: ns = -ns
            v.co = Mi @ (loc + ns * (-embed + h * (R3 @ a).length))
            continue
        hit = surface_hit(g, w - n_rigid * h, n_rigid, 0.3)
        if hit is None: continue
        loc, idx = hit; ns = surface_normal(g, idx, loc)
        if ns.dot(n_rigid) < 0.2: continue
        k = 1.0 if h <= band else max(0.0, 1.0 - (h - band) / band)
        v.co = Mi @ (w.lerp(loc + ns * (h - embed), k))      # offset along the LOCAL normal: thickness kept
    me.update()


def _rec(kind, part, host, **kw):
    r = {'kind': kind, 'part': part.name, 'host': host.name if host is not None else '', 'plan_part': core.part_of(part)}
    if host is not None: r['plan_host'] = core.part_of(host)
    for k, v in kw.items():
        if isinstance(v, Vector): v = [round(x, 6) for x in v]
        elif isinstance(v, (tuple, list)) and v and isinstance(v[0], Vector): v = [[round(x, 6) for x in q] for q in v]
        r[k] = v
    return core.put_rel(r)


def _spec(x):
    """JSON form of an anchor/by spec."""
    if isinstance(x, Vector): return {'point': [round(c, 6) for c in x]}
    if isinstance(x, (tuple, list)) and len(x) == 3 and all(isinstance(c, (int, float)) for c in x):
        return {'point': [float(c) for c in x]}
    if isinstance(x, (tuple, list)) and len(x) == 2 and not isinstance(x[0], (int, float, str)):
        return {'point_normal': [[float(c) for c in x[0]], [float(c) for c in x[1]]]}
    if isinstance(x, (tuple, list)): return list(x)
    return x


def _unspec(x):
    if isinstance(x, dict) and 'point' in x: return Vector(x['point'])
    if isinstance(x, dict) and 'point_normal' in x: return (Vector(x['point_normal'][0]), Vector(x['point_normal'][1]))
    if isinstance(x, list): return tuple(x)
    return x


# ============================================================================================ attach
def attach(part, to, at='top', by=None, embed=None, align=True, up=None, spin_deg=0.0, conform=0.0,
           ref=None, _record=True):
    """Place `part` on host `to`: the part's mounting side (by) goes onto anchor `at` of the host and enters it by
    `embed` (5 mm) at its SHALLOWEST point: on a curved host a flat base sinks until its edges are 5 mm in (no slit).
    embed=None (default): 5 mm, or for a part under 7 mm tall 45 % of its height (>= 2.5 mm: a 5 mm rivet
    head sinks 2.5 mm, not out of sight).
    conform=m bends the part onto the host: everything within m of its base follows the surface (thickness kept),
    the next m fades back to the rigid shape (base plates, saddles, frames and glass on a curved flank).
    Returns the part. Recorded: kind 'attach'."""
    p = obj(part); h = obj(to)
    if p == h: raise ValueError('kit3d.attach: a part cannot attach to itself')
    if p.type == 'MESH' and is_frozen(p): unfreeze(p)      # placed again by its script: by= is read in the frame it was built in
    if by is None: by = _default_by(at)
    if conform > 0 and p.type == 'MESH':          # bend needs vertices: n-gon caps and long edges stay flat chords
        if bpy.data.meshes.get('kit3d_src:' + p.name): _src_mesh(p, False)
        else: _subdivide_long(p.data, bend_edge(core.local_verts(p))); _src_mesh(p, True)
    g = core.geo(h); s, n, idx = resolve(h, at)
    lv, lt = core.local_geo(p); scale = _scale_of(p)
    pb, a = _part_side(p, by, lv)
    if align: R = _rotation(a, n, up, spin_deg, ref)
    else:
        R = p.matrix_world.to_3x3().normalized(); n = (R @ a).normalized()
    foot, base_h, ext = _footprint(lv * np.array(scale), a, tris=lt)
    auto = embed is None
    foot = foot / np.array(scale); embed = auto_embed(embed, ext)
    if auto:                      # a thin host wall: keep the part's back >= 2.5 mm off the wall's far side (z-fight)
        wl = wall_below(g, s, n)
        if wl is not None and embed > wl - const.COPLANAR - 0.0005:
            embed = max(const.ENTRY_MIN + 0.0005, round(wl - const.COPLANAR - 0.0005, 5))
    reach = max(0.1, 2 * ext * max(scale), 4 * abs(embed))
    t, hit, tot = _fit(p, g, s, n, R, pb, foot, scale, embed, reach)
    if hit == 0: raise ValueError(f'kit3d.attach: {p.name} footprint is not over {h.name} at {at}')
    _set_world(p, R, t, scale)
    if conform > 0 and p.type == 'MESH':
        _conform(p, g, n, a, base_h, conform, embed); core.update()
    if _record:
        _rec('attach', p, h, at=_spec(at), by=_spec(by), embed=embed, align=align, up=_spec(up) if up is not None else None,
             spin_deg=spin_deg, conform=conform, ref=_spec(ref) if ref is not None else None,
             a=[round(c, 6) for c in a], s=s, n=n, coverage=round(hit / max(1, tot), 3))
    return p


# ============================================================================================ into / free / root
def into(part, host, note=''):
    """Declare that `part` (placed by its own construction: built from the same outline, a frame on its door ...)
    enters `host`. Nothing moves; check() measures it: they must interpenetrate by >= 2 mm (ENTRY_MIN)."""
    p = obj(part); h = obj(host)
    _rec('into', p, h, note=note)
    return p


def free(part, reason):
    """Declare a part that is held by nothing on purpose (a bird, a hanging banner the far version drops ...).
    The reason goes into parts.json and the hand-back. check() lists free parts but does not fail them."""
    p = obj(part); p['kit3d_free'] = reason
    _rec('free', p, None, reason=reason)
    return p


def root(part, reason='root'):
    """The part everything else hangs on (the car body, a building's slab). Same as free() with a root reason."""
    p = obj(part); p['kit3d_root'] = reason
    _rec('root', p, None, reason=reason)
    return p


# ============================================================================================ span
def _section(section, segs):
    from .shapes import circle
    if isinstance(section, (int, float)): return circle(float(section), segs or core.lod_segments(16)), float(section)
    if isinstance(section, (tuple, list)) and section and section[0] == 'rect':
        w, h = section[1], section[2]; return [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)], max(w, h) / 2
    pts = [tuple(q) for q in section]
    return pts, max(math.hypot(*q) for q in pts)


def _end_extend(g, P0, P1, prof_world_fn, embed, reach):
    """Distance to move end P0 along (P0 - P1) so every point of the end section is `embed` inside host g."""
    d = (P0 - P1).normalized(); ds = []
    for q in prof_world_fn(P0, d):
        x = depth_along(g, q, -d, reach)
        if x is not None: ds.append(x)
    if not ds: return None
    return embed - min(ds)


def span(name, a, b, section=0.01, mat=None, segs=None, form='straight', out=0.06, via=None, bend_r=None,
         embed=const.EMBED, up=None, caps=True, coil=None, _replace=None):
    """A member between two hosts, built from its ends: a rail between two posts, a strut, a rod, a cable, a hose,
    a grab handle on stand-offs. a, b = (host, anchor). section = radius (round), ('rect', w, h) or a 2D outline.
    form 'straight' | 'standoff' (out from each surface by `out`, along, back in: grab handles) | 'via' (through
    `via` world points) | 'coil' (coil=(radius, turns): a spring between its seats). Each end is extended or
    trimmed so its whole section enters its host by `embed`. Returns the new object. Recorded: kind 'span'."""
    from .shapes import sweep, round_path, frames_along
    ha, aa = obj(a[0]), a[1]; hb, ab = obj(b[0]), b[1]
    pa, na, _ = resolve(ha, aa); pb, nb, _ = resolve(hb, ab)
    prof, rad = _section(section, segs)
    if form == 'standoff':
        pts = [pa, pa + na * out, pb + nb * out, pb]
    elif form == 'via':
        pts = [pa] + [vec(q) for q in (via or [])] + [pb]
    elif form == 'coil':
        R_, turns = coil; ax = (pb - pa); L = ax.length; q = ax.normalized().to_track_quat('Z', 'Y').to_matrix()
        turns = max(1, round(turns)); N = max(8, int(turns * core.lod_segments(16)))
        helix = []
        for i in range(N + 1):
            t = i / N; ang = 2 * math.pi * turns * t
            helix.append(pa + q @ Vector((R_ * math.cos(ang), R_ * math.sin(ang), L * (0.06 + 0.88 * t))))
        # the wire's ends drop straight onto the seats (along the axis), so they enter them end-on
        pts = [pa + q @ Vector((R_, 0, 0))] + helix + [pb + q @ Vector((R_, 0, 0))]
    else:
        pts = [pa, pb]
    if form in ('standoff', 'via') and len(pts) > 2:
        pts = round_path(pts, bend_r if bend_r is not None else max(2.5 * rad, 0.02))
    ga, gb = core.geo(ha), core.geo(hb); reach = max(0.1, 4 * rad + 2 * embed)

    def ring(P, d):
        t_ = d.normalized(); u = t_.orthogonal().normalized(); w = t_.cross(u)
        return [P + u * x + w * y for (x, y) in prof]
    for _ in range(2):
        e0 = _end_extend(ga, pts[0], pts[1], ring, embed, reach)
        e1 = _end_extend(gb, pts[-1], pts[-2], ring, embed, reach)
        if e0 is None or e1 is None:
            raise ValueError(f'kit3d.span {name}: end {"a" if e0 is None else "b"} does not meet its host '
                             f'({(ha if e0 is None else hb).name}) along the member')
        pts[0] = pts[0] + (pts[0] - pts[1]).normalized() * e0
        pts[-1] = pts[-1] + (pts[-1] - pts[-2]).normalized() * e1
    if _replace is None:
        o = sweep(name, pts, prof, mat, True, caps, True, up, miter=True)
    else:
        # a replay: the member is rebuilt INTO the object that is there, which keeps its name, plan part, collections,
        # modifiers and materials. (A new object took the part of whatever step was running and, when the old name
        # was still in use, came back as '<name>.002': the next run of its own script then built a second bar.)
        o = _replace; st = core.S().get('step'); made = list(st['created']) if st else None
        tmp = sweep(name + '.kit3d_tmp', pts, prof, None, True, caps, True, up, miter=True)
        if st is not None: st['created'] = made
        new = tmp.data; old = o.data
        for m in old.materials: new.materials.append(m)
        bpy.data.objects.remove(tmp, do_unlink=True)
        o.data = new; new.name = old.name if old.users == 0 else o.name
        if old.users == 0: bpy.data.meshes.remove(old)
        o.matrix_world = Matrix.Identity(4); core.update()
    _rec('span', o, ha, host_b=hb.name, plan_host_b=core.part_of(hb), a=_spec(aa), b=_spec(ab),
         section=_spec(section) if not isinstance(section, (int, float)) else section, segs=segs, form=form, out=out,
         via=[list(map(float, v)) for v in (via or [])], bend_r=bend_r, embed=embed, coil=list(coil) if coil else None,
         ring=len(prof), rings=len(pts), caps=caps, up=_spec(up) if up is not None else None,
         mat=mat.name if mat is not None else (o.data.materials[0].name if o.data.materials and o.data.materials[0] else None))
    return o


# ============================================================================================ lay
def bend_edge(lv):
    """Longest edge allowed before bending a part: a fifth of its largest size, 4 mm .. MAX_EDGE (5 cm). A 43 mm
    louvre on a 0.1 m radius hood with 5 cm edges stays a flat chord 2.2 mm deep and pokes through a 4 mm wall."""
    ext = float((lv.max(0) - lv.min(0)).max()) if len(lv) else const.MAX_EDGE
    return min(const.MAX_EDGE, max(0.004, 0.2 * ext))


def _subdivide_long(me, max_edge):
    """Split until no edge is longer than max_edge, n-gons first triangulated (a bent n-gon cap triangulates into
    chords that cut through the part: a 0.3 m cap on R 1.4 m sags 8 mm, through a 4 mm plate)."""
    bm = bmesh.new(); bm.from_mesh(me)
    ng = [f for f in bm.faces if len(f.verts) > 4]
    if ng: bmesh.ops.triangulate(bm, faces=ng, quad_method='BEAUTY', ngon_method='BEAUTY')
    for _ in range(8):
        long_ = [e for e in bm.edges if e.calc_length() > max_edge]
        if not long_: break
        bmesh.ops.subdivide_edges(bm, edges=long_, cuts=1, use_grid_fill=True)
    # all triangles: a bent quad is not flat, and its two possible diagonals differ by its twist (0.2 mm for 5 cm on
    # R 1.4 m); triangles fix the surface so plug, cutter, Boolean pocket and the check all see the same one
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 3], quad_method='FIXED', ngon_method='BEAUTY')
    bm.to_mesh(me); bm.free(); me.update()


def lay(layer, on_, at='+y', lift=const.LIFT, cut=False, up=None, spin_deg=0.0, depth=None, max_edge=None,
        _record=True):
    """Lay a layer (decal, stripe, plate, lettering: built facing +Z in its own frame) onto host `on_` at `at`,
    following a curved surface. lift (6 mm): the layer's back stands that far off the surface everywhere.
    cut=True instead sinks it as a solid inlay (depth, default LIFT) into a pocket cut in the host (a live Boolean
    modifier 'kit3d_cut:<layer>' + hidden cutter), top flush with the surface: no base left under it to fight with.
    Recorded: kind 'lay'."""
    p = obj(layer); h = obj(on_); thick = None
    if p.type != 'MESH': raise ValueError('kit3d.lay: the layer must be a mesh')
    if is_frozen(p): unfreeze(p)
    if bpy.data.meshes.get('kit3d_src:' + p.name): _src_mesh(p, False)
    else:
        _subdivide_long(p.data, max_edge or bend_edge(core.local_verts(p))); _src_mesh(p, True)
    md = h.modifiers.get('kit3d_cut:' + p.name)
    if md is not None: md.show_viewport = False; core.update()
    try:
        g = core.geo(h, cache=md is None); s, n, idx = resolve(h, at) if md is None else _resolve_nocache(h, at)
        lv = core.local_verts(p); scale = _scale_of(p)
        pb, a = _part_side(p, '-z', lv)
        R = _rotation(a, n, up, spin_deg)
        t = s - R @ (Matrix.Diagonal(scale) @ pb) + (n * lift if not cut else Vector())
        _set_world(p, R, t, scale)
        if not cut:      # heights are counted from the layer's BACK (its lowest z), not from z = 0: a text mesh is
            _conform(p, g, n, a, float(lv[:, 2].min()), 0.0, -lift, lift_mode=True)      # centred on z and stood 3.5 mm off
        else:
            thick = _inlay(p, h, g, depth if depth is not None else const.LIFT)
    finally:
        if md is not None: md.show_viewport = True
    core.update()
    if _record:
        _rec('lay', p, h, at=_spec(at), lift=0.0 if cut else lift, cut=cut, depth=depth, up=_spec(up) if up is not None else None,
             spin_deg=spin_deg, a=[0, 0, 1], s=s, n=n, thick=thick)
    return p


def _resolve_nocache(h, at):
    core.clear_cache(); return resolve(h, at)


def _slab(top, bot, faces):
    """Closed solid between two point sheets with the same faces (top, bottom: world points)."""
    bm = bmesh.new(); T = [bm.verts.new(q) for q in top]; B = [bm.verts.new(q) for q in bot]
    cnt = {}
    for f in faces:
        bm.faces.new([T[i] for i in f]); bm.faces.new([B[i] for i in reversed(f)])
        for k in range(len(f)):
            e = (f[k], f[(k + 1) % len(f)]); cnt[e] = cnt.get(e, 0) + 1
    for (i, j) in cnt:
        if (j, i) not in cnt:
            try:
                bm.faces.new((T[j], T[i], B[i], B[j]))
            except ValueError:
                pass
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def _inlay(p, h, g, d):
    """Make the placed layer p an inlay plug and cut its pocket in host h. A flat layer is first given thickness
    d - CUT_GAP; a solid layer (a plate) keeps its own thickness t. The plug is bent onto the surface with its top
    flush (height h above its base -> surface + normal * (h - t)); the cutter is the plug grown by CUT_GAP sideways
    and below, reaching d/2 above the surface, applied as a live Boolean DIFFERENCE on h. Returns t."""
    src = p.data; M = p.matrix_world.copy(); Mi = M.inverted()
    co = np.empty(len(src.vertices) * 3); src.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
    t = float(co[:, 2].max() - co[:, 2].min())
    if t < 1e-5:                                   # a sheet: extrude it into a slab under itself
        faces = [list(pl.vertices) for pl in src.polygons]
        bm = _slab([Vector(c) for c in co], [Vector((c[0], c[1], c[2] - (d - const.CUT_GAP))) for c in co], faces)
        from . import uv as _uv
        uvl = _uv.layer(bm); _uv.box(bm, uvl=uvl)
        if src.uv_layers:
            su = src.uv_layers.active.data
            for fi, f in enumerate(bm.faces):
                if fi % 2 == 0 and fi // 2 < len(src.polygons):
                    for kk, l in enumerate(f.loops): l[uvl].uv = tuple(su[src.polygons[fi // 2].loop_indices[kk]].uv)
        me = bpy.data.meshes.new(p.name); bm.to_mesh(me); bm.free()
        for m in src.materials: me.materials.append(m)
        p.data = me
        if src.users == 0 and not src.use_fake_user: bpy.data.meshes.remove(src)
        src = me; co = np.empty(len(src.vertices) * 3); src.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
        t = d - const.CUT_GAP
    z0, z1 = float(co[:, 2].min()), float(co[:, 2].max())
    cx, cy = float(co[:, 0].mean()), float(co[:, 1].mean())
    wx = float(np.abs(co[:, 0] - cx).max()) or 1.0; wy = float(np.abs(co[:, 1] - cy).max()) or 1.0

    def bent(q, hgt, below):
        w = M @ Vector((q[0], q[1], z0)); loc, nor, idx, dist = g.bvh.find_nearest(w)
        ns = surface_normal(g, idx, loc)
        return loc + ns * (hgt - below)
    for v in src.vertices:
        v.co = Mi @ bent(v.co, v.co.z - z0, t)
    src.update()
    cme = src.copy(); cme.name = 'kit3d_cut:' + p.name; cme.materials.clear()
    for v, c in zip(cme.vertices, co):
        hgt = c[2] - z0; up = (hgt / t) if t > 0 else 1.0
        q = (cx + (c[0] - cx) * (wx + const.CUT_GAP) / wx, cy + (c[1] - cy) * (wy + const.CUT_GAP) / wy)
        v.co = Mi @ bent(q, -const.CUT_GAP + up * (t + const.CUT_GAP + d * 0.5), t)
    cme.update()
    ct = bpy.data.objects.get('kit3d_cut:' + p.name)
    if ct is None:
        ct = bpy.data.objects.new('kit3d_cut:' + p.name, cme); core.current_coll().objects.link(ct)
    else:
        old = ct.data; ct.data = cme
        if old.users == 0: bpy.data.meshes.remove(old)
    ct.matrix_world = M; ct.hide_render = True; ct.display_type = 'WIRE'; ct['kit3d_cutter'] = h.name; ct.hide_set(True)
    m = h.modifiers.get('kit3d_cut:' + p.name) or h.modifiers.new('kit3d_cut:' + p.name, 'BOOLEAN')
    m.operation = 'DIFFERENCE'; m.solver = 'EXACT'; m.object = ct
    return t


# ============================================================================================ scatter
def _uv_grid(me, count):
    """(columns, step u, step v) of the grid that gives each of `count` copies of mesh `me` its own UV place."""
    uvl = me.uv_layers.active if me.uv_layers else None
    if uvl is None or not len(uvl.data) or count < 2: return 0, 0.0, 0.0
    u = np.empty(len(uvl.data) * 2, np.float32); uvl.data.foreach_get('uv', u); u = u.reshape(-1, 2)
    w, h = (float(x) for x in (u.max(0) - u.min(0)))
    m = max(0.002, 0.1 * max(w, h))
    return max(1, int(math.ceil(math.sqrt(count)))), w + m, h + m


def scatter(name, proto, host, points, by='-z', embed=None, up=None, spin_deg=0.0, mat=None):
    """Many small copies of `proto` (rivets, bolts, studs) each attached to `host` at its own anchor in `points`
    (any anchor form), merged into ONE object `name`. Each copy is fitted and later measured on its own.
    proto is deleted. Recorded: kind 'scatter' (items: vertex range + out axis per copy)."""
    pr = obj(proto); h = obj(host); g = core.geo(h)
    lv, lt = core.local_geo(pr); pb, a = _part_side(pr, by, lv)
    foot, base_h, ext = _footprint(lv, a, tris=lt); reach = max(0.1, 4 * ext); embed = auto_embed(embed, ext)
    src = pr.data; bm = bmesh.new(); items = []
    one = Vector((1, 1, 1))
    # every copy gets its own place in UV space (a grid of the proto's UV box + 10 % margin, metres kept), so the
    # copies never share texture space: the proto's UVs on all of them fail kit3d's own uv_overlap check
    cols, du, dv = _uv_grid(src, len(points))
    for i, at in enumerate(points):
        s, n, _ = resolve(h, at); R = _rotation(a, n, up, spin_deg)
        t, hit, tot = _fit(pr, g, s, n, R, pb, foot, one, embed, reach)
        M = Matrix.Translation(t) @ R.to_4x4()
        tmp = src.copy(); tmp.transform(M); start = len(bm.verts); f0 = len(bm.faces)
        bm.from_mesh(tmp); bpy.data.meshes.remove(tmp)
        uvl = bm.loops.layers.uv.active
        if uvl is not None and i and cols:
            ou, ov = (i % cols) * du, (i // cols) * dv
            bm.faces.ensure_lookup_table()
            for fi in range(f0, len(bm.faces)):
                for l in bm.faces[fi].loops: l[uvl].uv = (l[uvl].uv[0] + ou, l[uvl].uv[1] + ov)
        items.append([start, len(bm.verts) - start, [round(c, 6) for c in n], [round(c, 6) for c in s]])
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for m in (src.materials if mat is None else [mat]): me.materials.append(m)
    for pl in me.polygons: pl.use_smooth = src.polygons[0].use_smooth if len(src.polygons) else False
    o = core.new_object(name, me)
    bpy.data.objects.remove(pr, do_unlink=True)
    _rec('scatter', o, h, at=[_spec(q) for q in points], by=_spec(by), embed=embed, a=[round(c, 6) for c in a],
         items=items, base_h=float(base_h))
    return o


# ============================================================================================ mirror / array / replay
def _mname(n):
    for a, b in (('.L', '.R'), ('_L', '_R'), ('.left', '.right'), ('_left', '_right')):
        if n.endswith(a): return n[:-len(a)] + b
        if n.endswith(b): return n[:-len(b)] + a
    return n + '.M'


def _refl(axis):
    i = 'xyz'.index(axis.lower()[-1]); m = Matrix.Identity(3); m[i][i] = -1; return m


def _rels_of(name):
    return [r for r in core.rels().values() if r['part'] == name]


def mirror(parts, axis='y', reflect=True, names=None):
    """Mirrored copies of parts across the world plane through 0 normal to `axis`, WITH their relations: each copy is
    re-attached to its (mirrored, if copied too, else the same) host at the mirrored anchor, so it is fitted to the
    real surface on the other side. reflect=False keeps lettering and decals readable (no mirror image).
    names: the copies' names, as {original name: new name} or as a list in the order of `parts` (a string for one
    part); default: .L <-> .R, _left <-> _right, else '<name>.M'.
    Returns {original name: copy}."""
    ps = [obj(p) for p in (parts if isinstance(parts, (list, tuple)) else [parts])]
    if isinstance(names, str): names = [names]
    if isinstance(names, (list, tuple)):
        if len(names) != len(ps): raise ValueError(f'kit3d.mirror: names has {len(names)} entries for {len(ps)} parts (one per part, or a dict {{original: new}})')
        names = {p.name: n for p, n in zip(ps, names)}
    elif names is not None and not isinstance(names, dict):
        raise TypeError('kit3d.mirror: names is a list in the order of parts, or a dict {original name: new name}')
    fz = [p.name for p in ps if is_frozen(p)]
    if fz:                                  # copy the parts as they were built, then freeze originals and copies
        with _thawed(fz): out = mirror(ps, axis, reflect, names)
        freeze([out[n] for n in fz if n in out]); return out
    W = _refl(axis); W4 = W.to_4x4(); out = {}; group = {p.name for p in ps}
    names = names or {}
    # hosts first
    order = []; rest = list(ps)
    while rest:
        moved = False
        for p in list(rest):
            hs = {r.get('host') for r in _rels_of(p.name)} | {r.get('host_b') for r in _rels_of(p.name)}
            if not (hs & {q.name for q in rest if q is not p}):
                order.append(p); rest.remove(p); moved = True
        if not moved: order += rest; break
    for p in order:
        rs = _rels_of(p.name); nm = names.get(p.name) or _mname(p.name)
        old = bpy.data.objects.get(nm)
        if old is not None and old is not p:
            core.drop_rels_of([nm]); bpy.data.objects.remove(old, do_unlink=True)
        kinds = {r['kind'] for r in rs}
        if 'span' in kinds:
            r = next(r for r in rs if r['kind'] == 'span')
            ha = out.get(r['host']).name if r['host'] in out else r['host']
            hb = out.get(r['host_b']).name if r['host_b'] in out else r['host_b']
            pa, na, _ = resolve(r['host'], _unspec(r['a'])); pb_, nb, _ = resolve(r['host_b'], _unspec(r['b']))
            mat = p.data.materials[0] if p.data.materials else None
            c = span(nm, (ha, W @ pa), (hb, W @ pb_), _unspec(r['section']) if not isinstance(r['section'], (int, float)) else r['section'],
                     mat, r.get('segs'), r.get('form', 'straight'), r.get('out', 0.06),
                     [W @ Vector(v) for v in r.get('via') or []], r.get('bend_r'), r.get('embed', const.EMBED),
                     coil=tuple(r['coil']) if r.get('coil') else None)
            out[p.name] = c; continue
        c = p.copy(); c.name = nm
        if p.data is not None: c.data = p.data.copy(); c.data.name = nm
        for col in p.users_collection: col.objects.link(c)
        for k in ('kit3d_free', 'kit3d_root'):
            if k in p: c[k] = p[k]
        out[p.name] = c
        rattach = next((r for r in rs if r['kind'] in ('attach', 'lay')), None)
        if rattach is not None:
            a = Vector(rattach['a']); host = out[rattach['host']].name if rattach['host'] in out else rattach['host']
            s = Vector(rattach['s'])
            if c.type == 'MESH':
                src = bpy.data.meshes.get('kit3d_src:' + p.name)
                if src is not None:
                    c.data = src.copy(); c.data.name = nm
                    m2 = src.copy(); m2.name = 'kit3d_src:' + nm; m2.use_fake_user = True
                    if reflect and rattach['kind'] == 'attach':
                        m2.transform(_reflect_along(a).to_4x4()); m2.flip_normals()
                if reflect and rattach['kind'] == 'attach':
                    c.data.transform(_reflect_along(a).to_4x4()); c.data.flip_normals()
            by = _unspec(rattach.get('by'))
            if reflect and rattach['kind'] == 'attach':
                by = OPP[by] if isinstance(by, str) and by in OPP else (
                    (_reflect_along(a) @ Vector(by[0]), _reflect_along(a) @ (-Vector(by[1]))) if isinstance(by, tuple) else by)
            up = _unspec(rattach.get('up')); up = (W @ Vector(up)) if up is not None else None
            if rattach['kind'] == 'attach':
                attach(c, host, W @ s, by=by, embed=rattach.get('embed', const.EMBED), align=rattach.get('align', True),
                       up=up, spin_deg=-rattach.get('spin_deg', 0.0), conform=rattach.get('conform', 0.0))
            else:
                lay(c, host, W @ s, lift=rattach.get('lift', const.LIFT) or const.LIFT, cut=rattach.get('cut', False),
                    up=up, spin_deg=-rattach.get('spin_deg', 0.0), depth=rattach.get('depth'))
        else:
            # placed by construction (into / free / root / scatter): reflect the geometry in place
            M = p.matrix_world; R3 = M.to_3x3().normalized(); l = R3.inverted() @ Vector([1 if q == axis.lower()[-1] else 0 for q in 'xyz'])
            if c.type == 'MESH':
                c.data.transform(_reflect_along(l).to_4x4()); c.data.flip_normals()
            c.matrix_world = Matrix.Translation(W @ M.translation) @ M.to_3x3().to_4x4()
            core.update()
            for r in rs:
                if r['kind'] == 'into':
                    into(c, out[r['host']].name if r['host'] in out else r['host'], r.get('note', ''))
                elif r['kind'] == 'free':
                    free(c, r.get('reason', ''))
                elif r['kind'] == 'root':
                    root(c, r.get('reason', 'root'))
                elif r['kind'] == 'scatter':
                    rr = dict(r); rr['part'] = c.name; rr['host'] = out[r['host']].name if r['host'] in out else r['host']
                    rr['items'] = [[it[0], it[1], list(W @ Vector(it[2])), list(W @ Vector(it[3]))] for it in r['items']]
                    core.put_rel(rr)
    return out


def _reflect_along(a):
    a = Vector(a).normalized(); return Matrix.Identity(3) - 2 * Matrix(((a.x * a.x, a.x * a.y, a.x * a.z), (a.y * a.x, a.y * a.y, a.y * a.z), (a.z * a.x, a.z * a.y, a.z * a.z)))


def array(part, count=None, step=None, points=None, names=None):
    """Copies of an attached or laid part, each re-attached at its own anchor: anchor + i * step (world metres) for
    i in 1..count-1, or at each of `points`. Copies share the mesh. Returns the list of copies."""
    p = obj(part); rs = [r for r in _rels_of(p.name) if r['kind'] in ('attach', 'lay')]
    if not rs: raise ValueError(f'kit3d.array: {p.name} has no attach/lay relation to repeat')
    if is_frozen(p):
        with _thawed([p.name]): out = array(p, count, step, points, names)
        freeze(out); return out
    r = rs[0]; s = Vector(r['s'])
    pts = [s + vec(step) * i for i in range(1, count)] if points is None else [vec(q) for q in points]
    out = []
    for i, q in enumerate(pts):
        nm = (names[i] if names else f'{p.name}.{i + 1:03d}')
        old = bpy.data.objects.get(nm)
        if old is not None: core.drop_rels_of([nm]); bpy.data.objects.remove(old, do_unlink=True)
        c = p.copy(); c.name = nm
        src = bpy.data.meshes.get('kit3d_src:' + p.name)
        if src is not None and c.type == 'MESH':
            c.data = src.copy(); c.data.name = nm
            m2 = src.copy(); m2.name = 'kit3d_src:' + nm; m2.use_fake_user = True
        for col in p.users_collection: col.objects.link(c)
        if r['kind'] == 'attach':
            attach(c, r['host'], q, by=_unspec(r.get('by')), embed=r.get('embed', const.EMBED), align=r.get('align', True),
                   up=_unspec(r.get('up')), spin_deg=r.get('spin_deg', 0.0), conform=r.get('conform', 0.0))
        else:
            lay(c, r['host'], q, lift=r.get('lift') or const.LIFT, cut=r.get('cut', False), up=_unspec(r.get('up')),
                spin_deg=r.get('spin_deg', 0.0), depth=r.get('depth'))
        out.append(c)
    return out


def reattach(parts=None, hosts=None):
    """Replay recorded attach / lay / span relations against the hosts as they are NOW (after a host changed):
    anchors are re-resolved on the new surface. parts: names (default all); hosts: only relations on these hosts.
    Returns the names re-placed."""
    done = []
    for k, r in sorted(core.rels().items()):
        if parts is not None and r['part'] not in parts and r.get('plan_part') not in parts: continue
        if hosts is not None and r.get('host') not in hosts and r.get('host_b') not in hosts: continue
        if bpy.data.objects.get(r['part']) is None: continue
        if r['kind'] in ('attach', 'lay') and r.get('frozen'):
            with _thawed([r['part']]): reattach(parts=[r['part']], hosts=hosts)
            done.append(r['part']); continue
        if r['kind'] == 'attach':
            attach(r['part'], r['host'], _unspec(r['at']), by=_unspec(r.get('by')), embed=r.get('embed', const.EMBED),
                   align=r.get('align', True), up=_unspec(r.get('up')), spin_deg=r.get('spin_deg', 0.0),
                   conform=r.get('conform', 0.0), ref=_unspec(r.get('ref')))
        elif r['kind'] == 'lay':
            lay(r['part'], r['host'], _unspec(r['at']), lift=r.get('lift') or const.LIFT, cut=r.get('cut', False),
                up=_unspec(r.get('up')), spin_deg=r.get('spin_deg', 0.0), depth=r.get('depth'))
        elif r['kind'] == 'span':
            o = obj(r['part'])
            span(o.name, (r['host'], _unspec(r['a'])), (r['host_b'], _unspec(r['b'])),
                 r['section'] if isinstance(r['section'], (int, float)) else _unspec(r['section']), None, r.get('segs'),
                 r.get('form', 'straight'), r.get('out', 0.06), r.get('via'), r.get('bend_r'), r.get('embed', const.EMBED),
                 up=_unspec(r.get('up')), caps=r.get('caps', True), coil=tuple(r['coil']) if r.get('coil') else None,
                 _replace=o)
        else:
            continue
        done.append(r['part'])
    return done


def reattach_chain(changed, limit=20):
    """Re-attach everything that hangs on `changed`, then what hangs on those, level by level (a vent base on the
    roof, then the hood on the base). Returns the names re-placed."""
    done = []; frontier = set(changed); seen = set(changed)
    for _ in range(limit):
        deps = [d for d in dependents(frontier) if d not in seen]
        if not deps: break
        reattach(parts=deps); done += deps; seen |= set(deps); frontier = set(deps)
    return done


def dependents(names):
    """Parts whose relation's host is one of `names` (to re-attach after those hosts were rebuilt)."""
    names = set(names)
    return sorted({r['part'] for r in core.rels().values() if r.get('host') in names or r.get('host_b') in names})


# ============================================================================================ adopt / freeze
def adopt(objs, part=None, host=None, note=''):
    """Take objects that kit3d did not make (the kept objects of an asset being UPGRADED, an appended library part)
    into plan part `part` (default: the part of the running step / begin()). objs: an object, a name, a list, or a
    {name: part} dict. Each gets o['kit3d_part'] = part, relations already recorded under its bare name move to the
    part, and it counts as touched by the running step, so the step measures it. host= also declares into(obj, host).
    It does not move anything and survives begin(part) only if you adopt it again (begin clears what the part made:
    adopt kept objects in the step that loads them, into parts whose scripts do not rebuild them). Returns the objects."""
    if isinstance(objs, dict): pairs = [(obj(n), p) for n, p in objs.items()]
    else:
        pp = part or (core.S().get('step') or {}).get('part') or core.S().get('part')
        if not pp: raise ValueError('kit3d.adopt: give part= (no begin() or step is running)')
        pairs = [(obj(x), pp) for x in (objs if isinstance(objs, (list, tuple, set)) else [objs])]
    d = core.rels(); ch = False; st = core.S().get('step')
    for o, pp in pairs:
        o['kit3d_part'] = pp
        for r in d.values():
            if r['part'] == o.name and r.get('plan_part') != pp: r['plan_part'] = pp; ch = True
            if r.get('host') == o.name and r.get('plan_host') != pp: r['plan_host'] = pp; ch = True
            if r.get('host_b') == o.name and r.get('plan_host_b') != pp: r['plan_host_b'] = pp; ch = True
        if st is not None and o.name not in st.setdefault('created', []): st['created'].append(o.name)
    if ch: core.save_rels(d)
    if host is not None:
        for o, _ in pairs: into(o, host, note)
    return [o for o, _ in pairs]


def is_frozen(part):
    """Was freeze() applied to this part?"""
    return 'kit3d_frame' in obj(part)


def _apply_matrix(o, M):
    """Move matrix M into the mesh of o (o then sits at its old matrix @ inverse(M)); children keep their place."""
    kids = [(c, c.matrix_world.copy()) for c in o.children]
    if o.data.users > 1: o.data = o.data.copy()          # array copies share one mesh: this one gets its own
    o.data.transform(M)
    if M.to_3x3().determinant() < 0: o.data.flip_normals()
    o.data.update()
    o.matrix_world = o.matrix_world @ M.inverted(); core.update()
    for c, mw in kids: c.matrix_world = mw
    if kids: core.update()


def freeze(parts=None):
    """Apply the placement of parts into their meshes, so each object sits at the origin with no rotation or scale and
    its OBJECT coordinates are the asset's own (x along, z up from the rail or floor). The shared shader kinds read
    object coordinates (grime by height = object Z, brushing along object X, the wear mask's panel cells): a part
    left in the frame attach() gave it gets road film all over and a turned brush. Call it once the part is placed
    (after attach / lay / mirror / array; span, scatter and into parts are built in the asset's frame already).
    parts: objects / names / plan part names (default: every object of the current part).
    Nothing else changes for the builder: the relation stays measured (its mounting axis is rewritten into the new
    frame), the applied matrix is kept on the object (o['kit3d_frame']), so reattach(), mirror() and array() thaw the
    part, do their work and freeze it again, and anchors on a frozen host (on('+y', x=..), 'top') are still read in
    the frame the host was BUILT in: scripts of the parts that hang on it need no change. Never apply a transform
    by hand: the relation keeps the old axis and check() measures along the wrong one. Returns the objects frozen."""
    if parts is None:
        cur = core.S().get('part'); sel = [o for o in bpy.data.objects if cur and o.get('kit3d_part') == cur]
    else:
        sel = []
        for x in (parts if isinstance(parts, (list, tuple, set)) else [parts]):
            if isinstance(x, bpy.types.Object) or bpy.data.objects.get(x) is not None: sel.append(obj(x))
            else:
                got = [o for o in bpy.data.objects if o.get('kit3d_part') == x]
                if not got: raise KeyError(f'kit3d.freeze: no object or plan part {x!r}')
                sel += got
    core.update(); done = []; I = Matrix.Identity(4)
    for o in sel:
        if o.type != 'MESH' or o.library is not None or o.name.startswith(('kit3d_cut:', 'anchor.')): continue
        M = o.matrix_world.copy()
        if all(abs(M[i][j] - I[i][j]) < 1e-9 for i in range(4) for j in range(4)): continue
        d = core.rels(); R3 = M.to_3x3(); ch = False
        for r in d.values():                       # this part's own attach / lay: the mounting axis in the new frame
            if r['part'] != o.name or r['kind'] not in ('attach', 'lay'): continue
            if 'a_local' not in r: r['a_local'] = r['a']
            r['a'] = [round(c, 6) for c in (R3 @ Vector(r['a'])).normalized()]; r['frozen'] = True; ch = True
        if ch: core.save_rels(d)
        prev = frame_of(o); F = M @ prev if prev is not None else M
        _apply_matrix(o, M); o['kit3d_frame'] = [x for row in F for x in row]; done.append(o)
    core.clear_cache()
    return done


def unfreeze(parts):
    """Undo freeze(): the mesh goes back into the frame the part was built in and the object gets the matrix it had.
    (reattach / mirror / array do this themselves.) Returns the names thawed."""
    out = []
    for x in (parts if isinstance(parts, (list, tuple, set)) else [parts]):
        o = obj(x); F = frame_of(o)
        if F is None: continue
        d = core.rels(); ch = False
        for r in d.values():
            if r['part'] == o.name and r.get('frozen'):
                r.pop('frozen'); r['a'] = r.pop('a_local', r['a']); ch = True
        if ch: core.save_rels(d)
        del o['kit3d_frame']
        _apply_matrix(o, F.inverted())           # the object is left at (its matrix now) @ F: F, after a freeze()
        out.append(o.name)
    if out: core.clear_cache()
    return out


class _thawed:
    """with _thawed(names): the frozen ones among names are in their built frames inside, frozen again after."""
    def __init__(self, names): self.names = [n for n in names if is_frozen(n)]
    def __enter__(self): self.done = unfreeze(self.names); return self
    def __exit__(self, *a):
        freeze([n for n in self.done if bpy.data.objects.get(n) is not None]); return False
