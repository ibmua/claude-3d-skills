"""A near or mid game version with LIVE material slots (a design decision: "materials stay shaders through near and mid; only far
may be fully baked"; owner 2026-10-15: "not to bake anything ... except for low quality assets", and 18:18 "it still
seems to have baked it"). lods_all.py runs this for near and mid instead of bake.py + export_game.py; far still bakes.

  blender -b WORK.blend --python live_version.py -- --high COLL --low COLL --level near|mid --out VERSION.blend
        --tex DIR [--size 512] [--exclude GLOBS] [--live GLOBS] [--merge '{"dark_cover":"bezel"}'] [--no-normal SLOTS]
        [--name ROOT] [--root-props JSON] [--mounts 'mount.*,light.*,fx.*'] [--report JSON]

The version's geometry (--low: a given GAME_<level> collection or simplify.py's output, already UV-packed by uvpack.py)
is joined into one object `surface`. Then:
1. Every low face takes the material of the original surface it shows: rays from 7 points on the triangle back along
   its normal into the --high parts (first hit within 3 cm facing the same way, else the nearest surface), area-weighted
   vote. --merge folds slots (a 6 mm screw is 0.3 px at mid); faces whose vote merges to null take their second vote.
2. ONLY what geometry knows is baked, high -> low: a tangent normal map, and the wear mask carried over texel for texel
   (each library-kind material's Mask image, (1,0,1) = neutral elsewhere). Rays that meet a wrong surface are flattened.
3. Slots, one material each, named as in the original (the game drives looks by material name):
   - a library kind (`idle.<kind>@<ver>` group): a COPY of the original material, the version's mask and normal wired
     into Mask / Base Normal; export_original.py writes it as the library contract (extras.idle) -> drawn live.
   - a plain Principled with constant values: a copy, plus the normal map.
   - anything else (a printed image, a decal, a procedural graph): its colour, rough/metal and emission are PROJECTED
     onto the low's UVs from the original surface (an image moved to new UVs). Listed as `projected` in the report so
     the summary says which slots are pictures, not shaders; a procedural one belongs in the library as a kind.
4. --live parts (screens, glow cards) and the mounts/lights/fx empties go along unchanged, under one root empty.
Saves VERSION.blend holding only the collection LIVE_<level>; lods_all.py exports it with export_original.py.
Generalised from the an earlier asset's assembly/live_versions.py (corner repair session, 2026-10-15)."""
import argparse, json, os, sys, time
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _kit as K
import bpy, bmesh
import numpy as np
from mathutils.bvhtree import BVHTree

ap = argparse.ArgumentParser(prog='live_version.py')
ap.add_argument('--high', required=True); ap.add_argument('--low', required=True); ap.add_argument('--level', required=True, choices=('near', 'mid'))
ap.add_argument('--out', required=True); ap.add_argument('--tex', required=True); ap.add_argument('--size', type=int, default=512)
ap.add_argument('--exclude', default=''); ap.add_argument('--live', default=''); ap.add_argument('--merge', default='{}')
ap.add_argument('--no-normal', default=''); ap.add_argument('--name', default=''); ap.add_argument('--root-props', default='{}')
ap.add_argument('--mounts', default='mount.*,light.*,fx.*'); ap.add_argument('--report', default='')
ap.add_argument('--threads', type=int, default=8)
A = ap.parse_args(K.script_argv())
T0 = time.time(); LV = A.level; os.makedirs(A.tex, exist_ok=True)
MERGE = json.loads(A.merge) if A.merge else {}
NO_NORMAL = set(K.csv(A.no_normal)); EXCL = K.csv(A.exclude); LIVE = K.csv(A.live); MOUNTS = K.csv(A.mounts)
log = lambda *a: print('[live]', *a, flush=True)

