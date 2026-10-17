"""Headlight on a curved nose (a train car headlight_unit): the housing attached to the nose surface (turned to its
normal), the chrome bezel ring and the lens attached on the housing front. Night: warm 2700 K glow."""
import os, sys; sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]
import kit3d as k
from kit3d.examples._host import nose
n = nose()
k.begin('headlight')
chrome = k.metal('hl.chrome', rough=0.07, ref='physicallybased:Chromium', src={'rough': 'judged: polished'})
dark = k.material('hl.housing', '#202224', 0.2, 0.6, src='judged: black enamel')
housing = k.lathe('hl.housing', [(0, -0.10), (0.13, -0.10), (0.14, -0.05), (0.14, 0.0), (0, 0.0)], axis='Z', mat=dark)
k.attach(housing, n, k.on('+x', y=0.55, z=0.25), by='-z', up=(0, 0, 1))
bezel = k.lathe('hl.bezel', [(0.10, 0), (0.15, 0), (0.15, 0.02), (0.13, 0.035), (0.10, 0.03)], axis='Z', mat=chrome)
k.attach(bezel, housing, 'top')
lens = k.lathe('hl.lens', [(0, 0.0), (0.12, 0.0), (0.10, 0.02), (0.05, 0.035), (0, 0.04)], axis='Z', mat=k.lamp('hl.lens', 2700, 8.0))
k.attach(lens, housing, 'top', embed=0.008)         # inside the bezel ring; deeper than the bezel: no shared base plane
