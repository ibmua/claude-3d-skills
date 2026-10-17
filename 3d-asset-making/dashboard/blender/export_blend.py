"""Port one .blend to a web GLB (for the three.js viewer).
blender -b FILE.blend --python export_blend.py -- OUT.glb
Exports the saved scene, or an unlinked asset library's collections, +Y up, with extras and morphs."""
import bpy, sys, os, json, struct
import math
out = sys.argv[sys.argv.index("--") + 1]
os.makedirs(os.path.dirname(out), exist_ok=True)
tmp = out + ".tmp.glb"
# A declaration library can contain a swatch rather than the actual asset.
# Config supplies its producer's studio assembler; only call prepare(), never
# its renderer/main(), and leave all source files untouched.
assembled = False
if '--assembler' in sys.argv and any(c.get('mv_surface') for c in bpy.data.collections):
    import runpy
    from pathlib import Path
    source = Path(bpy.data.filepath)
    assembler = sys.argv[sys.argv.index('--assembler') + 1]
    module = runpy.run_path(assembler, run_name='dashboard_assembler')
    metadata, original_wood, count = module['prepare'](str(source.parents[5]), source.stem)
    module['PM'].wood = original_wood
    assembled = True
    print('ASSEMBLED actual cached surface geometry', source.stem, count, flush=True)

# libraries.write saves data blocks without a scene; Blender opens these files
# in an Empty scene. Link root collections only in that case, leaving normal
# scenes and their visibility untouched. Never modify the source .blend.
if not bpy.context.scene.objects:
    nested = {child for coll in bpy.data.collections for child in coll.children}
    for coll in bpy.data.collections:
        if coll not in nested:
            bpy.context.scene.collection.children.link(coll)
    for obj in bpy.data.objects:
        if not obj.users_collection:
            bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.update()

# glTF's use_visible filter alone does not honour Blender render-only hiding.
# Material holders, proxies and helper meshes must not reappear in the web asset.
for coll in bpy.data.collections:
    if coll.hide_render: coll.hide_viewport = True
for obj in bpy.context.scene.objects:
    if obj.hide_render: obj.hide_set(True)
bpy.context.view_layer.update()

# Parts modelled at their own pivot (a washer drum, a door) sit at the origin until the film engine places them. A
# sidecar <stem>.json "preview_at" {collection name: 4x4 row-major matrix} says where a preview puts each such
# collection: apply it to the collection's root objects (in memory only; the .blend is never saved).
side = os.path.splitext(bpy.data.filepath)[0] + ".json"
try:
    with open(side) as f: meta = json.load(f)
except FileNotFoundError:
    meta = {}
if not isinstance(meta, dict): raise RuntimeError('Asset sidecar must be a JSON object: ' + side)
def _matrix(rows, label):
    from mathutils import Matrix
    if not isinstance(rows, (list,tuple)) or len(rows) != 4 or any(len(row)!=4 for row in rows):
        raise RuntimeError('Invalid placement matrix: ' + label)
    if any(not isinstance(v,(int,float)) or not math.isfinite(v) for row in rows for v in row):
        raise RuntimeError('Non-finite placement matrix: ' + label)
    M=Matrix(rows)
    if abs(M.determinant()) < 1e-12: raise RuntimeError('Collapsed placement matrix: ' + label)
    return M
if assembled: meta = {}  # producer already returned standalone posed geometry
at = dict(meta.get("preview_at") or {})
# A standalone kit library keeps each part at its engine pivot. Its existing
# node_at records assemble it. Remove the main part's film pose/scale so the
# standalone preview shows the intrinsic asset, as the kit's studio render does.
# The largest measured part is the anchor; explicit preview_at always wins.
# Location files already carry preview_at and keep their world-space assembly.
parts = [p for p in meta.get("place", []) if p.get("node") and p.get("node_at")]
for part in meta.get('place', []):
    name=f'kit-{meta.get("id")}|{part.get("node")}'
    if part.get('node') and bpy.data.collections.get(name) and not part.get('node_at') and name not in at:
        raise RuntimeError('Missing node_at for kit part ' + name + '; rebuild/backfill its placement metadata')
if parts and meta.get("id"):
    from mathutils import Matrix
    def _volume(part):
        lo, hi = part.get("bb_prod") or part.get("bb_engine") or [[0,0,0], [0,0,0]]
        return abs((hi[0]-lo[0]) * (hi[1]-lo[1]) * (hi[2]-lo[2]))
    anchor = _matrix(max(parts, key=_volume)["node_at"], 'kit anchor').inverted()
    for part in parts:
        rows = anchor @ _matrix(part["node_at"], part['node'])
        at.setdefault(f'kit-{meta["id"]}|{part["node"]}', rows)
if at:
    from mathutils import Matrix
    for name, rows in at.items():
        coll = bpy.data.collections.get(name)
        if not coll: continue
        M = rows if isinstance(rows,Matrix) else _matrix(rows, name)
        roots = [(obj, obj.matrix_world.copy()) for obj in coll.all_objects
                 if obj.parent is None or obj.parent.name not in coll.all_objects]
        for obj, original in roots:
            obj.matrix_world = M @ original
    bpy.context.view_layer.update()
    print("PLACED", ", ".join(at))

# ALTERNATIVES side by side (owner 2026-10-14 21:06, "quite some issues": the modern-effort shell.blend keeps four
# Modern classes SHELL_09..12, all visible, all modelled at the origin; the viewer drew them on top of each other and
# they z-fought into black dashes and a frosted roof). Two or more top-level collections named as variants of one thing
# (same stem, a numbered suffix: SHELL_09, SHELL_10 …) whose visible meshes occupy the same space (bounds IoU >= 0.5 with
# the first) are variants, not an assembly (an EXTERIOR + INTERIOR pair never qualifies by name): spread them,
# in memory only, along the axis where the set is thinnest, in name order, with a gap of 25 % of that extent.
# A sidecar preview_at, or a kit with node_at placements, means the file says where things go: then nothing moves.
def _box(objs):
    from mathutils import Vector
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    return ([min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]) if pts else None
def _vol(b): return max((b[1][0]-b[0][0]) * (b[1][1]-b[0][1]) * (b[1][2]-b[0][2]), 1e-12)
def _inter(a, b): return _vol(([max(a[0][i], b[0][i]) for i in range(3)], [min(a[1][i], b[1][i]) for i in range(3)])) \
    if all(min(a[1][i], b[1][i]) > max(a[0][i], b[0][i]) for i in range(3)) else 0.0
