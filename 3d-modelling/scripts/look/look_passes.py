"""look_passes.py: render the passes the look measurements need, lit exactly like render.py's day state. 3-6 s a view.

  python3 look_passes.py FILE.blend|FILE.glb --out DIR [--views front34,side,rear34] [--size 960] [--samples 32]
                         [--collection NAME] [--front +x] [--device auto|gpu|cpu] [--no-ground]
                         [--bevel MM] [--bevel-only REGEX]
  (the same under Blender: blender -b --factory-startup -noaudio -t 8 --python look_passes.py -- ARGS)

Per view it writes into DIR:  <view>.png  the picture a reviewer sees (Khronos PBR Neutral)
                              <view>.npz  float arrays, top row first: normal, position, diffcol, glosscol, ao,
                                          obj (object index), mat (material index); meta (JSON): metres per pixel
                                          constants, bounds, material names, textures_missing
It imports the shared renderer (3d-asset-making/scripts/render.py) for loading, lights, camera fit and device choice,
so the light is the reviewers' light, and it needs Cycles because the base-colour, AO and index passes come from it
(32 samples at 960x720; on the build box start it with MV_BLENDER_GPU=1, which look.py and the python3 form do). Never saves
its input. `textures_missing` > 0 means the picture and every colour number are wrong: a copy of a .blend with
relative texture links must sit at the same folder depth as the original.

--bevel MM is the "what if" picture for the edge rule: in memory, Bevel (30 deg, MM wide, 2 segments, Harden Normals)
+ smooth shading on every mesh (or those matching --bevel-only). Diagnostic, not a finish.
"""
import sys, os, re, json, math, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _run  # noqa: E402
try:
    import bpy
except ImportError:
    bpy = None

WANT = {'normal': ('Normal',), 'position': ('Position',), 'diffcol': ('Diffuse Color', 'DiffCol'),
        'glosscol': ('Glossy Color', 'GlossCol'), 'ao': ('Ambient Occlusion', 'AO'), 'rgb': ('Combined',),
        'obj': ('Object Index', 'IndexOB'), 'mat': ('Material Index', 'IndexMA')}


def read_exr(path):
    import numpy as np
    import OpenImageIO as oiio
    out = {}
    n = oiio.ImageBuf(path).nsubimages
    for sub in range(max(1, n)):
        buf = oiio.ImageBuf(path, sub, 0)
        names = list(buf.spec().channelnames)
        px = None
        for key, alias in WANT.items():
            if key in out:
                continue
            chans = 'X' if key in ('obj', 'mat') else ('XYZ' if key in ('normal', 'position') else 'RGB')
            idx = [next((i for i, nm in enumerate(names) if any(nm.endswith(a + '.' + c) for a in alias)), None) for c in chans]
            if None in idx:
                continue
            if px is None:
                px = np.asarray(buf.get_pixels(oiio.FLOAT))
            out[key] = px[..., idx].astype(np.float32)
    return out


def textures_missing():
    n = 0
    for im in bpy.data.images:
        if im.source == 'FILE' and not im.packed_file and im.users and im.filepath:
            if not os.path.exists(bpy.path.abspath(im.filepath, library=im.library)):
                n += 1
    return n


