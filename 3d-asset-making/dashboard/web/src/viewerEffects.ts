import * as THREE from 'three';
import { attachSurface } from '@shaderlab/surface.js';
import { PICTURE_EFFECTS } from './pictureEffects.ts';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { GTAOPass } from 'three/examples/jsm/postprocessing/GTAOPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { Pass, FullScreenQuad } from 'three/examples/jsm/postprocessing/Pass.js';
import { CopyShader } from 'three/examples/jsm/shaders/CopyShader.js';
import { HorizontalBlurShader } from 'three/examples/jsm/shaders/HorizontalBlurShader.js';
import { VerticalBlurShader } from 'three/examples/jsm/shaders/VerticalBlurShader.js';

// Post effects and the contact shadow (owner 2026-10-13: import what threepipe/webgi have and we missed).
// Chain, only while one of them is on: RenderPass (4× MSAA, half float) → GTAO → bloom → accumulate → OutputPass
// (tone mapping + sRGB, as the plain path does). Everything off = the plain renderer.render(), exactly as before.
// Report and costs: docs/effects-import-20261013.md.

export const REFINE_FRAMES = 32;
const halton = (i: number, b: number) => { let f = 1, r = 0; while (i > 0) { f /= b; r += f * (i % b); i = Math.floor(i / b); } return r; };
// Sub-pixel camera offsets for the accumulated frames; sample 0 is the plain frame.
const JITTER = Array.from({ length: REFINE_FRAMES }, (_, i) => i ? [halton(i, 2) - .5, halton(i, 3) - .5] : [0, 0]);

// Running average of jittered frames: sample i is blended in with weight 1/(i+1), so after N frames it holds their mean.
class AccumulatePass extends Pass {
  index = 0;
  target = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, depthBuffer: false });
  private quad = new FullScreenQuad();
  private blend = new THREE.ShaderMaterial({
    uniforms: { tDiffuse: { value: null }, weight: { value: 1 } }, vertexShader: CopyShader.vertexShader,
    fragmentShader: 'uniform sampler2D tDiffuse;uniform float weight;varying vec2 vUv;void main(){gl_FragColor=vec4(texture2D(tDiffuse,vUv).rgb,weight);}',
    blending: THREE.CustomBlending, blendSrc: THREE.SrcAlphaFactor, blendDst: THREE.OneMinusSrcAlphaFactor, blendSrcAlpha: THREE.OneFactor, blendDstAlpha: THREE.ZeroFactor, depthTest: false, depthWrite: false,
  });
  // Opaque copy: the canvas is composited with alpha, so the blend weight (1/32 on the last sample) must not leak out.
  private copy = new THREE.ShaderMaterial({ uniforms: { tDiffuse: { value: null } }, vertexShader: CopyShader.vertexShader, fragmentShader: 'uniform sampler2D tDiffuse;varying vec2 vUv;void main(){gl_FragColor=vec4(texture2D(tDiffuse,vUv).rgb,1.0);}', depthTest: false, depthWrite: false });
  setSize(w: number, h: number) { this.target.setSize(w, h); }
  render(renderer: THREE.WebGLRenderer, writeBuffer: THREE.WebGLRenderTarget, readBuffer: THREE.WebGLRenderTarget) {
    const autoClear = renderer.autoClear; renderer.autoClear = false;
    this.blend.uniforms.tDiffuse.value = readBuffer.texture; this.blend.uniforms.weight.value = 1 / (this.index + 1);
    renderer.setRenderTarget(this.target); this.quad.material = this.blend; this.quad.render(renderer);
    this.copy.uniforms.tDiffuse.value = this.target.texture; this.quad.material = this.copy;
    renderer.setRenderTarget(this.renderToScreen ? null : writeBuffer); this.quad.render(renderer);
    renderer.autoClear = autoClear;
  }
  dispose() { this.target.dispose(); this.blend.dispose(); this.copy.dispose(); this.quad.dispose(); }
}