if not at and not parts:
    tops = []
    for coll in sorted(bpy.context.scene.collection.children, key=lambda c: c.name):
        meshes = [o for o in coll.all_objects if o.type == 'MESH' and o.visible_get() and not o.hide_render]
        if meshes and not coll.hide_render: tops.append((coll, meshes, _box(meshes)))
    import re
    stem = lambda n: re.sub(r'[ ._-]*[A-Za-z]?\d+[A-Za-z]?$', '', n)   # SHELL_09 -> SHELL; Car.v2 -> Car.v ... -> Car
    iou = lambda a, b: _inter(a, b) / (_vol(a) + _vol(b) - _inter(a, b))
    if len(tops) >= 2 and len({stem(t[0].name) for t in tops}) == 1 and stem(tops[0][0].name) != tops[0][0].name \
            and not any(set(a[1]) & set(b[1]) for i, a in enumerate(tops) for b in tops[i+1:]) \
            and all(iou(tops[0][2], t[2]) >= 0.5 for t in tops[1:]):
        from mathutils import Matrix
        lo = [min(t[2][0][i] for t in tops) for i in range(3)]; hi = [max(t[2][1][i] for t in tops) for i in range(3)]
        axis = min((0, 1), key=lambda i: hi[i] - lo[i])   # sideways on the ground, never stacked up Z
        step = (hi[axis] - lo[axis]) * 1.25
        for k, (coll, meshes, _) in enumerate(tops):
            d = [0.0, 0.0, 0.0]; d[axis] = step * k; M = Matrix.Translation(d)
            for obj in coll.all_objects:
                if obj.parent is None or obj.parent.name not in coll.all_objects: obj.matrix_world = M @ obj.matrix_world
        bpy.context.view_layer.update()
        print('SIDE BY SIDE', len(tops), 'overlapping collections along', 'XY'[axis], ', '.join(t[0].name for t in tops), flush=True)

# Applied modifiers read mesh-data materials; OBJECT-linked overrides can be
# silently replaced by the original unbaked graph. Normalize on private mesh
# copies, including producer surface recipes that need no colour bake.
for obj in bpy.context.scene.objects:
    if obj.type != 'MESH' or not any(slot.link == 'OBJECT' for slot in obj.material_slots): continue
    materials = [slot.material for slot in obj.material_slots]
    obj.data = obj.data.copy()
    for slot, material in zip(obj.material_slots, materials):
        slot.link = 'DATA'; slot.material = material

# Materials the glTF exporter cannot represent come out opaque black or grey: a surface with no Principled BSDF in what
# the CAMERA sees (Mix Shader factors from Light Path are evaluated for a camera ray, so a camera-only branch counts)
# that is emission-only, an additive glow (Emission + Transparent / Add Shader, e.g. a torch beam), a holdout or bare
# Transparent cut-out, or an emission VOLUME with no surface (a club light beam). The standard glTF stand-in, in memory
# only: a Principled BSDF with the emission colour as base and emissive colour (KHR_materials_emissive_strength when
# the strength > 1); alphaMode BLEND for the see-through ones: glow / emission volume alpha 0.25, holdout / bare
# Transparent alpha 0 (invisible, as in the render); emission-only stays opaque. Principled-based materials (with their
# own alpha / emission) and node groups are left to the exporter.
_RAY = {"Is Camera Ray": 1.0}   # every other Light Path output is 0 for a camera ray

def _value(sock, depth=0, representative=False):
    """a float input's value for a camera ray, or None when it depends on anything else (textures, coordinates)"""
    if not sock.is_linked:
        v = getattr(sock, "default_value", None)
        return float(v) if isinstance(v, (int, float)) else None
    l = sock.links[0]; n = l.from_node
    if depth > 40 or l.is_muted: return None
    if n.type == "LIGHT_PATH": return _RAY.get(l.from_socket.name, 0.0)
    if n.type == "VALUE": return float(n.outputs[0].default_value)
    if representative and n.type in ("TEX_NOISE", "TEX_VORONOI"):
        return 0.5  # representative value for a procedural surface (not a camera-ray decision)
    if representative and n.type == 'MAP_RANGE' and n.data_type == 'FLOAT':
        vals=[_value(n.inputs[key],depth+1,True) for key in ('Value','From Min','From Max','To Min','To Max')]
        if None in vals: return None
        value,low,high,start,end=vals
        t=(value-low)/(high-low) if high!=low else 0.0
        if n.clamp or n.interpolation_type in ('SMOOTHSTEP','SMOOTHERSTEP'): t=min(max(t,0.0),1.0)
        if n.interpolation_type == 'SMOOTHSTEP': t=t*t*(3-2*t)
        elif n.interpolation_type == 'SMOOTHERSTEP': t=t*t*t*(t*(t*6-15)+10)
        elif n.interpolation_type != 'LINEAR': return None
        result=start+t*(end-start)
        return result if math.isfinite(result) else None
    if n.type != "MATH": return None
    a = [_value(i, depth + 1, representative) for i in n.inputs if i.enabled][:3]
    if None in a[:2 if n.operation not in ("ABSOLUTE", "SQRT", "ROUND", "FLOOR", "CEIL", "SIGN") else 1]: return None
    x, y = a[0], (a + [0.0, 0.0])[1]
    ops = {"ADD": lambda: x+y, "SUBTRACT": lambda: x-y, "MULTIPLY": lambda: x*y,
           "DIVIDE": lambda: x/y if y else 0.0, "MINIMUM": lambda: min(x,y), "MAXIMUM": lambda: max(x,y),
           "LESS_THAN": lambda: float(x<y), "GREATER_THAN": lambda: float(x>y), "ABSOLUTE": lambda: abs(x),
           "POWER": lambda: x**y, "SIGN": lambda: float((x>0)-(x<0)), "SQRT": lambda: math.sqrt(x),
           "ROUND": lambda: math.floor(x+.5), "FLOOR": lambda: math.floor(x), "CEIL": lambda: math.ceil(x)}
    try: op = ops[n.operation]()
    except (KeyError, ValueError, ZeroDivisionError, OverflowError, TypeError): return None
    if not isinstance(op, (int,float)) or not math.isfinite(op): return None
    return min(max(op, 0.0), 1.0) if n.use_clamp else op

