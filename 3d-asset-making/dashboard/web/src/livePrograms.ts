// Live surface programs (Shader Lab, skill 3d-asset-making): an asset folder with shaders/spec.json gets its
// programs attached by material name with the lab's own surface.js, the module the game imports. The GLB keeps its
// baked FALLBACK (what a plain glTF viewer shows); this module keeps both material sets so the viewer can show either.
import * as THREE from 'three';
import { attachByName, type SurfaceProgram } from '@shaderlab/surface.js';
import { loadIdleLibrary, makeIdleMaterial, packSlot, type IdleLibrary, type IdleRecord } from '@idle-library/idle-three.js';

type Mat = THREE.Material | THREE.Material[];
export type LiveSpec = { url: string; programs: Record<string, SurfaceProgram> };
export type LiveInfo = { spec: string; materials: string[]; missing: string[]; on: boolean; playing: boolean; noShadow?: string[]; kinds: string[]; animated: boolean };

// Library KINDS (a design decision, 3d-asset-making skill: materials stay shaders through near and mid): a material whose glTF
// extras carry idle = {kind, slot, p} is drawn with the kind's GLSL twin from the shader library's own idle-three.js
// (the module the game uses). Bound per mesh with that module's makeIdleMaterial/packSlot, never its bindIdleAsset:
// that merges every primitive of a node into one mesh, which would break parts, framing and checker marks here.
export const idleRecord = (m: THREE.Material): IdleRecord | null => {
  let v = m.userData?.idle as IdleRecord | string | undefined;
  if (typeof v === 'string') try { v = JSON.parse(v) as IdleRecord; } catch { return null; }
  return v && typeof v === 'object' && v.kind && v.p ? v : null;
};
export function hasIdleKinds(model: THREE.Object3D) {
  let found = false;
  model.traverse(o => { const m = o as THREE.Mesh; if (m.isMesh && [m.material].flat().some(idleRecord)) found = true; });
  return found;
}
let library: Promise<IdleLibrary> | null = null;
/** kinds.json, idle-kinds.glsl and the shared noise, served from config idleLibrary; loaded once per page. */
export const loadKinds = () => (library ??= loadIdleLibrary(THREE, 'api/idle-library/').catch(e => { library = null; throw e; }));

/** Ask the server for shaders/spec.json in the GLB's folder or its parent (assets keep exports in export/);
 * absent = {url: null}, so assets without programs cost one small request and no console 404. */
export async function findLiveSpec(glbUrl: string): Promise<LiveSpec | null> {
  if (!/^\/?f\//.test(glbUrl)) return null;
  const found = await fetch(`api/live-spec?glb=${encodeURIComponent(glbUrl)}`).then(r => r.ok ? r.json() : { url: null }) as { url: string | null; base?: string };
  if (!found.url) return null;
  const spec = await fetch(found.url).then(r => { if (!r.ok) throw new Error(`spec.json: HTTP ${r.status}`); return r.json(); }) as { programs?: Record<string, SurfaceProgram> };
  if (!spec.programs || !Object.keys(spec.programs).length) return null;
  const programs: Record<string, SurfaceProgram> = {};
  for (const [name, p] of Object.entries(spec.programs)) {
    const inline = /\n|void\s+surface/.test(p.glsl);
    const glsl = inline ? p.glsl : await fetch(`${found.base}/${p.glsl}`).then(r => { if (!r.ok) throw new Error(`${p.glsl}: HTTP ${r.status}`); return r.text(); });
    programs[name] = { ...p, glsl };
  }
  return { url: found.url, programs };
}

/** Both material sets of a model with live programs; swap() shows one. */
export class LivePrograms {
  readonly fallback = new Map<THREE.Mesh, Mat>();
  readonly live = new Map<THREE.Mesh, Mat>();
  readonly uniforms: { uTime: { value: number } }[];
  readonly info: LiveInfo;
  time = 0;
  constructor(model: THREE.Object3D, spec: LiveSpec | null, lib: IdleLibrary | null = null) {
    const programs = spec?.programs || {};
    const named = (m: THREE.Material) => !!programs[m.name];
    model.traverse(o => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh) return;
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      if (!mats.some(named)) return;
      this.fallback.set(mesh, mesh.material);
      const clone = (m: THREE.Material) => named(m) ? m.clone() : m; // the program edits a copy; the fallback stays as exported
      mesh.material = Array.isArray(mesh.material) ? mesh.material.map(clone) : clone(mesh.material);
    });
    let attached: { materials: THREE.Material[]; missing: string[] } = { materials: [], missing: [] };
    try { if (spec) attached = attachByName(model, programs); }
    catch (e) { for (const [mesh, mat] of this.fallback) mesh.material = mat; throw e; } // e.g. a hook string missing in this three revision
    const { materials, missing } = attached;
    for (const mesh of this.fallback.keys()) this.live.set(mesh, mesh.material);
    const kinds = new Set<string>();
    if (lib) {
      const made = new Map<THREE.Material, THREE.Material>(); // one live material per exported material (shared by its meshes)
      const live = (m: THREE.Material) => {
        const idle = named(m) ? null : idleRecord(m), kind = idle && lib.kinds[idle.kind];
        if (!idle || !kind) return m;
        let out = made.get(m);
        if (!out) {
          const src = m as THREE.MeshStandardMaterial;
          out = makeIdleMaterial(THREE, lib, { slots: [packSlot(lib, idle)], kinds: [kind.id], aoMap: src.aoMap || null,
            normalMap: src.normalMap || null, normalScale: src.normalMap ? src.normalScale : null, transparent: !!kind.transparent, tier: 'near' });
          out.name = m.name; out.userData.idleRecord = idle; made.set(m, out); kinds.add(idle.kind);
        }
        return out;
      };
      model.traverse(o => {
        const mesh = o as THREE.Mesh;
        if (!mesh.isMesh || ![mesh.material].flat().some(m => !named(m) && idleRecord(m) && lib.kinds[idleRecord(m)!.kind])) return;
        const g = mesh.geometry; // every vertex in slot 0: one slot per material here
        if (!g.getAttribute('_idle_slot')) g.setAttribute('_idle_slot', new THREE.BufferAttribute(new Float32Array(g.getAttribute('position').count), 1));
        if (!this.fallback.has(mesh)) this.fallback.set(mesh, mesh.material);
        const cur = this.live.get(mesh) ?? mesh.material;
        this.live.set(mesh, Array.isArray(cur) ? cur.map(live) : live(cur));
      });
      for (const [mesh, mat] of this.live) mesh.material = mat;
    }
    this.uniforms = materials.map(m => (m.userData.surface as { uniforms: { uTime: { value: number } } }).uniforms);
    this.info = { spec: spec?.url || '', materials: materials.map(m => m.name), missing, on: true, playing: true, kinds: [...kinds].sort(), animated: materials.length > 0 };
  }
  set(on: boolean) { this.info.on = on; return on ? this.live : this.fallback; }
  advance(dt: number) { this.time += dt; for (const u of this.uniforms) u.uTime.value = this.time; }
  /** Disposes the program materials; the caller shows the fallback first so disposing the model frees the rest. */
  dispose() { const keep = new Set([...this.fallback.values()].flat()); for (const mat of this.live.values()) for (const m of [mat].flat()) if (!keep.has(m)) m.dispose(); }
}

/** Alpha-blended or additive materials (glow cards, halos) never cast shadows. */
export const castsShadow = (mat: Mat) => (Array.isArray(mat) ? mat : [mat]).every(m => !m.transparent && m.blending !== THREE.AdditiveBlending);
