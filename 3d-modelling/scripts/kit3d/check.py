"""kit3d.check (R2): measure the recorded relations and the faults that blink or speckle, in live Blender.

  r = kit3d.check(parts=None, json_path=None)    # parts: plan part names or object names (default: everything)
  print(r['text'])                                # <= 10 lines; r['ok']; r['fails'] = places for render.py inspect

Per relation (mathutils.bvhtree, world space, modifiers and collection instances included):
  attach / scatter   entry depth of the mounting side over its whole footprint, measured along the part's mounting
                     axis: the SHALLOWEST point must be 2-10 mm inside (ENTRY_MIN..ENTRY_MAX); < 0 = gap (floating
                     or slit), 0-2 mm = slit after any rounding; also the deepest point must not go through the host
                     wall (poke)
  span               the same at each end, over the end's whole section, along the member
  lay                every vertex of the layer stands >= LIFT - 0.5 mm off the host (and <= 15 mm); cut=True: the
                     host has no surface within LIFT under the inlay's top (the pocket is really there)
  into               the two parts interpenetrate by >= 2 mm; else the gap. What is measured: sample points of the
                     PART (vertices, face centres, points toward the corners; where surfaces cross, a grid on the
                     crossing triangles of both) and, for each one inside the host, its distance to the host's NEAREST
                     surface; the largest is the entry. So in a host wall of thickness w the reading is at most w/2: a
                     vertex pushed 2.8 mm into a 3.1 mm pocket floor reads 0.3 mm (the far skin is nearer). A wall
                     under 4.4 mm cannot be entered 2 mm: kit3d.seat grows a hidden far side or says what to do
  free / root        listed, never failed
Over the checked objects: parts with no relation and no free()/root() (unplaced); same-facing faces of any two
surfaces within 2 mm and overlapping (coplanar, z-fight; >= 1 cm2 is a FAULT); opposite faces within 0.2 mm
(back-to-back duplicate; >= 1 cm2 FAULT); textured meshes (an image in the material) with no UV map, with
degenerate UVs (> 1 % of area) or with faces sharing texture space (> 1 %, the _kit/exporter rule).
JSON place fields: kind, rel, part, host, plan_part, plan_host, value_mm, need, world [x,y,z] (where to look),
normal, radius_m (size of the region to frame), objects [the two objects].
"""
import json, math, os, sys, time
import bpy
import numpy as np
from mathutils import Vector

from . import const, core
from .place import depth_along, wall_below, _footprint, foot_band

SKIP_PREFIX = ('kit3d_cut:', 'anchor.')


def _excluded(o):
    if any(c.hide_viewport for c in o.users_collection): return True
    def find(lc, name):
        if lc.collection.name == name: return lc
        for ch in lc.children:
            r = find(ch, name)
            if r: return r
        return None
    root = bpy.context.view_layer.layer_collection
    for c in o.users_collection:
        if c == bpy.context.scene.collection: return False
        lc = find(root, c.name)
        if lc is not None and not lc.exclude: return False
    return True


def _p3(v):
    return [round(float(x), 4) for x in v]


def _fail(fails, kind, r, value_mm, need, world, normal=None, radius=0.1, objects=None, **kw):
    f = {'kind': kind, 'rel': r.get('kind') if r else None, 'part': r.get('part') if r else kw.pop('part', None),
         'host': r.get('host') if r else kw.pop('host', None), 'plan_part': r.get('plan_part') if r else kw.pop('plan_part', None),
         'plan_host': r.get('plan_host') if r else kw.pop('plan_host', None),
         'value_mm': None if value_mm is None else round(value_mm, 2), 'need': need,
         'world': _p3(world) if world is not None else None, 'normal': _p3(normal) if normal is not None else None,
         'radius_m': round(float(radius), 3)}
    f['objects'] = objects or [x for x in (f['part'], f['host']) if x]
    f.update(kw); fails.append(f)
    return f


def _world(o, lv):
    M = np.array(o.matrix_world, dtype=np.float64)
    return lv @ M[:3, :3].T + M[:3, 3]


def _size(o):
    try:
        return max(o.dimensions) if o.type == 'MESH' else 0.2
    except Exception:
        return 0.2


