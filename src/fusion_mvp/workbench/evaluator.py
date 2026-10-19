"""Independent evaluation: truth never fed back into fusion inputs."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _source_key(st: dict) -> str:
    return f"{st.get('source')}|{st.get('detectorId')}|{st.get('sourceTrackId')}"


def _bound_sources(tr: dict) -> set[str]:
    st = {s.get("source") for s in (tr.get("sourceTracks") or []) if s.get("source")}
    return st or set(tr.get("sources") or [])


def _build_key_intervals(
    delivered_obs: list[dict[str, Any]], obs_truth_map: dict[str, str]
) -> dict[str, list[tuple[datetime, datetime, frozenset[str]]]]:
    """
    Per source-key, time segments → frozenset of truth_ids.
    Same key+measurementTime keeps the full candidate set (no order-based last-wins).
    """
    by_key_time: dict[str, dict[datetime, set[str]]] = defaultdict(lambda: defaultdict(set))
    for o in delivered_obs:
        tid = obs_truth_map.get(o["observationId"])
        if not tid:
            continue
        mt = o.get("measurementTime")
        if not mt:
            continue
        key = f"{o.get('source')}|{o.get('detectorId')}|{o.get('sourceTrackId')}"
        by_key_time[key][_parse(mt)].add(tid)
    out: dict[str, list[tuple[datetime, datetime, frozenset[str]]]] = {}
    far = datetime(9999, 1, 1, tzinfo=timezone.utc)
    for key, time_map in by_key_time.items():
        times = sorted(time_map.keys())
        segs: list[tuple[datetime, datetime, frozenset[str]]] = []
        for i, t0 in enumerate(times):
            t1 = times[i + 1] if i + 1 < len(times) else far
            segs.append((t0, t1, frozenset(time_map[t0])))
        out[key] = segs
    return out


def _truths_at(
    intervals: dict[str, list[tuple[datetime, datetime, frozenset[str]]]],
    key: str,
    at: Optional[str],
    global_map: Optional[dict[str, set[str]]] = None,
) -> set[str]:
    segs = intervals.get(key) or []
    if not segs:
        # No timed obs for key → fall back to global union (fixtures without measurementTime)
        return set((global_map or {}).get(key) or [])
    if not at:
        hits: set[str] = set()
        for _t0, _t1, tids in segs:
            hits |= set(tids)
        return hits
    t = _parse(at)
    hits = set()
    for t0, t1, tids in segs:
        if t0 <= t < t1:
            hits |= set(tids)
    if hits:
        return hits
    t0, _t1, tids = segs[-1]
    if t >= t0:
        return set(tids)
    return set()


def _sn_map(delivered_obs: list[dict], obs_truth_map: dict[str, str]) -> dict[str, str]:
    sn_to_truth: dict[str, str] = {}
    for o in delivered_obs:
        tid = obs_truth_map.get(o["observationId"])
        if tid and o.get("aircraftId"):
            sn_to_truth[o["aircraftId"]] = tid
    return sn_to_truth


def _intervals_upto(
    intervals: dict[str, list[tuple[datetime, datetime, frozenset[str]]]],
    frontier: Optional[str],
) -> dict[str, list[tuple[datetime, datetime, frozenset[str]]]]:
    """Keep only segments whose start is at/before committed frontier (watermark)."""
    if not frontier:
        return intervals
    ft = _parse(frontier)
    out: dict[str, list[tuple[datetime, datetime, frozenset[str]]]] = {}
    for key, segs in intervals.items():
        kept = [(t0, t1, tids) for t0, t1, tids in segs if t0 <= ft]
        if not kept:
            continue
        t0, t1, tids = kept[-1]
        if t1 > ft:
            # Exclusive end just past frontier so lastSeen<=ft still hits; post-frontier
            # reuse observations are excluded from active intervals.
            kept[-1] = (t0, ft + timedelta(microseconds=1), tids)
        out[key] = kept
    return out


def _snapshot_attribution(
    tracks: list[dict],
    *,
    intervals: dict[str, list[tuple[datetime, datetime, frozenset[str]]]],
    sn_to_truth: dict[str, str],
    global_key_truths: dict[str, set[str]],
    processing_time: Optional[str] = None,
    watermark: Optional[str] = None,
) -> tuple[list[dict], list[dict], dict[str, str], list[dict]]:
    fusion_to_truth: dict[str, str] = {}
    for tr in tracks:
        aid = tr.get("aircraftId")
        if aid and aid in sn_to_truth:
            fusion_to_truth[tr["fusionId"]] = sn_to_truth[aid]

    false_merges: list[dict] = []
    attribution_errors: list[dict] = []
    # Attribution clock: bound observation time (lastSeen), not display processingTime
    active = _intervals_upto(intervals, watermark)

    for tr in tracks:
        bound_truths: set[str] = set()
        primary = fusion_to_truth.get(tr["fusionId"])
        for st in tr.get("sourceTracks") or []:
            key = _source_key(st)
            at = st.get("lastSeen") or processing_time
            truths = set(_truths_at(active, key, at, global_key_truths if not watermark else None))
            aid = st.get("aircraftId")
            if aid and aid in sn_to_truth:
                truths.add(sn_to_truth[aid])
            if not truths:
                continue
            if len(truths) > 1:
                attribution_errors.append(
                    {
                        "fusionId": tr["fusionId"],
                        "sourceKey": key,
                        "truths": sorted(truths),
                        "reason": "ambiguous_key_undetermined",
                        "at": at,
                        "lookup": "lastSeen" if st.get("lastSeen") else "processingTime",
                    }
                )
                # Do not treat multi-truth as a definite false merge
                continue
            bound_truths |= truths
            if primary and truths and primary not in truths:
                attribution_errors.append(
                    {
                        "fusionId": tr["fusionId"],
                        "sourceKey": key,
                        "track_truth": primary,
                        "obs_truths": sorted(truths),
                        "reason": "foreign_source_bound",
                        "at": at,
                    }
                )
                false_merges.append(
                    {
                        "fusionId": tr["fusionId"],
                        "truth_ids": sorted({primary} | truths),
                        "via": key,
                        "at": at,
                    }
                )
        if len(bound_truths) > 1:
            false_merges.append(
                {"fusionId": tr["fusionId"], "truth_ids": sorted(bound_truths), "at": processing_time}
            )

    truth_to_fusions: dict[str, set[str]] = defaultdict(set)
    for fid, tid in fusion_to_truth.items():
        truth_to_fusions[tid].add(fid)
    duplicate_targets = [
        {"truth_id": tid, "fusionIds": sorted(fids), "at": processing_time}
        for tid, fids in truth_to_fusions.items()
        if len(fids) > 1
    ]
    return false_merges, attribution_errors, fusion_to_truth, duplicate_targets


def evaluate_run(
    *,
    snapshots_by_time: list[dict[str, Any]],
    obs_truth_map: dict[str, str],
    delivered_obs: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    events: list[dict[str, Any]],
    expected_stable_entities: Optional[dict[str, set[str]]] = None,
    stable_window: Optional[tuple[str, str]] = None,
) -> dict[str, Any]:
    """
    Association uses observationId -> truth_id and time-segmented sourceTrack keys.
    Evaluates every snapshot; stable_window checks entity presence on EVERY in-window frame.
    """
    intervals = _build_key_intervals(delivered_obs, obs_truth_map)
    sn_to_truth = _sn_map(delivered_obs, obs_truth_map)
    global_key_truths: dict[str, set[str]] = defaultdict(set)
    for o in delivered_obs:
        tid = obs_truth_map.get(o["observationId"])
        if not tid:
            continue
        key = f"{o.get('source')}|{o.get('detectorId')}|{o.get('sourceTrackId')}"
        global_key_truths[key].add(tid)

    false_merges: list[dict] = []
    attribution_errors: list[dict] = []
    duplicate_targets: list[dict] = []
    fusion_to_truth: dict[str, str] = {}

    snaps = snapshots_by_time or [{"tracks": []}]
    for snap in snaps:
        tracks = snap.get("tracks") or []
        pt = snap.get("processingTime")
        wm = snap.get("watermark")
        fm, ae, f2t, dup = _snapshot_attribution(
            tracks,
            intervals=intervals,
            sn_to_truth=sn_to_truth,
            global_key_truths=global_key_truths,
            processing_time=pt,
            watermark=wm,
        )
        false_merges.extend(fm)
        attribution_errors.extend(ae)
        duplicate_targets.extend(dup)
        fusion_to_truth = f2t

    def _dedupe(items: list[dict], keyfn) -> list[dict]:
        seen = set()
        out = []
        for it in items:
            k = keyfn(it)
            if k in seen:
                continue
            seen.add(k)
            out.append(it)
        return out

    false_merges = _dedupe(
        false_merges, lambda fm: (fm.get("fusionId"), tuple(fm.get("truth_ids") or []), fm.get("via"), fm.get("at"))
    )
    attribution_errors = _dedupe(
        attribution_errors,
        lambda ae: (ae.get("fusionId"), ae.get("sourceKey"), ae.get("reason"), ae.get("at")),
    )
    duplicate_targets = _dedupe(
        duplicate_targets, lambda d: (d.get("truth_id"), tuple(d.get("fusionIds") or []), d.get("at"))
    )

    last = snaps[-1]
    tracks = last.get("tracks") or []

    # Separate definite errors from same-key same-time undetermined (not order-resolved)
    undetermined = [
        a
        for a in attribution_errors
        if "ambiguous" in str(a.get("reason") or "") or "undetermined" in str(a.get("reason") or "")
    ]
    hard_attrs = [a for a in attribution_errors if a not in undetermined]
    known_errors = bool(false_merges or hard_attrs or duplicate_targets)
    has_undetermined = bool(undetermined)

    entity_check: dict[str, Any] = {
        "ok": True,
        "details": [],
        "status": "PASS",
        "no_known_attribution_errors": not known_errors and not has_undetermined,
    }

    if known_errors:
        entity_check["ok"] = False
        entity_check["status"] = "FAIL"
        entity_check["details"].append(
            {
                "error": "false_attribution_or_merge",
                "n_attr": len(hard_attrs),
                "n_merge": len(false_merges),
                "n_dup": len(duplicate_targets),
            }
        )
    elif has_undetermined:
        # Ambiguity is not a definite false merge and not a definite PASS
        entity_check["ok"] = False
        entity_check["status"] = "UNDETERMINED"
        entity_check["details"].append(
            {
                "error": "ambiguous_same_key_same_time",
                "n_undetermined": len(undetermined),
                "samples": undetermined[:5],
            }
        )

    if expected_stable_entities is None:
        # No scenario expectation → do not claim entity integrity PASS
        if delivered_obs or tracks:
            if entity_check["status"] == "PASS":
                entity_check["status"] = "NOT_TESTED"
            # ok stays True only when no known errors / undetermined; status must not say PASS
            if known_errors or has_undetermined:
                entity_check["ok"] = False
            else:
                entity_check["ok"] = True  # no known errors, but NOT_TESTED completeness
            entity_check["details"].append(
                {"note": "no_expected_stable_entities", "completeness": "NOT_TESTED"}
            )
        else:
            entity_check["status"] = "NOT_TESTED"
    else:
        # Select frames in stable window — EVERY frame must satisfy; no fallback to final if empty
        if stable_window:
            t0, t1 = stable_window
            windowed = [
                s
                for s in snaps
                if s.get("processingTime") and t0 <= s["processingTime"] <= t1
            ]
            if not windowed:
                entity_check["ok"] = False
                entity_check["status"] = "FAIL"
                entity_check["details"].append(
                    {"error": "stable_window_no_frames", "window": [t0, t1]}
                )
                eval_snaps: list[dict] = []
            else:
                eval_snaps = windowed
        else:
            eval_snaps = [last]

        for snap in eval_snaps:
            eval_tracks = snap.get("tracks") or []
            pt = snap.get("processingTime")
            wm = snap.get("watermark")
            _, _, f2t, _ = _snapshot_attribution(
                eval_tracks,
                intervals=intervals,
                sn_to_truth=sn_to_truth,
                global_key_truths=global_key_truths,
                processing_time=pt,
                watermark=wm,
            )
            active = _intervals_upto(intervals, wm)
            for truth_id, need_sources in expected_stable_entities.items():
                matched = [tr for tr in eval_tracks if f2t.get(tr["fusionId"]) == truth_id]
                if not matched:
                    entity_check["ok"] = False
                    entity_check["status"] = "FAIL"
                    entity_check["details"].append(
                        {"truth_id": truth_id, "error": "missing_entity", "at": pt}
                    )
                    continue
                if len(matched) > 1:
                    entity_check["ok"] = False
                    entity_check["status"] = "FAIL"
                    entity_check["details"].append(
                        {
                            "truth_id": truth_id,
                            "error": "non_unique_entity",
                            "fusionIds": [t["fusionId"] for t in matched],
                            "at": pt,
                        }
                    )
                for tr in matched:
                    have = _bound_sources(tr)
                    foreign = False
                    ambiguous = False
                    for st in tr.get("sourceTracks") or []:
                        key = _source_key(st)
                        at = st.get("lastSeen") or pt
                        truths = _truths_at(active, key, at, None if wm else global_key_truths)
                        if len(truths) > 1:
                            ambiguous = True
                            break
                        if truths and truth_id not in truths:
                            foreign = True
                            break
                    if ambiguous:
                        entity_check["ok"] = False
                        if entity_check.get("status") == "PASS":
                            entity_check["status"] = "UNDETERMINED"
                        entity_check["details"].append(
                            {
                                "truth_id": truth_id,
                                "fusionId": tr["fusionId"],
                                "error": "ambiguous_source_key_at_lastSeen",
                                "at": pt,
                            }
                        )
                    elif foreign or not need_sources.issubset(have):
                        entity_check["ok"] = False
                        entity_check["status"] = "FAIL"
                        entity_check["details"].append(
                            {
                                "truth_id": truth_id,
                                "fusionId": tr["fusionId"],
                                "error": "sources_mismatch_or_foreign",
                                "need": sorted(need_sources),
                                "have": sorted(have),
                                "foreign": foreign,
                                "at": pt,
                            }
                        )
                    else:
                        entity_check["details"].append(
                            {
                                "truth_id": truth_id,
                                "fusionId": tr["fusionId"],
                                "sources": sorted(have),
                                "ok": True,
                                "at": pt,
                            }
                        )
            extras = [
                t
                for t in eval_tracks
                if f2t.get(t["fusionId"]) not in expected_stable_entities and t.get("aircraftId")
            ]
            if extras:
                entity_check["ok"] = False
                entity_check["status"] = "FAIL"
                entity_check["details"].append(
                    {"error": "extra_entities", "fusionIds": [t["fusionId"] for t in extras], "at": pt}
                )

    if known_errors:
        entity_check["ok"] = False
        if entity_check.get("status") == "PASS":
            entity_check["status"] = "FAIL"
    elif has_undetermined:
        entity_check["ok"] = False
        if entity_check.get("status") == "PASS":
            entity_check["status"] = "UNDETERMINED"

    return {
        "n_tracks_final": len(tracks),
        "n_delivered": len(delivered_obs),
        "n_rejected": len(rejected),
        "false_merges": false_merges,
        "attribution_errors": attribution_errors,
        "undetermined": undetermined,
        "duplicate_targets": duplicate_targets,
        "fusion_to_truth": fusion_to_truth,
        "entity_check": entity_check,
        "event_types": sorted({e.get("type") for e in events if e.get("type")}),
        "denominators": {
            "delivered_observations": len(delivered_obs),
            "rejected_observations": len(rejected),
            "snapshots_evaluated": len(snaps),
            "note": "全过程评估；同键同刻保留真值集合；稳定窗逐帧检查",
        },
    }


def position_errors(
    truth_timeline: dict[str, list[dict]],
    tracks_at: list[dict],
    fusion_to_truth: dict[str, str],
    *,
    mode: str = "committed",
) -> list[dict]:
    out = []
    by_truth = {k: v for k, v in truth_timeline.items()}
    for tr in tracks_at:
        tid = fusion_to_truth.get(tr["fusionId"])
        if not tid or tid not in by_truth:
            continue
        ts = tr.get("displayStateTime") if mode == "display" else tr.get("stateTime")
        if not ts:
            continue
        t = _parse(ts).timestamp()
        samples = by_truth[tid]
        best = min(samples, key=lambda s: abs(_parse(s["time"]).timestamp() - t))
        dlat = (tr["latitude"] - best["lat"]) * 111_320.0
        dlon = (tr["longitude"] - best["lon"]) * 111_320.0 * math.cos(math.radians(best["lat"]))
        err = math.hypot(dlat, dlon)
        out.append({"truth_id": tid, "fusionId": tr["fusionId"], "error_m": err, "mode": mode})
    return out