// GTAO that ignores the viewer's helpers (floor, contact plane, markers); lines/points are already skipped by three.
class ModelAOPass extends GTAOPass {
  skip: () => THREE.Object3D[] = () => [];
  private hidden: THREE.Object3D[] = [];
  _overrideVisibility() {
    (GTAOPass.prototype as unknown as { _overrideVisibility: () => void })._overrideVisibility.call(this);
    this.hidden = this.skip().filter(o => o.visible); this.hidden.forEach(o => { o.visible = false; });
  }
  _restoreVisibility() {
    (GTAOPass.prototype as unknown as { _restoreVisibility: () => void })._restoreVisibility.call(this);
    this.hidden.forEach(o => { o.visible = true; }); this.hidden = [];
  }
}

// Bloom of emissive surfaces only (screens, lamps, signs). A plain luminance threshold also catches lit white paint
// (measured: the cab's cream sides reach about 2 in linear HDR under the studio key), so the bright pass reads a
// separate emissive render (one extra geometry pass: emissive colour × intensity × map, everything else black) and the
// blurred glow is added over the beauty image by UnrealBloomPass's own composite.
// A material driven by a live surface program (livePrograms.ts) gets the SAME program in an emission-only form, sharing
// its uniforms: its exported emissive map is the baked still fallback, and blooming that put a frozen copy of the
// picture over the moving one (owner 2026-10-13 18:2x: "two centre circles", smeared players, haze).
// Strength, radius and threshold are the game's (effects.json bloom.params), so the viewer glows like the game.
const BLOOM = (PICTURE_EFFECTS.find(e => e.key === 'bloom')?.source as { params?: { threshold: number; strength: number; radius: number } } | undefined)?.params ?? { threshold: 1.6, strength: .4, radius: .35 };
type SurfaceData = { glsl: string; uniforms: Record<string, { value: unknown }> };
const rawUniform = (v: unknown): unknown => typeof v === 'number' ? v : (v as THREE.Color).isColor ? '#' + (v as THREE.Color).getHexString() : (v as THREE.Vector4).toArray();
function emissionProgram(material: THREE.Material, surface: SurfaceData) {
  const r = new THREE.MeshBasicMaterial({ side: material.side, transparent: material.transparent, blending: material.blending, depthWrite: material.depthWrite, toneMapped: false, fog: false });
  const extra = Object.fromEntries(Object.entries(surface.uniforms).filter(([k]) => k !== 'uTime').map(([k, u]) => [k, rawUniform(u.value)]));
  const glsl = surface.glsl.replace(/void\s+surface\s*\(/, 'void surface_program(') + '\nvoid surface(inout Surface s, vec2 uv, float t) { surface_program(s, uv, t); s.albedo = vec3(0.0); }\n';
  const u = attachSurface(r, glsl, extra);
  for (const k of Object.keys(u)) if (surface.uniforms[k]) u[k] = surface.uniforms[k]; // the live material's uniforms: same time, same tuning
  return r;
}
class EmissiveBloomPass extends UnrealBloomPass {
  skip: () => THREE.Object3D[] = () => [];
  private emissive = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType });
  private replacements = new Map<THREE.Material, THREE.Material>();
  constructor(private scene: THREE.Scene, private camera: () => THREE.Camera, resolution: THREE.Vector2) {
    super(resolution, BLOOM.strength, BLOOM.radius, BLOOM.threshold);
    const emissive = this.emissive;
    (this.highPassUniforms as Record<string, unknown>).tDiffuse = { get value() { return emissive.texture; }, set value(_: unknown) { /* the bright pass always reads the emissive render */ } };
  }
  setSize(w: number, h: number) { super.setSize(w, h); this.emissive.setSize(w, h); }
  private replacement(material: THREE.Material) {
    let r = this.replacements.get(material);
    if (!r) {
      const surface = material.userData.surface as SurfaceData | undefined;
      if (surface) { r = emissionProgram(material, surface); this.replacements.set(material, r); return r; }
      const m = material as THREE.MeshStandardMaterial, color = m.emissive ? m.emissive.clone().multiplyScalar(m.emissiveIntensity ?? 1) : new THREE.Color(0);
      r = new THREE.MeshBasicMaterial({ color, map: m.emissiveMap || null, side: material.side, transparent: material.transparent, opacity: material.transparent ? 0 : 1, depthWrite: material.depthWrite, alphaTest: material.alphaTest, toneMapped: false, fog: false });
      this.replacements.set(material, r);
    }
    return r;
  }
  render(renderer: THREE.WebGLRenderer, writeBuffer: THREE.WebGLRenderTarget, readBuffer: THREE.WebGLRenderTarget, deltaTime: number, maskActive: boolean) {
    const swapped: [THREE.Mesh, THREE.Material | THREE.Material[]][] = [], hidden = this.skip().filter(o => o.visible), background = this.scene.background;
    this.scene.traverseVisible(o => { const m = o as THREE.Mesh; if (m.isMesh && m.material) { swapped.push([m, m.material]); m.material = Array.isArray(m.material) ? m.material.map(x => this.replacement(x)) : this.replacement(m.material); } });
    hidden.forEach(o => { o.visible = false; }); this.scene.background = null;
    const clear = renderer.getClearColor(new THREE.Color()), alpha = renderer.getClearAlpha(); renderer.setClearColor(0x000000, 1);
    renderer.setRenderTarget(this.emissive); renderer.clear(); renderer.render(this.scene, this.camera());
    renderer.setClearColor(clear, alpha); this.scene.background = background; hidden.forEach(o => { o.visible = true; }); for (const [m, material] of swapped) m.material = material;
    super.render(renderer, writeBuffer, readBuffer, deltaTime, maskActive);
  }
  dispose() { super.dispose(); this.emissive.dispose(); this.replacements.forEach(m => m.dispose()); this.replacements.clear(); }
}

