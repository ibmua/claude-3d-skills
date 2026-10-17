// "To be done": a generated inventory of the assets a project still needs (config/sources.json `todo`; a film
// pipeline is written by a film pipeline's asset_todo.py). Each card shows the reference art the asset should be made
// from, the shots it is in and why it is not done. Built assets are one filter away.
import { useEffect, useMemo, useState } from 'react';
import type { MadeWith, TodoDoc, TodoItem, TodoSummary } from './types.ts';
import { MadeWithBadge } from './MadeWith.tsx';

const STATUS = { todo: 'To do', flagged: 'Open issues', built: 'Built' } as const;
const SHOW = { open: 'To do + open issues', todo: 'To do only', flagged: 'Open issues only', built: 'Built', all: 'Everything' } as const;
type Show = keyof typeof SHOW;
const secs = (s: number) => (s >= 60 ? `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, '0')} s` : `${s < 10 ? s.toFixed(1) : Math.round(s)} s`);
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
const routeTodo = () => (location.hash.startsWith('#/t/') ? decodeURIComponent(location.hash.slice(4)) : null);
const base = (p?: string | null) => (p ? p.split('/').pop() : '');
// the model + effort setting that made a built asset ("Sol-6.1 max", "Opus max"; unknown when nothing records it)
function commonFlags(items: TodoItem[]): string[] {
  const open = items.filter((a) => a.status !== 'built');
  if (open.length < 2) return [];
  return open[0].flags.filter((f) => open.every((a) => a.flags.includes(f)));
}

// a flag every open card of a section shares is said once above the section (commonFlags), not on each card
function why(a: TodoItem, common: Set<string>): { cls: string; text: string } | null {
  const own = a.flags.filter((f) => !common.has(f));
  if (a.status === 'flagged' && own.length) return { cls: 'flagged', text: own[0].replace(/^open: /, '') + (own.length > 1 ? ` (+${own.length - 1} more)` : '') };
  if (a.status === 'flagged' && a.flags.length) return { cls: 'flagged', text: 'See the note above this group' };
  if (a.status === 'todo' && a.now) return { cls: 'todo', text: `Now: ${a.now}` };
  if (a.status === 'built') return { cls: 'built', text: a.asset ? `Production asset ${base(a.asset)}` : a.by ? `Made by ${a.by}` : 'Built' };
  return null;
}

