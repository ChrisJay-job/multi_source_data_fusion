"""Round4: explicit JSON containers, including RECORDS, without truthiness fallback."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fusion_mvp.api import _bounded_source_sample
from fusion_mvp.workbench.importer import MappingTemplate, import_tabular, page_observations

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "samples" / "task006" / "10_M_rid_spectrum_radia_data_simp.json"
REAL_SHA = "8f20c17a1f05b4513bd73b83459012b93b677ea3974b9d8a091b6993cf311cee"


def _tmpl() -> MappingTemplate:
    return MappingTemplate(
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
        treat_raw_id_as_aircraftId=False,
    )


def _row(**over):
    row = {
        "source": "rid",
        "id": "T1",
        "detector": "D1",
        "created_at": "2026-06-24 08:00:30",
        "longitude": 120.1,
        "latitude": 36.1,
        "heading": 10,
    }
    row.update(over)
    return row


def _write(tmp_path: Path, name: str, data) -> Path:
    p = tmp_path / name
    if isinstance(data, str):
        p.write_text(data, encoding="utf-8")
    else:
        p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_real_records_file_counts_and_ranges():
    assert REAL.is_file()
    assert hashlib.sha256(REAL.read_bytes()).hexdigest() == REAL_SHA
    summary = import_tabular(REAL, _tmpl(), max_rows=50)
    assert summary["ok"] is True
    assert summary["file_read_ok"] is True
    assert summary["json_container"] == "RECORDS"
    assert summary["empty_record_set"] is False
    assert summary["scanned_rows"] == 28
    assert summary["n_observations"] == 26
    assert summary["n_errors"] == 2
    assert summary["by_source"] == {"rid": 8, "spectrum": 18}
    rejects = summary["errors_sample"]
    assert sorted(e["record_index"] for e in rejects) == [10, 17]
    assert {e["reason"] for e in rejects} == {"position_placeholder_0_0"}
    assert summary["time_range"][0].startswith("2026-06-24T08:00:30+08:00")
    assert summary["time_range"][1].startswith("2026-06-24T08:19:32.472688+08:00")
    assert summary["lon_range"][0] == 120.2215347290039
    assert summary["lon_range"][1] == 120.467041015625
    assert summary["lat_range"][0] == 35.954776763916016
    assert summary["lat_range"][1] == 36.093666076660156
    flagged = [o for o in summary["observations"] if "heading_out_of_range" in o["qualityFlags"]]
    assert flagged
    assert all(o["heading"] is None for o in flagged)
    assert all("timezone_pending_device_confirm" in o["qualityFlags"] for o in summary["observations"])
    raw = json.loads(REAL.read_text(encoding="utf-8"))["RECORDS"]
    by_index = {o["rawRef"]["line"]: o for o in summary["observations"]}
    compared = 0
    for i, row in enumerate(raw, start=1):
        if row.get("longitude") in (0, 0.0) and row.get("latitude") in (0, 0.0):
            continue
        obs = by_index[i]
        created_at = str(row["created_at"])
        created_time = row.get("created_time")
        assert obs["measurementTime"].startswith("2026-06-24T")
        if created_time not in (None, "") and str(created_time) != created_at:
            compared += 1
            assert created_time not in obs["measurementTime"]
            assert "created_time_present_distinct" in obs["qualityFlags"]
    assert compared > 0
    page = page_observations(REAL, _tmpl(), offset=0, limit=50)
    assert page["ok"] is True
    assert page["scanned"] == 28
    assert page["n"] == 26
    assert page["json_container"] == "RECORDS"


def test_known_containers_and_empty_array_does_not_fall_through(tmp_path):
    top = _write(tmp_path, "top.json", [_row()])
    obs = _write(tmp_path, "obs.json", {"observations": [_row(source="spectrum")]})
    rows = _write(tmp_path, "rows.json", {"rows": [_row()]})
    empty = _write(tmp_path, "empty.json", {"RECORDS": []})
    empty_obs = _write(tmp_path, "empty_obs.json", {"observations": [], "RECORDS": [_row()]})
    for path, container, n in ((top, "top_level_array", 1), (obs, "observations", 1), (rows, "rows", 1)):
        summary = import_tabular(path, _tmpl(), max_rows=10)
        assert summary["ok"] is True
        assert summary["json_container"] == container
        assert summary["n_observations"] == n
    summary = import_tabular(empty, _tmpl(), max_rows=10)
    assert summary["ok"] is True
    assert summary["empty_record_set"] is True
    assert summary["scanned_rows"] == 0
    assert summary["n_observations"] == 0
    blocked = import_tabular(empty_obs, _tmpl(), max_rows=10)
    assert blocked["ok"] is False
    assert blocked["error"] == "json_structure"
    assert "ambiguous_containers" in blocked["detail"]
    assert blocked["file_read_ok"] is False
    assert blocked["scanned_rows"] == 0


def test_structure_errors_are_not_silent_zero(tmp_path):
    cases = {
        "unknown.json": {"other": [_row()]},
        "scalar.json": 1,
        "not_array.json": {"RECORDS": {"source": "rid"}},
        "bad.json": "{",
    }
    for name, data in cases.items():
        summary = import_tabular(_write(tmp_path, name, data), _tmpl(), max_rows=10)
        assert summary["ok"] is False
        assert summary["error"] == "json_structure"
        assert summary["n_observations"] == 0
        assert summary["scanned_rows"] == 0
    bad = import_tabular(tmp_path / "bad.json", _tmpl(), max_rows=10)
    assert "malformed" in bad["detail"]


def test_non_object_element_is_indexed_and_not_fatal(tmp_path):
    path = _write(tmp_path, "mix.json", {"RECORDS": [1, _row()]})
    summary = import_tabular(path, _tmpl(), max_rows=10)
    assert summary["ok"] is True
    assert summary["scanned_rows"] == 2
    assert summary["n_observations"] == 1
    assert summary["n_errors"] == 1
    err = summary["errors_sample"][0]
    assert err["reason"] == "json_element_not_object"
    assert err["record_index"] == 1
    assert err["index_kind"] == "json_record"


def test_json_too_large_still_rejected(tmp_path, monkeypatch):
    path = _write(tmp_path, "big.json", [])
    orig = Path.stat

    def fake(self, *args, **kwargs):
        if str(self) == str(path):
            return type("ST", (), {"st_size": 32_000_001})()
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake)
    summary = import_tabular(path, _tmpl(), max_rows=10)
    assert summary["ok"] is False
    assert summary["error"] == "json_too_large"


def test_preview_sample_cap_keeps_each_source():
    obs = [{"source": "rid", "i": i} for i in range(150)]
    obs += [{"source": "spectrum", "i": i} for i in range(150)]
    sample = _bounded_source_sample(obs, 200)
    assert len(sample) == 200
    assert {o["source"] for o in sample} == {"rid", "spectrum"}
    assert _bounded_source_sample(obs[:26], 200) == obs[:26]
