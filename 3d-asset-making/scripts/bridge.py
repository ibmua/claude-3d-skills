#!/usr/bin/env python3
"""bridge.py: run a Blender Python file on a Blender MCP bridge, and claim / release a bridge for one builder.
Runs on the build box (the bridges are the build box's systemd user units blender-mcp-bridge@<port>, 127.0.0.1 only).

  python3 bridge.py <port> <script.py> [--timeout 590]   run the file inside that Blender; prints the result as JSON
  python3 bridge.py claim <task> <run folder>            get a bridge of our own (prints {"port": N, "mcp": ...})
  python3 bridge.py release <task> <run folder>          stop it and give the port back
  python3 bridge.py step <port> <part_script.py> --part NAME [--thumb] [--plan parts.json] [--run DIR] [--lod L]
                                                         one build step in <= 8 lines (below)
  python3 bridge.py <port> <script.py> --detach [--name N] [--dir D]   the same run in the background (a .done file)
  python3 bridge.py detach <name> [--dir D] [--nice 10] [--mem 12G] -- <command ...>   any long job (round,
                                                         lods_all, Luna, sweep) in the background: returns at once,
                                                         D/<name>.log, D/<name>.done (JSON: exit, seconds, last lines);
                                                         runs in `systemd-run --user --scope MemoryMax=<mem>
                                                         MemorySwapMax=0`, nice 10, a blender command gets -t 8
  python3 bridge.py wait <D/name.done|name> [--dir D] [--max 110]   block up to --max s (default 110: under the 120 s
                                                         a tool call gets by default; with a longer call timeout up
                                                         to 230, under the 5-minute cache), print the .done summary
                                                         or "still running" (exit 4: call it again)"

run: the script runs in the bridge's Blender (bpy available) through bridge_call.py's wire format.
     It should set `result = {...}` (JSON-able); if it does not, the wrapper sets result = {"ok": True, "vars": [names]}.
     A raised exception comes back as {"error": "...", "traceback": "..."}. Exit 0 ok, 1 error (Blender raised, the
     bridge refused, or no bridge listens on the port), 2 usage.
claim: opus_dispatch.blender_bridge(task, run): takes a free port of the project's pool (9901-9909, 10901-10920) by an
     exclusive claim file ~/.config/blender-mcp-bridge/<port>.env (MV_CKPT_DIR=<run>/blender, where the bridge saves
     the scene), writes <run>/blender-port and <run>/mcp.json (for `claude --mcp-config`), starts the unit. Claiming
     again with the same run folder returns the same port. Each builder of a run that draws in parallel needs its own
     run folder (e.g. <run>/builders/<name>), since the port file lives in the folder.
release: opus_dispatch.blender_bridge_stop(task, run) stops the unit (the scene is on disk in <run>/blender); then,
     unlike the dispatcher, this also removes the claim file (only if it still points at this run) and <run>/blender-port,
     so the port returns to the pool. Claim again later with the same folder: a new port reopens the saved scene.
step: runs the part script in the bridge's live Blender between kit3d.step_begin(part) and kit3d.step_end(): the
     dependents of anything the script changed are re-attached (kit3d.reattach), kit3d.check measures the touched parts
     (relations, unplaced, coplanar, back-to-back, UVs), the scene is saved as <run>/steps/<part>/<part>-vNNN.blend
     (a copy: the bridge's own checkpoint is untouched), --thumb renders <part>-vNNN.png (Workbench, ~0.5 s), the
     relations and the relations/uv flags go into parts.json (--plan, default <run>/parts.json if it exists), and
     report.py logs a `component` event. Prints <= 8 lines: verdict, failing places, paths. The check JSON
     (<part>-vNNN.check.json) lists every failing place (world xyz, the two parts, the measured mm) for
     render.py inspect. <run>: --run, else the claim file of the port (~/.config/blender-mcp-bridge/<port>.env).
     Exit 0 PASS, 3 check FAIL, 1 script error (prints where to look it up: never delete the failing line).
detach / wait: a long job never blocks the builder (95 % of wall time was idle waiting on Blender): start it detached,
     build the next part, then `wait` in slices (110 s by default, never over 230 s).
Never touches a port the run folder does not hold (10914/10915 hold a train car cab and a train car film-original
scenes of earlier runs; their claim files keep the pool off them).
"""
import contextlib, json, os, re, socket, subprocess, sys, time