high_c = bpy.data.collections.get(A.high); low_c = bpy.data.collections.get(A.low)
if not high_c or not low_c: K.die(f'collections {A.high!r} / {A.low!r} not both in the file')
parts = [o for o in high_c.all_objects if o.type == 'MESH' and not K.match(o.name, EXCL + LIVE) and o.visible_get()]
lives = [o for o in high_c.all_objects if o.type == 'MESH' and K.match(o.name, LIVE)]
empties = [o for o in high_c.all_objects if o.type == 'EMPTY' and K.match(o.name, MOUNTS)]
lows = [o for o in low_c.all_objects if o.type == 'MESH' and not K.match(o.name, EXCL + LIVE)]
if not parts or not lows: K.die(f'nothing to work with: {len(parts)} original parts, {len(lows)} version meshes')

dg = bpy.context.evaluated_depsgraph_get()
trees = []
for o in parts:
    me = o.evaluated_get(dg).to_mesh()
    vs = [o.matrix_world @ v.co for v in me.vertices]
    mats = [(me.materials[p.material_index].name if me.materials and me.materials[p.material_index] else None) for p in me.polygons]
    nrm = [(o.matrix_world.to_3x3() @ p.normal).normalized() for p in me.polygons]
    trees.append((BVHTree.FromPolygons(vs, [tuple(p.vertices) for p in me.polygons]), mats, nrm))
    o.evaluated_get(dg).to_mesh_clear()

# the version as ONE triangulated object with its UVs (uvpack.py's 'UVMap' or the first map)
lc = bpy.data.collections.new(f'LIVE_{LV}'); bpy.context.scene.collection.children.link(lc)
bm = bmesh.new()
for o in lows:
    me = o.evaluated_get(dg).to_mesh(); t = bmesh.new(); t.from_mesh(me); t.transform(o.matrix_world)
    m2 = bpy.data.meshes.new('tmp'); t.to_mesh(m2); t.free(); bm.from_mesh(m2); bpy.data.meshes.remove(m2)
    o.evaluated_get(dg).to_mesh_clear()
bmesh.ops.triangulate(bm, faces=bm.faces[:])
# slivers of ~0 area (an n-gon's triangulation) have no tangent: glTF-Validator ACCESSOR_VECTOR3_NON_UNIT refuses the file
nf = len(bm.faces); bmesh.ops.dissolve_degenerate(bm, dist=1e-4, edges=bm.edges[:])
bmesh.ops.triangulate(bm, faces=bm.faces[:])
def _thin(f):                                    # a needle: width under 0.1 % of its length (collinear corners)
    a, b, c = (v.co for v in f.verts); l2 = max((b - a).length_squared, (c - b).length_squared, (a - c).length_squared, 1e-20)
    return (b - a).cross(c - a).length < 1e-3 * l2
needles = [f for f in bm.faces if _thin(f)]
bmesh.ops.delete(bm, geom=needles, context='FACES_ONLY')
if len(bm.faces) != nf: log(f'{nf - len(bm.faces)} sliver and needle triangles (< 0.1 mm, or thinner than 0.1 % of their length) removed')
lme = bpy.data.meshes.new(f'{LV}_surface'); bm.to_mesh(lme); bm.free()
low = bpy.data.objects.new('surface', lme); lc.objects.link(low)
if not lme.uv_layers: K.die(f'{A.low}: the version has no UV map (run uvpack.py first)')
uvname = 'UVMap' if 'UVMap' in lme.uv_layers else lme.uv_layers[0].name
lme.uv_layers.active = lme.uv_layers[uvname]
# a UV triangle squashed to a line (under 1 % of a texel) has no tangent (glTF-Validator ACCESSOR_VECTOR3_NON_UNIT, export refused; the low ticket
# validator's hand-built near had 2): open it to a 1-texel triangle at its own place, which samples what it sampled
uvd = lme.uv_layers[uvname].data; opened = 0; e = 1.0 / A.size
for p in lme.polygons:
    li = list(p.loop_indices); a, b, c = (uvd[i].uv.copy() for i in li)
    l2 = max((b - a).length_squared, (c - b).length_squared, (a - c).length_squared, 1e-20)
    if abs((b - a).cross(c - a)) < max(0.02 * e * e, 1e-3 * l2):   # a line in UV (thin for its length): no tangent
        m_ = (a + b + c) / 3; uvd[li[0]].uv = m_; uvd[li[1]].uv = (m_.x + e, m_.y); uvd[li[2]].uv = (m_.x, m_.y + e); opened += 1
