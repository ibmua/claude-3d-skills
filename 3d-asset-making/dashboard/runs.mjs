// Runs view (owner 2026-10-12 22:47: "report as progress goes to some dashboard so I can see api use, progress, etc.").
// A run = a folder under a config `runs[].root` glob that holds progress.jsonl (writer: skill 3d-asset-making
// scripts/report.py). Its API cost comes from the Claude Code transcripts of the run (parent + subagent builders),
// priced with Claude Cost's table. Everything is computed on request; transcripts are read incrementally (byte offset +
// parsed messages per file), so a repeated page load reads only appended bytes. No timers. See README.md "Runs".
import fsp from 'node:fs/promises';
import path from 'node:path';

const ACTIVE_MS = 10 * 60_000;          // "running" = any activity in the last 10 min
const RESULT_TTL = 10_000;              // one computation per 10 s, however many tabs poll
const PRICES_URL = process.env.PRICES_URL || 'http://127.0.0.1:8799/api/prices';
const PRICES_TTL = 10 * 60_000;

// ---------------------------------------------------------------- small helpers
const globRe = (g) => new RegExp('^' + g.split('*').map((s) => s.replace(/[.+?^${}()|[\]\\]/g, '\\$&')).join('[^/]*') + '$');
const readJson = (p) => fsp.readFile(p, 'utf8').then(JSON.parse).catch(() => null);
const statOr = (p) => fsp.stat(p).catch(() => null);
// a remote host's paths -> its local mount (config host_map); local paths stay
function localPath(cfg, p) {
  if (typeof p !== 'string' || !p) return null;
  for (const h of Object.values(cfg.host_map || {})) if (p.startsWith(h.remote_prefix)) return h.local_prefix + p.slice(h.remote_prefix.length);
  return p;
}
const tsOf = (v) => { const t = typeof v === 'number' ? v : Date.parse(v); return Number.isFinite(t) ? t : null; };

// ---------------------------------------------------------------- incremental jsonl reader
// state per file: {offset, ino, ...parser state}; reads [offset, size) and parses only whole lines
const files = new Map();
async function readAppended(file, init, onLine) {
  const st = await statOr(file);
  if (!st) return files.get(file)?.state || null;
  let f = files.get(file);
  if (!f || st.size < f.offset || (f.ino && st.ino !== f.ino)) { f = { offset: 0, ino: st.ino, state: init() }; files.set(file, f); }
  if (st.size > f.offset) {
    let h;
    try {
      h = await fsp.open(file, 'r');
      const CHUNK = 8 << 20;
      while (f.offset < st.size) {
        const len = Math.min(CHUNK, st.size - f.offset), buf = Buffer.alloc(len);
        const { bytesRead } = await h.read(buf, 0, len, f.offset);
        if (!bytesRead) break;
        const end = buf.lastIndexOf(10, bytesRead - 1);          // only whole lines; a half-written tail waits
        if (end < 0) { if (len === CHUNK) { f.offset += bytesRead; continue; } break; }
        for (const line of buf.subarray(0, end).toString('utf8').split('\n')) if (line) onLine(line, f.state);
        f.offset += end + 1;
      }
    } catch { /* flaky SSHFS: keep what we have, retry on the next request */ } finally { await h?.close(); }
  }
  f.mtime = st.mtimeMs;
  return f.state;
}

// Claude Code transcript: one API message spans several lines (one per content block); keep each message id's last usage
const transcriptInit = () => ({ msgs: new Map(), first: null, last: null });
function transcriptLine(sidechainSkip) {
  return (line, s) => {
    if (!line.includes('"usage"') || !line.includes('"assistant"')) {
      const m = line.match(/"timestamp":"([^"]+)"/); const t = m && tsOf(m[1]);
      if (t) { s.first ??= t; s.last = Math.max(s.last || 0, t); }
      return;
    }
    let r; try { r = JSON.parse(line); } catch { return; }
    const t = tsOf(r.timestamp); if (t) { s.first ??= t; s.last = Math.max(s.last || 0, t); }
    if (r.type !== 'assistant' || (sidechainSkip && r.isSidechain)) return;
    const m = r.message; if (!m?.usage || m.model === '<synthetic>') return;
    s.msgs.set(m.id || r.uuid, { u: m.usage, model: m.model, t });
  };
}
const readTranscript = (file, isParent) => readAppended(file, transcriptInit, transcriptLine(isParent));

