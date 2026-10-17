#!/usr/bin/env python3
"""plan_check.py: validate a parts.json plan (format: kit3d/PARTS-SCHEMA.md). Standard library only.

  python3 plan_check.py <run>/parts.json [--done] [--json] [--template]

An entry with "feature_of": "<part>" is a FEATURE made in that part (slots cut into a kept housing, a pocket, an
engraved line): it has no objects, so it needs only "feature_of" (a part of this plan), "how" (how it is made, with
numbers) and "lod"; it carries no checks flags and --done asks nothing more of it.
Fails a part that lacks: dims_m (3 positive numbers); a host (another part, or "host_external": true) or a free reason;
a material with a source for its values (ref / src / <key>_src; "inferred" is accepted and counted); states (what it
does at night at least, or "as host"); a LOD fate for near, mid and far (keep / merge into X / texture / emissive band
/ normal map / card / simplify / drop); the four checks flags. Fails the PLAN when the top-level "composition" is
missing: {"dense_clusters": [...], "rest_areas": [...], "splits": [...]}, three non-empty lists of sentences (skill
3d-modelling "Compose the detail before modelling"); a builder's share of an asset may point at the asset's plan
instead: "composition": {"see": "/abs/path/parts.json"}. A flag that is true must have evidence written by a
tool, and for relations/uv the evidence file (kit3d.check JSON) must exist and show that part passing: a flag
flipped by hand fails. --done also fails every part whose four flags are not all true (the "done means" gate), and the
ASSET when its web export is missing, refused, stale or baked without a declared plan, or it lacks game versions, unless
asset.json says "purpose": "movie" (films only: no web export, no lower-poly versions; owner 2026-10-15).
The top-level "needs" says which looks and versions THIS subject calls for, decided from its subject and story
(owner 2026-10-17: not every asset needs both day and night looks, nor near/mid/far):
  "needs": {"looks": ["day", "night"], "versions": ["near", "far"], "why": "seen only by day from the road ..."}
looks from day/dawn/dusk/night/rain, versions from near/mid/far ([] = no game versions); "why" is required. A part's
states then must cover night only when night is a look, and its lod gives fates only for the listed versions. A plan
without "needs" is checked as before (night state, near/mid/far fates) and the summary says so.
Prints one line per failing part (<= 25 lines) and a summary; exit 0 ok, 1 failures, 2 usage.
"""
import json, os, sys

FLAGS = ('relations', 'uv', 'inspect', 'lod_kept')
LOOKS = ('day', 'dawn', 'dusk', 'night', 'rain')
VERSIONS = ('near', 'mid', 'far')
NEEDS = {'looks': ('day', 'night'), 'versions': VERSIONS}   # main() replaces it from the plan's "needs"
FATES = ('keep', 'merge', 'texture', 'emissive', 'normal', 'card', 'simplify', 'drop', 'bake')
MAT_KEYS = ('base', 'metallic', 'rough', 'coat', 'transmission', 'ior', 'emission', 'emission_k', 'alpha')
TEMPLATE = {
    "part": "roof.vent", "dims_m": [0.62, 0.40, 0.13], "host": "roof.shell",
    "relations": [{"kind": "attach", "at": "top", "by": "bottom"}],
    "material": {"ref": "physicallybased:Aluminum", "rough": 0.35, "rough_src": "judged: brushed, aged"},
    "states": ["day", "dusk", "night: unlit, catches the cab glow", "rain: wet sheen"],
    "lod": {"near": "keep", "mid": "keep, louvres as texture", "far": "merge into roof.shell"},
    "checks": {k: False for k in FLAGS}}


