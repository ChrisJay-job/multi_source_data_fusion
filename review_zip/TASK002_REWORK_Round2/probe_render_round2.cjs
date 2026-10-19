// Render-logic probes only; no browser E2E claim.
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const script=fs.readFileSync(path.join(process.argv[2],'demo/workbench/canvas.js'),'utf8').replace('export class MapView','class MapView')+'\nglobalThis.MapView=MapView';
const context={document:{getElementById(){return {textContent:''}}}};vm.createContext(context);vm.runInContext(script,context);
const ctx=new Proxy({},{get(t,k){return t[k]||(t[k]=()=>{})},set(t,k,v){t[k]=v;return true}});
const v=new context.MapView({width:1100,height:720,getContext(){return ctx},addEventListener(){}});v._grid=()=>{};
let polylines=[],points=[];v._poly=(pts,color,dashed)=>polylines.push({n:pts.length,color,dashed});v._point=(x,y,color,shape)=>points.push({color,shape});v._points=()=>{};
const track=(n,mode)=>({fusionId:'F-A',aircraftId:'SN-A-001',latitude:39.13,longitude:117.2+n*.0001,positionMode:mode,speed:10,heading:90});
v.state={snapshots:[{processingTime:'2026-04-09T12:00:00Z',tracks:[track(0,'measured_assisted')]},{processingTime:'2026-04-09T12:00:01Z',tracks:[track(1,'predicted')]},{processingTime:'2026-04-09T12:00:02Z',tracks:[track(2,'predicted')]}]};v.tIndex=2;
v.targetFilter=new Set(['A']);v.draw();const target={selected:'A',fused_points:points.length,fused_history_lines:polylines.filter(x=>x.color==='#f72585').length,expected_points:1};
polylines=[];points=[];v.targetFilter=null;v.layers.pred=false;v.draw();const hidden={prediction_checkbox:false,solid_history_segments:polylines.filter(x=>x.color==='#f72585'),expected_predicted_positions_in_solid_history:0};
console.log(JSON.stringify({only_A_filter:target,hide_prediction_history:hidden,verification_type:'Node execution of actual canvas module with stub canvas, not browser'},null,2));
