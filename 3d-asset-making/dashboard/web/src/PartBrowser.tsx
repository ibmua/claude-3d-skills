import { useEffect, useRef, useState } from 'react';
import { assetHref } from './assetLinks.ts';
import type { ModelPart } from './modelParts.ts';

export default function PartBrowser({ asset, parts, selected, picked, active, revision, capture, onSelect, onVisible, onAll }: {
  asset: string; parts: ModelPart[]; selected: string | null; picked: string | null; active: boolean; revision: string;
  capture: (id: string) => Promise<string | null>; onSelect: (id: string) => void;
  onVisible: (uuid: string, visible: boolean) => void; onAll: () => void;
}) {
  const [expanded, setExpanded] = useState(!!selected), [query, setQuery] = useState('');
  const [pictures, setPictures] = useState<Record<string, string | null>>({});
  const [visible, setVisible] = useState<string[]>([]);
  const root = useRef<HTMLDivElement>(null), cache = useRef<Record<string, string | null>>({});
  const [stableRevision, setStableRevision] = useState(revision);
  useEffect(()=>{if(picked){setExpanded(true);setQuery('');const timer=setTimeout(()=>{const card=[...(root.current?.querySelectorAll<HTMLElement>('[data-part]')||[])].find(el=>el.dataset.part===picked);card?.scrollIntoView({block:'nearest',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});},80);return()=>clearTimeout(timer);}},[picked]);
  const filtered = parts.filter(p => p.name.toLowerCase().includes(query.toLowerCase()));
  const key = filtered.map(p => p.id).join('|');
  useEffect(() => { const timer = setTimeout(() => setStableRevision(revision), 300); return () => clearTimeout(timer); }, [revision]);
  useEffect(() => { cache.current = {}; setPictures({}); }, [stableRevision]);
  useEffect(() => { cache.current = {}; setPictures({}); setQuery(''); }, [asset]);
  useEffect(() => {
    if (!expanded || !root.current) { setVisible([]); return; }
    const inView = new Set<string>();
    const observer = new IntersectionObserver(entries => {
      entries.forEach(e => { const id = (e.target as HTMLElement).dataset.part!; if (e.isIntersecting) inView.add(id); else inView.delete(id); });
      setVisible([...inView]);
    }, { root: root.current.closest('.asset-inspector'), rootMargin: '80px' });
    root.current.querySelectorAll('[data-part]').forEach(el => observer.observe(el));
    return () => observer.disconnect();
  }, [expanded, key]);
  useEffect(() => {
    if (!expanded || !active || document.hidden) return;
    let cancelled = false, timer = 0;
    const next = async () => {
      const id = visible.find(id => !(id in cache.current)); if (!id || cancelled) return;
      try {
        const url = await capture(id);
        if (cancelled) return;
        cache.current[id] = url; setPictures({ ...cache.current });
      } catch { if (!cancelled) { cache.current[id] = null; setPictures({ ...cache.current }); } }
      if (!cancelled) timer = window.setTimeout(next, 40);
    };
    timer = window.setTimeout(next, 100);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [expanded, active, visible, stableRevision, capture]);
  return <details className="parts-details" open={expanded} onToggle={e => setExpanded(e.currentTarget.open)}>
    <summary>Parts <span>{parts.length}</span></summary>
    <div className="parts-toolbar"><input aria-label="Find part" type="search" placeholder="Find a part…" value={query} onChange={e => setQuery(e.target.value)} /><button onClick={onAll} title="Restore all parts and fit model">Show all</button></div>
    <p className="inspector-note">Click a picture to isolate. ↗ opens that part in a new tab.</p>
    {selected && <p className="selected-part" role="status">Isolated: <strong>{parts.find(p => p.id === selected)?.name}</strong></p>}
    <div className="part-grid" ref={root}>{filtered.map(p => <div className={`part-card${selected === p.id ? ' selected' : ''}${picked===p.id?' picked':''}`} data-part={p.id} key={p.id}>
      <a className="part-picture" href={assetHref(asset, {part: p.id, view: 'model'})} aria-label={`Inspect part ${p.name}`} onClick={e => { if (e.button === 0 && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey) { e.preventDefault(); onSelect(p.id); } }}>
        {pictures[p.id] ? <img src={pictures[p.id]!} alt={`${p.name} part preview`} draggable={false} /> : <span>{p.id in pictures ? 'No picture' : active ? 'Preparing…' : 'Open 3D'}</span>}
      </a>
      <div className="part-caption"><label title={p.name}><input type="checkbox" aria-label={`Show part ${p.name}`} checked={p.visible} onChange={e => onVisible(p.uuid, e.target.checked)} /><span>{p.name.replace(/_/g, ' ')}</span></label><a href={assetHref(asset, {part: p.id, view: 'model'})} target="_blank" rel="noopener noreferrer" aria-label={`Open part ${p.name} in new tab`} title="Open part in new tab">↗</a></div>
    </div>)}</div>
    {!filtered.length && <p className="inspector-note">No parts match “{query}”.</p>}
  </details>;
}
