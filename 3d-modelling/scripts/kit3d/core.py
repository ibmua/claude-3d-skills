"""kit3d core: the current part, object creation, the relation store, world geometry + BVH cache.

State that must survive a reload of the module (the bridge re-imports kit3d on every step) lives in
bpy.app.driver_namespace['kit3d'] (per Blender process) and in the scene (relations: scene['kit3d_rel'], JSON).
"""
import json, math
import bpy, bmesh
import numpy as np
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

from . import const


# ------------------------------------------------------------------------------------------------- process state
def S():
    d = bpy.app.driver_namespace.get('kit3d')
    if not isinstance(d, dict):
        d = {'part': None, 'coll': None, 'lod': 'film', 'plan': None, 'created': [], 'step': None, 'gen': 0}
        bpy.app.driver_namespace['kit3d'] = d
    return d


def lod():
    return S().get('lod') or 'film'


def set_lod(level):
    if level not in const.LOD_LEVELS: raise ValueError(f'lod {level!r}: one of {const.LOD_LEVELS}')
    S()['lod'] = level


def lod_segments(n, level=None, minimum=6):
    """Segments for a round thing that has n at film level: fewer at near/mid/far, never under `minimum`,
    rounded to a multiple of 2 so mirrored halves stay matched. Every primitive's segs=None uses this."""
    f = const.LOD_SEG_FACTOR[level or lod()]
    return max(minimum, int(round(n * f / 2.0)) * 2)


def keep(size, level=None):
    """True if a detail of this size (m) is still visible at the current level (2 px at its switch distance).
    `if kit3d.keep(0.012): bolts(...)` drops 12 mm bolts from mid and far versions of the same program."""
    return size >= const.LOD_MIN_SIZE[level or lod()]


# ------------------------------------------------------------------------------------------------- relations store
def rels(scene=None):
    sc = scene or bpy.context.scene
    try:
        return json.loads(sc.get('kit3d_rel', '{}'))
    except (TypeError, ValueError):
        return {}


def save_rels(d, scene=None):
    (scene or bpy.context.scene)['kit3d_rel'] = json.dumps(d, separators=(',', ':'))


def rel_key(kind, part, host):
    return f'{kind}:{part}:{host}'


def put_rel(r):
    d = rels(); d[rel_key(r['kind'], r['part'], r.get('host', ''))] = r; save_rels(d)
    st = S().get('step')
    if st is not None: st.setdefault('rels', []).append(rel_key(r['kind'], r['part'], r.get('host', '')))
    return r


def drop_rels_of(names):
    names = set(names); d = rels()
    keep_ = {k: r for k, r in d.items() if r['part'] not in names}
    if len(keep_) != len(d): save_rels(keep_)


# ------------------------------------------------------------------------------------------------- parts and objects
def begin(part, coll=None, parent=None, clear=True):
    """Start (or re-run) a part: its objects go to collection `coll` (default: the part name) and are tagged
    o['kit3d_part'] = part. clear=True deletes the objects the last run of this part made, and their relations,
    so re-running a script never piles up copies. In the part's OWN collection (coll=None) untagged objects count as
    the part's; in a collection given with coll= (the original's collection of an asset being upgraded) only objects
    tagged with this part are cleared: the kept originals there stay. Returns the collection."""
    st = S(); name = coll or part
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(c)
    elif clear:
        gone = [o.name for o in list(c.all_objects) if o.get('kit3d_part', part if name == part else None) == part]
        drop_rels_of(gone)
        for o in list(c.all_objects):
            if o.name in gone: bpy.data.objects.remove(o, do_unlink=True)
        for n in gone:          # the unbent source a re-made part of the same name would otherwise restore, its cutter
            me = bpy.data.meshes.get('kit3d_src:' + n)
            if me is not None: bpy.data.meshes.remove(me)
            ct = bpy.data.objects.get('kit3d_cut:' + n)
            if ct is not None: bpy.data.objects.remove(ct, do_unlink=True)
        for m in [m for m in bpy.data.meshes if m.users == 0 and not m.use_fake_user]: bpy.data.meshes.remove(m)
    st['part'] = part; st['coll'] = c.name; st['gen'] = st.get('gen', 0) + 1
    return c


def current_coll():
    st = S(); c = bpy.data.collections.get(st.get('coll') or '')
    return c or bpy.context.scene.collection


