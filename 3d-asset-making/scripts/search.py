#!/usr/bin/env python3
"""search.py: cheap asset search WITH PICTURES. Haiku scouts (claude -p) look in our libraries first, then free
sources online (Poly Haven CC0 first), save a picture of every candidate, and this tool lays them out on one sheet.

  python3 search.py <run folder> <parts.json> [--model claude-haiku-5-5] [--parallel 3] [--group 4] [--timeout 1200]
                    [--subject "one line about the whole asset"]

parts.json: a list of {"part": "bogie", "description": "...", "look": "day: ... / night: ...", "size": "2.6 x 2.1 x 0.9 m"}
            or {"subject": "...", "parts": [...]}.
For each group of <= --group parts it runs one searcher (at most --parallel at once):
  claude -p --model <model> --output-format json --dangerously-skip-permissions "<brief>"
with the brief = search_brief.md next to this script, placeholders filled ($SUBJECT, $PARTS, $SEARCH_DIR,
$MACHINE_NOTE); edit the template, not this code. The searcher inherits CLAUDE_CONFIG_DIR (the account) and runs in
the run folder, so its transcript lands under that account like any session (Claude Cost reads it from there).
Output in <run>/search/:
  <part>/<candidate>.jpg|png   pictures saved by the searchers
  raw-g<N>.json                each searcher's whole claude -p JSON answer (cost, session id, its text)
  results.json                 [{part, description, look, size, candidates:[{name, source, path_or_url, license,
                               format, tris, materials, picture, fit_note}]}], plus cost and sessions
  SHEET.jpg                    one row per part: its words on the left, the candidates' pictures with captions
and one `search` event per part in <run>/progress.jsonl (via report.py next to this script), picture = SHEET.jpg.
Exit 0 when every part got an answer (even "nothing fits"), 1 when a searcher failed (its parts say so), 2 usage.
"""
import concurrent.futures as cf, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
CLAUDE = next((p for p in (os.environ.get('CLAUDE_BIN'), os.path.expanduser('~/.local/bin/claude'))
               if p and os.path.exists(p)), 'claude')
ON_PC = True   # the dashboard runs on this machine
MACHINE_NOTE = ('- the asset dashboard catalog: `curl -s http://127.0.0.1:8152/api/catalog | '
                'python3 -c "import json,sys; ..."` (filter it, never print it whole)'
                if ON_PC else
                '- (the Blender asset dashboard catalog at 127.0.0.1:8152 is on the PC only, not here; use the folders above)')


def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', str(s).lower()).strip('-')[:60] or 'x'


def opts(a):
    o = {'model': 'claude-haiku-5-5', 'parallel': 3, 'group': 4, 'timeout': 1200, 'subject': None}
    pos, i = [], 0
    while i < len(a):
        if a[i].startswith('--'):
            k = a[i][2:]
            if k not in o: raise SystemExit(f'unknown option {a[i]}')
            o[k] = a[i + 1] if k in ('model', 'subject') else int(a[i + 1]); i += 2
        else: pos.append(a[i]); i += 1
    return pos, o


def parse_answer(text):
    """The searcher's JSON array (tolerates a code fence or stray prose around it)."""
    t = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
    try: return json.loads(t)
    except Exception: pass
    a, b = t.find('['), t.rfind(']')
    if a >= 0 and b > a:
        try: return json.loads(t[a:b + 1])
        except Exception: pass
    return None


