# Blender 5.2 pitfalls: look the error up here

**Rule: when a line fails, look the error up here and in the API docs, then fix the cause. Never delete the failing
line, and never wrap it in `try/except: pass`.** A silent guard swallowed the NISHITA error, so a builder blamed the
sky. `bridge.py step` prints this file's path under every SCRIPT ERROR.

Facts are from Blender 5.2.2 LTS (d13f752e3b9c). **V** means checked by a probe in October 2026; **NV** means not
verified. Sources: two train-car rebuild sessions (659 tool calls scanned) and the kit3d build.

## A. Errors with a message (search for the text)
| Message (or part of it) | Cause | Do this instead |
|---|---|---|
| `KeyError: 'Emission'` / `'Clearcoat'` / `'Specular'` / `'Transmission'` / `'Subsurface'` | Principled v2 renamed its inputs. | Use `Emission Color` + `Emission Strength`, `Coat Weight` / `Coat Roughness`, `Specular IOR Level`, `Transmission Weight`, `Subsurface Weight`. V |
| `KeyError: 'A_Color'` on a Mix node | Socket identifiers are not keys. | Set `data_type='RGBA'` FIRST, then use `inputs['A']` / `['B']` / `['Factor']` / `outputs['Result']`, or `inputs[6]`, `[7]`, `outputs[2]`. A link made before setting `data_type` silently lands on the hidden float socket. V |
| `TypeError: enum "NISHITA" not found` (or nothing, if guarded) | NISHITA was removed. | `sky_type` is one of SINGLE_SCATTERING, MULTIPLE_SCATTERING (default), PREETHAM, HOSEK_WILKIE. `dust_density` became `aerosol_density`. V |
| `enum "BLENDER_EEVEE_NEXT" not found` | Renamed back in 5.x. | Use `BLENDER_EEVEE`, `BLENDER_WORKBENCH` or `CYCLES`. Baking needs CYCLES. V |
| `AttributeError: ... 'use_auto_smooth'` / `auto_smooth_angle` / `calc_normals_split` | Removed in 4.1. | Use `mesh.set_sharp_from_angle(angle=rad)`, `shade_smooth()`, `corner_normals`. V |
| `AttributeError: ... 'shadow_method'`; `blend_method` reads back wrong | `blend_method` is only a compatibility shim. | Use `material.surface_render_method = 'DITHERED'` or `'BLENDED'`. Never test `blend_method == 'OPAQUE'`. V |
| `Node type ShaderNodeSeparateRGB` / `CombineRGB` / `TexMusgrave` `undefined` | Removed. | Use `ShaderNodeSeparateColor` / `CombineColor`. Musgrave became `ShaderNodeTexNoise` (`noise_type`). V |
| `AttributeError: type object 'Matrix' has no attribute 'Diag'` | The name never existed. | `Matrix.Diagonal((sx, sy, sz, 1))`. A 3-vector gives a 3x3 matrix: call `.to_4x4()` before `@` with a 4x4. V |
| `has no evaluated mesh data` (Object.ray_cast) | The object sits in a hidden or excluded collection, so it is not evaluated. | Unhide the collection, set the layer collection `exclude=False`, then `view_layer.update()`. See C1. V |
| `poll() failed, context is incorrect` (modifier_apply, join, shade_smooth, smart_project) | Running with `-b`: no active object, nothing selected, no area. | `with bpy.context.temp_override(object=o, active_object=o, selected_objects=[o], selected_editable_objects=[o]):`. smart_project also needs EDIT mode and select all. V |
| `No active UV layer found` (bake) | The bake target has no UVs. | Make UVs at creation (kit3d does), or `me.uv_layers.new()` and set it active. V |
| `write() argument 2 must be set, not list` | `bpy.data.libraries.write` takes a set. | `libraries.write(path, {ids}, ...)`. V |
| `TypeError` on `create_cone(diameter1=...)` | Wrong keyword. | `create_cone(radius1=, radius2=, depth=, segments=, cap_ends=)`; `create_uvsphere(radius=)`. V |
| `ValueError: face already exists` | A duplicate `bm.faces.new`. | Find out why it is a duplicate. A skipped face is a hole (NV link to a nose-crown hole). |
| `The 'result' variable must be a dict, not str` (bridge) | Bridge contract. Its side effects have already run. | `result = {...}` with JSON types only: `v[:]`, `.tolist()`, `float()`, `str(op_result)`. V |
| `NameError: name 'bpy' is not defined` (bridge) | Every call runs in a fresh namespace. | `import bpy` in every snippet. Modules persist between calls; variables do not. V |
| `KeyError` from module-level state after a reload | `from mod import M` keeps a reference to the old dict. | Read `mod.M` after `importlib.reload`, or rebuild the state. |
| `kit3d.attach: ... footprint is not over <host>` | The part's mounting face lands over a hole, off the host's edge, or on the wrong face. | Check the anchor: `on()` coordinates are HOST-LOCAL. Check `by=` too: the default is the face opposite `at`. On one train car the side skin ends at z 0.72, with door openings above. |
| `kit3d: no surface of <host> at ...` | The ray from that face of the host's bbox missed: a hole, or coordinates outside the host. | Use host-local coordinates inside the face (a box centred on its origin spans -size/2..+size/2). |
| `kit3d: <part> has a mirroring (negative) scale` | Mirroring by scale breaks normals (C3). | `kit3d.mirror(parts, axis='y')`. |

