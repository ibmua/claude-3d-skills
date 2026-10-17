// Attach a SURFACE program (plain GLSL) to a three.js material. The same file runs in the lab and in the game, so
// what was prototyped is what ships: the game loads the GLB, finds the material by name and calls attachSurface().
//
// The GLSL defines   void surface(inout Surface s, vec2 uv, float t)
//   s arrives with the material's own values (base colour, roughness, metalness, emission, alpha) and the function
//   may change any of them. uv is uv0 (0..1 over the part, as modelled), t is seconds (the caller's clock).
//   Lit materials (MeshStandard/MeshPhysical): s goes into three's PBR lighting; s.emission is HDR radiance added on
//   top (values above 1 glow under bloom and saturate under tone mapping).
//   Unlit materials (MeshBasic): the pixel is s.albedo + s.emission, alpha s.alpha (halos, light shafts, glow cards).
// Uniforms: uTime is always there; extra ones come from `uniforms` ({name: number | [x,y] | [x,y,z] | [x,y,z,w] |
// '#rrggbb'}) and are declared for you. Tune them live through the returned object: u.uGain.value = 2.
import * as THREE from 'three';

const HEADER = `
struct Surface { vec3 albedo; float roughness; float metalness; vec3 emission; float alpha; };
uniform float uTime;
// Guard: a NaN/Inf from a program (exp/pow/division overflow, often in a branch mix()/step() throws away) blends as
// black and bloom smears it into a big rectangle (an old-TV prop 2026-10-13). Ternaries, not mix(): NaN * 0 is still NaN.
// The lab's render refuses such a program anyway (checkFinite); this keeps a missed one from blacking out a scene.
float surfaceFinite( float v, float hi ) { return ( isnan( v ) || isinf( v ) ) ? 0.0 : clamp( v, 0.0, hi ); }
vec3 surfaceFinite( vec3 v, float hi ) { return vec3( surfaceFinite( v.x, hi ), surfaceFinite( v.y, hi ), surfaceFinite( v.z, hi ) ); }
`;
const LIT_HOOK = '#include <emissivemap_fragment>';
const LIT_CALL = `
	Surface s_ = Surface( diffuseColor.rgb, roughnessFactor, metalnessFactor, totalEmissiveRadiance, diffuseColor.a );
	surface( s_, vUv, uTime );
	diffuseColor = vec4( surfaceFinite( s_.albedo, 1e4 ), surfaceFinite( s_.alpha, 1.0 ) ); roughnessFactor = surfaceFinite( s_.roughness, 1.0 );
	metalnessFactor = surfaceFinite( s_.metalness, 1.0 ); totalEmissiveRadiance = surfaceFinite( s_.emission, 1e4 );`;
const UNLIT_HOOK = 'vec3 outgoingLight = reflectedLight.indirectDiffuse;';
const UNLIT_CALL = `
	Surface s_ = Surface( diffuseColor.rgb, 1.0, 0.0, vec3( 0.0 ), diffuseColor.a );
	surface( s_, vUv, uTime );
	outgoingLight = surfaceFinite( s_.albedo, 1e4 ) + surfaceFinite( s_.emission, 1e4 ); diffuseColor.a = surfaceFinite( s_.alpha, 1.0 );`;

export function uniformValue(v) {
  if (typeof v === 'number') return v;
  if (typeof v === 'string') return new THREE.Color(v);
  const V = Array.isArray(v) && [null, null, THREE.Vector2, THREE.Vector3, THREE.Vector4][v.length];
  if (!V) throw new Error(`uniform value ${JSON.stringify(v)}: use a number, '#rrggbb' or an array of 2-4 numbers`);
  return new V(...v);
}
function glslType(v) {
  if (typeof v === 'number') return 'float';
  if (typeof v === 'string') return 'vec3';
  return ['', 'float', 'vec2', 'vec3', 'vec4'][v.length];
}
function hash(s) { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return h.toString(36); }