def _entry(rel, foot_w, n, g, fails, kind_label, reach=0.25):
    ds = [(depth_along(g, w, n, reach), w) for w in foot_w]
    ok = [(d, w) for d, w in ds if d is not None]
    if not ok:
        _fail(fails, 'not_over_host', rel, None, 'footprint over its host', foot_w[0] if len(foot_w) else None, n)
        return None
    dmin, wmin = min(ok, key=lambda x: x[0]); dmax, wmax = max(ok, key=lambda x: x[0])
    m = {'entry_min_mm': round(dmin * 1000, 2), 'entry_max_mm': round(dmax * 1000, 2),
         'coverage': round(len(ok) / max(1, len(ds)), 3)}
    if dmin < 0:
        _fail(fails, 'gap' if dmin < -0.01 else 'slit', rel, -dmin * 1000, f'enter {const.ENTRY_MIN*1e3:.0f}-{const.ENTRY_MAX*1e3:.0f} mm',
              wmin, n, label=kind_label)
    elif dmin < const.ENTRY_MIN:
        _fail(fails, 'slit', rel, dmin * 1000, f'enter >= {const.ENTRY_MIN*1e3:.0f} mm (touching only)', wmin, n, label=kind_label)
    elif dmin > const.ENTRY_MAX:
        _fail(fails, 'sunk', rel, dmin * 1000, f'enter <= {const.ENTRY_MAX*1e3:.0f} mm', wmin, n, label=kind_label)
    if dmax > 0:
        s = Vector(wmax) + Vector(n) * dmax; wall = wall_below(g, s, Vector(n))
        m['wall_mm'] = None if wall is None else round(wall * 1000, 2)
        if wall is not None and dmax > wall + 1e-4:
            _fail(fails, 'poke', rel, dmax * 1000, f'stay inside the host wall ({wall*1000:.1f} mm)', wmax, n, label=kind_label)
    return m


