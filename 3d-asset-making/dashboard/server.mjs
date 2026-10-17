// Blender asset dashboard: fresh renders of every Blender-derived asset (PC + the build box) and a click-to-web three.js viewer.
// No npm deps. Sources: config/sources.json (`sources` = asset folders, `todo` = generated to-do inventories). Scans only when the page asks (no background load); anything whose
// newest preview is older than the asset gets a niced headless-Blender render queued. See README.md.
import http from 'node:http';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { gzipSync } from 'node:zlib';
import { annotateMadeWith, buildGroups } from './groups.mjs'; // time to build + group sessions on the cards
import { getRuns, runRoots, runPictureAllowed } from './runs.mjs'; // Runs view (#/runs): progress + API cost of asset runs
import { imageThumbnail } from './thumbnails.mjs';
import { createIntegrity } from './integrity.mjs'; // geometry check (mesh_integrity.py) on open / after a viewer export; README "Geometry check"

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const PORT = +(process.env.PORT || 8152);
const HOST = process.env.HOST || '127.0.0.1';
const BLENDER = process.env.BLENDER || '/snap/bin/blender';
const CACHE = process.env.CACHE || path.join(ROOT, 'cache');
const DIST = path.join(ROOT, 'web', 'dist');
const LOCAL_SLOTS = +(process.env.LOCAL_SLOTS || 2);
const SCAN_TTL = 10_000;
const FRESH_SLACK = 2_000; // ms: a preview written within 2 s before the asset still counts as fresh

// SOURCES picks the host's config (default config/sources.json)
const SOURCES = process.env.SOURCES || path.join(ROOT, 'config', 'sources.json');
// madeWithDefaults (per project): a source that names no `madeWith` record still looks for its project's record, so a newly
// added source shows its maker and price, or a visible "model unknown", never silently nothing (owner 2026-10-12 22:1x)
const loadCfg = () => {
  const cfg = JSON.parse(fs.readFileSync(SOURCES, 'utf8'));
  for (const s of cfg.sources || []) if (!s.madeWith && cfg.madeWithDefaults?.[s.project]) s.madeWith = cfg.madeWithDefaults[s.project];
  return cfg;
};

// ---------------------------------------------------------------- tiny glob helpers
const globRe = (g) => new RegExp('^' + g.split('*').map((s) => s.replace(/[.+?^${}()|[\]\\]/g, '\\$&')).join('[^/]*') + '$');
// last good listing per directory: the SSHFS mount to the build box fails intermittently (EPERM / io error); a failed readdir used to
// become an empty folder and the assets under it vanished from the catalog for a scan (owner 2026-10-12: buggy + slow)
const lastDir = new Map();
async function listDir(dir, memo) {
  if (!memo.has(dir)) memo.set(dir, fsp.readdir(dir, { withFileTypes: true }).then((r) => { lastDir.set(dir, r); return r; })
    .catch((e) => (e.code === 'ENOENT' || e.code === 'ENOTDIR' ? (lastDir.delete(dir), []) : lastDir.get(dir) || [])));
  return memo.get(dir);
}
async function expandRoot(root, memo) {
  const segs = root.split('/');
  const i = segs.findIndex((s) => s.includes('*'));
  if (i < 0) return [{ dir: root, group: '' }];
  const parent = segs.slice(0, i).join('/') || '/';
  const re = globRe(segs[i]);
  const out = [];
  for (const e of await listDir(parent, memo)) {
    if (!e.isDirectory() && !e.isSymbolicLink()) continue;
    if (!re.test(e.name)) continue;
    const dir = [parent, e.name, ...segs.slice(i + 1)].join('/');
    // a later '*' segment expands too (train/rebuild-*/components/*); the group names every match, outermost first
    if (segs.slice(i + 1).some((s) => s.includes('*'))) {
      for (const r of await expandRoot(dir, memo)) out.push({ dir: r.dir, group: `${e.name} / ${r.group}` });
    } else if (await statOr(dir)) out.push({ dir, group: e.name });
  }
  return out;
}
async function globFiles(dir, pattern, memo) {
  const sub = path.dirname(pattern) === '.' ? '' : path.dirname(pattern);
  const d = path.join(dir, sub);
  const re = globRe(path.basename(pattern));
  return (await listDir(d, memo)).filter((e) => e.isFile() && re.test(e.name)).map((e) => path.join(d, e.name));
}
const lastStat = new Map();
const statOr = (p) => fsp.stat(p).then((s) => { lastStat.set(p, s); return s; })
  .catch((e) => (e.code === 'ENOENT' || e.code === 'ENOTDIR' ? (lastStat.delete(p), null) : lastStat.get(p) || null));
const sub = (s, key) => s.replaceAll('{key}', key);
// which model + effort made an asset (films made_with, owner 2026-10-01): an audit's `made_with`, or a design
// lane's lane.json {model, effort}; a source with `madeWith` patterns and no record shows "unknown", never a guess
const MODEL_NAME = (m) => /opus/i.test(m) ? 'Opus' : /sonnet/i.test(m) ? 'Sonnet' : /fable/i.test(m) ? 'Fable' : /haiku/i.test(m) ? 'Haiku'
  : (m.match(/^gpt-([\d.]+)-(\w+)$/) ? m.replace(/^gpt-([\d.]+)-(\w+)$/, (_, v, n) => n[0].toUpperCase() + n.slice(1) + '-' + v) : m);
