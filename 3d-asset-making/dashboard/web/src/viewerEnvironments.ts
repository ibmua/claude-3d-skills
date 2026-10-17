import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { disposeObject } from './viewerMetrics.ts';
export function makeEnvironment(renderer:THREE.WebGLRenderer,id:string) {
  const pmrem=new THREE.PMREMGenerator(renderer);
  try{
    if(id==='studio'){const room=new RoomEnvironment();try{return pmrem.fromScene(room,.04);}finally{disposeObject(room);}}
    const canvas=document.createElement('canvas');canvas.width=1024;canvas.height=512;
    const ctx=canvas.getContext('2d')!;const gradient=ctx.createLinearGradient(0,0,0,512);
    const stops=id==='sunset'?[[0,'#1d355d'],[.42,'#c3948a'],[.5,'#ffe0b0'],[.58,'#8b7770'],[1,'#363238']]:[[0,'#93aac4'],[.42,'#e6edf4'],[.5,'#f7f7f4'],[.58,'#9ba39f'],[1,'#454e4e']];
    for(const [position,color]of stops)gradient.addColorStop(position as number,color as string);ctx.fillStyle=gradient;ctx.fillRect(0,0,1024,512);
    const glow=ctx.createRadialGradient(300,190,0,300,190,id==='sunset'?65:180);glow.addColorStop(0,id==='sunset'?'#fff4d6':'#ffffff');glow.addColorStop(1,'#ffffff00');ctx.fillStyle=glow;ctx.fillRect(0,0,1024,512);
    const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;texture.mapping=THREE.EquirectangularReflectionMapping;
    try{return pmrem.fromEquirectangular(texture);}finally{texture.dispose();}
  }finally{pmrem.dispose();}
}