def _evidence_ok(e, part, flag):
    ev = (e.get('evidence') or {}).get(flag)
    if not isinstance(ev, dict) or not ev.get('tool'):
        return f'checks.{flag} true without tool evidence (only tools flip flags)'
    if flag in ('relations', 'uv'):
        f = ev.get('file')
        if not f or not os.path.exists(f): return f'checks.{flag}: evidence file missing ({f})'
        try:
            j = json.load(open(f))
        except (OSError, ValueError):
            return f'checks.{flag}: evidence file unreadable ({f})'
        pp = (j.get('per_part') or {}).get(part)
        if pp is None: return f'checks.{flag}: {os.path.basename(f)} did not check this part'
        if not pp.get(flag): return f'checks.{flag}: {os.path.basename(f)} shows it FAILING'
    elif ev.get('file') and not os.path.exists(ev['file']):
        return f'checks.{flag}: evidence file missing ({ev["file"]})'
    return None


def _material_issues(m, counts):
    out = []
    ms = m if isinstance(m, list) else [m]
    if not ms or ms == [None]: return ['material missing']
    for x in ms:
        if not isinstance(x, dict): out.append('material must be an object (or a list of them)'); continue
        whole = x.get('ref') or x.get('src')
        vals = [k for k in MAT_KEYS if k in x]
        unsourced = [k for k in vals if not (x.get(f'{k}_src') or whole)]
        if not whole and not vals: out.append('material: no ref/src and no values'); continue
        if unsourced: out.append(f'material values without a source: {", ".join(unsourced)} (add <key>_src, ref or src)')
        for k in vals:
            s = x.get(f'{k}_src') or ('' if x.get('ref') else x.get('src', ''))
            if str(s).strip().lower().startswith('inferred'): counts['inferred'] += 1
    return out


def check_feature(e, names):
    """A feature made IN another part (slots cut into a kept housing, an engraved line, a pocket): it has no objects
    of its own, so no dims / host / material / checks; it says whose it is, how it is made and what each version keeps."""
    p = e.get('part'); issues = []; host = e.get('feature_of')
    if host == p: issues.append('feature_of is the entry itself')
    elif host not in names: issues.append(f'feature_of {host!r} is not a part of this plan')
    if not str(e.get('how', '')).strip(): issues.append('how: how it is made in that part, with numbers ("42 slots 3 x 81 mm cut into the lid")')
    lod = e.get('lod')
    if not NEEDS['versions']: pass
    elif not isinstance(lod, dict): issues.append(f'lod: {{{", ".join(NEEDS["versions"])}}} fates')
    else:
        for lv in NEEDS['versions']:
            f = str(lod.get(lv, '')).strip().lower()
            if not f: issues.append(f'lod.{lv} missing')
            elif not f.startswith(FATES): issues.append(f'lod.{lv} {f[:30]!r}: start with one of {"/".join(FATES)}')
    if isinstance(e.get('checks'), dict) and any(e['checks'].get(k) is True for k in FLAGS):
        issues.append('checks: a feature has no flags of its own (the part it is cut into carries them)')
    return issues