// ---------------------------------------------------------------- prices (Claude Cost /api/prices, USD per million)
let prices = null, pricesAt = 0, pricesErr = null;
async function getPrices(cacheDir) {
  if (prices && Date.now() - pricesAt < PRICES_TTL) return prices;
  const file = path.join(cacheDir, 'prices.json');
  try {
    const r = await fetch(PRICES_URL, { signal: AbortSignal.timeout(4000) });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    prices = await r.json(); pricesAt = Date.now(); pricesErr = null;
    fsp.writeFile(file + '.tmp', JSON.stringify(prices)).then(() => fsp.rename(file + '.tmp', file)).catch(() => {});
  } catch (e) {
    pricesErr = `Claude Cost prices unavailable (${e.message}); ${prices ? 'using the last table read' : 'using the cached copy'}`;
    prices ||= await readJson(file); pricesAt = Date.now() - PRICES_TTL + 60_000;   // retry in a minute
  }
  return prices;
}
function priceOf(table, model) {
  if (!model || !table?.claude) return null;
  const k = String(model).replace(/\[.*\]$/, '').replace(/-\d{8}$/, '');
  return table.claude[k] || null;
}

// ---------------------------------------------------------------- one run's transcripts
const metaCache = new Map();
async function subagentLabel(file) {
  if (!metaCache.has(file)) metaCache.set(file, readJson(file.replace(/\.jsonl$/, '.meta.json')).then((m) => m?.description || null));
  return metaCache.get(file);
}
const rawSid = new Map();   // raw-<n>.jsonl -> session id (from its first lines; a raw file never changes session)
async function sessionOfRaw(file) {
  if (rawSid.has(file)) return rawSid.get(file);
  let h, sid = null;
  try { h = await fsp.open(file, 'r'); const buf = Buffer.alloc(8192); const { bytesRead } = await h.read(buf, 0, 8192, 0); sid = buf.subarray(0, bytesRead).toString().match(/"session_id":\s*"([0-9a-f-]{36})"/)?.[1] || null; }
  catch { } finally { await h?.close(); }
  if (sid) rawSid.set(file, sid);
  return sid;
}
const homesMemo = { at: 0, v: [] };
async function accountHomes(cfg, rc) {
  if (Date.now() - homesMemo.at < 60_000) return homesMemo.v;
  const homes = new Set((rc.homes || []).map((h) => localPath(cfg, h)));
  const d = rc.dispatch && await readJson(rc.dispatch);
  for (const a of Object.values(d?.accounts || {})) if (a?.home) homes.add(localPath(cfg, a.home));
  homesMemo.at = Date.now(); homesMemo.v = [...homes].filter(Boolean);
  return homesMemo.v;
}
// which transcript files belong to a run: run.json `transcripts` (explicit), else every session the dispatcher started
// (RUN.json session_id + each raw-<n>.jsonl's session) looked up in every account home (sessions move between logins)
async function runTranscripts(cfg, rc, dir, names, meta) {
  const out = [];
  const add = async (file, role) => { if (await statOr(file)) out.push({ file, role, label: role === 'builder' ? (await subagentLabel(file)) || path.basename(file, '.jsonl') : 'lead' }); };
  if (Array.isArray(meta.local?.transcripts)) {
    for (const t of meta.local.transcripts) { const p = localPath(cfg, t); if (p) await add(p, /\/subagents\/agent-[^/]+\.jsonl$/.test(p) ? 'builder' : 'parent'); }
    return out;
  }
  const sids = new Set([meta.dispatch?.session_id].filter(Boolean));
  for (const n of names) if (/^raw-\d+\.jsonl$/.test(n)) { const s = await sessionOfRaw(path.join(dir, n)); if (s) sids.add(s); }
  meta.sessions = [...sids];
  if (!sids.size) return out;
  const slug = rc.slug;
  for (const home of await accountHomes(cfg, rc)) {
    for (const sid of sids) {
      const base = path.join(home, 'projects', slug, sid);
      await add(base + '.jsonl', 'parent');
      let subs = []; try { subs = await fsp.readdir(path.join(base, 'subagents')); } catch { }
      for (const n of subs) if (/^agent-.*\.jsonl$/.test(n)) await add(path.join(base, 'subagents', n), 'builder');
    }
  }
  return out;
}

