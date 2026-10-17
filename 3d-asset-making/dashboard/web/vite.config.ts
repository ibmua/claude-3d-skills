import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';
// dev server proxies the Node backend (server.mjs on :8152)
// Two files come from outside this repo, read at build time so the viewer runs exactly what the game ships:
//   the game's picture-effects list (a design decision), the Shader Lab's surface.js (live surface programs, 3d-asset-making skill)
//   and the shader library's idle-three.js (live library kinds, a design decision).
const GAME_EFFECTS = path.resolve(__dirname, '../stubs/picture-effects.json');
const SHADERLAB = path.resolve(__dirname, '../../shaderlab');
// a game's shader library three.js binder (library kinds); stubs/ stand in without one
const IDLE_LIBRARY = path.resolve(__dirname, '../stubs/shader-library');
export default defineConfig({
  resolve: { alias: { '@game-picture-effects': GAME_EFFECTS, '@shaderlab': SHADERLAB, '@idle-library': IDLE_LIBRARY }, dedupe: ['three'] }, // one three (r180) for surface.js too
  base: './', // relative asset URLs: the same build works at / and under a path prefix
  plugins: [react()],
  // Already-open tabs still import the previous build's lazy viewer chunks.
  // Hashed files are immutable; overwrite index.html, retain those old assets.
  build: { emptyOutDir: false },
  server: { fs: { allow: ['..', GAME_EFFECTS, SHADERLAB, IDLE_LIBRARY] }, proxy: { '/api': 'http://127.0.0.1:8152', '/f': 'http://127.0.0.1:8152' } },
});
