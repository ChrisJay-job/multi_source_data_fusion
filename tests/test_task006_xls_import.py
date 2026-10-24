"""TASK-006: real OLE .xls import + mapping edge cases."""
from __future__ import annotations

from pathlib import Path

import pytest

from fusion_mvp.workbench.importer import MappingTemplate, _to_iso, page_observations, row_to_observation
from fusion_mvp.workbench.xls_reader import detect_spreadsheet_kind

XLS = Path(__file__).resolve().parents[1] / "data" / "10_m_rid_spectrum_radia_data.xls"


@pytest.mark.skipif(not XLS.exists(), reason="full XLS not linked in this environment")
def test_detect_ole_xls():
    assert detect_spreadsheet_kind(XLS) == "ole_xls"


def test_slash_time_and_pp_leida():
    tmpl = MappingTemplate(source_timezone="Asia/Shanghai")
    iso, flags = _to_iso("2026/6/24 8:00:30", tmpl)
    assert iso is not None and iso.startswith("2026-06-24T08:00:30")
    assert any("timezone_applied" in f for f in flags)
    row = {
        "source": "pp",
        "id": "T1",
        "created_at": "2026-06-24 08:19:16.473551",
        "longitude": 120.1,
        "latitude": 36.1,
        "detector": "D1",
        "heading": "361.0",
        "__sheet__": "S",
        "__row__": 2,
    }
    obs, err = row_to_observation(row, tmpl, 2)
    assert err is None
    assert obs["source"] == "spectrum"
    assert obs["heading"] is None
    assert "heading_out_of_range" in obs["qualityFlags"]
    row2 = dict(row)
    row2["source"] = "leida"
    obs2, err2 = row_to_observation(row2, tmpl, 3)
    assert err2 is None and obs2["source"] == "radar"
    row3 = dict(row)
    row3["longitude"] = 0.0
    row3["latitude"] = 0.0
    obs3, err3 = row_to_observation(row3, tmpl, 4)
    assert obs3 is None and err3["reason"] == "position_placeholder_0_0"


@pytest.mark.skipif(not XLS.exists(), reason="full XLS not linked")
def test_page_late_and_mixed_sources():
    tmpl = MappingTemplate(
        field_map={
            "source": "source",
            "sourceTrackId": "id",
            "measurementTime": "created_at",
            "longitude": "longitude",
            "latitude": "latitude",
            "detectorId": "detector",
            "heading": "heading",
        },
        source_timezone="Asia/Shanghai",
    )
    early = page_observations(XLS, tmpl, offset=0, limit=5)
    assert early["ok"] and early["n"] >= 1
    late = page_observations(XLS, tmpl, offset=90000, limit=2)
    assert late["ok"] and late["matched_so_far"] >= 90000
    assert late["n"] >= 1
