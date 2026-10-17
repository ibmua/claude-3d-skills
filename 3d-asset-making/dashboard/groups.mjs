// Time to build + group sessions on the asset cards (owner 2026-10-12 23:04: "show time to build in the assets dashboard
// too. And if smth is built as part of group session, we should be able to click and view all assets that were developed
// as part of that group session and that api/time"). server.mjs calls annotateMadeWith() for each record it reads and
// buildGroups() once per catalog scan; the page opens #/group/<key>. See README.md "Time to build and group sessions".
import fs from 'node:fs';
import path from 'node:path';

const num = (v) => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : null);
const ts = (v) => { const t = Date.parse(v); return Number.isFinite(t) ? t : null; };

// time: the record's time.active_minutes_total, else the makers' active_minutes summed, else start/end (wall only).
// Nothing recorded -> no time (never a guess).
function timeOf(j) {
  const mw = Array.isArray(j?.made_with) ? j.made_with : j?.made_with ? [j.made_with] : [];
  const t = j?.time || {};
  let active = num(t.active_minutes_total);
  if (active == null) { const xs = mw.map((e) => num(e?.active_minutes)).filter((x) => x != null); if (xs.length) active = xs.reduce((a, b) => a + b, 0); }
  const starts = [t.first_start, ...mw.map((e) => e?.start)].map(ts).filter(Boolean);
  const ends = [t.last_end, ...mw.map((e) => e?.end)].map(ts).filter(Boolean);
  const first = starts.length ? Math.min(...starts) : null, last = ends.length ? Math.max(...ends) : null;
  const wall = first && last && last > first ? +((last - first) / 60000).toFixed(1) : null;
  if (active == null && wall == null) return null;
  return { active_min: active, wall_min: wall, first: first ? new Date(first).toISOString() : null, last: last ? new Date(last).toISOString() : null };
}

// group key priority (coordinator 2026-10-12 23:04): generation.cost_group, else the made_with task, else a session id
function groupOf(j, m) {
  const mw = Array.isArray(j?.made_with) ? j.made_with : j?.made_with ? [j.made_with] : [];
  const cg = j?.generation?.cost_group || mw.map((e) => e?.generation?.cost_group).find(Boolean) || j?.api_cost?.cost_groups?.[0]?.group || mw.map((e) => e?.api_cost?.cost_group).find(Boolean);
  if (cg) return { key: String(cg), label: String(cg).replace(/^[^:]+:task:/, ''), kind: 'cost_group', task: String(cg).match(/:task:(.+)$/)?.[1] || null };
  const task = mw.map((e) => e?.task).find((x) => typeof x === 'string' && x) || j?.generation?.tasks?.[0] || (typeof j?.owner === 'string' && j.owner) || null;
  if (task) return { key: 'task:' + task, label: task, kind: 'task', task };
  const sid = [m?.api_cost?.session_id, j?.session_id, ...mw.map((e) => (Array.isArray(e?.session) ? e.session[0] : e?.session))].find((x) => typeof x === 'string' && x);
  if (sid) return { key: 'session:' + sid, label: 'session ' + sid.replace(/\.jsonl$/, '').slice(0, 14), kind: 'session', task: null };
  return null;
}

// the makers of a record with their own amount and time (for the group's per-maker split)
function makersOf(j) {
  const mw = Array.isArray(j?.made_with) ? j.made_with : j?.made_with ? [j.made_with] : [];
  return mw.filter(Boolean).map((e) => ({ label: e.label || e.model || 'unknown', model: typeof e.model === 'string' ? e.model : null, effort: e.effort || null,
    usd: num(e.api_cost?.usd), images: num(e.images), active_min: num(e.active_minutes), calls: num(e.api_cost?.calls) }));
}

export function annotateMadeWith(m, record, file) {
  if (!m || typeof m !== 'object') return m;
  const time = timeOf(record); if (time) m.time = time;
  const group = groupOf(record, m); if (group) m.group = group;
  m.record = file;
  m.makersDetail = makersOf(record);
  return m;
}

// One index per catalog scan: group key -> totals. Shared amounts are the whole group's and are never summed across
// members; distinct per-asset amounts from different record files are summed.
export function buildGroups(items, cfg) {
  const groups = new Map();
  for (const it of items) {
    const m = it.made_with; if (!m || m.label === 'unknown') continue;
    if (!m.group && m.api_cost?.session_id) m.group = { key: 'session:' + m.api_cost.session_id, label: 'session ' + m.api_cost.session_id.slice(0, 8), kind: 'session', task: null };
    if (!m.group) { delete m.makersDetail; continue; }
    const g = groups.get(m.group.key) || { ...m.group, count: 0, records: new Map() };
    g.count++;
    const rec = m.record || it.id;
    if (!g.records.has(rec)) g.records.set(rec, { cost: m.api_cost || null, time: m.time || null, makers: m.makersDetail || [], label: m.label });
    delete m.makersDetail;   // only the group needs it; keeps the polled catalog small
    groups.set(m.group.key, g);
  }
  const runDirs = (cfg.runs || []).map((r) => ({ id: r.id, parent: r.root.split('*')[0] }));
  const out = {};
  for (const [key, g] of groups) {
    const recs = [...g.records.values()];
    const shared = recs.filter((r) => r.cost && /shared|asset_group/.test(r.cost.scope || '') || r.cost?.partial);
    const amt = (c) => (c ? num(c.usd) ?? null : null);
    let usd = null, credits = null, basis = 'none';
    const sharedAmts = shared.map((r) => amt(r.cost)).filter((x) => x != null);
    const ownAmts = recs.filter((r) => !shared.includes(r)).map((r) => amt(r.cost)).filter((x) => x != null);
    if (sharedAmts.length || ownAmts.length) { usd = Math.max(sharedAmts.length ? Math.max(...sharedAmts) : 0, ownAmts.reduce((a, b) => a + b, 0)); basis = sharedAmts.length >= ownAmts.length ? 'shared (largest recorded amount; never summed)' : 'sum of per-asset amounts'; }
    const cr = recs.map((r) => num(r.cost?.credits)).filter((x) => x != null); if (cr.length) credits = Math.max(...cr);
    const partial = recs.some((r) => r.cost?.partial);
    // time: the record with the most active minutes (members of one session share it); the wall span over all records
    const times = recs.map((r) => r.time).filter(Boolean);
    const active = times.map((t) => t.active_min).filter((x) => x != null);
    const firsts = times.map((t) => ts(t.first)).filter(Boolean), lasts = times.map((t) => ts(t.last)).filter(Boolean);
    const lead = recs.reduce((b, r) => ((amt(r.cost) ?? -1) > (amt(b?.cost) ?? -1) ? r : b), null);
    let run = null;
    if (g.task) for (const r of runDirs) if (fs.existsSync(path.join(r.parent, g.task, 'progress.jsonl'))) { run = `${r.id}:${g.task}`; break; }
    out[key] = { key, label: g.label, kind: g.kind, task: g.task, count: g.count, records: recs.length, usd: usd == null ? null : +usd.toFixed(4), credits, partial, basis,
      time: times.length ? { active_min: active.length ? Math.max(...active) : null, first: firsts.length ? new Date(Math.min(...firsts)).toISOString() : null, last: lasts.length ? new Date(Math.max(...lasts)).toISOString() : null } : null,
      makers: lead?.makers || [], run };
  }
  return out;
}
