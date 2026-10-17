import { useEffect, useState } from 'react';
import type { IntegrityBadge, IntegrityPlace, IntegrityResponse, IntegrityResult } from './types.ts';

// Geometry check (owner 2026-10-12): the 3d-modelling skill's mesh_integrity.py, run by the server when an asset opens
// (integrity.mjs, /api/integrity). The card shows only cached results; the viewer panel lists every line and its places.
const MARK = { sound: '✓', fault: '⚠', look: '⚠', unreadable: '⚠' } as const;
const NAME = { sound: 'Sound', fault: 'Fault', look: 'Look', unreadable: 'Unreadable' } as const;
export const hasFault = (b?: IntegrityBadge | null) => !!b && b.status !== 'sound';

export function GeometryBadge({ b }: { b?: IntegrityBadge | null }) {
  if (!b) return null;
  const tip = `Geometry check: ${b.verdict}${b.against ? ` (compared with the ${b.against} version)` : ''}`;
  return <span className={`geo-badge ${b.status}`} title={tip}>{MARK[b.status]}{b.status !== 'sound' && <span>{b.short}</span>}</span>;
}

// the lines that decide the verdict first (floating, blinking, slits, lost), then the pointers
const SHOWN = ['BODIES', 'FLICKER', 'GAPS', 'AGAINST', 'OPEN EDGES', 'LOOKED INTO', 'LOOK', 'WARNING', 'NOTE'];

export default function GeometryCheck({ id, active, onMark }: { id: string; active: boolean; onMark?: (p: IntegrityPlace | null) => void }) {
  const [r, setR] = useState<IntegrityResponse | null>(null);
  const [marked, setMarked] = useState<string | null>(null);
  useEffect(() => {
    let stop = false, timer = 0; setR(null); setMarked(null); onMark?.(null);
    const controller = new AbortController();
    const poll = async () => {
      try {
        const response = await fetch(`api/integrity?id=${encodeURIComponent(id)}`, { signal: controller.signal });
        const next: IntegrityResponse = await response.json();
        if (stop) return; setR(next);
        // poll only while a check runs, or while this viewer waits for the 3D export the check needs
        if (next.state === 'queued' || next.state === 'running' || (next.state === 'needs-export' && active)) timer = window.setTimeout(poll, 2500);
      } catch { if (!stop) timer = window.setTimeout(poll, 5000); }
    };
    poll();
    return () => { stop = true; clearTimeout(timer); controller.abort(); };
  }, [id, active]);
  const res: IntegrityResult | null | undefined = r?.result;
  const busy = r?.state === 'queued' || r?.state === 'running';
  const mark = (key: string, p: IntegrityPlace) => { const same = marked === key; setMarked(same ? null : key); onMark?.(same ? null : p); };
  const chip = res ? <span className={`geo-badge ${res.status}`}>{MARK[res.status]} {NAME[res.status]}</span> : <span className="geo-badge pending">{busy ? 'Checking…' : r?.state === 'needs-export' ? 'Needs 3D' : r?.state === 'error' ? 'Failed' : '…'}</span>;
  const b2b = res?.counts?.back_to_back_pairs || 0;
  return <details className="geometry-check">
    <summary>Geometry check {chip}</summary>
    {!r && <p className="inspector-note">Loading…</p>}
    {r?.state === 'needs-export' && <p className="inspector-note">The check reads the GLB. Open the 3D model; it runs when the export finishes.</p>}
    {r?.state === 'error' && <p className="inspector-note">Check failed: {r.err}</p>}
    {busy && <p className="inspector-note" role="status">{res ? 'The file or its reference changed; checking again…' : 'Checking floating parts, open edges, slits and blinking faces… (seconds; up to ~4 min for big models)'}</p>}
    {res && <>
      <p className={`geo-verdict ${res.status}`}>{res.verdict}</p>
      {res.sections.filter(s => SHOWN.includes(s.kind)).sort((a, b) => SHOWN.indexOf(a.kind) - SHOWN.indexOf(b.kind)).map((s, si) => <div key={si} className={`geo-line ${s.kind === 'LOOK' ? 'geo-look' : ''}`}>
        <b>{s.kind}</b> <span>{s.text}</span>
        {!!s.details.length && <ul className="geo-places">{(() => { let n = 0; return s.details.map((d, di) => {
          const p = /\(-?\d+(?:\.\d+)?, -?\d/.test(d) ? s.places[n++] : undefined, key = `${si}:${di}`;
          return <li key={key} className={p ? 'placed' : ''}>{p && <button aria-pressed={marked === key} disabled={!onMark} onClick={() => mark(key, p)} title={onMark ? 'Mark this place in 3D' : 'Open 3D to mark places'} aria-label={`Mark ${p.label} in 3D`}>⌖</button>}<span>{d}</span></li>; }); })()}</ul>}
      </div>)}
      {b2b > 0 && <p className="inspector-note">{res.doubleSided ? `⚠ ${res.doubleSided} double-sided material${res.doubleSided === 1 ? '' : 's'} in this GLB: the ${b2b} back-to-back face pairs can blink where they use one.` : `The ${b2b} back-to-back pairs use no double-sided material, so they do not blink.`}</p>}
      {res.againstNote && <p className="inspector-note">{res.againstNote}</p>}
      <p className="inspector-note">Checked {new Date(res.at).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })} Kyiv in {(res.ms / 1000).toFixed(1)} s{res.against ? ` · compared with ${res.against.key}` : ''}. Coordinates in metres, glTF axes (+Y up); ⌖ marks a place in 3D. Re-runs only when the file changes.</p>
      <details className="geo-raw"><summary>Full report</summary><pre>{res.text}</pre></details>
    </>}
  </details>;
}
