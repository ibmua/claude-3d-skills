// Group view (#/group/<key>): every asset made in one task / session / cost group, with the group's API cost and time
// (owner 2026-10-12 23:04). Data: catalog.groups (server groups.mjs) + the items whose made_with.group.key matches.
import type { Catalog } from './types.ts';
import { dur } from './MadeWith.tsx';

const usd = (v: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v);
const KYIV = new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short' });
const when = (s: string | null) => (s ? KYIV.format(new Date(s)) : '');

export default function GroupView({ cat, gkey }: { cat: Catalog | null; gkey: string }) {
  if (!cat) return <p className="muted pad">Scanning PC + the build box…</p>;
  const g = cat.groups?.[gkey];
  const items = cat.items.filter((i) => i.made_with?.group?.key === gkey);
  const src = new Map(cat.sources.map((s) => [s.id, s]));
  if (!g) return <div className="empty"><span>👥</span><h2>No such group</h2><p>No asset names this task or session any more.</p><a href="#/">Show all assets</a></div>;
  const wall = g.time?.first && g.time?.last ? (Date.parse(g.time.last) - Date.parse(g.time.first)) / 60000 : null;
  const bySource = new Map<string, typeof items>();
  for (const it of items) bySource.set(it.source, [...(bySource.get(it.source) || []), it]);
  return (
    <>
      <header className="library-heading">
        <div><p className="breadcrumb">Workspace / Group session</p><h1>👥 {g.label}<span>{items.length}</span></h1>
          <p className="intro">{g.kind === 'session' ? 'Every asset made in this session' : 'Every asset made in this task'}, with what the whole group cost.</p></div>
        {g.run && <a className="queue" href={`#/runs/${encodeURIComponent(g.run)}`} title="Open this run's progress, pictures and live cost">🏃 open the run</a>}
      </header>
      <section className="group-sum" aria-label="Group totals">
        <div title={`API-equivalent list price, not a bill; ${g.basis}`}><b>{g.usd != null ? `API ≈ ${usd(g.usd)}` : g.credits != null ? `${g.credits.toLocaleString('en-US', { maximumFractionDigits: 2 })} credits` : 'API cost unknown'}</b>{g.partial && <small> + unpriced part</small>}<small>whole group, shared</small></div>
        <div title="Active = time between consecutive API calls; a long gap counts as idle"><b>{g.time?.active_min != null ? `⏱ ${dur(g.time.active_min)} active` : '⏱ not recorded'}</b>{wall != null && <small>{dur(wall)} wall · {when(g.time!.first)} → {when(g.time!.last)}</small>}</div>
        <div><b>🧊 {items.length}</b><small>assets · {g.records} record{g.records === 1 ? '' : 's'}</small></div>
      </section>
      {g.makers.length > 0 && <ul className="group-makers" aria-label="Per maker">
        {g.makers.map((m, i) => <li key={i}><span>⚙ {m.label}{m.effort && !m.label.includes(m.effort) ? ` ${m.effort}` : ''}</span><b>{m.usd != null ? usd(m.usd) : m.images != null ? `${m.images} images · unpriced` : 'unpriced'}</b><small>{[m.active_min != null ? `⏱ ${dur(m.active_min)}` : '', m.calls != null ? `${m.calls} calls` : ''].filter(Boolean).join(' · ')}</small></li>)}
      </ul>}
      {[...bySource].map(([sid, xs]) => (
        <section key={sid}>
          <h2>{src.get(sid)?.emoji} {src.get(sid)?.label || sid} <span className="section-count">{xs.length}</span></h2>
          <div className="grid">
            {xs.map((it) => (
              <a key={it.id} className="card" href={`#/a/${encodeURIComponent(it.id)}`} title={it.path}>
                <div className="thumb">{it.preview ? <img loading="lazy" src={it.preview.url} alt="" /> : <div className="ph">🧊</div>}</div>
                <div className="cap"><span className="name">{it.key}</span>{it.group && <span className="muted"> · {it.group}</span>}</div>
              </a>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}