if opened: log(f'{opened} UV triangles squashed to a line opened to 1 texel (no tangent otherwise)')


def shows(p, n):
    best = None
    for t, mats, nrm in trees:
        hit = t.ray_cast(p + n * 0.012, -n, 0.03)
        if hit[0] is not None and nrm[hit[2]].dot(n) > 0.2 and (best is None or hit[3] < best[1]): best = (mats[hit[2]], hit[3])
    if best: return best[0], 1.0
    near = min(((mats[r[2]], r[3]) for t, mats, nrm in trees for r in [t.find_nearest(p, 0.05)] if r[0] is not None),
               key=lambda x: x[1], default=(None, 0))
    return near[0], 0.5


area = defaultdict(float); face_mat = []; unseen = 0
for poly in lme.polygons:
    c = poly.center; n = poly.normal.normalized(); vw = [lme.vertices[i].co for i in poly.vertices]
    pts = [c] + [(vw[0] * a + vw[1] * b + vw[2] * (5 - a - b)) / 5 for a in range(1, 4) for b in range(1, 4) if 1 <= 5 - a - b]
    v = defaultdict(float)
    for p in pts:
        m, w = shows(p, n)
        if m: v[m] += w * poly.area
    pick = next((MERGE.get(m, m) for m in sorted(v, key=lambda k: -v[k]) if MERGE.get(m, m) is not None), None)
    if pick is None: unseen += 1; pick = max(area, key=area.get) if area else next(iter(v), None)
    face_mat.append(pick); area[pick] += poly.area
slots = [s for s in sorted(area, key=lambda s: -area[s]) if s]
log(f'{len(lme.polygons)} triangles -> slots {[(s, round(area[s] * 1e4, 1)) for s in slots]} (cm2); {unseen} faces without a vote')

# ---------------------------------------------------------------- bakes high -> low: normal, wear mask, projections
K.set_threads(A.threads, 4)
scn = bpy.context.scene; scn.render.engine = 'CYCLES'; scn.cycles.device = 'CPU'
bk = scn.render.bake; bk.use_selected_to_active = True; bk.cage_extrusion = 0.004; bk.max_ray_distance = 0.02; bk.margin = 8
tgt = bpy.data.materials.new('bake_target'); tgt.use_nodes = True; lme.materials.clear(); lme.materials.append(tgt)
for x in bpy.context.view_layer.objects: x.select_set(False)
for o in parts: o.hide_set(False); o.hide_render = False; o.select_set(True)
low.select_set(True); bpy.context.view_layer.objects.active = low


def target(name, colour=False, float_=False):
    im = bpy.data.images.new(f'{A.name or "asset"}_{LV}_{name}', A.size, A.size, alpha=False, float_buffer=float_)
    if not colour: im.colorspace_settings.name = 'Non-Color'
    nt = tgt.node_tree; [nt.nodes.remove(n) for n in [n for n in nt.nodes if n.type == 'TEX_IMAGE']]
    ti = nt.nodes.new('ShaderNodeTexImage'); ti.image = im; nt.nodes.active = ti; ti.select = True
    return im


def bake(kind):
    r = bpy.ops.object.bake(type=kind, **({'normal_space': 'TANGENT'} if kind == 'NORMAL' else {}),
                            use_selected_to_active=True, cage_extrusion=0.004, max_ray_distance=0.02, margin=8)
    if 'FINISHED' not in r: K.die(f'bake {kind} was {r}')


def px(im): a = np.empty(A.size * A.size * 4, np.float32); im.pixels.foreach_get(a); return a.reshape(-1, 4)


hmats = {s.material for o in parts for s in o.material_slots if s.material}
kinds = {m.name for m in hmats if K.idle_record(m)}
NORMAL = target('normal'); bake('NORMAL')
a = px(NORMAL); v = a[:, :3] * 2 - 1; bad = v[:, 2] <= 0                 # a ray met a wrong surface: flat
v[bad] = (0, 0, 1); v /= np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-6); a[:, :3] = v * .5 + .5
NORMAL.pixels.foreach_set(a.ravel()); flat_share = float(bad.mean())

