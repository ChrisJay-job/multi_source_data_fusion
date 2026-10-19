from fusion_mvp.workbench.evaluator import evaluate_run

def ev(snaps, rows, truth, expected=None, window=None):
    return evaluate_run(snapshots_by_time=snaps, delivered_obs=rows, obs_truth_map=truth,
                        rejected=[], events=[], expected_stable_entities=expected, stable_window=window)

def track(sn, key='R', source='rid', fid='F'):
    return dict(fusionId=fid, aircraftId=sn, sources=[source], sourceTracks=[dict(source=source,detectorId='D',sourceTrackId=key,aircraftId=sn)])

def test_stable_window_checks_missing_entity_in_middle():
    rows=[dict(observationId='a',source='rid',detectorId='D',sourceTrackId='R',aircraftId='SN-A')]
    snaps=[dict(processingTime=f'2026-04-09T12:00:0{i}Z',tracks=([track('SN-A')] if i!=2 else [])) for i in (1,2,3)]
    r=ev(snaps,rows,{'a':'TRUTH-A'},{'TRUTH-A':{'rid'}},('2026-04-09T12:00:01Z','2026-04-09T12:00:03Z'))
    assert not r['entity_check']['ok'],r

def test_time_separated_radar_key_reuse_is_not_false_merge():
    rows=[dict(observationId='a',source='radar',detectorId='D',sourceTrackId='R',aircraftId=None,measurementTime='2026-04-09T12:00:01Z'),
          dict(observationId='b',source='radar',detectorId='D',sourceTrackId='R',aircraftId=None,measurementTime='2026-04-09T12:10:01Z')]
    a=track(None,source='radar',fid='F-A'); a.update(trackSegmentId='1')
    b=track(None,source='radar',fid='F-B'); b.update(trackSegmentId='2')
    snaps=[dict(processingTime='2026-04-09T12:00:01Z',tracks=[a]),dict(processingTime='2026-04-09T12:10:01Z',tracks=[b])]
    r=ev(snaps,rows,{'a':'TRUTH-A','b':'TRUTH-B'})
    assert not r['false_merges'] and not r['attribution_errors'],r

def test_no_expected_rule_does_not_claim_pass():
    rows=[dict(observationId='a',source='rid',detectorId='D',sourceTrackId='R',aircraftId='SN-A')]
    r=ev([dict(tracks=[track('SN-A')])],rows,{'a':'TRUTH-A'})
    assert r['entity_check']['status']=='NOT_TESTED',r

def test_oversized_json_rejected_before_read_text(tmp_path, monkeypatch):
    from pathlib import Path
    from fusion_mvp.workbench.importer import import_tabular, MappingTemplate
    path=tmp_path/'large.json'
    with path.open('wb') as f: f.truncate(32_000_001)
    original=Path.read_text
    def guarded(self,*args,**kwargs):
        if self==path:
            raise AssertionError('oversized JSON read before size guard')
        return original(self,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',guarded)
    result=import_tabular(path,MappingTemplate(),max_rows=1)
    assert result.get('error')=='json_too_large',result
