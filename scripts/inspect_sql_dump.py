"""Bounded streaming inspection of a large PostgreSQL SQL dump.

Does not load the full file into memory. Collects CREATE TABLE, risky
statements, source enums, and reservoir samples per source.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


CREATE_TABLE_RE = re.compile(r"^CREATE TABLE(?: IF NOT EXISTS)?\s+([^\s(]+)", re.I)
COPY_RE = re.compile(r"^COPY\s+([^\s(]+)\s*\((.*)\)\s+FROM stdin;", re.I)
INSERT_RE = re.compile(r"^INSERT INTO\s+([^\s(]+)", re.I)
DROP_RE = re.compile(r"^DROP\s+", re.I)
ROLE_RE = re.compile(r"^(CREATE|ALTER)\s+ROLE\b|^GRANT\b|^REVOKE\b", re.I)
EXT_RE = re.compile(r"^CREATE\s+EXTENSION\b", re.I)
COPY_CMD_RE = re.compile(r"^\\copy\b", re.I)


def peek_header(path: Path, n: int = 512) -> dict:
    with path.open("rb") as f:
        raw = f.read(n)
    magic = raw[:5]
    kind = "unknown"
    if magic == b"PGDMP":
        kind = "pg_dump_custom"
    elif raw.startswith(b"\x1f\x8b"):
        kind = "gzip"
    elif raw[:2] == b"PK":
        kind = "zip"
    elif raw.lstrip().startswith((b"--", b"SET ", b"CREATE", b"BEGIN", b"COPY", b"INSERT")):
        kind = "plain_sql"
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = ""
    return {
        "magic_hex": raw[:16].hex(),
        "kind": kind,
        "header_preview": text[:400].replace("\x00", "\\0"),
    }


def split_sql_ident(name: str) -> str:
    return name.strip().strip('"')


def parse_copy_line(line: str, columns: list[str]) -> dict | None:
    if line in ("\\.", "\\.\n"):
        return None
    parts = line.rstrip("\n").split("\t")
    if len(parts) != len(columns):
        return {"_parse_error": True, "_n": len(parts), "_expect": len(columns)}
    row = {}
    for k, v in zip(columns, parts):
        row[k] = None if v == "\\N" else v
    return row


def reservoir_add(store: list, item, k: int, rng: random.Random, seen: list[int]) -> None:
    seen[0] += 1
    n = seen[0]
    if len(store) < k:
        store.append(item)
        return
    j = rng.randint(1, n)
    if j <= k:
        store[j - 1] = item


def summarize_times(values: list[str]) -> dict:
    parsed = []
    for v in values:
        if not v:
            continue
        s = v.replace(" ", "T")
        try:
            if s.endswith("Z"):
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            elif "+" in s[10:] or s.count("-") >= 3:
                dt = datetime.fromisoformat(s)
            else:
                dt = datetime.fromisoformat(s)
            parsed.append(dt)
        except Exception:
            continue
    if not parsed:
        return {"min": None, "max": None, "n_parsed": 0, "n_raw": len(values)}
    return {
        "min": min(parsed).isoformat(),
        "max": max(parsed).isoformat(),
        "n_parsed": len(parsed),
        "n_raw": len(values),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sql_path")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sample-per-source", type=int, default=30)
    ap.add_argument("--max-bytes", type=int, default=0, help="0 = full file")
    args = ap.parse_args()

    path = Path(args.sql_path)
    st = path.stat()
    header = peek_header(path)
    rng = random.Random(17)

    report = {
        "file": str(path),
        "size_bytes": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        "header": header,
        "risky": {"drop": 0, "role_grant": 0, "extension": 0, "copy_meta": 0},
        "tables": {},
        "copy_jobs": [],
        "source_counts": {},
        "notes": [],
        "scan": {"bytes_read": 0, "lines": 0, "truncated": False},
    }

    if header["kind"] != "plain_sql":
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": False, "kind": header["kind"]}, ensure_ascii=False))
        return 2

    current_copy = None
    current_table_ddl = None
    ddl_buf: list[str] = []
    in_ddl = False

    per_table = defaultdict(
        lambda: {
            "rows": 0,
            "bad_rows": 0,
            "columns": [],
            "sources": Counter(),
            "ids": Counter(),
            "aerial_sn": Counter(),
            "time_fields": defaultdict(list),
            "nulls": Counter(),
            "heading_samples": Counter(),
            "alt_samples": Counter(),
            "source_data_keys": Counter(),
            "samples": [],
            "sample_seen": [0],
        }
    )

    max_bytes = args.max_bytes or st.st_size
    bytes_read = 0

    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        for line in f:
            bytes_read += len(line.encode("utf-8", errors="replace"))
            report["scan"]["lines"] += 1
            if bytes_read > max_bytes:
                report["scan"]["truncated"] = True
                break

            if in_ddl:
                ddl_buf.append(line)
                if ");" in line:
                    ddl = "".join(ddl_buf)
                    report["tables"][current_table_ddl] = ddl[:8000]
                    in_ddl = False
                    ddl_buf = []
                continue

            m = CREATE_TABLE_RE.match(line)
            if m:
                current_table_ddl = split_sql_ident(m.group(1))
                in_ddl = True
                ddl_buf = [line]
                continue

            if DROP_RE.match(line):
                report["risky"]["drop"] += 1
            if ROLE_RE.match(line):
                report["risky"]["role_grant"] += 1
            if EXT_RE.match(line):
                report["risky"]["extension"] += 1
            if COPY_CMD_RE.match(line):
                report["risky"]["copy_meta"] += 1

            cm = COPY_RE.match(line)
            if cm:
                table = split_sql_ident(cm.group(1))
                cols = [c.strip().strip('"') for c in cm.group(2).split(",")]
                current_copy = {"table": table, "columns": cols}
                per_table[table]["columns"] = cols
                report["copy_jobs"].append({"table": table, "columns": cols})
                continue

            if current_copy is not None:
                if line.startswith("\\."):
                    current_copy = None
                    continue
                table = current_copy["table"]
                cols = current_copy["columns"]
                row = parse_copy_line(line, cols)
                stt = per_table[table]
                stt["rows"] += 1
                if not row or row.get("_parse_error"):
                    stt["bad_rows"] += 1
                    continue
                for c in cols:
                    if row.get(c) is None:
                        stt["nulls"][c] += 1
                src = row.get("source") or row.get("data_source") or row.get("origin")
                if src:
                    stt["sources"][src] += 1
                if row.get("aerial_sn") is not None and (
                    len(stt["aerial_sn"]) < 80 or row["aerial_sn"] in stt["aerial_sn"]
                ):
                    stt["aerial_sn"][row["aerial_sn"]] += 1
                for tf in ("created_at", "created_time", "track_time", "event_time", "ts", "time"):
                    if tf in row and row[tf] is not None and len(stt["time_fields"][tf]) < 5000:
                        stt["time_fields"][tf].append(row[tf])
                if row.get("heading") is not None and len(stt["heading_samples"]) < 40:
                    stt["heading_samples"][row["heading"]] += 1
                if row.get("altitude") is not None and len(stt["alt_samples"]) < 40:
                    stt["alt_samples"][row["altitude"]] += 1
                sd = row.get("source_data")
                if sd and stt["rows"] <= 20000:
                    try:
                        obj = json.loads(sd)
                        if isinstance(obj, dict):
                            for k in obj.keys():
                                stt["source_data_keys"][k] += 1
                    except Exception:
                        pass
                compact = {k: row.get(k) for k in cols if k in (
                    "id", "source", "aerial_sn", "longitude", "latitude", "altitude",
                    "heading", "speed", "created_at", "created_time", "source_data",
                    "device_id", "detector_id", "track_id"
                ) or k in cols[:12]}
                reservoir_add(stt["samples"], compact, args.sample_per_source, rng, stt["sample_seen"])

            if INSERT_RE.match(line) and "VALUES" in line.upper():
                report["notes"].append("insert_values_detected")

            if report["scan"]["lines"] % 2_000_000 == 0:
                print(f"progress lines={report['scan']['lines']} bytes={bytes_read}", file=sys.stderr, flush=True)

    report["scan"]["bytes_read"] = bytes_read

    tables_out = {}
    for table, stt in per_table.items():
        time_summary = {k: summarize_times(v) for k, v in stt["time_fields"].items()}
        id_repeat = sum(1 for _, c in stt["ids"].most_common(20) if c > 1)
        tables_out[table] = {
            "rows": stt["rows"],
            "bad_rows": stt["bad_rows"],
            "columns": stt["columns"],
            "sources": stt["sources"].most_common(30),
            "aerial_sn_top": stt["aerial_sn"].most_common(20),
            "nulls": dict(stt["nulls"]),
            "time_summary": time_summary,
            "heading_samples": stt["heading_samples"].most_common(20),
            "alt_samples": stt["alt_samples"].most_common(20),
            "source_data_keys": stt["source_data_keys"].most_common(40),
            "id_counter_capped": True,
            "id_repeat_in_capped_counter": id_repeat,
            "samples": stt["samples"][: args.sample_per_source],
        }
    report["per_table"] = tables_out

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out), "tables": list(tables_out), "lines": report["scan"]["lines"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
