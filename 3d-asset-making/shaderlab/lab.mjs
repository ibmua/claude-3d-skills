#!/usr/bin/env node
// Shader Lab CLI (no dependencies beyond three in ./node_modules and a Chrome on the machine).
//   node lab.mjs serve  SPEC.json [--port 8790]             interactive page on 127.0.0.1 (orbit, time, live uniforms)
//   node lab.mjs render SPEC.json [--out DIR] [--size 960x540] [--times 8] [--clip VIEW|all|none] [--seconds 4]
//                                 [--fps 24] [--look game|dark|studio] [--bloom on|off] [--gpu] [--timeout 600]
//   node lab.mjs fallback SPEC.json --out DIR [--t 3.5] [--size 512]   each program baked over its UV square at time t:
//        DIR/<material>.png + DIR/fallback.json {material: {scale, mode}}; export_game.py --live-fallback DIR puts them on the
//        live parts so the GLB looks right where the program does not run (glTF viewers, the dashboard, a game without it)
// render writes DIR/sheet-<view>.png (one row of --times frames over the loop), DIR/<view>.mp4 (the clip, real speed),
// DIR/frames/... and DIR/result.json (errors, triangles, materials, the game views' real pixel sizes). Exit code 2 on
// a GLSL error, a missing material or a program that outputs NaN/Inf anywhere in its loop (checked before any frame,
// no model calls), so an agent's loop can stop on it. Spec format and the method: README.md.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawn, execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const [cmd, specArg, ...rest] = process.argv.slice(2);
const opt = (k, d) => { const i = rest.indexOf('--' + k); return i < 0 ? d : rest[i + 1]; };
const flag = (k) => rest.includes('--' + k);
if (!['serve', 'render', 'fallback'].includes(cmd) || !specArg) { console.error(fs.readFileSync(fileURLToPath(import.meta.url), 'utf8').split('\n').slice(1, 8).join('\n')); process.exit(1); }
const specPath = path.resolve(specArg);
// Serve from the spec's folder, or from the common ancestor of it and the model when "model" points outside (../export/x.glb).
let workDir = path.dirname(specPath);
try {
  const model = JSON.parse(fs.readFileSync(specPath, 'utf8')).model;
  if (model) { const mp = path.resolve(workDir, model); while (!mp.startsWith(workDir.endsWith(path.sep) ? workDir : workDir + path.sep) && path.dirname(workDir) !== workDir) workDir = path.dirname(workDir); }
} catch (e) { /* the page reports a bad spec */ }
const THREE_DIR = path.join(HERE, 'node_modules', 'three');
if (!fs.existsSync(THREE_DIR)) { console.error(`three missing: cd ${HERE} && npm install`); process.exit(1); }

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.glsl': 'text/plain',
  '.glb': 'model/gltf-binary', '.gltf': 'model/gltf+json', '.png': 'image/png', '.jpg': 'image/jpeg', '.bin': 'application/octet-stream', '.svg': 'image/svg+xml', '.wasm': 'application/wasm' };
const MOUNTS = { '/lab/': HERE, '/three/': THREE_DIR, '/work/': workDir };
function serve(port) {
  const srv = http.createServer((req, res) => {
    const u = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    const m = Object.keys(MOUNTS).find((k) => u.startsWith(k));
    const f = m && path.resolve(MOUNTS[m], u.slice(m.length));
    if (!f || !f.startsWith(path.resolve(MOUNTS[m])) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); return res.end('not found ' + u); }
    res.writeHead(200, { 'content-type': MIME[path.extname(f)] || 'application/octet-stream', 'cache-control': 'no-store' });
    fs.createReadStream(f).pipe(res);
  });
  return new Promise((ok) => srv.listen(port, '127.0.0.1', () => ok(srv)));
}
const pageUrl = (port, extra = '') => `http://127.0.0.1:${port}/lab/lab.html?spec=/work/${path.relative(workDir, specPath).split(path.sep).map(encodeURIComponent).join('/')}${extra}`;