def _measure(rel, fails):
    kind = rel['kind']; p = bpy.data.objects.get(rel['part'])
    if p is None:
        _fail(fails, 'part_missing', rel, None, 'the part exists', None); return None
    if kind in ('free', 'root'): return {}
    h = bpy.data.objects.get(rel.get('host') or '')
    if h is None:
        _fail(fails, 'host_missing', rel, None, f'host {rel.get("host")} exists', p.matrix_world.translation); return None
    g = core.geo(h)
    if kind == 'attach':
        lv, lt = core.local_geo(p); a = Vector(rel['a'])
        sc = np.array(p.matrix_world.to_scale())
        foot, base, ext = _footprint(lv * sc, a, tris=lt)
        fw = _world(p, foot / sc); n = (p.matrix_world.to_3x3() @ a).normalized()
        return _entry(rel, fw, n, g, fails, 'attach', reach=max(0.25, 2 * ext))
    if kind == 'scatter':
        me = p.data; co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
        W = _world(p, co); worst = None; bad = 0; out = {'items': len(rel['items'])}
        for (st, cnt, nn, ss) in rel['items']:
            n = Vector(nn); w = W[st:st + cnt]; h_ = w @ np.array(n); sel = w[h_ <= h_.min() + foot_band(float(h_.max() - h_.min()))]
            sub = []
            m = _entry(rel, sel, n, g, sub, 'scatter item', reach=0.15)
            if sub:
                bad += 1
                if worst is None: worst = sub[0]
            if m and (out.get('entry_min_mm') is None or m['entry_min_mm'] < out['entry_min_mm']): out['entry_min_mm'] = m['entry_min_mm']
        if worst is not None:
            worst['need'] += f' ({bad} of {len(rel["items"])} items fail)'; fails.append(worst)
        return out
    if kind == 'span':
        me = p.data; k = rel['ring']; nr = rel['rings']
        co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
        if len(co) < k * nr:
            _fail(fails, 'changed', rel, None, 'span mesh as built (re-run span)', p.matrix_world.translation); return None
        W = _world(p, co[:k * nr]); out = {}
        hb = bpy.data.objects.get(rel.get('host_b') or '')
        if hb is None:
            _fail(fails, 'host_missing', rel, None, f'host {rel.get("host_b")} exists', W[-1]); return None
        for end, (r0, r1, gg, hn) in {'a': (W[:k], W[k:2 * k], g, rel['host']), 'b': (W[(nr - 1) * k:nr * k], W[(nr - 2) * k:(nr - 1) * k], core.geo(hb), rel['host_b'])}.items():
            d = Vector(r0.mean(0) - r1.mean(0)).normalized()
            rr = dict(rel); rr['host'] = hn; rr['plan_host'] = rel.get('plan_host') if end == 'a' else rel.get('plan_host_b')
            m = _entry(rr, r0, -d, gg, fails, f'span end {end}', reach=0.15)
            if m: out[end] = m
        return out
    if kind == 'lay':
        me = p.data; co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
        nm = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('normal', nm); nm = nm.reshape(-1, 3)
        W = _world(p, co); R = np.array(p.matrix_world.to_3x3().normalized()); N = nm @ R.T
        if rel.get('cut'):
            nr = Vector(rel['n']); top = (N @ np.array(nr)) > 0.85
            W = W[top]; N = N[top]
        cl = []
        if rel.get('cut'):
            for w, n in zip(W, N):
                d = depth_along(g, w, n, 0.05)
                if d is not None: cl.append((-d, w, n))
        else:
            # every vertex, back and sides included: its distance to the nearest point of the host (signed: under
            # the surface = negative). Measured along the vertex normal, the back of a layer that has thickness
            # (lettering) was never seen: example 07 stood 3.5 mm off and passed on one flank, failed on the other.
            for w, n in zip(W, N):
                loc, nor, idx, dist = g.bvh.find_nearest(Vector(w))
                if loc is None: continue
                out_n = Vector(g.n[idx])
                cl.append((dist if (Vector(w) - loc).dot(out_n) >= 0 else -dist, w, out_n))
        if not cl:
            if rel.get('cut'): return {'clear_min_mm': None}
            _fail(fails, 'float', rel, None, f'lie {const.LIFT*1e3:.0f} mm off the host', W[0], N[0]); return None
        cmin, wmin, nmin = min(cl, key=lambda x: x[0]); out = {'clear_min_mm': round(cmin * 1000, 2)}
        need = const.LIFT - const.LIFT_TOL
        if rel.get('cut'):
            th = rel.get('thick') or 0.0
            if cmin < th - 1e-4:
                _fail(fails, 'coplanar', rel, cmin * 1000, f'cut: the host surface removed under the inlay (pocket >= {th*1e3:.1f} mm)', wmin, nmin)
        elif cmin < need:
            _fail(fails, 'lift' if cmin > -0.0005 else 'sunk_layer', rel, cmin * 1000, f'lift >= {const.LIFT*1e3:.0f} mm or cut=True', wmin, nmin)
        elif cmin > const.LIFT_MAX:
            _fail(fails, 'float', rel, cmin * 1000, f'lift <= {const.LIFT_MAX*1e3:.0f} mm', wmin, nmin)
        return out
    if kind == 'into':
        gp = core.geo(p); hb = g.bvh; pb = gp.bvh
        if hb is None or pb is None:
            _fail(fails, 'empty', rel, None, 'both have surfaces', p.matrix_world.translation); return None
        pairs = pb.overlap(hb)
        P = gp.v[gp.t]; C = gp.c
        V = np.concatenate([gp.v, C] + [C + 0.8 * (P[:, k] - C) for k in range(3)]) if len(gp.t) else gp.v
        if len(V) > 6000: V = V[np.linspace(0, len(V) - 1, 6000).astype(int)]
        inside = 0.0; gap = 1e9; gw = None; dw = None
        for v in V:
            loc, nor, idx, dist = hb.find_nearest(Vector(v))
            if loc is None: continue
            if (Vector(v) - loc).dot(g.n[idx]) < 0:
                if dist > inside: inside = dist; dw = v
            elif dist < gap: gap = dist; gw = v
        if pairs and inside < const.ENTRY_MIN:
            # where the surfaces cross, sample the crossing triangles densely, both ways (a rod entering a big face)
            for G1, B2, G2, col in ((gp, hb, g, 0), (g, pb, gp, 1)):
                ts = np.unique(np.array([q[col] for q in pairs]))[:400]
                for X in _grid(G1, ts):
                    loc, nor, idx, dist = B2.find_nearest(Vector(X))
                    if loc is not None and (Vector(X) - loc).dot(G2.n[idx]) < 0 and dist > inside: inside = dist; dw = X
        if not pairs and inside == 0.0:
            # the closest approach can lie between vertices: also look from the host's vertices
            Hv = g.v
            if len(Hv) > 3000: Hv = Hv[np.linspace(0, len(Hv) - 1, 3000).astype(int)]
            for v in Hv:
                loc, nor, idx, dist = pb.find_nearest(Vector(v))
                if loc is not None and dist < gap: gap = dist; gw = loc
        out = {'overlap_tris': len(pairs), 'entry_mm': round(inside * 1000, 2)}
        if inside >= const.ENTRY_MIN: return out
        if pairs or inside > 0:
            wl = None
            if dw is not None:                         # how thick is the host where the deepest point sits?
                loc, nor, idx, dist = hb.find_nearest(Vector(dw))
                if loc is not None: wl = wall_below(g, loc, Vector(g.n[idx]))
            thin = wl is not None and wl < 2 * const.ENTRY_MIN + 0.0004
            _fail(fails, 'slit', rel, inside * 1000, f'enter >= {const.ENTRY_MIN*1e3:.0f} mm (touching only)', dw if dw is not None else gw,
                  wall_mm=None if wl is None else round(wl * 1000, 2),
                  do=(f'into reads the deepest point of the part to the host\'s NEAREST skin, and the host is {wl * 1e3:.1f} mm thin here '
                      f'(under 4.4 mm nothing enters 2 mm): k.seat({rel["part"]!r}) grows a hidden far side, or name a thicker host'
                      if thin else f'k.seat({rel["part"]!r}) moves its contact side in'))
        else:
            out['gap_mm'] = round(gap * 1000, 2)
            _fail(fails, 'gap' if gap > 0.01 else 'slit', rel, gap * 1000, f'enter >= {const.ENTRY_MIN*1e3:.0f} mm', gw,
                  radius=max(0.05, min(_size(p), 1.0)),
                  do=f'k.seat({rel["part"]!r}) (re-hosts it on the mesh it touches)' if gap <= 0.01 else None)
        return out
    return {}


