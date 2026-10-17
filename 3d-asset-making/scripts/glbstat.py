#!/usr/bin/env python3
"""glbstat.py: one line per GLB with what a budget is measured in. No Blender, no dependencies.

    python3 glbstat.py FILE.glb [FILE.glb ...] [--json]

Prints: triangles, draws (primitives; instanced nodes count once per instance), materials (names), textures
(count and pixel sizes), extents in metres (glTF axes x, y=up, z; node transforms applied) and file size; when any
material has an occlusionTexture (bake.py `ao`), how many, and how many share the metallic-roughness texture (ORM:
one fetch for occlusion R, roughness G, metal B).
Use it to read a released version's budget before building a new one, and to report a version against its budget.
"""
import json, struct, sys, os

def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]

def node_matrix(n):
    if 'matrix' in n:
        m = n['matrix']; return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
    t = n.get('translation', [0, 0, 0]); r = n.get('rotation', [0, 0, 0, 1]); s = n.get('scale', [1, 1, 1])
    x, y, z, w = r
    R = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    return [[R[i][0] * s[0], R[i][1] * s[1], R[i][2] * s[2], t[i]] for i in range(3)] + [[0, 0, 0, 1]]

def png_jpg_size(b):
    if b[:8] == b'\x89PNG\r\n\x1a\n': return struct.unpack('>II', b[16:24])
    if b[:2] == b'\xff\xd8':
        i = 2
        while i < len(b) - 9:
            if b[i] != 0xFF: i += 1; continue
            m = b[i + 1]
            if m in (0xC0, 0xC1, 0xC2): h, w = struct.unpack('>HH', b[i + 5:i + 9]); return (w, h)
            i += 2 + struct.unpack('>H', b[i + 2:i + 4])[0]
    if b[:4] == b'RIFF' and b[8:12] == b'WEBP': return ('webp', '?')
    return ('?', '?')

def stat(path):
    raw = open(path, 'rb').read()
    n = struct.unpack('<I', raw[12:16])[0]; j = json.loads(raw[20:20 + n])
    binoff = 20 + n + 8
    acc, views = j.get('accessors', []), j.get('bufferViews', [])
    tris = draws = 0; lo = [1e18] * 3; hi = [-1e18] * 3
    def walk(i, M):
        nonlocal tris, draws
        nd = j['nodes'][i]; M = mat_mul(M, node_matrix(nd))
        if 'mesh' in nd:
            for p in j['meshes'][nd['mesh']]['primitives']:
                draws += 1
                mode = p.get('mode', 4)
                cnt = acc[p['indices']]['count'] if 'indices' in p else acc[p['attributes']['POSITION']]['count']
                if mode == 4: tris += cnt // 3
                a = acc[p['attributes']['POSITION']]
                for cx in (a['min'][0], a['max'][0]):
                    for cy in (a['min'][1], a['max'][1]):
                        for cz in (a['min'][2], a['max'][2]):
                            for k in range(3):
                                v = M[k][0] * cx + M[k][1] * cy + M[k][2] * cz + M[k][3]
                                lo[k] = min(lo[k], v); hi[k] = max(hi[k], v)
        for c in nd.get('children', []): walk(c, M)
    I = [[1 if r == c else 0 for c in range(4)] for r in range(4)]
    for s in j.get('scenes', [{'nodes': list(range(len(j.get('nodes', []))))}])[:1]:
        for i in s['nodes']: walk(i, I)
    tex = []
    for im in j.get('images', []):
        if 'bufferView' in im:
            bv = views[im['bufferView']]; b = raw[binoff + bv.get('byteOffset', 0): binoff + bv.get('byteOffset', 0) + 32768]
            tex.append('%sx%s' % png_jpg_size(b) + ('/' + im.get('mimeType', '?').split('/')[-1]))
        else:
            tex.append('uri')
    ext = [round(hi[k] - lo[k], 2) if hi[k] > lo[k] else 0 for k in range(3)]
    mats = j.get('materials', [])
    occ = [m for m in mats if (m.get('occlusionTexture') or {}).get('index') is not None]
    orm = [m for m in occ if m['occlusionTexture']['index'] == ((m.get('pbrMetallicRoughness') or {}).get('metallicRoughnessTexture') or {}).get('index')]
    return {'occlusion': {'materials': len(occ), 'orm': len(orm)}, 'file': path, 'tris': tris, 'draws': draws, 'materials': [m.get('name', '?') for m in j.get('materials', [])],
            'textures': tex, 'extent_m_xyz': ext, 'mb': round(len(raw) / 1e6, 2)}

if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args or '-h' in sys.argv or '--help' in sys.argv: print(__doc__); sys.exit(0)
    out = [stat(a) for a in args]
    if '--json' in sys.argv: print(json.dumps(out, indent=1)); sys.exit(0)
    for s in out:
        print(f"{os.path.basename(s['file'])}: {s['tris']:,} tris, {s['draws']} draws, extent {s['extent_m_xyz']} m, "
              f"{s['mb']} MB; {len(s['materials'])} materials {s['materials'][:8]}; textures {s['textures'][:8]}" +
              (f"; occlusion on {s['occlusion']['materials']} materials ({s['occlusion']['orm']} ORM = in the MR texture)"
               if s['occlusion']['materials'] else ''))