const tokKinds = ['in', 'cw', 'cw1h', 'cr', 'out'];
// time (owner 2026-10-12 22:59: "should remember time"): wall = first to last activity; active = sum of the gaps between
// consecutive API calls, a gap over IDLE_GAP counting as idle (limit pauses, waits for the owner, nights)
const IDLE_GAP = 10 * 60_000;
function activeMs(ts) {
  const t = [...ts].sort((a, b) => a - b); let a = 0;
  for (let i = 1; i < t.length; i++) { const g = t[i] - t[i - 1]; if (g <= IDLE_GAP) a += g; }
  return a;
}
const h3 = (ms) => +(ms / 3.6e6).toFixed(3);
// active time inside [a, b]: the overlap of each busy gap (consecutive calls <= IDLE_GAP apart) with the window; pts sorted
function activeIn(pts, a, b) {
  let x = 0;
  for (let i = 1; i < pts.length; i++) {
    const s = pts[i - 1][0], e = pts[i][0]; if (e - s > IDLE_GAP || e <= a || s >= b) continue;
    x += Math.min(e, b) - Math.max(s, a);
  }
  return x;
}
const tokOf = (u) => ({ in: u.input_tokens || 0, cw: u.cache_creation_input_tokens || 0, cr: u.cache_read_input_tokens || 0, out: u.output_tokens || 0,
  cw1h: Math.min(u.cache_creation?.ephemeral_1h_input_tokens || 0, u.cache_creation_input_tokens || 0) });
// The canonical usd prices each cache write by its own TTL, as Claude Cost does: the usage splits 1h writes out
// (ephemeral_1h_input_tokens) and those are billed at pr.cw1h (2x base input; 2x in when the table has no cw1h). The rest
// (5-minute writes) bill at pr.cw. Main threads on a subscription write the 1h cache; this reproduces the CLI's own
// total_cost_usd (fix-train-cab: $57.9623 reported, $57.9646 here). Subagents use the 5-minute TTL: priced at pr.cw.
const usdOf = (tk, pr) => (tk.in * pr.in + (tk.cw - tk.cw1h) * pr.cw + tk.cw1h * (pr.cw1h ?? 2 * pr.in) + tk.cr * pr.cr + tk.out * pr.out) / 1e6;
function costRun(parts, table) {
  // dedupe by message id across all files of the run (a session copied to another login holds the same messages);
  // a builder's file wins the attribution
  const seen = new Map();
  for (const p of parts) for (const [id, m] of p.state?.msgs || []) if (!seen.has(id) || p.role === 'builder') seen.set(id, { ...m, part: p });
  const sum = () => ({ usd: 0, calls: 0, tokens: { in: 0, cw: 0, cw1h: 0, cr: 0, out: 0 }, unpriced: { calls: 0, tokens: 0, models: [] }, first: null, last: null });
  const total = sum(), by = new Map(), byModel = new Map(), points = [];
  for (const m of seen.values()) {
    const key = m.part.role === 'builder' ? m.part.file : 'lead';
    if (!by.has(key)) by.set(key, { ...sum(), role: m.part.role, label: m.part.label, file: m.part.file });
    if (!byModel.has(m.model)) byModel.set(m.model, { ...sum(), model: m.model });
    const tk = tokOf(m.u), pr = priceOf(table, m.model);
    for (const s of [total, by.get(key), byModel.get(m.model)]) {
      s.calls++; for (const k of tokKinds) s.tokens[k] += tk[k];
      if (m.t) { s.first = Math.min(s.first ?? m.t, m.t); s.last = Math.max(s.last ?? 0, m.t); }
      if (pr) s.usd += usdOf(tk, pr);
      else { s.unpriced.calls++; s.unpriced.tokens += tk.in + tk.cw + tk.cr + tk.out; if (!s.unpriced.models.includes(m.model)) s.unpriced.models.push(m.model); }
    }
    if (m.t) { const p = [m.t, pr ? usdOf(tk, pr) : 0]; points.push(p); (by.get(key).pts ||= []).push(p); (byModel.get(m.model).pts ||= []).push(p); }
  }
  // cumulative cost over the run's span, 40 bins
  let spark = [];
  if (points.length && total.first != null && total.last > total.first) {
    const N = 40, w = (total.last - total.first) / N, bins = new Array(N).fill(0);
    for (const [t, usd] of points) bins[Math.min(N - 1, Math.floor((t - total.first) / w))] += usd;
    let acc = 0; spark = bins.map((v) => +(acc += v).toFixed(4));
  }
  // active hours: gaps between consecutive API calls up to 15 min count (limit pauses and idle nights do not)
  points.sort((a, b) => a[0] - b[0]);
  for (const s of [total, ...by.values(), ...byModel.values()]) {
    const pts = s === total ? points : s.pts || [];
    s.activeHours = h3(activeMs(pts.map((p) => p[0])));
    s.wallHours = s.first != null && s.last != null ? h3(s.last - s.first) : null;
    s.perActiveHour = s.activeHours > 0.02 && s.usd ? +(s.usd / s.activeHours).toFixed(2) : null;
    delete s.pts;
  }
  const round = (s) => ({ ...s, usd: +s.usd.toFixed(4) });
  const builders = [...by.values()].map(round).sort((a, b) => (a.role === 'parent' ? -1 : b.role === 'parent' ? 1 : b.usd - a.usd));
  return { ...round(total), spark, parts: builders, models: [...byModel.values()].map(round), points };
}

