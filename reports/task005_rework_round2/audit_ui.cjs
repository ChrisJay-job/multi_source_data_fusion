// Source-level VM probe of real app.js functions, not browser E2E.
const fs=require('fs'),vm=require('vm'),path=require('path');
const root=process.argv[2];if(!root)throw Error('project path required');
const src=fs.readFileSync(path.join(root,'demo/workbench/app.js'),'utf8').replace(/\r/g,'');
function fn(name){const i=src.indexOf('function '+name+'('),j=src.indexOf('\n}\n',i);if(i<0||j<0)throw Error(name);return src.slice(i,j+2)}
const boxes=new Map();const document={getElementById:id=>{if(!boxes.has(id))boxes.set(id,{textContent:'',innerHTML:''});return boxes.get(id)}};
const ctx={document,map:{tIndex:0,targetFilter:null},runState:{snapshots:[{processingTime:'2026-04-09T12:00:00Z',watermark:'2026-04-09T11:59:58Z',tracks:[]}],events:[]},pinnedDetail:{fusionId:'PREVIOUS_RUN_TARGET'},countsUpTo:()=>({source:'snapshot.counts_at',delivered_at_t:1,binds_at_t:0,pending_buffer:1,rejected_at_t:0,run_total_updates:0}),parseT:x=>x?Date.parse(x):0,renderResultPanels:()=>{},renderExplainAssoc:()=>{},renderInspector:()=>{throw Error('no target should be rendered')}};
document.getElementById('inspector').innerHTML='OLD_RUN_A_TARGET';document.getElementById('explainAssoc').innerHTML='OLD_RUN_A_EXPLANATION';
vm.createContext(ctx);vm.runInContext(fn('updateTransport')+'\n'+fn('updateNearDist'),ctx);ctx.updateTransport();
ctx.updateNearDist({min_truth_distance_m:0,min_truth_distance_pair:['H','I'],min_truth_distance_at_s:14},['J','K']);
console.log(JSON.stringify({test_type:'actual product functions in VM, not E2E',empty_snapshot_leaves_old_inspector:document.getElementById('inspector').innerHTML==='OLD_RUN_A_TARGET',empty_snapshot_leaves_old_explanation:document.getElementById('explainAssoc').innerHTML==='OLD_RUN_A_EXPLANATION',detail:document.getElementById('detail').textContent,counts:document.getElementById('counts').textContent,near_distance_with_JK_selected:document.getElementById('nearDist').textContent},null,2));
