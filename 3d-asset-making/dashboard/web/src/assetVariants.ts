import type { Item } from './types.ts';
export function assetVariants(item: Item, items: Item[]) {
  const suffix = /-(original|near|mid|far)$/i, stem = item.key.replace(suffix, '');
  const label = (i: Item) => suffix.exec(i.key)?.[1].toLowerCase() || 'current';
  const record = item.made_with?.record;
  const folder = (i: Item) => i.path.replace(/\/(export|original)\/[^/]+$/, '');
  const family = items.filter(i => i.host === item.host && i.key.replace(suffix, '') === stem && (record && i.made_with?.record === record || folder(i) === folder(item)));
  const order = ['original', 'near', 'mid', 'far', 'current'];
  return (family.length ? family : [item]).sort((a,b) => order.indexOf(label(a)) - order.indexOf(label(b))).map(i => ({ item: i, label: label(i) }));
}
