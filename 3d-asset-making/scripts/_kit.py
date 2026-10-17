"""Shared helpers of the game-version toolkit (bake.py, uvpack.py, export_game.py, export_original.py, asset_record.py).

Pure-python parts (GLB reading, PNG writing, argument helpers) import nothing from Blender, so asset_record.py can use
them with the system python. Blender parts import bpy lazily inside the functions.
"""
import fnmatch, json, math, os, struct, sys, zlib

HERE = os.path.dirname(os.path.abspath(__file__))


# ----------------------------------------------------------------------------------------------------------- arguments
def script_argv():
    """Arguments after Blender's `--` (or all of them outside Blender)."""
    a = sys.argv
    return a[a.index('--') + 1:] if '--' in a else a[1:]


def csv(s):
    return [x.strip() for x in s.split(',') if x.strip()] if s else []


def floats(s, n=None):
    v = [float(x) for x in csv(s)]
    if n and len(v) != n: raise SystemExit(f'expected {n} numbers in {s!r}')
    return v


def die(msg):
    print('ERROR:', msg, flush=True)
    sys.exit(2)


# ---------------------------------------------------------------------------------------------------------- PNG / GLB
def png_write(path, arr):
    """Write an 8-bit PNG from a numpy array (H, W, C) in Blender's bottom-up row order (row 0 = bottom).
    C = 1, 3 or 4. Atomic (temp + rename). Filter 'Up' on every row (good compression, vectorised)."""
    import numpy as np
    a = np.ascontiguousarray(np.flipud(arr))
    if a.dtype != np.uint8: a = np.clip(a * 255.0 + 0.5, 0, 255).astype(np.uint8)
    if a.ndim == 2: a = a[..., None]
    h, w, c = a.shape
    ctype = {1: 0, 3: 2, 4: 6}[c]
    flat = a.reshape(h, w * c).astype(np.int16)
    up = np.empty_like(flat); up[0] = flat[0]; up[1:] = flat[1:] - flat[:-1]
    rows = np.empty((h, w * c + 1), np.uint8); rows[:, 0] = 2; rows[:, 1:] = (up & 0xFF).astype(np.uint8)
    rows[0, 0] = 0; rows[0, 1:] = a.reshape(h, w * c)[0]
    def chunk(t, d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    data = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, ctype, 0, 0, 0)) + \
        chunk(b'IDAT', zlib.compress(rows.tobytes(), 6)) + chunk(b'IEND', b'')
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f: f.write(data)
    os.replace(tmp, path)


def glb_json(path):
    with open(path, 'rb') as f:
        head = f.read(20)
        if head[:4] != b'glTF': raise ValueError(f'not a .glb: {path}')
        n = struct.unpack('<I', head[12:16])[0]
        return json.loads(f.read(n))


def glb_fix_zero_tangents(path):
    """Replace zero-length TANGENT vectors in a .glb by a unit vector across the vertex normal (w = 1), in place.
    Blender's exporter writes (0, 0, 0, w) at a corner whose triangles' tangents cancel (mirrored UV islands or back-to-back
    faces meeting at a point: a car near had 19 of 60,000); the glTF-Validator calls each an error
    (ACCESSOR_VECTOR3_NON_UNIT) and a shader normalising it gets NaN. Only vectors shorter than 0.5 are touched.
    Returns how many were replaced. (Lead 2026-10-13, after a test run.)"""
    with open(path, 'rb') as f: data = bytearray(f.read())
    if data[:4] != b'glTF': raise ValueError(f'not a .glb: {path}')
    jn = struct.unpack('<I', data[12:16])[0]; j = json.loads(bytes(data[20:20 + jn]))
    b0 = 20 + jn + 8                                          # start of the BIN chunk's payload
    acc, bvs = j.get('accessors', []), j.get('bufferViews', [])
    def loc(ai, width):
        a = acc[ai]; bv = bvs[a['bufferView']]
        if a.get('componentType') != 5126 or bv.get('buffer', 0) != 0 or 'sparse' in a: return None
        return b0 + bv.get('byteOffset', 0) + a.get('byteOffset', 0), bv.get('byteStride') or width, a['count']
    fixed, seen = 0, set()
    for m in j.get('meshes', []):
        for pr in m.get('primitives', []):
            at = pr.get('attributes', {})
            if 'TANGENT' not in at or 'NORMAL' not in at or at['TANGENT'] in seen: continue
            seen.add(at['TANGENT']); lt, ln = loc(at['TANGENT'], 16), loc(at['NORMAL'], 12)
            if not lt or not ln or lt[2] != ln[2]: continue
            for i in range(lt[2]):
                o = lt[0] + i * lt[1]; x, y, z = struct.unpack_from('<3f', data, o)
                if x * x + y * y + z * z >= 0.25: continue
                nx, ny, nz = struct.unpack_from('<3f', data, ln[0] + i * ln[1])
                ax = (1.0, 0.0, 0.0) if abs(nx) < 0.9 else (0.0, 1.0, 0.0)          # any axis not along the normal
                d = ax[0] * nx + ax[1] * ny + ax[2] * nz
                t = (ax[0] - d * nx, ax[1] - d * ny, ax[2] - d * nz); l = math.sqrt(sum(c * c for c in t)) or 1.0
                struct.pack_into('<4f', data, o, t[0] / l, t[1] / l, t[2] / l, 1.0); fixed += 1
    if fixed:
        tmp = path + '.fix'
        with open(tmp, 'wb') as f: f.write(data)
        os.replace(tmp, path)
    return fixed


