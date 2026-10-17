// Runs view (#/runs): live progress, pictures and API use of asset-building runs (owner 2026-10-12 22:47).
// Data: /api/runs (server runs.mjs). Refreshes every 30 s while the page is visible, never when hidden.
import { useEffect, useMemo, useRef, useState } from 'react';
import { PhotoStrip, type Photo } from './PhotoGallery.tsx';
import { thumbnailUrl } from './imageLinks.ts';

type Tokens = { in: number; cw: number; cw1h: number; cr: number; out: number };
type CostPart = { role: 'parent' | 'builder'; label: string; file: string; usd: number; calls: number; activeHours: number; wallHours: number | null; perActiveHour: number | null; tokens: Tokens; first: number | null; last: number | null; unpriced: Unpriced };
type Unpriced = { calls: number; tokens: number; models: string[] };
type RunEvent = { ts: string; kind: string; msg: string; asset?: string; stage?: string; round?: number; luna?: number; builder?: string; data?: Record<string, unknown>; picture: string | null; backfilled?: boolean };
type Run = {
  id: string; name: string; source: string; project: string; host: string; dir: string; err?: string;
  title: string | null; family: string | null; asset: string | null; model: string | null; effort: string | null; account: string | null;
  test: string | null; arm: string | null; backfilled: string | null; dispatched: boolean;
  attempts: number | null; sessions: number | null; limit: { text: string | null; until: number | null } | null;
  state: 'running' | 'idle' | 'done' | 'failed' | 'blocked'; lastEvent: number | null; lastActivity: number | null; firstActivity: number | null; hours: number | null;
  stage: string | null; latest: { url: string | null; round: number | null; ts: string; msg: string } | null;
  luna: { round: number | null; luna: number; ts: string }[]; bestLuna: number | null;
  counts: { events: number; components: number; rounds: number; exports: number; blocked: number };
  cost: { usd: number; calls: number; tokens: Tokens; unpriced: Unpriced; first: number | null; last: number | null; activeHours: number; perHour: number | null; spark: number[]; parts: CostPart[]; transcripts: number };
  images: { images: number; calls: number; failed: number } | null;
  events: RunEvent[];
  time: {
    wallHours: number | null; activeHours: number; perActiveHour: number | null; meanRoundHours: number | null; hoursToLuna7: number | null; activeHoursToLuna7: number | null;
    rounds: { round: number; ts: string; wallHours: number | null; activeHours: number | null; usd: number }[];
    assets: { asset: string; events: number; component: boolean; first: number; last: number; wallHours: number }[];
  };
};
type RunsDoc = { generated: number; ms: number; prices: { from: string; err: string | null; ok: boolean }; errors: { source: string; err: string }[]; runs: Run[] };

