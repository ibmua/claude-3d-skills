"""Thumbnail of one GLB: Workbench (studio light, textures, cavity), perspective 3/4 view from the asset's front.
blender -b --factory-startup -noaudio --python render_glb.py -- IN.glb OUT.png [WIDTH HEIGHT]
Hides LOD1/impostor nodes so a LOD'd asset shows its LOD0 once."""
import bpy, sys, math
from mathutils import Vector

a = sys.argv[sys.argv.index("--") + 1:]
src, out = a[0], a[1]
W, H = (int(a[2]), int(a[3])) if len(a) > 3 else (640, 480)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
sc = bpy.context.scene
# Workbench shows material.diffuse_color; the glTF importer only sets the Principled base colour, and another
# exporter puts part colours in COLOR_0 (vertex colour x base). Bake: diffuse = base x mean vertex colour.
import numpy as np
acc = {}
for o in bpy.data.objects:
    if o.type != "MESH" or not o.data.color_attributes:
        continue
    me = o.data; ca = me.color_attributes.active_color or me.color_attributes[0]
    n = len(ca.data); col = np.zeros(n * 4); ca.data.foreach_get("color", col); col = col.reshape(n, 4)
    if ca.domain == "CORNER":
        mi = np.zeros(len(me.polygons), int); me.polygons.foreach_get("material_index", mi)
        tot = np.zeros(len(me.polygons), int); me.polygons.foreach_get("loop_total", tot)
        per_loop = np.repeat(mi, tot)
    else:
        per_loop = None
    for si, slot in enumerate(o.material_slots):
        if not slot.material:
            continue
        c = col if per_loop is None else col[per_loop == si] if len(per_loop) == n else col
        if len(c):
            a = acc.setdefault(slot.material.name, [np.zeros(3), 0]); a[0] += c[:, :3].sum(0); a[1] += len(c)
# glTF baseColorFactor straight from the file: the importer routes it through a MIX node with vertex colours, so
# the Principled socket default (0.8) is not the asset's colour.
import json, struct
FACTOR, ALPHA = {}, {}
try:
    with open(src, "rb") as fh:
        hdr = fh.read(20); jl = struct.unpack("<I", hdr[12:16])[0]
        for gm in json.loads(fh.read(jl)).get("materials", []):
            FACTOR[gm.get("name", "")] = gm.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])[:3]
            if gm.get("alphaMode") == "BLEND":   # a see-through material (export_blend's glow / cut-out stand-in, glass)
                ALPHA[gm.get("name", "")] = (gm.get("pbrMetallicRoughness", {}).get("baseColorFactor") or [1, 1, 1, 1])[3]
except Exception as e:
    print("no glTF json:", e)
for m in bpy.data.materials:
    b = m.node_tree and next((nd for nd in m.node_tree.nodes if nd.type == "BSDF_PRINCIPLED"), None)
    if not b:
        continue
    nm = m.name if m.name in FACTOR else m.name.rsplit(".", 1)[0]
    base = np.array(FACTOR[nm]) if nm in FACTOR else np.array(tuple(b.inputs["Base Color"].default_value)[:3])
    has_tex = any(nd.type == "TEX_IMAGE" for nd in m.node_tree.nodes)
    if m.name in acc and not has_tex:
        base = base * acc[m.name][0] / max(acc[m.name][1], 1)
    elif b.inputs["Base Color"].is_linked and not has_tex:
        continue
    m.diffuse_color = tuple(base.clip(0, 1)) + (float(ALPHA.get(nm, 1)),)
for o in list(bpy.data.objects):
    if o.type in ("LIGHT", "CAMERA") or any(t in o.name.upper() for t in ("_LOD1", "_LOD2", "IMPOSTOR")):
        o.hide_render = True
bpy.context.view_layer.update()
# Frame the solid asset: a mostly see-through mesh (a light beam's glow cone, alpha < 0.5) does not set the view
# (the film's own previews leave such NS| effect parts out of the framing too), unless nothing else is left.
see = lambda o: o.material_slots and all(s.material and s.material.diffuse_color[3] < 0.5 for s in o.material_slots)
vis = [o for o in sc.objects if o.type == "MESH" and not o.hide_render]
pts = [o.matrix_world @ Vector(c) for o in (vis if all(see(o) for o in vis) else [o for o in vis if not see(o)])
       for c in o.bound_box]
if not pts:
    sys.exit("no visible mesh")
lo = Vector(tuple(min(p[i] for p in pts) for i in range(3))); hi = Vector(tuple(max(p[i] for p in pts) for i in range(3)))
ctr = (lo + hi) / 2
corners = [Vector((x, y, z)) - ctr for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.lens = 50; cam.data.sensor_width = 36; cam.data.sensor_fit = "HORIZONTAL"
view = Vector((0.55, -1.0, 0.42)).normalized()          # three's front (+z) is Blender -Y after the +Y-up import
fwd = -view; right = fwd.cross(Vector((0, 0, 1))).normalized(); up = right.cross(fwd)
tx = 18 / 50 * 0.88; ty = tx * H / W                     # tan(half fov) x/y, bbox fills 88 % of the frame
d = max(max(abs(c.dot(right)) / tx, abs(c.dot(up)) / ty) - c.dot(fwd) for c in corners)
d = max(d, 1e-3)
rad = max(c.length for c in corners)
cam.location = ctr + view * d
cam.rotation_euler = fwd.to_track_quat("-Z", "Y").to_euler()
cam.data.clip_start, cam.data.clip_end = max(d - rad, d * 0.01) * 0.5, d + rad * 2
sc.render.engine = "BLENDER_WORKBENCH"
sh = sc.display.shading
textured = any(nd.type == "TEX_IMAGE" for m in bpy.data.materials if m.node_tree for nd in m.node_tree.nodes)
sh.light, sh.color_type, sh.show_cavity = "STUDIO", "TEXTURE" if textured else "MATERIAL", True
sh.show_backface_culling = False
sc.world = bpy.data.worlds.new("w"); sc.world.color = (0.16, 0.17, 0.19)
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
sc.render.film_transparent = False
sc.render.image_settings.file_format = "PNG"
sc.render.filepath = out
bpy.ops.render.render(write_still=True)
print("RENDERED", out)
