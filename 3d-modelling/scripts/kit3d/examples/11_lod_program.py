"""The SAME program at film / near / mid / far (kit3d.set_lod): segments shrink, bevels go, 12 mm bolts drop
below 'near', and every level is checked like the film one. Copies sit side by side for the picture."""
import os, sys; sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]
import kit3d as k
from mathutils import Matrix
for i, lvl in enumerate(('film', 'near', 'mid', 'far')):
    k.set_lod(lvl); k.begin(f'lamp_{lvl}')
    m = k.metal(f'lamp.brass_{lvl}', rough=0.3, ref='physicallybased:Brass', src={'rough': 'judged'})
    post = k.cyl(f'{lvl}.post', 0.04, 1.2, mat=m, loc=(i * 0.6, 0, 0.6)); k.root(post, 'lamp post')
    k.bevel(post, 0.006)
    head = k.lathe(f'{lvl}.head', [(0, 0), (0.12, 0), (0.15, 0.08), (0.10, 0.20), (0, 0.24)], mat=m)
    k.attach(head, post, 'top')
    if k.keep(0.012):
        bolt = k.cyl(f'{lvl}.bolt', 0.012, 0.01, 'X', m, segs=6)
        k.scatter(f'{lvl}.bolts', bolt, post, [k.on('+x', z=z) for z in (-0.3, 0.0, 0.3)], by='-x')
k.set_lod('film')
