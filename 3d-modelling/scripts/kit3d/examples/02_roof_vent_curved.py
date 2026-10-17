"""Teardrop roof ventilator on a CURVED roof (a train car roof_vent): the base plate is bent onto the roof
(attach conform=), the hood (a lofted shell, solidified) sits on the base, a ring of rivets is scattered round it."""
import os, sys; sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]
import math
import kit3d as k
from kit3d.examples._host import car_body
body = car_body()
k.begin('vent')
alu = k.metal('vent.alu', rough=0.35, ref='physicallybased:Aluminum', src={'rough': 'judged: brushed, aged'})
base = k.rbox('vent.base', (0.70, 0.46, 0.012), 0.05, 'Z', alu)
k.attach(base, body, k.on('top', x=0.8, y=0.35), conform=0.012)
n = k.lod_segments(24); rings = []
for i in range(n + 1):
    t = i / n; x = -0.31 + 0.62 * t
    w = 0.20 * math.sin(math.pi * t) ** 0.55 * (1 - 0.35 * t) + 0.01; h = 0.13 * math.sin(math.pi * t) ** 0.5 * (1 - 0.25 * t) + 0.01
    rings.append([(x, w * math.cos(math.pi * j / 16), h * math.sin(math.pi * j / 16)) for j in range(17)])
hood = k.loft('vent.hood', rings, alu, closed=False, smooth=True)
k.solidify(hood, 0.004, offset=-1)
k.attach(hood, base, 'top', conform=0.01)          # rigid it would sag 14 mm through the bent base (check: poke)
riv = k.lathe('vent.rivet', [(0, 0), (0.006, 0), (0.006, 0.002), (0.0035, 0.0045), (0, 0.005)], mat=alu, segs=8)
k.scatter('vent.rivets', riv, base, [k.on('top', x=0.31 * math.cos(a), y=0.20 * math.sin(a)) for a in
                                     [2 * math.pi * i / 14 + 0.2 for i in range(14)]])
