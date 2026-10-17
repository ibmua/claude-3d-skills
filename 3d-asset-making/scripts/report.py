#!/usr/bin/env python3
"""Report one event of an asset run to its progress log (owner 2026-10-12 22:47: "report as progress goes to some
dashboard so I can see api use, progress, etc."). The dashboard's Runs view (http://127.0.0.1:8152/#/runs) reads
<run folder>/progress.jsonl; the API cost it shows comes from the run's transcripts, not from here.

  report.py <run folder> <kind> "<one sentence>" [--asset KEY] [--picture PATH] [--stage A|B|C] [--round N]
            [--luna N] [--builder NAME] [--data JSON]

kind: start | plan | search | decision | component | assembly | round | review | export | thumbnail | blocked | done
      (anything else is refused, so the page can rely on it)
--picture: a file on disk (absolute, or relative to the run folder); the page shows it.
--data:    a JSON object of numbers the page may show (tris, draws, components, images …).
Appends one JSON line {ts, kind, msg, …} with an exclusive lock; never rewrites earlier lines. Prints the line.
"""
import datetime, fcntl, json, os, sys

KINDS = {'start', 'plan', 'search', 'decision', 'component', 'assembly', 'round', 'review', 'export', 'thumbnail',
         'blocked', 'done'}


def main(a):
    if len(a) < 3 or a[0] in ('-h', '--help'):
        print(__doc__); return 0 if a and a[0] in ('-h', '--help') else 2
    run, kind, msg, rest = os.path.abspath(a[0]), a[1], a[2], a[3:]
    if kind not in KINDS:
        print(f'unknown kind {kind!r}; one of: {", ".join(sorted(KINDS))}'); return 2
    if not os.path.isdir(run):
        print(f'no run folder {run}'); return 2
    ev = {'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'), 'kind': kind, 'msg': msg}
    opts = {'--asset': 'asset', '--picture': 'picture', '--stage': 'stage', '--round': 'round', '--luna': 'luna',
            '--builder': 'builder', '--data': 'data'}
    i = 0
    while i < len(rest):
        k = rest[i]
        if k not in opts or i + 1 >= len(rest):
            print(f'bad option {k}'); return 2
        v = rest[i + 1]; key = opts[k]
        if key in ('round',): v = int(v)
        elif key == 'luna': v = float(v)
        elif key == 'data':
            v = json.loads(v)
            if not isinstance(v, dict): print('--data must be a JSON object'); return 2
        elif key == 'picture':
            v = v if os.path.isabs(v) else os.path.join(run, v)
            if not os.path.exists(v): print(f'warning: picture not found yet: {v}')
        ev[key] = v; i += 2
    if os.environ.get('ASSET_BUILDER') and 'builder' not in ev: ev['builder'] = os.environ['ASSET_BUILDER']
    line = json.dumps(ev, ensure_ascii=False)
    with open(os.path.join(run, 'progress.jsonl'), 'a') as f:
        fcntl.flock(f, fcntl.LOCK_EX); f.write(line + '\n'); f.flush(); fcntl.flock(f, fcntl.LOCK_UN)
    print(line); return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