def _camera_shaders(sock, seen):
    """the shader nodes a camera ray reaches from this shader socket"""
    for l in sock.links:
        n = l.from_node
        if l.is_muted or n in seen: continue
        seen.append(n)
        if n.type == "MIX_SHADER":
            f = _value(n.inputs[0]); a, b = [i for i in n.inputs if i.type == "SHADER"][:2]
            if f is None or f < 1: _camera_shaders(a, seen)
            if f is None or f > 0: _camera_shaders(b, seen)
        else:
            for i in n.inputs:
                if i.type == "SHADER": _camera_shaders(i, seen)
    return seen

def _const_colour(sock, depth=0):
    """an emission colour input's representative colour: its value, an RGB node, a colour ramp's mean, a colour mix of
    those (at its factor, else halfway); anything else a light grey"""
    if not sock.is_linked: return tuple(sock.default_value)[:3]
    n = sock.links[0].from_node; grey = (0.8, 0.8, 0.8)
    if depth > 20: return grey
    if n.type == "RGB": return tuple(n.outputs[0].default_value)[:3]
    if n.type == "VALTORGB":
        es = n.color_ramp.elements
        return tuple(sum(e.color[k] for e in es) / len(es) for k in range(3))
    if n.type in ("MIX", "MIX_RGB"):
        ins = {i.identifier: i for i in n.inputs if i.enabled}
        f = _value(ins.get("Factor_Float") or ins.get("Fac") or n.inputs[0], representative=True)
        a, b = (ins.get("A_Color") or ins.get("Color1")), (ins.get("B_Color") or ins.get("Color2"))
        if a is None or b is None: return grey
        f = 0.5 if f is None else min(max(f, 0.0), 1.0)
        ca, cb = _const_colour(a, depth + 1), _const_colour(b, depth + 1)
        return tuple(ca[k] + (cb[k] - ca[k]) * f for k in range(3))
    return grey

# Inspect texture graphs for baking eligibility and scalar fallback values.
def _upstream(sock, seen=None):
    seen = set() if seen is None else seen
    for link in sock.links:
        node = link.from_node
        if link.is_muted or node in seen: continue
        seen.add(node)
        for i in node.inputs: _upstream(i, seen)
    return seen


# Relocated originals sometimes retain one too many ../ segments. Recover the
# exact recorded suffix under an ancestor, never a same-named unrelated image.
# Validate before baking: Cycles otherwise bakes its magenta error into a valid GLB.
def _validate_texture_images():
    from pathlib import Path
    images = set()
    def connected(tree, sockets):
        for sock in sockets:
            for node in _upstream(sock):
                if node.type == 'TEX_IMAGE' and node.image: images.add(node.image)
                elif node.type == 'GROUP' and node.node_tree:
                    outputs = [n for n in node.node_tree.nodes if n.type == 'GROUP_OUTPUT' and n.is_active_output]
                    for output in outputs: connected(node.node_tree, output.inputs)
    materials = {slot.material for obj in bpy.context.scene.objects
                 if obj.type == 'MESH' and obj.visible_get() and not obj.hide_render
                 for slot in obj.material_slots if slot.material}
    # Instance components are not scene objects until realized below.
    for instance in bpy.context.evaluated_depsgraph_get().object_instances:
        obj = instance.object
        if instance.is_instance and obj.type == 'MESH' and not obj.hide_render:
            materials.update(slot.material for slot in obj.material_slots if slot.material)
    for material in materials:
        if not material.use_nodes: continue
        output = material.node_tree.get_output_node('ALL')
        if output: connected(material.node_tree, output.inputs)
    for im in sorted(images, key=lambda im: im.name):
        if im.packed_file or im.source != 'FILE': continue
        # Match Blender's lexical .. normalization before the OS follows symlinks
        # (the train's assets-lib symlink made is_file(raw_path) a false assurance).
        resolved = Path(os.path.normpath(bpy.path.abspath(im.filepath, library=im.library)))
        if not resolved.is_file():
            parts = im.filepath[2:].split('/') if im.filepath.startswith('//') else []
            while parts and parts[0] in ('..', '.'): parts.pop(0)
            origin = Path(im.library.filepath if im.library else bpy.data.filepath).resolve().parent
            candidates = {candidate.resolve() for parent in (origin, *origin.parents)
                          if parts and (candidate := parent.joinpath(*parts)).is_file()}
            if len(candidates) > 1:
                raise RuntimeError('Ambiguous texture path: ' + im.name + ': ' + str(sorted(map(str, candidates))))
            if not candidates:
                raise RuntimeError('Missing texture: ' + im.name + ': ' + im.filepath)
            resolved = candidates.pop()
            print('GLTF TEXTURE RECOVERED', im.name, '->', str(resolved), flush=True)
            im.filepath = str(resolved)
        im.reload()
        if min(im.size) <= 0:
            raise RuntimeError('Unreadable texture: ' + im.name + ': ' + str(resolved))

_validate_texture_images()