function madeWithOf(j, file) {
  // the asset record: made_with is a LIST (one entry a maker), with maker_label and the total in api_cost (empty
  // when a maker's price is unknown; then api_cost_known_part holds the priced part and the badge says so)
  if (Array.isArray(j?.made_with) && j.made_with.length) {
    const lead = j.made_with.find((e) => e && (e.label || typeof e.model === 'string')) || {};
    const ok = (c) => c && typeof c.usd === 'number' && Number.isFinite(c.usd) && c.usd >= 0;
    const api_cost = ok(j.api_cost) ? j.api_cost : ok(j.api_cost_known_part) ? { ...j.api_cost_known_part, partial: true } : ok(lead.api_cost) ? lead.api_cost : undefined;
    const names = [...new Set(j.made_with.map((e) => e?.label || (typeof e?.model === 'string' ? `${MODEL_NAME(e.model)} ${e.effort || ''}`.trim() : '')).filter(Boolean))];
    // maker_label may be only a count ("2 models"): name the makers then, so the badge says who
    const label = (j.maker_label && !/^\d+ models?$/.test(j.maker_label)) ? j.maker_label : names.length ? names.join(' + ') : (j.maker_label || 'unknown');
    return { label, model: lead.model, effort: lead.effort || null, makers: j.made_with.length, via: path.basename(file), ...(api_cost ? { api_cost } : {}) };
  }
  if (j?.made_with?.label || typeof j?.made_with?.model === 'string') return { ...j.made_with, label: j.made_with.label || `${MODEL_NAME(j.made_with.model)} ${j.made_with.effort || ''}`.trim() };
  if (j && typeof j.model === 'string') return { label: `${MODEL_NAME(j.model)} ${j.effort || ''}`.trim(), model: j.model, effort: j.effort || null, via: path.basename(file) };
  return null;
}
// Producer result totals are API-equivalent dollars, shared by all assets in that session.
// Read a bounded tail once per catalog scan; never scan multi-megabyte transcripts per card.
async function readGenerationCost(src, dir, m, memo) {
  if (m.api_cost || m.generation?.scope_id) return m;
  const lane = m.via?.match(/render\/blender\/(design-[A-Za-z0-9_-]+)\/lane\.json/)?.[1];
  for (const pattern of src.generationStreams || []) {
    if (pattern.includes('{lane}') && !lane) continue;
    const file = path.resolve(dir, pattern.replaceAll('{lane}', lane || ''));
    if (!memo.has(file)) memo.set(file, (async () => {
      let handle;
      try {
        handle = await fsp.open(file, 'r');
        const st = await handle.stat();
        const start = Math.max(0, st.size - 65536), buf = Buffer.alloc(st.size - start);
        const { bytesRead } = await handle.read(buf, 0, buf.length, start);
        const lines = buf.subarray(0, bytesRead).toString('utf8').split('\n');
        if (start) lines.shift();
        for (const line of lines.reverse()) {
          let r; try { r = JSON.parse(line); } catch { continue; }
          if (r.type === 'result' && Number.isFinite(r.total_cost_usd) && r.total_cost_usd >= 0)
            return { usd: r.total_cost_usd, basis: 'api_equivalent', scope: 'shared_session', via: path.basename(file), session_id: r.session_id };
        }
      } catch { } finally { await handle?.close(); }
      return null;
    })());
    const cost = await memo.get(file);
    if (cost) return { ...m, api_cost: cost };
  }
  return m;
}
async function readMadeWith(src, dir, key, costMemo, group = '') {
  if (!src.madeWith) return undefined;
  let result = null, owner = '';
  if (src.ownerManifest) { try { owner = JSON.parse(await fsp.readFile(path.resolve(dir, src.ownerManifest), 'utf8')).owner || ''; } catch { } }
  if (!/^[A-Za-z0-9_-]+$/.test(owner)) owner = '';
  for (const pat of src.madeWith) {
    const f = path.resolve(dir, sub(pat, key).replaceAll('{group}', group).replaceAll('{owner}', owner));
    try { const record = JSON.parse(await fsp.readFile(f, 'utf8')); const m = annotateMadeWith(madeWithOf(record, f), record, f); if (m && m.label !== 'unknown' && m.model !== 'unknown') { if (!m.api_cost && typeof record.total_cost_usd === 'number' && record.total_cost_usd >= 0) m.api_cost = { usd: record.total_cost_usd, basis: 'api_equivalent', scope: 'shared_session', session_id: record.session_id, via: f }; result = await readGenerationCost(src, dir, m, costMemo); break; } } catch { }
  }
  result ||= { label: 'unknown' };
  if (src.generationStats && !result.api_cost) {
    const file = src.generationStats;
    if (!costMemo.has(file)) costMemo.set(file, (async () => {
      let h;
      try {
        h = await fsp.open(file, 'r'); const st = await h.stat();
        const start = Math.max(0, st.size - 512 * 1024), buf = Buffer.alloc(st.size - start);
        const { bytesRead } = await h.read(buf, 0, buf.length, start);
        for (const line of buf.subarray(0, bytesRead).toString('utf8').trim().split('\n').reverse()) {
          try { const record = JSON.parse(line); if (Array.isArray(record.rows)) return record; } catch { }
        }
      } catch { } finally { await h?.close(); }
      return null;
    })());
    const snapshot = await costMemo.get(file);
    const row = snapshot?.rows.find(r => r.family === group) || snapshot?.rows.find(r => owner === 'asset-' + r.family);
    if (row && Number.isFinite(row.credits) && row.credits >= 0)
      result = { ...result, api_cost: { credits: row.credits, basis: 'api_equivalent', scope: 'asset_group', assets: [row.family], status: row.state === 'ready' ? 'complete' : 'pending', via: file, at: snapshot.at } };
  }
  if (!result.api_cost && owner && src.generationUsage && src.creditRates) {
    const usageDir = path.resolve(dir, src.generationUsage.replaceAll('{owner}', owner));
    const memoKey = 'usage:' + usageDir;
    if (!costMemo.has(memoKey)) costMemo.set(memoKey, (async () => {
      try {
        const rates = JSON.parse(await fsp.readFile(src.creditRates, 'utf8'));
        if (rates.model !== 'GPT-6.1 Sol' || result.model !== 'gpt-6.1-sol') return null;
        let credits = 0, count = 0;
        for (const name of await fsp.readdir(usageDir)) {
          if (!/^codex-\d+\.jsonl$/.test(name)) continue;
          const h = await fsp.open(path.join(usageDir, name), 'r');
          let usage;
          try {
            const st = await h.stat(), start = Math.max(0, st.size - 65536), buf = Buffer.alloc(st.size - start);
            const {bytesRead} = await h.read(buf, 0, buf.length, start);
            for (const line of buf.subarray(0, bytesRead).toString().trim().split('\n').reverse()) {
              try { const record = JSON.parse(line); if (record.type === 'turn.completed' && record.usage) { usage = record.usage; break; } } catch { }
            }
          } finally { await h.close(); }
          if (usage) { const r = rates.credits_per_million; credits += ((usage.input_tokens - (usage.cached_input_tokens || 0)) * r.input + (usage.cached_input_tokens || 0) * r.cached_input + usage.output_tokens * r.output) / 1e6; count++; }
        }
        return count ? {credits, basis: 'api_equivalent', scope: 'shared_session', via: usageDir} : null;
      } catch { return null; }
    })());
    const cost = await costMemo.get(memoKey); if (cost) result = {...result, api_cost: cost};
  }
  return result;
}

