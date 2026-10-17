#!/usr/bin/env python3
"""rounds.py: keep the best round, revert the rest, cap the rounds (R6 of the 2026-10-13 agent research: gains come in
the first 2-4 rounds, later rounds can be worse, and without revert a loop drifts: BlenderAlchemy 25.8 vs 28.2).

  rounds.py save <asset dir> <n> <work.blend> [--stage NAME]
        copy the work file to <asset dir>/rounds/ROUND-<n>.blend (whole file or nothing) and record it
  rounds.py decide <asset dir> <n> --gate pass|fail|<render.py round log> [--luna DIR] [--stage NAME] [--cap 4]
        [--level-target 7] [--questions-gate] [--finding "<named finding>"] [--run <run folder>]
        decide round n: prints one of
          KEEP n          new best (first passing round; or checks pass and versus win; or a tie with every named
                          fix applied)
          REVERT to m     checks fail, or versus lose, or a tie without the named fixes all applied: copy
                          rounds/ROUND-<m>.blend back (`rounds.py revert`) and try a DIFFERENT fix
          FIX CHECKS      no best yet and this round's checks fail
        then STOP when the stage has used --cap rounds (default 4) unless --finding names what the next round fixes,
        or when the best round's LEVEL reached --level-target.
  rounds.py revert <asset dir> <work.blend>    copy ROUND-<best>.blend over the work file (the work file is first kept
        as <work>.reverted-<time>.blend)
  rounds.py status <asset dir>

Inputs. --gate: `pass`/`fail`, or the log of `render.py round` (RT_FAIL / STRICT FAIL = fail) or a kit3d check json
({"result": ...} or {"failures"/"places": [...]} non-empty = fail). --luna DIR: the --out-dir of luna_review.py, whose
round.json holds level, versus (win/tie/lose), fixes {applied, not applied, made worse, unclear} and questions
{faults, unclear}. Question faults are advisory (printed, kept in the state) unless --questions-gate makes them fail
the checks: Luna's yes/no answers are a second look, not a measurement (2026-10-13 seeded test, 3d-asset-making
CHANGELOG: one run flagged 4-5 of 8 clean copies; only `luna_review.py --repeat 2` on the edge-on gap question was clean).
State: <asset dir>/rounds/rounds.json {stage, best, rounds: {n: {blend, gate, versus, fixes, questions, level,
decision, why, at}}}. With --run, a `round` event goes to the run's progress log (report.py).
Exit 0 KEEP, 3 REVERT or FIX CHECKS, 2 usage or a KEEP whose ROUND-<n>.blend was never saved.
"""
import datetime, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def state_path(d):
    return os.path.join(os.path.abspath(d), 'rounds', 'rounds.json')


def load(d):
    try:
        return json.load(open(state_path(d)))
    except FileNotFoundError:
        return {'stage': None, 'best': None, 'rounds': {}}


def save_state(d, S):
    p = state_path(d); os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'; json.dump(S, open(tmp, 'w'), indent=1); os.replace(tmp, p)


def copy_atomic(src, dst):
    tmp = dst + '.tmp'; shutil.copyfile(src, tmp); os.replace(tmp, dst)


def gate_of(g):
    if g in ('pass', 'fail'):
        return g == 'pass', g
    if not os.path.isfile(g):
        raise SystemExit(f'--gate: pass, fail or a file; no such file {g}')
    txt = open(g, errors='replace').read()
    if g.endswith('.json'):
        try:
            J = json.loads(txt)
            res = str(J.get('result', ''))
            bad = res.upper().startswith(('FAIL', 'FAULT')) or bool(J.get('failures')) or (bool(J.get('places')) and 'result' not in J)
            return not bad, f'{os.path.basename(g)}: {res or ("%d places" % len(J.get("places", J.get("failures", []))))}'
        except Exception:
            pass
    bad = 'RT_FAIL' in txt or 'STRICT FAIL' in txt
    line = next((l for l in txt.splitlines() if 'RT_FAIL' in l or 'STRICT FAIL' in l), 'no RT_FAIL / STRICT FAIL')
    return not bad, f'{os.path.basename(g)}: {line.strip()[:160]}'


