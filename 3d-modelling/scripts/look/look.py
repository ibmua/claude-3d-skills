#!/usr/bin/env python3
"""look.py: does this model look made by a master or by a computer? The mesh pass + the picture pass in one call.

  python3 look.py FILE.blend|FILE.glb --out DIR [--camera-set game|film] [--family train|building|city-kit|component|pole]
                  [--reference PIC --reference-view side|34 [--reference-crop x0,y0,x1,y1] [--reference-bg-tol 14]]
                  [--collection NAME] [--body REGEX] [--front +x] [--views front34,side,rear34] [--size 960]
                  [--length M] [--mesh-only] [--overlay] [--json]
  from python:    import look; r = look.run(path, out_dir)        # same options as keywords; returns look.json

Prints at most 10 lines: one `LOOK <measure> <value> (band <band>) <where>` per measure outside its band, then
`RESULT LOOK n` or `RESULT OK`. Writes DIR/look.json (every measure, its band, where, the usual fix, the full mesh
and picture numbers), DIR/mesh.json, DIR/passes/<view>.png|.npz, with --overlay DIR/passes/<view>-look.jpg, and
with --reference DIR/overlay.jpg + .json. Exit 0 whatever the result, 2 when a tool broke. The input is never saved.

ADVISORY: "look", never "fail". The bands are provisional: they rest on 2 of our own assets (two train cars) and 7 CC0 references, none of them a rail vehicle. A number outside its band is a reason to look
at the place named and to say in the hand-back why it stays; it is not a gate. A vision reviewer cannot stand in for
these (asked about edges it answered yes 12 times of 12 whatever the bevel), so they are measured.

Measures and provisional bands (game camera set, family train; `mesh_look.py --help`, `look_metrics.py --help` and
references/LOOK-TOOLS.md say how each is computed and how to fix the usual causes):
%(bands)s

No --collection: the mesh pass picks the asset itself and both passes measure the same objects: the kit3d-tagged
objects when the file has any (a bridge step file also holds Blender's default Cube), else the whole file without the
stage / review / LOD collections and without an untouched default Cube. The first line then says what was measured
and what was left out (`LOOK note: no --collection ...`). Give --collection C.<name> to be sure.
Options may be written `--front -y` or `--front=-y`.

--family pole (or pole:train ...): a POLE, POST or MAST (lamp post, signal, sign: street furniture, city-kit distances
unless named after the colon). Dropped: body_bevel_mm (the largest part is a round tube), rest_cells (a thin outline
leaves too few 32 px cells) and the two outline measures. razor_share is still judged: lips under 1.5 px at the near
distance are counted (no size floor yet), so say so in the hand-back when it names slot lips.

--family component (or component:building ...): ONE COMPONENT of an asset (a door, a window unit, a vent), measured at
its parent family's distances (train unless named after the colon). The two outline measures (hull_features_side,
hull_features_side_mid) are dropped: a part that sits flush in its host has no outline of its own to break, and the
line could never be fixed. They are listed under "dropped" in look.json; every other measure is judged as usual.

Camera sets (the pixel sizes come from 3d-asset-making/scripts/switch.json: fov 40, 1080 rows, so 1 px = distance x
0.000674 m; an edge reads from about 1.5 px, a thing on the outline from about 2 px):
  game   the family's nearest look (train 7.5 m: 5.1 mm a pixel, so body bevel >= 7.6 mm) and the distances its mid
         and far versions appear at (train 92 m and 292 m: the side outline is re-measured at those sizes).
  film   no camera table exists for film shots: the picture pass (the asset filling a 960 px frame) is scaled to a
         1920 px frame and the body bevel must be 1.5 px of that; the outline is measured at full size only. DERIVED.

Cost on the build box (two train cars original, about 270k / 370k triangles): mesh pass 3 s, 0.5 GB; picture pass 16-18 s
on the shared 3090 at 32 samples, 1.6-1.8 GB; metrics 3 s. Blender runs with -b --factory-startup -noaudio -t 8 in a
12 GB memory scope under nice 10 (LOOK_MEM, LOOK_NO_SCOPE=1, BLENDER=/path override).
"""
import sys, os, json, time, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _run, bands, look_metrics  # noqa: E402


