"""Synthetic co-occurrence / identity / NN rules (TASK-006 R1)."""
from fusion_mvp.workbench.cooccurrence import (
    extract_raw_identities,
    find_three_source_candidates,
    identity_enhanced,
    nn_diagnostics,
    prefix_suffix_identity_candidates,
    two_source_pairs,
)


def _p(source, t, lat, lon, id_, sn=None, **extra):
    d = {"source": source, "t": t, "lat": lat, "lon": lon, "id": id_, "sn": sn}
    d.update(extra)
    return d


def test_same_time_different_region_no_b():
    pts = [
        _p("rid", 1000, 36.1, 120.3, "R1"),
        _p("spectrum", 1001, 36.1, 120.3, "S1"),
        _p("radar", 1002, 37.5, 118.5, "L1"),
    ]
    assert find_three_source_candidates(pts, dt_s=5, dist_m=100) == []


def test_chain_drift_not_whole_window():
    lat, lon = 36.1000, 120.3000
    pts = [
        _p("rid", 1000, lat, lon, "R1"),
        _p("spectrum", 1005, lat, lon + 0.00001, "S1"),
        _p("radar", 1010, lat, lon + 0.00002, "L1"),
    ]
    assert find_three_source_candidates(pts, dt_s=5, dist_m=100) == []
    assert len(find_three_source_candidates(pts, dt_s=10, dist_m=100)) == 1


def test_prefix_sn_does_not_upgrade_to_c():
    lat, lon = 36.1000, 120.3000
    pts = [
        _p("rid", 1000, lat, lon, "SN001", raw_rid_uasId="SN001"),
        _p("spectrum", 1001, lat, lon + 0.00001, "X", sn="PREFIXSN001", raw_spectrum_serialNumber="PREFIXSN001"),
        _p("radar", 1002, lat, lon + 0.00002, "L1"),
    ]
    b = find_three_source_candidates(pts, dt_s=5, dist_m=100)
    assert len(b) == 1
    assert identity_enhanced(b, strict=True) == []
    assert len(prefix_suffix_identity_candidates(b)) == 1


def test_strict_equal_identity_upgrades_c():
    lat, lon = 36.1000, 120.3000
    pts = [
        _p("rid", 1000, lat, lon, "SN123", raw_rid_uasId="SN123"),
        _p("spectrum", 1001, lat, lon + 0.00001, "X", sn="SN123", raw_spectrum_serialNumber="SN123"),
        _p("radar", 1002, lat, lon + 0.00002, "L1"),
    ]
    b = find_three_source_candidates(pts, dt_s=5, dist_m=100)
    c = identity_enhanced(b, strict=True)
    assert len(c) == 1 and c[0]["level"] == "C_identity_enhanced"


def test_anonymous_near_is_b_not_c():
    lat, lon = 36.1000, 120.3000
    pts = [
        _p("rid", 1000, lat, lon, "R1"),
        _p("spectrum", 1001, lat, lon + 0.00001, "S1"),
        _p("radar", 1002, lat, lon + 0.00002, "L1"),
    ]
    b = find_three_source_candidates(pts, dt_s=5, dist_m=100)
    assert len(b) == 1
    assert identity_enhanced(b) == []


def test_missing_source_still_reports_two_source():
    lat, lon = 36.1000, 120.3000
    pts = [_p("rid", 1000, lat, lon, "R1"), _p("spectrum", 1001, lat, lon + 0.00001, "S1")]
    assert find_three_source_candidates(pts, dt_s=5, dist_m=100) == []
    assert len(two_source_pairs(pts, "rid", "spectrum", dt_s=5, dist_m=100)) == 1


def test_nn_window_missing_not_mixed_with_fallback():
    A = [(1000.0, 36.1, 120.3)]
    B = [(2000.0, 36.1, 120.3)]  # 1000s away
    d = nn_diagnostics(A, B, sample_n=1, window_s=30.0, seed=1)
    assert d["in_window_hits"] == 0
    assert d["in_window_missing"] == 1
    assert d["in_window"]["n"] == 0
    assert d["unrestricted_fallback"]["n"] == 1
    assert d["unrestricted_fallback"]["dt_s_min"] == 1000.0


def test_raw_sn_present_when_aerial_empty():
    row = {
        "id": "T1",
        "aerial_sn": "",
        "source_data": '{"serialNumber":"ABC999","identification1":{"uasIdAsString":"UAS1"}}',
    }
    idents = extract_raw_identities(row)
    assert idents["aerial_sn"] is None
    assert idents["raw_spectrum_serialNumber"] == "ABC999"
    assert idents["raw_rid_uasId"] == "UAS1"


def test_bad_source_data_json_counted():
    idents = extract_raw_identities({"id": "1", "source_data": "{not-json"})
    assert idents["source_data_error"] == "source_data_bad_json"
