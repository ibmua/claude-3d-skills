"""Export the film original to a GLB WITH its look, so the dashboard's 3D viewer is not white.

  nice -n 10 blender -b ORIGINAL.blend --python export_original.py -- --out ORIGINAL.glb [--collection COLL[,COLL]]
        [--exclude GLOB[,GLOB]] [--density 128] [--max-size 512] [--min-size 32] [--threads 8] [--samples 1]
        [--image-format JPEG|AUTO|WEBP] [--no-bake]

* Scope: --collection (the original; default everything visible). Collection instances are made real as linked
  duplicates (instances share one mesh in the GLB; mirrored mounts keep their negative scale, three.js flips the
  winding itself), curves and text become meshes.
* Every mesh whose material samples an image but has no usable UV map (none, or all collapsed to a point) first
  gets a box UV in metres (the material's Mapping keeps its tiling); after export the GLB is read back and the tool
  FAILS (exit 1) if any textured primitive still has no TEXCOORD (glTF texCoord -1: per-pixel speckle in three.js;
  a train car guide tyres, 2026-10-12).
* A baked mesh gets its modifiers applied BEFORE its atlas is unwrapped, and the atlas is refused when > 1 % of
  its triangles share texels (a Solidify wall's inner skin keeps the outer skin's UVs: the inner wall baked over
  the outer steel and a car looked like white plastic, 2026-10-13).
* Materials glTF can carry as they are (one Principled BSDF with plain values, image textures straight into its
  inputs, a normal map from an image, vertex colours) are exported unchanged.
* Library KINDS stay live (a design decision): a material with an `idle` record and an idle.<kind>@<ver> group exports the
  library contract (extras.idle, fallback factors, its mask as occlusion), never a bake; the dashboard viewer and the
  game draw the kind's GLSL twin (`_kit.kinds_to_contract`; 2026-10-14). Any other group ending in one Principled is
  lifted to the top level first (`_kit.lift_groups`) and baked like the rest.
* NO BAKING unless --bake-ok "<reason>" names a deliberate plan (owner 2026-10-15: "not to bake anything ... except for
  low quality assets"); without it a bake makes OUT.rejected.glb. An image x constant colour Mix is folded into a tinted
  image, not baked.
* Every other material (procedural noise/wear/grime, Mix/Add shader layers, node groups, glass shaders) is baked
  per mesh into its own small atlas: base colour (+ alpha), glTF metallic-roughness, normal when the material
  bends normals, emission when it glows. Image size by surface: --density px per metre, clamped to
  [--min-size, --max-size] (a bolt does not get 512 px), but never coarser than the largest image the material samples
  (a glyph or label keeps its detail, up to --max-size). Alpha comes only from texels a face covers (empty atlas
  texels never turn an opaque material BLEND); baked materials keep the source's backface culling. Passes: colour, one packed rough/metal/alpha pass, emission
  only for the meshes that glow, normal only for those that bend normals. All meshes of one map are baked in ONE bake call
  (one scene sync), so a 600-part original takes minutes, not an hour. A mesh shared by many copies is baked
  once and reused, unless its material reads the object itself (Object Info, Object/Instancer attributes, world
  position, a TexCoord pointing at an object): then each copy gets its own mesh and bake. Channels come from the same channel graph
  as bake.py (Mix shaders mixed by their factor, glass as a dark pane).
* Textures JPEG by default; AUTO (PNG) is used automatically when any material has alpha (decals keep their cut-out)
  or a normal map is baked (JPEG ringing breaks unit normals).
GATES before OUT.glb is replaced (written to a temp file first; refused -> OUT.rejected.glb, exit 1): textured
primitives without TEXCOORD; the Khronos glTF-Validator (errors; --skip-validator only without node); a fresh reimport
(Blender, empty scene) reading back other mesh objects / primitives / triangles / materials / textures than exported.
Writes OUT.glb.json (triangles, draw calls, KB, images, materials baked, seconds) and OUT.glb.integrity.json (gates).

When to leave only the .blend instead: when the dashboard source can point at the .blend (its exporter,
the dashboard/blender/export_blend.py, bakes procedural colour per object at 512 px by itself) and
nobody else needs the GLB. A film original that is a collection of instances in a file that ALSO holds part
libraries, review props or game versions must be exported with this tool and --collection: the dashboard would
export everything visible in that file.
"""
import argparse, json, math, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _kit as K

