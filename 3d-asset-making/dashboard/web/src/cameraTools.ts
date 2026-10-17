import * as THREE from 'three';
import { fitCamera } from './framing.ts';
import type { CameraPreset, CameraState } from './viewerSettings.ts';
export type ViewCamera = THREE.PerspectiveCamera | THREE.OrthographicCamera;
export const cameraDirection = (preset: CameraPreset) => new THREE.Vector3(...({ 'three-quarter': [.55,.42,1], front:[0,0,1], rear:[0,0,-1], left:[-1,0,0], right:[1,0,0], top:[0,1,.00001] }[preset] as [number,number,number])).normalize();
export function fitView(camera: ViewCamera, box: THREE.Box3, aspect: number, direction?: THREE.Vector3) {
  const center = box.getCenter(new THREE.Vector3()), view = direction || camera.position.clone().sub(center).normalize();
  camera.up.set(0,1,0);
  if (camera instanceof THREE.PerspectiveCamera) { camera.aspect = aspect; fitCamera(camera,box,view.lengthSq() ? view : cameraDirection('three-quarter')); }
  else {
    const r = Math.max(box.getSize(new THREE.Vector3()).length(), .001);
    camera.position.copy(center).addScaledVector(view,r*2); camera.lookAt(center); camera.updateMatrixWorld();
    const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld,0), up = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld,1);
    let xMax=0,yMax=0;
    for(const x of [box.min.x,box.max.x]) for(const y of [box.min.y,box.max.y]) for(const z of [box.min.z,box.max.z]) { const v = new THREE.Vector3(x,y,z).sub(center); xMax=Math.max(xMax,Math.abs(v.dot(right))); yMax=Math.max(yMax,Math.abs(v.dot(up))); }
    const half = Math.max(yMax, xMax / aspect, .0001) / .88;
    camera.top=half; camera.bottom=-half; camera.left=-half*aspect; camera.right=half*aspect; camera.zoom=1; camera.near=.00001;camera.far=r*20;camera.updateProjectionMatrix();
  }
  return center;
}
export function cameraState(camera: ViewCamera, target: THREE.Vector3): CameraState {
  return { position: camera.position.toArray(), target: target.toArray(), up: camera.up.toArray(), projection: camera instanceof THREE.OrthographicCamera ? 'orthographic':'perspective', scale: camera instanceof THREE.OrthographicCamera ? (camera.top-camera.bottom)/camera.zoom : camera.position.distanceTo(target) };
}
