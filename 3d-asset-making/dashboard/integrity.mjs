// Geometry check per GLB (owner 2026-10-12: "how they can avoid stuff like in <that link>"): runs the 3d-modelling skill's
// mesh_integrity.py on demand only (an asset opened in the viewer, or a viewer export that just finished), never as a sweep.
// Results are cached in cache/integrity/<sha1(glb path)>.json keyed by the GLB's path + mtime + size; the catalog shows the
// cached badge, the viewer asks /api/integrity for the full report. The checker's verdict is never changed here: exit 0 =
// sound, RESULT "FAULT" = fault, any other exit 1 = look (a pointer), exit 2 = unreadable. See README "Geometry check".
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';

export const CHECKER = process.env.MESH_INTEGRITY || new URL('../../3d-modelling/scripts/mesh_integrity.py', import.meta.url).pathname;
const SLOTS = 2;                       // at most two checks at once, under nice
const TIMEOUT = 15 * 60_000;           // under a minute even on a 371k-triangle assembly since 2026-10-13 (was ~5 min); a stuck run is killed
const RETRY_ERROR = 10 * 60_000;       // a failed run is retried on a later open after 10 min
const VERSION = 1;                     // record format

const TRIPLE = /\((-?\d+(?:\.\d+)?), (-?\d+(?:\.\d+)?), (-?\d+(?:\.\d+)?)\)/g;
// one place (point, or box with its centre) from a detail line such as "floating 1: …, centre (0.000, 0.482, 0.250), …",
// "gap 2: 1.4 mm near (…)", "blinks, place 1: … at (…)", "lost region 1 of 28: … from (…) to (…)"
export function placeOf(line) {
  const t = [...line.matchAll(TRIPLE)].map((m) => [+m[1], +m[2], +m[3]]);
  if (!t.length) return null;
  const label = line.split(':')[0].trim();
  if (t.length >= 2 && /from \(/.test(line) && / to \(/.test(line)) {
    const [min, max] = t;
    return { label, at: min.map((v, i) => +((v + max[i]) / 2).toFixed(4)), min, max };
  }
  const across = line.match(/([\d.]+) m across/);
  return { label, at: t[0], ...(across ? { size: +across[1] } : {}) };
}

// The printed report → sections (one per top-level line: BODIES, OPEN EDGES, NON-MANIFOLD, WATERTIGHT, LOOKED INTO, GAPS,
// FLICKER, AGAINST, LOOK, RESULT, NOTE, WARNING) with their detail lines and places. The text is the checker's own wording,
// shown as is. Section names may hold a hyphen (NON-MANIFOLD).
export function parseReport(text) {
  const lines = String(text || '').split('\n');
  const sections = []; let cur = null;
  for (const line of lines.slice(1)) {
    const m = line.match(/^ {2}([A-Z][A-Z-]+(?: [A-Z-]+)*)(?=[: ])[: ]\s*(.*)$/);
    if (m) { cur = { kind: m[1], text: m[2], details: [], places: [] }; sections.push(cur); continue; }
    if (cur && /^ {4,}\S/.test(line)) { const d = line.trim(); cur.details.push(d); const p = placeOf(d); if (p) cur.places.push(p); }
  }
  return { header: lines[0] || '', sections };
}

export function statusOf(exit, verdict) {
  if (exit === 0) return 'sound';
  if (exit === 2) return 'unreadable';
  return /^FAULT/.test(verdict || '') ? 'fault' : 'look';
}

// The short fault for the card: "2 floating · 12 % open", "20 blink · 3 slits", "1 inside out". Counts come from the checker's
// JSON. Order = weight: FAULTs first (floating, inside out, blink), then LOOKs (slits, turned faces, lost, open).
export function shortFault(j, status) {
  if (status === 'sound') return '';
  if (status === 'unreadable') return 'unreadable';
  if (!j) return status;
  const out = [];
  const floating = (j.bodies?.length || 1) - 1;
  if (floating > 0) out.push(`${floating} floating`);
  const inside = j.non_manifold?.inside_out_parts;
  if (inside) out.push(`${inside} inside out`);
  if (j.flicker?.same_facing_pairs) out.push(`${j.flicker.same_facing_pairs} blink`);
  if (j.gap_count) out.push(`${j.gap_count} slit${j.gap_count === 1 ? '' : 's'}`);
  const turned = j.non_manifold?.turned_edges;
  if (turned) out.push(`${turned} turned`);
  const lost = j.against?.reference_seen_lost_share;
  if (lost > 0.15) out.push(`${Math.round(lost * 100)} % lost`);
  if (j.open_share >= 0.05) out.push(`${Math.round(j.open_share * 100)} % open`);
  return out.slice(0, 3).join(' · ') || status;
}

// Double-sided materials make back-to-back face pairs blink too (the checker reports them but cannot see materials).
export async function doubleSidedMaterials(glb) {
  let h;
  try {
    h = await fsp.open(glb, 'r');
    const head = Buffer.alloc(20); await h.read(head, 0, 20, 0);
    if (head.toString('latin1', 0, 4) !== 'glTF') return null;
    const n = head.readUInt32LE(12); if (n > 64 * 1024 * 1024) return null;
    const buf = Buffer.alloc(n); await h.read(buf, 0, n, 20);
    const mats = JSON.parse(buf.toString('utf8')).materials || [];
    return mats.filter((m) => m?.doubleSided).length;
  } catch { return null; } finally { await h?.close(); }
}

const sha1 = (s) => createHash('sha1').update(s).digest('hex');

export function createIntegrity(cacheRoot, { checker = CHECKER, python = process.env.INTEGRITY_PYTHON || 'python3' } = {}) {
  const dir = path.join(cacheRoot, 'integrity');
  const records = new Map();                       // glb path -> latest record (loaded once; written on every finish)
  try {
    for (const f of fs.readdirSync(dir)) if (f.endsWith('.json')) {
      try { const r = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')); if (r.v === VERSION && r.glb) records.set(r.glb, r); } catch { }
    }
  } catch { }
  const jobs = new Map();                          // job key -> {state, err, t1, promise}
  const queue = []; let running = 0;
  let checkerMemo = { mtimeMs: -1, hash: '' };
  const checkerHash = () => {
    try { const s = fs.statSync(checker); if (s.mtimeMs !== checkerMemo.mtimeMs) checkerMemo = { mtimeMs: s.mtimeMs, hash: sha1(fs.readFileSync(checker)).slice(0, 8) }; } catch { }
    return checkerMemo.hash;
  };

  // The cached record for this exact file (path + mtime + size), whatever reference or checker version made it.
  const cached = (glb, stat) => {
    const r = glb && stat && records.get(glb);
    return r && r.mtimeMs === stat.mtimeMs && r.size === stat.size ? r : null;
  };
  const badge = (r) => r && { status: r.status, short: r.short, verdict: r.verdict, at: r.at, ms: r.ms, against: r.against?.level || null };
  const badgeFor = (glb, stat) => badge(cached(glb, stat));

  function pump() {
    while (running < SLOTS && queue.length) {
      const go = queue.shift(); running++;
      go().finally(() => { running--; pump(); });
    }
  }
  function runChecker(glb, against, out) {
    return new Promise((resolve, reject) => {
      const args = ['-n', '15', python, checker, glb, ...(against ? ['--against', against] : []), '--json', out];
      const p = spawn('nice', args, { stdio: ['ignore', 'pipe', 'pipe'] });
      let text = '', err = '';
      p.stdout.on('data', (d) => { if (text.length < 400_000) text += d; });
      p.stderr.on('data', (d) => { err = (err + d).slice(-2000); });
      const timer = setTimeout(() => { p.kill('SIGKILL'); reject(new Error(`check timed out after ${TIMEOUT / 60_000} min`)); }, TIMEOUT);
      p.on('error', (e) => { clearTimeout(timer); reject(e); });
      p.on('close', (code) => { clearTimeout(timer); code === 0 || code === 1 || code === 2 ? resolve({ code, text }) : reject(new Error(`checker exit ${code}: ${err || text.slice(-600)}`)); });
    });
  }
  async function check(glb, stat, ref) {
    const t0 = Date.now();
    await fsp.mkdir(dir, { recursive: true });
    const base = path.join(dir, sha1(glb));
    const tmpJson = `${base}.${process.pid}.${t0}.out.json`;
    const refStat = ref?.glb ? await fsp.stat(ref.glb).catch(() => null) : null;
    try {
      const { code, text } = await runChecker(glb, refStat ? ref.glb : null, tmpJson);
      const j = code === 2 ? null : await fsp.readFile(tmpJson, 'utf8').then(JSON.parse).catch(() => null);
      const after = await fsp.stat(glb);
      if (after.mtimeMs !== stat.mtimeMs || after.size !== stat.size) throw new Error('the GLB changed during the check; open it again');
      const { header, sections } = parseReport(text);
      const verdict = sections.find((s) => s.kind === 'RESULT')?.text || (code === 2 ? text.trim().slice(0, 300) : '');
      // floating bodies: add each one's box from the JSON (the printed line names only its centre), for the 3D mark
      const bodies = sections.find((s) => s.kind === 'BODIES');
      if (bodies && j?.bodies) bodies.places.forEach((p, i) => { const b = j.bodies[i + 1]; if (b?.min && b?.max) Object.assign(p, { min: b.min, max: b.max }); });
      const status = statusOf(code, verdict);
      const record = {
        v: VERSION, glb, mtimeMs: stat.mtimeMs, size: stat.size, checker: checkerHash(), exit: code, status, verdict,
        short: shortFault(j, status), header, sections, text,
        counts: j && { triangles: j.triangles, bodies: j.bodies?.length, open_edges: j.open_edges, open_share: j.open_share, gaps: j.gap_count,
          blink_pairs: j.flicker?.same_facing_pairs, back_to_back_pairs: j.flicker?.back_to_back_pairs, back_to_back_m2: j.flicker?.back_to_back_m2,
          seen_lost_share: j.against?.reference_seen_lost_share ?? null, inside_out: j.non_manifold?.inside_out_parts ?? null,
          turned_edges: j.non_manifold?.turned_edges ?? null },
        doubleSided: await doubleSidedMaterials(glb),
        against: refStat ? { glb: ref.glb, mtimeMs: refStat.mtimeMs, level: ref.level, key: ref.key, id: ref.id || null } : null,
        againstNote: ref && !refStat ? `${ref.level} version (${ref.key}) ${ref.note || 'has no GLB yet'}: not compared` : null,
        ms: Date.now() - t0, at: Date.now(),
      };
      await fsp.writeFile(base + '.json.tmp', JSON.stringify(record));
      await fsp.rename(base + '.json.tmp', base + '.json');
      records.set(glb, record);
      return record;
    } finally { await fsp.rm(tmpJson, { force: true }); }
  }

  // The full result for the viewer: the cached one when it matches the file, the reference it would be compared with now,
  // and the checker version; otherwise one queued check (deduplicated). onDone(record) runs when a new check finishes.
  async function request(glb, ref, onDone) {
    const stat = await fsp.stat(glb).catch(() => null);
    if (!stat) return { state: 'missing', glb };
    const refStat = ref?.glb ? await fsp.stat(ref.glb).catch(() => null) : null;
    const r = cached(glb, stat);
    const sameRef = r && (r.against?.glb || null) === (refStat ? ref.glb : null) && (!refStat || r.against.mtimeMs === refStat.mtimeMs);
    if (r && sameRef && r.checker === checkerHash()) return { state: 'done', result: r };
    const key = `${glb}:${stat.mtimeMs}:${stat.size}:${refStat ? ref.glb + ':' + refStat.mtimeMs : ''}:${checkerHash()}`;
    const j = jobs.get(key);
    if (j && (j.state === 'queued' || j.state === 'running')) return { state: j.state, result: r || null };
    if (j && j.state === 'error' && Date.now() - j.t1 < RETRY_ERROR) return { state: 'error', err: j.err, result: r || null };
    if (j && j.state === 'done' && j.record) return { state: 'done', result: j.record };
    const job = { state: 'queued', err: null, t1: 0, record: null };
    jobs.set(key, job);
    job.promise = new Promise((resolve) => {
      queue.push(async () => {
        job.state = 'running';
        try { job.record = await check(glb, stat, ref); job.state = 'done'; onDone?.(job.record); }
        catch (e) { job.state = 'error'; job.err = String(e.message || e).slice(-600); console.error('integrity', glb, job.err); }
        job.t1 = Date.now(); resolve(job);
      });
      pump();
    });
    return { state: 'queued', result: r || null };
  }
  return { request, cached, badge, badgeFor, records, queue: () => ({ running, queued: queue.length }) };
}
