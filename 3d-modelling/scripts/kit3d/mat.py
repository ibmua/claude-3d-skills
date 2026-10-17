"""kit3d materials: one Principled material builder plus layered presets, every value with its SOURCE (F6).

  m = kit3d.material('stl.alu', base='#d8d5cb', metallic=1.0, rough=0.35,
                     ref='physicallybased:Aluminum', src={'rough': 'judged: brushed, aged'})
Measured values come from the reference: with ref='physicallybased:<name>' the values you leave out (base colour,
metallic, IOR, transmission for glass) are FILLED from the vendored Physically Based table (3d-asset-making/scripts/
matref.py, loaded automatically; roughness is never filled: the table's is a polished sample, judge it and say so).
Sources per value: src[key] (or src='...' for all you passed) > 'ref:<ref>' (filled from, or equal to, the reference)
> 'inferred' (a number you typed without a source: plan_check / pbr_check S1 count it). Stored on the material as
custom properties kit3d_ref, kit3d_values, kit3d_src (JSON); kit3d.sources() lists them, kit3d.inferred() the
inferred ones. set_ref_lookup(fn) swaps the database (fn(ref) -> {'base': linear rgb, 'metallic', 'ior', ...} or
None); set_ref_lookup(None) turns filling off.
Images are read through the UV map (metre UVs, Mapping scale 1/tile_m), never Object/Box projection: glTF has no such
node, and a texture without UVs exports as speckle (F4).
"""
import importlib.util, json, math, os
import bpy

from . import core

KEYS = ('base', 'metallic', 'rough', 'coat', 'coat_rough', 'transmission', 'ior', 'alpha', 'emission', 'emission_k',
        'emission_strength', 'image', 'tile_m', 'bump')


def set_ref_lookup(fn):
    core.S()['ref_lookup'] = fn or False