COMPONENT_DROPS = ('hull_features_side', 'hull_features_side_mid')   # outline measures a flush component cannot meet
# a pole / post / mast (street furniture): the largest part is a round tube (no corner to bevel), the thin outline
# leaves too few 32 px picture cells for the calm-area share, and nothing stands proud of a post's outline
POLE_DROPS = ('body_bevel_mm', 'rest_cells', 'hull_features_side', 'hull_features_side_mid')
FAMILY_DROPS = {'component': ('train', 'COMPONENT_DROPS'), 'pole': ('city-kit', 'POLE_DROPS')}


def family_of(family):
    """'train' -> ('train', ()); 'component' -> ('train', COMPONENT_DROPS); 'component:building' -> ('building', ...);
    'pole' -> ('city-kit', POLE_DROPS); 'pole:train' -> ('train', POLE_DROPS)."""
    head = (family or '').split(':', 1)[0]
    if head in FAMILY_DROPS:
        base, drops = FAMILY_DROPS[head]
        return (family.split(':', 1)[1] if ':' in family else base), tuple(globals()[drops])
    return family, ()


def judge_family(val, where, cam, family):
    """bands.judge after dropping the measures the family cannot meet. Returns (outside, all, dropped names)."""
    drops = [m for m in family_of(family)[1] if m in val]
    return bands.judge({k: v for k, v in val.items() if k not in drops}, where, cam) + (drops,)


def _parts(rows, key, n=3):
    return ', '.join('%s x%d' % (r['part'], r['instances']) for r in rows[:n] if r.get(key, 1) > 0)


def _worst(views, f, low=True):
    v = (min if low else max)(views, key=f)
    return '%s view %g' % (v['view'], f(v))


def collect(mesh, pic, overlay, cam):
    """mesh.json + metrics dict (+ overlay json) -> ({measure: value}, {measure: where})."""
    val, where = {}, {}
    if mesh:
        c = mesh['corners_share']; b = mesh.get('body_bevel') or {}
        val.update(razor_share=c['razor'], facet_share=c['facet'], flat_shaded_area=mesh['flat_shaded_area_share'])
        where['razor_share'] = _parts([r for r in mesh['razor_by_part'] if r['razor_m'] > 0], 'razor_m')
        where['facet_share'] = _parts(mesh.get('facet_by_part', []), 'facet_m')
        where['flat_shaded_area'] = _parts(mesh.get('flat_by_part', []), 'flat_m2')
        if b:
            val['body_bevel_mm'] = b['bevel_mm']
            where['body_bevel_mm'] = '%s, %s, = %.1f px at %s' % (
                b['part'], b['shading'], b['bevel_mm'] / max(cam['near_mm_per_px'], 1e-9),
                ('%g m' % cam['near_m']) if cam['set'] == 'game' else 'the film frame')
    if pic:
        s, V = pic['summary'], pic['views']
        val.update(base_colour_spread=s['base_colour_spread'], dark_in_cavities=s['dark_in_cavities'], dark_low_down=s['dark_low_down'],
                   largest_material_variation=s['largest_material_variation'], rest_cells=s['rest_cells'], busy_cells=s['busy_cells'])
        where['base_colour_spread'] = 'lowest: ' + _worst(V, lambda v: v['wear']['base_colour_spread'])
        where['dark_in_cavities'] = 'lowest: ' + _worst(V, lambda v: v['wear'].get('dark_in_cavities_corr') or 0)
        where['dark_low_down'] = 'lowest: ' + _worst(V, lambda v: v['wear'].get('dark_low_down_corr') or 0)
        t = min(V, key=lambda v: v['materials']['top'][0]['variation'])['materials']['top'][0]
        where['largest_material_variation'] = '%s covers %d %% at %g' % (t['material'], round(100 * t['share']), t['variation'])
        where['rest_cells'] = 'lowest: ' + _worst(V, lambda v: v['detail']['rest_cells'])
        where['busy_cells'] = 'highest: ' + _worst(V, lambda v: v['detail']['busy_cells'], low=False)
        if 'hull_features_side' in s:
            side = next(v for v in V if v['view'].startswith('side'))
            val['hull_features_side'] = s['hull_features_side']
            where['hull_features_side'] = 'side view, outline fills %d %% of its hull' % round(100 * side['silhouette']['filled']['hull_fill'])
            if 'hull_features_side_mid' in s:
                val['hull_features_side_mid'] = s['hull_features_side_mid']
                where['hull_features_side_mid'] = 'side view at %g m: 2 px = %.0f cm' % (
                    cam['mid_appears_m'], 2 * cam['mid_mm_per_px'] / 10)
    if overlay:
        val['proportion_error_pct'] = overlay['reference_height_for_length_vs_model_pct']
        where['proportion_error_pct'] = 'outline overlap %.2f, see overlay.jpg' % overlay['iou']
    return val, where


