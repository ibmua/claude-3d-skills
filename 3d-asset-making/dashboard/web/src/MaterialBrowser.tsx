import { useEffect, useState } from 'react';
import type { MaterialRow } from './materialInspection.ts';
function TexturePicture({ material, texture, capture }: { material:string; texture:MaterialRow['textures'][number]; capture:(material:string,texture:string,full?:boolean)=>string|null }) {
  const [image,setImage]=useState<string|null>(null),[original,setOriginal]=useState<string|null>(null),[notice,setNotice]=useState('');
  useEffect(()=>{setImage(capture(material,texture.id));setOriginal(null);},[material,texture.id,capture]);
  useEffect(()=>()=>{if(original)URL.revokeObjectURL(original);},[original]);
  const prepare=async()=>{if(original)return;const data=capture(material,texture.id,true);if(!data){setNotice('This texture cannot be exported by the browser.');return;}try{setOriginal(URL.createObjectURL(await(await fetch(data)).blob()));}catch{setNotice('Texture preview unavailable.');}};
  return <div className="texture-card">{image?<img src={image} alt={`${texture.usage} texture`} />:<span className="inspector-note">Preview unavailable for this texture format</span>}<div><strong>{texture.usage}</strong><small>{texture.width} × {texture.height} · UV {texture.channel}<br />{texture.colorSpace}</small>{original?<a href={original} target="_blank" rel="noopener noreferrer">↗ Open texture</a>:<button onClick={prepare}>Prepare full texture ↗</button>}{notice&&<small role="status">{notice}</small>}</div></div>;
}
export default function MaterialBrowser({materials,revision,capture,onHighlight}:{materials:MaterialRow[];revision:string;capture:(material:string,texture:string,full?:boolean)=>string|null;onHighlight:(id:string|null)=>void}){
  const [expanded,setExpanded]=useState(false),[id,setId]=useState(materials[0]?.id||'');
  const material=materials.find(m=>m.id===id)||materials[0];
  useEffect(()=>{setId(materials[0]?.id||'');},[revision]);
  return <details className="materials-details" onToggle={e=>{setExpanded(e.currentTarget.open);if(!e.currentTarget.open)onHighlight(null);}}><summary>Materials &amp; textures <span>{materials.length}</span></summary>
    <label className="quality-control">Material<select aria-label="Material" value={material?.id||''} onChange={e=>{setId(e.target.value);onHighlight(e.target.value);}}>{materials.map(m=><option value={m.id} key={m.id}>{m.name}</option>)}</select></label>
    {material&&<><p className="inspector-note">{material.type} · {material.meshes} mesh{material.meshes===1?'':'es'}{material.roughness!=null&&<> · roughness {material.roughness.toFixed(2)}</>}{material.metalness!=null&&<> · metalness {material.metalness.toFixed(2)}</>}</p><button onClick={()=>onHighlight(material.id)}>⌖ Highlight uses</button>{expanded&&material.textures.map(t=><TexturePicture key={`${revision}:${material.id}:${t.id}:${t.usage}`} material={material.id} texture={t} capture={capture}/>)}{!material.textures.length&&<p className="inspector-note">No image textures; this material uses surface values.</p>}</>}
  </details>;
}
