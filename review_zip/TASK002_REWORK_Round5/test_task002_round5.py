import json
import pytest

@pytest.fixture
def dataset(tmp_path,monkeypatch):
    import fusion_mvp.api as api
    monkeypatch.setattr(api,'UPLOAD_DIR',tmp_path)
    rows=[dict(observationId=f'o{i}',source='rid',sourceTrackId='R',detectorId=det,aircraftId='SN',measurementTime=f'2026-04-09T12:00:0{i}Z',longitude=lon,latitude=39.13) for i,det,lon in [(1,'D1',117.1),(2,'D2',117.3),(3,'D2',117.4)]]
    (tmp_path/'rows.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
    return api

def test_detector_filter_precedes_page_limit(dataset):
    r=dataset.dataset_observations('rows.jsonl',offset=0,limit=1,detectorId='D2')
    assert r['n']==1 and r['observations'][0]['observationId']=='o2',r

def test_region_filter_precedes_page_limit(dataset):
    r=dataset.dataset_observations('rows.jsonl',offset=0,limit=1,lonMin=117.2)
    assert r['n']==1 and r['observations'][0]['observationId']=='o2',r

def test_offset_is_skipped_without_materializing_prefix(dataset,monkeypatch):
    original=dataset._load_observations
    held=[]
    def spy(*a,**kw):
        r=original(*a,**kw)
        held.append(len(r.get('observations') or []))
        return r
    monkeypatch.setattr(dataset,'_load_observations',spy)
    r=dataset.dataset_observations('rows.jsonl',offset=2,limit=1)
    assert r['n']==1,r
    assert not held or max(held)<=1,f'page size 1, materialized {held} rows including skipped prefix'

def test_same_time_reused_key_is_not_definite_pass():
    from fusion_mvp.workbench.evaluator import evaluate_run
    t='2026-04-09T12:00:01Z'
    rows=[dict(observationId='a',source='radar',detectorId='D',sourceTrackId='R',aircraftId=None,measurementTime=t),
          dict(observationId='b',source='radar',detectorId='D',sourceTrackId='R',aircraftId=None,measurementTime=t),
          dict(observationId='ridb',source='rid',detectorId='D',sourceTrackId='RB',aircraftId='SN-B',measurementTime=t)]
    tr=dict(fusionId='F-B',aircraftId='SN-B',sources=['rid','radar'],sourceTracks=[
        dict(source='radar',detectorId='D',sourceTrackId='R',aircraftId=None,lastSeen=t),
        dict(source='rid',detectorId='D',sourceTrackId='RB',aircraftId='SN-B',lastSeen=t)])
    r=evaluate_run(snapshots_by_time=[dict(processingTime=t,watermark=t,tracks=[tr])],delivered_obs=rows,
        obs_truth_map={'a':'TRUTH-A','b':'TRUTH-B','ridb':'TRUTH-B'},events=[],rejected=[],expected_stable_entities={'TRUTH-B':{'rid','radar'}})
    assert r['entity_check']['status']!='PASS',r

def test_formal_replay_respects_device_filter(dataset,monkeypatch):
    monkeypatch.setattr(dataset,'ROOT',dataset.UPLOAD_DIR)
    req=dataset.ImportRunRequest(path='rows.jsonl',maxRows=10,detectorId='D2')
    r=dataset.run_import(req)
    assert r['n_observations']==2 and all(o['detectorId']=='D2' for o in r['observations']),r['n_observations']
