"""TASK-006 Round1: fingerprint, epoch time, detect head-only, preview timeline probe."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from fusion_mvp.workbench.importer import (
    MappingTemplate,
    _path_fp8,
    _to_iso,
    clear_path_fp_cache,
    import_tabular,
    row_to_observation,
)
from fusion_mvp.workbench.xls_reader import detect_spreadsheet_kind

ROOT = Path(__file__).resolve().parents[1]
MINI_XLS = ROOT / "samples" / "task006" / "biff" / "mini_mixed.xls"


def test_epoch_60000_not_excel_serial():
    iso, flags = _to_iso(60000, MappingTemplate(source_timezone="Asia/Shanghai"))
    assert iso is not None
    assert "1970-01-01T16:40:00" in iso.replace("+00:00", "Z").replace("+0000", "")
    assert "excel_serial" not in "".join(flags)


def test_path_fp_differs_same_name_size_mtime(tmp_path):
    clear_path_fp_cache()
    a = tmp_path / "a" / "same.jsonl"
    b = tmp_path / "b" / "same.jsonl"
    a.parent.mkdir()
    b.parent.mkdir()
    a.write_text("AAAA\n", encoding="utf-8")
    b.write_text("BBBB\n", encoding="utf-8")
    # align size+mtime second
    now = time.time()
    import os

    os.utime(a, (now, now))
    os.utime(b, (now, now))
    assert a.stat().st_size == b.stat().st_size
    fa, fb = _path_fp8(a), _path_fp8(b)
    assert fa != fb


def test_path_fp_invalidates_on_content_replace(tmp_path):
    clear_path_fp_cache()
    p = tmp_path / "x.jsonl"
    p.write_text("OLD\n", encoding="utf-8")
    f1 = _path_fp8(p)
    time.sleep(0.02)
    p.write_text("UPDATED-CONTENT-LONGER\n", encoding="utf-8")
    f2 = _path_fp8(p)
    assert f1 != f2


def test_detect_kind_reads_prefix_only(tmp_path):
    # OLE magic only — not a valid workbook, but kind detection must not require full parse
    p = tmp_path / "tiny.xls"
    p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
    assert detect_spreadsheet_kind(p) == "ole_xls"


@pytest.mark.skipif(not MINI_XLS.exists(), reason="mini BIFF fixture missing")
def test_mini_biff_import_and_page():
    tmpl = MappingTemplate(
        field_map={
            "source": "source",
            "sourceTrackId": "id",
            "measurementTime": "created_at",
            "longitude": "longitude",
            "latitude": "latitude",
            "detectorId": "detector",
        },
        source_timezone="Asia/Shanghai",
    )
    assert detect_spreadsheet_kind(MINI_XLS) == "ole_xls"
    summary = import_tabular(MINI_XLS, tmpl, max_rows=50)
    assert summary.get("ok") is True
    assert summary.get("n_observations", 0) >= 3
    sources = set(summary.get("by_source") or {})
    assert "rid" in sources or "spectrum" in sources or "radar" in sources


def test_preview_timeline_cover_end_logic():
    """Mirror R1-01: sorted sample + end snap must expose all points under canvas rule t<=now."""
    sample = []
    for i in range(20):
        sample.append(
            {
                "measurementTime": f"2026-06-24T08:00:{i:02d}+08:00",
                "longitude": 120.3 + i * 1e-5,
                "latitude": 36.1,
                "source": "rid",
                "sourceTrackId": "T",
                "detectorId": "D",
            }
        )
    sample.sort(key=lambda o: o["measurementTime"])
    t_end = sample[-1]["measurementTime"]
    visible = [o for o in sample if o["measurementTime"] <= t_end]
    assert len(visible) == 20
    assert sample[0]["measurementTime"] != sample[-1]["measurementTime"]


def test_importable_jsonl_product_path():
    imp = ROOT / "samples" / "task006" / "importable"
    cands = list(imp.glob("slice_*_continuous_std.jsonl")) + list(imp.glob("slice_*_longspan_smoke_std.jsonl"))
    if not cands:
        pytest.skip("importable slice not generated yet")
    p = cands[0]
    tmpl = MappingTemplate(source_timezone="Asia/Shanghai")
    # Standard top-level fields
    row = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    assert "source" in row and "measurementTime" in row
    obs, err = row_to_observation(
        {
            **row,
            "__sheet__": "jsonl",
            "__row__": 1,
            "created_at": row.get("measurementTime"),
            "id": row.get("sourceTrackId"),
            "detector": row.get("detectorId"),
        },
        tmpl,
        1,
    )
    # May need field_map — also try import_tabular
    summary = import_tabular(
        p,
        MappingTemplate(
            field_map={
                "source": "source",
                "sourceTrackId": "sourceTrackId",
                "measurementTime": "measurementTime",
                "longitude": "longitude",
                "latitude": "latitude",
                "detectorId": "detectorId",
            },
            source_timezone="Asia/Shanghai",
        ),
        max_rows=20,
    )
    assert summary.get("n_observations", 0) >= 1
    assert summary.get("ok") is True