def glb_stats(path):
    """Triangles and draw calls as three.js would draw the default scene (every mesh node x its primitives), plus the
    named empties (mount.*, light.*) with their world transform (glTF frame, +Y up) and extras."""
    j = glb_json(path); acc = j.get('accessors', []); nodes = j.get('nodes', [])
    tris = draws = 0; per_node = {}; empties = []
    def mat_mul(a, b): return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
    def local(nd):
        if 'matrix' in nd:
            m = nd['matrix']; return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
        t = nd.get('translation', [0, 0, 0]); q = nd.get('rotation', [0, 0, 0, 1]); s = nd.get('scale', [1, 1, 1])
        x, y, z, w = q
        R = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
             [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
             [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
        return [[R[r][0] * s[0], R[r][1] * s[1], R[r][2] * s[2], t[r]] for r in range(3)] + [[0, 0, 0, 1]]
    def walk(i, M):
        nonlocal tris, draws
        nd = nodes[i]; W = mat_mul(M, local(nd)); name = nd.get('name', '')
        if 'mesh' in nd:
            t = 0
            for pr in j['meshes'][nd['mesh']]['primitives']:
                c = acc[pr['indices']]['count'] if 'indices' in pr else acc[pr['attributes']['POSITION']]['count']
                t += c // 3; draws += 1
            tris += t; per_node[name] = per_node.get(name, 0) + t
        elif name.startswith(('mount.', 'light.')):
            empties.append(dict(name=name, translation=[round(W[r][3], 4) for r in range(3)],
                                matrix=[[round(v, 5) for v in row] for row in W[:3]], extras=nd.get('extras', {})))
        for c in nd.get('children', []): walk(c, W)
    I = [[1 if r == c else 0 for c in range(4)] for r in range(4)]
    sc = j.get('scenes', [{}])[j.get('scene', 0)] if j.get('scenes') else {'nodes': list(range(len(nodes)))}
    for r in sc.get('nodes', []): walk(r, I)
    return dict(triangles=tris, draw_calls=draws, per_node=per_node, kb=os.path.getsize(path) // 1024,
                materials=len(j.get('materials', [])), images=len(j.get('images', [])), nodes=len(nodes),
                mounts=[e for e in empties if e['name'].startswith('mount.')],
                lights=[e for e in empties if e['name'].startswith('light.')],
                extensions=j.get('extensionsUsed', []))


# ------------------------------------------------------------------- GLB gates: Khronos validator + a fresh reimport
# Coordinator 2026-10-13 (a survey of 25 public 3D/agent skills, five do this): before a new GLB replaces the old one,
# run the official Khronos glTF-Validator and fail on errors, and reimport the file fresh (Blender, empty scene) and
# compare meshes, triangles, materials and textures with what was exported. Node packages live outside the public
# skills repo, in KIT_NODE_DIR (default ~/.cache/3d-asset-kit/node), installed on first use at pinned versions.
NODE_PKGS = {'gltf-validator': '2.0.0-dev.3.10', 'meshoptimizer': '1.3.0'}


def node_dir(install=True):
    """The node_modules home of the kit's node tools (gltf-validator, meshoptimizer); installs them when missing.
    Returns the directory or None (no node/npm)."""
    import shutil, subprocess
    d = os.environ.get('KIT_NODE_DIR') or os.path.expanduser('~/.cache/3d-asset-kit/node')
    if all(os.path.isdir(os.path.join(d, 'node_modules', k)) for k in NODE_PKGS): return d
    if not install or not shutil.which('npm') or not shutil.which('node'): return None
    os.makedirs(d, exist_ok=True)
    if not os.path.exists(os.path.join(d, 'package.json')):
        with open(os.path.join(d, 'package.json'), 'w') as f: f.write('{"name": "kit-node-tools", "private": true}\n')
    r = subprocess.run(['npm', 'install', '--no-audit', '--no-fund', '--prefix', d] + [f'{k}@{v}' for k, v in NODE_PKGS.items()],
                       capture_output=True, text=True)
    return d if r.returncode == 0 else None


def gltf_validate(glb):
    """Khronos glTF-Validator on a GLB. Returns {ok, errors, warnings, infos, hints, version, messages[:40]} or
    {ok: False, error: why}."""
    import subprocess
    d = node_dir()
    if not d: return dict(ok=False, error='glTF-Validator unavailable (needs node + npm; KIT_NODE_DIR)')
    js = ("const v=require(process.argv[1]+'/node_modules/gltf-validator');const fs=require('fs');"
          "v.validateBytes(new Uint8Array(fs.readFileSync(process.argv[2])),{maxIssues:500}).then(r=>{const i=r.issues;"
          "console.log(JSON.stringify({version:r.validatorVersion,errors:i.numErrors,warnings:i.numWarnings,infos:i.numInfos,"
          "hints:i.numHints,messages:i.messages.filter(m=>m.severity<=1).slice(0,40).map(m=>({code:m.code,severity:m.severity,"
          "message:m.message,pointer:m.pointer}))}))}).catch(e=>{console.log(JSON.stringify({error:String(e)}))})")
    r = subprocess.run(['node', '-e', js, d, os.path.abspath(glb)], capture_output=True, text=True)
    try: out = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception: return dict(ok=False, error=f'validator gave no report: {r.stderr[-400:]}')
    out['ok'] = 'error' not in out and out.get('errors', 1) == 0
    return out


REIMPORT_PY = r"""
import bpy, json, sys
p = sys.argv[sys.argv.index('--') + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)
r = bpy.ops.import_scene.gltf(filepath=p)
obs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
tris = 0; prims = 0; mats = set()
for o in obs:
    me = o.data; me.calc_loop_triangles(); tris += len(me.loop_triangles)
    used = {pl.material_index for pl in me.polygons}
    prims += max(1, len(used))
    for i in used:
        if i < len(o.material_slots) and o.material_slots[i].material: mats.add(o.material_slots[i].material.name)
imgs = {i.name for i in bpy.data.images if i.users and i.type == 'IMAGE'}
print('REIMPORT ' + json.dumps(dict(result=list(r), mesh_objects=len(obs), meshes=len({o.data.name for o in obs}),
      primitives=prims, triangles=tris, materials=len(mats), textures=len(imgs),
      empties=len([o for o in bpy.context.scene.objects if o.type == 'EMPTY']))))
"""


def reimport_check(glb, expect, blender=None):
    """Import the GLB into an EMPTY Blender (a separate process) and compare with `expect` (what the exporter meant:
    any of mesh_objects, primitives, triangles, materials, textures). Returns {ok, got, expect, mismatch}."""
    import subprocess, tempfile
    blender = blender or (sys.executable if 'blender' in os.path.basename(sys.executable).lower() else None)
    try:
        import bpy; blender = blender or bpy.app.binary_path
    except ImportError: pass
    if not blender: return dict(ok=False, error='no Blender to reimport with')
    with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as f: f.write(REIMPORT_PY); sp = f.name
    try:
        r = subprocess.run([blender, '-b', '-t', '8', '--factory-startup', '-noaudio', '--python', sp, '--', os.path.abspath(glb)],
                           capture_output=True, text=True, timeout=1800)
    finally: os.unlink(sp)
    line = next((l for l in r.stdout.splitlines() if l.startswith('REIMPORT ')), None)
    if not line: return dict(ok=False, error='reimport failed: ' + (r.stdout + r.stderr)[-600:])
    got = json.loads(line[9:])
    mism = {k: dict(exported=v, reimported=got.get(k)) for k, v in expect.items() if v is not None and got.get(k) != v}
    return dict(ok=not mism and got.get('result') == ['FINISHED'], got=got, expect=expect, mismatch=mism)


def export_expect(objs, depsgraph=None):
    """What an export of these objects should read back as: mesh objects, primitives, triangles, materials, textures
    (images reachable in the used materials' trees). Modifiers are counted applied (export_apply=True)."""
    import bpy
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    n = prims = tris = 0; mats = set(); imgs = set()
    def tree_imgs(nt, seen):
        if nt is None or nt.as_pointer() in seen: return
        seen.add(nt.as_pointer())
        for nd in nt.nodes:
            if nd.type == 'TEX_IMAGE' and nd.image and any(o.links for o in nd.outputs): imgs.add(nd.image.name)
            if nd.type == 'GROUP': tree_imgs(nd.node_tree, seen)
    for o in objs:
        if o.type not in ('MESH', 'CURVE', 'FONT', 'SURFACE', 'META'): continue
        me = o.evaluated_get(dg).to_mesh()
        if me is None or not len(me.polygons): o.evaluated_get(dg).to_mesh_clear(); continue
        me.calc_loop_triangles(); n += 1; tris += len(me.loop_triangles)
        used = {pl.material_index for pl in me.polygons}; prims += max(1, len(used))
        for i in used:
            m = o.material_slots[i].material if i < len(o.material_slots) else None
            if m: mats.add(m.name); tree_imgs(m.node_tree, set())
        o.evaluated_get(dg).to_mesh_clear()
    return dict(mesh_objects=n, primitives=prims, triangles=tris, materials=len(mats), textures=len(imgs))


def pbr_check(args, blender_file=None, rules=None):
    """Run scripts/pbr_check.py (material-class checker, rules M1-M11 / E1-E3 / G1-G8 / T1; built by another agent,
    standards research 2026-10-13) when it is on disk. A GLB: python3 pbr_check.py <glb> ...; a .blend: blender -b FILE
    --python pbr_check.py -- .... Its findings are one line each ('ERROR M2 ...'). Returns dict(available, errors
    [lines, filtered to `rules` when given], lines, exit). Guarded: absent tool -> available False, nothing refused."""
    import subprocess, re
    pc = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pbr_check.py')
    if not os.path.exists(pc): return dict(available=False, errors=[], lines=['pbr_check.py not on disk: skipped'])
    if blender_file:
        try:
            import bpy; b = bpy.app.binary_path
        except ImportError: b = 'blender'
        cmd = [b, '-b', '-t', '8', blender_file, '--python', pc, '--'] + list(args)
    else:     # the SYSTEM python (numpy + Pillow): Blender's bundled python has no Pillow and, outside Blender, no bpy to
              # decode textures, so pbr_check read every texture as 1.0 there (synth: lit share 100 % instead of 1.7 %)
        import shutil
        cmd = [shutil.which('python3') or '/usr/bin/python3', pc] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    lines = [l.strip() for l in (r.stdout + r.stderr).splitlines() if re.match(r'\s*(ERROR|WARN|INFO|OK|RESULT|PBR RESULT)\b', l)]
    errs = [l for l in lines if l.startswith('ERROR') and (not rules or any(re.match(rf'ERROR\s+{x}\b', l) for x in rules))]
    res = next((l.split(':', 1)[1].strip() for l in lines if l.startswith('PBR RESULT')), None)
    if res is None and r.returncode not in (0, 2): res = f'not run (exit {r.returncode}: {(r.stderr or r.stdout)[-300:]})'
    return dict(available=True, result=res, errors=errs, lines=[l for l in lines if not l.startswith('PBR RESULT')][:40]
                + ([f'PBR RESULT: {res}'] if res else []), exit=r.returncode)


def glb_gates(glb, expect, skip_validator=False):
    """Both gates on a (temp) GLB; merges the results into <glb>.integrity.json. Returns (refusals, results)."""
    # textures: the exporter writes its own images (packs metal/rough, folds alpha into the colour), so the number the
    # reimport must find is the GLB's own image list; the scene's count is kept as info (a train car original: 1052
    # Blender images -> 581 glTF images, by design)
    expect = dict(expect); scene_tex = expect.pop('textures', None)
    expect['textures'] = len(glb_json(glb).get('images', []))
    res = dict(gltf_validator=(dict(ok=None, skipped=True) if skip_validator else gltf_validate(glb)),
               reimport=reimport_check(glb, expect))
    res['reimport']['scene_images'] = scene_tex
    refuse = []
    v = res['gltf_validator']
    if not skip_validator and not v.get('ok'):
        refuse.append('glTF-Validator: ' + (v.get('error') or f'{v.get("errors")} errors: ' +
                      '; '.join(f'{m["code"]} {m.get("pointer", "")}' for m in v.get('messages', []) if m.get('severity') == 0)[:600]))
    ri = res['reimport']
    if not ri.get('ok'): refuse.append('reimport differs from the export: ' + str(ri.get('error') or ri.get('mismatch')))
    ij = {}
    try: ij = json.load(open(glb + '.integrity.json'))
    except Exception: pass
    ij.update(res)
    with open(glb + '.integrity.json', 'w') as f: json.dump(ij, f, indent=1)
    return refuse, res


def integrity_script():
    for p in (os.path.join(HERE, '..', '..', '3d-modelling', 'scripts', 'mesh_integrity.py'),
              os.path.expanduser('~/.claude/skills/3d-modelling/scripts/mesh_integrity.py')):
        if os.path.exists(p): return os.path.abspath(p)
    return None


def run_integrity(glb, against=None, extra=(), python='python3'):
    """Run mesh_integrity.py on a GLB; save the full text beside it; return the key lines."""
    import subprocess
    mi = integrity_script()
    if not mi: return dict(error='mesh_integrity.py not found (skill 3d-modelling)')
    cmd = [python, mi, glb] + (['--against', against] if against else []) + list(extra) + ['--json', glb + '.integrity.json']
    r = subprocess.run(cmd, capture_output=True, text=True)
    txt = r.stdout + r.stderr
    with open(glb + '.integrity.txt', 'w') as f: f.write(txt)
    keys = {}
    for line in txt.splitlines():
        s = line.strip()
        for k in ('RESULT', 'GAPS', 'FLICKER', 'BODIES', 'CRACKS', 'LOST', 'AGAINST'):
            if s.startswith(k) or s.startswith(k + ':'):
                keys.setdefault(k.lower(), s)
    keys['exit'] = r.returncode; keys['report'] = glb + '.integrity.txt'
    return keys


# ------------------------------------------------------------------------------------------------------ numpy imaging
def srgb_encode(lin):
    import numpy as np
    lin = np.clip(lin, 0.0, 1.0)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)


def raster_uv(tri_uv, size, ids=None, count=False):
    """Rasterise UV triangles (N, 3, 2) into a size x size grid (row 0 = v 0, Blender's order). A pixel belongs to a
    triangle when its centre is inside. Returns a bool mask, an int32 map of ids (-1 = none) when ids is given, or an
    int16 count of covering triangles when count=True."""
    import numpy as np
    if count: out = np.zeros((size, size), np.int16)
    else: out = np.full((size, size), -1, np.int32) if ids is not None else np.zeros((size, size), bool)
    P = np.asarray(tri_uv, np.float64) * size - 0.5          # pixel centres at integer coordinates
    for k in range(len(P)):
        (x0, y0), (x1, y1), (x2, y2) = P[k]
        d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(d) < 1e-12: continue
        lo_x = max(int(math.ceil(min(x0, x1, x2))), 0); hi_x = min(int(math.floor(max(x0, x1, x2))), size - 1)
        lo_y = max(int(math.ceil(min(y0, y1, y2))), 0); hi_y = min(int(math.floor(max(y0, y1, y2))), size - 1)
        if hi_x < lo_x or hi_y < lo_y: continue
        X, Y = np.meshgrid(np.arange(lo_x, hi_x + 1), np.arange(lo_y, hi_y + 1))
        a = ((y1 - y2) * (X - x2) + (x2 - x1) * (Y - y2)) / d
        b = ((y2 - y0) * (X - x2) + (x0 - x2) * (Y - y2)) / d
        m = (a >= -1e-6) & (b >= -1e-6) & (a + b <= 1 + 1e-6)
        sub = out[lo_y:hi_y + 1, lo_x:hi_x + 1]
        if count: sub += m
        elif ids is None: sub |= m
        else: sub[m] = ids[k]
    return out


def dilate(img, valid, steps):
    """Grow valid pixels outward `steps` times (8-neighbour mean). img (H, W, C) float, valid (H, W) bool."""
    import numpy as np
    img = img.copy(); valid = valid.copy()
    for _ in range(steps):
        if valid.all(): break
        acc = np.zeros_like(img); cnt = np.zeros(valid.shape, np.float32)
        vf = valid.astype(np.float32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0: continue
                acc += np.roll(np.roll(img * vf[..., None], dy, 0), dx, 1)
                cnt += np.roll(np.roll(vf, dy, 0), dx, 1)
        grow = (~valid) & (cnt > 0)
        img[grow] = acc[grow] / cnt[grow][:, None]
        valid = valid | grow
    return img, valid


def push_pull(img, valid):
    """Fill every invalid pixel from a pyramid of valid averages (no hard background anywhere, mip-safe)."""
    import numpy as np
    if valid.all(): return img
    if not valid.any(): return img
    h, w, c = img.shape
    if h <= 1 or w <= 1:
        mean = img[valid].mean(0); out = img.copy(); out[~valid] = mean; return out
    H2, W2 = (h + 1) // 2, (w + 1) // 2
    pi = np.zeros((H2 * 2, W2 * 2, c), img.dtype); pv = np.zeros((H2 * 2, W2 * 2), np.float32)
    pi[:h, :w] = img * valid[..., None]; pv[:h, :w] = valid
    s = pi.reshape(H2, 2, W2, 2, c).sum((1, 3)); n = pv.reshape(H2, 2, W2, 2).sum((1, 3))
    low = np.where(n[..., None] > 0, s / np.maximum(n, 1)[..., None], 0)
    low = push_pull(low.astype(img.dtype), n > 0)
    up = np.repeat(np.repeat(low, 2, 0), 2, 1)[:h, :w]
    return np.where(valid[..., None], img, up)


def pad_fill(img, valid, margin):
    """Crisp padding of `margin` px around valid texels, then a pyramid fill of the rest."""
    img, v2 = dilate(img, valid, margin)
    return push_pull(img, v2)


# ------------------------------------------------------------------------------------------------- Blender: selection
def match(name, patterns):
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


# ------------------------------------------------------------------------- game material slots (coordinator 2026-10-13)
# The game drives class colours, its glass shader, night cabin glow, lamps and rain by MATERIAL NAME (the game:
# docs/assets-lib/train/GAME-CONTRACT.md, from src/train-models.js). So near and mid keep one
# material slot per game role; the bake only adds what lives inside a slot (AO, wear, dirt as a grey multiplier,
# normal detail); far may merge roles, down to ONE baked material, and keeps the night look (far_night below). A family's slots.json maps the
# original's material names onto those roles:
#   {"contract": "/abs/GAME-CONTRACT.md",
#    "roles": {"body-ceramic": ["stl.alu", "stl.alu_flute"], "stripe-lagoon": ["stl.red"], "glass-window": ["stl.glass"],
#              "LED-ivory": ["stl.lens*"], ...},                 # role name must contain a contract name
#    "required": {"near": [...], "mid": [...], "far": [...]},   # optional; defaults below (substrings)
#    "merge": {"far": ["trim-gunmetal", ...]}}                   # optional; roles folded into the baked slot
# or the shader library's game-slots.json (the game docs/research/shader-assets-20261013/library/), whose
# slot names match original materials that are NAMED with them ("a car.body-ceramic"); both forms can be combined.
# Materials not mapped go into one '<name>.baked' slot that carries the full baked colour (no role: the game leaves it).
SLOT_REQUIRED = {'near': ['body-ceramic', 'stripe-lagoon', 'trim-gunmetal', 'glass-', 'LED-ivory'],
                 'mid': ['body-ceramic', 'stripe-lagoon', 'trim-gunmetal', 'glass-', 'LED-ivory'],
                 'far': []}        # GAME-CONTRACT (corrected 2026-10-13): far may be ONE baked material; see far_night()
# slots the game lights at night (GAME-CONTRACT's table: emissive by the template's update hook)
SLOT_LIT = ('LED-ivory', 'interior-warm-grey', 'seat-ocean-fabric')


def far_night(material_names, emit_used, emit_lit_share):
    """What the contract asks of a far version instead of named slots: it "keeps lit windows and lamps for the night
    look (emissive in the bake)". Passed when a slot the game lights is among the GLB's materials, or the baked emissive
    map is on a material and has lit texels. -> (ok, how, refusal text)"""
    lit = sorted({t for t in SLOT_LIT for n in material_names if t in n})
    if lit: return True, f'slots the game lights: {lit}', ''
    if emit_used and (emit_lit_share or 0) > 0: return True, f'baked emissive, {emit_lit_share:.2%} of the texels lit', ''
    return False, 'none', ('far keeps no night look: no slot the game lights (' + ', '.join(SLOT_LIT) + ') and no lit texel in a baked '
                           'emissive map. The contract lets far be one baked material only with the night glow baked in: give the '
                           "original's lamps and lit windows emission (bake.py then writes <prefix>_emit.png), or keep their faces "
                           'in a lit slot (slots.json roles; --simplify-args "--layers off" drops small lamp faces at far)')
SLOT_MERGE = {'far': ['trim-gunmetal', 'door-vertex-paint', 'interior-warm-grey', 'seat-ocean-fabric']}


def load_slots(path):
    """A slots file: {"roles": {slot: [original material globs]}} and/or the shader library's game-slots.json form
    {"slots": {slot: {kind, ...}}}, whose slot names match original materials NAMED with them (substring)."""
    with open(path) as f: sl = json.load(f)
    roles = {r: (csv(g) if isinstance(g, str) else list(g)) for r, g in sl.get('roles', {}).items()}
    for r in (sl.get('slots') or {}):
        roles.setdefault(r, [])
        roles[r] = roles[r] + [f'*{r}*']
    sl['roles'] = roles
    return sl


def level_of(prefix, given=None):
    return given or next((l for l in ('near', 'mid', 'far') if l in (prefix or '')), 'near')


def slot_role(name, slots, level):
    """The game role of an original material name at this level (None = the baked slot)."""
    merge = set((slots.get('merge') or {}).get(level, SLOT_MERGE.get(level, [])))
    for r, globs in slots['roles'].items():
        if name and match(name, globs): return None if r in merge else r
    return None


def contract_names(path):
    """The material-name tokens a game contract page lists (backticked names in its table rows)."""
    import re
    names = []
    for line in open(path):
        if line.startswith('| `'):
            first = line.split('|')[1]
            names += re.findall(r'`([A-Za-z][\w-]*)`', first)
    return names


# ------------------------------------------------------------------------------- switch distances (one constant)
def switch(family=None):
    """Switch distances of a family from scripts/switch.json (the one place for them). Returns dict with near_mid,
    mid_far ([low, full graphics] m), hysteresis, near_m, appears ({near, mid, far}: the closest distance each version
    can be seen = the low end of its range minus the hysteresis), m_per_px ({level: metres per pixel there}), target_m
    (px pixels there), switch_m ([near->mid, mid->far] at full graphics, what asset.json records) and source."""
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'switch.json')) as f: d = json.load(f)
    fam = family or d.get('default_family')
    if fam not in d['families']: die(f'switch.json has no family {fam!r} (has {sorted(d["families"])})')
    f_ = dict(d['families'][fam]); cam = d['camera']; f_['family'] = fam; f_['camera'] = cam
    h = f_['hysteresis']
    f_['appears'] = dict(near=f_['near_m'], mid=max(f_['near_m'], f_['near_mid'][0] - h), far=max(f_['near_m'], f_['mid_far'][0] - h))
    k = 2 * math.tan(math.radians(cam['fov_deg']) / 2) / cam['rows']
    f_['m_per_px'] = {l: round(v * k, 5) for l, v in f_['appears'].items()}
    f_['target_m'] = {l: round(v * k * cam['px'], 4) for l, v in f_['appears'].items()}
    f_['switch_m'] = [f_['near_mid'][1], f_['mid_far'][1]]
    return f_


