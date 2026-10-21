// Source-level probe of actual product functions; not a browser acceptance test.
const fs=require('fs'),vm=require('vm'),path=require('path');
const root=process.argv[2]||'review_task005_e373';
const source=fs.readFileSync(path.join(root,'demo/workbench/app.js'),'utf8').replace(/\r/g,'');
function fn(name){const i=source.indexOf('function '+name+'(');const j=source.indexOf('\n}\n',i);if(i<0||j<0)throw Error(name);return source.slice(i,j+2);}
const boxes=new Map();const document={getElementById:id=>{if(!boxes.has(id))boxes.set(id,{innerHTML:'',textContent:''});return boxes.get(id)}};
const ctx={document,SRC_LABEL:{rid:'RID',radar:'雷达'},runState:{scenario:{name:'challenge_simultaneous_cross_anon'},events:[{fusionId:'F1',type:'future_event_at_t20',time:'2026-04-09T12:00:20Z'}],rejected:[{observationId:'OTHER_TARGET',reason:'OTHER_TARGET_REJECTION'}],evaluation:{entity_check:{status:'FAIL'}}},primaryPositionSource:()=> 'rid',evalVerdict:ev=>ev.entity_check.status};
ctx.map={tIndex:0};ctx.runState.snapshots=[{processingTime:'2026-04-09T12:00:05Z',watermark:'2026-04-09T12:00:03Z'}];
vm.createContext(ctx);vm.runInContext(['emptyField','fmtObsField','renderExplainAssoc','renderInspector'].map(fn).join('\n'),ctx);
ctx.renderExplainAssoc({fusionId:'F1'},'track');
const trackHTML=document.getElementById('explainAssoc').innerHTML;
document.getElementById('explainAssoc').innerHTML='PREVIOUS_TARGET_EXPLANATION';
ctx.renderInspector({source:'radar',observationId:'NEW_OBS',sourceTrackId:'T123'},'obs');
const evidence={
 test_type:'source-level VM probe, not browser E2E',
 future_event_in_current_explanation:trackHTML.includes('future_event_at_t20'),
 unrelated_target_rejection_in_explanation:trackHTML.includes('OTHER_TARGET_REJECTION'),
 observation_click_leaves_previous_explanation:document.getElementById('explainAssoc').innerHTML==='PREVIOUS_TARGET_EXPLANATION',
 metric_breakdown_used_in_UI:source.includes('metrics_display'),
 trackHTML,
 browser_evidence_limit:'Submitted Playwright switches scenario but waits only for any existing snapshots; does not await matching new run, and does not reimport download.'
};
console.log(JSON.stringify(evidence,null,2));
