#!/usr/bin/env python3
"""matref.py: measured material values from the vendored Physically Based table (CC0), with the source to put on the
material, so no metallic or colour number is invented.

  python3 matref.py stainless            best match: linear base colour, Y, metallic, IOR / F82, ready lines
  python3 matref.py steel --all          every candidate
  python3 matref.py tyre --json          the lookup dict as JSON
  python3 matref.py --list [Metal]       every name (optionally one category)

Python:
  from matref import lookup, search
  r = lookup('Stainless Steel')   # -> dict or None
  r['color_linear'], r['metallic'], r['Y'], r['f82'], r['ior'], r['props'] ({'ref', 'source'} for custom properties)

Data: scripts/data/physicallybased-v2.json = https://api.physicallybased.info/v2/materials (CC0 1.0, fetched
2026-10-13, header updated 2026-10-11). Roughness there is the polished reference (mostly 0): roughness stays a
judged value ("judged: brushed"). For glass, liquids and clear plastics `color` is the TRANSMISSION tint, not an
albedo (r['color_is'] says which).
"""
import difflib, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data', 'physicallybased-v2.json')
SOURCE = 'physicallybased.info'
LUM = (0.2126, 0.7152, 0.0722)
# our words -> table names (notes say what the alias assumes)
ALIASES = {
    'alu': ('Aluminum', None), 'aluminium': ('Aluminum', None), 'aluminum': ('Aluminum', None),
    'stainless': ('Stainless Steel', None), 'inox': ('Stainless Steel', None), 'stl': ('Stainless Steel', None),
    'stainless steel': ('Stainless Steel', None),
    'steel': ('Iron', 'carbon / mild steel: F0 of iron (the table has no carbon steel)'),
    'mild steel': ('Iron', 'carbon / mild steel: F0 of iron'), 'carbon steel': ('Iron', 'F0 of iron'),
    'chrome': ('Chromium', 'chrome plating = chromium'), 'chromium': ('Chromium', None),
    'tyre': ('Tire', None), 'tire': ('Tire', None), 'rubber': ('Tire', 'black rubber: the tyre value'),
    'asphalt': ('Asphalt (Fresh)', None), 'glass': ('Glass (Soda-lime)', 'window glass'),
    'window glass': ('Glass (Soda-lime)', None), 'paper': ('Office Paper', None), 'acrylic': ('Plastic (Acrylic)', None),
    'perspex': ('Plastic (Acrylic)', None), 'plexiglass': ('Plastic (Acrylic)', None),
    'polycarbonate': ('Plastic (PC)', None), 'pvc': ('Plastic (PVC)', None), 'bronze': ('Copper', 'no bronze in the table: copper is closest (bronze is less red)'),
    'cast iron': ('Cast Iron', None), 'iron': ('Iron', None), 'gold': ('Gold', None), 'silver': ('Silver', None),
    'copper': ('Copper', None), 'brass': ('Brass', None), 'zinc': ('Zinc', None), 'galvanised': ('Zinc', 'galvanised steel: zinc'),
    'galvanized': ('Zinc', 'galvanized steel: zinc'), 'nickel': ('Nickel', None), 'titanium': ('Titanium', None),
    'car paint': ('Car Paint', 'a clear-coated paint (the colour is a mid grey placeholder: take the livery colour)'),
    'lacquer': ('Plastic (PUR)', 'clear lacquer / coat'), 'clear coat': ('Plastic (PUR)', 'clear lacquer / coat'),
}
_DB = None


def _db():
    global _DB
    if _DB is None:
        with open(DATA) as f: d = json.load(f)
        _DB = {'meta': {**d.get('header', {}), **d.get('_vendored', {})}, 'data': d['data']}
    return _DB


def _lin(colors, space='srgb-linear'):
    for c in colors or []:
        if c.get('colorSpace') == space: return [float(x) for x in c['color']]
    return None


def _norm(s): return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()


def _srgb8(c):
    out = []
    for x in c:
        x = min(max(x, 0.0), 1.0)
        out.append(round(255 * (12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055)))
    return out


