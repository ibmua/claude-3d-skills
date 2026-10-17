#!/usr/bin/env python3
"""pbr_check.py: refuse physically wrong materials (white-plastic "steel", dark metal F0, lost clear coat, no night glow,
bad normal maps, double-sided opaque walls) in a GLB or in a .blend, before the owner finds them.

GLB (system python with numpy + Pillow, or Blender's python):
  python3 pbr_check.py FILE.glb [--class-map asset.json] [--version near|mid|far] [--family train] [--against ABOVE.glb]
                       [--samples 20000] [--json OUT.json] [--heatmap DIR] [--strict] [--quiet]
.blend (read inside Blender; either form):
  python3 pbr_check.py FILE.blend [--collection C] [--class-map asset.json] [--bake 64] [--for-bake]
                       [--against EXPORTED.glb] [--json OUT.json] [--strict]     starts Blender itself (headless, -t 8,
                       nice 10, a 12 GB scope; BLENDER=/path overrides) and returns its result code
  blender -b FILE.blend --python pbr_check.py -- [the same options]
  An input driven by nodes (linked) is NOT measured without --bake N: the rules that read it are not judged and one
  `INFO M0 ... not measured` line says which (never a WARN or an ERROR on a stand-in value). --bake 64 measures base
  colour, roughness, metallic and a linked Coat Weight (a coat linked inside a node group stays "not measured").
  python3 pbr_check.py --rules          every rule with its threshold, severity and source

Output: one block per surface group (a material, or a slot of a live-shader material), one line per finding
`SEVERITY RULE 'group' share of area: what was measured. Decide: ...`, and last `PBR RESULT: PASS|WARN n|FAIL n`.
Exit 0 on PASS or WARN, 2 on FAIL (`--strict` also fails on WARN).

What it measures (GLB): area-weighted random points over every triangle (node transforms applied), UVs interpolated,
base colour (sRGB -> linear) x factor x COLOR_0, metallic/roughness x factors with glTF defaults (metallic 1,
roughness 1), emissive x factor x KHR_materials_emissive_strength, KHR_materials_clearcoat, doubleSided, alphaMode,
TANGENT, image sizes and types; every share is a fraction of surface area. Live shader slots are judged by what the
game will draw, not by their fallback factors:
  * `extras.idle` (shader library, research/shader-assets-20261013): the kind's parameters, per slot (a material with
    `table` + `idmap` is split by the slot id in occlusionTexture.a);
  * `extras.shader_slot = train.surface.batch.v1` (the shipped train batches): COLOR_0, `_TRAIN_PBR`, `_TRAIN_EMIT`.
Classes come from `--class-map` (asset.json "materials"), the shader kind, the game contract's slot names, or a guess
from the name (reported as guessed; a guessed class never makes an ERROR on its own).

Python API (no side effects; nothing is written unless asked):
  from pbr_check import check_glb, check_blend
  r = check_glb('x-near.glb', class_map='asset.json', version='near', against='x-original.glb')
  r.ok, r.result ('PASS'|'WARN 2'|'FAIL 3'), r.lines, r.findings (r.errors(), r.has('M2', 'M5')), r.to_json()
  r = check_blend(collection='CAR', class_map='asset.json', for_bake=True)      # inside Blender
Spec and evidence: the toolkit research notes section 2; build notes:
the toolkit research notes
"""
import fnmatch, io, json, math, os, re, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path: sys.path.insert(0, HERE)

# ------------------------------------------------------------------------------------------------------- the rules
# id: (what, threshold and severity, where the number comes from). Severity labels: ERROR fails, WARN warns, INFO notes.
RULES = {
    'M0': ('.blend only: a rule was not judged because an input it reads is driven by nodes and was not measured', 'INFO',
           'pilot-lamp 2026-10-13: a stand-in value was reported as "metal too dark" and "no clear coat"'),
    'M1': ('metallic in-between (0.1-0.9) without clear coat', '>5 % of the group WARN, >20 % ERROR; class layered: INFO',
           'convention: Adobe PBR guide p2, Unreal "0 or 1", Khronos 3DC v1.0 ("avoid metalness other than 0 and 1")'),
    'M2': ('white plastic: 0.1<m<0.9 and base Y>0.5 and clear coat <0.5', '>=2 % ERROR',
           'measured: two train cars 2026-10-12 (stl.alu 0.55, light base, no coat)'),
    'M3': ('metal too dark: m>=0.9 and base Y<0.35', '>10 % of the metal area WARN',
           'measured: physicallybased.info v2 (CC0) - no common metal F0 below Y 0.40 (titanium); Adobe 180-255 sRGB'),
    'M4': ('declared metal off its reference F0', 'median Y off by >0.10, or hue off (chromaticity >0.04) ERROR',
           'measured: physicallybased.info v2 (CC0, updated 2026-10-11)'),
    'M5': ('declared class contradicts the values', 'bare_metal median m<0.9; dielectric class median m>0.1; '
           'metallic_paint in-between without coat: ERROR (guessed class: WARN)', 'spec glTF + convention 3DC fig 5.31'),
    'M6': ('non-metal albedo below 30 sRGB (Y<0.0123)', '>5 % WARN', 'convention: Adobe p2, Lagarde 2011; '
           'Khronos CarConcept goes lower, so WARN only'),
    'M7': ('non-metal albedo above 243 / 250 sRGB', '>5 % WARN / >1 % ERROR', 'convention + physicallybased.info '
           '(snow .85, white paint .77)'),
    'M8': ('roughness <0.02 on an opaque non-glass surface', '>5 % WARN', 'taste (Roblox reference, Polycount)'),
    'M9': ('roughness or metallic constant at a default (0.5 or 1.0) on a textured material', '>90 % INFO', 'derived'),
    'M10': ('metallicFactor omitted (= 1.0, metal) on a non-metal without a metallic texture', 'WARN',
            'spec: glTF default metallicFactor 1'),
    'M11': ('clear coat lost: coat in the original / version above, none here (or a coated in-between metal headed '
            'for a bake that has no coat channel)', 'ERROR', 'derived from the pipeline: bake.py has no coat channel'),
    'E1': ('night lights declared but this version has no lit texels (max channel >0.02)', 'ERROR',
           'measured: both shipped train rebuilds dark at night (lodcmp night 21-51 %)'),
    'E2': ('lit share differs from the version above by more than x0.7-1.3', 'WARN', 'taste'),
    'E3': ('window emissive peak >1.5 or <0.2 (linear, night value)', 'WARN',
           'derived: Khronos PBR Neutral compresses above 0.76, reads white above ~1.5'),
    'G1': ('doubleSided on an opaque surface', 'ERROR unless declared a sheet ("sheet": true)',
           'spec glTF + our blinking faults (back-to-back faces)'),
    'G2': ('normal map blue <=0.5 on covered texels', '>0.1 % ERROR', 'spec glTF (SHOULD NOT point inward)'),
    'G3': ('normal map vector length error, 99th percentile of covered texels', '>0.1 WARN',
           'measured: a car JPEG normals p99 .32-.45 vs PNG .004'),
    'G4': ('normal map without TANGENT', 'ERROR', 'spec glTF 3.7.2.1; three derives other tangents'),
    'G5': ('texture not a power of two / not a multiple of 4 / larger than 2048', 'ERROR / ERROR / WARN',
           'KTX Artist Guide, glTF 3.8.4.5'),
    'G6': ('metallic-roughness or normal map larger than base colour; normal map as JPEG', 'WARN',
           'KTX Artist Guide, 3DC'),
    'G7': ('image colour space wrong for its role (.blend)', 'ERROR', 'spec glTF (colour sRGB, data linear)'),
    'G8': ('BLEND alpha on a non-glass material; alpha channel on an opaque colour texture', 'WARN', 'glTF, 3DC'),
    'G9': ('occlusionTexture (R x strength; three.js aoMap: hemisphere + environment light only): median and dark share '
           'per material', 'INFO; median <0.5 WARN', 'derived (bake.py ao 2026-10-13): a baked AO whose median texel is '
           'below 0.5 takes most of the ambient light off the whole material: inverted, too long a distance, or rays '
           'starting inside the hull'),
    'T1': ('colour atlas median px/m against the band need (switch.json, 1080p)', '<0.7x WARN, >2.5x INFO',
           'derived: px/m = rows / (2 d tan(fov/2)); thresholds are taste'),
    'S1': ('class-map entry without a "source"', 'WARN', 'agents REPORT R8: mark invented numbers'),
}

DECIDE = {
    'M1': 'what IS it? bare metal (metallic 1, real F0: stainless Y .64, aluminium .92; matref.py) / metallic paint '
          '(keep the value, add clear coat >= 0.5: KHR_materials_clearcoat or kind paint.metallic) / paint, dirt, wear '
          '(metallic 0); declare it in asset.json "materials"',
    'M2': 'bare metal (1.0, F0 Y .64 stainless / .92 aluminium) / metallic paint (+ clear coat) / paint (0)',
    'M3': 'metal F0 is never this dark: set the metal\'s reference colour (matref.py <metal>); dirt or paint over metal '
          'is a metallic-0 layer, not a darker F0',
    'M4': 'set the base colour to the reference F0 (matref.py <metal>)',
    'M5': 'fix the values, or correct the class in asset.json "materials"',
    'M6': 'darkest real dielectrics are Y .02-.04 (charcoal, asphalt, tyre .023); raise it unless intended',
    'M7': 'brightest real dielectrics: snow .85, white paint .77 (<= 243 sRGB)',
    'M8': 'below 0.02 is a mirror; paint and plastic >= 0.05',
    'M10': 'write metallicFactor 0 for a non-metal (the glTF default 1 is metal)',
    'M11': 'keep the coat: KHR_materials_clearcoat / kind paint.metallic, or convert per 3DC (metallic 0, rough .15-.3)',
    'E1': 'author night glow as emissive (windows: emissive glass or a glow card; lamps: emissive faces) and keep it in '
          'every version; light.* empties alone add only spill',
    'E2': 'keep the lit area through the version change (window strips, a per-version emissive gain)',
    'E3': 'lit windows 0.4-1.2 linear (>= 1.5 reads white under PBR Neutral, < 0.2 vanishes at distance)',
    'G1': 'single-sided opaque walls; declare a real sheet as "sheet": true in asset.json "materials"',
    'G2': 're-bake; store normals as PNG (JPEG rings), renormalise',
    'G3': 'store normals lossless (PNG now, UASTC KTX2 later)',
    'G4': 'export TANGENT (MikkTSpace) with the normal map',
    'G5': 'resize to a power of two, at most 2048',
    'G6': 'metallic-roughness and normal no larger than base colour; normal maps PNG',
    'G7': 'Base Color / Emission images sRGB; roughness, metallic, alpha, normal Non-Color',
    'G8': 'BLEND only for glass on its own primitive; cut-outs MASK 0.5; drop the alpha channel of opaque colour',
    'G9': 'look at the bake\'s <prefix>_ao.png: a shorter bake.py --ao-distance, a cage outside the hull, not inverted',
    'T1': 'atlas size or packing for this band',
    'S1': 'add "source": physicallybased.info | measured | judged: <why> | inferred',
}

# Material classes. A class says what the surface IS; the rules use it.
DIELECTRIC = {'paint', 'plastic', 'rubber', 'glass', 'fabric', 'wood', 'stone', 'ceramic', 'leather', 'dielectric',
              'dirt', 'sheet', 'foliage', 'decal'}
CLASSES = DIELECTRIC | {'bare_metal', 'metallic_paint', 'layered', 'emissive', 'mixed', 'unknown'}
KIND_CLASS = {'metal.brushed': 'bare_metal', 'paint.worn': 'paint', 'paint.metallic': 'metallic_paint',
              'rubber': 'rubber', 'lamp.emissive': 'emissive', 'glass.window': 'glass', 'fabric.weave': 'fabric',
              'wood.varnished': 'wood'}
# name guess, first match wins (lowercase name)
GUESS = [
    (r'metallic.?paint|body-metallic|metallic', 'metallic_paint'),
    (r'window.?lit|lit.?window|lamp|led\b|led-|headl|tail.?l|light\b|emiss|glow|neon|\bsign', 'emissive'),
    (r'glass|lens|windscreen|windshield|\bpane', 'glass'),
    (r'rubber|tyre|tire|gasket', 'rubber'),
    (r'surface|atlas|bake|batch', 'mixed'),
    (r'chrome|alu|stainless|steel|brass|copper|bronze|iron|zinc|nickel|titan|metal', 'bare_metal'),
    (r'paint|livery|body|stripe|ceramic|enamel', 'paint'),
    (r'wood|timber|oak|varnish|plank', 'wood'),
    (r'fabric|seat|cloth|uphol|carpet|curtain', 'fabric'),
    (r'plastic', 'plastic'),
    (r'concrete|stone|brick|asphalt|tile|plaster', 'stone'),
    (r'grime|dirt|rust|soot', 'dirt'),
]
# train.surface.batch.v1 kind codes (assets-lib/train/shaders/train-batches.mjs: 1 roof, 2 paint, 3 timber, 4 cab lamp,
# 5 interior lamp, 0 other). Night emissive there = _TRAIN_EMIT x (0.12 + 1.8 night).
BATCH_KINDS = {0: ('other', 'mixed'), 1: ('roof', None), 2: ('paint', 'paint'), 3: ('timber', 'wood'),
               4: ('cab lamp', 'emissive'), 5: ('interior lamp', 'emissive')}
BATCH_NIGHT = 1.92
# game names whose night glow the game draws itself (GAME-CONTRACT.md: cabin glow, LED lamps, own glass shader)
GAME_LIT = ('interior-warm-grey', 'seat-ocean-fabric', 'led-ivory', 'glass-')
GAME_DEFAULT_FAMILIES_NIGHT = {'train': 'GAME-CONTRACT.md: cabin glow at night (interior-warm-grey, seat-ocean-fabric), '
                                        'LED-ivory lamps, lit windows'}
LUM = (0.2126, 0.7152, 0.0722)
SEVERITY_RANK = {'ERROR': 3, 'WARN': 2, 'INFO': 1}
RESEARCH_LIB = ['<game>/research/shader-assets-20261013/library',
                '<game>/research/shader-assets-20261013/library']


# ------------------------------------------------------------------------------------------------------ small helpers
def _np():
    import numpy as np
    return np


