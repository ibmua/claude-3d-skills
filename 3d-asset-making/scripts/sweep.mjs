#!/usr/bin/env node
/**
 * sweep.mjs: blink (z-fighting) and slit check of a GLB in the game's own renderer (three.js of the game, headless
 * Chromium on the GPU). Owner 2026-10-12: tools prepared once so asset workers stop improvising them each session.
 *
 *   node sweep.mjs <file.glb> <out dir> [--dist 12,30,60,100] [--elev 15,35] [--step 2] [--near 0.5] [--far 6000]
 *                  [--fov 40] [--size 960] [--frames 10|all|marked|none] [--fault 40] [--flip 32]
 *                  [--method jitter|turn] [--gpu on|off] [--three DIR]
 *   node sweep.mjs --selftest <out dir> [--step 10]   calibration on synthetic GLBs: overlapping coplanar panels
 *                  0.5 mm apart must FAULT, 10 mm apart must PASS, a 6 mm slit between two panels must show slit px
 *
 * The camera circles the model's bounding-box centre at each distance (m) and elevation (deg) in --step degree steps
 * (defaults: 4 x 2 rings x 180 = 1440 views, about 4 min on the build box's 3090). The near LOD is drawn up to ~100 m in the game
 * (assets-lib/lod.js), and z-fighting grows with distance squared, so the far rings matter most.
 *
 * BLINK, method jitter (default): frame A, then 4 more frames from the same camera with the near plane moved by
 * 0.75, 1.5, 2.25, 3 depth-buffer steps at that distance. Screen positions do not depend on near, so edges, texture and
 * shadows stay exactly put; a pixel whose colour changes (max RGB channel >= --flip 32 of 255) is one where two
 * surfaces are so close that the depth test's rounding picks the winner: exactly what blinks when the game camera moves.
 * Method turn (the first brief's design, kept for comparison): frame B turned 0.15 deg more; a pixel blinks when its
 * colour flips, the surface seen there changes (uv / mesh / normal) and no geometric edge (normal+depth pass) is within
 * 2 px in A or B. Measured 2026-10-12 on the self-test: turn flags the sliding OUTLINES of coplanar decals (10 mm gap:
 * 34 px at 30 m, close to the threshold) and misses the 0.5 mm interior, which does not fight below ~60 m with near 0.5.
 * Lone blink pixels (no blink neighbour) are dropped from `blink` (kept in `blink_raw`). FAULT: worst view >= --fault px.
 *
 * SLIT: sky seen through a crack at most ~1.5 px wide between surfaces that continue each other (depth within
 * max(3 cm, 0.4 % of the distance), normals within ~35 deg; other thin gaps are counted as `gaps`, unmarked) (coverage pass at
 * 2x size with 4x MSAA, so sub-pixel cracks count): light through cracks. Reported (cyan), not a FAULT: look at them.
 * Noise floor ~0-2 px per view (self-test panels); a car near shows 18-58 px, mostly sky through its bogie wells.
 *
 * Calibration (the build box, 2026-10-12, step 10): gap 0.5 mm: 0 px at 12 and 30 m, 620 px worst at 60 m, 532 at 100 m (FAULT);
 * gap 10 mm: 0 px at every distance to 150 m (PASS); slit 6 mm: 155 px at 12 m, 62 at 30 m, 0 from 60 m (sub-sample).
 * Real near LODs (defaults): a car-cab-a-near FAULT 45 px (coupler, x=-4.5 end, 12 m); a car-cab-a-near FAULT 18 400 px
 * at 12 m, 1 772 at 30 m, 111 at 100 m (the gangway end wall, x=-4.3..-4.5), visible to the eye as a speckled band.
 * Depth precision: a 24-bit step at distance d is d^2 / (near * 2^24): 0.1 mm at 30 m, 0.4 mm at 60 m, 1.2 mm at 100 m.
 * So keep stacked surfaces >= 5 mm apart (better: cut the hidden one away).
 *
 * Renderer like the game (src/world/Environment.js + Game.js): three r186 from vendor/three,
 * WebGLRenderer antialias, sRGB output, NeutralToneMapping exposure 1, PCF sun shadows 2048 (bias -0.0005, normal bias
 * 0.06, the game's shadow box for the view distance), sun 0xffdcae 2.7 from bearing 250 / elevation 30, hemisphere
 * 0xc4d6ee/0x9f8f70 1.25, RoomEnvironment at 0.45, haze background 0xe6dccb, no fog; PerspectiveCamera(fov 40, 16:9,
 * near 0.5, far 6000) like Game.js. Not applied: the game's own train shaders (assets-lib/materials): the GLB's
 * materials are drawn; phones held upright widen the fov (Game.js), which this does not model.
 *
 * Output in <out dir>: frames/<ring>_azNNN.png (frame A every --frames degrees; `all` = every view), marked/<same>.png
 * (every view with marks: blink red, slit cyan), SWEEP.jpg (contact sheet: worst blink and slit views marked, per-ring
 * charts of blink and slit pixels by azimuth, a ring of views every 30 deg), sweep.json ({views:[{dist,elev,az,blink,
 * blink_raw,slit}], worst_blink, worst_slit, totals, result}). Prints a summary; last line  RESULT: PASS|FAULT ...;
 * exit 0 PASS, 1 FAULT, 2 usage, 3 error.
 *
 * Finds playwright via $PLAYWRIGHT_PATH, else the known installs on the build box/PC; Chromium via $CHROME_PATH, else the newest
 * ~/.cache/ms-playwright headless shell, else /usr/bin/google-chrome. --gpu on (default) = ANGLE/Vulkan on the NVIDIA
 * card; off = SwiftShader (slower; its depth rounding may differ from a phone GPU).
 */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const HELP = fs.readFileSync(new URL(import.meta.url)).toString().split('/**')[1].split('*/')[0].replace(/^ \* ?/gm, '');
