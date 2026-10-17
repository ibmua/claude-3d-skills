"""mesh_look.py: how the EDGES and SHAPES of a model are built, measured on the mesh as it renders. 1-3 s.

  python3 mesh_look.py FILE.blend|FILE.glb --out OUT.json [--collection NAME] [--hide REGEX] [--body REGEX]
                                           [--bevel MM] [--top 15]
  (the same under Blender: blender -b --factory-startup -noaudio -t 8 [FILE.blend] --python mesh_look.py -- ARGS)

It walks every rendered mesh instance (modifiers applied, linked components included, world scale) and never saves.
ADVISORY: a number outside its band means "look", never "fail"; the bands rest on 2 of our assets and 7 CC0 references.

What each number means (JSON key: provisional band):
  corners_share        every edge where the surface turns >= 30 deg is a corner; each is put in one class, weighted by
                       length x turn angle (one 90 deg razor counts like the two 45 deg edges of a chamfer):
    razor   : <= 0.02    normals split and both faces >= 20 mm wide: a mathematically sharp corner, it can never
                         catch a highlight. The "computer made" edge. train car 0.21, a train car 0.08, references 0.
    facet   : <= 0.02    normals split, one face a strip < 20 mm: a bevel that is there but shades flat, or whose
                         boundary against the face is a hard edge (also counted from a 12 deg turn). Two causes:
                         flat shading, and Bevel with Harden Normals followed by WeightedNormal with Keep Sharp.
    rounded              normals shared and a narrow strip beside it: a bevel that shades as a round edge. Wanted.
    blobby               normals shared across >= 60 deg between two wide faces: smooth shading with no bevel.
    curved               normals shared, 30-60 deg, wide faces: a coarse curved surface (few-sided cylinder).
  flat_shaded_area_share : <= 0.05   area with flat shading; Harden Normals and WeightedNormal do nothing there.
                         train car 0.74 (the cause of its facets), a train car 0.17, references 0.
  body_bevel.bevel_mm  : >= 1.5 px at the nearest camera (game set: 7.6 mm at 7.5 m; look.py takes the camera set)
                         width of the whole bevel (all its segments, walked across the narrow quads) on the part
                         with the largest single instance by area, the shell (--body REGEX names another);
                         body_bevel.strip_mm is one segment, the number the research reported (3.3 and 3.1 mm).
                         On a triangulated file (GLB) the walk stops at one segment.
  bevel_width_mm_share   whole-bevel widths in mm (histogram by corner length x turn); strip_width_mm_share the
                         same per segment; strip_width_vs_part_share per segment against the part's middle
                         dimension; strip_width_median_mm the weighted median segment.
  razor_by_part / facet_by_part / flat_by_part    where: the parts carrying the most of each.
  patches                faces joined across edges < 12 deg are one surface patch; areas by decade say whether
                         there are big, medium and small shapes or one size repeated. No band.
  repetition             share of triangles in the most repeated meshes (misplaced budget). No band.

--bevel MM adds in memory a Bevel (30 deg, MM wide, 2 segments, Harden Normals) + smooth shading to every mesh
without a Bevel modifier: the same numbers "as if bevelled". (No WeightedNormal after it: with Keep Sharp it splits
the normals on the edges Harden Normals marks sharp, and the bevel's boundary turns hard.)
"""
import sys, os, json, re, math, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _run  # noqa: E402
try:
    import bpy
except ImportError:
    bpy = None

HIDE_DEFAULT = r'^(STAGE|REVIEW|CMP_|LOD_|EXPORT_|BAKE|HELPER|GUIDE|WIDGET|_)|(^|[_.\- ])stage([_.\- ]|$)'


def auto_only():
    """No --collection given: what IS the asset in this file? (only names or None, how, left out)
    1. objects kit3d tagged (o['kit3d_part']): a step file from a bridge holds the asset plus whatever the session
       started with (Blender's own Cube);
    2. else everything outside the stage / review / LOD collections, minus Blender's untouched default Cube.
    The second pilot measured a presentation deck (92 % of the picture) and the default Cube without knowing."""
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    tagged = [o.name for o in meshes if 'kit3d_part' in o]
    if tagged:
        return set(tagged), 'the %d kit3d-tagged objects' % len(tagged), sorted(o.name for o in meshes if 'kit3d_part' not in o)
    cube = [o.name for o in meshes if o.name == 'Cube' and len(o.data.vertices) == 8 and not o.data.materials[:1] == [None]
            and all(abs(d - 2.0) < 1e-6 for d in o.dimensions) and o.matrix_world.translation.length < 1e-6 and len(meshes) > 1]
    return (set(o.name for o in meshes) - set(cube)) if cube else None, 'the whole file', sorted(cube)


def hidden_collections(hide):
    rx = re.compile(hide, re.I) if hide else None
    bad = set()

    def walk(c, off):
        off = off or c.hide_render or bool(rx and rx.search(c.name))
        if off:
            bad.update(o.name for o in c.objects)
        for ch in c.children:
            walk(ch, off)
    walk(bpy.context.scene.collection, False)
    return bad


def add_bevels(mm):
    n = 0
    for o in bpy.data.objects:
        if o.type != 'MESH' or any(m.type == 'BEVEL' for m in o.modifiers):
            continue
        b = o.modifiers.new('LOOK_bevel', 'BEVEL')
        b.width = mm / 1000.0; b.segments = 2; b.limit_method = 'ANGLE'; b.angle_limit = math.radians(30)
        b.harden_normals = True; b.miter_outer = 'MITER_ARC'; b.use_clamp_overlap = True   # no WeightedNormal: see LOOK-TOOLS.md
        for p in o.data.polygons:
            p.use_smooth = True
        n += 1
    return n


