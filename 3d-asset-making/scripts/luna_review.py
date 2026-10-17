#!/usr/bin/env python3
"""luna_review.py: one Luna review of one asset, without hand-building the packet. Runs on the build box.

  python3 luna_review.py <key> "<what it is, for the reviewer>" <picture> [<picture> ...]
         [--run <run folder>] [--glb <file.glb>] [--concept <picture>]... [--family train] [--form "<form>"]
         [--size X,H,D] [--tris N] [--draws N] [--materials N] [--textures N] [--bytes N] [--redo]
         [--questions q.json] [--versus BEST.jpg] [--fixes fixes.json [--before PREV.jpg]]
         [--no-level] [--out-dir DIR] [--effort high|max] [--per-call 6] [--repeat 2] [--inspect inspect.json]
         [--parts-json parts.json] [--dry-run]
  python3 luna_review.py --make-questions inspect.json [--parts-json parts.json] [--changed A,B]
         [--concept-notes "<what the concept shows>"] [--max-per-part 5] --out q.json

THE LEVEL REVIEW (default; the stopping signal). It writes the packet the project's reviewer reads, exactly like the
workers' luna_pack.py / luna_packet.py did:
  assets-lib/_luna-review/<key>/facts.json  {family, form, title, size_m [x, height, depth], triangles, draw_calls,
                                            materials, textures, bytes, concepts, views}
  assets-lib/_luna-review/<key>/views/<name>.jpg   each picture at most 1280x720 (names from the file names)
  concept pictures (--concept, any number) are copied into <key>/concepts/ and listed first, as luna_assets.py wants
then runs  ops/luna_assets.py run --only <key> --jobs 1 [--redo]  (gpt-6-luna, effort max, on the Codex logins in
turn: ops/heads/luna-asset-review.md is the request), prints  LEVEL <n>  and the REVIEW.md path, and with --run appends
a `review` event (--luna <level>, --asset <key>, picture = the first view) to <run>/progress.jsonl via report.py.
--glb fills triangles, draw calls (primitives), materials, textures, bytes and size from the file; explicit flags win.
The description becomes the reviewer's title line: say what it is, which version (original / near / mid / far), what
in the pictures is NOT part of the asset (stand beams, placeholders), and what to judge it against.
Use a NEW key per round (e.g. a car-cab-a-near-r3): a key that already has REVIEW.md is skipped unless --redo.
If the review fails, facts.json is renamed facts.kept.json, so nobody's later `luna_assets.py run` (without --only)
reviews it by accident (ops/heads/asset-repair.md). --no-level skips it (only the checks below run).

THE CHECKS (each a fresh Luna session through concepts/tools/judge.luna: gpt-6-luna, --effort high by default, images
copied under neutral names and capped at 1280x720, never upscaled). BLIND: Luna sees only pictures and neutral
questions, never why a place was picked, what was changed, what we hope, or which picture is newer. Every call's
prompt, image list and raw answer are kept in <out-dir>/calls/; one usage record per call goes to
~/.local/share/3d-review/luna-usage.jsonl, written by judge.luna itself for every caller (codex-direct form; Claude
Cost's ocgoLedgers read it, because judge.luna deletes its Codex home after each call).
  --questions q.json   yes / no / unclear per question, plus what is seen and which picture/tile would settle it.
                       q.json: {"questions": [{"id", "text", "images": [paths] (default: the pictures given),
                       "fault_if": "yes"|"no", "part"?, "place"?}]}. Pictures go --per-call (6) per session, each
                       with the questions that name them. -> questions-result.json {answers[], summary: n, faults,
                       unclear, ok}. With --inspect inspect.json (+ --parts-json), a part whose joints were all
                       rendered (inspect coverage complete) and all answered without a fault or "unclear" gets
                       parts.json checks.inspect = true; a fault or "unclear" sets it false.
                       --repeat 2 asks every batch again in fresh sessions; a fault counts only when every run says
                       so, differing answers become "unclear" (seeded test 2026-10-13: one run 4-5 of 8 clean copies
                       flagged; the edge-on "gap" question asked twice: 3/8 caught, 0/8 false alarms).
  --versus BEST.jpg    "which is closer to the concept" (--concept pictures; without one: the better-made model),
                       asked in TWO separate sessions: (this round's first picture, BEST) and the mirror (BEST, this).
                       Both pick this round = win, both pick BEST = lose, anything else = tie. -> versus.json
  --fixes fixes.json   last round's named weaknesses ({"weaknesses": [{"id", "text"}]} or a list of strings), each
                       described as a thing seen, never as a fix. Luna gets two pictures as FIRST/SECOND (--before,
                       default the --versus picture, against this round's first picture) and says per point where
                       the problem shows MORE: FIRST / SECOND / SAME / NEITHER; again in two mirrored sessions.
                       Decoded per point: applied (less now in both), made worse (more now in both), not applied
                       (same in both), not seen (NEITHER in both: no evidence), unclear (the sessions disagree).
                       -> fixes-result.json
  round.json in <out-dir> sums it up for rounds.py (level, versus, fixes, questions).
  --out-dir DIR        where the check results go (default assets-lib/_luna-review/<key>/)
  --dry-run            write every prompt and image list to <out-dir>/calls/ and call nobody
--make-questions writes 3 questions per inspect place (the two tinted parts meet along the whole joint: fault if no;
the orange part is lifted, tilted or sunk: fault if yes; the "as rendered" tile shows speckle, noise or fighting
patterns: fault if yes) and, from parts.json for --changed parts, one about the material source and one per night
state, at most --max-per-part (5) per part. Luna is never asked to measure.
Exit 0 reviewed, 1 the review failed, 2 usage.
"""
import json, os, re, shutil, struct, subprocess, sys, time

