"""Bogie frame (a train car c_bogie2, rebuilt by relation): two side frames (web + flanges + legs + gussets + bolt
rows) tied by two transoms that span between the webs. Coordinates in on() are the HOST's own (web centre = 0)."""
import os, sys; sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]
import kit3d as k
k.begin('bogie')
steel = k.paint('bogie.steel', '#545b61', 0.55, src={'base': 'judged: grey-painted steel', 'rough': 'judged: weathered'})
webL = k.rbox('bogie.web.L', (1.55, 0.05, 0.16), 0.01, 'Y', steel, loc=(0, 0.865, 0.40))   # root: placed by design
webR = k.rbox('bogie.web.R', (1.55, 0.05, 0.16), 0.01, 'Y', steel, loc=(0, -0.865, 0.40))  # held by the transoms below
k.root(webL, 'bogie frame: the car body rests on it')
for x in (0.48, -0.48):
    k.span(f'bogie.transom{x:+.2f}', (webL, k.on('-y', x=x)), (webR, k.on('+y', x=x)), section=('rect', 0.16, 0.14), mat=steel)
k.into(webR, 'bogie.transom+0.48', 'the right side frame is welded to the transoms')
for web in (webL, webR):
    s = web.name[-1]; out = '+y' if s == 'L' else '-y'
    k.attach(k.rbox(f'bogie.flange_t.{s}', (1.58, 0.11, 0.018), 0.005, 'Y', steel), web, 'top')
    k.attach(k.rbox(f'bogie.flange_b.{s}', (1.40, 0.11, 0.018), 0.005, 'Y', steel), web, 'bottom')
    for x in (-0.5, 0.5):
        leg = k.rbox(f'bogie.leg.{s}{x:+.1f}', (0.22, 0.04, 0.92), 0.012, 'Y', steel)   # 5 mm in from the web faces: no shared plane
        k.attach(leg, web, k.on('bottom', x=x))
        for d in (-1, 1):                                          # gussets either side of the leg, entering it 5 mm
            g = k.gusset(f'bogie.gusset.{s}{x:+.1f}{d:+d}', 0.16, 0.16, 0.012, steel)
            k.attach(g, web, k.on('bottom', x=x + d * (0.11 + 0.08 - k.EMBED)), by='+z', spin_deg=0 if d > 0 else 180)
            k.into(g, leg)
    if k.keep(0.011):                                              # bolts vanish from mid/far versions
        bolt = k.cyl(f'bogie.bolt.{s}', 0.011, 0.012, segs=6, mat=steel)
        k.scatter(f'bogie.bolts.{s}', bolt, web, [k.on(out, x=-0.66 + 0.12 * i, z=z) for i in range(12) for z in (-0.04, 0.04)
                                                  if abs(abs(-0.66 + 0.12 * i) - 0.5) > 0.14])