def run(path, out, camera_set='game', family='train', reference=None, reference_view='side', reference_crop=None,
        reference_bg_tol=None, collection=None, body=None, front='+x', views='front34,side,rear34', size=960,
        length=None, mesh_only=False, overlay=False, quiet=True):
    """Measure `path`, write out/look.json, return it. r['lines'] are the <= 10 lines look.py prints; r['outside']
    the measures outside their bands; r['result'] 'OK' or 'LOOK n'. Raises RuntimeError when a tool broke."""
    t0 = time.time()
    path, out = os.path.abspath(path), os.path.abspath(out)
    cam_family = family_of(family)[0]
    os.makedirs(out, exist_ok=True)
    times, notes = {}, []
    opt = lambda k, v: [k, str(v)] if v else []

    t = time.time()
    mj = os.path.join(out, 'mesh.json')
    rc, keep = _run.blender('mesh_look.py', [path, '--out', mj] + opt('--collection', collection) + opt('--body', body), quiet=quiet)
    if rc != 0 or not os.path.exists(mj):
        raise RuntimeError('mesh pass failed: ' + ' | '.join(keep[-6:]))
    with open(mj) as f:
        mesh = json.load(f)
    times['mesh_s'] = round(time.time() - t, 1)
    md = mesh.get('measured') or {}
    hide_names = []
    if not collection and md:
        hide_names = [n for n in md.get('left_out', []) if ',' not in n]
        notes.append('LOOK note: no --collection: measured %s (%d objects in %s)%s' % (
            md.get('how'), md.get('objects', 0), ', '.join(md.get('collections', [])[:3]) or 'no collection',
            ('; left out %d (%s%s)' % (md['left_out_count'], ', '.join(md['left_out'][:3]), ' ...' if md['left_out_count'] > 3 else '')) if md.get('left_out_count') else ''))

    pic = None
    if not mesh_only:
        t = time.time()
        pd = os.path.join(out, 'passes')
        for f in os.listdir(pd) if os.path.isdir(pd) else []:        # a stale view must not be averaged in
            if f.endswith(('.npz', '.png', '-look.jpg')):
                os.remove(os.path.join(pd, f))
        rc, keep = _run.blender('look_passes.py', [path, '--out', pd, '--views', views, '--size', size, '--front', front]
                                + opt('--collection', collection) + opt('--hide-names', ','.join(hide_names)), gpu=True, quiet=quiet)
        if rc != 0 or not any(k.startswith('LOOK_DONE') for k in keep):
            raise RuntimeError('picture pass failed: ' + ' | '.join(keep[-6:]))
        notes[0:0] = [k for k in keep if k.startswith('LOOK textures missing')]
        times['passes_s'] = round(time.time() - t, 1)
        t = time.time()
        game = bands.camera('game', cam_family)
        pic = look_metrics.measure_dir(pd, length, game['silhouette_distances_m'] if camera_set == 'game' else (), overlay)
        times['metrics_s'] = round(time.time() - t, 1)

    mpp = (sum(v['mm_per_px'] for v in pic['views']) / len(pic['views'])) if pic else None
    cam = bands.camera(camera_set, cam_family, mpp)
    if camera_set == 'film' and not pic:
        notes.append('LOOK note: film camera set needs the picture pass for its pixel size; body bevel band not judged')

    ov = None
    if reference:
        t = time.time()
        oj = os.path.join(out, 'overlay.jpg')
        rc, keep = _run.blender('proportion_overlay.py', [path, '--ref', os.path.abspath(reference), '--out', oj, '--view', reference_view, '--front', front]
                                + opt('--crop', reference_crop) + opt('--bg-tol', reference_bg_tol) + opt('--collection', collection), quiet=quiet)
        if rc != 0 or not os.path.exists(oj[:-4] + '.json'):
            raise RuntimeError('reference overlay failed: ' + ' | '.join(keep[-6:]))
        with open(oj[:-4] + '.json') as f:
            ov = json.load(f)
        times['overlay_s'] = round(time.time() - t, 1)

    val, where = collect(mesh, pic, ov, cam)
    if camera_set == 'film' and not pic:
        val.pop('body_bevel_mm', None)
    outside, allm, dropped = judge_family(val, where, cam, family)
    lines = bands.lines(outside, max_lines=10 - len(notes[:1]))
    lines = notes[:1] + lines
    info = dict(triangles=mesh['triangles'], strip_width_median_mm=mesh.get('strip_width_median_mm'))
    if pic:
        info.update({k: pic['summary'][k] for k in ('edge_light_line', 'orientation_entropy', 'dead_share', 'hull_fill', 'materials_effective', 'tonal_range')})
    times['total_s'] = round(time.time() - t0, 1)
    res = dict(file=path, advisory='look, never fail: bands rest on 2 of our assets and 7 CC0 references (provisional)',
               result='LOOK %d' % len(outside) if outside else 'OK', lines=lines, outside=[d['measure'] for d in outside],
               measures=allm, info=info, camera=cam, seconds=times, notes=notes, family=family, dropped=dropped,
               mesh=mesh, picture=pic, reference=ov)
    with open(os.path.join(out, 'look.json'), 'w') as f:
        f.write(json.dumps(res, indent=1) + '\n')
    return res


