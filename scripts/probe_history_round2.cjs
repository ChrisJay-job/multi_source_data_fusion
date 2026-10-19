// Actual canvas.js logic with stub canvas; not browser E2E.
const fs=require('fs'),vm=require('vm'),path=require('path');
const root=process.argv[2];const c={document:{getElementById(){return {textContent:''}}}};vm.createContext(c);
vm.runInContext(fs.readFileSync(path.join(root,'demo/workbench/canvas.js'),'utf8').replaceAll('export ','')+';globalThis.MapView=MapView;',c);
const ctx=new Proxy({},{get(t,k){return t[k]||(t[k]=()=>{})}});const v=new c.MapView({width:1100,height:720,getContext(){return ctx},addEventListener(){}});
v._grid=()=>{};let lines=[],points=[];v._poly=(pts,color,dashed)=>lines.push({n:pts.length,color,dashed});v._point=(x,y,color)=>points.push({color});
function t(i){return '2026-04-09T12:00:'+String(i).padStart(2,'0')+'Z'}
const commits=[0,1].map(i=>({fusionId:'F',trackSegmentId:'S1',stateTime:t(i),east_m:i*10,north_m:0,latitude:39.13,longitude:117.2+i*.0001}));
function track(i){return {fusionId:'F',trackSegmentId:'S1',latitude:39.13,longitude:117.2+i*.0001,stateTime:t(1),displayStateTime:t(i),positionMode:'predicted',committedHistory:commits}}
v.state={snapshots:[{processingTime:t(1),tracks:[track(1)]},{processingTime:t(2),tracks:[track(2)]},{processingTime:t(3),tracks:[track(3)]},{processingTime:t(4),tracks:[track(4)]}]};v.tIndex=3;
v.layers={rid:false,spectrum:false,radar:false,truth:false,plan:false,fused:false,current:false,pred:true};v.draw();
const pred={expected:'actual predicted history polyline with dashed styling',line_count:lines.filter(x=>x.color==='#ff6b6b'&&x.dashed).length,points:points.length};
lines=[];points=[];v.layers.pred=false;v.layers.fused=true;v.state.snapshots.push({processingTime:t(40),tracks:[]});v.tIndex=4;v.draw();
const expired={expected:'previous committed historical line remains after target termination',line_count:lines.filter(x=>x.color==='#f72585').length};
console.log(JSON.stringify({verification_type:'actual JS with stubs, not browser',prediction_history:pred,terminated_history:expired},null,2));
if(pred.line_count<1||expired.line_count<1)process.exitCode=1;