OPS = os.environ.get('ASSET_OPS', '<game>/ops')   # the project's ops tools (bridge pool, level review)
BRIDGE_CALL = '<films>/blender/bridge_call.py'

WRAP = '''import traceback as _tb
_g = {"__name__": "__bridge_script__", "__file__": %(path)r}
try:
    exec(compile(%(src)r, %(path)r, "exec"), _g)
    result = _g.get("result")
    if not isinstance(result, dict):
        result = {"ok": True, "result": result} if result is not None else {"ok": True, "vars": sorted(k for k in _g if not k.startswith("_"))[:60]}
except BaseException as _e:
    result = {"error": repr(_e), "traceback": _tb.format_exc()[-4000:]}
'''


# A bridge starts as Blender does: Cube, Camera, Light. BUILDER.md says "start each component with an empty scene", and
# look.py / render.py measured that Cube (pilot-lamp 2026-10-13). claim() runs this once: ONLY an untouched start scene
# (unsaved file, exactly those three objects) is emptied; a reopened or already used scene is left as it is.
EMPTY_START = '''
import bpy
names = sorted(o.name for o in bpy.data.objects)
if not bpy.data.filepath and names == ['Camera', 'Cube', 'Light']:
    for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.cameras, bpy.data.lights, bpy.data.materials):
        for d in [d for d in coll if d.users == 0]: coll.remove(d)
    result = {'scene': 'emptied (Blender start objects removed)'}
else:
    result = {'scene': 'kept', 'objects': len(names), 'file': bpy.data.filepath}
'''


def call(port, code, timeout):
    """bridge_call.call when importable (same wire format: JSON + NUL), else an inline copy of it."""
    sys.path.insert(0, os.path.dirname(BRIDGE_CALL))
    try:
        from bridge_call import call as bc
        return bc(port, code, timeout=timeout)
    except ImportError:
        with socket.create_connection(('127.0.0.1', int(port)), timeout=timeout) as s:
            s.sendall((json.dumps({'type': 'execute', 'code': code, 'strict_json': True}) + '\0').encode())
            buf = bytearray()
            while b'\0' not in buf:
                chunk = s.recv(1 << 16)
                if not chunk: break
                buf.extend(chunk)
        return json.loads(bytes(buf).split(b'\0')[0] or b'{}')


def run(port, script, timeout):
    src = open(script).read()
    t0 = time.time()
    try:
        r = call(port, WRAP % {'src': src, 'path': os.path.abspath(script)}, timeout)
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        print(json.dumps({'error': f'bridge {port}: {e!r}'})); return 1
    # the bridge answers {"status": "success", "result": {...}} or {"status": "error", "message": ...}
    inner = r.get('result') if isinstance(r, dict) and 'result' in r else r
    if isinstance(inner, dict) and 'result' in inner and len(inner) <= 3 and isinstance(inner['result'], dict): inner = inner['result']
    print(json.dumps(inner, indent=1, ensure_ascii=False, default=str))
    print(f'({time.time() - t0:.1f} s on bridge {port})', file=sys.stderr)
    bad = (isinstance(r, dict) and r.get('status') == 'error') or (isinstance(inner, dict) and 'error' in inner)
    return 1 if bad else 0


def dispatch():
    sys.path.insert(0, OPS)
    import opus_dispatch
    return opus_dispatch


def claim(task, d):
    d = os.path.abspath(d); os.makedirs(d, exist_ok=True)
    with contextlib.redirect_stdout(sys.stderr):        # the dispatcher's log lines go to stderr; stdout stays JSON
        mcp = dispatch().blender_bridge(task, d)
    if not mcp:
        print(json.dumps({'error': 'no bridge (see the log line above)'})); return 1
    port = int(open(os.path.join(d, 'blender-port')).read().strip())
    for _ in range(90):                                  # the unit is up when its socket answers
        try:
            socket.create_connection(('127.0.0.1', port), timeout=2).close(); break
        except OSError: time.sleep(2)
    else:
        print(json.dumps({'error': f'bridge {port} started but does not listen after 180 s', 'port': port})); return 1
    scene = None
    try:                                                 # an untouched start scene is emptied (see EMPTY_START)
        r = call(port, EMPTY_START, 30); inner = r.get('result') if isinstance(r, dict) and 'result' in r else r
        if isinstance(inner, dict) and isinstance(inner.get('result'), dict): inner = inner['result']
        scene = inner.get('scene') if isinstance(inner, dict) else None
    except Exception as e:
        scene = f'not checked ({type(e).__name__})'
    print(json.dumps({'port': port, 'mcp': mcp, 'scene': scene, 'scene_dir': os.path.join(d, 'blender'),
                      'run': f'python3 {os.path.abspath(__file__)} {port} <script.py>'})); return 0


