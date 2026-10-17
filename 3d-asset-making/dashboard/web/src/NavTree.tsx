// The rail's collections as a small folder tree (owner 2026-10-15: "tabs in tabs … slight folder structure").
// A source with `folder: "A/B"` (config/sources.json) sits in folder A › B under its `navLabel`; sources without a
// folder stay at the top. A folder's name selects every source inside it ("folder:A/B"); its caret opens and closes it.
// Open folders are remembered per browser; the folders holding the current selection always open.
import { useEffect, useState } from 'react';
import type { Source } from './types.ts';

type Folder = { path: string; name: string; emoji: string; count: number; folders: Folder[]; sources: Source[] };

export const FOLDER = 'folder:';
export const inFolder = (s: Source, path: string) => !!s.folder && (s.folder === path || s.folder.startsWith(path + '/'));

function tree(sources: Source[]): Folder {
  const root: Folder = { path: '', name: '', emoji: '', count: 0, folders: [], sources: [] };
  for (const s of sources) {
    let f = root;
    for (const name of (s.folder || '').split('/').filter(Boolean)) {
      const path = f.path ? f.path + '/' + name : name;
      let g = f.folders.find(x => x.path === path);
      if (!g) { g = { path, name, emoji: s.emoji, count: 0, folders: [], sources: [] }; f.folders.push(g); }
      g.count += s.count; f = g;
    }
    f.sources.push(s);
  }
  return root;
}

const load = (): string[] => { try { return JSON.parse(localStorage.getItem('bd.openFolders') || '[]'); } catch { return []; } };

export default function NavTree({ sources, cur, pick, hostName }: { sources: Source[]; cur: string; pick: (id: string) => void; hostName: (s: Source) => string }) {
  const [open, setOpen] = useState<string[]>(load);
  // the folders above the current selection open by themselves (a ?c= link, or a pick from the grid)
  const sel = cur.startsWith(FOLDER) ? cur.slice(FOLDER.length) : sources.find(s => s.id === cur)?.folder || '';
  useEffect(() => {
    const need = sel.split('/').filter(Boolean).map((_, i, a) => a.slice(0, i + 1).join('/')).filter(p => !open.includes(p));
    if (need.length) setOpen(o => [...o, ...need]);
  }, [sel]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { try { localStorage.setItem('bd.openFolders', JSON.stringify(open)); } catch { /* private mode */ } }, [open]);
  const toggle = (p: string) => setOpen(o => o.includes(p) ? o.filter(x => x !== p) : [...o, p]);

  const leaf = (s: Source, depth: number) => (
    <button key={s.id} className={cur === s.id ? 'collection on' : 'collection'} style={{ '--depth': depth } as React.CSSProperties}
      onClick={() => pick(s.id)} aria-pressed={cur === s.id} title={s.err || `${s.label} · ${hostName(s)}`}>
      <span>{depth ? '' : s.emoji}</span><span>{depth ? s.navLabel || s.label : s.label}{!depth && <small>{hostName(s)}</small>}</span><b>{s.count}</b>
    </button>);
  const folder = (f: Folder, depth: number): React.ReactNode => {
    const isOpen = open.includes(f.path), id = FOLDER + f.path;
    return (
      <div key={f.path} className="nav-folder" role="group" aria-label={f.name}>
        <div className={cur === id ? 'collection folder on' : 'collection folder'} style={{ '--depth': depth } as React.CSSProperties}>
          <button className="folder-caret" aria-expanded={isOpen} aria-label={(isOpen ? 'Close ' : 'Open ') + f.name} onClick={() => toggle(f.path)}>{isOpen ? '▾' : '▸'}</button>
          <button className="folder-name" onClick={() => { pick(id); if (!isOpen) toggle(f.path); }} aria-pressed={cur === id} title={`Everything in ${f.path.replace(/\//g, ' › ')}`}>
            <span>{depth ? '' : f.emoji}</span><span>{f.name}</span><b>{f.count}</b>
          </button>
        </div>
        {isOpen && <>{f.folders.map(g => folder(g, depth + 1))}{f.sources.map(s => leaf(s, depth + 1))}</>}
      </div>);
  };
  const t = tree(sources);
  return <>{t.folders.map(f => folder(f, 0))}{t.sources.map(s => leaf(s, 0))}</>;
}

export const folderTitle = (cur: string) => cur.startsWith(FOLDER) ? cur.slice(FOLDER.length).replace(/\//g, ' › ') : '';
