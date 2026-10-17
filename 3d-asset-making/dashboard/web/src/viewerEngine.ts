import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader, type GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/examples/jsm/libs/meshopt_decoder.module.js';
import { clipRange, frameBounds } from './framing.ts';
import { cameraDirection, cameraState, fitView, type ViewCamera } from './cameraTools.ts';
import { disposeObject, measureAsset, type AssetStats, type ViewPerf } from './viewerMetrics.ts';
import { modelParts, partPicture, type ModelPart } from './modelParts.ts';
import { DEPTH_RANGE, inspectMaterials, MaterialInspection, type MaterialRow } from './materialInspection.ts';
import { REFINE_FRAMES, ViewerEffects } from './viewerEffects.ts';
import { GAME_LOOK, gameFog, gameShadowHalf, gameSunDirection, patchGameFog } from './gameLook.ts';
import { makeEnvironment } from './viewerEnvironments.ts';
import { castsShadow, findLiveSpec, hasIdleKinds, loadKinds, LivePrograms, type LiveInfo, type LiveSpec } from './livePrograms.ts';
import type { IdleLibrary } from '@idle-library/idle-three.js';
import { activeEffects, type CameraPreset, type CameraState, type SavedView, type ViewSettings } from './viewerSettings.ts';

const present=(...objects:(THREE.Object3D|undefined)[])=>objects.filter((o):o is THREE.Object3D=>!!o);
const MODEL_TRANSITION={out:160,in:200,settle:50,cancel:120} as const;