const argv = process.argv.slice(2);
if (!argv.length || argv.includes('-h') || argv.includes('--help')) { console.log(HELP); process.exit(argv.length ? 0 : 2); }

// ---------- options ----------
const opt = { dist: '12,30,60,100', elev: '15,35', step: '2', near: '0.5', far: '6000', fov: '40', size: '960', frames: '10', fault: '40', gpu: 'on', three: '', method: 'jitter', flip: '32' };
const pos = [];
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === '--selftest') { opt.selftest = true; continue; }
  if (a.startsWith('--')) { const k = a.slice(2); if (!(k in opt)) { console.error(`unknown option ${a}`); process.exit(2); } opt[k] = argv[++i]; continue; }
  pos.push(a);
}

function firstExisting(list) { return list.find((p) => p && fs.existsSync(p)); }
function findPlaywright() {
  const c = [process.env.PLAYWRIGHT_PATH, path.join(os.homedir(), 'node_modules/playwright')];
  for (const p of c) { if (!p) continue; try { return require(p); } catch {} }
  try { return require('playwright'); } catch {}
  throw new Error('playwright not found: set PLAYWRIGHT_PATH to a node_modules/playwright folder');
}
function findChrome() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const root = path.join(os.homedir(), '.cache/ms-playwright');
  const found = [];
  try {
    for (const d of fs.readdirSync(root)) {
      const m = d.match(/^chromium(_headless_shell)?-(\d+)$/); if (!m) continue;
      for (const sub of ['chrome-headless-shell-linux64/chrome-headless-shell', 'chrome-linux64/chrome', 'chrome-linux/chrome']) {
        const p = path.join(root, d, sub); if (fs.existsSync(p)) found.push([Number(m[2]) + (m[1] ? 0.5 : 0), p]);
      }
    }
  } catch {}
  found.sort((a, b) => b[0] - a[0]);
  return found[0]?.[1] ?? firstExisting(['/usr/bin/google-chrome', '/usr/bin/chromium']);
}
function findThree() {
  const d = firstExisting([opt.three, process.env.THREE_DIR, process.env.GAME_DIR && process.env.GAME_DIR + '/vendor/three', null]);
  if (!d || !fs.existsSync(path.join(d, 'three.module.js'))) throw new Error('three.js of the game not found: pass --three <dir with three.module.js>');
  return d;
}

