"""Remaining end-to-end workbench behaviours; synthetic data only."""
import pytest
from fusion_mvp.api import _default_mapping
from fusion_mvp.workbench.importer import import_sql_stream
from fusion_mvp.workbench.runner import WorkbenchRunner
from fusion_mvp.workbench.evaluator import evaluate_run


def item(oid,t):
 return dict(observationId=oid,source='rid',detectorId='D',sourceTrackId='R',aircraftId='SN',measurementTime=f'2026-04-09T12:00:{t:02d}+00:00',receivedAt=f'2026-04-09T12:00:{t:02d}+00:00',timeBasis='measurement',longitude=117.2,latitude=39.13,altitude=None,altitudeDatum='unknown',speed=None,heading=None,verticalSpeed=None,qualityFlags=[])


def test_actual_sql_works_with_the_pages_default_mapping(tmp_path):
 path=tmp_path/'flight.sql'
 path.write_text('INSERT INTO "public"."aircraft_flight_data" VALUES (\'SN\',117.2,39.13,40,8,90,\'2026-04-09 12:00:01\',\'tj-rid\',NULL,\'tcp\',\'D\',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);\n')
 mapping=_default_mapping({'source_timezone':'Asia/Shanghai'})
 result=import_sql_stream(path,mapping,max_rows=10)
 assert result['n_observations']==1,result


def test_realtime_empty_ticks_are_included_in_processing_counts():
 result=WorkbenchRunner().run_batch_replay([item('a',0),item('b',10)],mode='realtime',time_step_s=1)
 assert result['counts']['delivered']==2
 assert result['counts']['pending_buffer']==0
 assert result['counts']['rejected']==0
 assert result['counts']['processed_updates']==2,result['counts']


def fixtures():
 rows=[dict(observationId='ra',source='rid',detectorId='D',sourceTrackId='RA',aircraftId='SN-A'),dict(observationId='rb',source='radar',detectorId='D',sourceTrackId='RB',aircraftId=None)]
 truths={'ra':'TRUTH-A','rb':'TRUTH-B'}
 own=dict(source='rid',detectorId='D',sourceTrackId='RA',aircraftId='SN-A')
 foreign=dict(source='radar',detectorId='D',sourceTrackId='RB',aircraftId=None)
 good=dict(fusionId='F-A',aircraftId='SN-A',sourceTracks=[own],sources=['rid'])
 bad={**good,'sourceTracks':[own,foreign],'sources':['rid','radar']}
 return rows,truths,good,bad


def test_wrong_midflight_binding_is_not_erased_by_final_recovery():
 rows,truths,good,bad=fixtures()
 r=evaluate_run(snapshots_by_time=[{'processingTime':'2026-04-09T12:00:01Z','tracks':[bad]},{'processingTime':'2026-04-09T12:00:02Z','tracks':[good]}],obs_truth_map=truths,delivered_obs=rows,rejected=[],events=[],expected_stable_entities={'TRUTH-A':{'rid'}})
 assert r['false_merges'] or r['attribution_errors'] or not r['entity_check']['ok']


def test_duplicate_entity_cannot_have_entity_check_pass():
 rows,truths,good,bad=fixtures()
 clone={**good,'fusionId':'F-A2'}
 r=evaluate_run(snapshots_by_time=[{'tracks':[good,clone]}],obs_truth_map=truths,delivered_obs=rows,rejected=[],events=[],expected_stable_entities={'TRUTH-A':{'rid'}})
 assert r['duplicate_targets']
 assert not r['entity_check']['ok']
