"""kit3d upgrade tools: for an asset that is UPGRADED, not rebuilt (kept meshes that only touch their hosts).

  seat(part=None, host=None, depth=0.003)   move the contact of a kept part INTO its host (the look stays)
  restore(obj, source.blend)                take a kept mesh back to its source, with the scene's own materials
"""
import bpy
import numpy as np
from mathutils import Vector

from . import const, core
from .core import obj
from .place import into, wall_below, ray

SEAT_TOL = 0.0012          # a vertex this close to the host's surface is "in contact" (m)
SEAT_MIN_WALL = 2 * const.ENTRY_MIN + 0.0004      # a wall under this cannot be entered 2 mm (into reads the NEARER skin)


def _objs(part):
    if isinstance(part, bpy.types.Object): return [part]
    if isinstance(part, (list, tuple, set)): return [o for x in part for o in _objs(x)]
    if bpy.data.objects.get(part) is not None: return [bpy.data.objects[part]]
    got = [o for o in bpy.data.objects if o.get('kit3d_part') == part]
    if not got: raise KeyError(f'kit3d: no object or plan part {part!r}')
    return got


def _into_rels(name):
    return [r for r in core.rels().values() if r['part'] == name and r['kind'] == 'into']


def _entry(p, h):
    """Measured `into` entry of p in h (mm), as check() reads it; None when it cannot be measured."""
    from .check import _measure
    m = _measure({'kind': 'into', 'part': p.name, 'host': h.name}, [])
    return None if not m else m.get('entry_mm')


def _contact(p, g, tol):
    """[(vertex index, world point, nearest host point, host outward normal, signed distance)] for the vertices of p
    that lie within tol of host geometry g."""
    if g.bvh is None or p.type != 'MESH': return []
    M = p.matrix_world; out = []
    lo = g.lo - tol; hi = g.hi + tol
    for v in p.data.vertices:
        w = M @ v.co
        if w.x < lo[0] or w.y < lo[1] or w.z < lo[2] or w.x > hi[0] or w.y > hi[1] or w.z > hi[2]: continue
        loc, nor, idx, dist = g.bvh.find_nearest(w, tol)
        if loc is None: continue
        n = Vector(g.n[idx])
        out.append((v.index, w, loc, n, (w - loc).dot(n)))
    return out


def _hangs_on(name, target, d=None, depth=0):
    """Does `name` hang (through its hosts) on `target`?"""
    d = d or core.rels()
    if depth > 30: return False
    for r in d.values():
        if r['part'] != name: continue
        for hk in ('host', 'host_b'):
            h = r.get(hk)
            if h and (h == target or _hangs_on(h, target, d, depth + 1)): return True
    return False


def _touching(p, tol, skip=()):
    """The mesh object (other than p, not hanging on p) that most vertices of p touch: (object, contact list)."""
    best = None; bb = core.geo(p)
    for o in bpy.context.scene.objects:
        if o is p or o.type != 'MESH' or o.name.startswith(('kit3d_cut:', 'anchor.')) or o.name in skip: continue
        g = core.geo(o)
        if not len(g.t) or not g.overlaps_box(bb, tol) or _hangs_on(o.name, p.name): continue
        c = _contact(p, g, tol)
        if c and (best is None or len(c) > len(best[1])): best = (o, c)
    return best or (None, [])