// ---------------------------------------------------------------- hosts
// host 'pc' and 'local' both mean this machine; anything else is a host_map entry
const isLocal = (h) => h === 'pc' || h === 'local';
function hostOf(cfg, src) { return isLocal(src.host) ? null : cfg.host_map[src.host]; }
const toRemote = (h, p) => h.remote_prefix + p.slice(h.local_prefix.length);
const toLocal = (h, p) => h.local_prefix + p.slice(h.remote_prefix.length);
const safeName = (s) => s.replace(/[^A-Za-z0-9._-]+/g, '_');
function exportPaths(cfg, src, group, key, stamp = '') {
  const h = hostOf(cfg, src);
  const rel = path.join('exports', EXPORT_VER, src.id, safeName(group || '_'), safeName(key) + (stamp ? '.' + stamp : '') + '.glb');
  if (!h) return { local: path.join(CACHE, rel) };
  return { local: toLocal(h, path.join(h.cache, rel)), remote: path.join(h.cache, rel) };
}
// Render cache is keyed by the renderer's own hash: editing render_glb.py re-renders everything on the next look.
const RENDER_VER = createHash('sha1').update(fs.readFileSync(path.join(ROOT, 'blender', 'render_glb.py'))).digest('hex').slice(0, 8);
// Exporter changes invalidate local and remote exports, including old empty GLBs.
const EXPORT_VER = createHash('sha1').update(fs.readFileSync(path.join(ROOT, 'blender', 'export_blend.py'))).digest('hex').slice(0, 8);
const LOCAL_EXPORT_SCRIPT = path.join(CACHE, 'scripts', `export_${EXPORT_VER}.py`);
const renderPath = (src, group, key, stamp = '') => path.join(CACHE, 'renders', RENDER_VER, src.id, safeName(group || '_'), safeName(key) + (stamp ? '.' + EXPORT_VER + '.' + stamp : '') + '.png');
// Placement/material metadata can be edited while retaining mtime. Hash its bytes,
// together with the source stat, so neither catalog nor click exports reuse it.
async function exportStamp(blend, stat, src = {}) {
  if (!blend || !stat) return '';
  const side = await fsp.readFile(blend.replace(/\.blend$/, '.json')).catch((e) => { if (e.code === 'ENOENT') return ''; throw e; });
  const hash = createHash('sha1').update(`${stat.size}:${stat.mtimeMs}:`).update(side);
  let meta = {}; try { meta = side ? JSON.parse(side) : {}; } catch { /* exporter reports the malformed asset; keep the catalog usable */ }
  if (src.previewAssembler && meta.params?.family === 'surface') {
    for (const file of [src.previewAssembler, ...(src.previewDependencies || [])]) hash.update(await fsp.readFile(file));
    const project = path.resolve(path.dirname(blend), '../../../../..');
    const inputs = new Set([path.join(project, 'render/blender/home-assets/specs.json')]);
    for (const p of meta.place || []) if (p.cache) {
      const folder = path.dirname(path.join(project, p.cache));
      for (const name of [path.basename(p.cache), 'extra.glb', 'track.json', 'track.bin']) inputs.add(path.join(folder, name));
    }
    for (const file of inputs) { const st = await statOr(file); hash.update(file + ':' + (st ? `${st.size}:${st.mtimeMs}` : 'missing')); }
  }
  return hash.digest('hex').slice(0, 16);
}
const exportJobKey = (it) => 'export:' + it.id + ':' + it.exportStamp;
const renderJobKey = (it) => 'render:' + it.id + ':' + it.exportStamp;
for (const d of fs.existsSync(path.join(CACHE, 'renders')) ? fs.readdirSync(path.join(CACHE, 'renders')) : [])
  if (d !== RENDER_VER) fs.rmSync(path.join(CACHE, 'renders', d), { recursive: true, force: true });

// ---------------------------------------------------------------- job queue (render / export)
const jobs = new Map(); // jobKey -> {state, kind, err, t0, t1}
const queues = { pc: [], tr: [] };
const running = { pc: 0, tr: 0 };
const slots = (host) => (isLocal(host) ? LOCAL_SLOTS : 1);