// three.js example "webgl_shadow_contact": the model's depth seen from below, blurred, on a ground plane.
// Sized to the model's footprint; redrawn only when the model changes (not per camera move).
export class ContactShadow {
  group = new THREE.Group();
  private rt = new THREE.WebGLRenderTarget(512, 512);
  private blurRT = new THREE.WebGLRenderTarget(512, 512);
  private camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  private plane: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>;
  private blurPlane: THREE.Mesh<THREE.PlaneGeometry, THREE.ShaderMaterial>;
  private depth = new THREE.MeshDepthMaterial({ side: THREE.DoubleSide });
  private hBlur = new THREE.ShaderMaterial({ ...HorizontalBlurShader, uniforms: THREE.UniformsUtils.clone(HorizontalBlurShader.uniforms), depthTest: false });
  private vBlur = new THREE.ShaderMaterial({ ...VerticalBlurShader, uniforms: THREE.UniformsUtils.clone(VerticalBlurShader.uniforms), depthTest: false });
  private darkness = { value: 1.15 };
  constructor() {
    this.rt.texture.generateMipmaps = false; this.blurRT.texture.generateMipmaps = false;
    const geometry = new THREE.PlaneGeometry(1, 1).rotateX(Math.PI / 2);
    this.plane = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ map: this.rt.texture, transparent: true, depthWrite: false, fog: false }));
    this.plane.renderOrder = 1; this.plane.name = 'contact-shadow';
    this.blurPlane = new THREE.Mesh(geometry, this.hBlur); this.blurPlane.visible = false;
    this.camera.rotation.x = Math.PI / 2; // look up at the model's underside
    this.group.add(this.plane, this.blurPlane, this.camera); this.group.visible = false;
    this.depth.onBeforeCompile = shader => {
      shader.uniforms.darkness = this.darkness;
      shader.fragmentShader = 'uniform float darkness;\n' + shader.fragmentShader.replace('gl_FragColor = vec4( vec3( 1.0 - fragCoordZ ), opacity );', 'gl_FragColor = vec4( vec3( 0.0 ), ( 1.0 - fragCoordZ ) * darkness );');
    };
    this.depth.depthTest = false; this.depth.depthWrite = false;
  }
  private slabs: THREE.Object3D[] = [];
  // A model that brings its own ground (a display slab or base plate) would shadow the whole slab: such flat, wide meshes
  // are left out of the depth view and the shadow lies on their top instead of the bounding box's bottom.
  fit(box: THREE.Box3, model?: THREE.Object3D) {
    if (box.isEmpty()) return;
    const full = box.getSize(new THREE.Vector3()), longest = Math.max(full.x, full.y, full.z), footprint = Math.max(full.x * full.z, 1e-12);
    this.slabs = []; let floorY = box.min.y;
    model?.traverse(o => { const m = o as THREE.Mesh; if (!m.isMesh) return; const b = new THREE.Box3().setFromObject(m), s = b.getSize(new THREE.Vector3());
      if (s.y < longest * .01 && s.x * s.z > footprint * .3 && b.min.y < box.min.y + longest * .02) { this.slabs.push(m); floorY = Math.max(floorY, b.max.y); } });
    box = this.slabs.length ? new THREE.Box3(new THREE.Vector3(box.min.x, floorY, box.min.z), box.max.clone()) : box;
    if (this.slabs.length) { const rest = new THREE.Box3(); model?.traverse(o => { const m = o as THREE.Mesh; if (m.isMesh && !this.slabs.includes(m)) rest.expandByObject(m); }); if (!rest.isEmpty()) box = new THREE.Box3(new THREE.Vector3(rest.min.x, floorY, rest.min.z), new THREE.Vector3(rest.max.x, box.max.y, rest.max.z)); }
    const size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3());
    const pad = Math.max(size.y * .5, Math.max(size.x, size.z) * .12), w = size.x + pad * 2, d = size.z + pad * 2;
    this.group.position.set(center.x, box.min.y + Math.max(size.y, .001) * .0004, center.z);
    this.plane.scale.set(w, -1, d); this.blurPlane.scale.set(w, 1, d);
    Object.assign(this.camera, { left: -w / 2, right: w / 2, top: d / 2, bottom: -d / 2, near: 0, far: Math.max(size.y * .35, Math.max(size.x, size.z) * .03, 1e-4) });
    this.camera.updateProjectionMatrix();
    const long = 1024, rw = w >= d ? long : Math.max(128, Math.round(long * w / d)), rh = d >= w ? long : Math.max(128, Math.round(long * d / w));
    this.rt.setSize(rw, rh); this.blurRT.setSize(rw, rh);
  }
  private blur(renderer: THREE.WebGLRenderer, amount: number) {
    this.blurPlane.visible = true;
    this.blurPlane.material = this.hBlur; this.hBlur.uniforms.tDiffuse.value = this.rt.texture; this.hBlur.uniforms.h.value = amount * 2 / this.rt.width;
    renderer.setRenderTarget(this.blurRT); renderer.render(this.blurPlane, this.camera);
    this.blurPlane.material = this.vBlur; this.vBlur.uniforms.tDiffuse.value = this.blurRT.texture; this.vBlur.uniforms.v.value = amount * 2 / this.rt.height;
    renderer.setRenderTarget(this.rt); renderer.render(this.blurPlane, this.camera);
    this.blurPlane.visible = false;
  }
  update(renderer: THREE.WebGLRenderer, scene: THREE.Scene, hide: THREE.Object3D[]) {
    hide = [...hide, ...this.slabs];
    const background = scene.background, visible = hide.map(o => o.visible), shadows = renderer.shadowMap.enabled, clear = renderer.getClearColor(new THREE.Color()), alpha = renderer.getClearAlpha(), target = renderer.getRenderTarget();
    scene.background = null; hide.forEach(o => { o.visible = false; }); this.group.visible = false; renderer.shadowMap.enabled = false;
    scene.overrideMaterial = this.depth; renderer.setClearColor(0x000000, 0);
    renderer.setRenderTarget(this.rt); renderer.clear(); renderer.render(scene, this.camera);
    scene.overrideMaterial = null;
    this.blur(renderer, 3.5); this.blur(renderer, 1.4);
    renderer.setRenderTarget(target); renderer.setClearColor(clear, alpha); renderer.shadowMap.enabled = shadows;
    scene.background = background; hide.forEach((o, i) => { o.visible = visible[i]; }); this.group.visible = true;
  }
  dispose() { this.rt.dispose(); this.blurRT.dispose(); this.plane.geometry.dispose(); this.plane.material.dispose(); this.depth.dispose(); this.hBlur.dispose(); this.vBlur.dispose(); }
}

