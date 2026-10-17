"""_run.py: start Blender the way the build box allows (memory-capped scope, nice, -t 8) and pass tool arguments after `--`."""
import os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.normpath(os.path.join(HERE, '..', '..', '..', '3d-asset-making', 'scripts'))   # the shared render.py


def blender_bin():
    for p in (os.environ.get('BLENDER'), '/snap/blender/current/blender', shutil.which('blender')):
        if p and os.path.exists(p):
            return p
    raise SystemExit('look: no Blender found (set BLENDER=/path/to/blender)')


def scope():
    """systemd scope with a memory cap (LOOK_MEM, default 12G) when this session may make one; always nice 10."""
    if os.environ.get('LOOK_NO_SCOPE') or not shutil.which('systemd-run'):
        return ['nice', '-n', '10']
    if subprocess.call(['systemd-run', '--user', '--scope', '-q', 'true'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        return ['nice', '-n', '10']
    return ['systemd-run', '--user', '--scope', '-q', '-p', 'MemoryMax=' + os.environ.get('LOOK_MEM', '12G'), '-p', 'MemorySwapMax=0', 'nice', '-n', '10']


def blender(script, args, blend=None, gpu=False, quiet=True, timeout=1800):
    """Run `script` in a fresh headless Blender. Returns (exit code, the lines the script printed that start with a
    capital tag, e.g. MESH_LOOK / LOOK / OVERLAY, and any traceback)."""
    env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='8')
    if gpu:
        env.setdefault('MV_BLENDER_GPU', '1')
    cmd = scope() + [blender_bin(), '-b', '--factory-startup', '-noaudio', '-t', '8']
    if blend:
        cmd.append(blend)
    cmd += ['--python', os.path.join(HERE, script), '--'] + [str(a) for a in args]
    p = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
    keep, tb = [], False
    for ln in p.stdout.splitlines():
        if ln.startswith('Traceback'):
            tb = True
        if tb or ln.startswith(('MESH_LOOK', 'LOOK', 'OVERLAY', 'Error', 'ERROR')):
            keep.append(ln)
        if not quiet:
            print(ln)
    return p.returncode, keep


def tool_argv():
    """Arguments of a tool whether it runs under Blender (after `--`) or under plain python3."""
    return sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]


def arg(argv, name, default=None, flag=False):
    if name in argv:
        return True if flag else argv[argv.index(name) + 1]
    return default
