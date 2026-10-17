"""Roof marker light on a curved roof: housing (lathe) attached to the roof, red lens attached on the housing,
chrome rim built around the lens edge and declared into() the housing. Night: the lens glows."""
import os, sys; sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]
import kit3d as k
from kit3d.examples._host import car_body
body = car_body()
k.begin('roof_light')
chrome = k.metal('chrome', rough=0.07, ref='physicallybased:Chromium', src={'rough': 'judged: polished'})
red = k.material('lens.red', (0.8, 0.05, 0.03), 0.0, 0.08, src={'base': 'design: tail red', 'rough': 'judged'},
                 transmission=0.6, emission=(1.0, 0.12, 0.05), emission_strength=1.5)
housing = k.lathe('roof_light.housing', [(0, 0), (0.07, 0), (0.075, 0.01), (0.07, 0.05), (0, 0.05)], mat=chrome)
k.attach(housing, body, k.on('top', x=2.6, y=-0.45))
lens = k.lathe('roof_light.lens', [(0, 0), (0.06, 0), (0.05, 0.03), (0.03, 0.045), (0, 0.05)], mat=red)
k.attach(lens, housing, 'top')
rim = k.lathe('roof_light.rim', [(0.058, -0.004), (0.074, -0.004), (0.074, 0.006), (0.058, 0.006)], mat=chrome)
rim.matrix_world = housing.matrix_world @ __import__('mathutils').Matrix.Translation((0, 0, 0.05)); k.update()
k.into(rim, housing, 'rim ring sits 4 mm into the housing top, around the lens')