/** Returns the uniforms object ({uTime: {value}, ...}); advance uTime yourself each frame. */
export function attachSurface(material, glsl, uniforms = {}) {
  const lit = !!(material.isMeshStandardMaterial || material.isMeshPhysicalMaterial);
  if (!lit && !material.isMeshBasicMaterial) throw new Error(`attachSurface: ${material.type} is not MeshStandard/MeshPhysical/MeshBasic`);
  const u = { uTime: { value: 0 } };
  for (const [k, v] of Object.entries(uniforms)) u[k] = { value: uniformValue(v) };
  const decl = Object.entries(uniforms).map(([k, v]) => `uniform ${glslType(v)} ${k};`).join('\n');
  material.defines = { ...(material.defines || {}), USE_UV: '' };
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, u);
    const [hook, call] = lit ? [LIT_HOOK, LIT_CALL] : [UNLIT_HOOK, UNLIT_CALL];
    if (!shader.fragmentShader.includes(hook)) throw new Error(`attachSurface: hook "${hook}" not found (three revision changed?)`);
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>\n${HEADER}\n${decl}\n// ---- surface program ----\n${glsl}\n// ---- end surface program ----\n`)
      .replace(hook, hook + '\n' + call);
  };
  const key = 'surface:' + hash(glsl + decl) + (lit ? ':lit' : ':unlit');
  material.customProgramCacheKey = () => key;
  material.userData.surface = { uniforms: u, glsl };
  material.needsUpdate = true;
  return u;
}

/** Walk a loaded scene and attach programs by material name: {name: {glsl, uniforms, unlit?, blending?}}. */
export function attachByName(root, programs) {
  const done = new Map(), missing = new Set(Object.keys(programs));
  root.traverse((o) => {
    if (!o.isMesh) return;
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    mats.forEach((m, i) => {
      const p = programs[m.name];
      if (!p) return;
      missing.delete(m.name);
      let mat = done.get(m);
      if (!mat) {
        mat = p.unlit ? new THREE.MeshBasicMaterial({ name: m.name, map: m.map, color: m.color }) : m;
        // the program owns alpha: a glow card's plain-viewer fallback is exported invisible (alpha 0 -> glTF MASK), and
        // three runs the alpha test BEFORE the program's hook, so keep the GLB's cutoff and opacity off the program.
        Object.assign(mat, { alphaTest: 0, opacity: 1 });
        if (p.blending === 'additive') Object.assign(mat, { blending: THREE.AdditiveBlending, transparent: true, depthWrite: false });
        else if (p.transparent) Object.assign(mat, { transparent: true });
        if (p.side === 'double') mat.side = THREE.DoubleSide;
        attachSurface(mat, p.glsl, p.uniforms || {});
        done.set(m, mat);
      }
      if (Array.isArray(o.material)) o.material[i] = mat; else o.material = mat;
      if (mat.transparent) o.castShadow = false;   // a glow card's shadow is a grey slab on the wall behind (2026-10-13)
    });
  });
  return { materials: [...done.values()], missing: [...missing] };
}