def new_object(name, me, mat=None, coll=None, part=None):
    """Link mesh `me` as a new object in the current part's collection, tagged with the part."""
    if mat is not None:
        for m in (mat if isinstance(mat, (list, tuple)) else [mat]):
            if m is not None: me.materials.append(m)
    o = bpy.data.objects.new(name, me)
    (coll or current_coll()).objects.link(o)
    p = part or S().get('part')
    if p: o['kit3d_part'] = p
    st = S().get('step')
    if st is not None: st.setdefault('created', []).append(o.name)
    return o


def obj(x):
    """Object from an object or a name (raises with the near names when missing)."""
    if isinstance(x, bpy.types.Object): return x
    o = bpy.data.objects.get(x)
    if o is None:
        near = [n for n in bpy.data.objects.keys() if str(x).split('.')[0] in n][:5]
        raise KeyError(f'kit3d: no object {x!r}' + (f' (near: {near})' if near else ''))
    return o


def part_of(o):
    return o.get('kit3d_part') or o.name


def mesh_from_bm(name, bm):
    me = bpy.data.meshes.new(name)
    bm.normal_update(); bm.to_mesh(me); bm.free()
    return me


# ------------------------------------------------------------------------------------------------- world geometry
class Geo:
    """World-space triangles of one object (modifiers applied, collection instances realised), with a BVH."""
    __slots__ = ('name', 'v', 't', 'n', 'a', 'c', 'q', 'lo', 'hi', '_bvh')

    def __init__(self, name, v, t):
        self.name = name; self.v = v; self.t = t
        if len(t):
            p = v[t]; cr = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]); ln = np.linalg.norm(cr, axis=1)
            self.a = ln * 0.5; self.n = cr / np.maximum(ln, 1e-20)[:, None]; self.c = p.mean(1)
            e2 = np.max([((p[:, i] - p[:, (i + 1) % 3]) ** 2).sum(1) for i in range(3)], axis=0)
            self.q = ln / np.maximum(e2, 1e-30)          # height / longest edge: ~0 for slivers (normal meaningless)
        else:
            self.a = np.zeros(0); self.n = np.zeros((0, 3)); self.c = np.zeros((0, 3)); self.q = np.zeros(0)
        self.lo = v.min(0) if len(v) else np.zeros(3); self.hi = v.max(0) if len(v) else np.zeros(3)
        self._bvh = None

    @property
    def bvh(self):
        if self._bvh is None:
            self._bvh = BVHTree.FromPolygons(self.v.tolist(), self.t.tolist(), all_triangles=True) if len(self.t) else None
        return self._bvh

    def overlaps_box(self, other, pad=0.0):
        return bool(np.all(self.lo - pad <= other.hi) and np.all(other.lo - pad <= self.hi))


def _mesh_local(me):
    me.calc_loop_triangles()
    nv = len(me.vertices); nt = len(me.loop_triangles)
    v = np.empty(nv * 3, np.float64); me.vertices.foreach_get('co', v)
    t = np.empty(nt * 3, np.int64); me.loop_triangles.foreach_get('vertices', t)
    return v.reshape(-1, 3), t.reshape(-1, 3)


def _xf(v, mw):
    M = np.array(mw, dtype=np.float64)
    return v @ M[:3, :3].T + M[:3, 3]


_IMAP = {'key': None, 'map': {}}


def _imap(dg):
    """{instancing empty name: [(evaluated mesh object, world matrix)]} built in one pass over the depsgraph."""
    key = (dg.as_pointer(), S().get('gen'), len(bpy.data.objects), bpy.context.scene.frame_current)
    if _IMAP['key'] != key:
        m = {}
        for inst in dg.object_instances:
            if inst.is_instance and inst.parent is not None and inst.object.type == 'MESH':
                m.setdefault(inst.parent.original.name, []).append((inst.object, inst.matrix_world.copy()))
        _IMAP['key'] = key; _IMAP['map'] = m
    return _IMAP['map']


def _wind(t, mw):
    """Triangles of a mirrored placement (negative scale, det < 0) wound back so normals still point out, as Blender
    draws them. (A mirrored instance whose exporter does not do this ships inside-out: see PITFALLS.)"""
    return t[:, ::-1].copy() if mw.to_3x3().determinant() < 0 else t