// The plain path clears to the background colour after tone mapping; the composer tone-maps the cleared colour too.
// So the composer clears to the colour whose tone-mapped value is the requested one, and the background stays identical.
type RGB = [number, number, number];
const aces = (c: RGB, exposure: number): RGB => {
  const v = c.map(x => x * exposure / .6) as RGB;
  const i: RGB = [.59719 * v[0] + .35458 * v[1] + .04823 * v[2], .07600 * v[0] + .90834 * v[1] + .01566 * v[2], .02840 * v[0] + .13383 * v[1] + .83777 * v[2]];
  const f = i.map(x => (x * (x + .0245786) - .000090537) / (x * (.983729 * x + .4329510) + .238081)) as RGB;
  return [1.60475 * f[0] - .53108 * f[1] - .07367 * f[2], -.10208 * f[0] + 1.10813 * f[1] - .00605 * f[2], -.00327 * f[0] - .07276 * f[1] + 1.07602 * f[2]].map(x => Math.min(1, Math.max(0, x))) as RGB;
};
const neutral = (c: RGB, exposure: number): RGB => {
  let v = c.map(x => x * exposure) as RGB; const x = Math.min(...v), offset = x < .08 ? x - 6.25 * x * x : .04; v = v.map(a => a - offset) as RGB;
  const peak = Math.max(...v), start = .76; if (peak < start) return v; const d = 1 - start, np = 1 - d * d / (peak + d - start);
  v = v.map(a => a * np / peak) as RGB; const g = 1 - 1 / (.15 * (peak - np) + 1); return v.map(a => a + (np - a) * g) as RGB;
};
export function toneMapRGB(c: RGB, mapping: THREE.ToneMapping, exposure: number): RGB {
  if (mapping === THREE.ACESFilmicToneMapping) return aces(c, exposure);
  if (mapping === THREE.NeutralToneMapping) return neutral(c, exposure);
  if (mapping === THREE.LinearToneMapping) return c.map(x => Math.min(1, x * exposure)) as RGB;
  return c;
}
export function inverseToneMap(target: RGB, mapping: THREE.ToneMapping, exposure: number): RGB {
  const x: RGB = [...target];
  for (let iteration = 0; iteration < 40; iteration++) {
    const y = toneMapRGB(x, mapping, exposure), r = y.map((v, i) => v - target[i]);
    if (Math.max(...r.map(Math.abs)) < 1e-6) break;
    // Newton step with a numeric Jacobian (the ACES matrices mix channels a little).
    const J = [0, 1, 2].map(j => { const e = Math.max(1e-5, x[j] * 1e-4), p: RGB = [...x]; p[j] += e; const yp = toneMapRGB(p, mapping, exposure); return yp.map((v, i) => (v - y[i]) / e); }); // J[j][i] = dy_i/dx_j
    const m = [[J[0][0], J[1][0], J[2][0]], [J[0][1], J[1][1], J[2][1]], [J[0][2], J[1][2], J[2][2]]];
    const det = m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
    if (!Number.isFinite(det) || Math.abs(det) < 1e-12) break;
    const solve = (col: number) => { const n = m.map(row => [...row]); for (let i = 0; i < 3; i++) n[i][col] = r[i]; return (n[0][0] * (n[1][1] * n[2][2] - n[1][2] * n[2][1]) - n[0][1] * (n[1][0] * n[2][2] - n[1][2] * n[2][0]) + n[0][2] * (n[1][0] * n[2][1] - n[1][1] * n[2][0])) / det; };
    const step = [solve(0), solve(1), solve(2)];
    for (let i = 0; i < 3; i++) x[i] = Math.max(0, x[i] - step[i]);
  }
  return x;
}

