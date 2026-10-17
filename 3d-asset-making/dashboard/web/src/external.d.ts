// Files read from outside this repo at build time (aliases in vite.config.ts).
declare module '@game-picture-effects' { const list: unknown; export default list; }
declare module '@shaderlab/surface.js' {
  import type * as THREE from 'three';
  export type SurfaceProgram = { glsl: string; uniforms?: Record<string, unknown>; unlit?: boolean; blending?: string; transparent?: boolean; side?: string };
  export function attachSurface(material: THREE.Material, glsl: string, uniforms?: Record<string, unknown>): Record<string, { value: unknown }>;
  export function attachByName(root: THREE.Object3D, programs: Record<string, SurfaceProgram>): { materials: THREE.Material[]; missing: string[] };
}
declare module '@idle-library/idle-three.js' {
  import type * as THREE from 'three';
  export type IdleRecord = { kind: string; slot?: string; p: Record<string, number | number[]> };
  export type IdleKind = { kind: string; id: number; transparent?: boolean };
  export type IdleLibrary = { kinds: Record<string, IdleKind>; slotVec4: number };
  export function loadIdleLibrary(three: typeof THREE, base: string): Promise<IdleLibrary>;
  export function packSlot(lib: IdleLibrary, idle: IdleRecord, overrides?: Record<string, Record<string, unknown>> | null): Float32Array;
  export function makeIdleMaterial(three: typeof THREE, lib: IdleLibrary, opts: { slots: Float32Array[]; kinds: number[]; aoMap?: THREE.Texture | null; normalMap?: THREE.Texture | null; normalScale?: THREE.Vector2 | null; transparent?: boolean; tier?: 'near' | 'mid'; debug?: number }): THREE.MeshStandardMaterial;
}