// ---------- the page ----------
const HTML = `<!doctype html><html><head><meta charset="utf-8"><style>body{margin:0;background:#222}</style>
<script type="importmap">{"imports":{"three":"/three/three.module.js","three/addons/":"/three/addons/"}}</script></head>
<body><script type="module">
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
const HAZE = new THREE.Color(0xe6dccb);
const S = {};
const AUXV = 'varying vec3 vN; varying float vD; varying vec2 vUv; void main(){ vec4 mv = modelViewMatrix*vec4(position,1.0); vN = normalize(normalMatrix*normal); vD = -mv.z; vUv = uv; gl_Position = projectionMatrix*mv; }';
const NF = 'varying vec3 vN; varying float vD; varying vec2 vUv; void main(){ vec3 n = normalize(vN) * (gl_FrontFacing ? 1.0 : -1.0); gl_FragColor = vec4(n, vD); }';
const UF = 'uniform float id; varying vec3 vN; varying float vD; varying vec2 vUv; void main(){ gl_FragColor = vec4(vUv, id, 1.0); }';
window.setup = async (o) => {
  Object.assign(S, o);
  const canvas = document.createElement('canvas'); document.body.appendChild(canvas);
  const r = S.r = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
  r.setPixelRatio(1); r.setSize(o.W, o.H, false);
  r.outputColorSpace = THREE.SRGBColorSpace; r.toneMapping = THREE.NeutralToneMapping; r.toneMappingExposure = 1.0;
  r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFShadowMap;
  const scene = S.scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(r);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture; scene.environmentIntensity = 0.45; pmrem.dispose();
  scene.add(new THREE.HemisphereLight(0xc4d6ee, 0x9f8f70, 1.25));
  const b = 250 * Math.PI / 180, e = 30 * Math.PI / 180;
  S.sunDir = new THREE.Vector3(Math.sin(b) * Math.cos(e), Math.sin(e), -Math.cos(b) * Math.cos(e)).normalize();
  const sun = S.sun = new THREE.DirectionalLight(0xffdcae, 2.7);
  sun.castShadow = true; sun.shadow.mapSize.setScalar(2048); sun.shadow.bias = -0.0005; sun.shadow.normalBias = 0.06;
  sun.shadow.camera.near = 1; sun.shadow.camera.far = 1600; scene.add(sun, sun.target);
  const gltf = await new GLTFLoader().loadAsync('/model.glb');
  const model = gltf.scene; scene.add(model); model.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(model); S.center = box.getCenter(new THREE.Vector3());
  S.meshes = []; let tris = 0;
  model.traverse((m) => {
    if (!m.isMesh) return;
    m.castShadow = m.receiveShadow = true;
    const side = Array.isArray(m.material) ? m.material[0].side : m.material.side;
    const id = S.meshes.length + 1;
    S.meshes.push({ m, orig: m.material,
      n: new THREE.ShaderMaterial({ vertexShader: AUXV, fragmentShader: NF, side }),
      u: new THREE.ShaderMaterial({ vertexShader: AUXV, fragmentShader: UF, side, uniforms: { id: { value: id } } }),
      c: new THREE.MeshBasicMaterial({ color: 0x000000, side }) });
    const g = m.geometry; tris += (g.index ? g.index.count : g.attributes.position.count) / 3;
  });
  S.cam = new THREE.PerspectiveCamera(o.fov, o.W / o.H, o.near, o.far);
  const fl = { type: THREE.FloatType, format: THREE.RGBAFormat, minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, depthBuffer: true, samples: 0 };
  S.rtN = new THREE.WebGLRenderTarget(o.W, o.H, fl); S.rtU = new THREE.WebGLRenderTarget(o.W, o.H, fl);
  S.ss = 2; S.rtC = new THREE.WebGLRenderTarget(o.W * S.ss, o.H * S.ss, { minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, samples: 4 });
  S.thumbs = []; S.gl = r.getContext();
  const dbg = S.gl.getExtension('WEBGL_debug_renderer_info');
  return { renderer: S.gl.getParameter(dbg ? dbg.UNMASKED_RENDERER_WEBGL : S.gl.RENDERER), depthBits: S.gl.getParameter(S.gl.DEPTH_BITS),
    tris: Math.round(tris), meshes: S.meshes.length, size: box.getSize(new THREE.Vector3()).toArray().map((v) => +v.toFixed(3)),
    center: S.center.toArray().map((v) => +v.toFixed(3)) };
};
function place(az, el, dist) {
  const a = az * Math.PI / 180, e = el * Math.PI / 180, c = S.center;
  S.cam.position.set(c.x + dist * Math.cos(e) * Math.sin(a), c.y + dist * Math.sin(e), c.z + dist * Math.cos(e) * Math.cos(a));
  S.cam.lookAt(c); S.cam.updateMatrixWorld();
}
function setMats(k) { for (const x of S.meshes) x.m.material = k === 'orig' ? x.orig : x[k]; }
function color() {
  setMats('orig'); S.scene.background = HAZE; S.r.shadowMap.autoUpdate = true; S.r.setRenderTarget(null); S.r.render(S.scene, S.cam);
  const gl = S.gl, px = new Uint8Array(S.W * S.H * 4); gl.readPixels(0, 0, S.W, S.H, gl.RGBA, gl.UNSIGNED_BYTE, px); return px;
}
function aux(k, rt) {
  setMats(k); S.scene.background = null; S.r.shadowMap.autoUpdate = false; S.r.setClearColor(0x000000, 0);
  S.r.setRenderTarget(rt); S.r.clear(); S.r.render(S.scene, S.cam); S.r.setRenderTarget(null);
  const px = k === 'c' ? new Uint8Array(rt.width * rt.height * 4) : new Float32Array(rt.width * rt.height * 4);
  S.r.readRenderTargetPixels(rt, 0, 0, rt.width, rt.height, px); return px;
}
function cover() {
  setMats('c'); S.scene.background = new THREE.Color(0xffffff); S.r.shadowMap.autoUpdate = false;
  S.r.setRenderTarget(S.rtC); S.r.clear(); S.r.render(S.scene, S.cam); S.r.setRenderTarget(null);
  const px = new Uint8Array(S.rtC.width * S.rtC.height * 4); S.r.readRenderTargetPixels(S.rtC, 0, 0, S.rtC.width, S.rtC.height, px); return px;
}
// geometric edges of a normal+depth buffer, dilated by R px: silhouettes, creases (normal turn > ~25 deg) and depth
// steps (second difference of 1/depth, which is affine across any plane in screen space)
function edges(N, R) {
  const W = S.W, H = S.H, e = new Uint8Array(W * H), K = S.kLap;
  const fg = (i) => N[i * 4 + 3] > 0;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const i = y * W + x; let ed = 0;
    for (const [dx, dy] of [[1, 0], [0, 1]]) {
      const x2 = x + dx, y2 = y + dy; if (x2 >= W || y2 >= H) continue;
      const j = y2 * W + x2;
      if (fg(i) !== fg(j)) { ed = 1; break; }
      if (!fg(i)) continue;
      const dot = N[i*4]*N[j*4] + N[i*4+1]*N[j*4+1] + N[i*4+2]*N[j*4+2];
      if (dot < 0.9) { ed = 1; break; }
      const x0 = x - dx, y0 = y - dy; if (x0 < 0 || y0 < 0) continue;
      const h = y0 * W + x0; if (!fg(h)) { ed = 1; break; }
      const a = 1 / N[h*4+3], c = 1 / N[i*4+3], d = 1 / N[j*4+3];
      if (Math.abs(a + d - 2 * c) > K * c) { ed = 1; break; }
    }
    e[i] = ed;
  }
  // dilate: separable max filter
  const t = new Uint8Array(W * H), out = new Uint8Array(W * H);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { let m = 0; for (let k = -R; k <= R && !m; k++) { const xx = x + k; if (xx >= 0 && xx < W) m = e[y * W + xx]; } t[y * W + x] = m; }
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { let m = 0; for (let k = -R; k <= R && !m; k++) { const yy = y + k; if (yy >= 0 && yy < H) m = t[yy * W + x]; } out[y * W + x] = m; }
  return out;
}
function slits(C, N, dist) {
  // C: black geometry on white sky, 4x MSAA at 2x size, so a gap thinner than a sample row still shows as lighter.
  // A sky pixel with solid geometry within R hi-res px on both sides along one of 4 directions is a thin gap; it is a
  // SLIT (a crack) when the surfaces on the two sides continue each other: depth within max(3 cm, 0.4 % of the view
  // distance) and normals within ~35 deg (from the base-size normal+depth pass N). Other thin gaps (between a wheel and
  // a frame, a handrail and the wall) are counted as "gaps" and not marked.
  const ss = S.ss, W = S.W * ss, H = S.H * ss, R = 3, BW = S.W, BH = S.H, mark = new Uint8Array(BW * BH), tol = Math.max(0.03, 0.004 * dist);
  const geo = (x, y) => x >= 0 && y >= 0 && x < W && y < H && C[(y * W + x) * 4] < 20;
  const surf = (x, y, dx, dy) => {                       // the base-size surface sample at a hi-res point, stepping outward to find geometry
    for (let k = 0; k < 3; k++) {
      const bx = Math.floor((x + dx * k * ss) / ss), by = Math.floor((y + dy * k * ss) / ss);
      if (bx < 0 || by < 0 || bx >= BW || by >= BH) return null;
      const i = (by * BW + bx) * 4; if (N[i + 3] > 0) return i;
    }
    return null;
  };
  let n = 0, gaps = 0;
  for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) {
    if (C[(y * W + x) * 4] < 64) continue;
    let thin = false, crack = false;
    for (const [dx, dy] of [[1, 0], [0, 1], [1, 1], [1, -1]]) {
      let a = 0, b = 0;
      for (let k = 1; k <= R && !a; k++) if (geo(x + dx * k, y + dy * k)) a = k;
      for (let k = 1; k <= R && !b; k++) if (geo(x - dx * k, y - dy * k)) b = k;
      if (!a || !b) continue;
      thin = true;
      const i = surf(x + dx * a, y + dy * a, dx, dy), j = surf(x - dx * b, y - dy * b, -dx, -dy);
      if (i === null || j === null) continue;
      const dot = N[i] * N[j] + N[i + 1] * N[j + 1] + N[i + 2] * N[j + 2];
      if (Math.abs(N[i + 3] - N[j + 3]) < tol && dot > 0.82) { crack = true; break; }
    }
    if (crack) { n++; mark[Math.floor(y / ss) * BW + Math.floor(x / ss)] = 1; } else if (thin) gaps++;
  }
  return { n: n / (ss * ss), gaps: gaps / (ss * ss), mark };
}
window.view = (az, el, dist, dAz, want) => {
  const half = Math.min(700, Math.max(90, dist * 1.25 + 60)), sc = S.sun.shadow.camera;   // the game's shadow box for this view distance
  if (sc.right !== half) { sc.left = sc.bottom = -half; sc.right = sc.top = half; sc.updateProjectionMatrix(); }
  S.sun.position.copy(S.center).addScaledVector(S.sunDir, 400); S.sun.target.position.copy(S.center); S.sun.target.updateMatrixWorld();
  const W = S.W, H = S.H, blink = new Uint8Array(W * H);
  let raw = 0, CA, NS, pngA = null;
  const cdiff = (P, Q, i) => Math.max(Math.abs(P[i*4] - Q[i*4]), Math.abs(P[i*4+1] - Q[i*4+1]), Math.abs(P[i*4+2] - Q[i*4+2]));
  if (S.method === 'turn') {
    place(az + dAz, el, dist); const CB = color(), NB = aux('n', S.rtN), UB = aux('u', S.rtU);
    place(az, el, dist); const NA = aux('n', S.rtN), UA = aux('u', S.rtU); CA = color(); NS = NA;
    const eA = edges(NA, 2), eB = edges(NB, 2);
    for (let i = 0; i < W * H; i++) {
      if (!(NA[i*4+3] > 0) || !(NB[i*4+3] > 0) || eA[i] || eB[i]) continue;
      if (cdiff(CA, CB, i) < S.tColor) continue;
      const duv = Math.abs(UA[i*4] - UB[i*4]) + Math.abs(UA[i*4+1] - UB[i*4+1]);
      const dot = NA[i*4]*NB[i*4] + NA[i*4+1]*NB[i*4+1] + NA[i*4+2]*NB[i*4+2];
      if (duv > 0.01 || UA[i*4+2] !== UB[i*4+2] || dot < 0.98) { blink[i] = 1; raw++; }
    }
  } else {
    // jitter: same camera, the near plane moved by a few depth-buffer steps at this distance. Screen positions do not
    // depend on near, so edges and texture stay put; only which of two close surfaces wins the depth test can change.
    place(az, el, dist); NS = aux('n', S.rtN); CA = color();
    if (want.frame) pngA = S.r.domElement.toDataURL('image/png');
    const n0 = S.cam.near, eps = Math.pow(2, -24) * dist / n0 * S.jitterSteps;
    S.r.shadowMap.autoUpdate = false;
    for (let k = 1; k <= S.jitterFrames; k++) {
      S.cam.near = n0 * (1 + k * eps); S.cam.updateProjectionMatrix();
      setMats('orig'); S.scene.background = HAZE; S.r.setRenderTarget(null); S.r.render(S.scene, S.cam);
      const gl = S.gl, CB = new Uint8Array(W * H * 4); gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, CB);
      for (let i = 0; i < W * H; i++) if (!blink[i] && cdiff(CA, CB, i) >= S.tColor) { blink[i] = 1; raw++; }
    }
    S.cam.near = n0; S.cam.updateProjectionMatrix();
  }
  const CV = cover();
  if (S.method === 'turn' && want.frame) { place(az, el, dist); color(); pngA = S.r.domElement.toDataURL('image/png'); }
  const keep = new Uint8Array(W * H); let kept = 0;
  for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) {
    const i = y * W + x; if (!blink[i]) continue;
    if (blink[i-1] || blink[i+1] || blink[i-W] || blink[i+W] || blink[i-W-1] || blink[i-W+1] || blink[i+W-1] || blink[i+W+1]) { keep[i] = 1; kept++; }
  }
  const sl = slits(CV, NS, dist);
  // marked image: frame A with blink (red, grown by 1 px) and slit (cyan) pixels; buffers are bottom-up
  const cv = document.createElement('canvas'); cv.width = W; cv.height = H; const ctx = cv.getContext('2d');
  const img = ctx.createImageData(W, H), pts = [];
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const i = y * W + x, o = ((H - 1 - y) * W + x) * 4;
    img.data[o] = CA[i*4]; img.data[o+1] = CA[i*4+1]; img.data[o+2] = CA[i*4+2]; img.data[o+3] = 255;
    if (sl.mark[i]) pts.push([x, H - 1 - y, 0]);
    if (keep[i]) pts.push([x, H - 1 - y, 1]);
  }
  ctx.putImageData(img, 0, 0);
  for (const [x, y, k] of pts) { ctx.fillStyle = k ? '#ff0000' : '#00e5ff'; ctx.fillRect(x - 1, y - 1, 3, 3); }
  const marked = (kept || sl.n) && want.marked ? cv.toDataURL('image/png') : null;
  const tw = 320, th = Math.round(H * tw / W), tc = document.createElement('canvas'); tc.width = tw; tc.height = th;
  const tx = tc.getContext('2d'); tx.drawImage(cv, 0, 0, tw, th);
  for (const [x, y, k] of pts) { tx.fillStyle = k ? '#ff0000' : '#00e5ff'; tx.fillRect(Math.floor(x * tw / W) - 1, Math.floor(y * tw / W) - 1, 2, 2); }
  if (kept) {                                            // a red box around the blink pixels, readable on the small picture
    let x0 = 1e9, y0 = 1e9, x1 = -1, y1 = -1;
    for (const [x, y, k] of pts) if (k) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
    const f = tw / W; tx.strokeStyle = '#ff0000'; tx.lineWidth = 2; tx.strokeRect(x0 * f - 6, y0 * f - 6, (x1 - x0) * f + 12, (y1 - y0) * f + 12);
  }
  S.thumbs.push(tc);
  return { blink: kept, blink_raw: raw, slit: Math.round(sl.n), gaps: Math.round(sl.gaps), pngA, marked, idx: S.thumbs.length - 1 };
};
window.sheet = (o) => {
  const tw = 320, th = S.thumbs[0].height, Wd = 1920, pad = 6, cap = 18;
  const rows = [['title', 70]];
  if (o.worstBlink.length) rows.push(['h', 26], ['grid', o.worstBlink, Math.ceil(o.worstBlink.length / 6)]);
  if (o.worstSlit.length) rows.push(['h', 26], ['grid', o.worstSlit, Math.ceil(o.worstSlit.length / 6)]);
  rows.push(['h', 26]); for (const g of o.rings) rows.push(['chart', g, 70]);
  rows.push(['h', 26]); for (const g of o.rings) rows.push(['grid', g.overview, Math.ceil(g.overview.length / 6)]);
  let Ht = 0; for (const r of rows) Ht += r[0] === 'grid' ? r[2] * (th + cap + pad) : r[r.length - 1] + pad;
  const c = document.createElement('canvas'); c.width = Wd; c.height = Ht + 10; const x = c.getContext('2d');
  x.fillStyle = '#16181c'; x.fillRect(0, 0, Wd, c.height); x.font = '15px sans-serif'; let y = 6, hi = 0;
  const heads = o.heads;
  for (const r of rows) {
    if (r[0] === 'title') { x.fillStyle = o.fault ? '#ff5050' : '#7ee07e'; x.font = 'bold 22px sans-serif'; x.fillText(o.title, 10, y + 24); x.font = '15px sans-serif'; x.fillStyle = '#ddd'; x.fillText(o.sub, 10, y + 52); y += 70 + pad; }
    else if (r[0] === 'h') { x.fillStyle = '#9cf'; x.font = 'bold 17px sans-serif'; x.fillText(heads[hi++], 10, y + 19); x.font = '15px sans-serif'; y += 26 + pad; }
    else if (r[0] === 'grid') {
      r[1].forEach((v, k) => { const cx = 10 + (k % 6) * (tw + 0), cy = y + Math.floor(k / 6) * (th + cap + pad);
        x.drawImage(S.thumbs[v.idx], cx, cy); x.fillStyle = v.blink ? '#ff8080' : '#ccc'; x.fillText(v.label, cx + 4, cy + th + 14); });
      y += r[2] * (th + cap + pad);
    } else if (r[0] === 'chart') {
      const g = r[1], n = g.blink.length, bw = (Wd - 220) / n, mx = Math.max(o.fault, ...g.blink, 1), ms = Math.max(1, ...g.slit);
      x.fillStyle = '#ccc'; x.fillText(g.label, 10, y + 20); x.fillText('blink max ' + Math.max(...g.blink), 10, y + 40); x.fillText('slit max ' + Math.max(...g.slit), 10, y + 60);
      x.fillStyle = '#2a2d33'; x.fillRect(200, y, Wd - 210, 70);
      g.blink.forEach((v, k) => { x.fillStyle = '#ff4040'; const h = 34 * v / mx; x.fillRect(200 + k * bw, y + 35 - h, Math.max(1, bw - 1), h); });
      g.slit.forEach((v, k) => { x.fillStyle = '#00d0ff'; const h = 34 * v / ms; x.fillRect(200 + k * bw, y + 36, Math.max(1, bw - 1), h); });
      x.strokeStyle = '#ff8080'; x.beginPath(); x.moveTo(200, y + 35 - 34 * o.fault / mx); x.lineTo(Wd - 10, y + 35 - 34 * o.fault / mx); x.stroke();
      y += 70 + pad;
    }
  }
  return c.toDataURL('image/jpeg', 0.88);
};
window.ready = true;
</script></body></html>`;

