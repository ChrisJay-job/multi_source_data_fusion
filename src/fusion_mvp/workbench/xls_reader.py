"""OLE .xls (BIFF) reader for workbench import. Does not execute macros."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterator, Optional

# Expected Sheet1 header names for this export (Sheet1(2) continues without header).
CANONICAL_HEADERS = [
    "id",
    "longitude",
    "latitude",
    "altitude",
    "speed",
    "heading",
    "created_at",
    "source",
    "type",
    "aerial_sn",
    "detector",
    "source_data",
    "uav_type",
    "model",
    "brand",
    "model_number",
    "base_latitude",
    "base_longitude",
    "azimuth_angle",
    "target_distance",
    "sensors",
    "freq",
    "district",
    "tenant_region_code",
    "height",
    "is_cooperation",
    "created_time",
]


def detect_spreadsheet_kind(path: Path) -> str:
    """Read only a fixed prefix; never load the full file into memory."""
    with path.open("rb") as f:
        head = f.read(256)
    if len(head) >= 8 and head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "ole_xls"
    if len(head) >= 2 and head[:2] == b"PK":
        return "ooxml_xlsx"
    text = head.lstrip().lower()
    if text.startswith(b"<html") or text.startswith(b"<!doctype html"):
        return "html_table"
    return "unknown"


def _cell_value(book: Any, sheet: Any, row: int, col: int) -> Any:
    import xlrd

    cell = sheet.cell(row, col)
    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            dt = xlrd.xldate_as_datetime(cell.value, book.datemode)
            return dt.isoformat(sep=" ")
        except Exception:
            return cell.value
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        # Keep ints that are whole numbers as int-like string for IDs when in id column later
        v = cell.value
        if isinstance(v, float) and v == int(v) and abs(v) < 1e15:
            # Still return float for lon/lat/alt; string conversion happens by column
            return v
        return v
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return bool(cell.value)
    if cell.ctype == xlrd.XL_CELL_EMPTY:
        return ""
    return cell.value


def _row_dict(book: Any, sheet: Any, row: int, headers: list[str]) -> dict[str, Any]:
    import xlrd

    out: dict[str, Any] = {}
    for c, h in enumerate(headers):
        if c >= sheet.ncols:
            break
        val = _cell_value(book, sheet, row, c)
        # Untyped numeric Excel serials only in known time columns (workbook datemode).
        if (
            h in ("created_at", "created_time")
            and isinstance(val, (int, float))
            and not isinstance(val, bool)
            and 20000.0 <= float(val) <= 80000.0
        ):
            try:
                val = xlrd.xldate_as_datetime(float(val), book.datemode).isoformat(sep=" ")
            except Exception:
                pass
        # ID-like columns: prefer stable string without scientific notation
        if h in ("id", "detector", "aerial_sn", "source", "type", "district") and val != "":
            if isinstance(val, float) and val == int(val):
                val = str(int(val))
            else:
                val = str(val).strip() if not isinstance(val, str) else val
        out[h] = val
    out["__sheet__"] = sheet.name
    out["__sheet_index__"] = getattr(sheet, "number", 0)
    out["__row__"] = row + 1  # 1-based spreadsheet row
    return out


def _headers_look_canonical(headers: list[str]) -> bool:
    low = {str(h).strip().lower() for h in headers}
    return "id" in low and "source" in low and "longitude" in low and "created_at" in low


def iter_ole_xls_rows(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield (physical_line_no, row). Continuations without header reuse first sheet headers."""
    import xlrd

    book = xlrd.open_workbook(str(path), formatting_info=False, on_demand=True)
    try:
        headers: Optional[list[str]] = None
        line_no = 0
        for si in range(book.nsheets):
            sh = book.sheet_by_index(si)
            if sh.nrows == 0:
                book.unload_sheet(si)
                continue
            row0 = [str(_cell_value(book, sh, 0, c)).strip() for c in range(sh.ncols)]
            start = 0
            if headers is None:
                if _headers_look_canonical(row0):
                    headers = [str(_cell_value(book, sh, 0, c)).strip() or CANONICAL_HEADERS[c] if c < len(CANONICAL_HEADERS) else str(c) for c in range(sh.ncols)]
                    # normalize to canonical names when close
                    for i, h in enumerate(headers):
                        if i < len(CANONICAL_HEADERS) and h.lower() == CANONICAL_HEADERS[i].lower():
                            headers[i] = CANONICAL_HEADERS[i]
                    start = 1
                else:
                    headers = list(CANONICAL_HEADERS[: sh.ncols])
                    start = 0
            else:
                # Continuation sheet: if first row looks like headers again, skip; else all data
                if _headers_look_canonical(row0):
                    start = 1
                else:
                    start = 0
            assert headers is not None
            for r in range(start, sh.nrows):
                line_no += 1
                yield line_no, _row_dict(book, sh, r, headers)
            book.unload_sheet(si)
    finally:
        book.release_resources()


def file_identity(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:16]
