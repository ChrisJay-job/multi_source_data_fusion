"""Exploration-only spatiotemporal co-occurrence + identity helpers (not algorithm gates)."""
from __future__ import annotations

import json
import math
import random
from bisect import bisect_left, bisect_right
from typing import Any, Iterable, Optional


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(x)))


def triple_time_span_ok(t_a: float, t_b: float, t_c: float, dt_s: float) -> bool:
    return (max(t_a, t_b, t_c) - min(t_a, t_b, t_c)) <= dt_s


def pair_near(a: dict[str, Any], b: dict[str, Any], *, dt_s: float, dist_m: float) -> bool:
    if abs(float(a["t"]) - float(b["t"])) > dt_s:
        return False
    return haversine_m(a["lat"], a["lon"], b["lat"], b["lon"]) <= dist_m


def parse_source_data(raw: Any) -> tuple[Optional[dict], Optional[str]]:
    """Return (dict|None, error_tag|None). Bad/oversized JSON must not abort callers."""
    if raw in (None, ""):
        return None, "missing_source_data"
    if isinstance(raw, dict):
        return raw, None
    if not isinstance(raw, str):
        return None, "source_data_not_str_or_dict"
    s = raw.strip()
    if not s:
        return None, "missing_source_data"
    if len(s) > 2_000_000:
        return None, "source_data_too_large"
    try:
        obj = json.loads(s)
    except Exception:
        return None, "source_data_bad_json"
    if not isinstance(obj, dict):
        return None, "source_data_not_object"
    return obj, None


def extract_raw_identities(row: dict[str, Any]) -> dict[str, Any]:
    """
    Surface vs raw identity fields. Does not confirm protocol/device semantics.
    Status ladder: field_present | suspected_identity | confirmed_identity (never auto).
    """
    aerial = row.get("aerial_sn")
    aerial_s = str(aerial).strip() if aerial not in (None, "") else ""
    sd, err = parse_source_data(row.get("source_data"))
    rid_uas = ""
    spectrum_sn = ""
    channel_hint = None
    if sd:
        sn = sd.get("serialNumber")
        if sn not in (None, ""):
            spectrum_sn = str(sn).strip()
        ident = sd.get("identification1") or sd.get("identification") or {}
        if isinstance(ident, dict):
            uas = ident.get("uasIdAsString") or ident.get("uasId")
            if uas not in (None, ""):
                rid_uas = str(uas).strip()
        channel_hint = sd.get("type") or sd.get("channelType") or sd.get("msgType")
    surface_id = str(row.get("id") or "").strip()
    return {
        "surface_id": surface_id or None,
        "aerial_sn": aerial_s or None,
        "raw_rid_uasId": rid_uas or None,
        "raw_spectrum_serialNumber": spectrum_sn or None,
        "source_data_error": err,
        "channel_hint": channel_hint,
        "identity_status": {
            "aerial_sn": "field_present" if aerial_s else "absent",
            "raw_rid_uasId": "suspected_identity" if rid_uas else "absent",
            "raw_spectrum_serialNumber": "suspected_identity" if spectrum_sn else "absent",
            "confirmed_identity": "none",  # requires external/device confirm
        },
    }


def classify_id_vs_raw(surface_id: Optional[str], raw_id: Optional[str]) -> str:
    a = (surface_id or "").strip()
    b = (raw_id or "").strip()
    if not a and not b:
        return "both_missing"
    if not a:
        return "surface_missing_raw_present"
    if not b:
        return "raw_missing_surface_present"
    if a == b:
        return "equal"
    if a.endswith(b) or b.endswith(a) or a.startswith(b) or b.startswith(a):
        return "prefix_suffix_candidate"  # not identity confirm
    return "conflict_or_unrelated"