# Shader Lab materials (idle.paint.worn@1, idle.glass.window@1 …) are ONE group node whose shader output reaches the
# Material Output; the Principled and its images live inside. Neither the stand-in nor the bake below looks inside a
# group, and glTF then wrote the group's first inner image raw as Base Color (modern-effort shell, 2026-10-14: confetti
# paint, white windscreen). Lift that Principled to the material level, in memory: constants are copied, group inputs
# are followed outward, every other channel leaves the group through an added output, so it still evaluates inside the
# group and the ordinary bake applies. Nested groups lift inside-out. A group ending in anything but one Principled stays.
#
# Library KINDS are not baked (a design decision, 3d-asset-making skill: "materials stay shaders through near and mid"). A material
# with an `idle` record {kind, slot, p} whose surface is an `idle.<kind>@<ver>` group exports the library's contract
# (library/idle_export.py): the record as extras.idle, fallback factors from p for plain viewers, the group's Mask image
# as occlusionTexture, its Base Normal as the normal. The viewer draws the kind's GLSL twin live (web/src/livePrograms.ts).
def _idle_record(m):
    v = m.get('idle') if hasattr(m, 'get') else None
    if v is not None:
        v = v.to_dict() if hasattr(v, 'to_dict') else json.loads(v) if isinstance(v, str) else v
        if isinstance(v, dict) and v.get('kind') and isinstance(v.get('p'), dict): return v
    return _idle_record_from_group(m)
# Mirror of _kit.idle_record_from_group (owner 2026-10-15 18:18): an `idle.<kind>@<ver>` group wired to the Surface IS
# that kind, its unlinked inputs are the params; a missing `idle` property no longer turns a library kind into a bake.
def _idle_record_from_group(m):
    if not getattr(m, 'node_tree', None): return None
    on = m.node_tree.get_output_node('ALL')
    if on is None or not on.inputs['Surface'].links: return None
    g = on.inputs['Surface'].links[0].from_node
    if g.type != 'GROUP' or not g.node_tree or not g.node_tree.name.startswith('idle.'): return None
    p = {}
    for i in g.inputs:
        if i.is_linked or not hasattr(i, 'default_value') or i.name[:1].isupper(): continue
        v = i.default_value
        p[i.name] = [round(float(x), 5) for x in tuple(v)[:3]] if hasattr(v, '__len__') else round(float(v), 5)
    return {'kind': g.node_tree.name[len('idle.'):], 'slot': m.name, 'p': p, 'from': 'group wiring'}
def _occlusion_input(nt):
    g = bpy.data.node_groups.get('glTF Material Output')
    if g is None:
        g = bpy.data.node_groups.new('glTF Material Output', 'ShaderNodeTree')
        g.interface.new_socket('Occlusion', in_out='INPUT', socket_type='NodeSocketFloat')
    n = nt.nodes.new('ShaderNodeGroup'); n.node_tree = g
    return n.inputs['Occlusion']
IDLE_KIND = []
for m in bpy.data.materials:
    if not m.use_nodes or not m.node_tree or not m.users: continue
    rec = _idle_record(m); onode = m.node_tree.get_output_node('ALL')
    links = onode.inputs['Surface'].links if onode else []
    g = links[0].from_node if links else None
    if not rec or not g or g.type != 'GROUP' or not g.node_tree or not g.node_tree.name.startswith('idle.'): continue
    nt = m.node_tree; p = rec['p']; pb = nt.nodes.new('ShaderNodeBsdfPrincipled')
    col = list(p.get('color') or p.get('lens') or p.get('tint') or p.get('light') or [0.5, 0.5, 0.5])[:3]
    alpha = float(p.get('opacity', 1.0))
    pb.inputs['Base Color'].default_value = (*col, 1.0); pb.inputs['Alpha'].default_value = alpha
    pb.inputs['Metallic'].default_value = float(p.get('metal', 0.0)); pb.inputs['Roughness'].default_value = float(p.get('rough', 0.5))
    if 'lamp' in rec['kind']:
        pb.inputs['Emission Color'].default_value = (*list(p['light'])[:3], 1.0)
        pb.inputs['Emission Strength'].default_value = float(p.get('day', 1.0))
    if 'paint.metallic' in rec['kind']:
        pb.inputs['Coat Weight'].default_value = float(p.get('coat', 1.0)); pb.inputs['Coat Roughness'].default_value = float(p.get('coat_rough', 0.04))
    mask = g.inputs.get('Mask')
    if mask is not None and mask.is_linked and mask.links[0].from_node.type == 'TEX_IMAGE':
        sep = nt.nodes.new('ShaderNodeSeparateColor'); nt.links.new(mask.links[0].from_node.outputs['Color'], sep.inputs[0])
        nt.links.new(sep.outputs['Red'], _occlusion_input(nt))
    normal = g.inputs.get('Base Normal')
    if normal is not None and normal.is_linked: nt.links.new(normal.links[0].from_socket, pb.inputs['Normal'])
    nt.links.new(pb.outputs['BSDF'], onode.inputs['Surface'])
    if alpha < 1:
        if hasattr(m, 'surface_render_method'): m.surface_render_method = 'BLENDED'
        else: m.blend_method = 'BLEND'
    m['idle'] = rec   # a plain dict again: glTF writes it as extras.idle
    IDLE_KIND.append(f"{m.name}={rec['kind']}")
if IDLE_KIND: print('GLTF IDLE KINDS (live, not baked)', len(IDLE_KIND), ', '.join(IDLE_KIND[:12]), flush=True)

_LIFTED = {}   # group tree -> {Principled input identifier: added group output identifier}
def _assign(sock, value):
    try: sock.default_value = value; return
    except (TypeError, ValueError, AttributeError): pass
    seq = tuple(value) if hasattr(value, '__len__') else None
    try: sock.default_value = sum(seq[:3]) / 3 if seq else (value, value, value, 1.0)[:len(sock.default_value)]
    except (TypeError, ValueError, AttributeError): pass
