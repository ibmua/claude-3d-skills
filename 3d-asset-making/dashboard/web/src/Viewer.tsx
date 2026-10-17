import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Item } from './types.ts';
import { ago, kyiv, mb } from './libraryFormat.ts';
import { MadeWithBadge } from './MadeWith.tsx';
import PhotoGallery, { assetPhotos, PhotoStrip } from './PhotoGallery.tsx';
import type { AssetStats, ViewPerf } from './viewerMetrics.ts';
import { assetHref, readAssetRoute } from './assetLinks.ts';
import PartBrowser from './PartBrowser.tsx';
import type { ModelPart } from './modelParts.ts';
import { BACKGROUNDS, DEFAULT_LIGHTING, LIGHTING_PRESETS, CAMERA_PRESETS, ENVIRONMENTS, INSPECTION_MODES, LOOKS, activeEffects, withEffect, DEFAULT_SETTINGS, PREFS_KEY, assetViewKey, bookmarksKey, readLocal, saveLocal, validSettings, validView, type CameraState, type Lighting, type SavedView, type ViewSettings } from './viewerSettings.ts';
import { ViewerEngine, type PartInfo } from './viewerEngine.ts';
import { assetVariants } from './assetVariants.ts';
import MaterialBrowser from './MaterialBrowser.tsx';
import type { MaterialRow } from './materialInspection.ts';
import FrameGraph from './FrameGraph.tsx';
import GeometryCheck from './GeometryCheck.tsx';
import { GAME_LOOK } from './gameLook.ts';
import { REFINE_FRAMES } from './viewerEffects.ts';
import type { LiveInfo } from './livePrograms.ts';
import { EFFECTS_SOURCE as EFFECTS_FILE, PICTURE_EFFECTS, TIERS, optionsFor, tierValues } from './pictureEffects.ts';

export type GlbCheck = { id?:string; glb?:string; ok:boolean; err?:string; tris?:number; meshes?:number; textures?:number; frame?:boolean; live?:{on:boolean;kinds:string[];kindMeshes:number;programs:string[]}|null; clip?:{near:number;far:number} };
declare global { interface Window { __glbCheck?:GlbCheck } }
const count=(n:number)=>n.toLocaleString();
const memorySize=(n:number)=>n===0?'0 B':mb(n);
type Bookmark={name:string;view:SavedView};

