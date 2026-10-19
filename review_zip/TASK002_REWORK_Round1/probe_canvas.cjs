// Executes submitted render logic with a stub canvas. This is not a browser test.
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=process.argv[2];
const code=fs.readFileSync(path.join(root,'demo/workbench/canvas.js'),'utf8').replace('export class MapView','class MapView')+'\nglobalThis.MapView=MapView;';
const sandbox={document:{getElementById(){return {textContent:''};}}};vm.createContext(sandbox);vm.runInContext(code,sandbox);
const ctx=new Proxy({},{get(t,k){return t[k]||(t[k]=()=>{});},set(t,k,v){t[k]=v;return true;}});
const view=new sandbox.MapView({width:1100,height:720,getContext(){return ctx;},addEventListener(){}});
let polylines=[],rawPoints=0,fusedPoints=0;
view._grid=()=>{};view._points=pts=>{rawPoints+=pts.length;};view._poly=(pts,color)=>{polylines.push({n:pts.length,color});};view._point=(x,y,color,shape)=>{if(shape==='square'||shape==='diamond')fusedPoints++;};
view.state={observations:[{source:'rid',detectorId:'D',sourceTrackId:'A',measurementTime:'2026-04-09T12:00:01Z',latitude:39.13,longitude:117.2},{source:'rid',detectorId:'D',sourceTrackId:'B',measurementTime:'2026-04-09T12:00:01Z',latitude:39.13,longitude:117.21},{source:'rid',detectorId:'D',sourceTrackId:'A',measurementTime:'2026-04-09T12:00:02Z',latitude:39.13,longitude:117.2001}],snapshots:[{processingTime:'2026-04-09T12:00:01Z',tracks:[{fusionId:'F1',latitude:39.13,longitude:117.2,positionMode:'measured_assisted'}]},{processingTime:'2026-04-09T12:00:02Z',tracks:[{fusionId:'F1',latitude:39.13,longitude:117.2001,positionMode:'measured_assisted'}]}]};
view.tIndex=0;view.draw();
console.log(JSON.stringify({rendered_at_snapshot:0,visible_raw_points:rawPoints,expected_visible_raw_points:2,raw_polylines:polylines,fused_points:fusedPoints,notes:['Future raw observations are already visible','One polyline joins sourceTrack A and B','No fused historical polyline is generated; only current point'],verification_type:'render-logic execution with canvas stub, not browser E2E'},null,2));
