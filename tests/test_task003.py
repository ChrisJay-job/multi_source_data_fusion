"""TASK-003: seven-aircraft defaults, association fixes, dynamic evaluation."""
from __future__ import annotations

import json
from pathlib import Path

from fusion_mvp.workbench.runner import WorkbenchRunner
from fusion_mvp.workbench.scenario import (
    generate_observations,
    get_preset,
    scenario_from_dict,
)

ROOT = Path(__file__).resolve().parents[1]
FOUR = ROOT / "samples/workbench/user_four_aircraft_20261019.json"
FOUR_SWAP = ROOT / "samples/workbench/user_four_aircraft_explicit_swap20.json"


def _run(path: Path, *, mode: str = "realtime", raw_override=None):
    raw = raw_override or json.loads(path.read_text(encoding="utf-8"))
    sc = scenario_from_dict(raw)
    bundle = generate_observations(sc)
    bundle["scenario"] = raw
    return WorkbenchRunner().run_scenario_bundle(bundle, mode=mode), bundle


def _a_has_radar_from_c(out: dict, tid_substr: str = "radar-C") -> list[dict]:
    hits = []
    for s in out.get("snapshots") or []:
        for tr in s.get("tracks") or []:
            sts = tr.get("sourceTracks") or []
            if tr.get("aircraftId") == "SN-A-001" and any(
                (x.get("source") == "radar" and tid_substr in str(x.get("sourceTrackId") or ""))
                for x in sts
            ):
                hits.append({"pt": s.get("processingTime"), "fid": tr.get("fusionId")})
    return hits


def _truth_sources(out: dict, truth_id: str) -> set[str]:
    f2t = (out.get("evaluation") or {}).get("fusion_to_truth") or {}
    finals = out.get("final_tracks") or []
    fids = [fid for fid, tid in f2t.items() if tid == truth_id]
    srcs: set[str] = set()
    for tr in finals:
        if tr.get("fusionId") in fids or (
            truth_id == "TRUTH-D" and tr.get("aircraftId") == "SN-X-4"
        ):
            srcs |= set(tr.get("sources") or [])
            for st in tr.get("sourceTracks") or []:
                if st.get("source"):
                    srcs.add(st["source"])
    return srcs


def test_no_hidden_radar_swap_when_null():
    raw = json.loads(FOUR.read_text(encoding="utf-8"))
    sc = scenario_from_dict(raw)
    bundle = generate_observations(sc)
    radar_ids = {o["sourceTrackId"] for o in bundle["observations"] if o["source"] == "radar"}
    assert not any(str(i).endswith("-v2") for i in radar_ids), radar_ids
    assert "radar-C" in radar_ids


def test_explicit_swap20_emits_v2():
    raw = json.loads(FOUR_SWAP.read_text(encoding="utf-8"))
    sc = scenario_from_dict(raw)
    bundle = generate_observations(sc)
    radar_c = [o for o in bundle["observations"] if o["source"] == "radar" and "C" in o["sourceTrackId"]]
    assert any(o["sourceTrackId"].endswith("-v2") for o in radar_c)


def test_user_four_no_c_to_a_misbind():
    out, _ = _run(FOUR)
    assert _a_has_radar_from_c(out) == []
    ec = (out.get("evaluation") or {}).get("entity_check") or {}
    assert ec.get("status") == "PASS", ec
    assert _truth_sources(out, "TRUTH-A") == {"rid"}
    assert "spectrum" in _truth_sources(out, "TRUTH-B")
    assert "radar" in _truth_sources(out, "TRUTH-C")
    assert {"rid", "spectrum", "radar"} <= _truth_sources(out, "TRUTH-D")
    attrs = out.get("evaluation", {}).get("attribution_errors") or []
    assert not any(a.get("track_truth") == "TRUTH-A" and "radar" in str(a) for a in attrs), attrs[:5]