def check_part(e, names, counts, done):
    p = e.get('part'); issues = []
    if not p: return ['(no "part" name)']
    if e.get('feature_of'): return check_feature(e, names)
    d = e.get('dims_m')
    if not (isinstance(d, list) and len(d) == 3 and all(isinstance(v, (int, float)) and v > 0 for v in d)):
        issues.append('dims_m: 3 positive numbers (m)')
    if e.get('free'):
        if not str(e['free']).strip(): issues.append('free: give the reason')
    elif e.get('host'):
        if e['host'] not in names and not e.get('host_external'):
            issues.append(f'host {e["host"]!r} is not a part of this plan (or set "host_external": true)')
        if e['host'] == p: issues.append('host is the part itself')
        if not e.get('relations'): issues.append('relations: how it meets its host (attach/span/lay/into)')
    else:
        issues.append('host (what holds it) or free (why nothing does)')
    issues += _material_issues(e.get('material', e.get('materials')), counts)
    st = e.get('states')
    if st != 'as host':
        if not isinstance(st, list) or not st: issues.append('states: list (day, night: ..., dusk, rain) or "as host"')
        elif 'night' in NEEDS['looks'] and not any(str(s).lower().startswith('night') for s in st): issues.append('states: say what it does at night ("night: unlit" / "night: glows 2700K")')
    lod = e.get('lod')
    if not NEEDS['versions']: pass
    elif not isinstance(lod, dict): issues.append(f'lod: {{{", ".join(NEEDS["versions"])}}} fates')
    else:
        for lv in NEEDS['versions']:
            f = str(lod.get(lv, '')).strip().lower()
            if not f: issues.append(f'lod.{lv} missing')
            elif not f.startswith(FATES): issues.append(f'lod.{lv} {f[:30]!r}: start with one of {"/".join(FATES)}')
            elif f.startswith('merge') and ' into ' in f:
                tgt = f.split(' into ', 1)[1].split(',')[0].split(' ')[0].strip()
                if tgt and tgt not in {n.lower() for n in names}: counts['merge_unknown'] += 1
    ck = e.get('checks')
    if not isinstance(ck, dict) or any(k not in ck for k in FLAGS):
        issues.append(f'checks: {{{", ".join(FLAGS)}}} (false until a tool flips them)')
    else:
        for k in FLAGS:
            if ck.get(k) is True:
                bad = _evidence_ok(e, p, k)
                if bad: issues.append(bad)
            elif done:
                issues.append(f'checks.{k} not true yet')
    if e.get('added_by', '').startswith('kit3d'): issues.insert(0, 'built but not planned (added by kit3d)')
    return issues


def needs_issues(d):
    """Plan-level "needs" (looks and versions this subject calls for). Sets NEEDS; returns issue strings."""
    n = d.get('needs') if isinstance(d, dict) else None
    if n is None: return []
    if not isinstance(n, dict): return ['needs must be an object {"looks": [...], "versions": [...], "why": "..."}']
    out = []
    looks, vers = n.get('looks'), n.get('versions')
    if not isinstance(looks, list) or not looks or any(l not in LOOKS for l in looks): out.append(f'needs.looks: a non-empty list from {"/".join(LOOKS)}')
    if not isinstance(vers, list) or any(v not in VERSIONS for v in vers): out.append(f'needs.versions: a list from {"/".join(VERSIONS)} ([] = none)')
    if not str(n.get('why', '')).strip(): out.append('needs.why: why the subject and story call for these looks and versions')
    if not out: NEEDS.update(looks=tuple(looks), versions=tuple(v for v in VERSIONS if v in vers))
    return out


COMPOSITION = ('dense_clusters', 'rest_areas', 'splits')


def composition_issues(d, path=None, depth=0):
    """Plan-level: the three composition lists (written BEFORE modelling: where detail is dense, what stays plain,
    the uneven splits). Returns a list of issue strings."""
    c = d.get('composition') if isinstance(d, dict) else None
    if c is None:
        return ['composition missing: {"dense_clusters": [...], "rest_areas": [...], "splits": [...]} (3d-modelling: '
                'Compose the detail before modelling)']
    if not isinstance(c, dict): return ['composition must be an object with dense_clusters, rest_areas, splits']
    if c.get('see'):
        ref = c['see'] if os.path.isabs(c['see']) else os.path.join(os.path.dirname(os.path.abspath(path or '.')), c['see'])
        if depth > 2: return [f'composition.see chain too long at {ref}']
        try:
            return [f'composition (see {os.path.basename(ref)}): {x}' for x in composition_issues(json.load(open(ref)), ref, depth + 1)]
        except (OSError, ValueError) as e:
            return [f'composition.see: cannot read {ref} ({type(e).__name__})']
    out = []
    for k in COMPOSITION:
        v = c.get(k)
        if not isinstance(v, list) or not v or not all(isinstance(x, str) and x.strip() for x in v):
            out.append(f'composition.{k}: a non-empty list of sentences')
    return out