// ---------------------------------------------------------------- image ledger (Codex image calls: counted, unpriced)
const ledgerInit = () => ({ rows: [] });
const ledgerLine = (line, s) => { try { const r = JSON.parse(line); s.rows.push({ run: r.run || '', where: `${r.cwd || ''} ${r.out || ''}`, ok: r.status === 'OK', n: +r.images || (r.status === 'OK' ? 1 : 0), t: tsOf(r.at) }); } catch { } };
function imagesOf(ledger, name, match = []) {
  const keys = [`/runs/${name}/`, ...match];
  let images = 0, calls = 0, failed = 0, last = null;
  for (const r of ledger?.rows || []) {
    if (r.run !== name && !keys.some((k) => r.where.includes(k))) continue;
    calls++; images += r.ok ? r.n : 0; if (!r.ok) failed++; if (r.t) last = Math.max(last || 0, r.t);
  }
  return calls ? { images, calls, failed, last } : null;
}

// ---------------------------------------------------------------- progress events
const progressInit = () => ({ events: [] });
const progressLine = (line, s) => { try { const e = JSON.parse(line); if (e && typeof e.kind === 'string') s.events.push(e); } catch { } };

export const pictureFiles = new Set();     // exact picture files named by progress events: the /f/ guard serves these too
function pictureUrl(cfg, dir, p) {
  if (typeof p !== 'string' || !p) return null;
  const abs = localPath(cfg, path.isAbsolute(p) ? p : path.join(dir, p));
  if (!/\.(png|jpe?g|webp)$/i.test(abs)) return null;
  pictureFiles.add(path.resolve(abs));
  return 'f' + abs;
}

function stateOf(meta, events, lastActivity, now) {
  const last = events[events.length - 1];
  const ds = String(meta.local?.state || meta.dispatch?.state || '').toLowerCase();
  if (last?.kind === 'done' || ds === 'done') return 'done';
  if (ds === 'failed') return 'failed';
  if (ds === 'blocked' || ds === 'limited') return 'blocked';
  if (lastActivity && now - lastActivity < ACTIVE_MS && ds !== 'limited') return 'running';
  if (last?.kind === 'blocked' || ds === 'limited' || ds === 'blocked') return 'blocked';
  if (ds === 'running' && lastActivity && now - lastActivity < ACTIVE_MS) return 'running';
  return 'idle';
}