def describe(m, note=None):
    """The table entry as the dict tools use."""
    col = _lin(m.get('color')) or [0.5, 0.5, 0.5]
    Y = sum(a * b for a, b in zip(col, LUM))
    f82 = spec = None
    for s in m.get('specularColor') or []:
        fmt = (s.get('format') or [''])[0]
        if fmt == 'F82': f82 = _lin(s.get('color'))
        elif fmt == 'Gulbrandsen': spec = _lin(s.get('color'))
    ior = m.get('ior'); ior = ior[0] if isinstance(ior, list) and ior else ior
    metal = float(m.get('metalness', 0) or 0); trans = m.get('transmission')
    cat = (m.get('category') or ['?'])[0]
    color_is = 'F0 (specular reflectance at normal incidence)' if metal >= 0.5 else \
        'transmission tint (not an albedo)' if trans else 'albedo (diffuse base colour)'
    cls = 'bare_metal' if metal >= 0.5 else 'glass' if trans and cat in ('Crystal', 'Plastic') else \
        'rubber' if m['name'] == 'Tire' else 'plastic' if cat == 'Plastic' else 'stone' if m['name'] in (
            'Concrete', 'Brick', 'Asphalt (Fresh)', 'Clay', 'Terracotta') else 'dielectric'
    meta = _db()['meta']; upd = str(meta.get('updated', ''))
    src_detail = f'physicallybased.info v2 (CC0), updated {upd[:4]}-{upd[4:6]}-{upd[6:8]}' if len(upd) >= 8 else 'physicallybased.info v2 (CC0)'
    return {
        'name': m['name'], 'category': cat, 'tags': m.get('tags') or [], 'color_linear': [round(x, 4) for x in col],
        'srgb8': _srgb8(col), 'Y': round(Y, 4), 'metallic': metal, 'roughness': m.get('roughness'),
        'roughness_note': 'polished reference sample: judge the real roughness' if not m.get('roughness') else 'typical sample value: judge yours',
        'ior': ior, 'f82': f82,
        'specular_color': spec, 'transmission': trans, 'color_is': color_is, 'class': cls,
        'description': (m.get('description') or '').strip(), 'note': note,
        'references': [r.get('url') or r.get('doi') for r in (m.get('references') or []) if r.get('url') or r.get('doi')],
        'source': SOURCE, 'source_detail': src_detail, 'url': meta.get('source') or meta.get('origin'),
        'props': {'ref': m['name'], 'source': SOURCE},
    }


def search(query, n=5):
    """Ranked candidates [(score, dict)] for a free-text query (name, alias, tag)."""
    q = _norm(query); data = _db()['data']; out = {}
    if not q: return []
    def add(m, score, note=None):
        if m['name'] not in out or out[m['name']][0] < score: out[m['name']] = (score, m, note)
    by = {m['name']: m for m in data}
    if q in ALIASES:
        name, note = ALIASES[q]; add(by[name], 99, note)
    for m in data:
        nm = _norm(m['name']); tags = [_norm(t) for t in (m.get('tags') or [])]
        if nm == q: add(m, 100)
        elif nm.startswith(q): add(m, 85)
        elif all(t in nm.split() for t in q.split()): add(m, 75)
        elif q in tags: add(m, 70)
        elif q in nm: add(m, 60)
        elif any(q in t for t in tags): add(m, 50)
    for k, (name, note) in ALIASES.items():
        if k != q and (q in k.split() or k in q): add(by[name], 65, note)
    if not out:
        for nm in difflib.get_close_matches(q, [_norm(m['name']) for m in data], n=n, cutoff=0.5):
            m = next(x for x in data if _norm(x['name']) == nm); add(m, 40)
    ranked = sorted(out.values(), key=lambda x: (-x[0], x[1]['name']))[:n]
    return [(s, describe(m, note)) for s, m, note in ranked]