# the wear mask: each kind material emits its own Mask image (with the UV map that image reads), others (1,0,1)
saved = []
for m in hmats:
    nt = m.node_tree; on = K.output_node(m) if nt else None
    if on is None: continue
    saved.append((m, on.inputs['Surface'].links[0].from_socket if on.inputs['Surface'].is_linked else None))
    em = nt.nodes.new('ShaderNodeEmission'); em.name = K.TMP + 'mask'; em.inputs['Color'].default_value = (1, 0, 1, 1)
    g = on.inputs['Surface'].links[0].from_node if m.name in kinds else None
    mk = g.inputs.get('Mask') if g is not None else None
    if mk is not None and mk.is_linked: nt.links.new(mk.links[0].from_socket, em.inputs['Color'])
    nt.links.new(em.outputs[0], on.inputs['Surface'])
MASK = target('mask'); bake('EMIT')
for m, src in saved:
    nt = m.node_tree; [nt.nodes.remove(n) for n in [n for n in nt.nodes if n.name == K.TMP + 'mask']]
    if src is not None: nt.links.new(src, K.output_node(m).inputs['Surface'])
a = px(MASK); miss = a[:, :3].sum(1) < 1e-4; a[miss] = (1, 0, 1, 1); MASK.pixels.foreach_set(a.ravel())


def plain(m):
    on = K.output_node(m) if m and m.node_tree else None
    p = on.inputs['Surface'].links[0].from_node if on and on.inputs['Surface'].is_linked else None
    return p is not None and p.type == 'BSDF_PRINCIPLED' and not any(p.inputs[k].is_linked for k in ('Base Color', 'Roughness', 'Metallic', 'Emission Color', 'Emission Strength', 'Alpha'))


projected = [s for s in slots if s not in kinds and not plain(bpy.data.materials.get(s))]
PROJ = {}; EMIT_PEAK = 1.0
if projected:
    scn.cycles.samples = 32                              # printed edges anti-aliased (4 samples drew the ring jagged)
    swap = K.MaterialSwap(list(hmats))
    for ch in ('color', 'packed'):
        swap.set(ch); PROJ[ch] = target('proj_' + ch, colour=(ch == 'color')); bake('EMIT')
    swap.restore()
    if K.has_emission([bpy.data.materials[s] for s in projected]):
        # glow is brighter than 1: an 8-bit target clipped the reader ring (lodcmp night -11 %); bake float, store the
        # picture normalised to its peak and the peak as Emission Strength (as export_original.py does)
        im = target('proj_emit', colour=True, float_=True); bake('EMIT'); e = px(im); EMIT_PEAK = max(float(e[:, :3].max()), 1.0)
        e[:, :3] = K.srgb_encode(e[:, :3] / EMIT_PEAK); e[:, 3] = 1
        PROJ['emit'] = bpy.data.images.new(im.name + '_n', A.size, A.size, alpha=False); PROJ['emit'].pixels.foreach_set(e.ravel())
for im in [NORMAL, MASK, *PROJ.values()]:
    im.filepath_raw = os.path.join(A.tex, im.name + '.png'); im.file_format = 'PNG'; im.save()

# ---------------------------------------------------------------- slot materials
lme.materials.clear(); idx = {}


def uvnode(nt): u = nt.nodes.new('ShaderNodeUVMap'); u.uv_map = uvname; return u


def teximg(nt, im):
    t = nt.nodes.new('ShaderNodeTexImage'); t.image = im; nt.links.new(uvnode(nt).outputs[0], t.inputs['Vector']); return t


def normal_into(nt, sock):
    nm = nt.nodes.new('ShaderNodeNormalMap'); nm.uv_map = uvname
    nt.links.new(teximg(nt, NORMAL).outputs['Color'], nm.inputs['Color']); nt.links.new(nm.outputs['Normal'], sock)


