"""Round4 positive lifecycle / multi-aircraft oracle cases."""
from copy import deepcopy
from datetime import datetime

from fusion_mvp.workbench.scenario import generate_observations, get_preset
import fusion_mvp.workbench.runner as runner


def test_normal_lost_terminate_recovery_explains_phases():
    sc = get_preset("seven_aircraft_combinations")
    sc.aircraft = sc.aircraft[:1]
    sc.duration_s = 80
    sc.aircraft[0].sources["rid"].outage = [(12.0, 50.0)]
    result = runner.WorkbenchRunner().run_scenario_bundle(generate_observations(sc))
    ec = result["evaluation"]["entity_check"]
    assert ec["status"] != "FAIL", ec.get("phases")
    assert "lifecycle_thresholds" in ec
    assert float(ec["lifecycle_thresholds"]["terminate_s"]) == 30.0
    names = [p["name"] for p in ec.get("phases") or []]
    assert "outage_0" in names and any(n.startswith("recovery") for n in names)


def test_sibling_aircraft_missing_during_other_outage_is_fail(monkeypatch):
    """Only A has mid outage; B must still be fully checked — emptying B in recovery fails."""
    sc = get_preset("seven_aircraft_combinations")
    sc.aircraft = sc.aircraft[:2]
    sc.duration_s = 55
    sc.aircraft[0].sources["rid"].outage = [(12.0, 22.0)]
    # B keeps spectrum continuously
    bundle = generate_observations(sc)
    t0 = datetime.fromisoformat(bundle["t0"].replace("Z", "+00:00"))
    original = runner.evaluate_run

    def inject(**kw):
        snaps = deepcopy(kw["snapshots_by_time"])
        for snap in snaps:
            dt = (datetime.fromisoformat(snap["processingTime"].replace("Z", "+00:00")) - t0).total_seconds()
            if 30 <= dt <= 35:
                snap["tracks"] = [
                    tr
                    for tr in (snap.get("tracks") or [])
                    if not str(tr.get("aircraftId") or "").startswith("SN-B")
                ]
        kw["snapshots_by_time"] = snaps
        return original(**kw)

    monkeypatch.setattr(runner, "evaluate_run", inject)
    result = runner.WorkbenchRunner().run_scenario_bundle(bundle)
    assert result["evaluation"]["entity_check"]["status"] == "FAIL"
