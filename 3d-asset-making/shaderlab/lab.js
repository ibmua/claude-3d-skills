// Shader Lab page: loads a spec (?spec=URL), builds the scene (GLB and/or primitives), attaches surface programs by
// material name (surface.js), and either runs interactively (orbit, time, live uniforms, GLSL reload) or is driven
// headless by lab.mjs through window.lab (renderFrame(view, t) -> PNG data URL). Spec format: README.md.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { attachByName, uniformValue, bakeSurfaceUV, checkFinite } from './surface.js';

const q = new URLSearchParams(location.search);
const specUrl = q.get('spec');
const headless = q.has('headless');
const errors = [];
const lab = (window.lab = { ready: false, errors, info: {} });
const $ = (id) => document.getElementById(id);
const fail = (m) => { errors.push(String(m)); $('err').textContent = errors.join('\n\n'); };

// The game's renderer and light, copied from the game src/world/Environment.js (createRenderer, Environment):
// NeutralToneMapping, exposure 1, RoomEnvironment at 0.45, hemisphere 0xc4d6ee/0x9f8f70 1.25, sun 0xffdcae 2.7 from
// bearing 250 deg elevation 30 deg, haze 0xe6dccb. Re-check them there when the game's look changes.
const LOOKS = {
  game: { tone: THREE.NeutralToneMapping, env: 0.45, bg: 0xe6dccb, hemi: [0xc4d6ee, 0x9f8f70, 1.25], sun: [0xffdcae, 2.7] },
  dark: { tone: THREE.NeutralToneMapping, env: 0.04, bg: 0x0b0c10, hemi: [0x334455, 0x111111, 0.15], sun: null },
  studio: { tone: THREE.ACESFilmicToneMapping, env: 1.0, bg: 0x2a2d33, hemi: [0xffffff, 0x444444, 0.4], sun: [0xffffff, 1.5] },
};
const SUN_DIR = (() => { const b = THREE.MathUtils.degToRad(250), e = THREE.MathUtils.degToRad(30); return new THREE.Vector3(Math.sin(b) * Math.cos(e), Math.sin(e), -Math.cos(b) * Math.cos(e)).normalize(); })();

const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFShadowMap;
renderer.debug.onShaderError = (gl, program, vs, fs) => {
  const log = [gl.getProgramInfoLog(program), gl.getShaderInfoLog(fs), gl.getShaderInfoLog(vs)].filter(Boolean).join('\n');
  const src = gl.getShaderSource(fs) || '';
  const m = /ERROR: \d+:(\d+)/.exec(log);
  let ctx = '';
  if (m) { const L = src.split('\n'), n = +m[1]; ctx = L.slice(Math.max(0, n - 4), n + 2).map((l, i) => `${Math.max(1, n - 3) + i}: ${l}`).join('\n'); }
  fail('GLSL error:\n' + log.trim() + (ctx ? '\n---\n' + ctx : ''));
};
$('view').appendChild(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 500);
const controls = headless ? null : new OrbitControls(camera, renderer.domElement);
const hemi = new THREE.HemisphereLight();
const sun = new THREE.DirectionalLight();
sun.castShadow = true; sun.shadow.mapSize.setScalar(2048); sun.shadow.bias = -0.0005; sun.shadow.normalBias = 0.02;
scene.add(hemi, sun, sun.target);
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

let spec, root, box = new THREE.Box3(), programs = {}, mats = [], composer = null, bloomPass = null;
let lookName = 'game', bloomOn = false, playing = !headless, t = 0, views = [], activeView = null;

function applyLook(name) {
  const L = LOOKS[name] || LOOKS.game; lookName = name;
  renderer.toneMapping = L.tone; renderer.toneMappingExposure = spec.exposure ?? 1;
  scene.environmentIntensity = L.env; scene.background = new THREE.Color(spec.background ?? L.bg);
  hemi.color.set(L.hemi[0]); hemi.groundColor.set(L.hemi[1]); hemi.intensity = L.hemi[2];
  sun.visible = !!L.sun; if (L.sun) { sun.color.set(L.sun[0]); sun.intensity = L.sun[1]; }
  const c = box.getCenter(new THREE.Vector3()), r = Math.max(box.getSize(new THREE.Vector3()).length(), 0.1);
  sun.target.position.copy(c); sun.position.copy(c).addScaledVector(SUN_DIR, r * 4);
  Object.assign(sun.shadow.camera, { left: -r, right: r, top: r, bottom: -r, near: 0.01, far: r * 10 }); sun.shadow.camera.updateProjectionMatrix();
  $('look').textContent = { game: '🎮 game look', dark: '🌙 dark room', studio: '💡 studio' }[name];
}