def _lift(tree, gnode, out_sock, depth=0):
    gt = gnode.node_tree
    if not gt or depth > 8: return None
    gout = next((n for n in gt.nodes if n.type == 'GROUP_OUTPUT' and n.is_active_output), None)
    inner = gout and next((s for s in gout.inputs if s.identifier == out_sock.identifier), None)
    if not inner or not inner.is_linked: return None
    src = inner.links[0].from_node
    if src.type == 'GROUP': src = _lift(gt, src, inner.links[0].from_socket, depth + 1)
    if not src or src.type != 'BSDF_PRINCIPLED': return None
    lifted = _LIFTED.setdefault(gt.name_full, {})
    pb = tree.nodes.new('ShaderNodeBsdfPrincipled')
    for attr in ('distribution', 'subsurface_method'):
        if hasattr(src, attr): setattr(pb, attr, getattr(src, attr))
    for i in src.inputs:
        o = next((s for s in pb.inputs if s.identifier == i.identifier), None)
        if o is None or i.type == 'SHADER': continue
        link = i.links[0] if i.is_linked and not i.links[0].is_muted else None
        if link is None:
            if hasattr(i, 'default_value'): _assign(o, i.default_value)
            continue
        n = link.from_node
        if n.type in ('VALUE', 'RGB'): _assign(o, link.from_socket.default_value); continue
        if n.type == 'GROUP_INPUT':
            outer = next(s for s in gnode.inputs if s.identifier == link.from_socket.identifier)
            if outer.is_linked: tree.links.new(outer.links[0].from_socket, o)
            elif hasattr(outer, 'default_value'): _assign(o, outer.default_value)
            continue
        ident = lifted.get(i.identifier)
        if ident is None:
            b = i.bl_idname
            kind = 'NodeSocketColor' if 'Color' in b else 'NodeSocketVector' if 'Vector' in b else 'NodeSocketFloat' if 'Float' in b else None
            if kind is None: continue
            ident = lifted[i.identifier] = gt.interface.new_socket('dash.' + i.name, in_out='OUTPUT', socket_type=kind).identifier
            gt.links.new(link.from_socket, next(s for s in gout.inputs if s.identifier == ident))
        tree.links.new(next(s for s in gnode.outputs if s.identifier == ident), o)
    for l in list(out_sock.links): tree.links.new(pb.outputs['BSDF'], l.to_socket)
    return pb
LIFT = []
for m in bpy.data.materials:
    if not m.use_nodes or not m.node_tree or not m.users: continue
    onode = m.node_tree.get_output_node('ALL')
    if not onode: continue
    for l in list(onode.inputs['Surface'].links):
        if l.from_node.type == 'GROUP' and _lift(m.node_tree, l.from_node, l.from_socket): LIFT.append(m.name)
if LIFT: print('GLTF LIFTED GROUP PRINCIPLED', len(LIFT), ', '.join(LIFT[:12]), flush=True)

STANDIN = []
for m in bpy.data.materials:
    if not m.use_nodes or not m.node_tree or not m.users: continue
    onode = m.node_tree.get_output_node("ALL")
    if not onode: continue
    sh = _camera_shaders(onode.inputs["Surface"], [])
    vol = not sh and _camera_shaders(onode.inputs["Volume"], [])
    kinds = {n.type for n in sh or vol or []}
    if not kinds or kinds & {"BSDF_PRINCIPLED", "GROUP"}: continue
    emit = [n for n in sh or vol if n.type == "EMISSION"]
    see = bool(vol) or bool(kinds & {"BSDF_TRANSPARENT", "ADD_SHADER", "HOLDOUT"})
    if not kinds <= {"EMISSION", "BSDF_TRANSPARENT", "HOLDOUT", "MIX_SHADER", "ADD_SHADER"}: continue   # another BSDF too
    nt = m.node_tree; p = nt.nodes.new("ShaderNodeBsdfPrincipled")
    col = _const_colour(emit[0].inputs["Color"]) if emit else (0.0, 0.0, 0.0)
    s = emit[0].inputs["Strength"] if emit else None
    strength = (s.default_value if not s.is_linked else 1.0) if emit else 0.0
    p.inputs["Base Color"].default_value = col + (1.0,)
    p.inputs["Emission Color"].default_value = col + (1.0,)
    if emit and emit[0].inputs['Color'].is_linked:
        source = emit[0].inputs['Color'].links[0].from_socket
        nt.links.new(source,p.inputs['Base Color']); nt.links.new(source,p.inputs['Emission Color'])
    p.inputs["Emission Strength"].default_value = strength
    alpha = (0.25 if emit else 0.0) if see else 1.0
    p.inputs["Alpha"].default_value = alpha
    for l in list(onode.inputs["Volume"].links): nt.links.remove(l)
    nt.links.new(p.outputs["BSDF"], onode.inputs["Surface"])
    if alpha < 1:
        if hasattr(m, "surface_render_method"): m.surface_render_method = "BLENDED"
        else: m.blend_method = "BLEND"
    STANDIN.append(f"{m.name}={'glow' if emit and see else 'emissive' if emit else 'cutout'}")
if STANDIN: print("GLTF STAND-IN", ", ".join(STANDIN))

# Bake colour graphs that native glTF cannot express instead of exporting default
# white (or destroying texture/attribute-dependent colour with a guessed mean).
# These are in-memory copies; the source .blend, rig, morphs and original UVs survive.
def _native_colour(sock, mesh):
    if not sock.is_linked: return True
    link = sock.links[0]; n = link.from_node
    if n.type in ("RGB", "VERTEX_COLOR"): return True
    if n.type == "ATTRIBUTE": return n.attribute_type == 'GEOMETRY' and n.attribute_name in mesh.color_attributes
    if n.type == "TEX_IMAGE":
        return all(a.type in ("TEX_IMAGE", "UVMAP", "MAPPING", "TEX_COORD") for a in _upstream(sock)) and not any(
            l.from_node.type == 'TEX_COORD' and l.from_socket.name != 'UV'
            for a in _upstream(sock) for s in a.inputs for l in s.links)
    if n.type == 'MIX_RGB' and n.blend_type == 'MULTIPLY' and not n.inputs[0].is_linked and n.inputs[0].default_value == 1:
        return all(_native_colour(i, mesh) for i in (n.inputs[1],n.inputs[2]))
    return False

BAKED = []
BAKE_SIZE = 512
SECONDARY_COLOURS = {'Sheen Tint': 'Sheen Weight', 'Specular Tint': 'Specular IOR Level',
                     'Coat Tint': 'Coat Weight', 'Emission Color': 'Emission Strength'}