def release(task, d):
    d = os.path.abspath(d); pf = os.path.join(d, 'blender-port')
    if not os.path.exists(pf):
        print(json.dumps({'released': None, 'note': f'{pf} does not exist: this run holds no bridge'})); return 0
    port = open(pf).read().strip()
    od = dispatch()
    with contextlib.redirect_stdout(sys.stderr): od.blender_bridge_stop(task, d)
    claimf = os.path.join(od.BRIDGE_CFG, f'{port}.env'); freed = False
    try:
        if open(claimf).read().split('MV_CKPT_DIR=', 1)[1].strip() == os.path.join(d, 'blender'):
            os.remove(claimf); freed = True
    except (OSError, IndexError): pass
    os.remove(pf)
    active = subprocess.run(['systemctl', '--user', 'is-active', f'blender-mcp-bridge@{port}.service'], env=od.BUS,
                            capture_output=True, text=True).stdout.strip()
    print(json.dumps({'released': int(port), 'claim_removed': freed, 'unit': active, 'scene_dir': os.path.join(d, 'blender')}))
    return 0


# ------------------------------------------------------------------------------------------------ step (kit3d)
HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.normpath(os.path.join(HERE, '..', '..', '3d-modelling', 'scripts'))
PITFALLS = os.path.normpath(os.path.join(HERE, '..', '..', '3d-modelling', 'references', 'PITFALLS-blender-5.2.md'))
CFG = os.path.expanduser('~/.config/blender-mcp-bridge')

STEP = '''import sys, json, traceback as _tb
_K = %(kit)r
while _K in sys.path: sys.path.remove(_K)
sys.path.insert(0, _K)                     # the kit3d beside this bridge.py, whatever an earlier script put first
for _m in [m for m in list(sys.modules) if m == 'kit3d' or m.startswith('kit3d.')]: del sys.modules[_m]
import kit3d as _k3
_k3.step_begin(%(part)r, plan=%(plan)r, lod=%(lod)r)
_g = {"__name__": "__bridge_script__", "__file__": %(path)r}
try:
    exec(compile(%(src)r, %(path)r, "exec"), _g)
    _err = None
except BaseException as _e:
    _err = {"error": repr(_e)[:400], "traceback": _tb.format_exc()[-3000:]}
if _err:
    _k3.core.S()['step'] = None
    result = _err
else:
    try:
        result = _k3.step_end(save_dir=%(steps)r, thumb=%(thumb)r)
    except BaseException as _e:
        result = {"error": "kit3d.step_end: " + repr(_e)[:400], "traceback": _tb.format_exc()[-3000:]}
result = json.loads(json.dumps(result, default=str))
'''


def opt(a, name, default=None):
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else default


def run_dir_of(port, given=None, plan=None):
    if given: return os.path.abspath(given)
    try:
        ck = open(os.path.join(CFG, f'{port}.env')).read().split('MV_CKPT_DIR=', 1)[1].split()[0].strip()
        if ck.rstrip('/').endswith('/blender'): return os.path.dirname(ck.rstrip('/'))
    except (OSError, IndexError):
        pass
    return os.path.dirname(os.path.abspath(plan)) if plan else None


