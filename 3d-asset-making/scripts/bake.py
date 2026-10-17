"""Bake a film original onto a game version's UV atlas (selected-to-active, headless Blender).

  nice -n 10 blender -b ORIGINAL.blend --python bake.py -- --low LOW --out DIR [--size 2048]
        [--maps color,rough,metal,normal,emit,ao[,alpha]] [--threads 8] [--samples 4] [--prefix near]
        [--ao-distance M] [--ao-samples 256] [--ao-blur 0]
        [--high COLL[,COLL]] [--exclude GLOB[,GLOB]] [--decals GLOB[,GLOB]] [--glass-collection NAME]
        [--glass-through MATERIAL_GLOB[,..]]
        [--uv NAME] [--extrusion M] [--max-ray M] [--normal-extrusion M] [--normal-max-ray M]
        [--margin PX] [--glass-color R,G,B] [--glass-alpha 0.7] [--normal-min-z 0.35]
        [--verify-metal 0.1] [--verify-de 8] [--no-verify]
        [--verify-only --verify-maps color=PNG,mr=PNG]   (check maps that already exist, e.g. another builder's)

LOW    the game mesh: a collection or object in ORIGINAL.blend, or OTHER.blend[:COLLECTION]. Its mesh objects share
       one UV atlas (uvpack.py makes one); objects named *glass* (or in --glass-collection, or with custom prop
       glass=1) are the glass batch and are NOT baked (export_game.py gives them their own alpha material).
--extrusion / --max-ray  default: an AUTOMATIC CAGE OBJECT per version. Every low triangle's depth under the
       original's outer surface is measured (rays walked outward) and a cage mesh is built with each vertex pushed
       out just past the deepest of its triangles, so no ray starts inside the hull and lands on an inner wall (the
       a train car's white steel; its near's B-end wall sits > 7 cm inside the bulkhead while the sides fit tightly,
       which one extrusion cannot serve). --extrusion M gives a uniform extrusion instead. In the json: `cage`.
       Then a start check: from the cage inward the FIRST surface met must face the cage. A back face first while
       the cage point itself is inside a solid of the original (the first surface outward faces away from it: between
       the skins of a thickened wall, inside the hull) AND that face is another material than the surface seen there
       from outside, on more than 2 % of samples -> refused (places + materials in <prefix>_start_check.json;
       --allow-inside-start overrides); a single-sided sheet seen from behind is only counted. The low atlas
       must not be covered twice (> 1 % overlap: a Solidify inner skin, mirrored halves) -> refused: run uvpack.
--high the collections that are the original (default: everything visible except the low). Name it when the file
       also holds part libraries, review props or other versions (they would be baked in).
--exclude  glob(s) over object / instancer / instanced-collection names left out of the bake (e.g. an interior
       liner the low's inner skin must not pick up: 'C.saloon_liner').
--glass-through  material glob(s) whose faces are left out of the original, so rays see what is behind them
       (a clear headlight lens over its chrome reflector; without it the lens bakes as a dark pane).
--decals   glob(s) of decal sheets. Objects whose materials are all alpha cut-outs are decals automatically.

What it does (each step a lesson from two train cars rebuilds, 2026-10-12):
 * Realises the original: every object and collection instance (nested too) with modifiers applied, its WORLD matrix
   baked into the mesh and faces flipped where the matrix mirrors (det < 0); otherwise mirrored mounts bake inside
   out and render black. All parts become ONE high object (baking against 1,500 objects is many times slower).
   Each part's own texture space is kept (Texture Coordinate Object/Generated and Object Info Location/Random/Color
   are pinned as attributes), so procedural materials look as they did on the separate parts.
 * Colour, roughness, metal (and alpha) are baked through EMISSION from the material's own inputs; Mix/Add shaders
   become colour mixes by the same factor, so layered node materials (paint over primer by a wear mask) bake right.
   Never the DIFFUSE pass (it is base x (1 - metallic): metal bakes black). Clear glass in the original bakes as a
   dark pane (--glass-color, linear) with low roughness; tinted glass (red/amber lamps) keeps its tint;
   --glass-through drops named lenses so the reflector behind them is baked instead.
 * Decals are left out of the base and normal passes and baked on their own (colour + alpha), then laid over the
   base colour by their alpha, so a cut-out shows the paint under it, never black.
 * Normal: tangent space of the low's triangulated mesh (the same triangles export_game.py writes). Ray misses and
   turned texels (z < --normal-min-z) become flat.
 * Emission (night lights): the original's own emission as it is set in the file; stored as an sRGB texture scaled
   to its peak, the peak written as `emit_strength` (glTF KHR_materials_emissive_strength).
 * Ambient occlusion (`ao`, on by default; owner 2026-10-13 16:41 "we defo wanna import all the effects we've missed"):
   the game has no SSAO, so the contact darkness in seams, gaps, louvres and window insets that the low version
   flattens comes only from this map. Cycles AO bake, selected-to-active through the same cage, so occlusion is
   measured on the HIGH original at the surface the low shows (detail the low lacks still occludes); the low itself,
   the cage and the decal sheets are not occluders. --ao-distance (default 2.5 % of the original's diagonal, clamped
   to 0.05-1.0 m: 0.28 m on an 11 m car, 0.06 m on a door) is how far an occluder still counts. --ao-samples 256 rays
   per texel (Cycles adaptive sampling stops early: a car near 2048 px, 64 samples 14.5 s, 512 18.4 s); no blur by
   default (measured on a car near against 512 samples: 64 samples leave rms 0.027 noise, and a sigma-1 blur ADDS
   error, rms 0.058, because seams and gaskets are 1-2 texels wide); --ao-blur S (texel sigma at --size, over hit
   texels only, so background and other islands do not bleed in) is there for cheap low-sample bakes. Stored in R of the packed mr image (glTF ORM: R occlusion, G roughness,
   B metal: one texture, no extra fetch); without rough/metal maps it is its own <prefix>_ao.png (grey). Flat faces
   and misses get 1 (no occlusion). export_game.py writes it as the material's occlusionTexture (three.js aoMap: it
   darkens only the hemisphere and environment light, never the sun). The bake.json `ao` block has distance, samples,
   median / p5 and the share of texels darker than 0.5. The colour, rough and metal self-check never reads it.
 * Misses are measured, not hidden: every pass starts from a sentinel, so texels inside the atlas that no ray hit
   are counted (`miss_share` per pass, a _miss.png mask above 0.5 %). Raise --max-ray / --extrusion when it is high.
 * Padding: --margin px of crisp dilation around every island, then a pyramid fill of the whole atlas (no hard
   background reaches a mip level). Faces of the low whose material has custom prop `flat` (or `flat_color`
   [r,g,b] linear or '#rrggbb', `flat_rough`, `flat_metal`) get those flat values (interior walls, floors the
   original does not have).

Self-check (owner fault 2026-10-12: a train car side steel baked white, metallic 0.23 instead of 0.55, because the
rays also reached the interior wall): per face group of the low (+x -x +y -y up down) 400 points compare the baked
metal / roughness / colour with the original's material of the surface a viewer SEES there: the first original
surface met by a ray coming in along the low's normal from well outside (8 % of the diagonal), independent of the
cage (plain values only; procedural ones are 'not checkable'). The nearest-surface drift is reported too
(metal_drift_nearest, info: on a coarse far version the nearest surface is often a part the low cuts through).
Drift = mean of the best 90 % of samples (robust to a few ambiguous places, still moved by a systematic error). Metal drift > --verify-metal or colour dE >
--verify-de (with >= 20 samples) -> FAULT, the maps
are still written for a look, exit 1, and export_game.py refuses them (unless --allow-bake-drift).

--slots FILE --level near|mid|far  game material slots (the game trains, GAME-CONTRACT.md; format in _kit.py
       'game material slots' and SKILL.md): every low triangle gets the game role of the original surface it shows
       (rays from outside along its normal at 4 points, majority; the whole original incl. --glass-through lenses);
       role texels then hold only a grey multiplier (baked luminance / the slot's median, clipped to 1: AO, wear,
       dirt) in <prefix>_slotcolor.png, the unmapped '.baked' slot the full colour; <prefix>_slots.json carries the
       per-triangle roles, each slot's colour and area, and the share of triangles whose votes disagreed.
--skip-pbr-check  pbr_check.py (when on disk) refuses M2/M5/M11 material errors in the original before baking
       (`--for-bake --bake 32`, ~20 s: M2 is measurable on textured base colours, M11 fires on coated in-between metal
       the bake cannot carry). --class-map asset.json: its "materials" classes (default: the asset.json beside the
       .blend); --pbr-bake N samples (0 = values only).
Writes DIR/<prefix>_{color,rough,metal,mr,normal,emit,ao}.png (mr = glTF ORM: R occlusion (1 when ao is not baked),
G rough, B metal; ao.png = the occlusion alone, for a look and for versions without mr) and
DIR/<prefix>_bake.json (what was baked, timings, miss shares, emission strength, UV hash). Never saves the .blend.
the build box is shared: run under `nice -n 10`, at most 8 threads, one bake at a time.
"""
import argparse, json, math, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _kit as K