def _secondary_unsupported(pb, mesh):
    return [name for name, weight in SECONDARY_COLOURS.items()
            if pb.inputs.get(name) and pb.inputs.get(weight)
            and (pb.inputs[weight].is_linked or pb.inputs[weight].default_value > 0)
            and not _native_colour(pb.inputs[name], mesh)]
def _scalar_unsupported(pb, mesh):
    return any(pb.inputs[name].is_linked and not _native_colour(pb.inputs[name], mesh)
               and _value(pb.inputs[name],representative=True) is None
               for name in ('Roughness','Metallic','Alpha'))
def _usable_uv(mesh):
    uv = mesh.uv_layers.active
    if not uv or not len(uv.data): return False
    import numpy as np
    values=np.empty(len(uv.data)*2,dtype=np.float32);uv.data.foreach_get('uv',values)
    values=values.reshape(-1,2)
    return bool(np.isfinite(values).all() and np.ptp(values,axis=0).min()>1e-6)
def _uv_overlaps(mesh):
    # Faces that share texture space (a Solidify wall's inner skin keeps the outer skin's UVs; mirrored halves) bake
    # over each other: a car's steel took the inner wall's metallic 0 and looked like white plastic (2026-10-13).
    import numpy as np
    uv = mesh.uv_layers.active
    if not uv or not len(mesh.polygons): return False
    mesh.calc_loop_triangles(); n = len(mesh.loop_triangles)
    if not n: return False
    loops = np.empty(n*3, dtype=np.int32); mesh.loop_triangles.foreach_get('loops', loops)
    uvs = np.empty(len(uv.data)*2, dtype=np.float32); uv.data.foreach_get('uv', uvs)
    cent = uvs.reshape(-1, 2)[loops].reshape(n, 3, 2).mean(1)
    _, counts = np.unique(np.round(cent, 5), axis=0, return_counts=True)
    return (counts[counts > 1].sum() / n) > 0.01
def _samples_image(pb):
    # Any image feeding the surface (colour, roughness, normal …) needs real UVs in glTF;
    # without them the exporter writes texCoord -1 and the viewer shows per-pixel speckle.
    return any(a.type == 'TEX_IMAGE' for sock in pb.inputs if sock.is_linked for a in _upstream(sock))
def _box_uv(mesh):
    # Box projection in metres (the material's Mapping node keeps its tiling); in memory only.
    import bmesh
    bm = bmesh.new(); bm.from_mesh(mesh); layer = bm.loops.layers.uv.new('DashboardUV')
    for f in bm.faces:
        ax = max(range(3), key=lambda i: abs(f.normal[i])); a, b = [i for i in range(3) if i != ax]
        for l in f.loops: l[layer].uv = (l.vert.co[a], l.vert.co[b])
    bm.to_mesh(mesh); bm.free()
    mesh.uv_layers.active = mesh.uv_layers['DashboardUV']; mesh.uv_layers['DashboardUV'].active_render = True
sc = bpy.context.scene
# A film original assembled from linked component libraries (a car: 40 components) shows its parts through collection
# instances, which neither this bake nor the UV check can reach: glTF then wrote rubber.png raw as colour, roughness
# and normal map (owner 2026-10-12, speckled guide tyres). Make them real in memory; nested instances too.
for _ in range(4):
    inst = [o for o in sc.objects if o.instance_type == 'COLLECTION' and o.instance_collection and o.visible_get()]
    if not inst: break
    bpy.ops.object.select_all(action='DESELECT')
    for o in inst: o.select_set(True)
    bpy.context.view_layer.objects.active = inst[0]
    bpy.ops.object.duplicates_make_real(use_base_parent=True, use_hierarchy=True)
    for o in inst: o.instance_type = 'NONE'
    print('GLTF REALIZED', len(inst), flush=True)
for obj in sc.objects:
    if obj.hide_render: obj.hide_set(True)
bpy.context.view_layer.update()
def _nodes(tree, seen=None):
    seen = set() if seen is None else seen
    if tree.name_full in seen: return
    seen.add(tree.name_full)
    for n in tree.nodes:
        yield n
        if n.type == 'GROUP' and n.node_tree: yield from _nodes(n.node_tree, seen)
def _per_object(m):
    # Graphs that read the object itself cannot share one bake between copies of a mesh (group insides included).
    return any(n.type == 'OBJECT_INFO' or (n.type == 'ATTRIBUTE' and n.attribute_type in ('OBJECT', 'INSTANCER'))
               or (n.type == 'TEX_COORD' and n.object) for n in _nodes(m.node_tree))