def step(port, script, a):
    part = opt(a, '--part')
    if not part: print('step: --part NAME is required'); return 2
    plan = opt(a, '--plan'); run_ = run_dir_of(port, opt(a, '--run'), plan)
    if not run_: print(f'step: no run folder (give --run DIR; port {port} has no claim file)'); return 2
    if plan is None:      # the plan of the run: in the claim folder, or two up when the claim folder is <run>/builders/<set>
        up = os.path.dirname(os.path.dirname(run_.rstrip('/'))) if os.path.basename(os.path.dirname(run_.rstrip('/'))) == 'builders' else None
        for d in (run_, up):
            if d and os.path.exists(os.path.join(d, 'parts.json')): plan = os.path.join(d, 'parts.json'); break
    code = STEP % {'kit': KIT, 'part': part, 'plan': os.path.abspath(plan) if plan else None, 'lod': opt(a, '--lod'),
                   'path': os.path.abspath(script), 'src': open(script).read(), 'steps': os.path.join(run_, 'steps'),
                   'thumb': '--thumb' in a}
    t0 = time.time()
    try:
        r = call(port, code, float(opt(a, '--timeout', 590)))
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        print(f'step {part}: bridge {port} unreachable: {e!r}'); return 1
    if isinstance(r, dict) and r.get('status') == 'error':
        print(f'step {part}: bridge refused: {str(r.get("message"))[-600:]}'); return 1
    res = r.get('result') if isinstance(r, dict) and 'result' in r else r
    if not isinstance(res, dict): print(f'step {part}: unexpected answer {str(res)[:300]}'); return 1
    if 'error' in res:
        tb = [l for l in res.get('traceback', '').strip().splitlines() if l.strip() and set(l.strip()) - set('~^ ')]
        where = [l.strip() for l in tb if l.strip().startswith('File ')][-1:] if tb else []
        print(f'step {part}: SCRIPT ERROR {res["error"]}')
        for l in (where + tb[-2:])[:4]: print('  ' + l.strip()[:220])
        print(f'look it up in {PITFALLS} (and the API docs); fix the cause, never delete the failing line')
        return 1
    v = re.search(r'-v(\d+)\.blend$', res.get('blend', '') or '')
    ver = f'v{int(v.group(1)):03d}' if v else ''
    head = (f'step {part} {ver} {"PASS" if res.get("ok") else "FAIL"}: {res.get("touched")} objects touched'
            + (f', re-attached {len(res["reattached"])} dependents' if res.get('reattached') else '')
            + f', check {res.get("check_s", 0):.2f} s, total {time.time() - t0:.1f} s')
    out = [head] + [l for l in res.get('lines', [])[1:] if not l.startswith('json ')][:4]
    if res.get('json'): out.append(f'json {res["json"]}')
    if res.get('blend'): out.append(f'blend {res["blend"]}' + (f'  thumb {res["thumb"]}' if res.get('thumb') else ''))
    if res.get('plan_updated') is not None:
        pp = res.get('per_part') or {}
        flags = ', '.join(f'{k}: rel {"ok" if v_.get("relations") else "FAIL"} uv {"ok" if v_.get("uv") else "FAIL"}' for k, v_ in list(pp.items())[:3])
        un = res.get('untagged') or []
        out.append(f'plan {plan}: {flags}' + (f'; NOT written, {len(un)} untagged objects ({", ".join(un[:3])}{" ..." if len(un) > 3 else ""}): '
                                              f'k.adopt(obj, part) or delete' if un else ''))
    out = out[:8]
    print('\n'.join(out))
    if '--no-report' not in a:
        msg = f'{part} {ver}: kit3d.check {"PASS" if res.get("ok") else "FAIL"}' + (f' ({res.get("fails")} faults)' if not res.get('ok') else '')
        cmd = [sys.executable, os.path.join(HERE, 'report.py'), os.path.dirname(os.path.abspath(plan)) if plan else run_, 'component', msg,      # the RUN's progress.jsonl (where the plan is), not the builder's claim folder
               '--data', json.dumps({'faults': res.get('fails', 0), 'touched': res.get('touched', 0), 'check_s': res.get('check_s')})]
        if res.get('thumb'): cmd += ['--picture', res['thumb']]
        if opt(a, '--builder'): cmd += ['--builder', opt(a, '--builder')]
        subprocess.run(cmd, capture_output=True, text=True)
    return 0 if res.get('ok') else 3


# ------------------------------------------------------------------------------------------------ detach / wait
def scoped(cmd, mem='12G'):
    """the build box rule (2026-10-13, after an OOM kill of a film render): every heavy job in its own memory-capped scope,
    Blender on at most 8 threads unless told otherwise. No systemd --user (some sandboxes): the bare command."""
    cmd = list(cmd)
    if cmd and 'blender' in os.path.basename(cmd[0]) and '-t' not in cmd and '--threads' not in cmd:
        cmd = cmd[:1] + ['-t', '8'] + cmd[1:]
    if mem and mem != '0' and subprocess.run(['systemd-run', '--user', '--scope', '-q', 'true'], capture_output=True).returncode == 0:
        cmd = ['systemd-run', '--user', '--scope', '-q', '-p', f'MemoryMax={mem}', '-p', 'MemorySwapMax=0'] + cmd
    return cmd


