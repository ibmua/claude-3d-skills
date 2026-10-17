import { validView, type SavedView } from './viewerSettings.ts';
export type AssetRoute = { id: string; part?: string; view?: 'model' | 'photos'; photo?: string; state?: SavedView };

export function readAssetRoute(): AssetRoute | null {
  if (!location.hash.startsWith('#/a/')) return null;
  const [id, query = ''] = location.hash.slice(4).split('?');
  try {
    const params = new URLSearchParams(query), view = params.get('view');
    let state: SavedView | undefined;
    try { const raw = params.get('state'); if (raw && raw.length < 32000) state = validView(JSON.parse(raw)); } catch { /* A malformed optional state leaves the asset usable. */ }
    return { id: decodeURIComponent(id), part: params.get('part') || undefined, photo: params.get('photo') || undefined, state, view: view === 'photos' || view === 'model' ? view : undefined };
  } catch { return null; }
}

export function assetHref(id: string, options: Omit<AssetRoute, 'id'> = {}) {
  const params = new URLSearchParams();
  if (options.part) params.set('part', options.part);
  if (options.view) params.set('view', options.view);
  if (options.photo) params.set('photo', options.photo);
  if (options.state) params.set('state', JSON.stringify(validView(options.state)));
  return `#/a/${encodeURIComponent(id)}${params.size ? `?${params}` : ''}`;
}
