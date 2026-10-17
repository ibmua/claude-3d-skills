import * as THREE from 'three';
import { frameBounds, visibleMeshes } from './framing.ts';
export type AssetStats = { tris: number; meshes: number; materials: number; textures: number; vertices: number; geometryBytes: number; textureBytes: number; dimensions: number[] };
export type ViewPerf = { calls: number; triangles: number; textures: number; geometries: number; cpuMs: number; fps: number | null; width: number; height: number; intervals?: number[]; ratio?: number; post?: string[]; refine?: number | null };

// Visible asset content; unique GPU buffers are counted once even for instancing/shared geometry.
export function measureAsset(root: THREE.Object3D): AssetStats {
  let tris = 0, vertices = 0, geometryBytes = 0, textureBytes = 0;
  const meshes = visibleMeshes(root), materials = new Set<THREE.Material>(), textures = new Set<THREE.Texture>(), buffers = new Set<THREE.BufferAttribute | THREE.InterleavedBuffer>();
  const addBuffer = (a: THREE.BufferAttribute | THREE.InterleavedBufferAttribute) => {
    const buffer = (a as THREE.InterleavedBufferAttribute).isInterleavedBufferAttribute ? (a as THREE.InterleavedBufferAttribute).data : a as THREE.BufferAttribute;
    if (!buffers.has(buffer)) { buffers.add(buffer); geometryBytes += buffer.array.byteLength; }
  };
  for (const mesh of meshes) {
    const g = mesh.geometry, instances = (mesh as THREE.InstancedMesh).isInstancedMesh ? (mesh as THREE.InstancedMesh).count : 1;
    tris += (g.index?.count ?? g.attributes.position?.count ?? 0) / 3 * instances;
    vertices += (g.attributes.position?.count ?? 0) * instances;
    Object.values(g.attributes).forEach(addBuffer); if (g.index) addBuffer(g.index);
    Object.values(g.morphAttributes).flat().forEach(addBuffer);
    if ((mesh as THREE.InstancedMesh).isInstancedMesh) { const m = mesh as THREE.InstancedMesh; addBuffer(m.instanceMatrix); if (m.instanceColor) addBuffer(m.instanceColor); }
    for (const mat of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
      materials.add(mat);
      for (const value of Object.values(mat)) if ((value as THREE.Texture)?.isTexture) textures.add(value as THREE.Texture);
    }
  }
  for (const tex of textures) {
    const images = Array.isArray(tex.image) ? tex.image : [tex.image];
    for (const img of images) if (img?.width && img?.height) textureBytes += img.width * img.height * 4;
  }
  const box = frameBounds(root);
  return { tris: Math.round(tris), vertices, meshes: meshes.length, materials: materials.size, textures: textures.size, geometryBytes, textureBytes, dimensions: box.isEmpty() ? [] : box.getSize(new THREE.Vector3()).toArray() };
}
export function disposeObject(root: THREE.Object3D) {
  const materials = new Set<THREE.Material>(), textures = new Set<THREE.Texture>(), geometries = new Set<THREE.BufferGeometry>();
  root.traverse(o => { const m = o as THREE.Mesh; if (m.geometry) geometries.add(m.geometry); for (const mat of m.material ? (Array.isArray(m.material) ? m.material : [m.material]) : []) materials.add(mat); });
  materials.forEach(mat => { for (const value of Object.values(mat)) if ((value as THREE.Texture)?.isTexture) textures.add(value as THREE.Texture); mat.dispose(); });
  geometries.forEach(g => g.dispose()); textures.forEach(t => t.dispose());
}
