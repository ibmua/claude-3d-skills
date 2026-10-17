import * as THREE from 'three';

export function visibleMeshes(root: THREE.Object3D) {
  const meshes: THREE.Mesh[] = [];
  root.traverseVisible((o) => {
    const m = o as THREE.Mesh;
    if (!m.isMesh) return;
    const materials = Array.isArray(m.material) ? m.material : [m.material];
    if (materials.some((mat) => mat.visible && mat.opacity > 0)) meshes.push(m);
  });
  return meshes;
}

export function frameBounds(root: THREE.Object3D) {
  root.updateWorldMatrix(true, true);
  const meshes = visibleMeshes(root);
  const solids = meshes.filter((m) => (Array.isArray(m.material) ? m.material : [m.material])
    .some((mat) => mat.visible && mat.opacity >= 0.5));
  const box = new THREE.Box3();
  for (const mesh of solids.length ? solids : meshes) {
    const posed = mesh as THREE.InstancedMesh | THREE.SkinnedMesh;
    if ((mesh as THREE.InstancedMesh).isInstancedMesh || (mesh as THREE.SkinnedMesh).isSkinnedMesh) {
      posed.computeBoundingBox();
      if (posed.boundingBox) box.union(posed.boundingBox.clone().applyMatrix4(mesh.matrixWorld));
    } else {
      mesh.geometry.computeBoundingBox();
      if (mesh.geometry.boundingBox) box.union(mesh.geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld));
    }
  }
  return box;
}

// Fit every bbox corner inside both axes, including a portrait viewport.
export function fitCamera(cam: THREE.PerspectiveCamera, box: THREE.Box3, direction = new THREE.Vector3(0.55, 0.42, 1)) {
  const center = box.getCenter(new THREE.Vector3());
  const view = direction.clone().normalize();
  const forward = view.clone().negate();
  const right = forward.clone().cross(cam.up).normalize();
  const up = right.clone().cross(forward).normalize();
  const ty = Math.tan(THREE.MathUtils.degToRad(cam.fov / 2)) * 0.88;
  const tx = ty * Math.max(cam.aspect, 1e-3);
  let distance = 1e-3;
  for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
    const corner = new THREE.Vector3(x, y, z).sub(center);
    distance = Math.max(distance, Math.max(Math.abs(corner.dot(right)) / tx, Math.abs(corner.dot(up)) / ty) - corner.dot(forward));
  }
  cam.position.copy(center).addScaledVector(view, distance);
  cam.near = distance / 200; cam.far = distance * 20;
  cam.lookAt(center); cam.updateProjectionMatrix(); cam.updateMatrixWorld();
  return center;
}

// Camera depth range. Depth resolution falls with z²/near, so near sits as far out as is safe: half the gap to the
// nearest mesh box or the ground plane (half covers the frustum's corner rays up to tan 1.7). The distance-only value
// is the floor and the whole answer when the camera is inside a mesh box (close inspection) or `boxes` is empty.
// Owner 2026-10-14: a fixed radius/10000 near (0.9 mm on four side-by-side shells) left ~4 cm depth steps at 25 m and
// 2.5 mm seam overlaps z-fought as jagged dashes.
export function clipRange(position: THREE.Vector3, model: THREE.Box3, boxes: THREE.Box3[], perspective = true) {
  const radius = Math.max(model.getSize(new THREE.Vector3()).length() / 2, 0.001), distance = position.distanceTo(model.getCenter(new THREE.Vector3()));
  let near = Math.max(1e-7, distance > radius * 4 ? (distance - radius * 3) * 0.1 : Math.min(radius / 10000, Math.max(distance, 1e-6) / 1000));
  const far = Math.max(radius * 40, distance + radius * 20);
  if (perspective && boxes.length) {
    let gap = Math.abs(position.y - model.min.y);
    for (const box of boxes) { gap = Math.min(gap, box.distanceToPoint(position)); if (gap <= 0) break; }
    if (gap > 0) near = Math.max(near, gap * 0.5);
  }
  return { near, far };
}