_BARY = np.array([(i / 6, j / 6, 1 - (i + j) / 6) for i in range(7) for j in range(7 - i)])


def _grid(G, ts):
    """28 barycentric points on each of triangles ts of Geo G."""
    P = G.v[G.t[ts]]                                  # (n, 3, 3)
    return np.einsum('kb,nbc->nkc', _BARY, P).reshape(-1, 3)


def _hidden(p, hosts):
    """Is point p inside one of the host Geos by more than 1 mm (a face there can never be seen)?"""
    for g in hosts:
        if g.bvh is None or np.any(p < g.lo - 1e-3) or np.any(p > g.hi + 1e-3): continue
        loc, nor, idx, dist = g.bvh.find_nearest(Vector(p))
        if loc is not None and dist > 1e-3 and (Vector(p) - loc).dot(Vector(g.n[idx])) < 0: return True
    return False


def _coplanar(objs, scene_objs, fails, stats):
    """Same-facing faces within COPLANAR that overlap (z-fight) and opposite faces within BACK2BACK (duplicates).
    Overlaps buried inside a host of either object (two parts entering the same wall by the same 5 mm) cannot be seen
    and are not counted."""
    geos = {}
    hosts_of = {}
    for r in core.rels().values():
        for hk in ('host', 'host_b'):
            if r.get(hk): hosts_of.setdefault(r['part'], set()).add(r[hk])
    def G(o):
        if o.name not in geos: geos[o.name] = core.geo(o)
        return geos[o.name]
    boxes = {}
    for o in scene_objs:
        try:
            bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
        except Exception:
            continue
        if o.type == 'EMPTY':
            g = G(o)
            if not len(g.v): continue
            boxes[o.name] = (g.lo, g.hi)
        else:
            boxes[o.name] = (np.array([min(v[i] for v in bb) for i in range(3)]), np.array([max(v[i] for v in bb) for i in range(3)]))
    pad = const.COPLANAR; pairs = {}
    for o in objs:
        if o.name not in boxes: continue
        lo, hi = boxes[o.name]; g = G(o)
        if not len(g.t): continue
        cands = [q for q, (l2, h2) in boxes.items() if np.all(lo - pad <= h2) and np.all(l2 - pad <= hi)]
        P = g.v[g.t]; C = g.c
        samples = [C] + [C + 0.7 * (P[:, k] - C) for k in range(3)]
        for qn in cands:
            q = bpy.data.objects[qn]; gq = G(q)
            if gq.bvh is None: continue
            same = qn == o.name
            second = not same and o.name > qn and any(x.name == qn for x in objs)   # the pair was read from q's side already
            ql, qh = gq.lo - pad, gq.hi + pad
            for si, S in enumerate(samples):
                if same and si > 0: break
                m = np.all((S >= ql) & (S <= qh), axis=1)
                idxs = np.nonzero(m)[0]
                for ti in idxs:
                    if g.a[ti] < 1e-9 or g.q[ti] < 2e-3: continue   # slivers (collinear n-gon corners): their normal means nothing
                    s = Vector(S[ti]); nO = Vector(g.n[ti])
                    for loc, nor, idx, dist in gq.bvh.find_nearest_range(s, pad):
                        if (same and idx == ti) or gq.a[idx] < 1e-9 or gq.q[idx] < 2e-3: continue
                        if dist > 1e-7 and (s - loc).normalized().cross(nor).length > 0.1: continue
                        c = nO.dot(nor)
                        if second and dist > const.COPLANAR - 0.00025: continue    # second reading: 0.25 mm less, for chords on a curved host
                        if c > const.PARALLEL: kind = 'coplanar'
                        elif c < -const.PARALLEL and dist < const.BACK2BACK: kind = 'back2back'
                        else: continue
                        hs = [G(bpy.data.objects[x]) for x in (hosts_of.get(o.name, set()) | hosts_of.get(qn, set())) - {o.name, qn}
                              if bpy.data.objects.get(x)]
                        if hs and _hidden(S[ti], hs): break
                        key = (kind,) + tuple(sorted((o.name, qn)))
                        e = pairs.setdefault(key, {}).setdefault(o.name, {'area': 0.0, 'pts': [], 'dist': 1e9, 'n': nO, 'n2': Vector(nor), 'sd': 0.0})
                        e['area'] += g.a[ti] / 4.0
                        if dist < e['dist']: e['dist'] = dist; e['n'] = nO; e['n2'] = Vector(nor); e['sd'] = (s - loc).dot(nO)
                        if len(e['pts']) < 64: e['pts'].append(S[ti])
                        break
    # Each pair is read from both sides. The FIRST reading (from the object whose name sorts first, the only one
    # until 2026-10-13) decides PASS/FAIL. The faces of a big plate rarely have a sample under a small strap lying on
    # it, so the SECOND reading (from the other object) finds overlaps the first misses: those are listed as advisory
    # (stats['second']) until the examples and the assets in work are clean of them (example 01 has four).
    for (kind, a, b), sides in pairs.items():
        first = sides.get(a) if a != b else next(iter(sides.values()))
        lim0 = const.COPLANAR_AREA if kind == 'coplanar' else const.BACK2BACK_AREA
        if (first is None or first['area'] < lim0) and a != b:
            e2 = sides.get(b)
            if e2 is not None and e2['area'] >= lim0:
                c2 = np.array(e2['pts']).mean(0)
                stats.setdefault('second', []).append({'kind': kind, 'objects': [a, b], 'area_cm2': round(e2['area'] * 1e4, 1),
                                                       'gap_mm': round(e2['dist'] * 1000, 3), 'world': _p3(c2)})
        if first is None: continue
        e = first
        lim = const.COPLANAR_AREA if kind == 'coplanar' else const.BACK2BACK_AREA
        stats[kind] = stats.get(kind, 0) + 1
        if e['area'] >= lim:
            pts = np.array(e['pts']); c = pts.mean(0); rad = float(np.linalg.norm(pts - c, axis=1).max()) if len(pts) > 1 else 0.05
            oa, ob = bpy.data.objects.get(a), bpy.data.objects.get(b)
            # which of the two stands proud (its face is the outer one), by how much, and what to do about it
            top = (a if e['sd'] >= 0 else b) if a != b else a; gap = e['dist'] * 1000
            if kind == 'coplanar':
                do = ((f'one object, two skins {gap:.1f} mm apart facing the same way: delete the inner faces, or give the mesh one skin' if a == b else
                       f'{top} stands {gap:.1f} mm proud, same-facing: lift it to >= {const.COPLANAR * 1e3:.0f} mm (k.lay lifts {const.LIFT * 1e3:.0f}), '
                       f'or cut its footprint out of the face under it (k.lay(cut=True) / k.cut), or sink it under') )
            else:
                do = (f'faces {gap:.2f} mm apart facing each other: the parts only touch; k.seat({a!r}, {b!r}) moves the contact in, '
                      f'or delete the hidden pair' if a != b else 'a doubled face inside one mesh: delete one (merge by distance does not)')
            _fail(fails, kind, None, e['area'] * 1e4, f'{"no two faces in one place" if kind == "coplanar" else "no duplicate back-to-back faces"} (area cm2)',
                  c, e['n'], radius=max(0.03, rad), objects=[a, b] if a != b else [a], part=a, host=b,
                  plan_part=oa.get('kit3d_part', a) if oa else a, plan_host=ob.get('kit3d_part', b) if ob else b, gap_mm=round(gap, 3),
                  normals=[_p3(e['n']), _p3(e['n2'])], proud=top, do=do)


