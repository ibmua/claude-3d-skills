"""One build step inside a live Blender (used by `bridge.py step`; also callable from any script):
step_begin(part) -> run the part script -> step_end(): re-attach dependents of what changed, kit3d.check the
touched parts, save a versioned .blend, optional thumbnail, record relations + flags in parts.json.
"""
import glob, json, math, os, re, time
import bpy
from mathutils import Vector, Matrix

from . import core, plan as _plan
from .check import check
from .place import reattach_chain


def step_begin(part, plan=None, lod=None):
    st = core.S()
    if lod: core.set_lod(lod)
    st['step'] = {'part': part, 'plan': plan, 't0': time.time(), 'created': [], 'rels': [],
                  'before': {o.name: core._sig(o) for o in bpy.data.objects if o.type in ('MESH', 'EMPTY')}}
    return st['step']


def _touched(st):
    part = st['part']; before = st['before']; names = set(st.get('created', []))
    for o in bpy.data.objects:
        if o.type not in ('MESH', 'EMPTY') or o.name.startswith(('kit3d_cut:',)): continue
        if o.get('kit3d_part') == part: names.add(o.name)
        elif o.name in before and before[o.name] != core._sig(o): names.add(o.name)
        elif o.name not in before: names.add(o.name)
    for k in st.get('rels', []):
        names.add(k.split(':', 2)[1])
    return sorted(n for n in names if bpy.data.objects.get(n) is not None)


def next_version(d, part):
    vs = [int(m.group(1)) for f in glob.glob(os.path.join(d, f'{part}-v*.blend')) if (m := re.search(r'-v(\d+)\.blend$', f))]
    return (max(vs) + 1) if vs else 1


def step_end(save_dir=None, thumb=False, extra_parts=()):
    st = core.S().get('step') or {}
    part = st.get('part'); t0 = st.get('t0', time.time())
    touched = _touched(st)
    redone = reattach_chain(touched)
    core.S()['step'] = None
    plan_parts = sorted({bpy.data.objects[n].get('kit3d_part', n) for n in touched + redone if bpy.data.objects.get(n)} | {part} | set(extra_parts))
    out = {'part': part, 'touched': len(touched), 'reattached': redone, 'plan_parts': plan_parts}
    v = None
    if save_dir:
        d = os.path.join(save_dir, part); os.makedirs(d, exist_ok=True); v = next_version(d, part)
        out['json'] = os.path.join(d, f'{part}-v{v:03d}.check.json')
    r = check(parts=plan_parts, json_path=out.get('json'), max_lines=6)
    out.update(ok=r['ok'], lines=r['lines'], fails=len(r['fails']), check_s=r['time_s'], per_part=r['per_part'])
    if save_dir:
        out['blend'] = os.path.join(d, f'{part}-v{v:03d}.blend')
        bpy.ops.wm.save_as_mainfile(filepath=out['blend'], copy=True, compress=False)
        if thumb:
            out['thumb'] = os.path.join(d, f'{part}-v{v:03d}.png')
            render_thumb(out['thumb'], [n for n in touched + redone])
    pl = st.get('plan')
    # objects kit3d did not make and nobody adopted (the originals of an asset being upgraded, loaded in this step) are
    # measured (and FAIL as unplaced) but never written into the plan as parts of their own
    tagged = {bpy.data.objects[n]['kit3d_part'] for n in touched + redone if bpy.data.objects.get(n) and 'kit3d_part' in bpy.data.objects[n]}
    known = {e.get('part') for e in _plan.load(pl)['parts']} if pl else set()
    keep = [pp for pp in plan_parts if pp in tagged or pp == part or pp in known or pp in extra_parts]
    out['untagged'] = [pp for pp in plan_parts if pp not in keep]
    if pl:
        rels = [rr for rr in core.rels().values() if rr.get('plan_part') in keep]
        mrel = {(x['kind'], x['part'], x.get('host', '')): x.get('measured') for x in r['relations']}
        for rr in rels: rr['measured'] = mrel.get((rr['kind'], rr['part'], rr.get('host', '')))
        out['plan_updated'] = _plan.record(pl, rels, {k_: v for k_, v in r['per_part'].items() if k_ in keep}, out.get('json'))
    out['time_s'] = round(time.time() - t0, 2)
    return out