def run_group(n, parts, run, sdir, subject, o):
    brief = open(os.path.join(HERE, 'search_brief.md')).read()
    for k, v in (('$SUBJECT', subject or '(not given: infer it from the parts)'),
                 ('$PARTS', '\n'.join('- ' + json.dumps(p, ensure_ascii=False) for p in parts)),
                 ('$SEARCH_DIR', sdir), ('$MACHINE_NOTE', MACHINE_NOTE)):
        brief = brief.replace(k, v)
    for p in parts: os.makedirs(os.path.join(sdir, slug(p['part'])), exist_ok=True)
    open(os.path.join(sdir, f'brief-g{n}.md'), 'w').write(brief)
    env = {k: v for k, v in os.environ.items() if k not in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN')}   # subscription only
    t0 = time.time()
    try:
        r = subprocess.run([CLAUDE, '-p', '--model', o['model'], '--output-format', 'json', '--dangerously-skip-permissions', brief],
                           cwd=run, env=env, capture_output=True, text=True, timeout=o['timeout'])
        out, err = r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        out, err = (e.stdout or b'').decode() if isinstance(e.stdout, bytes) else (e.stdout or ''), f'timeout after {o["timeout"]} s'
    open(os.path.join(sdir, f'raw-g{n}.json'), 'w').write(out or '')
    try: d = json.loads(out)
    except Exception: d = {}
    ans = parse_answer(d.get('result', '')) if d else None
    meta = {'group': n, 'seconds': round(time.time() - t0), 'cost_usd': d.get('total_cost_usd'), 'session': d.get('session_id'),
            'error': None if isinstance(ans, list) else (d.get('result') or err or 'no answer')[:500]}
    print(f'  group {n}: {len(parts)} parts, {meta["seconds"]} s, ${meta["cost_usd"]}, '
          f'{"ok" if not meta["error"] else "FAILED: " + meta["error"][:200]}', flush=True)
    return parts, ans if isinstance(ans, list) else [], meta


def sheet(rows, path):
    from PIL import Image, ImageDraw, ImageFont
    def font(sz):
        for f in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/TTF/DejaVuSans.ttf'):
            if os.path.exists(f): return ImageFont.truetype(f, sz)
        return ImageFont.load_default()
    F, FB, FS = font(15), font(19), font(13)
    TW, TH, LW, CAP, PAD = 300, 225, 360, 74, 10
    ncol = max([len(r['candidates']) for r in rows] + [1])
    W = LW + ncol * (TW + PAD) + PAD; RH = TH + CAP + PAD
    im = Image.new('RGB', (W, 50 + RH * len(rows)), (22, 24, 28)); dr = ImageDraw.Draw(im)
    dr.text((PAD, 14), f'Asset search: {len(rows)} parts, {sum(len(r["candidates"]) for r in rows)} candidates', fill=(160, 200, 255), font=FB)
    def wrap(t, w, f):
        out, line = [], ''
        for word in str(t).split():
            if dr.textlength(line + ' ' + word, font=f) > w and line: out.append(line); line = word
            else: line = (line + ' ' + word).strip()
        return out + ([line] if line else [])
    for i, r in enumerate(rows):
        y = 50 + i * RH
        dr.text((PAD, y), r['part'], fill=(255, 255, 255), font=FB)
        yy = y + 28
        for t in [r.get('description', ''), 'look: ' + str(r.get('look', '')), 'size: ' + str(r.get('size', ''))]:
            for ln in wrap(t, LW - 2 * PAD, FS)[:5]:
                dr.text((PAD, yy), ln, fill=(200, 200, 200), font=FS); yy += 17
        if not r['candidates']:
            dr.text((LW, y + TH // 2), r.get('note') or 'no candidates', fill=(255, 120, 120), font=F)
        for j, c in enumerate(r['candidates']):
            x = LW + j * (TW + PAD)
            p = c.get('picture'); ok = False
            if p and os.path.exists(p):
                try:
                    t = Image.open(p).convert('RGB'); t.thumbnail((TW, TH))
                    im.paste(t, (x + (TW - t.width) // 2, y + (TH - t.height) // 2)); ok = True
                except Exception: pass
            if not ok:
                dr.rectangle([x, y, x + TW, y + TH], outline=(90, 90, 90)); dr.text((x + 90, y + TH // 2 - 8), 'no picture', fill=(150, 150, 150), font=F)
            cy = y + TH + 4
            dr.text((x, cy), (c.get('name') or '?')[:38], fill=(255, 255, 255), font=F)
            dr.text((x, cy + 18), f"{c.get('source', '?')} | {c.get('license', '?')} | {c.get('format', '?')} | tris {c.get('tris') if c.get('tris') is not None else '?'}"[:46], fill=(160, 220, 160), font=FS)
            for k, ln in enumerate(wrap(c.get('fit_note', ''), TW, FS)[:2]):
                dr.text((x, cy + 36 + k * 16), ln, fill=(190, 190, 190), font=FS)
    im.save(path, quality=88)


def main(a):
    if not a or a[0] in ('-h', '--help'):
        print(__doc__); return 0 if a else 2
    pos, o = opts(a)
    if len(pos) != 2: print(__doc__); return 2
    run, pj = os.path.abspath(pos[0]), pos[1]
    data = json.load(open(pj))
    subject = o['subject']
    if isinstance(data, dict): subject = subject or data.get('subject'); data = data['parts']
    if not data or not all(isinstance(p, dict) and p.get('part') for p in data): print('parts.json: a list of {part, description, look, size}'); return 2
    os.makedirs(run, exist_ok=True); sdir = os.path.join(run, 'search'); os.makedirs(sdir, exist_ok=True)
    groups = [data[i:i + o['group']] for i in range(0, len(data), o['group'])]
    print(f'search: {len(data)} parts in {len(groups)} groups, model {o["model"]}, account {os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")}', flush=True)
    rows, metas = [], []
    with cf.ThreadPoolExecutor(max_workers=max(1, min(3, o['parallel']))) as ex:
        futs = [ex.submit(run_group, n + 1, g, run, sdir, subject, o) for n, g in enumerate(groups)]
        for f in futs:
            parts, ans, meta = f.result(); metas.append(meta)
            by = {str(x.get('part')): x for x in ans if isinstance(x, dict)}
            for p in parts:
                got = by.get(p['part']) or by.get(slug(p['part'])) or {}
                cands = [c for c in got.get('candidates', []) if isinstance(c, dict)]
                for c in cands:                               # a relative or missing picture: look where the brief told it to save
                    pic = c.get('picture')
                    if pic and not os.path.isabs(pic): pic = os.path.join(run, pic)
                    if not (pic and os.path.exists(pic)):
                        alt = [os.path.join(sdir, slug(p['part']), f) for f in sorted(os.listdir(os.path.join(sdir, slug(p['part']))))
                               if f.rsplit('.', 1)[0] == slug(c.get('name', ''))]
                        pic = alt[0] if alt else None
                    c['picture'] = pic
                rows.append({**p, 'candidates': cands, 'note': None if got else ('searcher failed: ' + (meta['error'] or '')[:120] if meta['error'] else 'no answer for this part')})
    order = {p['part']: i for i, p in enumerate(data)}; rows.sort(key=lambda r: order[r['part']])
    sp = os.path.join(sdir, 'SHEET.jpg'); sheet(rows, sp)
    cost = sum(m['cost_usd'] or 0 for m in metas)
    json.dump({'subject': subject, 'model': o['model'], 'cost_usd_list_price': round(cost, 4), 'searchers': metas, 'parts': rows},
              open(os.path.join(sdir, 'results.json'), 'w'), indent=1, ensure_ascii=False)
    for r in rows:
        n = len(r['candidates']); best = r['candidates'][0] if n else None
        msg = (f"{r['part']}: {n} candidates, {sum(1 for c in r['candidates'] if c.get('picture'))} with pictures"
               + (f"; first: {best.get('name')} ({best.get('source')}, {best.get('license')})" if best else f"; {r.get('note') or 'none fits'}"))
        subprocess.run([sys.executable, os.path.join(HERE, 'report.py'), run, 'search', msg, '--picture', sp,
                        '--data', json.dumps({'candidates': n})], capture_output=True)
    for r in rows:
        print(f"  {r['part']}: " + (', '.join(f"{c.get('name')} [{c.get('source')}{'' if c.get('picture') else ', NO PICTURE'}]" for c in r['candidates']) or (r.get('note') or 'none')))
    print(f'sheet {sp}\nresults {os.path.join(sdir, "results.json")}\ncost ${cost:.3f} (list price; subscription)')
    return 1 if any(m['error'] for m in metas) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
