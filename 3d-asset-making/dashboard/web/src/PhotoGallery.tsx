import { useEffect, useRef, useState } from 'react';
import type { Item } from './types.ts';
import { thumbnailUrl } from './imageLinks.ts';

export type Photo = { url: string; label: string };
const names: Record<string, string> = { front34: 'Front ¾', rear34: 'Rear ¾', under34: 'Underneath ¾', nose: 'Nose detail', side: 'Side view', top: 'Top view', 'film-sheet': 'Film sheet' };
export function assetPhotos(item: Item): Photo[] {
  const unique = new Map<string, Photo>();
  for (const url of [...(item.preview ? [item.preview.url] : []), ...item.extras]) {
    const parsed = new URL(url, location.href);
    if (unique.has(parsed.pathname)) continue;
    const filename = decodeURIComponent(parsed.pathname.split('/').pop() || 'Render').replace(/\.[^.]+$/, '');
    const label = names[filename.toLowerCase()] || filename.replace(/[_-]+/g, ' ').replace(/^./, c => c.toUpperCase());
    if (!parsed.searchParams.has('v')) parsed.searchParams.set('v', String(Math.floor(item.preview?.mtime || item.assetMtime)));
    unique.set(parsed.pathname, { url: url.split(/[?#]/)[0] + parsed.search, label });
  }
  return [...unique.values()];
}

export function PhotoStrip({ photos, index, onSelect }: { photos: Photo[]; index: number; onSelect: (i: number) => void }) {
  const strip = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = strip.current, active = el?.children[index] as HTMLElement | undefined;
    if (!el || !active) return;
    const left = active.offsetLeft - el.offsetLeft;
    if (left < el.scrollLeft) el.scrollTo({ left, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    else if (left + active.offsetWidth > el.scrollLeft + el.clientWidth) el.scrollTo({ left: left + active.offsetWidth - el.clientWidth, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  }, [index]);
  return <div className="photo-strip" ref={strip} aria-label="Render thumbnails">
    {photos.map((p, i) => <div key={p.url} className={`photo-thumb${i === index ? ' selected' : ''}`}><button aria-label={`View ${p.label}`} aria-pressed={i === index} title={p.label} onClick={() => onSelect(i)}><img src={thumbnailUrl(p.url, 160)} alt="" loading="lazy" decoding="async" draggable={false} onError={e => { if (e.currentTarget.src !== new URL(p.url, location.href).href) e.currentTarget.src = p.url; }} /><span>{p.label}</span></button><a href={p.url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${p.label} image in new tab`} title="Open image in new tab">↗</a></div>)}
  </div>;
}

export default function PhotoGallery({ photos, index, onSelect, fullscreen, onFullscreen, title }: {
  photos: Photo[]; index: number; onSelect: (i: number) => void; fullscreen: boolean; onFullscreen: () => void; title: string;
}) {
  const [shown, setShown] = useState(index);
  const [fading, setFading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);
  const [size, setSize] = useState('');
  const [zoom, setZoom] = useState(false);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const pointer = useRef<{ x: number; y: number; px: number; py: number } | null>(null);
  const surface = useRef<HTMLDivElement>(null);
  const image = useRef<HTMLImageElement>(null);
  const intent = useRef(index); intent.current = index;
  const photo = photos[shown];
  const move = (n: number) => onSelect((index + n + photos.length) % photos.length);

  useEffect(() => {
    if (index === shown) return;
    setFading(true);
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const timer = window.setTimeout(() => { setLoaded(false); setError(false); setSize(''); setZoom(false); setPan({x: 0, y: 0}); setShown(index); }, reduce ? 0 : 110);
    return () => clearTimeout(timer);
  }, [index, shown]);
  useEffect(() => {
    if ((!loaded && !error) || shown !== index) return;
    const timer = window.setTimeout(() => setFading(false), 40);
    return () => clearTimeout(timer);
  }, [loaded, error, shown, index]);
  useEffect(() => {
    // Fetch only adjacent images; the thumbnails remain lazy.
    const images = photos.length > 1 ? [-1, 1].map(n => { const img = new Image(); img.src = photos[(index + n + photos.length) % photos.length].url; return img; }) : [];
    return () => { images.forEach(img => { img.src = ''; }); };
  }, [index, photos]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || (e.target as HTMLElement)?.matches('input, textarea, select, [contenteditable=true]')) return;
      const i = intent.current;
      if (e.key === 'ArrowRight') onSelect((i + 1) % photos.length);
      else if (e.key === 'ArrowLeft') onSelect((i - 1 + photos.length) % photos.length);
      else if (e.key === 'Home') onSelect(0);
      else if (e.key === 'End') onSelect(photos.length - 1);
      else return;
      e.preventDefault();
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [photos.length, onSelect]);
  useEffect(() => {
    const el = surface.current;
    if (!el) return;
    const wheel = (e: WheelEvent) => {
      if (Math.abs(e.deltaX) <= Math.abs(e.deltaY) || Math.abs(e.deltaX) < 12 || zoom) return;
      e.preventDefault();
      const now = performance.now();
      if (now - lastWheel > 450) { const i = intent.current; onSelect((i + (e.deltaX > 0 ? 1 : -1) + photos.length) % photos.length); lastWheel = now; }
    };
    let lastWheel = -Infinity;
    el.addEventListener('wheel', wheel, { passive: false });
    return () => el.removeEventListener('wheel', wheel);
  }, [onSelect, photos.length, zoom]);
  const changing = fading || !loaded;
  const toggleZoom = () => { setZoom(z => !z); setPan({ x: 0, y: 0 }); };
  return <div className={`photo-gallery${fullscreen ? ' immersive' : ''}`} role={fullscreen ? 'dialog' : undefined} aria-modal={fullscreen || undefined} aria-label={`${title} renders`}>
    <div className="gallery-toolbar">
      <div className="photo-caption" aria-live="polite"><strong className={changing ? 'changing' : ''}>{photo.label}</strong><span><span className={`photo-position${changing ? ' changing' : ''}`}>{shown + 1}</span> / {photos.length}<span className={`photo-size${changing ? ' changing' : ''}`}>{size && ` · ${size}`}</span></span></div>
      <div className="gallery-actions">
        <button onClick={toggleZoom} aria-pressed={zoom} disabled={error || !loaded} title={zoom ? 'Fit image' : 'Zoom to 2×'} aria-label={zoom ? 'Fit image' : 'Zoom image'}>{zoom ? '⊖' : '⊕'}</button>
        <a href={photo.url} target="_blank" rel="noreferrer" title="Open original image" aria-label="Open original image">↗</a>
        <button onClick={onFullscreen} title={fullscreen ? 'Close full screen (Esc)' : 'Full screen'} aria-label={fullscreen ? 'Close full screen' : 'Full screen'}>{fullscreen ? '✕' : '⛶'}</button>
      </div>
    </div>
    <div className={`photo-surface${zoom ? ' zoomed' : ''}`} ref={surface}
      onDoubleClick={toggleZoom}
      onPointerDown={e => { if (e.button !== 0 || (e.target as HTMLElement).closest('a, button')) return; pointer.current = {x: e.clientX, y: e.clientY, px: pan.x, py: pan.y}; e.currentTarget.setPointerCapture(e.pointerId); }}
      onPointerMove={e => { const p = pointer.current; if (p && zoom) { const bounds = surface.current!.getBoundingClientRect(), img = image.current; const maxX = Math.max(0, ((img?.clientWidth || 0) * 2 - bounds.width) / 2), maxY = Math.max(0, ((img?.clientHeight || 0) * 2 - bounds.height) / 2); setPan({x: Math.max(-maxX, Math.min(maxX, p.px + e.clientX - p.x)), y: Math.max(-maxY, Math.min(maxY, p.py + e.clientY - p.y))}); } }}
      onPointerUp={e => { const p = pointer.current; pointer.current = null; if (!p || zoom || photos.length < 2) return; const dx = e.clientX - p.x, dy = e.clientY - p.y; if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy) * 1.3) move(dx < 0 ? 1 : -1); }}
      onPointerCancel={() => { pointer.current = null; }}>
      {(!loaded && !error) && <span className="photo-loading" role="status">Loading render…</span>}
      <div className={`photo-image${fading || !loaded ? ' changing' : ''}`} style={{transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom ? 2 : 1})`}}>
        <img ref={image} key={photo.url} src={photo.url} alt={`${title}: ${photo.label}`} draggable={false}
          onLoad={e => { setLoaded(true); setError(false); setSize(`${e.currentTarget.naturalWidth.toLocaleString()} × ${e.currentTarget.naturalHeight.toLocaleString()}`); }}
          onError={() => { setError(true); setLoaded(false); }} />
      </div>
      {error && <div className="photo-error" role="status"><strong>This render could not load</strong><p>Try another image or open the original.</p><a href={photo.url} target="_blank" rel="noreferrer">Open original ↗</a></div>}
    </div>
    {photos.length > 1 && <><button className="photo-arrow previous" aria-label="Previous render" title="Previous render (←)" onClick={() => move(-1)}>‹</button><button className="photo-arrow next" aria-label="Next render" title="Next render (→)" onClick={() => move(1)}>›</button></>}
    <div className="gallery-footer"><PhotoStrip photos={photos} index={index} onSelect={onSelect} /><p>Swipe or use <kbd>←</kbd> <kbd>→</kbd><span>Double-click to zoom</span></p></div>
  </div>;
}
