#!/usr/bin/env python3
"""All game versions of one asset in ONE background job, every gate on: per version simplify (or judge the version
that exists) -> uvpack -> bake -> export_game, then the picture checks the owner's Done needs, and the record.
Read one short file (LODS-SUMMARY.md) instead of driving steps.

Measured 2026-10-12 (the game ops/runs/rebuild-compare/OPTIMIZE.md item 3): the game-version phase cost 50-63 % of
each train builder's money ($14-21): the model drove bake, uvpack, export and compare by hand, reran a 30-min CPU
finalize after a camera bug, broke it with a sed edit, and waited idle 0.3-0.5 h.

  nice -n 10 python3 lods_all.py ORIGINAL.blend OUT_DIR --key KEY --high COLL --family train|building|city-kit
        [--lows near=GAME_near,mid=GAME_mid,far=GAME_far] [--source auto|simplify|given] [--budgets 9600,3500,2100]
        [--sizes 2048,1024,512] [--slots FILE | --no-slots] [--contract GAME-CONTRACT.md] [--exclude GLOBS]
        [--glass-through GLOBS] [--surface-node N] [--glass-node N] [--root-props JSON] [--allow-designed FILE]
        [--original-glb GLB] [--allow-over] [--no-lodcmp] [--no-sweep] [--no-thumbs] [--picture-passes 3]
        [--uvpack auto|keep|smart|skip] [--threads 8] [--mem 12G] [--record ASSET.json --model M --effort E --task T --session S]
        [--class-map ASSET.json] [--skip-pbr-check] [--allow-inherited] [--allow-faults]
  (run it in the background: `... > OUT_DIR/lods.log 2>&1 &`, then read OUT_DIR/LODS.json or LODS-SUMMARY.md)

Every child job runs in `systemd-run --user --scope -p MemoryMax=12G -p MemorySwapMax=0 nice -n 10` (--mem; the build box is
shared: an OOM on 2026-10-13 took a film render), Blender with -t --threads (8), and its peak memory is logged.
ORIGINAL.blend is never written: the work happens in OUT_DIR/work/KEY-work.blend (a copy with absolute paths).
Switch distances, pixel error targets and (per family) the game contract and slots file come from ONE place,
scripts/switch.json (--family). Steps, each logged to OUT_DIR/logs/<step>.log:
 0. the original as a GLB with its look (export_original.py; Khronos validator + reimport gates) unless --original-glb.
 1. per version: SOURCE. --source auto (default): a --lows collection that exists in the file is a by-construction
    version (hand or generator) and is JUDGED (simplify.py --judge: 2 px error at the closest distance the game shows
    it, and the budget); one that does not exist is MADE by simplify.py (meshoptimizer, colour-aware, material borders
    locked, budget = ceiling: over it the run stops with "needs N for 2 px, budget B, over by X, mostly in <parts>").
    --source simplify makes every version, given judges every one. --allow-over goes on past an error/budget miss
    (said loudly in the summary; for a look, never for a release).
    NEAR AND MID ARE LIVE (a design decision; owner 2026-10-15 18:18: "even though we wrote in the skill that it's not supposed to
    bake near and mid, it still seems to have baked it"): uvpack.py -> live_version.py (each face takes the original
    material it shows; library kinds stay live shaders, constants stay constants, only a normal map + the wear mask
    are baked; printed pictures are projected) -> export_original.py (no bake allowed, validator + reimport) ->
    mesh_integrity --against the version above (--held-by the original) + pbr_check. --baked-near-mid "<plan>" goes
    back to one baked material for near/mid (said in the summary). FAR (and any --baked-near-mid version):
    uvpack.py (overlap 0) -> bake.py (pbr_check pre-flight M2/M5/M11 on the original, cage start check, drift
    self-check, game slots) -> export_game.py --against the version above (mesh_integrity, textured-without-UV,
    glTF-Validator, reimport, slot names vs the contract, pbr_check incl. E1 night glow). pbr_check reads the
    materials' classes from --class-map (default: --record asset.json, its "materials"); the summary shows each
    version's PBR RESULT and first 3 errors.
 2. picture checks (each skippable): render.py lodcmp --at-switch --states day,dusk,night per version against the
    original. A SIMPLIFIED version whose day/dusk regions fail is simplified again with those regions locked
    (--lock-from), at most --picture-passes 3, then re-baked and re-exported; a given version is only reported.
    Night is reported as a KNOWN fail (no loop) until the named slots carry the game's night glow into the renders.
    sweep.mjs (blink + slits in the game's three.js) on each GLB; render.py thumb --states day,dawn,dusk,night,rain.
 3. render.py versions (game camera at each version's switch distance) -> OUT_DIR/versions/VERSIONS.jpg.
 4. asset_record.py (when --record): made_with entry, lods, the real switch distances (--switch-family), mounts.
Writes OUT_DIR/LODS.json after every step ({key, state: running|failed|done, gate, steps: [...]}) and at the end
OUT_DIR/LODS-SUMMARY.md: per version tris / budget, draws, source, error px, integrity, drift, slots, pictures.
Exits non-zero on the FIRST failing gate and names it (LODS.json gate, the summary's first line).

SLOTS (the game trains, GAME-CONTRACT.md): the game drives class colours, its glass shader, night glow, lamps and
rain by material NAME, so near and mid keep one material per game role; a slots file maps the original's materials
to the roles: {"roles": {"body-ceramic": ["stl.alu*"], ...}, "required": {...}, "merge": {"far": [...]}} and/or the
shader library's game-slots.json (originals whose materials carry the slot names). Default: the family's 'slots'
in switch.json; --no-slots bakes one material per version (non-train assets).
"""
import argparse, json, os, shutil, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _kit as K

