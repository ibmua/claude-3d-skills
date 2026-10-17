import type { MadeWith } from './types.ts';

// The whole library shares these immutable formatters; constructing one per card
// accounted for ~48 ms of a 4.4k-card render in the live Chrome probe.
const currencyOptions = { style: 'currency', currency: 'USD', minimumFractionDigits: 2 } as const;
const usd = new Intl.NumberFormat('en-US', { ...currencyOptions, maximumFractionDigits: 2 });
const tinyUsd = new Intl.NumberFormat('en-US', { ...currencyOptions, maximumFractionDigits: 4 });
const credits = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });

// Provider marks: Simple Icons (CC0), OpenAI v11.15.0 and Anthropic.
// This shared mapping also recognizes historical label-only provenance.
const providers = [
  { id: 'openai', label: 'OpenAI', model: /^(?:gpt|chatgpt|codex|o[1-9]|sol|luna|astra|terra)(?:[-\s]|$)/i,
    path: 'M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464zM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.872zm16.5963 3.8558L13.1038 8.364 15.1192 7.2a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654l2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z' },
  { id: 'anthropic', label: 'Anthropic', model: /^(?:claude|opus|sonnet|haiku|fable)(?:[-\s]|$)/i,
    path: 'M17.3041 3.541h-3.6718l6.696 16.918H24Zm-10.6082 0L0 20.459h3.7442l1.3693-3.5527h7.0052l1.3693 3.5528h3.7442L10.5363 3.5409Zm-.3712 10.2232 2.2914-5.9456 2.2914 5.9456Z' },
];

// Time to build (owner 2026-10-12 23:04): the record's active minutes (or wall span when only start/end are recorded);
// nothing recorded shows nothing. Server: groups.mjs timeOf.
export const dur = (min: number) => (min < 60 ? `${Math.round(min)} m` : `${Math.floor(min / 60)} h ${String(Math.round(min % 60)).padStart(2, '0')} m`);
function buildTime(m: MadeWith) {
  const t = m.time; if (!t || (t.active_min == null && t.wall_min == null)) return null;
  const txt = t.active_min != null ? `⏱ ${dur(t.active_min)} active` : `⏱ ${dur(t.wall_min!)} wall`;
  return <span className="build-time" title={`Time to build${t.first ? ` · ${t.first} → ${t.last}` : ''}${t.active_min != null && t.wall_min != null ? ` · wall ${dur(t.wall_min)}` : ''}${m.group ? ' · shared by the whole group' : ''}`}>{txt}</span>;
}
// Shared work: the whole group (one session / task / cost group) opens at #/group/<key>. The badge sits inside a card
// link, so this is a span with link behaviour rather than a nested <a>.
function groupLink(m: MadeWith) {
  const g = m.group; if (!g) return null;
  const go = (e: { preventDefault: () => void; stopPropagation: () => void }) => { e.preventDefault(); e.stopPropagation(); location.hash = '#/group/' + encodeURIComponent(g.key); };
  return <span className="group-link" role="link" tabIndex={0} title={`Made in ${g.kind === 'session' ? 'session' : 'task'} ${g.label}: show every asset made there, with its API cost and time`} onClick={go} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') go(e); }}>👥 {g.label}</span>;
}

// One badge for the grid, inventory and asset details.
export function MadeWithBadge({ m, long }: { m?: MadeWith | null; long?: boolean }) {
  if (!m) return null;
  const unknown = m.label === 'unknown';
  const identity = (m.model || m.label).split('/').pop() || '';
  const provider = providers.find(p => p.model.test(identity));
  const c = m.api_cost;
  const valid = c && typeof c.usd === 'number' && Number.isFinite(c.usd) && c.usd >= 0;
  const amount = valid ? (c.usd! > 0 && c.usd! < 0.01 ? tinyUsd : usd).format(c.usd!) : '';
  const creditValid = c && typeof c.credits === 'number' && Number.isFinite(c.credits) && c.credits >= 0;
  const pending = c?.status === 'pending' || m.generation?.cost_status === 'pending';
  const shared = c?.scope === 'asset_group';
  const price = valid ? `${c.basis === 'paid' ? 'Paid' : 'API ≈'} ${amount}${c.scope === 'shared_session' ? ' · shared session' : shared ? ' · shared work' : ''}${pending ? ' · so far' : ''}${c.partial ? ' + unpriced part' : ''}` : creditValid ? `API ≈ ${credits.format(c.credits!)} credits · ${c.scope === 'shared_session' ? 'shared session' : 'shared family'}${pending ? ' · so far' : ''}` : pending ? 'API cost pending' : 'API cost unknown';
  const explanation = valid ? `${c.basis === 'paid' ? 'Recorded amount paid' : 'Estimated API-equivalent cost, not an invoice'}${c.scope === 'shared_session' ? '; recorded generation session includes multiple assets, not a per-asset charge' : shared ? `; shared work for ${(c.assets || []).join(', ') || 'multiple assets'}${c.shared_call_ids?.length ? '; one native response crosses work boundaries' : ''}` : c.scope_id ? '; measured native usage between this asset’s work boundaries' : '; attributed to this asset'}${pending ? '; updates when final usage arrives' : ''}${c.session_id ? `; session ${c.session_id}` : ''}${c.partial ? `; priced part only, leaves out: ${c.leaves_out || 'an unpriced maker'}` : ''}` : creditValid ? `Measured family-wide API-equivalent credits; shared by all family members and LODs, not a per-model charge; USD conversion unverified; snapshot ${c.at || ''}; source ${c.via || ''}` : pending ? 'Work boundary recorded; waiting for native usage, then final pricing' : 'No attributable generation price recorded; missing cost does not mean $0';
  const tip = [unknown ? 'No record of the model and effort' : [provider?.label, m.model, m.effort, m.via, m.at].filter(Boolean).join(' · '), explanation].join(' · ');
  return <span className={`made-with${unknown ? ' unknown' : ''}`} title={tip}><span className="model-name">{provider ? <svg className="provider-icon" data-provider={provider.id} viewBox="0 0 24 24" role="img" aria-label={provider.label}><title>{provider.label}</title><path d={provider.path} /></svg> : <span aria-hidden="true">⚙</span>}<span>{long ? 'Made with ' : ''}{unknown ? 'model unknown' : m.label}</span></span><span className="generation-price">{price}</span>{buildTime(m)}{groupLink(m)}</span>;
}
