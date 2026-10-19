// Actual canvas.js logic with stub canvas; not browser E2E.
const fs=require('fs'),vm=require('vm'),path=require('path');
const root=process.argv[2];const c={document:{getElementById(){return {textContent:''}}}};vm.createContext(c);
vm.runInContext(fs.readFileSync(path.join(root,'demo/workbench/canvas.js'),'utf8').replaceAll('export ','')+';globalThis.MapView=MapView;',c);
const ctx=new Proxy({},{get(t,k){return t[k]||(t[k]=()=>{})}});const v=new c.MapView({width:1100,height:720,getContext(){return ctx},addEventListener(){}});
v._grid=()=>{};let lines=[],points=[];v._poly=(pts,color,dashed)=>lines.push({n:pts.length,color,dashed});v._point=(x,y,color)=>points.push({color});
function t(i){return '2026-04-09T12:00:'+String(i).padStart(2,'0')+'Z'}
const commits=[0,1].map(i=>({fusionId:'F',trackSegmentId:'S1',stateTime:t(i),east_m:i*10,north_m:0,latitude:39.13,longitude:117.2+i*.0001}));
function track(i){return {fusionId:'F',trackSegmentId:'S1',latitude:39.13,longitude:117.2+i*.0001,stateTime:t(1),displayStateTime:t(i),positionMode:'predicted',committedHistory:commits}}
v.state={snapshots:[1,2,3,4,5,6].map(i=>({processingTime:t(i),tracks:[{...track(i),positionMode:(i===3||i===4)?'measured':'predicted'}]}))};v.tIndex=5;
v.layers={rid:false,spectrum:false,radar:false,truth:false,plan:false,fused:false,current:false,pred:true};v.draw();
const drawn=lines.filter(x=>x.color==='#ff6b6b'&&x.dashed);
console.log(JSON.stringify({verification_type:'actual canvas JS with stubs, not browser',expected:'two separate prediction episodes (1-2s and 5-6s), measured at 3-4s',actual:drawn},null,2));
if(drawn.length!==2||drawn.some(x=>x.n!==2))process.exitCode=1;