def export_issues(path):
    """--done, asset level (owner 2026-10-15 12:53): an asset is not done unless its web export carries real materials
    (no undeclared bake, made from the CURRENT original) and it has game versions, UNLESS asset.json says
    "purpose": "movie" (an asset only for the films, never rendered on the web): then no web export is required and no
    lower-poly versions are made. Looks beside parts.json: asset.json, original/export/*.glb(.json), export/*-near|mid|far.glb."""
    import glob
    root = os.path.dirname(os.path.abspath(path))
    try: rec = json.load(open(os.path.join(root, 'asset.json')))
    except (OSError, ValueError): rec = {}
    purpose = rec.get('purpose', 'game')
    if purpose not in ('game', 'movie'): return [f'asset.json purpose {purpose!r}: use "game" (default) or "movie"']
    lods = [p for p in glob.glob(os.path.join(root, 'export', '*.glb')) if any(t in os.path.basename(p) for t in ('-near', '-mid', '-far'))]
    if purpose == 'movie':
        return [f'purpose "movie" makes no lower-poly versions, but export/ has {len(lods)}'] if lods else []
    out = []
    reps = [p for p in glob.glob(os.path.join(root, 'original', 'export', '*.glb.json')) if '.rejected.' not in p]
    if not reps:
        out.append('no web export of the original (original/export/<key>.glb from export_original.py); a game asset '
                   'needs one, or set "purpose": "movie" in asset.json')
    for rp in reps:
        try: r = json.load(open(rp))
        except (OSError, ValueError): out.append(f'{os.path.basename(rp)} unreadable'); continue
        if r.get('refused'): out.append(f'{os.path.basename(rp)}: export REFUSED: {r["refused"][:2]}')
        if r.get('baked_meshes') and not str(r.get('bake_ok') or '').strip():
            out.append(f'{os.path.basename(rp)}: {r["baked_meshes"]} meshes BAKED ({", ".join((r.get("baked_materials") or [])[:6])}) '
                       'with no declared plan: give them library kinds (standard idle record) or glTF-direct materials')
        src = r.get('source') or ''
        src_pc = src
        glb = rp[:-5]
        if os.path.exists(src_pc) and os.path.exists(glb) and os.path.getmtime(src_pc) > os.path.getmtime(glb) + 1:
            out.append(f'{os.path.basename(glb)} is older than its source {os.path.basename(src)}: re-export')
    if not lods and NEEDS['versions']: out.append(f'no game versions in export/ (lods_all.py; needs.versions {"/".join(NEEDS["versions"])}); or set "purpose": "movie"')
    # near / mid keep live shader slots (a design decision; owner 2026-10-15: "not to bake anything ... except for low quality
    # assets"): a near or mid whose materials carry no library kind (extras.idle) and do carry a base-colour texture is a
    # full bake. An earlier asset's game versions were exactly that and passed this check until 2026-10-15 14:2x.
    origs = [p for p in glob.glob(os.path.join(root, 'original', '*.blend'))]
    newest_orig = max((os.path.getmtime(p) for p in origs), default=0)
    for p in lods:
        b = os.path.basename(p)
        if newest_orig and os.path.getmtime(p) + 1 < newest_orig:
            out.append(f'{b} is older than the original .blend: remake the versions from the current original')
        if '-far' in b: continue
        try:
            mats = _glb_json(p).get('materials', [])
        except (OSError, ValueError) as e:
            out.append(f'{b}: unreadable GLB ({e})'); continue
        live = [m for m in mats if isinstance((m.get('extras') or {}).get('idle'), (dict, str))]
        baked = [m.get('name') for m in mats if (m.get('pbrMetallicRoughness') or {}).get('baseColorTexture') and m not in live]
        if not live and baked:
            out.append(f'{b}: no live shader slot, {len(baked)} baked material(s) {baked[:3]}: near and mid keep the '
                       'library kinds (a design decision); only far may be fully baked')
    return out