def _default_lookup():
    """matref.kit3d_lookup from the sibling skill (loaded by path once per Blender), or False when it is absent."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        p = os.path.normpath(os.path.join(here, '..', '..', '..', '3d-asset-making', 'scripts', 'matref.py'))
        spec = importlib.util.spec_from_file_location('matref_for_kit3d', p)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        return m.kit3d_lookup
    except Exception as e:
        print(f'kit3d: matref not loaded ({e!r}); ref= values are not filled')
        return False


def _lookup(ref):
    st = core.S()
    if 'ref_lookup' not in st: st['ref_lookup'] = _default_lookup()
    fn = st['ref_lookup']
    if not fn or not ref: return {}
    try:
        return fn(ref) or {}
    except Exception as e:
        print(f'kit3d: ref lookup {ref!r} failed: {e!r}')
        return {}


def hexc(h, a=1.0):
    """'#rrggbb' (sRGB) -> linear RGBA."""
    h = h.lstrip('#'); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple((x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4) for x in c) + (a,)


def col(c, a=1.0):
    if isinstance(c, str): return hexc(c, a)
    c = tuple(float(x) for x in c)
    return c if len(c) == 4 else c + (a,)


def kelvin(k):
    """Linear RGB of a black body at k kelvin (Tanner Helland fit, normalised so the max channel is 1)."""
    t = k / 100.0
    r = 255.0 if t <= 66 else 329.698727446 * ((t - 60) ** -0.1332047592)
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * ((t - 60) ** -0.0755148492)
    b = 255.0 if t >= 66 else (0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307)
    s = [min(255.0, max(0.0, x)) / 255.0 for x in (r, g, b)]
    lin = [(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4) for x in s]
    m = max(lin) or 1.0
    return tuple(x / m for x in lin) + (1.0,)


def _fresh(name):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial'); out.location = (900, 0)
    bs = nt.nodes.new('ShaderNodeBsdfPrincipled'); bs.location = (600, 0)
    nt.links.new(bs.outputs[0], out.inputs[0])
    return m, nt, bs, out


def _mix(nt, fac, a, b, blend='MIX'):
    """RGBA Mix node (data_type set BEFORE linking: a link made earlier stays on the hidden float socket)."""
    m = nt.nodes.new('ShaderNodeMix'); m.data_type = 'RGBA'; m.blend_type = blend
    if isinstance(fac, (int, float)): m.inputs[0].default_value = fac
    else: nt.links.new(fac, m.inputs[0])
    for sock, v in ((m.inputs[6], a), (m.inputs[7], b)):
        if isinstance(v, tuple): sock.default_value = v
        else: nt.links.new(v, sock)
    return m.outputs[2]


def _math(nt, op, a, b=None, clamp=False):
    m = nt.nodes.new('ShaderNodeMath'); m.operation = op; m.use_clamp = clamp
    for s, v in ((m.inputs[0], a), (m.inputs[1], b)):
        if v is None: continue
        if isinstance(v, (int, float)): s.default_value = v
        else: nt.links.new(v, s)
    return m.outputs[0]


def _noise(nt, vec, scale, detail=4.0, rough=0.55):
    n = nt.nodes.new('ShaderNodeTexNoise'); n.inputs['Scale'].default_value = scale
    n.inputs['Detail'].default_value = detail; n.inputs['Roughness'].default_value = rough
    nt.links.new(vec, n.inputs['Vector']); return n


def _uv_image(nt, path, tile_m, noncolor=False):
    """Image tile read through the UV map: UV metres * (1/tile_m)."""
    im = bpy.data.images.load(path, check_existing=True)
    if noncolor: im.colorspace_settings.name = 'Non-Color'
    tc = nt.nodes.new('ShaderNodeTexCoord'); mp = nt.nodes.new('ShaderNodeMapping')
    mp.inputs['Scale'].default_value = (1.0 / tile_m,) * 3
    nt.links.new(tc.outputs['UV'], mp.inputs['Vector'])
    t = nt.nodes.new('ShaderNodeTexImage'); t.image = im; t.interpolation = 'Linear'
    nt.links.new(mp.outputs['Vector'], t.inputs['Vector'])
    return t


def _record(m, given, ref, src):
    """Write values + their sources onto the material."""
    s = src if isinstance(src, dict) else ({k: src for k in given} if isinstance(src, str) else {})
    vals, srcs = {}, {}
    for k, v in given.items():
        if v is None: continue
        vals[k] = list(v) if isinstance(v, tuple) else v
        srcs[k] = s.get(k) or 'inferred'
    m['kit3d_ref'] = ref or ''
    m['kit3d_values'] = json.dumps(vals, default=str)
    m['kit3d_src'] = json.dumps(srcs)
    return m


def _same(a, b):
    try:
        if isinstance(a, str): a = hexc(a)
        a = [float(x) for x in (a if hasattr(a, '__len__') else [a])][:3]; b = [float(x) for x in (b if hasattr(b, '__len__') else [b])][:3]
        return len(a) == len(b) and all(abs(x - y) <= 0.02 + 0.05 * abs(y) for x, y in zip(a, b))
    except (TypeError, ValueError):
        return False


def material(name, base=None, metallic=None, rough=None, *, ref=None, src=None, coat=None, coat_rough=None,
             transmission=None, ior=None, alpha=None, emission=None, emission_k=None, emission_strength=None,
             image=None, tile_m=1.0, tint=1.0, rough_var=0.0, bump=0.0, noise_bump=0.0, dirt=0.0, low_z=None):
    """Principled material. base: '#hex' sRGB or linear RGB(A). image: a tile (path) multiplied onto base by `tint`
    (its luminance; keeps the palette), read through UVs in metres; rough_var: roughness follows the image/noise by
    +-rough_var; bump: height from the image (m); noise_bump: fine procedural bump (m); dirt 0..1: grime rising from
    low_z=(z0, z1) world metres (and in AO crevices). emission_k: emission colour from kelvin (2700 = warm lamp).
    Values not passed are Blender defaults and are not recorded."""
    look = _lookup(ref)
    given = {'base': base, 'metallic': metallic, 'rough': rough, 'coat': coat, 'coat_rough': coat_rough,
             'transmission': transmission, 'ior': ior, 'alpha': alpha, 'emission': emission, 'emission_k': emission_k,
             'emission_strength': emission_strength}
    sf = dict(src) if isinstance(src, dict) else ({} if src is None else {k: src for k, v in given.items() if v is not None})
    for k, v in look.items():                       # measured values fill what was left out, and source what agrees
        if k not in given: continue
        if given[k] is None: given[k] = v; sf[k] = f'ref:{ref}'
        elif k not in sf and _same(given[k], v): sf[k] = f'ref:{ref}'
    m, nt, bs, out = _fresh(name)
    bc = col(given['base']) if given['base'] is not None else (0.8, 0.8, 0.8, 1.0)
    bs.inputs['Base Color'].default_value = bc; m.diffuse_color = bc
    r0 = 0.5 if given['rough'] is None else given['rough']
    if given['metallic'] is not None: bs.inputs['Metallic'].default_value = given['metallic']
    bs.inputs['Roughness'].default_value = r0
    if given['coat']: bs.inputs['Coat Weight'].default_value = given['coat']
    if given['coat_rough'] is not None: bs.inputs['Coat Roughness'].default_value = given['coat_rough']
    if given['transmission']: bs.inputs['Transmission Weight'].default_value = given['transmission']
    if given['ior'] is not None: bs.inputs['IOR'].default_value = given['ior']
    if given['alpha'] is not None and given['alpha'] < 1:
        bs.inputs['Alpha'].default_value = given['alpha']; m.surface_render_method = 'BLENDED'
    ec = kelvin(given['emission_k']) if given['emission_k'] else (col(given['emission']) if given['emission'] is not None else None)
    if ec is not None:
        bs.inputs['Emission Color'].default_value = ec
        bs.inputs['Emission Strength'].default_value = given['emission_strength'] or 1.0
    tc = nt.nodes.new('ShaderNodeTexCoord')
    color_sock = None; rough_src = None; height = None
    if image:
        t = _uv_image(nt, image, tile_m)
        bw = nt.nodes.new('ShaderNodeRGBToBW'); nt.links.new(t.outputs['Color'], bw.inputs[0])
        lum = _math(nt, 'MULTIPLY_ADD', bw.outputs[0], 1.6); lum.node.inputs[2].default_value = 0.2
        color_sock = _mix(nt, float(tint), bc, (1, 1, 1, 1), 'MULTIPLY')
        nt.links.new(lum, color_sock.node.inputs[7])
        rough_src = bw.outputs[0]; height = bw.outputs[0] if bump else None
        given['image'] = os.path.basename(image); given['tile_m'] = tile_m
    elif rough_var or noise_bump:
        nz = _noise(nt, tc.outputs['Object'], 40.0, 6.0, 0.6); rough_src = nz.outputs['Fac']
        height = nz.outputs['Fac'] if noise_bump else None
    if rough_src is not None and rough_var:
        mr = nt.nodes.new('ShaderNodeMapRange'); nt.links.new(rough_src, mr.inputs['Value'])
        mr.inputs['To Min'].default_value = max(0.0, r0 - rough_var); mr.inputs['To Max'].default_value = min(1.0, r0 + rough_var)
        nt.links.new(mr.outputs[0], bs.inputs['Roughness'])
    if dirt:
        base_in = color_sock if color_sock is not None else bc
        color_sock, dmask = _grime(nt, base_in, dirt, low_z)
        r_in = bs.inputs['Roughness'].links[0].from_socket if bs.inputs['Roughness'].links else r0
        nt.links.new(_math(nt, 'ADD', r_in, _math(nt, 'MULTIPLY', dmask, 0.3)), bs.inputs['Roughness'])
    if color_sock is not None: nt.links.new(color_sock, bs.inputs['Base Color'])
    if height is not None:
        bn = nt.nodes.new('ShaderNodeBump'); bn.inputs['Strength'].default_value = 1.0
        bn.inputs['Distance'].default_value = bump or noise_bump
        nt.links.new(height, bn.inputs['Height']); nt.links.new(bn.outputs[0], bs.inputs['Normal'])
    _record(m, {k: v for k, v in given.items() if v is not None and k in KEYS}, ref, sf)
    return m


def _grime(nt, base, amount, low_z=None, ao_dist=0.12):
    """Darken base with AO crevices + dirt rising from low_z (world z0 -> z1), broken up by noise. Returns
    (colour socket, dirt mask socket)."""
    geo = nt.nodes.new('ShaderNodeNewGeometry'); sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    nt.links.new(geo.outputs['Position'], sep.inputs[0])
    ao = nt.nodes.new('ShaderNodeAmbientOcclusion'); ao.inputs['Distance'].default_value = ao_dist; ao.samples = 8
    n = _noise(nt, geo.outputs['Position'], 6.0, 6.0, 0.6); n2 = _noise(nt, geo.outputs['Position'], 1.3, 3.0, 0.5)
    d = _math(nt, 'MULTIPLY', _math(nt, 'SUBTRACT', 1.0, ao.outputs['AO']), 1.6, True)
    if low_z is not None:
        mr = nt.nodes.new('ShaderNodeMapRange'); nt.links.new(sep.outputs['Z'], mr.inputs['Value'])
        mr.inputs['From Min'].default_value = low_z[0]; mr.inputs['From Max'].default_value = low_z[1]
        mr.inputs['To Min'].default_value = 1.0; mr.inputs['To Max'].default_value = 0.0
        d = _math(nt, 'MAXIMUM', d, _math(nt, 'MULTIPLY', _math(nt, 'MULTIPLY', mr.outputs[0], n2.outputs['Fac']), 1.2))
    d = _math(nt, 'MULTIPLY', _math(nt, 'MULTIPLY', d, n.outputs['Fac']), 1.2 * amount, True)
    c = _mix(nt, d, base, (0.55, 0.47, 0.40, 1.0), 'MULTIPLY')
    return c, d


def _preset_src(src, passed, fixed, label):
    """Sources for a preset: the caller's (dict, or one string for the values they passed), the class facts in
    `fixed`, and 'inferred: <label> preset' for preset defaults nobody sourced (counted as inferred)."""
    sf = dict(src) if isinstance(src, dict) else ({k: src for k in passed} if src else {})
    for k, v in fixed.items(): sf.setdefault(k, v)
    return sf, f'inferred: kit3d {label} preset'


def paint(name, base, rough=None, *, ref=None, src=None, coat=0.25, dirt=0.6, low_z=None, metallic=0.0):
    """Painted panel: soft roughness break-up, low-frequency mottling, AO + height grime, light clear coat.
    rough/coat default to 0.42/0.25 (sourced 'inferred: kit3d paint preset' unless you pass and source them)."""
    sf, dflt = _preset_src(src, ['base'] + (['rough'] if rough is not None else []), {'metallic': 'class: paint (dielectric)'}, 'paint')
    for k in ('rough', 'coat', 'coat_rough'): sf.setdefault(k, dflt)
    return material(name, base, metallic, 0.42 if rough is None else rough, ref=ref, src=sf, coat=coat, coat_rough=0.18,
                    rough_var=0.08, noise_bump=0.0004, dirt=dirt, low_z=low_z)


def metal(name, base=None, rough=None, *, ref=None, src=None, dirt=0.3, image=None, tile_m=0.35):
    """Bare metal (metallic 1): roughness break-up, light grime. Decide bare metal / metallic paint / paint first.
    With ref='physicallybased:<metal>' leave base out: the measured colour is filled. Judge rough and source it."""
    sf, dflt = _preset_src(src, (['base'] if base is not None else []) + (['rough'] if rough is not None else []),
                           {'metallic': 'class: bare metal'}, 'metal')
    sf.setdefault('rough', dflt)
    r = 0.25 if rough is None else rough
    return material(name, base, 1.0, r, ref=ref, src=sf, rough_var=r * 0.4, dirt=dirt, image=image,
                    tile_m=tile_m, tint=0.2)


def glass(name, tint=(0.82, 0.9, 0.92, 1.0), rough=0.03, *, ref='physicallybased:Glass', src=None):
    """Clear glass (transmission 1, IOR 1.5) that lets shadow rays through (lighter interiors in Cycles)."""
    sf, dflt = _preset_src(src, [], {'base': 'judged: float-glass tint (design)', 'metallic': 'class: glass'}, 'glass')
    sf.setdefault('rough', dflt)
    m = material(name, tint, 0.0, rough, ref=ref, src=sf, transmission=1.0, ior=1.5)
    nt = m.node_tree; bs = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'); out = next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL')
    lp = nt.nodes.new('ShaderNodeLightPath'); tr = nt.nodes.new('ShaderNodeBsdfTransparent'); tr.inputs[0].default_value = col(tint)
    mx = nt.nodes.new('ShaderNodeMixShader')
    nt.links.new(lp.outputs['Is Shadow Ray'], mx.inputs[0]); nt.links.new(bs.outputs[0], mx.inputs[1]); nt.links.new(tr.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], out.inputs[0])
    m.diffuse_color = (col(tint)[0], col(tint)[1], col(tint)[2], 0.3)
    return m


def lamp(name, kelvin_k=2700, strength=6.0, base=(0.95, 0.93, 0.85), *, src=None):
    """A lens / bulb that glows at night: emission colour from kelvin, transmissive."""
    return material(name, base, 0.0, 0.05, src=src or {'emission_k': 'design: night state'}, transmission=0.8,
                    emission_k=kelvin_k, emission_strength=strength)


def decal_mat(name, image, rough=0.3, *, src=None):
    """Alpha decal: image colour + alpha through UV 0..1 (CLIP), dithered."""
    m, nt, bs, out = _fresh(name)
    t = nt.nodes.new('ShaderNodeTexImage'); t.image = bpy.data.images.load(image, check_existing=True); t.extension = 'CLIP'
    tc = nt.nodes.new('ShaderNodeTexCoord'); nt.links.new(tc.outputs['UV'], t.inputs['Vector'])
    nt.links.new(t.outputs['Color'], bs.inputs['Base Color']); nt.links.new(t.outputs['Alpha'], bs.inputs['Alpha'])
    bs.inputs['Roughness'].default_value = rough; m.surface_render_method = 'DITHERED'; m.diffuse_color = (0.8, 0.6, 0.2, 1)
    return _record(m, {'image': os.path.basename(image), 'rough': rough}, None, src or {'image': 'made: decal art'})


def sources(mats=None):
    """[(material, key, value, source)] for every recorded material value (materials made by kit3d)."""
    rows = []
    for m in (mats or bpy.data.materials):
        if 'kit3d_src' not in m: continue
        v = json.loads(m.get('kit3d_values', '{}')); s = json.loads(m['kit3d_src'])
        for k in sorted(s): rows.append((m.name, k, v.get(k), s[k]))
    return rows


def inferred(mats=None):
    """Material values with no source (to fix, or to list in the hand-back)."""
    return [r for r in sources(mats) if str(r[3]).startswith('inferred')]
