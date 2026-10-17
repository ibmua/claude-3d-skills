"""parts.json read/write (stdlib only; usable outside Blender). The format is PARTS-SCHEMA.md beside this file.

Tools write here, builders write the plan: kit3d records the measured relations of each part (`relations`, the
builder's planned ones are kept once under `relations_planned`) and flips `checks.relations` / `checks.uv` with
`evidence` (tool, time, the check JSON). render.py inspect flips `checks.inspect`, the LOD tools `checks.lod_kept`.
plan_check.py refuses a flag that is true without matching evidence.
"""
import contextlib, datetime, fcntl, json, os

FLAGS = ('relations', 'uv', 'inspect', 'lod_kept')


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def load(path):
    if not path or not os.path.exists(path): return {'parts': []}
    with open(path) as f: d = json.load(f)
    if isinstance(d, list): d = {'parts': d}
    d.setdefault('parts', [])
    return d


@contextlib.contextmanager
def locked(path):
    lk = open(path + '.lock', 'a+')
    try:
        fcntl.flock(lk, fcntl.LOCK_EX); yield
    finally:
        fcntl.flock(lk, fcntl.LOCK_UN); lk.close()


def save(path, d):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f: json.dump(d, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def entry(d, name, create=False):
    for p in d['parts']:
        if p.get('part') == name: return p
    if not create: return None
    p = {'part': name, 'added_by': 'kit3d (not in the plan yet: fill dims_m, host/free, material, states, lod)',
         'checks': {k: False for k in FLAGS}}
    d['parts'].append(p); return p


def _compact(r):
    keep = ('kind', 'part', 'host', 'host_b', 'plan_host', 'plan_host_b', 'at', 'by', 'a', 'b', 'embed', 'lift', 'cut', 'form',
            'reason', 'note', 'measured')
    out = {k: r[k] for k in keep if k in r and r[k] not in (None, '', [])}
    if 'items' in r: out['items'] = len(r['items'])
    return out


def record(path, rels, per_part=None, check_json=None, tool='kit3d.check'):
    """Write relations (list of relation dicts with plan_part) and check flags into parts.json at `path`.
    per_part: {plan part: {'relations': bool, 'uv': bool}} from kit3d.check. Returns the plan parts touched."""
    if not path: return []
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with locked(path):
        d = load(path); touched = set()
        byp = {}
        for r in rels: byp.setdefault(r.get('plan_part') or r['part'], []).append(r)
        for pp, rs in byp.items():
            e = entry(d, pp, create=True); touched.add(pp)
            if 'relations' in e and 'relations_planned' not in e and not e.get('relations_by_tool'):
                e['relations_planned'] = e['relations']
            e['relations'] = [_compact(r) for r in sorted(rs, key=lambda x: (x['part'], x['kind']))]
            e['relations_by_tool'] = tool
            kinds = {r['kind'] for r in rs}
            if kinds <= {'free', 'root'} and not e.get('free') and not e.get('host'):
                e['free'] = '; '.join(sorted({r.get('reason', '') for r in rs})) or 'free'
        for pp, fl in (per_part or {}).items():
            e = entry(d, pp, create=True); touched.add(pp)
            e.setdefault('checks', {k: False for k in FLAGS}); e.setdefault('evidence', {})
            for k in ('relations', 'uv'):
                if k in fl:
                    e['checks'][k] = bool(fl[k])
                    e['evidence'][k] = {'tool': tool, 'at': now(), 'file': check_json, 'ok': bool(fl[k])}
        d['updated'] = now(); save(path, d)
    return sorted(touched)


def set_flag(path, part, flag, ok, tool, file=None, note=None):
    """For other tools (render.py inspect -> 'inspect', lods_all / lodcmp -> 'lod_kept')."""
    if flag not in FLAGS: raise ValueError(f'flag {flag!r} not in {FLAGS}')
    with locked(path):
        d = load(path); e = entry(d, part, create=True)
        e.setdefault('checks', {k: False for k in FLAGS}); e.setdefault('evidence', {})
        e['checks'][flag] = bool(ok)
        e['evidence'][flag] = {'tool': tool, 'at': now(), 'file': file, 'ok': bool(ok), **({'note': note} if note else {})}
        d['updated'] = now(); save(path, d)