SHARED = {}   # (source mesh, materials) -> baked mesh: copies of one component share one bake
for obj in list(sc.objects):
    if obj.type != 'MESH' or not obj.visible_get() or obj.hide_render: continue
    has_uv = _usable_uv(obj.data)
    candidates = []
    for slot in obj.material_slots:
        m = slot.material
        if not m or not m.use_nodes: continue
        outnode = m.node_tree.get_output_node('ALL')
        if not outnode: continue
        shaders = _camera_shaders(outnode.inputs['Surface'], [])
        pbs = [n for n in shaders if n.type == 'BSDF_PRINCIPLED']
        if len(pbs) == 1 and (not _native_colour(pbs[0].inputs['Base Color'], obj.data)
                             or _secondary_unsupported(pbs[0], obj.data)
                             or _scalar_unsupported(pbs[0], obj.data)):
            candidates.append(slot)
    if not candidates: continue
    share = None if any(_per_object(sl.material) for sl in obj.material_slots if sl.material and sl.material.use_nodes) \
        else (obj.data.name_full, tuple(sl.material.name_full if sl.material else '' for sl in obj.material_slots),
              tuple((md.type, md.name) for md in obj.modifiers))
    if share in SHARED:
        obj.data = SHARED[share]
        for slot in obj.material_slots: slot.link = 'DATA'
        continue
    print('GLTF BAKE', obj.name, len(candidates), flush=True)
    # Bake what is exported: modifiers applied first (the export applies them anyway). A live Solidify makes the inner
    # skin only at evaluation and copies the outer skin's UVs onto it, so neither the overlap check nor a fresh unwrap
    # of the base mesh could separate them (a car steel, 2026-10-13). Rigged or shape-keyed meshes keep theirs.
    if obj.modifiers and not obj.data.shape_keys and not any(md.type == 'ARMATURE' for md in obj.modifiers):
        dg = bpy.context.evaluated_depsgraph_get()
        obj.data = bpy.data.meshes.new_from_object(obj.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
        obj.modifiers.clear()
        has_uv = _usable_uv(obj.data)
    else:
        obj.data = obj.data.copy()
    if share: SHARED[share] = obj.data
    old_uv = obj.data.uv_layers.active
    old_uv_name = old_uv.name if old_uv else None
    # Reuse authored charts, but pack them into an independent non-overlapping
    # atlas. Smart-projecting hundreds of thousands of hair faces is quadratic.
    # A collapsed/missing UV map still needs an actual unwrap.
    usable_uv = has_uv and not _uv_overlaps(obj.data)
    if has_uv and not usable_uv: print('GLTF UV OVERLAP', obj.name, 'unwrapped afresh', flush=True)
    # Pin original UV lookups before making an export atlas active. Cloned materials
    # prevent this per-object UV name from changing another object's surface.
    for slot in obj.material_slots:
        if not slot.material or not slot.material.use_nodes: continue
        copied = slot.material.copy(); slot.link = 'DATA'; slot.material = copied
        if old_uv_name:
            nt = slot.material.node_tree; uv = nt.nodes.new('ShaderNodeUVMap'); uv.uv_map = old_uv_name
            for n in list(nt.nodes):
                if n.type == 'UVMAP' and not n.uv_map: n.uv_map = old_uv_name
                if n.type == 'TEX_IMAGE' and not n.inputs['Vector'].is_linked:
                    nt.links.new(uv.outputs['UV'],n.inputs['Vector'])
                if n.type == 'TEX_COORD':
                    for link in list(n.outputs['UV'].links): nt.links.new(uv.outputs['UV'],link.to_socket)
    atlas = obj.data.uv_layers.new(name='DashboardAtlas')
    atlas_name = atlas.name  # UV-layer RNA handles are invalidated by the edit-mode unwrap.
    obj.data.uv_layers.active = atlas; atlas.active_render = True
    bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True); bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
    if usable_uv:
        bpy.ops.uv.select_all(action='SELECT')
        bpy.ops.uv.pack_islands(rotate=False, margin=0.002, shape_method='AABB')
    else:
        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.02)
    bpy.ops.object.mode_set(mode='OBJECT')
    entries=[]
    for slot in candidates:
        m=slot.material; nt=m.node_tree; on=nt.get_output_node('ALL')
        pb=next(n for n in _camera_shaders(on.inputs['Surface'],[]) if n.type=='BSDF_PRINCIPLED')
        entries.append((m,nt,on,pb))
    sc.render.engine='CYCLES'; sc.cycles.device='CPU'; sc.cycles.samples=1
    sc.render.bake.use_clear=True; sc.render.bake.margin=8; sc.render.bake.target='IMAGE_TEXTURES'
    sc.render.bake.use_selected_to_active=False
    def image(name, data=False):
        im=bpy.data.images.new(name,width=BAKE_SIZE,height=BAKE_SIZE,alpha=True)
        if data: im.colorspace_settings.name='Non-Color'
        return im
    def bake_target(im, kind):
        active=[]
        for slot in obj.material_slots:
            m=slot.material
            if not m or not m.use_nodes: continue
            nt=m.node_tree; n=nt.nodes.new('ShaderNodeTexImage'); n.image=im
            nt.nodes.active=n; active.append((nt,n))
        bpy.ops.object.bake(type=kind)
        for nt,n in active: nt.nodes.remove(n)
    def emission_bake(im, packed=False, socket_name='Base Color'):
        changes=[]
        for m,nt,on,pb in entries:
            links=[l.from_socket for l in on.inputs['Surface'].links]
            emit=nt.nodes.new('ShaderNodeEmission'); emit.inputs['Strength'].default_value=1
            extra=[]
            if packed:
                combine=nt.nodes.new('ShaderNodeCombineColor'); extra.append(combine)
                for key,channel in [('Alpha','Red'),('Roughness','Green'),('Metallic','Blue')]:
                    sock=pb.inputs[key]
                    if sock.is_linked: nt.links.new(sock.links[0].from_socket,combine.inputs[channel])
                    else: combine.inputs[channel].default_value=sock.default_value
                nt.links.new(combine.outputs[0],emit.inputs['Color'])
            else:
                sock=pb.inputs[socket_name]
                if sock.is_linked: nt.links.new(sock.links[0].from_socket,emit.inputs['Color'])
                else: emit.inputs['Color'].default_value=sock.default_value
            nt.links.new(emit.outputs[0],on.inputs['Surface']); changes.append((nt,on,links,[emit,*extra]))
        try: bake_target(im,'EMIT')
        finally:
            for nt,on,links,nodes in changes:
                for l in list(on.inputs['Surface'].links): nt.links.remove(l)
                for sock in links: nt.links.new(sock,on.inputs['Surface'])
                for n in nodes: nt.nodes.remove(n)
    colour=image('dashboard:'+obj.name+':base'); emission_bake(colour)
    secondary={}
    for name in SECONDARY_COLOURS:
        if any(name in _secondary_unsupported(pb, obj.data) for _,_,_,pb in entries):
            secondary[name]=image('dashboard:'+obj.name+':'+name)
            emission_bake(secondary[name],socket_name=name)
    packed=image('dashboard:'+obj.name+':orm',True); emission_bake(packed,True)
    normal=None
    if any(pb.inputs['Normal'].is_linked for _,_,_,pb in entries):
        normal=image('dashboard:'+obj.name+':normal',True); bake_target(normal,'NORMAL')
    import numpy as np
    rgba=np.empty(BAKE_SIZE*BAKE_SIZE*4,dtype=np.float32); colour.pixels.foreach_get(rgba)
    orm=np.empty_like(rgba); packed.pixels.foreach_get(orm)
    rgba[3::4]=orm[0::4]; colour.pixels.foreach_set(rgba); colour.update()
    for im in (colour,packed,normal,*secondary.values()):
        if im: im.pack()
    for m,nt,on,pb in entries:
        uv=nt.nodes.new('ShaderNodeUVMap'); uv.uv_map=atlas_name
        tex=nt.nodes.new('ShaderNodeTexImage'); tex.image=colour; nt.links.new(uv.outputs[0],tex.inputs['Vector'])
        alpha=pb.inputs['Alpha'].is_linked or pb.inputs['Alpha'].default_value < 1
        same_emission = (pb.inputs['Emission Color'].is_linked and pb.inputs['Base Color'].is_linked
                         and pb.inputs['Emission Color'].links[0].from_socket == pb.inputs['Base Color'].links[0].from_socket)
        nt.links.new(tex.outputs['Color'],pb.inputs['Base Color'])
        if same_emission: nt.links.new(tex.outputs['Color'],pb.inputs['Emission Color'])
        for name, im in secondary.items():
            extra=nt.nodes.new('ShaderNodeTexImage'); extra.image=im
            nt.links.new(uv.outputs[0],extra.inputs['Vector']); nt.links.new(extra.outputs['Color'],pb.inputs[name])
        if alpha: nt.links.new(tex.outputs['Alpha'],pb.inputs['Alpha'])
        ormtex=nt.nodes.new('ShaderNodeTexImage'); ormtex.image=packed; nt.links.new(uv.outputs[0],ormtex.inputs['Vector'])
        separate=nt.nodes.new('ShaderNodeSeparateColor'); nt.links.new(ormtex.outputs['Color'],separate.inputs[0])
        nt.links.new(separate.outputs['Green'],pb.inputs['Roughness']); nt.links.new(separate.outputs['Blue'],pb.inputs['Metallic'])
        if normal:
            ntex=nt.nodes.new('ShaderNodeTexImage'); ntex.image=normal; nt.links.new(uv.outputs[0],ntex.inputs['Vector'])
            nmap=nt.nodes.new('ShaderNodeNormalMap'); nmap.uv_map=atlas_name
            nt.links.new(ntex.outputs['Color'],nmap.inputs['Color']); nt.links.new(nmap.outputs['Normal'],pb.inputs['Normal'])
        BAKED.append(m.name)