OPS = os.environ.get('ASSET_OPS', '<game>/ops')   # the project's ops tools (bridge pool, level review)
PROJECT = os.environ.get('ASSET_PROJECT', '<game>')
LIB_LINK = os.path.join(PROJECT, 'docs/assets-lib')
OUT = os.path.join(os.path.realpath(LIB_LINK), '_luna-review')
HERE = os.path.dirname(os.path.abspath(__file__))
JUDGE_DIR = os.path.join(PROJECT, 'docs/concepts/tools')
LOGINS = os.environ.get('CODEX_HOMES', os.path.expanduser('~/.codex')).split(':')   # Codex logins tried in turn


def glb_facts(path):
    """triangles, primitives, materials, textures, bytes and the world-space size [x, height, depth] of a .glb."""
    b = open(path, 'rb').read(); n = struct.unpack('<I', b[12:16])[0]; j = json.loads(b[20:20 + n])
    acc = j.get('accessors', []); meshes = j.get('meshes', []); nodes = j.get('nodes', [])
    import math
    def mat(nd):
        if 'matrix' in nd: m = nd['matrix']; return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
        t = nd.get('translation', [0, 0, 0]); q = nd.get('rotation', [0, 0, 0, 1]); s = nd.get('scale', [1, 1, 1]); x, y, z, w = q
        R = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
             [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
        return [[R[r][0] * s[0], R[r][1] * s[1], R[r][2] * s[2], t[r]] for r in range(3)] + [[0, 0, 0, 1]]
    mul = lambda A, B: [[sum(A[r][k] * B[k][c] for k in range(4)) for c in range(4)] for r in range(4)]
    lo, hi = [math.inf] * 3, [-math.inf] * 3; tris = prims = 0
    def walk(i, M, seen):
        nonlocal tris, prims
        nd = nodes[i]; M = mul(M, mat(nd))
        if 'mesh' in nd:
            for p in meshes[nd['mesh']]['primitives']:
                prims += 1
                cnt = acc[p['indices']]['count'] if 'indices' in p else acc[p['attributes']['POSITION']]['count']
                tris += cnt // 3 if p.get('mode', 4) == 4 else 0
                a = acc[p['attributes']['POSITION']]
                if 'min' in a:
                    for cx in (a['min'][0], a['max'][0]):
                        for cy in (a['min'][1], a['max'][1]):
                            for cz in (a['min'][2], a['max'][2]):
                                v = [M[r][0] * cx + M[r][1] * cy + M[r][2] * cz + M[r][3] for r in range(3)]
                                for k in range(3): lo[k] = min(lo[k], v[k]); hi[k] = max(hi[k], v[k])
        for c in nd.get('children', []):
            if c not in seen: walk(c, M, seen | {c})
    I = [[1 if r == c else 0 for c in range(4)] for r in range(4)]
    for r in j.get('scenes', [{}])[j.get('scene', 0)].get('nodes', []): walk(r, I, {r})
    size = [round(hi[k] - lo[k], 2) for k in range(3)] if lo[0] < math.inf else [0, 0, 0]
    return {'triangles': tris, 'draw_calls': prims, 'materials': len(j.get('materials', [])), 'textures': len(j.get('textures', [])),
            'bytes': os.path.getsize(path), 'size_m': size}


# ------------------------------------------------------------------------------------------------- one Luna session
def kyiv_iso():
    import datetime
    from zoneinfo import ZoneInfo
    return datetime.datetime.now(ZoneInfo('Europe/Kyiv')).isoformat(timespec='seconds')


def put_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def luna(tag, prompt, images, out_dir, effort='high', timeout=1200, dry=False, cwd=None):
    """images: [(neutral name, path)]. Returns the answer text or None. Keeps prompt/images/answer in out_dir/calls/."""
    cd = os.path.join(out_dir, 'calls'); os.makedirs(cd, exist_ok=True)
    open(os.path.join(cd, tag + '.prompt.txt'), 'w').write(prompt)
    put_json(os.path.join(cd, tag + '.images.json'), [{'name': n, 'path': os.path.abspath(p)} for n, p in images])
    if dry:
        print(f'  dry run: {tag}: {len(images)} pictures, prompt {len(prompt)} chars', flush=True)
        return None
    sys.path.insert(0, JUDGE_DIR)
    import judge
    tried = []
    for home in LOGINS:
        try:
            ok, why = judge.room(home)
        except Exception as ex:
            ok, why = False, repr(ex)[:120]
        if not ok:
            tried.append(f'{os.path.basename(home)}: {why}'); continue
        t0 = time.time()
        text, tail, err = judge.luna(prompt, images, home, model='gpt-6-luna', effort=effort, timeout=timeout,
                                     tag=tag, cwd=cwd or os.path.abspath(out_dir), arm='3d-review')   # writes the usage record
        u, _ = judge.usage_from_tail(tail); st = 'ok' if (text or '').strip() else ('error' if err else 'empty')
        print(f'  luna {tag}: {st} in {round(time.time() - t0)} s on {os.path.basename(home)}, '
              f'{int((u or {}).get("output_tokens") or 0)} out tokens', flush=True)
        if (text or '').strip():
            open(os.path.join(cd, tag + '.answer.txt'), 'w').write(text)
            return text
        tried.append(f'{os.path.basename(home)}: {err or "empty answer"}')
    print(f'  luna {tag}: no answer ({"; ".join(tried)[:300]})', flush=True)
    return None


# ------------------------------------------------------------------------------------------------------ questions
CLOSEUP_INTRO = """Each picture is one close-up sheet of one place on the model. On it, the two parts that meet at that
place are tinted ORANGE and BLUE, with shading that darkens creases; other nearby parts are see-through grey; the
model is cut away outside a box round the place, so cut faces at the frame border are not faults. Tiles: "view 1" to
"view 3" look at the place from different sides; "along the seam, low" looks along the joint from just above the
surface; "as rendered" shows the real materials and light from one side, untinted. Each tile shows its scale in
millimetres per pixel. The legend tile names the two parts."""

QUESTION_HEAD = """You are checking pictures of a 3D model made for a game. Answer each question from the pictures
alone. Answer "unclear" when the pictures do not show it well enough, and say which picture, tile or other view would
settle it. Do not guess what the model is meant to be beyond what the pictures show.

{intro}

Pictures: {pictures}.

Questions:
{questions}

Answer with exactly one line per question and nothing else, in this form:
<id> | yes / no / unclear | what you see (at most 25 words) | the picture and tile that shows it, or would settle it
"""


def parse_answers(text, ids):
    out = {}
    for line in (text or '').splitlines():
        m = re.match(r'^\W*([A-Za-z]\w*)\W*\|\s*\**(yes|no|unclear)\**\s*\|([^|]*)\|?(.*)$', line.strip(), re.I)
        if m and m.group(1) in ids:
            out[m.group(1)] = dict(answer=m.group(2).lower(), seen=m.group(3).strip(), settle=m.group(4).strip())
    return out


def run_questions(o, pics, out_dir):
    Q = json.load(open(o['questions']))
    qs = Q.get('questions', Q) if isinstance(Q, dict) else Q
    intro = Q.get('intro') if isinstance(Q, dict) and Q.get('intro') else (CLOSEUP_INTRO if any(q.get('images') for q in qs) else
            'The pictures are review renders of the whole model from several sides and in several light states.')
    for q in qs:
        q['images'] = [os.path.abspath(p) for p in (q.get('images') or pics)]
    order = []
    for q in qs:
        for p in q['images']:
            if p not in order:
                order.append(p)
    per = int(o.get('per-call', 6))
    groups, cur = [], []
    for p in order:   # pictures in batches; a question goes with the batch holding all its pictures
        cur.append(p)
        if len(cur) == per:
            groups.append(cur); cur = []
    if cur:
        groups.append(cur)
    reps = max(1, int(o.get('repeat', 1)))
    runs = []
    for rep in range(1, reps + 1):   # --repeat N: the same calls again in fresh sessions; a fault needs every run
        answers = {}
        for gi, g in enumerate(groups, 1):
            names = {p: f'picture-{k}.jpg' for k, p in enumerate(g, 1)}
            mine = [q for q in qs if all(p in g for p in q['images']) and q['id'] not in answers]
            if not mine:
                continue
            lines = []
            for q in mine:
                where = ', '.join(names[p] for p in q['images']) if q.get('images') and len(g) > 1 else ''
                lines.append(f"{q['id']}" + (f' ({where})' if where else '') + f": {q['text']}")
            prompt = QUESTION_HEAD.format(intro=intro, pictures=', '.join(names[p] for p in g), questions='\n'.join(lines))
            tag = f'questions-{gi}' + (f'-r{rep}' if reps > 1 else '')
            text = luna(tag, prompt, [(names[p], p) for p in g], out_dir, o.get('effort', 'high'), dry=o.get('dry-run'))
            got = parse_answers(text, {q['id'] for q in mine})
            for q in mine:
                a = got.get(q['id'], dict(answer='unclear', seen='(no parsable answer)', settle=''))
                answers[q['id']] = dict(q, **a, call=tag, fault=a['answer'] == q.get('fault_if', 'no'))
        runs.append(answers)
    answers = runs[0]
    if reps > 1:   # 2026-10-13 seeded test: "gap" asked twice, fault only when both say so: 3/8 caught, 0/8 false alarms
        for qid in list(answers):
            rs = [r[qid] for r in runs if qid in r]
            same = len({r['answer'] for r in rs}) == 1
            answers[qid] = dict(rs[0], answer=rs[0]['answer'] if same else 'unclear', fault=all(r['fault'] for r in rs),
                                runs=[dict(answer=r['answer'], seen=r['seen'], call=r['call']) for r in rs],
                                seen=rs[0]['seen'] if same else ' / '.join(r['seen'] for r in rs)[:400])
    res = [answers.get(q['id'], dict(q, answer='unclear', seen='(not asked: pictures exceed one batch)', settle='', fault=False)) for q in qs]
    summ = dict(n=len(res), faults=sum(1 for r in res if r['fault']), unclear=sum(1 for r in res if r['answer'] == 'unclear'),
                ok=sum(1 for r in res if not r['fault'] and r['answer'] != 'unclear'), calls=len(groups) * reps, repeat=reps)
    put_json(os.path.join(out_dir, 'questions-result.json'), dict(when=kyiv_iso(), summary=summ, answers=res))
    for r in res:
        print(f"  {r['id']}: {r['answer']:<7} {'FAULT ' if r['fault'] else ''}{r.get('part') or ''} {r['seen'][:90]}", flush=True)
    print(f"QUESTIONS {summ['n']}: {summ['faults']} faults, {summ['unclear']} unclear, {summ['ok']} fine", flush=True)
    if o.get('inspect') and not o.get('dry-run'):
        flip_inspect(o, res)
    return summ


def flip_inspect(o, res):
    """parts.json checks.inspect: true when every joint of the part was rendered (coverage complete) and every
    question about its places was answered without a fault or 'unclear'; false otherwise."""
    J = json.load(open(o['inspect']))
    pp = o.get('parts-json') or J.get('parts_json')
    if not pp or not os.path.exists(pp):
        print('  checks.inspect: no parts.json; nothing flipped', flush=True); return
    by_place = {}
    for r in res:
        if r.get('place'):
            by_place.setdefault(r['place'], []).append(r)
    cov = J.get('coverage', {})
    verdict = {}
    for pl in J.get('places', []):
        for k, part in zip(pl.get('instances', []), pl.get('plan_parts') or [None, None]):
            name = part or re.sub(r'#\d+$', '', k)
            rs = by_place.get(pl['id'], [])
            good = bool(rs) and all(not r['fault'] and r['answer'] != 'unclear' for r in rs) and cov.get(k, {}).get('complete', False)
            verdict[name] = verdict.get(name, True) and good
    P = json.load(open(pp)); L = P.get('parts', P) if isinstance(P, dict) else P
    items = L.values() if isinstance(L, dict) else L
    n = 0
    for x in items:
        nm = x.get('part') or x.get('name') if isinstance(x, dict) else None
        if nm in verdict:
            x.setdefault('checks', {})['inspect'] = verdict[nm]; n += 1
            x.setdefault('evidence', {})['inspect'] = {'tool': 'luna_review.py --questions', 'at': kyiv_iso(), 'ok': bool(verdict[nm]),      # plan_check.py refuses a true flag without tool evidence
                                                      'file': os.path.abspath(o['inspect']), 'note': 'every joint rendered and every question answered without a fault or unclear'}
    put_json(pp, P)
    print(f'  checks.inspect set on {n} parts in {pp}: ' + ', '.join(f'{k}={v}' for k, v in sorted(verdict.items()))[:400], flush=True)


# The three close-up questions. v1 (2026-10-13 02:5x: "do they meet along the whole joint", "lifted, tilted or sunk",
# "speckle, noise, stripes, blotches ... in the as-rendered tile") did not separate faulted from clean on the seeded test
# (5 of 8 caught, 6 of 8 clean copies flagged): Luna read overlap in projection as contact, "sunk into" fired on
# designed embeds, and film textures (grain, grime) read as speckle. v2 points at the decisive tile and excludes texture.
QUESTIONS_V2 = [
    ('gap', 'In the tile "along the seam, low", does a strip of the pale background show between the orange part and '
            'the blue part, where they would otherwise touch?', 'yes'),
    ('touch', 'In views 1 to 3, wherever the orange part reaches the blue part, does it visibly touch it (no light '
              'line, no shadow gap, no pale background between them)?', 'no'),
    ('look', 'In the "as rendered" tile, leaving aside the material\'s own grain, grime or wear, is there a rendering '
             'defect: a speckle of mixed colours, a black or flat hole where a surface or picture should be, or a '
             'pattern broken into random stripes?', 'yes'),
]


def make_questions(a):
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a else d
    J = json.load(open(opt('--make-questions')))
    base = os.path.dirname(os.path.abspath(opt('--make-questions')))
    changed = [x for x in (opt('--changed') or '').split(',') if x]
    cap = int(opt('--max-per-part', 5))
    qs, per_part, k = [], {}, 0

    def add(part, text, fault_if, images, place=None, kind=None):
        nonlocal k
        if per_part.get(part, 0) >= cap:
            return
        k += 1; per_part[part] = per_part.get(part, 0) + 1
        qs.append(dict(id=f'q{k:02d}', part=part, place=place, kind=kind, text=text, fault_if=fault_if, images=images))
    for pl in J.get('places', []):
        img = [os.path.join(base, pl['image'])]
        part = pl['parts'][0]
        for kind, text, fi in QUESTIONS_V2:
            add(part, text, fi, img, pl['id'], kind)
    pj = opt('--parts-json') or J.get('parts_json')
    if pj and os.path.exists(pj):
        P = json.load(open(pj)); L = P.get('parts', P) if isinstance(P, dict) else P
        items = [dict(v, part=kk) for kk, v in L.items()] if isinstance(L, dict) else L
        for x in items:
            nm = x.get('part') or x.get('name')
            if changed and nm not in changed:
                continue
            m = x.get('material') or {}
            if isinstance(m, dict) and m.get('ref'):
                add(nm, f'Does the {nm.replace(".", " ").replace("_", " ")} read as {m["ref"].lower()}'
                        + (f' ({m["rough_src"].split(":", 1)[-1].strip()})' if m.get('rough_src') else '') + '?', 'no', [], None, 'material')
            for st in x.get('states') or []:
                if isinstance(st, str) and ':' in st and st.split(':')[0].strip() in ('night', 'dusk', 'rain'):
                    s0, s1 = st.split(':', 1)
                    add(nm, f'In the {s0.strip()} pictures, does the {nm.replace(".", " ").replace("_", " ")} show this: {s1.strip()}?',
                        'no', [], None, s0.strip())
    out = dict(made=kyiv_iso(), source=os.path.abspath(opt('--make-questions')), questions=qs)
    if opt('--concept-notes'):
        out['concept_notes'] = opt('--concept-notes')
    put_json(opt('--out', 'q.json'), out)
    print(f"{len(qs)} questions for {len(per_part)} parts -> {opt('--out', 'q.json')}")
    return 0


# ---------------------------------------------------------------------------------------------- versus and fixes
VERSUS_HEAD = """You compare two pictures of a 3D model made for a game, called FIRST and SECOND.{concept}
Which of the two {crit}? If they are equally {short}, say EQUAL. Do not prefer a picture for its position.
Answer with exactly two lines:
FIRST or SECOND or EQUAL
why, in at most 40 words, naming what differs
"""


def pick(text):
    m = re.search(r'\b(FIRST|SECOND|EQUAL)\b', (text or '').upper())
    return m.group(1) if m else None


def run_versus(o, pics, concepts, out_dir):
    best = os.path.abspath(o['versus']); cur = os.path.abspath(pics[0])
    if concepts:
        cpt = ' The concept art it was made from comes first (' + ', '.join(f'concept-{i}.jpg' for i in range(1, len(concepts) + 1)) + ').'
        crit, short = 'is closer to the concept', 'close'
    else:
        cpt, crit, short = '', 'shows the better-made model of the same object (form, proportion, construction, materials)', 'good'
    cimg = [(f'concept-{i}.jpg', p) for i, p in enumerate(concepts, 1)]
    calls = {}
    for tag, first, second in (('versus-ab', cur, best), ('versus-ba', best, cur)):
        text = luna(tag, VERSUS_HEAD.format(concept=cpt, crit=crit, short=short),
                    cimg + [('first.jpg', first), ('second.jpg', second)], out_dir, o.get('effort', 'high'), dry=o.get('dry-run'))
        c = pick(text)
        calls[tag] = dict(choice=c, why=' '.join((text or '').strip().splitlines()[1:2]), current=('FIRST' if first == cur else 'SECOND'))
    votes = []
    for v in calls.values():
        votes.append('current' if v['choice'] == v['current'] else 'tie' if v['choice'] in ('EQUAL', None) else 'best')
    res = 'win' if votes == ['current', 'current'] else 'lose' if votes == ['best', 'best'] else 'tie'
    put_json(os.path.join(out_dir, 'versus.json'), dict(when=kyiv_iso(), current=cur, best=best, concepts=concepts,
                                                         calls=calls, votes=votes, result=res))
    print(f'VERSUS {res}  (votes {votes[0]} / {votes[1]})', flush=True)
    return res


FIXES_HEAD = """You compare two pictures of a 3D model made for a game, called FIRST and SECOND. Below are points, each
describing a problem that may show in either picture. For each point, say in which picture the problem shows MORE:
FIRST, SECOND, SAME (it shows equally in both), or NEITHER (it shows in neither). Judge only what the pictures show.

Points:
{points}

Answer with exactly one line per point and nothing else:
<id> | FIRST / SECOND / SAME / NEITHER | what you see (at most 25 words)
"""


def run_fixes(o, pics, out_dir):
    F = json.load(open(o['fixes']))
    W = F.get('weaknesses', F) if isinstance(F, dict) else F
    W = [dict(id=f'w{i}', text=w) if isinstance(w, str) else dict(w, id=w.get('id') or f'w{i}') for i, w in enumerate(W, 1)]
    before = os.path.abspath(o.get('before') or o.get('versus') or '')
    if not os.path.isfile(before):
        print('--fixes needs --before PICTURE (or --versus)'); return None
    cur = os.path.abspath(pics[0])
    pts = '\n'.join(f"{w['id']}: {w['text']}" for w in W)
    per = {}
    for tag, first, second in (('fixes-ab', before, cur), ('fixes-ba', cur, before)):
        text = luna(tag, FIXES_HEAD.format(points=pts), [('first.jpg', first), ('second.jpg', second)], out_dir,
                    o.get('effort', 'high'), dry=o.get('dry-run'))
        for line in (text or '').splitlines():
            m = re.match(r'^\W*(\w+)\W*\|\s*\**(FIRST|SECOND|SAME|NEITHER)\**\s*\|?(.*)$', line.strip(), re.I)
            if m:
                lab = m.group(2).upper()
                if lab in ('FIRST', 'SECOND'):
                    reads = 'more before' if (first if lab == 'FIRST' else second) == before else 'more now'
                else:
                    reads = lab.lower()   # same / neither
                per.setdefault(m.group(1), {})[tag] = dict(label=lab, reads=reads, seen=m.group(3).strip())
    out = []
    for w in W:
        r = per.get(w['id'], {})
        reads = [r.get(t, {}).get('reads') for t in ('fixes-ab', 'fixes-ba')]
        if reads[0] == reads[1] == 'more before':
            v = 'applied'
        elif reads[0] == reads[1] == 'neither':
            v = 'not seen'   # in neither picture: no evidence either way (2026-10-13: 6 of 8 sheet-size points)
        elif reads[0] == reads[1] == 'more now':
            v = 'made worse'
        elif reads[0] == reads[1] == 'same':
            v = 'not applied'
        else:
            v = 'unclear'
        out.append(dict(w, verdict=v, calls=r))
        print(f"  {w['id']}: {v:<12} {w['text'][:80]}", flush=True)
    summ = {k: sum(1 for x in out if x['verdict'] == k) for k in ('applied', 'not applied', 'made worse', 'unclear', 'not seen')}
    put_json(os.path.join(out_dir, 'fixes-result.json'), dict(when=kyiv_iso(), before=before, current=cur, summary=summ, points=out))
    print('FIXES ' + ', '.join(f'{k} {v}' for k, v in summ.items()), flush=True)
    return summ


# ----------------------------------------------------------------------------------------------------------- main
def main(a):
    if a and a[0] == '--make-questions':
        return make_questions(a)
    if len(a) < 3 or a[0] in ('-h', '--help'):
        print(__doc__); return 0 if a and a[0] in ('-h', '--help') else 2
    key, desc, rest = a[0], a[1], a[2:]
    if not re.fullmatch(r'[A-Za-z0-9._-]+', key): print('key: letters, digits, . _ - only'); return 2
    pics, concepts, o, i = [], [], {}, 0
    flags = {'--run', '--glb', '--concept', '--family', '--form', '--size', '--tris', '--draws', '--materials', '--textures', '--bytes',
             '--questions', '--versus', '--fixes', '--before', '--out-dir', '--effort', '--per-call', '--inspect', '--parts-json',
             '--repeat'}
    bools = {'--redo', '--no-level', '--dry-run'}
    while i < len(rest):
        x = rest[i]
        if x in bools: o[x[2:]] = True; i += 1
        elif x in flags:
            if i + 1 >= len(rest): print(f'{x} needs a value'); return 2
            if x == '--concept': concepts.append(rest[i + 1])
            else: o[x[2:]] = rest[i + 1]
            i += 2
        elif x.startswith('--'): print(f'unknown option {x}'); return 2
        else: pics.append(x); i += 1
    if not pics: print('give at least one picture'); return 2
    for p in pics + concepts + [o[k] for k in ('questions', 'versus', 'fixes', 'before', 'inspect') if k in o]:
        if not os.path.isfile(p): print(f'no such file {p}'); return 2
    if o.get('effort') and o['effort'] not in ('low', 'medium', 'high', 'xhigh', 'max'): print('--effort low|medium|high|xhigh|max'); return 2
    rc = 0
    if any(k in o for k in ('questions', 'versus', 'fixes')):
        out_dir = os.path.abspath(o.get('out-dir') or os.path.join(OUT, key)); os.makedirs(out_dir, exist_ok=True)
        summ = dict(key=key, when=kyiv_iso(), pictures=[os.path.abspath(p) for p in pics])
        if 'questions' in o: summ['questions'] = run_questions(o, pics, out_dir)
        if 'versus' in o: summ['versus'] = run_versus(o, pics, [os.path.abspath(c) for c in concepts], out_dir)
        if 'fixes' in o: summ['fixes'] = run_fixes(o, pics, out_dir)
        prev = {}
        try: prev = json.load(open(os.path.join(out_dir, 'round.json')))
        except Exception: pass
        put_json(os.path.join(out_dir, 'round.json'), dict(prev, **summ))
        print(f'checks -> {out_dir}/round.json', flush=True)
        if o.get('run') and not o.get('dry-run'):
            msg = '; '.join(f'{k} {v}' for k, v in (('questions', summ.get('questions')), ('versus', summ.get('versus')),
                                                    ('fixes', summ.get('fixes'))) if v is not None)
            subprocess.run([sys.executable, os.path.join(HERE, 'report.py'), o['run'], 'review', f'Luna checks on {key}: {msg}'[:300], '--asset', key])
        if o.get('no-level'):
            return 0
    from PIL import Image
    d = os.path.join(OUT, key)
    if os.path.exists(os.path.join(d, 'REVIEW.md')) and not o.get('redo'):
        print(f'{d}/REVIEW.md exists: use a new key per round, or --redo'); return 2
    os.makedirs(os.path.join(d, 'views'), exist_ok=True)
    facts = {'triangles': 0, 'draw_calls': 0, 'materials': 0, 'textures': 0, 'bytes': 0, 'size_m': [0, 0, 0]}
    if o.get('glb'): facts.update(glb_facts(o['glb'])); facts['glb'] = os.path.abspath(o['glb'])
    for k, f in (('tris', 'triangles'), ('draws', 'draw_calls'), ('materials', 'materials'), ('textures', 'textures'), ('bytes', 'bytes')):
        if k in o: facts[f] = int(o[k])
    if 'size' in o: facts['size_m'] = [float(v) for v in o['size'].split(',')]
    views, used = [], set()
    for p in pics:
        n = re.sub(r'[^A-Za-z0-9_-]+', '-', os.path.splitext(os.path.basename(p))[0]).strip('-') or 'view'
        base, k = n, 2
        while n in used: n = f'{base}-{k}'; k += 1
        used.add(n)
        im = Image.open(p).convert('RGB'); im.thumbnail((1280, 720)); im.save(os.path.join(d, 'views', n + '.jpg'), quality=92)
        views.append({'name': n, 'w': im.width, 'h': im.height})
    cl = []
    if concepts:
        os.makedirs(os.path.join(d, 'concepts'), exist_ok=True)
        for k, p in enumerate(concepts, 1):
            dst = os.path.join(d, 'concepts', f'concept-{k}.jpg'); Image.open(p).convert('RGB').save(dst, quality=92)
            cl.append(os.path.relpath(os.path.join(LIB_LINK, '_luna-review', key, 'concepts', f'concept-{k}.jpg'), PROJECT))
    facts.update(family=o.get('family', key.split('-')[0]), form=o.get('form', key), title=desc, concepts=cl, views=views)
    json.dump(facts, open(os.path.join(d, 'facts.json'), 'w'), indent=1)
    try: os.remove(os.path.join(d, 'facts.kept.json'))
    except OSError: pass
    print(f'packet {d}: {len(views)} views, {len(cl)} concepts, {facts["triangles"]} tris, {facts["draw_calls"]} draws', flush=True)
    cmd = [sys.executable, os.path.join(OPS, 'luna_assets.py'), 'run', '--only', key, '--jobs', '1'] + (['--redo'] if o.get('redo') else [])
    r = subprocess.run(cmd, capture_output=True, text=True)
    print((r.stdout + r.stderr).strip()[-1500:], flush=True)
    rj = os.path.join(d, 'review.json'); rv = os.path.join(d, 'REVIEW.md')
    ok = os.path.exists(rv) and os.path.exists(rj) and os.path.getmtime(rj) >= os.path.getmtime(os.path.join(d, 'facts.json'))
    if not ok:
        os.replace(os.path.join(d, 'facts.json'), os.path.join(d, 'facts.kept.json'))
        err = ''
        try: err = json.load(open(os.path.join(d, 'review-error.json'))).get('error', '')
        except Exception: pass
        print(f'REVIEW FAILED {key}: {err[:400]}')
        if o.get('run'):
            subprocess.run([sys.executable, os.path.join(HERE, 'report.py'), o['run'], 'blocked', f'Luna review of {key} failed: {err[:160]}', '--asset', key])
        return 1
    j = json.load(open(rj)); lvl = j.get('level')
    print(f'LEVEL {lvl}\nverdict {j.get("verdict")}\nreview {rv}')
    if any(k in o for k in ('questions', 'versus', 'fixes')):
        rp = os.path.join(os.path.abspath(o.get('out-dir') or d), 'round.json')
        try:
            R = json.load(open(rp)); R['level'] = lvl; put_json(rp, R)
        except Exception:
            pass
    if o.get('run'):
        args = [sys.executable, os.path.join(HERE, 'report.py'), o['run'], 'review',
                f'Luna (gpt-6-luna max) on {key}: level {lvl}; {(j.get("verdict") or "")[:160]}', '--asset', key,
                '--picture', os.path.join(d, 'views', views[0]['name'] + '.jpg')]
        if lvl is not None: args += ['--luna', str(lvl)]
        subprocess.run(args)
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