## B. Silent failures (no error, wrong result)
| Symptom | Cause | Fix |
|---|---|---|
| A game LOD lost 3.7k of 8.6k triangles; the bake source had too few triangles | A hidden collection means no modifiers: `evaluated_get().data` / `new_from_object` return the BASE mesh. | Unhide before reading the depsgraph and assert the triangle count. `kit3d.apply_mods` asserts; `kit3d.check` warns about objects in hidden collections. V |
| The glTF export reports FINISHED, but the GLB has no `meshes` | `select_set(True)` on a hidden object does nothing, so `use_selection=True` exports nothing. | Unhide, `assert o.select_get()`, and read the GLB back. V |
| One side renders black or bakes inside-out | `Mesh.transform(M)` with det(M) < 0 (a mirrored mount) keeps the winding, so faces point inward. | `me.transform(M); if M.determinant() < 0: me.flip_normals()`. kit3d geometry rewinds det < 0 placements itself. V |
| The near GLB is 13 MB | A float-buffer image saved as PNG is 16-bit and gets embedded as is. | `export_image_format='JPEG', export_jpeg_quality=92`. V |
| `matrix_world` / bounds are stale after setting location or moving the parent | Only a depsgraph update recomputes them. | `bpy.context.view_layer.update()` (`kit3d.update()`). V |
| A bridge error, yet the pipeline ran on | `bridge_call.py` always exits 0, and `\| tail` hid the error. | Use the skill's `bridge.py` (exit 1 on error, `step` exit 3 on FAIL). Never pipe bridge output through tail/grep unchecked. V |
| A texture renders as speckle in the game | The image is read through Object/Box coordinates and the mesh has no UVs; glTF has no such node. | Read images through UVs only (kit3d.mat does) and make metre UVs at creation. |
| Material `metallic` 0.35 / 0.45 / 0.55 / 0.85 with no source | An invented in-between value (a car's alu/roof/steel/chequer). | Pick bare metal or paint first. Use `ref='physicallybased:<name>'` (fills measured values); a judged value gets a `src`. |

## C. kit3d traps (found by measurement while building it)
1. **Hidden collection = not evaluated.** Keep the parts you measure in visible collections. `check` prints WARN for any it had to measure without modifiers.
2. **`begin(part)` clears.** Re-running a part script deletes that part's objects, relations, unbent source meshes and cutters. A seed or test that must keep them uses `begin(part, clear=False)`.
3. **No negative scale.** Mirror with `kit3d.mirror`, which reflects the mesh, flips the winding and replays the relation on the mirrored host point. `reflect=False` keeps lettering readable.
4. **`on()` coordinates are host-local.** On a 2.4 m wall built centred, z = 1.9 is outside it. kit3d's `wall()` example host has its floor at z = 0.
5. **sys.path order in the bridge.** A part script's `sys.path.insert(0, '~/.claude/...')` shadowed the copy under test. `bridge.py step` forces its own kit3d first and purges stale `kit3d*` modules every step.
6. **BVHTree.ray_cast misses a ray that runs exactly along a shared edge or vertex** (float32). The centre-line ray onto a subdivided plate missed both triangles. `kit3d.place.ray()` retries with 10 µm offsets; use it for any ray you cast yourself.
7. **Smooth normals blend across hard edges.** The interpolated normal at the top of a box tilted 30° toward its side. kit3d blends normals only between faces within about 45° (`SMOOTH_COS`).
8. **Bent quads are not flat.** The plug and the Boolean pocket chose different diagonals, so a 0.4 mm gap measured 0.185 mm. Bent meshes are triangulated, after subdividing to a fifth of the part (4 mm to 5 cm).
9. **A flat part bent without vertices stays a chord.** n-gon caps and long edges cut through a curved host: an 8 mm sag through a 4 mm plate. conform and lay subdivide first.
10. **Thickness under bending.** Moving vertices along the rigid normal thins a layer on a tilted flank (3 mm steps became 1.7 mm). kit3d offsets along the local surface normal.
11. **Small parts and thin walls.** A default 5 mm entry buries a 5 mm rivet, and on a 4 mm wall it brings the part's back within 1.3 mm of the inner skin (z-fight). With `embed=None`, kit3d uses 45 % of a small part's height and stays at least 2.5 mm off a thin wall's far side.
12. **Never rsync a plan that tools write** (`parts.json`). It reset flags the check had flipped.
13. **2 mm is the z-fight limit.** Step stacked layers (surround / gasket / glass) at least 3 mm apart. A part as thick as its host shares the host's side planes over the entry depth.

## D. Bridge contract (one long-lived Blender per port)
- Each call runs `exec(code, {"result": {}})` on Blender's main thread, with **no execution timeout**, one connection at a time. Killing the client does not stop Blender.
- `bpy.data` persists and is checkpointed to `$MV_CKPT_DIR/scene.blend`. `sys.exit`, `wm.quit_blender` and `wm.read_factory_settings` are blocked.
- `result` must be a JSON dict. Vector, Matrix, Color, numpy scalars and arrays, sets and bpy objects all fail.
- `bridge.py run` uses `exec(compile(src, path))` with `__name__="__bridge_script__"`, so `if __name__ == "__main__":` blocks do not run.
- Ports 10914/10915 are the film's: never use them. The `opus_dispatch.py` pool (`10901-10920`) still lists them (claim conflict, reported).
- Inside Blender: Python 3.13 with numpy 2.3; no PIL. A system `python3` may have PIL but no numpy.
- Memory rule on a shared box: run heavy jobs as `systemd-run --user --scope -p MemoryMax=12G -p MemorySwapMax=0 nice -n 10 blender -t 8 ...`. `bridge.py step` / `detach` and `tests/run.sh` do this.