async function oneRun(cfg, rc, dir, table, ledger, limited) {
  const name = path.basename(dir);
  let names = []; try { names = await fsp.readdir(dir); } catch { }
  const [dispatch, local] = await Promise.all([names.includes('RUN.json') ? readJson(path.join(dir, 'RUN.json')) : null, names.includes('run.json') ? readJson(path.join(dir, 'run.json')) : null]);
  const meta = { dispatch, local };
  const pick = (k) => local?.[k] ?? dispatch?.[k] ?? null;
  const prog = await readAppended(path.join(dir, 'progress.jsonl'), progressInit, progressLine);
  const events = prog?.events || [];
  const tfiles = await runTranscripts(cfg, rc, dir, names, meta);
  const parts = await Promise.all(tfiles.map(async (t) => ({ ...t, state: await readTranscript(t.file, t.role === 'parent') })));
  const runPrices = local?.pricesFile ? await readJson(localPath(cfg, local.pricesFile)) : null;
  const cost = costRun(parts, runPrices || table);
  const runLedger = local?.imgLedger ? await readAppended(localPath(cfg, local.imgLedger), ledgerInit, ledgerLine) : ledger;
  const images = imagesOf(runLedger, name, local?.images_match || []);
  const evT = events.map((e) => tsOf(e.ts)).filter(Boolean);
  const transcriptLast = Math.max(0, ...parts.map((p) => p.state?.last || 0));
  const lastEvent = evT.length ? Math.max(...evT) : null;
  const lastActivity = Math.max(lastEvent || 0, transcriptLast, images?.last || 0) || null;
  const firsts = [evT.length ? Math.min(...evT) : null, cost.first, dispatch?.started_kyiv ? tsOf(dispatch.started_kyiv.replace(' ', 'T') + '+03:00') : null].filter(Boolean);
  const firstActivity = firsts.length ? Math.min(...firsts) : null;
  const now = Date.now();
  const lastOf = (pred) => { for (let i = events.length - 1; i >= 0; i--) if (pred(events[i])) return events[i]; return null; };
  const latestRound = lastOf((e) => e.kind === 'round' && e.picture) || lastOf((e) => e.picture);
  const rounds = new Set(events.filter((e) => e.kind === 'round').map((e, i) => e.round ?? 'i' + i));
  // per round: from the previous round event (or the run's start) to this one; its API time and $ from the calls inside
  const pts = cost.points; delete cost.points;
  const slice = (a, b) => pts.filter((p) => p[0] > a && p[0] <= b);
  const roundEv = events.filter((e) => e.kind === 'round' && tsOf(e.ts)).map((e) => ({ e, t: tsOf(e.ts) })).sort((a, b) => a.t - b.t);
  const startT = Math.min(...[evT.length ? Math.min(...evT) : Infinity, cost.first ?? Infinity]);
  const roundTimes = roundEv.map(({ e, t }, i) => {
    const from = i ? roundEv[i - 1].t : startT, inside = Number.isFinite(from) ? slice(i ? from : from - 1, t) : [];
    return { round: e.round ?? i + 1, ts: e.ts, wallHours: Number.isFinite(from) ? h3(t - from) : null, activeHours: Number.isFinite(from) ? h3(activeIn(pts, from, t)) : null, usd: +inside.reduce((s, p) => s + p[1], 0).toFixed(4) };
  });
  const meanRoundH = roundTimes.length ? h3(roundTimes.reduce((s, r) => s + (r.wallHours || 0), 0) * 3.6e6 / roundTimes.length) : null;
  // per asset / component: first to last event naming it (a component reported once has no span)
  const byAsset = new Map();
  for (const e of events) { const t = tsOf(e.ts); if (!e.asset || !t) continue; const a = byAsset.get(e.asset) || { asset: e.asset, first: t, last: t, events: 0, kinds: new Set() }; a.first = Math.min(a.first, t); a.last = Math.max(a.last, t); a.events++; a.kinds.add(e.kind); byAsset.set(e.asset, a); }
  const assetTimes = [...byAsset.values()].map((a) => ({ asset: a.asset, events: a.events, component: a.kinds.has('component'), first: a.first, last: a.last, wallHours: h3(a.last - a.first) })).sort((a, b) => b.wallHours - a.wallHours || a.first - b.first);
  const luna = events.filter((e) => typeof e.luna === 'number').map((e) => ({ round: e.round ?? null, luna: e.luna, ts: e.ts }));
  const spanH = firstActivity && lastActivity ? (lastActivity - firstActivity) / 3.6e6 : null;
  return {
    id: rc.id + ':' + name, name, source: rc.id, project: rc.project, host: rc.host, dir,
    title: pick('title'), family: pick('family'), asset: pick('asset') || lastOf((e) => e.asset)?.asset || null,
    model: pick('model'), effort: pick('effort'), account: pick('account'), test: local?.test || null, arm: local?.arm || null,
    backfilled: local?.backfilled || null, dispatched: !!dispatch,
    attempts: dispatch?.attempts ?? null, sessions: meta.sessions?.length ?? null,
    // a dispatcher run stopped by a usage limit continues (often as a fresh session) once the account's window resets:
    // ops/limited-until.json {email: {until, seen}} (opus_dispatch.py mark_limited) + RUN.json state 'limited'
    limit: String(pick('state') || '').toLowerCase() === 'limited' ? { text: dispatch?.limit_text || null, until: (() => { const m = limited?.[pick('account')]; return m?.until ? m.until * 1000 : null; })() } : null,
    state: stateOf(meta, events, lastActivity, now), lastEvent, lastActivity, firstActivity, hours: spanH,
    stage: lastOf((e) => e.stage)?.stage || null,
    latest: latestRound && { url: pictureUrl(cfg, dir, latestRound.picture), round: latestRound.round ?? null, ts: latestRound.ts, msg: latestRound.msg },
    luna, bestLuna: luna.length ? Math.max(...luna.map((l) => l.luna)) : null,
    time: {
      wallHours: firstActivity && lastActivity ? h3(lastActivity - firstActivity) : null, activeHours: cost.activeHours,
      perActiveHour: cost.perActiveHour, meanRoundHours: meanRoundH, rounds: roundTimes, assets: assetTimes.slice(0, 80),
      hoursToLuna7: (() => { const e = events.find((x) => typeof x.luna === 'number' && x.luna >= 7); const t = e && tsOf(e.ts); return t && firstActivity ? h3(t - firstActivity) : null; })(),
      activeHoursToLuna7: (() => { const e = events.find((x) => typeof x.luna === 'number' && x.luna >= 7); const t = e && tsOf(e.ts); return t && pts.length ? h3(activeIn(pts, pts[0][0], t)) : null; })(),
    },
    counts: { events: events.length, components: events.filter((e) => e.kind === 'component').length, rounds: rounds.size, exports: events.filter((e) => e.kind === 'export').length, blocked: events.filter((e) => e.kind === 'blocked').length },
    cost: { ...cost, perHour: cost.perActiveHour, transcripts: tfiles.length },
    images,
    events: events.slice(-200).reverse().map((e) => ({ ts: e.ts, kind: e.kind, msg: e.msg, asset: e.asset, stage: e.stage, round: e.round, luna: e.luna, builder: e.builder, data: e.data, backfilled: e.backfilled || undefined, picture: pictureUrl(cfg, dir, e.picture) })),
  };
}

