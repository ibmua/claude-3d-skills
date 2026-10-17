import { tierValues, validValues, viewerDefaults, type EffectKey, type EffectValue, type EffectValues } from './pictureEffects.ts';
export type Lighting = { environment: number; key: number; angle: number; exposure: number; warmth: number; elevation?: number; color?: string; environmentPreset?: string; shadows?: boolean };
export const LIGHTING_PRESETS: { id: string; label: string; values: Lighting }[] = [
  { id: 'studio', label: 'Studio', values: { environment: 1, key: 1.2, angle: 37, exposure: 1, warmth: 0 } },
  { id: 'soft', label: 'Soft', values: { environment: 1.4, key: 0.3, angle: 37, exposure: 1, warmth: 0 } },
  { id: 'dramatic', label: 'Dramatic', values: { environment: 0.3, key: 3, angle: -55, exposure: 1, warmth: 0 } },
  { id: 'warm', label: 'Warm', values: { environment: 0.7, key: 2, angle: 65, exposure: 1.1, warmth: 1 } },
];
export const BACKGROUNDS = [
  { label: 'Graphite', color: '#1d1f23' }, { label: 'Slate', color: '#64717e' },
  { label: 'Paper', color: '#e6e3db' }, { label: 'Black', color: '#090a0d' },
];
export const DEFAULT_LIGHTING = LIGHTING_PRESETS[0].values;
export const ENVIRONMENTS = [{ id: 'studio', label: 'Studio room' }, { id: 'overcast', label: 'Overcast sky' }, { id: 'sunset', label: 'Sunset sky' }];
export const CAMERA_PRESETS = [{ id: 'three-quarter', label: '¾' }, { id: 'front', label: 'Front' }, { id: 'rear', label: 'Rear' }, { id: 'left', label: 'Left' }, { id: 'right', label: 'Right' }, { id: 'top', label: 'Top' }] as const;
export type CameraPreset = typeof CAMERA_PRESETS[number]['id'];
export const INSPECTION_MODES = [{ id: 'textured', label: 'Materials' }, { id: 'clay', label: 'Clay' }, { id: 'normals', label: 'Normals' }, { id: 'roughness', label: 'Roughness' }, { id: 'uv', label: 'UV checker' }, { id: 'depth', label: 'Depth' }] as const;
export type InspectionMode = typeof INSPECTION_MODES[number]['id'];
// Look = what lights and tone-maps the model. 'viewer' is the beautified inspection look; 'game' is what the game renders
// (gameLook.ts mirrors its Environment.js) with the game's own effect switches (tiers of config/picture-effects.json).
export const LOOKS = [{ id: 'viewer', label: 'Viewer' }, { id: 'game', label: 'Game' }] as const;
export type Look = typeof LOOKS[number]['id'];
// Effects come from the shared list config/picture-effects.json (pictureEffects.ts). `effects` = the viewer look's values
// (its sun shadow and resolution are lighting.shadows and quality, so those controls stay one state); `game` = the game look's.
export function activeEffects(s: ViewSettings): EffectValues {
  return s.look === 'game' ? s.game : { ...s.effects, sunShadow: s.lighting.shadows ? 1024 : 0, resolution: s.quality };
}
export function withEffect(s: ViewSettings, key: EffectKey, value: EffectValue): ViewSettings {
  if (s.look === 'game') return { ...s, game: { ...s.game, [key]: value } };
  if (key === 'sunShadow') return { ...s, lighting: { ...s.lighting, shadows: Number(value) > 0 } };
  if (key === 'resolution') return { ...s, quality: Number(value) };
  return { ...s, effects: { ...s.effects, [key]: value } };
}
export type CameraState = { position: number[]; target: number[]; up: number[]; projection: 'perspective' | 'orthographic'; scale: number };
export type ViewSettings = { quality: number; adaptive: boolean; lighting: Lighting; background: string; grid: boolean; wire: boolean; mode: InspectionMode; explode: number; orthographic: boolean; look: Look; effects: EffectValues; game: EffectValues };
export type SavedView = { camera?: CameraState; settings?: ViewSettings; variant?: string; selected?: string; isolated?: string; hidden?: string[]; morphs?: Record<string, number> };
export const DEFAULT_SETTINGS: ViewSettings = { quality: viewerDefaults().resolution, adaptive: false, lighting: { ...DEFAULT_LIGHTING }, background: BACKGROUNDS[0].color, grid: true, wire: false, mode: 'textured', explode: 0, orthographic: false, look: 'viewer', effects: viewerDefaults(), game: tierValues('standard') };
const bounded = (value: unknown, lo: number, hi: number, fallback: number) => typeof value === 'number' && Number.isFinite(value) ? Math.max(lo, Math.min(hi, value)) : fallback;
const color = (v: unknown, fallback: string) => typeof v === 'string' && /^#[\da-f]{6}$/i.test(v) ? v : fallback;
export function validSettings(value: unknown): ViewSettings {
  const s = (value || {}) as Partial<ViewSettings>, l = (s.lighting || {}) as Lighting;
  return { quality: [1, 1.5, 2].includes(s.quality!) ? s.quality! : 1.5, adaptive: s.adaptive === true,
    lighting: { environment: bounded(l.environment, 0, 3, 1), key: bounded(l.key, 0, 5, 1.2), angle: bounded(l.angle, -180, 180, 37), exposure: bounded(l.exposure, .2, 3, 1), warmth: l.warmth === 1 ? 1 : 0, elevation: bounded(l.elevation, 5, 85, 45), color: color(l.color, l.warmth ? '#ffd2a0' : '#ffffff'), environmentPreset: ENVIRONMENTS.some(e => e.id === l.environmentPreset) ? l.environmentPreset : 'studio', shadows: l.shadows === true },
    background: color(s.background, BACKGROUNDS[0].color), grid: s.grid !== false, wire: s.wire === true, mode: INSPECTION_MODES.some(m => m.id === s.mode) ? s.mode! : 'textured', explode: bounded(s.explode, 0, 1, 0), orthographic: s.orthographic === true,
    look: s.look === 'game' ? 'game' : 'viewer', effects: validValues(s.effects, viewerDefaults(), 'viewer'), game: validValues(s.game, tierValues('standard'), 'game') };
}
export function validView(value: unknown): SavedView {
  const v = (value || {}) as SavedView, out: SavedView = {};
  const vector = (n: unknown) => Array.isArray(n) && n.length === 3 && n.every(x => typeof x === 'number' && Number.isFinite(x) && Math.abs(x) < 1e8);
  if (v.camera && vector(v.camera.position) && vector(v.camera.target) && vector(v.camera.up)) out.camera = { position: v.camera.position, target: v.camera.target, up: v.camera.up, projection: v.camera.projection === 'orthographic' ? 'orthographic' : 'perspective', scale: bounded(v.camera.scale, 1e-6, 1e8, 1) };
  if (v.settings) out.settings = validSettings(v.settings);
  for (const k of ['variant', 'selected', 'isolated'] as const) if (typeof v[k] === 'string' && v[k]!.length < 1000) out[k] = v[k];
  if (Array.isArray(v.hidden)) out.hidden = v.hidden.filter(x => typeof x === 'string' && x.length < 1000).slice(0, 1000);
  if (v.morphs && typeof v.morphs === 'object') out.morphs = Object.fromEntries(Object.entries(v.morphs).filter(([k, n]) => k.length < 200 && typeof n === 'number' && Number.isFinite(n)).slice(0, 100).map(([k,n]) => [k, bounded(n, 0, 1, 0)]));
  return out;
}
export function readLocal<T>(key: string, fallback: T): T { try { return JSON.parse(localStorage.getItem(key) || 'null') || fallback; } catch { return fallback; } }
export function saveLocal(key: string, value: unknown) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* A full/private store must not break viewing. */ } }
export const PREFS_KEY = 'bd.viewer.preferences.v1';
export const assetViewKey = (id: string) => `bd.viewer.asset.v1:${id}`;
export const bookmarksKey = (id: string) => `bd.viewer.bookmarks.v1:${id}`;
