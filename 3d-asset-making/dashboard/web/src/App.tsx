import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import type { Catalog, Item } from './types.ts';
const Viewer = lazy(() => import('./Viewer.tsx'));
import TodoView from './Todo.tsx';
import RunsView from './Runs.tsx';
import NavTree, { FOLDER, inFolder, folderTitle } from './NavTree.tsx';
import GroupView from './Group.tsx';
import { hasFault } from './GeometryCheck.tsx';
import { readAssetRoute } from './assetLinks.ts';
import { ago } from './libraryFormat.ts';
import { AssetCard, assetStatus as status } from './AssetCard.tsx';
import { reuseCatalogItems } from './catalogItems.ts';
const HOST = { pc: '🖥️', tr: '🧵' } as const;
const HOST_NAME = { pc: 'this PC', tr: 'the build box (Threadripper)' } as const;

// faults first, then pointers to look at, then sound, then unchecked (the grid shows cached checks only; opening an asset runs one)
const geoRank = (i: Item) => ({ fault: 0, unreadable: 1, look: 2, sound: 3 } as Record<string, number>)[i.integrity?.status ?? ''] ?? 4;
const routeId = () => readAssetRoute()?.id || null;
const isRuns = () => location.hash.startsWith('#/runs');   // Runs view: #/runs[/<run id>]
const groupRoute = () => (location.hash.startsWith('#/group/') ? decodeURIComponent(location.hash.slice(8)) : null);   // #/group/<key>