export default function TodoView({ sum, compact, setCompact }: { sum: TodoSummary; compact: boolean; setCompact: (v: boolean) => void }) {
  const [doc, setDoc] = useState<TodoDoc | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [show, setShow] = useState<Show>('open');
  const [group, setGroup] = useState('');
  const [sort, setSort] = useState('screen');
  const [open, setOpen] = useState<string | null>(routeTodo());

  useEffect(() => { // (re)load whenever the inventory file changes (its mtime rides on the polled catalog)
    let stop = false;
    fetch(`api/todo?id=${encodeURIComponent(sum.id)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`To-do list unavailable (${r.status})`))))
      .then((d: TodoDoc) => { if (!stop) { setDoc(d); setErr(null); } })
      .catch((e) => { if (!stop) setErr(String(e)); });
    return () => { stop = true; };
  }, [sum.id, sum.mtime]);
  useEffect(() => {
    const h = () => setOpen(routeTodo());
    window.addEventListener('hashchange', h);
    return () => window.removeEventListener('hashchange', h);
  }, []);

  const groups = doc?.groups || sum.groups || {};
  const counts = doc?.counts || sum.counts || {};
  const totals = doc?.totals || sum.totals || { todo: 0, flagged: 0, built: 0 };
  const sections = useMemo(() => {
    if (!doc) return [];
    const needle = q.trim().toLowerCase();
    const order = { todo: 0, flagged: 1, built: 2 };
    const keep = (a: TodoItem) => (show === 'all' || (show === 'open' ? a.status !== 'built' : a.status === show))
      && (!group || a.group === group)
      && (!needle || `${a.name} ${a.id} ${a.kind} ${a.made_with?.label ?? ''} ${a.shots.join(' ')} ${Object.keys(a.members || {}).join(' ')}`.toLowerCase().includes(needle));
    return Object.entries(groups)
      .map(([g, label]) => ({ g, label, items: doc.items.filter((a) => a.group === g && keep(a)).sort((a, b) => order[a.status] - order[b.status]
        || (sort === 'name' ? a.name.localeCompare(b.name) : sort === 'shots' ? b.shots.length - a.shots.length : b.screen_s - a.screen_s)) }))
      .filter((s) => s.items.length)
      .map((s) => ({ ...s, common: commonFlags(doc.items.filter((a) => a.group === s.g)) }));
  }, [doc, q, show, group, sort, groups]);
  const item = open && doc ? doc.items.find((a) => a.id === open) : null;
  const shown = sections.reduce((n, s) => n + s.items.length, 0);
  const close = () => { history.pushState(null, '', location.pathname + location.search); setOpen(null); };

  return (
    <>
      <header className="library-heading">
        <div>
          <p className="breadcrumb">Workspace / To be done / {sum.group || sum.label}</p>
          <h1>{sum.title || sum.group}: assets to be done<span>{totals.todo + totals.flagged}</span></h1>
          <p className="intro">
            Every object, person, place and light the film shows ({sum.cutShots ?? doc?.cut_shots} shots, {clock(sum.cutS ?? doc?.cut_s ?? 0)}), checked against the
            production assets: <b>{totals.todo}</b> still to make, <b>{totals.flagged}</b> built with open issues, {totals.built} built.
            The picture on each card is the reference art it should be made from.
          </p>
        </div>
        <span className="queue" title={doc?.file || ''}>Inventory of {sum.generated ?? doc?.generated} Kyiv</span>
      </header>
      <div className="todo-groups" role="group" aria-label="Asset groups">
        {Object.entries(groups).map(([g, label]) => {
          const c = counts[g] || { todo: 0, flagged: 0, built: 0 };
          return (
            <button key={g} className={c.todo + c.flagged ? 'todo-group' : 'todo-group done'} aria-pressed={group === g} onClick={() => setGroup(group === g ? '' : g)}>
              <span>{label}</span><b>{c.todo}</b><small>to do{c.flagged ? ` · ${c.flagged} with open issues` : ''} · {c.built} built</small>
            </button>
          );
        })}
      </div>
      <div className="toolbar">
        <label className="search-wrap"><span aria-hidden="true">⌕</span><textarea rows={1} className="search" aria-label="Search assets to do" placeholder="Search names, shots or object ids…" value={q} onChange={(e) => setQ(e.target.value.replace(/\n/g, ''))} />{q && <button aria-label="Clear search" onClick={() => setQ('')}>×</button>}</label>
        <select aria-label="Which assets" value={show} onChange={(e) => setShow(e.target.value as Show)}>{Object.entries(SHOW).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <select aria-label="Sort assets" value={sort} onChange={(e) => setSort(e.target.value)}><option value="screen">Most screen time</option><option value="shots">Most shots</option><option value="name">Name A–Z</option></select>
        <button className="density" aria-label="Compact grid" title="Compact grid" aria-pressed={compact} onClick={() => setCompact(!compact)}>▦</button>
      </div>
      {err && <p className="error">⚠️ {err}</p>}
      {sum.err && <p className="error">{sum.label}: {sum.err}</p>}
      {!!doc && (doc.unclassified.length > 0 || doc.broken_rules.length > 0) && (
        <p className="todo-alert">⚠️ The inventory is incomplete: {doc.unclassified.length} kinds of objects have no rule, {doc.broken_rules.length} coverage rules lost their evidence. Re-run the generator after fixing its config.</p>
      )}
      {!doc && !err && <p className="muted pad">Loading the inventory…</p>}
      {doc && !shown && <div className="empty"><span>✓</span><h2>Nothing here</h2><p>No asset matches this group, filter and search.</p><button onClick={() => { setQ(''); setGroup(''); setShow('open'); }}>Reset filters</button></div>}
      {sections.map(({ g, label, items, common }) => (
        <section key={g}>
          <h2>{label} <span className="section-count">{items.length}</span><span className="section-host">{(counts[g]?.todo ?? 0)} to do · {(counts[g]?.flagged ?? 0)} open issues · {(counts[g]?.built ?? 0)} built</span></h2>
          {common.map((f) => <p key={f} className="todo-common">Every one of these: {f}</p>)}
          <div className="grid">
            {items.map((a) => {
              const r = a.refs[0]; const w = why(a, new Set(common));
              return (
                <a key={a.id} className="card todo-card" href={`#/t/${encodeURIComponent(a.id)}`} title={a.id}>
                  <div className="thumb ref">
                    {r?.url ? <img loading="lazy" src={r.url} alt={`Reference: ${r.label}`} /> : <div className="ph"><b>🎨</b>{a.refs_missing || 'No reference art yet'}</div>}
                    <span className={`todo-state ${a.status}`}><i />{STATUS[a.status]}</span>
                    {a.refs.length > 1 && <span className="tag">+{a.refs.length - 1} more ref{a.refs.length > 2 ? 's' : ''}</span>}
                    <span className="open-hint">↗ Details</span>
                  </div>
                  <div className="cap">
                    <span className="name">{a.name}</span>
                    <MadeWithBadge m={a.made_with} />
                    <div className="todo-meta">{a.shots.length} shot{a.shots.length === 1 ? '' : 's'} · {secs(a.screen_s)} on screen{a.wip ? ` · WIP: ${a.wip.builds ?? ''} build${a.wip.builds === 1 ? '' : 's'}` : ''}</div>
                    {r && <div className="todo-ref">Ref: {r.label}</div>}
                    {w && <div className={`todo-why ${w.cls}`}>{w.text}</div>}
                  </div>
                </a>
              );
            })}
          </div>
        </section>
      ))}
      {item && <TodoSheet a={item} onClose={close} />}
    </>
  );
}

