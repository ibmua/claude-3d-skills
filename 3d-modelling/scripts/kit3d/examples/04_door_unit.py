"""Door unit in a car side (cab doors): architrave frame on the wall, leaf inside the opening entering the frame's
rubber seal, glazed upper light with gasket, kick plate inlaid (cut), pull handle spanning on stand-offs."""
import os, sys; sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]
import kit3d as k
from kit3d.examples._host import wall
from mathutils import Matrix
w = wall((2.0, 0.06, 2.4))
k.begin('door')
wood = k.material('door.wood', '#6b4a2e', 0.0, 0.35, src='judged: varnished teak', coat=0.6, coat_rough=0.1)
cream = k.paint('door.cream', '#e8dfc8', 0.35, src={'base': 'livery sheet', 'rough': 'judged: gloss enamel'})
rubber = k.material('door.rubber', rough=0.7, ref='physicallybased:Tire', src={'rough': 'judged'})
brass = k.metal('door.brass', rough=0.25, ref='physicallybased:Brass', src={'rough': 'judged: handled'})
frame = k.frame('door.frame', 0.9, 2.0, 0.05, 0.07, 0.04, cream, axis='Y')
k.attach(frame, w, k.on('+y', z=1.1), by='-y')
seal = k.frame('door.seal', 0.86, 1.96, 0.04, 0.025, 0.05, rubber, axis='Y')    # enters the frame 5 mm
seal.matrix_world = frame.matrix_world.copy(); k.update(); k.into(seal, frame)
leaf = k.rbox('door.leaf', (0.87, 0.045, 1.97), 0.03, 'Y', wood)
leaf.matrix_world = frame.matrix_world.copy(); k.update(); k.into(leaf, seal)
opening = k.rbox('door.opening', (0.60, 0.2, 0.68), 0.05, 'Y')
opening.matrix_world = leaf.matrix_world @ Matrix.Translation((0, 0, 0.45)); k.update()
k.cut(leaf, [opening])                                         # the glazed upper light
gl = k.pane('door.glass', k.rr_outline(0.62, 0.70, 0.05), 0.008, k.glass('door.glass'), axis='Y')
gasket = k.frame('door.gasket', 0.56, 0.64, 0.03, 0.04, 0.05, rubber, axis='Y')   # laps the cut edge 2 cm both ways
for o in (gl, gasket):
    o.matrix_world = leaf.matrix_world @ Matrix.Translation((0, 0, 0.45))
k.update(); k.into(gasket, leaf); k.into(gl, gasket)
kick = k.plate('door.kick', 0.80, 0.14, 0.004, 0.01, brass)
k.lay(kick, leaf, k.on('+y', z=-0.85), cut=True)
k.span('door.handle', (leaf, k.on('+y', x=0.33, z=0.0)), (leaf, k.on('+y', x=0.33, z=0.35)), section=0.011, mat=brass,
       form='standoff', out=0.045)
