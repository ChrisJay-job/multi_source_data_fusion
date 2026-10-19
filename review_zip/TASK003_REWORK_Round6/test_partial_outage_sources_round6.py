"""Expected active sources must preserve last-seen TTL, and reject stale extras."""
from copy import deepcopy
from datetime import datetime
import pytest
from fusion_mvp.workbench.scenario import get_preset, generate_observations
import fusion_mvp.workbench.runner as runner


@pytest.mark.parametrize('fault',['premature_rid_removal','expired_rid_kept_active'])
def test_partial_outage_active_set_must_match_ttl(monkeypatch,fault):
    sc=get_preset('seven_aircraft_combinations')
    sc.aircraft=[sc.aircraft[3]]  # D: RID+spectrum, one identified entity
    sc.duration_s=45
    sc.aircraft[0].sources['rid'].outage=[(12.,30.)]
    bundle=generate_observations(sc)
    t0=datetime.fromisoformat(bundle['t0'].replace('Z','+00:00'))
    original=runner.evaluate_run
    touched=[]
    def inject(**kw):
        snaps=deepcopy(kw['snapshots_by_time'])
        for snap in snaps:
            dt=(datetime.fromisoformat(snap['watermark'].replace('Z','+00:00'))-t0).total_seconds()
            if (fault=='premature_rid_removal' and 12<=dt<=13) or (fault=='expired_rid_kept_active' and 18<=dt<=22):
                for tr in snap['tracks']:
                    before=set(tr['sources'])
                    assert 'spectrum' in before
                    if fault=='premature_rid_removal':
                        assert 'rid' in before,before
                        tr['sources']=[x for x in tr['sources'] if x!='rid']
                    else:
                        assert 'rid' not in before,before
                        tr['sources']=tr['sources']+['rid']
                    touched.append({'frontier_s':dt,'before':sorted(before),'after':tr['sources']})
        kw['snapshots_by_time']=snaps
        return original(**kw)
    monkeypatch.setattr(runner,'evaluate_run',inject)
    result=runner.WorkbenchRunner().run_scenario_bundle(bundle)
    assert touched
    ec=result['evaluation']['entity_check']
    assert ec['status']=='FAIL',{'fault':fault,'status':ec['status'],'touched':touched}