export default function App() {
  const [cat, setCat] = useState<Catalog | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [sort, setSort] = useState('recent');
  const [filter, setFilter] = useState('all');
  const [compact, setCompact] = useState(false);
  // ?c=<collection id> (e.g. ?c=todo:mv-todo:film) opens a collection by link; else the last one used here
  const [src, setSrc] = useState<string>(() => { const c = new URLSearchParams(location.search).get('c'); if (c != null) return c; try { return localStorage.getItem('bd.src') || ''; } catch { return ''; } });
  const [routeKey,setRouteKey]=useState(location.hash);
  const [open, setOpen] = useState<string | null>(routeId());
  const [runs, setRuns] = useState(isRuns());
  const [showRunCollections, setShowRunCollections] = useState(false);
  const [gkey, setGkey] = useState(groupRoute());
  const cur = runs ? '#runs' : gkey ? '#group' : src;   // the rail's selection
  const pick = (id: string) => { if (runs || gkey) { history.pushState(null, '', location.pathname + location.search); setRuns(false); setGkey(null); } setSrc(id); };

  useEffect(() => {
    let stop = false, timer = 0, inFlight = false, etag = '';
    let snapshot: Catalog | null = null;
    const controller = new AbortController();
    const busy = (c: Catalog | null) => !!c && Object.values(c.queue).some((x) => x.running + x.queued > 0);
    async function tick() {
      if (stop || inFlight) return;
      inFlight = true;
      try {
        if (document.visibilityState === 'visible') {
          const response = await fetch('api/catalog', { cache: 'no-store', signal: controller.signal, headers: etag ? { 'If-None-Match': etag } : {} });
          if (response.status === 304) {
            if (!snapshot) throw new Error('Catalog cache unavailable');
          } else {
            if (!response.ok) throw new Error(`Catalog unavailable (${response.status})`);
            const c = reuseCatalogItems(await response.json() as Catalog, snapshot);
            if (stop) return;
            snapshot = c; etag = response.headers.get('etag') || ''; setCat(c);
          }
          if (!stop) setErr(null);
        }
      } catch (e) { if (!stop) setErr(String(e)); }
      finally {
        inFlight = false;
        if (!stop) timer = window.setTimeout(tick, document.visibilityState === 'visible' && (snapshot?.refreshing || busy(snapshot)) ? 4000 : 20000);
      }
    }
    tick();
    const vis = () => { if (document.visibilityState === 'visible') { clearTimeout(timer); tick(); } };
    document.addEventListener('visibilitychange', vis);
    const hash = () => { setRouteKey(location.hash); setOpen(routeId()); setRuns(isRuns()); if (!routeId()) setGkey(groupRoute()); };
    window.addEventListener('hashchange', hash);
    return () => { stop = true; clearTimeout(timer); controller.abort(); document.removeEventListener('visibilitychange', vis); window.removeEventListener('hashchange', hash); };
  }, []);
  useEffect(() => {
    try { localStorage.setItem('bd.src', src); } catch { /* private mode */ }
    const u = new URL(location.href); if (src) u.searchParams.set('c', src); else u.searchParams.delete('c');
    if (u.href !== location.href) history.replaceState(history.state, '', u);   // the address is a link to this collection
  }, [src]);

  const sections = useMemo(() => {
    if (!cat) return [];
    const needle = q.trim().toLowerCase();
    return cat.sources
      .filter((s) => !src || s.id === src || (src.startsWith(FOLDER) && inFolder(s, src.slice(FOLDER.length))))
      .map((s) => ({ s, items: cat.items.filter((i) => i.source === s.id && (!needle || `${i.key} ${i.group} ${s.label} ${i.made_with?.label ?? ''}`.toLowerCase().includes(needle)) && (filter === 'all' || (filter === 'geo-fault' ? hasFault(i.integrity) : filter === 'geo-sound' ? i.integrity?.status === 'sound' : filter === 'attention' ? ['err', 'stale', 'none'].includes(status(i).cls) : status(i).cls === filter))).sort((a, b) => sort === 'faults' ? geoRank(a) - geoRank(b) || b.assetMtime - a.assetMtime : sort === 'name' ? a.key.localeCompare(b.key) : sort === 'size' ? (b.glbBytes ?? b.blendBytes ?? 0) - (a.glbBytes ?? a.blendBytes ?? 0) : b.assetMtime - a.assetMtime) }))
      .filter((x) => x.items.length)
      .sort((a, b) => Math.max(...b.items.map(i => i.assetMtime)) - Math.max(...a.items.map(i => i.assetMtime)));
  }, [cat, q, src, sort, filter]);

  const item = open && cat ? cat.items.find((i) => i.id === open) : null;
  const todoSel = src.startsWith('todo:') ? cat?.todo?.find((t) => 'todo:' + t.id === src) || null : null;
  const pending = cat ? Object.values(cat.queue).reduce((n, x) => n + x.running + x.queued, 0) : 0;

  return (
    <div className={`app${runs ? ' runs-active' : ''}${showRunCollections ? ' run-collections-open' : ''}`}>
      <nav className="library-nav" aria-label="Asset collections" inert={!!item || undefined}>
        <div className="brand"><span className="brand-icon">⬡</span><div>Blender assets<small>Your 3D library</small></div></div>
        <div className="nav-label">Collections</div>
        {runs && <button className="mobile-library-toggle" aria-label="Toggle asset collections" aria-expanded={showRunCollections} onClick={() => setShowRunCollections(!showRunCollections)}>☰ Collections</button>}
        <button className={!cur ? 'collection on' : 'collection'} onClick={() => pick('')} aria-pressed={!cur}><span>◈</span><span>All assets</span><b>{cat?.items.length ?? '…'}</b></button>
        {cat && <NavTree sources={cat.sources} cur={cur} pick={pick} hostName={s => HOST_NAME[s.host as 'pc' | 'tr'] || 'This machine'} />}
        {!!cat?.todo?.length && <div className="nav-label todo-label">To be done</div>}
        {cat?.todo?.map(t => { const n = (t.totals?.todo ?? 0) + (t.totals?.flagged ?? 0); return <button key={t.id} className={cur === 'todo:' + t.id ? 'collection todo on' : 'collection todo'} onClick={() => pick('todo:' + t.id)} aria-pressed={cur === 'todo:' + t.id} title={t.err || `${t.label}: ${t.totals?.todo ?? 0} to do, ${t.totals?.flagged ?? 0} built with open issues`}><span>{t.emoji}</span><span>{t.title || t.group}<small>{t.err ? 'unreadable' : `${t.totals?.todo ?? 0} to do · ${t.totals?.flagged ?? 0} open issues`}</small></span><b>{n}</b></button>; })}
        <div className="nav-label todo-label">Activity</div>
        <a className={runs ? 'collection on' : 'collection'} href="#/runs" aria-current={runs ? 'page' : undefined} title="Asset-building runs: progress, pictures, API cost and time"><span>🏃</span><span>Runs<small>progress · API $ · time</small></span><b /></a>
        <div className="nav-foot"><span className={pending || cat?.refreshing ? 'live busy' : 'live'} />{err ? 'Connection interrupted' : !cat ? 'Connecting…' : cat.refreshing ? 'Refreshing library…' : pending ? `${pending} jobs in progress` : 'Library synced'}<small>Previews refresh while you browse</small></div>
      </nav>
      <main inert={!!item || undefined} className={compact ? 'library compact' : 'library'}>
      {runs ? <RunsView route={routeKey} /> : gkey ? <GroupView cat={cat} gkey={gkey} /> : src.startsWith('todo:') ? (todoSel ? <TodoView sum={todoSel} compact={compact} setCompact={setCompact} /> : (
        <div className="empty"><span>🎨</span><h2>{cat ? 'This to-do list is gone' : 'Connecting…'}</h2>{cat && <><p>Its inventory file is no longer found.</p><button onClick={() => setSrc('')}>Show all assets</button></>}</div>
      )) : <>
      <header className="library-heading">
        <div><p className="breadcrumb">Workspace / Asset library</p><h1>{folderTitle(src) || cat?.sources.find(s => s.id === src)?.label || 'All assets'}<span>{sections.reduce((n, s) => n + s.items.length, 0)}</span></h1><p className="intro">Browse your renders. Open any asset to explore it in 3D.</p></div>
        <span className="queue">{cat?.refreshing ? '↻ Refreshing library…' : pending ? `⚙ ${pending} rendering` : cat ? `✓ Synced ${ago(cat.generated)}` : 'Connecting…'}</span>
      </header>
      <div className="toolbar">
        <label className="search-wrap"><span aria-hidden="true">⌕</span><textarea rows={1} className="search" aria-label="Search assets" placeholder="Search assets or collections…" value={q} onChange={e => setQ(e.target.value.replace(/\n/g, ''))} />{q && <button aria-label="Clear search" onClick={() => setQ('')}>×</button>}</label>
        <select aria-label="Preview status" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All previews</option><option value="ok">Fresh previews</option><option value="busy">Rendering</option><option value="attention">Needs attention</option><option value="geo-fault">⚠ Geometry faults</option><option value="geo-sound">✓ Geometry sound</option></select>
        <select aria-label="Sort assets" value={sort} onChange={e => setSort(e.target.value)}><option value="recent">Recently updated</option><option value="name">Name A–Z</option><option value="size">Largest first</option><option value="faults">Geometry faults first</option></select>
        <button className="density" aria-label="Compact grid" title="Compact grid" aria-pressed={compact} onClick={() => setCompact(!compact)}>▦</button>
      </div>
      {err && <p className="error">⚠️ {err}</p>}
      {!cat && !err && <p className="muted pad">Scanning PC + the build box…</p>}
      {cat?.sources.filter(s => s.err && (!src || src === s.id)).map(s => <p className="error" key={s.id}>{s.label}: {s.err}</p>)}
      {cat && !sections.length && <div className="empty"><span>⌕</span><h2>No matching assets</h2><p>Try another name, collection, or preview status.</p><button onClick={() => { setQ(''); setSrc(''); setFilter('all'); }}>Reset filters</button></div>}
      {sections.map(({ s, items }) => (
        <section key={s.id}>
          <h2>{s.emoji} {s.label} <span className="section-count">{items.length}</span><span className="section-host">{HOST[s.host as 'pc' | 'tr']} {HOST_NAME[s.host as 'pc' | 'tr'] || 'This machine'}</span></h2>
          <div className="grid">
            {items.map(it => <AssetCard key={it.id} item={it} age={ago(it.assetMtime)} />)}
          </div>
        </section>
      ))}
      </>}
      </main>
      {item && <Suspense fallback={<div className="viewer-loading" role="status">Opening asset…</div>}><Viewer key={item.id+routeKey} item={item} items={cat?.items||[]} collection={cat?.sources.find(s => s.id === item.source)?.label} onClose={() => { history.pushState(null, '', location.pathname + location.search); setOpen(null); }} /></Suspense>}
    </div>
  );
}
