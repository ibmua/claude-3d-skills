#!/usr/bin/env python3
"""Create or update an asset's own record (asset.json): who made it, when, its game versions, mounts, lights, states,
components and sources. Plain python3, no Blender.

  asset_record.py ASSET.json
      [--model claude-opus-5-5 --effort medium [--label "Opus 5.5 medium"] --task TASK [--session ID] [--start TS] [--end TS]
       [--active-minutes N] [--did "what this maker did"] [--transcript FILE.jsonl ...]]
      [--made-with '{"model": ..., ...}']
      [--lod near=export/x-near.glb@12 --lod mid=export/x-mid.glb@30 --lod far=export/x-far.glb@70]
      [--mounts-from GLB] [--states day,dusk,night,rain]
      [--component NAME=built:PATH] [--component NAME=borrowed:PATH] ...
      [--source '{"url": ..., "license": "CC0", "author": ..., "changes": "..."}'] ...
      [--set KEY=JSON] ... [--dry-run]

made_with  a LIST, one entry per model/session that worked on the asset: model, effort, label, task, session,
           start, end, active_minutes. An entry is matched on (model, task, session): given fields update it, every
           other field stays (api_cost and other cost keys written by the cost tools survive); no match -> appended.
           Earlier entries are never removed.
time       (owner 2026-10-12 22:59, "should remember time") each entry carries start, end and active_minutes when
           known (gaps over 10 min between a maker's messages count as idle); the record carries top-level
           `time` {first_start, last_end, active_minutes_total}. Unknown stays EMPTY (null), never guessed: the
           cost/time writer fills it from the transcripts. --transcript FILE.jsonl (a Claude Code session or subagent
           log; several allowed) computes start/end/active_minutes of THIS entry from its message timestamps.
           `time` is recomputed from the entries only when every entry is known; otherwise what is there is kept.
lods       {near|mid|far: file (relative to the record), tris, draws, kb, switch_m, integrity, gaps, flicker,
           mounts, lights}: numbers read from the GLB itself and from export_game.py's GLB.json report.
           --switch-family F: switch_m / shown_m / error_target_m per version and a top-level lod_switch block, all
           from scripts/switch.json (the one place for switch distances, read from the game code).
mounts / lights  read from --mounts-from (default: the highest version given with --lod): every node named
           mount.<kind>.<n> / light.<kind>.<n> with its world position (glTF frame, +Y up) and extras. Same-named
           entries keep their other fields; entries gone from the GLB are dropped (and printed).
states     list, merged (order kept). components: list of {name, kind: built|borrowed, path}, merged by name.
sources    list of {url or path, license, author, changes}, merged by url/path.
Cost keys (api_cost, api_cost_known_part, maker_label, maker_count) are written by the cost tools, never here.

Safe to run again and again: the file is rewritten only when something changed (then `updated` is set), atomically
(temp + rename), and refused when the result would grow suspiciously (> 1.5x + 200 KB: a tool feeding back its own
output; LESSONS 2026-10-12 16:12). Unknown keys already in the record are never dropped.
"""
import argparse, datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _kit as K
try:
    from zoneinfo import ZoneInfo
    KYIV = ZoneInfo('Europe/Kyiv')
except Exception:
    KYIV = None

COST_KEYS = {'api_cost', 'api_cost_known_part', 'maker_label', 'maker_count'}
IDLE_MIN = 10
PRETTY = {'opus': 'Opus 5.5', 'sonnet': 'Sonnet', 'haiku': 'Haiku', 'fable': 'Fable'}


def now():
    return datetime.datetime.now(KYIV).isoformat(timespec='seconds') if KYIV else datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def parse_ts(s):
    if not s: return None
    try:
        d = datetime.datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except ValueError:
        return None
    if d.tzinfo is None and KYIV: d = d.replace(tzinfo=KYIV)
    return d


def from_transcripts(paths):
    """start, end, active minutes from the message timestamps of Claude Code transcripts (gaps > 10 min idle)."""
    ts = []
    for p in paths:
        with open(p, errors='replace') as f:
            for line in f:
                i = line.find('"timestamp"')
                if i < 0: continue
                try: d = parse_ts(json.loads(line).get('timestamp'))
                except Exception: d = None
                if d: ts.append(d)
    if not ts: return None
    ts.sort(); act = 0.0
    for a, b in zip(ts, ts[1:]):
        g = (b - a).total_seconds() / 60
        if g <= IDLE_MIN: act += g
    tz = KYIV or ts[0].tzinfo
    return dict(start=ts[0].astimezone(tz).isoformat(timespec='seconds'), end=ts[-1].astimezone(tz).isoformat(timespec='seconds'),
                active_minutes=round(act, 1))