/** The program's raw output over its UV square at time t, as floats (RGBA, rows bottom-up). No guard: NaN/Inf stay. */
export function evalSurfaceUV(renderer, material, glsl, uniforms = {}, { t = 0, size = 512, unlit = false } = {}) {
  const u = { uTime: { value: t } };
  for (const [k, v] of Object.entries(uniforms)) u[k] = { value: uniformValue(v) };
  const decl = Object.entries(uniforms).map(([k, v]) => `uniform ${glslType(v)} ${k};`).join('\n');
  const c = material.color || new THREE.Color(0, 0, 0);
  const e = (material.emissive || new THREE.Color(0, 0, 0)).clone().multiplyScalar(material.emissiveIntensity ?? 1);
  const v3 = (x) => `vec3(${x.r.toFixed(5)}, ${x.g.toFixed(5)}, ${x.b.toFixed(5)})`;
  const mat = new THREE.ShaderMaterial({
    uniforms: u, depthTest: false, depthWrite: false,
    vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy * 2.0, 0.0, 1.0); }',
    fragmentShader: `${HEADER}\n${decl}\nvarying vec2 vUv;\n${glsl}\nvoid main(){
      Surface s = Surface(${v3(c)}, ${(material.roughness ?? 1).toFixed(4)}, ${(material.metalness ?? 0).toFixed(4)}, ${v3(e)}, ${(material.opacity ?? 1).toFixed(4)});
      surface(s, vUv, uTime);
      gl_FragColor = vec4(${unlit ? 's.albedo + s.emission' : 's.emission'}, s.alpha); }`,
  });
  const rt = new THREE.WebGLRenderTarget(size, size, { type: THREE.FloatType });
  const scene = new THREE.Scene(), cam = new THREE.Camera();
  scene.add(new THREE.Mesh(new THREE.PlaneGeometry(1, 1), mat));
  const prev = renderer.getRenderTarget(); renderer.setRenderTarget(rt); renderer.render(scene, cam); renderer.setRenderTarget(prev);
  const f = new Float32Array(size * size * 4); renderer.readRenderTargetPixels(rt, 0, 0, size, size, f);
  rt.dispose(); mat.dispose();
  return f;
}

/** Times (seconds) at which the program writes NaN or Inf anywhere on its UV square, sampled `n` times over
 * [0, seconds). Inf/NaN render black under blending and bloom spreads it, so any hit is an error to fix in the GLSL. */
export function checkFinite(renderer, material, glsl, uniforms = {}, { seconds = 8, n = 64, size = 96, unlit = false } = {}) {
  const bad = [];
  for (let k = 0; k < n; k++) {
    const t = (k * seconds) / n, f = evalSurfaceUV(renderer, material, glsl, uniforms, { t, size, unlit });
    let hits = 0; for (let i = 0; i < f.length; i++) if (!Number.isFinite(f[i])) hits++;
    if (hits) bad.push({ t: +t.toFixed(3), share: +(hits / f.length).toFixed(4) });
  }
  return bad;
}

/** Bake a surface program into a texture over its UV square at time t (the FALLBACK a glTF viewer or a game without
 * the program shows). Returns {data: RGBA Uint8 (rows bottom-up, as WebGL reads them), size, scale, mode}:
 *  mode 'lit'    (screens): rgb = emission / scale (sRGB), a = 1; the material's base colour stays its own.
 *  mode 'blend'  (unlit / additive glow cards): rgb = emission / scale, a = its luminance / max luminance, so an
 *                alpha-blended card over a dark or light background reads like the additive original.
 * scale = the largest emission component (at least 1): the exporter sets it as the emissive strength. */
export function bakeSurfaceUV(renderer, material, glsl, uniforms = {}, { t = 0, size = 512, unlit = false } = {}) {
  const f = evalSurfaceUV(renderer, material, glsl, uniforms, { t, size, unlit });
  let scale = 1, lmax = 1e-6;
  const lum = (i) => 0.2126 * f[i] + 0.7152 * f[i + 1] + 0.0722 * f[i + 2];
  for (let i = 0; i < f.length; i += 4) { scale = Math.max(scale, f[i], f[i + 1], f[i + 2]); lmax = Math.max(lmax, lum(i)); }
  const enc = (x) => { x = Math.min(1, Math.max(0, x)); return 255 * (x <= 0.0031308 ? 12.92 * x : 1.055 * Math.pow(x, 1 / 2.4) - 0.055); };
  const data = new Uint8ClampedArray(f.length), blend = unlit;
  for (let i = 0; i < f.length; i += 4) {
    const a = blend ? lum(i) / lmax : 1, k = blend ? 1 / Math.max(a * scale, 1e-6) : 1 / scale;   // blend: colour at full strength where it shows
    data[i] = enc(f[i] * k); data[i + 1] = enc(f[i + 1] * k); data[i + 2] = enc(f[i + 2] * k); data[i + 3] = 255 * a;
  }
  return { data, size, scale: +scale.toFixed(4), mode: blend ? 'blend' : 'lit' };
}
