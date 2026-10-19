from copy import deepcopy
from datetime import datetime,timedelta
from fusion_mvp.workbench.scenario import get_preset,generate_observations
import fusion_mvp.workbench.runner as runner

def test_missing_target_after_outage_recovery_cannot_pass_whole_run(monkeypatch):
    sc=get_preset('seven_aircraft_combinations')
    sc.aircraft=sc.aircraft[:1]
    sc.aircraft[0].sources['rid'].outage=[(12.0,22.0)]
    bundle=generate_observations(sc)
    cutoff=datetime.fromisoformat(bundle['t0'].replace('Z','+00:00'))+timedelta(seconds=26)
    original=runner.evaluate_run
    def evaluator_with_recovery_failure(**kw):
        snaps=deepcopy(kw['snapshots_by_time'])
        for snap in snaps:
            if datetime.fromisoformat(snap['processingTime'].replace('Z','+00:00'))>=cutoff:
                snap['tracks']=[]
        kw['snapshots_by_time']=snaps
        return original(**kw)
    monkeypatch.setattr(runner,'evaluate_run',evaluator_with_recovery_failure)
    r=runner.WorkbenchRunner().run_scenario_bundle(bundle,mode='realtime')
    ec=r['evaluation']['entity_check']
    assert ec['status']!='PASS',{'stable_window':r['stable_window'],'entity_check':ec}