def find_three_source_candidates(
    points: Iterable[dict[str, Any]],
    *,
    dt_s: float,
    dist_m: float,
) -> list[dict[str, Any]]:
    by = {"rid": [], "spectrum": [], "radar": []}
    for p in points:
        src = p.get("source")
        if src in by:
            by[src].append(p)
    out: list[dict[str, Any]] = []
    for r in by["rid"]:
        for s in by["spectrum"]:
            if not pair_near(r, s, dt_s=dt_s, dist_m=dist_m):
                continue
            for rad in by["radar"]:
                if not triple_time_span_ok(r["t"], s["t"], rad["t"], dt_s):
                    continue
                if not pair_near(r, rad, dt_s=dt_s, dist_m=dist_m):
                    continue
                if not pair_near(s, rad, dt_s=dt_s, dist_m=dist_m):
                    continue
                out.append(
                    {
                        "level": "B_spatiotemporal",
                        "rid": r,
                        "spectrum": s,
                        "radar": rad,
                        "span_s": max(r["t"], s["t"], rad["t"]) - min(r["t"], s["t"], rad["t"]),
                        "max_pair_dist_m": max(
                            haversine_m(r["lat"], r["lon"], s["lat"], s["lon"]),
                            haversine_m(r["lat"], r["lon"], rad["lat"], rad["lon"]),
                            haversine_m(s["lat"], s["lon"], rad["lat"], rad["lon"]),
                        ),
                    }
                )
    return out


def identity_enhanced(
    candidates: Iterable[dict[str, Any]],
    *,
    strict: bool = True,
) -> list[dict[str, Any]]:
    """
    Level-C upgrade only on strict equality of confirmed/suspected identity fields.
    Prefix/suffix matches are reported separately and do NOT upgrade to C.
    """
    enhanced = []
    for c in candidates:
        rid_id = str(c["rid"].get("raw_rid_uasId") or c["rid"].get("id") or "")
        sn = str(c["spectrum"].get("raw_spectrum_serialNumber") or c["spectrum"].get("sn") or "")
        if not sn or not rid_id:
            continue
        if sn == rid_id:
            item = dict(c)
            item["level"] = "C_identity_enhanced"
            item["identity_match"] = "strict_equal"
            enhanced.append(item)
            continue
        if not strict and (sn.endswith(rid_id) or rid_id.endswith(sn)):
            # Explicit non-upgrade path for tests/reporting only
            item = dict(c)
            item["level"] = "B_spatiotemporal"
            item["identity_match"] = "prefix_suffix_candidate_not_upgraded"
            enhanced.append(item)
    return enhanced


