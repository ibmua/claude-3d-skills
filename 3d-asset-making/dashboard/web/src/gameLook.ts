import * as THREE from 'three';
// "Game" look = what the game renders, so the viewer can show it next to its own beautified look (owner 2026-10-13).
// Source of truth: <game>/src/world/Environment.js (createRenderer + the Environment constructor
// and update()), camera far from src/Game.js. Shadow map size and pixel ratio per tier live in config/picture-effects.json.
// These numbers are a mirror of that file: tests/game_look.mjs reads it and fails when they drift. Never edit the game.
export const GAME_LOOK = {
  toneMapping: THREE.NeutralToneMapping, exposure: 1.0, shadowType: THREE.PCFShadowMap,
  environmentIntensity: 0.45, // RoomEnvironment through PMREM at sigma 0.04, i.e. the viewer's 'studio' map, unrotated
  hemi: { sky: 0xc4d6ee, ground: 0x9f8f70, intensity: 1.25 },
  sun: { color: 0xffdcae, intensity: 2.7, bearing: 250, elevation: 30, distance: 800, near: 1, far: 1600, bias: -0.0005, normalBias: 0.06 },
  haze: 0xe6dccb, // scene.background and fog colour (the game's sky dome is not drawn here; this is its horizon colour)
  cameraFar: 6000,
} as const;
// World: x east, z south, y up (Environment.js SUN_DIR).
export function gameSunDirection() {
  const b = THREE.MathUtils.degToRad(GAME_LOOK.sun.bearing), e = THREE.MathUtils.degToRad(GAME_LOOK.sun.elevation);
  return new THREE.Vector3(Math.sin(b) * Math.cos(e), Math.sin(e), -Math.cos(b) * Math.cos(e)).normalize();
}
// Environment.update(): fog clear to well past the target, fully closed just before the far plane; shadow box grows with distance.
export function gameFog(viewDistance: number) { const far = GAME_LOOK.cameraFar * 0.96; return { near: Math.min(far * 0.5, viewDistance * 0.7 + 60), far }; }
export const gameShadowHalf = (viewDistance: number) => Math.min(700, Math.max(90, viewDistance * 1.25 + 60));
// The game's fog curve (Environment.js patchFog). Only linear THREE.Fog uses it and only the game look sets scene.fog.
let fogPatched = false;
export function patchGameFog() {
  if (fogPatched) return; fogPatched = true;
  THREE.ShaderChunk.fog_fragment = /* glsl */ `
#ifdef USE_FOG
  #ifdef FOG_EXP2
    float fogFactor = 1.0 - exp( - fogDensity * fogDensity * vFogDepth * vFogDepth );
  #else
    float fogT = clamp( ( vFogDepth - fogNear ) / ( fogFar - fogNear ), 0.0, 1.0 );
    float fogFactor = fogT * fogT * ( 1.6 - 0.6 * fogT );
  #endif
  gl_FragColor.rgb = mix( gl_FragColor.rgb, fogColor, fogFactor );
#endif
`;
}