def arrays(me, M):
    """Evaluated mesh + 4x4 world matrix -> the world-space arrays mesh_core.edges takes (None for an empty mesh)."""
    import numpy as np
    nv, nl, npoly = len(me.vertices), len(me.loops), len(me.polygons)
    if npoly == 0:
        return None
    co = np.empty(nv * 3, np.float64); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
    M = np.array(M); co = co @ M[:3, :3].T + M[:3, 3]
    lv = np.empty(nl, np.int64); me.loops.foreach_get('vertex_index', lv)
    le = np.empty(nl, np.int64); me.loops.foreach_get('edge_index', le)
    ls = np.empty(npoly, np.int64); me.polygons.foreach_get('loop_start', ls)
    lt = np.empty(npoly, np.int64); me.polygons.foreach_get('loop_total', lt)
    cn = np.empty(nl * 3, np.float64); me.corner_normals.foreach_get('vector', cn); cn = cn.reshape(-1, 3)
    cn = cn @ np.linalg.inv(M[:3, :3]); cn /= np.maximum(np.linalg.norm(cn, axis=1, keepdims=True), 1e-12)
    sm = np.empty(npoly, bool); me.polygons.foreach_get('use_smooth', sm)
    return co, lv, le, ls, lt, cn, sm


def measure(collection=None, hide=HIDE_DEFAULT, body=None, top=15, only_objects=None):
    """Measure the open scene. only_objects: a set of object names (tests); collection: a collection name."""
    import mesh_core
    bad = hidden_collections(hide)
    only = set(only_objects) if only_objects is not None else None
    how, left = 'the objects given', []
    if collection:
        if collection not in bpy.data.collections:
            raise SystemExit('MESH_LOOK ERROR no collection %r in this file (it has: %s)' % (collection, ', '.join(sorted(c.name for c in bpy.data.collections)[:12])))
        only = set(o.name for o in bpy.data.collections[collection].all_objects); how = 'collection ' + collection
    elif only is None:
        only, how, left = auto_only()
        left = sorted(set(left) | set(n for n in bad if bpy.data.objects.get(n) is not None and bpy.data.objects[n].type == 'MESH'))
    seen = set()
    T = mesh_core.Tally()
    for di in bpy.context.evaluated_depsgraph_get().object_instances:
        ob = di.object
        if ob.type != 'MESH':
            continue
        topo = di.parent.original if di.is_instance and di.parent else ob.original
        if topo.name in bad or ob.original.name in bad or topo.hide_render:
            continue
        if only is not None and topo.name not in only:
            continue
        a = arrays(ob.data, di.matrix_world)
        if a is None:
            continue
        seen.add(topo.name)
        T.add(topo.name if di.is_instance else ob.original.name, ob.original.data.name, mesh_core.edges(*a))
    res = T.result(top=top, body=body)
    res['measured'] = dict(how=how, objects=len(seen), left_out=left[:40], left_out_count=len(left),
                           collections=sorted({c.name for n in seen for c in bpy.data.objects[n].users_collection})[:8])
    return res


def main(argv):
    t0 = time.time()
    src = next((a for a in argv[:1] if not a.startswith('--')), None) or _run.arg(argv, '--glb')
    out = _run.arg(argv, '--out'); bevel = float(_run.arg(argv, '--bevel', 0))
    if src and src.lower().endswith(('.glb', '.gltf')):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=os.path.abspath(src))
    elif src and os.path.abspath(src) != bpy.data.filepath:
        bpy.ops.wm.open_mainfile(filepath=os.path.abspath(src))
    nb = add_bevels(bevel) if bevel else 0
    res = dict(file=os.path.abspath(src) if src else bpy.data.filepath, bevel_added_mm=bevel, bevel_added_to=nb)
    res.update(measure(_run.arg(argv, '--collection'), _run.arg(argv, '--hide', HIDE_DEFAULT), _run.arg(argv, '--body'),
                       int(_run.arg(argv, '--top', 15))))
    res['seconds'] = round(time.time() - t0, 1)
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)) or '.', exist_ok=True)
        with open(out, 'w') as f:
            f.write(json.dumps(res, indent=1) + '\n')
    c = res['corners_share']; b = res['body_bevel'] or {}
    print('MESH_LOOK razor %.0f%% facet %.0f%% rounded %.0f%% blobby %.0f%% curved %.0f%% | flat-shaded %.0f%% | body bevel %s mm (%s) | %d tris, %d instances, %.0fs -> %s'
          % (100 * c['razor'], 100 * c['facet'], 100 * c['rounded'], 100 * c['blobby'], 100 * c['curved'],
             100 * res['flat_shaded_area_share'], b.get('bevel_mm'), b.get('part'), res['triangles'], res['instances'],
             time.time() - t0, out), flush=True)


if __name__ == '__main__':
    argv = _run.tool_argv()
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__); sys.exit(0)
    if bpy is None:                                         # plain python3: the same arguments, inside Blender
        rc, keep = _run.blender('mesh_look.py', argv)
        print('\n'.join(keep)); sys.exit(rc)
    try:
        main(argv)
    except Exception:
        import traceback
        traceback.print_exc(); sys.exit(2)