def prefix_suffix_identity_candidates(candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for c in candidates:
        rid_id = str(c["rid"].get("raw_rid_uasId") or c["rid"].get("id") or "")
        sn = str(c["spectrum"].get("raw_spectrum_serialNumber") or c["spectrum"].get("sn") or "")
        if not sn or not rid_id or sn == rid_id:
            continue
        if sn.endswith(rid_id) or rid_id.endswith(sn) or sn.startswith(rid_id) or rid_id.startswith(sn):
            item = dict(c)
            item["level"] = "identity_prefix_suffix_candidate"
            item["note"] = "not C-level; no vendor rule confirmed"
            out.append(item)
    return out


def two_source_pairs(
    points: Iterable[dict[str, Any]],
    a: str,
    b: str,
    *,
    dt_s: float,
    dist_m: float,
) -> list[tuple[dict, dict]]:
    A = [p for p in points if p.get("source") == a]
    B = [p for p in points if p.get("source") == b]
    hits = []
    for x in A:
        for y in B:
            if pair_near(x, y, dt_s=dt_s, dist_m=dist_m):
                hits.append((x, y))
    return hits


def count_pair_best_per_a(
    points: list[dict[str, Any]],
    a: str,
    b: str,
    *,
    dt_s: float,
    dist_m: float,
) -> dict[str, Any]:
    """Indexed search: each A keeps at most one nearest B within gates. Distinct from all-pairs."""
    A = [p for p in points if p.get("source") == a]
    B = sorted([p for p in points if p.get("source") == b], key=lambda p: p["t"])
    bt = [p["t"] for p in B]
    raw_hits = 0
    selected = 0
    for x in A:
        lo = bisect_left(bt, x["t"] - dt_s)
        hi = bisect_right(bt, x["t"] + dt_s)
        best = None
        for y in B[lo:hi]:
            d = haversine_m(x["lat"], x["lon"], y["lat"], y["lon"])
            if d <= dist_m:
                raw_hits += 1
                score = (d, abs(y["t"] - x["t"]))
                if best is None or score < best[0]:
                    best = (score, y)
        if best:
            selected += 1
    return {
        "params": {"dt_s": dt_s, "dist_m": dist_m, "pair": f"{a}_{b}"},
        "raw_gated_pair_records": raw_hits,
        "selected_best_per_a": selected,
        "n_a": len(A),
        "n_b": len(B),
        "note": "selected_best_per_a ≠ all-pairs count",
    }


def nn_diagnostics(
    A: list[tuple],
    B: list[tuple],
    *,
    sample_n: int = 2000,
    window_s: float = 30.0,
    seed: int = 42,
    criterion: str = "spatial",  # spatial | temporal — which pair to keep inside window
) -> dict[str, Any]:
    """
    A/B tuples: (t, lat, lon, ...)
    Strict ±window_s stats are separate from unrestricted fallback.
    dist_m and dt_s always come from the same chosen partner.
    """
    if not A or not B:
        return {"sample_n": 0, "in_window": {}, "unrestricted_fallback": {}}
    idxs = list(range(len(A)))
    rng = random.Random(seed)
    rng.shuffle(idxs)
    idxs = idxs[: min(sample_n, len(idxs))]
    bt = [p[0] for p in B]
    in_pairs: list[dict[str, Any]] = []
    miss = 0
    fallback_pairs: list[dict[str, Any]] = []
    for i in idxs:
        ta, la, loa = A[i][0], A[i][1], A[i][2]
        lo = bisect_left(bt, ta - window_s)
        hi = bisect_right(bt, ta + window_s)
        window = B[lo:hi]
        if window:
            best = None
            for p in window:
                d = haversine_m(la, loa, p[1], p[2])
                dt = abs(p[0] - ta)
                key = (d, dt) if criterion == "spatial" else (dt, d)
                if best is None or key < best[0]:
                    best = (key, d, dt, p)
            assert best is not None
            _, d, dt, p = best
            in_pairs.append({"dist_m": d, "dt_s": dt, "partner_t": p[0], "partner_lat": p[1], "partner_lon": p[2]})
        else:
            miss += 1
            # unrestricted nearest-in-time (explicitly separate)
            j = bisect_left(bt, ta)
            cands = []
            for k in (j - 1, j, j + 1):
                if 0 <= k < len(B):
                    cands.append(B[k])
            if not cands:
                continue
            p = min(cands, key=lambda q: abs(q[0] - ta))
            d = haversine_m(la, loa, p[1], p[2])
            dt = abs(p[0] - ta)
            fallback_pairs.append({"dist_m": d, "dt_s": dt, "partner_t": p[0]})

    def summarize(pairs: list[dict[str, Any]]) -> dict[str, Any]:
        if not pairs:
            return {"n": 0}
        ds = sorted(p["dist_m"] for p in pairs)
        dts = sorted(p["dt_s"] for p in pairs)

        def pct(arr, p):
            return arr[int((len(arr) - 1) * p)]

        return {
            "n": len(pairs),
            "dist_m_p50": pct(ds, 0.5),
            "dist_m_p10": pct(ds, 0.1),
            "dist_m_min": ds[0],
            "dt_s_p50": pct(dts, 0.5),
            "dt_s_min": dts[0],
            "criterion": criterion,
            "same_partner_for_dist_and_dt": True,
        }

    return {
        "sample_n_requested": sample_n,
        "sample_n_drawn": len(idxs),
        "seed": seed,
        "window_s": window_s,
        "in_window_hits": len(in_pairs),
        "in_window_missing": miss,
        "in_window": summarize(in_pairs),
        "unrestricted_fallback": {
            **summarize(fallback_pairs),
            "note": "NOT within ±window_s; do not mix with in_window stats",
        },
        "note": "Exploration only; not algorithm gates; not full-file min distance",
    }


# Canonical exploration param sets actually enumerated by full scan (not 3×3 cartesian).
EXPLORATION_PARAM_SETS = [
    {"dt_s": 1.0, "dist_m": 20.0},
    {"dt_s": 2.0, "dist_m": 50.0},
    {"dt_s": 5.0, "dist_m": 100.0},
]
