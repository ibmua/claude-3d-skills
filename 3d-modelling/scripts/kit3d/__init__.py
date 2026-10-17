"""kit3d: the shared modelling library for Blender 5.2 part scripts. Parts are connected BY CONSTRUCTION (placed by
relation, entering their host by 5 mm) and passed BY MEASUREMENT (kit3d.check in live Blender), never by eye.

    import sys; sys.path.insert(0, '~/.claude/skills/3d-modelling/scripts')
    import kit3d as k
    k.begin('roof_vent')                                   # this part's objects; re-running replaces them
    hood = k.lathe('roof_vent.hood', [(0, 0), (0.2, 0), (0.2, 0.12), (0, 0.14)], mat=k.metal('alu', '#d8d5cb', ref='physicallybased:Aluminum'))
    k.attach(hood, to='body.roof', at=k.on('top', x=1.2))   # on the real (curved) roof, 5 mm in at its shallowest
    k.span('grab.bar', a=('door.frame', k.on('+y', x=-0.4, z=1.2)), b=('door.frame', k.on('+y', x=-0.4, z=2.0)),
           section=0.014, form='standoff', out=0.06)
    k.lay(k.decal('num', 0.3, 0.2, mat), 'body.side', k.on('+y', x=2.0, z=1.0))   # 6 mm off, following the curve
    print(k.check(['roof_vent'])['text'])                   # <= 10 lines; FAIL lines name part, host, mm and place

Placement (place.py; module doc lists the anchor forms):
  attach(part, to, at, by=None, embed=None, align=True, up=None, spin_deg=0, conform=0)  rests on / enters
    (embed None: 5 mm; small parts 45 % of their height; >= 2.5 mm off a thin wall's far side)
  span(name, a=(host, anchor), b=(host, anchor), section=r|('rect',w,h)|outline, form='straight'|'standoff'|'via'|'coil')
  lay(layer, on_, at, lift=LIFT, cut=False)       decals, stripes, plates, lettering
  scatter(name, proto, host, points)              rivets / bolts: many copies, each fitted, one object
  into(part, host)                                declared contact for a part built in place (measured, not moved)
  free(part, reason) / root(part)                 held by nothing on purpose / the part everything hangs on
  anchor(host, name, at) -> 'anchor.<name>'       mark a mount point once in the host's script
  mirror(parts, axis='y', names=[...] or {orig: new}), array(part, count, step), reattach(parts), dependents(hosts)   relations are copied/replayed
    (a replayed span is rebuilt INTO its object: name, plan part, collection and modifiers stay)
  adopt(objs, part, host=None)                    UPGRADING: objects kit3d did not make (the kept originals) join plan
    part `part` ({name: part} for many); then declare them: root(), into(obj, host), attach(...). Objects left
    untagged FAIL the step as `unplaced` and are not written to parts.json
  seat(part=None, host=None, depth=0.003)         UPGRADING: a kept part that only TOUCHES its host: its contact
    vertices move 3 mm into the host (the look stays), `into` is declared and measured. seat() with no argument
    seats every failing `into`; a gap is re-hosted on the mesh the part really touches; a host under 4.4 mm thin is
    grown on its hidden far side or reported (upgrade.py)
  restore(obj, source.blend)                      UPGRADING: the kept mesh back from its source before a cut or seat
    is redone, wearing THIS file's materials (never libraries.load a kept object again: it brings material copies)
  freeze(parts=None) / unfreeze(parts)            apply the placement into the mesh: the object sits at identity, so the
    shared shader kinds (they read OBJECT coordinates: grime by height, brushing along X) see the asset's frame.
    Relations stay measured and replayable, and anchors on a frozen host are still read in the frame it was built
    in (scripts of what hangs on it do not change). Call it once a part is placed; check() names parts that need it
Shapes (shapes.py, UVs in metres made at creation): box rbox cyl lathe prism loft sweep tube ring_solid frame pane
  decal plate gusset text_mesh; 2D: rr_outline circle fillet offset resample arc_pts round_path;
  modifiers: bevel subsurf smooth solidify(inner skin + rim get their own UVs; apply=False: split_shell_uv after
  apply_mods) apply_mods join boolean cut union.  scatter: every copy gets its own UV place
Check (check.py): relations, unplaced, coplanar, back-to-back, UVs decide PASS/FAIL (the PASS line shows entry AND
  into overlaps; a coplanar line gives the gap in mm, both face normals and what to do; `into` reads the distance of
  the part's deepest point to the host's NEAREST skin); a MATERIALS line names unused copies that shadow a used
  material (edits to them show nowhere); two ADVISORY lines never fail: LOOK (per part razor / facet / flat-shaded share, look.py's own
  classes and bands via ../look/mesh_core.py, ~1 ms a part) and FRAME (parts in their own frame under a shared kind)
Materials (mat.py): material(name, base, metallic, rough, ref=, src=) paint metal glass lamp(kelvin) decal_mat;
  ref='physicallybased:<name>' fills the measured values left out (matref.py); sources() inferred() set_ref_lookup(fn)
LOD from the same program: set_lod('mid'); lod_segments(n); keep(size) (2 px at the switch distance).
Plan: parts.json (PARTS-SCHEMA.md), written by bridge.py step / sync_plan(); plan_check.py validates it.
Constants (const.py): EMBED 5 mm, LIFT 6 mm, ENTRY 2-10 mm, COPLANAR 2 mm / 1 cm2, BACK2BACK 0.2 mm.
Examples: examples/ (14 parts; run_all.py rebuilds, checks and draws pics/SHEET.jpg). Self-test: ../tests/run.sh
  (6 seeded faults, 15 build cases, plan_check 9).
Pitfalls of Blender 5.2: ../../references/PITFALLS-blender-5.2.md (look an error up there; never delete the line).
"""
from .const import *                                     # noqa: F401,F403
from .core import begin, lod, set_lod, lod_segments, keep, rels, geo, clear_cache, obj, update
from .shapes import (poly_area, rr_outline, circle, fillet, offset, resample, arc_pts, round_path, box, prism, rbox,
                     loft, cyl, lathe, sweep, tube, ring_solid, frame, pane, decal, plate, gusset, text_mesh, bevel,
                     subsurf, smooth, apply_mods, solidify, split_shell_uv, join, boolean, cut, union, frames_along)
from .place import (on, attach, span, lay, scatter, into, free, root, anchor, mirror, array, reattach, reattach_chain, dependents,
                    resolve, depth_along, adopt, freeze, unfreeze, is_frozen)
from .check import check
from .upgrade import seat, restore, shadow_materials
from .mat import (material, paint, metal, glass, lamp, decal_mat, sources, inferred, set_ref_lookup, hexc, kelvin)
from .step import step_begin, step_end, render_thumb
from . import plan as plan_io
from . import uv


def sync_plan(path, parts=None, check_result=None, check_json=None):
    """Write the scene's relations (and, given a check result, its flags) into parts.json at `path`."""
    rs = [r for r in rels().values() if parts is None or r.get('plan_part') in parts or r['part'] in parts]
    if check_result is not None:
        m = {(x['kind'], x['part'], x.get('host', '')): x.get('measured') for x in check_result['relations']}
        for r in rs: r['measured'] = m.get((r['kind'], r['part'], r.get('host', '')))
    return plan_io.record(path, rs, check_result['per_part'] if check_result else None, check_json)
