"""bands.py: the provisional band of every look measure, the camera pixel sizes they assume, and the LOOK lines.

ADVISORY. The bands rest on 2 of our own assets (two train cars) and 7 CC0 references, none of them
a rail vehicle (research model-quality-20261013, REPORT.md § 4). A value outside its band means "look here", never
"fail". Re-set them once ten or more accepted and rejected assets of ours have been measured.
"""
import json, math, os

SWITCH_JSON = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..',
                                            '3d-asset-making', 'scripts', 'switch.json'))
EDGE_READS_PX = 1.5        # an edge reads as a lit line from about this many pixels (research rule 1, derived)
FEATURE_READS_PX = 2.0     # a thing on the outline reads from about this many pixels (research rule 4)
PICTURE_PX = 960           # width of the picture pass
FILM_PX = 1920             # width a film frame is delivered at (the film set scales the picture pass to it)

# measure -> (low, high, unit, what it is, the usual fix).  None = no limit on that side.
BANDS = {
    'razor_share':        (None, 0.02, 'share', 'corner length (x turn) that is a hard, unbevelled, split-normal edge',
                           'Bevel (angle 30 deg, Harden Normals) + WeightedNormal on the named parts, smooth shading on'),
    'facet_share':        (None, 0.02, 'share', 'corner length that is a bevel shaded flat, or with a hard boundary against its face',
                           'shade smooth; use Harden Normals OR WeightedNormal, never both with Keep Sharp'),
    'flat_shaded_area':   (None, 0.05, 'share', 'surface area with flat shading (bevels and weighted normals do nothing there)',
                           'shade smooth + WeightedNormal (Keep Sharp); declare parts that must stay flat'),
    'body_bevel_mm':      ('CAMERA', None, 'mm', 'whole bevel width (all segments) on the shell, the largest single part',
                           'widen the primary bevel; primary corners take the real radius, never under 60 mm'),
    'base_colour_spread': (0.20, None, 'ratio', 'spread of base colour inside a material (0 = each material one flat value)',
                           'wear layer (cavity grime, low film, streaks), per-panel value jitter of 3-5 %'),
    'dark_in_cavities':   (0.20, None, 'corr', 'base colour darker where occluded (grime where parts meet)',
                           'cavity grime from the baked AO channel of the mask'),
    'dark_low_down':      (0.20, None, 'corr', 'base colour darker toward the bottom (road and wheel film)',
                           'low road film: grime_height on the lower slots'),
    'largest_material_variation': (0.12, None, 'ratio', 'variation of base colour inside the material that covers most of the picture',
                           'per-panel jitter and a soft roughness/value noise on the biggest material'),
    'rest_cells':         (0.20, 0.35, 'share', 'picture cells of the asset with almost no detail (calm areas)',
                           'below: clear the upper side band, roof field, nose crown; above: add 3-5 functional clusters'),
    'busy_cells':         (None, 0.55, 'share', 'picture cells of the asset dense with detail',
                           'gather detail into clusters; a repeated pattern covers at most a third of a face'),
    'hull_features_side': (3, None, 'count', 'things that break the convex outline in the side view',
                           'functional things that stand proud: roof pods, vents, horn, underfloor boxes, coupler, steps'),
    'hull_features_side_mid': (2, None, 'count', 'the same at the size the asset has where the mid version appears',
                           'make the outline breakers at least 2 px there (size in the LOOK line)'),
    'proportion_error_pct': (-2.0, 2.0, '%', 'reference height-for-length against the model (outline fit)',
                           'check the envelope against the reference; see overlay.jpg for where the outline differs'),
}
ORDER = ['razor_share', 'facet_share', 'flat_shaded_area', 'body_bevel_mm', 'base_colour_spread', 'dark_in_cavities',
         'dark_low_down', 'largest_material_variation', 'rest_cells', 'busy_cells', 'hull_features_side',
         'hull_features_side_mid', 'proportion_error_pct']