function List({ title, xs }: { title: string; xs?: string[] | null }) {
  if (!xs?.length) return null;
  return <><h4>{title}</h4><ul className="flag-list">{xs.map((x, i) => <li key={i}>{x}</li>)}</ul></>;
}
function Groups({ title, m }: { title: string; m?: Record<string, string[]> | null }) {
  const e = Object.entries(m || {});
  if (!e.length) return null;
  return (
    <details><summary>{title} ({e.length})</summary>
      <table className="meta"><tbody>{e.map(([k, v]) => <tr key={k}><td>{k}</td><td>{v.join(', ')}</td></tr>)}</tbody></table>
    </details>
  );
}

function TodoSheet({ a, onClose }: { a: TodoItem; onClose: () => void }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose]);
  const au = a.audit;
  return (
    <div className="todo-sheet" role="dialog" aria-modal="true" aria-label={a.name}>
      <div className="sheet-gallery">
        {a.refs.map((r, i) => (
          <figure key={i}>
            {r.full ? <a href={r.full} target="_blank" rel="noreferrer"><img src={r.crop ? r.url || r.full : r.full} alt={r.label} /></a> : <div className="ph">no image</div>}
            <figcaption>Reference: {r.label}{r.crop ? ' (cropped from the sheet; click for the whole sheet)' : ''}</figcaption>
          </figure>
        ))}
        {!a.refs.length && <div className="ph big"><b>🎨</b>{a.refs_missing || 'No reference art yet'}</div>}
        {a.now_url && <figure><a href={a.now_url} target="_blank" rel="noreferrer"><img src={a.now_url} alt="" /></a><figcaption>Now: the audit's comparison picture</figcaption></figure>}
        {a.wip_url && <figure><a href={a.wip_url} target="_blank" rel="noreferrer"><img src={a.wip_url} alt="" /></a><figcaption>Work in progress (not in the film yet)</figcaption></figure>}
      </div>
      <aside>
        <button className="sheet-close" aria-label="Close" onClick={onClose}>×</button>
        <h3>{a.name}</h3>
        <p><span className={`todo-state inline ${a.status}`}><i />{STATUS[a.status]}</span> <span className="muted small">{a.group} · {a.kind} · {a.id}</span></p>
        {a.made_with && <p><MadeWithBadge m={a.made_with} long />{a.made_with.via && a.made_with.label !== 'unknown' && <span className="muted small made-via">{a.made_with.via}</span>}</p>}
        <p className="stats">{a.shots.length} shots · {secs(a.screen_s)} on screen <span className="muted small">(total length of the shots it is in)</span></p>
        <List title="Why it is not done" xs={a.flags} />
        {a.now && <><h4>What the film shows now</h4><p>{a.now}</p></>}
        {a.wip && (
          <><h4>Work in progress</h4>
            <p>{a.wip.state}</p>
            {a.wip.builds != null && <p className="muted small">{a.wip.builds} work builds, latest {base(a.wip.latest)} ({a.wip.latest_at} Kyiv)</p>}
            {a.wip.src && <p className="path">{a.wip.src}</p>}
          </>
        )}
        {a.note && <><h4>Note</h4><p>{a.note}</p></>}
        {au && (
          <details open={a.status !== 'built'}><summary>Audit: {au.verdict ?? 'no verdict'}{au.score != null ? ` (${au.score}/5)` : ''}</summary>
            {au.why && <p className="small">{au.why}</p>}
            <List title="Open (named requests)" xs={au.open} />
            <List title="Other notes" xs={au.residual} />
            <List title="Closed" xs={au.closed?.map((c) => `${c.note} (${c.why})`)} />
          </details>
        )}
        <Groups title="Parts attached to it" m={a.parts} />
        <Groups title="What the location file covers" m={a.covers} />
        <Groups title="Objects in the film" m={a.members} />
        <details><summary>Shots ({a.shots.length})</summary><div className="shot-chips">{a.shots.map((s) => <span key={s}>{s}</span>)}</div></details>
        {a.asset && <p className="path">{a.asset}</p>}
      </aside>
    </div>
  );
}
