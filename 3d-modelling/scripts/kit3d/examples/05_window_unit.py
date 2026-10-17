"""Window unit on a CURVED flank (a train car side_window_unit): polished surround, rubber gasket and glass each
bent onto the flank (attach conform=), stepped 3 mm apart so no two faces share a plane (2 mm is the z-fight limit): surround 9 mm proud, gasket 6 mm,
glass 3 mm; the gasket enters the surround and the glass enters the gasket (into: measured)."""
import os, sys; sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]
import kit3d as k
from kit3d.examples._host import car_body
body = car_body()
k.begin('window')
trim = k.metal('window.trim', rough=0.26, ref='physicallybased:Aluminum', src={'rough': 'judged: polished'})
rubber = k.material('window.rubber', rough=0.6, ref='physicallybased:Tire', src={'rough': 'judged'})
W, H = 0.86, 0.85; at = k.on('+y', x=-1.0, z=1.95)
sur = k.frame('window.surround', W, H, 0.05, 0.045, 0.014, trim, axis='Z')
k.attach(sur, body, at, by='-z', conform=0.014)
gas = k.frame('window.gasket', W - 0.01, H - 0.01, 0.045, 0.02, 0.011, rubber, axis='Z')
k.attach(gas, body, at, by='-z', conform=0.011); k.into(gas, sur)
gl = k.pane('window.glass', k.rr_outline(W + 0.002, H + 0.002, 0.05), 0.008, k.glass('window.glass'), axis='Z')
k.attach(gl, body, at, by='-z', conform=0.008); k.into(gl, gas)