def _uvs(objs, fails):
    from . import uv
    k = uv.kit(); dg = bpy.context.evaluated_depsgraph_get(); n = 0
    for o in objs:
        if o.type != 'MESH' or not uv.textured(o): continue
        n += 1; ev = o.evaluated_get(dg) if len(o.modifiers) else None
        me = ev.to_mesh() if ev is not None else o.data      # no modifiers: the data itself (no stale depsgraph)
        try:
            c = o.matrix_world.translation; rad = max(0.05, _size(o) / 2)
            if not k.usable_uv(me):
                _fail(fails, 'uv_missing', None, None, 'a UV map (textured: image in its material)', c, radius=rad, part=o.name, plan_part=o.get('kit3d_part', o.name))
                continue
            dsh = uv.degenerate_share(me)
            if dsh > 0.01:
                _fail(fails, 'uv_degenerate', None, dsh * 100, 'degenerate UV area < 1 %', c, radius=rad, part=o.name, plan_part=o.get('kit3d_part', o.name))
            osh = k.uv_overlap_share(me)
            if osh > 0.01:
                _fail(fails, 'uv_overlap', None, osh * 100, 'faces sharing texture space < 1 %', c, radius=rad, part=o.name, plan_part=o.get('kit3d_part', o.name))
        finally:
            if ev is not None: ev.to_mesh_clear()
    return n


_LOOK = None
LOOK_MIN_M = 0.05      # a part with less corner than this (metres of edge x radians turned) is not judged


def _look_mods():
    """(mesh_core, mesh_look.arrays, bands) of the look tools beside kit3d (../look): imported, never copied, so the
    classes and bands here are look.py's own."""
    global _LOOK
    if _LOOK is None:
        d = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'look'))
        if d not in sys.path: sys.path.insert(0, d)
        import mesh_core, mesh_look, bands
        _LOOK = (mesh_core, mesh_look.arrays, {k: bands.BANDS[k][1] for k in ('razor_share', 'facet_share', 'flat_shaded_area')})
    return _LOOK