function primitive(p) {
  const s = p.size || [1, 1, 1];
  const geo = { box: () => new THREE.BoxGeometry(...s), plane: () => new THREE.PlaneGeometry(s[0], s[1]),
    cylinder: () => new THREE.CylinderGeometry(s[0], s[0], s[1], 48), sphere: () => new THREE.SphereGeometry(s[0], 48, 24) }[p.shape];
  if (!geo) throw new Error(`primitive shape "${p.shape}": box | plane | cylinder | sphere`);
  const mat = new THREE.MeshStandardMaterial({ name: p.material || 'default', color: p.color || '#888888', roughness: p.roughness ?? 0.5, metalness: p.metalness ?? 0 });
  const m = new THREE.Mesh(geo(), mat);
  m.position.fromArray(p.position || [0, 0, 0]);
  if (p.rotation) m.rotation.set(...p.rotation.map(THREE.MathUtils.degToRad));
  m.castShadow = m.receiveShadow = true;
  return m;
}

async function loadPrograms() {
  programs = {};
  for (const [name, p] of Object.entries(spec.programs || {})) {
    const url = new URL(p.glsl, specUrl.startsWith('http') ? specUrl : location.origin + specUrl).href;
    const r = await fetch(url + '?v=' + Date.now());
    if (!r.ok) { fail(`program "${name}": ${p.glsl} -> HTTP ${r.status}`); continue; }
    programs[name] = { ...p, glsl: await r.text() };
  }
}

function attach() {
  const prev = Object.fromEntries(mats.flatMap((m) => Object.entries(m.userData.surface.uniforms).map(([k, v]) => [k, v.value])));
  const res = attachByName(root, programs);
  if (res.missing.length) fail('materials not found in the scene: ' + res.missing.join(', '));
  mats = res.materials;
  for (const m of mats) for (const [k, v] of Object.entries(m.userData.surface.uniforms)) if (k !== 'uTime' && k in prev) v.value = prev[k];
}

function setupViews() {
  const c = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3()), r = size.length() / 2 || 1;
  const auto = [{ name: 'front', dir: [0, 0.05, 1] }, { name: 'three-quarter', dir: [0.7, 0.3, 0.8] }];
  views = (spec.views && spec.views.length ? spec.views : auto).map((v) => {
    const fov = v.fov ?? v.game?.fov ?? 35;
    let pos, target = v.target ? new THREE.Vector3(...v.target) : c.clone();
    if (v.position) pos = new THREE.Vector3(...v.position);
    else {
      const d = v.game ? v.game.distance : (r / Math.sin(THREE.MathUtils.degToRad(fov) / 2)) * (v.margin ?? 1.15);
      pos = target.clone().addScaledVector(new THREE.Vector3(...(v.dir || v.game?.dir || [0, 0.05, 1])).normalize(), d);
    }
    return { ...v, fov, pos, target };
  });
  $('views').innerHTML = '';
  for (const v of views) { const b = document.createElement('button'); b.textContent = v.name; b.onclick = () => useView(v); $('views').appendChild(b); }
  useView(views[0]);
}

function useView(v) {
  activeView = v; camera.fov = v.fov; camera.position.copy(v.pos); camera.near = Math.max(0.005, v.pos.distanceTo(v.target) / 200);
  camera.far = v.pos.distanceTo(v.target) * 20; camera.lookAt(v.target); camera.updateProjectionMatrix();
  if (controls) { controls.target.copy(v.target); controls.update(); }
  [...$('views').children].forEach((b) => b.classList.toggle('on', b.textContent === v.name));
}

function buildBloom(w, h) {
  const B = spec.bloom || {};
  composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  bloomPass = new UnrealBloomPass(new THREE.Vector2(w, h), B.strength ?? 0.6, B.radius ?? 0.4, B.threshold ?? 1.0);
  composer.addPass(bloomPass); composer.addPass(new OutputPass());
  composer.setSize(w, h);
}

function draw() {
  for (const m of mats) m.userData.surface.uniforms.uTime.value = t;
  if (bloomOn) { if (!composer) buildBloom(renderer.domElement.width, renderer.domElement.height); composer.render(); }
  else renderer.render(scene, camera);
}

function setSize(w, h) {
  renderer.setPixelRatio(headless ? 1 : Math.min(devicePixelRatio, 2));
  renderer.setSize(w, h, !headless); camera.aspect = w / h; camera.updateProjectionMatrix();
  if (composer) { composer.setSize(w, h); bloomPass.resolution.set(w, h); }
}

