import { memo } from 'react';
import type { Item } from './types.ts';
import { kyiv, mb } from './libraryFormat.ts';
import { MadeWithBadge } from './MadeWith.tsx';
import { GeometryBadge } from './GeometryCheck.tsx';
import { thumbnailUrl } from './imageLinks.ts';

export function assetStatus(it: Item): { cls: string; tip: string } {
  const j = it.job.find((x) => x.state === 'error');
  if (j) return { cls: 'err', tip: `${j.kind} failed: ${j.err}` };
  const q = it.job.find((x) => x.state === 'running' || x.state === 'queued');
  if (q) return { cls: 'busy', tip: `${q.kind} ${q.state}…` };
  if (!it.preview) return { cls: 'none', tip: 'no preview yet' };
  return it.preview.fresh
    ? { cls: 'ok', tip: `render ${kyiv(it.preview.mtime)} (${it.preview.origin === 'dash' ? 'dashboard Blender render' : 'pipeline preview'})` }
    : { cls: 'stale', tip: `preview older than asset (${kyiv(it.preview.mtime)})` };
}

// Stable item references let unrelated controls and catalog changes skip card
// subtrees. Age is a value prop so relative timestamps still refresh correctly.
export const AssetCard = memo(function AssetCard({ item: it, age }: { item: Item; age: string }) {
  const st = assetStatus(it);
  return <a className="card asset-card" href={`#/a/${encodeURIComponent(it.id)}`} title={it.path}>
    <div className="thumb">
      {it.preview ? <img loading="lazy" decoding="async" src={thumbnailUrl(it.preview.url, 320, it.preview.bytes)} alt="" onError={e => { if (it.preview && e.currentTarget.src !== new URL(it.preview.url, location.href).href) e.currentTarget.src = it.preview.url; }} /> : <div className="ph">🧊</div>}
      <span className={`preview-state ${st.cls}`} title={st.tip}><i />{st.cls === 'ok' ? 'Fresh' : st.cls === 'busy' ? 'Rendering' : st.cls === 'err' ? 'Failed' : st.cls === 'stale' ? 'Outdated' : 'No preview'}</span><span className="open-hint">↗ Explore in 3D</span>
      {!it.glb && it.blend && <span className="tag" title="Blender file; opens after a GLB export">.blend</span>}
    </div>
    <div className="cap">
      <span className="name">{it.key}</span>
      {it.group && <span className="muted"> · {it.group}</span>}
      <MadeWithBadge m={it.made_with} />
      <GeometryBadge b={it.integrity} />
      <div className="muted small" title={kyiv(it.assetMtime)}>{age} · {mb(it.glbBytes ?? it.blendBytes)}</div>
    </div>
  </a>;
});
