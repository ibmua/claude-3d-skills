"""Build every example in a fresh scene, kit3d.check it (must PASS), draw pics/<name>.jpg and pics/SHEET.jpg.
  <blender> -t 8 -b --factory-startup -noaudio --python run_all.py -- [--only 03,07] [--engine CYCLES] [--out DIR]
Prints one line per example; exit 1 if any fails."""
import os, sys, time, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(os.path.dirname(HERE))]
import bpy
import numpy as np
import kit3d as k
from kit3d import core
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
only = argv[argv.index('--only') + 1].split(',') if '--only' in argv else None
engine = argv[argv.index('--engine') + 1] if '--engine' in argv else 'BLENDER_WORKBENCH'
out = argv[argv.index('--out') + 1] if '--out' in argv else os.path.join(HERE, 'pics')
os.makedirs(out, exist_ok=True); os.environ.setdefault('KIT3D_EXAMPLE_TMP', out)
rows = []; bad = 0
for f in sorted(x for x in os.listdir(HERE) if x[:2].isdigit() and x.endswith('.py')):
    name = f[:-3]
    if only and not any(name.startswith(o) for o in only): continue
    bpy.ops.wm.read_factory_settings(use_empty=True); core.clear_cache(); core.S()['step'] = None; k.set_lod('film')
    t0 = time.time(); err = None
    try:
        exec(compile(open(os.path.join(HERE, f)).read(), os.path.join(HERE, f), 'exec'), {'__name__': '__example__', '__file__': os.path.join(HERE, f)})
    except Exception as e:
        import traceback; err = traceback.format_exc().strip().splitlines()[-3:]
    tb = time.time() - t0
    if err:
        bad += 1; print(f'ERR  {name}: ' + ' | '.join(err)); rows.append({'example': name, 'error': err}); continue
    r = k.check(json_path=os.path.join(out, name + '.check.json'))
    # the picture: the example's own parts (stand-in hosts only as context)
    hosts = {'body.shell', 'wall', 'nose.shell'}
    parts = [o.name for o in bpy.data.objects if o.type == 'MESH' and o.name not in hosts and not o.name.startswith('kit3d_cut')]
    pic = os.path.join(out, name + '.jpg')
    k.render_thumb(pic, parts, size=(480, 360), engine=engine)
    if not r['ok']: bad += 1
    print(f'{"OK  " if r["ok"] else "FAIL"} {name}: build {tb:.2f} s, {r["lines"][0].split(", ", 1)[1]}' + ('' if r['ok'] else '\n     ' + '\n     '.join(r['lines'][1:5])))
    rows.append({'example': name, 'ok': r['ok'], 'build_s': round(tb, 2), 'check_s': r['time_s'], 'counts': r['counts'], 'pic': pic})
# contact sheet (Blender's image API: no PIL in Blender's Python)
pics = [x['pic'] for x in rows if x.get('pic') and os.path.exists(x['pic'])]
if pics and not only:
    cols = 4; W, H = 480, 360; rws = (len(pics) + cols - 1) // cols
    sheet = np.zeros((rws * H, cols * W, 4), np.float32); sheet[..., 3] = 1
    for i, p in enumerate(pics):
        im = bpy.data.images.load(p); a = np.empty(W * H * 4, np.float32); im.pixels.foreach_get(a)
        r_, c_ = divmod(i, cols); y0 = (rws - 1 - r_) * H
        sheet[y0:y0 + H, c_ * W:(c_ + 1) * W] = a.reshape(H, W, 4); bpy.data.images.remove(im)
    im = bpy.data.images.new('sheet', cols * W, rws * H); im.pixels.foreach_set(sheet.ravel())
    sc = bpy.context.scene; sc.render.image_settings.file_format = 'JPEG'; sc.render.image_settings.quality = 85
    im.save_render(os.path.join(out, 'SHEET.jpg'), scene=sc)
for x in rows:
    if x.get('pic'): x['pic'] = os.path.basename(x['pic'])     # relative: the folder is published with the skills repo
json.dump(rows, open(os.path.join(out, 'results.json'), 'w'), indent=1)
print(f'RESULT {"PASS" if not bad else "FAIL"}: {len(rows) - bad}/{len(rows)} examples pass; pictures in {out}')
sys.stdout.flush(); os._exit(1 if bad else 0)
