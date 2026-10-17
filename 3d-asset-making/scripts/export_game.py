"""Build one game GLB (three.js) from a low mesh + the maps bake.py wrote, then check it.

  nice -n 10 blender -b FILE.blend --python export_game.py -- --low LOW --maps DIR --prefix near --out OUT.glb
        [--live GLOB[,GLOB] (own-material screens/glow cards, not baked) [--live-fallback DIR]] [--name ROOT_NODE] [--surface-node surface] [--glass-node glass] [--glass-collection NAME]
        [--glass-color R,G,B] [--glass-alpha 0.7] [--glass-rough 0.05] [--mounts 'mount.*,light.*']
        [--mount-collection NAME] [--root-props JSON] [--no-normal] [--double-sided]
        [--image-format JPEG|AUTO|WEBP] [--jpeg-quality 92] [--against REF.glb] [--from-below] [--uv NAME] [--no-ao]
        [--allow-designed FILE] [--allow-inherited] [--allow-bake-drift] [--skip-validator] [--skip-pbr-check] [--class-map asset.json]
        [--family train] [--slots FILE --contract GAME-CONTRACT.md --level near|mid|far]

What goes in (one root node `--name` at the world origin, so the asset's origin is kept; +Y up):
 * `--surface-node`: the low surface mesh(es), joined and triangulated exactly as bake.py baked them (the UV hash is
   compared with <prefix>_bake.json), ONE PBR material: baseColor (+alpha when baked), metallicRoughness packed per
   glTF (G rough, B metal), occlusionTexture = R of that same image when bake.py baked `ao` (one ORM texture;
   its own grey texture when the version has no mr; --no-ao leaves it out), tangent-space normal (+ exported tangents), emissive texture with
   KHR_materials_emissive_strength when the bake found light. Single-sided unless --double-sided. 1 draw call.
 * `--glass-node`: the low's glass meshes (named *glass*, custom prop glass=1, or in --glass-collection) as their
   own batch, alpha BLEND, tinted (--glass-color, linear) or their own simple Principled values. 1 draw call.
 * Every empty named mount.<kind>.<n> or light.<kind>.<n> (globs --mounts; only inside --mount-collection when
   given) that is NOT a collection instancer (those are construction mounts, already baked into the surface), with
   its custom properties as glTF extras; a Blender LIGHT object named light.* becomes such an empty with its colour,
   energy, type and cone in the extras (the game decides per its budget what a light becomes).
 * --root-props: a JSON object of extras for the root (family, member, lod, origin, ...).
Textures: colour as JPEG q92 by default (16-bit PNG everything made a 1.2 MB near 13 MB). The packed ORM (R occlusion,
G rough, B metal) is always 8-bit PNG: JPEG's 4:2:0 chroma subsampling bleeds the packed channels into each other (a car
near: metal error p99 59/255, rough mean 2.7/255; owner 2026-10-13 17:14 "fix the JPEG channel bleed, use PNG"). The normal map always
PNG (JPEG normals: 2.4 % texels with blue <= 0.5, length error to 0.45); emission PNG (JPEG noise x emissive strength
glows everywhere); PNG colour when it has alpha.

--slots FILE --contract GAME-CONTRACT.md --level near|mid|far  one material per game role (bake.py --slots wrote the
   roles): '<name>.<role>' with the slot colour as base colour factor x the grey multiplier texture, '<name>.baked'
   for the rest, all on one atlas; the glass batch is '<name>.<glass role>.pane'. The contract's names are read from
   its table; a required slot missing (default near/mid: body-ceramic, stripe-lagoon, trim-gunmetal, glass-,
   LED-ivory; far: none, the contract lets far be ONE baked material) or a used role the contract does not know ->
   refused. Far instead must keep the night look: a slot the game lights (LED-ivory, interior-warm-grey,
   seat-ocean-fabric) or lit texels in the baked emissive map; neither -> refused (_kit.far_night).
Then: reads the GLB back (triangles and draw calls the way three.js draws it, mounts, lights, size), runs
`mesh_integrity.py` (skill 3d-modelling; --against the version above, or the original) and prints its RESULT /
GAPS / FLICKER lines, and writes OUT.glb.json (the numbers asset_record.py records) and OUT.glb.integrity.txt.
GATES (owner 2026-10-12: a far went out with 2 floating boxes and a half-open shell, a near with bands blinking
across the end door, tyres with speckle; nobody had run the check). The GLB is written to a temp file and checked;
the final OUT.glb is written ONLY when all pass, else it is kept as OUT.rejected.glb with its reports and exit 1:
 * mesh_integrity RESULT FAULT (floating bodies, same-facing coplanar faces) -> refused, fault places printed.
   The floating bodies are judged against the film ORIGINAL (mesh_integrity --held-by): a piece that sits on the
   original and is joined there by faces no outside view reaches (the culling dropped them) is HELD, no fault; one
   that MOVED off the original, or whose joining surface is gone and shows, is refused; one that floats in the
   original too is INHERITED (said, not refused). The original is --held-by GLB, or by default the end of the
   --against chain (near: --against itself; mid/far: the `against` / `held_by` recorded in <against>.json).
   --held-tol M: how far a piece may lie from the original and how wide an opening counts as closed (default: the
   touch distance, 11 mm on a car; give the version's error target only when it must be larger).
   --allow-inherited: passed when the version has no more floating bodies (not held ones) and no more same-facing blink pairs than
   the --against reference itself (its faults, fixed in the original; said in the report as integrity_inherited).
   --allow-designed FILE: one substring per line naming designed places (e.g. 'blinks at (-4.330, 0.713'); only
   when EVERY fault place is named is it written. Always give --against (the version above; near: the original).
 * --double-sided with back-to-back face pairs (they blink on a double-sided material; a closed wall needs no back
   faces): refused. The surface is single-sided by default; only the glass batch (a single sheet) is double-sided.
 * the bake's own self-check found drift (<prefix>_bake.json verify faults) -> refused unless --allow-bake-drift.
 * any primitive whose material has a texture but no TEXCOORD for it -> refused.
 * the low's UVs or its triangulation (index buffer + positions) differ from what bake.py baked -> refused (the
   normal map's tangent frames belong to that triangulation).
 * the Khronos glTF-Validator reports errors -> refused (node package, installed on first use into
   ~/.cache/3d-asset-kit/node; --skip-validator only when node is missing and you say so).
 * scripts/pbr_check.py, when on disk: any ERROR -> refused (guarded: skipped and said while it is absent;
   --skip-pbr-check only with a reason). Its rules include E1: night lights declared (light.* empties, or the family's
   game contract) but no emissive texels and no slot the game lights. Findings with places: OUT.glb.pbr.json;
   --class-map asset.json ("materials" classes), --family (switch.json; T1 px/m, night).
 * a fresh reimport (Blender, empty scene, separate process) reads back other mesh objects / primitives / triangles /
   materials / textures than were exported -> refused. Both results go into OUT.glb.integrity.json.
Writes OUT.glb.integrity.json / .integrity.txt next to the GLB (the dashboard and asset_record.py read them).
Fails (exit 1) when any primitive whose material has a texture carries no TEXCOORD for it (three.js speckle;
a train car guide tyres 2026-10-12). Writes atomically (temp + rename). Never saves the .blend.
"""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _kit as K