def resolve(spec, into='KIT_LOW'):
    """Objects named by SPEC: a collection name, an object name, or FILE.blend[:COLLECTION] (appended into a new
    collection `into`). Returns (objects, label)."""
    import bpy
    if '.blend' in spec:
        path, _, cname = spec.partition('.blend'); path += '.blend'; cname = cname.lstrip(':')
        if not os.path.exists(path): die(f'no such file {path}')
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            if cname:
                if cname not in src.collections: die(f'{path} has no collection {cname!r}; it has {src.collections[:20]}')
                dst.collections = [cname]
            else:
                dst.objects = list(src.objects)
        c = bpy.data.collections.new(into); bpy.context.scene.collection.children.link(c)
        if cname:
            col = dst.collections[0]; c.children.link(col); objs = list(col.all_objects)
        else:
            objs = [o for o in dst.objects if o is not None]
            for o in objs: c.objects.link(o)
        return objs, os.path.basename(path)[:-6] + (':' + cname if cname else '')
    c = bpy.data.collections.get(spec)
    if c: return list(c.all_objects), spec
    o = bpy.data.objects.get(spec)
    if o: return [o], spec
    die(f'{spec!r} is neither a collection, an object nor a .blend path. Collections: '
        f'{[c.name for c in bpy.data.collections][:40]}')