def main(argv):
    import numpy as np
    import io, contextlib
    src = os.path.abspath(argv[0]); out = os.path.abspath(_run.arg(argv, '--out'))
    views = _run.arg(argv, '--views', 'front34,side,rear34').split(',')
    size = int(_run.arg(argv, '--size', 960)); bevel = float(_run.arg(argv, '--bevel', 0)); bevel_only = _run.arg(argv, '--bevel-only')
    os.makedirs(out, exist_ok=True)
    real_argv = sys.argv
    sys.argv = real_argv[:real_argv.index('--') + 1] if '--' in real_argv else real_argv[:1]   # render.py's main() then only prints its help
    sys.path.insert(0, _run.KIT)
    with contextlib.redirect_stdout(io.StringIO()):
        import render as R
    sys.argv = real_argv
    # '--front=-y': render.py's argparse reads a separate '-y' as an option ("expected one argument")
    ra = ['thumb', src, '--samples', _run.arg(argv, '--samples', '32'), '--front=' + _run.arg(argv, '--front', '+x'),
          '--device', _run.arg(argv, '--device', 'auto')]
    if _run.arg(argv, '--collection'):
        ra += ['--collection', _run.arg(argv, '--collection')]
    if '--no-ground' in argv:
        ra += ['--no-ground']
    A = R.parse(ra); A.sky = 'auto'
    A.hide_globs = [g for g in (_run.arg(argv, '--hide-names') or '').split(',') if g]     # exact object names the mesh pass left out
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.app.handlers.save_pre.append(R.refuse_save)
    sc, stage, groups, P = R.prepare(A, [src], False)
    missing_tex = textures_missing()
    if missing_tex:
        print('LOOK textures missing: %d image files not found (the picture and colour numbers are wrong)' % missing_tex, flush=True)

    if bevel:
        R.localize()
        rx = re.compile(bevel_only, re.I) if bevel_only else None
        n = 0
        for o in bpy.data.objects:
            if o.type != 'MESH' or o.name.startswith('RT_') or (rx and not rx.search(o.name)):
                continue
            for m in [m for m in o.modifiers if m.type in ('BEVEL', 'WEIGHTED_NORMAL')]:
                o.modifiers.remove(m)
            b = o.modifiers.new('LOOK_bevel', 'BEVEL')
            b.width = bevel / 1000.0; b.segments = 2; b.limit_method = 'ANGLE'; b.angle_limit = math.radians(30)
            b.harden_normals = True; b.miter_outer = 'MITER_ARC'; b.use_clamp_overlap = True   # no WeightedNormal: see LOOK-TOOLS.md
            o.data.polygons.foreach_set('use_smooth', [True] * len(o.data.polygons)); o.data.update()
            n += 1
        print('LOOK bevel %.1f mm added to %d meshes' % (bevel, n), flush=True)

    obj_names, mat_names = {}, {}
    for i, o in enumerate([o for o in bpy.data.objects if o.type == 'MESH' and not o.name.startswith('RT_')], 1):
        try:
            o.pass_index = i; obj_names[i] = o.name
        except Exception:
            pass
    for i, m in enumerate(list(bpy.data.materials), 1):
        try:
            m.pass_index = i; mat_names[i] = m.name
        except Exception:
            pass

    dev = R.setup_render(A, sc, size, size * 3 // 4)
    vl = sc.view_layers[0]
    for p in ('normal', 'position', 'diffuse_color', 'glossy_color', 'ambient_occlusion', 'object_index', 'material_index'):
        setattr(vl, 'use_pass_' + p, True)

    def save_passes(view):
        im = sc.render.image_settings
        exr = os.path.join(out, '_look_%s.exr' % view)       # beside the output, never /tmp (RAM on the build box)
        if hasattr(im, 'media_type'):
            im.media_type = 'MULTI_LAYER_IMAGE'
        im.file_format = 'OPEN_EXR_MULTILAYER'; im.color_depth = '32'; im.exr_codec = 'ZIP'
        bpy.data.images['Render Result'].save_render(exr, scene=sc)
        if hasattr(im, 'media_type'):
            im.media_type = 'IMAGE'
        im.file_format = 'PNG'; im.color_mode = 'RGB'; im.color_depth = '8'
        d = read_exr(exr)
        os.remove(exr)
        return d

    from mathutils import Vector
    lo, hi = P.min(0), P.max(0)
    k = 2 * math.tan(math.radians(A.fov) / 2) / 1080.0
    for view in views:
        t = time.time()
        R.shoot(stage, A, P, view, 'day', os.path.join(out, view + '.png'), 4 / 3)
        d = save_passes(view)
        missing = [key for key in WANT if key not in d]
        cam = stage.cam
        meta = dict(view=view, source=src, bevel_mm=bevel, size=[size, size * 3 // 4], bounds_lo=lo.tolist(), bounds_hi=hi.tolist(),
                    cam_location=list(cam.location), lens=cam.data.lens, sensor=cam.data.sensor_width, missing=missing,
                    textures_missing=missing_tex, device=dev, samples=A.samples, m_per_px_per_m=k,
                    obj_names=obj_names, mat_names=mat_names,
                    sun_dir=[float(x) for x in (stage.sun.matrix_world.to_quaternion() @ Vector((0, 0, 1)))])
        d.pop('rgb', None)                                   # the picture is the PNG
        np.savez_compressed(os.path.join(out, view + '.npz'), meta=json.dumps(meta), **d)
        print('LOOK view %s %.1fs device %s missing passes %s' % (view, time.time() - t, dev, missing), flush=True)
    print('LOOK_DONE', out, flush=True)


if __name__ == '__main__':
    argv = _run.tool_argv()
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__); sys.exit(0)
    if bpy is None:
        rc, keep = _run.blender('look_passes.py', argv, gpu=True)
        print('\n'.join(keep)); sys.exit(rc)
    try:
        main(argv)
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc(); sys.exit(2)