def render_thumb(path, names, size=(480, 360), engine='BLENDER_WORKBENCH', samples=16, context=True, view=None):
    """Small picture of the named objects (their hosts ghosted in when context=True), three-quarter view, in this
    Blender. Workbench by default (~0.5 s on the build box, no GPU needed); engine='CYCLES' for a lit look. A .jpg path is
    written as JPEG (q88), anything else PNG. Restores the scene."""
    sc = bpy.context.scene; objs = [bpy.data.objects[n] for n in names if bpy.data.objects.get(n)]
    if not objs: return None
    keep = {o.name for o in objs}
    if context:
        for r in core.rels().values():
            if r['part'] in keep and r.get('host'): keep.add(r['host'])
            if r['part'] in keep and r.get('host_b'): keep.add(r['host_b'])
    lo = Vector((1e9,) * 3); hi = Vector((-1e9,) * 3)
    for o in objs:
        g = core.geo(o)
        if not len(g.v): continue
        lo = Vector(map(min, lo, g.lo)); hi = Vector(map(max, hi, g.hi))
    if lo.x > hi.x: return None
    saved = {'engine': sc.render.engine, 'rx': sc.render.resolution_x, 'ry': sc.render.resolution_y, 'pct': sc.render.resolution_percentage,
             'fp': sc.render.filepath, 'cam': sc.camera, 'film': sc.render.film_transparent, 'world': sc.world,
             'fmt': sc.render.image_settings.file_format, 'q': sc.render.image_settings.quality}
    wd = bpy.data.worlds.new('kit3d_thumb_world'); wd.color = (0.045, 0.05, 0.055); sc.world = wd
    hid = {}
    for o in sc.objects:
        if o.type in ('MESH', 'EMPTY', 'CURVE', 'FONT'):
            hid[o.name] = o.hide_render; o.hide_render = o.name not in keep and not o.name.startswith('anchor.')
            if o.name.startswith('kit3d_cut:'): o.hide_render = True
    cam_d = bpy.data.cameras.new('kit3d_thumb_cam'); cam = bpy.data.objects.new('kit3d_thumb_cam', cam_d)
    sc.collection.objects.link(cam); cam_d.lens_unit = 'FOV'; cam_d.angle = math.radians(40)
    c = (lo + hi) / 2; rad = max((hi - lo).length / 2, 0.02)
    if view is None:
        ns = [Vector(r['n']) for r in core.rels().values() if r['part'] in names and r.get('n')]
        m = sum(ns, Vector()) if ns else Vector()
        view = (m.normalized() * 1.2 if m.length > 1e-6 else Vector()) + Vector((0.55, -0.7, 0.55))
    dirv = Vector(view).normalized(); dist = rad / math.sin(math.radians(20)) * 1.05
    cam.location = c + dirv * dist; cam.rotation_euler = (-dirv).to_track_quat('-Z', 'Y').to_euler()
    cam_d.clip_start = max(0.001, dist - rad * 3); cam_d.clip_end = dist + rad * 4
    try:
        sc.camera = cam; sc.render.engine = engine; sc.render.resolution_x, sc.render.resolution_y = size
        sc.render.resolution_percentage = 100; sc.render.filepath = path; sc.render.film_transparent = False
        jpg = path.lower().endswith(('.jpg', '.jpeg'))           # .jpg path -> JPEG q88 (pictures kept in git)
        sc.render.image_settings.file_format = 'JPEG' if jpg else 'PNG'
        if jpg: sc.render.image_settings.quality = 88
        if engine == 'BLENDER_WORKBENCH':
            sh = sc.display.shading; sh.light = 'STUDIO'; sh.color_type = 'MATERIAL'; sh.show_cavity = True
            sh.cavity_type = 'BOTH'; sh.show_shadows = False
        else:
            sc.cycles.samples = samples; sc.cycles.device = 'CPU'
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        bpy.ops.render.render(write_still=True)
    finally:
        sc.render.engine = saved['engine']; sc.render.resolution_x = saved['rx']; sc.render.resolution_y = saved['ry']
        sc.render.resolution_percentage = saved['pct']; sc.render.filepath = saved['fp']; sc.camera = saved['cam']
        sc.render.film_transparent = saved['film']; sc.world = saved['world']; bpy.data.worlds.remove(wd)
        sc.render.image_settings.file_format = saved['fmt']; sc.render.image_settings.quality = saved['q']
        for n, hv in hid.items():
            o = bpy.data.objects.get(n)
            if o: o.hide_render = hv
        bpy.data.objects.remove(cam, do_unlink=True); bpy.data.cameras.remove(cam_d)
    return path
