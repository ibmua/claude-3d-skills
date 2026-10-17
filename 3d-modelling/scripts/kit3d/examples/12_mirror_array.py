"""Relations copied by mirror() and array(): a roof lamp arrayed along the curved roof (each copy re-fitted to the
curve where it lands) and a pair of handrail posts mirrored to the other side of the car."""
import os, sys; sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]
import kit3d as k
from kit3d.examples._host import car_body
body = car_body()
k.begin('roof_lamps')
lens = k.lamp('roof.lamp', 2700, 4.0)
lamp = k.lathe('roof.lamp.1', [(0, 0), (0.05, 0), (0.05, 0.03), (0.02, 0.05), (0, 0.05)], mat=lens)
k.attach(lamp, body, k.on('top', x=-2.4, y=0.5))
k.array(lamp, 9, step=(0.6, 0.0, 0.0))
k.begin('handrails')
chrome = k.metal('hr.chrome', rough=0.07, ref='physicallybased:Chromium', src={'rough': 'judged'})
a = k.cyl('hr.post.a.L', 0.016, 0.5, 'Y', chrome); k.attach(a, body, k.on('+y', x=-1.2, z=1.4), by='-y')
b = k.cyl('hr.post.b.L', 0.016, 0.5, 'Y', chrome); k.attach(b, body, k.on('+y', x=-1.2, z=2.0), by='-y')
k.span('hr.bar.L', (a, k.on('+z')), (b, k.on('-z')), section=0.014, mat=chrome)
k.mirror([a, b, 'hr.bar.L'], axis='y')
