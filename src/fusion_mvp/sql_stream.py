from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

COLUMNS = [
    "id", "longitude", "latitude", "altitude", "speed", "heading", "created_at",
    "source", "type", "aerial_sn", "detector", "source_data", "uav_type", "model",
    "brand", "model_number", "base_latitude", "base_longitude", "azimuth_angle",
    "target_distance", "sensors", "freq", "district", "height", "created_time",
]
PREFIX = 'INSERT INTO "public"."aircraft_flight_data" VALUES ('


def parse_sql_tuple(body: str) -> list:
    out = []
    i = 0
    n = len(body)
    while i < n:
        while i < n and body[i] in " \t\r\n,":
            i += 1
        if i >= n or body[i] == ")":
            break
        if body.startswith("NULL", i) and (i + 4 == n or body[i + 4] in ",)"):
            out.append(None)
            i += 4
            continue
        if body[i] == "'":
            i += 1
            buf = []
            while i < n:
                ch = body[i]
                if ch == "'" and i + 1 < n and body[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                if ch == "'":
                    i += 1
                    break
                buf.append(ch)
                i += 1
            out.append("".join(buf))
            continue
        j = i
        while j < n and body[j] not in ",)":
            j += 1
        token = body[i:j].strip()
        if token:
            out.append(token)
        i = j
    return out


def iter_insert_rows(path: str | Path, sources: set[str] | None = None, limit: int | None = None) -> Iterator[tuple[int, dict]]:
    n = 0
    with Path(path).open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, 1):
            if not line.startswith(PREFIX):
                continue
            vals = parse_sql_tuple(line[len(PREFIX):])
            row = {COLUMNS[i]: (vals[i] if i < len(vals) else None) for i in range(len(COLUMNS))}
            if sources and row.get("source") not in sources:
                continue
            yield line_no, row
            n += 1
            if limit is not None and n >= limit:
                return
