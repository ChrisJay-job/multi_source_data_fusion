// Actual submitted JavaScript with DOM/canvas stubs. Not browser E2E.
const fs=require('fs'),vm=require('vm'),path=require('path');
const root=process.argv[2],runFile=process.argv[3];
const nodes={};function el(id){return nodes[id]||(nodes[id]={value:'',textContent:'',innerHTML:'',style:{},dataset:{},checked:false,classList:{add(){},remove(){},toggle(){}},addEventListener(){},querySelectorAll(){return []},querySelector(){return null},click(){}})}
const doc={getElementById:el,querySelectorAll(){return []},querySelector(){return null},addEventListener(){}};
const c={document:doc,console,setTimeout,clearTimeout,window:{},alert(){}};vm.createContext(c);
vm.runInContext(fs.readFileSync(path.join(root,'demo/workbench/canvas.js'),'utf8').replaceAll('export ','')+';globalThis.MapView=MapView;',c);
const ctx=new Proxy({},{get(t,k){return t[k]||(t[k]=()=>{})}});
const v=new c.MapView({width:1100,height:720,getContext(){return ctx},addEventListener(){}});
v._grid=()=>{};let lines=[],pts=[];v._poly=(p,col,dash)=>lines.push({n:p.length,color:col,dash});v._point=(x,y,color)=>pts.push({color});
v.state=JSON.parse(fs.readFileSync(runFile,'utf8'));v.tIndex=v.state.snapshots.length-1;v.layers={rid:false,spectrum:false,radar:false,fused:true,pred:false,current:false,truth:false,plan:false};v.draw();
const result={verification_type:'actual JS with stubs, not browser E2E',fused_only:{history_lines:lines.filter(x=>x.color==='#f72585'),history_and_current_points:pts.filter(x=>x.color==='#f72585').length,snapshots:v.state.snapshots.length}};
class DummyMap {setLayers(){} constructor(){this.tIndex=0;this.displayIndex=new Map()}}c.DummyMap=DummyMap;
let js=fs.readFileSync(path.join(root,'demo/workbench/app.js'),'utf8').replace(/^import.*\n/,'').replace('new MapView(', 'new DummyMap(').split('// Boot: list presets')[0];
vm.runInContext(js,c);
vm.runInContext(`runState={scenario:{aircraft:[]},snapshots:[{processingTime:'2026-04-09T12:00:02Z',tracks:[]}],events:[],evaluation:{entity_check:{status:'FAIL',ok:false},false_merges:[{fusionId:'F-A',truth_ids:['TRUTH-A','TRUTH-C'],at:'2026-04-09T12:00:01Z'}]}};renderResultPanels();`,c);
result.result_panel={html:el('resultSummary').innerHTML,shows_FAIL:el('resultSummary').innerHTML.includes('FAIL'),anomaly_html:el('anomalyList').innerHTML};
const active=vm.runInContext(`activeSourcesOnTrack({sources:[],sourceTracks:[{source:'radar',bindingStatus:'confirmed',lastSeen:'2026-04-09T11:00:00Z'}]})`,c);
result.expired_sources={algorithm_active:[],page_active:active};
console.log(JSON.stringify(result,null,2));
