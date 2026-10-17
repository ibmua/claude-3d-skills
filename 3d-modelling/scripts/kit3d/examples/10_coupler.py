"""Coupler under a buffer beam: the draft-gear box attached under the beam; the head placed at coupling height
(free: the coupling height is the design input); the shank spans box -> head and enters both (both ends measured)."""
import os, sys; sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]
import kit3d as k
k.begin('coupler')
iron = k.paint('coupler.iron', '#2c2e30', 0.5, src={'base': 'judged: black-painted, oily', 'rough': 'judged'}, coat=0.0)
beam = k.rbox('coupler.beam', (0.20, 2.6, 0.30), 0.02, 'X', iron, loc=(0, 0, 0.6))
k.root(beam, 'buffer beam: part of the car end')
box = k.box('coupler.box', (0.6, 0.3, 0.25), iron)
k.attach(box, beam, k.on('bottom', x=-0.05))
head = k.rbox('coupler.head', (0.22, 0.26, 0.24), 0.04, 'Z', iron, loc=(0.75, 0, 0.30))
k.free(head, 'coupler head: placed at the coupling height; held by the shank (measured below)')
k.span('coupler.shank', (box, k.on('+x')), (head, k.on('-x')), section=0.05, mat=iron)   # enters box and head 5 mm (measured)
