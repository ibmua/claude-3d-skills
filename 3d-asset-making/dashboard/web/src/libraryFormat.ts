// Shared library/viewer display formatting; this module never imports UI or 3D.
const KYIV = new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short' });
export const kyiv = (t: number) => KYIV.format(new Date(t)) + ' Kyiv';
export function ago(t: number) {
  const s = (Date.now() - t) / 1000;
  if (s < 90) return 'just now';
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}
export const mb = (b: number | null) => (b == null ? '' : b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1e3))} kB`);
