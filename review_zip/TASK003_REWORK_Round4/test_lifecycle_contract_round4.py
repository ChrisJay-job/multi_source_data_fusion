"""Independent review: oracle must distinguish normal termination and broken lifecycle."""
from copy import deepcopy
from datetime import datetime
import pytest
from fusion_mvp.workbench.scenario import get_preset, generate_observations
import fusion_mvp.workbench.runner as runner


@pytest.mark.parametrize('outage,duration', [([(12.,50.)],80), ([(0.,10.)],40)],
                         ids=['normal_termination_then_rebirth', 'startup_without_prior_detection'])
def test_normal_outage_is_not_false_failure(outage,duration):
    sc=get_preset('seven_aircraft_combinations')
    sc.aircraft=sc.aircraft[:1]
    sc.duration_s=duration
    sc.aircraft[0].sources['rid'].outage=outage
    result=runner.WorkbenchRunner().run_scenario_bundle(generate_observations(sc))
    check=result['evaluation']['entity_check']
    assert check['status'] != 'FAIL', {'phases':check.get('phases'),
        'errors':[d for d in check['details'] if d.get('error')][:3]}


def test_stopped_source_cannot_remain_fresh_measured_and_tracked(monkeypatch):
    sc=get_preset('seven_aircraft_combinations')
    sc.aircraft=sc.aircraft[:1]
    sc.duration_s=55
    sc.aircraft[0].sources['rid'].outage=[(12.,38.)]
    bundle=generate_observations(sc)
    t0=datetime.fromisoformat(bundle['t0'].replace('Z','+00:00'))
    original=runner.evaluate_run
    injected=[]
    def inject(**kw):
        snaps=deepcopy(kw['snapshots_by_time'])
        for snap in snaps:
            dt=(datetime.fromisoformat(snap['processingTime'].replace('Z','+00:00'))-t0).total_seconds()
            if 26 <= dt <= 29:
                for tr in snap['tracks']:
                    injected.append((tr['trackStatus'],tr['positionMode']))
                    # Output uses trackStatus, not the internal Track.status.
                    tr['trackStatus']='tracked'
                    tr['positionMode']='measured'
                    tr['sources']=['rid']
        kw['snapshots_by_time']=snaps
        return original(**kw)
    monkeypatch.setattr(runner,'evaluate_run',inject)
    result=runner.WorkbenchRunner().run_scenario_bundle(bundle)
    assert injected and all(x==('lost','stale') for x in injected), injected
    check=result['evaluation']['entity_check']
    assert check['status']!='PASS', {'injected_from':injected,'phases':check.get('phases')}
