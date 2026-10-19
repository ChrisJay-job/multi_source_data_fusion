// Executes submitted JS with DOM/canvas stubs. Logic evidence only, not browser E2E.
const fs=require('fs'),vm=require('vm'),path=require('path');
const root=process.argv[2]||'review_task002_r2';
const nodes={};
function node(id){return nodes[id]||(nodes[id]={value:'',checked:false,textContent:'',style:{},classList:{toggle(){},add(){},remove(){}},addEventListener(){},querySelectorAll(){return []},click(){},get innerHTML(){return this.html||''},set innerHTML(v){this.html=v;if(id==='routeAcSelect'){this.value=(v.match(/value="([^"]+)"/)||[])[1]||''}}});}
const doc={getElementById:node,querySelectorAll(){return []}};
const context={document:doc,console,setTimeout,clearTimeout,alert(){},prompt(){return null},window:{}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root,'demo/workbench/canvas.js'),'utf8').replaceAll('export ','')+'\nglobalThis.MapView=MapView;',context);
const ctx=new Proxy({},{get(t,k){return t[k]||(t[k]=()=>{})}});
const cv={width:1100,height:720,getContext(){return ctx},addEventListener(){},getBoundingClientRect(){return {width:1100,height:720}}};
const view=new context.MapView(cv);view._grid=()=>{};view._poly=()=>{};view._point=()=>{};
view.setState({scenario:{aircraft:[{label:'A',truth_id:'TRUTH-A',rid_sn:'SN-A',sources:{}},{label:'B',truth_id:'TRUTH-B',rid_sn:'SN-B',sources:{}}]},snapshots:[{tracks:[]}]},{fit:false});
view.targetFilter=new Set(['A']);
const result={verification_type:'Actual JS with stub DOM/canvas, not browser E2E'};
result.only_A_truth_filter={allows_B_truth:view._allowedByFilter('truth','TRUTH-B'),allows_B_plan:view._allowedByFilter('plan','TRUTH-B'),expected:false};
view.startRouteEdit([{x_m:0,y_m:0},{x_m:10,y_m:0}],()=>{});
const [x,y]=view.worldToScreen(0,0);view._onDown({offsetX:x,offsetY:y});view._onMove({offsetX:x+30,offsetY:y+20});
view.drag=null;view.routeEdit.dragging=null; // actual mouseup handler
view._onClick({offsetX:x+30,offsetY:y+20});
result.drag_waypoint={after_drag_point_count:view.routeEdit.points.length,expected:2};
// Independent app event handlers, no auto startup.
class FakeMap {constructor(){this.tIndex=0}startRouteEdit(pts,cb){this.edited=pts}stopRouteEdit(){}setState(){}currentTimeMs(){return 0}setTargetFilter(){} }
context.FakeMap=FakeMap;
let calls=[];let loaded={field_map:{measurementTime:'ts'},source_timezone:'UTC',assume_utc_naive:false,treat_raw_id_as_aircraftId:true};
context.fetch=async(url,opts={})=>{calls.push({url,body:opts.body});return {ok:true,json:async()=>url.includes('/mapping/')?loaded:{snapshots:[],import_summary:{}}}};
let app=fs.readFileSync(path.join(root,'demo/workbench/app.js'),'utf8').replace(/^import.*\n/,'').replace('new MapView(', 'new FakeMap(').replace(/loadScenarioList\(\)\.then\([^\n]+\ninitFieldMapForm\(\);\ndocument.getElementById\("btnHealth"\)\.click\(\);/,'');
vm.runInContext(app,context);
vm.runInContext('draftScenario={aircraft:[{label:"A",waypoints:[{x_m:1,y_m:1}]},{label:"B",waypoints:[{x_m:99,y_m:99}]}]};refreshRouteAcSelect();',context);
node('routeAcSelect').value='1';node('btnRouteAdd').onclick();
result.select_B_then_draw={edited_first_x:vm.runInContext('map.edited[0].x_m',context),expected:99};
(async()=>{
node('tzMode').value='Asia/Shanghai';node('rawIdAsSn').checked=false;node('mapTemplateSelect').value='utc_template';
await node('btnLoadMap').onclick();
result.load_mapping_template={actual_tz:node('tzMode').value,expected_tz:'UTC',actual_raw_sn:node('rawIdAsSn').checked,expected_raw_sn:true};
vm.runInContext('multiQueue=[{path:"data/old.csv"}];',context);
node('fileInput').files=[{name:'new.csv'}];
await node('btnRunMulti').onclick();
const body=JSON.parse(calls.find(c=>c.url.endsWith('/run/import/multi')).body);
result.new_file_selection_after_previous_run={sent_files:body.files.map(f=>f.path),selected:'new.csv',expected:'new dataset replaces old queue or explicit editable queue'};
console.log(JSON.stringify(result,null,2));
})().catch(e=>{console.error(e);process.exitCode=1});