// Headless: one frame of a view at time t. A "game" view is rendered as the phone sees it (portrait frame of
// game.heightPx, game.fov at game.distance) and cropped to the object, then enlarged by game.zoom with no smoothing,
// so the picture shows the real pixel count the player gets.
lab.renderFrame = (viewName, time, w, h, opts = {}) => {
  const v = views.find((x) => x.name === viewName); if (!v) throw new Error('no view ' + viewName);
  bloomOn = opts.bloom ?? !!spec.bloom; if (opts.look) applyLook(opts.look);
  useView(v); t = time;
  if (!v.game) { setSize(w, h); draw(); return renderer.domElement.toDataURL('image/png'); }
  const H = v.game.heightPx || 1688, W = Math.round(H * (v.game.aspect ?? 0.46));
  setSize(W, H); draw();
  const pts = [], b = box;
  for (const x of [b.min.x, b.max.x]) for (const y of [b.min.y, b.max.y]) for (const z of [b.min.z, b.max.z]) pts.push(new THREE.Vector3(x, y, z).project(camera));
  const xs = pts.map((p) => (p.x + 1) / 2 * W), ys = pts.map((p) => (1 - p.y) / 2 * H), pad = 6;
  const x0 = Math.max(0, Math.floor(Math.min(...xs)) - pad), y0 = Math.max(0, Math.floor(Math.min(...ys)) - pad);
  const cw = Math.min(W, Math.ceil(Math.max(...xs)) + pad) - x0, ch = Math.min(H, Math.ceil(Math.max(...ys)) + pad) - y0;
  const z = v.game.zoom ?? 4, out = document.createElement('canvas'); out.width = cw * z; out.height = ch * z;
  const g = out.getContext('2d'); g.imageSmoothingEnabled = false; g.drawImage(renderer.domElement, x0, y0, cw, ch, 0, 0, cw * z, ch * z);
  lab.info.gamePx = { ...(lab.info.gamePx || {}), [viewName]: [cw, ch] };
  return out.toDataURL('image/png');
};

// Headless: the fallback texture of one program (surface.js bakeSurfaceUV) as a PNG data URL in glTF's orientation.
lab.bakeFallback = (name, time, size = 512) => {
  const p = programs[name]; if (!p) throw new Error('no program ' + name);
  const m = mats.find((x) => x.name === name); if (!m) throw new Error('no material ' + name + ' in the scene');
  const r = bakeSurfaceUV(renderer, m, p.glsl, p.uniforms || {}, { t: time, size, unlit: !!p.unlit });
  const cv = document.createElement('canvas'); cv.width = cv.height = size; const g = cv.getContext('2d'), img = g.createImageData(size, size);
  img.data.set(r.data);   // no flip: glTF puts texture row 0 (the PNG's top) at uv.y = 0, which is what the program saw there
  g.putImageData(img, 0, 0);
  return { png: cv.toDataURL('image/png'), scale: r.scale, mode: r.mode };
};

// Headless: times over the loop at which a program's raw output is NaN/Inf (surface.js checkFinite); [] when clean.
lab.checkFinite = (name, seconds, n = 64) => {
  const p = programs[name]; if (!p) throw new Error('no program ' + name);
  const m = mats.find((x) => x.name === name); if (!m) throw new Error('no material ' + name + ' in the scene');
  return checkFinite(renderer, m, p.glsl, p.uniforms || {}, { seconds, n, unlit: !!p.unlit });
};

function uniformsUI() {
  const box_ = $('uniforms'); box_.innerHTML = '';
  for (const m of mats) for (const [k, u] of Object.entries(m.userData.surface.uniforms)) {
    if (k === 'uTime') continue;
    const range = (spec.programs[m.name].ranges || {})[k];
    const add = (label, get, set, lo, hi) => {
      const l = document.createElement('label'); l.textContent = `${m.name}.${label} = ${(+get()).toFixed(3)}`;
      const s = document.createElement('input'); Object.assign(s, { type: 'range', min: lo, max: hi, step: (hi - lo) / 500, value: get() });
      s.oninput = () => { set(+s.value); l.textContent = `${m.name}.${label} = ${(+s.value).toFixed(3)}`; if (!playing) draw(); };
      box_.append(l, s);
    };
    if (typeof u.value === 'number') { const v0 = u.value; add(k, () => u.value, (x) => (u.value = x), range?.[0] ?? Math.min(0, v0 * 2), range?.[1] ?? (Math.max(1, Math.abs(v0) * 3))); }
    else if (u.value.isColor) { const c = document.createElement('input'); c.type = 'color'; c.value = '#' + u.value.getHexString(); c.oninput = () => u.value.set(c.value); const l = document.createElement('label'); l.textContent = `${m.name}.${k}`; box_.append(l, c); }
    else for (const ax of ['x', 'y', 'z', 'w']) if (ax in u.value) add(`${k}.${ax}`, () => u.value[ax], (x) => (u.value[ax] = x), range?.[0] ?? -2, range?.[1] ?? 2);
  }
}