def keep_only_collections(keep):
    """Exclude every view-layer collection that is not one of `keep`, an ancestor of one, or inside one."""
    import bpy
    keep = set(keep)
    def visit(lc):
        c = lc.collection
        inside = c in keep
        below = any(ch in keep for ch in c.children_recursive)
        if inside:
            lc.exclude = False; return
        if below:
            lc.exclude = False
            for ch in lc.children: visit(ch)
        else:
            lc.exclude = True
    for lc in bpy.context.view_layer.layer_collection.children: visit(lc)
    bpy.context.view_layer.update()


def is_glass_obj(o, glass_names=()):
    return ('glass' in o.name.lower()) or bool(o.get('glass')) or any(o.name in n for n in glass_names)


def low_copy(objs, uv_name=None, name='KIT_LOW_COPY', triangulate=True, need_uv=True):
    """One world-space, triangulated copy of the low mesh objects (modifiers applied) with ONE UV layer 'atlas'
    (the given UV layer name, else each object's active-render layer). Materials kept per face. The same function
    is used by bake.py and export_game.py, so the baked UVs and the exported UVs are the same triangles."""
    import bpy, bmesh
    dg = bpy.context.evaluated_depsgraph_get()
    bm = bmesh.new()
    mats = []
    for o in objs:
        if o.type != 'MESH': continue
        me = bpy.data.meshes.new_from_object(o.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
        if not me.uv_layers or (need_uv and not usable_uv(me)):
            if need_uv: die(f'low mesh {o.name} has no usable UV map (none, or collapsed to a point): run uvpack.py first')
            for u in list(me.uv_layers): me.uv_layers.remove(u)
            me.uv_layers.new(name='atlas')
        lay = me.uv_layers.get(uv_name) if uv_name else None
        if lay is None:
            lay = next((u for u in me.uv_layers if u.active_render), me.uv_layers.active)
        keepname = lay.name
        for u in [u for u in me.uv_layers if u.name != keepname]: me.uv_layers.remove(u)
        me.uv_layers[0].name = 'atlas'
        me.transform(o.matrix_world)
        if o.matrix_world.determinant() < 0: me.flip_normals()
        slot_mats = [s.material for s in o.material_slots] or [None]
        base = len(mats); mats += slot_mats
        for p in me.polygons: p.material_index = base + min(p.material_index, len(slot_mats) - 1)
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    if not bm.faces: die('the low version has no mesh faces')
    if triangulate:
        bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for m in mats: me.materials.append(m)
    ob = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(ob)
    me.uv_layers.active = me.uv_layers['atlas']; me.uv_layers['atlas'].active_render = True
    return ob


def tri_arrays(me):
    """(uv (N,3,2), material index (N,), area3d (N,)) of a triangulated mesh's loop triangles."""
    import numpy as np
    me.calc_loop_triangles()
    n = len(me.loop_triangles)
    loops = np.empty(n * 3, np.int32); me.loop_triangles.foreach_get('loops', loops)
    uv = np.empty(len(me.loops) * 2, np.float32); me.uv_layers['atlas'].data.foreach_get('uv', uv)
    mi = np.empty(n, np.int32); me.loop_triangles.foreach_get('material_index', mi)
    ar = np.empty(n, np.float32); me.loop_triangles.foreach_get('area', ar)
    return uv.reshape(-1, 2)[loops].reshape(n, 3, 2), mi, ar


def uv_hash(me):
    import hashlib, numpy as np
    uv, _, _ = tri_arrays(me)
    return hashlib.sha256(np.round(uv, 5).astype(np.float32).tobytes()).hexdigest()[:16]


def tri_hash(me):
    """Hash of the triangulation (index buffer + positions to 0.1 mm): the tangent frame the normal map was baked in
    belongs to exactly this triangulation; any re-triangulation or simplification after the bake breaks it."""
    import hashlib, numpy as np
    me.calc_loop_triangles()
    tv = np.empty(len(me.loop_triangles) * 3, np.int32); me.loop_triangles.foreach_get('vertices', tv)
    co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get('co', co)
    return hashlib.sha256(tv.tobytes() + np.round(co, 4).astype(np.float32).tobytes()).hexdigest()[:16]


def set_threads(n, samples=1):
    import bpy
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'; sc.cycles.device = 'CPU'; sc.cycles.samples = samples
    try: sc.cycles.use_denoising = False
    except Exception: pass
    sc.render.threads_mode = 'FIXED'; sc.render.threads = n


# --------------------------------------------------------------------------- Blender: material channel graph (baking)
TMP = '_kit_'
GLASS = dict(color=(0.06, 0.075, 0.09, 1.0), rough=0.05, metal=0.0, alpha=0.7)
UNKNOWN = []          # materials with shader nodes the channel builder does not know (reported)


def _const(nt, v):
    n = nt.nodes.new('ShaderNodeRGB'); n.name = TMP + 'c'; n.label = TMP
    v = tuple(v) if hasattr(v, '__len__') else (v, v, v)
    n.outputs[0].default_value = (tuple(v) + (1.0,))[:4] if len(v) == 3 else tuple(v)[:4]
    return n.outputs[0]


def _inp(nt, sock):
    if sock.is_linked:
        l = sock.links[0]
        if not l.is_muted: return l.from_socket
    return _const(nt, sock.default_value)


def is_glass_principled(n):
    t = n.inputs.get('Transmission Weight')
    return t is not None and (t.is_linked or t.default_value >= 0.5)


def glass_value(n, chan, glass):
    """Glass seen in an opaque texture: clear glass is a dark pane (glass['color']); TINTED glass (a red tail lamp, an
    amber marker: saturation > 0.3) keeps its tint at 80 %, so lamps do not bake as black holes."""
    if chan == 'color':
        c = n.inputs.get('Base Color') or n.inputs.get('Color')
        if c is not None and not c.is_linked:
            r, g, b = tuple(c.default_value)[:3]; mx = max(r, g, b)
            if mx > 1e-4 and (mx - min(r, g, b)) / mx > 0.3: return (r * 0.8, g * 0.8, b * 0.8, 1.0)
    return glass[chan]


def channel(nt, sock, chan, glass=GLASS, depth=0):
    """An output socket that gives material channel `chan` (color, rough, metal, alpha) for the shader that feeds
    `sock` (a shader input). Mix/Add shaders become colour mixes with the same factor, so layered materials (paint
    over primer by a wear mask) bake as they look. Returns None for a branch that contributes nothing (Transparent,
    Holdout)."""
    if not sock.is_linked or depth > 40: return None
    l = sock.links[0]
    if l.is_muted: return None
    n = l.from_node; t = n.type
    if t == 'REROUTE': return channel(nt, n.inputs[0], chan, glass, depth + 1)
    def const(v): return _const(nt, v)
    if t == 'BSDF_PRINCIPLED':
        if is_glass_principled(n): return const(glass_value(n, chan, glass))
        return _inp(nt, n.inputs[{'color': 'Base Color', 'rough': 'Roughness', 'metal': 'Metallic', 'alpha': 'Alpha'}[chan]])
    if t in ('MIX_SHADER', 'ADD_SHADER'):
        shs = [i for i in n.inputs if i.type == 'SHADER']
        a, b = channel(nt, shs[0], chan, glass, depth + 1), channel(nt, shs[1], chan, glass, depth + 1)
        if chan == 'alpha':
            if a is None: a = const(0.0)
            if b is None: b = const(0.0)
        if a is None: return b
        if b is None: return a
        if t == 'ADD_SHADER':
            kinds = [s.links[0].from_node.type if s.is_linked else None for s in shs]
            if kinds[0] == 'EMISSION': return b
            if kinds[1] == 'EMISSION': return a
        mx = nt.nodes.new('ShaderNodeMix'); mx.name = TMP + 'mix'; mx.data_type = 'RGBA'; mx.clamp_factor = True
        ins = {s.identifier: s for s in mx.inputs}; outs = {s.identifier: s for s in mx.outputs}
        if t == 'MIX_SHADER':
            f = n.inputs[0]
            if f.is_linked: nt.links.new(f.links[0].from_socket, ins['Factor_Float'])
            else: ins['Factor_Float'].default_value = f.default_value
        else:
            ins['Factor_Float'].default_value = 0.5
        nt.links.new(a, ins['A_Color']); nt.links.new(b, ins['B_Color'])
        return outs['Result_Color']
    if t in ('BSDF_GLASS', 'BSDF_REFRACTION'): return const(glass_value(n, chan, glass))
    if t in ('BSDF_TRANSPARENT', 'HOLDOUT'): return const(0.0) if chan == 'alpha' else None
    if chan == 'alpha': return const(1.0)
    if t == 'EMISSION':
        return _inp(nt, n.inputs['Color']) if chan == 'color' else const(0.5 if chan == 'rough' else 0.0)
    if t in ('BSDF_GLOSSY', 'BSDF_ANISOTROPIC', 'BSDF_METALLIC'):
        if chan == 'color': return _inp(nt, n.inputs.get('Color') or n.inputs.get('Base Color'))
        if chan == 'rough': return _inp(nt, n.inputs['Roughness'])
        return const(1.0)
    col = n.inputs.get('Color') or n.inputs.get('Base Color')
    if col is not None and t != 'GROUP':
        if chan == 'color': return _inp(nt, col)
        if chan == 'rough':
            r = n.inputs.get('Roughness')
            return _inp(nt, r) if (r is not None and t not in ('BSDF_DIFFUSE',)) else const(0.9 if t == 'BSDF_DIFFUSE' else 0.5)
        return const(0.0)
    UNKNOWN.append(f'{nt.name if hasattr(nt, "name") else "?"}:{t}')
    return const({'color': (0.5, 0.5, 0.5), 'rough': 0.6, 'metal': 0.0}[chan])


def output_node(m):
    nt = m.node_tree
    if nt is None: return None
    return nt.get_output_node('CYCLES') or nt.get_output_node('ALL') or next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None)