ap = argparse.ArgumentParser(prog='export_original.py', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('--out', required=True); ap.add_argument('--collection', default=''); ap.add_argument('--exclude', default='')
ap.add_argument('--density', type=float, default=128); ap.add_argument('--max-size', type=int, default=512)
ap.add_argument('--min-size', type=int, default=32); ap.add_argument('--threads', type=int, default=8)
ap.add_argument('--samples', type=int, default=1); ap.add_argument('--image-format', default='JPEG', choices=('JPEG', 'AUTO', 'WEBP'))
ap.add_argument('--no-bake', action='store_true'); ap.add_argument('--bake-ok', default='', help='the deliberate plan that allows baking (owner 2026-10-15: no baking except low-quality versions or a written plan); without it a bake is REFUSED'); ap.add_argument('--skip-validator', action='store_true')
A = ap.parse_args(K.script_argv())

import bpy
import numpy as np
log = lambda *a: print('[original]', *a, flush=True)
T0 = time.time(); out = os.path.abspath(A.out); os.makedirs(os.path.dirname(out), exist_ok=True)
vl = bpy.context.view_layer
colls = [bpy.data.collections.get(n) or K.die(f'no collection {n!r}') for n in K.csv(A.collection)]
if colls: K.keep_only_collections(colls)
EXC = K.csv(A.exclude)


def scope():
    s = [o for o in vl.objects if o.visible_get() and not o.hide_render]
    if colls:
        names = {o.name for c in colls for o in c.all_objects}
        s = [o for o in s if o.name in names]
    return [o for o in s if not (EXC and K.match(o.name, EXC))]


# ---- make instances real (nested too), instancers stop instancing
for _ in range(6):
    inst = [o for o in scope() if o.instance_type == 'COLLECTION' and o.instance_collection]
    inst = [o for o in inst if not (EXC and K.match(o.instance_collection.name, EXC))]
    if not inst: break
    for o in vl.objects: o.select_set(False)
    for o in inst: o.select_set(True)
    vl.objects.active = inst[0]
    bpy.ops.object.duplicates_make_real(use_base_parent=True, use_hierarchy=True)
    for o in inst: o.instance_type = 'NONE'
for o in scope():
    if o.instance_type == 'COLLECTION': o.instance_type = 'NONE'
# curves / text -> meshes (same place, same parent)
dg = bpy.context.evaluated_depsgraph_get()
for o in [o for o in scope() if o.type in ('CURVE', 'FONT', 'SURFACE', 'META')]:
    me = bpy.data.meshes.new_from_object(o.evaluated_get(dg), depsgraph=dg)
    n = bpy.data.objects.new(o.name + '.mesh', me)
    for c in o.users_collection: c.objects.link(n)
    n.parent = o.parent; n.matrix_world = o.matrix_world.copy(); o.hide_render = True; o.hide_set(True)
objs = [o for o in scope() if o.type == 'MESH']
for o in objs:                                   # materials linked to the object count for its mesh's check
    if any(s.link == 'OBJECT' for s in o.material_slots):
        mats_ = [s.material for s in o.material_slots]; o.data = o.data.copy()
        for s, m_ in zip(o.material_slots, mats_): s.link = 'DATA'; s.material = m_
uvfixed = K.fix_textured_without_uv({o.data.name: o.data for o in objs}.values())
log(f'scope: {len(objs)} mesh objects, {len({o.data.name for o in objs})} meshes; textured meshes without UVs given '
    f'a box UV in metres: {len(uvfixed)} {uvfixed[:8]}')


# ---- which materials glTF carries as they are
def native(sock, colour=True):
    if not sock.is_linked: return True
    n = sock.links[0].from_node
    if n.type == 'REROUTE': return native(n.inputs[0], colour)
    if n.type in ('RGB', 'VERTEX_COLOR', 'VALUE'): return True
    if n.type == 'ATTRIBUTE': return n.attribute_type == 'GEOMETRY'
    if n.type == 'SEPARATE_COLOR': return native(n.inputs[0])
    if n.type == 'NORMAL_MAP': return native(n.inputs['Color'])
    if n.type == 'TEX_IMAGE':
        v = n.inputs['Vector']
        if not v.is_linked: return True
        f = v.links[0].from_node
        if f.type == 'UVMAP': return True
        if f.type == 'TEX_COORD': return v.links[0].from_socket.name == 'UV'
        if f.type == 'MAPPING':      # only a UV fed mapping is glTF (KHR_texture_transform); TexCoord Object/Generated is not
            if not f.inputs[0].is_linked: return False
            l0 = f.inputs[0].links[0]
            return l0.from_node.type == 'UVMAP' or (l0.from_node.type == 'TEX_COORD' and l0.from_socket.name == 'UV')
    return False


def needs_bake(m):
    if not m or not m.node_tree: return False
    on = K.output_node(m)
    if on is None or not on.inputs['Surface'].is_linked: return False
    p = on.inputs['Surface'].links[0].from_node
    if p.type != 'BSDF_PRINCIPLED': return True
    return not all(native(p.inputs[k]) for k in ('Base Color', 'Roughness', 'Metallic', 'Alpha', 'Normal', 'Emission Color', 'Emission Strength'))


def reads_object(m):
    """Does the material read the object itself (so copies of one mesh look different and need a bake each)?"""
    def tree_reads(nt, seen):
        if nt is None or nt.as_pointer() in seen: return False
        seen.add(nt.as_pointer())
        for n in nt.nodes:
            if n.type == 'OBJECT_INFO' and any(o.links for o in n.outputs): return True
            if n.type == 'ATTRIBUTE' and n.attribute_type in ('OBJECT', 'INSTANCER'): return True
            if n.type == 'TEX_COORD' and (n.object is not None or any(n.outputs[k].links for k in ('Window', 'Camera', 'Reflection'))): return True
            if n.type == 'NEW_GEOMETRY' and any(n.outputs[k].links for k in ('Position', 'Normal', 'Incoming')): return True
            if n.type == 'GROUP' and tree_reads(n.node_tree, seen): return True
        return False
    return bool(m and m.node_tree and tree_reads(m.node_tree, set()))


# one bake per shared mesh + material set, reused by every copy; a copy whose material reads the object (Object Info,
# Object/Instancer attributes, world position, a TexCoord pointing at an object) gets its own mesh and its own bake
split = 0
users = {}
for o in objs: users.setdefault(o.data.name, []).append(o)
for mn, us in users.items():
    if len(us) > 1 and any(reads_object(s.material) for s in us[0].material_slots):
        for o in us[1:]: o.data = o.data.copy(); split += 1
meshes = {}
for o in objs: meshes.setdefault(o.data.name, []).append(o)
log(f'{len(meshes)} meshes after giving {split} object-reading copies their own mesh; '
    f'{sum(len(v) > 1 for v in meshes.values())} meshes shared by several copies (baked once)')
used = {s.material for o in objs for s in o.material_slots if s.material}
kinds = K.kinds_to_contract(used)
if kinds: log(f'{len(kinds)} library-kind materials stay live (extras.idle + fallback factors, not baked; a design decision): {", ".join(sorted(kinds)[:8])}')
lifted = K.lift_groups(used)
if lifted: log(f'{len(lifted)} Shader Lab group materials lifted to a top-level Principled: {", ".join(sorted(lifted)[:8])}')


def fold_const_mix(m):
    """Owner 2026-10-15 12:45: "not to bake anything ... except for low quality assets". A colour input fed by
    MULTIPLY(UV image, constant colour) is exact as a tinted copy of the image (in memory), which glTF carries as a
    plain texture; the validator's ring (mask x ring colour) was baked for this alone. Returns folded socket names."""
    import numpy as np
    on = K.output_node(m) if m and m.node_tree else None
    p = on.inputs['Surface'].links[0].from_node if on and on.inputs['Surface'].is_linked else None
    if not p or p.type != 'BSDF_PRINCIPLED': return []
    nt, done = m.node_tree, []
    for name in ('Base Color', 'Emission Color'):
        s = p.inputs[name]
        if not s.is_linked or s.links[0].from_node.type != 'MIX': continue
        x = s.links[0].from_node
        if x.data_type != 'RGBA' or x.blend_type != 'MULTIPLY' or x.inputs['Factor'].is_linked or x.inputs['Factor'].default_value < 0.999: continue
        a, b = x.inputs['A'], x.inputs['B']
        img, col = (a, b) if a.is_linked else (b, a)
        if col.is_linked or not img.is_linked: continue
        t = img.links[0].from_node
        if t.type != 'TEX_IMAGE' or not t.image or not native(img): continue
        c = tuple(col.default_value)[:3]
        tim = t.image.copy(); tim.name = f'{t.image.name}.x{c[0]:.2f}_{c[1]:.2f}_{c[2]:.2f}'
        px = np.empty(len(tim.pixels), np.float32); tim.pixels.foreach_get(px); px = px.reshape(-1, 4)
        px[:, :3] *= np.array(c, np.float32); tim.pixels.foreach_set(px.ravel()); tim.pack()
        tn = nt.nodes.new('ShaderNodeTexImage'); tn.image = tim; tn.interpolation = t.interpolation
        if t.inputs['Vector'].is_linked: nt.links.new(t.inputs['Vector'].links[0].from_socket, tn.inputs['Vector'])
        nt.links.new(tn.outputs['Color'], s); done.append(name)
    return done


folded = {m.name: f for m in used if (f := fold_const_mix(m))}
if folded: log(f'{len(folded)} materials: image x constant colour folded into a tinted image (not baked): {folded}')
todo = {} if A.no_bake else {mn: us for mn, us in meshes.items()
                             if any(needs_bake(s.material) for s in us[0].material_slots)}
log(f'{len(todo)} meshes have materials glTF cannot carry: baking them')
baked_mats = sorted({s.material.name for us in todo.values() for s in us[0].material_slots if s.material})

if todo:
    K.set_threads(A.threads, A.samples)
    bk = bpy.context.scene.render.bake
    bk.use_selected_to_active = False; bk.use_clear = True; bk.margin = 4; bk.target = 'IMAGE_TEXTURES'
    reps, size, copies, cull = {}, {}, {}, {}
    dg = bpy.context.evaluated_depsgraph_get(); applied = 0
    for mn, us in todo.items():
        rep = us[0]
        if any(u.modifiers for u in us):
            # apply modifiers BEFORE unwrapping: a Solidify inner skin keeps the outer skin's UVs, so an atlas made on the
            # base mesh lets the inner wall bake over the outer steel (a car white steel, 2026-10-13)
            new_me = bpy.data.meshes.new_from_object(rep.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
            for u in us: u.modifiers.clear(); u.data = new_me
            applied += 1
        me = rep.data
        for u in us:                                                  # materials on the mesh, one copy per mesh
            for s in u.material_slots:
                if s.link == 'OBJECT': mat = s.material; s.link = 'DATA'; s.material = mat
        orig_uv = next((u.name for u in me.uv_layers if u.active_render), me.uv_layers[0].name if me.uv_layers else None)
        cs = []
        for i, mat in enumerate(me.materials):
            c = (mat or bpy.data.materials.new('KIT_GREY')).copy(); c.name = f'kit:{mat.name if mat else "grey"}@{mn}'
            nt = c.node_tree
            if orig_uv and nt:
                uvn = nt.nodes.new('ShaderNodeUVMap'); uvn.uv_map = orig_uv
                for n in list(nt.nodes):
                    if n.type == 'TEX_IMAGE' and not n.inputs['Vector'].is_linked: nt.links.new(uvn.outputs[0], n.inputs['Vector'])
                    if n.type in ('UVMAP', 'NORMAL_MAP') and not n.uv_map: n.uv_map = orig_uv
                    if n.type == 'TEX_COORD':
                        for l in list(n.outputs['UV'].links): nt.links.new(uvn.outputs[0], l.to_socket)
            me.materials[i] = c; cs.append(c)
        if not me.materials:
            c = bpy.data.materials.new(f'kit:grey@{mn}'); me.materials.append(c); cs.append(c)
        copies[mn] = cs
        cull[mn] = all(m_.use_backface_culling for m_ in me.materials if m_ and not m_.name.startswith('kit:grey@'))
        atlas =me.uv_layers.new(name='KIT_ATLAS'); me.uv_layers.active = atlas
        for x in vl.objects: x.select_set(False)
        rep.hide_set(False); rep.select_set(True); vl.objects.active = rep
        with bpy.context.temp_override(active_object=rep, object=rep, selected_objects=[rep], selected_editable_objects=[rep]):
            bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.02)
            bpy.ops.object.mode_set(mode='OBJECT')
        me = rep.data; me.uv_layers.active = me.uv_layers['KIT_ATLAS']
        ovs = K.uv_overlap_share(me, 'KIT_ATLAS')
        if ovs > 0.01:                     # duplicate faces: smart project lays them on the same texels; one cell per face
            with bpy.context.temp_override(active_object=rep, object=rep, selected_objects=[rep], selected_editable_objects=[rep]):
                bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.uv.lightmap_pack(PREF_CONTEXT='ALL_FACES', PREF_MARGIN_DIV=0.3)
                bpy.ops.object.mode_set(mode='OBJECT')
            me = rep.data; me.uv_layers.active = me.uv_layers['KIT_ATLAS']; ovs = K.uv_overlap_share(me, 'KIT_ATLAS')
        if ovs > 0.01: K.die(f'{mn}: {ovs:.1%} of its triangles share atlas texels after a fresh unwrap; refusing to bake it')
        sc3 = abs(rep.matrix_world.to_3x3().determinant()) ** (2 / 3)
        area = sum(p.area for p in me.polygons) * sc3
        px = 2 ** math.ceil(math.log2(max(1.0, math.sqrt(area) * A.density)))
        # a material that samples an image (glyph, label, decal) keeps that image's detail: by area alone the ticket
        # validator's reader pad (1200 px contactless glyph) got 32 px and the glyph vanished (2026-10-14)
        src_px = max((max(n.image.size) for c in cs if c.node_tree for n in c.node_tree.nodes
                      if n.type == 'TEX_IMAGE' and n.image and n.name != '_kit_target'), default=0)
        if src_px: px = max(px, 2 ** math.ceil(math.log2(src_px)))
        size[mn] = int(min(A.max_size, max(A.min_size, px))); reps[mn] = rep
    log(f'modifiers applied before unwrapping on {applied} meshes')
    allc = [c for cs in copies.values() for c in cs]
    has_norm = {mn: any(n.type == 'BSDF_PRINCIPLED' and n.inputs['Normal'].is_linked for c in cs if c.node_tree for n in c.node_tree.nodes)
                for mn, cs in copies.items()}
    has_emit = {mn: K.has_emission(cs) for mn, cs in copies.items()}
    swap = K.MaterialSwap(allc)
    imgs = {mn: {} for mn in todo}
    passes = [('color', set(copies)), ('packed', set(copies)), ('emit', {m for m, v in has_emit.items() if v}),
              ('normal', {m for m, v in has_norm.items() if v})]
    def const_one(sock, d=0):
        """Is this channel-graph socket provably 1 (constants, mixes of ones)? Then the material is opaque, whatever
        the bake margin smears into island edges (0.5-0.99 alpha there turned opaque paint BLEND, 2026-10-14)."""
        if not sock.is_linked:
            v = sock.default_value; v = tuple(v)[:3] if hasattr(v, '__len__') else (v,)
            return min(v) >= 0.99
        n = sock.links[0].from_node
        if d > 40: return False
        if n.type == 'RGB': return min(tuple(n.outputs[0].default_value)[:3]) >= 0.99
        if n.type == 'REROUTE': return const_one(n.inputs[0], d + 1)
        if n.type == 'MIX':
            ins = {s.identifier: s for s in n.inputs}
            return const_one(ins['A_Color'], d + 1) and const_one(ins['B_Color'], d + 1)
        return False
    opaque = {}
    for ps, which in passes:
        if not which: continue
        t = time.time(); sel = []
        if ps in ('normal', 'emit'): swap.restore()        # first: new nodes made by the swap take the active state
        else: swap.set(ps)
        if ps == 'packed':
            opaque = {mn: all(const_one(n.inputs['Blue']) for c in copies[mn] if c.node_tree
                              for n in c.node_tree.nodes if n.name == K.TMP + 'pack') for mn in which}
        for mn in which:
            cs = copies[mn]
            # packed gets an alpha plane: the bake clears it to 0 and writes 1 where a face lands = the atlas coverage
            im = bpy.data.images.new(f'kit:{mn}:{ps}', size[mn], size[mn], alpha=(ps == 'packed'), float_buffer=(ps == 'emit'))
            if ps != 'color': im.colorspace_settings.name = 'Non-Color'
            imgs[mn][ps] = im
            for c in cs:
                for n in [n for n in c.node_tree.nodes if n.name == '_kit_target']: c.node_tree.nodes.remove(n)
                tn = c.node_tree.nodes.new('ShaderNodeTexImage'); tn.name = '_kit_target'; tn.image = im
                for n in c.node_tree.nodes: n.select = False
                tn.select = True; c.node_tree.nodes.active = tn          # Blender 5.2 bakes into the ACTIVE AND SELECTED node
            sel.append(reps[mn])
        for x in vl.objects: x.select_set(False)
        for r_ in sel: r_.hide_set(False); r_.select_set(True)
        vl.objects.active = sel[0]
        if ps == 'normal': res = bpy.ops.object.bake(type='NORMAL', normal_space='TANGENT')
        else: res = bpy.ops.object.bake(type='EMIT')
        log(f'pass {ps}: {res} {len(sel)} meshes in {time.time() - t:.1f} s')
        if 'FINISHED' not in res: K.die(f'bake pass {ps} was {res}: nothing written (see the Info lines above)')
    swap.restore()
    # new simple materials (one per mesh = one draw per mesh)
    for mn, rep in reps.items():
        me = rep.data; I = imgs[mn]; S_ = size[mn]
        def px(im): a = np.empty(S_ * S_ * 4, np.float32); im.pixels.foreach_get(a); return a.reshape(S_, S_, 4)
        col = px(I['color']); pk = px(I['packed'])
        # alpha only from texels a face covers: empty atlas texels (alpha 0) made 8 opaque kiosk materials
        # BLEND, and three.js draws BLEND without depth writes, so the white shell painted over the black reader pad
        cov = pk[..., 3] > 0.5
        alpha = np.where(cov, pk[..., 2], 1.0)
        has_a = not opaque.get(mn) and bool(cov.any()) and float(alpha.min()) < 0.99
        log(f'{mn}: atlas coverage {cov.mean():.1%}, opaque by graph {bool(opaque.get(mn))}, covered alpha min '
            f'{float(alpha.min()):.2f}, under 0.99 on {float((alpha < 0.99).mean()):.1%} -> {"BLEND" if has_a else "OPAQUE"}')
        if has_a: col[..., 3] = alpha
        cim = bpy.data.images.new(f'{mn}_color', S_, S_, alpha=has_a); cim.pixels.foreach_set(col.ravel())
        mr = np.ones((S_, S_, 4), np.float32); mr[..., 1] = pk[..., 0]; mr[..., 2] = pk[..., 1]
        mim = bpy.data.images.new(f'{mn}_mr', S_, S_); mim.colorspace_settings.name = 'Non-Color'; mim.pixels.foreach_set(mr.ravel())
        m = bpy.data.materials.new(f'baked:{mn}'); nt = m.node_tree; b = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
        m.use_backface_culling = cull[mn]   # glTF doubleSided only if a real source material was (an empty slot is not)
        uvn = nt.nodes.new('ShaderNodeUVMap'); uvn.uv_map = 'KIT_ATLAS'
        def tex(im):
            t = nt.nodes.new('ShaderNodeTexImage'); t.image = im; nt.links.new(uvn.outputs[0], t.inputs[0]); return t
        c = tex(cim); nt.links.new(c.outputs['Color'], b.inputs['Base Color'])
        if has_a:
            nt.links.new(c.outputs['Alpha'], b.inputs['Alpha']); m.surface_render_method = 'BLENDED'
        sp = nt.nodes.new('ShaderNodeSeparateColor'); nt.links.new(tex(mim).outputs[0], sp.inputs[0])
        nt.links.new(sp.outputs['Green'], b.inputs['Roughness']); nt.links.new(sp.outputs['Blue'], b.inputs['Metallic'])
        if 'normal' in I:
            nmap = nt.nodes.new('ShaderNodeNormalMap'); nmap.uv_map = 'KIT_ATLAS'
            nt.links.new(tex(I['normal']).outputs[0], nmap.inputs['Color']); nt.links.new(nmap.outputs[0], b.inputs['Normal'])
        if 'emit' in I:
            e = px(I['emit'])[..., :3]; peak = float(e.max())
            if peak > 1e-3:
                st = max(peak, 1.0); e4 = np.ones((S_, S_, 4), np.float32); e4[..., :3] = K.srgb_encode(e / st)
                eim = bpy.data.images.new(f'{mn}_emit', S_, S_); eim.pixels.foreach_set(e4.ravel())
                nt.links.new(tex(eim).outputs[0], b.inputs['Emission Color']); b.inputs['Emission Strength'].default_value = st
        me.polygons.foreach_set('material_index', np.zeros(len(me.polygons), np.int32))
        me.materials.clear(); me.materials.append(m)
        for u in [u for u in me.uv_layers if u.name != 'KIT_ATLAS']: me.uv_layers.remove(u)
        me.uv_layers['KIT_ATLAS'].active_render = True

alpha_any = any(m.node_tree and any(n.type == 'BSDF_PRINCIPLED' and (n.inputs['Alpha'].is_linked or n.inputs['Alpha'].default_value < 1)
                                    for n in m.node_tree.nodes) for o in objs for m in o.data.materials if m)
normals_baked = bool(todo) and any('normal' in v for v in imgs.values())   # JPEG ringing breaks unit normals (pbr_check G6)
fmt = 'AUTO' if (alpha_any or normals_baked) and A.image_format == 'JPEG' else A.image_format
for o in vl.objects: o.select_set(False)
for o in scope():
    if o.type in ('MESH', 'EMPTY'): o.hide_set(False); o.select_set(True)
sel = [o for o in vl.objects if o.select_get()]
expect = K.export_expect(sel)
tmp = out + '.tmp.glb'
r = bpy.ops.export_scene.gltf(filepath=tmp, export_format='GLB', use_selection=True, export_yup=True, export_apply=True,
                              export_extras=True, export_tangents=True, export_image_format=fmt, export_jpeg_quality=90, export_cameras=False,
                              export_lights=False, export_materials='EXPORT')
st = K.glb_stats(tmp)
nouv = K.glb_texcoord_faults(tmp)
refuse = [f'{len(nouv)} textured primitives without UVs (three.js shows speckle): {nouv[:10]}'] if nouv else []
if todo and not A.bake_ok.strip():   # owner 2026-10-15: no baking unless it is a deliberate plan
    refuse.append(f'baked {len(todo)} meshes ({", ".join(baked_mats[:8])}) without --bake-ok: give each a library kind with the '
                  f'standard idle record or a glTF-direct graph, or name the plan with --bake-ok "<reason>"')
gate_refuse, gates = K.glb_gates(tmp, expect, skip_validator=A.skip_validator)
refuse += gate_refuse
v_ = gates['gltf_validator']; ri_ = gates['reimport']
vtxt = 'skipped' if v_.get('skipped') else (v_.get('error') or f"{v_.get('errors')} errors, {v_.get('warnings')} warnings")
log(f'glTF-Validator: {vtxt}; reimport: {ri_.get("got") or ri_.get("error")}' + (f' MISMATCH {ri_["mismatch"]}' if ri_.get('mismatch') else ''))
dest = out if not refuse else out[:-4] + '.rejected.glb'
os.replace(tmp, dest)
if os.path.exists(tmp + '.integrity.json'): os.replace(tmp + '.integrity.json', dest + '.integrity.json')
rep = dict(tool='3d-asset-making/scripts/export_original.py', when=time.strftime('%Y-%m-%d %H:%M:%S %z'), file=dest,
           source=bpy.data.filepath, collection=K.csv(A.collection) or 'all visible', triangles=st['triangles'],
           draw_calls=st['draw_calls'], kb=st['kb'], images=st['images'], materials=st['materials'],
           baked_meshes=len(todo), baked_materials=baked_mats, bake_ok=A.bake_ok, uv_added=uvfixed, textured_without_uv=nouv, image_format=fmt,
           gltf_validator=gates['gltf_validator'], reimport=gates['reimport'], refused=refuse, seconds=round(time.time() - T0, 1))
with open(dest + '.json', 'w') as f: json.dump(rep, f, indent=1)
log(f'{r} {dest}: {st["triangles"]} triangles, {st["draw_calls"]} draws, {st["kb"]} KB, {st["images"]} images, '
    f'{len(todo)} meshes baked, {rep["seconds"]} s')
if refuse:
    for x in refuse: log('REFUSED:', x)
    log(f'NOT written: {out}. The checked file is {dest} for a look.'); sys.exit(1)