ap = argparse.ArgumentParser(prog='lods_all.py', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('original'); ap.add_argument('out'); ap.add_argument('--key', required=True); ap.add_argument('--high', required=True)
ap.add_argument('--family'); ap.add_argument('--source', default='auto', choices=('auto', 'simplify', 'given'))
ap.add_argument('--lows', default='near=GAME_near,mid=GAME_mid,far=GAME_far'); ap.add_argument('--sizes', default='2048,1024,512')
ap.add_argument('--budgets', default=''); ap.add_argument('--allow-over', action='store_true')
ap.add_argument('--slots'); ap.add_argument('--no-slots', action='store_true'); ap.add_argument('--contract')
ap.add_argument('--exclude', default=''); ap.add_argument('--live', default='', help='GLOBS of live surfaces (screens, glow cards) kept unbaked with their own material: left out of simplify and bake, passed to export_game --live'); ap.add_argument('--live-fallback', default='', help='Shader Lab fallback DIR for --live (lab.mjs fallback)'); ap.add_argument('--glass-through', default='')
ap.add_argument('--surface-node', default='surface'); ap.add_argument('--glass-node', default='glass')
ap.add_argument('--root-props', default=''); ap.add_argument('--allow-designed'); ap.add_argument('--original-glb')
ap.add_argument('--no-lodcmp', action='store_true'); ap.add_argument('--no-sweep', action='store_true')
ap.add_argument('--no-thumbs', action='store_true'); ap.add_argument('--picture-passes', type=int, default=3)
ap.add_argument('--uvpack', default='auto', choices=('auto', 'keep', 'smart', 'skip')); ap.add_argument('--threads', type=int, default=8)
ap.add_argument('--record'); ap.add_argument('--model'); ap.add_argument('--effort'); ap.add_argument('--task'); ap.add_argument('--session')
ap.add_argument('--mem', default='12G')
ap.add_argument('--baked-near-mid', default='', help='the deliberate plan that bakes near/mid into one material (a design decision: they stay live '
                'shaders by default; only far bakes). Said in the summary as an override')
ap.add_argument('--merge', default='', help='live near/mid slot merges, JSON {"near": {"dark_cover": "bezel"}, "mid": {"stainless": null}} '
                '(null = the face takes its second vote)')
ap.add_argument('--no-normal', default='', help='live near/mid: slots that get no baked normal map (comma list)')
ap.add_argument('--simplify-args', default='', help='extra arguments handed to simplify.py as they are, e.g. "--layers off" or "--layer-k 0.5" (said in the summary)')
ap.add_argument('--class-map', help='asset.json with "materials" classes for pbr_check (default: --record)')
ap.add_argument('--allow-faults', action='store_true', help='when export_game REFUSES a version, go on with its .rejected.glb for '
                'the pictures (lodcmp, sweep, thumbs, sheet) and say so; nothing is recorded in asset.json (for a look, never a release)')
ap.add_argument('--allow-inherited', action='store_true', help='export_game --allow-inherited: integrity faults no worse than the '
                'version above / the original pass, said in the summary (the original must be fixed)')
ap.add_argument('--skip-pbr-check', action='store_true', help='bake and export without the pbr_check gates (an OVERRIDE, said in the summary)')
ap.add_argument('--blender', default=os.environ.get('BLENDER') or ('blender'))
A = ap.parse_args()
EXCL_LOW = ','.join(x for x in (A.exclude, A.live) if x)   # live parts are not simplified or baked (2026-10-13, an old-TV prop)

OUT = os.path.abspath(A.out); os.makedirs(os.path.join(OUT, 'logs'), exist_ok=True); os.makedirs(os.path.join(OUT, 'work'), exist_ok=True)
WORK = os.path.join(OUT, 'work', f'{A.key}-work.blend')
VIS = os.path.join(OUT, 'work', 'visibility.npz')
LOWS = [tuple(x.split('=', 1)) for x in K.csv(A.lows)]
SIZES = [int(x) for x in K.csv(A.sizes)]; BUD = [int(x) for x in K.csv(A.budgets)] if A.budgets else []
SW = K.switch(A.family)
SLOTS = None if A.no_slots else (A.slots or SW.get('slots'))
if SLOTS and not os.path.exists(SLOTS): SLOTS = None
CONTRACT = A.contract or SW.get('contract')
CLASSMAP = A.class_map or (A.record if A.record and os.path.exists(A.record) else None)
S = dict(key=A.key, original=os.path.abspath(A.original), out=OUT, state='running', gate=None, started=time.strftime('%Y-%m-%d %H:%M:%S %z'),
         family=SW['family'], switch=dict(near_mid=SW['near_mid'], mid_far=SW['mid_far'], hysteresis=SW['hysteresis'],
         appears=SW['appears'], target_m=SW['target_m'], source=SW['source']), slots=SLOTS, contract=CONTRACT,
         overrides=[], known_fails=[], steps=[], versions={}, class_map=CLASSMAP)
if A.baked_near_mid: S['overrides'].append(f'--baked-near-mid: near/mid BAKED into one material ({A.baked_near_mid})')
if A.skip_pbr_check: S['overrides'].append('--skip-pbr-check: bake and export ran WITHOUT the pbr_check material gates')


def save():
    tmp = os.path.join(OUT, 'LODS.json.tmp')
    with open(tmp, 'w') as f: json.dump(S, f, indent=1)
    os.replace(tmp, os.path.join(OUT, 'LODS.json'))


# the build box is shared (2026-10-13 02:53: the global OOM killer took a film render while ~70 GB of other jobs sat in RAM and
# swap): every child job runs in its own systemd scope with a memory ceiling and no swap, niced, its peak measured.
SCOPE = (['systemd-run', '--user', '--scope', '--quiet', '-p', f'MemoryMax={A.mem}', '-p', 'MemorySwapMax=0']
         if shutil.which('systemd-run') and A.mem != 'none' else [])


def step(name, cmd, gpu=False):
    t = time.time(); log = os.path.join(OUT, 'logs', name + '.log')
    S['steps'].append(dict(step=name, state='running', log=log, started=time.strftime('%H:%M:%S'))); save()
    env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS=str(A.threads))   # numpy: no thread per core
    if gpu: env['MV_BLENDER_GPU'] = '1'
    timer = ['/usr/bin/time', '-f', 'PEAK_KB %M'] if os.path.exists('/usr/bin/time') else []
    with open(log, 'w') as f:
        r = subprocess.run(SCOPE + ['nice', '-n', '10'] + timer + cmd, stdout=f, stderr=subprocess.STDOUT, env=env)
    peak = next((int(l.split()[1]) for l in reversed(open(log, errors='replace').read().splitlines()) if l.startswith('PEAK_KB ')), None)
    S['steps'][-1].update(state='ok' if r.returncode == 0 else f'exit {r.returncode}', seconds=round(time.time() - t, 1),
                          peak_mb=peak // 1024 if peak else None); save()
    print(f'[lods_all] {name}: exit {r.returncode} in {time.time() - t:.0f} s' + (f', peak {peak // 1024} MB' if peak else ''), flush=True)
    return r.returncode, log


def tail(log, pat=('REFUSED', 'FAULT', 'ERROR', 'Error', 'WARNING', 'FAIL', 'OVER')):
    try: return [l.strip() for l in open(log, errors='replace') if any(p in l for p in pat)][-6:]
    except OSError: return []


def fail(gate, detail):
    S['state'] = 'failed'; S['gate'] = gate; S['gate_detail'] = detail; save(); summary()
    print(f'[lods_all] GATE FAILED: {gate}: {detail}', flush=True); sys.exit(1)


def summary():
    L = [f'# {A.key}: game versions ({S["state"]}' + (f', FAILED at gate: {S["gate"]}' if S['gate'] else '') + ')', '']
    if S['gate']: L += [f'**Gate:** {S["gate"]}: {S.get("gate_detail")}', '']
    L.append(f'Family {SW["family"]}: versions seen from {SW["appears"]} m -> 2 px = {SW["target_m"]} m ({SW["source"]})')
    L.append(f'Slots: {SLOTS or "none (one baked material per version)"}; contract: {CONTRACT if SLOTS else "-"}')
    for o in S['overrides']: L.append(f'- **OVERRIDE** {o}')
    L.append('')
    for lv, v in S['versions'].items():
        e = v.get('error') or {}
        L.append(f'- **{lv}** ({v.get("source")}): {v.get("tris")} tris' + (f' / budget {v["budget"]}' if v.get('budget') else '') +
                 f', {v.get("draws")} draws, error p99 {e.get("p99_cm")} cm = {e.get("px")} px at {e.get("at_m")} m, '
                 f'{v.get("result", "not exported")}, drift {v.get("drift")}, miss {v.get("miss")}, slots {v.get("slots")}, {v.get("glb", "")}')
        for k in ('live', 'layers', 'refused', 'uv', 'pbr_check', 'lodcmp', 'sweep', 'thumbs'):
            if v.get(k): L.append(f'  - {k}: {v[k]}')
    for k in S['known_fails']: L.append(f'- known fail: {k}')
    if S.get('sheet'): L.append(f'- versions sheet: {S["sheet"]}')
    if S.get('original_glb'): L.append(f'- original GLB: {S["original_glb"]}')
    L.append(f'- progress: {os.path.join(OUT, "LODS.json")}; logs: {os.path.join(OUT, "logs")}/')
    with open(os.path.join(OUT, 'LODS-SUMMARY.md'), 'w') as f: f.write('\n'.join(L) + '\n')


B = A.blender
py = lambda s: os.path.join(HERE, s)
# the work copy goes through Blender with absolute paths: a plain file copy re-anchors relative texture paths and the
# bake then runs without them (first run of this tool: 7-9 textures missing). It also lists the collections.
r_ = subprocess.run(SCOPE + ['nice', '-n', '10', B, '-b', '-t', str(A.threads), '-noaudio', A.original, '--python-expr',
                     "import bpy; bpy.ops.file.make_paths_absolute(); "
                     "print('COLLS ' + '|'.join(c.name for c in bpy.data.collections)); "
                     f"bpy.ops.wm.save_as_mainfile(filepath={WORK!r}, copy=True, relative_remap=False)"],
                    capture_output=True, text=True)
if r_.returncode or not os.path.exists(WORK): fail('work copy', r_.stdout[-800:] + r_.stderr[-800:])
COLLS = set(next((l[6:] for l in r_.stdout.splitlines() if l.startswith('COLLS ')), '').split('|'))

# 0. the original
orig = A.original_glb
if not orig:
    orig = os.path.join(OUT, f'{A.key}-original.glb')
    rc, log = step('original', [B, '-b', '-t', str(A.threads), '-noaudio', WORK, '--python', py('export_original.py'), '--', '--out', orig,
                                '--collection', A.high, '--threads', str(A.threads)] + (['--exclude', A.exclude] if A.exclude else []))
    if rc: fail('original export', tail(log))
S['original_glb'] = orig; save()


def judge_or_make(lv, coll, budget, lock_from=None):
    """Returns the collection the version lives in and fills V['error']."""
    V = S['versions'][lv]
    given = (A.source == 'given') or (A.source == 'auto' and coll in COLLS and lock_from is None and V.get('source') != 'simplified')
    rep = os.path.join(OUT, 'logs', f'simplify-{lv}.json')
    base = [B, '-b', '-t', str(A.threads), '-noaudio', WORK, '--python', py('simplify.py'), '--', '--high', A.high, '--level', lv,
            '--family', SW['family'], '--vis-cache', VIS, '--report', rep] + (['--exclude', EXCL_LOW] if EXCL_LOW else []) + \
           (['--slots', SLOTS] if SLOTS else []) + \
           (['--budget', str(budget)] if budget else []) + A.simplify_args.split()
    if given:
        V['source'] = 'given (judged)'
        rc, log = step(f'judge-{lv}', base + ['--judge', coll])
        out_coll = coll
    else:
        V['source'] = 'simplified'; out_coll = f'GAME_{lv}_auto' + ('_locked' if lock_from else '')
        cmd = base + ['--into', out_coll, '--save', WORK] + (['--keep-over'] if A.allow_over else [])
        if lock_from: cmd += ['--lock-from', lock_from, '--lock-label', lv]
        rc, log = step(f'simplify-{lv}' + ('-locked' if lock_from else ''), cmd)
    j = json.load(open(rep)) if os.path.exists(rep) else {}
    if lock_from and V.get('error') and j.get('triangles'):
        # a lock pass keeps the ORIGINAL's density inside the failing boxes: a test run (2026-10-13) mid 4 356 -> 27 750 and far
        # 2 681 -> 65 827 triangles, and far still failed (a bake/material difference, not geometry). Taken only when it
        # costs at most 1.5x the unlocked triangles; otherwise the unlocked version stays and the summary says so.
        before = V.get('tris_unlocked') or V.get('tris')
        if before and j['triangles'] > 1.5 * before:
            S['known_fails'].append(f'{lv}: lodcmp lock pass NOT taken: {j["triangles"]} triangles vs {before} unlocked (> 1.5x)')
            save(); return None
    e = j.get('error') or {}
    V['error'] = dict(p99_cm=round(e.get('error_p99_m', 0) * 100, 2) if e else None, px=e.get('error_p99_px'), at_m=j.get('distance_m'),
                      target_cm=round(j.get('target_m', 0) * 100, 2) if j else None, worst=e.get('worst_places', [])[:3],
                      triangles_by_part=j.get('triangles_by_part'), verdict=j.get('verdict'))
    if j.get('layers'):      # laid-on parts lower than the error target, cut into their base (simplify.py LAYERS)
        ly = j['layers']; ot = j.get('on_top') or {}
        V['layers'] = dict(parts=ly.get('parts'), cut_in=ly.get('cut_in'), proud=len(ly.get('proud') or []), reach_mm=round(ly.get('reach_m', 0) * 1000, 1),
                           retagged=(ly.get('imprint') or {}).get('retagged'), on_top_right=ot.get('right'), on_top_worst=ot.get('worst', [])[:4])
    save()
    if rc:
        msg = j.get('verdict') or tail(log)
        if rc == 3 and A.allow_over:
            S['overrides'].append(f'{lv}: {msg} (--allow-over)'); save()
        else: fail(f'{"judge" if given else "simplify"} {lv} (error {SW["camera"]["px"]} px / budget)', msg)
    return out_coll


def pbr_short(p):
    """pbr_check in one line: its PBR RESULT plus the first 3 ERROR lines (cut at 'Decide:')."""
    if not p: return None
    if p.get('skipped') or not p.get('available', True): return (p.get('lines') or ['not run'])[0]
    errs = [e.split(' Decide:')[0] for e in (p.get('errors') or [])[:3]]
    return f"PBR RESULT: {p.get('result') or ('exit ' + str(p.get('exit')))}" + (' | ' + ' | '.join(errs) if errs else '')


def make_version(i, lv, coll, prev):
    size = SIZES[min(i, len(SIZES) - 1)]; V = S['versions'][lv]; maps = os.path.join(OUT, 'maps')
    if A.uvpack != 'skip':
        rep = os.path.join(OUT, 'logs', f'uvpack-{lv}.json')
        mode = 'smart' if V.get('source') == 'simplified' else A.uvpack
        rc, log = step(f'uvpack-{lv}', [B, '-b', '-t', str(A.threads), '-noaudio', WORK, '--python', py('uvpack.py'), '--', '--low', coll, '--save', WORK,
                                        '--size', str(size), '--mode', mode, '--report', rep, '--band', lv, '--family', SW['family']])
        if rc: fail(f'uvpack {lv}', tail(log))
        u = json.load(open(rep)); V['uv'] = dict(px_per_m=u['texel_density_px_per_m']['median'], used=u['atlas_texels_used'], overlap=u['overlap_px'],
                                                 need=(u.get('density_need') or {}).get('need_px_per_m'), ratio=(u.get('density_need') or {}).get('ratio'))
        if u['overlap_px']: fail(f'uvpack {lv}: UV overlap', f'{u["overlap_px"]} texels shared by two islands')
    if lv in ('near', 'mid') and not A.baked_near_mid: return live_version(lv, coll, prev, size)
    cmd = [B, '-b', '-t', str(A.threads), '-noaudio', WORK, '--python', py('bake.py'), '--', '--low', coll, '--out', maps, '--prefix', lv, '--size', str(size),
           '--high', A.high, '--threads', str(A.threads), '--level', lv]
    if EXCL_LOW: cmd += ['--exclude', EXCL_LOW]
    if A.glass_through: cmd += ['--glass-through', A.glass_through]
    if SLOTS: cmd += ['--slots', SLOTS]
    if A.skip_pbr_check: cmd += ['--skip-pbr-check']
    elif CLASSMAP: cmd += ['--class-map', CLASSMAP]
    rc, log = step(f'bake-{lv}', cmd)
    bj = os.path.join(maps, f'{lv}_bake.json')
    if os.path.exists(bj):
        b = json.load(open(bj)); V['miss'] = max(b.get('miss_share', {}).values() or [0])
        g = ((b.get('verify') or {}).get('groups') or {})
        V['drift'] = dict(metal=max([x['metal_drift'] for x in g.values() if x.get('metal_drift') is not None] or [None], key=lambda v: -1 if v is None else v),
                          dE=max([x['colour_dE'] for x in g.values() if x.get('colour_dE') is not None and x.get('colour_samples', 0) >= 20]
                                 or [None], key=lambda v: -1 if v is None else v))   # dE only where the check counts it (>= 20 plain-colour samples)
        if b.get('slots'): V['slots'] = {r: x['area_share'] for r, x in b['slots']['roles'].items()} | {'baked': b['slots']['baked_area_share']}
    if rc: fail(f'bake {lv}' + (' (material drift against the original)' if rc == 1 else ''), tail(log))
    out = os.path.join(OUT, f'{A.key}-{lv}.glb')
    cmd = [B, '-b', '-t', str(A.threads), '-noaudio', WORK, '--python', py('export_game.py'), '--', '--low', coll, '--maps', maps, '--prefix', lv, '--out', out,
           '--name', f'{A.key}_{lv}', '--surface-node', A.surface_node, '--glass-node', A.glass_node, '--against', prev, '--level', lv]
    rp = json.loads(A.root_props) if A.root_props else {}
    rp.setdefault('lod', lv); cmd += ['--root-props', json.dumps(rp)]
    if A.allow_designed: cmd += ['--allow-designed', A.allow_designed]
    if A.allow_inherited: cmd += ['--allow-inherited']
    if A.live: cmd += ['--live', A.live] + (['--live-fallback', A.live_fallback] if A.live_fallback else [])
    if SLOTS: cmd += ['--slots', SLOTS] + (['--contract', CONTRACT] if CONTRACT else [])
    cmd += ['--family', SW['family']] + (['--skip-pbr-check'] if A.skip_pbr_check else (['--class-map', CLASSMAP] if CLASSMAP else []))
    rc, log = step(f'export-{lv}', cmd)
    rj = out + '.json' if os.path.exists(out + '.json') else out[:-4] + '.rejected.glb.json'
    if os.path.exists(rj):
        r = json.load(open(rj)); V.update(tris=r['triangles'], draws=r['draw_calls'], kb=r['kb'], result=(r.get('integrity') or {}).get('result'),
                                          glb=r['file'], maps=r.get('maps'),
                                          pbr_check=pbr_short(r.get('pbr_check')),
                                          validator=((r.get('gltf_validator') or {}).get('errors')), reimport_ok=(r.get('reimport') or {}).get('ok'),
                                          slots_missing=(r.get('slots') or {}).get('missing'))
        if r.get('integrity_inherited'):
            ih = r['integrity_inherited']
            S['overrides'].append(f'{lv}: integrity FAULT inherited (--allow-inherited): version {ih.get("version")} vs reference '
                                  f'{ih.get("reference")} ({prev})')
    save()
    if rc:
        why = (json.load(open(rj)).get('refused') if os.path.exists(rj) else None) or tail(log)
        rej = out[:-4] + '.rejected.glb'
        if A.allow_faults and os.path.exists(rej):
            V['refused'] = [str(x)[:400] for x in why]
            S['overrides'].append(f'{lv}: export REFUSED ({len(why)} gate(s)); pictures made from {os.path.basename(rej)} '
                                  f'(--allow-faults): ' + ' || '.join(str(x)[:160] for x in why)); save()
            return rej
        fail(f'export {lv}', why)
    if V.get('budget') and V.get('tris', 0) > V['budget'] and not A.allow_over: fail(f'budget {lv}', f'{V["tris"]} triangles > {V["budget"]}')
    return out


def live_version(lv, coll, prev, size):
    """Near/mid with live material slots (live_version.py -> export_original.py -> integrity + pbr_check gates)."""
    V = S['versions'][lv]; vb = os.path.join(OUT, 'work', f'{A.key}-{lv}-live.blend'); rep = os.path.join(OUT, 'logs', f'live-{lv}.json')
    merge = (json.loads(A.merge) if A.merge else {}).get(lv, {})
    cmd = [B, '-b', '-t', str(A.threads), '-noaudio', WORK, '--python-exit-code', '1', '--python', py('live_version.py'), '--', '--high', A.high,
           '--low', coll, '--level', lv, '--out', vb, '--tex', os.path.join(OUT, 'maps', 'live'), '--size', str(size), '--name', f'{A.key}_{lv}',
           '--report', rep, '--threads', str(A.threads), '--merge', json.dumps(merge)]
    if A.exclude: cmd += ['--exclude', A.exclude]
    if A.live: cmd += ['--live', A.live]
    if A.no_normal: cmd += ['--no-normal', A.no_normal]
    rp = json.loads(A.root_props) if A.root_props else {}
    rp.setdefault('lod', lv); cmd += ['--root-props', json.dumps(rp)]
    rc, log = step(f'live-{lv}', cmd)
    if rc: fail(f'live {lv}', tail(log))
    lj = json.load(open(rep)); V['live'] = dict(slots=lj['slots'], projected=lj['projected'], blend=vb,
                                               mask_filled=lj['mask_texels_filled'], normal_flattened=lj['normal_texels_flattened'])
    out = os.path.join(OUT, f'{A.key}-{lv}.glb')
    rc, log = step(f'export-{lv}', [B, '-b', '-t', str(A.threads), '-noaudio', vb, '--python', py('export_original.py'), '--', '--out', out,
                                   '--collection', f'LIVE_{lv}', '--image-format', 'AUTO', '--threads', str(A.threads)])
    rj = out + '.json' if rc == 0 else out[:-4] + '.rejected.glb.json'
    r = json.load(open(rj)) if os.path.exists(rj) else {}
    why = list(r.get('refused') or ([] if rc == 0 else tail(log)))
    glb = r.get('file') or out
    if glb and os.path.exists(glb):
        ig = K.run_integrity(glb, prev, ['--held-by', orig])
        res = ig.get('result', ig.get('error', ''))
        if 'FAULT' in res: why.append(f'mesh_integrity: {res}')
        pc = dict(available=False, skipped=True, errors=[], lines=['--skip-pbr-check'], result='skipped') if A.skip_pbr_check else \
            K.pbr_check([glb, '--version', lv, '--json', glb + '.pbr.json', '--against', prev] + (['--class-map', CLASSMAP] if CLASSMAP else []) +
                        ['--family', SW['family']])
        if pc['errors']: why.append(f'pbr_check: {len(pc["errors"])} errors: ' + ' | '.join(pc['errors'][:6]))
        V.update(tris=r.get('triangles'), draws=r.get('draw_calls'), kb=r.get('kb'), result=res, glb=glb, pbr_check=pbr_short(pc),
                 validator=(r.get('gltf_validator') or {}).get('errors'), baked_meshes=r.get('baked_meshes'))
    save()
    if why:
        rej = out[:-4] + '.rejected.glb'
        if glb == out and os.path.exists(out): os.replace(out, rej); glb = rej
        if A.allow_faults and os.path.exists(rej):
            V['refused'] = [str(x)[:400] for x in why]
            S['overrides'].append(f'{lv}: live export REFUSED; pictures from {os.path.basename(rej)} (--allow-faults): ' + ' || '.join(str(x)[:160] for x in why))
            save(); return rej
        fail(f'export {lv} (live)', why)
    if V.get('budget') and (V.get('tris') or 0) > V['budget'] and not A.allow_over: fail(f'budget {lv}', f'{V["tris"]} triangles > {V["budget"]}')
    return out


ADV = {}        # version -> advisory lines of the last lodcmp (thin features; render.py --thin-fail makes them count)
def lodcmp(lv, glb):
    """render.py lodcmp of one version at its switch distance; returns (day/dusk fails, night fails, json path)."""
    od = os.path.join(OUT, 'lodcmp', lv); os.makedirs(od, exist_ok=True)
    rc, log = step(f'lodcmp-{lv}', [B, '-b', '-t', str(A.threads), '--factory-startup', '-noaudio', '--python', py('render.py'), '--', 'lodcmp', '--original', orig,
                                    '--versions', glb, '--at-switch', '--family', SW['family'], '--states', 'day,dusk,night',
                                    '--out', os.path.join(od, 'LODCMP.jpg')], gpu=True)
    jp = os.path.join(od, 'lodcmp.json')
    if not os.path.exists(jp): return None, None, None, tail(log)
    j = json.load(open(jp)); res = next(iter((j.get('results') or {}).values()), {})
    fails = res.get('fail') or []
    night = [f for f in fails if '/night' in f or 'night:' in f]
    other = [f for f in fails if f not in night]
    ADV[lv] = [a for a in (res.get('advisory') or []) if '/night' not in a and 'night:' not in a]
    return other, night, jp, None


prev = orig; glbs = []
for i, (lv, coll) in enumerate(LOWS):
    budget = BUD[min(i, len(BUD) - 1)] if BUD else None
    S['versions'][lv] = dict(low=coll, size=SIZES[min(i, len(SIZES) - 1)], budget=budget); save()
    vcoll = judge_or_make(lv, coll, budget)
    out = make_version(i, lv, vcoll, prev)
    V = S['versions'][lv]
    if not A.no_lodcmp:
        for p_ in range(A.picture_passes + 1):
            other, night, jp, err = lodcmp(lv, out)
            if err is not None: V['lodcmp'] = f'no result: {err}'; break
            V['lodcmp'] = dict(fails=other, night_known_fail=bool(night), json=jp, pass_no=p_, advisory=ADV.get(lv, []))
            if night and f'{lv}: lodcmp night' not in ' '.join(S['known_fails']):
                S['known_fails'].append(f'{lv}: lodcmp night ({len(night)} checks) - the renders lack the game\'s night glow '
                                        f'(named slots carry it in the game; no loop on night)')
            save()
            if not other or V.get('source') != 'simplified' or p_ == A.picture_passes: break
            V['tris_unlocked'] = V.get('tris_unlocked') or V.get('tris')
            vcoll_ = judge_or_make(lv, coll, budget, lock_from=jp)     # lock the failing regions and simplify again
            if vcoll_ is None: break                                   # too dear: the unlocked version stays
            vcoll = vcoll_; out = make_version(i, lv, vcoll, prev)
    if not A.no_sweep:
        od = os.path.join(OUT, 'sweep', lv); os.makedirs(od, exist_ok=True)
        rc, log = step(f'sweep-{lv}', ['node', py('sweep.mjs'), out, od])
        sj = next((os.path.join(od, f) for f in sorted(os.listdir(od)) if f.endswith('.json')), None)
        V['sweep'] = dict(exit=rc, dir=od, lines=tail(log, ('FAULT', 'PASS', 'blink', 'slit', 'RESULT'))[-3:])
        save()
    if not A.no_thumbs:
        od = os.path.join(OUT, 'thumbs')
        rc, log = step(f'thumbs-{lv}', [B, '-b', '-t', str(A.threads), '--factory-startup', '-noaudio', '--python', py('render.py'), '--', 'thumb', out,
                                        '--states', 'day,dawn,dusk,night,rain', '--out', od], gpu=True)
        V['thumbs'] = od if rc == 0 else f'failed: {tail(log)}'
        save()
    prev = out; glbs.append(out)

# 3. versions sheet at the game camera, each version at the closest distance it is shown
sheet = os.path.join(OUT, 'versions', 'VERSIONS.jpg'); os.makedirs(os.path.dirname(sheet), exist_ok=True)
dists = [SW['appears'][lv] for lv, _ in LOWS][:len(glbs)]
rc, log = step('versions', [B, '-b', '-t', str(A.threads), '--factory-startup', '-noaudio', '--python', py('render.py'), '--', 'versions', '--files', ','.join([orig] + glbs),
                            '--dist', ','.join(f'{d:g}' for d in dists), '--family', SW['family'], '--out', sheet], gpu=True)
if rc == 0: S['sheet'] = sheet
else: S['sheet_error'] = tail(log)
# 4. the record
refused = [lv for lv, v in S['versions'].items() if v.get('refused')]
if A.record and refused:
    S['overrides'].append(f'asset record NOT written: versions {refused} were refused by export_game (--allow-faults run)')
elif A.record:
    cmd = [sys.executable, py('asset_record.py'), A.record, '--switch-family', SW['family']]
    if A.model: cmd += ['--model', A.model] + (['--effort', A.effort] if A.effort else []) + (['--task', A.task] if A.task else []) + (['--session', A.session] if A.session else [])
    for i, g in enumerate(glbs): cmd += ['--lod', f'{LOWS[i][0]}={g}']
    rc, log = step('record', cmd)
    if rc: fail('asset record', tail(log))
S['state'] = 'done'; S['finished'] = time.strftime('%Y-%m-%d %H:%M:%S %z'); save(); summary()
print(open(os.path.join(OUT, 'LODS-SUMMARY.md')).read())