function copyUniforms() {
  const out = {};
  for (const m of mats) { out[m.name] = {}; for (const [k, u] of Object.entries(m.userData.surface.uniforms)) if (k !== 'uTime') out[m.name][k] = typeof u.value === 'number' ? +u.value.toFixed(4) : u.value.isColor ? '#' + u.value.getHexString() : u.value.toArray().map((x) => +x.toFixed(4)); }
  navigator.clipboard?.writeText(JSON.stringify(out, null, 1)); $('err').textContent = JSON.stringify(out, null, 1);
}

async function main() {
  if (!specUrl) throw new Error('no ?spec=');
  spec = await (await fetch(specUrl + '?v=' + Date.now())).json();
  $('title').textContent = spec.title || 'Shader Lab';
  root = new THREE.Group(); scene.add(root);
  if (spec.model) {
    const url = new URL(spec.model, location.origin + specUrl).href;
    const gltf = await new GLTFLoader().loadAsync(url);
    gltf.scene.traverse((o) => { if (o.isMesh) o.castShadow = o.receiveShadow = true; });
    root.add(gltf.scene);
  }
  for (const p of spec.primitives || []) root.add(primitive(p));
  for (const L of spec.lights || []) {
    const l = L.type === 'spot' ? new THREE.SpotLight(L.color, L.intensity, L.distance || 0, THREE.MathUtils.degToRad(L.angle ?? 40), 0.5) : new THREE.PointLight(L.color, L.intensity, L.distance || 0);
    l.position.fromArray(L.position); if (L.target) { l.target.position.fromArray(L.target); scene.add(l.target); } scene.add(l);
  }
  root.updateMatrixWorld(true); box.setFromObject(root);
  if (spec.context === 'floor' || spec.context === 'room') {
    const s = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3()), R = Math.max(s.x, s.z, s.y) * 4;
    const mk = (geo, pos, rot) => { const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: spec.contextColor || '#8a8478', roughness: 0.85 })); m.position.copy(pos); m.rotation.set(...rot); m.receiveShadow = true; scene.add(m); };
    mk(new THREE.PlaneGeometry(R, R), new THREE.Vector3(c.x, box.min.y, c.z), [-Math.PI / 2, 0, 0]);
    if (spec.context === 'room') mk(new THREE.PlaneGeometry(R, R), new THREE.Vector3(c.x, box.min.y + R / 2, box.min.z - (spec.wallGap ?? 0.15)), [0, 0, 0]);
  }
  await loadPrograms(); attach();
  applyLook(spec.look || 'game'); bloomOn = !!spec.bloom; $('bloom').classList.toggle('on', bloomOn);
  setupViews();
  lab.info = { triangles: 0, materials: [], box: [box.min.toArray(), box.max.toArray()] };
  root.traverse((o) => { if (o.isMesh) { lab.info.triangles += (o.geometry.index ? o.geometry.index.count : o.geometry.attributes.position.count) / 3; [].concat(o.material).forEach((m) => lab.info.materials.includes(m.name) || lab.info.materials.push(m.name)); } });
  lab.views = views.map((v) => v.name); lab.programs = programs;
  // compile now so GLSL errors surface before the first frame is asked for
  setSize(64, 64); draw();
  if (headless) { lab.ready = true; return; }
  const resize = () => { const r = $('view').getBoundingClientRect(); setSize(r.width, r.height); };
  addEventListener('resize', resize); resize();
  uniformsUI();
  const T = spec.clip?.seconds || 4;
  $('play').onclick = () => { playing = !playing; $('play').textContent = playing ? '⏸' : '▶'; };
  $('time').oninput = () => { t = +$('time').value * T; playing = false; $('play').textContent = '▶'; draw(); };
  $('bloom').onclick = () => { bloomOn = !bloomOn; $('bloom').classList.toggle('on', bloomOn); };
  $('look').onclick = () => applyLook({ game: 'dark', dark: 'studio', studio: 'game' }[lookName]);
  const reload = async () => { errors.length = 0; $('err').textContent = ''; await loadPrograms(); attach(); uniformsUI(); };
  $('reload').onclick = reload; addEventListener('focus', reload);
  $('copy').onclick = copyUniforms;
  let last = performance.now(), frames = 0, acc = 0;
  renderer.setAnimationLoop((now) => {
    const dt = (now - last) / 1000; last = now;
    if (playing) { t += dt; $('time').value = (t % T) / T; }
    controls.update(); draw();
    frames++; acc += dt; if (acc > 0.5) { $('hud').textContent = `${(frames / acc).toFixed(0)} fps · t ${t.toFixed(2)} s · ${renderer.info.render.calls} calls · ${lab.info.triangles | 0} tris`; frames = 0; acc = 0; }
  });
  lab.ready = true;
}
main().catch((e) => { fail(e.stack || e); lab.ready = true; lab.fatal = String(e); });