if (cmd === 'serve') {
  const srv = await serve(+opt('port', 8790));
  console.log(pageUrl(srv.address().port));
} else {
  const t0 = Date.now();
  const out = path.resolve(opt('out', path.join(path.dirname(specPath), 'out')));
  fs.mkdirSync(path.join(out, 'frames'), { recursive: true });
  const [W, H] = opt('size', '960x540').split('x').map(Number);
  const srv = await serve(0), port = srv.address().port;
  const chrome = ['google-chrome', 'chromium', 'chromium-browser'].map((b) => { try { return execFileSync('which', [b]).toString().trim(); } catch { return null; } }).find(Boolean);
  if (!chrome) { console.error('no chrome/chromium found'); process.exit(1); }
  const prof = fs.mkdtempSync(path.join(os.tmpdir(), 'shaderlab-'));
  const gl = flag('gpu') ? ['--use-angle=default', '--enable-gpu', '--ignore-gpu-blocklist'] : ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'];
  const proc = spawn(chrome, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${prof}`, '--no-first-run', '--hide-scrollbars', ...gl, 'about:blank'], { stdio: 'ignore' });
  const cleanup = () => { try { proc.kill('SIGKILL'); } catch {} srv.close(); try { fs.rmSync(prof, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 }); } catch {} };   // Chrome still writes its profile after SIGKILL: ENOTEMPTY crashed whole renders (2026-10-13 an old-TV prop)
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let devPort;
  for (let i = 0; i < 100 && !devPort; i++) { await sleep(100); try { devPort = fs.readFileSync(path.join(prof, 'DevToolsActivePort'), 'utf8').split('\n')[0]; } catch {} }
  if (!devPort) { cleanup(); console.error('chrome did not start'); process.exit(1); }
  const tgt = await (await fetch(`http://127.0.0.1:${devPort}/json/new?${encodeURIComponent(pageUrl(port, '&headless'))}`, { method: 'PUT' })).json();
  const ws = new WebSocket(tgt.webSocketDebuggerUrl);
  await new Promise((ok, no) => { ws.onopen = ok; ws.onerror = no; });
  let id = 0; const pending = new Map(); const consoleLines = [];
  ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
    if (m.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(m.params.type)) consoleLines.push(m.params.args.map((a) => a.value ?? a.description).join(' '));
    if (m.method === 'Runtime.exceptionThrown') consoleLines.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text); };
  const send = (method, params = {}) => new Promise((ok) => { const i = ++id; pending.set(i, ok); ws.send(JSON.stringify({ id: i, method, params })); });
  const evaluate = async (expression) => { const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text); return r.result?.result?.value; };
  await send('Runtime.enable');
  const deadline = Date.now() + 1000 * +opt('timeout', 600);
  while (!(await evaluate('!!(window.lab && window.lab.ready)').catch(() => false))) { if (Date.now() > deadline) break; await sleep(200); }
  const state = await evaluate('({errors: lab.errors, info: lab.info, views: lab.views, fatal: lab.fatal || null})');
  const result = { spec: specPath, errors: [...(state?.errors || []), ...consoleLines.filter((l) => !/GPU stall|swiftshader|WebGL-/i.test(l))], info: state?.info, views: state?.views || [], files: [] };
  const finish = (code) => { result.seconds = +((Date.now() - t0) / 1000).toFixed(1); fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify(result, null, 1)); cleanup();
    console.log(JSON.stringify({ out, errors: result.errors.length, files: result.files.length, seconds: result.seconds })); if (result.errors.length) console.error(result.errors.join('\n\n')); process.exit(code); };
  if (!state || state.fatal || result.errors.length) finish(2);
  // A program that writes NaN/Inf at any moment of its loop blacks out a rectangle under blending + bloom (an old-TV prop
  // 2026-10-13: exp() overflow in a branch step() discarded). Sample the whole loop densely and refuse the program.
  const loopSeconds = +opt('seconds', (() => { try { return JSON.parse(fs.readFileSync(specPath, 'utf8')).clip?.seconds; } catch { return 0; } })() || 4);
  for (const name of await evaluate('Object.keys(lab.programs || {})')) {
    const bad = await evaluate(`lab.checkFinite(${JSON.stringify(name)}, ${loopSeconds}, ${Math.max(64, Math.ceil(loopSeconds * 8))})`);
    if (bad.length) result.errors.push(`program "${name}" outputs NaN/Inf at t = ${bad.map((b) => b.t).join(', ')} s (of a ${loopSeconds} s loop; up to ${(100 * Math.max(...bad.map((b) => b.share))).toFixed(1)} % of its UV square). `
      + 'It renders as black blocks under blending and bloom. Usual cause: exp/pow/division overflowing in a branch that mix()/step() throws away; GLSL evaluates both sides, so clamp the argument (e.g. exp(-max(x, 0.0) * k)).');
  }
  if (result.errors.length) finish(2);
  if (cmd === 'fallback') {
    const fb = {}, t = +opt('t', 0), size = +opt('size', 512);
    for (const name of await evaluate('Object.keys(lab.programs || {})')) {
      const r = await evaluate(`lab.bakeFallback(${JSON.stringify(name)}, ${t}, ${size})`);
      const f = path.join(out, name + '.png'); fs.writeFileSync(f, Buffer.from(r.png.split(',')[1], 'base64'));
      fb[name] = { scale: r.scale, mode: r.mode, t, size }; result.files.push(f);
    }
    fs.writeFileSync(path.join(out, 'fallback.json'), JSON.stringify(fb, null, 1)); finish(0);
  }
  const look = opt('look', null), bloom = opt('bloom', null);
  const o = JSON.stringify({ ...(look ? { look } : {}), ...(bloom ? { bloom: bloom === 'on' } : {}) });
  const save = async (view, t, file) => {
    const url = await evaluate(`lab.renderFrame(${JSON.stringify(view)}, ${t}, ${W}, ${H}, ${o})`);
    fs.writeFileSync(file, Buffer.from(url.split(',')[1], 'base64')); return file;
  };
  const seconds = loopSeconds, n = +opt('times', 8), fps = +opt('fps', 24);
  const ff = (args) => execFileSync('ffmpeg', ['-y', '-loglevel', 'error', ...args]);
  for (const v of result.views) {
    const dir = path.join(out, 'frames', v); fs.mkdirSync(dir, { recursive: true });
    for (let k = 0; k < n; k++) await save(v, (k * seconds) / n, path.join(dir, `sheet_${String(k).padStart(2, '0')}.png`));
    const sheet = path.join(out, `sheet-${v}.png`);
    ff(['-i', path.join(dir, 'sheet_%02d.png'), '-vf', `tile=${n}x1:padding=4:color=0x202020`, '-frames:v', '1', '-update', '1', sheet]);
    result.files.push(sheet);
  }
  const clip = opt('clip', result.views[0]);
  for (const v of clip === 'all' ? result.views : clip === 'none' ? [] : [clip]) {
    const dir = path.join(out, 'frames', v, 'clip'); fs.mkdirSync(dir, { recursive: true });
    for (let k = 0; k < Math.round(seconds * fps); k++) await save(v, k / fps, path.join(dir, `${String(k).padStart(4, '0')}.png`));
    const mp4 = path.join(out, `${v}.mp4`);
    ff(['-framerate', String(fps), '-i', path.join(dir, '%04d.png'), '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', mp4]);
    result.files.push(mp4);
  }
  result.info = await evaluate('lab.info');
  const late = await evaluate('lab.errors'); if (late.length > (state.errors || []).length) result.errors.push(...late.slice((state.errors || []).length));
  finish(result.errors.length ? 2 : 0);
}