def _assign(sock, value):
    try: sock.default_value = value; return
    except (TypeError, ValueError, AttributeError): pass
    seq = tuple(value) if hasattr(value, '__len__') else None
    try: sock.default_value = sum(seq[:3]) / 3 if seq else (value, value, value, 1.0)[:len(sock.default_value)]
    except (TypeError, ValueError, AttributeError): pass


def idle_record(m):
    """The library-kind record {kind, slot, p} a material carries as custom property `idle` (a design decision), or None."""
    v = m.get('idle') if m is not None else None
    if v is not None:
        v = v.to_dict() if hasattr(v, 'to_dict') else json.loads(v) if isinstance(v, str) else v
        if isinstance(v, dict) and v.get('kind') and isinstance(v.get('p'), dict): return v
    return idle_record_from_group(m)


def idle_record_from_group(m):
    """The record read off the wiring itself: a material whose Surface comes straight from an `idle.<kind>@<ver>`
    group IS that kind, with the group's unlinked inputs as its params (the sockets are the kind's param names). Both
    kiosk designers (2026-10-14/15) wired the groups right but wrote no `idle` property (one wrote its own
    `tv_kind`, one nothing), so every exporter baked the library kinds (owner 2026-10-15 18:18: "you only fixed that
    exact asset but didn't actually fix the skill or export scripts"). The wiring is the truth; the property is optional."""
    on = output_node(m) if m is not None and m.node_tree else None
    if on is None or not on.inputs['Surface'].is_linked: return None
    g = on.inputs['Surface'].links[0].from_node
    if g.type != 'GROUP' or not g.node_tree or not g.node_tree.name.startswith('idle.'): return None
    p = {}
    for i in g.inputs:
        if i.is_linked or not hasattr(i, 'default_value') or i.name[:1].isupper(): continue   # Mask, Base Normal: images
        v = i.default_value
        p[i.name] = [round(float(x), 5) for x in tuple(v)[:3]] if hasattr(v, '__len__') else round(float(v), 5)
    return {'kind': g.node_tree.name[len('idle.'):], 'slot': m.name, 'p': p, 'from': 'group wiring'}