def _glb_json(path):
    """The JSON chunk of a .glb."""
    import struct
    with open(path, 'rb') as f:
        head = f.read(20)
        if head[:4] != b'glTF': raise ValueError('not a GLB')
        n = struct.unpack('<I', head[12:16])[0]
        return json.loads(f.read(n))


def main(a):
    if not a or a[0] in ('-h', '--help'):
        print(__doc__); return 0 if a else 2
    if a[0] == '--template':
        print(json.dumps({'asset': '<key>', 'needs': {'looks': ['day', 'dusk', 'night'], 'versions': ['near', 'mid', 'far'],
            'why': 'a station kiosk on the line: passed at every hour, lit at night, seen from the cab and across the yard'},
            'composition': {
            'dense_clusters': ['each doorway: handles on roses, lock, kick plate with its screws (z 0.7-1.5)'],
            'rest_areas': ['upper side band', 'roof field'],
            'splits': ['side height: skirt 0.25 / window band 0.30 / upper band 0.45 (no two equal)']},
            'parts': [TEMPLATE]}, indent=1)); return 0
    path = a[0]
    try:
        d = json.load(open(path))
    except (OSError, ValueError) as e:
        print(f'plan_check: cannot read {path}: {e}'); return 2
    parts = d if isinstance(d, list) else d.get('parts', [])
    need_bad = needs_issues(d)
    names = [e.get('part') for e in parts if isinstance(e, dict)]
    counts = {'inferred': 0, 'merge_unknown': 0}
    dup = sorted({n for n in names if names.count(n) > 1})
    res = {}
    for e in parts:
        if not isinstance(e, dict): continue
        res[e.get('part') or '?'] = check_part(e, set(names), counts, '--done' in a)
    for n in dup: res.setdefault(n, []).insert(0, 'duplicate part name')
    bad = {k: v for k, v in res.items() if v}
    plan_bad = need_bad + composition_issues(d, path)
    comp_bad = list(plan_bad)
    if '--done' in a: plan_bad = plan_bad + export_issues(path)
    if '--json' in a:
        print(json.dumps({'ok': not bad and not plan_bad, 'parts': len(res), 'failing': bad, 'plan': plan_bad, 'counts': counts}, indent=1))
        return 1 if bad or plan_bad else 0
    flags = {k: sum(1 for e in parts if isinstance(e, dict) and (e.get('checks') or {}).get(k) is True) for k in FLAGS}
    lines = [f'{p}: ' + '; '.join(v) for p, v in sorted(bad.items())]
    for l in plan_bad[:3]: print(('plan: ' + l)[:400])
    for l in lines[:25 - len(plan_bad[:3])]: print(l[:400])
    if len(lines) > 25 - len(plan_bad[:3]): print(f'... {len(lines) - 25 + len(plan_bad[:3])} more parts fail (--json for all)')
    nfeat = sum(1 for e in parts if isinstance(e, dict) and e.get('feature_of'))
    print(('needs: looks ' + '/'.join(NEEDS['looks']) + ', versions ' + ('/'.join(NEEDS['versions']) or 'none')) if isinstance(d, dict) and 'needs' in d
          else 'needs: not declared, checked for night + near/mid/far (add "needs" with a why)')
    print(f'{"FAIL" if bad or plan_bad else "PASS"} {len(res) - len(bad)}/{len(res)} parts planned completely' + (f' ({nfeat} features)' if nfeat else '') + '; composition '
          f'{"MISSING" if comp_bad else "ok"}' + (f'; web export/versions {len(plan_bad) - len(comp_bad)} faults' if len(plan_bad) > len(comp_bad) else '') + '; flags true: '
          + ', '.join(f'{k} {v}' for k, v in flags.items()) + f'; inferred material values {counts["inferred"]}'
          + (f'; merge targets not in the plan {counts["merge_unknown"]}' if counts['merge_unknown'] else ''))
    return 1 if bad or plan_bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