export type PostRequest = { ao: boolean; bloom: boolean; aa: boolean; sample: number };
export class ViewerEffects {
  contact = new ContactShadow();
  private composer?: EffectComposer;
  private renderPass?: RenderPass; private ao?: ModelAOPass; private bloom?: EmissiveBloomPass; private accumulate?: AccumulatePass; private output?: OutputPass;
  private size = new THREE.Vector2(); private box = new THREE.Box3();
  private clearColor = { key: '', color: new THREE.Color() };
  constructor(private renderer: THREE.WebGLRenderer, private scene: THREE.Scene, private skip: () => THREE.Object3D[]) { scene.add(this.contact.group); }
  // Sizes AO and the contact shadow to the model.
  fit(box: THREE.Box3, model?: THREE.Object3D) { this.box.copy(box); this.contact.fit(box, model); if (this.ao) this.fitAO(); }
  private fitAO() {
    if (!this.ao || this.box.isEmpty()) return;
    const r = Math.max(this.box.getSize(new THREE.Vector3()).length() / 2, 1e-4), radius = r * .1;
    // Tuned on the cab (2026-10-13): 5% of the half-diagonal and scale 1 changed pixels by ~1 level; this reads as seams and recesses.
    this.ao.updateGtaoMaterial({ radius, thickness: radius * 2, distanceExponent: 1, distanceFallOff: 1, scale: 1.8, samples: 16 });
    this.ao.updatePdMaterial({ lumaPhi: 10, depthPhi: 2, normalPhi: 3, radius: 6, rings: 2, samples: 16 });
    this.ao.setSceneClipBox(this.box.clone().expandByScalar(radius * 2));
  }
  private ensure(camera: THREE.Camera) {
    if (this.composer) return;
    const { x, y } = this.renderer.getDrawingBufferSize(this.size);
    const target = new THREE.WebGLRenderTarget(x, y, { type: THREE.HalfFloatType, samples: 4 }); target.texture.name = 'viewer.post';
    this.composer = new EffectComposer(this.renderer, target); this.composer.setPixelRatio(1); this.composer.setSize(x, y);
    this.renderPass = new RenderPass(this.scene, camera);
    this.ao = new ModelAOPass(this.scene, camera, x, y); this.ao.skip = this.skip; this.fitAO();
    this.bloom = new EmissiveBloomPass(this.scene, () => this.renderPass!.camera, new THREE.Vector2(x, y)); this.bloom.skip = this.skip;
    this.accumulate = new AccumulatePass(); this.output = new OutputPass();
    for (const pass of [this.renderPass, this.ao, this.bloom, this.accumulate, this.output]) this.composer.addPass(pass);
  }
  private useCamera(camera: THREE.Camera) {
    if (this.renderPass!.camera === camera) return;
    this.renderPass!.camera = camera; this.ao!.camera = camera;
    const material = (this.ao as unknown as { gtaoMaterial: THREE.ShaderMaterial }).gtaoMaterial;
    material.defines.PERSPECTIVE_CAMERA = (camera as THREE.PerspectiveCamera).isPerspectiveCamera ? 1 : 0; material.needsUpdate = true;
  }
  // Renders one frame: the plain path when nothing is on, else the composer chain.
  render(camera: THREE.PerspectiveCamera | THREE.OrthographicCamera, request: PostRequest) {
    if (!request.ao && !request.bloom && !request.aa) { this.renderer.render(this.scene, camera); return; }
    this.ensure(camera); this.useCamera(camera);
    const { x, y } = this.renderer.getDrawingBufferSize(this.size), composer = this.composer!;
    if (composer.renderTarget1.width !== x || composer.renderTarget1.height !== y) composer.setSize(x, y);
    this.ao!.enabled = request.ao; this.bloom!.enabled = request.bloom; this.accumulate!.enabled = request.aa; this.accumulate!.index = request.sample;
    const background = this.scene.background as THREE.Color | null, original = background?.clone();
    if (background) {
      const key = background.getHexString() + this.renderer.toneMapping + this.renderer.toneMappingExposure;
      if (this.clearColor.key !== key) { this.clearColor.key = key; this.clearColor.color.setRGB(...inverseToneMap([background.r, background.g, background.b], this.renderer.toneMapping, this.renderer.toneMappingExposure), THREE.LinearSRGBColorSpace); }
      background.copy(this.clearColor.color);
    }
    const restoreLines = this.untoneLines();
    const [jx, jy] = request.aa ? JITTER[request.sample % REFINE_FRAMES] : [0, 0];
    if (jx || jy) camera.setViewOffset(x, y, jx, jy, x, y);
    try { composer.render(); } finally { restoreLines(); if (jx || jy) camera.clearViewOffset(); if (background && original) background.copy(original); }
  }
  // Helper lines (grid, part outline) use toneMapped:false, which OutputPass cannot honour per material; while the
  // composer draws, they carry inverse-tone-mapped colours so they look exactly as on the plain path.
  private lineColors = new WeakMap<object, { key: string; value: THREE.Color | Float32Array }>();
  private untoneLines() {
    const key = `${this.renderer.toneMapping}:${this.renderer.toneMappingExposure}`, undo: (() => void)[] = [];
    const inverse = (r: number, g: number, b: number) => inverseToneMap([r, g, b], this.renderer.toneMapping, this.renderer.toneMappingExposure);
    this.scene.traverseVisible(o => {
      const line = o as THREE.LineSegments; if (!line.isLine) return; const material = line.material as THREE.LineBasicMaterial;
      if (Array.isArray(material) || material.toneMapped !== false) return;
      const colors = line.geometry.getAttribute('color') as THREE.BufferAttribute | undefined;
      if (material.vertexColors && colors) {
        let cached = this.lineColors.get(colors); if (!cached || cached.key !== key) { const a = new Float32Array(colors.array as ArrayLike<number>), memo = new Map<string, number[]>(); for (let i = 0; i < a.length; i += 3) { const k = `${a[i]},${a[i + 1]},${a[i + 2]}`; let v = memo.get(k); if (!v) memo.set(k, v = inverse(a[i], a[i + 1], a[i + 2])); a.set(v, i); } cached = { key, value: a }; this.lineColors.set(colors, cached); }
        const original = colors.array; colors.array = cached.value as Float32Array; colors.needsUpdate = true; undo.push(() => { colors.array = original; colors.needsUpdate = true; });
      } else {
        let cached = this.lineColors.get(material); if (!cached || cached.key !== key) { cached = { key, value: new THREE.Color().setRGB(...inverse(material.color.r, material.color.g, material.color.b), THREE.LinearSRGBColorSpace) }; this.lineColors.set(material, cached); }
        const original = material.color.clone(); material.color.copy(cached.value as THREE.Color); undo.push(() => material.color.copy(original));
      }
    });
    return () => undo.forEach(f => f());
  }
  dispose() {
    this.contact.dispose(); this.scene.remove(this.contact.group);
    this.ao?.dispose(); this.bloom?.dispose(); this.accumulate?.dispose(); this.output?.dispose(); this.composer?.dispose();
  }
}