how = {}
for s in slots:
    src = bpy.data.materials[s]; m = src.copy(); m.name = f'{s}@{LV}'; nt = m.node_tree; on = K.output_node(m)
    if s in kinds:
        g = on.inputs['Surface'].links[0].from_node
        w = teximg(nt, MASK); w.interpolation = 'Closest'
        nt.links.new(w.outputs['Color'], g.inputs['Mask'])
        if g.inputs.get('Mask Alpha') is not None: nt.links.new(w.outputs['Alpha'], g.inputs['Mask Alpha'])
        if s not in NO_NORMAL and g.inputs.get('Base Normal') is not None: normal_into(nt, g.inputs['Base Normal'])
        m['idle'] = json.dumps(K.idle_record(src)); how[s] = 'live kind'
    elif s not in projected:
        p = on.inputs['Surface'].links[0].from_node
        if s not in NO_NORMAL and not p.inputs['Normal'].is_linked: normal_into(nt, p.inputs['Normal'])
        how[s] = 'constant'
    else:
        for n in [n for n in nt.nodes if n != on]: nt.nodes.remove(n)
        p = nt.nodes.new('ShaderNodeBsdfPrincipled'); nt.links.new(p.outputs[0], on.inputs['Surface'])
        nt.links.new(teximg(nt, PROJ['color']).outputs['Color'], p.inputs['Base Color'])
        sp = nt.nodes.new('ShaderNodeSeparateColor'); nt.links.new(teximg(nt, PROJ['packed']).outputs['Color'], sp.inputs[0])
        nt.links.new(sp.outputs['Red'], p.inputs['Roughness']); nt.links.new(sp.outputs['Green'], p.inputs['Metallic'])
        if 'emit' in PROJ:
            nt.links.new(teximg(nt, PROJ['emit']).outputs['Color'], p.inputs['Emission Color']); p.inputs['Emission Strength'].default_value = EMIT_PEAK
        if s not in NO_NORMAL: normal_into(nt, p.inputs['Normal'])
        how[s] = 'projected picture'
    m.use_backface_culling = True
    idx[s] = len(lme.materials); lme.materials.append(m)
lme.polygons.foreach_set('material_index', np.array([idx.get(s, 0) for s in face_mat], np.int32))
for poly in lme.polygons: poly.use_smooth = False

# ---------------------------------------------------------------- live parts, empties, root; keep only LIVE_<level>
root = bpy.data.objects.new(A.name or f'asset_{LV}', None); lc.objects.link(root)
for k_, v_ in (json.loads(A.root_props) if A.root_props else {}).items(): root[k_] = v_
root['lod'] = LV
keep = {low, root}
for o in lives + empties:
    c = o.copy(); lc.objects.link(c); c.parent = None; c.matrix_world = o.matrix_world.copy(); keep.add(c); c['_src'] = o.name
for o in keep - {root}:
    mw = o.matrix_world.copy(); o.parent = root; o.matrix_world = mw
for o in list(bpy.data.objects):
    if o not in keep: bpy.data.objects.remove(o, do_unlink=True)
for c in list(bpy.data.collections):
    if c != lc: bpy.data.collections.remove(c)
for o in keep:
    if '_src' in o: n = o['_src']; del o['_src']; o.name = n
for m in list(bpy.data.materials):
    if m.users == 0: bpy.data.materials.remove(m)
mine = {m.name for m in lme.materials}
for m in bpy.data.materials:
    if m.name not in mine and m.name in {x.rsplit('@', 1)[0] for x in mine}: m.name = m.name + '.src'
for m in lme.materials: m.name = m.name.rsplit('@', 1)[0]
bpy.ops.file.make_paths_absolute(); bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(A.out))
rep = dict(tool='3d-asset-making/scripts/live_version.py', level=LV, triangles=len(lme.polygons), slots=how,
           area_cm2={s: round(area[s] * 1e4, 1) for s in slots}, projected=projected, size=A.size,
           mask_texels_filled=round(float(miss.mean()), 4), normal_texels_flattened=round(flat_share, 4),
           images=[im.filepath_raw for im in [NORMAL, MASK, *PROJ.values()]], seconds=round(time.time() - T0, 1))
if A.report:
    with open(A.report, 'w') as f: json.dump(rep, f, indent=1)
print('LIVE_VERSION', json.dumps(rep), flush=True)