export type PartInfo = { id:string; name:string; stats:AssetStats; materials:string[] };
export type LoadedModel = { stats:AssetStats; parts:ModelPart[]; morphs:string[]; clips:string[]; materials:MaterialRow[]; loadMs:number; url:string; id:string; bytes:number|null };
export type BenchResult = { frames: number; medianMs: number; meanMs: number; calls: number; triangles: number; post: string[]; width: number; height: number };
declare global { interface Window { __viewerBench?: (options?: { frames?: number; resting?: boolean; contact?: boolean }) => BenchResult | null } }
export type EngineCallbacks = { phase:(message:string)=>void; loaded:(value:LoadedModel)=>void; parts:(value:ModelPart[],stats:AssetStats,isolated:string|null)=>void; picked:(value:PartInfo|null)=>void; notice:(value:string)=>void; perf:(value:ViewPerf)=>void; camera:(value:CameraState)=>void; live?:(value:LiveInfo|null)=>void };
export class ViewerEngine {
  renderer:THREE.WebGLRenderer;
  scene=new THREE.Scene();
  camera:ViewCamera=new THREE.PerspectiveCamera(40,1,.001,1000);
  controls:OrbitControls;
  model?:THREE.Object3D; gltf?:GLTF; mixer?:THREE.AnimationMixer;
  parts:ModelPart[]=[]; inspector?:MaterialInspection;
  grid?:THREE.GridHelper; floor?:THREE.Mesh; selected:PartInfo|null=null; isolated:string|null=null;
  settings:ViewSettings;
  active=true; anim=false; disposed=false;
  private live?:LivePrograms; private livePref={on:true,playing:true};
  private sun=new THREE.DirectionalLight(0xffffff,1.2);
  private outline=new THREE.Box3Helper(new THREE.Box3(),0xf2a366);
  private environments=new Map<string,THREE.WebGLRenderTarget>();
  private originalPositions=new Map<THREE.Object3D,THREE.Vector3>();
  private defaults=new Map<string,boolean>();
  private baseBox=new THREE.Box3();
  private ro:ResizeObserver;private raf=0;private idleTimer=0;private cameraTimer=0;
  private generation=0;private dragging=false;private ratio=0;private aspect=1;private lastFrame=0;
  private lastPublish=0;private intervals:number[]=[];private sampleCount=0;private latestPerf?:ViewPerf;
  private clock=new THREE.Clock();private down?:{x:number;y:number};private saved:SavedView;
  private swapAnimation?:Animation;
  private initial=true;private keys=new Set<string>();private unserved=new Set<string>();private releaseAfterStep=new Set<string>();
  private marker?:THREE.Group;   // a place the geometry check names (GeometryCheck.tsx ⌖)
  private fx:ViewerEffects;      // post effects + contact shadow (viewerEffects.ts); off = the plain render
  private hemi=new THREE.HemisphereLight(GAME_LOOK.hemi.sky,GAME_LOOK.hemi.ground,GAME_LOOK.hemi.intensity); // game look only
  private sample=0;private modelDirty=true;private game=false;
  constructor(private el:HTMLDivElement,settings:ViewSettings,saved:SavedView,private cb:EngineCallbacks) {
    this.settings=settings;this.saved=saved;
    this.renderer=new THREE.WebGLRenderer({antialias:true});this.renderer.toneMapping=THREE.ACESFilmicToneMapping;
    this.renderer.shadowMap.type=THREE.PCFSoftShadowMap;this.renderer.info.autoReset=false;
    // A surface program that does not compile: say so and show the exported fallback instead of a black part.
    this.renderer.debug.onShaderError=(gl,program,vs,fs)=>{console.error('Shader compile error',gl.getProgramInfoLog(program),gl.getShaderInfoLog(vs),gl.getShaderInfoLog(fs));
      if(this.live?.info.on){this.cb.notice('A live surface program does not compile here; showing the exported fallback.');queueMicrotask(()=>this.setLive(false));}};
    this.renderer.domElement.setAttribute('aria-label','Interactive 3D model');this.renderer.domElement.tabIndex=0;el.appendChild(this.renderer.domElement);
    this.scene.background=new THREE.Color(settings.background);this.scene.add(this.sun,this.sun.target,this.outline,this.hemi);this.outline.visible=false;this.hemi.visible=false;patchGameFog();
    this.fx=new ViewerEffects(this.renderer,this.scene,()=>present(this.floor,this.fx.contact.group,this.marker,this.outline));
    window.__viewerBench=o=>this.bench(o);
    this.controls=new OrbitControls(this.camera,this.renderer.domElement);this.controls.enableDamping=true;
    this.controls.addEventListener('change',()=>{this.render();this.publishCamera();});
    this.controls.addEventListener('start',()=>{this.dragging=true;this.lastFrame=0;if(this.settings.adaptive)this.setRatio(Math.min(this.ratioCap(),1));});
    this.controls.addEventListener('end',()=>{this.dragging=false;this.publishCamera();this.render();});
    this.renderer.domElement.addEventListener('pointerdown',this.pointerDown);
    this.renderer.domElement.addEventListener('pointerup',this.pointerUp);
    this.renderer.domElement.addEventListener('webglcontextlost',this.contextLost);
    window.addEventListener('keydown',this.keyDown);window.addEventListener('keyup',this.keyUp);window.addEventListener('blur',this.clearKeys);
    this.ro=new ResizeObserver(this.resize);this.ro.observe(el);
    this.applySettings(settings);this.resize();
  }
  private keyDown=(e:KeyboardEvent)=>{const key=e.key.toLowerCase();if(!this.active||e.ctrlKey||e.metaKey||e.altKey||(e.target as HTMLElement)?.closest('input,textarea,select,[contenteditable="true"]'))return;if(['w','a','s','d','q','e','shift'].includes(key)){e.preventDefault();if(!this.keys.has(key))this.unserved.add(key);this.keys.add(key);this.render();}};
  // A press always moves at least one step, even when it is released before the next frame (slow frames, e.g. refinement on software GL).
  private keyUp=(e:KeyboardEvent)=>{const key=e.key.toLowerCase();if(this.unserved.has(key))this.releaseAfterStep.add(key);else this.keys.delete(key);};
  private clearKeys=()=>{this.keys.clear();this.unserved.clear();this.releaseAfterStep.clear();};
  private navigate(dt:number){
    if((document.activeElement as HTMLElement)?.closest('input,textarea,select,[contenteditable="true"]')){this.clearKeys();return false;}
    if(!this.model||!['w','a','s','d','q','e'].some(k=>this.keys.has(k)))return false;
    const forward=this.camera.getWorldDirection(new THREE.Vector3()),right=new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld,0),delta=new THREE.Vector3();
    if(this.keys.has('w'))delta.add(forward);if(this.keys.has('s'))delta.sub(forward);if(this.keys.has('d'))delta.add(right);if(this.keys.has('a'))delta.sub(right);if(this.keys.has('e'))delta.y+=1;if(this.keys.has('q'))delta.y-=1;
    const radius=Math.max(this.baseBox.getSize(new THREE.Vector3()).length()/2,.001),scale=this.camera instanceof THREE.OrthographicCamera?(this.camera.top-this.camera.bottom)/this.camera.zoom:this.camera.position.distanceTo(this.controls.target);
    delta.normalize().multiplyScalar(Math.max(radius,scale*.4)*dt*(this.keys.has('shift')?3:1));this.camera.position.add(delta);this.controls.target.add(delta);this.publishCamera();
    this.unserved.clear();for(const k of this.releaseAfterStep)this.keys.delete(k);this.releaseAfterStep.clear();return true;
  }
  private updateClipping(){
    // OrbitControls permits unbounded dolly. Keep the model inside the camera's depth range at every distance (framing.ts clipRange).
    if(!this.model||this.baseBox.isEmpty())return;const {near,far}=clipRange(this.camera.position,this.baseBox,this.meshBoxes(),this.camera instanceof THREE.PerspectiveCamera);
    if(this.camera.near!==near||this.camera.far!==far){this.camera.near=near;this.camera.far=far;this.camera.updateProjectionMatrix();if(window.__glbCheck)window.__glbCheck.clip={near,far};}
  }
  // World boxes of every mesh for clipRange (hidden ones too: safe; instances included), rebuilt after load/explode;
  // skinned or a playing animation = none (boxes move), which leaves the distance-only near.
  private clipBoxes:THREE.Box3[]|null=null;
  private meshBoxes(){
    if(!this.model||this.anim)return [];
    if(!this.clipBoxes){const boxes:THREE.Box3[]=[];let skinned=false;this.model.updateWorldMatrix(true,true);this.model.traverse(o=>{const m=o as THREE.Mesh;if((m as THREE.SkinnedMesh).isSkinnedMesh)skinned=true;else if(m.isMesh){const inst=m as THREE.InstancedMesh;let local:THREE.Box3;if(inst.isInstancedMesh){inst.computeBoundingBox();local=inst.boundingBox!;}else{if(!m.geometry.boundingBox)m.geometry.computeBoundingBox();local=m.geometry.boundingBox!;}boxes.push(local.clone().applyMatrix4(m.matrixWorld));}});this.clipBoxes=skinned?[]:boxes;}
    return this.clipBoxes;
  }
  private contextLost=(e:Event)=>{if(!this.disposed){e.preventDefault();this.setActive(false);this.cb.phase('3D paused by the browser. Reload to resume, or view the renders.');}};
  private pointerDown=(e:PointerEvent)=>{if(e.button===0)this.down={x:e.clientX,y:e.clientY};};
  private pointerUp=(e:PointerEvent)=>{
    const down=this.down;this.down=undefined;if(e.button!==0||!down||!this.model||Math.hypot(e.clientX-down.x,e.clientY-down.y)>5)return;
    const bounds=this.renderer.domElement.getBoundingClientRect(),ray=new THREE.Raycaster();
    ray.setFromCamera(new THREE.Vector2((e.clientX-bounds.left)/bounds.width*2-1,-(e.clientY-bounds.top)/bounds.height*2+1),this.camera);
    const hits=ray.intersectObject(this.model,true).filter(hit=>{for(let o:THREE.Object3D|null=hit.object;o;o=o.parent)if(!o.visible)return false;return true;});
    const object=hits[0]?.object;let part:ModelPart|undefined;
    for(let node:THREE.Object3D|null|undefined=object;node&&!part;node=node.parent)part=this.parts.find(p=>p.uuid===node!.uuid);
    this.pick(part?.id||null);
  };
  private setRatio(value:number){const ratio=Math.min(devicePixelRatio,value);if(Math.abs(this.ratio-ratio)<.01)return;this.ratio=ratio;this.renderer.setPixelRatio(ratio);this.resize();}
  resize=()=>{
    const w=this.el.clientWidth,h=this.el.clientHeight;if(!w||!h||this.disposed)return;
    this.aspect=w/h;this.renderer.setSize(w,h,false);Object.assign(this.renderer.domElement.style,{width:'100%',height:'100%'});
    if(this.camera instanceof THREE.PerspectiveCamera)this.camera.aspect=this.aspect;
    else{const half=(this.camera.top-this.camera.bottom)/2;this.camera.left=-half*this.aspect;this.camera.right=half*this.aspect;}
    this.camera.updateProjectionMatrix();this.render();
  };
  // Any change restarts edge refinement; the refinement frames themselves continue via schedule().
  render=()=>{this.sample=0;this.schedule();};
  private ratioCap(){return activeEffects(this.settings).resolution;}
  private schedule(){if(!this.raf&&this.active&&!this.disposed)this.raf=requestAnimationFrame(this.loop);}
  // Which effects this frame uses (config/picture-effects.json values of the active look). The analysis views keep
  // the plain path: normals/roughness/UV/depth materials are not tone-mapped, which the composer's OutputPass would change.
  private effects(){
    const e=activeEffects(this.settings),on=!!this.model,surface=this.settings.mode==='textured'||this.settings.mode==='clay';
    return {ao:on&&e.ao&&surface,bloom:on&&e.bloom&&surface,aa:on&&e.aa==='refine'&&surface,contact:on&&e.contactShadow};
  }
  private postNames(e:ReturnType<ViewerEngine['effects']>,refining:boolean){return [e.contact&&'contact shadow',e.ao&&'AO',e.bloom&&'bloom',refining&&'edge refinement'].filter((n):n is string=>!!n);}
  private drawFrame(e:ReturnType<ViewerEngine['effects']>,refining:boolean,sample:number,forceContact=false){
    this.fx.contact.group.visible=e.contact;
    if(e.contact&&(this.modelDirty||this.anim||forceContact)){this.fx.contact.update(this.renderer,this.scene,present(this.grid,this.floor,this.outline,this.marker));this.modelDirty=false;}
    if(this.settings.mode==='depth')this.updateDepthRange();
    if(this.game)this.followGameCamera();
    this.fx.render(this.camera,{ao:e.ao,bloom:e.bloom,aa:refining,sample:refining?sample:0});
  }
  private updateDepthRange(){
    if(this.baseBox.isEmpty())return;this.camera.updateMatrixWorld();const inverse=this.camera.matrixWorld.clone().invert(),v=new THREE.Vector3(),b=this.baseBox;let near=Infinity,far=-Infinity;
    for(let i=0;i<8;i++){v.set(i&1?b.max.x:b.min.x,i&2?b.max.y:b.min.y,i&4?b.max.z:b.min.z).applyMatrix4(inverse);near=Math.min(near,-v.z);far=Math.max(far,-v.z);}
    // The box's far half is mostly hidden behind the model, so the ramp ends a little past the box centre: visible depth spans the full ramp.
    const center=b.getCenter(new THREE.Vector3()).applyMatrix4(inverse),r=b.getSize(new THREE.Vector3()).length()/2;far=Math.min(far,-center.z+r*.35);
    DEPTH_RANGE.depthNear.value=Math.max(near,this.camera.near);DEPTH_RANGE.depthFar.value=Math.max(far,DEPTH_RANGE.depthNear.value+1e-6);
  }
  // Environment.update() of the game: fog and the sun's shadow box follow the camera's distance to its target.
  private followGameCamera(){
    const distance=this.camera.position.distanceTo(this.controls.target),fog=gameFog(distance);
    if(this.scene.fog instanceof THREE.Fog){this.scene.fog.near=fog.near;this.scene.fog.far=fog.far;}
    const half=gameShadowHalf(distance),cam=this.sun.shadow.camera;if(cam.right!==half){cam.left=cam.bottom=-half;cam.right=cam.top=half;cam.updateProjectionMatrix();}
  }
  // Measures whole frames (CPU + GPU: each waits for a 1-pixel read-back) on the current view, for docs/effects-import-20261013.md.
  bench({frames=30,resting=false,contact=false}:{frames?:number;resting?:boolean;contact?:boolean}={}):BenchResult|null{
    if(!this.model||!this.active)return null;const gl=this.renderer.getContext(),pixel=new Uint8Array(4),times:number[]=[],e=this.effects(),refining=resting&&e.aa;let calls=0,triangles=0;
    for(let i=0;i<frames+3;i++){const start=performance.now();this.renderer.info.reset();this.drawFrame(e,refining,i%REFINE_FRAMES,contact);gl.readPixels(0,0,1,1,gl.RGBA,gl.UNSIGNED_BYTE,pixel);if(i>=3)times.push(performance.now()-start);calls=this.renderer.info.render.calls;triangles=this.renderer.info.render.triangles;}
    const sorted=[...times].sort((a,b)=>a-b),size=this.renderer.getDrawingBufferSize(new THREE.Vector2());this.render();
    return {frames,medianMs:sorted[Math.floor(sorted.length/2)],meanMs:times.reduce((a,b)=>a+b,0)/times.length,calls,triangles,post:this.postNames(e,refining),width:size.x,height:size.y};
  }
  private loop=()=>{
    this.raf=0;if(!this.active||this.disposed)return;
    const dt=Math.min(this.clock.getDelta(),.1),navigating=this.navigate(dt),moving=this.controls.update()||navigating;this.updateClipping();if(this.anim)this.mixer?.update(Math.min(dt,.1));
    const live=this.liveRunning();if(live)this.live!.advance(dt); // a live surface program is the one case of continuous rendering
    if(this.selected)this.updateOutline();
    const now=performance.now();const interval=this.lastFrame?now-this.lastFrame:0;this.lastFrame=now;
    if(interval>0&&interval<10000){this.intervals.push(interval);if(this.intervals.length>60)this.intervals.shift();}
    if(this.settings.adaptive&&(moving||this.dragging||this.anim||live)&&++this.sampleCount%10===0&&interval>0&&interval<10000){
      const maximum=Math.min(this.ratioCap(),1.25);const next=interval>28?this.ratio-.15:interval<18?this.ratio+.05:this.ratio;this.setRatio(Math.max(.5,Math.min(maximum,next)));
    }
    const effects=this.effects(),resting=!moving&&!this.anim&&!live&&!this.dragging,refining=resting&&effects.aa&&!this.swapAnimation,sample=this.sample;
    this.renderer.info.reset();this.drawFrame(effects,refining,sample);const cpuMs=performance.now()-now;
    const more=refining&&sample<REFINE_FRAMES-1;if(more)this.sample++;
    if(more)this.renderer.domElement.dataset.refining=String(sample+1);else delete this.renderer.domElement.dataset.refining;
    const size=this.renderer.getDrawingBufferSize(new THREE.Vector2()),recent=this.intervals.slice(-20);const fps=recent.length>1?1000/(recent.reduce((a,b)=>a+b,0)/recent.length):null;
    this.latestPerf={calls:this.renderer.info.render.calls,triangles:this.renderer.info.render.triangles,textures:this.renderer.info.memory.textures,geometries:this.renderer.info.memory.geometries,cpuMs,fps,width:size.x,height:size.y,intervals:[...this.intervals],ratio:this.ratio,post:[...this.postNames(effects,refining),...(live?['live surfaces']:[])],refine:refining?sample+1:null};
    if(now-this.lastPublish>200||!this.lastPublish||(refining&&!more)){this.cb.perf(this.latestPerf);this.lastPublish=now;}
    clearTimeout(this.idleTimer);this.idleTimer=window.setTimeout(()=>{
      this.lastFrame=0;if(this.latestPerf)this.cb.perf({...this.latestPerf,fps:null,refine:null});
      if(this.settings.adaptive&&this.active&&!this.anim&&!this.dragging)this.setRatio(this.ratioCap());
    },220);
    if((moving||this.anim||live||more)&&!this.raf)this.raf=requestAnimationFrame(this.loop);
  };
  setActive(value:boolean){this.active=value;this.controls.enabled=value;
    if(!value){this.clearKeys();cancelAnimationFrame(this.raf);this.raf=0;delete this.renderer.domElement.dataset.refining;clearTimeout(this.idleTimer);this.lastFrame=0;if(this.latestPerf)this.cb.perf({...this.latestPerf,fps:null});}
    else{this.clock.getDelta();this.resize();this.render();}
  }
  applySettings(settings:ViewSettings){
    this.settings=settings;
    if((this.camera instanceof THREE.OrthographicCamera)!==settings.orthographic)this.projection(settings.orthographic);
    this.settings=settings;this.setRatio(this.ratioCap());const game=settings.look==='game';
    if(game!==this.game){this.game=game;this.scene.traverse(o=>{const m=(o as THREE.Mesh).material;if(m)for(const mat of Array.isArray(m)?m:[m])mat.needsUpdate=true;});this.sun.shadow.map?.dispose();this.sun.shadow.map=null;}
    (this.scene.background as THREE.Color).set(game?GAME_LOOK.haze:settings.background);
    const l=settings.lighting,id=game?'studio':l.environmentPreset||'studio';
    if(!this.environments.has(id))this.environments.set(id,makeEnvironment(this.renderer,id));
    this.scene.environment=this.environments.get(id)!.texture;this.scene.environmentIntensity=game?GAME_LOOK.environmentIntensity:l.environment;
    this.scene.environmentRotation.y=game?0:THREE.MathUtils.degToRad(l.angle-37);
    this.renderer.toneMapping=game?GAME_LOOK.toneMapping:THREE.ACESFilmicToneMapping;this.renderer.toneMappingExposure=game?GAME_LOOK.exposure:l.exposure;
    this.renderer.shadowMap.type=game?GAME_LOOK.shadowType:THREE.PCFSoftShadowMap;
    this.hemi.visible=game;this.scene.fog=game?new THREE.Fog(GAME_LOOK.haze,1,2):null;
    this.sun.intensity=game?GAME_LOOK.sun.intensity:l.key;this.sun.color.set(game?GAME_LOOK.sun.color:l.color||(l.warmth?'#ffd2a0':'#ffffff'));
    this.inspector?.apply(settings.mode,settings.wire);if(this.grid)this.grid.visible=settings.grid&&!game;
    this.explode(settings.explode);this.updateLights();this.render();
  }
  private updateLights(){
    const center=this.baseBox.isEmpty()?new THREE.Vector3():this.baseBox.getCenter(new THREE.Vector3());const r=Math.max(this.baseBox.getSize(new THREE.Vector3()).length(),1);
    const l=this.settings.lighting,angle=THREE.MathUtils.degToRad(l.angle),height=THREE.MathUtils.degToRad(l.elevation??45),game=this.game,g=GAME_LOOK.sun;
    if(game)this.sun.position.copy(center).addScaledVector(gameSunDirection(),g.distance);
    else this.sun.position.copy(center).add(new THREE.Vector3(Math.sin(angle)*Math.cos(height),Math.sin(height),Math.cos(angle)*Math.cos(height)).multiplyScalar(r*3));
    this.sun.target.position.copy(center);this.sun.target.updateMatrixWorld();
    // Game look = the game's sun: models cast and receive (Train.js), its biases; map size = the 'sunShadow' effect (0 = off).
    const sun=activeEffects(this.settings).sunShadow,shadows=sun>0,size=game&&sun?sun:1024;this.renderer.shadowMap.enabled=shadows;this.sun.castShadow=shadows;
    if(this.sun.shadow.mapSize.x!==size){this.sun.shadow.mapSize.set(size,size);this.sun.shadow.map?.dispose();this.sun.shadow.map=null;}
    if(game){const half=gameShadowHalf(this.camera.position.distanceTo(this.controls.target));Object.assign(this.sun.shadow.camera,{left:-half,right:half,top:half,bottom:-half,near:g.near,far:g.far});this.sun.shadow.bias=g.bias;this.sun.shadow.normalBias=g.normalBias;}
    else{Object.assign(this.sun.shadow.camera,{left:-r,right:r,top:r,bottom:-r,near:r*.01,far:r*8});this.sun.shadow.bias=0;this.sun.shadow.normalBias=r*.00005;}
    this.sun.shadow.camera.updateProjectionMatrix();
    const noShadow:string[]=[];this.model?.traverse(o=>{const mesh=o as THREE.Mesh;if(mesh.isMesh){const casts=castsShadow(mesh.material);if(!casts)noShadow.push(mesh.name);mesh.castShadow=shadows&&casts;mesh.receiveShadow=game;}});
    if(this.live&&String(this.live.info.noShadow)!==String(noShadow)){this.live.info.noShadow=noShadow;this.cb.live?.({...this.live.info});}
    if(this.floor)this.floor.visible=shadows;
  }
  projection(ortho:boolean){
    if((this.camera instanceof THREE.OrthographicCamera)===ortho)return;
    const old=this.camera,target=this.controls.target.clone(),distance=old.position.distanceTo(target);
    const camera:ViewCamera=ortho?new THREE.OrthographicCamera(-1,1,1,-1,.00001,1e7):new THREE.PerspectiveCamera(40,this.aspect,old.near,old.far);
    camera.position.copy(old.position);camera.quaternion.copy(old.quaternion);camera.up.copy(old.up);
    if(camera instanceof THREE.OrthographicCamera){const half=Math.max(distance*Math.tan(THREE.MathUtils.degToRad(20)),.001);camera.top=half;camera.bottom=-half;camera.left=-half*this.aspect;camera.right=half*this.aspect;camera.near=old.near;camera.far=old.far;}
    else if(old instanceof THREE.OrthographicCamera){const d=(old.top-old.bottom)/old.zoom/2/Math.tan(THREE.MathUtils.degToRad(20));camera.position.copy(target).add(old.position.clone().sub(target).normalize().multiplyScalar(d));}
    camera.updateProjectionMatrix();this.camera=camera;this.controls.object=camera;this.controls.target.copy(target);this.controls.update();this.publishCamera();this.render();
  }
  getCamera(){return cameraState(this.camera,this.controls.target);}
  restoreCamera(state:CameraState){this.projection(state.projection==='orthographic');this.camera.position.fromArray(state.position);this.camera.up.fromArray(state.up);this.controls.target.fromArray(state.target);
    if(this.camera instanceof THREE.OrthographicCamera){const half=state.scale/2;this.camera.top=half;this.camera.bottom=-half;this.camera.left=-half*this.aspect;this.camera.right=half*this.aspect;this.camera.zoom=1;}
    const d=Math.max(this.camera.position.distanceTo(this.controls.target),.0001);this.camera.near=d/1000;this.camera.far=d*1000;this.camera.updateProjectionMatrix();this.controls.update();this.publishCamera();this.render();}
  private publishCamera(){clearTimeout(this.cameraTimer);this.cameraTimer=window.setTimeout(()=>{if(!this.disposed)this.cb.camera(this.getCamera());},80);}
  frame(preset?:CameraPreset,selected=false){
    const node=selected&&this.selected?this.model?.getObjectByProperty('uuid',this.parts.find(p=>p.id===this.selected!.id)?.uuid||''):this.model;
    if(!node)return;const box=frameBounds(node);if(box.isEmpty())return;
    const center=fitView(this.camera,box,this.aspect,preset?cameraDirection(preset):this.camera.position.clone().sub(this.controls.target).normalize());
    this.controls.target.copy(center);this.controls.update();this.publishCamera();this.render();
  }
  private setupGround(){
    if(this.grid){this.scene.remove(this.grid);disposeObject(this.grid);}if(this.floor){this.scene.remove(this.floor);disposeObject(this.floor);}
    const center=this.baseBox.getCenter(new THREE.Vector3()),r=Math.max(this.baseBox.getSize(new THREE.Vector3()).length()/2,.001);
    this.grid=new THREE.GridHelper(r*4,20,0x555a66,0x33363d);this.grid.visible=this.settings.grid;this.grid.position.set(center.x,this.baseBox.min.y-r*.0002,center.z);this.scene.add(this.grid);
    this.floor=new THREE.Mesh(new THREE.PlaneGeometry(r*8,r*8),new THREE.ShadowMaterial({color:0x000000,opacity:.4}));this.floor.rotation.x=-Math.PI/2;this.floor.position.set(center.x,this.baseBox.min.y-r*.0003,center.z);this.floor.receiveShadow=true;this.floor.visible=!!this.settings.lighting.shadows;this.scene.add(this.floor);
    this.fx.fit(this.baseBox,this.model);this.modelDirty=true;
  }
  // ---- live surface programs (livePrograms.ts) ----
  private liveRunning(){return !!this.live&&this.live.info.animated&&this.live.info.on&&this.live.info.playing&&this.settings.mode==='textured'&&this.active;}
  private attachLive(model:THREE.Object3D,spec:LiveSpec|null|{error:string},kinds:IdleLibrary|null|{error:string}=null){
    if(spec&&'error' in spec){this.cb.notice(`Live surface program could not load: ${spec.error}. Showing the exported fallback.`);spec=null;}
    if(kinds&&'error' in kinds){this.cb.notice(`Shader library could not load: ${kinds.error}. Showing the exported fallback colours.`);kinds=null;}
    if(!spec&&!kinds){this.cb.live?.(null);return;}
    try{this.live=new LivePrograms(model,spec,kinds);}
    catch(e){this.cb.notice(`Live surface program failed: ${(e as Error).message}. Showing the exported fallback.`);this.cb.live?.(null);return;}
    if(!this.livePref.on)for(const [mesh,mat] of this.live.set(false))mesh.material=mat;
    this.live.info.playing=this.livePref.playing;this.live.advance(0);this.cb.live?.({...this.live.info});
  }
  // For headless checks: which live shaders are on screen (library kinds bound per mesh, Shader Lab programs).
  private liveCheck(){if(!this.live)return null;let kindMeshes=0;for(const [mesh] of this.live.live)if([mesh.material].flat().some(m=>(m.userData as {idle?:{uniforms?:unknown}}).idle?.uniforms))kindMeshes++;
    return {on:this.live.info.on,kinds:this.live.info.kinds,kindMeshes,programs:this.live.info.materials};}
  private disposeLive(){if(!this.live)return;for(const [mesh,mat] of this.live.fallback)mesh.material=mat;this.live.dispose();this.live=undefined;}
  /** Live = the surface programs the game runs; fallback = the still picture baked into the GLB (any glTF viewer). */
  setLive(on:boolean){
    if(!this.live)return;this.livePref.on=on;this.inspector?.restore();
    for(const [mesh,mat] of this.live.set(on)){mesh.material=mat;this.inspector?.originals.set(mesh,mat);}
    this.inspector?.apply(this.settings.mode,this.settings.wire);this.updateLights();this.cb.live?.({...this.live.info});this.render();
  }
  setLivePlaying(playing:boolean){if(!this.live)return;this.livePref.playing=playing;this.live.info.playing=playing;this.clock.getDelta();this.cb.live?.({...this.live.info});this.render();}
  cancelLoad(){
    this.generation++;
    if(this.disposed){this.swapAnimation?.cancel();this.swapAnimation=undefined;return;}
    void this.fadeModel(1,MODEL_TRANSITION.cancel);
  }
  private async fadeModel(opacity:number,duration:number,delay=0){
    const canvas=this.renderer.domElement,from=+getComputedStyle(canvas).opacity;
    const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.swapAnimation?.cancel();this.swapAnimation=undefined;canvas.style.opacity=String(from);
    if(reduce||Math.abs(from-opacity)<.001){canvas.style.opacity=String(opacity);return;}
    const animation=canvas.animate([{opacity:from},{opacity}],{duration,easing:'ease-in-out',fill:'forwards',delay});
    this.swapAnimation=animation;
    await animation.finished.catch(()=>{});
    if(this.swapAnimation===animation){canvas.style.opacity=String(opacity);animation.cancel();this.swapAnimation=undefined;if(opacity>0)this.render();}// refinement waits for the fade
  }
  load(url:string,id:string){
    this.cancelLoad();const generation=this.generation,started=performance.now();this.cb.phase('Loading model…');window.__glbCheck=undefined;
    const liveSpec:Promise<LiveSpec|null|{error:string}>=findLiveSpec(url).catch(e=>({error:String((e as Error).message||e)}));
    new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).load(url,async gltf=>{
      if(this.disposed||generation!==this.generation){disposeObject(gltf.scene);return;}
      const model=gltf.scene;model.traverse(o=>{if(/_LOD[1-9]|IMPOSTOR/i.test(o.name))o.visible=false;});const stats=measureAsset(model);
      if(!stats.meshes||!stats.tris){disposeObject(model);this.cb.phase('This GLB contains no visible geometry.');window.__glbCheck={id,glb:url,ok:false,err:'No visible geometry'};return;}
      if(this.model)await this.fadeModel(0,MODEL_TRANSITION.out);
      const spec=await liveSpec;
      const kinds:IdleLibrary|null|{error:string}=hasIdleKinds(model)?await loadKinds().catch(e=>({error:String((e as Error).message||e)})):null;
      if(this.disposed||generation!==this.generation){disposeObject(model);return;}
      const previousCamera=this.model?this.getCamera():null;
      this.mixer?.stopAllAction();if(this.model){this.mixer?.uncacheRoot(this.model);this.inspector?.dispose();this.disposeLive();this.scene.remove(this.model);disposeObject(this.model);}
      this.mark(null);this.model=model;this.gltf=gltf;this.scene.add(model);this.attachLive(model,spec,kinds);this.inspector=new MaterialInspection(model);const materials=inspectMaterials(model);this.parts=modelParts(model);this.defaults=new Map(this.parts.map(p=>[p.id,p.visible]));
      this.originalPositions.clear();for(const part of this.parts){const node=model.getObjectByProperty('uuid',part.uuid)!;this.originalPositions.set(node,node.position.clone());}
      this.baseBox=frameBounds(model).clone();this.clipBoxes=null;this.setupGround();this.mixer=gltf.animations.length?new THREE.AnimationMixer(model):undefined;this.anim=false;this.selected=null;this.cb.picked(null);this.isolated=null;this.outline.visible=false;
      this.intervals=[];this.lastFrame=0;this.lastPublish=0;clearTimeout(this.idleTimer);this.applySettings(this.settings);
      const saved=this.initial?this.saved:{};this.initial=false;
      if(saved.hidden)this.parts.forEach(p=>{if(saved.hidden!.includes(p.id))model.getObjectByProperty('uuid',p.uuid)!.visible=false;});
      if(saved.isolated)this.isolate(saved.isolated,false);
      if(saved.morphs)for(const [name,value]of Object.entries(saved.morphs))this.morph(name,value);
      if(saved.selected)this.pick(saved.selected);
      if(saved.camera)this.restoreCamera(saved.camera);else if(previousCamera)this.restoreCamera(previousCamera);else this.frame('three-quarter');
      const names=new Set<string>();model.traverse(o=>{const m=o as THREE.Mesh;if(m.morphTargetDictionary)Object.keys(m.morphTargetDictionary).forEach(n=>names.add(n));});
      this.syncParts();const resource=performance.getEntriesByName(new URL(url,location.href).href).at(-1) as PerformanceResourceTiming|undefined;
      this.cb.loaded({stats:this.measure(),parts:[...this.parts],morphs:[...names],clips:gltf.animations.map(c=>c.name||'clip'),materials,loadMs:performance.now()-started,url,id,bytes:resource?.encodedBodySize||null});
      this.cb.phase('ready');this.cb.camera(this.getCamera());window.__glbCheck={id,glb:url,ok:true,...stats,live:this.liveCheck(),frame:this.renderer.getContext().getError()===0};this.render();
      if(previousCamera)void this.fadeModel(1,MODEL_TRANSITION.in,MODEL_TRANSITION.settle);
    },e=>{if(!this.disposed&&generation===this.generation&&e.lengthComputable)this.cb.phase(`Loading model… ${Math.round(e.loaded/e.total*100)}%`);},e=>{if(!this.disposed&&generation===this.generation){const err=String((e as Error).message||e);this.cb.phase(`Model could not load: ${err}`);window.__glbCheck={id,glb:url,ok:false,err};}});
  }
  private measure(){this.inspector?.restore();const stats=measureAsset(this.model!);this.inspector?.apply(this.settings.mode,this.settings.wire);return stats;}
  syncParts(){if(!this.model)return;this.modelDirty=true;this.parts=this.parts.map(p=>({...p,visible:this.model!.getObjectByProperty('uuid',p.uuid)!.visible}));this.cb.parts([...this.parts],this.measure(),this.isolated);this.render();}
  visible(uuid:string,value:boolean){const node=this.model?.getObjectByProperty('uuid',uuid);if(!node)return;node.visible=value;this.isolated=null;this.syncParts();}
  isolate(id:string|null,fit=true){if(!this.model)return;const part=this.parts.find(p=>p.id===id);
    if(id&&!part){this.cb.notice('This part link no longer matches the model. Showing the complete asset.');id=null;}
    for(const p of this.parts)this.model.getObjectByProperty('uuid',p.uuid)!.visible=part?p.id===part.id:this.defaults.get(p.id)!;
    this.isolated=id;this.syncParts();if(fit)this.frame();
  }
  pick(id:string|null){const part=this.parts.find(p=>p.id===id),node=part&&this.model?.getObjectByProperty('uuid',part.uuid);
    if(!part||!node){this.selected=null;this.outline.visible=false;this.cb.picked(null);this.render();return;}
    this.inspector?.restore();const names=new Set<string>();node.traverse(o=>{const m=o as THREE.Mesh;if(m.isMesh)for(const mat of Array.isArray(m.material)?m.material:[m.material])names.add(mat.name||mat.type);});
    this.selected={id:part.id,name:part.name,stats:measureAsset(node),materials:[...names]};this.inspector?.apply(this.settings.mode,this.settings.wire);this.updateOutline();this.cb.picked(this.selected);this.render();
  }
  private updateOutline(){const part=this.selected&&this.parts.find(p=>p.id===this.selected!.id),node=part&&this.model?.getObjectByProperty('uuid',part.uuid);if(!node){this.outline.visible=false;return;}this.outline.box.copy(frameBounds(node));this.outline.visible=!this.outline.box.isEmpty();}
  highlightMaterial(id:string|null){if(!id||!this.inspector){this.updateOutline();this.render();return;}this.selected=null;this.cb.picked(null);const box=new THREE.Box3();for(const mesh of this.inspector.materialMeshes(id))box.union(frameBounds(mesh));this.outline.box.copy(box);this.outline.visible=!box.isEmpty();this.render();}
  explode(amount:number){if(!this.model||this.baseBox.isEmpty())return;const center=this.baseBox.getCenter(new THREE.Vector3()),radius=Math.max(this.baseBox.getSize(new THREE.Vector3()).length()/2,.001);
    let skipped=0;this.parts.forEach((part,index)=>{const node=this.model!.getObjectByProperty('uuid',part.uuid)!,position=this.originalPositions.get(node);if(!position)return;node.position.copy(position);node.updateWorldMatrix(true,true);
      let unsafe=false;node.traverse(o=>{const m=o as THREE.SkinnedMesh;if(m.isSkinnedMesh)for(const bone of m.skeleton.bones){let parent:THREE.Object3D|null=bone;while(parent&&parent!==node)parent=parent.parent;if(!parent)unsafe=true;}});
      if(unsafe){skipped++;return;}
      const visible=node.visible;node.visible=true;const box=frameBounds(node);node.visible=visible;if(box.isEmpty())return;const direction=box.getCenter(new THREE.Vector3()).sub(center);if(direction.length()<radius*.05)direction.set(Math.cos(index*2.399),.2+index%2*.25,Math.sin(index*2.399));direction.normalize();
      if(node.parent)direction.transformDirection(node.parent.matrixWorld.clone().invert());node.position.addScaledVector(direction,amount*radius*.8);
    });this.model.updateMatrixWorld(true);this.clipBoxes=null;this.modelDirty=true;if(amount&&skipped)this.cb.notice(`${skipped} part${skipped===1?'':'s'} remain assembled to preserve shared skinning.`);this.updateOutline();this.render();}
  // Mark a checker place: a dot (and its box when the line names one), drawn through the model, and turn the camera to it.
  // Checker coordinates are glTF world space with every node transform applied = this scene's space (the model is not moved).
  mark(place:{at:number[];min?:number[];max?:number[]}|null){
    if(this.marker){this.scene.remove(this.marker);disposeObject(this.marker);this.marker=undefined;}
    if(!place||!this.model){this.render();return;}
    const r=Math.max(this.baseBox.getSize(new THREE.Vector3()).length(),.001),group=new THREE.Group(),at=new THREE.Vector3().fromArray(place.at);
    const top=(o:THREE.Object3D)=>{o.renderOrder=999;const m=(o as THREE.Mesh).material as THREE.Material;if(m){m.depthTest=false;m.transparent=true;}return o;};
    const dot=top(new THREE.Mesh(new THREE.SphereGeometry(r*.008,16,12),new THREE.MeshBasicMaterial({color:0xff2d6f})));dot.position.copy(at);group.add(dot);
    const halo=top(new THREE.Mesh(new THREE.SphereGeometry(r*.025,20,14),new THREE.MeshBasicMaterial({color:0xff2d6f,wireframe:true,opacity:.55})));halo.position.copy(at);group.add(halo);
    if(place.min&&place.max)group.add(top(new THREE.Box3Helper(new THREE.Box3(new THREE.Vector3().fromArray(place.min),new THREE.Vector3().fromArray(place.max)),0xff2d6f)));
    this.scene.add(group);this.marker=group;
    const offset=this.camera.position.clone().sub(this.controls.target);this.controls.target.copy(at);this.camera.position.copy(at).add(offset);
    this.controls.update();this.publishCamera();this.render();
  }
  morph(name:string,value:number){this.modelDirty=true;this.model?.traverse(o=>{const m=o as THREE.Mesh,i=m.morphTargetDictionary?.[name];if(i!=null&&m.morphTargetInfluences)m.morphTargetInfluences[i]=value;});this.render();}
  play(name:string|null){this.modelDirty=true;this.mixer?.stopAllAction();if(name){const clip=this.gltf?.animations.find(c=>(c.name||'clip')===name);if(clip)this.mixer?.clipAction(clip).play();}this.anim=!!name;this.clock.getDelta();this.render();}
  async picture(id:string){if(!this.model||!this.active||this.disposed)return null;const floor=this.floor?.visible,outline=this.outline.visible,contact=this.fx.contact.group.visible;if(this.floor)this.floor.visible=false;this.outline.visible=false;this.fx.contact.group.visible=false;let result:Promise<string|null>;try{result=partPicture(this.renderer,this.scene,this.model,this.parts,id,this.grid);}finally{if(this.floor)this.floor.visible=!!floor;this.outline.visible=outline;this.fx.contact.group.visible=contact;this.render();}return result;}
  state():SavedView{return {camera:this.getCamera(),settings:this.settings,selected:this.selected?.id,isolated:this.isolated||undefined,hidden:this.parts.filter(p=>!p.visible).map(p=>p.id)};}
  dispose(){this.disposed=true;this.cancelLoad();cancelAnimationFrame(this.raf);clearTimeout(this.idleTimer);clearTimeout(this.cameraTimer);this.ro.disconnect();window.removeEventListener('keydown',this.keyDown);window.removeEventListener('keyup',this.keyUp);window.removeEventListener('blur',this.clearKeys);this.controls.dispose();this.mixer?.stopAllAction();if(this.model)this.mixer?.uncacheRoot(this.model);this.inspector?.dispose();this.disposeLive();this.fx.dispose();if(window.__viewerBench)delete window.__viewerBench;disposeObject(this.scene);this.environments.forEach(e=>e.dispose());this.renderer.dispose();this.renderer.forceContextLoss();this.renderer.domElement.remove();}
}