def srgb2lin(c):
    np = _np()
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin2srgb8(c):
    np = _np()
    c = np.clip(c, 0, 1)
    return 255 * np.where(c <= 0.0031308, 12.92 * c, 1.055 * c ** (1 / 2.4) - 0.055)


def luminance(rgb):
    np = _np(); a = np.asarray(rgb)
    if a.dtype != np.float32: a = a.astype(np.float64)
    return a[..., :3] @ np.array(LUM, a.dtype)


def pct(x, q):
    np = _np()
    return float(np.percentile(x, q)) if len(x) else float('nan')


def fmt_q(x):
    return '-' if not len(x) else ' '.join(f'{pct(x, q):.3f}' for q in (5, 50, 95))


def _jsonish(v):
    if isinstance(v, str):
        try: return json.loads(v)
        except Exception: return v
    return v


class Finding:
    __slots__ = ('rule', 'sev', 'group', 'share', 'value', 'threshold', 'msg', 'decide', 'where')

    def __init__(self, rule, sev, group, msg, share=None, value=None, threshold=None, where=None, decide=None):
        self.rule, self.sev, self.group, self.msg = rule, sev, group, msg
        self.share, self.value, self.threshold, self.where = share, value, threshold, where
        self.decide = DECIDE.get(rule) if decide is None else decide

    def line(self):
        s = f'{self.sev} {self.rule} \'{self.group}\''
        if self.share is not None: s += f' {self.share:.1%} of area'
        s += f': {self.msg}'
        if self.decide: s += f'. Decide: {self.decide}.'
        return s

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}


class Result:
    """ok: no ERROR (and with strict no WARN); result: 'PASS' | 'WARN n' | 'FAIL n'; lines: the printed report."""

    def __init__(self, path, findings, lines, groups, meta, strict=False):
        self.path, self.findings, self.lines, self.groups, self.meta, self.strict = path, findings, lines, groups, meta, strict
        ne = sum(f.sev == 'ERROR' for f in findings); nw = sum(f.sev == 'WARN' for f in findings)
        fail = ne + (nw if strict else 0)
        self.result = f'FAIL {fail}' if fail else (f'WARN {nw}' if nw else 'PASS')
        self.ok = not fail
        self.lines = lines + [f'PBR RESULT: {self.result}']

    def errors(self): return [f for f in self.findings if f.sev == 'ERROR']

    def has(self, *rules, sev=('ERROR',)):
        """Findings of these rules (default: ERRORs only), e.g. r.has('M2', 'M5', 'M11') for the bake pre-flight."""
        sev = (sev,) if isinstance(sev, str) else sev
        return [f for f in self.findings if f.rule in rules and f.sev in sev]

    def text(self): return '\n'.join(self.lines)

    def to_json(self):
        return {'file': self.path, 'result': self.result, 'ok': self.ok, 'strict': self.strict, **self.meta,
                'counts': {s: sum(f.sev == s for f in self.findings) for s in ('ERROR', 'WARN', 'INFO')},
                'groups': self.groups, 'findings': [f.to_dict() for f in self.findings],
                'rules': {k: {'what': v[0], 'threshold': v[1], 'source': v[2]} for k, v in RULES.items()}}


# ------------------------------------------------------------------------------------------------------ class map
def load_class_map(cm):
    """asset.json path, its dict, or a {"materials": ...} / plain {name: entry} dict -> (entries {pattern: entry},
    lights declared?, family, source path). A "materials" LIST (the family record's list of names) carries no class."""
    if cm is None: return {}, False, None, None
    src = None
    if isinstance(cm, str):
        src = cm
        with open(cm) as f: cm = json.load(f)
    entries, lights, family = {}, False, None
    if isinstance(cm, dict):
        family = cm.get('family') if isinstance(cm.get('family'), str) else None
        lights = bool(cm.get('lights'))
        mats = cm.get('materials', cm if 'materials' not in cm and all(isinstance(v, dict) for v in cm.values()) else {})
        if isinstance(mats, dict):
            for k, v in mats.items():
                if isinstance(v, str): v = {'class': v}
                if isinstance(v, dict): entries[k] = v
    return entries, lights, family, src


def find_asset_json(path):
    """The asset record beside a file or up to two folders above it (export/x.glb -> <asset>/asset.json), or None."""
    d = os.path.dirname(os.path.abspath(path)) if path else None
    for _ in range(3):
        if not d: break
        p = os.path.join(d, 'asset.json')
        if os.path.exists(p): return p
        d = os.path.dirname(d)
    return None


def class_entry(entries, *names):
    """The class-map entry for the first name that matches a key exactly, then by glob or substring."""
    for n in names:
        if n and n in entries: return n, entries[n]
    for n in names:
        if not n: continue
        for k, v in entries.items():
            if fnmatch.fnmatchcase(n, k) or (not any(c in k for c in '*?[') and k.lower() in n.lower()):
                return k, v
    return None, None


def guess_class(name):
    """Class from the name: the last dotted part first ('stl.alu' -> alu; 'stl.' is a project prefix), then the whole."""
    low = (name or '').lower()
    for part in ([low.rsplit('.', 1)[-1]] if '.' in low else []) + [low]:
        for rx, cls in GUESS:
            if re.search(rx, part): return cls
    return None


_LIB = {}


def library():
    """kinds.json and game-slots.json of the shader library (research/shader-assets-20261013/library), if reachable."""
    if _LIB: return _LIB
    dirs = [os.environ.get('PBR_CHECK_LIBRARY')] if os.environ.get('PBR_CHECK_LIBRARY') else []
    try:
        import _kit
        p = (_kit.switch('train') or {}).get('slots')
        if p: dirs.append(os.path.dirname(p))
    except BaseException:
        pass
    for d in dirs + RESEARCH_LIB:
        if d and os.path.exists(os.path.join(d, 'kinds.json')):
            try:
                with open(os.path.join(d, 'kinds.json')) as f: _LIB['kinds'] = {k['kind'].split('@')[0]: k for k in json.load(f)['kinds']}
                gs = os.path.join(d, 'game-slots.json')
                if os.path.exists(gs):
                    with open(gs) as f: _LIB['slots'] = json.load(f)['slots']
                _LIB['dir'] = d
                break
            except Exception:
                continue
    _LIB.setdefault('kinds', {}); _LIB.setdefault('slots', {}); _LIB.setdefault('dir', None)
    return _LIB


def kind_defaults(kind):
    k = library()['kinds'].get(kind.split('@')[0])
    return {p['name']: p['default'] for p in k['params']} if k else {}


def game_slot(name):
    """(slot name, entry) of the game contract whose name the material carries (substring), or (None, None)."""
    low = (name or '').lower()
    for s, e in library()['slots'].items():
        if s.lower() in low: return s, e
    return None, None


def metal_ref(metal, any_class=False):
    """The measured reference of a declared metal (matref lookup; 'physicallybased:' prefix allowed), or None."""
    try:
        import matref
        r = matref.lookup(str(metal))
        return r if r and (any_class or r.get('metallic', 0) >= 0.5) else None
    except Exception:
        return None


# ------------------------------------------------------------------------------------------------------ GLB reading
CT = {5120: 'i1', 5121: 'u1', 5122: 'i2', 5123: 'u2', 5125: 'u4', 5126: 'f4'}
NORM = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0, 5125: 4294967295.0}
NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


class Gltf:
    def __init__(self, path):
        self.path = path; self.dir = os.path.dirname(os.path.abspath(path)); self.bins = {}
        with open(path, 'rb') as f: b = f.read()
        if b[:4] == b'glTF':
            off = 12; self.j = None
            while off < len(b):
                ln, typ = struct.unpack_from('<II', b, off); chunk = b[off + 8: off + 8 + ln]
                if typ == 0x4E4F534A: self.j = json.loads(chunk)
                elif typ == 0x004E4942: self.bins[0] = chunk
                off += 8 + ln
        else:
            self.j = json.loads(b)
        self._acc, self._img, self.img_info = {}, {}, {}

    def buffer(self, i):
        if i not in self.bins:
            uri = self.j['buffers'][i].get('uri', '')
            if uri.startswith('data:'):
                import base64
                self.bins[i] = base64.b64decode(uri.split(',', 1)[1])
            else:
                from urllib.parse import unquote
                with open(os.path.join(self.dir, unquote(uri)), 'rb') as f: self.bins[i] = f.read()
        return self.bins[i]

    def view(self, i):
        bv = self.j['bufferViews'][i]; buf = self.buffer(bv.get('buffer', 0)); o = bv.get('byteOffset', 0)
        return buf[o: o + bv['byteLength']], bv.get('byteStride')

    def acc(self, i):
        if i in self._acc: return self._acc[i]
        np = _np(); a = self.j['accessors'][i]; ct = a['componentType']; n = NC[a['type']]; cnt = a['count']
        dt = np.dtype(CT[ct]).newbyteorder('<')
        if 'bufferView' in a:
            data, stride = self.view(a['bufferView']); o = a.get('byteOffset', 0); es = dt.itemsize * n
            stride = stride or es
            raw = np.frombuffer(data, np.uint8, count=stride * (cnt - 1) + es, offset=o) if cnt else np.zeros(0, np.uint8)
            out = np.lib.stride_tricks.as_strided(raw, (cnt, es), (stride, 1)).copy().view(dt).reshape(cnt, n) \
                if cnt else np.zeros((0, n), dt)
        else:
            out = np.zeros((cnt, n), dt)
        out = out.astype(np.float64)
        if a.get('normalized') and ct in NORM: out /= NORM[ct]
        sp = a.get('sparse')
        if sp:
            idx = self._raw(sp['indices'], sp['count'], 1, sp['indices']['componentType']).ravel().astype(int)
            val = self._raw(sp['values'], sp['count'], n, ct)
            if a.get('normalized') and ct in NORM: val = val / NORM[ct]
            out[idx] = val
        self._acc[i] = out
        return out

    def _raw(self, ref, cnt, n, ct):
        np = _np(); data, _ = self.view(ref['bufferView']); dt = np.dtype(CT[ct]).newbyteorder('<')
        return np.frombuffer(data, dt, count=cnt * n, offset=ref.get('byteOffset', 0)).reshape(cnt, n).astype(np.float64)

    def image_bytes(self, src):
        im = self.j['images'][src]
        if 'bufferView' in im: return self.view(im['bufferView'])[0], im.get('mimeType', '')
        uri = im.get('uri', '')
        if uri.startswith('data:'):
            import base64
            head, data = uri.split(',', 1)
            return base64.b64decode(data), head[5:].split(';')[0]
        from urllib.parse import unquote
        p = os.path.join(self.dir, unquote(uri))
        mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'webp': 'image/webp',
                'ktx2': 'image/ktx2'}.get(p.rsplit('.', 1)[-1].lower(), '')
        with open(p, 'rb') as f: return f.read(), mime

    def tex_source(self, tex_index):
        t = self.j['textures'][tex_index]; src = t.get('source')
        for e in (t.get('extensions') or {}).values():
            if isinstance(e, dict) and 'source' in e: src = e['source'] if src is None else src
        return src, t.get('sampler')

    def image(self, src):
        """(H, W, 4) uint8 RGBA, row 0 = top (glTF UV v = 0), or None (KTX2 / undecodable). Info in img_info[src]."""
        if src in self._img: return self._img[src]
        data, mime = self.image_bytes(src); info = {'mime': mime, 'bytes': len(data), 'name': self.j['images'][src].get('name')}
        arr = None
        if data[:12] == b'\xabKTX 20\xbb\r\n\x1a\n':
            info['mime'] = 'image/ktx2'; info['w'], info['h'] = struct.unpack_from('<II', data, 20); info['mode'] = 'ktx2'
        else:
            arr, mode = decode_image(data)
            if arr is not None: info['h'], info['w'] = arr.shape[:2]; info['mode'] = mode
        self.img_info[src] = info; self._img[src] = arr
        return arr

    def world_prims(self):
        """[(node index, node name, world 4x4, primitive)] for every mesh node of the default scene."""
        np = _np(); j = self.j; nodes = j.get('nodes', []); out = []
        def local(nd):
            if 'matrix' in nd: return np.array(nd['matrix'], np.float64).reshape(4, 4).T
            t = nd.get('translation', [0, 0, 0]); r = nd.get('rotation', [0, 0, 0, 1]); s = nd.get('scale', [1, 1, 1])
            x, y, z, w = r
            R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                          [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                          [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
            M = np.eye(4); M[:3, :3] = R * np.array(s)[None, :]; M[:3, 3] = t
            return M
        scenes = j.get('scenes')
        if scenes: roots = scenes[j.get('scene', 0)].get('nodes', [])
        else:
            child = {c for nd in nodes for c in nd.get('children', [])}
            roots = [i for i in range(len(nodes)) if i not in child]
        stack = [(r, np.eye(4)) for r in roots]
        while stack:
            i, P = stack.pop(); nd = nodes[i]; W = P @ local(nd)
            if 'mesh' in nd:
                for pr in j['meshes'][nd['mesh']]['primitives']: out.append((i, nd.get('name', f'node{i}'), W, pr))
            stack += [(c, W) for c in nd.get('children', [])]
        return out


def decode_image(data):
    """Bytes -> ((H, W, 4) uint8, PIL-like mode string). Pillow first; inside Blender without Pillow, bpy."""
    np = _np()
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data)); mode = im.mode
        if mode == 'P' and 'transparency' in im.info: mode = 'PA'
        return np.asarray(im.convert('RGBA'), np.uint8), mode
    except ImportError:
        pass
    except Exception:
        return None, 'undecodable'
    try:
        import bpy, tempfile
        ext = '.png' if data[:4] == b'\x89PNG' else '.jpg' if data[:2] == b'\xff\xd8' else '.webp'
        fd, p = tempfile.mkstemp(suffix=ext); os.write(fd, data); os.close(fd)
        img = bpy.data.images.load(p); img.colorspace_settings.name = 'Non-Color'
        w, h = img.size; ch = img.channels
        px = np.empty(w * h * 4, np.float32); img.pixels.foreach_get(px)
        mode = 'RGBA' if (ch == 4 and img.alpha_mode != 'NONE' and data[:4] == b'\x89PNG' and data[25] in (4, 6)) else 'RGB'
        bpy.data.images.remove(img); os.remove(p)
        return np.flipud(np.clip(px.reshape(h, w, 4) * 255 + 0.5, 0, 255).astype(np.uint8)), mode
    except Exception:
        return None, 'undecodable'