def kinds_to_contract(materials):
    """Library KINDS stay live shaders (a design decision: "materials stay shaders through near and mid"), so they are NOT baked.
    A material with an `idle` record whose surface is an `idle.<kind>@<ver>` group gets, in memory, the library's export
    contract (library/idle_export.py): a plain Principled with fallback factors from p, the group's Mask image as glTF
    occlusion, its Base Normal as the normal; the record rides as extras.idle and the viewer/game draws the kind's GLSL
    twin. Mirror: blender-dash blender/export_blend.py (IDLE_KIND). Returns 'material=kind' strings."""
    import bpy
    done = []
    for m in materials:
        on = output_node(m) if m and m.node_tree else None
        rec = idle_record(m) if on else None
        g = on.inputs['Surface'].links[0].from_node if rec and on.inputs['Surface'].is_linked else None
        if not g or g.type != 'GROUP' or not g.node_tree or not g.node_tree.name.startswith('idle.'): continue
        nt = m.node_tree; p = rec['p']; pb = nt.nodes.new('ShaderNodeBsdfPrincipled')
        col = list(p.get('color') or p.get('lens') or p.get('tint') or p.get('light') or [0.5, 0.5, 0.5])[:3]
        alpha = float(p.get('opacity', 1.0))
        pb.inputs['Base Color'].default_value = (*col, 1.0); pb.inputs['Alpha'].default_value = alpha
        pb.inputs['Metallic'].default_value = float(p.get('metal', 0.0)); pb.inputs['Roughness'].default_value = float(p.get('rough', 0.5))
        if 'lamp' in rec['kind']:
            pb.inputs['Emission Color'].default_value = (*list(p['light'])[:3], 1.0)
            pb.inputs['Emission Strength'].default_value = float(p.get('day', 1.0))
        if 'paint.metallic' in rec['kind']:
            pb.inputs['Coat Weight'].default_value = float(p.get('coat', 1.0)); pb.inputs['Coat Roughness'].default_value = float(p.get('coat_rough', 0.04))
        mask = g.inputs.get('Mask')
        if mask is not None and mask.is_linked and mask.links[0].from_node.type == 'TEX_IMAGE':
            og = bpy.data.node_groups.get('glTF Material Output')
            if og is None:
                og = bpy.data.node_groups.new('glTF Material Output', 'ShaderNodeTree')
                og.interface.new_socket('Occlusion', in_out='INPUT', socket_type='NodeSocketFloat')
            on_ = nt.nodes.new('ShaderNodeGroup'); on_.node_tree = og
            sep = nt.nodes.new('ShaderNodeSeparateColor'); nt.links.new(mask.links[0].from_node.outputs['Color'], sep.inputs[0])
            nt.links.new(sep.outputs['Red'], on_.inputs['Occlusion'])
        normal = g.inputs.get('Base Normal')
        if normal is not None and normal.is_linked: nt.links.new(normal.links[0].from_socket, pb.inputs['Normal'])
        nt.links.new(pb.outputs['BSDF'], on.inputs['Surface'])
        if alpha < 1:
            if hasattr(m, 'surface_render_method'): m.surface_render_method = 'BLENDED'
            else: m.blend_method = 'BLEND'
        m['idle'] = rec
        done.append(f"{m.name}={rec['kind']}")
    return done