# reported in look.json, no band: weak or informative only (REPORT.md § 4)
INFO = ('edge_light_line', 'orientation_entropy', 'dead_share', 'hull_fill', 'materials_effective', 'tonal_range',
        'strip_width_median_mm', 'triangles')


def camera(camera_set='game', family=None, picture_mm_per_px=None):
    """Pixel sizes a camera set assumes. game: scripts/switch.json (fov, rows, the family's nearest look and the
    distances its mid and far versions appear at). film: no camera table exists for film shots, so the film set takes
    the picture pass itself (the asset filling a frame) scaled to a FILM_PX-wide frame; DERIVED, not sourced."""
    with open(SWITCH_JSON) as f:
        d = json.load(f)
    cam = d['camera']; fam = family or d.get('default_family'); f_ = d['families'][fam]
    k = 2 * math.tan(math.radians(cam['fov_deg']) / 2) / cam['rows']          # metres per pixel per metre of distance
    mid = max(f_['near_m'], f_['near_mid'][0] - f_['hysteresis']); far = max(f_['near_m'], f_['mid_far'][0] - f_['hysteresis'])
    out = dict(set=camera_set, family=fam, m_per_px_per_m=round(k, 6), source=SWITCH_JSON,
               near_m=f_['near_m'], mid_appears_m=mid, far_appears_m=far)
    if camera_set == 'film':
        mm = (picture_mm_per_px or 0.0) * PICTURE_PX / FILM_PX
        out.update(near_mm_per_px=round(mm, 2), silhouette_distances_m=[],
                   note='film: picture pass scaled to a %d px frame (derived; no film camera table exists)' % FILM_PX)
    else:
        out.update(near_mm_per_px=round(f_['near_m'] * k * 1000, 2), silhouette_distances_m=[mid, far],
                   mid_mm_per_px=round(mid * k * 1000, 1), far_mm_per_px=round(far * k * 1000, 1))
    out['body_bevel_min_mm'] = round(EDGE_READS_PX * out['near_mm_per_px'], 1)
    return out


def band_of(measure, cam):
    lo, hi, unit, what, fix = BANDS[measure]
    if lo == 'CAMERA':
        lo = cam['body_bevel_min_mm']
    return lo, hi, unit, what, fix


def band_text(lo, hi):
    f = lambda v: ('%g' % v)
    return ('%s-%s' % (f(lo), f(hi))) if lo is not None and hi is not None else ('>= ' + f(lo)) if lo is not None else ('<= ' + f(hi))


def judge(values, where, cam):
    """values {measure: number or None}, where {measure: text} -> (list of out-of-band dicts in ORDER, all dicts)."""
    out, allm = [], []
    for m in ORDER:
        v = values.get(m)
        if v is None:
            continue
        lo, hi, unit, what, fix = band_of(m, cam)
        ok = (lo is None or v >= lo) and (hi is None or v <= hi)
        d = dict(measure=m, value=v, band=band_text(lo, hi), unit=unit, inside=ok, where=where.get(m, ''), what=what, fix=fix)
        allm.append(d)
        if not ok:
            out.append(d)
    return out, allm


def lines(outside, max_lines=10):
    """At most max_lines lines: one LOOK line per measure outside its band, then RESULT."""
    room = max_lines - 1
    show = outside if len(outside) <= room else outside[:room - 1]
    L = ['LOOK %s %g (band %s) %s' % (d['measure'], d['value'], d['band'], d['where']) for d in show]
    if len(outside) > len(show):
        L.append('LOOK +%d more outside their bands: %s (look.json)' % (len(outside) - len(show), ', '.join(d['measure'] for d in outside[len(show):])))
    L.append('RESULT LOOK %d' % len(outside) if outside else 'RESULT OK')
    return [s.rstrip() for s in L]


def help_table(cam=None):
    cam = cam or camera()
    rows = []
    for m in ORDER:
        lo, hi, unit, what, fix = band_of(m, cam)
        rows.append('  %-27s %-9s %s' % (m, band_text(lo, hi), what))
    return '\n'.join(rows)