export default function Viewer({item,items,collection,onClose}:{item:Item;items:Item[];collection?:string;onClose:()=>void}) {
  const photos=useMemo(()=>assetPhotos(item),[item.preview?.url,item.preview?.mtime,item.extras.join('|'),item.assetMtime]);
  const initialRoute=useMemo(()=>readAssetRoute(),[item.id]);
  const initial=useMemo(()=>{
    const saved=validView(initialRoute?.state||readLocal(assetViewKey(item.id),{}));
    if(initialRoute?.part){saved.isolated=initialRoute.part;saved.selected=initialRoute.part;delete saved.camera;delete saved.hidden;delete saved.variant;}
    return saved;
  },[item.id]);
  const variants=useMemo(()=>assetVariants(item,items),[item,items]);
  const [variant,setVariant]=useState(variants.some(v=>v.item.id===initial.variant)?initial.variant!:item.id);
  const activeItem=variants.find(v=>v.item.id===variant)?.item||item;
  const [displayedId,setDisplayedId]=useState(activeItem.id);
  const displayedItem=variants.find(v=>v.item.id===displayedId)?.item||item;
  const [settings,setSettings]=useState<ViewSettings>(()=>validSettings(initial.settings||readLocal(PREFS_KEY,DEFAULT_SETTINGS)));
  const {lighting,background,wire,grid}=settings;
  const patch=(values:Partial<ViewSettings>)=>setSettings(s=>({...s,...values}));
  const setLighting=(update:Lighting|((l:Lighting)=>Lighting))=>setSettings(s=>({...s,lighting:typeof update==='function'?update(s.lighting):update}));
  const setBackground=(color:string)=>patch({background:color});
  const [view,setView]=useState<'model'|'photos'>(initialRoute?.part?'model':initialRoute?.view==='photos'&&photos.length?'photos':initialRoute?.view==='model'?'model':!activeItem.glb&&photos.length?'photos':'model');
  const [requested,setRequested]=useState(!(initialRoute?.view==='photos'&&photos.length&&!initialRoute?.part)&&(!!activeItem.glb||!photos.length||!!initialRoute?.part||initialRoute?.view==='model'));
  const [photoIndex,setPhotoIndex]=useState(()=>Math.max(0,photos.findIndex(p=>new URL(p.url,location.href).pathname===initialRoute?.photo)));
  const [fullscreen,setFullscreen]=useState(false),[info,setInfo]=useState(true);
  const [selectedPart,setSelectedPart]=useState<string|null>(initial.isolated||null),[picked,setPicked]=useState<PartInfo|null>(null),[partNotice,setPartNotice]=useState('');
  const [glb,setGlb]=useState<string|null>(activeItem.glb),[glbBytes,setGlbBytes]=useState<number|null>(activeItem.glbBytes);
  const [loadedGlb,setLoadedGlb]=useState(activeItem.glb);
  const [loadAttempt,setLoadAttempt]=useState(0);
  const [phase,setPhase]=useState(activeItem.glb?'Loading model…':'Open 3D to inspect the model');
  const loadError=/could not|failed|no visible/i.test(phase);
  const loading=requested&&phase!=='ready'&&!loadError;
  const [live,setLive]=useState<LiveInfo|null>(null);
  const [stats,setStats]=useState<AssetStats|null>(null),[perf,setPerf]=useState<ViewPerf|null>(null),[loadMs,setLoadMs]=useState<number|null>(null);
  const [nodes,setNodes]=useState<ModelPart[]>([]),[materials,setMaterials]=useState<MaterialRow[]>([]);
  const [morphs,setMorphs]=useState<{name:string;value:number}[]>([]),[clips,setClips]=useState<string[]>([]),[playing,setPlaying]=useState<string|null>(null);
  const [measured,setMeasured]=useState<Record<string,{tris:number;meshes:number;calls?:number}>>({});
  const [camera,setCamera]=useState<CameraState|undefined>(initial.camera),[bookmarkName,setBookmarkName]=useState(''),[bookmarks,setBookmarks]=useState<Bookmark[]>(()=>{
    const stored=readLocal<unknown>(bookmarksKey(item.id),[]);return Array.isArray(stored)?stored.filter(b=>typeof b?.name==='string').slice(0,12).map(b=>({name:b.name.slice(0,80),view:validView(b.view)})):[];
  });
  const [shareNotice,setShareNotice]=useState(''),[shareFallback,setShareFallback]=useState(''),[rerender,setRerender]=useState('');
  const host=useRef<HTMLDivElement>(null),dialog=useRef<HTMLDivElement>(null),api=useRef<ViewerEngine|null>(null);
  const pendingView=useRef<SavedView|null>(null),restoreRef=useRef<(saved:SavedView)=>void>(()=>{});
  const loadedId=useRef(''),settingsRef=useRef(settings);settingsRef.current=settings;
  const closeRef=useRef(onClose);closeRef.current=onClose;
  const modeRef=useRef({view,fullscreen});modeRef.current={view,fullscreen};
  const [pageVisible,setPageVisible]=useState(!document.hidden);
  const capturePart=useCallback(async(id:string)=>api.current?.picture(id)??null,[]);
  const captureTexture=useCallback((material:string,texture:string,full=false)=>api.current?.inspector?.texturePicture(material,texture,full)??null,[]);
  const snapshot=():SavedView=>({...validView(api.current?.model?api.current.state():{...initial,camera,settings}),settings,variant:api.current?.model?(loadedId.current||displayedId):variant,morphs:morphs.length?Object.fromEntries(morphs.map(m=>[m.name,m.value])):initial.morphs||{}});
  const snapshotRef=useRef(snapshot);snapshotRef.current=snapshot;
  useEffect(()=>{const visibility=()=>setPageVisible(!document.hidden);document.addEventListener('visibilitychange',visibility);return()=>document.removeEventListener('visibilitychange',visibility);},[]);
  useEffect(()=>{
    saveLocal(PREFS_KEY,settings);
    // Persist only the loaded version, never stamp a pending replacement onto old geometry.
    const timer=setTimeout(()=>{if(!requested||loadedId.current===variant)saveLocal(assetViewKey(item.id),snapshotRef.current());},180);
    return()=>clearTimeout(timer);
  },[settings,camera,nodes,picked,variant,morphs,requested,item.id]);
  useEffect(()=>{saveLocal(bookmarksKey(item.id),bookmarks);},[bookmarks,item.id]);
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null,overflow=document.body.style.overflow;document.body.style.overflow='hidden';dialog.current?.querySelector<HTMLButtonElement>('.viewer-close')?.focus();
    const key=(e:KeyboardEvent)=>{
      if(e.key==='Escape'){e.preventDefault();if(modeRef.current.fullscreen)setFullscreen(false);else closeRef.current();}
      if(e.key.toLowerCase()==='f'&&!e.ctrlKey&&!e.metaKey&&modeRef.current.view==='model'&&!(e.target as HTMLElement).matches('input,textarea,select'))api.current?.frame();
      if(e.key==='Tab'){
        const scope=modeRef.current.fullscreen?dialog.current?.querySelector('.immersive'):dialog.current;
        const buttons=[...(scope?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input,select,summary,[tabindex="0"]')||[])].filter(el=>el.checkVisibility()&&!el.closest('[inert]'));
        const first=buttons[0],last=buttons.at(-1);if(e.shiftKey&&(document.activeElement===first||!scope?.contains(document.activeElement))){e.preventDefault();last?.focus();}else if(!e.shiftKey&&(document.activeElement===last||!scope?.contains(document.activeElement))){e.preventDefault();first?.focus();}
      }
    };window.addEventListener('keydown',key);return()=>{window.removeEventListener('keydown',key);document.body.style.overflow=overflow;if(previous?.isConnected)previous.focus();};
  },[]);
  useEffect(()=>{if(!fullscreen)return;const previous=document.activeElement as HTMLElement|null;dialog.current?.querySelector<HTMLButtonElement>('[aria-label="Close full screen"]')?.focus();return()=>{if(previous?.isConnected&&previous.checkVisibility())previous.focus();else dialog.current?.querySelector<HTMLButtonElement>('[aria-label="Full screen"]')?.focus();};},[fullscreen]);
  useEffect(()=>{if(photoIndex>=photos.length)setPhotoIndex(0);},[photoIndex,photos.length]);
  useEffect(()=>{
    setGlb(activeItem.glb);setGlbBytes(activeItem.glbBytes);
    if(!requested)return;if(activeItem.glb)return;
    let stop=false,timer=0;const controller=new AbortController();
    const poll=async()=>{try{const response=await fetch(`api/port?id=${encodeURIComponent(activeItem.id)}`,{method:'POST',signal:controller.signal});if(!response.ok)throw new Error(`Export request failed (${response.status})`);const r=await response.json();if(stop)return;if(r.glb){setGlb(r.glb);return;}if(r.state==='error'||r.error){setPhase(`Export failed: ${r.err||r.error}`);return;}setPhase(r.state==='running'?`Preparing 3D on ${activeItem.host==='tr'?'the build box':'this PC'}…`:'Queued for 3D export…');}catch(e){if(stop)return;setPhase(`${String((e as Error).message)}. Retrying…`);}timer=window.setTimeout(poll,2500);};poll();return()=>{stop=true;clearTimeout(timer);controller.abort();};
  },[requested,activeItem.id,activeItem.glb,activeItem.host,activeItem.glbBytes,loadAttempt]);
  useEffect(()=>{
    if(!requested||!host.current)return;let engine:ViewerEngine;
    try{engine=new ViewerEngine(host.current,settingsRef.current,initial,{
      phase:setPhase,notice:setPartNotice,picked:setPicked,camera:setCamera,live:setLive,
      parts:(parts,statistics,isolated)=>{setNodes(parts);setStats(statistics);setSelectedPart(isolated);},
      loaded:data=>{loadedId.current=data.id;setDisplayedId(data.id);setLoadedGlb(data.url);setStats(data.stats);setLoadMs(data.loadMs);setMaterials(data.materials);setMorphs(data.morphs.map(name=>{let value=0;api.current?.model?.traverse(o=>{const m=o as unknown as {morphTargetDictionary?:Record<string,number>;morphTargetInfluences?:number[]};const i=m.morphTargetDictionary?.[name];if(i!=null)value=m.morphTargetInfluences?.[i]||0;});return {name,value};}));setClips(data.clips);setPlaying(null);if(data.bytes)setGlbBytes(data.bytes);setMeasured(old=>({...old,[data.id]:{tris:data.stats.tris,meshes:data.stats.meshes}}));if(pendingView.current){const pending=pendingView.current;pendingView.current=null;restoreRef.current(pending);}},
      perf:data=>{setPerf(data);if(loadedId.current)setMeasured(old=>{const current=old[loadedId.current];return current&&current.calls!==data.calls?{...old,[loadedId.current]:{...current,calls:data.calls}}:old;});}
    });api.current=engine;engine.setActive(modeRef.current.view==='model'&&!modeRef.current.fullscreen&&!document.hidden);}
    catch{setPhase('3D could not start. Try the renders or reload this page.');return;}
    return()=>{if(engine.model)saveLocal(assetViewKey(item.id),snapshotRef.current());engine.dispose();api.current=null;};
  },[requested]);
  useEffect(()=>{if(requested&&glb&&api.current){setPartNotice('');api.current.load(glb,activeItem.id);}},[requested,glb,activeItem.id,loadAttempt]);
  useEffect(()=>{api.current?.setActive(view==='model'&&!fullscreen&&pageVisible);},[view,fullscreen,pageVisible]);
  useEffect(()=>{api.current?.applySettings(settings);},[settings]);
  const setNode=(uuid:string,visible:boolean)=>api.current?.visible(uuid,visible);
  const selectPart=(id:string|null)=>{setPartNotice('');api.current?.isolate(id);if(id)api.current?.pick(id);else api.current?.pick(null);};
  const setMorph=(name:string,value:number)=>{api.current?.morph(name,value);setMorphs(ms=>ms.map(m=>m.name===name?{...m,value}:m));};
  const play=(name:string|null)=>{api.current?.play(name);setPlaying(name);};
  const openModel=()=>{setRequested(true);setView('model');};
  const chooseVariant=(id:string)=>{if(id===variant){openModel();if(loadError)setLoadAttempt(n=>n+1);return;}pendingView.current=null;api.current?.cancelLoad();setVariant(id);setGlb(null);setPhase('Loading version…');setRequested(true);setView('model');};
  const restoreView=(saved:SavedView)=>{const s=validView(saved);if(s.settings){setSettings(s.settings);api.current?.applySettings(s.settings);}if(s.variant&&s.variant!==variant&&variants.some(v=>v.item.id===s.variant)){chooseVariant(s.variant);pendingView.current=s;return;}if(s.isolated)api.current?.isolate(s.isolated,false);else api.current?.isolate(null,false);if(s.hidden)for(const p of api.current?.parts||[])if(s.hidden.includes(p.id))api.current?.visible(p.uuid,false);api.current?.pick(s.selected||null);if(s.camera){api.current?.restoreCamera(s.camera);setCamera(s.camera);}if(s.morphs)for(const [n,v]of Object.entries(s.morphs))setMorph(n,v);};
  restoreRef.current=restoreView;
  const saveAngle=()=>{if(!stats)return;const name=bookmarkName.trim().slice(0,80)||`Angle ${bookmarks.length+1}`;setBookmarks(b=>[...b.filter(v=>v.name!==name),{name,view:snapshot()}].slice(-12));setBookmarkName('');setShareNotice(`Saved “${name}” on this browser.`);};
  const share=async()=>{const href=assetHref(item.id,{view,photo:view==='photos'&&photos[photoIndex]?new URL(photos[photoIndex].url,location.href).pathname:undefined,state:snapshot()});try{await navigator.clipboard.writeText(new URL(href,location.href).href);setShareNotice('View link copied.');setShareFallback('');}catch{setShareFallback(new URL(href,location.href).href);setShareNotice('Copy this view link:');}};
  const queueRender=async()=>{setRerender('Requesting…');try{const response=await fetch(`api/rerender?id=${encodeURIComponent(item.id)}`,{method:'POST'});const r=await response.json();if(!response.ok||r.error)throw new Error(r.error||`Request failed (${response.status})`);setRerender(r.state==='running'?'Rendering…':'Render queued');}catch(e){setRerender(String((e as Error).message));}};
  const suspended=view==='photos'||fullscreen||!pageVisible;
  const preset=LIGHTING_PRESETS.find(p=>Object.entries(p.values).every(([key,value])=>lighting[key as keyof Lighting]===value)&&(lighting.elevation??45)===45&&(lighting.environmentPreset||'studio')==='studio'&&(!lighting.color||lighting.color===(p.values.warmth?'#ffd2a0':'#ffffff'))) ?.id||'custom';
  const pictureRevision=JSON.stringify([displayedItem.id,lighting,background,wire,settings.mode,settings.look,morphs]);
  const effectValues=activeEffects(settings),gameTier=TIERS.find(t=>JSON.stringify(tierValues(t.id))===JSON.stringify(settings.game));
  const game=settings.look==='game',stageBackground=game?'#'+GAME_LOOK.haze.toString(16).padStart(6,'0'):background;
  const currentHref=assetHref(item.id,{view,photo:view==='photos'&&photos[photoIndex]?new URL(photos[photoIndex].url,location.href).pathname:undefined,state:snapshot()});
  return <div className={`viewer asset-viewer${info ? '' : ' inspector-hidden'}`} ref={dialog} role="dialog" aria-modal="true" aria-labelledby="asset-title">
    <header className="viewer-header" inert={fullscreen || undefined}>
      <button className="viewer-close" onClick={onClose} aria-label="Back to library" title="Back to library (Esc)">←</button>
      <div className="viewer-title"><p>{collection || item.source}{item.group && ` / ${item.group}`}</p><h2 id="asset-title">{item.key.replace(/-(original|near|mid|far)$/i,'')}</h2></div>
      <div className="media-tabs" role="group" aria-label="Asset view"><button aria-pressed={view === 'model'} onClick={openModel}>⬡ <span>3D model</span></button><button aria-pressed={view === 'photos'} disabled={!photos.length} onClick={() => setView('photos')}>▧ <span>Renders</span><b>{photos.length}</b></button></div>
      <a className="asset-new-tab" href={currentHref} target="_blank" rel="noopener noreferrer" aria-label="Open asset in new tab" title="Open this view in a new tab">↗</a>
      <button className="view-share" onClick={share} aria-label="Copy view link" title="Copy camera, lighting, version and visible parts">⤴</button>
      <button className="info-toggle" aria-label="Asset information" aria-pressed={info} title="Asset information" onClick={() => setInfo(v => !v)}>ⓘ</button>
    </header>
    <div className="viewer-media">
      <div className="stage" ref={host} style={{background:stageBackground}} hidden={view !== 'model'} inert={fullscreen || undefined}>
        {phase !== 'ready' && <div className={stats ? 'phase phase-update' : 'phase'}><div><span className="phase-symbol">⬡</span><p role="status">{phase}</p>{!stats && !!photos.length && <button onClick={() => setView('photos')}>▧ View {photos.length} renders</button>}{loadError&&<button onClick={()=>setLoadAttempt(n=>n+1)}>↻ Retry</button>}</div></div>}
        <div className="hud"><button onClick={() => api.current?.frame()} title="Fit model (F)" aria-label="Fit model" disabled={!stats}>⌖</button><button aria-pressed={wire} onClick={() => patch({wire:!wire})} title="Wireframe" aria-label="Wireframe" disabled={!stats}>▦</button><button aria-pressed={grid} onClick={() => patch({grid:!grid})} title="Ground grid" aria-label="Ground grid">#</button><button aria-pressed={game} onClick={() => patch({look:game?'viewer':'game'})} title={game?'Game look: what the game renders. Click for the viewer look':'Show what the game renders (the game lighting, no effects)'} aria-label="Game look">🎮</button>{live&&<><button aria-pressed={live.on} onClick={()=>api.current?.setLive(!live.on)} title={live.on?`Live shaders: ${[...live.materials.map(m=>`program ${m}`),...live.kinds.map(k=>`library kind ${k}`)].join(', ')}. What the game runs. Click for the fallback in the GLB (what a plain glTF viewer shows)`:'Fallback in the GLB (what a plain glTF viewer shows). Click for the live shaders'} aria-label="Live surface programs" data-no-shadow={live.noShadow?.join(',')}>{live.on?'✨':'🖼'}</button>{live.on&&live.animated&&<button onClick={()=>api.current?.setLivePlaying(!live.playing)} title={live.playing?'Pause the live surfaces (rendering stops)':'Play the live surfaces (renders every frame)'} aria-label={live.playing?'Pause live surfaces':'Play live surfaces'}>{live.playing?'⏸':'▶'}</button>}</>}</div>
        {selectedPart && nodes.some(n => n.id === selectedPart) && <div className="part-focus"><span>{nodes.find(n => n.id === selectedPart)?.name.replace(/_/g, ' ')}</span><button onClick={() => selectPart(null)}>Show all</button></div>}
        <div className="stage-footer"><span>Drag to orbit <i>·</i> Scroll to zoom <i>·</i> WASD to move</span>{perf && <span className="perf-pill" title={`Frame rate while moving; rendering stops at rest${perf.post?.length?`. Draws include: ${perf.post.join(', ')}`:''}`}>{perf.refine ? `◐ Refining ${perf.refine}/${REFINE_FRAMES}` : perf.fps == null ? '● Idle' : `${Math.round(perf.fps)} fps`} <i>·</i> {perf.calls} draws{!!perf.post?.length && <> <i>·</i> ✦ {perf.post.length}</>}</span>}</div>
      </div>
      {(view === 'photos' || fullscreen) && !!photos.length && <PhotoGallery photos={photos} index={Math.min(photoIndex, photos.length - 1)} onSelect={setPhotoIndex} fullscreen={fullscreen} onFullscreen={() => setFullscreen(v => !v)} title={item.key} />}
    </div>
    <aside className="asset-inspector-shell" aria-hidden={!info || fullscreen || undefined} inert={!info || fullscreen || undefined}>
      {variants.length>1&&<div className="model-versions">
        <div className="inspector-heading"><h3>Model versions</h3><span className="version-label">{view==='model'?(variants.find(v=>v.item.id===displayedId)?.label||'current'):'3D'}</span></div>
        <div className="variant-switch" role="group" aria-label="Model versions">{variants.map(v=><button key={v.item.id} aria-pressed={activeItem.id===v.item.id} aria-busy={activeItem.id===v.item.id&&loading||undefined} title={`${v.label} · ${mb(v.item.glbBytes)||'export on demand'}`} onClick={()=>chooseVariant(v.item.id)}>{v.label}</button>)}</div>
        <p className="version-progress" role="status" title={phase==='ready'?'Camera and lighting stay fixed':phase}>{phase==='ready'?'Camera and lighting stay fixed':stats?`${phase} Showing ${variants.find(v=>v.item.id===displayedId)?.label||'current'}.`:phase}</p>
      </div>}
      <div className="asset-inspector">
      <div className="inspector-heading"><h3>Asset overview</h3><span className={`asset-status ${item.preview?.fresh ? 'fresh' : ''}`}>{item.preview?.fresh ? 'Fresh preview' : item.preview ? 'Older preview' : 'No preview'}</span></div>
      <p className="asset-updated" title={kyiv(item.assetMtime)}>{item.host === 'tr' ? '🧵 Threadripper' : '🖥 This PC'} <span>Updated {ago(item.assetMtime)}</span></p>
      {item.made_with && <div className="viewer-made"><MadeWithBadge m={item.made_with} long /></div>}
      <dl className="asset-facts"><div><dt>{item.blend ? 'Blender source' : 'GLB file'}</dt><dd>{mb(item.blend ? item.blendBytes : stats?(displayedItem.glbBytes||glbBytes):glbBytes) || 'Unknown size'}</dd></div>{item.blend && <div><dt>Web model</dt><dd>{(stats?displayedItem.glbBytes||glbBytes:glbBytes) ? mb(stats?displayedItem.glbBytes||glbBytes:glbBytes) : glb ? 'Available' : 'Export on demand'}</dd></div>}{stats && <><div><dt>Visible triangles</dt><dd>{count(stats.tris)}</dd></div><div><dt>Visible meshes</dt><dd>{count(stats.meshes)}</dd></div><div><dt>Materials / textures</dt><dd>{stats.materials} / {stats.textures}</dd></div><div><dt>Size (X × Y × Z)</dt><dd>{stats.dimensions.map(n => n.toLocaleString(undefined, {maximumFractionDigits: 2})).join(' × ')}<small>scene units</small></dd></div></>}</dl>
      <GeometryCheck id={displayedItem.id} active={requested} onMark={stats ? p => api.current?.mark(p) : undefined} />
      <div className="asset-downloads">{(stats?loadedGlb:glb) && <a href={(stats?loadedGlb:glb)!} download>↓ GLB</a>}{item.blend && item.path.endsWith('.blend') && <a href={`f${item.path.split('/').map(encodeURIComponent).join('/')}`} download>↓ Blender</a>}</div>
      {!!photos.length && <div className="inspector-renders"><div className="inspector-heading"><h3>Renders <span>{photos.length}</span></h3><button aria-label="Browse renders full screen" title="Browse renders full screen" onClick={() => setFullscreen(true)}>⛶</button></div><PhotoStrip photos={photos} index={photoIndex} onSelect={i => { setPhotoIndex(i); setView('photos'); }} /></div>}
      <details className="camera-details"><summary>Camera &amp; saved views <span>⌖</span></summary>
        <div className="camera-presets" role="group" aria-label="Camera presets">{CAMERA_PRESETS.map(p=><button key={p.id} disabled={!stats} onClick={()=>api.current?.frame(p.id)} aria-label={`${p.label} camera`}>{p.label}</button>)}</div>
        <label className="check-control"><input type="checkbox" aria-label="Orthographic camera" checked={settings.orthographic} onChange={e=>patch({orthographic:e.target.checked})}/>Orthographic camera</label>
        <p className="inspector-note">Axes: front +Z, right +X, up +Y. Drag to orbit; right-drag to pan. WASD moves relative to the camera, Q/E moves down/up, Shift speeds up. F fits the model.</p>
        <div className="bookmark-entry"><input aria-label="Saved view name" maxLength={80} placeholder="Name this view…" value={bookmarkName} onChange={e=>setBookmarkName(e.target.value)}/><button onClick={saveAngle} disabled={!stats}>☆ Save</button></div>
        {!!bookmarks.length&&<div className="bookmarks">{bookmarks.map(b=><div key={b.name}><button onClick={()=>restoreView(b.view)} disabled={!stats}>{b.name}</button><button aria-label={`Delete saved view ${b.name}`} onClick={()=>setBookmarks(bs=>bs.filter(v=>v.name!==b.name))}>×</button></div>)}</div>}
        <div className="view-actions"><button onClick={share}>⤴ Copy view link</button><button onClick={()=>{const defaults=validSettings(DEFAULT_SETTINGS);setSettings(defaults);api.current?.applySettings(defaults);morphs.forEach(m=>setMorph(m.name,0));play(null);api.current?.isolate(null,false);api.current?.pick(null);api.current?.frame('three-quarter');}}>↺ Reset view</button></div>
        <p className="inspector-note">Your last view and favourites stay in this browser. Links include viewing settings; recipients need access to this dashboard and its asset files.</p>
      </details>
      {variants.length>1&&<details className="variants-details"><summary>Version comparison <span>{variants.length}</span></summary><table className="version-table"><thead><tr><th>Version</th><th>File</th><th>Triangles</th><th>Draws</th></tr></thead><tbody>{variants.map(v=><tr key={v.item.id} className={displayedId===v.item.id?'current':''}><td>{v.label}</td><td>{mb(v.item.glbBytes)||'Export'}</td><td>{measured[v.item.id]?count(measured[v.item.id].tris):'—'}</td><td>{measured[v.item.id]?.calls??'—'}</td></tr>)}</tbody></table><p className="inspector-note">Switch to measure each version. Camera and lighting stay fixed. Draws reflect the last measured view, including shadows. “—” means unmeasured.</p></details>}
      {picked&&<section className="picked-part" aria-label="Selected part"><div className="inspector-heading"><h3>{picked.name.replace(/_/g,' ')}</h3><button aria-label="Clear part selection" onClick={()=>api.current?.pick(null)}>×</button></div><p>{count(picked.stats.tris)} triangles · {picked.stats.meshes} meshes</p><p className="inspector-note">{picked.materials.join(', ')}</p><div className="view-actions"><button onClick={()=>api.current?.frame(undefined,true)}>⌖ Fit selection</button><button onClick={()=>selectPart(picked.id)}>Isolate</button><button onClick={()=>{const part=nodes.find(p=>p.id===picked.id);if(part)setNode(part.uuid,false);api.current?.pick(null);}}>Hide</button></div></section>}
      {shareNotice&&<p className="inspector-note" role="status">{shareNotice}</p>}{shareFallback&&<textarea className="share-link" aria-label="View link" readOnly value={shareFallback} onFocus={e=>e.target.select()}/>}
      <details className="inspection-details"><summary>Surface &amp; assembly <span>⬡</span></summary><div className="inspection-modes" role="group" aria-label="Surface inspection">{INSPECTION_MODES.map(m=><button key={m.id} aria-pressed={settings.mode===m.id} disabled={!stats} onClick={()=>patch({mode:m.id})}>{m.label}</button>)}</div><p className="inspector-note">Roughness: black is smooth, white is rough (texture green channel × material value). Normals show surface direction. UV checker: labelled cells on UV0; stretched, uneven or mirrored cells show bad UVs, red means no UVs. Depth: linear camera distance, white at the model's nearest point, black a little past its centre. Materials restores the authored surfaces.</p><label className="viewer-slider">Explode parts <output>{Math.round(settings.explode*100)}%</output><input aria-label="Explode parts" type="range" min={0} max={1} step={.01} value={settings.explode} disabled={!stats} onChange={e=>patch({explode:+e.target.value})}/></label><button disabled={!stats} onClick={()=>{patch({explode:0});setPartNotice('');}}>↺ Assemble</button><p className="inspector-note">Separates authored groups; shared skeletons stay assembled. Click the model to pick a part and highlight its card.</p></details>
      {!!materials.length&&<MaterialBrowser materials={materials} revision={displayedId} capture={captureTexture} onHighlight={id=>api.current?.highlightMaterial(id)}/>}
      <details className="effects-details"><summary>Look &amp; effects <span className="summary-status">{game?`Game · ${gameTier?.label||'Custom'}`:'Viewer'}</span></summary>
        <div className="lighting-presets" role="group" aria-label="Look">{LOOKS.map(l=><button key={l.id} aria-pressed={settings.look===l.id} onClick={()=>patch({look:l.id})}>{l.id==='game'?'🎮 ':'✦ '}{l.label}</button>)}</div>
        <p className="inspector-note">{game?'What the game renders: neutral tone mapping, dim room light, sky/ground fill, the low golden sun, haze and fog, with the game\'s own effect settings below.':'The beautified inspection look: ACES, your lighting and the effects below.'}</p>
        {game&&<div className="lighting-presets" role="group" aria-label="Game quality tier">{TIERS.map(t=><button key={t.id} title={t.note} aria-pressed={gameTier?.id===t.id} onClick={()=>patch({game:tierValues(t.id)})}>{t.label}</button>)}</div>}
        {PICTURE_EFFECTS.map(e=>{const value=effectValues[e.key],title=`${e.how}${game?` · game default: ${TIERS.map(t=>`${t.label} ${String(e.game[t.id])}`).join(', ')}`:''}${(e.cost as {draws?:string}|null)?.draws?` · cost: ${(e.cost as {draws:string}).draws} draw calls`:''}`;
          return e.kind==='toggle'
            ?<label key={e.key} className="check-control" title={title}><input type="checkbox" aria-label={e.label} checked={!!value} onChange={ev=>setSettings(s=>withEffect(s,e.key,ev.target.checked))}/><span aria-hidden="true">{e.icon}</span> {e.label}</label>
            :<label key={e.key} className="quality-control" title={title}><span><span aria-hidden="true">{e.icon}</span> {e.label}</span><select aria-label={e.label} value={String(value)} onChange={ev=>{const o=optionsFor(e,settings.look).find(o=>String(o.value)===ev.target.value);if(o)setSettings(s=>withEffect(s,e.key,o.value));}}>{optionsFor(e,settings.look).map(o=><option key={String(o.value)} value={String(o.value)}>{o.label}</option>)}</select></label>;})}
        <p className="inspector-note">One list with the game's settings sheet (a design decision): {EFFECTS_FILE}. Effects cost extra GPU work; draw calls and frame times under Viewing performance include them{perf?.post?.length?` (now: ${perf.post.join(', ')})`:''}. AO, glow and edge refinement apply to Materials and Clay; analysis views stay exact. Rendering still stops at rest, after at most {REFINE_FRAMES} refinement frames.</p>
      </details>
      <details className="lighting-details"><summary>Lighting &amp; background <span>☀</span></summary>{game&&<p className="inspector-note">The game look sets its own lighting; these controls apply to the viewer look.</p>}
        <div className="lighting-presets" role="group" aria-label="Lighting presets">{LIGHTING_PRESETS.map(p => <button key={p.id} aria-pressed={preset === p.id} onClick={() => setLighting(l=>({...l,...p.values,color:p.values.warmth?'#ffd2a0':'#ffffff'}))}>{p.label}</button>)}</div>
        <label className="quality-control">Environment<select aria-label="Environment preset" value={lighting.environmentPreset||'studio'} onChange={e=>setLighting(l=>({...l,environmentPreset:e.target.value}))}>{ENVIRONMENTS.map(e=><option key={e.id} value={e.id}>{e.label}</option>)}</select></label>
        <label className="check-control"><input type="checkbox" aria-label="Ground shadows" disabled={game} checked={!!lighting.shadows} onChange={e=>setLighting(l=>({...l,shadows:e.target.checked}))}/>Ground shadows</label>
        <label className="viewer-slider">Light elevation <output>{lighting.elevation??45}°</output><input type="range" aria-label="Light elevation" min={5} max={85} step={1} value={lighting.elevation??45} onChange={e=>setLighting(l=>({...l,elevation:+e.target.value}))}/></label>
        <label className="color-control">Light colour<input type="color" aria-label="Light colour" value={lighting.color||(lighting.warmth?'#ffd2a0':'#ffffff')} onChange={e=>setLighting(l=>({...l,color:e.target.value}))}/></label>
        <label className="viewer-slider">Exposure <output>{lighting.exposure.toFixed(1)}×</output><input type="range" aria-label="Exposure" min={0.2} max={3} step={0.1} value={lighting.exposure} onChange={e => setLighting(l => ({...l, exposure: +e.target.value}))} /></label>
        <label className="viewer-slider">Environment light <output>{lighting.environment.toFixed(1)}</output><input type="range" aria-label="Environment light" min={0} max={3} step={0.1} value={lighting.environment} onChange={e => setLighting(l => ({...l, environment: +e.target.value}))} /></label>
        <label className="viewer-slider">Key light <output>{lighting.key.toFixed(1)}</output><input type="range" aria-label="Key light" min={0} max={5} step={0.1} value={lighting.key} onChange={e => setLighting(l => ({...l, key: +e.target.value}))} /></label>
        <label className="viewer-slider">Light direction <output>{lighting.angle}°</output><input type="range" aria-label="Light direction" min={-180} max={180} step={1} value={lighting.angle} onChange={e => setLighting(l => ({...l, angle: +e.target.value}))} /></label>
        <div className="background-control"><span>Background</span><div role="group" aria-label="Background color">{BACKGROUNDS.map(b => <button key={b.color} style={{background: b.color}} aria-label={`${b.label} background`} title={b.label} aria-pressed={background === b.color} onClick={() => setBackground(b.color)}>{background === b.color ? '✓' : ''}</button>)}</div></div>
        <div className="lighting-reset"><span>{preset === 'custom' ? 'Custom lighting' : LIGHTING_PRESETS.find(p => p.id === preset)?.label}</span><button onClick={() => { setLighting({...DEFAULT_LIGHTING,elevation:45,color:'#ffffff',environmentPreset:'studio',shadows:false}); setBackground(BACKGROUNDS[0].color); }}>↺ Reset lighting</button></div>
        <p className="inspector-note">Applies to 3D viewing. Exposure changes brightness; the environment lights surfaces and reflections. Saved renders keep their original lighting.</p>
      </details>
      <details className="performance-details" open><summary>Viewing performance <span className="summary-status">{stats ? (suspended ? 'Paused for photos' : perf?.fps ? 'Live' : 'Idle') : 'Not loaded'}</span></summary>
        {perf ? <><dl className="asset-facts"><div><dt>Motion frame rate</dt><dd>{suspended ? 'Paused' : perf.fps == null ? 'Idle' : `${Math.round(perf.fps)} fps`}</dd></div><div><dt title="CPU time spent submitting the last measured frame, not GPU time">Frame submission ⓘ</dt><dd>{perf.cpuMs.toFixed(1)} ms</dd></div><div><dt>Draw calls / frame</dt><dd>{count(perf.calls)}</dd></div><div><dt title="Effects drawn in the last frame; their passes are included in draw calls">Effects ⓘ</dt><dd>{perf.post?.length?perf.post.join(', '):'None'}</dd></div><div><dt>Rendered triangles</dt><dd>{count(perf.triangles)}</dd></div><div><dt>Render resolution</dt><dd>{perf.width} × {perf.height}</dd></div>{loadMs != null && <div><dt title="Download and parse in this visit; excludes any Blender export">Model load ⓘ</dt><dd>{(loadMs / 1000).toFixed(2)} s</dd></div>}</dl><p className="inspector-note">Measured in this browser. Frame submission is CPU time; GPU time is not measured. Rendering stops at rest and while viewing photos.</p></> : <p className="inspector-note">{requested ? 'Measurements appear when the 3D model is visible.' : 'Open the 3D model to see geometry and live rendering measurements.'}</p>}
        {perf&&<FrameGraph values={perf.intervals||[]}/>}
        <label className="check-control"><input type="checkbox" aria-label="Adaptive motion resolution" checked={settings.adaptive} onChange={e=>patch({adaptive:e.target.checked})}/>Adaptive motion resolution</label><p className="inspector-note">Reduces resolution during movement when frames slow down, then restores detail at rest. {perf?.ratio!=null&&<>Active: {perf.ratio.toFixed(2)}×.</>}</p>
        <label className="quality-control">Pixel density<select aria-label="Pixel density" value={effectValues.resolution} onChange={e => setSettings(s=>withEffect(s,'resolution',+e.target.value))}><option value={1}>Economy · up to 1×</option><option value={1.5}>Balanced · up to 1.5×</option><option value={2}>Detail · up to 2×</option></select></label>
        <p className="inspector-note">3D resolution per screen pixel, capped by your display. 2× draws up to four times the pixels of 1×. Anti-aliasing smooths edges separately and stays enabled.</p>
        {stats && <details className="memory-details"><summary>Memory estimates</summary><dl className="asset-facts"><div><dt>Geometry buffers</dt><dd>{memorySize(stats.geometryBytes)}</dd></div><div><dt>Texture pixels</dt><dd>≈ {memorySize(stats.textureBytes)}</dd></div><div><dt>Renderer resources</dt><dd>{perf?.geometries ?? '—'} geometries / {perf?.textures ?? '—'} textures</dd></div></dl><p className="inspector-note">Textures estimated as base-level RGBA pixels, excluding mipmaps, compression and driver overhead. Visible asset only; this is not total GPU memory.</p></details>}
      </details>
      {!!nodes.length && <PartBrowser asset={displayedItem.id} parts={nodes} selected={selectedPart} picked={picked?.id||null} active={!suspended && info && pageVisible} revision={pictureRevision} capture={capturePart} onSelect={id => selectPart(id)} onVisible={setNode} onAll={() => selectPart(null)} />}
      {!nodes.length && <details><summary>Parts <span>▧</span></summary><p className="inspector-note">Part pictures come from the 3D model. {requested ? 'They appear when the model finishes loading.' : 'Open 3D to inspect individual parts.'}</p><button onClick={openModel}>⬡ Open 3D parts</button></details>}
      {partNotice && <p className="inspector-note" role="status">{partNotice}</p>}
      {!!morphs.length && <details><summary>Morphs <span>{morphs.length}</span></summary>{morphs.map(m => <label key={m.name} className="row">{m.name}<input type="range" min={0} max={1} step={0.01} value={m.value} onChange={e => setMorph(m.name, +e.target.value)} /></label>)}</details>}
      {!!clips.length && <details open><summary>Animations <span>{clips.length}</span></summary>{clips.map(c => <button key={c} aria-pressed={playing === c} onClick={() => play(playing === c ? null : c)}>{playing === c ? '⏸' : '▶'} {c}</button>)}</details>}
      <details><summary>Source &amp; details</summary><p className="path">{item.path}</p><p className="inspector-note">Modified {kyiv(item.assetMtime)}{item.preview && <><br />Preview {kyiv(item.preview.mtime)}<br />{item.preview.origin === 'pipeline' ? 'Project render' : 'Dashboard render'}</>}</p>{item.made_with?.via && <p className="path">Maker record: {item.made_with.via}</p>}{item.meta && <table className="meta"><tbody>{Object.entries(item.meta).map(([k, v]) => <tr key={k}><td>{k}</td><td>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</td></tr>)}</tbody></table>}<button onClick={queueRender} disabled={rerender === 'Requesting…'}>↻ Re-render preview</button>{rerender && <p className="inspector-note" role="status">{rerender}</p>}</details>
      </div>
    </aside>
  </div>;
}
