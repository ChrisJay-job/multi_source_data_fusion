"""Instrument the supplied continuous segment without copying private observations into results."""
import json,sys,hashlib,platform,importlib.metadata as md
from pathlib import Path
from datetime import timedelta
from collections import Counter
root=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve()
mode=sys.argv[3] if len(sys.argv)>3 else 'realtime'
sys.path.insert(0,str(root/'src'))
from fusion_mvp.engine import FusionSession,load_config
from fusion_mvp.mapping import parse_dt,iso
rows=[json.loads(line)['standard'] for line in (root/'samples/continuous/segment.jsonl').read_text().splitlines() if '"standard"' in line]
s=FusionSession('independent-continuous',load_config());counts=Counter();events=Counter();deltas=Counter()
archive=root.parent/'upload/TASK-001-attempt-001-rework-round1-review-bundle.zip'
original=s._apply_update

def counted(tr,obs,t,primary_forced,is_birth=False):
 before=tr.hits
 ev=original(tr,obs,t,primary_forced,is_birth)
 counts['apply_calls']+=1
 if tr.hits>before:counts['position_updates']+=1
 events.update(x.type for x in ev)
 return ev
s._apply_update=counted
response_events=Counter()
for i,row in enumerate(rows):
 r=s.process(str(i),row['measurementTime'],[row],mode)
 response_events.update(e.type for e in r.events)
 counts['explicit_rejections']+=len(r.rejected)
 counts['request_errors']+=int(r.error is not None)
last=parse_dt(rows[-1]['measurementTime'])[0]
buffer_before=len(s.buffer)
r=s.process('flush',iso(last+timedelta(seconds=3)),[],mode)
response_events.update(e.type for e in r.events)
ids=[row['observationId'] for row in rows]
result={'mode':mode,'input_rows':len(rows),'unique_observation_ids':len(set(ids)),'counts':dict(counts),'events':dict(response_events),'buffer_before_final_flush':buffer_before,'buffer_after_final_flush':len(s.buffer),'stored_seen_ids':len(s.seen_obs),'final_total_hits':sum(t.hits for t in s.tracks.values()),'input_times_nondecreasing':all(rows[i]['measurementTime']<=rows[i+1]['measurementTime'] for i in range(len(rows)-1)),'source_archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest() if archive.exists() else None,'python':platform.python_version(),'versions':{n:md.version(n) for n in ['numpy','scipy','pyproj','pydantic','pytest','fastapi','httpx']}}
out.write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result,indent=2))
