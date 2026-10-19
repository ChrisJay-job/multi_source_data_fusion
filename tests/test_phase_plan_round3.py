"""Round3 positive phase-plan coverage (no fault injection)."""
from fusion_mvp.workbench.scenario import (
    evaluation_phases_from_bundle,
    generate_observations,
    get_preset,
)


def test_two_outages_yield_mid_recovery_and_outage_phases():
    sc = get_preset("seven_aircraft_combinations")
    sc.aircraft = sc.aircraft[:1]
    sc.duration_s = 55
    sc.aircraft[0].sources["rid"].outage = [(12.0, 18.0), (32.0, 38.0)]
    bundle = generate_observations(sc)
    phases = evaluation_phases_from_bundle(bundle)
    names = [p["name"] for p in phases]
    assert "pre_outage" in names, names
    assert "outage_0" in names and "outage_1" in names, names
    assert "recovery_0" in names, names
    assert any(n.startswith("recovery") for n in names if n != "recovery_0"), names
    modes = {p["name"]: p["mode"] for p in phases}
    assert modes["outage_0"] == "lifecycle"
    assert modes["recovery_0"] == "full"
    # Mid recovery must cover the gap after first outage (≈22–31s → includes 24–29 fault window)
    rec0 = next(p for p in phases if p["name"] == "recovery_0")
    assert rec0["available"] and rec0["window"]
    assert "12:00:2" in rec0["window"][0] or "12:00:2" in rec0["window"][1]


def test_overlapping_outages_merge():
    sc = get_preset("seven_aircraft_combinations")
    sc.aircraft = sc.aircraft[:1]
    sc.duration_s = 40
    sc.aircraft[0].sources["rid"].outage = [(10.0, 16.0), (15.0, 20.0)]
    bundle = generate_observations(sc)
    phases = evaluation_phases_from_bundle(bundle)
    outages = [p for p in phases if str(p["name"]).startswith("outage")]
    assert len(outages) == 1, phases
