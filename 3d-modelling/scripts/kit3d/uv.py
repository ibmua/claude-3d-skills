"""UVs made at creation (every kit3d primitive has a real UV map, F4) and the UV checks.

All UVs are in METRES of surface, so an image tile of `tile_m` metres reads the same on every part (material Mapping
scale = 1 / tile_m) and texel density is even. Faces never share texture space inside one mesh: box projection puts
each of the six directions in its own 10 m band, solidify() moves the inner skin to its own band (the a car white-steel
fault: an inner skin with the outer skin's UVs baked over it, last write wins).
"""
import importlib.util, math, os
import bmesh
import numpy as np
from mathutils import Vector

BAND = 10.0        # m between the UV bands of box directions / inner skins


def layer(bm, name='UVMap'):
    return bm.loops.layers.uv.get(name) or bm.loops.layers.uv.new(name)


def box(bm, faces=None, band=True, uvl=None):
    """Box projection in metres: each face onto the plane of its dominant normal axis, the +/- directions of each axis
    in separate bands (no duplicate UVs between opposite faces), u running so that no side is mirrored."""
    uvl = uvl or layer(bm)
    for f in (faces if faces is not None else bm.faces):
        n = f.normal; ax = max(range(3), key=lambda i: abs(n[i])); s = 1.0 if n[ax] >= 0 else -1.0
        d = ax * 2 + (0 if s > 0 else 1)
        off = d * BAND if band else 0.0
        for l in f.loops:
            co = l.vert.co
            if ax == 0: u, v = s * co.y, co.z
            elif ax == 1: u, v = -s * co.x, co.z
            else: u, v = s * co.x, co.y
            l[uvl].uv = (u + off, v)
    return uvl


def planar(bm, axis='Z', faces=None, uvl=None, offset=(0.0, 0.0)):
    """Planar projection in metres on the plane normal to `axis` (decals, plates)."""
    uvl = uvl or layer(bm); a = 'XYZ'.index(axis.upper()[-1]); i, j = [k for k in range(3) if k != a]
    for f in (faces if faces is not None else bm.faces):
        for l in f.loops:
            l[uvl].uv = (l.vert.co[i] + offset[0], l.vert.co[j] + offset[1])
    return uvl


def unit(bm, axis='Z', uvl=None):
    """0..1 over the mesh's extent on the plane normal to `axis` (one image over the whole decal)."""
    uvl = uvl or layer(bm); a = 'XYZ'.index(axis.upper()[-1]); i, j = [k for k in range(3) if k != a]
    xs = [v.co[i] for v in bm.verts]; ys = [v.co[j] for v in bm.verts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys); dx = max(x1 - x0, 1e-9); dy = max(y1 - y0, 1e-9)
    for f in bm.faces:
        for l in f.loops:
            l[uvl].uv = ((l.vert.co[i] - x0) / dx, (l.vert.co[j] - y0) / dy)
    return uvl


def ring_coords(rings, closed=True, v_off=0.0):
    """For lofted rings of points (rings[i][k] = Vector): us[i][k] = arc length around ring i up to point k (m; k runs
    to n for a closed ring so the seam gets the full perimeter) and vs[i] = mean distance along the path (m)."""
    n = len(rings[0]); us = []
    for r in rings:
        acc = [0.0]
        for k in range(1, n + (1 if closed else 0)):
            acc.append(acc[-1] + (Vector(r[k % n]) - Vector(r[k - 1])).length)
        us.append(acc)
    vs = [v_off]
    for i in range(1, len(rings)):
        vs.append(vs[-1] + sum((Vector(rings[i][k]) - Vector(rings[i - 1][k])).length for k in range(n)) / n)
    return us, vs


def cap(bm, faces, axis_vec, uvl=None, off=(0.0, 0.0)):
    """Planar UVs (m) for cap faces seen along axis_vec."""
    uvl = uvl or layer(bm)
    a = Vector(axis_vec).normalized(); t = a.orthogonal().normalized(); b = a.cross(t)
    for f in faces:
        for l in f.loops:
            co = l.vert.co; l[uvl].uv = (co.dot(t) + off[0], co.dot(b) + off[1])
    return uvl


# --------------------------------------------------------------------------------------------- checks (reuse _kit)
_KIT = None


def kit():
    """The game toolkit's shared helpers (3d-asset-making/scripts/_kit.py): samples_image, usable_uv,
    uv_overlap_share are reused, not copied."""
    global _KIT
    if _KIT is None:
        here = os.path.dirname(os.path.abspath(__file__))
        p = os.path.normpath(os.path.join(here, '..', '..', '..', '3d-asset-making', 'scripts', '_kit.py'))
        spec = importlib.util.spec_from_file_location('_kit_for_kit3d', p)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); _KIT = m
    return _KIT


def textured(o):
    """Does any material of this mesh object sample an image?"""
    k = kit()
    return any(k.samples_image(s.material) for s in o.material_slots if s.material)


def degenerate_share(me):
    """Share of the textured surface (by 3D area) whose UV triangles have no area: the texture streaks there."""
    uvl = next((u for u in me.uv_layers if u.active_render), me.uv_layers.active) if me.uv_layers else None
    if uvl is None or not len(me.polygons): return 1.0
    me.calc_loop_triangles(); n = len(me.loop_triangles)
    if not n: return 0.0
    loops = np.empty(n * 3, np.int32); me.loop_triangles.foreach_get('loops', loops)
    vidx = np.empty(n * 3, np.int32); me.loop_triangles.foreach_get('vertices', vidx)
    co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3)[vidx].reshape(n, 3, 3)
    u = np.empty(len(uvl.data) * 2, np.float32); uvl.data.foreach_get('uv', u); t = u.reshape(-1, 2)[loops].reshape(n, 3, 2)
    a3 = np.linalg.norm(np.cross(co[:, 1] - co[:, 0], co[:, 2] - co[:, 0]), axis=1) * 0.5
    a2 = np.abs((t[:, 1, 0] - t[:, 0, 0]) * (t[:, 2, 1] - t[:, 0, 1]) - (t[:, 1, 1] - t[:, 0, 1]) * (t[:, 2, 0] - t[:, 0, 0])) * 0.5
    tot = a3.sum()
    if tot <= 0: return 0.0
    bad = (a2 < 1e-4 * np.maximum(a3, 1e-12)) & (a3 > 1e-10)       # UV area under 1e-4 of the 3D area (m2 per m2)
    return float(a3[bad].sum() / tot)
