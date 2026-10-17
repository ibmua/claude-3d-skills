"""Textured chequer step plate under a door sill: the image is read through the plate's own metre UVs (made at
creation), so the game export keeps it (no speckle); brackets attach under the plate into the wall."""
import os, sys; sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]
import os
import bpy
import kit3d as k
from kit3d.examples._host import wall
w = wall((2.0, 0.06, 2.4))
k.begin('step')
img = os.path.join(os.environ.get('KIT3D_EXAMPLE_TMP', '/tmp'), 'kit3d_chequer.png')
if not os.path.exists(img):
    im = bpy.data.images.new('chequer', 64, 64); px = []
    for y in range(64):
        for x in range(64):
            c = 0.75 if (x // 8 + y // 8) % 2 else 0.35; px += [c, c, c, 1.0]
    im.pixels.foreach_set(px); im.filepath_raw = img; im.file_format = 'PNG'; im.save()
steel = k.material('step.chequer', '#b9bdbd', 0.85, 0.35, image=img, tile_m=0.08, tint=0.7, bump=0.0015,
                   ref='physicallybased:Iron', src={'base': 'judged: galvanised', 'rough': 'judged: worn chequer'})
tread = k.box('step.tread', (1.3, 0.16, 0.025), steel)
k.attach(tread, w, k.on('+y', z=0.35), by='-y')
nos = k.rbox('step.nosing', (1.32, 0.03, 0.04), 0.008, 'X', k.metal('step.trim', rough=0.3, ref='physicallybased:Aluminum', src={'rough': 'judged'}))
k.attach(nos, tread, '+y')
for x in (-0.55, 0.0, 0.55):
    br = k.box(f'step.bracket{x:+.2f}', (0.03, 0.12, 0.10), steel)
    k.attach(br, w, k.on('+y', x=x, z=0.30), by='-y')            # its top enters the tread from below