ap = argparse.ArgumentParser(prog='bake.py', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('--low', required=True); ap.add_argument('--out', required=True)
ap.add_argument('--size', type=int, default=2048); ap.add_argument('--maps', default='color,rough,metal,normal,emit,ao')
ap.add_argument('--ao-distance', type=float, help='AO: how far an occluder counts (m); default 2.5 %% of the diagonal, 0.05-1.0 m')
ap.add_argument('--ao-samples', type=int, default=256); ap.add_argument('--ao-blur', type=float, default=0.0,
                help='AO: Gaussian sigma in texels at --size, over hit texels only (0 = none)')
ap.add_argument('--threads', type=int, default=8); ap.add_argument('--samples', type=int, default=4)
ap.add_argument('--prefix'); ap.add_argument('--high', default=''); ap.add_argument('--exclude', default='')
ap.add_argument('--decals', default=''); ap.add_argument('--glass-through', default=''); ap.add_argument('--no-auto-decals', action='store_true')
ap.add_argument('--glass-collection', default=''); ap.add_argument('--uv')
ap.add_argument('--extrusion', type=float); ap.add_argument('--max-ray', type=float)
ap.add_argument('--normal-extrusion', type=float); ap.add_argument('--normal-max-ray', type=float)
ap.add_argument('--margin', type=int); ap.add_argument('--glass-color', default='0.06,0.075,0.09')
ap.add_argument('--verify-metal', type=float, default=0.1); ap.add_argument('--verify-de', type=float, default=8.0)
ap.add_argument('--no-verify', action='store_true'); ap.add_argument('--allow-missing-images', action='store_true'); ap.add_argument('--allow-inside-start', action='store_true'); ap.add_argument('--verify-only', action='store_true'); ap.add_argument('--verify-maps', default='')
ap.add_argument('--glass-alpha', type=float, default=0.7); ap.add_argument('--normal-min-z', type=float, default=0.35)
ap.add_argument('--slots', default=''); ap.add_argument('--level', choices=('near', 'mid', 'far'))
ap.add_argument('--skip-pbr-check', action='store_true'); ap.add_argument('--class-map', default='')
ap.add_argument('--slot-fit', type=float, default=0.12, help='slots: a body/stripe/trim triangle whose texels miss grey x the '
                'slot colour by more than this (linear, mean of max channel) goes to the baked slot')
ap.add_argument('--pbr-bake', type=int, default=32)
A = ap.parse_args(K.script_argv())

import bpy, bmesh
import numpy as np

T0 = time.time()
S = A.size; MAPS = K.csv(A.maps); MARGIN = A.margin if A.margin is not None else max(4, S // 128)
os.makedirs(A.out, exist_ok=True)
glass = dict(K.GLASS, color=tuple(K.floats(A.glass_color, 3)) + (1.0,), alpha=A.glass_alpha)
import resource
log = lambda *a: print('[bake]', *a, f'(peak {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} MB)', flush=True)

# ------------------------------------------------------------------------------------------------ the low version
low_objs, low_label = K.resolve(A.low)
gcol = bpy.data.collections.get(A.glass_collection) if A.glass_collection else None
gnames = {o.name for o in gcol.all_objects} if gcol else set()
surf = [o for o in low_objs if o.type == 'MESH' and not (o.name in gnames or K.is_glass_obj(o))]
if not surf: K.die(f'no surface mesh in {A.low}: {[o.name for o in low_objs]}')
prefix = A.prefix or ''.join(c if c.isalnum() or c in '-_' else '_' for c in low_label)
low = K.low_copy(surf, A.uv, 'KIT_BAKE_LOW')
uvs, mat_idx, tri_area = K.tri_arrays(low.data)
_flatm = [i for i, m in enumerate(low.data.materials) if m and (m.get('flat') or 'flat_color' in m)]
_ov = K.raster_uv(uvs[~np.isin(mat_idx, _flatm)], S, count=True)
_ovs = float((_ov > 1).sum() / max(1, (_ov > 0).sum()))
if _ovs > 0.01:     # (flat faces share their square on purpose; Solidify skins sharing texels bake over each other)
    K.die(f'{_ovs:.1%} of the low atlas is covered twice (overlapping UVs: a Solidify inner skin, mirrored halves): '
          f'the last face baked would win. Run uvpack.py on {A.low} first')
log(f'low {low_label}: {len(surf)} mesh(es) {[o.name for o in surf]}, {len(uvs)} triangles')

# flat faces (custom props on the low's materials)
def hexlin(h):
    h = h.lstrip('#'); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
flat = {}
for i, m in enumerate(low.data.materials):
    if not m or not (m.get('flat') or 'flat_color' in m): continue
    p = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if m.node_tree else None
    c = m.get('flat_color'); c = hexlin(c) if isinstance(c, str) else (list(c)[:3] if c is not None else
                                  (list(p.inputs['Base Color'].default_value)[:3] if p else [0.5] * 3))
    flat[i] = dict(color=c, rough=float(m.get('flat_rough', p.inputs['Roughness'].default_value if p else 0.6)),
                   metal=float(m.get('flat_metal', p.inputs['Metallic'].default_value if p else 0.0)), name=m.name)
inside = K.raster_uv(uvs, S)
flat_mask = {}
if flat:
    idmap = K.raster_uv(uvs, S, ids=mat_idx)
    for i in flat: flat_mask[i] = idmap == i
any_flat = np.zeros((S, S), bool)
for v in flat_mask.values(): any_flat |= v
log(f'atlas coverage {inside.mean():.1%}, flat materials {[f["name"] for f in flat.values()]}')

# ------------------------------------------------------------------------------------------------ pbr pre-flight
# (standards research 2026-10-13): pbr_check.py on the original's materials; M2 white-plastic metal, M5 declared class
# contradicted, M11 clear coat lost -> refused before any bake (guarded: skipped while pbr_check.py is not on disk)
PBR = dict(available=False, errors=[], lines=['--skip-pbr-check'])
if not A.skip_pbr_check and not A.verify_only:
    PBR = K.pbr_check((['--collection', K.csv(A.high)[0]] if A.high else []) + ['--for-bake'] +
                      (['--bake', str(A.pbr_bake)] if A.pbr_bake else []) + (['--class-map', A.class_map] if A.class_map else []),
                      blender_file=bpy.data.filepath, rules=('M2', 'M5', 'M11'))
    for l in PBR['lines'][:12]: log('pbr_check:', l)
    if PBR['errors']:
        K.die(f'pbr_check pre-flight: {len(PBR["errors"])} material errors (M2/M5/M11) in the original: ' + ' | '.join(PBR['errors'][:6]) +
              ' -- fix the original\'s materials (or --skip-pbr-check, and say why)')

# ------------------------------------------------------------------------------------------------ the original
high_colls = [bpy.data.collections.get(n) or K.die(f'no collection {n!r}') for n in K.csv(A.high)]
low_names = {o.name for o in low_objs}
if high_colls: K.keep_only_collections(high_colls)
high_set = {o.name for c in high_colls for o in c.all_objects} if high_colls else None
EXC, DEC = K.csv(A.exclude), K.csv(A.decals)
dg = bpy.context.evaluated_depsgraph_get()
cache, items, skipped = {}, [], 0
for inst in dg.object_instances:
    ob = inst.object
    if ob.type not in ('MESH', 'CURVE', 'FONT', 'SURFACE', 'META'): continue
    orig = ob.original
    top = inst.parent.original if inst.is_instance and inst.parent else orig
    if top.name in low_names or orig.name in low_names or top.name.startswith('KIT_'): continue
    if high_set is not None and top.name not in high_set: continue
    if orig.hide_render or top.hide_render: continue
    names = [n for n in (orig.name, top.name, top.instance_collection.name if top.instance_collection else '') if n]
    if EXC and any(K.match(n, EXC) for n in names): skipped += 1; continue
    if orig.name not in cache:
        me = bpy.data.meshes.new_from_object(ob, preserve_all_data_layers=True, depsgraph=dg)
        if any(s.link == 'OBJECT' for s in orig.material_slots):
            me.materials.clear()
            for s in orig.material_slots: me.materials.append(s.material)
        cache[orig.name] = me
    decal = any(K.match(n, DEC) for n in names) or bool(orig.get('decal')) or orig.get('part') == 'decal'
    items.append((orig.name, inst.matrix_world.copy(), decal))
uvfixed = K.fix_textured_without_uv(cache.values())     # an image sampled with no UVs bakes one texel's colour
log(f'original: {len(items)} parts from {len(cache)} meshes ({skipped} excluded); textured meshes without UVs given a '
    f'box UV: {len(uvfixed)} {uvfixed[:8]}')
if not items: K.die('nothing to bake from: check --high / --exclude')

def all_cutout(me):
    ms = [m for m in me.materials if m and m.node_tree]
    if not ms: return False
    for m in ms:
        p = [n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED']
        if not p or K.is_glass_principled(p[0]) or not p[0].inputs['Alpha'].is_linked: return False
    return True

default_mat = bpy.data.materials.new('KIT_DEFAULT_GREY')
mats, mat_index = [], {}
def gidx(m):
    m = m or default_mat
    if m.name not in mat_index: mat_index[m.name] = len(mats); mats.append(m)
    return mat_index[m.name]
bms = {False: bmesh.new(), True: bmesh.new()}
nflip = ndecal = 0
for name, mw, decal in items:
    src = bpy.data.objects[name]; me = cache[name].copy()
    if not decal and not A.no_auto_decals and all_cutout(me): decal = True
    if me.uv_layers:
        rl = next((u for u in me.uv_layers if u.active_render), me.uv_layers[0])
        if rl.name != 'UVMap' and 'UVMap' not in me.uv_layers: rl.name = 'UVMap'
    K.pin_object_coords([(src, me, mw)])
    remap = [gidx(m) for m in me.materials] or [gidx(None)]
    if len(me.polygons):
        mi = np.empty(len(me.polygons), np.int32); me.polygons.foreach_get('material_index', mi)
        me.polygons.foreach_set('material_index', np.array(remap, np.int32)[np.clip(mi, 0, len(remap) - 1)])
    me.transform(mw)
    if mw.determinant() < 0: me.flip_normals(); nflip += 1
    bms[decal].from_mesh(me); ndecal += decal
    bpy.data.meshes.remove(me)
for me in cache.values(): bpy.data.meshes.remove(me)

def to_obj(bm, nm):
    if not bm.faces: bm.free(); return None
    me = bpy.data.meshes.new(nm); bm.to_mesh(me); bm.free()
    for m in mats: me.materials.append(m)
    o = bpy.data.objects.new(nm, me); bpy.context.scene.collection.objects.link(o); return o
THRU = K.csv(A.glass_through); thru_faces = 0
BCLS = bms[False].copy() if A.slots else None     # the whole original (lenses too): which game role a low face shows
if THRU:
    ids = {i for i, m in enumerate(mats) if K.match(m.name, THRU)}
    rm = [f for f in bms[False].faces if f.material_index in ids]; thru_faces = len(rm)
    bmesh.ops.delete(bms[False], geom=rm, context='FACES')
    log(f'--glass-through: {thru_faces} faces of {sorted(m.name for m in mats if K.match(m.name, THRU))} left out')
hi = to_obj(bms[False], 'KIT_HIGH'); hdec = to_obj(bms[True], 'KIT_HIGH_DECALS')
if hi is None: K.die('every part of the original was classed as a decal')
def _unloadable(im):
    """Blender resolves '..' lexically, the OS after following symlinks: through the game's symlinked assets-lib a path can
    exist for os.path and still load nothing in Blender, which then bakes its missing-texture magenta (blender-dash incident
    2026-10-13, the dashboard notes). So: normpath first, then ask Blender itself."""
    if not os.path.isfile(os.path.normpath(bpy.path.abspath(im.filepath, library=im.library))): return True
    im.reload(); return min(im.size) <= 0
missing = sorted({n.image.filepath for m in mats if m.node_tree for n in m.node_tree.nodes
                  if n.type == 'TEX_IMAGE' and n.image and n.image.source == 'FILE' and not n.image.packed_file
                  and _unloadable(n.image)})
if missing and not A.allow_missing_images:
    K.die(f'{len(missing)} image textures of the original are missing on disk (a copied .blend with relative paths?): '
          f'{missing[:6]}; open the original where it lives, or make paths absolute first (--allow-missing-images to go on)')
uvnames = {u.name for u in hi.data.uv_layers} | ({u.name for u in hdec.data.uv_layers} if hdec else set())
trees = [m.node_tree for m in mats if m.node_tree]
rewired = K.repoint_object_coords(trees)
for t in trees:
    for n in t.nodes:
        if n.type in ('UVMAP', 'NORMAL_MAP') and getattr(n, 'uv_map', '') and n.uv_map not in uvnames: n.uv_map = ''
high_tris = 0
for o in (hi, hdec):
    if o: o.data.calc_loop_triangles(); high_tris += len(o.data.loop_triangles)
log(f'high: {high_tris} triangles, {len(mats)} materials, {ndecal} decal parts, {nflip} mirrored parts flipped, '
    f'{rewired} texture-coordinate links pinned')

# only the bake objects stay in the scene
for lc in bpy.context.view_layer.layer_collection.children: lc.exclude = True
for o in bpy.context.scene.collection.objects:
    if o not in (hi, hdec, low): o.hide_render = True
bpy.context.view_layer.update()

# ------------------------------------------------------------------------------------------------ bake setup
from mathutils import Vector
bb = [hi.matrix_world @ Vector(c) for c in hi.bound_box]
diag = (Vector([max(v[i] for v in bb) for i in range(3)]) - Vector([min(v[i] for v in bb) for i in range(3)])).length
# automatic CAGE OBJECT: the low may sit INSIDE the original's skin (a coarse far hull cuts corners; a train car
# near's B-end wall lies > 7 cm inside the original's bulkhead). A ray that starts inside the skin bakes the inner side
# (a car's white steel). One extrusion cannot fit a coarse end and a tight side at once, so every low triangle's depth
# under the original's outer surface is measured (rays walked outward to the first outward-facing face) and a cage
# mesh is built: each vertex pushed out along its normal just past the deepest of its triangles. Blender then casts
# every bake ray from that cage toward the low surface (bake.cage_object).
from mathutils.bvhtree import BVHTree
_bmh = bmesh.new(); _bmh.from_mesh(hi.data); HTREE = BVHTree.FromBMesh(_bmh); _bmh.free()
lme = low.data; lme.calc_loop_triangles()
LCO = np.empty(len(lme.vertices) * 3, np.float32); lme.vertices.foreach_get('co', LCO); LCO = LCO.reshape(-1, 3)
LTV = np.empty(len(lme.loop_triangles) * 3, np.int32); lme.loop_triangles.foreach_get('vertices', LTV); LTV = LTV.reshape(-1, 3)
LP = LCO[LTV]; LN = np.cross(LP[:, 1] - LP[:, 0], LP[:, 2] - LP[:, 0]); LN /= np.maximum(np.linalg.norm(LN, axis=1, keepdims=True), 1e-12)
FLAT_T = np.isin(mat_idx, list(flat)) if flat else np.zeros(len(LP), bool)
REACH = 0.08 * diag


def depth_under(p, n):
    o = p + n * 1e-4; d = 0.0
    while d < REACH:                                       # walk outward: an outward-facing hit = we were under it
        loc, nrm, fi, dist = HTREE.ray_cast(o, n, REACH - d)
        if loc is None: return 0.0
        d += dist
        if nrm.dot(n) > 0: return d
        o = loc + n * 1e-4
    return 0.0


CAGE_OBJ = None; CCO = None
if A.extrusion is None:
    # depth at the centroid AND toward each corner (a proud handle over one end of a big triangle misses the centroid)
    _W = np.array([[1/3, 1/3, 1/3], [2/3, 1/6, 1/6], [1/6, 2/3, 1/6], [1/6, 1/6, 2/3], [.9, .05, .05], [.05, .9, .05], [.05, .05, .9]])
    tdep = np.array([0.0 if FLAT_T[t] else max(depth_under(Vector((w @ LP[t]).tolist()), Vector(LN[t].tolist())) for w in _W)
                     for t in range(len(LP))])
    base = 0.004 * diag
    text = np.clip(tdep * 1.15 + 0.002 * diag, base, REACH)
    vext = np.full(len(LCO), base); vcos = np.ones(len(LCO))
    vn = np.empty(len(LCO) * 3, np.float32); lme.vertices.foreach_get('normal', vn); vn = vn.reshape(-1, 3)
    for k in range(3):
        np.maximum.at(vext, LTV[:, k], text)
        np.minimum.at(vcos, LTV[:, k], np.einsum('ij,ij->i', vn[LTV[:, k]], LN))
    disp = vext / np.maximum(vcos, 0.4)
    CCO = LCO + vn * disp[:, None]
    cme = lme.copy(); cme.name = 'KIT_BAKE_CAGE'; cme.vertices.foreach_set('co', CCO.ravel()); cme.update()
    CAGE_OBJ = bpy.data.objects.new('KIT_BAKE_CAGE', cme); bpy.context.scene.collection.objects.link(CAGE_OBJ)
    CAGE_OBJ.hide_render = True
    EXT = round(float(np.median(disp)), 4)
    CAGE_INFO = dict(auto=True, cage_object=True, inside_share=round(float((tdep > 1e-3).mean()), 3),
                     inside_p90_m=round(float(np.percentile(tdep, 90)), 4), inside_max_m=round(float(tdep.max()), 4),
                     push_median_m=EXT, push_max_m=round(float(disp.max()), 4))
    RAY = A.max_ray if A.max_ray is not None else round(float(disp.max()) + 0.025 * diag, 4)
else:
    EXT = A.extrusion; CAGE_INFO = dict(auto=False)
    RAY = A.max_ray if A.max_ray is not None else round(EXT + 0.025 * diag, 4)


def inside_solid(p, n):
    """Is p inside a solid of the original? The first surface met going outward (along n) faces AWAY from p (we see
    its back from inside). A surface facing p means open air (under an overhang, between parts), not inside: walking on
    through other parts, as depth_under does to find the outer skin, would call every point under a skirt 'inside'
    (simplified a train car near 2026-10-13: 3.3 % flagged, mostly air under the skirts and in the bogies)."""
    loc, nrm, fi, dist = HTREE.ray_cast(p + n * 1e-4, n, REACH)
    return loc is not None and nrm.dot(n) > 0


def cage_start_check(n_pts=2000):
    """From the cage toward the low, the FIRST surface a bake ray meets must face the cage. A back face first means the
    ray started inside the original (between the skins of a thickened wall, or under the hull) and would bake the inner
    side: refused (owner fault 2026-10-13, a car's white steel)."""
    idx = np.where(~FLAT_T)[0]
    rng = np.random.default_rng(5); pick = rng.choice(idx, size=n_pts, p=tri_area[idx] / tri_area[idx].sum())
    front = back = none = thin = sheet = same = 0; where = {}
    for t in pick:
        a, b = rng.random(2)
        if a + b > 1: a, b = 1 - a, 1 - b
        w = np.array([1 - a - b, a, b])
        pl = (w[:, None] * LP[t]).sum(0); n = Vector(LN[t].tolist())
        pc = (w[:, None] * CCO[LTV[t]]).sum(0) if CCO is not None else pl + LN[t] * EXT
        dv = Vector((pl - pc).tolist()); L = dv.length
        if L < 1e-9: continue
        loc, nrm, fi, dist = HTREE.ray_cast(Vector(pc.tolist()), dv / L, L + 0.025 * diag)
        if loc is None: none += 1; continue
        if nrm.dot(n) > 0:
            front += 1
            l2, n2, f2, d2 = HTREE.ray_cast(loc - n * 1e-4, -n, 0.01 * diag)
            if l2 is not None and n2.dot(n) < 0: thin += 1      # a wall's inner skin right behind: fine, it is hidden
        elif not inside_solid(Vector(pc.tolist()), n):
            sheet += 1                    # cage point in open air: a single-sided sheet / open shell seen from behind
        else:
            back += 1
            # harmful only when the inner face is ANOTHER material than the surface seen there from outside (a car: the
            # inner wall stl.wall under the steel skin); an inner face of the same material bakes the same colour and
            # metal (its turned normal is flattened by the normal pass)
            mid_ = hi.data.polygons[fi].material_index if fi is not None and fi < len(hi.data.polygons) else -1
            lo_, no_, fo_, do_ = HTREE.ray_cast(Vector(pl.tolist()) + n * REACH, -n, REACH + 0.01 * diag)
            seen_ = hi.data.polygons[fo_].material_index if fo_ is not None and fo_ < len(hi.data.polygons) else -2
            if mid_ == seen_: same += 1; continue
            ax = int(np.argmax(np.abs(LN[t]))); key = ('xyz'[ax] + ('+' if LN[t][ax] > 0 else '-'))
            m_ = mats[mid_].name if mid_ >= 0 else '?'; s_ = mats[seen_].name if seen_ >= 0 else '?'
            where.setdefault(key, []).append((tuple(round(float(c), 2) for c in pl), f'{m_} instead of {s_}'))
    hits = max(1, front + back + sheet)
    places = {}
    for key, v in where.items():
        P_ = np.array([x[0] for x in v]); mm = {}
        for _, m_ in v: mm[m_] = mm.get(m_, 0) + 1
        places[key] = dict(n=len(v), min=P_.min(0).round(2).tolist(), max=P_.max(0).round(2).tolist(),
                           materials=sorted(mm.items(), key=lambda x: -x[1])[:4])
    return dict(samples=n_pts, front=front, inside_start=back, inside_same_material=same, sheet_back=sheet, miss=none,
                inside_share=round(back / hits, 4), back_share=round((back - same) / hits, 4),
                sheet_back_share=round(sheet / hits, 4), thin_wall_share=round(thin / max(1, front), 4), inside_places=places,
                note='back_share (the gate) = rays starting inside a solid whose first face is another material than the '
                     'surface seen there from outside; inside_share counts every inside start')


CAGE_INFO['start_check'] = cs = cage_start_check()
if cs['back_share'] > 0.02 and not A.allow_inside_start and not A.verify_only:
    os.makedirs(A.out, exist_ok=True)
    with open(os.path.join(A.out, f'{A.prefix}_start_check.json'), 'w') as f: json.dump(dict(CAGE_INFO, extrusion=EXT, max_ray=RAY), f, indent=1)
    K.die(f'{cs["back_share"]:.1%} of bake rays would start INSIDE the original and meet the back of ANOTHER material first (the inner skin of '
          f'a thickened wall, or the hull from inside): they would bake the inner side. Fix the low there, or give the '
          f'cage room (--extrusion); {cs}')
NEXT = A.normal_extrusion if A.normal_extrusion is not None else EXT
NRAY = A.normal_max_ray if A.normal_max_ray is not None else RAY
K.set_threads(A.threads, A.samples)
bk = bpy.context.scene.render.bake
bk.use_selected_to_active = True; bk.use_clear = False; bk.margin = 0; bk.target = 'IMAGE_TEXTURES'
bt = bpy.data.materials.new('KIT_BAKE_TARGET'); tnode = bt.node_tree.nodes.new('ShaderNodeTexImage')
for n in bt.node_tree.nodes: n.select = False
tnode.select = True; bt.node_tree.nodes.active = tnode                  # Blender 5.2 bakes into the ACTIVE AND SELECTED node
for i in range(len(low.data.materials)): low.data.materials[i] = bt
glass_mats = [m.name for m in mats if m.node_tree and any(n.type in ('BSDF_GLASS', 'BSDF_REFRACTION') or
              (n.type == 'BSDF_PRINCIPLED' and K.is_glass_principled(n)) for n in m.node_tree.nodes)]
# library kinds and other Shader Lab groups: channel() cannot see into a group and baked them grey-white (the low
# validator far 2026-10-15 19:01: graphite bracket came out cream, lodcmp luminance +1639 %). Lift them first, in memory.
LIFTED = K.lift_groups(mats)
if LIFTED: log(f"{len(LIFTED)} group materials lifted to a top-level Principled before baking: {sorted(LIFTED)[:8]}")
swap = K.MaterialSwap(mats, glass)
AO_DIST = A.ao_distance if A.ao_distance is not None else round(min(1.0, max(0.05, 0.025 * diag)), 3)
log(f'diag {diag:.2f} m, cage extrusion {EXT} m, max ray {RAY} m (normal {NEXT}/{NRAY}), {A.threads} threads, '
    f'{A.samples} sample(s), margin {MARGIN}px, glass materials {glass_mats}' +
    (f'; ao distance {AO_DIST} m, {A.ao_samples} samples, blur {A.ao_blur} px' if 'ao' in MAPS else ''))

timings, miss = {}, {}
CAGE_KW = dict(use_cage=True, cage_object=CAGE_OBJ.name, max_ray_distance=RAY) if CAGE_OBJ is not None else {}
def bake_pass(kind, source, chan=None):
    t = time.time()
    img = bpy.data.images.new('kit_' + kind, S, S, alpha=True, float_buffer=True)
    img.colorspace_settings.name = 'Non-Color'; img.generated_color = (1, 0, 1, 0); tnode.image = img
    for o in bpy.context.view_layer.objects: o.select_set(False)
    source.select_set(True); low.select_set(True); bpy.context.view_layer.objects.active = low
    if kind == 'normal':
        swap.restore()
        r = bpy.ops.object.bake(type='NORMAL', normal_space='TANGENT', use_selected_to_active=True, margin=0, use_clear=False,
                                **(CAGE_KW if CAGE_OBJ is not None else dict(cage_extrusion=NEXT, max_ray_distance=NRAY)))
    elif kind == 'ao':
        # Cycles AO at the HIGH surface each cage ray meets; every render-visible object occludes, so the decal sheets
        # (they lie millimetres over the paint) are hidden for this pass; the low and the cage are not occluders (bake
        # hides the active object; the cage is hide_render). Probe 2026-10-13: a low plane lying ON the high plate
        # gives 1.0 in the open, so the low does not shadow the high.
        swap.restore(); sc_ = bpy.context.scene
        if sc_.world is None: sc_.world = bpy.data.worlds.new('KIT_BAKE_WORLD')
        old = (sc_.world.light_settings.distance, sc_.cycles.samples, hdec.hide_render if hdec else None)
        sc_.world.light_settings.distance = AO_DIST; sc_.cycles.samples = A.ao_samples
        if hdec: hdec.hide_render = True
        try:
            r = bpy.ops.object.bake(type='AO', use_selected_to_active=True, margin=0, use_clear=False,
                                    **(CAGE_KW if CAGE_OBJ is not None else dict(cage_extrusion=EXT, max_ray_distance=RAY)))
        finally:
            sc_.world.light_settings.distance, sc_.cycles.samples = old[0], old[1]
            if hdec: hdec.hide_render = old[2]
    else:
        if kind == 'emit': swap.restore()
        else: swap.set(chan)
        r = bpy.ops.object.bake(type='EMIT', use_selected_to_active=True, margin=0, use_clear=False,
                                **(CAGE_KW if CAGE_OBJ is not None else dict(cage_extrusion=EXT, max_ray_distance=RAY)))
    a = np.empty(S * S * 4, np.float32); img.pixels.foreach_get(a); a = a.reshape(S, S, 4)
    bpy.data.images.remove(img)
    if 'FINISHED' not in r: K.die(f'bake pass {kind} was {r}: nothing baked (see the Info lines above)')
    hit = a[..., 3] > 0.5
    timings[kind] = round(time.time() - t, 1)
    if source is hi: miss[kind] = round(float((inside & ~hit & ~any_flat).sum() / max(1, inside.sum())), 4)
    log(f'pass {kind}: {r} {timings[kind]} s, hit {hit.mean():.1%} of the image' +
        (f', miss {miss[kind]:.2%} of the atlas' if kind in miss else ''))
    return a[..., :3], hit

res = {}
def load_map(path):
    im = bpy.data.images.load(path); im.colorspace_settings.name = 'Non-Color'
    if tuple(im.size) != (S, S): im.scale(S, S)
    a = np.empty(S * S * 4, np.float32); im.pixels.foreach_get(a); return a.reshape(S, S, 4)
if A.verify_only:                     # check maps that exist (another builder's) instead of baking
    vm = dict(x.split('=', 1) for x in K.csv(A.verify_maps))
    full = np.ones((S, S), bool) & inside
    if 'color' in vm:
        c = load_map(vm['color'])[..., :3]; c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
        res['color'] = (c, full)
    if 'mr' in vm:
        mr = load_map(vm['mr']); res['rough'] = (mr[..., 1:2].repeat(3, -1), full); res['metal'] = (mr[..., 2:3].repeat(3, -1), full)
    for k in ('rough', 'metal'):
        if k in vm: res[k] = (load_map(vm[k])[..., :3], full)
    MAPS = []
for chan in ('color', 'rough', 'metal', 'alpha'):
    if chan in MAPS: res[chan] = bake_pass(chan, hi, chan)
if 'normal' in MAPS: res['normal'] = bake_pass('normal', hi)
emits = 'emit' in MAPS and K.has_emission(mats)
if 'emit' in MAPS and not emits: log('no emission in the original: no emit map')
if emits: res['emit'] = bake_pass('emit', hi)
if 'ao' in MAPS: res['ao'] = bake_pass('ao', hi)
if hdec is not None and 'color' in MAPS:
    res['decal_color'] = bake_pass('decal_color', hdec, 'color')
    res['decal_alpha'] = bake_pass('decal_alpha', hdec, 'alpha')

# ------------------------------------------------------------------------------------------------ finish the maps
out, info = {}, {}
def fill_flat(arr, key):
    for i, m in flat_mask.items():
        v = flat[i][key]; arr[m] = v if hasattr(v, '__len__') else (v, v, v)
def finish(arr, hit, key):
    arr = arr.copy()
    if key in ('rough', 'metal', 'color') and flat_mask: fill_flat(arr, key)
    return K.pad_fill(arr, hit | any_flat, MARGIN)

if 'color' in res:
    col, hit = res['color']
    if 'decal_color' in res:
        dc, dh = res['decal_color']; da, _ = res['decal_alpha']
        a = np.where(dh[..., None], np.clip(da[..., :1], 0, 1), 0.0)
        col = col * (1 - a) + dc * a
        info['decal_texels'] = round(float((a[..., 0] > 0.5).mean()), 4)
    col = finish(col, hit, 'color')
    ch = [K.srgb_encode(col)]
    if 'alpha' in res:
        al, ah = res['alpha']; al = K.pad_fill(np.where(ah[..., None], al, 1.0), ah | any_flat, MARGIN)[..., :1]
        if al.min() < 0.99: ch.append(np.clip(al, 0, 1)); info['alpha'] = 'in color.png (A)'
        else: info['alpha'] = 'all opaque: not stored'
    out['color'] = np.concatenate(ch, -1)
    COL_LIN = col

# ------------------------------------------------------------------------------------------------ game material slots
# (coordinator 2026-10-13, GAME-CONTRACT.md): every low triangle gets the game role of the original surface it shows
# (rays from outside along its normal at 4 points, majority, looking through glass-* panes: the surface batch is opaque
# and the glass batch carries the glass role; unmapped = the baked slot). Role texels then store only
# what lives inside the slot: a grey multiplier (AO, wear, dirt = baked luminance / the slot's median luminance,
# clipped to 1); the material carries the slot's colour as a factor, which the game replaces for body/stripe/trim.
SLOTINFO = None
if A.slots and 'color' in res:
    SL = K.load_slots(A.slots); LEVEL = K.level_of(prefix, A.level)
    from mathutils.bvhtree import BVHTree as _BT
    BCLS.faces.ensure_lookup_table(); cmat = [f.material_index for f in BCLS.faces]; CT = _BT.FromBMesh(BCLS)
    mrole = [K.slot_role(m.name, SL, LEVEL) for m in mats]
    tri_role, mixed = [], 0
    _W4 = np.array([[1/3, 1/3, 1/3], [2/3, 1/6, 1/6], [1/6, 2/3, 1/6], [1/6, 1/6, 2/3]])
    for t in range(len(LP)):
        if FLAT_T[t]:         # (the low's slots hold the bake target by now: the flat material's name was kept)
            tri_role.append(K.slot_role(flat.get(int(mat_idx[t]), {}).get('name', ''), SL, LEVEL)); continue
        nv = Vector(LN[t].tolist()); votes = []
        for w in _W4:
            pv = Vector((w @ LP[t]).tolist())
            o_, left = pv + nv * REACH, REACH + 0.01 * diag
            for _k in range(6):     # the surface batch never shows glass: a pane in front is looked through (the game
                loc, nrm, fi, dist = CT.ray_cast(o_, -nv, left)    # draws glass-* with its own shader, see-through)
                if fi is None or 'glass-' not in (mrole[cmat[fi]] or ''): break
                o_, left = loc - nv * 1e-4, left - dist - 1e-4
            if fi is not None and 'glass-' not in (mrole[cmat[fi]] or ''): votes.append(mrole[cmat[fi]])
        if not votes: tri_role.append(None); continue
        best = max(set(votes), key=votes.count); tri_role.append(best); mixed += len(set(votes)) > 1
    BCLS.free()
    tid = K.raster_uv(uvs, S, ids=np.arange(len(uvs)))
    lum = lambda c: c[..., 0] * 0.2126 + c[..., 1] * 0.7152 + c[..., 2] * 0.0722
    ok = res['color'][1] & inside
    # slot fit: a triangle in a slot whose colour the game REPLACES (body / stripe / trim) must look like "grey x the slot's
    # colour"; one that shows something else (an emblem, a decal, a lamp ring of another colour) goes to the baked slot,
    # which keeps the full colour. a test run near: the nose emblem inside stripe-lagoon became a red block.
    FIT_ROLES = ('body-', 'stripe-', 'trim-'); moved_fit = 0
    for _r in sorted({r for r in tri_role if r and r.startswith(FIT_ROLES)}):
        tr_ = np.array([x == _r for x in tri_role] + [False]); tsel = tr_[np.where(tid >= 0, tid, len(tri_role))] & ok
        if not tsel.any(): continue
        C_ = COL_LIN[tsel][:, :3]; ref_ = np.median(C_, 0)
        mod_ = np.clip(lum(C_) / max(float(lum(ref_)), 1e-4), 0, 1)
        mis = np.abs(C_ - mod_[:, None] * ref_[None]).max(1)
        sm = np.bincount(tid[tsel], weights=mis, minlength=len(tri_role)); ct = np.bincount(tid[tsel], minlength=len(tri_role))
        for i in np.where((ct >= 4) & (sm / np.maximum(ct, 1) > A.slot_fit))[0]:
            if tri_role[i] == _r: tri_role[i] = None; moved_fit += 1
    if moved_fit: log(f'slot fit: {moved_fit} triangles show something other than grey x their slot colour -> baked slot')
    rnames = sorted({r for r in tri_role if r})
    rid = np.array([rnames.index(r) if r else -1 for r in tri_role] + [-2])      # -2: no triangle
    texrole = rid[np.where(tid >= 0, tid, len(tri_role))]
    sc = COL_LIN.copy(); per = {}
    for k, r in enumerate(rnames):
        mk = (texrole == k) & ok
        ref = np.median(COL_LIN[mk], 0) if mk.any() else np.full(3, 0.5)
        mod = np.clip(lum(COL_LIN) / max(float(lum(ref)), 1e-4), 0, 1)
        sel = texrole == k
        sc[sel] = mod[sel][:, None].repeat(3, 1)
        at = np.array([tri_area[i] for i, x in enumerate(tri_role) if x == r])
        per[r] = dict(triangles=int(len(at)), area_share=round(float(at.sum() / max(tri_area.sum(), 1e-9)), 4),
                      ref_linear=[round(float(x), 4) for x in ref],
                      ref_hex='#' + ''.join(f'{int(round(float(v) * 255)):02x}' for v in K.srgb_encode(np.asarray(ref))),
                      clipped_share=round(float((lum(COL_LIN[mk]) > lum(ref) * 1.0001).mean()) if mk.any() else 0.0, 4))
    sc = K.pad_fill(sc, inside | any_flat, MARGIN)
    out['slotcolor'] = np.concatenate([K.srgb_encode(sc)] + ([out['color'][..., 3:4]] if out['color'].shape[-1] == 4 else []), -1)
    baked_area = float(sum(tri_area[i] for i, x in enumerate(tri_role) if x is None) / max(tri_area.sum(), 1e-9))
    SLOTINFO = dict(file=os.path.abspath(A.slots), level=LEVEL, roles=per, baked_area_share=round(baked_area, 4), slot_fit_moved=moved_fit,
                    mixed_triangle_share=round(mixed / max(1, len(tri_role)), 4), tri_roles=tri_role, uv_hash=K.uv_hash(low.data),
                    rule='role texels = grey multiplier (baked luminance / slot median, clipped to 1); baked slot = full colour')
    log(f'slots ({LEVEL}): ' + ', '.join(f'{r} {v["triangles"]} tris {v["area_share"]:.0%}' for r, v in per.items()) +
        f'; baked {baked_area:.0%}; mixed triangles {SLOTINFO["mixed_triangle_share"]:.1%}')
for key in ('rough', 'metal'):
    if key in res: out[key] = np.clip(finish(*res[key], key)[..., :1], 0, 1)


def masked_blur(v, w, sigma):
    """Gaussian blur of v over the texels where w is set (normalised by the blurred weight), so background and other
    islands (uvpack keeps them >= 4 px apart) do not bleed in; texels outside w keep their value."""
    if sigma <= 0: return v
    r = max(1, int(math.ceil(2.5 * sigma))); k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2); k /= k.sum()
    def sep(a):
        for ax in (0, 1):
            p = np.pad(a, [(r, r) if i == ax else (0, 0) for i in range(2)]); o = np.zeros_like(a)
            for i, kv in enumerate(k): o += kv * (p[i:i + a.shape[0]] if ax == 0 else p[:, i:i + a.shape[1]])
            a = o
        return a
    wf = w.astype(np.float32); num, den = sep(v * wf), sep(wf)
    return np.where(w, num / np.maximum(den, 1e-6), v)


AO = None
if 'ao' in res:
    ao_raw, ao_hit = res['ao']
    ao_ok = ao_hit & ~any_flat
    v = masked_blur(np.clip(ao_raw[..., 0], 0, 1).astype(np.float32), ao_ok, A.ao_blur * S / 2048)
    v[any_flat] = 1.0
    AO = np.clip(K.pad_fill(v[..., None], ao_hit | any_flat, MARGIN), 0, 1)       # misses: filled from their neighbours
    sel = AO[..., 0][inside & ao_ok]
    info['ao'] = dict(distance_m=AO_DIST, samples=A.ao_samples, blur_px=round(A.ao_blur * S / 2048, 2),
                      stored='in mr.png (R)' if ('rough' in out or 'metal' in out) else 'ao.png',
                      median=round(float(np.median(sel)), 3) if sel.size else None,
                      p5=round(float(np.percentile(sel, 5)), 3) if sel.size else None,
                      dark_share=round(float((sel < 0.5).mean()), 4) if sel.size else None,
                      note='glTF occlusionTexture (R); three.js aoMap darkens hemisphere + environment light only')
    out['ao'] = AO
    log(f'ao: distance {AO_DIST} m, median {info["ao"]["median"]}, p5 {info["ao"]["p5"]}, darker than 0.5 on '
        f'{info["ao"]["dark_share"]:.1%} of the atlas texels -> {info["ao"]["stored"]}')
if 'rough' in out or 'metal' in out:
    r = out.get('rough', np.full((S, S, 1), 0.6, np.float32)); m = out.get('metal', np.zeros((S, S, 1), np.float32))
    out['mr'] = np.concatenate([AO if AO is not None else np.ones_like(r), r, m], -1)    # glTF ORM: R occlusion
if 'normal' in res:
    nm, hit = res['normal']; nm = nm.copy()
    v = nm * 2 - 1; bad = hit & (v[..., 2] < A.normal_min_z)
    flatn = np.array([0.5, 0.5, 1.0], np.float32)
    nm[bad] = flatn; nm[inside & ~hit] = flatn; nm[any_flat] = flatn
    v = nm * 2 - 1; v /= np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-6); nm = (v + 1) / 2
    info['normal_turned_share'] = round(float(bad.sum() / max(1, hit.sum())), 4)
    out['normal'] = K.pad_fill(nm, hit | inside | any_flat, MARGIN)
if 'emit' in res:
    em, hit = res['emit']; em = np.where(hit[..., None], np.maximum(em, 0), 0)
    peak = float(np.percentile(em.max(-1)[hit], 99.9)) if hit.any() else 0.0
    lit = float((em.max(-1) > 0.01).sum() / max(1, hit.sum()))
    if peak < 1e-3:
        log('emit pass is black where the low sees the original (lights off in this state?)'); info['emit'] = 'black'
    else:
        strength = max(peak, 1.0)
        out['emit'] = K.srgb_encode(K.pad_fill(np.clip(em / strength, 0, 1), hit | any_flat, MARGIN))
        info.update(emit_strength=round(strength, 4), emit_lit_share=round(lit, 4))


# ------------------------------------------------------------------------------------------------ self-check
# Owner fault 2026-10-12 (a train car near): the side steel came out white (metallic 0.23 where the original's
# exterior steel is 0.55) because rays from the low shell also reached the interior wall behind it. So: on every big
# face group of the low (by facing: +x -x +y -y up down), sample points; the EXPECTED value is the original's material
# of the surface seen from outside along the low normal (not along the bake ray from the cage, which would repeat the
# bake's own mistake: a ray starting inside the skin meets the inner wall, the outside view meets the skin); compare where
# that material's metallic / roughness / base colour are plain values (procedural ones cannot be read off: counted
# as not checkable). FAULT when a group's mean metal drift > --verify-metal, or its mean colour drift > --verify-de.
def verify_bake():
    from mathutils.bvhtree import BVHTree
    from mathutils import Vector
    bmh = bmesh.new(); bmh.from_mesh(hi.data); bmh.faces.ensure_lookup_table()
    fmat = [f.material_index for f in bmh.faces]; tree = BVHTree.FromBMesh(bmh); bmh.free()
    def plain(m):
        if not m or not m.node_tree: return None
        on = K.output_node(m)
        if on is None or not on.inputs['Surface'].is_linked: return None
        p = on.inputs['Surface'].links[0].from_node
        if p.type != 'BSDF_PRINCIPLED' or K.is_glass_principled(p): return None
        g = lambda k: None if p.inputs[k].is_linked else p.inputs[k].default_value
        c = g('Base Color')
        return dict(metal=g('Metallic'), rough=g('Roughness'), color=tuple(c)[:3] if c is not None else None)
    pv = [plain(m) for m in mats]
    me = low.data; me.calc_loop_triangles()
    co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
    tv = np.empty(len(me.loop_triangles) * 3, np.int32); me.loop_triangles.foreach_get('vertices', tv); tv = tv.reshape(-1, 3)
    P = co[tv]; N = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]); N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    flat_tri = np.isin(mat_idx, list(flat)) if flat else np.zeros(len(P), bool)
    ax = np.argmax(np.abs(N), 1); sg = np.sign(N[np.arange(len(N)), ax])
    names = {(0, 1): '+x', (0, -1): '-x', (1, 1): '+y', (1, -1): '-y', (2, 1): 'up', (2, -1): 'down'}
    col_lin = res['color'][0] if 'color' in res else None; col_hit = res['color'][1] if 'color' in res else None
    rough = res.get('rough'); metal = res.get('metal')
    dec_a = np.where(res['decal_alpha'][1], res['decal_alpha'][0][..., 0], 0) if 'decal_alpha' in res else None
    def lab(c):
        c = np.clip(np.asarray(c, np.float64), 0, 1)
        M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
        x = (M @ c) / np.array([0.9505, 1.0, 1.089])
        f = np.where(x > 0.008856, np.cbrt(x), 7.787 * x + 16 / 116)
        return np.array([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])
    rng = np.random.default_rng(7); out = {}; fault = []
    tot_area = float(tri_area[~flat_tri].sum()) or 1.0
    for key, nm in names.items():
        sel = np.where((ax == key[0]) & (sg == key[1]) & ~flat_tri)[0]
        area = float(tri_area[sel].sum()) if len(sel) else 0.0
        if area < 0.03 * tot_area: continue
        pick = rng.choice(sel, size=400, p=tri_area[sel] / tri_area[sel].sum())
        dm, dr, de, dmn, n_ok = [], [], [], [], 0
        for t in pick:
            a, b = rng.random(2)
            if a + b > 1: a, b = 1 - a, 1 - b
            w = np.array([1 - a - b, a, b]); p3 = (w[:, None] * P[t]).sum(0); uv = (w[:, None] * uvs[t]).sum(0)
            px, py = min(S - 1, int(uv[0] * S)), min(S - 1, int(uv[1] * S))
            if col_hit is None or not col_hit[py, px] or (dec_a is not None and dec_a[py, px] > 0.1): continue
            # expected = what a viewer sees here from outside: the first original surface met by a ray coming in along
            # the low's normal from well outside (REACH), independent of the cage. On a coarse far version the NEAREST
            # surface is often a part the low cuts through, not the one seen (kept as *_nearest, info only).
            nv = Vector(N[t].tolist()); pv3 = Vector(p3.tolist())
            loc, nrm, fi, dist = tree.ray_cast(pv3 + nv * REACH, -nv, REACH + 0.01 * diag)
            loc2, nrm2, fi2, dist2 = tree.find_nearest(pv3, RAY)
            if fi is None: fi = fi2
            if fi is None: continue
            e = pv[fmat[fi]]; e2 = pv[fmat[fi2]] if fi2 is not None else None
            if e2 and e2['metal'] is not None and metal is not None: dmn.append(abs(float(metal[0][py, px, 0]) - e2['metal']))
            if not e: continue
            n_ok += 1
            if e['metal'] is not None and metal is not None: dm.append(abs(float(metal[0][py, px, 0]) - e['metal']))
            if e['rough'] is not None and rough is not None: dr.append(abs(float(rough[0][py, px, 0]) - e['rough']))
            if e['color'] is not None: de.append(float(np.linalg.norm(lab(col_lin[py, px]) - lab(e['color']))))
        def tmean(v):        # mean of the best 90 %: a systematic drift (rays on the wrong wall) moves it, the few samples
            v = np.sort(np.asarray(v)); return float(v[:max(1, int(len(v) * 0.9))].mean())   # where 'nearest' is ambiguous do not
        g = dict(area_share=round(area / tot_area, 3), samples=400, checkable=n_ok,
                 metal_drift=round(tmean(dm), 3) if dm else None, metal_drift_mean=round(float(np.mean(dm)), 3) if dm else None,
                 rough_drift=round(tmean(dr), 3) if dr else None, colour_dE=round(tmean(de), 1) if de else None,
                 colour_samples=len(de), metal_drift_nearest=round(tmean(dmn), 3) if dmn else None)
        bad = []
        if dm and len(dm) >= 20 and g['metal_drift'] > A.verify_metal: bad.append(f'metal drift {g["metal_drift"]}')
        if de and len(de) >= 20 and g['colour_dE'] > A.verify_de: bad.append(f'colour dE {g["colour_dE"]}')
        g['verdict'] = ('FAULT: ' + ', '.join(bad)) if bad else ('ok' if (len(dm) >= 20 or len(de) >= 20) else 'not checkable (procedural)')
        if bad: fault.append(f'{nm}: ' + ', '.join(bad))
        out[nm] = g
    return dict(groups=out, faults=fault, limits=dict(metal=A.verify_metal, dE=A.verify_de),
                expected_from='material of the first original surface seen from outside along the low normal (plain values only)')