function run(cmd, args, logFile) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    let log = ''; const saved = logFile ? fs.createWriteStream(logFile) : null;
    saved?.on('error', (e) => { p.kill(); reject(e); });
    const output = (d) => { log = (log + d).slice(-4000); saved?.write(d); };
    p.stdout.on('data', output); p.stderr.on('data', output);
    p.on('close', (code) => { saved?.end(); code === 0 ? resolve(log) : reject(new Error(`exit ${code}: ${log.slice(-600)}`)); });
    p.on('error', reject);
  });
}
const sq = (s) => `'${String(s).replaceAll("'", `'\\''`)}'`;

function enqueue(jobKey, host, kind, fn, front = false) {
  host = isLocal(host) ? 'pc' : host; // local and pc share the initialized local queue
  const j = jobs.get(jobKey);
  if (j && (j.state === 'queued' || j.state === 'running')) {
    if (front) { const q = queues[host]; const i = q.findIndex((x) => x.jobKey === jobKey); if (i > 0) q.unshift(...q.splice(i, 1)); }
    return j;
  }
  const job = { state: 'queued', kind, err: null, t0: Date.now(), t1: null };
  jobs.set(jobKey, job);
  job.promise = new Promise((resolve) => {
    const entry = { jobKey, go: async () => {
      job.state = 'running';
      try { await fn(); job.state = 'done'; } catch (e) { job.state = 'error'; job.err = String(e.message || e).slice(-800); console.error(jobKey, job.err); }
      job.t1 = Date.now(); resolve(job);
    } };
    front ? queues[host].unshift(entry) : queues[host].push(entry);
    pump(host);
  });
  return job;
}
function pump(host) {
  while (running[host] < slots(host) && queues[host].length) {
    const e = queues[host].shift();
    running[host]++;
    e.go().finally(() => { running[host]--; catalogDirty = true; pump(host); });
  }
}

const activeExports = new Map();
function doExport(cfg, src, it) {
  const snapshot = { ...it }; const key = exportJobKey(snapshot);
  if (activeExports.has(key)) return activeExports.get(key);
  const promise = produceExport(cfg, src, snapshot).finally(() => activeExports.delete(key));
  activeExports.set(key, promise); return promise;
}
async function produceExport(cfg, src, it) {
  const ex = exportPaths(cfg, src, it.group, it.key, it.exportStamp);
  const h = hostOf(cfg, src);
  const assembler = src.previewAssembler;
  await fsp.mkdir(path.dirname(ex.local), { recursive: true });
  if (!h) {
    await fsp.mkdir(path.dirname(ex.local), { recursive: true });
    await run('nice', ['-n', '10', BLENDER, '-b', it.blendPath, '-noaudio', '-t', '4', '--python-exit-code', '1',
      '--python', LOCAL_EXPORT_SCRIPT, '--', ex.local, ...(assembler ? ['--assembler', assembler] : [])], ex.local + '.log');
  } else {
    const cmd = `mkdir -p ${sq(path.dirname(ex.remote))} && nice -n 15 ${sq(h.blender)} -b ${sq(toRemote(h, it.blendPath))} -noaudio -t 6 ` +
      `--python-exit-code 1 --python ${sq(path.join(h.cache, `export_${EXPORT_VER}.py`))} -- ${sq(ex.remote)}` + (assembler ? ` --assembler ${sq(toRemote(h, assembler))}` : '');
    await run('ssh', ['-o', 'BatchMode=yes', h.ssh, cmd], ex.local + '.log');
  }
  if (await exportStamp(it.blendPath, await statOr(it.blendPath), src) !== it.exportStamp)
    throw new Error('Export inputs changed while Blender was running; retry the current asset');
  const st = await statOr(ex.local);
  const receipt = { exporter: EXPORT_VER, inputStamp: it.exportStamp, bytes: st.size, mtimeMs: st.mtimeMs, mode: 'generated', source: it.blendPath };
  await fsp.writeFile(ex.local + '.receipt.json.tmp', JSON.stringify(receipt) + '\n');
  await fsp.rename(ex.local + '.receipt.json.tmp', ex.local + '.receipt.json');
}
async function exportFresh(cfg, src, it) {
  const ex = exportPaths(cfg, src, it.group, it.key, it.exportStamp);
  const [s, b] = await Promise.all([statOr(ex.local), statOr(it.blendPath)]);
  if (!s || !b || s.mtimeMs < b.mtimeMs) return null;
  const receipt = await fsp.readFile(ex.local + '.receipt.json', 'utf8').then(JSON.parse).catch(() => null);
  return receipt?.exporter === EXPORT_VER && receipt?.inputStamp === it.exportStamp && receipt?.bytes === s.size && receipt?.mtimeMs === s.mtimeMs ? ex.local : null;
}
// Port a .blend on its own host's queue (click-to-web). PC renders never wait on this queue (see ensureRender).
async function ensureExport(cfg, src, it, front) {
  const fresh = await exportFresh(cfg, src, it);
  if (fresh) return { path: fresh, job: null };
  const snapshot = { ...it }; // later clicks may refresh the mutable catalog item
  const job = enqueue(exportJobKey(snapshot), src.host, 'export', () => doExport(cfg, src, snapshot), front);
  return { path: exportPaths(cfg, src, it.group, it.key, it.exportStamp).local, job };
}

async function ensureRender(cfg, src, it) {
  const out = renderPath(src, it.group, it.key, it.exportStamp);
  enqueue(renderJobKey(it), 'pc', 'render', async () => {
    let glb = it.renderFrom || it.glbPath;
    if (!glb && it.blendPath) {
      glb = await exportFresh(cfg, src, it);
      if (!glb && isLocal(src.host)) { await doExport(cfg, src, it); glb = exportPaths(cfg, src, it.group, it.key, it.exportStamp).local; }
      else if (!glb) {        // the build box: its queue (1 slot, nice 15) is never held by a PC slot, so waiting cannot deadlock
        const r = await ensureExport(cfg, src, it, false).then((e) => e.job?.promise);
        if (r && r.state !== 'done') throw new Error('export failed: ' + r.err);
        glb = exportPaths(cfg, src, it.group, it.key, it.exportStamp).local;
      }
    }
    await fsp.mkdir(path.dirname(out), { recursive: true });
    const tmp = out.replace(/\.png$/, '.tmp.png');
    await run('nice', ['-n', '10', BLENDER, '-b', '--factory-startup', '-noaudio', '-t', '4', '--python-exit-code', '1',
      '--python', path.join(ROOT, 'blender', 'render_glb.py'), '--', glb, tmp, '640', '480']);
    await fsp.rename(tmp, out);
  });
}

// ---------------------------------------------------------------- scan
let catalog = null, catalogAt = 0, catalogDirty = false, scanning = null;
let catalogResponseRevision = 0;
const items = new Map(); // id -> internal item (paths)

async function readManifest(cfg, src, dir) {
  if (!src.manifest) return null;
  const f = path.isAbsolute(src.manifest.file) ? src.manifest.file : path.join(dir, src.manifest.file);
  try {
    let m = JSON.parse(await fsp.readFile(f, 'utf8'));
    for (const k of (src.manifest.path || '').split('.').filter(Boolean)) m = m?.[k];
    return m || null;
  } catch { return null; }
}

function summarizeMeta(m) {
  if (!m || typeof m !== 'object') return null;
  const out = {};
  for (const [k, v] of Object.entries(m)) {
    if (v === null || typeof v === 'number' || typeof v === 'boolean' || (typeof v === 'string' && v.length < 160)) out[k] = v;
    else if (typeof v === 'object' && !Array.isArray(v) && Object.values(v).every((x) => typeof x === 'number')) out[k] = v;
  }
  return Object.keys(out).length ? out : null;
}

async function scanSource(cfg, src, memo, queueRenders) {
  const out = [];
  for (const { dir, group } of await expandRoot(src.root, memo)) {
    const manifest = await readManifest(cfg, src, dir);
    const assets = new Map();
    if (src.glb) {
      const ex = src.exclude ? globRe(src.exclude) : null;
      for (const f of await globFiles(dir, src.glb, memo)) {
        if (ex && ex.test(path.basename(f))) continue;
        let key = path.basename(f, '.glb'); if (src.keyStrip) key = key.replace(src.keyStrip, '');
        assets.set(key, { glbPath: f });
      }
    }
    if (src.blend) for (const f of await globFiles(dir, src.blend, memo)) {
      const key = path.basename(f, '.blend');
      assets.set(key, { ...(assets.get(key) || {}), blendPath: f });
    }
    await Promise.all([...assets].map(async ([key, a]) => {
      const id = [src.id, group, key].filter(Boolean).join(':');
      const [gs, bs] = await Promise.all([a.glbPath && statOr(a.glbPath), a.blendPath && statOr(a.blendPath)]);
      const stamp = !a.glbPath ? await exportStamp(a.blendPath, bs, src) : '';
      const ex = a.blendPath && !a.glbPath ? exportPaths(cfg, src, group, key, stamp) : null;
      const exS = ex && await statOr(ex.local);
      const validExport = ex && await exportFresh(cfg, src, { group, key, exportStamp: stamp, blendPath: a.blendPath });
      const assetMtime = Math.max(gs?.mtimeMs || 0, bs?.mtimeMs || 0);
      const cands = (src.previews || []).map((p) => ({ p: path.join(dir, sub(p, key)), origin: 'pipeline' }));
      cands.push({ p: renderPath(src, group, key, stamp), origin: 'dash' });
      const stats = await Promise.all(cands.map((c) => statOr(c.p)));
      let best = null;
      cands.forEach((c, i) => {
        const s = stats[i]; if (!s) return;
        const fresh = s.mtimeMs >= assetMtime - FRESH_SLACK && (c.origin !== 'dash' || !ex || (validExport && s.mtimeMs >= exS.mtimeMs - FRESH_SLACK));
        // prefer fresh; among equals prefer pipeline (its own look), then newest
        const score = (fresh ? 2 : 0) + (c.origin === 'pipeline' ? 1 : 0);
        if (!best || score > best.score || (score === best.score && s.mtimeMs > best.mtime))
          best = { url: 'f' + c.p + '?v=' + s.mtimeMs, mtime: s.mtimeMs, bytes: s.size, origin: c.origin, fresh, score };
      });
      let renderFrom = null;
      let rfStat = null;
      if (src.renderFrom) { const rf = path.join(dir, sub(src.renderFrom, key)); rfStat = await statOr(rf); if (rfStat) renderFrom = rf; }
      const extras = [];
      for (const pat of src.extras || []) for (const f of await globFiles(dir, sub(pat, key), memo)) if (!extras.includes(f)) extras.push(f);
      let meta = manifest ? summarizeMeta(manifest[sub(src.manifest.key || '{key}', key)]) : null;
      if (src.meta) {
        try { meta = { ...(meta || {}), ...summarizeMeta(JSON.parse(await fsp.readFile(path.join(dir, sub(src.meta, key)), 'utf8'))) }; } catch { }
      }
      const made_with = await readMadeWith(src, dir, key, memo, group);
      const it = {
        id, source: src.id, group, key, host: src.host, glbPath: a.glbPath || null, blendPath: a.blendPath || null, renderFrom, exportStamp: stamp,
        pub: {
          id, source: src.id, group, key, host: src.host,
          glb: a.glbPath ? 'f' + a.glbPath + '?v=' + gs.mtimeMs : validExport ? 'f' + ex.local + '?v=' + exS.mtimeMs : null,
          glbBytes: gs?.size || exS?.size || null, blend: a.blendPath ? path.basename(a.blendPath) : null, blendBytes: bs?.size || null,
          path: a.glbPath || a.blendPath, assetMtime,
          preview: best && { url: best.url, mtime: best.mtime, bytes: best.bytes, origin: best.origin, fresh: best.fresh },
          extras: extras.slice(0, 60).map((f) => 'f' + f), meta, made_with,
          integrity: renderFrom ? integrity.badgeFor(renderFrom, rfStat) : a.glbPath ? integrity.badgeFor(a.glbPath, gs) : validExport ? integrity.badgeFor(ex.local, exS) : null, // cached only, never started here
        },
      };
      items.set(id, it);
      if (queueRenders && !best?.fresh) {
        const j = jobs.get(renderJobKey(it));
        if (!j || j.state === 'done' || (j.state === 'error' && Date.now() - j.t1 > 10 * 60_000)) ensureRender(cfg, src, it);
      }
      out.push(it.pub);
    }));
  }
  return out;
}

async function scan(queueRenders = true) {
  const cfg = loadCfg();
  const memo = new Map();
  const t0 = Date.now();
  const res = await Promise.all(cfg.sources.map(async (s) => {
    try { return { s, items: await scanSource(cfg, s, memo, queueRenders) }; } catch (e) { return { s, items: [], err: String(e) }; }
  }));
  const all = res.flatMap((r) => r.items);
  const todo = await scanTodo(cfg, memo).catch((e) => [{ id: 'todo', label: 'To be done', err: String(e) }]);
  for (const it of all) {
    const internal = items.get(it.id);
    const r = jobs.get(renderJobKey(internal)), e = jobs.get(exportJobKey(internal));
    it.job = [r, e].filter(Boolean).map((j) => ({ kind: j.kind, state: j.state, err: j.err }))
      .filter((j) => j.state !== 'done');
  }
  all.sort((a, b) => b.assetMtime - a.assetMtime);
  catalog = {
    generated: Date.now(), scanMs: Date.now() - t0,
    sources: res.map(({ s, items: xs, err }) => ({ id: s.id, label: s.label, emoji: s.emoji, host: s.host, project: s.project, folder: s.folder, navLabel: s.navLabel, count: xs.length, err })),
    items: all, todo, groups: buildGroups(all, cfg),
    queue: { pc: { running: running.pc, queued: queues.pc.length }, tr: { running: running.tr, queued: queues.tr.length } },
  };
  catalogAt = Date.now(); catalogDirty = false; catalogNeedsRenders = !queueRenders;
  fsp.writeFile(CATALOG_FILE + '.tmp', JSON.stringify(catalog)).then(() => fsp.rename(CATALOG_FILE + '.tmp', CATALOG_FILE)).catch(() => {});
  return catalog;
}
let catalogNeedsRenders = false;
// the last catalog survives restarts: the page paints from it at once while the first scan runs
const CATALOG_FILE = path.join(CACHE, 'catalog.json');
try { catalog = JSON.parse(fs.readFileSync(CATALOG_FILE, 'utf8')); catalogAt = 0; catalogDirty = true; } catch { }
async function getCatalog(force, queueRenders = true, allowCached = false) {
  if (!force && catalog && !catalogDirty && (!queueRenders || !catalogNeedsRenders) && Date.now() - catalogAt < SCAN_TTL) return catalog;
  if (!scanning) {
    scanning = scan(queueRenders).finally(() => { scanning = null; });
    // Library requests return before this work finishes; still handle a failed background scan.
    scanning.catch((e) => console.error('catalog refresh:', e));
  }
  // Only the read-only library may use a snapshot. Export/check callers still await
  // discovery of internal paths, and force remains an explicit fresh-scan barrier.
  if (allowCached && catalog && !force) return { ...catalog, refreshing: true };
  return scanning;
}

// ---------------------------------------------------------------- to-do inventories (config `todo`)
// A generated JSON per project (films: a film pipeline's asset_todo.py) that lists what a film still needs
// modelled/painted, with reference art. Paths inside it are relative to the JSON's folder; the server turns image paths
// into f/ URLs. The catalog carries only the counts (it is polled); /api/todo?id= returns one inventory.
const todoFiles = new Map(); // id -> abs json path
async function scanTodo(cfg, memo) {
  const out = [];
  for (const t of cfg.todo || []) {
    for (const { dir, group } of await expandRoot(t.root, memo)) {
      const f = path.join(dir, t.file);
      const id = [t.id, group].filter(Boolean).join(':');
      try {
        const [s, T] = await Promise.all([fsp.stat(f), fsp.readFile(f, 'utf8').then(JSON.parse)]);
        todoFiles.set(id, f);
        out.push({ id, source: t.id, group, label: t.label, emoji: t.emoji, host: t.host, project: t.project,
          title: T.title || group, generated: T.generated, mtime: s.mtimeMs, cutShots: T.cut_shots, cutS: T.cut_s,
          groups: T.groups, counts: T.counts, totals: T.totals, unclassified: (T.unclassified || []).length,
          brokenRules: (T.broken_rules || []).length });
      } catch (e) { if (e.code !== 'ENOENT') out.push({ id, source: t.id, group, label: t.label, emoji: t.emoji, host: t.host, err: String(e.message || e) }); }
    }
  }
  return out;
}
const IMG = /\.(png|jpe?g|webp)$/i;
async function todoDoc(id) {
  const f = todoFiles.get(id);
  if (!f) return null;
  const T = JSON.parse(await fsp.readFile(f, 'utf8'));
  const dir = path.dirname(f);
  const url = async (rel) => {
    if (typeof rel !== 'string' || !IMG.test(rel) || path.isAbsolute(rel)) return null; // relative image paths only
    const abs = path.resolve(dir, rel);
    return (await statOr(abs)) ? 'f' + abs : null;
  };
  await Promise.all(T.items.map(async (a) => {
    a.refs = await Promise.all((a.refs || []).map(async (r) => ({ label: r.label, crop: r.crop, url: await url(r.thumb) || await url(r.img), full: await url(r.img) })));
    a.now_url = await url(a.now_img); a.wip_url = await url(a.wip_img);
  }));
  return { ...T, id, file: f, mtime: (await statOr(f))?.mtimeMs };
}

// ---------------------------------------------------------------- geometry check (integrity.mjs)
const integrity = createIntegrity(CACHE);
// The GLB the viewer shows: the asset's own, or the dashboard's completed export of its .blend (never starts an export).
// A source with `renderFrom` (uncompressed build of a meshopt GLB) is checked from that: the checker cannot decode meshopt.
async function glbOf(cfg, it) {
  if (it.renderFrom) return it.renderFrom;
  if (it.glbPath) return it.glbPath;
  const src = it.blendPath && cfg.sources.find((s) => s.id === it.source);
  return src ? exportFresh(cfg, src, it) : null;
}
// LOD versions are compared with the next version up: far → mid, mid → near, near → the original (a GLB beside it, or the
// dashboard's export of the family's original .blend). Naming: <stem>.near/.mid/.far[.variant] or <stem>-near/-mid/-far.
const LOD_UP = { far: 'mid', mid: 'near', near: 'original' };
async function lodReference(cfg, it) {
  const m = it.key.match(/^(.+?)([.-])(near|mid|far)((?:\.[A-Za-z0-9_]+)*)$/);
  if (!m) return null;
  const [, stem, sep, level, suffix] = m, up = LOD_UP[level];
  const keys = [...new Set(up === 'original' ? [`${stem}${sep}original${suffix}`, `${stem}-original${suffix}`, `${stem}.original${suffix}`] : [`${stem}${sep}${up}${suffix}`])];
  const own = it.glbPath || it.blendPath, family = path.dirname(path.dirname(own)) + '/';
  for (const k of keys) {
    if (it.glbPath) { const f = path.join(path.dirname(it.glbPath), k + '.glb'); if (await statOr(f)) return { level: up, key: k, glb: f }; }
    for (const other of items.values()) {
      if (other.key !== k || other.host !== it.host || !(other.glbPath || other.blendPath || '').startsWith(family)) continue;
      const glb = await glbOf(cfg, other);
      return { level: up, key: k, id: other.id, glb, note: glb ? undefined : 'is a .blend not exported yet (open its card to export it)' };
    }
  }
  return null;
}
async function checkItem(cfg, it) {
  const glb = await glbOf(cfg, it);
  if (!glb) return { state: 'needs-export' };
  const ref = await lodReference(cfg, it);
  const r = await integrity.request(glb, ref, (record) => { const cur = items.get(it.id); if (cur) { cur.pub.integrity = integrity.badge(record); catalogResponseRevision++; } });
  if (r.state === 'done') { const cur = items.get(it.id); if (cur) { cur.pub.integrity = integrity.badge(r.result); catalogResponseRevision++; } }
  return { ...r, reference: ref ? { level: ref.level, key: ref.key, id: ref.id || null, exported: !!ref.glb } : null };
}

// ---------------------------------------------------------------- files (path-guarded)
const MIME = { '.glb': 'model/gltf-binary', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
  '.json': 'application/json', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.html': 'text/html; charset=utf-8',
  '.svg': 'image/svg+xml', '.wasm': 'application/wasm', '.bin': 'application/octet-stream', '.ktx2': 'image/ktx2' };
function allowedRoots() {
  const cfg = loadCfg();
  const r = [...cfg.sources, ...(cfg.todo || [])].map((s) => s.root.split('*')[0]);
  for (const h of Object.values(cfg.host_map || {})) r.push(toLocal(h, h.cache + '/'));
  r.push(CACHE + '/');
  r.push(...runRoots(cfg));
  return r;
}
async function sendFile(req, res, p, cache = 'no-cache') {
  const s = await statOr(p);
  if (!s || !s.isFile()) { res.writeHead(404); return res.end('not found'); }
  const etag = `"${s.size.toString(16)}-${Math.floor(s.mtimeMs).toString(16)}"`;
  if (req.headers['if-none-match'] === etag) { res.writeHead(304); return res.end(); }
  res.writeHead(200, { 'content-type': MIME[path.extname(p).toLowerCase()] || 'application/octet-stream', 'content-length': s.size, etag, 'cache-control': cache });
  // an unhandled stream error (EPERM on the flaky SSHFS mount) used to kill the whole server
  fs.createReadStream(p).on('error', () => res.destroy()).pipe(res);
}
// Only the small, local built UI uses this path. SSHFS reads can occupy every
// libuv filesystem worker; they must not keep HTML/JS/CSS from reaching a new tab.
// Local stat notices builds without a restart; unchanged files reuse their bytes.
const webFiles = new Map();
const wantsGzip = (req) => {
  const match = (req.headers['accept-encoding'] || '').match(/(?:^|,)\s*gzip(?:\s*;\s*q=([\d.]+))?\s*(?=,|$)/i);
  return !!match && (match[1] === undefined || +match[1] > 0);
};
function sendRepresentation(req, res, entry, type, cache) {
  const headers = { 'content-type': type, etag: entry.etag, 'cache-control': cache, vary: 'Accept-Encoding' };
  if ((req.headers['if-none-match'] || '').split(',').some(x => x.trim() === entry.etag || x.trim() === '*')) {
    res.writeHead(304, headers); return res.end();
  }
  let bytes = entry.bytes;
  if (wantsGzip(req) && (type.startsWith('text/') || type === 'application/json' || type === 'image/svg+xml')) {
    entry.gzip ||= gzipSync(bytes, { level: 1 });
    bytes = entry.gzip; headers['content-encoding'] = 'gzip';
  }
  res.writeHead(200, { ...headers, 'content-length': bytes.length }); res.end(bytes);
}
let catalogResponse = { items: null, revision: -1, variants: new Map() };
// The rail (label, emoji, folder, navLabel; README "Rail folders") follows config/sources.json at once, without waiting
// for a scan: the served sources are the config's, in its order, with the last scan's counts (0 for one not scanned yet).
let railCfg = { mtime: -1, sources: [] };
function railFor(scanned) {
  const m = fs.statSync(SOURCES, { throwIfNoEntry: false })?.mtimeMs ?? 0;
  if (railCfg.mtime !== m) { try { railCfg = { mtime: m, sources: loadCfg().sources || [] }; } catch { railCfg = { mtime: m, sources: [] }; } }
  if (!railCfg.sources.length) return { mtime: m, list: scanned };
  const byId = new Map(scanned.map((s) => [s.id, s]));
  return { mtime: m, list: railCfg.sources.map((c) => ({ ...(byId.get(c.id) || { id: c.id, host: c.host, project: c.project, count: 0 }),
    label: c.label, emoji: c.emoji, folder: c.folder, navLabel: c.navLabel })) };
}
function sendCatalog(req, res, value) {
  // Two wire representations per snapshot (refreshing / complete), built once.
  // Geometry results can update an item in place, so they invalidate this cache too; so does an edit of the rail's config.
  const rail = railFor(value.sources || []);
  if (catalogResponse.items !== value.items || catalogResponse.revision !== catalogResponseRevision || catalogResponse.rail !== rail.mtime)
    catalogResponse = { items: value.items, revision: catalogResponseRevision, rail: rail.mtime, variants: new Map() };
  const state = !!value.refreshing;
  let entry = catalogResponse.variants.get(state);
  if (!entry) {
    const bytes = Buffer.from(JSON.stringify({ ...value, sources: rail.list }));
    entry = { bytes, etag: `W/"${createHash('sha1').update(bytes).digest('base64url')}"` };
    catalogResponse.variants.set(state, entry);
  }
  return sendRepresentation(req, res, entry, 'application/json', 'private, no-cache');
}
function sendLocalFile(req, res, p, cache = 'no-cache') {
  const s = fs.statSync(p, { throwIfNoEntry: false });
  if (!s?.isFile()) { res.writeHead(404); return res.end('not found'); }
  const etag = `W/"${s.size.toString(16)}-${Math.floor(s.mtimeMs).toString(16)}"`;
  let entry = webFiles.get(p);
  if (!entry || entry.mtimeMs !== s.mtimeMs || entry.size !== s.size) {
    entry = { mtimeMs: s.mtimeMs, size: s.size, bytes: fs.readFileSync(p), etag };
    if (webFiles.size >= 32) webFiles.clear();
    webFiles.set(p, entry);
  }
  return sendRepresentation(req, res, entry, MIME[path.extname(p).toLowerCase()] || 'application/octet-stream', cache);
}
function sendWebFile(req, res, p) {
  if (!fs.statSync(p, { throwIfNoEntry: false })?.isFile()) p = path.join(DIST, 'index.html');
  return sendLocalFile(req, res, p, p.includes(`${path.sep}assets${path.sep}`) ? 'public, max-age=31536000, immutable' : 'no-cache');
}
const json = (res, code, o) => { res.writeHead(code, { 'content-type': 'application/json', 'cache-control': 'no-store' }); res.end(JSON.stringify(o)); };

// ---------------------------------------------------------------- http
const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://x');
  try {
    if (u.pathname === '/api/catalog') return sendCatalog(req, res, await getCatalog(u.searchParams.has('force'), true, true));
    if (u.pathname === '/api/live-spec') { // Shader Lab spec next to a GLB (its folder or the parent): web/src/livePrograms.ts
      const glb = '/' + decodeURIComponent((u.searchParams.get('glb') || '').split('?')[0].replace(/^\/?f\//, ''));
      const abs = path.resolve(glb);
      if (!allowedRoots().some(r => abs.startsWith(r))) return json(res, 403, { error: 'outside sources' });
      for (const dir of [path.dirname(abs), path.dirname(path.dirname(abs))]) {
        const spec = path.join(dir, 'shaders', 'spec.json');
        if (await fsp.access(spec).then(() => true, () => false)) return json(res, 200, { url: 'f' + spec, base: 'f' + path.join(dir, 'shaders') });
      }
      return json(res, 200, { url: null });
    }
    if (u.pathname.startsWith('/api/idle-library/')) { // the shader library's data (config idleLibrary): web/src/livePrograms.ts
      const lib = loadCfg().idleLibrary;
      if (!lib) return json(res, 404, { error: 'no idleLibrary in config' });
      const rel = decodeURIComponent(u.pathname.slice('/api/idle-library/'.length));
      const abs = path.resolve(lib, rel);
      if (!abs.startsWith(path.resolve(lib) + path.sep) || !/^(kinds\.json|idle-kinds\.glsl|tex\/[\w.-]+\.png)$/.test(rel)) return json(res, 403, { error: 'not a library data file' });
      return sendFile(req, res, abs);
    }
    if (u.pathname === '/api/runs') return json(res, 200, await getRuns(loadCfg(), CACHE, u.searchParams.has('force')));
    if (u.pathname === '/api/thumbnail') {
      const input = new URL(u.searchParams.get('src') || '', 'http://x/');
      if (input.origin !== 'http://x' || !input.pathname.startsWith('/f/')) return json(res, 400, { error: 'a local asset image is required' });
      const p = path.resolve(decodeURIComponent(input.pathname.slice(2)));
      if (!allowedRoots().some(r => p.startsWith(r)) && !runPictureAllowed(p)) return json(res, 403, { error: 'outside sources' });
      const stamp = { mtimeMs: Number(input.searchParams.get('v')), size: Number(u.searchParams.get('bytes')) };
      try { return sendLocalFile(req, res, await imageThumbnail(p, CACHE, u.searchParams.get('w'), stamp), 'private, max-age=86400'); }
      catch (e) { return json(res, e.status || (e.code === 'ENOENT' ? 404 : 500), { error: e.message }); }
    }
    if (u.pathname === '/api/integrity') {
      if (!items.has(u.searchParams.get('id') || '')) await getCatalog(false, false);
      const it = items.get(u.searchParams.get('id') || '');
      if (!it) return json(res, 404, { error: 'unknown id' });
      return json(res, 200, await checkItem(loadCfg(), it));
    }
    if (u.pathname === '/api/todo') {
      await getCatalog();
      const doc = await todoDoc(u.searchParams.get('id') || '');
      return doc ? json(res, 200, doc) : json(res, 404, { error: 'unknown to-do id' });
    }
    if (u.pathname === '/api/port' || u.pathname === '/api/rerender') {
      // A known selection refreshes its own source/export stamps below. It need
      // not wait for an unrelated collection's slow discovery. Cold/unknown ids
      // still await discovery, preserving selected-export queue priority.
      if (!items.has(u.searchParams.get('id') || '')) await getCatalog(false, false);
      const it = items.get(u.searchParams.get('id') || '');
      if (!it) return json(res, 404, { error: 'unknown id' });
      const cfg = loadCfg(); const src = cfg.sources.find((s) => s.id === it.source);
      if (it.blendPath && !it.glbPath) {
        const stamp = await exportStamp(it.blendPath, await statOr(it.blendPath), src);
        if (stamp !== it.exportStamp) { it.exportStamp = stamp; catalogDirty = true; }
      }
      if (u.pathname === '/api/rerender') {
        await fsp.rm(renderPath(src, it.group, it.key, it.exportStamp), { force: true });
        await ensureRender(cfg, src, it); catalogDirty = true;
        return json(res, 200, { state: 'queued' });
      }
      if (it.glbPath) {
        const stat = await statOr(it.glbPath);
        if (!stat) return json(res, 404, { error: 'asset file no longer exists' });
        return json(res, 200, { state: 'done', glb: 'f' + it.glbPath + '?v=' + stat.mtimeMs });
      }
      if (!it.blendPath) return json(res, 400, { error: 'nothing to port' });
      const ex = await ensureExport(cfg, src, it, true);
      // a viewer export that finishes gets its geometry check at once (the viewer asks for it anyway; this saves the wait)
      if (ex.job && !ex.job.integrityHook) { ex.job.integrityHook = true; const snap = { ...it }; ex.job.promise?.then((j) => { if (j.state === 'done') checkItem(cfg, snap).catch(() => {}); }); }
      if (!ex.job) return json(res, 200, { state: 'done', glb: 'f' + ex.path + '?v=' + (await statOr(ex.path))?.mtimeMs });
      if (ex.job.state === 'done') return json(res, 200, { state: 'done', glb: 'f' + ex.path + '?v=' + (await statOr(ex.path))?.mtimeMs });
      catalogDirty = true;
      return json(res, 200, { state: ex.job.state, err: ex.job.err });
    }
    if (u.pathname.startsWith('/f/')) {
      const p = path.resolve(decodeURIComponent(u.pathname.slice(2)));
      if (!allowedRoots().some((r) => p.startsWith(r)) && !runPictureAllowed(p)) { res.writeHead(403); return res.end('outside sources'); }
      return sendFile(req, res, p);
    }
    let p = path.join(DIST, path.normalize(decodeURIComponent(u.pathname)).replace(/^([/\\])+/, ''));
    if (!p.startsWith(DIST)) { res.writeHead(403); return res.end(); }
    return sendWebFile(req, res, p);
  } catch (e) {
    console.error(e); if (!res.headersSent) json(res, 500, { error: String(e.message || e) });
  }
});

// keep the build box's copy of the export script current (written through the SSHFS mount)
function installExporter(destination) {
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  const source = fs.readFileSync(path.join(ROOT, 'blender', 'export_blend.py'));
  if (createHash('sha1').update(source).digest('hex').slice(0, 8) !== EXPORT_VER) throw new Error('Exporter changed during startup');
  if (fs.existsSync(destination) && createHash('sha1').update(fs.readFileSync(destination)).digest('hex').slice(0, 8) === EXPORT_VER) return;
  const temporary = destination + '.' + process.pid + '.tmp';
  fs.writeFileSync(temporary, source); fs.renameSync(temporary, destination);
}
try {
  installExporter(LOCAL_EXPORT_SCRIPT);
  for (const h of Object.values(loadCfg().host_map || {})) {
    const d = toLocal(h, h.cache); fs.mkdirSync(d, { recursive: true });
    installExporter(path.join(d, `export_${EXPORT_VER}.py`));
  }
} catch (e) { console.error('host cache setup:', e.message); }

server.listen(PORT, HOST, () => console.log(`blender-dash on http://${HOST}:${PORT}/`));