// ---------- the sweep ----------
function list(s) { return String(s).split(',').map(Number).filter((v) => Number.isFinite(v)); }
function writeData(file, dataUrl) { fs.writeFileSync(file, Buffer.from(dataUrl.split(',')[1], 'base64')); }

async function openBrowser() {
  const pw = findPlaywright(), exe = findChrome();
  const args = opt.gpu === 'off' ? [] : ['--use-angle=vulkan', '--enable-gpu', '--ignore-gpu-blocklist'];
  return pw.chromium.launch({ executablePath: exe, args });
}

export async function sweep(browser, glb, out, o) {
  const three = findThree();
  fs.mkdirSync(path.join(out, 'frames'), { recursive: true }); fs.mkdirSync(path.join(out, 'marked'), { recursive: true });
  const page = await browser.newPage();
  const errors = []; page.on('pageerror', (e) => errors.push(String(e))); page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  await page.route('http://sweep.local/**', (route) => {
    const u = new URL(route.request().url()).pathname;
    if (u === '/' || u === '/index.html') return route.fulfill({ contentType: 'text/html', body: HTML });
    if (u === '/model.glb') return route.fulfill({ contentType: 'model/gltf-binary', body: fs.readFileSync(glb) });
    if (u.startsWith('/three/')) { const f = path.join(three, decodeURIComponent(u.slice(7))); if (f.startsWith(three) && fs.existsSync(f)) return route.fulfill({ contentType: 'text/javascript', body: fs.readFileSync(f) }); }
    return route.fulfill({ status: 404, body: '' });
  });
  await page.goto('http://sweep.local/');
  await page.waitForFunction(() => window.ready === true, null, { timeout: 30000 }).catch(() => { throw new Error('page did not start: ' + errors.join(' | ')); });
  const W = o.size, H = Math.round(o.size * 9 / 16);
  const info = await page.evaluate((a) => window.setup(a), { W, H, near: o.near, far: o.far, fov: o.fov, tColor: o.flip, kLap: 1e-3, method: o.method, jitterFrames: 4, jitterSteps: 0.75 })
    .catch((e) => { throw new Error('setup failed: ' + e.message + ' ' + errors.join(' | ')); });
  if (/SwiftShader/i.test(info.renderer) && o.gpu !== 'off') console.log('warning: rendering on SwiftShader, not the GPU');
  console.log(`${path.basename(glb)}: ${info.tris} tris, ${info.meshes} meshes, size ${info.size.join(' x ')} m; ${info.renderer}; depth ${info.depthBits} bit`);
  const views = [], rings = [], t0 = Date.now();
  for (const dist of o.dist) for (const elev of o.elev) {
    const ring = { label: `d${dist} e${elev}`, dist, elev, blink: [], slit: [], overview: [] };
    for (let az = 0; az < 360 - 1e-9; az += o.step) {
      const name = `d${dist}_e${elev}_az${String(Math.round(az * 10) / 10).padStart(3, '0')}`;
      const r = await page.evaluate(([a, e, d, x, w]) => window.view(a, e, d, x, w), [az, elev, dist, 0.15, { frame: o.frames === 'all' || (o.frames !== 'none' && o.frames !== 'marked' && Math.abs(az / Number(o.frames) - Math.round(az / Number(o.frames))) < 1e-6), marked: o.frames !== 'none' }]);
      if (r.pngA) writeData(path.join(out, 'frames', name + '.png'), r.pngA);
      if (r.marked) writeData(path.join(out, 'marked', name + '.png'), r.marked);
      const v = { name, dist, elev, az, blink: r.blink, blink_raw: r.blink_raw, slit: r.slit, gaps: r.gaps, idx: r.idx,
        frame: r.pngA ? `frames/${name}.png` : null, marked: r.marked ? `marked/${name}.png` : null };
      views.push(v); ring.blink.push(r.blink); ring.slit.push(r.slit);
      if (Math.abs((az / 30) - Math.round(az / 30)) < 1e-6) ring.overview.push({ idx: r.idx, blink: r.blink, label: `${ring.label} az${Math.round(az)}  b${r.blink} s${r.slit}` });
    }
    rings.push(ring);
    console.log(`  ring ${ring.label}: blink max ${Math.max(...ring.blink)} px (views > 0: ${ring.blink.filter((b) => b > 0).length}/${ring.blink.length}), slit max ${Math.max(...ring.slit)} px  [${((Date.now() - t0) / 1000).toFixed(0)} s]`);
  }
  const lab = (v) => `${v.name.replace(/_/g, ' ')}  blink ${v.blink}  slit ${v.slit}`;
  const worstBlink = [...views].sort((a, b) => b.blink - a.blink).filter((v) => v.blink > 0).slice(0, 12);
  const worstSlit = [...views].sort((a, b) => b.slit - a.slit).filter((v) => v.slit > 0).slice(0, 6);
  const worst = views.reduce((m, v) => Math.max(m, v.blink), 0);
  const fault = worst >= o.fault;
  const result = `RESULT: ${fault ? 'FAULT' : 'PASS'}  blink ${worst} px in the worst view (threshold ${o.fault}); slit ${Math.max(0, ...views.map((v) => v.slit))} px in the worst view`;
  const jpg = await page.evaluate((a) => window.sheet(a), {
    title: `${path.basename(glb)}   ${fault ? 'FAULT' : 'PASS'}: blink ${worst} px in the worst view (threshold ${o.fault})`,
    sub: `${o.method} method, ${views.length} views, step ${o.step} deg, dist ${o.dist.join('/')} m, elev ${o.elev.join('/')} deg, near ${o.near} far ${o.far} fov ${o.fov}; red = blink (z-fight), cyan = slit (sky through a crack <= 1.5 px between continuing surfaces)`,
    heads: [...(worstBlink.length ? ['Worst blink views'] : []), ...(worstSlit.length ? ['Worst slit views'] : []), 'Blink (red, up) and slit (cyan, down) pixels by azimuth, 0..360; line = fault threshold', 'Every 30 degrees'],
    worstBlink: worstBlink.map((v) => ({ idx: v.idx, blink: v.blink, label: lab(v) })), worstSlit: worstSlit.map((v) => ({ idx: v.idx, blink: v.blink, label: lab(v) })),
    rings, fault: o.fault });
  writeData(path.join(out, 'SWEEP.jpg'), jpg);
  const strip = (v) => { const { idx, ...rest } = v; return rest; };
  const report = { file: path.resolve(glb), when: new Date().toISOString(), renderer: info.renderer, model: info,
    params: { method: o.method, dist: o.dist, elev: o.elev, step: o.step, near: o.near, far: o.far, fov: o.fov, size: [W, H], colour_flip: o.flip, fault_px: o.fault,
      ...(o.method === 'turn' ? { extra_turn_deg: 0.15, edge_px: 2 } : { jitter_frames: 4, jitter_depth_steps_each: 0.75 }) },
    totals: { blink: views.reduce((s, v) => s + v.blink, 0), views_with_blink: views.filter((v) => v.blink > 0).length, slit: views.reduce((s, v) => s + v.slit, 0), views: views.length, worst_blink: worst },
    worst_blink: worstBlink.map(strip), worst_slit: worstSlit.map(strip), views: views.map(strip), result: fault ? 'FAULT' : 'PASS', errors };
  fs.writeFileSync(path.join(out, 'sweep.json'), JSON.stringify(report, null, 1));
  await page.close();
  console.log(`  worst blink views: ${worstBlink.slice(0, 5).map((v) => `${v.name} ${v.blink}`).join(', ') || 'none'}`);
  console.log(`  worst slit views:  ${worstSlit.slice(0, 5).map((v) => `${v.name} ${v.slit}`).join(', ') || 'none'}`);
  console.log(`  sheet ${path.join(out, 'SWEEP.jpg')}  data ${path.join(out, 'sweep.json')}  (${((Date.now() - t0) / 1000).toFixed(0)} s)`);
  console.log(result);
  return report;
}