def lift_groups(materials):
    """Shader Lab materials (idle.paint.worn@1, idle.glass.window@1 …) are ONE group node feeding the Material Output,
    with the Principled and its images inside. channel() cannot see into a group (flat grey + UNKNOWN), and glTF writes
    the group's first inner image raw as Base Color (modern-effort shell, 2026-10-14: confetti paint, white windscreen).
    Lift that Principled to the material level, in memory: constants are copied, group inputs are followed outward,
    every other input leaves the group through an added output (so it still evaluates inside the group and bakes).
    Nested groups lift inside-out; a group ending in anything but one Principled stays. Mirror: blender-dash
    blender/export_blend.py (_lift). Returns the lifted material names."""
    lifted_out = {}

    def lift(tree, gnode, out_sock, depth=0):
        gt = gnode.node_tree
        if not gt or depth > 8: return None
        gout = next((n for n in gt.nodes if n.type == 'GROUP_OUTPUT' and n.is_active_output), None)
        inner = gout and next((s for s in gout.inputs if s.identifier == out_sock.identifier), None)
        if not inner or not inner.is_linked: return None
        src = inner.links[0].from_node
        if src.type == 'GROUP': src = lift(gt, src, inner.links[0].from_socket, depth + 1)
        if not src or src.type != 'BSDF_PRINCIPLED': return None
        done = lifted_out.setdefault(gt.as_pointer(), {})
        pb = tree.nodes.new('ShaderNodeBsdfPrincipled')
        for attr in ('distribution', 'subsurface_method'):
            if hasattr(src, attr): setattr(pb, attr, getattr(src, attr))
        for i in src.inputs:
            o = next((s for s in pb.inputs if s.identifier == i.identifier), None)
            if o is None or i.type == 'SHADER': continue
            link = i.links[0] if i.is_linked and not i.links[0].is_muted else None
            if link is None:
                if hasattr(i, 'default_value'): _assign(o, i.default_value)
                continue
            n = link.from_node
            if n.type in ('VALUE', 'RGB'): _assign(o, link.from_socket.default_value); continue
            if n.type == 'GROUP_INPUT':
                outer = next(s for s in gnode.inputs if s.identifier == link.from_socket.identifier)
                if outer.is_linked: tree.links.new(outer.links[0].from_socket, o)
                elif hasattr(outer, 'default_value'): _assign(o, outer.default_value)
                continue
            ident = done.get(i.identifier)
            if ident is None:
                b = i.bl_idname
                kind = 'NodeSocketColor' if 'Color' in b else 'NodeSocketVector' if 'Vector' in b else 'NodeSocketFloat' if 'Float' in b else None
                if kind is None: continue
                ident = done[i.identifier] = gt.interface.new_socket('kit.' + i.name, in_out='OUTPUT', socket_type=kind).identifier
                gt.links.new(link.from_socket, next(s for s in gout.inputs if s.identifier == ident))
            tree.links.new(next(s for s in gnode.outputs if s.identifier == ident), o)
        for l in list(out_sock.links): tree.links.new(pb.outputs['BSDF'], l.to_socket)
        return pb

    names = []
    for m in materials:
        on = output_node(m) if m and m.node_tree else None
        if on is None: continue
        for l in list(on.inputs['Surface'].links):
            if l.from_node.type == 'GROUP' and lift(m.node_tree, l.from_node, l.from_socket): names.append(m.name)
    return names


class MaterialSwap:
    """Swaps materials' surfaces to an Emission of one channel and back. Works in a throwaway session (never saved),
    but restores the surface link anyway so later passes see the authored material."""

    def __init__(self, mats, glass=GLASS):
        self.mats = [m for m in mats if m and m.node_tree]; self.glass = glass; self.orig = {}
        for m in self.mats:
            on = output_node(m)
            if on is None: continue
            s = on.inputs['Surface']; v = on.inputs.get('Volume')
            self.orig[m.name] = (on, s.links[0].from_socket if s.is_linked else None)
            if v is not None:
                for l in list(v.links): m.node_tree.links.remove(l)        # a volume adds to every EMIT pass

    def _clean(self, m):
        nt = m.node_tree
        for n in [n for n in nt.nodes if n.name.startswith(TMP)]: nt.nodes.remove(n)

    def set(self, chan):
        for m in self.mats:
            if m.name not in self.orig: continue
            self._clean(m); nt = m.node_tree; on, src = self.orig[m.name]
            if src is not None: nt.links.new(src, on.inputs['Surface'])   # the authored surface again: channel() reads it
            em = nt.nodes.new('ShaderNodeEmission'); em.name = TMP + 'em'; em.inputs['Strength'].default_value = 1.0
            if chan == 'packed':                       # R rough, G metal, B alpha in one pass
                cc = nt.nodes.new('ShaderNodeCombineColor'); cc.name = TMP + 'pack'
                for ch, inp, dflt in (('rough', 'Red', 0.6), ('metal', 'Green', 0.0), ('alpha', 'Blue', 1.0)):
                    x = channel(nt, on.inputs['Surface'], ch, self.glass) if src is not None else None
                    if x is None: cc.inputs[inp].default_value = 0.0 if ch == 'alpha' and src is not None else dflt
                    else: nt.links.new(x, cc.inputs[inp])
                nt.links.new(cc.outputs[0], em.inputs['Color']); nt.links.new(em.outputs[0], on.inputs['Surface'])
                continue
            s = channel(nt, on.inputs['Surface'], chan, self.glass) if src is not None else None
            if s is None:
                em.inputs['Color'].default_value = {'color': (0.5, 0.5, 0.5, 1), 'rough': (0.6,) * 3 + (1,), 'metal': (0, 0, 0, 1),
                                                    'alpha': (1, 1, 1, 1) if src is not None else (1, 1, 1, 1)}[chan]
                if chan == 'alpha' and src is not None: em.inputs['Color'].default_value = (0, 0, 0, 1)
            else:
                nt.links.new(s, em.inputs['Color'])
            nt.links.new(em.outputs[0], on.inputs['Surface'])

    def restore(self):
        for m in self.mats:
            if m.name not in self.orig: continue
            self._clean(m); on, src = self.orig[m.name]
            if src is not None: m.node_tree.links.new(src, on.inputs['Surface'])


def has_emission(mats):
    """Does any material emit light (Principled emission, an Emission shader)?"""
    for m in mats:
        if not m or not m.node_tree: continue
        for n in m.node_tree.nodes:
            if n.type == 'BSDF_PRINCIPLED':
                s = n.inputs['Emission Strength']; c = n.inputs['Emission Color']
                if (s.is_linked or s.default_value > 0) and (c.is_linked or max(tuple(c.default_value)[:3]) > 0): return True
            if n.type == 'EMISSION':
                s = n.inputs['Strength']; c = n.inputs['Color']
                if (s.is_linked or s.default_value > 0) and any(l.to_node.type != 'OUTPUT_MATERIAL' or True for l in n.outputs[0].links):
                    if not n.name.startswith(TMP) and n.outputs[0].is_linked: return True
    return False


def pin_object_coords(objs_meshes):
    """Before realised meshes are joined into one object, keep each part's own texture coordinates so procedural
    materials look as they did: Texture Coordinate 'Object'/'Generated' and Object Info 'Location'/'Random'/'Color'
    read per-vertex attributes written here. objs_meshes: [(source object, mesh in its own object space, world matrix)]."""
    import numpy as np, random
    for src, me, mw in objs_meshes:
        n = len(me.vertices)
        if n == 0: continue
        co = np.empty(n * 3, np.float32); me.vertices.foreach_get('co', co); co = co.reshape(n, 3)
        d = getattr(src, 'data', None)
        if d is not None and hasattr(d, 'texspace_location'):
            loc = np.array(d.texspace_location); size = np.array(d.texspace_size)
            lo, span = loc - size, np.maximum(2 * size, 1e-9)
        else:
            lo = co.min(0); span = np.maximum(co.max(0) - lo, 1e-9)
        gen = (co - lo) / span
        for nm, val in (('kit_obj', co), ('kit_gen', gen)):
            a = me.attributes.new(nm, 'FLOAT_VECTOR', 'POINT'); a.data.foreach_set('vector', val.ravel())
        rnd = random.Random(hash((src.name, tuple(round(v, 4) for v in mw.translation)))).random()
        oc = tuple(src.color)[:3] if hasattr(src, 'color') else (1, 1, 1)
        for nm, kind, val in (('kit_loc', 'FLOAT_VECTOR', np.tile(np.array(mw.translation, np.float32), n)),
                              ('kit_rand', 'FLOAT', np.full(n, rnd, np.float32)),
                              ('kit_ocol', 'FLOAT_COLOR', np.tile(np.array(oc + (1.0,), np.float32), n))):
            a = me.attributes.new(nm, kind, 'POINT')
            a.data.foreach_set({'FLOAT_VECTOR': 'vector', 'FLOAT': 'value', 'FLOAT_COLOR': 'color'}[kind], val.ravel())


