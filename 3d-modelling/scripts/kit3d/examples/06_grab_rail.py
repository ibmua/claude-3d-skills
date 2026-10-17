"""A rail spanning two posts (each post attached to the floor plate), and a grab handle on stand-offs spanning
two points of a wall, with roses attached under its feet. The span ends enter their hosts 5 mm over the whole section."""
import os, sys; sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]
import kit3d as k
from kit3d.examples._host import wall
w = wall((2.0, 0.06, 2.4))
k.begin('rails')
chrome = k.metal('rail.chrome', rough=0.07, ref='physicallybased:Chromium', src={'rough': 'judged: polished'})
plate = k.box('rail.floor', (1.4, 0.5, 0.02), k.material('rail.lino', '#7f877d', 0.0, 0.4, src='judged: linoleum'))
k.attach(plate, w, k.on('+y', z=0.2), by='-y')
p1 = k.cyl('rail.post1', 0.02, 0.9, mat=chrome); k.attach(p1, plate, k.on('top', x=-0.5))
p2 = k.cyl('rail.post2', 0.02, 0.9, mat=chrome); k.attach(p2, plate, k.on('top', x=0.5))
k.span('rail.bar', (p1, k.on('+x', z=0.35)), (p2, k.on('-x', z=0.35)), section=0.016, mat=chrome)
h = k.span('grab.bar', (w, k.on('+y', x=-0.7, z=1.1)), (w, k.on('+y', x=-0.7, z=1.9)), section=0.014, mat=chrome,
           form='standoff', out=0.065)
for z in (1.1, 1.9):
    rose = k.cyl(f'grab.rose{z}', 0.026, 0.008, 'Y', chrome)
    k.attach(rose, w, k.on('+y', x=-0.7, z=z), by='-y')