// ---------- synthetic GLBs for the self-test ----------
function glbOf(quads) {
  // quads: [{c:[r,g,b], p:[[x,y,z] x4]}] -> one mesh per quad, double-sided flat material each
  const bin = [], views = [], accessors = [], meshes = [], materials = [], nodes = [];
  let off = 0;
  const push = (arr, target) => { const b = Buffer.from(arr.buffer); views.push({ buffer: 0, byteOffset: off, byteLength: b.length, ...(target ? { target } : {}) }); bin.push(b); off += b.length; const pad = (4 - (off % 4)) % 4; if (pad) { bin.push(Buffer.alloc(pad)); off += pad; } return views.length - 1; };
  quads.forEach((q, i) => {
    const P = new Float32Array(q.p.flat());
    const u = [q.p[1][0] - q.p[0][0], q.p[1][1] - q.p[0][1], q.p[1][2] - q.p[0][2]], v = [q.p[3][0] - q.p[0][0], q.p[3][1] - q.p[0][1], q.p[3][2] - q.p[0][2]];
    let n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]; const l = Math.hypot(...n); n = n.map((x) => x / l);
    const N = new Float32Array([...n, ...n, ...n, ...n]), UV = new Float32Array([0, 0, 1, 0, 1, 1, 0, 1]), I = new Uint16Array([0, 1, 2, 0, 2, 3]);
    const mn = [0, 1, 2].map((k) => Math.min(...q.p.map((p) => p[k]))), mx = [0, 1, 2].map((k) => Math.max(...q.p.map((p) => p[k])));
    const a0 = accessors.push({ bufferView: push(P, 34962), componentType: 5126, count: 4, type: 'VEC3', min: mn, max: mx }) - 1;
    const a1 = accessors.push({ bufferView: push(N, 34962), componentType: 5126, count: 4, type: 'VEC3' }) - 1;
    const a2 = accessors.push({ bufferView: push(UV, 34962), componentType: 5126, count: 4, type: 'VEC2' }) - 1;
    const a3 = accessors.push({ bufferView: push(I, 34963), componentType: 5123, count: 6, type: 'SCALAR' }) - 1;
    materials.push({ pbrMetallicRoughness: { baseColorFactor: [...q.c, 1], metallicFactor: 0, roughnessFactor: 0.8 }, doubleSided: true });
    meshes.push({ primitives: [{ attributes: { POSITION: a0, NORMAL: a1, TEXCOORD_0: a2 }, indices: a3, material: i }] });
    nodes.push({ mesh: i });
  });
  const body = Buffer.concat(bin);
  const json = Buffer.from(JSON.stringify({ asset: { version: '2.0' }, scene: 0, scenes: [{ nodes: nodes.map((_, i) => i) }], nodes, meshes, materials, accessors, bufferViews: views, buffers: [{ byteLength: body.length }] }));
  const jpad = Buffer.alloc((4 - (json.length % 4)) % 4, 0x20), jb = Buffer.concat([json, jpad]);
  const head = Buffer.alloc(12); head.writeUInt32LE(0x46546c67, 0); head.writeUInt32LE(2, 4); head.writeUInt32LE(12 + 8 + jb.length + 8 + body.length, 8);
  const ch = (len, type) => { const b = Buffer.alloc(8); b.writeUInt32LE(len, 0); b.writeUInt32LE(type, 4); return b; };
  return Buffer.concat([head, ch(jb.length, 0x4e4f534a), jb, ch(body.length, 0x004e4942), body]);
}
// a "car body" stand-in: a 9 x 2.6 m side panel facing +z and one facing +x, a 9 x 2.4 m roof, each with an overlapping
// second panel (other colour) `gap` m in front of it, covering part of it
function stackScene(gap) {
  const red = [0.55, 0.08, 0.06], green = [0.08, 0.32, 0.12], cream = [0.85, 0.8, 0.65], blue = [0.1, 0.2, 0.55];
  return [
    { c: green, p: [[-4.5, 0, 1.2], [4.5, 0, 1.2], [4.5, 2.6, 1.2], [-4.5, 2.6, 1.2]] },
    { c: cream, p: [[-3, 0.8, 1.2 + gap], [3, 0.8, 1.2 + gap], [3, 1.8, 1.2 + gap], [-3, 1.8, 1.2 + gap]] },
    { c: green, p: [[4.5, 0, 1.2], [4.5, 0, -1.2], [4.5, 2.6, -1.2], [4.5, 2.6, 1.2]] },
    { c: red, p: [[4.5 + gap, 0.5, 0.8], [4.5 + gap, 0.5, -0.8], [4.5 + gap, 2.2, -0.8], [4.5 + gap, 2.2, 0.8]] },
    { c: blue, p: [[-4.5, 2.6, 1.2], [4.5, 2.6, 1.2], [4.5, 2.6, -1.2], [-4.5, 2.6, -1.2]] },
    { c: cream, p: [[-4, 2.6 + gap, 0.6], [4, 2.6 + gap, 0.6], [4, 2.6 + gap, -0.6], [-4, 2.6 + gap, -0.6]] },
  ];
}
// two panels side by side with a 6 mm vertical slit between them, and a third behind nothing: sky shows through
function slitScene() {
  const g = [0.08, 0.32, 0.12];
  return [
    { c: g, p: [[-4.5, 0, 0], [-0.003, 0, 0], [-0.003, 2.6, 0], [-4.5, 2.6, 0]] },
    { c: g, p: [[0.003, 0, 0], [4.5, 0, 0], [4.5, 2.6, 0], [0.003, 2.6, 0]] },
  ];
}