const KIND: Record<string, [string, string]> = {
  start: ['▶️', 'Started'], plan: ['🗺️', 'Plan'], search: ['🔎', 'Library search'], decision: ['⚖️', 'Decision'], component: ['🧩', 'Component saved'],
  assembly: ['🏗️', 'Assembly'], round: ['🔁', 'Review round'], review: ['🌙', 'Luna review'], export: ['📦', 'Game version exported'],
  thumbnail: ['🖼️', 'Thumbnail'], blocked: ['⛔', 'Blocked'], done: ['✅', 'Handed back'],
};
const STATE: Record<Run['state'], [string, string]> = {
  running: ['●', 'Running: activity in the last 10 minutes'], idle: ['⏸', 'Idle: no activity for 10 minutes or more'],
  done: ['✓', 'Done: handed back'], failed: ['✕', 'Failed'], blocked: ['⛔', 'Blocked or stopped by a limit'],
};
const usd = (v: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: v > 0 && v < 0.1 ? 3 : 2 }).format(v);
const num = (v: number) => v >= 1e6 ? `${(v / 1e6).toFixed(1)} M` : v >= 1e4 ? `${Math.round(v / 1e3)} k` : v.toLocaleString('en-US');
const KYIV_T = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit' });
const KYIV_D = new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short' });
const tOf = (s: string | number) => (typeof s === 'number' ? s : Date.parse(s));
const hm = (s: string | number) => KYIV_T.format(new Date(tOf(s)));
const full = (s: string | number | null) => (s == null ? '' : KYIV_D.format(new Date(tOf(s))) + ' Kyiv');
function age(t: number | null) {
  if (!t) return '';
  const s = (Date.now() - t) / 1000;
  return s < 90 ? 'just now' : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 129600 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`;
}
const hours = (h: number | null) => (h == null ? '–' : h < 1 ? `${Math.round(h * 60)} min` : `${h.toFixed(1)} h`);
const modelName = (m: string | null) => {
  if (!m) return 'model unknown';
  const x = m.match(/^claude-(opus|sonnet|haiku|fable)-(\d+)(?:-(\d+))?/);
  return x ? `${x[1][0].toUpperCase() + x[1].slice(1)} ${x[2]}${x[3] && x[3].length < 3 ? '.' + x[3] : ''}` : m;
};
const tokTip = (t: Tokens) => `input ${num(t.in)} · cache write ${num(t.cw)}${t.cw1h ? ` (1h ${num(t.cw1h)})` : ''} · cache read ${num(t.cr)} · output ${num(t.out)}`;

function Spark({ v }: { v: number[] }) {
  if (v.length < 2) return null;
  const W = 120, H = 28, max = v[v.length - 1] || 1;
  const pts = v.map((y, i) => `${(i / (v.length - 1)) * W},${H - 2 - (y / max) * (H - 4)}`).join(' ');
  return <svg className="run-spark" viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label="Cumulative API cost over the run"><polyline points={`0,${H} ${pts} ${W},${H}`} className="area" /><polyline points={pts} className="line" /></svg>;
}

function LunaHistory({ l }: { l: Run['luna'] }) {
  if (!l.length) return null;
  return <div className="run-luna" title="Luna review levels, oldest first (the bar is 7+ twice)">🌙{l.map((x, i) => <span key={i} className={x.luna >= 7 ? 'ok' : x.luna >= 5 ? 'mid' : 'low'} title={`${x.round != null ? 'round ' + x.round + ' · ' : ''}${full(x.ts)}`}><i style={{ height: `${Math.max(2, x.luna) * 2.2}px` }} /><b>{x.luna}</b></span>)}</div>;
}

function Compare({ runs }: { runs: Run[] }) {
  const groups = useMemo(() => {
    const g = new Map<string, Run[]>();
    for (const r of runs) if (r.test) g.set(r.test, [...(g.get(r.test) || []), r]);
    return [...g].filter(([, xs]) => xs.length > 1);
  }, [runs]);
  if (!groups.length) return null;
  const rows: [string, string, (r: Run) => string, (r: Run) => number | null, 'min' | 'max' | null][] = [
    ['🎚️', 'Model + effort', (r) => `${modelName(r.model)} ${r.effort || ''}`, () => null, null],
    ['💵', 'API ≈ $ so far', (r) => usd(r.cost.usd), (r) => r.cost.usd, 'min'],
    ['🔁', 'Rounds', (r) => String(r.counts.rounds), (r) => r.counts.rounds, null],
    ['🌙', 'Best Luna', (r) => (r.bestLuna == null ? '–' : String(r.bestLuna)), (r) => r.bestLuna, 'max'],
    ['🧩', 'Components saved', (r) => String(r.counts.components), (r) => r.counts.components, null],
    ['🕰️', 'Wall time', (r) => hours(r.time.wallHours), (r) => r.time.wallHours, 'min'],
    ['⚡', 'Active time (gaps over 10 min idle)', (r) => hours(r.time.activeHours), (r) => r.time.activeHours, 'min'],
    ['💸', '$ per active hour', (r) => (r.time.perActiveHour == null ? '–' : usd(r.time.perActiveHour)), (r) => r.time.perActiveHour, 'min'],
    ['⏳', 'Time to Luna 7 (wall / active)', (r) => (r.time.hoursToLuna7 == null ? 'not reached' : `${hours(r.time.hoursToLuna7)} / ${hours(r.time.activeHoursToLuna7)}`), (r) => r.time.hoursToLuna7, 'min'],
    ['🔁', 'Mean time per round', (r) => hours(r.time.meanRoundHours), () => null, null],
    ['🖼️', 'Images (unpriced)', (r) => String(r.images?.images ?? 0), () => null, null],
  ];
  return <>{groups.map(([test, xs]) => (
    <section className="run-compare" key={test} aria-label={`A/B test ${test}`}>
      <h2>⚖️ {test}</h2>
      <div className="run-compare-grid" style={{ gridTemplateColumns: `minmax(0, 1.1fr) repeat(${xs.length}, minmax(0, 1fr))` }}>
        <span />{xs.map((r) => <a key={r.id} href={`#/runs/${encodeURIComponent(r.id)}`} className="arm" title={r.name}><span className={`run-state ${r.state}`}>{STATE[r.state][0]}</span> {r.arm || r.name}<small>{r.asset}</small></a>)}
        {rows.map(([icon, label, f, val, best]) => {
          const vals = xs.map(val).filter((v): v is number => v != null);
          const target = best === 'min' ? Math.min(...vals) : best === 'max' ? Math.max(...vals) : null;
          return [<span key={label} className="rowhead" title={label}>{icon} <span>{label}</span></span>,
            ...xs.map((r) => <b key={label + r.id} className={target != null && vals.length > 1 && val(r) === target ? 'best' : ''}>{f(r)}</b>)];
        })}
      </div>
    </section>
  ))}</>;
}

