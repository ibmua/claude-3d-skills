"""A maker's plate inlaid in a CURVED panel (lay cut=True: a pocket is cut, the plate's top is flush, nothing lies
under it to blink); raised lettering stands on the plate, entering it 3 mm (attach)."""
import os, sys; sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]
import kit3d as k
from kit3d.examples._host import car_body
body = car_body()
k.begin('maker_plate')
brass = k.metal('plate.brass', rough=0.25, ref='physicallybased:Brass', src={'rough': 'judged: polished, handled'})
plate = k.plate('maker.plate', 0.36, 0.16, 0.006, 0.025, brass)   # 6 mm: the letters' 3 mm roots stay 3 mm off its back
k.lay(plate, body, k.on('+y', x=-2.2, z=1.0), cut=True)
txt = k.text_mesh('maker.text', 'KIT 1926', 0.05, 0.006, k.material('plate.black', '#151515', 0.0, 0.5, src='judged: black enamel'))
k.attach(txt, plate, '+z', by='-z', embed=0.003, conform=0.006)   # rigid, the 0.3 m line pokes through the bent plate