def lookup(name):
    """The best match for a name or alias ('stainless', 'Stainless Steel', 'alu', 'tyre', 'physicallybased:Aluminum')
    as a dict, or None. pbr_check.py (M4, declared metals, material refs) calls this."""
    name = re.sub(r'^\s*physicallybased(\.info)?\s*:\s*', '', str(name or ''), flags=re.I)
    r = search(name, 1)
    return r[0][1] if r else None


def kit3d_lookup(ref):
    """The hook kit3d.set_ref_lookup() takes: ref ('physicallybased:Stainless Steel', 'stainless', ...) -> the values
    kit3d may fill when the caller left them out: {'base': (r, g, b) linear, 'metallic': m, 'ior': x (dielectrics),
    'transmission': 1.0 (glass, clear plastics)}, or None. Roughness is never filled: the table's is a polished sample."""
    r = lookup(ref)
    if not r: return None
    out = {'base': tuple(r['color_linear']), 'metallic': float(r['metallic'])}
    if r['metallic'] < 0.5 and r.get('ior'): out['ior'] = float(r['ior'])
    if r.get('transmission') and r['class'] == 'glass': out['transmission'] = 1.0
    return out


def ready_lines(r, mat='mat'):
    """Text lines to paste: Blender custom properties, asset.json "materials" entry, kit3d call."""
    c = ', '.join(f'{x:.3f}' for x in r['color_linear'])
    entry = {'class': r['class'], 'ref': r['name'], 'source': r['source']}
    if r['class'] == 'bare_metal': entry['metal'] = r['name']
    return [
        f'Blender:   {mat}["ref"] = "{r["name"]}"; {mat}["source"] = "{r["source"]}"   '
        f'# Base Color ({c}, 1), Metallic {r["metallic"]:g}' + (f', IOR {r["ior"]}' if r['ior'] and r['metallic'] < 0.5 else ''),
        f'asset.json "materials": "<material name>": {json.dumps(entry)}',
        f'kit3d:     material("<name>", ref="physicallybased:{r["name"]}", rough=<value>, src={{"rough": "judged: <why>"}})',
    ]


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    if not a or a[0] in ('-h', '--help'):
        print(__doc__); return 0
    if a[0] == '--list':
        cat = a[1] if len(a) > 1 else None
        for m in _db()['data']:
            d = describe(m)
            if cat and d['category'].lower() != cat.lower(): continue
            print(f"{d['category']:10s} {d['name']:28s} met={d['metallic']:g} Y={d['Y']:.3f} lin=({', '.join(f'{x:.3f}' for x in d['color_linear'])})")
        return 0
    js = '--json' in a; allc = '--all' in a; q = ' '.join(x for x in a if not x.startswith('--'))
    res = search(q, 8 if allc else 1)
    if not res:
        print(f'no match for {q!r} (python3 matref.py --list)'); return 1
    if js:
        print(json.dumps([r for _, r in res] if allc else res[0][1], indent=1)); return 0
    meta = _db()['meta']
    for score, r in res:
        print(f"{r['name']}  [{r['category']}; match {score}]" + (f"  ({r['note']})" if r['note'] else ''))
        print(f"  base colour linear ({', '.join(f'{x:.3f}' for x in r['color_linear'])}) = sRGB {tuple(r['srgb8'])}, "
              f"Y {r['Y']:.3f}: {r['color_is']}")
        print(f"  metallic {r['metallic']:g}" + (f", IOR {r['ior']}" if r['ior'] else '') +
              (f", F82 ({', '.join(f'{x:.3f}' for x in r['f82'])})" if r['f82'] else '') +
              f", roughness {r['roughness']} ({r['roughness_note']})")
        if r['transmission']: print('  transmissive: in a game file use alphaMode BLEND (or KHR_materials_transmission); base colour = tint')
        if not allc:
            for line in ready_lines(r): print('  ' + line)
            if r['references']: print('  references: ' + ' | '.join(r['references'][:3]))
    print(f"source: {meta.get('source')} ({meta.get('license', 'CC0')}, fetched {meta.get('fetched', '?')})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