def tex_uv(tinfo, uvsets):
    """UVs for a textureInfo: its texCoord set, KHR_texture_transform applied."""
    np = _np()
    tt = (tinfo.get('extensions') or {}).get('KHR_texture_transform')
    tc = tinfo.get('texCoord', 0)
    if tt and 'texCoord' in tt: tc = tt['texCoord']
    uv = uvsets.get(tc)
    if uv is None: return None
    if tt:
        ox, oy = tt.get('offset', [0, 0]); r = tt.get('rotation', 0.0); sx, sy = tt.get('scale', [1, 1])
        c, s = math.cos(r), math.sin(r)
        u = uv[:, 0] * sx; v = uv[:, 1] * sy
        uv = np.stack([c * u + s * v + ox, -s * u + c * v + oy], 1)
    return uv


WRAP = {33071: 'clamp', 33648: 'mirror', 10497: 'repeat'}


def sample_img(img, uv, sampler=None):
    """Nearest texel (float RGBA 0..1) at glTF UVs (origin top-left), honouring the sampler's wrap modes."""
    np = _np()
    h, w = img.shape[:2]; ws = sampler or {}
    def wrap(x, mode):
        if mode == 'clamp': return np.clip(x, 0, 1 - 1e-9)
        if mode == 'mirror':
            f = np.mod(x, 2.0); return np.where(f > 1, 2 - f, f)
        return np.mod(x, 1.0)
    u = wrap(uv[:, 0], WRAP.get(ws.get('wrapS', 10497))); v = wrap(uv[:, 1], WRAP.get(ws.get('wrapT', 10497)))
    return img[np.clip((v * h).astype(int), 0, h - 1), np.clip((u * w).astype(int), 0, w - 1)].astype(np.float64) / 255.0


def raster(tri_uv, w, h):
    """Coverage mask (h, w) of UV triangles (N, 3, 2) in glTF UV (row 0 = v 0), wrapped into 0..1 per triangle."""
    np = _np()
    out = np.zeros((h, w), bool)
    P = np.asarray(tri_uv, np.float64).copy()
    P -= np.floor(P.min(1, keepdims=True))                   # a tiled triangle lands where its texels are
    P[..., 0] = P[..., 0] * w - 0.5; P[..., 1] = P[..., 1] * h - 0.5
    for k in range(len(P)):
        (x0, y0), (x1, y1), (x2, y2) = P[k]
        d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(d) < 1e-12: continue
        lx = max(int(math.ceil(min(x0, x1, x2))), 0); hx = min(int(math.floor(max(x0, x1, x2))), w - 1)
        ly = max(int(math.ceil(min(y0, y1, y2))), 0); hy = min(int(math.floor(max(y0, y1, y2))), h - 1)
        if hx < lx or hy < ly: continue
        X, Y = np.meshgrid(np.arange(lx, hx + 1), np.arange(ly, hy + 1))
        a = ((y1 - y2) * (X - x2) + (x2 - x1) * (Y - y2)) / d
        b = ((y2 - y0) * (X - x2) + (x0 - x2) * (Y - y2)) / d
        out[ly:hy + 1, lx:hx + 1] |= (a >= -1e-6) & (b >= -1e-6) & (a + b <= 1 + 1e-6)
    return out


# ---------------------------------------------------------------------------------------------- surface groups
class Group:
    """One checked surface: a material, or one slot / shader kind of a live-shader material. Samples are area-weighted."""

    def __init__(self, name, material, mode):
        self.name, self.material, self.mode = name, material, mode
        self.cls, self.cls_src, self.declared, self.entry = None, None, False, {}
        self.area = 0.0; self.s = {}; self.lit_by_game = None; self.notes = []
        self.alpha_mode = 'OPAQUE'; self.double_sided = False; self.textured = False; self.tex = {}
        self.props = {}; self.metal_name = None    # material custom properties / glTF extras; declared reference metal

    def n(self): return len(self.s.get('metal', ()))


def _assign_class(g, entries, extra_names=()):
    """Class from the class map > live shader kind > the material's own reference (kit3d_ref / ref custom property,
    looked up in the measured table) > game contract name > guess. Sets cls, cls_src, declared, metal_name."""
    _assign_class_inner(g, entries, extra_names)
    e = g.entry or {}
    if e.get('metal') or (g.cls == 'bare_metal' and e.get('ref')): g.metal_name = e.get('metal') or e.get('ref')


def _assign_class_inner(g, entries, extra_names):
    key, e = class_entry(entries, g.name, g.material, *extra_names)
    if e:
        g.entry = e; g.cls = e.get('class'); g.declared = g.cls in CLASSES
        g.cls_src = f'class map ({key})' + ('' if g.declared else f': unknown class {g.cls!r}')
        if not g.declared: g.cls = None
        if g.cls: return
    if g.cls: return                                    # set by the live-shader reader
    ref = (g.props or {}).get('kit3d_ref') or (g.props or {}).get('ref')
    if isinstance(ref, str) and ref:
        r = metal_ref(ref, any_class=True)
        if r:
            g.declared = True; g.cls_src = f'material ref {ref!r} -> {r["name"]} (physicallybased.info)'
            if r['metallic'] >= 0.5: g.cls = 'bare_metal'; g.metal_name = r['name']; return
            m, c = g.s.get('metal'), g.s.get('coat')
            coated_mid = m is not None and len(m) and float(((m > .1) & (m < .9) & (c >= .5)).mean()) > 0.5
            g.cls = 'metallic_paint' if coated_mid else (r['class'] if r['class'] in CLASSES else 'dielectric'); return
    s, ge = game_slot(g.material)
    if ge and ge.get('kind'):
        g.cls = KIND_CLASS.get(ge['kind'].split('@')[0]); g.declared = g.cls is not None
        g.cls_src = f'game contract name {s!r} -> {ge["kind"]}'
        if any(x in (g.material or '').lower() for x in GAME_LIT): g.lit_by_game = f'game draws its night glow ({s})'
        if g.cls: return
    gc = guess_class(g.name if g.mode != 'pbr' else g.material)
    g.cls = gc or 'unknown'; g.cls_src = 'guessed from the name' if gc else 'no class (no map entry, no kind, no guess)'
    g.declared = False
    em = g.s.get('emit') if g.s else None
    if em is not None and len(em) and float((em.max(1) > 0.02).mean()) > 0.5 and g.cls != 'glass':
        g.cls, g.cls_src = 'emissive', 'emits light on most of its area (not declared)'


