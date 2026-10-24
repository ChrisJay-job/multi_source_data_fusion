"""Round2: CSV fixture + preview layer enable logic probes."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

from fusion_mvp.workbench.importer import MappingTemplate, import_tabular

ROOT = Path(__file__).resolve().parents[1]
MINI_CSV = ROOT / "samples" / "task006" / "csv" / "mini_mixed.csv"

csv.field_size_limit(min(16 * 1024 * 1024, sys.maxsize // 10))


def test_mini_csv_long_json_and_duplicates():
    assert MINI_CSV.exists()
    with MINI_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 5  # includes one duplicate surface key
    # multiline / quoted source_data preserved
    assert any("\n" in (r.get("source_data") or "") or "comma" in (r.get("source_data") or "") for r in rows)
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
    summary = import_tabular(MINI_CSV, tmpl, max_rows=20)
    assert summary.get("ok") is True
    assert summary.get("n_observations", 0) >= 4
    by = summary.get("by_source") or {}
    assert set(by) >= {"rid", "spectrum", "radar"} or set(by) >= {"rid", "spectrum"}


def test_epoch_still_not_excel():
    from fusion_mvp.workbench.importer import _to_iso

    iso, _ = _to_iso(60000, MappingTemplate())
    assert "1970-01-01" in iso


def test_dmy_slash_date_csv_style():
    from fusion_mvp.workbench.importer import MappingTemplate, _to_iso

    iso, flags = _to_iso("24/6/2026 08:00:30", MappingTemplate(source_timezone="Asia/Shanghai"))
    assert iso is not None and iso.startswith("2026-06-24T08:00:30")
    assert any("timezone_applied" in f for f in flags)
