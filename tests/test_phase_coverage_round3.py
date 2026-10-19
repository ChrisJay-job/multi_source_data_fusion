"""Review oracle tests: inject missing tracks ONLY into evaluator input, not engine."""
from copy import deepcopy
from datetime import datetime
import pytest
from fusion_mvp.workbench.scenario import get_preset, generate_observations
import fusion_mvp.workbench.runner as runner


@pytest.mark.parametrize('outages,missing', [
    ([(12., 18.), (32., 38.)], (24., 29.)),
    ([(12., 38.)], (20., 28.)),
], ids=['first_recovery_between_two_outages', 'unplanned_early_disappearance_during_outage'])
def test_unchecked_middle_must_not_be_whole_run_pass(monkeypatch, outages, missing):
    sc = get_preset('seven_aircraft_combinations')
    sc.aircraft = sc.aircraft[:1]
    sc.duration_s = 55
    sc.aircraft[0].sources['rid'].outage = outages
    bundle = generate_observations(sc)
    t0 = datetime.fromisoformat(bundle['t0'].replace('Z', '+00:00'))
    original = runner.evaluate_run
    def inject(**kw):
        snaps = deepcopy(kw['snapshots_by_time'])
        for snap in snaps:
            dt = (datetime.fromisoformat(snap['processingTime'].replace('Z', '+00:00')) - t0).total_seconds()
            if missing[0] <= dt <= missing[1]:
                snap['tracks'] = []
        kw['snapshots_by_time'] = snaps
        return original(**kw)
    monkeypatch.setattr(runner, 'evaluate_run', inject)
    result = runner.WorkbenchRunner().run_scenario_bundle(bundle, mode='realtime')
    check = result['evaluation']['entity_check']
    assert check['status'] != 'PASS', {'phases': result['eval_phases'], 'entity_check_status': check['status']}
