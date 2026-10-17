"""kit3d constants. Units: metres, degrees in names ending _deg. Change a rule here, never in a part script.

Where the numbers come from (skill 3d-modelling, owner 2026-10-12):
- EMBED 5 mm: a part enters what holds it by ~5 mm; exact contact turns into a slit after rounding/export/LOD and into
  flicker where faces share a plane. check() passes an entry of ENTRY_MIN..ENTRY_MAX (2-10 mm).
- LIFT 6 mm: an applied layer (decal, stripe, plate) stands clear of its base by more than the depth precision at the
  game camera (24-bit depth step 0.4 mm at 60 m, 1.2 mm at 100 m; sweep.mjs), or its base is cut (lay(cut=True)).
- COPLANAR 2 mm / 1 cm2: mesh_integrity FLICKER counts same-facing faces within 2 mm; over 1 cm2 is a FAULT.
- LOD: 2 px at the switch distance (fov 40, 1080p: 1 px = d * 0.00067 m; the game switches at 24 / 70 m), so
  about 1 cm near, 3 cm mid, 13 cm far.
"""

EMBED = 0.005          # attach/span: depth a part enters its host (m)
LIFT = 0.006           # lay: clearance of a layer over its base (m)
ENTRY_MIN = 0.002      # check: shallowest accepted entry (m); below = slit, negative = floating
ENTRY_MAX = 0.010      # check: deepest accepted shallowest-entry (m); above = sunk
LIFT_TOL = 0.0005      # check: a layer may sit this much under LIFT (float/rounding)
LIFT_MAX = 0.015       # check: a layer further than this off its base is floating
COPLANAR = 0.002       # check: same-facing faces closer than this overlap = z-fight
COPLANAR_AREA = 1e-4   # check: coplanar overlap area that is a FAULT (1 cm2)
BACK2BACK = 0.0002     # check: opposite-facing faces closer than this = back-to-back duplicate (true duplicates sit at ~0)
BACK2BACK_AREA = 1e-4  # check: back-to-back area that is a FAULT (1 cm2)
TOUCH = 0.0003         # into(): surfaces closer than this touch (no entry: still a fault, needs ENTRY_MIN)
CUT_GAP = 0.0004       # lay(cut=True): clearance between an inlay plug and its pocket (> BACK2BACK, < 0.5 mm)
MAX_EDGE = 0.05        # lay/conform: a layer is subdivided to edges <= this so it can follow a curved host
PARALLEL = 0.985       # |cos| above which two face normals count as parallel (~10 deg)

# Level of detail. 'film' is the original. A program builds every level from the same code: kit3d.LOD picks one.
LOD_LEVELS = ('film', 'near', 'mid', 'far')
LOD_SEG_FACTOR = {'film': 1.0, 'near': 0.5, 'mid': 0.25, 'far': 0.125}
LOD_MIN_SIZE = {'film': 0.0, 'near': 0.01, 'mid': 0.03, 'far': 0.13}   # 2 px at the switch distance (skill 3d-modelling)
LOD_SWITCH_M = {'near': 24.0, 'mid': 70.0}                            # the game KIT_LOD (game); others: their own rule

KIT3D_VERSION = '2026-10-13'
OBJECT_SPACE_GROUPS = ('idle.',)   # node groups (shared shader kinds) that read OBJECT coordinates where direction matters
