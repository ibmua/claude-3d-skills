import * as THREE from 'three';
import { fitCamera, frameBounds } from './framing.ts';

export type ModelPart = { id: string; uuid: string; name: string; visible: boolean };

// Descend single wrapper nodes, retaining authored groups rather than splitting skinned meshes.
export function modelParts(model: THREE.Object3D): ModelPart[] {
  const hasGeometry = (node: THREE.Object3D) => { let found = false; node.traverse(o => { if ((o as THREE.Mesh).isMesh) found = true; }); return found; };
  let parent = model, path: number[] = [];
  while (!(parent as THREE.Mesh).isMesh) {
    const children = parent.children.map((node, i) => ({ node, i })).filter(c => hasGeometry(c.node));
    if (children.length !== 1 || (children[0].node as THREE.Mesh).isMesh) break;
    path = [...path, children[0].i]; parent = children[0].node;
  }
  return parent.children.flatMap((node, i) => hasGeometry(node) ? [{ id: `${[...path, i].join('.')}:${node.name || node.type}`, uuid: node.uuid, name: node.name || node.type, visible: node.visible }] : []);
}

// One tiny offscreen frame per requested part, with live scene state restored before awaiting pixels.
export async function partPicture(renderer: THREE.WebGLRenderer, scene: THREE.Scene, model: THREE.Object3D, parts: ModelPart[], id: string, grid?: THREE.GridHelper) {
  const selected = parts.find(p => p.id === id), node = selected && model.getObjectByProperty('uuid', selected.uuid);
  if (!node) return null;
  const visibility = parts.map(p => { const object = model.getObjectByProperty('uuid', p.uuid)!; return { object, visible: object.visible }; });
  const target = new THREE.WebGLRenderTarget(256, 192, { samples: 2 });
  target.texture.colorSpace = THREE.SRGBColorSpace;
  const previousTarget = renderer.getRenderTarget(), gridVisible = grid?.visible;
  const pixels = new Uint8Array(256 * 192 * 4);
  let reading: Promise<unknown> | undefined;
  try {
    visibility.forEach(v => { v.object.visible = v.object === node; });
    if (grid) grid.visible = false;
    const box = frameBounds(node); if (box.isEmpty()) return null;
    const camera = new THREE.PerspectiveCamera(40, 256 / 192, 0.001, 1000); fitCamera(camera, box);
    renderer.setRenderTarget(target); renderer.render(scene, camera);
    reading = renderer.readRenderTargetPixelsAsync(target, 0, 0, 256, 192, pixels);
  } finally {
    renderer.setRenderTarget(previousTarget);
    visibility.forEach(v => { v.object.visible = v.visible; });
    if (grid) grid.visible = gridVisible!;
    if (!reading) target.dispose();
  }
  try {
    await reading;
    const canvas = document.createElement('canvas'); canvas.width = 256; canvas.height = 192;
    const ctx = canvas.getContext('2d'); if (!ctx) return null;
    const image = ctx.createImageData(256, 192);
    for (let y = 0; y < 192; y++) image.data.set(pixels.subarray((191 - y) * 1024, (192 - y) * 1024), y * 1024);
    ctx.putImageData(image, 0, 0); return canvas.toDataURL('image/png');
  } finally { target.dispose(); }
}