def read_glb_groups(G, n_samples, rng, entries):
    """Sample every material of the GLB -> list of Group."""
    np = _np(); j = G.j; mats = j.get('materials', [])
    prims = G.world_prims()
    by_mat = {}
    for ni, nname, W, pr in prims:
        mode = pr.get('mode', 4)
        if mode not in (4, 5, 6) or 'POSITION' not in pr['attributes']: continue
        P = G.acc(pr['attributes']['POSITION'])[:, :3]
        I = G.acc(pr['indices']).astype(np.int64).ravel() if 'indices' in pr else np.arange(len(P))
        if mode == 5: I = np.concatenate([[I[k], I[k + 1 + (k % 2)], I[k + 2 - (k % 2)]] for k in range(len(I) - 2)]) if len(I) > 2 else I[:0]
        if mode == 6: I = np.concatenate([[I[0], I[k], I[k + 1]] for k in range(1, len(I) - 1)]) if len(I) > 2 else I[:0]
        T = I[: len(I) // 3 * 3].reshape(-1, 3)
        if not len(T): continue
        Pw = P @ W[:3, :3].T + W[:3, 3]
        A = 0.5 * np.linalg.norm(np.cross(Pw[T[:, 1]] - Pw[T[:, 0]], Pw[T[:, 2]] - Pw[T[:, 0]]), axis=1)
        by_mat.setdefault(pr.get('material', -1), []).append((ni, nname, pr, Pw, T, A))
    total = sum(float(x[5].sum()) for v in by_mat.values() for x in v) or 1.0
    groups, meta_prims = [], {}
    for mi, plist in by_mat.items():
        mat = mats[mi] if mi >= 0 else {'name': '(no material)'}
        mname = mat.get('name') or f'material{mi}'
        area = sum(float(x[5].sum()) for x in plist)
        if area <= 0: continue
        ex = mat.get('extras') or {}
        idle = _jsonish(ex.get('idle')) if isinstance(ex, dict) else None
        slot = ex.get('shader_slot') if isinstance(ex, dict) else None
        live = 'idle' if isinstance(idle, dict) and idle.get('kind') else 'batch' if slot == 'train.surface.batch.v1' else None
        n = max(2000 if live else 400, int(round(n_samples * area / total)))
        # pick triangles across this material's primitives by area
        cumA = np.concatenate([x[5] for x in plist]); off = np.cumsum([0] + [len(x[5]) for x in plist])
        pick = rng.choice(len(cumA), n, p=cumA / cumA.sum())
        r1, r2 = rng.random(n), rng.random(n); sq = np.sqrt(r1); w = np.stack([1 - sq, sq * (1 - r2), sq * r2], 1)
        S = {k: [] for k in ('base', 'alpha', 'metal', 'rough', 'emit', 'coat', 'occ', 'pos', 'uv', 'node', 'nrmB', 'nrmL',
                             'slot', 'tan')}
        for pi, (ni, nname, pr, Pw, T, A) in enumerate(plist):
            sel = (pick >= off[pi]) & (pick < off[pi + 1]); k = pick[sel] - off[pi]; ww = w[sel]
            if not len(k): continue
            tri = T[k]
            def interp(arr): return (ww[:, 0, None] * arr[tri[:, 0]] + ww[:, 1, None] * arr[tri[:, 1]] + ww[:, 2, None] * arr[tri[:, 2]])
            def nearest(arr): return arr[tri[np.arange(len(k)), ww.argmax(1)]]
            at = pr['attributes']
            uvsets = {int(a.split('_')[1]): interp(G.acc(at[a])[:, :2]) for a in at if a.startswith('TEXCOORD_')}
            col = interp(G.acc(at['COLOR_0'])) if 'COLOR_0' in at else None
            if col is not None and col.shape[1] == 3: col = np.concatenate([col, np.ones((len(col), 1))], 1)
            m = len(k); pb = mat.get('pbrMetallicRoughness') or {}; mex = mat.get('extensions') or {}
            base = np.tile(np.array((pb.get('baseColorFactor') or [1, 1, 1, 1]), np.float64), (m, 1))
            metal = np.full(m, float(pb.get('metallicFactor', 1.0))); rough = np.full(m, float(pb.get('roughnessFactor', 1.0)))
            def tex(tinfo, role):
                if not tinfo or 'index' not in tinfo: return None
                src, smp = G.tex_source(tinfo['index'])
                if src is None: return None
                img = G.image(src)
                uv = tex_uv(tinfo, uvsets)
                if img is None or uv is None: return None
                return sample_img(img, uv, j['samplers'][smp] if smp is not None and j.get('samplers') else None)
            if live == 'batch':
                base = col[:, :4].copy() if col is not None else np.ones((m, 4))
                pbr = interp(G.acc(at['_TRAIN_PBR'])) if '_TRAIN_PBR' in at else np.tile([0.5, 0, 0], (m, 1))
                rough, metal = pbr[:, 0], pbr[:, 1]
                kind = np.rint(nearest(G.acc(at['_TRAIN_PBR'])[:, 2])) if '_TRAIN_PBR' in at else np.zeros(m)
                emit = interp(G.acc(at['_TRAIN_EMIT'])[:, :3]) * BATCH_NIGHT if '_TRAIN_EMIT' in at else np.zeros((m, 3))
                coat = np.where(kind == 3, 0.18, 0.0)
                S['slot'].append(kind.astype(int))
            else:
                if col is not None: base = base * col[:, :4]
                t = tex(pb.get('baseColorTexture'), 'base')
                if t is not None: base[:, :3] *= srgb2lin(t[:, :3]); base[:, 3] *= t[:, 3]
                t = tex(pb.get('metallicRoughnessTexture'), 'mr')
                if t is not None: rough = rough * t[:, 1]; metal = metal * t[:, 2]
                es = float((mex.get('KHR_materials_emissive_strength') or {}).get('emissiveStrength', 1.0))
                emit = np.tile(np.array(mat.get('emissiveFactor', [0, 0, 0]), np.float64) * es, (m, 1))
                t = tex(mat.get('emissiveTexture'), 'emit')
                if t is not None: emit = emit * srgb2lin(t[:, :3])
                cc = mex.get('KHR_materials_clearcoat') or {}
                coat = np.full(m, float(cc.get('clearcoatFactor', 0.0)))
                t = tex(cc.get('clearcoatTexture'), 'coat')
                if t is not None: coat = coat * t[:, 0]
                ot = mat.get('occlusionTexture')        # glTF: R channel, occluded = 1 + strength * (R - 1)
                t = tex(ot, 'occ') if ot and not live else None
                if t is not None: S['occ'].append(1.0 + float(ot.get('strength', 1.0)) * (t[:, 0] - 1.0))
                if live == 'idle':
                    tid = np.zeros(m, int)
                    if idle.get('table') and mat.get('occlusionTexture'):
                        t = tex(mat['occlusionTexture'], 'occ')
                        if t is not None: tid = np.rint(t[:, 3] * 255).astype(int)
                    S['slot'].append(tid)
            t = tex(mat.get('normalTexture'), 'nrm')
            if t is not None:
                nv = t[:, :3] * 2 - 1; S['nrmB'].append(t[:, 2]); S['nrmL'].append(np.abs(np.linalg.norm(nv, axis=1) - 1))
            S['base'].append(base[:, :3]); S['alpha'].append(base[:, 3]); S['metal'].append(metal); S['rough'].append(rough)
            S['emit'].append(emit); S['coat'].append(coat); S['pos'].append(interp(Pw))
            buv = tex_uv(pb.get('baseColorTexture') or pb.get('metallicRoughnessTexture') or {'texCoord': 0}, uvsets)
            S['uv'].append(buv if buv is not None else np.full((m, 2), np.nan)); S['node'].append(np.full(m, ni))
            S['tan'].append(np.full(m, 'TANGENT' in at))
        S = {k: np.concatenate(v) for k, v in S.items() if v}
        meta_prims[mname] = plist
        info = dict(mat=mat, plist=plist, idle=idle, slot=slot)
        if live == 'batch':
            for code in sorted(set(S['slot'].tolist())):
                sel = S['slot'] == code; kname, kcls = BATCH_KINDS.get(code, (f'kind{code}', None))
                g = Group(f'{mname}[{kname}]', mname, 'batch'); g.info = info
                g.s = {k: v[sel] for k, v in S.items()}; g.area = area * sel.mean()
                if kcls: g.cls, g.cls_src = kcls, 'shader kind (train.surface.batch.v1) - treated as guessed'
                if code in (4, 5): g.lit_by_game = 'shader kind lamp (night x1.92)'
                groups.append(g)
        elif live == 'idle':
            table = _jsonish(idle.get('table')) or []
            for tid in sorted(set(S['slot'].tolist())):
                sel = S['slot'] == tid
                ent = idle if tid <= 0 or tid > len(table) else table[tid - 1]
                sname = ent.get('slot') or idle.get('slot') or '?'
                g = Group(f'{mname}[{sname}]' if table else mname, mname, 'idle'); g.info = info
                g.s = {k: v[sel] for k, v in S.items()}; g.area = area * sel.mean()
                _apply_kind(g, ent)
                groups.append(g)
        else:
            g = Group(mname, mname, 'pbr'); g.info = info; g.s = S; g.area = area
            groups.append(g)
    for g in groups:
        mat = g.info['mat']; g.alpha_mode = mat.get('alphaMode', 'OPAQUE'); g.double_sided = bool(mat.get('doubleSided'))
        g.props = mat.get('extras') if isinstance(mat.get('extras'), dict) else {}
        pb = mat.get('pbrMetallicRoughness')
        g.textured = bool(pb and (pb.get('baseColorTexture') or pb.get('metallicRoughnessTexture')))
        g.metal_omitted = pb is None or ('metallicFactor' not in pb and not pb.get('metallicRoughnessTexture'))
        g.pbr_missing = pb is None
        _assign_class(g, entries, extra_names=((g.name.split('[')[-1].rstrip(']'),) if '[' in g.name else ()))
    return groups, total, prims


def _apply_kind(g, ent):
    """Values a library kind will draw (its parameters), replacing the sampled fallback factors."""
    np = _np()
    kind = (ent.get('kind') or '').split('@')[0]; p = dict(kind_defaults(kind)); p.update(_jsonish(ent.get('p')) or {})
    m = g.n(); g.kind = ent.get('kind'); g.cls = KIND_CLASS.get(kind); g.declared = g.cls is not None
    g.cls_src = f'extras.idle kind {ent.get("kind")}'
    if g.cls is None: g.notes.append(f'unknown kind {ent.get("kind")!r}: checked by its fallback factors'); return
    col = p.get('color') or p.get('lens') or p.get('tint')
    if kind == 'wood.varnished': col = [(a + b) / 2 for a, b in zip(p.get('light', [.4] * 3), p.get('dark', [.2] * 3))]
    if kind == 'fabric.weave': col = [(a + b) / 2 for a, b in zip(p.get('color', [.3] * 3), p.get('color2', p.get('color', [.3] * 3)))]
    if col is None: col = [0.5, 0.5, 0.5]
    g.s['base'] = np.tile(np.array(col[:3], np.float64), (m, 1))
    g.s['metal'] = np.full(m, float(p.get('metal', 1.0 if kind == 'metal.brushed' else 0.0)) if kind in ('metal.brushed', 'paint.metallic') else 0.0)
    g.s['rough'] = np.full(m, float(p.get('rough', 0.5)))
    g.s['coat'] = np.full(m, float(p.get('coat', 0.0)) if kind == 'paint.metallic' else 0.0)
    g.s['alpha'] = np.full(m, float(p.get('opacity', 1.0)))
    emit = np.zeros(3)
    if kind == 'lamp.emissive': emit = np.array(p.get('light', [1, 1, 1])[:3]) * float(p.get('night', 1.0)); g.lit_by_game = 'kind lamp.emissive (night value)'
    if kind == 'glass.window' and float(p.get('glow', 0)) > 0:
        emit = np.array(p.get('glow_color', [1, .8, .55])[:3]) * float(p['glow']); g.lit_by_game = 'kind glass.window glow (night)'
    g.s['emit'] = np.tile(emit, (m, 1))
    g.params = p


# ------------------------------------------------------------------------------------------------------ where clusters
def where(g, mask, k=5, frame='gltf', node_names=None):
    """Up to k clusters of the failing samples: centre and 5-95 % box in glTF metres (+Y up), UV box, share, node."""
    np = _np()
    pos = g.s['pos'][mask]
    if not len(pos): return []
    uv = g.s['uv'][mask] if 'uv' in g.s else None; nodes = g.s['node'][mask] if 'node' in g.s else None
    k = max(1, min(k, len(pos) // 8 or 1))
    C = [pos[0]]
    for _ in range(1, k):
        d = np.min([np.sum((pos - c) ** 2, 1) for c in C], 0)
        if d.max() <= 1e-6: break
        C.append(pos[d.argmax()])
    C = np.array(C)
    for _ in range(10):
        lab = np.argmin(((pos[:, None, :] - C[None]) ** 2).sum(2), 1)
        C = np.array([pos[lab == i].mean(0) if (lab == i).any() else C[i] for i in range(len(C))])
    out = []
    for i in range(len(C)):
        sel = lab == i
        if not sel.any(): continue
        p = pos[sel]; c = {'gltf_xyz': [round(float(x), 3) for x in p.mean(0)],
                           'box_gltf': [[round(float(x), 3) for x in np.percentile(p, 5, 0)],
                                        [round(float(x), 3) for x in np.percentile(p, 95, 0)]],
                           'share': round(float(sel.mean()), 3)}
        if uv is not None:
            u = uv[sel]; u = u[np.isfinite(u).all(1)]
            if len(u): c['uv_box'] = [round(float(x), 4) for x in (*np.percentile(u, 5, 0), *np.percentile(u, 95, 0))]
        if nodes is not None and node_names is not None:
            vals, cnt = np.unique(nodes[sel], return_counts=True); c['node'] = node_names.get(int(vals[cnt.argmax()]))
        out.append(c)
    return sorted(out, key=lambda c: -c['share'])


# ------------------------------------------------------------------------------------------------------ the checks
def group_rules(g, ctx):
    """M1-M10 (+ M4 metal reference, S1) on one group. Returns findings."""
    np = _np(); F = []; s = g.s
    if not g.n(): return F
    m, Y, coat = s['metal'], luminance(s['base']), s['coat']
    W = lambda mask: where(g, mask, node_names=ctx.get('node_names'))
    nm = g.name; cls = g.cls
    sev_decl = (lambda sev: sev) if g.declared else (lambda sev: 'WARN' if sev == 'ERROR' else sev)
    glassy = cls in ('glass',) or g.alpha_mode == 'BLEND'
    emissive = cls == 'emissive'
    inb = (m > 0.1) & (m < 0.9) & (coat < 0.5)
    sh = float(inb.mean())
    if sh > 0.05:
        if cls == 'layered': sev = 'INFO'
        else: sev = 'ERROR' if sh > 0.20 else 'WARN'
        F.append(Finding('M1', sev, nm, f'metallic in-between (0.1-0.9) without clear coat (p50 {np.median(m[inb]):.2f}, '
                         f'p95 {pct(m[inb], 95):.2f}); thresholds >5 % WARN, >20 % ERROR', share=sh, value=round(float(np.median(m[inb])), 3),
                         threshold=0.20 if sev == 'ERROR' else 0.05, where=W(inb)))
    wp = inb & (Y > 0.5)
    sh = float(wp.mean())
    if sh >= 0.02:
        F.append(Finding('M2', 'ERROR' if cls != 'layered' else 'WARN', nm,
                         f'metallic 0.1-0.9 with base Y>0.5 and no clear coat = white plastic (base Y p50 {np.median(Y[wp]):.2f}, '
                         f'metallic p50 {np.median(m[wp]):.2f})', share=sh, value=round(float(np.median(m[wp])), 3), threshold=0.02,
                         where=W(wp)))
    met = m >= 0.9
    ref = metal_ref(g.metal_name) if g.metal_name else None
    ref_dark = ref is not None and ref['Y'] < 0.35
    if met.sum() >= 50 and met.mean() >= 0.005 and not ref_dark:
        dk = met & (Y < 0.35); shm = float(dk.sum() / met.sum())
        if shm > 0.10:
            F.append(Finding('M3', 'WARN', nm, f'metal (m>=0.9) with base Y<0.35 on {shm:.1%} of the metal area '
                             f'({dk.mean():.1%} of the group; metal Y p50 {np.median(Y[met]):.2f}); real metals F0 Y .40-.98',
                             share=float(dk.mean()), value=round(float(np.median(Y[met])), 3), threshold=0.10, where=W(dk)))
    if ref is not None and met.mean() >= 0.02:
        rgb = np.median(s['base'][met], 0); y = float(luminance(rgb)); ry = ref['Y']
        ch = lambda c: np.asarray(c, float) / max(sum(c), 1e-6)
        dch = float(np.abs(ch(rgb) - ch(ref['color_linear'])).max())
        tinted = max(ref['color_linear']) - min(ref['color_linear']) > 0.15
        if abs(y - ry) > 0.10 or (tinted and dch > 0.04):
            F.append(Finding('M4', 'ERROR', nm, f'declared metal {g.metal_name!r} = {ref["name"]} '
                             f'F0 {tuple(round(x, 3) for x in ref["color_linear"])} Y {ry:.2f}; measured median '
                             f'{tuple(round(float(x), 3) for x in rgb)} Y {y:.2f}' + (f', hue off {dch:.2f}' if tinted else ''),
                             share=float(met.mean()), value=round(y, 3), threshold=0.10))
    if g.cls and g.cls not in ('mixed', 'unknown', 'layered', 'emissive'):
        med = float(np.median(m)); msg = None
        if cls == 'bare_metal' and med < 0.9: msg = f'class bare_metal but median metallic {med:.2f} (< 0.9)'
        if cls in DIELECTRIC and med > 0.1: msg = f'class {cls} (a dielectric) but median metallic {med:.2f} (> 0.1)'
        if cls == 'metallic_paint':
            mid = (m > 0.1) & (m < 0.9)
            if mid.mean() > 0.2 and float(np.median(coat[mid])) < 0.5:
                msg = f'class metallic_paint with in-between metallic (p50 {np.median(m[mid]):.2f}) and no clear coat in this file'
        if msg:
            F.append(Finding('M5', sev_decl('ERROR'), nm, msg + f' [class from {g.cls_src}]', share=1.0, value=round(med, 3)))
    diel = m <= 0.1
    if diel.any() and not glassy and not emissive:
        Y8 = lin2srgb8(Y)
        dk = diel & (Y8 < 30); sh = float(dk.mean())
        if sh > 0.05:
            F.append(Finding('M6', 'WARN', nm, f'non-metal albedo below 30 sRGB (p5 {pct(Y8[diel], 5):.0f} sRGB, Y {pct(Y[diel], 5):.3f})',
                             share=sh, value=round(pct(Y8[diel], 5), 1), threshold=30, where=W(dk)))
        b250 = diel & (Y8 > 250); b243 = diel & (Y8 > 243)
        if b250.mean() > 0.01:
            F.append(Finding('M7', 'ERROR', nm, f'non-metal albedo above 250 sRGB (p99 {pct(Y8[diel], 99):.0f})',
                             share=float(b250.mean()), value=round(pct(Y8[diel], 99), 1), threshold=250, where=W(b250)))
        elif b243.mean() > 0.05:
            F.append(Finding('M7', 'WARN', nm, f'non-metal albedo above 243 sRGB (p95 {pct(Y8[diel], 95):.0f})',
                             share=float(b243.mean()), value=round(pct(Y8[diel], 95), 1), threshold=243, where=W(b243)))
    if not glassy and not emissive:
        lo = s['rough'] < 0.02; sh = float(lo.mean())
        if sh > 0.05:
            F.append(Finding('M8', 'WARN', nm, f'roughness below 0.02 on an opaque surface (p5 {pct(s["rough"], 5):.3f})',
                             share=sh, value=round(pct(s['rough'], 5), 4), threshold=0.02, where=W(lo)))
    if g.mode == 'pbr' and g.textured:
        for ch, vals in (('roughness', s['rough']), ('metallic', s['metal'])):
            for dv in (0.5, 1.0):
                sh = float((np.abs(vals - dv) < 0.004).mean())
                if sh > 0.9:
                    F.append(Finding('M9', 'INFO', nm, f'{ch} constant at {dv} on {sh:.0%} of a textured material (not authored?)',
                                     share=sh, value=dv, decide=''))
    if g.mode == 'pbr' and len(s.get('occ', ())):
        o = s['occ']; med = float(np.median(o)); dk = float((o < 0.5).mean())
        F.append(Finding('G9', 'WARN' if med < 0.5 else 'INFO', nm, f'occlusion (R x strength) median {med:.2f}, p5 {pct(o, 5):.2f}, '
                         f'darker than 0.5 on {dk:.1%} of the area' + (' (most of the ambient light is gone)' if med < 0.5 else ''),
                         share=dk, value=round(med, 3), threshold=0.5, decide=None if med < 0.5 else ''))
    if g.mode == 'pbr' and getattr(g, 'metal_omitted', False) and cls != 'bare_metal' and float(np.median(m)) > 0.9:
        F.append(Finding('M10', 'WARN', nm, ('no pbrMetallicRoughness block at all (exporter gave up on a procedural input?): '
                                             'renders as white metal' if g.pbr_missing else 'metallicFactor omitted (glTF default 1 = metal) '
                                             'and no metallic texture') + f' on class {cls}', share=1.0, value=1.0))
    if g.entry and not g.entry.get('source'):
        F.append(Finding('S1', 'WARN', nm, 'class-map entry has no "source"', decide=None))
    srcs = _jsonish((g.props or {}).get('kit3d_src'))
    if isinstance(srcs, dict):       # kit3d records a source per value: an inferred metallic or colour is an invented number
        bad = [k for k in ('metallic', 'base') if str(srcs.get(k, '')).strip().lower() in ('inferred', '')
               and k in (_jsonish((g.props or {}).get('kit3d_values')) or {k: 1})]
        if bad: F.append(Finding('S1', 'WARN', nm, f'{" and ".join(bad)} set without a source (kit3d_src says inferred)', decide=None))
    return F


def asset_rules(groups, total, G, ctx):
    """G1, G6, G8 per material; G4 per mesh; G2/G3/G6-JPEG/T1 per image; E1-E3, M11 per asset. A live-shader material
    (extras.idle) is judged by the textures the game samples (normal + mask), not the exporter's guessed base maps."""
    np = _np(); F = []; j = G.j; done = set()
    def size(t):
        if not t or 'index' not in t: return None
        src, _ = G.tex_source(t['index'])
        if src is None: return None
        G.image(src); i = G.img_info.get(src, {})
        return (i.get('w'), i.get('h'), i.get('mime'), i.get('mode'), src)
    for g in groups:
        mat = g.info['mat']; mname = g.material
        if mname in done: continue
        done.add(mname); gs = [x for x in groups if x.material == mname]
        a_share = sum(x.area for x in gs) / total
        sheet = any(x.entry.get('sheet') or x.cls in ('sheet', 'foliage', 'decal') for x in gs)
        if g.double_sided and g.alpha_mode == 'OPAQUE' and not sheet:
            mask = np.concatenate([np.ones(x.n(), bool) for x in gs]); gx = _merge(gs)
            F.append(Finding('G1', 'ERROR', mname, 'doubleSided on an opaque surface material (back faces drawn: blinking, '
                             'inner walls through gaps)', share=a_share, where=where(gx, mask, node_names=ctx['node_names'])))
        if g.alpha_mode == 'BLEND' and not any(x.cls == 'glass' for x in gs):
            F.append(Finding('G8', 'WARN', mname, f'alphaMode BLEND on a non-glass material (class {g.cls})', share=a_share))
        pb = mat.get('pbrMetallicRoughness') or {}
        bc, mr, nr = size(pb.get('baseColorTexture')), size(pb.get('metallicRoughnessTexture')), size(mat.get('normalTexture'))
        occ = size(mat.get('occlusionTexture'))
        if g.mode == 'idle':                       # the game samples only the declared normal map and the mask
            idle = g.info.get('idle') or {}
            g.tex = {'normal': nr if idle.get('normal') else None, 'mask': occ}
            g.density_tex = (mat.get('normalTexture') if idle.get('normal') else None) or mat.get('occlusionTexture')
            continue
        g.tex = {'base': bc, 'mr': mr, 'normal': nr}
        g.density_tex = pb.get('baseColorTexture') or pb.get('metallicRoughnessTexture') or mat.get('normalTexture')
        if bc and bc[0]:
            for nmx, t in (('metallic-roughness', mr), ('normal', nr)):
                if t and t[0] and t[0] * t[1] > bc[0] * bc[1]:
                    F.append(Finding('G6', 'WARN', mname, f'{nmx} map {t[0]}x{t[1]} larger than base colour {bc[0]}x{bc[1]}', share=a_share))
        if bc and g.alpha_mode == 'OPAQUE' and bc[3] in ('RGBA', 'LA', 'PA') and not g.cls == 'glass':
            a = G.image(bc[4])
            varies = a is not None and int(a[..., 3].min()) < 255
            F.append(Finding('G8', 'WARN', mname, f'base colour image has an alpha channel ({bc[3]}{", not all opaque" if varies else ", all 255"}) '
                             f'on an OPAQUE material', share=a_share))
    for g in groups:
        for x in [y for y in groups if y.material == g.material]:
            if not x.tex: x.tex, x.density_tex = g.tex, getattr(g, 'density_tex', None)
    # G4: a normal-mapped primitive without TANGENT (one finding per mesh)
    miss = {}
    for ni, nname, W_, pr in ctx['prims']:
        mi = pr.get('material')
        if mi is None or not j['materials'][mi].get('normalTexture') or 'TANGENT' in pr['attributes']: continue
        mesh = j['meshes'][j['nodes'][ni]['mesh']].get('name') or nname
        miss.setdefault(mesh, set()).add(j['materials'][mi].get('name', '?'))
    for mesh, mats_ in sorted(miss.items()):
        a_share = sum(x.area for x in groups if x.material in mats_) / total
        F.append(Finding('G4', 'ERROR', f'mesh {mesh}', f'normal map but no TANGENT ({len(mats_)} material(s): '
                         f'{", ".join(sorted(mats_)[:4])}{"…" if len(mats_) > 4 else ""}); three falls back to screen-space '
                         f'tangents that differ from the baker\'s MikkTSpace', share=a_share))
    # G5: every image a material uses
    used = set()
    for mat in j.get('materials', []):
        for t in _tex_infos(mat):
            src, _ = G.tex_source(t['index'])
            if src is not None: used.add(src)
    for src in sorted(used):
        G.image(src); i = G.img_info.get(src, {}); w, h = i.get('w'), i.get('h')
        if not w: continue
        nm = i.get('name') or f'image{src}'; pot = lambda x: x & (x - 1) == 0
        if not (pot(w) and pot(h)): F.append(Finding('G5', 'ERROR', f'image {nm}', f'{w}x{h} is not a power of two'))
        elif w % 4 or h % 4: F.append(Finding('G5', 'ERROR', f'image {nm}', f'{w}x{h} is not a multiple of 4'))
        if max(w, h) > 2048: F.append(Finding('G5', 'WARN', f'image {nm}', f'{w}x{h} is larger than 2048'))
    # G2/G3: normal images over the texels the triangles cover
    nimgs = {}
    for mat_i, mat in enumerate(j.get('materials', [])):
        nt = mat.get('normalTexture')
        if nt and 'index' in nt:
            src, _ = G.tex_source(nt['index'])
            if src is not None: nimgs.setdefault(src, []).append((mat_i, nt))
    for src, users in nimgs.items():
        img = G.image(src)
        if img is None: continue
        h, w = img.shape[:2]; cov = np.zeros((h, w), bool); names = []
        for ni, nname, W_, pr in ctx['prims']:
            if pr.get('material') not in [u[0] for u in users]: continue
            nt = next(u[1] for u in users if u[0] == pr.get('material'))
            at = pr['attributes']; tc = nt.get('texCoord', 0)
            if f'TEXCOORD_{tc}' not in at: continue
            UV = tex_uv(nt, {tc: G.acc(at[f'TEXCOORD_{tc}'])[:, :2]})
            I = G.acc(pr['indices']).astype(np.int64).ravel() if 'indices' in pr else np.arange(len(UV))
            T = I[: len(I) // 3 * 3].reshape(-1, 3)
            cov |= raster(UV[T], w, h)
        names = sorted({j['materials'][u[0]].get('name', '?') for u in users})
        if not cov.any(): continue
        px = img[cov][:, :3].astype(np.float64) / 255.0
        bshare = float((px[:, 2] <= 0.5).mean()); L = np.abs(np.linalg.norm(px * 2 - 1, axis=1) - 1); p99 = float(np.percentile(L, 99))
        label = f'{G.img_info[src].get("name") or "image" + str(src)} (normal of {", ".join(names[:3])}{"…" if len(names) > 3 else ""})'
        ctx.setdefault('normal_maps', {})[src] = dict(cov=cov, label=label)
        if G.img_info[src].get('mime') == 'image/jpeg':
            F.append(Finding('G6', 'WARN', label, f'normal map stored as JPEG ({w}x{h}): ringing breaks unit length'))
        if bshare > 0.001:
            gx = _merge([x for x in groups if x.material in names]); mk = gx.s['nrmB'] <= 0.5 if 'nrmB' in gx.s else None
            F.append(Finding('G2', 'ERROR', label, f'blue <= 0.5 on {bshare:.2%} of {int(cov.sum())} covered texels '
                             f'(points into the surface)', share=None, value=round(bshare, 5), threshold=0.001,
                             where=where(gx, mk, node_names=ctx['node_names']) if mk is not None and mk.any() else None))
        if p99 > 0.1:
            F.append(Finding('G3', 'WARN', label, f'| |n| - 1 | p99 {p99:.3f} over covered texels (p50 {np.median(L):.3f})',
                             value=round(p99, 4), threshold=0.1))
    # E1-E3: night glow
    lit_share, lit_groups = 0.0, []
    for g in groups:
        if not g.n(): continue
        lit = g.s['emit'].max(1) > 0.02
        if g.lit_by_game: lit = np.ones(g.n(), bool)
        if lit.any(): lit_groups.append(g)
        lit_share += g.area * float(lit.mean()) / total
    ctx['lit_share'] = lit_share
    decl = ctx['night_declared']
    if decl and not lit_groups:
        F.append(Finding('E1', 'ERROR', os.path.basename(G.path), f'night lights declared ({decl}) but no lit texel in this '
                         f'version (emissive max channel <= 0.02 everywhere, no lamp/glow kind)', share=0.0))
    for g in groups:
        low = (g.name or '').lower()
        is_win = (g.entry or {}).get('window') or ((g.cls == 'glass' or re.search(r'window|cabin|pane', low)) and
                                                   not re.search(r'lamp|led|light|head|tail|marker|indicator|signal|lens', low))
        if not is_win or g.mode == 'batch': continue
        lit = g.s['emit'].max(1) > 0.02
        if not lit.any(): continue
        peak = pct(g.s['emit'][lit].max(1), 99)
        if peak > 1.5 or peak < 0.2:
            F.append(Finding('E3', 'WARN', g.name, f'window emissive peak (p99, night value) {peak:.2f} outside 0.2-1.5',
                             share=float(lit.mean()), value=round(peak, 3)))
    ab = ctx.get('above')
    if ab is not None:
        if ab['lit_share'] > 0 and lit_groups:
            ratio = lit_share / ab['lit_share']
            if ratio < 0.7 or ratio > 1.3:
                F.append(Finding('E2', 'WARN', os.path.basename(G.path), f'lit share {lit_share:.2%} vs {ab["lit_share"]:.2%} in '
                                 f'{os.path.basename(ab["path"])} (x{ratio:.2f}, keep x0.7-1.3)', value=round(ratio, 3)))
        coat_here = sum(g.area * float((g.s['coat'] >= 0.5).mean()) for g in groups if g.n()) / total
        for mname, cs in ab['coat_mats'].items():
            here = [g for g in groups if g.material == mname]
            if here and all(float((g.s['coat'] >= 0.5).mean()) < 0.5 for g in here if g.n()):
                F.append(Finding('M11', 'ERROR', mname, f'clear coat {cs:.0%} of its area in {os.path.basename(ab["path"])}, none here'))
        if ab['coat_share'] > 0.05 and coat_here < 0.5 * ab['coat_share'] and not any(f.rule == 'M11' for f in F):
            F.append(Finding('M11', 'ERROR', os.path.basename(G.path), f'clear-coated area {ab["coat_share"]:.1%} in '
                             f'{os.path.basename(ab["path"])}, {coat_here:.1%} here', value=round(coat_here, 4)))
    # T1: texel density per image (the colour atlas; for a live-shader material the baked normal or the mask)
    band = ctx.get('band')
    if band:
        by_img = {}
        for g in groups:
            t = getattr(g, 'density_tex', None)
            if not t or g.cls == 'glass' or 'index' not in t: continue
            src, _ = G.tex_source(t['index'])
            if src is None: continue
            by_img.setdefault(src, {}).setdefault(g.material, (g, t))
        for src, mats_ in by_img.items():
            G.image(src); info = G.img_info.get(src, {}); W, H = info.get('w'), info.get('h')
            if not W: continue
            dens, wts = [], []
            for mname, (g, tinfo) in mats_.items():
                for ni, nname, pr, Pw, T, A in g.info['plist']:
                    tc = tinfo.get('texCoord', 0); at = pr['attributes']
                    if f'TEXCOORD_{tc}' not in at: continue
                    U = tex_uv(tinfo, {tc: G.acc(at[f'TEXCOORD_{tc}'])[:, :2]})
                    e1 = U[T[:, 1]] - U[T[:, 0]]; e2 = U[T[:, 2]] - U[T[:, 0]]
                    A2 = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) * W * H
                    ok = A > 1e-9; dens.append(np.sqrt(A2[ok] / A[ok])); wts.append(A[ok])
            if not dens: continue
            d = np.concatenate(dens); wt = np.concatenate(wts); o = np.argsort(d); cw = np.cumsum(wt[o]) / wt.sum()
            q = lambda x: float(d[o][min(np.searchsorted(cw, x), len(d) - 1)])
            med = q(0.5); need = band['need']; r = med / need
            names = sorted(mats_); a_share = sum(x.area for x in groups if x.material in mats_) / total
            label = f'{info.get("name") or "image" + str(src)} ({", ".join(names[:3])}{"…" if len(names) > 3 else ""})'
            msg = (f'median {med:.0f} px/m (p10 {q(0.1):.0f}, p90 {q(0.9):.0f}) on the {W}x{H} map; the {band["level"]} version is '
                   f'seen from {band["dist"]:.1f} m (switch.json family {band["family"]}) = {need:.0f} px/m at 1080p '
                   f'({need * 1.67:.0f} on a DPR-2 screen): x{r:.2f}')
            if r < 0.7: F.append(Finding('T1', 'WARN', label, msg, share=a_share, value=round(med, 1), threshold=round(0.7 * need, 1)))
            elif r > 2.5: F.append(Finding('T1', 'INFO', label, msg + ' (memory spent beyond need)', share=a_share,
                                           value=round(med, 1), threshold=round(2.5 * need, 1), decide=''))
    return F


def _tex_infos(mat):
    pb = mat.get('pbrMetallicRoughness') or {}; ex = mat.get('extensions') or {}
    out = [pb.get('baseColorTexture'), pb.get('metallicRoughnessTexture'), mat.get('normalTexture'),
           mat.get('occlusionTexture'), mat.get('emissiveTexture')]
    for e in ex.values():
        if isinstance(e, dict): out += [v for k, v in e.items() if k.endswith('Texture') and isinstance(v, dict)]
    return [t for t in out if t and 'index' in t]


def _merge(gs):
    np = _np(); g = Group(gs[0].material, gs[0].material, gs[0].mode)
    keys = set.intersection(*[set(x.s) for x in gs]) if gs else set()
    g.s = {k: np.concatenate([x.s[k] for x in gs]) for k in keys}; return g


def band_need(version, family, path):
    """Texel need of a version from switch.json (the one constant): px/m at the closest distance it is seen."""
    if not version: return None
    try:
        import _kit
        sw = _kit.switch(family)
    except BaseException:
        sw = None
    if not sw: return None
    d = sw['appears'][version]; cam = sw['camera']
    need = cam['rows'] / (2 * d * math.tan(math.radians(cam['fov_deg']) / 2))
    return {'level': version, 'family': sw['family'], 'dist': d, 'need': need}


def _family(family, cm_family, path):
    if family: return family, 'given'
    if cm_family: return cm_family, 'class map'
    low = os.path.abspath(path).lower(); base = os.path.basename(low)
    if '/train/' in low or re.match(r'trn\d', base): return 'train', 'path'
    return None, None


def _summary_lines(g, total):
    np = _np(); s = g.s; m = s['metal']; Y = luminance(s['base']); n = g.n()
    if not n: return [f"group '{g.name}' (no samples)"]
    lit = s['emit'].max(1) > 0.02
    head = (f"group '{g.name}' {g.area / total:.1%} of area ({g.area:.2f} m2), {n} samples, class {g.cls} "
            f"[{g.cls_src}]" + (f", lit: {g.lit_by_game}" if g.lit_by_game else '') +
            f", alpha {g.alpha_mode}{', doubleSided' if g.double_sided else ''}")
    maps = [f'{k} {v[0]}x{v[1]} {str(v[2]).split("/")[-1]}' for k, v in (g.tex or {}).items() if v and v[0]]
    if maps: head += ', maps ' + ' '.join(maps)
    diel, met, inb = m <= 0.1, m >= 0.9, (m > 0.1) & (m < 0.9)
    l2 = (f"    metallic: dielectric {diel.mean():.1%}  metal {met.mean():.1%}  in-between {inb.mean():.1%} (p5/50/95 {fmt_q(m)})"
          f"  coat>=0.5 {(s['coat'] >= 0.5).mean():.1%}")
    l3 = (f"    base Y p5/50/95 {fmt_q(Y)}  (sRGB {' '.join(f'{pct(lin2srgb8(Y), q):.0f}' for q in (5, 50, 95))})  rough p5/50/95 {fmt_q(s['rough'])}"
          f"  lit {lit.mean():.1%}" + (f" peak {s['emit'].max():.2f}" if lit.any() else ''))
    out = [head, l2, l3]
    out += [f'    note: {x}' for x in g.notes]
    return out


def group_json(g, total):
    np = _np(); s = g.s; n = g.n()
    d = {'group': g.name, 'material': g.material, 'mode': g.mode, 'class': g.cls, 'class_source': g.cls_src,
         'declared': g.declared, 'area_m2': round(g.area, 4), 'area_share': round(g.area / total, 4), 'samples': n,
         'alpha_mode': g.alpha_mode, 'double_sided': g.double_sided, 'lit_by': g.lit_by_game}
    if n:
        m = s['metal']; Y = luminance(s['base'])
        d.update(metal={'dielectric': round(float((m <= .1).mean()), 4), 'metal': round(float((m >= .9).mean()), 4),
                        'in_between': round(float(((m > .1) & (m < .9)).mean()), 4), 'p50': round(float(np.median(m)), 4)},
                 base_Y={'p5': round(pct(Y, 5), 4), 'p50': round(pct(Y, 50), 4), 'p95': round(pct(Y, 95), 4)},
                 rough={'p5': round(pct(s['rough'], 5), 4), 'p50': round(pct(s['rough'], 50), 4), 'p95': round(pct(s['rough'], 95), 4)},
                 coat_share=round(float((s['coat'] >= .5).mean()), 4),
                 lit_share=round(float((s['emit'].max(1) > .02).mean()), 4), emit_peak=round(float(s['emit'].max()), 4))
    if getattr(g, 'kind', None): d['kind'] = g.kind
    return d


def _above(path, entries, samples, rng):
    """Summary of the version above (or the original GLB) for E2 / M11."""
    np = _np(); G = Gltf(path); groups, total, _ = read_glb_groups(G, samples, rng, entries)
    lit = sum(g.area * float(((g.s['emit'].max(1) > .02) | bool(g.lit_by_game)).mean()) for g in groups if g.n()) / total
    coat_mats = {}
    for g in groups:
        if g.n() and (g.s['coat'] >= 0.5).mean() > 0.05: coat_mats[g.material] = float((g.s['coat'] >= .5).mean())
    coat_share = sum(g.area * float((g.s['coat'] >= .5).mean()) for g in groups if g.n()) / total
    return {'path': path, 'lit_share': lit, 'coat_mats': coat_mats, 'coat_share': coat_share}


# ------------------------------------------------------------------------------------------------------ heat maps
HEAT = {'M2': (255, 30, 30), 'M1': (255, 160, 0), 'M3': (40, 110, 255), 'M6': (160, 60, 255), 'M7': (0, 220, 220)}


def heatmaps(G, groups, ctx, out_dir, stem):
    """Per textured material: its colour map dimmed, failing texels marked (M2 red, M1 orange, M3 blue, M6 purple,
    M7 cyan); per normal map: B <= 0.5 magenta, length error > 0.1 yellow. Returns written paths."""
    np = _np(); os.makedirs(out_dir, exist_ok=True); written = []
    from PIL import Image
    done = set()
    for g in groups:
        if g.mode != 'pbr' or g.material in done: continue
        done.add(g.material); mat = g.info['mat']; pb = mat.get('pbrMetallicRoughness') or {}
        bt, mt = pb.get('baseColorTexture'), pb.get('metallicRoughnessTexture')
        ref = bt or mt
        if not ref: continue
        src, _ = G.tex_source(ref['index']); img = G.image(src)
        if img is None: continue
        h, w = img.shape[:2]; cov = np.zeros((h, w), bool)
        for ni, nname, pr, Pw, T, A in g.info['plist']:
            tc = ref.get('texCoord', 0); at = pr['attributes']
            if f'TEXCOORD_{tc}' in at: cov |= raster(tex_uv(ref, {tc: G.acc(at[f'TEXCOORD_{tc}'])[:, :2]})[T], w, h)
        bf = np.array(pb.get('baseColorFactor', [1, 1, 1, 1])[:3])
        bf = bf.astype(np.float32)
        base = srgb2lin(G.image(G.tex_source(bt['index'])[0])[..., :3].astype(np.float32) / 255) * bf if bt else np.ones((h, w, 3), np.float32) * bf
        if base.shape[:2] != (h, w): base = _resize_nearest(base, h, w)
        mf, rf = float(pb.get('metallicFactor', 1.0)), float(pb.get('roughnessFactor', 1.0))
        if mt:
            mr = G.image(G.tex_source(mt['index'])[0]).astype(np.float32) / 255
            if mr.shape[:2] != (h, w): mr = _resize_nearest(mr, h, w)
            metal = mr[..., 2] * mf
        else:
            metal = np.full((h, w), mf)
        coat = float(((mat.get('extensions') or {}).get('KHR_materials_clearcoat') or {}).get('clearcoatFactor', 0))
        Y = luminance(base); Y8 = lin2srgb8(Y)
        inb = (metal > .1) & (metal < .9) & (coat < .5)
        flags = {'M1': inb, 'M2': inb & (Y > .5), 'M3': (metal >= .9) & (Y < .35), 'M6': (metal <= .1) & (Y8 < 30),
                 'M7': (metal <= .1) & (Y8 > 243)}
        grey = (lin2srgb8(Y) * 0.35)[..., None].repeat(3, 2); out = np.where(cov[..., None], grey, 0.0)
        counts = {}
        for rule in ('M1', 'M6', 'M7', 'M3', 'M2'):
            f = flags[rule] & cov; counts[rule] = round(float(f.sum() / max(cov.sum(), 1)), 4)
            out[f] = np.array(HEAT[rule], float) * 0.9 + out[f] * 0.1
        p = os.path.join(out_dir, f'{stem}.{_safe(g.material)}.heat.png')
        Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(p); written.append(p)
        ctx.setdefault('heat', {})[g.material] = {'file': p, 'covered_texel_share': counts}
    for src, d in (ctx.get('normal_maps') or {}).items():
        img = G.image(src); cov = d['cov']; px = img[..., :3].astype(np.float32) / 255
        L = np.abs(np.linalg.norm(px * 2 - 1, axis=2) - 1); out = np.where(cov[..., None], img[..., :3] * 0.35, 0.0)
        out[cov & (L > 0.1)] = (255, 220, 0); out[cov & (px[..., 2] <= 0.5)] = (255, 0, 255)
        p = os.path.join(out_dir, f'{stem}.{_safe(d["label"].split(" ")[0])}.normal-heat.png')
        Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(p); written.append(p)
    return written


def _resize_nearest(a, h, w):
    np = _np(); H, W = a.shape[:2]
    return a[(np.arange(h) * H // h)[:, None], (np.arange(w) * W // w)[None, :]]


def _safe(s): return re.sub(r'[^A-Za-z0-9_.-]+', '_', s or 'x')[:60]


# ------------------------------------------------------------------------------------------------------ GLB entry
def check_glb(path, class_map=None, version=None, against=None, samples=20000, family=None, heatmap=None, strict=False,
              json_out=None, seed=1, lights=None):
    """Check a GLB. class_map: asset.json path or dict; version: near|mid|far (default from the file name);
    against: the version above or the original GLB (E2 lit share, M11 lost coat); heatmap: a folder for heat PNGs;
    lights: extra reason the asset has night lights (str). Returns Result; writes only json_out / heatmap when given."""
    np = _np(); rng = np.random.default_rng(seed)
    if class_map is None: class_map = find_asset_json(path)        # the asset's own record, when it sits beside it
    entries, cm_lights, cm_family, cm_src = load_class_map(class_map)
    G = Gltf(path)
    groups, total, prims = read_glb_groups(G, samples, rng, entries)
    base = os.path.basename(path)
    version = version or next((v for v in ('near', 'mid', 'far') if re.search(rf'(^|[-_.]){v}([-_.]|$)', base)), None)
    fam, fam_src = _family(family, cm_family, path)
    node_names = {i: nd.get('name', f'node{i}') for i, nd in enumerate(G.j.get('nodes', []))}
    lights_nodes = [n for n in node_names.values() if n.startswith('light.')]
    night = lights or ('asset.json "lights"' if cm_lights else None) or (f'{len(lights_nodes)} light.* empties' if lights_nodes else None) \
        or next((f"class {g.cls} '{g.name}'" for g in groups if g.declared and g.cls == 'emissive'), None) \
        or (GAME_DEFAULT_FAMILIES_NIGHT.get(fam) if fam else None)
    ctx = {'node_names': node_names, 'prims': prims, 'night_declared': night, 'band': band_need(version, fam, path)}
    if against: ctx['above'] = _above(against, entries, samples, np.random.default_rng(seed))
    findings = []
    for g in groups: findings += group_rules(g, ctx)
    findings += asset_rules(groups, total, G, ctx)
    if entries:
        for g in groups:
            if not g.entry and g.mode == 'pbr': g.notes.append('not in the class map')
    findings.sort(key=lambda f: (-SEVERITY_RANK[f.sev], f.rule, f.group))
    lines = [f'PBR CHECK {path}', f'  version {version or "?"}, family {fam or "?"}' + (f' ({fam_src})' if fam_src else '') +
             f'; {sum(g.n() for g in groups)} samples over {total:.2f} m2; class map {cm_src or ("given" if entries else "none")}'
             f'; night lights: {night or "none declared"}; lit share {ctx.get("lit_share", 0):.2%}' +
             (f'; against {against}' if against else '')]
    for g in sorted(groups, key=lambda x: -x.area): lines += ['  ' + x if i == 0 else '  ' + x for i, x in enumerate(_summary_lines(g, total))]
    lines += [f.line() for f in findings]
    meta = {'version': version, 'family': fam, 'band': ctx.get('band'), 'area_m2': round(total, 4), 'samples': samples,
            'class_map': cm_src, 'night_declared': night, 'lit_share': round(ctx.get('lit_share', 0), 5), 'against': against,
            'library': library().get('dir')}
    res = Result(path, findings, lines, [group_json(g, total) for g in groups], meta, strict)
    if heatmap:
        try:
            res.meta['heatmaps'] = heatmaps(G, groups, ctx, heatmap, os.path.splitext(base)[0]); res.meta['heat'] = ctx.get('heat')
        except ImportError:
            res.meta['heatmaps'] = 'Pillow missing: no heat maps'
    if json_out:
        tmp = json_out + '.tmp'
        with open(tmp, 'w') as f: json.dump(res.to_json(), f, indent=1, default=_json_default)
        os.replace(tmp, json_out)
    return res


def _json_default(o):
    try:
        import numpy as np
        if isinstance(o, np.generic): return o.item()
        if isinstance(o, np.ndarray): return o.tolist()
    except ImportError:
        pass
    return str(o)


# ------------------------------------------------------------------------------------------------------ .blend side
# the channels each value rule reads (a .blend whose channel is linked and not baked cannot be judged by that rule)
RULE_NEEDS = {'M1': ('metal', 'coat'), 'M2': ('metal', 'base', 'coat'), 'M3': ('metal', 'base'), 'M4': ('metal', 'base'),
              'M5': ('metal', 'coat'), 'M6': ('metal', 'base'), 'M7': ('metal', 'base'), 'M8': ('rough',), 'M9': ('rough', 'metal'),
              'M11': ('coat',)}
COLOR_SOCKETS = ('Base Color', 'Emission Color', 'Coat Tint', 'Sheen Tint', 'Specular Tint', 'Subsurface Color')
DATA_SOCKETS = ('Metallic', 'Roughness', 'Alpha', 'Coat Weight', 'Coat Roughness', 'Transmission Weight', 'IOR',
                'Specular IOR Level', 'Anisotropic', 'Normal', 'Coat Normal', 'Emission Strength')
PASS_THROUGH = {'REROUTE', 'MIX', 'MIX_RGB', 'HUE_SAT', 'BRIGHTCONTRAST', 'GAMMA', 'INVERT', 'CURVE_RGB'}
TO_DATA = {'SEPARATE_COLOR', 'SEPRGB', 'MATH', 'MAP_RANGE', 'CLAMP', 'NORMAL_MAP', 'BUMP', 'VALTORGB', 'RGBTOBW'}


def _principled_nodes(m):
    """Principled BSDFs that feed the material output (inside groups too), with the path of group nodes."""
    out = []; seen = set()
    def walk(tree, sock, path, depth):
        if depth > 30 or not sock.is_linked: return
        for l in sock.links:
            if l.is_muted: continue
            n = l.from_node
            if (tree.name, n.name, path) in seen: continue
            seen.add((tree.name, n.name, path))
            if n.type == 'BSDF_PRINCIPLED': out.append((n, path)); continue
            if n.type == 'GROUP' and n.node_tree:
                go = next((x for x in n.node_tree.nodes if x.type == 'GROUP_OUTPUT' and x.is_active_output), None) or \
                    next((x for x in n.node_tree.nodes if x.type == 'GROUP_OUTPUT'), None)
                if go:
                    for i in go.inputs:
                        if i.type == 'SHADER': walk(n.node_tree, i, path + (n.name,), depth + 1)
                continue
            if n.type == 'REROUTE' and n.type != 'GROUP_INPUT': walk(tree, n.inputs[0], path, depth + 1); continue
            for i in n.inputs:
                if i.type == 'SHADER': walk(tree, i, path, depth + 1)
    try:
        import _kit
        on = _kit.output_node(m)
    except Exception:
        on = next((n for n in m.node_tree.nodes if n.type == 'OUTPUT_MATERIAL'), None) if m.node_tree else None
    if on is not None: walk(m.node_tree, on.inputs['Surface'], (), 0)
    return out


def _idle_group(m):
    if not m or not m.node_tree: return None
    for n in m.node_tree.nodes:
        if n.type == 'GROUP' and n.node_tree and n.node_tree.get('idle_kind'): return n
    return None


def _images_upstream(sock, role, depth=0, out=None):
    """(image, role) pairs that reach a socket through nodes that keep the image's meaning: colour through mixes and
    colour corrections, data through reroutes, Separate Color and Normal Map. An image that passes a ColorRamp, Math,
    Map Range or Bump is an artist's mask whose response was tuned by eye: not judged."""
    out = [] if out is None else out
    if depth > 12 or not sock.is_linked: return out
    for l in sock.links:
        if l.is_muted: continue
        n = l.from_node
        if n.type == 'TEX_IMAGE':
            if n.image and l.from_socket.name == 'Color': out.append((n.image, role, n.name))
            elif n.image and l.from_socket.name == 'Alpha': out.append((n.image, 'alpha', n.name))
            continue
        if n.type == 'REROUTE': _images_upstream(n.inputs[0], role, depth + 1, out); continue
        if role == 'color' and n.type in ('MIX', 'MIX_RGB', 'HUE_SAT', 'BRIGHTCONTRAST', 'GAMMA', 'INVERT', 'CURVE_RGB'):
            for i in n.inputs:
                if i.type == 'RGBA' and i.name not in ('Fac', 'Factor'): _images_upstream(i, role, depth + 1, out)
            continue
        if role == 'data' and n.type in ('SEPARATE_COLOR', 'SEPRGB', 'NORMAL_MAP'):
            _images_upstream(n.inputs['Color'] if 'Color' in n.inputs else n.inputs[0], 'data', depth + 1, out)
    return out


def check_blend(collection=None, class_map=None, bake=0, for_bake=False, objects=None, against=None, strict=False,
                json_out=None, lights=None):
    """Inside Blender: check the materials of a collection (default: every visible mesh). Unlinked Principled inputs
    are read; linked ones are measured by an N x N emission bake per object when bake=N (else reported as not
    measured). for_bake=True (bake.py pre-flight): a coated in-between metal is M11 ERROR (the bake has no coat
    channel). against: the exported GLB, for M11 (coat in the .blend, none in the GLB). Nothing is saved."""
    import bpy
    np = _np()
    if class_map is None: class_map = find_asset_json(bpy.data.filepath)
    entries, cm_lights, cm_family, cm_src = load_class_map(class_map)
    if objects is None:
        if collection:                                  # one name or a comma list (bake.py passes its --high as given)
            objects = []
            for cname in [c.strip() for c in collection.split(',') if c.strip()]:
                if cname not in bpy.data.collections: raise SystemExit(f'no collection {cname!r}')
                objects += [o for o in bpy.data.collections[cname].all_objects if o not in objects]
        else:
            objects = [o for o in bpy.context.scene.objects if not o.hide_render]
    objset = {o.name for o in objects}
    deps = bpy.context.evaluated_depsgraph_get()
    area, where_pts, rep = {}, {}, {}
    for inst in deps.object_instances:
        ob = inst.object; orig = ob.original
        owner = inst.parent.original if inst.is_instance and inst.parent else orig
        if owner.name not in objset and orig.name not in objset: continue
        if ob.type not in ('MESH', 'CURVE', 'SURFACE', 'FONT', 'META'): continue
        try: me = ob.to_mesh()
        except RuntimeError: continue
        if me is None: continue
        me.calc_loop_triangles(); nt = len(me.loop_triangles)
        if nt:
            co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
            Mw = np.array(inst.matrix_world); co = co @ Mw[:3, :3].T + Mw[:3, 3]
            tv = np.empty(nt * 3, np.int64); me.loop_triangles.foreach_get('vertices', tv); tv = tv.reshape(-1, 3)
            mi = np.empty(nt, np.int64); me.loop_triangles.foreach_get('material_index', mi)
            A = 0.5 * np.linalg.norm(np.cross(co[tv[:, 1]] - co[tv[:, 0]], co[tv[:, 2]] - co[tv[:, 0]]), axis=1)
            slots = ob.material_slots
            for k in np.unique(mi):
                m = slots[k].material if k < len(slots) else None
                if m is None: continue
                sel = mi == k; area[m.name] = area.get(m.name, 0.0) + float(A[sel].sum())
                c = co[tv[sel]].mean(1); c = c[np.argsort(-A[sel])[:50]]
                where_pts.setdefault(m.name, []).append((orig.name, c))
                a_here = float(A[sel].sum())
                if a_here > rep.get(m.name, (None, None, 0))[2]: rep[m.name] = (orig.name, [list(r) for r in inst.matrix_world], a_here)
        ob.to_mesh_clear()
    total = sum(area.values()) or 1.0
    groups, F = [], []
    blend_name = os.path.basename(bpy.data.filepath) or '(unsaved)'
    for mname, a in sorted(area.items(), key=lambda x: -x[1]):
        m = bpy.data.materials[mname]; g = Group(mname, mname, 'blend'); g.area = a; g.info = {'mat': None}
        for k in m.keys():
            v = m[k]; g.props[k] = v.to_dict() if hasattr(v, 'to_dict') else v.to_list() if hasattr(v, 'to_list') else v
        n = 64
        vals = {'base': None, 'metal': None, 'rough': None, 'coat': None, 'emit': None, 'alpha': None}; linked = []
        ig = _idle_group(m)
        if ig is not None:
            kind = ig.node_tree['idle_kind']; p = dict(kind_defaults(kind))
            for i in ig.inputs:
                if not i.is_linked and hasattr(i, 'default_value'):
                    v = i.default_value; p[i.name] = list(v)[:3] if hasattr(v, '__len__') else float(v)
            g.s = {'metal': np.zeros(n), 'base': np.zeros((n, 3)), 'rough': np.zeros(n), 'coat': np.zeros(n), 'emit': np.zeros((n, 3)), 'alpha': np.ones(n)}
            _apply_kind(g, {'kind': kind, 'p': p}); g.mode = 'idle'
        else:
            pr = _principled_nodes(m)
            if not pr:
                g.notes.append('no Principled BSDF reaches the output: not measured'); g.s = {}
            else:
                node, path = pr[0]
                if len(pr) > 1: g.notes.append(f'{len(pr)} Principled BSDFs mixed: the first is read, a bake measures the mix')
                def val(name, default):
                    s = node.inputs.get(name)
                    if s is None: return default
                    if s.is_linked: linked.append(name); return None
                    v = s.default_value
                    return list(v)[:3] if hasattr(v, '__len__') else float(v)
                b = val('Base Color', [0.8] * 3); mt = val('Metallic', 0.0); rg = val('Roughness', 0.5)
                cw = val('Coat Weight', 0.0); es = val('Emission Strength', 0.0); ec = val('Emission Color', [0, 0, 0])
                al = val('Alpha', 1.0); tw = val('Transmission Weight', 0.0)
                if tw is not None and tw >= 0.5: g.cls, g.cls_src = 'glass', 'Transmission Weight >= 0.5'
                g.s = {}
                for k, v in (('base', b), ('metal', mt), ('rough', rg), ('coat', cw), ('alpha', al)):
                    if v is not None: g.s[k] = np.tile(np.array(v, float), (n, 1)) if k == 'base' else np.full(n, float(v))
                if es is not None and ec is not None: g.s['emit'] = np.tile(np.array(ec, float) * es, (n, 1))
                elif es is not None and es == 0: g.s['emit'] = np.zeros((n, 3))
                g.linked = linked
                # G7: image colour spaces against their roles
                seen_g7 = set()
                for sock in node.inputs:
                    role = 'color' if sock.name in COLOR_SOCKETS else 'data' if sock.name in DATA_SOCKETS else None
                    if role is None or not sock.is_linked: continue
                    for img, r, nn in _images_upstream(sock, role):
                        if r == 'alpha' or (img.name, sock.name) in seen_g7: continue
                        seen_g7.add((img.name, sock.name))
                        cs = img.colorspace_settings.name; is_srgb = 'srgb' in cs.lower() and 'linear' not in cs.lower()
                        if r == 'color' and not is_srgb and not img.is_float:
                            F.append(Finding('G7', 'ERROR', mname, f"image '{img.name}' feeds {sock.name} but is {cs!r} (colour wants sRGB)"))
                        if r == 'data' and is_srgb:
                            F.append(Finding('G7', 'ERROR', mname, f"image '{img.name}' feeds {sock.name} as data but is {cs!r} (wants Non-Color)"))
        g.pts = where_pts.get(mname, [])
        groups.append(g)
    if bake:
        _blend_bake(groups, rep, bake)
    for g in groups:
        _assign_class(g, entries)
        missing = [k for k in ('base', 'metal', 'rough', 'coat') if k not in g.s]
        g.unmeasured = list(missing)
        if missing:
            g.notes.append(f'linked, not measured: {", ".join(getattr(g, "linked", []) or missing)} '
                           f'(run with --bake 64, or check the exported GLB)')
        n = max((len(v) for v in g.s.values()), default=0)
        # rules need all channels: fill unknowns with neutral values that cannot trip a rule, and say so
        fill = {'base': np.full((n, 3), 0.3), 'metal': np.zeros(n), 'rough': np.full(n, 0.5), 'coat': np.zeros(n),
                'emit': np.zeros((n, 3)), 'alpha': np.ones(n)}
        unknown_metal = 'metal' not in g.s; unknown_base = 'base' not in g.s
        for k, v in fill.items(): g.s.setdefault(k, v)
        g.s['pos'] = np.zeros((n, 3))
        if unknown_base and not unknown_metal:
            mm = g.s['metal']; inb = (mm > .1) & (mm < .9) & (g.s['coat'] < .5)
            if inb.mean() > 0.2: g.notes.append('base colour linked: M2 (white plastic) not measured; M1 still applies')
        g.unknown_metal = unknown_metal
    node_pts = {}
    findings = list(F)
    for g in groups:
        ctx = {'node_names': None}
        fs = group_rules(g, ctx)
        # A linked input that was not measured holds a stand-in value (base 0.3, coat 0 ...): a rule that reads it has
        # nothing to judge. Such findings become ONE INFO line ("not measured"), never a WARN or an ERROR.
        unm = set(getattr(g, 'unmeasured', None) or [])
        skipped = sorted({f.rule for f in fs if unm & set(RULE_NEEDS.get(f.rule, ()))})
        if skipped:
            fs = [f for f in fs if f.rule not in skipped]
            fs.append(Finding('M0', 'INFO', g.name, f'not measured: {", ".join(skipped)} not judged, {", ".join(sorted(unm))} '
                              f'{"is" if len(unm) == 1 else "are"} driven by nodes (linked). Measure with --bake 64, or check the exported GLB',
                              decide=''))
        for f in fs:
            f.where = _blend_where(g)
        findings += fs
        # M11: a coat in the original
        if g.n():
            coat = g.s['coat']; m = g.s['metal']
            if (coat >= 0.5).mean() > 0.05:
                mid = ((m > .1) & (m < .9)).mean() > 0.2
                if for_bake:
                    findings.append(Finding('M11', 'ERROR' if mid else 'WARN', g.name,
                                            f'Coat Weight {np.median(coat):.2f} on {"an in-between metal" if mid else "a surface"}: the bake has no coat '
                                            f'channel, so the game version {"turns into white plastic (M2)" if mid else "loses its gloss layer"}',
                                            share=g.area / total))
    if against:
        G = Gltf(against); ab = {(x.get('name') or ''): x for x in G.j.get('materials', [])}
        for g in groups:
            if g.n() and (g.s['coat'] >= .5).mean() > 0.05:
                gm = ab.get(g.name)
                cc = ((gm or {}).get('extensions') or {}).get('KHR_materials_clearcoat') if gm else None
                if gm is not None and not cc:
                    findings.append(Finding('M11', 'ERROR', g.name, f'Coat Weight {np.median(g.s["coat"]):.2f} in the .blend, no '
                                            f'KHR_materials_clearcoat in {os.path.basename(against)}', share=g.area / total))
    # E1 in the original: lamps by real lights only = nothing to bake
    light_objs = [o.name for o in objects if o.name.startswith('light.')]
    fam, _ = _family(None, cm_family, bpy.data.filepath or '')
    decl = lights or ('asset.json "lights"' if cm_lights else None) or (f'{len(light_objs)} light.* empties' if light_objs else None) \
        or (GAME_DEFAULT_FAMILIES_NIGHT.get(fam) if fam else None)
    emitting = [g.name for g in groups if g.n() and (g.s['emit'].max(1) > 0.02).any()]
    linked_emit = [g.name for g in groups if 'Emission Strength' in (getattr(g, 'linked', None) or []) or
                   'Emission Color' in (getattr(g, 'linked', None) or [])]
    if decl and not emitting and not linked_emit:
        findings.append(Finding('E1', 'ERROR', blend_name, f'night lights declared ({decl}) but no material emits: the bake '
                                f'has nothing to bake, so every game version is dark at night'))
    findings.sort(key=lambda f: (-SEVERITY_RANK[f.sev], f.rule, f.group))
    lines = [f'PBR CHECK {bpy.data.filepath or "(unsaved)"} collection {collection or "(visible)"}: {len(groups)} materials over '
             f'{total:.2f} m2; class map {cm_src or ("given" if entries else "none")}; bake {bake or "off"}; night lights: {decl or "none declared"}']
    for g in groups:
        lines += ['  ' + x for x in _summary_lines(g, total)] if g.n() else [f"  group '{g.name}' not measured"] + [f'    note: {x}' for x in g.notes]
    lines += [f.line() for f in findings]
    meta = {'mode': 'blend', 'collection': collection, 'area_m2': round(total, 4), 'class_map': cm_src, 'bake': bake,
            'for_bake': for_bake, 'night_declared': decl}
    res = Result(bpy.data.filepath, findings, lines, [group_json(g, total) for g in groups], meta, strict)
    if json_out:
        with open(json_out + '.tmp', 'w') as f: json.dump(res.to_json(), f, indent=1, default=_json_default)
        os.replace(json_out + '.tmp', json_out)
    return res


def _blend_where(g):
    """Where a .blend material sits: its biggest objects with face centres in glTF frame (x, z, -y)."""
    np = _np(); out = []
    for name, c in sorted(g.pts, key=lambda x: -len(x[1]))[:5]:
        p = np.asarray(c); q = np.stack([p[:, 0], p[:, 2], -p[:, 1]], 1)
        out.append({'object': name, 'gltf_xyz': [round(float(x), 3) for x in q.mean(0)],
                    'box_gltf': [[round(float(x), 3) for x in q.min(0)], [round(float(x), 3) for x in q.max(0)]]})
    return out


def _blend_bake(groups, rep, N):
    """Measure linked channels. Per object that carries a not-yet-measured material (the instance where that material
    has the most area): an evaluated copy with local copies of its materials (linked library data stays untouched), a
    fresh Smart-UV layer as the bake target (the authored UVs stay the render UVs the textures read), N x N emission
    bakes of colour and of rough/metal through _kit.MaterialSwap, texels assigned to materials by a material-index
    raster. Everything temporary is removed again; nothing is saved."""
    import bpy, _kit
    np = _np()
    need = {g.name: g for g in groups if g.mode == 'blend' and any(k not in g.s for k in ('base', 'metal', 'rough', 'coat'))}
    if not need: return
    by_obj = {}
    for mname in need:
        if mname in rep: by_obj.setdefault(rep[mname][0], rep[mname][1])
    deps = bpy.context.evaluated_depsgraph_get()
    scene = bpy.context.scene
    keep = (scene.render.engine, scene.cycles.samples, scene.render.bake.use_selected_to_active)
    scene.render.engine = 'CYCLES'; scene.cycles.samples = 1; scene.render.bake.use_selected_to_active = False
    coll = bpy.data.collections.new('_pbrchk_'); scene.collection.children.link(coll)
    made = []
    try:
        for oname, mw in by_obj.items():
            o = bpy.data.objects.get(oname)
            if o is None or o.type != 'MESH': continue
            me = bpy.data.meshes.new_from_object(o.evaluated_get(deps)); made.append(me)
            tmp = bpy.data.objects.new('_pbrchk_obj', me); coll.objects.link(tmp)
            from mathutils import Matrix
            tmp.matrix_world = Matrix(mw)
            copies = {}
            for i, sl in enumerate(tmp.material_slots):
                src = sl.material
                if src is None or src.node_tree is None: continue
                c = src.copy(); copies[c.name] = src.name; sl.link = 'OBJECT'; sl.material = c
            if not copies: continue
            render_uv = next((u for u in me.uv_layers if u.active_render), None)
            uvl = me.uv_layers.new(name='_pbrchk_uv')
            if render_uv is not None: render_uv.active_render = True
            me.uv_layers.active = uvl
            for ob2 in bpy.context.view_layer.objects: ob2.select_set(False)
            bpy.context.view_layer.objects.active = tmp; tmp.select_set(True)
            bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.smart_project(island_margin=0.0, scale_to_bounds=False)
            bpy.ops.object.mode_set(mode='OBJECT')
            img = bpy.data.images.new('_pbrchk_img', N, N, float_buffer=True); img.colorspace_settings.name = 'Non-Color'
            mats = [sl.material for sl in tmp.material_slots if sl.material and sl.material.name in copies]
            tns = []
            for m in mats:
                tn = m.node_tree.nodes.new('ShaderNodeTexImage'); tn.image = img; tn.name = '_pbrchk_img'; tns.append((m, tn))
            me.calc_loop_triangles(); nt = len(me.loop_triangles)
            uvl = me.uv_layers['_pbrchk_uv']          # re-fetch: the edit-mode round trip left the old reference dangling (crash)
            luv = np.empty(len(me.loops) * 2); uvl.data.foreach_get('uv', luv); luv = luv.reshape(-1, 2)
            tl = np.empty(nt * 3, np.int64); me.loop_triangles.foreach_get('loops', tl); tl = tl.reshape(-1, 3)
            mi = np.empty(nt, np.int64); me.loop_triangles.foreach_get('material_index', mi)
            ids = np.full((N, N), -1, np.int64); tri = luv[tl]        # Blender pixel row 0 = v 0, as raster() counts
            for k in np.unique(mi): ids[raster(tri[mi == k], N, N)] = k
            swap = _kit.MaterialSwap(mats); vals = {}
            try:
                for chan in ('color', 'packed'):
                    swap.set(chan)
                    for m, tn in tns: m.node_tree.nodes.active = tn     # new nodes made by set() took the active slot
                    bpy.ops.object.bake(type='EMIT', margin=0, use_clear=True)
                    px = np.empty(N * N * 4, np.float32); img.pixels.foreach_get(px); vals[chan] = px.reshape(N, N, 4)
            finally:
                swap.restore()
            # a linked Coat Weight: its source socket through an Emission, one more pass (MaterialSwap has no coat channel)
            coat_baked = set(); coat_inside = set()
            for m in mats:
                pr = _principled_nodes(m)
                if not pr: continue
                node, path = pr[0]; cs = node.inputs.get('Coat Weight')
                if cs is None or not cs.is_linked: continue
                on = _kit.output_node(m)
                if path or on is None: coat_inside.add(m.name); continue        # inside a node group: not reachable from here
                nt = m.node_tree; em = nt.nodes.new('ShaderNodeEmission'); em.name = '_pbrchk_coat'; em.inputs['Strength'].default_value = 1.0
                nt.links.new(cs.links[0].from_socket, em.inputs['Color']); nt.links.new(em.outputs[0], on.inputs['Surface'])
                coat_baked.add(m.name)
            if coat_baked:
                for m, tn in tns: m.node_tree.nodes.active = tn
                bpy.ops.object.bake(type='EMIT', margin=0, use_clear=True)
                px = np.empty(N * N * 4, np.float32); img.pixels.foreach_get(px); vals['coat'] = px.reshape(N, N, 4)
            bpy.data.images.remove(img)
            for k, sl in enumerate(tmp.material_slots):
                if not sl.material or sl.material.name not in copies: continue
                g = need.get(copies[sl.material.name]); assigned = int((ids == k).sum())
                sel = ids == k
                if g is None or sel.sum() < 4 or getattr(g, '_baked', False):
                    if g is not None and not getattr(g, '_baked', False):
                        g.notes.append(f'bake on {oname}: only {assigned} texels at {N}x{N} (raise --bake)')
                    continue
                cnt = int(sel.sum()); old = g.s
                g.s = {'base': vals['color'][sel][:, :3].astype(float), 'rough': vals['packed'][sel][:, 0].astype(float),
                       'metal': vals['packed'][sel][:, 1].astype(float)}
                for key in ('coat', 'emit', 'alpha'):
                    v = old.get(key)
                    if v is not None: g.s[key] = np.resize(v, (cnt,) + v.shape[1:])
                if sl.material.name in coat_baked: g.s['coat'] = vals['coat'][sel][:, 0].astype(float)
                elif sl.material.name in coat_inside: g.notes.append('Coat Weight is linked inside a node group: not measured by the bake')
                g._baked = True; g.linked = [x for x in (getattr(g, 'linked', None) or []) if x == 'Coat Weight' and 'coat' not in g.s]
                g.notes.append(f'linked inputs measured by a {N}x{N} emission bake on {oname} ({cnt} texels)')
            for c in list(copies): bpy.data.materials.remove(bpy.data.materials[c])
            bpy.data.objects.remove(tmp)
    finally:
        for o in list(coll.objects): bpy.data.objects.remove(o)
        bpy.data.collections.remove(coll)
        for me in made:
            if me.name in bpy.data.meshes and me.users == 0: bpy.data.meshes.remove(me)
        scene.render.engine, scene.cycles.samples, scene.render.bake.use_selected_to_active = keep


# ------------------------------------------------------------------------------------------------------ CLI
def main(argv=None):
    import argparse
    in_blender = 'bpy' in sys.modules or os.path.basename(sys.executable).startswith('blender')
    try:
        import bpy  # noqa: F401
        in_blender = bool(getattr(bpy.data, 'filepath', None) is not None)
    except ImportError:
        in_blender = False
    a = sys.argv
    argv = argv if argv is not None else (a[a.index('--') + 1:] if '--' in a else a[1:] if not in_blender else [])
    ap = argparse.ArgumentParser(prog='pbr_check.py', description=__doc__.split('\n\n')[0])
    ap.add_argument('file', nargs='?', help='GLB / glTF (omit inside Blender to check the open .blend)')
    ap.add_argument('--class-map', help='asset.json with "materials": {name: {class, metal, source, sheet}} '
                    '(default: an asset.json beside the file or up to two folders above it)')
    ap.add_argument('--version', choices=('near', 'mid', 'far'), help='band for T1 (default from the file name)')
    ap.add_argument('--family', help='switch.json family for T1 and night (default: class map / path / switch.json default)')
    ap.add_argument('--against', help='GLB: the version above or the original (E2, M11); .blend: the exported GLB (M11)')
    ap.add_argument('--samples', type=int, default=20000)
    ap.add_argument('--json', help='write the findings here')
    ap.add_argument('--heatmap', help='folder for heat maps (failing texels marked)')
    ap.add_argument('--strict', action='store_true', help='WARN fails too')
    ap.add_argument('--quiet', action='store_true', help='print only findings and the result line')
    ap.add_argument('--lights', help='declare night lights (reason text) for E1')
    ap.add_argument('--collection', help='.blend: the collection to check')
    ap.add_argument('--bake', type=int, default=0, help='.blend: measure linked inputs with an N x N emission bake')
    ap.add_argument('--for-bake', action='store_true', help='.blend: pre-flight of bake.py (coated in-between metal = M11)')
    ap.add_argument('--rules', action='store_true', help='print every rule and exit')
    A = ap.parse_args(argv)
    if A.rules:
        for k, (w, t, s) in RULES.items(): print(f'{k:4s} {w}\n     {t}\n     source: {s}')
        return 0
    if A.file and A.file.lower().endswith('.blend'):
        if not in_blender:                              # plain python3: start Blender on the file with the same options
            return _run_in_blender(A.file, [x for x in argv if x != A.file])
        import bpy
        if os.path.abspath(A.file) != os.path.abspath(bpy.data.filepath or ''):
            bpy.ops.wm.open_mainfile(filepath=os.path.abspath(A.file))
        A.file = None
    if A.file:
        r = check_glb(A.file, class_map=A.class_map, version=A.version, against=A.against, samples=A.samples,
                      family=A.family, heatmap=A.heatmap, strict=A.strict, json_out=A.json, lights=A.lights)
    elif in_blender:
        r = check_blend(collection=A.collection, class_map=A.class_map, bake=A.bake, for_bake=A.for_bake, against=A.against,
                        strict=A.strict, json_out=A.json, lights=A.lights)
    else:
        ap.error('give a .glb, or run inside Blender on a .blend')
    lines = r.lines if not A.quiet else [x for x in r.lines if re.match(r'(ERROR|WARN|INFO) |PBR RESULT', x)]
    print('\n'.join(lines), flush=True)
    if A.heatmap and r.meta.get('heatmaps'): print('heat maps:', r.meta['heatmaps'] if isinstance(r.meta['heatmaps'], str) else ', '.join(r.meta['heatmaps']))
    return 0 if r.ok else 2


def _run_in_blender(blend, rest):
    """python3 pbr_check.py FILE.blend ...: a .blend can only be read inside Blender, so run Blender on it (headless,
    8 threads, nice 10, in a 12 GB memory scope when this session may make one) and hand its result code back."""
    import shutil, subprocess
    b = next((p for p in (os.environ.get('BLENDER'), '/snap/blender/current/blender', shutil.which('blender'))
              if p and os.path.exists(p)), None)
    me = os.path.abspath(__file__); blend = os.path.abspath(blend)
    form = f'<blender> -b --factory-startup -noaudio -t 8 {blend} --python {me} -- [--collection C.<name>] [--bake 64]'
    if not os.path.exists(blend):
        print(f'pbr_check: no file {blend}'); return 2
    if b is None:
        print(f'pbr_check: a .blend is read inside Blender and no Blender was found (set BLENDER=/path/to/blender). Run:\n  {form}'); return 2
    cmd = ['nice', '-n', '10', b, '-b', '--factory-startup', '-noaudio', '-t', '8', blend, '--python', me, '--'] + list(rest)
    if shutil.which('systemd-run') and not os.environ.get('PBR_NO_SCOPE') and subprocess.call(
            ['systemd-run', '--user', '--scope', '-q', 'true'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
        cmd = ['systemd-run', '--user', '--scope', '-q', '-p', 'MemoryMax=' + os.environ.get('PBR_MEM', '12G'), '-p', 'MemorySwapMax=0'] + cmd
    env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='8')
    print(f'pbr_check: {os.path.basename(blend)} is a .blend: running it inside Blender ({b})', flush=True)
    p = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    skip = ('EGL', 'libEGL', 'Blender quit', 'Blender 5', 'Read blend', 'Running scope', 'Info: Saved', 'Info: Baking', 'Fra:')
    out = [ln for ln in p.stdout.splitlines() if ln.strip() and not ln.startswith(skip) and '| Read blend' not in ln]
    print('\n'.join(out), flush=True)
    return p.returncode


if __name__ == '__main__':
    code = main()
    if 'bpy' in sys.modules:
        sys.stdout.flush()
        os._exit(code)          # leave Blender with the result code (sys.exit inside --python keeps Blender running)
    sys.exit(code)
