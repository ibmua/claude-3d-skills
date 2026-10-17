import * as THREE from 'three';
import type { InspectionMode } from './viewerSettings.ts';
export type TextureRow = { id: string; usage: string; name: string; width: number; height: number; channel: number; colorSpace: string; image?: string };
export type MaterialRow = { id: string; name: string; type: string; meshes: number; roughness?: number; metalness?: number; textures: TextureRow[] };
export function inspectMaterials(model: THREE.Object3D): MaterialRow[] {
  const found = new Map<THREE.Material,number>();
  model.traverse(o=>{const m=o as THREE.Mesh;if(m.isMesh) for(const mat of Array.isArray(m.material)?m.material:[m.material])found.set(mat,(found.get(mat)||0)+1);});
  return [...found].map(([mat,meshes],index)=>{const material=mat as THREE.MeshStandardMaterial; return { id:String(index), name:mat.name||`Material ${index+1}`,type:mat.type,meshes,roughness:material.roughness,metalness:material.metalness,textures:Object.entries(mat).filter(([,v])=>(v as THREE.Texture)?.isTexture).map(([usage,value])=>{const texture=value as THREE.Texture, image=texture.image; return {id:texture.uuid,usage:usage.replace(/Map$/,'').replace(/^map$/,'base color'),name:texture.name||usage,width:image?.width||0,height:image?.height||0,channel:texture.channel,colorSpace:texture.colorSpace||'Linear / data'};}) };});
}
// Depth view range in camera space, shared by every depth material; the engine sets it per frame from the model's bounds.
export const DEPTH_RANGE = { depthNear: { value: 0 }, depthFar: { value: 1 } };
// UV checker: 8×8 coloured, labelled cells (A1…H8) with a 2×2 checker inside each, on uv0, tiled outside 0…1.
// Mirrored text = flipped UVs; uneven cell sizes = stretching or mismatched texel density.
let checker: THREE.CanvasTexture | null = null;
function checkerTexture() {
  if (checker) return checker;
  const size = 1024, cells = 8, cell = size / cells, canvas = document.createElement('canvas'); canvas.width = canvas.height = size;
  const c = canvas.getContext('2d')!; c.textAlign = 'center'; c.textBaseline = 'middle';
  for (let row = 0; row < cells; row++) for (let col = 0; col < cells; col++) {
    const hue = (col * 45 + row * 17) % 360, light = row % 2 ? 58 : 46;
    for (let q = 0; q < 4; q++) { c.fillStyle = `hsl(${hue} 62% ${q === 0 || q === 3 ? light : light + 16}%)`; c.fillRect(col * cell + (q % 2) * cell / 2, row * cell + Math.floor(q / 2) * cell / 2, cell / 2, cell / 2); }
    c.strokeStyle = 'rgba(0,0,0,.55)'; c.lineWidth = 2; c.strokeRect(col * cell + 1, row * cell + 1, cell - 2, cell - 2);
    c.fillStyle = '#fff'; c.font = `700 ${cell * .3}px system-ui, sans-serif`; c.fillText(String.fromCharCode(65 + col) + (row + 1), col * cell + cell / 2, row * cell + cell / 2);
    c.fillStyle = 'rgba(0,0,0,.6)'; c.beginPath(); c.moveTo(col * cell + 8, row * cell + 8); c.lineTo(col * cell + 26, row * cell + 8); c.lineTo(col * cell + 8, row * cell + 26); c.fill(); // corner = cell origin
  }
  checker = new THREE.CanvasTexture(canvas); checker.colorSpace = THREE.SRGBColorSpace; checker.wrapS = checker.wrapT = THREE.RepeatWrapping;
  checker.flipY = false; checker.anisotropy = 8; checker.channel = 0; checker.name = 'uv-checker'; // flipY false: read the way glTF textures are
  return checker;
}
function depthMaterial(side: THREE.Side) {
  const m = new THREE.MeshBasicMaterial({ side, toneMapped: false, fog: false });
  m.onBeforeCompile = shader => {
    Object.assign(shader.uniforms, DEPTH_RANGE);
    shader.vertexShader = 'varying float vViewDepth;\n' + shader.vertexShader.replace('#include <project_vertex>', '#include <project_vertex>\nvViewDepth = -mvPosition.z;');
    shader.fragmentShader = 'uniform float depthNear;\nuniform float depthFar;\nvarying float vViewDepth;\n' + shader.fragmentShader.replace('#include <map_fragment>', 'float depthT = clamp((vViewDepth - depthNear) / max(depthFar - depthNear, 1e-9), 0.0, 1.0);\ndiffuseColor.rgb = vec3(pow(1.0 - depthT, 2.2));');
  };
  m.customProgramCacheKey = () => 'linear-depth-v1';
  return m;
}
export class MaterialInspection {
  originals = new Map<THREE.Mesh, THREE.Material | THREE.Material[]>();
  materials: THREE.Material[] = [];
  derived = new Map<string,THREE.Material>();
  wire = false;
  constructor(public model:THREE.Object3D) { model.traverse(o=>{const m=o as THREE.Mesh;if(m.isMesh){this.originals.set(m,m.material);for(const material of Array.isArray(m.material)?m.material:[m.material])if(!this.materials.includes(material))this.materials.push(material);}}); }
  apply(mode:InspectionMode,wire:boolean) {
    this.wire=wire;
    for(const [mesh,original] of this.originals){const convert=(mat:THREE.Material)=>{if(mode==='textured'){(mat as THREE.MeshStandardMaterial).wireframe=wire;return mat;}
      const hasUV=!!mesh.geometry.attributes.uv,key=mode+':'+mat.uuid+(mode==='uv'&&!hasUV?':no-uv':'');let replacement=this.derived.get(key);
      if(!replacement){const m=mat as THREE.MeshStandardMaterial;
        if(mode==='normals')replacement=new THREE.MeshNormalMaterial({side:mat.side});
        else if(mode==='uv')replacement=new THREE.MeshBasicMaterial({map:hasUV?checkerTexture():null,color:hasUV?0xffffff:0xd02020,side:mat.side,toneMapped:false});
        else if(mode==='depth')replacement=depthMaterial(mat.side);
        else if(mode==='clay')replacement=new THREE.MeshStandardMaterial({color:0xb8b5af,roughness:.8,metalness:0,side:mat.side});
        else {const roughness=m.roughness??1;const basic=new THREE.MeshBasicMaterial({color:new THREE.Color().setRGB(roughness,roughness,roughness),map:m.roughnessMap||null,side:mat.side,toneMapped:false});
          if(m.roughnessMap) {basic.onBeforeCompile=shader=>{shader.fragmentShader=shader.fragmentShader.replace('#include <map_fragment>','#ifdef USE_MAP\nvec4 roughSample=texture2D(map,vMapUv);\ndiffuseColor.rgb *= vec3(roughSample.g);\n#endif');};basic.customProgramCacheKey=()=> 'roughness-green-v1';} replacement=basic;
        }
        this.derived.set(key,replacement);
      }
      (replacement as THREE.MeshStandardMaterial).wireframe=wire;return replacement;};mesh.material=Array.isArray(original)?original.map(convert):convert(original);}
  }
  texturePicture(materialId:string,textureId:string,full=false) {
    const material=this.materials[+materialId];const texture=Object.values(material||{}).find(v=>(v as THREE.Texture)?.uuid===textureId) as THREE.Texture|undefined;
    const source=texture?.image;if(!source?.width||!source?.height)return null;
    try{const canvas=document.createElement('canvas');const factor=full?1:Math.min(1,512/Math.max(source.width,source.height));canvas.width=Math.round(source.width*factor);canvas.height=Math.round(source.height*factor);const context=canvas.getContext('2d');if(!context)return null;context.drawImage(source,0,0,canvas.width,canvas.height);return canvas.toDataURL('image/png');}catch{return null;}
  }
  materialMeshes(id:string){const mat=this.materials[+id];return [...this.originals].filter(([,m])=>(Array.isArray(m)?m:[m]).includes(mat)).map(([mesh])=>mesh);}
  restore(){for(const [mesh,original]of this.originals)mesh.material=original;}
  dispose(){this.restore();this.derived.forEach(m=>m.dispose());this.derived.clear();}
}