def _look(objs):
    """Per plan part: share of its corners that are razor (hard, unbevelled, split normals) or facet (a bevel shaded
    flat or with a hard boundary: Bevel Harden Normals + WeightedNormal Keep Sharp) and share of its area that is
    flat-shaded, on the EVALUATED meshes (modifiers on). ADVISORY: look.py's classes and bands, per part, in
    milliseconds, at every step instead of at the end. Returns ({part: numbers}, [parts outside a band, worst first])."""
    mc, arrays, band = _look_mods(); dg = bpy.context.evaluated_depsgraph_get(); per = {}
    for o in objs:
        if o.type != 'MESH' or o.hide_render: continue
        ev = o.evaluated_get(dg); me = ev.to_mesh()
        try:
            a = arrays(me, o.matrix_world)
            if a is None: continue
            r = mc.edges(*a); k = mc.classify(r); w = r['L'] * r['turn']
            p = per.setdefault(o.get('kit3d_part', o.name), {'razor_m': 0.0, 'facet_m': 0.0, 'corner_m': 0.0, 'flat_m2': 0.0,
                                                             'area_m2': 0.0, 'bends': False, 'objects': []})
            p['razor_m'] += float(w[k['razor']].sum()); p['facet_m'] += float(w[k['facet']].sum())
            p['corner_m'] += float(sum(w[m].sum() for m in k.values()))
            p['flat_m2'] += r['flat_area']; p['area_m2'] += r['all_area']
            p['bends'] = p['bends'] or bool((r['turn'] > math.radians(2.0)).any())
            p['objects'].append(o.name)
        finally:
            ev.to_mesh_clear()
    out = []
    for pp, p in per.items():
        c = max(p['corner_m'], 1e-12)
        p['razor'] = round(p['razor_m'] / c, 3) if p['corner_m'] >= LOOK_MIN_M else 0.0
        p['facet'] = round(p['facet_m'] / c, 3) if p['corner_m'] >= LOOK_MIN_M else 0.0
        p['flat'] = round(p['flat_m2'] / max(p['area_m2'], 1e-12), 3) if p['bends'] else 0.0   # one flat sheet may be flat-shaded
        for key in ('razor_m', 'facet_m', 'corner_m', 'flat_m2', 'area_m2'): p[key] = round(p[key], 4)
        p['outside'] = [n for n, v, b in (('razor', p['razor'], band['razor_share']), ('facet', p['facet'], band['facet_share']),
                                          ('flat', p['flat'], band['flat_shaded_area'])) if v > b]
        if p['outside']: out.append(pp)
    out.sort(key=lambda pp: -(per[pp]['razor_m'] + per[pp]['facet_m'] + per[pp]['flat_m2']))
    return per, out


def _reads_object_coords(mat):
    """Does this material wear a shared shader kind (a node group named const.OBJECT_SPACE_GROUPS, 'idle.<kind>@N')
    that reads the Texture Coordinate node's Object output, i.e. the object's own frame? The kinds do, and there
    direction matters: grime rises to an object Z, brushing runs along object X, panels are cells of object space.
    (kit3d's own materials read object space only for an isotropic noise: any frame does.)"""
    def walk(tree, inside, depth=0):
        if tree is None or depth > 6: return False
        for n in tree.nodes:
            if inside and n.type == 'TEX_COORD' and n.object is None and 'Object' in n.outputs and n.outputs['Object'].is_linked: return True
            if n.type == 'GROUP' and n.node_tree is not None and \
               walk(n.node_tree, inside or n.node_tree.name.startswith(const.OBJECT_SPACE_GROUPS), depth + 1): return True
        return False
    return bool(mat and mat.node_tree and walk(mat.node_tree, False))


def _own_frame(objs):
    """Objects that wear an object-space material while sitting in a frame of their own (rotated, scaled or moved)."""
    cache = {}; out = []
    for o in objs:
        if o.type != 'MESH': continue
        M = o.matrix_world
        if all(abs(M[i][j] - (1.0 if i == j else 0.0)) < 1e-6 for i in range(3) for j in range(4)): continue
        for s in o.material_slots:
            m = s.material
            if m is None: continue
            if m.name not in cache: cache[m.name] = _reads_object_coords(m)
            if cache[m.name]: out.append(o.name); break
    return out


def _select(parts):
    allrels = core.rels()
    objs = [o for o in bpy.context.scene.objects if (o.type == 'MESH' or (o.type == 'EMPTY' and o.instance_type == 'COLLECTION'))
            and not o.name.startswith(SKIP_PREFIX)]
    if parts is None:
        sel = [o for o in objs if 'kit3d_part' in o or any(r['part'] == o.name for r in allrels.values())]
        rels = list(allrels.values())
    else:
        ps = set(parts)
        sel = [o for o in objs if o.name in ps or o.get('kit3d_part') in ps]
        names = {o.name for o in sel}
        rels = [r for r in allrels.values() if r['part'] in names or r.get('plan_part') in ps]
    return sel, rels, objs