swap.restore()                        # the materials as authored: the check reads their plain values
verify = verify_bake() if 'color' in res and not A.no_verify else None
if A.verify_only:
    for nm, g in (verify or {}).get('groups', {}).items(): log(f'verify {nm}: {g}')
    with open(os.path.join(A.out, f'{prefix}_verify.json'), 'w') as f: json.dump(dict(maps=A.verify_maps, verify=verify), f, indent=1)
    if verify and verify['faults']: log('FAULT: the maps drift from the original on', verify['faults']); sys.exit(1)
    log('verify-only: no drift beyond the limits'); sys.exit(0)
if verify:
    for nm, g in verify['groups'].items(): log(f'verify {nm}: {g}')
files = {}
for k, arr in out.items():
    p = os.path.join(A.out, f'{prefix}_{k}.png'); K.png_write(p, arr); files[k] = os.path.basename(p)
worst = max(miss.values()) if miss else 0
if worst > 0.005 and 'color' in res:
    mm = (inside & ~res['color'][1] & ~any_flat)
    p = os.path.join(A.out, f'{prefix}_miss.png'); K.png_write(p, mm.astype(np.float32)[..., None]); files['miss'] = os.path.basename(p)
report = dict(tool='3d-asset-making/scripts/bake.py', when=time.strftime('%Y-%m-%d %H:%M:%S %z'),
              original=bpy.data.filepath, low=A.low, low_objects=[o.name for o in surf], prefix=prefix, size=S,
              maps=files, uv_hash=K.uv_hash(low.data), tri_hash=K.tri_hash(low.data), low_triangles=len(uvs), atlas_coverage=round(float(inside.mean()), 4),
              high=dict(collections=K.csv(A.high) or 'all visible', parts=len(items), triangles=high_tris,
                        decal_parts=ndecal, mirrored_parts=nflip, excluded=skipped, materials=len(mats),
                        glass_materials=glass_mats, glass_through_faces=thru_faces, textured_without_uv_fixed=uvfixed, pinned_coord_links=rewired),
              cage=dict(CAGE_INFO, extrusion=EXT, max_ray=RAY, normal_extrusion=NEXT, normal_max_ray=NRAY, diag=round(diag, 3)),
              threads=A.threads, samples=A.samples, margin_px=MARGIN, seconds=timings, total_seconds=round(time.time() - T0, 1),
              miss_share=miss, flat={f['name']: {k: f[k] for k in ('color', 'rough', 'metal')} for f in flat.values()},
              unknown_shader_nodes=sorted(set(K.UNKNOWN)), verify=verify, pbr_check=PBR, **info)
if SLOTINFO:
    with open(os.path.join(A.out, f'{prefix}_slots.json'), 'w') as f: json.dump(SLOTINFO, f, indent=1)
    report['slots'] = {k: v for k, v in SLOTINFO.items() if k != 'tri_roles'}
with open(os.path.join(A.out, f'{prefix}_bake.json'), 'w') as f: json.dump(report, f, indent=1)
log('DONE', json.dumps({k: report[k] for k in ('maps', 'miss_share', 'seconds', 'total_seconds')}))
if worst > 0.02: log(f'WARNING: {worst:.1%} of the atlas missed the original: raise --max-ray/--extrusion or look at {prefix}_miss.png')
if report['unknown_shader_nodes']: log('WARNING: shader nodes baked as grey:', report['unknown_shader_nodes'])
if verify and verify['faults']:
    log('FAULT: the bake drifts from the original on', verify['faults'], '- rays reach the wrong surface (an inner wall '
        'behind the skin?): lower --max-ray / --extrusion below the wall thickness, or --exclude the inner part; '
        'export_game.py refuses these maps unless --allow-bake-drift')
    sys.exit(1)