def repoint_object_coords(trees):
    """In the given node trees (materials' and their groups'), feed Texture Coordinate Object/Generated, Object Info
    Location/Random/Color, and procedural textures with an unlinked Vector (implicitly Generated) from the attributes
    pin_object_coords wrote. Returns how many links were rewired."""
    import bpy
    k = 0
    seen = set()
    def visit(nt):
        nonlocal k
        if nt is None or nt.as_pointer() in seen: return
        seen.add(nt.as_pointer())          # NOT nt.name: every material's tree is called 'Shader Nodetree'
        for n in list(nt.nodes):
            if n.type == 'GROUP' and n.node_tree: visit(n.node_tree)
            if n.type == 'TEX_COORD' and n.object is None:
                for out, attr in (('Object', 'kit_obj'), ('Generated', 'kit_gen')):
                    o = n.outputs[out]
                    if not o.links: continue
                    a = nt.nodes.new('ShaderNodeAttribute'); a.attribute_type = 'GEOMETRY'; a.attribute_name = attr
                    a.location = n.location; a.label = 'kit ' + out
                    for l in list(o.links): nt.links.new(a.outputs['Vector'], l.to_socket); k += 1
            # a procedural texture with NO vector link reads Generated implicitly (Cycles); after the join that would be
            # the joined mesh's box (synth test 2026-10-13: a 4x checker decal baked as stripes): feed it kit_gen too
            if (n.type.startswith('TEX_') and n.type not in ('TEX_IMAGE', 'TEX_ENVIRONMENT', 'TEX_COORD', 'TEX_SKY')
                    and 'Vector' in n.inputs and not n.inputs['Vector'].is_linked and n.inputs['Vector'].enabled):
                a = nt.nodes.new('ShaderNodeAttribute'); a.attribute_type = 'GEOMETRY'; a.attribute_name = 'kit_gen'
                a.location = (n.location.x - 200, n.location.y); a.label = 'kit Generated (implicit)'
                nt.links.new(a.outputs['Vector'], n.inputs['Vector']); k += 1
            if n.type == 'OBJECT_INFO':
                for out, attr, sock in (('Location', 'kit_loc', 'Vector'), ('Random', 'kit_rand', 'Fac'), ('Color', 'kit_ocol', 'Color')):
                    o = n.outputs.get(out)
                    if o is None or not o.links: continue
                    a = nt.nodes.new('ShaderNodeAttribute'); a.attribute_type = 'GEOMETRY'; a.attribute_name = attr
                    for l in list(o.links): nt.links.new(a.outputs[sock], l.to_socket); k += 1
    for t in trees: visit(t)
    return k


# ------------------------------------------------------------------------------- textured meshes without UVs (owner)
# Finding 2026-10-12 (a train car guide tyres): a mesh with NO UV layer whose material samples an image through
# TexCoord(UV) -> Mapping exports as texCoord -1 with no TEXCOORD_0; three.js then shows per-pixel speckle that looks
# like blinking (only 17 of 725 primitives of that GLB had UVs). Before an export or a bake such a mesh gets a box UV
# in metres (the material's Mapping keeps its tiling); after an export the GLB is checked and the tool fails.
def usable_uv(me):
    import numpy as np
    uv = next((u for u in me.uv_layers if u.active_render), me.uv_layers.active) if me.uv_layers else None
    if uv is None or not len(uv.data): return False
    v = np.empty(len(uv.data) * 2, np.float32); uv.data.foreach_get('uv', v); v = v.reshape(-1, 2)
    return bool(np.isfinite(v).all() and np.ptp(v, axis=0).min() > 1e-6)


def samples_image(m):
    """Does anything feeding the material's surface (any input of any shader it reaches) come from an image texture?"""
    if not m or not m.node_tree: return False
    on = output_node(m)
    if on is None: return False
    seen = set(); stack = [s for s in on.inputs if s.is_linked]
    while stack:
        s = stack.pop()
        for l in s.links:
            n = l.from_node
            if n in seen: continue
            seen.add(n)
            if n.type == 'TEX_IMAGE': return True
            if n.type == 'GROUP' and n.node_tree and any(x.type == 'TEX_IMAGE' for x in n.node_tree.nodes): return True
            stack += [i for i in n.inputs if i.is_linked]
    return False


def box_uv(me, name='UVMap'):
    """Box projection in metres on a mesh (no edit mode needed); made the active and render UV."""
    import bmesh
    bm = bmesh.new(); bm.from_mesh(me)
    lay = bm.loops.layers.uv.get(name) or bm.loops.layers.uv.new(name)
    for f in bm.faces:
        ax = max(range(3), key=lambda i: abs(f.normal[i])); a, b = [i for i in range(3) if i != ax]
        for l in f.loops: l[lay].uv = (l.vert.co[a], l.vert.co[b])
    bm.to_mesh(me); bm.free()
    me.uv_layers.active = me.uv_layers[name]; me.uv_layers[name].active_render = True


def fix_textured_without_uv(meshes):
    """meshes: iterable of Mesh datablocks (their own materials). Gives every textured one without usable UVs a box UV.
    Returns the names fixed."""
    fixed = []
    for me in meshes:
        if me is None or usable_uv(me): continue
        if any(samples_image(m) for m in me.materials):
            if me.library: me = me.make_local()
            for u in [u for u in me.uv_layers]: me.uv_layers.remove(u)
            box_uv(me); fixed.append(me.name)
    return fixed


def glb_texcoord_faults(path):
    """Primitives whose material uses a texture (base colour, metallic-roughness, normal, occlusion, emissive) but that
    carry no TEXCOORD_<n> for it. Returns ['mesh name (material): TEXCOORD_n missing', ...]."""
    j = glb_json(path); mats = j.get('materials', []); out = []
    for me in j.get('meshes', []):
        for pr in me.get('primitives', []):
            if 'material' not in pr: continue
            m = mats[pr['material']]; pbr = m.get('pbrMetallicRoughness', {})
            infos = [pbr.get('baseColorTexture'), pbr.get('metallicRoughnessTexture'), m.get('normalTexture'),
                     m.get('occlusionTexture'), m.get('emissiveTexture')]
            for ti in infos:
                if not ti: continue
                tc = ti.get('texCoord', 0)
                if tc < 0 or f'TEXCOORD_{tc}' not in pr.get('attributes', {}):
                    out.append(f'{me.get("name", "?")} ({m.get("name", "?")}): TEXCOORD_{tc} missing'); break
    return sorted(set(out))


def uv_overlap_share(me, layer=None):
    """Share of triangles whose UV centroid duplicates another's: faces sharing texture space bake over each other,
    last write wins (a car 2026-10-13: a Solidify wall's inner skin kept the outer skin's UVs, so the outer steel
    took the inner wall's metallic 0 and looked like white plastic). > 0.01 = unwrap afresh. Same rule as the
    dashboard exporter's _uv_overlaps."""
    import numpy as np
    uv = me.uv_layers.get(layer) if layer else (next((u for u in me.uv_layers if u.active_render), me.uv_layers.active) if me.uv_layers else None)
    if uv is None or not len(me.polygons): return 0.0
    me.calc_loop_triangles(); n = len(me.loop_triangles)
    if not n: return 0.0
    loops = np.empty(n * 3, np.int32); me.loop_triangles.foreach_get('loops', loops)
    u = np.empty(len(uv.data) * 2, np.float32); uv.data.foreach_get('uv', u)
    t = u.reshape(-1, 2)[loops].reshape(n, 3, 2)
    area = np.abs((t[:, 1, 0] - t[:, 0, 0]) * (t[:, 2, 1] - t[:, 0, 1]) - (t[:, 1, 1] - t[:, 0, 1]) * (t[:, 2, 0] - t[:, 0, 0]))
    t = t[area > 1e-12]                                   # degenerate triangles cover no texel
    if not len(t): return 0.0
    _, counts = np.unique(np.round(t.mean(1), 5), axis=0, return_counts=True)
    return float(counts[counts > 1].sum() / len(t))
