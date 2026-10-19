import json
from fusion_mvp.workbench.evaluator import evaluate_run


def test_reused_key_uses_bound_observation_time_not_future_processing_time():
    rows=[dict(observationId='ra',source='rid',detectorId='D',sourceTrackId='RA',aircraftId='SN-A',measurementTime='2026-04-09T12:00:01Z'),
          dict(observationId='a',source='radar',detectorId='D',sourceTrackId='R',aircraftId=None,measurementTime='2026-04-09T12:00:01Z'),
          dict(observationId='b',source='radar',detectorId='D',sourceTrackId='R',aircraftId=None,measurementTime='2026-04-09T12:00:03Z')]
    tr=dict(fusionId='FA',aircraftId='SN-A',sourceTracks=[
        dict(source='rid',detectorId='D',sourceTrackId='RA',aircraftId='SN-A',lastSeen='2026-04-09T12:00:01Z'),
        dict(source='radar',detectorId='D',sourceTrackId='R',aircraftId=None,lastSeen='2026-04-09T12:00:01Z')])
    r=evaluate_run(snapshots_by_time=[dict(processingTime='2026-04-09T12:00:04Z',watermark='2026-04-09T12:00:02Z',tracks=[tr])],
        delivered_obs=rows,obs_truth_map={'ra':'TRUTH-A','a':'TRUTH-A','b':'TRUTH-B'},rejected=[],events=[])
    assert not r['false_merges'] and not r['attribution_errors'],r


def test_primary_scenario_runner_supplies_stable_window(monkeypatch):
    import fusion_mvp.workbench.runner as mod
    from fusion_mvp.workbench.scenario import generate_observations,preset_three_aircraft
    original=mod.evaluate_run
    calls=[]
    def spy(**kw):
        calls.append(kw.get('stable_window'))
        return original(**kw)
    monkeypatch.setattr(mod,'evaluate_run',spy)
    mod.WorkbenchRunner().run_scenario_bundle(generate_observations(preset_three_aircraft()),mode='realtime')
    assert calls and calls[0] is not None, 'primary page run never enables stable-window check'


def test_time_window_limit_applies_after_filtering(tmp_path,monkeypatch):
    import fusion_mvp.api as api
    monkeypatch.setattr(api,'ROOT',tmp_path)
    data=tmp_path/'data';data.mkdir()
    rows=[dict(observationId=f'o{i}',source='rid',sourceTrackId='R',detectorId='D',aircraftId='SN-A',
               measurementTime=f'2026-04-09T12:00:0{i}Z',longitude=117.2,latitude=39.13) for i in (1,2,3)]
    p=data/'window.jsonl';p.write_text('\n'.join(json.dumps(r) for r in rows))
    result=api.run_import(api.ImportRunRequest(path='data/window.jsonl',maxRows=1,
        timeFrom='2026-04-09T12:00:03+00:00',timeTo='2026-04-09T12:00:04+00:00'))
    assert result['n_observations']==1,result


def test_sql_error_collector_has_bounded_samples(tmp_path,monkeypatch):
    import fusion_mvp.workbench.importer as mod
    p=tmp_path/'bad.sql'
    p.write_text('INSERT INTO "public"."aircraft_flight_data" VALUES (1,2,3);\n'*100)
    original=mod._summarize
    retained=[]
    def spy(observations,errors,preview,path):
        retained.append(len(errors))
        return original(observations,errors,preview,path)
    monkeypatch.setattr(mod,'_summarize',spy)
    result=mod.import_sql_stream(p,mod.MappingTemplate(),max_rows=1)
    assert retained and retained[0]<=20, f'retained {retained} errors in memory instead of bounded samples'
    assert result['n_errors']==100,result