def _far_hidden(h, pts):
    """Are these points (on the far side of host h) on or inside another mesh of the scene (so nobody sees them)?"""
    for o in bpy.context.scene.objects:
        if o is h or o.type != 'MESH' or o.name.startswith(('kit3d_cut:', 'anchor.')): continue
        g = core.geo(o)
        if g.bvh is None: continue
        n = 0
        for q in pts:
            loc, nor, idx, dist = g.bvh.find_nearest(Vector(q), 0.05)
            if loc is not None and (dist < SEAT_TOL or (Vector(q) - loc).dot(Vector(g.n[idx])) < 0): n += 1
        if n >= max(1, len(pts) // 2): return o.name
    return None


def _grow_far_side(h, g, hits, grow):
    """Move the far skin of host h (the faces a ray from each contact meets on the other side of the wall) `grow` m
    further away from the contact. Returns the number of host vertices moved."""
    Mi = h.matrix_world.inverted(); R = h.matrix_world.to_3x3().inverted(); me = h.data
    planes = []
    for _, w, loc, n, sd in hits[:200]:
        r = ray(g.bvh, loc - n * 1e-5, -n, 0.3)
        if r[0] is not None: planes.append((r[0], n))
    if not planes: return 0
    moved = {}
    for v in me.vertices:
        w = h.matrix_world @ v.co
        for q, n in planes:
            if abs((w - q).dot(n)) < 0.0003:
                moved[v.index] = n; break
    for i, n in moved.items(): me.vertices[i].co += R @ (-n * grow)
    me.update(); core.clear_cache()
    return len(moved)


def seat(part=None, host=None, depth=0.003, tol=SEAT_TOL, thin='grow', rehost=True, note=''):
    """UPGRADING: seat kept parts that only TOUCH their host. Every vertex of the part that lies on the host's surface
    (within `tol`, 1.2 mm) moves `depth` (3 mm) INTO the host along the host's own normal; nothing else moves, so the
    visible shape stays (only the hidden contact side goes in). The part then gets `into(part, host)` and is measured.

      k.seat()                       every object whose `into` relation fails now (slit / gap), each on its own host
      k.seat('LP_foot.pad')          one object (or a list, or a plan part name) on its declared `into` host
      k.seat(pad, cover, depth=0.004)

    A part with no vertex on its declared host (a gap) is re-hosted on the mesh it really touches (rehost=True; never
    when you name the host in the call) and the change is reported. Copies that share one mesh are seated once.
    The thin-host case: `into` reads the distance to the host's NEARER skin, so a wall under 4.4 mm cannot be entered
    2 mm. In a wall of 4.4-6 mm the part goes in half the wall. In a thinner one (a 1.6 mm board) thin='grow' moves the
    host's FAR skin away until the wall is 2 x depth + 1 mm, but only when that far side lies on or in another mesh (it is
    out of sight); otherwise the part is listed under 'thin' with what to do. thin='force' grows it whatever (look at
    the far side afterwards), thin='skip' never grows.
    Run it again freely: a part that already enters its host is left alone. To take a part back first: restore().
    Returns {'seated': [{part, host, verts, depth_mm, entry_mm}], 'ok': [...], 'rehosted': [...], 'thin': [...],
    'left': [...], 'text': one line}."""
    core.update()
    if part is None:
        names = sorted({r['part'] for r in core.rels().values() if r['kind'] == 'into'}); ps = [bpy.data.objects[n] for n in names if bpy.data.objects.get(n)]
    else: ps = _objs(part)
    H0 = obj(host) if host is not None else None
    out = {'seated': [], 'ok': [], 'rehosted': [], 'thin': [], 'left': []}; done_mesh = {}
    for p in ps:
        if p.type != 'MESH' or p.library is not None: continue
        declared = [bpy.data.objects.get(r['host']) for r in _into_rels(p.name)]
        declared = [h for h in declared if h is not None]
        if H0 is None and part is None and not declared: continue
        hs = [H0] if H0 is not None else declared
        if not hs:
            if not rehost: out['left'].append({'part': p.name, 'why': 'no host given and no into() declared'}); continue
            hs = [None]
        for h in hs:
            if h is not None:
                e = _entry(p, h)
                if e is not None and e >= const.ENTRY_MIN * 1000:          # it enters this host already: only say so
                    if not any(r['host'] == h.name for r in _into_rels(p.name)): into(p, h, note or 'kept; enters its host as made')
                    out['ok'].append(p.name); continue
            key = p.data.as_pointer()
            if key in done_mesh and h is not None and done_mesh[key] is not None:     # a copy of a mesh seated already
                into(p, h, note or 'kept; seated with its mesh'); e = _entry(p, h)
                if e is not None and e >= const.ENTRY_MIN * 1000:
                    out['seated'].append({'part': p.name, 'host': h.name, 'verts': 0, 'depth_mm': done_mesh[key], 'entry_mm': e, 'shared_mesh': True}); continue
                p.data = p.data.copy(); core.update()                             # this copy meets its host differently
            hits = _contact(p, core.geo(h), tol) if h is not None else []
            was = h
            if not hits and rehost and H0 is None:          # a host named in the call is the builder's word: never swapped
                h2, hits = _touching(p, tol, skip=(h.name,) if h is not None else ())
                if h2 is not None:
                    if was is not None:
                        d = core.rels(); d.pop(core.rel_key('into', p.name, was.name), None); core.save_rels(d)
                    out['rehosted'].append({'part': p.name, 'from': was.name if was else None, 'to': h2.name}); h = h2
            if not hits or h is None:
                deps = [o.name for o in bpy.context.scene.objects if o.type == 'MESH' and o is not p and _hangs_on(o.name, p.name)
                        and core.geo(o).overlaps_box(core.geo(p), tol) and _contact(p, core.geo(o), tol)][:3]
                out['left'].append({'part': p.name, 'host': was.name if was else None, 'touches_its_dependents': deps,
                                    'why': (f'it touches only parts that hang on it ({", ".join(deps)}): name its real host, k.seat({p.name!r}, <host>)' if deps else
                                            f'no vertex within {tol * 1e3:.1f} mm of a host: a real gap (move it, or build a joining part)')}); continue
            g = core.geo(h)
            walls = [wl for wl in (wall_below(g, loc, n) for _, w, loc, n, sd in hits[::max(1, len(hits) // 60)]) if wl is not None]
            wmin = min(walls) if walls else None; d_in = depth; grown = 0
            if wmin is not None and wmin < 2 * depth:
                if wmin >= SEAT_MIN_WALL: d_in = wmin / 2.0
                else:
                    need = 2 * depth + 0.001 - wmin
                    far = [loc - n * wmin for _, w, loc, n, sd in hits[::max(1, len(hits) // 24)]]
                    behind = _far_hidden(h, far) if thin == 'grow' else None
                    if thin == 'force' or behind:
                        grown = _grow_far_side(h, g, hits, need); g = core.geo(h)
                    if not grown:
                        out['thin'].append({'part': p.name, 'host': h.name, 'wall_mm': round(wmin * 1e3, 2),
                                            'do': f'{h.name} is {wmin * 1e3:.1f} mm thin here and its far side is in view: seat on a thicker host '
                                                  f'(k.seat({p.name!r}, <host>)), thicken it yourself, or thin="force" (grows the far side {need * 1e3:.1f} mm)'})
                        continue
            R = p.matrix_world.to_3x3().inverted(); me = p.data
            for i, w, loc, n, sd in hits: me.vertices[i].co += R @ (-n * (d_in + sd))
            me.update(); me['kit3d_seated'] = h.name; done_mesh[key] = round(d_in * 1e3, 2); done_mesh[me.as_pointer()] = done_mesh[key]
            core.clear_cache(); core.update()
            into(p, h, note or f'kept; its contact side enters the host {d_in * 1e3:.1f} mm (k.seat)')
            rec = {'part': p.name, 'host': h.name, 'verts': len(hits), 'depth_mm': round(d_in * 1e3, 2), 'entry_mm': _entry(p, h)}
            if grown: rec['host_far_side_grown_verts'] = grown
            out['seated'].append(rec)
    weak = [s['part'] for s in out['seated'] if s['entry_mm'] is None or s['entry_mm'] < const.ENTRY_MIN * 1000]
    out['weak'] = weak
    out['text'] = (f'kit3d.seat: {len(out["seated"])} seated, {len(out["ok"])} already in, {len(out["rehosted"])} re-hosted, '
                   f'{len(out["thin"])} thin host, {len(out["left"])} left'
                   + (f'; still under {const.ENTRY_MIN * 1e3:.0f} mm after seating: {", ".join(weak[:4])}' if weak else '')
                   + (f'; thin: {out["thin"][0]["do"]}' if out['thin'] else '')
                   + (f'; left: {out["left"][0]["part"]}: {out["left"][0]["why"]}' + (f' +{len(out["left"]) - 1}' if len(out['left']) > 1 else '') if out['left'] else ''))
    return out


# ============================================================================================ restore
_ID_LISTS = ('objects', 'meshes', 'materials', 'node_groups', 'images', 'textures', 'collections', 'curves', 'lights', 'cameras', 'actions')


def _base_name(n):
    return n[:-4] if len(n) > 4 and n[-4] == '.' and n[-3:].isdigit() else n


def restore(part, source, name=None, transform=False):
    """UPGRADING: take the mesh of a kept object back to what it is in `source` (.blend), before a cut, a seat or a
    boolean is redone. part: an object, a name, a list of them or a plan part name (one read of the file for all;
    copies that share a mesh in the source share it again). Only the mesh comes back: its material slots point at the
    materials of THIS file (same names), so material edits made here stay in use, and nothing else from the source
    stays (no 'LP_glass.001' copies, no second parent 'LP_root.001'). name: the object's name in the source when it
    differs (one object only). Objects outside the list that shared an old mesh get the restored one too.
    transform=True also takes the source object's world matrix back.
    The plan part, relations and modifiers stay; re-run the step that follows (seat / cut). Never reload kept objects
    with bpy.data.libraries.load yourself: that brings copies of their materials, and edits then go to materials no
    object uses (check() names such copies in a MATERIALS line). Returns the object (a list for a list)."""
    import os
    many = not isinstance(part, bpy.types.Object) and (isinstance(part, (list, tuple, set)) or bpy.data.objects.get(part) is None)
    os_ = [o for o in _objs(part) if o.type == 'MESH' and o.library is None]
    if not os_: raise ValueError(f'kit3d.restore: no mesh object in {part!r}')
    if name is not None and len(os_) != 1: raise ValueError('kit3d.restore: name= goes with one object')
    want = {o.name: (name or o.name) for o in os_}
    source = bpy.path.abspath(source)
    if not os.path.exists(source): raise FileNotFoundError(f'kit3d.restore: no file {source}')
    before = {k: {x.as_pointer() for x in getattr(bpy.data, k)} for k in _ID_LISTS}
    names_before = {m.name for m in bpy.data.materials}
    with bpy.data.libraries.load(source, link=False) as (src, dst):
        missing = [n for n in want.values() if n not in src.objects]
        if missing:
            near = [n for n in src.objects if _base_name(missing[0]) in n][:6]
            raise KeyError(f'kit3d.restore: not in {source}: {missing[:5]}' + (f' (near: {near}; give name=)' if near else ''))
        src_mats = set(src.materials); dst.objects = list(want.values())
    loaded = dict(zip(want.keys(), dst.objects))
    new = {k: [x for x in getattr(bpy.data, k) if x.as_pointer() not in before[k]] for k in _ID_LISTS}
    mws = {}
    if transform:
        tmp = bpy.data.collections.new('kit3d_restore_tmp'); bpy.context.scene.collection.children.link(tmp)
        for x in new['objects']: tmp.objects.link(x)
        core.update(); mws = {n: x.matrix_world.copy() for n, x in loaded.items() if x is not None}
    olds = {}; kept_meshes = set()
    for o in os_:
        new_o = loaded.get(o.name)
        if new_o is None or new_o.type != 'MESH': raise ValueError(f'kit3d.restore: {want[o.name]!r} in {source} is not a mesh')
        me = new_o.data; old = o.data
        if me.as_pointer() not in kept_meshes:
            # material slots: the scene's own material of the same name instead of the copy the load made
            for i, m in enumerate(me.materials):
                if m is None: continue
                own = None
                for cand in (m.name, _base_name(m.name)):
                    if cand in src_mats and cand in names_before and bpy.data.materials.get(cand) is not m:
                        own = bpy.data.materials[cand]; break
                if own is None and i < len(old.materials) and old.materials[i] is not None and _base_name(old.materials[i].name) == _base_name(m.name):
                    own = old.materials[i]
                if own is not None and own is not m: me.materials[i] = own
            kept_meshes.add(me.as_pointer())
        if old is not me:
            olds.setdefault(old.name, (old, me))
            for u in [u for u in bpy.data.objects if u.type == 'MESH' and u.data is old and u.as_pointer() in before['objects']]: u.data = me
    for x in new['objects']: bpy.data.objects.remove(x, do_unlink=True)
    if transform:
        bpy.data.collections.remove(bpy.data.collections['kit3d_restore_tmp'])
        for o in os_:
            if o.name in mws:
                o.matrix_world = mws[o.name]
                if 'kit3d_frame' in o: del o['kit3d_frame']
    named = set()
    for oldname, (old, me) in olds.items():
        if old.users == 0:
            bpy.data.meshes.remove(old)
            if me.as_pointer() not in named: me.name = oldname; named.add(me.as_pointer())
    for k in ('collections', 'meshes', 'curves', 'lights', 'cameras', 'materials', 'node_groups', 'textures', 'images', 'actions'):
        for _ in range(3):                                  # what only the copies used goes with them
            for x in list(new[k]):
                try:
                    if k == 'meshes' and x.as_pointer() in kept_meshes: new[k].remove(x); continue
                    if x.users == 0 or (x.users == 1 and x.use_fake_user): getattr(bpy.data, k).remove(x); new[k].remove(x)
                except ReferenceError:
                    new[k].remove(x)
    core.clear_cache(); core.update()
    st = core.S().get('step')
    for o in os_:
        if st is not None and o.name not in st.setdefault('created', []): st['created'].append(o.name)
    return os_ if many else os_[0]


def shadow_materials():
    """Materials no object uses whose name shadows one that IS used ('LP_glass.001' beside a used 'LP_glass', or the
    other way round): edits to them show nowhere. Returns [(unused name, used name)]."""
    used = set()
    for o in bpy.data.objects:
        for s in o.material_slots:
            if s.material is not None: used.add(s.material.name)
    by = {}
    for n in used: by.setdefault(_base_name(n), []).append(n)
    out = []
    for m in bpy.data.materials:
        if m.name in used or m.library is not None: continue
        b = _base_name(m.name)
        if b in by: out.append((m.name, sorted(by[b])[0]))
    return sorted(out)
