// The picture effects (the game a design decision) come from the GAME's canonical list, read at build time:
//   <game>/src/picture/effects.json (alias in vite.config.ts).
// The viewer keeps no copy. Game option ids map to viewer values by option.viewerValue (or, for resolution, the
// option's scale × the game's QUALITY.maxPixelRatio); viewer-only fields are viewerOptionList, viewerOptions, viewerHow,
// viewerCost. A game edit reaches the viewer at the next `npm run build`. tests/game_look.mjs checks the mapping.
import list from '@game-picture-effects';

export type EffectKey = 'ao' | 'contactShadow' | 'sunShadow' | 'bloom' | 'aa' | 'resolution';
export type EffectValue = boolean | number | string;
export type EffectValues = { ao: boolean; contactShadow: boolean; sunShadow: number; bloom: boolean; aa: 'msaa' | 'refine'; resolution: number };
export type Tier = 'standard' | 'low';
type GameOption = { id: string; label: string; viewerValue?: EffectValue; scale?: number };
type GameEffect = { key: EffectKey; label: string; label_long?: string; icon: string; kind: 'toggle' | 'choice'; options: GameOption[];
  game: Record<Tier, string>; viewer: EffectValue; viewerOptions?: EffectValue[]; viewerOptionList?: { value: EffectValue; label: string }[];
  how: string; viewerHow?: string; viewerCost?: unknown };
export type PictureEffect = { key: EffectKey; label: string; icon: string; kind: 'toggle' | 'choice'; options: { value: EffectValue; label: string }[];
  game: Record<Tier, string>; viewer: EffectValue; viewerOptions?: EffectValue[]; how: string; cost: unknown; source: GameEffect };

export const EFFECTS_SOURCE = 'stubs/picture-effects.json';
export const GAME_MAX_PIXEL_RATIO = 2; // the game's QUALITY.maxPixelRatio (src/config.js); tests/game_look.mjs checks it

const raw = (list as { effects: GameEffect[]; tiers: { id: Tier; label: string; note: string }[] });
/** The viewer value of one of the game's option ids, or undefined when the viewer has no equivalent (aa smaa/off). */
export function viewerValueOf(e: GameEffect, id: string): EffectValue | undefined {
  if (e.kind === 'toggle') return id === 'on';
  const o = e.options.find(o => o.id === id);
  if (!o) return undefined;
  if (o.viewerValue !== undefined) return o.viewerValue;
  if (e.key === 'resolution' && o.scale != null) return o.scale * GAME_MAX_PIXEL_RATIO;
  return undefined;
}
export const PICTURE_EFFECTS: PictureEffect[] = raw.effects.map(e => ({
  key: e.key, label: e.label_long || e.label, icon: e.icon, kind: e.kind, options: e.kind === 'toggle' ? [] : e.viewerOptionList || [],
  game: e.game, viewer: e.viewer, viewerOptions: e.viewerOptions, how: e.viewerHow || e.how, cost: e.viewerCost ?? null, source: e,
}));
export const TIERS = raw.tiers;

const values = (pick: (e: PictureEffect) => EffectValue) => Object.fromEntries(PICTURE_EFFECTS.map(e => [e.key, pick(e)])) as EffectValues;
export const tierValues = (tier: Tier) => values(e => viewerValueOf(e.source, e.game[tier]) ?? e.viewer);
export const viewerDefaults = () => values(e => e.viewer);
// The options a look offers for one effect (the viewer look keeps its 1024 floor shadow; the game look offers all).
export const optionsFor = (e: PictureEffect, look: 'viewer' | 'game') => e.options.filter(o => look === 'game' || !e.viewerOptions || e.viewerOptions.includes(o.value));
export function validValues(value: unknown, fallback: EffectValues, look: 'viewer' | 'game'): EffectValues {
  const v = (value || {}) as Record<string, unknown>;
  return values(e => {
    const x = v[e.key];
    if (e.kind === 'toggle') return typeof x === 'boolean' ? x : fallback[e.key];
    return optionsFor(e, look).some(o => o.value === x) ? x as EffectValue : fallback[e.key];
  });
}