def check(parts=None, json_path=None, coplanar=True, uvs=True, max_lines=10, look=True):
    """Measure the relations of `parts` (plan part or object names; None = all) and the blink/speckle faults among
    their objects. Returns {'ok', 'text', 'lines', 'fails', 'per_part', 'counts', 'time_s'}; writes json_path."""
    t0 = time.time(); core.update()
    sel, rels, scene_objs = _select(parts)
    fails = []; measured = []; counts = {}
    for r in rels:
        counts[r['kind']] = counts.get(r['kind'], 0) + 1
        try:
            m = _measure(r, fails)
        except Exception as e:
            _fail(fails, 'error', r, None, f'{type(e).__name__}: {e}'[:200], None); m = None
        measured.append(dict(r, measured=m))
    placed = {r['part'] for r in rels}
    for o in sel:
        if o.library is not None: continue          # linked from another builder's file (an external host): theirs to place
        if o.name not in placed and not o.get('kit3d_free') and not o.get('kit3d_root'):
            _fail(fails, 'unplaced', None, None, 'attach/span/lay/into, or free(reason)/root()' if 'kit3d_part' in o else
                  'adopt(obj, part) then into/attach, or delete it (kit3d did not make this object)', o.matrix_world.translation,
                  radius=max(0.05, _size(o) / 2), part=o.name, plan_part=o.get('kit3d_part', o.name))
    hidden = [o.name for o in sel if _excluded(o)]
    stats = {}
    if coplanar: _coplanar([o for o in sel if o.type == 'MESH' or o.type == 'EMPTY'], scene_objs, fails, stats)
    ntex = _uvs(sel, fails) if uvs else 0
    # advisory (never a fail): how each part's corners are shaded, and object-space materials on parts in their own frame
    t1 = time.time(); lk = {}; lk_out = []; own = []; adv = []
    if look:
        try:
            lk, lk_out = _look(sel); own = _own_frame(sel)
        except Exception as e:                       # the look tools missing or broken must never stop the measurement
            adv.append(f'LOOK (advisory) not measured: {type(e).__name__}: {e}'[:160])
    look_s = time.time() - t1
    if lk_out:
        bits = []
        for key, label in (('razor', 'razor'), ('facet', 'facet'), ('flat', 'flat-shaded')):
            ps = [pp for pp in lk_out if key in lk[pp]['outside']]
            if ps: bits.append(f'{label} ' + ', '.join(f'{pp} {lk[pp][key]:.2f}' for pp in ps[:2]) + (f' +{len(ps) - 2}' if len(ps) > 2 else ''))
        adv.append('LOOK (advisory) ' + '; '.join(bits) + ' -> smooth + Bevel, Harden OR WeightedNormal')
    sec = stats.get('second') or []
    if sec:
        adv.append(f'COPLANAR (advisory, read from the smaller side) {len(sec)}: ' + ', '.join(
            f'{x["objects"][1]} on {x["objects"][0]} {x["area_cm2"]:.0f} cm2 gap {x["gap_mm"]:.1f} mm' for x in sec[:2])
            + (f' +{len(sec) - 2}' if len(sec) > 2 else '') + ' -> two faces in one place blink: lift >= 2 mm, cut in, or sink')
    if own:
        adv.append(f'FRAME (advisory) {len(own)} in their own frame under an object-space shader kind: '
                   + ', '.join(own[:3]) + (f' +{len(own) - 3}' if len(own) > 3 else '') + ' -> k.freeze(part)')
    dt = time.time() - t0
    # per plan part flags
    per = {}
    for o in sel:
        pp = o.get('kit3d_part', o.name); per.setdefault(pp, {'relations': True, 'uv': True, 'objects': 0}); per[pp]['objects'] += 1
    for pp, v in lk.items():
        if pp in per: per[pp]['look'] = {k_: v[k_] for k_ in ('razor', 'facet', 'flat', 'outside')}
    for f in fails:
        for key in ('plan_part', 'plan_host'):
            pp = f.get(key)
            if pp in per and (key == 'plan_part' or f['kind'] in ('coplanar', 'back2back')):
                per[pp]['uv' if f['kind'].startswith('uv_') else 'relations'] = False
    ok = not fails
    entries = [x['measured'].get('entry_min_mm') for x in measured if x.get('measured') and x['measured'].get('entry_min_mm') is not None]
    lifts = [x['measured'].get('clear_min_mm') for x in measured if x.get('measured') and not x.get('cut') and x['measured'].get('clear_min_mm') is not None]
    ncut = sum(1 for x in measured if x.get('cut'))
    intos = [x['measured'].get('entry_mm') for x in measured if x['kind'] == 'into' and x.get('measured') and x['measured'].get('entry_mm') is not None]
    kinds = ', '.join(f'{k} {v}' for k, v in sorted(counts.items()))
    lines = [f'kit3d.check {len(sel)} objects, {len(rels)} relations ({kinds}), {ntex} textured, {dt:.2f} s']
    if hidden: lines.append(f'WARN {len(hidden)} objects in hidden/excluded collections are measured WITHOUT modifiers: {", ".join(hidden[:3])}')
    try:
        from .upgrade import shadow_materials
        shadow = shadow_materials()
    except Exception:
        shadow = []
    if shadow:
        lines.append(f'MATERIALS {len(shadow)} that no object uses shadow a used one: ' + ', '.join(f'{u} (used: {v})' for u, v in shadow[:3])
                     + (f' +{len(shadow) - 3}' if len(shadow) > 3 else '') + ' -> edits to them show nowhere: edit the used one, remove the copy')
    if ok:
        e = ', '.join(([f'entry {min(entries):.1f}-{max(entries):.1f} mm'] if entries else []) +
                      ([f'into {min(intos):.1f}-{max(intos):.1f} mm ({len(intos)})'] if intos else [])) or 'no entries'
        l_ = (f', lift >= {min(lifts):.1f} mm' if lifts else '') + (f', {ncut} inlay pockets' if ncut else '')
        nfree = counts.get('free', 0) + counts.get('root', 0)
        lines.append(f'PASS  {e}{l_}, 0 unplaced, 0 coplanar, 0 back-to-back, uv ok' + (f'; free/root {nfree}' if nfree else ''))
        lines += adv[:max(0, max_lines - len(lines) - (1 if json_path else 0))]
    else:
        if adv and max_lines - 2 - (1 if json_path else 0) < 4 + len(adv):      # tight (a build step): one short line
            adv = ['ADVISORY ' + ', '.join(([f'look: {len(lk_out)} parts'] if lk_out else []) + ([f'own frame: {len(own)} objects'] if own else [])
                                           + ([f'coplanar read from the smaller side: {len(sec)} pairs'] if sec else [])
                                           or ['look not measured']) + ' (in the json)']
        max_lines -= len(adv)
        by = {}
        for f in fails: by[f['kind']] = by.get(f['kind'], 0) + 1
        lines.append(f'FAIL {len(fails)}: ' + ', '.join(f'{k} {v}' for k, v in sorted(by.items(), key=lambda x: -x[1])))
        room = max_lines - len(lines) - (1 if json_path else 0) - (1 if len(fails) > max_lines - len(lines) - (1 if json_path else 0) else 0)
        for f in fails[:max(1, room)]:
            val = '' if f['value_mm'] is None else (f' {f["value_mm"]:.1f} cm2' if f['kind'] in ('coplanar', 'back2back') else
                                                   f' {f["value_mm"]:.1f} %' if f['kind'] in ('uv_degenerate', 'uv_overlap') else f' {f["value_mm"]:.1f} mm')
            rel = f' ({f.get("label") or f["rel"]})' if f.get('rel') else ''
            where = f' at ({", ".join(f"{x:.2f}" for x in f["world"])})' if f.get('world') else ''
            tgt = f' -> {f["host"]}' if f.get('host') and f['host'] != f['part'] else ''
            if f['kind'] in ('coplanar', 'back2back') and f.get('do'):
                nn = '/'.join('(' + ','.join(f'{x:.1f}' for x in n_) + ')' for n_ in f.get('normals', []))
                lines.append(f' {f["kind"]}{val}  {f["part"]}{tgt}{where}, gap {f["gap_mm"]:.2f} mm, normals {nn}; {f["do"]}')
            else:
                lines.append(f' {f["kind"]}{val}  {f["part"]}{tgt}{rel}{where}; need {f["need"]}' + (f'; {f["do"]}' if f.get('do') else ''))
        if len(fails) > room: lines.append(f' ... {len(fails) - room} more in the json')
        max_lines += len(adv); lines += adv
    out = {'ok': ok, 'time_s': round(dt, 3), 'counts': counts, 'objects': len(sel), 'textured': ntex,
           'fails': fails, 'per_part': per, 'relations': measured, 'hidden': hidden, 'coplanar_pairs': stats,
           'look': {'advisory': True, 'time_s': round(look_s, 4), 'parts': lk, 'outside': lk_out, 'own_frame': own, 'lines': adv},
           'shadow_materials': [list(x) for x in shadow], 'blend': bpy.data.filepath, 'parts': parts}
    if json_path:
        os.makedirs(os.path.dirname(os.path.abspath(json_path)), exist_ok=True)
        tmp = json_path + '.tmp'
        with open(tmp, 'w') as fh: json.dump(out, fh, indent=1, default=str)
        os.replace(tmp, json_path); lines.append(f'json {json_path}')
    out['lines'] = lines[:max_lines]; out['text'] = '\n'.join(out['lines'])
    return out
