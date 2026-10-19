"""Independent evaluator probes; mutate only evaluation inputs, never engine inputs."""
from copy import deepcopy
from datetime import datetime
import pytest
from fusion_mvp.workbench.scenario import get_preset, generate_observations
import fusion_mvp.workbench.runner as runner


@pytest.mark.parametrize('fault', ['early_termination', 'missing_snapshot_fields', 'empty_active_sources'])
def test_contract_fault_cannot_be_whole_run_pass(monkeypatch, fault):
    sc=get_preset('seven_aircraft_combinations')
    sc.aircraft=sc.aircraft[:1]
    if fault=='early_termination':
        sc.duration_s=80
        sc.aircraft[0].sources['rid'].outage=[(12.,50.)]
    bundle=generate_observations(sc)
    t0=datetime.fromisoformat(bundle['t0'].replace('Z','+00:00'))
    original=runner.evaluate_run
    touched=[]
    def inject(**kw):
        snaps=deepcopy(kw['snapshots_by_time'])
        for snap in snaps:
            dt=(datetime.fromisoformat(snap['processingTime'].replace('Z','+00:00'))-t0).total_seconds()
            if fault=='early_termination' and 42 <= dt <= 43:
                # Lifecycle frontier is pt-2s: target must still be retained through gap=30.
                assert snap['tracks'] and all(t['trackStatus']=='lost' for t in snap['tracks'])
                touched.append({'pt':snap['processingTime'],'watermark':snap['watermark']})
                snap['tracks']=[]
            elif fault!='early_termination' and 15 <= dt <= 20:
                for tr in snap['tracks']:
                    touched.append(dt)
                    if fault=='missing_snapshot_fields':
                        tr.pop('trackStatus',None)
                        tr.pop('positionMode',None)
                    else:
                        assert tr['sources']==['rid'],tr
                        tr['sources']=[]
        kw['snapshots_by_time']=snaps
        return original(**kw)
    monkeypatch.setattr(runner,'evaluate_run',inject)
    result=runner.WorkbenchRunner().run_scenario_bundle(bundle)
    assert touched, fault
    ec=result['evaluation']['entity_check']
    assert ec['status']!='PASS',{'fault':fault,'touched':touched,'status':ec['status']}