async function main() {
  const o = { dist: list(opt.dist), elev: list(opt.elev), step: Number(opt.step), near: Number(opt.near), far: Number(opt.far), fov: Number(opt.fov),
    size: Number(opt.size), frames: opt.frames, fault: Number(opt.fault), gpu: opt.gpu, method: opt.method, flip: Number(opt.flip) };
  if (opt.selftest) {
    const out = pos[0]; if (!out) { console.error('usage: sweep.mjs --selftest <out dir>'); process.exit(2); }
    fs.mkdirSync(out, { recursive: true });
    const cases = [['gap-0.5mm', stackScene(0.0005), 'FAULT'], ['gap-10mm', stackScene(0.010), 'PASS'], ['slit-6mm', slitScene(), 'slit']];
    const browser = await openBrowser(); let ok = true; const rows = [];
    try {
      for (const [name, quads, want] of cases) {
        const glb = path.join(out, name + '.glb'); fs.writeFileSync(glb, glbOf(quads));
        console.log(`\n== ${name} (want ${want})`);
        const r = await sweep(browser, glb, path.join(out, name), { ...o, step: argv.includes('--step') ? o.step : 10, dist: argv.includes('--dist') ? o.dist : [12, 30, 60, 100, 150], frames: 'marked' });
        const pass = want === 'slit' ? r.totals.slit > 0 : r.result === want;
        rows.push(`${pass ? 'ok  ' : 'FAIL'} ${name}: ${r.result}, worst blink ${r.totals.worst_blink} px, views with blink ${r.totals.views_with_blink}/${r.totals.views}, slit total ${r.totals.slit} px (want ${want})`);
        ok &&= pass;
      }
    } finally { await browser.close(); }
    console.log('\nSELFTEST\n' + rows.join('\n') + `\nSELFTEST ${ok ? 'PASSED' : 'FAILED'}`);
    process.exit(ok ? 0 : 1);
  }
  const [glb, out] = pos;
  if (!glb || !out) { console.error('usage: node sweep.mjs <file.glb> <out dir> [options]; --help'); process.exit(2); }
  if (!fs.existsSync(glb)) { console.error(`no such file ${glb}`); process.exit(2); }
  const browser = await openBrowser();
  try { const r = await sweep(browser, glb, out, o); process.exitCode = r.result === 'FAULT' ? 1 : 0; }
  finally { await browser.close(); }
}

if (import.meta.url === `file://${process.argv[1]}` || process.argv[1]?.endsWith('sweep.mjs')) main().catch((e) => { console.error(e.stack || String(e)); process.exit(3); });
