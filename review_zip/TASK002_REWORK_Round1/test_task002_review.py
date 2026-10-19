"""Independent Task002 regression probes; no private data required."""
import csv,io,json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from fusion_mvp.api import app,ROOT
from fusion_mvp.workbench.importer import MappingTemplate,iter_sql_inserts,row_to_observation
from fusion_mvp.workbench.evaluator import evaluate_run
from fusion_mvp.workbench.scenario import preset_three_aircraft,generate_observations


def mapping():
 return MappingTemplate(field_map={k:k for k in ['observationId','source','detectorId','sourceTrackId','aircraftId','measurementTime','longitude','latitude']},source_timezone='Asia/Shanghai')
def record(i):
 return dict(observationId=f'o{i}',source='rid',detectorId='D',sourceTrackId='R',aircraftId='SN',measurementTime=f'2026-04-09T12:00:0{i}+00:00',longitude=117.2,latitude=39.13)


@pytest.mark.parametrize('sql',[
 'INSERT INTO "public"."aircraft_flight_data" VALUES (\'A\',117.2,39.13,40,8,90,\'2026-04-09 12:00:01\',\'tj-rid\',NULL,\'tcp\',\'D\',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);\n',
 'INSERT INTO "public"."aircraft_flight_data" ("id","longitude","latitude") VALUES (\'A\',117.2,39.13);\n'])
def test_sql_recognizes_actual_dump_and_column_list(tmp_path,sql):
 p=tmp_path/'input.sql';p.write_text(sql)
 assert len(list(iter_sql_inserts(p)))==1


def test_explicit_named_timezone_is_applied():
 r=record(1);r['measurementTime']='2026-04-09 12:00:01'
 out,error=row_to_observation(r,mapping(),1)
 assert error is None
 from datetime import datetime,timezone
 assert datetime.fromisoformat(out['measurementTime']).astimezone(timezone.utc).hour==4


def upload_then_run():
 rows=[record(i) for i in [1,2,3]];s=io.StringIO();w=csv.DictWriter(s,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 client=TestClient(app)
 response=client.post('/v1/workbench/import/preview',files={'file':('review.csv',s.getvalue().encode(),'text/csv')},data={'max_rows':'2','mapping_json':json.dumps(mapping().to_dict())})
 assert response.status_code==200,response.text
 data=response.json();assert data['n_observations']==2
 try:
  r=client.post('/v1/workbench/run/import',json={'path':data['stored_as'],'maxRows':3,'mapping':mapping().to_dict(),'mode':'replay'})
  assert r.status_code==200,r.text
  return r.json()
 finally:
  p=ROOT/data['stored_as'];p.unlink(missing_ok=True);Path(str(p)+'.obs.json').unlink(missing_ok=True)


def test_preview_limit_is_not_actual_replay_dataset():
 result=upload_then_run()
 assert result['n_observations']==3,'Preview of two rows must not silently replace a three-row run'


def test_real_import_response_provides_raw_tracks_for_existing_canvas():
 result=upload_then_run()
 assert result.get('observations'),'Current frontend requires observations to draw source layers'


def test_evaluator_catches_wrong_radar_truth_binding():
 delivered=[];truth={};tracks=[]
 expected={'TRUTH-A':{'rid'},'TRUTH-B':{'spectrum'},'TRUTH-C':{'rid','spectrum','radar'}}
 for i,(label,src) in enumerate([('A','rid'),('B','spectrum'),('C','rid')]):
  sn='SN-'+label;oid='o-'+label
  delivered.append(dict(observationId=oid,aircraftId=sn,source=src,detectorId='D',sourceTrackId=sn))
  truth[oid]='TRUTH-'+label
  tracks.append(dict(fusionId='F-'+label,aircraftId=sn,sources=[src],sourceTracks=[dict(source=src,detectorId='D',sourceTrackId=sn,aircraftId=sn)]))
 delivered.extend([dict(observationId='spc',aircraftId='SN-C',source='spectrum',detectorId='D',sourceTrackId='SN-C'),dict(observationId='ra',aircraftId=None,source='radar',detectorId='D',sourceTrackId='RADAR-A')])
 truth.update({'spc':'TRUTH-C','ra':'TRUTH-A'})
 tracks[2]['sourceTracks'].extend([dict(source='spectrum',detectorId='D',sourceTrackId='SN-C',aircraftId='SN-C'),dict(source='radar',detectorId='D',sourceTrackId='RADAR-A',aircraftId=None)])
 result=evaluate_run(snapshots_by_time=[{'tracks':tracks}],obs_truth_map=truth,delivered_obs=delivered,rejected=[],events=[],expected_stable_entities=expected)
 assert result['false_merges'] or not result['entity_check']['ok'],'Radar-A falsely bound to C must fail evaluation'


def test_reorder_models_arrival_not_false_measurement_time():
 sc=preset_three_aircraft();sc.aircraft=sc.aircraft[:1];sc.duration_s=3
 for cfg in sc.aircraft[0].sources.values():cfg.reorder_window_s=1;cfg.pos_noise_m=0
 data=generate_observations(sc)
 from datetime import datetime
 t0=datetime.fromisoformat(data['t0'])
 for o in data['observations']:
  dt=(datetime.fromisoformat(o['measurementTime'])-t0).total_seconds()
  assert dt>=0 and abs(dt-round(dt))<1e-8,'Changing arrival order must not falsify measurement timestamps'