if BAKED: print('GLTF BAKED MATERIALS',len(BAKED),flush=True)

# Textured meshes without UVs, left after the bake (their native image graphs were not baked)
# (a car: 268 meshes exported with texCoord -1 showed per-pixel speckle in the viewer).
NO_UV = {}
for ob in sc.objects:
    if ob.type != 'MESH' or ob.data is None or not ob.visible_get() or _usable_uv(ob.data): continue
    for slot in ob.material_slots:
        m = slot.material
        if not m or not m.use_nodes or not m.node_tree: continue
        on = m.node_tree.get_output_node('ALL')
        if on and any(_samples_image(pb) for pb in _camera_shaders(on.inputs['Surface'], []) if pb.type == 'BSDF_PRINCIPLED'):
            NO_UV[ob.data.name_full] = ob.data; break
for mesh in NO_UV.values():
    if mesh.library: mesh.make_local()
    _box_uv(mesh)
if NO_UV: print('GLTF BOX UV', len(NO_UV), ', '.join(sorted(m.name for m in NO_UV.values())[:12]), flush=True)

for m in bpy.data.materials:
    if not m.use_nodes or not m.node_tree or not m.users: continue
    outnode = m.node_tree.get_output_node("ALL")
    if not outnode: continue
    for p in _camera_shaders(outnode.inputs["Surface"], []):
        if p.type != "BSDF_PRINCIPLED": continue
        for name in ("Roughness", "Metallic"):
            sock = p.inputs[name]
            upstream = _upstream(sock)
            if not upstream: continue
            if any(n.type in ("TEX_IMAGE", "GROUP", "ATTRIBUTE", "VERTEX_COLOR") for n in upstream): continue
            value = _const_colour(sock) + (1.0,) if name == 'Base Color' else _value(sock, representative=True)
            if value is None: continue
            for link in list(sock.links): m.node_tree.links.remove(link)
            sock.default_value = value
            print("GLTF PROCEDURAL MEAN", m.name, name, value)


try:
    bpy.ops.export_scene.gltf(filepath=tmp, export_format="GLB", use_visible=True, export_apply=True,
                              export_yup=True, export_extras=True, export_morph=True, export_cameras=False,
                              export_lights=False)
    with open(tmp, "rb") as f:
        header = f.read(20)
        doc = json.loads(f.read(struct.unpack_from("<I", header, 12)[0]))
    accessors = doc.get("accessors", [])
    if not any(accessors[p["attributes"]["POSITION"]].get("count", 0) >= 3
               for mesh in doc.get("meshes", []) for p in mesh.get("primitives", [])
               if "POSITION" in p.get("attributes", {})):
        raise RuntimeError("No visible geometry in the Blender asset; GLB export was not saved")
    # A textured primitive with no UV set renders as per-pixel speckle in three.js (a car tyres, 2026-10-12).
    def _textured(mat):
        pbr = mat.get("pbrMetallicRoughness", {})
        return any(k in pbr for k in ("baseColorTexture", "metallicRoughnessTexture")) or any(
            k in mat for k in ("normalTexture", "occlusionTexture", "emissiveTexture"))
    mats = doc.get("materials", [])
    no_uv = sorted({mesh.get("name", "?") for mesh in doc.get("meshes", []) for p in mesh.get("primitives", [])
                    if "material" in p and _textured(mats[p["material"]])
                    and not any(k.startswith("TEXCOORD_") for k in p.get("attributes", {}))})
    if no_uv:
        raise RuntimeError(f"{len(no_uv)} textured meshes have no UV set (would show speckle): {', '.join(no_uv[:12])}")
    os.replace(tmp, out)
finally:
    if os.path.exists(tmp):
        os.remove(tmp)
print("EXPORTED", out)