def merge_list(old, new, key):
    """merge dicts in `new` into list `old` by key (a function giving the identity); keep old order, append new."""
    out = [dict(x) for x in (old or [])]
    for n in new:
        k = key(n)
        hit = next((o for o in out if key(o) == k), None)
        if hit is None: out.append(n)
        else: hit.update({a: b for a, b in n.items() if b is not None})
    return out


def main(argv):
    ap = argparse.ArgumentParser(prog='asset_record.py', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('record')
    for k in ('model', 'effort', 'label', 'task', 'session', 'start', 'end', 'did'): ap.add_argument('--' + k)
    ap.add_argument('--active-minutes', type=float); ap.add_argument('--transcript', action='append', default=[])
    ap.add_argument('--made-with', action='append', default=[]); ap.add_argument('--lod', action='append', default=[])
    ap.add_argument('--mounts-from'); ap.add_argument('--states', default='')
    ap.add_argument('--component', action='append', default=[]); ap.add_argument('--source', action='append', default=[])
    ap.add_argument('--set', action='append', default=[]); ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--switch-family')
    A = ap.parse_args(argv)
    path = os.path.abspath(A.record); base = os.path.dirname(path)
    old_txt = open(path).read() if os.path.exists(path) else ''
    if len(old_txt) > 20_000_000: K.die(f'{path} is {len(old_txt) // 1_000_000} MB: a record that big is broken; look first')
    R = json.loads(old_txt) if old_txt else {}
    before = json.dumps(R, sort_keys=True)
    notes = []

    # ---- made_with
    entries = [json.loads(x) for x in A.made_with]
    if A.model:
        e = dict(model=A.model, effort=A.effort, label=A.label or f'{PRETTY.get(A.model, A.model)} {A.effort or ""}'.strip(),
                 task=A.task, session=A.session, start=A.start, end=A.end, active_minutes=A.active_minutes, did=A.did)
        if A.transcript:
            t = from_transcripts(A.transcript)
            if t:
                for k, v in t.items():
                    if e.get(k) is None: e[k] = v
                e['transcripts'] = A.transcript
            else: notes.append('no timestamps in the transcripts given')
        entries.append(e)
    for e in entries:
        if any(k in e for k in COST_KEYS): K.die('cost keys are written by the cost tools, not by asset_record.py')
        if not e.get('model'): K.die('a made_with entry needs a model')
    mw = R.get('made_with')
    if isinstance(mw, dict): mw = [mw]
    ident = lambda e: (e.get('model'), e.get('task'), e.get('session'))
    for e in entries:
        hit = next((o for o in (mw or []) if ident(o) == ident(e)), None)
        if hit is None:
            full = {k: e.get(k) for k in ('model', 'effort', 'label', 'task', 'session', 'start', 'end', 'active_minutes')}
            full.update({k: v for k, v in e.items() if v is not None})
            mw = (mw or []) + [full]
        else:
            hit.update({k: v for k, v in e.items() if v is not None})
    if mw is not None:
        for e in mw:
            for k in ('start', 'end', 'active_minutes'): e.setdefault(k, None)
        R['made_with'] = mw
        starts = [parse_ts(e.get('start')) for e in mw]; ends = [parse_ts(e.get('end')) for e in mw]
        acts = [e.get('active_minutes') for e in mw]
        T = dict(R.get('time') or {}); T.setdefault('first_start', None); T.setdefault('last_end', None); T.setdefault('active_minutes_total', None)
        if all(starts): T['first_start'] = min(starts).isoformat(timespec='seconds')
        if all(ends): T['last_end'] = max(ends).isoformat(timespec='seconds')
        if all(a is not None for a in acts): T['active_minutes_total'] = round(sum(acts), 1)
        R['time'] = T

    # ---- lods
    lods = dict(R.get('lods') or {}); top = None
    for spec in A.lod:
        lv, _, rest = spec.partition('='); f, _, sw = rest.partition('@')
        fp = os.path.abspath(f) if os.path.isabs(f) or os.path.exists(f) else os.path.join(base, f)
        if not os.path.exists(fp): K.die(f'no such GLB {fp}')
        st = K.glb_stats(fp)
        rel = os.path.relpath(fp, base) if fp.startswith(base + os.sep) else fp
        e = dict(lods.get(lv) or {})
        e.update(file=rel, tris=st['triangles'], draws=st['draw_calls'], kb=st['kb'], mounts=len(st['mounts']), lights=len(st['lights']))
        if sw: e['switch_m'] = float(sw)
        rep = fp + '.json'
        if os.path.exists(rep):
            ig = (json.load(open(rep)).get('integrity') or {})
            for k in ('result', 'gaps', 'flicker', 'bodies'):
                if ig.get(k): e['integrity' if k == 'result' else k] = ig[k]
            if ig.get('report'): e['integrity_report'] = os.path.relpath(ig['report'], base) if ig['report'].startswith(base + os.sep) else ig['report']
        lods[lv] = e
        order = ['near', 'mid', 'far']
        if top is None or (lv in order and (top[0] not in order or order.index(lv) < order.index(top[0]))): top = (lv, fp)
    if A.switch_family:       # the real switch distances, from scripts/switch.json (the one place; read from the game code)
        sw = K.switch(A.switch_family)
        R['lod_switch'] = dict(family=sw['family'], near_mid_m=sw['near_mid'], mid_far_m=sw['mid_far'], hysteresis_m=sw['hysteresis'],
                               note='[low graphics, full graphics]: the game picks a point in each range by its verified graphics '
                                    'level; a version is seen from the low end minus the hysteresis', source=sw['source'])
        shown = {'near': [0, sw['near_mid'][1] + sw['hysteresis']], 'mid': [sw['appears']['mid'], sw['mid_far'][1] + sw['hysteresis']],
                 'far': [sw['appears']['far'], None]}
        for lv, e in lods.items():
            if lv in shown:
                e['shown_m'] = shown[lv]; e['switch_m'] = {'near': sw['near_mid'][1], 'mid': sw['mid_far'][1]}.get(lv)
                e['error_target_m'] = sw['target_m'][lv]
    if A.lod: R['lods'] = lods

    # ---- mounts / lights
    mf = A.mounts_from or (top[1] if top else None)
    if mf:
        st = K.glb_stats(mf)
        for key in ('mounts', 'lights'):
            new = []
            for m in st[key]:
                parts = m['name'].split('.')
                new.append(dict(name=m['name'], kind=parts[1] if len(parts) > 1 else '', position=m['translation'],
                                matrix=m['matrix'], extras=m['extras']))
            oldl = R.get(key) or []
            if isinstance(oldl, list) and oldl and isinstance(oldl[0], str):            # older records listed names only
                oldl = [dict(name=n) for n in oldl]
            gone = [o.get('name') for o in oldl if isinstance(o, dict) and o.get('name') not in {n['name'] for n in new}]
            if gone: notes.append(f'{key} no longer in {os.path.basename(mf)}: {gone[:10]}{" ..." if len(gone) > 10 else ""}')
            keep = {o['name']: o for o in oldl if isinstance(o, dict) and 'name' in o}
            R[key] = [dict(keep.get(n['name'], {}), **n) for n in new]
            if key == 'mounts':
                cnt = {}
                for n in new: cnt[n['kind']] = cnt.get(n['kind'], 0) + 1
                R['mount_counts'] = cnt

    # ---- states, components, sources, free keys
    if A.states:
        st = list(R.get('states') or [])
        for s in K.csv(A.states):
            if s not in st: st.append(s)
        R['states'] = st
    if A.component:
        new = []
        for c in A.component:
            n, _, rest = c.partition('='); kind, _, p = rest.partition(':')
            if kind not in ('built', 'borrowed'): K.die(f'--component {c}: kind must be built or borrowed')
            new.append(dict(name=n, kind=kind, path=p or None))
        old = R.get('components') or []
        if isinstance(old, dict): old = [dict(name=k, **(v if isinstance(v, dict) else {'path': v})) for k, v in old.items()]
        R['components'] = merge_list(old, new, lambda x: x.get('name'))
    if A.source:
        new = [json.loads(s) for s in A.source]
        R['sources'] = merge_list(R.get('sources') or [], new, lambda x: x.get('url') or x.get('path'))
    for kv in A.set:
        k, _, v = kv.partition('=')
        if k in COST_KEYS: K.die(f'{k} is written by the cost tools, not here')
        val = json.loads(v)
        if isinstance(val, dict) and isinstance(R.get(k), dict): R[k] = {**R[k], **val}
        else: R[k] = val

    after = json.dumps({k: v for k, v in R.items() if k != 'updated'}, sort_keys=True)
    was = json.dumps({k: v for k, v in json.loads(before).items() if k != 'updated'}, sort_keys=True)
    for n in notes: print('note:', n)
    if after == was:
        print(f'unchanged: {path}'); return 0
    R['updated'] = now()
    txt = json.dumps(R, indent=1, ensure_ascii=False) + '\n'
    if old_txt and len(txt) > 1.5 * len(old_txt) + 200_000:
        K.die(f'refusing: {path} would grow from {len(old_txt)} to {len(txt)} bytes; look for feedback first')
    if A.dry_run:
        print(txt); return 0
    tmp = path + '.tmp'
    with open(tmp, 'w') as f: f.write(txt)
    os.replace(tmp, path)
    summary = dict(made_with=[(e.get('label'), e.get('task'), e.get('start'), e.get('active_minutes')) for e in R.get('made_with', [])],
                   time=R.get('time'), lods={k: (v.get('tris'), v.get('draws'), v.get('switch_m')) for k, v in (R.get('lods') or {}).items()},
                   mounts=len(R.get('mounts') or []), lights=len(R.get('lights') or []), states=R.get('states'))
    print(f'wrote {path}: {json.dumps(summary, ensure_ascii=False)}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