function runPhotos(r: Run): Photo[] {
  const urls = new Map<string, Photo>();
  for (const e of r.events || []) if (e.picture && !urls.has(e.picture)) {
    const name = decodeURIComponent(e.picture.split('/').pop() || 'Picture').replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ');
    urls.set(e.picture, { url: e.picture, label: e.round != null ? `Round ${e.round}` : name });
  }
  if (r.latest?.url && !urls.has(r.latest.url)) urls.set(r.latest.url, {url: r.latest.url, label: r.latest.round != null ? `Round ${r.latest.round}` : 'Latest picture'});
  return [...urls.values()];
}

function RunSummary({ r }: { r: Run }) {
  const picture = r.latest?.url ? {url: r.latest.url, label: r.latest.msg} : runPhotos(r)[0];
  return <a className="run-summary" href={`#/runs/${encodeURIComponent(r.id)}`}>
    <div className="run-summary-image">{picture ? <img src={thumbnailUrl(picture.url, 640)} alt="" loading="lazy" /> : <span>🧊</span>}</div>
    <div className="run-summary-info"><div className="run-summary-top"><span className={`run-state ${r.state}`} title={STATE[r.state][1]}>{STATE[r.state][0]} {r.state}</span><small>{age(r.lastActivity)}</small></div>
      <h2>{r.title || r.name}</h2><p>{modelName(r.model)} {r.effort}</p>
      {r.err ? <p className="error">{r.err}</p> : <div className="run-summary-stats"><b>{r.cost.transcripts ? `API ≈ ${usd(r.cost.usd)}` : 'Cost unknown'}</b><span>⚡ {hours(r.time.activeHours)}</span><span>🌙 {r.bestLuna ?? '–'}</span></div>}
      <span className="run-open">Inspect run ↗</span>
    </div>
  </a>;
}

