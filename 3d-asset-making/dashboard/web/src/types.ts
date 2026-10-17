export type Job = { kind: 'render' | 'export'; state: 'queued' | 'running' | 'error'; err: string | null };
export type Item = {
  id: string; source: string; group: string; key: string; host: 'pc' | 'tr';
  glb: string | null; glbBytes: number | null; blend: string | null; blendBytes: number | null;
  path: string; assetMtime: number;
  preview: { url: string; mtime: number; bytes?: number; origin: 'pipeline' | 'dash'; fresh: boolean } | null;
  extras: string[]; meta: Record<string, unknown> | null; job: Job[]; made_with?: MadeWith | null;
  integrity?: IntegrityBadge | null;   // cached geometry check (server integrity.mjs); null = not checked yet
};
// Geometry check (mesh_integrity.py, README "Geometry check"): sound = exit 0, fault = RESULT FAULT, look = a pointer, unreadable = exit 2
export type IntegrityStatus = 'sound' | 'fault' | 'look' | 'unreadable';
export type IntegrityBadge = { status: IntegrityStatus; short: string; verdict: string; at: number; ms: number; against: string | null };
export type IntegrityPlace = { label: string; at: number[]; min?: number[]; max?: number[]; size?: number };
export type IntegritySection = { kind: string; text: string; details: string[]; places: IntegrityPlace[] };
export type IntegrityResult = { status: IntegrityStatus; short: string; verdict: string; header: string; sections: IntegritySection[]; text: string; at: number; ms: number; exit: number;
  doubleSided: number | null; counts: { back_to_back_pairs?: number; back_to_back_m2?: number } | null;
  against: { glb: string; level: string; key: string; id: string | null } | null; againstNote: string | null };
export type IntegrityResponse = { state: 'done' | 'queued' | 'running' | 'error' | 'needs-export' | 'missing'; result?: IntegrityResult | null; err?: string;
  reference?: { level: string; key: string; id: string | null; exported: boolean } | null };
export type Source = { id: string; label: string; emoji: string; host: string; project: string; count: number; err?: string;
  folder?: string; navLabel?: string };   // folder "A/B": the rail nests it; navLabel: its short name there (config/sources.json)
export type Catalog = {
  generated: number; scanMs: number; sources: Source[]; items: Item[];
  refreshing?: boolean; // saved library is usable while a request-triggered scan runs
  queue: Record<string, { running: number; queued: number }>;
  todo?: TodoSummary[]; groups?: Record<string, GroupSummary>;
};

// To be done: generated inventories (config `todo`; music videos: a film pipeline's asset_todo.py)
export type TodoCounts = { todo: number; flagged: number; built: number };
export type TodoSummary = {
  id: string; source: string; group: string; label: string; emoji: string; host: string; project?: string; title?: string;
  generated?: string; mtime?: number; cutShots?: number; cutS?: number; groups?: Record<string, string>;
  counts?: Record<string, TodoCounts>; totals?: TodoCounts; unclassified?: number; brokenRules?: number; err?: string;
};
// which model + effort setting made an asset (owner 2026-10-01; a film pipeline), from its audit
export type MadeWith = { time?: { active_min: number | null; wall_min: number | null; first: string | null; last: string | null } | null; group?: { key: string; label: string; kind: 'cost_group' | 'task' | 'session'; task: string | null } | null; record?: string; label: string; model?: string | null; effort?: string | null; via?: string; at?: string; api_cost?: { usd?: number; credits?: number; at?: string; basis: "api_equivalent" | "paid"; scope: "asset" | "asset_group" | "shared_session"; status?: "pending" | "complete"; scope_id?: string; assets?: string[]; shared_call_ids?: string[]; via?: string; session_id?: string; partial?: boolean; leaves_out?: string }; generation?: { scope_id?: string; cost_status?: string; assets?: string[] } };
export type TodoRef = { label: string; crop: number[] | null; url: string | null; full: string | null };
export type TodoAudit = {
  score?: number | null; verdict?: string | null; redo?: string | null; why?: string | null; after?: string | null;
  open?: string[]; residual?: string[]; closed?: { note: string; why: string }[]; made_with?: MadeWith | null;
  wip?: { state?: string; score?: number; blend?: string; compare?: string | string[]; why?: string } | null;
};
export type TodoItem = {
  id: string; name: string; kind: string; group: string; source: string; status: 'todo' | 'flagged' | 'built';
  shots: string[]; members: Record<string, string[]>; screen_s: number; flags: string[]; refs: TodoRef[]; refs_missing?: string;
  now?: string | null; note?: string | null; by?: string | null; asset?: string | null; who?: string; loc?: string; setup?: string;
  wip?: { state?: string; builds?: number; latest?: string; latest_at?: string; src?: string } | null;
  audit?: TodoAudit | null; parts?: Record<string, string[]>; covers?: Record<string, string[]>;
  now_url?: string | null; wip_url?: string | null; made_with?: MadeWith | null;
};
export type TodoDoc = {
  id: string; file: string; title: string; generated: string; cut_shots: number; cut_s: number;
  groups: Record<string, string>; counts: Record<string, TodoCounts>; totals: TodoCounts; items: TodoItem[];
  excluded: { why: string; objects: Record<string, string[]> }[]; unclassified: { kind: string; objects: Record<string, string[]> }[];
  broken_rules: { rule: string; why: string }[]; unused_prod: string[];
};
// group sessions (server groups.mjs buildGroups, once per scan): every asset made in one task / session / cost group
export type GroupMaker = { label: string; model: string | null; effort: string | null; usd: number | null; images: number | null; active_min: number | null; calls: number | null };
export type GroupSummary = { key: string; label: string; kind: string; task: string | null; count: number; records: number; usd: number | null; credits: number | null; partial: boolean; basis: string;
  time: { active_min: number | null; first: string | null; last: string | null } | null; makers: GroupMaker[]; run: string | null };