def test_explicit_swap20_no_c_to_a_and_d_ok():
    out, _ = _run(FOUR_SWAP)
    assert _a_has_radar_from_c(out) == []
    finals = out.get("final_tracks") or []
    d = next((t for t in finals if t.get("aircraftId") == "SN-X-4"), None)
    assert d is not None, finals
    assert {"rid", "spectrum", "radar"} <= set(d.get("sources") or [])
    ec = (out.get("evaluation") or {}).get("entity_check") or {}
    assert ec.get("status") == "PASS", ec
    # Unique TRUTH-C (opaque rename / swap must not duplicate)
    f2t = (out.get("evaluation") or {}).get("fusion_to_truth") or {}
    c_fids = [fid for fid, tid in f2t.items() if tid == "TRUTH-C"]
    assert len(set(c_fids)) == 1, c_fids


def test_opaque_id_rename_four_equivalent():
    """radar-C→7319, swap→2048, D radar remapped — same association outcome as spelling form."""
    raw = json.loads(FOUR_SWAP.read_text(encoding="utf-8"))
    sc = scenario_from_dict(raw)
    bundle = generate_observations(sc)
    id_map = {"radar-C": "7319", "radar-C-v2": "2048", "radar-D": "8801"}
    for o in bundle["observations"]:
        if o["source"] == "radar" and o["sourceTrackId"] in id_map:
            o["sourceTrackId"] = id_map[o["sourceTrackId"]]
    out = WorkbenchRunner().run_scenario_bundle(bundle, mode="realtime")
    assert _a_has_radar_from_c(out, "7319") == []
    assert _a_has_radar_from_c(out, "2048") == []
    # A must not carry 7319/2048
    for s in out.get("snapshots") or []:
        for tr in s.get("tracks") or []:
            if tr.get("aircraftId") != "SN-A-001":
                continue
            for st in tr.get("sourceTracks") or []:
                assert st.get("sourceTrackId") not in {"7319", "2048"}
    ec = (out.get("evaluation") or {}).get("entity_check") or {}
    assert ec.get("status") == "PASS", ec


def test_seven_aircraft_stable_seven_entities():
    sc = get_preset("seven_aircraft_combinations")
    assert len(sc.aircraft) == 7
    assert sc.aircraft[2].rid_sn is None
    bundle = generate_observations(sc)
    bundle["scenario"] = sc.to_dict()
    out = WorkbenchRunner().run_scenario_bundle(bundle, mode="realtime")
    ec = (out.get("evaluation") or {}).get("entity_check") or {}
    assert ec.get("status") == "PASS", json.dumps(ec, ensure_ascii=False)[:2000]
    assert len(out.get("final_tracks") or []) == 7
    # commit history exists on multi-update tracks
    hist_n = sum(len(t.get("committedHistory") or []) for t in out.get("final_tracks") or [])
    assert hist_n >= 20, hist_n


def test_expected_from_custom_sources_not_name():
    raw = json.loads(FOUR.read_text(encoding="utf-8"))
    assert raw["name"] == "three_aircraft_primary"
    out, _ = _run(FOUR)
    details = ((out.get("evaluation") or {}).get("entity_check") or {}).get("details") or []
    bad = [
        d
        for d in details
        if d.get("truth_id") == "TRUTH-C"
        and d.get("error") == "sources_mismatch_or_foreign"
        and set(d.get("need") or []) == {"rid", "spectrum", "radar"}
    ]
    assert not bad, bad


def test_other_seed_nearby_no_c_to_a():
    raw = json.loads(FOUR_SWAP.read_text(encoding="utf-8"))
    raw["seed"] = 20261020
    out, _ = _run(FOUR_SWAP, raw_override=raw)
    assert _a_has_radar_from_c(out) == []


def test_short_duration_no_stable_window_not_invented_pass():
    raw = json.loads(FOUR.read_text(encoding="utf-8"))
    raw["duration_s"] = 5
    out, _ = _run(FOUR, raw_override=raw)
    ec = (out.get("evaluation") or {}).get("entity_check") or {}
    assert out.get("stable_window") in (None, []), out.get("stable_window")
    assert ec.get("status") == "NOT_TESTED", ec
