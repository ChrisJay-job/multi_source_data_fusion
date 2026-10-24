"""Round5: XLS sheet/row provenance and replay summary fields."""
from __future__ import annotations

import json
from pathlib import Path

import xlwt
from fastapi.testclient import TestClient

from fusion_mvp.api import app
from fusion_mvp.workbench.importer import MappingTemplate, import_tabular, page_observations

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "samples" / "task006" / "10_M_rid_spectrum_radia_data_simp.json"
HEADERS = ["id", "longitude", "latitude", "created_at", "source", "detector"]


def _tmpl() -> MappingTemplate:
    return MappingTemplate(
        field_map={
            "source": "source",
            "sourceTrackId": "id",
            "measurementTime": "created_at",
            "longitude": "longitude",
            "latitude": "latitude",
            "detectorId": "detector",
        },
        source_timezone="Asia/Shanghai",
        treat_raw_id_as_aircraftId=False,
    )


def _write_cell(sheet, row: int, values: dict) -> None:
    for col, name in enumerate(HEADERS):
        sheet.write(row, col, values[name])


def _build_xls(path: Path) -> None:
    book = xlwt.Workbook()
    a = book.add_sheet("Flight_A")
    for col, name in enumerate(HEADERS):
        a.write(0, col, name)
    _write_cell(a, 1, {
        "id": "TA",
        "longitude": 120.1,
        "latitude": 36.1,
        "created_at": "2026-06-24 08:00:30",
        "source": "rid",
        "detector": "D1",
    })
    b = book.add_sheet("Flight_B")
    for col, name in enumerate(HEADERS):
        b.write(0, col, name)
    _write_cell(b, 1, {
        "id": "TB",
        "longitude": 120.2,
        "latitude": 36.2,
        "created_at": "2026-06-24 08:01:30",
        "source": "spectrum",
        "detector": "D1",
    })
    _write_cell(b, 2, {
        "id": "T0",
        "longitude": 0,
        "latitude": 0,
        "created_at": "2026-06-24 08:02:30",
        "source": "spectrum",
        "detector": "D1",
    })
    c = book.add_sheet("Flight_C")
    _write_cell(c, 0, {
        "id": "TC",
        "longitude": 120.3,
        "latitude": 36.3,
        "created_at": "2026-06-24 08:03:30",
        "source": "radar",
        "detector": "D1",
    })
    book.save(str(path))


def _by_suffix(summary: dict) -> dict[str, dict]:
    out = {}
    for obs in summary["observations"]:
        oid = obs["observationId"]
        suffix = oid.rsplit("-imp-", 1)[-1]
        out[suffix] = obs
    return out


def test_xls_sheet_and_physical_row_survive_import_and_page(tmp_path):
    path = tmp_path / "two_sheet_trace.xls"
    _build_xls(path)
    first = import_tabular(path, _tmpl(), max_rows=20)
    second = import_tabular(path, _tmpl(), max_rows=20)
    assert first["ok"] is True
    assert first["n_observations"] == 3
    assert first["n_errors"] == 1
    located = _by_suffix(first)
    assert set(located) == {"Flight_A-2", "Flight_B-2", "Flight_C-1"}
    assert located["Flight_A-2"]["rawRef"]["sheet"] == "Flight_A"
    assert located["Flight_A-2"]["rawRef"]["row"] == 2
    assert located["Flight_B-2"]["rawRef"]["sheet"] == "Flight_B"
    assert located["Flight_B-2"]["rawRef"]["row"] == 2
    assert located["Flight_C-1"]["rawRef"]["sheet"] == "Flight_C"
    assert located["Flight_C-1"]["rawRef"]["row"] == 1
    ids = [o["observationId"] for o in first["observations"]]
    assert len(ids) == len(set(ids))
    assert all(item.startswith("two_sheet_trace-") and "-imp-Flight_" in item for item in ids)
    assert located["Flight_A-2"]["sourceTrackId"] == "TA"
    assert "observationId" not in HEADERS
    assert [o["observationId"] for o in second["observations"]] == ids
    err = first["errors_sample"][0]
    assert err["reason"] == "position_placeholder_0_0"
    assert err["sheet"] == "Flight_B"
    assert err["row"] == 3
    page = page_observations(path, _tmpl(), offset=0, limit=50)
    assert page["ok"] is True
    assert page["n"] == 3
    assert _by_suffix(page)["Flight_B-2"]["rawRef"]["row"] == 2
    assert page["errors_sample"][0]["sheet"] == "Flight_B"
    assert page["errors_sample"][0]["row"] == 3
    later = page_observations(path, _tmpl(), offset=1, limit=1)
    assert later["n"] == 1
    only = later["observations"][0]
    assert only["rawRef"]["sheet"] == "Flight_B"
    assert only["rawRef"]["row"] == 2
    assert only["observationId"] == located["Flight_B-2"]["observationId"]


def test_replay_summary_keeps_json_container_and_time():
    client = TestClient(app)
    mapping = {
        "field_map": {
            "measurementTime": "created_at",
            "sourceTrackId": "id",
            "detectorId": "detector",
            "source": "source",
            "longitude": "longitude",
            "latitude": "latitude",
        },
        "source_timezone": "Asia/Shanghai",
        "assume_utc_naive": False,
        "treat_raw_id_as_aircraftId": False,
    }
    with REAL.open("rb") as fh:
        preview = client.post(
            "/v1/workbench/import/preview",
            files={"file": (REAL.name, fh, "application/json")},
            data={"mapping_json": json.dumps(mapping), "max_rows": "50"},
        )
    assert preview.status_code == 200
    stored = preview.json()["stored_as"]
    replay = client.post(
        "/v1/workbench/run/import",
        json={"path": stored, "mode": "replay", "mapping": mapping, "maxRows": 50},
    )
    assert replay.status_code == 200
    summary = replay.json()["import_summary"]
    assert summary["json_container"] == "RECORDS"
    assert summary["empty_record_set"] is False
    assert summary["time_range"][0].startswith("2026-06-24T08:00:30+08:00")
    assert summary["time_range"][1].startswith("2026-06-24T08:19:32.472688+08:00")
    assert summary["scanned"] == 28
    assert replay.json()["n_observations"] == 26