def detach(name, cmd, d, nice_=10, mem='12G'):
    d = os.path.abspath(d); os.makedirs(d, exist_ok=True)
    cmd = scoped(cmd, mem)
    log = os.path.join(d, name + '.log'); done = os.path.join(d, name + '.done')
    for f in (done,):
        if os.path.exists(f): os.remove(f)
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), '_detached', name, d, str(nice_), '--'] + cmd,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    print(f'started {name} (pid {p.pid}) in the background; log {log}')
    print(f'done-file {done}; wait with: python3 {os.path.abspath(__file__)} wait {done}')
    return 0


def _detached(name, d, nice_, cmd):
    log = os.path.join(d, name + '.log'); done = os.path.join(d, name + '.done'); t0 = time.time()
    try:
        os.nice(int(nice_))
    except OSError:
        pass
    with open(log, 'w') as f:
        f.write(f'# {time.strftime("%Y-%m-%d %H:%M:%S")} {" ".join(cmd)}\n'); f.flush()
        try:
            rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT).returncode
        except OSError as e:
            f.write(f'cannot start: {e!r}\n'); rc = 127
    tail = open(log, errors='replace').read().splitlines()[-12:]
    info = {'name': name, 'exit': rc, 'seconds': round(time.time() - t0, 1), 'log': log, 'cmd': cmd, 'tail': tail,
            'ended': time.strftime('%Y-%m-%d %H:%M:%S')}
    with open(done + '.tmp', 'w') as f: json.dump(info, f, indent=1)
    os.replace(done + '.tmp', done)
    return 0


def wait(target, d=None, mx=110.0):
    done = target if target.endswith('.done') else os.path.join(os.path.abspath(d or 'jobs'), target + '.done')
    t0 = time.time()
    while not os.path.exists(done) and time.time() - t0 < mx: time.sleep(3)
    if not os.path.exists(done):
        log = done[:-5] + '.log'; last = ''
        if os.path.exists(log):
            ls = [l for l in open(log, errors='replace').read().splitlines() if l.strip()]
            last = ls[-1][:200] if ls else ''
        print(f'still running after {time.time() - t0:.0f} s: {done}' + (f'\n  last: {last}' if last else '')); return 4
    j = json.load(open(done))
    print(f'{j["name"]}: exit {j["exit"]} after {j["seconds"]} s; log {j["log"]}')
    for l in j['tail'][-5:]: print('  ' + l[:200])
    return 0 if j['exit'] == 0 else 1


def main(a):
    if not a or '-h' in a[:2] or '--help' in a[:3]:        # also `bridge.py wait --help` (it once waited 230 s for a job named --help)
        print(__doc__); return 0 if a else 2
    if a[0] == '_detached':
        return _detached(a[1], a[2], a[3], a[a.index('--') + 1:])
    if a[0] == 'detach':
        if '--' not in a or len(a) < 4: print(__doc__); return 2
        cmd = a[a.index('--') + 1:]; head = a[:a.index('--')]
        return detach(a[1], cmd, opt(head, '--dir', os.path.join(os.getcwd(), 'jobs')), int(opt(head, '--nice', 10)),
                      opt(head, '--mem', '12G'))
    if a[0] == 'wait':
        if len(a) < 2: print(__doc__); return 2
        return wait(a[1], opt(a, '--dir'), float(opt(a, '--max', 110)))
    if a[0] == 'step':
        if len(a) < 3 or not a[1].isdigit(): print(__doc__); return 2
        if not os.path.exists(a[2]): print(f'step: no such script {a[2]}'); return 2
        return step(a[1], a[2], a[3:])
    if a[0] in ('claim', 'release'):
        if len(a) != 3: print(__doc__); return 2
        return (claim if a[0] == 'claim' else release)(a[1], a[2])
    if len(a) < 2 or not a[0].isdigit(): print(__doc__); return 2
    timeout = 590
    if '--timeout' in a: timeout = float(a[a.index('--timeout') + 1])
    if not os.path.exists(a[1]): print(json.dumps({'error': f'no such script {a[1]}'})); return 2
    if '--detach' in a:
        name = opt(a, '--name', f'bridge{a[0]}-' + os.path.splitext(os.path.basename(a[1]))[0])
        return detach(name, [sys.executable, os.path.abspath(__file__), a[0], os.path.abspath(a[1]), '--timeout', str(timeout)],
                      opt(a, '--dir', os.path.join(os.getcwd(), 'jobs')), 0, '0')
    return run(a[0], a[1], timeout)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