def split_eq(argv):
    """['--front=-y'] -> ['--front', '-y'] (render.py needs the = form for a value that starts with '-'; here both work)."""
    out = []
    for a in argv:
        if a.startswith('--') and '=' in a: out += a.split('=', 1)
        else: out.append(a)
    return out


def main(argv):
    argv = split_eq(argv)
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__ % dict(bands=bands.help_table(bands.camera('game', 'train')))); return 0
    get = lambda k, d=None: argv[argv.index(k) + 1] if k in argv else d
    if not get('--out'):
        print('look.py: --out DIR is needed (see --help)'); return 2
    try:
        r = run(argv[0], get('--out'), camera_set=get('--camera-set', 'game'), family=get('--family', 'train'),
                reference=get('--reference'), reference_view=get('--reference-view', 'side'), reference_crop=get('--reference-crop'),
                reference_bg_tol=get('--reference-bg-tol'), collection=get('--collection'), body=get('--body'),
                front=get('--front', '+x'), views=get('--views', 'front34,side,rear34'), size=int(get('--size', 960)),
                length=float(get('--length')) if get('--length') else None, mesh_only='--mesh-only' in argv,
                overlay='--overlay' in argv, quiet='--verbose' not in argv)
    except (RuntimeError, subprocess.TimeoutExpired, KeyError) as e:
        print('LOOK ERROR %s' % e); return 2
    print(json.dumps(r, indent=1) if '--json' in argv else '\n'.join(r['lines']))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
