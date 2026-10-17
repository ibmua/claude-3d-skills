import type { Catalog } from './types.ts';

// Preserve unchanged item identities across fresh 200 responses. Compare every
// public field so cost, geometry, preview, extras and metadata edits still update.
export function reuseCatalogItems(next: Catalog, previous: Catalog | null): Catalog {
  if (!previous) return next;
  const old = new Map(previous.items.map(item => [item.id, item]));
  next.items = next.items.map(item => {
    const before = old.get(item.id);
    return before && JSON.stringify(before) === JSON.stringify(item) ? before : item;
  });
  return next;
}
