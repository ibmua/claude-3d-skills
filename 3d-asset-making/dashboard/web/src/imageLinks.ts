export function thumbnailUrl(url: string, width = 320, bytes?: number) {
  const source = new URL(url, location.href);
  const base = new URL('.', location.href);
  if (source.origin !== base.origin || !source.pathname.startsWith(base.pathname + 'f/')) return url;
  const params = new URLSearchParams({ src: source.pathname.slice(base.pathname.length) + source.search, w: String(width) });
  if (bytes != null) params.set('bytes', String(bytes));
  return `api/thumbnail?${params}`;
}
