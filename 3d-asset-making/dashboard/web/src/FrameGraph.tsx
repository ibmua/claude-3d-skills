export default function FrameGraph({values}:{values:number[]}){
  if(!values.length)return <p className="inspector-note">Move the model to sample frame intervals.</p>;
  const max=Math.max(50,...values),y=(n:number)=>38-Math.min(n,max)/max*35;
  const points=values.map((v,i)=>`${i/Math.max(values.length-1,1)*280},${y(v)}`).join(' ');
  return <figure className="frame-graph" title="Guides: 16.7 ms (60 fps) and 33.3 ms (30 fps). CPU frame intervals, including browser scheduling; GPU time is not measured."><svg viewBox="0 0 280 42" role="img" aria-label={`Last ${values.length} frame intervals, latest ${values.at(-1)!.toFixed(1)} milliseconds`}><path d={`M0 ${y(16.7)}H280 M0 ${y(33.3)}H280`} className="frame-guides"/><polyline points={points}/></svg><figcaption><span>Frame intervals · last {values.length}</span><span>{values.at(-1)!.toFixed(1)} ms</span></figcaption></figure>;
}