ap = argparse.ArgumentParser(prog='export_game.py', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('--low', required=True); ap.add_argument('--maps', required=True); ap.add_argument('--prefix')
ap.add_argument('--out', required=True); ap.add_argument('--name'); ap.add_argument('--surface-node', default='surface')
ap.add_argument('--live', default=''); ap.add_argument('--live-fallback', default='');ap.add_argument('--glass-node', default='glass'); ap.add_argument('--glass-collection', default='')
ap.add_argument('--glass-color', default='0.10,0.13,0.15'); ap.add_argument('--glass-alpha', type=float, default=0.7)
ap.add_argument('--glass-rough', type=float, default=0.05); ap.add_argument('--mounts', default='mount.*,light.*')
ap.add_argument('--mount-collection', default=''); ap.add_argument('--root-props', default='{}')
ap.add_argument('--no-normal', action='store_true'); ap.add_argument('--double-sided', action='store_true')
ap.add_argument('--no-ao', action='store_true', help='leave the baked occlusion out (an A/B look; the mr R channel stays in the file)')
ap.add_argument('--image-format', default='JPEG', choices=('JPEG', 'AUTO', 'WEBP')); ap.add_argument('--jpeg-quality', type=int, default=92)
ap.add_argument('--against'); ap.add_argument('--from-below', action='store_true'); ap.add_argument('--uv')
ap.add_argument('--allow-designed'); ap.add_argument('--allow-bake-drift', action='store_true')
ap.add_argument('--skip-validator', action='store_true'); ap.add_argument('--skip-pbr-check', action='store_true')
ap.add_argument('--allow-inherited', action='store_true')
ap.add_argument('--held-by', default=''); ap.add_argument('--held-tol', type=float)
ap.add_argument('--class-map', default=''); ap.add_argument('--family', default='')
ap.add_argument('--slots', default=''); ap.add_argument('--contract', default=''); ap.add_argument('--level', choices=('near', 'mid', 'far'))
A = ap.parse_args(K.script_argv())

import bpy
log = lambda *a: print('[export]', *a, flush=True)
T0 = time.time()
out = os.path.abspath(A.out); os.makedirs(os.path.dirname(out), exist_ok=True)

low_objs, label = K.resolve(A.low)
gcol = bpy.data.collections.get(A.glass_collection) if A.glass_collection else None
gnames = {o.name for o in gcol.all_objects} if gcol else set()
import fnmatch
LIVE = [x for x in A.live.split(',') if x]
is_live = lambda o: any(fnmatch.fnmatch(o.name, pat) for pat in LIVE)
live_objs = [o for o in bpy.data.objects if o.type == 'MESH' and is_live(o)]
low_objs = [o for o in low_objs if not is_live(o)]
surf = [o for o in low_objs if o.type == 'MESH' and not (o.name in gnames or K.is_glass_obj(o))]
glass = [o for o in low_objs if o.type == 'MESH' and (o.name in gnames or K.is_glass_obj(o))]
if gcol: glass += [o for o in gcol.all_objects if o.type == 'MESH' and o not in glass]
prefix = A.prefix or ''.join(c if c.isalnum() or c in '-_' else '_' for c in label)
bj = os.path.join(A.maps, f'{prefix}_bake.json')
bake = json.load(open(bj)) if os.path.exists(bj) else {}
if not bake: log(f'WARNING: no {bj}: maps are taken as they are')
name = A.name or os.path.splitext(os.path.basename(out))[0]

# mount / light empties first (renaming the sources frees their names for the exported copies)
pats = K.csv(A.mounts)
mcol = bpy.data.collections.get(A.mount_collection) if A.mount_collection else None
pool = list(mcol.all_objects) if mcol else list(bpy.data.objects)
marks = [o for o in pool if K.match(o.name, pats) and (o.type == 'LIGHT' or (o.type == 'EMPTY' and not o.instance_collection))
         and o not in low_objs]
src_marks = [(o.name, o.matrix_world.copy(), o) for o in marks]
for o in marks: o.name = '_kit_src_' + o.name

# ------------------------------------------------------------------------------------------------ surface
s = K.low_copy(surf, A.uv, A.surface_node)
h = K.uv_hash(s.data)
th = K.tri_hash(s.data)
hash_fault = []
if bake.get('uv_hash') and bake['uv_hash'] != h:
    hash_fault.append(f'UV hash {h} differs from the bake ({bake["uv_hash"]}): the maps belong to other UVs. Re-bake.')
if bake.get('tri_hash') and bake['tri_hash'] != th:
    hash_fault.append(f'triangulation hash {th} differs from the bake ({bake["tri_hash"]}): the low was re-triangulated or '
                      f'simplified after the bake, so the normal map\'s tangent frames no longer match. Re-bake.')
for x in hash_fault: log('WARNING:', x)
import numpy as np
SL = K.load_slots(A.slots) if A.slots else None
LEVEL = K.level_of(prefix, A.level)
slotrep = None
if SL:
    sj = os.path.join(A.maps, f'{prefix}_slots.json')
    if not os.path.exists(sj): K.die(f'--slots given but the bake wrote no {sj}: bake with --slots {A.slots}')
    slotrep = json.load(open(sj))
    if slotrep.get('uv_hash') != h or len(slotrep['tri_roles']) != len(s.data.polygons):
        K.die(f'{sj} belongs to another low ({len(slotrep["tri_roles"])} triangles, uv {slotrep.get("uv_hash")}; this one '
              f'{len(s.data.polygons)}, uv {h}): re-bake')
images = {}
def gltf_output_group():
    """The node group the glTF exporter reads occlusion from (name starts with 'glTF Material Output', input 'Occlusion')."""
    for g_ in bpy.data.node_groups:
        if g_.name.lower().startswith('gltf material output') and any(
                getattr(i, 'in_out', '') == 'INPUT' and i.name == 'Occlusion' for i in g_.interface.items_tree):
            return g_
    g_ = bpy.data.node_groups.new('glTF Material Output', 'ShaderNodeTree')
    g_.interface.new_socket('Occlusion', in_out='INPUT', socket_type='NodeSocketFloat')
    g_.nodes.new('NodeGroupInput'); g_.nodes.new('NodeGroupOutput')
    return g_
def make_material(mname, color_key='color', factor=None):
    """One PBR material on the shared atlas: colour (x factor), glTF-packed MR, normal, emission."""
    m = bpy.data.materials.new(mname); nt = m.node_tree
    b = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    uvn = nt.nodes.new('ShaderNodeUVMap'); uvn.uv_map = 'atlas'
    def tex(key, noncolor):
        fn = (bake.get('maps') or {}).get(key) or f'{prefix}_{key}.png'
        p = os.path.join(A.maps, fn)
        if not os.path.exists(p): return None
        if key not in images:
            # colour and MR go out as JPEG files (written here, exported AUTO = as they are). The NORMAL map stays PNG:
            # JPEG normals had 2.4 % texels with blue <= 0.5 and length errors to 0.45 (a car, standards research
            # 2026-10-13). The EMISSION map stays PNG: JPEG noise of 1-2/255 times emissive strength 5 lit the whole
            # synth surface (pbr_check E2: lit share 100 % vs 1.4 %). A colour map with alpha stays PNG.
            if A.image_format == 'JPEG' and key in ('color', 'slotcolor'):   # ORM (mr, ao) stays PNG: packed channels
                src = bpy.data.images.load(p)
                if not (src.channels == 4 and key in ('color', 'slotcolor') and 'in color.png' in str(bake.get('alpha', ''))):
                    jp = os.path.join(A.maps, f'{prefix}_{key}.q{A.jpeg_quality}.jpg')
                    src.file_format = 'JPEG'; src.save(filepath=jp, quality=A.jpeg_quality); p = jp
                bpy.data.images.remove(src)
            im = bpy.data.images.load(p); im.name = f'{name}_{key}'
            if noncolor: im.colorspace_settings.name = 'Non-Color'
            images[key] = im
        t = nt.nodes.new('ShaderNodeTexImage'); t.image = images[key]; nt.links.new(uvn.outputs[0], t.inputs[0]); return t
    used, alpha = [], False
    c = tex(color_key, False)
    if c:
        if factor is not None:        # glTF baseColorFactor x texture (the exporter reads a Multiply with a constant colour)
            mx = nt.nodes.new('ShaderNodeMix'); mx.data_type = 'RGBA'; mx.blend_type = 'MULTIPLY'
            mx.inputs['Factor'].default_value = 1.0
            nt.links.new(c.outputs['Color'], mx.inputs['A']); mx.inputs['B'].default_value = tuple(factor[:3]) + (1.0,)
            nt.links.new(mx.outputs['Result'], b.inputs['Base Color'])
        else: nt.links.new(c.outputs['Color'], b.inputs['Base Color'])
        used.append(color_key)
        if c.image.channels == 4 and 'in color.png' in str(bake.get('alpha', '')):
            rd = nt.nodes.new('ShaderNodeMath'); rd.operation = 'ROUND'
            nt.links.new(c.outputs['Alpha'], rd.inputs[0]); nt.links.new(rd.outputs[0], b.inputs['Alpha']); alpha = True
            m.surface_render_method = 'DITHERED'
    mr = tex('mr', True)
    sp = None
    if mr:
        sp = nt.nodes.new('ShaderNodeSeparateColor'); nt.links.new(mr.outputs[0], sp.inputs[0])
        nt.links.new(sp.outputs['Green'], b.inputs['Roughness']); nt.links.new(sp.outputs['Blue'], b.inputs['Metallic']); used.append('mr')
    # ambient occlusion (bake.py `ao`): glTF occlusionTexture, R channel. In R of the mr image the exporter writes ONE ORM
    # texture (occlusion R, rough G, metal B; Blender's __gather_orm_texture, same image = the file as it is); alone
    # it is its own grey texture. Blender reads occlusion only from a 'glTF Material Output' group's Occlusion input.
    ao_at = str((bake.get('ao') or {}).get('stored', ''))
    occ = None
    if not A.no_ao and ao_at:
        if 'mr.png' in ao_at and sp is not None: occ = sp.outputs['Red']
        elif 'ao.png' in ao_at:
            t_ = tex('ao', True)
            if t_:
                s2 = nt.nodes.new('ShaderNodeSeparateColor'); nt.links.new(t_.outputs[0], s2.inputs[0]); occ = s2.outputs['Red']
        if occ is None: log(f'WARNING: the bake says ao is {ao_at!r} but that map is not in {A.maps}: no occlusionTexture')
    if occ is not None:
        go = nt.nodes.new('ShaderNodeGroup'); go.node_tree = gltf_output_group()
        nt.links.new(occ, go.inputs['Occlusion']); used.append('ao')
    nm = None if A.no_normal else tex('normal', True)
    if nm:
        nmap = nt.nodes.new('ShaderNodeNormalMap'); nmap.uv_map = 'atlas'
        nt.links.new(nm.outputs[0], nmap.inputs['Color']); nt.links.new(nmap.outputs[0], b.inputs['Normal']); used.append('normal')
    em = tex('emit', False)
    if em:
        nt.links.new(em.outputs[0], b.inputs['Emission Color'])
        b.inputs['Emission Strength'].default_value = float(bake.get('emit_strength', 1.0)); used.append('emit')
    m.use_backface_culling = not A.double_sided
    return m, used, alpha, nm
if SL:
    roles = slotrep['tri_roles']; present = sorted({r for r in roles if r})
    mats_ = []; idx = {}
    for r in present:
        mm, used, a_, nm = make_material(f'{name}.{r}', 'slotcolor', factor=slotrep['roles'][r]['ref_linear'])
        idx[r] = len(mats_); mats_.append(mm)
    if any(r is None for r in roles):
        mm, used, a_, nm = make_material(f'{name}.baked', 'slotcolor'); idx[None] = len(mats_); mats_.append(mm)
    alpha = a_
    s.data.materials.clear()
    for mm in mats_: s.data.materials.append(mm)
    s.data.polygons.foreach_set('material_index', np.array([idx[r] for r in roles], np.int32))
    log(f'slots ({LEVEL}): {[mm.name for mm in mats_]} = {len(mats_)} primitives on one atlas')
else:
    m, used, alpha, nm = make_material(f'{name}.{A.surface_node}')
    s.data.polygons.foreach_set('material_index', np.zeros(len(s.data.polygons), np.int32))   # one slot = one primitive = 1 draw
    s.data.materials.clear(); s.data.materials.append(m)
log(f'surface: {len(surf)} mesh(es) -> {A.surface_node}, maps {used}, uv {h}')

# ------------------------------------------------------------------------------------------------ glass
g = None
if glass:
    g = K.low_copy(glass, None, A.glass_node, need_uv=False)
    src = next((sl.material for o in glass for sl in o.material_slots if sl.material and sl.material.node_tree), None)
    sp_ = next((n for n in src.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if src else None
    grole = (SL.get('glass_role') or next((r for r in SL['roles'] if 'glass-' in r), 'glass-window')) if SL else None
    gm = bpy.data.materials.new(f'{name}.{grole}.pane' if grole else f'{name}.{A.glass_node}'); gb = next(n for n in gm.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    if sp_ is not None and not sp_.inputs['Base Color'].is_linked and sp_.inputs['Alpha'].default_value < 1:
        col, al, ro = tuple(sp_.inputs['Base Color'].default_value), sp_.inputs['Alpha'].default_value, sp_.inputs['Roughness'].default_value
    else:
        col, al, ro = tuple(K.floats(A.glass_color, 3)) + (1.0,), A.glass_alpha, A.glass_rough
    gb.inputs['Base Color'].default_value = col; gb.inputs['Alpha'].default_value = al
    gb.inputs['Roughness'].default_value = ro; gb.inputs['Metallic'].default_value = 0.0
    gm.surface_render_method = 'BLENDED'; gm.use_backface_culling = False
    g.data.materials.clear(); g.data.materials.append(gm)
    log(f'glass: {len(glass)} mesh(es) -> {A.glass_node}, alpha {al:.2f}')

# ------------------------------------------------------------------------------------------------ live surfaces
# --live GLOB[,GLOB]: meshes kept as their own primitive with their OWN material (name, plain Principled values,
# emission) and their own UV 0..1, not baked: screens, displays, glow cards that a surface program (Shader Lab)
# draws at run time. They are checked by the same integrity gate (a screen must not share its body's plane).
# --live-fallback DIR (Shader Lab `lab.mjs fallback`: DIR/<material>.png + fallback.json): what the part shows where
# its program does NOT run (glTF viewers, the asset dashboard, a game build without it). Without it a glow card exports
# as an opaque emissive slab and a screen as one flat colour (2026-10-13 18:05, the TV prototype on the dashboard).
# 'lit' (screens): the picture becomes the emission texture at the baked strength; 'blend' (additive glow cards): the
# card stays, fully transparent (glTF has no additive blending; alpha-blending a glow darkens light backgrounds).
FB = json.load(open(os.path.join(A.live_fallback, 'fallback.json'))) if A.live_fallback else {}
def live_fallback(m):
    f = FB.get(m.name)
    if not f: return m
    name = m.name; m2 = m.copy(); m.name = name + '.src'; m2.name = name   # the glTF keeps the program's material name
    nt = m2.node_tree; bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    if f['mode'] == 'blend':
        # an additive glow card cannot be made by glTF's alpha blending: over a light background it DARKENS (a grey halo
        # around the TV in daylight, 2026-10-13 18:2x). Where the program does not run there is no glow: the card stays
        # (the program finds it by material name) but is fully transparent.
        for k in list(nt.links):
            if k.to_node == bsdf: nt.links.remove(k)
        bsdf.inputs['Base Color'].default_value = (0, 0, 0, 1); bsdf.inputs['Alpha'].default_value = 0.0
        bsdf.inputs['Emission Strength'].default_value = 0.0; m2.surface_render_method = 'BLENDED'
        log(f"live fallback: {m2.name} transparent (additive glow; only its program draws it)"); return m2
    im = bpy.data.images.load(os.path.join(A.live_fallback, m2.name + '.png')); im.name = m2.name + '_fallback'
    t = nt.nodes.new('ShaderNodeTexImage'); t.image = im; t.interpolation = 'Linear'
    nt.links.new(t.outputs['Color'], bsdf.inputs['Emission Color']); bsdf.inputs['Emission Strength'].default_value = f['scale']
    log(f"live fallback: {m2.name} <- {m2.name}.png ({f['mode']}, strength {f['scale']}, t {f.get('t')} s)")
    return m2

lives = []
for o in live_objs:
    lc = K.low_copy([o], None, o.name, need_uv=True)
    lc.data.materials.clear()
    for sl in o.material_slots: lc.data.materials.append(live_fallback(sl.material))
    lives.append(lc); log(f'live: {o.name} -> own material {[sl.material.name for sl in o.material_slots]}')

# ------------------------------------------------------------------------------------------------ root, mounts, lights
root = bpy.data.objects.new(name, None); bpy.context.scene.collection.objects.link(root)
for k, v in json.loads(A.root_props).items(): root[k] = v
for o in (s, g, *lives):
    if o: o.parent = root
def jsonable(v):
    try: json.dumps(v); return v
    except TypeError:
        try: return list(v)
        except TypeError: return str(v)
exported_marks = []
for nm_, mw, o in src_marks:
    e = bpy.data.objects.new(nm_, None); bpy.context.scene.collection.objects.link(e)
    e.matrix_world = mw; e.parent = root
    for k in o.keys():
        if not k.startswith('_'): e[k] = jsonable(o[k])
    if o.type == 'LIGHT':
        L = o.data; e['light_type'] = L.type; e['color'] = list(L.color); e['energy_w'] = L.energy
        if L.type == 'SPOT': e['spot_size_deg'] = round(L.spot_size * 57.2958, 2); e['spot_blend'] = L.spot_blend
        if hasattr(L, 'cutoff_distance') and L.use_custom_distance: e['range_m'] = L.cutoff_distance
    e['kind'] = e.get('kind', nm_.split('.')[1] if nm_.count('.') >= 1 else '')
    exported_marks.append(nm_)
for o in bpy.context.view_layer.objects: o.select_set(False)
objs = [root] + [o for o in (s, g, *lives) if o] + [bpy.data.objects[n] for n in exported_marks]
for o in objs: o.select_set(True)
bpy.context.view_layer.objects.active = root

fmt = 'WEBP' if A.image_format == 'WEBP' else 'AUTO'      # JPEG copies were made per map above; normals stay PNG
expect = K.export_expect([o for o in objs if o.type == 'MESH'])
tmp = out + '.tmp.glb'
r = bpy.ops.export_scene.gltf(filepath=tmp, export_format='GLB', use_selection=True, export_yup=True, export_apply=True,
                              export_extras=True, export_texcoords=True, export_normals=True, export_tangents=bool(nm),
                              export_materials='EXPORT', export_image_format=fmt, export_jpeg_quality=A.jpeg_quality,
                              export_cameras=False, export_lights=False)
zt = K.glb_fix_zero_tangents(tmp) if nm else 0
if zt: log(f'tangents: {zt} zero-length TANGENT vectors replaced by a unit vector across the normal (cancelled frames at shared corners)')
st = K.glb_stats(tmp)
nouv = K.glb_texcoord_faults(tmp)
log(f'{r} {out}: {st["triangles"]} triangles, {st["draw_calls"]} draw calls, {st["kb"]} KB, '
    f'{len(st["mounts"])} mounts, {len(st["lights"])} lights, per node {st["per_node"]}')
if not A.against: log('WARNING: no --against: give the version above (near: the original GLB) so a lost part is caught')
def original_of(path):
    """The film original a version was made from: follow the export reports (<glb>.json: held_by, else against) up from
    the --against file to the one no export wrote."""
    for _ in range(4):
        try: j_ = json.load(open(path + '.json'))
        except Exception: return path
        nxt = j_.get('held_by') or j_.get('against')
        if not nxt or not os.path.exists(nxt): return path
        path = nxt
    return path
HELD = A.held_by or (original_of(A.against) if A.against else '')
ig = K.run_integrity(tmp, A.against, (['--from-below'] if A.from_below else []) + (['--held-by', HELD] if HELD else []) +
                     (['--held-tol', str(A.held_tol)] if HELD and A.held_tol else []))
for k in ('bodies', 'gaps', 'flicker', 'result'):
    if k in ig: print('  ' + ig[k], flush=True)

def inherited_faults(ij):
    """--allow-inherited: this version's floating bodies and same-facing blink pairs against the REFERENCE's own (mesh_integrity
    on --against, cached as <ref>.mi.json). Inherited = no more of either than the reference has: the fault is the
    original's, to be fixed there (a train car original 2026-10-13: 2 floating, 8 913 blink pairs)."""
    import subprocess
    rj = A.against + '.mi.json'
    if not os.path.exists(rj) or os.path.getmtime(rj) < os.path.getmtime(A.against):
        subprocess.run(['python3', K.integrity_script(), A.against, '--json', rj], capture_output=True, text=True)
    try: rr = json.load(open(rj))
    except Exception as e: return dict(inherited=False, error=f'reference not checked: {e}')
    fb = lambda d: max(0, len(d.get('bodies') or []) - 1)
    fp = lambda d: int((d.get('flicker') or {}).get('same_facing_pairs') or 0)
    hb_ = ij.get('held_by')                              # judged against the original: only the bodies it does not hold count
    me_, ref_ = dict(floating=hb_['moved'] + hb_['floating'] if hb_ else fb(ij), blink_pairs=fp(ij)), dict(floating=fb(rr), blink_pairs=fp(rr))
    return dict(inherited=all(me_[k] <= ref_[k] for k in me_), version=me_, reference=ref_, reference_report=rj)
INHERITED = None

# ---- gates (owner 2026-10-12: floating boxes and blinking end-door bands went out because nobody ran the check)
refuse = list(hash_fault)
if nouv: refuse.append(f'{len(nouv)} textured primitives without UVs (three.js speckle): {nouv[:10]}')
if bake.get('verify') and bake['verify'].get('faults') and not A.allow_bake_drift:
    refuse.append(f'the bake drifts from the original: {bake["verify"]["faults"]} (re-bake, or --allow-bake-drift)')
ij = {}
try: ij = json.load(open(tmp + '.integrity.json'))
except Exception: refuse.append('mesh_integrity gave no report: ' + str(ig.get('error') or ig.get('exit')))
fl = ij.get('flicker') or {}
HB = ij.get('held_by')
if HB: log(f'floating bodies against the original {HELD}: {HB["floating_before"]} counted, {HB["held"]} held there, {HB["inherited"]} inherited, '
           f'{HB["moved"]} moved off it, {HB["floating"]} not held (within {HB["tolerance_m"] * 1000:.1f} mm)')
if A.double_sided and fl.get('back_to_back_pairs'):
    refuse.append(f'--double-sided with {fl["back_to_back_pairs"]} back-to-back face pairs ({fl.get("back_to_back_m2", 0):.2f} m2): '
                  'they blink on a double-sided material; delete the hidden skin or export single-sided')
# game material slots against the game's contract (coordinator 2026-10-13): the game acts on material names
slot_check = None
if SL or A.contract:
    cpath = A.contract or (SL or {}).get('contract')
    names = K.contract_names(cpath) if cpath and os.path.exists(cpath) else []
    gm_names = [mm.get('name', '') for mm in K.glb_json(tmp).get('materials', [])]
    req = ((SL or {}).get('required') or {}).get(LEVEL, K.SLOT_REQUIRED.get(LEVEL, []))
    missing = [t for t in req if not any(t in n for n in gm_names)]
    stale = [t for t in req if names and not any(c in t or t in c for c in names)]
    used_roles = sorted({r for r in (slotrep or {}).get('tri_roles', []) if r})
    unknown_roles = [r for r in used_roles if names and not any(c in r for c in names)]   # the game would ignore them
    slot_check = dict(contract=cpath, contract_names=names, level=LEVEL, required=req, materials=gm_names,
                      missing=missing, required_not_in_contract=stale, roles_not_in_contract=unknown_roles,
                      mixed_triangle_share=(slotrep or {}).get('mixed_triangle_share'))
    if not names: refuse.append(f'game contract not readable: {cpath} (give --contract or "contract" in slots.json)')
    if missing: refuse.append(f'required game material slots missing at {LEVEL}: {missing} (have {gm_names}); the low needs faces '
                              f'that mostly show those parts of the original, or a slots.json role mapped to them')
    if stale or unknown_roles: refuse.append(f'slot names the game contract does not know (a new name is a game change: lead + '
                                             f'owner): required {stale}, used roles {unknown_roles}')
    if LEVEL == 'far':
        fn_ok, fn_how, fn_msg = K.far_night(gm_names, 'emit' in used, bake.get('emit_lit_share'))
        slot_check['far_night'] = dict(ok=fn_ok, how=fn_how)
        if not fn_ok: refuse.append(fn_msg)
        log(f'far night look: {fn_how}')
    log(f'slots vs contract: required {req}, missing {missing}')
# pbr_check.py (when on disk): every ERROR refuses. It owns rule E1 too (night lights declared, by light.* empties or by the
# family's GAME-CONTRACT, but no lit texels; named slots the game lights -- LED-ivory, interior-warm-grey,
# seat-ocean-fabric -- count as lit). Its `where` clusters go to OUT.glb.pbr.json.
if A.skip_pbr_check: PBRC = dict(available=False, skipped=True, errors=[], lines=['--skip-pbr-check'], result='skipped')
else:
    PBRC = K.pbr_check([tmp, '--version', LEVEL, '--json', tmp + '.pbr.json'] + (['--against', A.against] if A.against else []) +
                       (['--class-map', A.class_map] if A.class_map else []) + (['--family', A.family] if A.family else []))
for l in PBRC['lines'][:12]: log('pbr_check:', l)
if PBRC['errors']: refuse.append(f'pbr_check: {len(PBRC["errors"])} errors: ' + ' | '.join(PBRC['errors'][:6]))
gate_refuse, gates = K.glb_gates(tmp, expect, skip_validator=A.skip_validator)
v_ = gates['gltf_validator']; ri_ = gates['reimport']
vtxt = 'skipped' if v_.get('skipped') else (v_.get('error') or f"{v_.get('errors')} errors, {v_.get('warnings')} warnings")
log(f'glTF-Validator: {vtxt}; reimport: {ri_.get("got") or ri_.get("error")}' + (f' MISMATCH {ri_["mismatch"]}' if ri_.get('mismatch') else ''))
refuse += gate_refuse
try: ij = json.load(open(tmp + '.integrity.json'))
except Exception: pass
if str(ig.get('result', '')).startswith('RESULT: FAULT'):
    items = []
    for b_ in (ij.get('bodies') or [])[1:]:
        if b_.get('held') in ('held', 'inherited'): continue      # --held-by: no fault of this version
        c_ = [(b_['min'][k] + b_['max'][k]) / 2 for k in range(3)] if 'min' in b_ else [0, 0, 0]
        items.append(f'floating at ({c_[0]:.3f}, {c_[1]:.3f}, {c_[2]:.3f}) {" / ".join(b_.get("names", []))}')
    for pl in fl.get('places', []):
        c_ = pl['centre']; items.append(f'blinks at ({c_[0]:.3f}, {c_[1]:.3f}, {c_[2]:.3f}) {" / ".join(pl.get("names", []))}')
    allow = [l.strip() for l in open(A.allow_designed) if l.strip() and not l.startswith('#')] if A.allow_designed else []
    unlisted = [x for x in items if not any(a in x for a in allow)]
    complete = len(fl.get('places', [])) >= int(fl.get('same_facing_pairs', 0) or 0)
    inh = inherited_faults(ij) if A.allow_inherited and A.against else None
    if inh and inh['inherited']:
        log(f'integrity FAULT INHERITED from {A.against}: {inh}'); INHERITED = inh
    elif unlisted or not complete or not items:
        if inh: refuse.append(f'faults beyond the reference (--allow-inherited): {inh}')
        refuse.append(ig['result'] + (f'; places not in --allow-designed: {unlisted[:12]}' if unlisted else '') +
                      ('' if complete else f'; only {len(fl.get("places", []))} of {fl.get("same_facing_pairs")} blink places listed'))
    else: log(f'integrity FAULT places all named as designed in {A.allow_designed}: {len(items)}')
rep = dict(tool='3d-asset-making/scripts/export_game.py', when=time.strftime('%Y-%m-%d %H:%M:%S %z'), file=out,
           source=bpy.data.filepath, low=A.low, prefix=prefix, root=name, triangles=st['triangles'],
           draw_calls=st['draw_calls'], per_node=st['per_node'], kb=st['kb'], images=st['images'],
           maps=used, emit_strength=bake.get('emit_strength'), image_format=fmt, uv_hash=h,
           uv_hash_matches_bake=(bake.get('uv_hash') == h) if bake.get('uv_hash') else None, double_sided=A.double_sided,
           mounts=st['mounts'], lights=st['lights'], textured_without_uv=nouv, integrity=ig, against=A.against,
           held_by=HELD or None, integrity_held_by={k: v for k, v in HB.items() if k != 'places'} if HB else None,
           gltf_validator=gates['gltf_validator'], reimport=gates['reimport'], slots=slot_check, pbr_check=PBRC, tri_hash=th,
           slot_roles={r: {k: v for k, v in d.items()} for r, d in (slotrep or {}).get('roles', {}).items()} or None,
           integrity_inherited=INHERITED, refused=refuse, seconds=round(time.time() - T0, 1))
dest = out if not refuse else out[:-4] + '.rejected.glb'
os.replace(tmp, dest)
for ext in ('.integrity.txt', '.integrity.json', '.pbr.json'):
    if os.path.exists(tmp + ext): os.replace(tmp + ext, dest + ext)
ig['report'] = dest + '.integrity.txt'; rep['file'] = dest
with open(dest + '.json', 'w') as f: json.dump(rep, f, indent=1)
if refuse:
    for x in refuse: log('REFUSED:', x)
    log(f'NOT written: {out}. The checked file is {dest} (+ .integrity.txt / .json) for a look; fix the low or the bake.')
    sys.exit(1)
log('DONE', json.dumps(dict(triangles=st['triangles'], draw_calls=st['draw_calls'], kb=st['kb'], result=ig.get('result'))))