// ---------------------------------------------------------------- API
let result = null, resultAt = 0, computing = null;
async function compute(cfg, cacheDir) {
  const t0 = Date.now();
  const table = await getPrices(cacheDir);
  const runs = [], errors = [];
  for (const rc of cfg.runs || []) {
    try {
      const ledger = rc.imgLedger ? await readAppended(rc.imgLedger, ledgerInit, ledgerLine) : null;
      const limited = rc.limitedUntil ? await readJson(rc.limitedUntil) : null;
      const segs = rc.root.split('/'), i = segs.findIndex((s) => s.includes('*'));
      let dirs = [rc.root];
      if (i >= 0) {
        const parent = segs.slice(0, i).join('/'), re = globRe(segs[i]);
        const ents = await fsp.readdir(parent, { withFileTypes: true });
        dirs = ents.filter((e) => (e.isDirectory() || e.isSymbolicLink()) && re.test(e.name)).map((e) => [parent, e.name, ...segs.slice(i + 1)].join('/'));
      }
      const has = await Promise.all(dirs.map((d) => statOr(path.join(d, 'progress.jsonl'))));
      const live = dirs.filter((d, k) => has[k]);
      runs.push(...await Promise.all(live.map((d) => oneRun(cfg, rc, d, table, ledger, limited).catch((e) => ({ id: rc.id + ':' + path.basename(d), name: path.basename(d), source: rc.id, err: String(e.message || e) })))));
    } catch (e) { errors.push({ source: rc.id, err: String(e.message || e) }); }
  }
  const order = { running: 0, blocked: 1, idle: 2, failed: 3, done: 4 };
  runs.sort((a, b) => (order[a.state] ?? 5) - (order[b.state] ?? 5) || (b.lastActivity || 0) - (a.lastActivity || 0));
  return { generated: Date.now(), ms: Date.now() - t0, prices: { from: PRICES_URL, err: pricesErr, ok: !!table }, sources: (cfg.runs || []).map((r) => ({ id: r.id, label: r.label, project: r.project, host: r.host })), errors, runs };
}
export async function getRuns(cfg, cacheDir, force = false) {
  if (!force && result && Date.now() - resultAt < RESULT_TTL) return result;
  computing ||= compute(cfg, cacheDir).then((r) => { result = r; resultAt = Date.now(); return r; }).finally(() => { computing = null; });
  return computing;
}
// /f/ guard: run folders (the part of each root before '*') and the exact pictures events name
export function runRoots(cfg) { return (cfg.runs || []).map((r) => r.root.split('*')[0]); }
export const runPictureAllowed = (p) => pictureFiles.has(p);
