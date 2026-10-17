"""A speed stripe and a number laid on a CURVED flank (lay: 6 mm off everywhere, following the curve), mirrored
to the other side without mirror-imaging the lettering (reflect=False)."""
import os, sys; sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]
import os
import bpy
import kit3d as k
from kit3d.examples._host import car_body
body = car_body()
k.begin('livery')
red = k.material('livery.red', '#a44439', 0.0, 0.28, src={'base': 'livery sheet', 'rough': 'judged: enamel', 'coat': 'judged: varnished'}, coat=0.6)
stripe = k.decal('livery.stripe.L', 5.0, 0.12, red)
k.lay(stripe, body, k.on('+y', x=0.0, z=1.15))
num = k.text_mesh('livery.number.L', '04', 0.22, 0.004, k.material('livery.gold', metallic=1.0, rough=0.3, ref='physicallybased:Gold', src={'rough': 'judged: gold leaf'}))
k.lay(num, body, k.on('+y', x=2.2, z=1.55))
k.mirror([stripe, num], axis='y', reflect=False)