def main(a):
    if not a or a[0] in ('-h', '--help'):
        print(__doc__); return 0 if a else 2
    cmd = a[0]
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a else d
    if cmd == 'status' and len(a) >= 2:
        S = load(a[1]); print(json.dumps(S, indent=1)); return 0
    if cmd == 'save' and len(a) >= 4:
        d, n, work = a[1], int(a[2]), a[3]
        S = load(d); dst = os.path.join(os.path.abspath(d), 'rounds', f'ROUND-{n}.blend')
        os.makedirs(os.path.dirname(dst), exist_ok=True); copy_atomic(work, dst)
        stage = opt('--stage', S.get('stage') or 'A')
        if S.get('stage') != stage:
            S['stage'] = stage
        S['rounds'].setdefault(str(n), {}).update(blend=dst, stage=stage, saved=now())
        save_state(d, S); print(f'saved {dst}'); return 0
    if cmd == 'revert' and len(a) >= 3:
        d, work = a[1], a[2]
        S = load(d)
        if S.get('best') is None:
            print('no best round yet: nothing to revert to'); return 3
        src = S['rounds'][str(S['best'])]['blend']
        keep = os.path.splitext(work)[0] + '.reverted-' + datetime.datetime.now().strftime('%H%M%S') + '.blend'
        if os.path.exists(work):
            shutil.copyfile(work, keep)
        copy_atomic(src, work)
        print(f'REVERTED {work} <- {src} (the reverted work is kept as {keep})'); return 0
    if cmd != 'decide' or len(a) < 3 or not opt('--gate'):
        print(__doc__); return 2
    d, n = a[1], int(a[2])
    S = load(d); r = S['rounds'].setdefault(str(n), {})
    stage = opt('--stage', r.get('stage') or S.get('stage') or 'A')
    ok, gate_why = gate_of(opt('--gate'))
    L = {}
    if opt('--luna'):
        try:
            L = json.load(open(os.path.join(opt('--luna'), 'round.json')))
        except Exception as ex:
            print(f'--luna: no round.json in {opt("--luna")} ({ex})'); return 2
    q = L.get('questions') or {}
    if q and q.get('faults'):
        if '--questions-gate' in a:
            ok = False; gate_why += f'; Luna answered {q["faults"]} close-up question(s) with a fault'
        else:
            print(f'  advisory: Luna answered {q["faults"]} close-up question(s) with a fault (questions-result.json); '
                  'look at those close-ups and the measured stand-offs in inspect.json')
    vs, fx = L.get('versus'), L.get('fixes') or {}
    fixes_applied = bool(fx) and fx.get('applied', 0) > 0 and not any(fx.get(k) for k in ('not applied', 'made worse', 'unclear', 'not seen'))
    best = S.get('best')
    if best is None:
        dec, why = ('KEEP', 'first round whose checks pass') if ok else ('FIX CHECKS', 'no best yet; checks fail: ' + gate_why)
    elif not ok:
        dec, why = f'REVERT to {best}', 'checks fail: ' + gate_why
    elif vs == 'win':
        dec, why = 'KEEP', f'checks pass and it wins against ROUND-{best} in both orders'
    elif vs == 'tie' and fixes_applied:
        dec, why = 'KEEP', f'checks pass, ties with ROUND-{best}, every named fix applied ({fx})'
    elif vs is None:
        dec, why = f'REVERT to {best}', 'no versus result: run luna_review.py --versus ROUND-%s.jpg' % best
    else:
        dec, why = f'REVERT to {best}', f'versus {vs}' + (f', fixes {fx}' if fx else ', no named fixes checked')
    blend = r.get('blend') or os.path.join(os.path.abspath(d), 'rounds', f'ROUND-{n}.blend')
    if dec == 'KEEP' and not os.path.exists(blend):   # a best that cannot be restored is no best
        print(f'KEEP refused: {blend} is missing; run `rounds.py save {d} {n} <work.blend>` first, then decide again')
        return 2
    r.update(stage=stage, gate=dict(ok=ok, why=gate_why), versus=vs, fixes=fx or None, questions=q or None,
             level=L.get('level'), decision=dec, why=why, at=now())
    if dec == 'KEEP':
        S['best'] = n; r.setdefault('blend', os.path.join(os.path.abspath(d), 'rounds', f'ROUND-{n}.blend'))
    S['stage'] = stage
    save_state(d, S)
    print(f'{dec}  ({why})')
    used = sum(1 for x in S['rounds'].values() if x.get('stage') == stage and x.get('decision'))
    cap = int(opt('--cap', 4)); lvl_t = float(opt('--level-target', 7))
    blv = S['rounds'].get(str(S['best']), {}).get('level') if S.get('best') is not None else None
    if blv is not None and float(blv) >= lvl_t:
        print(f'STOP: the best round (ROUND-{S["best"]}) reached LEVEL {blv} >= {lvl_t}')
    elif used >= cap and not opt('--finding'):
        print(f'STOP: stage {stage} used {used} of {cap} rounds; a further round needs --finding "<what it fixes>"')
    elif opt('--finding'):
        r['finding'] = opt('--finding'); save_state(d, S)
    if opt('--run'):
        subprocess.run([sys.executable, os.path.join(HERE, 'report.py'), opt('--run'), 'round',
                        f'round {n}: {dec} ({why})'[:300], '--round', str(n)] + (['--luna', str(L['level'])] if L.get('level') is not None else []))
    return 0 if dec == 'KEEP' else 3


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
