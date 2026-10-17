"""A coil spring between two spring cups (form='coil'): the wire's ends enter both seats; the cups are attached to
the plates they sit on."""
import os, sys; sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]
import kit3d as k
k.begin('spring')
steel = k.paint('spring.steel', '#3a3d40', 0.45, src={'base': 'judged: black-painted spring steel', 'rough': 'judged'}, coat=0.0)
lo = k.box('spring.lower', (0.3, 0.3, 0.03), steel, loc=(0, 0, 0)); k.root(lo, 'lower spring plank')
up = k.box('spring.upper', (0.3, 0.3, 0.03), steel, loc=(0, 0, 0.32)); k.free(up, 'upper plank: held by the spring (into below)')
c1 = k.cyl('spring.cup.lo', 0.07, 0.02, mat=steel); k.attach(c1, lo, 'top')
c2 = k.cyl('spring.cup.up', 0.07, 0.02, mat=steel); k.attach(c2, up, 'bottom')
k.span('spring.coil', (c1, 'top'), (c2, 'bottom'), section=0.009, mat=steel, form='coil', coil=(0.05, 5))