function PictureDialog({ url, close }: { url: string; close: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return <dialog ref={ref} className="run-lightbox" aria-label="Run picture" onCancel={close} onClick={e => { if (e.target === e.currentTarget) close(); }}>
    <div className="run-lightbox-tools"><a href={url} target="_blank" rel="noreferrer">↗ Original image</a><button autoFocus onClick={close} aria-label="Close picture">✕</button></div>
    <img src={url} alt="Run render" />
  </dialog>;
}

function RunPicture({ photo, zoom }: { photo: Photo; zoom: (url: string) => void }) {
  const [shown, setShown] = useState(photo);
  const [opacity, setOpacity] = useState(1);
  useEffect(() => {
    if (shown.url === photo.url) return;
    let stopped = false;
    const timers: number[] = [];
    const image = new Image(); image.src = photo.url;
    // Keep the old picture visible until its replacement is decoded, then swap at zero.
    image.decode().catch(() => undefined).then(() => {
      if (stopped) return;
      const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
      setOpacity(0);
      timers.push(window.setTimeout(() => {
        setShown(photo);
        timers.push(window.setTimeout(() => setOpacity(1), reduced ? 0 : 80));
      }, reduced ? 0 : 160));
    });
    return () => { stopped = true; timers.forEach(clearTimeout); setOpacity(1); };
  }, [photo.url]);
  return <button className="pic" onClick={() => zoom(shown.url)} aria-label="Enlarge the selected picture">
    <div className="run-picture-content" style={{opacity}}><img src={shown.url} alt={shown.label} /><span>⤢ {shown.label}</span></div>
  </button>;
}

function RunCard({ r, zoom }: { r: Run; zoom: (u: string) => void }) {
  const [all, setAll] = useState(false);
  const [eventKind, setEventKind] = useState('all');
  const [pictureUrl, setPictureUrl] = useState<string | null>(null);
  const photos = useMemo(() => runPhotos(r), [r]);
  const photoIndex = Math.max(0, photos.findIndex(p => p.url === pictureUrl));
  const picture = photos[photoIndex];
  if (r.err) return <article className="run-card"><h3>{r.name}</h3><p className="error">⚠️ {r.err}</p></article>;
  const builders = r.cost.parts.filter((p) => p.role === 'builder');
  const lead = r.cost.parts.find((p) => p.role === 'parent');
  const matching = r.events.filter(e => eventKind === 'all' || (eventKind === 'pictures' ? !!e.picture : eventKind === 'review' ? ['round', 'review'].includes(e.kind) : e.kind === eventKind));
  const ev = all ? matching : matching.slice(0, 8);
  const c = r.cost;
  return (
    <article className={`run-card ${r.state}`} id={r.id}>
      <header className="run-head">
        <span className={`run-state ${r.state}`} title={STATE[r.state][1]}>{STATE[r.state][0]} {r.state}</span>
        <h3 title={r.dir}>{r.name}</h3>
        <span className="muted small" title={full(r.lastActivity)}>{r.lastEvent ? `last event ${age(r.lastEvent)}` : 'no events yet'}</span>
      </header>
      {r.limit && <p className="run-limit" title={r.limit.text || ''}>⏳ {r.limit.until && r.limit.until > Date.now() ? `waiting for limit reset until ${hm(r.limit.until)}` : r.limit.until ? `limit reset at ${hm(r.limit.until)} passed; continues when the dispatcher restarts it` : 'stopped by a usage limit'}</p>}
      <div className="run-facts">
        {(r.family || r.asset) && <span title="Family / asset">🚃 {[r.family, r.asset].filter(Boolean).join(' / ')}</span>}
        <span title="Model and effort">🎚️ {modelName(r.model)} {r.effort}</span>
        {r.account && <span title="Account">👤 {r.account}</span>}
        {r.stage && <span title="Stage">🏁 stage {r.stage}</span>}
        {r.attempts != null && <span title="Dispatcher attempts and the sessions found for them; cost and time sum all of them">🔂 attempt {r.attempts}{r.sessions != null ? ` · ${r.sessions} session${r.sessions === 1 ? '' : 's'}` : ''}</span>}
        {r.test && <span title={`A/B test ${r.test}`}>⚖️ {r.arm || r.test}</span>}
      </div>
      <div className="run-body">
        <div className="run-pic">
          {picture ? <>
            <RunPicture photo={picture} zoom={zoom} />
            <PhotoStrip photos={photos} index={photoIndex} onSelect={i => setPictureUrl(photos[i].url)} />
          </> : <div className="ph"><span>🧊</span><small>No pictures reported yet</small></div>}
          <LunaHistory l={r.luna} />
        </div>
        <div className="run-side">
          <div className="run-cost" title={`${c.calls} API calls · ${tokTip(c.tokens)} · priced with Claude Cost's table; API-equivalent list price, not a bill`}>
            <div className="run-cost-total"><small>API-equivalent cost{r.state === 'running' ? ' so far' : ''}</small><b>{c.transcripts ? `≈ ${usd(c.usd)}` : 'Unknown'}</b></div>
            <dl className="run-metrics">
              <div><dt>⚡ Active time</dt><dd>{hours(r.time.activeHours)}</dd></div>
              <div title="First to last activity"><dt>🕰 Wall time</dt><dd>{hours(r.time.wallHours)}</dd></div>
              <div><dt>API calls</dt><dd>{num(c.calls)}</dd></div>
              <div title="Gaps over 10 minutes count as idle"><dt>Cost / active hour</dt><dd>{r.time.perActiveHour == null ? '–' : usd(r.time.perActiveHour)}</dd></div>
            </dl>
            {r.time.hoursToLuna7 != null && <div className="small muted">⏳ Luna 7 after {hours(r.time.hoursToLuna7)} ({hours(r.time.activeHoursToLuna7)} active)</div>}
            <Spark v={c.spark} />
            {c.unpriced.calls > 0 && <div className="small warn">+ unpriced part: {num(c.unpriced.tokens)} tokens ({c.unpriced.models.join(', ')})</div>}
            {!c.transcripts && <div className="small muted">no transcript found yet: cost unknown, not $0</div>}
            {r.images && <div className="small" title={`${r.images.calls} Codex image calls, ${r.images.failed} failed; per-image price not verified`}>🖼️ {r.images.images} images · unpriced</div>}
          </div>
          {(builders.length > 0 || !!lead) && <details className="run-breakdown"><summary>🛠 Session breakdown</summary><ul className="run-builders">
            {lead && <li title={`${tokTip(lead.tokens)} · ${lead.calls} calls · ${hours(lead.wallHours)} wall`}><span>🧭 lead</span><b>{usd(lead.usd)}</b><small>⚡ {hours(lead.activeHours)}</small></li>}
            {builders.map((b) => <li key={b.file} title={`${b.file}\n${tokTip(b.tokens)} · ${b.calls} calls · ${hours(b.wallHours)} wall${b.perActiveHour != null ? ` · ${usd(b.perActiveHour)}/active h` : ''}`}><span>🛠️ {b.label}</span><b>{b.unpriced.calls ? (b.usd ? `${usd(b.usd)} + unpriced` : 'unpriced') : usd(b.usd)}</b><small>⚡ {hours(b.activeHours)}</small></li>)}
          </ul></details>}
          <div className="run-counts">
            <span title="Components saved">🧩 <b>{r.counts.components}</b> components</span><span title="Review rounds">🔁 <b>{r.counts.rounds}</b> rounds</span>
            <span title="Game versions exported">📦 <b>{r.counts.exports}</b> exports</span><span title="Best Luna level">🌙 Best <b>{r.bestLuna ?? '–'}</b></span>
            {r.counts.blocked > 0 && <span className="bad" title="Blocked events">⛔ {r.counts.blocked}</span>}
          </div>
        </div>
      </div>
      {r.time.rounds.length > 0 && <details className="run-round-details"><summary>🔁 Time and cost per round <small>{r.time.rounds.length}</small></summary><div className="run-rounds" aria-label="Time and API cost per round">
        <span className="lbl" title={`Round time = since the previous round (the first: since the start); mean ${hours(r.time.meanRoundHours)}`}>🔁⏱</span>
        {r.time.rounds.map((x) => <span key={x.round + x.ts} className="rnd" title={`round ${x.round} at ${full(x.ts)} · ${hours(x.wallHours)} wall · ${hours(x.activeHours)} active · ${usd(x.usd)}`}><b>r{x.round}</b> {hours(x.wallHours)} <small>{usd(x.usd)}</small></span>)}
      </div></details>}
      {r.time.assets.some((a) => a.wallHours > 0) && <details className="run-assets"><summary>⏱ time per asset / component</summary><ul>
        {r.time.assets.filter((a) => a.wallHours > 0).map((a) => <li key={a.asset} title={`${full(a.first)} → ${full(a.last)} · ${a.events} events`}><span>{a.component ? '🧩' : '🚃'} {a.asset}</span><b>{hours(a.wallHours)}</b></li>)}
        {r.time.assets.some((a) => a.wallHours === 0) && <li className="muted small">{r.time.assets.filter((a) => a.wallHours === 0).length} more reported once (no span)</li>}
      </ul></details>}
      <div className="run-activity-head"><h2>Activity <small>{matching.length}</small></h2><label><span className="muted">Show</span> <select aria-label="Filter activity" value={eventKind} onChange={e => { setEventKind(e.target.value); setAll(false); }}><option value="all">All events</option><option value="pictures">Pictures</option><option value="review">Rounds & reviews</option><option value="export">Exports</option><option value="blocked">Issues</option></select></label></div>
      {r.backfilled && <p className="run-backfilled" title={r.backfilled}>↺ History reconstructed after the run</p>}
      <ol className="run-events">
        {ev.map((e, i) => (
          <li key={i} className={`run-event run-event-${e.kind}`}>
            <time title={full(e.ts)}>{hm(e.ts)}</time>
            <span className="k" title={KIND[e.kind]?.[1] || e.kind}>{KIND[e.kind]?.[0] || '•'}</span>
            <span className="m">{e.asset && e.kind === 'component' ? <b>{e.asset} </b> : null}{e.msg}{e.luna != null && <em className="luna-chip">🌙 {e.luna}</em>}{e.builder && <small> · 🛠️ {e.builder}</small>}{e.data && <details className="run-event-data"><summary>Details</summary><span className="muted">{Object.entries(e.data).map(([k, v]) => `${k}: ${typeof v === 'number' ? v.toLocaleString('en-US') : String(v)}`).join(' · ')}</span></details>}</span>
            {e.picture && <button className="thumb-btn" onClick={() => zoom(e.picture!)} aria-label="Enlarge picture"><img src={thumbnailUrl(e.picture, 160)} alt="" loading="lazy" /></button>}
          </li>
        ))}
      </ol>
      {!matching.length && <p className="muted">No events of this kind yet.</p>}
      {matching.length > 8 && <button className="run-more" onClick={() => setAll(!all)} aria-expanded={all}>{all ? '▴ Show recent events' : `▾ Show all ${matching.length} events`}</button>}
    </article>
  );
}

export default function RunsView({ route }: { route: string }) {
  let selectedId = '';
  try { if (route.startsWith('#/runs/')) selectedId = decodeURIComponent(route.slice('#/runs/'.length)); } catch { /* malformed external link: show overview */ }
  const [query, setQuery] = useState('');
  const [state, setState] = useState('all');
  const [doc, setDoc] = useState<RunsDoc | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [zoom, setZoom] = useState<string | null>(null);
  useEffect(() => {
    let timer = 0, stop = false, inFlight = false;
    const controller = new AbortController();
    async function tick() {
      if (stop || inFlight) return;
      if (document.visibilityState === 'visible') {
        inFlight = true;
        try { const r = await fetch('api/runs', {signal: controller.signal}); if (!r.ok) throw new Error(`Runs unavailable (${r.status})`); const d: RunsDoc = await r.json(); if (!stop) { setDoc(d); setErr(null); } }
        catch (e) { if (!stop) setErr(String(e)); }
        finally { inFlight = false; if (!stop) timer = window.setTimeout(tick, 30_000); }
      }
    }
    tick();
    const vis = () => { clearTimeout(timer); if (document.visibilityState === 'visible') tick(); };
    document.addEventListener('visibilitychange', vis);
    return () => { stop = true; controller.abort(); clearTimeout(timer); document.removeEventListener('visibilitychange', vis); };
  }, []);
  // Only explicit route navigation changes position. Fresh API documents must never scroll.
  useEffect(() => { window.scrollTo({ top: 0, behavior: 'instant' }); setZoom(null); }, [route]);
  const runs = doc?.runs || [];
  const selected = runs.find(r => r.id === selectedId);
  const filtered = runs.filter(r => (state === 'all' || r.state === state) && `${r.name} ${r.title || ''} ${r.asset || ''} ${r.model || ''}`.toLowerCase().includes(query.trim().toLowerCase()));
  const running = runs.filter((r) => r.state === 'running');
  const total = runs.reduce((s, r) => s + (r.cost?.usd || 0), 0);
  return (
    <div className="runs-workspace">
      <nav className="run-nav" aria-label="Run navigation"><a href="#/runs">All runs</a><span>/</span>{selectedId ? <select aria-label="Choose run" value={selectedId} onChange={e => { location.hash = `#/runs/${encodeURIComponent(e.target.value)}`; }}>{!selected && <option value={selectedId}>{doc ? 'Run not found' : 'Loading run…'}</option>}{runs.map(r => <option key={r.id} value={r.id}>{r.title || r.name}</option>)}</select> : <span>Overview</span>}</nav>
      <header className="library-heading runs-heading">
        <div><h1>{selected ? selected.title || selected.name : selectedId ? 'Asset run' : 'Asset runs'}{!selectedId && <span>{runs.length}</span>}</h1>
          <p className="intro">{selected ? [modelName(selected.model), selected.effort, selected.asset].filter(Boolean).join(' · ') : 'Pictures, progress and build costs'}</p></div>
        <span className="queue" title={doc ? `computed in ${doc.ms} ms; refreshes every 30 s while visible` : ''}>{doc ? selectedId ? `Updated ${age(doc.generated)} · refreshes every 30 s` : `${running.length ? `● ${running.length} running · ` : ''}All runs ≈ ${usd(total)} · ${age(doc.generated)}` : 'Connecting…'}</span>
      </header>
      {err && <p className="error">⚠️ {err}</p>}
      {doc?.prices.err && <p className="error">⚠️ {doc.prices.err}</p>}
      {doc?.errors.map((e) => <p className="error" key={e.source}>{e.source}: {e.err}</p>)}
      {doc && !runs.length && <div className="empty"><span>🏃</span><h2>No runs yet</h2><p>A run appears when its folder gets a progress.jsonl (skill 3d-asset-making, scripts/report.py).</p></div>}
      {doc && selectedId && !selected && <div className="empty"><h2>Run not found</h2><p>Choose a run above or return to <a href="#/runs">all runs</a>.</p></div>}
      {selected ? <div className="runs"><RunCard key={selected.id} r={selected} zoom={setZoom} /></div> : !selectedId && <>
        <div className="run-toolbar"><label className="search-wrap"><span>⌕</span><textarea rows={1} className="search" aria-label="Search runs" placeholder="Find a run…" value={query} onChange={e => setQuery(e.target.value)} /></label><select aria-label="Filter runs by status" value={state} onChange={e => setState(e.target.value)}><option value="all">All statuses</option>{Object.keys(STATE).map(x => <option key={x} value={x}>{x[0].toUpperCase() + x.slice(1)}</option>)}</select></div>
        <div className="run-summary-grid">{filtered.map(r => <RunSummary key={r.id} r={r} />)}</div>
        {doc && runs.length > 0 && !filtered.length && <p className="muted">No runs match these filters.</p>}
      </>}
      {runs.some(r => r.test && (!selected || r.test === selected.test) && runs.filter(x => x.test === r.test).length > 1) && <details className="run-comparisons"><summary>⚖️ Compare runs</summary><Compare runs={selected ? runs.filter(r => r.test === selected.test) : runs} /></details>}
      {zoom && <PictureDialog url={zoom} close={() => setZoom(null)} />}
    </div>
  );
}
