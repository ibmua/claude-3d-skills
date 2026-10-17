"""Stand-in hosts for the examples (a curved car body, a flat wall, a nose). Real parts attach to real hosts."""
import math
import kit3d as k


def section(x, half_w=1.4, zc=1.6, half_h=1.3, n=48):
    """Superellipse car section at x: curved flanks and roof everywhere (the hard case for placement)."""
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n; c, s = math.cos(a), math.sin(a)
        pts.append((x, half_w * math.copysign(abs(c) ** (2 / 3.0), c), zc + half_h * math.copysign(abs(s) ** (2 / 3.0), s)))
    return pts


def car_body(length=6.0, name='body.shell', part='body'):
    k.begin(part)
    m = k.paint('body.paint', '#c8c4b8', ref='physicallybased:Car Paint', src={'base': 'livery sheet', 'rough': 'judged: aged gloss'})
    xs = [-length / 2 + length * i / 6 for i in range(7)]
    b = k.loft(name, [section(x) for x in xs], m, caps=(True, True), smooth=True)
    return k.root(b, 'stand-in car body')


def wall(size=(2.0, 0.06, 2.4), name='wall', part='wall'):
    k.begin(part)
    w = k.box(name, size, k.paint('wall.paint', '#7d8a8c', 0.5, src='judged: example wall'), origin='bottom')   # floor at z = 0
    return k.root(w, 'stand-in car side')


def nose(name='nose.shell', part='nose'):
    """A blunt streamlined nose: a lathe around +X (the car's front)."""
    k.begin(part)
    prof = [(1.3 * math.cos(math.radians(a)) ** 0.6 if a < 90 else 0.0, 0.9 * math.sin(math.radians(a))) for a in range(0, 91, 6)]
    prof = [(0.0, -0.4)] + [(1.3, -0.4)] + prof
    n = k.lathe(name, prof, axis='X', mat=k.paint('nose.paint', '#a44439', 0.35, src={'base': 'livery sheet', 'rough': 'judged: gloss enamel'}))
    return k.root(n, 'stand-in nose')