def world_geo(o, dg=None):
    o = obj(o); dg = dg or bpy.context.evaluated_depsgraph_get()
    vs, ts, off = [], [], 0
    if o.type == 'MESH':
        ev = o.evaluated_get(dg); me = ev.to_mesh()
        try:
            v, t = _mesh_local(me)
        finally:
            ev.to_mesh_clear()
        vs.append(_xf(v, o.matrix_world)); ts.append(_wind(t, o.matrix_world))
    elif o.type == 'EMPTY' and o.instance_type == 'COLLECTION' and o.instance_collection:
        loc = {}
        for eo, mw in _imap(dg).get(o.name, []):
            if eo.name not in loc:
                try:
                    me = eo.to_mesh()
                except RuntimeError:              # an instanced object without geometry (e.g. hidden, unevaluated)
                    loc[eo.name] = None; continue
                try:
                    loc[eo.name] = _mesh_local(me)
                finally:
                    eo.to_mesh_clear()
            if loc[eo.name] is None: continue
            v, t = loc[eo.name]
            vs.append(_xf(v, mw)); ts.append(_wind(t, mw) + off); off += len(v)
    if not vs: return Geo(o.name, np.zeros((0, 3)), np.zeros((0, 3), np.int64))
    if len(vs) > 1:
        return Geo(o.name, np.concatenate(vs), np.concatenate(ts))
    return Geo(o.name, vs[0], ts[0])


_CACHE = {}


def _sig(o):
    m = tuple(round(x, 7) for r in o.matrix_world for x in r)
    if o.type == 'MESH':
        me = o.data; nv = len(me.vertices)
        s = 0.0
        if nv:
            k = min(nv, 64); a = np.empty(nv * 3, np.float32); me.vertices.foreach_get('co', a)
            s = float(a[:k * 3].sum() + a[-k * 3:].sum() + a.sum())
        mods = tuple((md.type, md.show_viewport, getattr(md, 'object', None) and md.object.name) for md in o.modifiers)
        return (o.name, me.as_pointer(), nv, len(me.polygons), m, round(s, 5), mods)
    ic = o.instance_collection
    return (o.name, 'inst', ic.name if ic else None, m, len(ic.all_objects) if ic else 0)


def geo(o, dg=None, cache=True):
    """Cached world_geo (keyed by a signature of the object: re-made meshes and moves invalidate it)."""
    o = obj(o)
    if not cache: return world_geo(o, dg)
    k = _sig(o); g = _CACHE.get(o.name)
    if g is not None and g[0] == k: return g[1]
    g = world_geo(o, dg); _CACHE[o.name] = (k, g)
    if len(_CACHE) > 4000: _CACHE.clear()
    return g


def clear_cache():
    _CACHE.clear(); _IMAP['key'] = None


def local_geo(o, dg=None):
    """(vertices, triangles) of a mesh object (evaluated) or an instancing empty, in the object's own frame."""
    o = obj(o); dg = dg or bpy.context.evaluated_depsgraph_get()
    if o.type == 'MESH':
        ev = o.evaluated_get(dg); me = ev.to_mesh()
        try:
            return _mesh_local(me)
        finally:
            ev.to_mesh_clear()
    g = world_geo(o, dg)
    if not len(g.v): return g.v, g.t
    M = np.array(o.matrix_world.inverted(), dtype=np.float64)
    return g.v @ M[:3, :3].T + M[:3, 3], g.t


def local_verts(o, dg=None):
    """Evaluated vertex coordinates of a mesh object (or the realised instance geometry of an empty) in the object's
    own frame, as numpy (N, 3)."""
    o = obj(o); dg = dg or bpy.context.evaluated_depsgraph_get()
    if o.type == 'MESH':
        ev = o.evaluated_get(dg); me = ev.to_mesh()
        try:
            v = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', v); return v.reshape(-1, 3)
        finally:
            ev.to_mesh_clear()
    g = world_geo(o, dg)
    if not len(g.v): return g.v
    M = np.array(o.matrix_world.inverted(), dtype=np.float64)
    return g.v @ M[:3, :3].T + M[:3, 3]


def update():
    bpy.context.view_layer.update()


def vec(x):
    return Vector(tuple(float(c) for c in x))
