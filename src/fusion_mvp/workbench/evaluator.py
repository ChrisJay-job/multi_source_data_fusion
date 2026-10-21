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
    """Historical bindings (sourceTracks) for attribution — not proof of current online."""
    st = {s.get("source") for s in (tr.get("sourceTracks") or []) if s.get("source")}
    return st or set(tr.get("sources") or [])


def _active_sources_field(tr: dict) -> set[str]:
    """Snapshot `sources` = currently fresh/active sources (engine contract)."""
    return {s for s in (tr.get("sources") or []) if s}


VALID_TRACK_STATUS = frozenset({"tentative", "tracked", "coasting", "lost", "terminated"})
VALID_POSITION_MODE = frozenset({"measured_assisted", "predicted", "stale"})

DEFAULT_LIFECYCLE = {
    "predict_horizon_s": 4.0,
    "coast_s": 4.0,
    "lost_s": 12.0,
    "terminate_s": 30.0,
}


def _snapshot_clocks(snap: dict) -> tuple[datetime, datetime]:
    """Separate engine clocks: lifecycle/frontier vs display/processing.

    Engine advances trackStatus / terminate / active-source TTL on event_watermark
    (realtime: processingTime − reorder_window). Display coast uses processingTime.
    """
    pt_raw = snap.get("processingTime")
    wm_raw = snap.get("watermark")
    pt = _parse(pt_raw) if pt_raw else None
    wm = _parse(wm_raw) if wm_raw else None
    if wm is None and pt is None:
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        return epoch, epoch
    lifecycle = wm if wm is not None else pt
    display = pt if pt is not None else wm
    assert lifecycle is not None and display is not None
    return lifecycle, display


def _validate_required_track_fields(tr: dict) -> Optional[dict[str, Any]]:
    """Structural/enum checks before phase business rules. No legacy field backfill."""
    errors: list[dict[str, Any]] = []
    if "trackStatus" not in tr or tr.get("trackStatus") is None or tr.get("trackStatus") == "":
        errors.append(
            {
                "field": "trackStatus",
                "error": "missing_required_field",
                "actual": tr.get("trackStatus", "__absent__"),
                "hint": "do not substitute legacy status",
            }
        )
    else:
        st = tr.get("trackStatus")
        if not isinstance(st, str) or st not in VALID_TRACK_STATUS:
            errors.append(
                {
                    "field": "trackStatus",
                    "error": "illegal_enum",
                    "actual": st,
                    "allowed": sorted(VALID_TRACK_STATUS),
                }
            )
    if "positionMode" not in tr or tr.get("positionMode") is None or tr.get("positionMode") == "":
        errors.append(
            {
                "field": "positionMode",
                "error": "missing_required_field",
                "actual": tr.get("positionMode", "__absent__"),
            }
        )
    else:
        pm = tr.get("positionMode")
        if not isinstance(pm, str) or pm not in VALID_POSITION_MODE:
            errors.append(
                {
                    "field": "positionMode",
                    "error": "illegal_enum",
                    "actual": pm,
                    "allowed": sorted(VALID_POSITION_MODE),
                }
            )
    if "sources" in tr and tr.get("sources") is not None and not isinstance(tr.get("sources"), list):
        errors.append(
            {
                "field": "sources",
                "error": "illegal_type",
                "actual": type(tr.get("sources")).__name__,
                "expected": "list",
            }
        )
    if not errors:
        return None
    return {
        "error": "snapshot_field_contract",
        "fusionId": tr.get("fusionId"),
        "field_errors": errors,
    }


def _source_fresh_limit(src: str, rid_fresh_s: float, coast_s: float) -> float:
    return rid_fresh_s if src == "rid" else coast_s


def _expected_active_sources(
    *,
    truth_id: str,
    sched: dict[str, Any],
    lifecycle_clock: datetime,
    t0_dt: Optional[datetime],
    delivered_obs: list[dict[str, Any]],
    obs_truth_map: dict[str, str],
    rid_fresh_s: float,
    coast_s: float,
    need_sources_default: set[str],
) -> set[str]:
    """Expected currently-active sources (aligns with engine._active_sources).

    Three distinct notions:
    - planned / enabled: scenario-enabled sources (outage only stops *new* obs)
    - emitting now: enabled and not in an outage interval (schedule)
    - active now: confirmed last committed obs at frontier still within per-source TTL

    Outage does **not** revoke an already-received observation's TTL window.
    History `sourceTracks` are not consulted.
    """
    _ = t0_dt  # retained for call-site symmetry; age uses lifecycle_clock only
    if sched.get("enabled"):
        candidates = set(sched["enabled"])
    else:
        candidates = set(need_sources_default)
    active: set[str] = set()
    for src in candidates:
        last: Optional[datetime] = None
        for o in delivered_obs:
            if obs_truth_map.get(o["observationId"]) != truth_id:
                continue
            if o.get("source") != src:
                continue
            mt = o.get("measurementTime")
            if not mt:
                continue
            t = _parse(mt)
            if t <= lifecycle_clock and (last is None or t > last):
                last = t
        if last is None:
            continue
        age = (lifecycle_clock - last).total_seconds()
        if age <= _source_fresh_limit(src, rid_fresh_s, coast_s):
            active.add(src)
    return active


def _diff_active_sources(need: set[str], have: set[str]) -> dict[str, Any]:
    """Bidirectional active-set check: missing_active and unexpected_active."""
    missing = need - have
    unexpected = have - need
    return {
        "ok": not missing and not unexpected,
        "missing_active": sorted(missing),
        "unexpected_active": sorted(unexpected),
        "expected_active": sorted(need),
        "actual_active": sorted(have),
    }


def _lifecycle_thresholds(cfg: Optional[dict[str, Any]]) -> dict[str, float]:
    life = dict(DEFAULT_LIFECYCLE)
    if cfg:
        for k in DEFAULT_LIFECYCLE:
            if k in cfg:
                try:
                    life[k] = float(cfg[k])
                except (TypeError, ValueError):
                    pass
    return life


def _last_obs_time_for_truth(
    delivered_obs: list[dict[str, Any]],
    obs_truth_map: dict[str, str],
    truth_id: str,
    at_or_before: datetime,
) -> Optional[datetime]:
    last: Optional[datetime] = None
    for o in delivered_obs:
        if obs_truth_map.get(o["observationId"]) != truth_id:
            continue
        mt = o.get("measurementTime")
        if not mt:
            continue
        t = _parse(mt)
        if t <= at_or_before and (last is None or t > last):
            last = t
    return last


def _truth_schedules(scenario: Optional[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """truth_id → takeoff_s, enabled sources, per-source outage intervals."""
    out: dict[str, dict[str, Any]] = {}
    if not scenario:
        return out
    for a in scenario.get("aircraft") or []:
        tid = a.get("truth_id") or a.get("truthId")
        if not tid:
            continue
        enabled: set[str] = set()
        outages: dict[str, list[tuple[float, float]]] = {}
        for src, cfg in (a.get("sources") or {}).items():
            if not (cfg or {}).get("enabled"):
                continue
            enabled.add(src)
            pairs: list[tuple[float, float]] = []
            for pair in (cfg or {}).get("outage") or []:
                try:
                    pairs.append((float(pair[0]), float(pair[1])))
                except (TypeError, ValueError, IndexError):
                    continue
            outages[src] = pairs
        out[str(tid)] = {
            "takeoff_s": float(a.get("takeoff_offset_s") or 0.0),
            "enabled": enabled,
            "outages": outages,
        }
    return out


def _source_in_outage(sched: dict[str, Any], src: str, t_s: float) -> bool:
    for a0, b0 in (sched.get("outages") or {}).get(src) or []:
        if a0 <= t_s <= b0:
            return True
    return False


def _expected_sources_at(sched: dict[str, Any], t_s: float) -> set[str]:
    return {s for s in (sched.get("enabled") or set()) if not _source_in_outage(sched, s, t_s)}


def _lifecycle_band(gap_s: float, life: dict[str, float]) -> dict[str, Any]:
    """Lifecycle-clock gap → trackStatus / absence / fresh-source policy.

    Boundaries match engine._advance_lifecycle exactly (no clock-skew expansion).
    Terminate only when gap > terminate_s.
    """
    h = life["predict_horizon_s"]
    lost = life["lost_s"]
    term = life["terminate_s"]
    if gap_s <= h:
        return {
            "band": "fresh_or_predict",
            "allow_absent": False,
            "trackStatus": {"tracked", "tentative", "coasting"},
            "forbid_fresh_sources": False,
        }
    if gap_s <= lost:
        return {
            "band": "coast_stale",
            "allow_absent": False,
            "trackStatus": {"coasting"},
            "forbid_fresh_sources": True,
        }
    if gap_s <= term:
        return {
            "band": "lost_stale",
            "allow_absent": False,
            "trackStatus": {"lost"},
            "forbid_fresh_sources": True,
        }
    return {
        "band": "terminated_absent",
        "allow_absent": True,
        "trackStatus": set(),
        "forbid_fresh_sources": True,
        "forbid_present": True,
    }


def _display_position_modes(disp_gap_s: float, life: dict[str, float]) -> set[str]:
    """Display-clock gap → allowed positionMode (engine display coast vs stale)."""
    h = life["predict_horizon_s"]
    if disp_gap_s <= h:
        return {"measured_assisted", "predicted", "stale"}
    return {"stale"}


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
        # Anonymous / radar-only: assign fusion→truth from unanimous source-key evidence
        if tr["fusionId"] not in fusion_to_truth and len(bound_truths) == 1:
            fusion_to_truth[tr["fusionId"]] = next(iter(bound_truths))
            primary = fusion_to_truth[tr["fusionId"]]
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
    eval_phases: Optional[list[dict[str, Any]]] = None,
    scenario: Optional[dict[str, Any]] = None,
    lifecycle_cfg: Optional[dict[str, Any]] = None,
    rid_fresh_s: float = 2.5,
    scenario_t0: Optional[str] = None,
) -> dict[str, Any]:
    """
    Association uses observationId -> truth_id and time-segmented sourceTrack keys.
    Entity checks use trackStatus/positionMode time bands from lifecycle config; terminated
    tracks may be absent from snapshots after terminate_s. Phases aggregate independently.
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
        # Normalize phases: prefer eval_phases; else single stable_window; else last frame only.
        phases: list[dict[str, Any]]
        if eval_phases:
            phases = list(eval_phases)
        elif stable_window:
            phases = [{"name": "stable", "mode": "full", "window": stable_window, "available": True}]
        else:
            phases = [{"name": "final_only", "mode": "full", "window": None, "available": True}]

        phase_cover: list[dict[str, Any]] = []
        missing_required = False
        life = _lifecycle_thresholds(lifecycle_cfg)
        schedules = _truth_schedules(scenario)
        t0_dt: Optional[datetime] = None
        if scenario_t0:
            t0_dt = _parse(scenario_t0)
        elif snaps:
            # fallback: earliest processingTime minus small offset — prefer explicit t0
            try:
                t0_dt = min(_parse(s["processingTime"]) for s in snaps if s.get("processingTime"))
            except ValueError:
                t0_dt = None

        coast_s = float(life.get("coast_s") or DEFAULT_LIFECYCLE["coast_s"])

        def _clock_meta(life_clk: datetime, disp_clk: datetime, last_obs: Optional[datetime]) -> dict[str, Any]:
            return {
                "lifecycle_clock": life_clk.isoformat(),
                "display_clock": disp_clk.isoformat(),
                "frontier": life_clk.isoformat(),
                "last_observation": last_obs.isoformat() if last_obs else None,
                "thresholds": life,
                "rid_fresh_s": rid_fresh_s,
                "coast_s": coast_s,
            }

        def _check_snaps(
            eval_snaps: list[dict],
            phase_name: str,
            *,
            mode: str = "full",
        ) -> tuple[str, list[dict[str, Any]]]:
            details: list[dict[str, Any]] = []
            status = "PASS"

            def _fail(err: dict) -> None:
                nonlocal status
                status = "FAIL"
                details.append(err)

            def _undetermined(err: dict) -> None:
                nonlocal status
                if status == "PASS":
                    status = "UNDETERMINED"
                details.append(err)

            for snap in eval_snaps:
                eval_tracks = snap.get("tracks") or []
                pt = snap.get("processingTime")
                wm = snap.get("watermark")
                life_clk, disp_clk = _snapshot_clocks(snap)
                t_s = (life_clk - t0_dt).total_seconds() if t0_dt else 0.0

                # Field/enum contract first — every track in the evaluation snapshot.
                for tr in eval_tracks:
                    ferr = _validate_required_track_fields(tr)
                    if ferr:
                        _fail(
                            {
                                **ferr,
                                "at": pt,
                                "phase": phase_name,
                                "mode": mode,
                                **_clock_meta(life_clk, disp_clk, None),
                            }
                        )

                _, _, f2t, _ = _snapshot_attribution(
                    eval_tracks,
                    intervals=intervals,
                    sn_to_truth=sn_to_truth,
                    global_key_truths=global_key_truths,
                    processing_time=pt,
                    watermark=wm,
                )
                active = _intervals_upto(intervals, wm)
                for truth_id, need_sources_default in expected_stable_entities.items():
                    sched = schedules.get(truth_id) or {
                        "takeoff_s": 0.0,
                        "enabled": set(need_sources_default),
                        "outages": {},
                    }
                    schedule_now = (
                        _expected_sources_at(sched, t_s) if schedules else set(need_sources_default)
                    )
                    # Outage lifecycle bands only when schedule says all enabled sources are down.
                    entity_outaged = bool(sched.get("enabled")) and len(schedule_now) == 0
                    use_life = entity_outaged
                    need_active = _expected_active_sources(
                        truth_id=truth_id,
                        sched=sched,
                        lifecycle_clock=life_clk,
                        t0_dt=t0_dt,
                        delivered_obs=delivered_obs,
                        obs_truth_map=obs_truth_map,
                        rid_fresh_s=rid_fresh_s,
                        coast_s=coast_s,
                        need_sources_default=set(need_sources_default),
                    )

                    # Last obs must already be committed at this frontier (not buffer/future).
                    last_obs = _last_obs_time_for_truth(
                        delivered_obs, obs_truth_map, truth_id, life_clk
                    )
                    if last_obs is None:
                        if any(obs_truth_map.get(o["observationId"]) == truth_id for o in delivered_obs):
                            # Rows without measurementTime (legacy fixtures)
                            last_obs = life_clk
                    matched = [tr for tr in eval_tracks if f2t.get(tr["fusionId"]) == truth_id]
                    if not matched:
                        matched = [
                            tr
                            for tr in eval_tracks
                            if (
                                tr.get("aircraftId")
                                and any(
                                    o.get("aircraftId") == tr.get("aircraftId")
                                    and obs_truth_map.get(o["observationId"]) == truth_id
                                    for o in delivered_obs
                                )
                            )
                        ]

                    if last_obs is None:
                        if matched:
                            details.append(
                                {
                                    "truth_id": truth_id,
                                    "ok": True,
                                    "note": "unexpected_early_track_tolerated",
                                    "at": pt,
                                    "phase": phase_name,
                                    **_clock_meta(life_clk, disp_clk, None),
                                }
                            )
                        else:
                            details.append(
                                {
                                    "truth_id": truth_id,
                                    "ok": True,
                                    "note": "not_yet_detected",
                                    "at": pt,
                                    "phase": phase_name,
                                    "mode": mode,
                                    **_clock_meta(life_clk, disp_clk, None),
                                }
                            )
                        continue

                    life_gap = (life_clk - last_obs).total_seconds()
                    disp_gap = (disp_clk - last_obs).total_seconds()
                    band = _lifecycle_band(life_gap, life)
                    pos_allowed = _display_position_modes(disp_gap, life)
                    meta = _clock_meta(life_clk, disp_clk, last_obs)

                    if not matched:
                        if band["allow_absent"]:
                            details.append(
                                {
                                    "truth_id": truth_id,
                                    "ok": True,
                                    "note": "absent_after_terminate_s",
                                    "gap_s": life_gap,
                                    "display_gap_s": disp_gap,
                                    "terminate_s": life["terminate_s"],
                                    "band": band["band"],
                                    "at": pt,
                                    "phase": phase_name,
                                    **meta,
                                }
                            )
                        else:
                            _fail(
                                {
                                    "truth_id": truth_id,
                                    "error": "missing_entity",
                                    "gap_s": life_gap,
                                    "display_gap_s": disp_gap,
                                    "band": band["band"],
                                    "expected": {
                                        "trackStatus": sorted(band["trackStatus"]),
                                        "positionMode": sorted(pos_allowed),
                                        "allow_absent": False,
                                    },
                                    "at": pt,
                                    "phase": phase_name,
                                    "mode": mode,
                                    **meta,
                                }
                            )
                        continue

                    if len(matched) > 1:
                        _fail(
                            {
                                "truth_id": truth_id,
                                "error": "non_unique_entity",
                                "fusionIds": [t["fusionId"] for t in matched],
                                "at": pt,
                                "phase": phase_name,
                                "mode": mode,
                                **meta,
                            }
                        )

                    for tr in matched:
                        # Skip business rules when this track already failed field contract.
                        if _validate_required_track_fields(tr) is not None:
                            continue
                        st_name = str(tr.get("trackStatus"))
                        pos_mode = str(tr.get("positionMode"))
                        active_srcs = _active_sources_field(tr)

                        # Fresh/active window still uses lifecycle trackStatus + display positionMode.
                        if not use_life and band["band"] == "fresh_or_predict":
                            if st_name not in band["trackStatus"] or pos_mode not in pos_allowed:
                                _fail(
                                    {
                                        "truth_id": truth_id,
                                        "fusionId": tr.get("fusionId"),
                                        "error": "lifecycle_state_mismatch",
                                        "actual": {
                                            "trackStatus": st_name,
                                            "positionMode": pos_mode,
                                            "sources": sorted(active_srcs),
                                        },
                                        "expected": {
                                            "band": band["band"],
                                            "trackStatus": sorted(band["trackStatus"]),
                                            "positionMode": sorted(pos_allowed),
                                            "forbid_fresh_sources": False,
                                        },
                                        "gap_s": life_gap,
                                        "display_gap_s": disp_gap,
                                        "at": pt,
                                        "phase": phase_name,
                                        **meta,
                                    }
                                )
                                continue

                        if use_life or band["band"] != "fresh_or_predict":
                            if band.get("forbid_present"):
                                fresh_looking = st_name in ("tracked", "tentative") or pos_mode in (
                                    "measured_assisted",
                                )
                                if fresh_looking or (active_srcs and band["forbid_fresh_sources"]):
                                    _fail(
                                        {
                                            "truth_id": truth_id,
                                            "fusionId": tr.get("fusionId"),
                                            "error": "present_after_terminate_s",
                                            "actual": {
                                                "trackStatus": st_name,
                                                "positionMode": pos_mode,
                                                "sources": sorted(active_srcs),
                                            },
                                            "gap_s": life_gap,
                                            "display_gap_s": disp_gap,
                                            "at": pt,
                                            "phase": phase_name,
                                            **meta,
                                        }
                                    )
                                else:
                                    details.append(
                                        {
                                            "truth_id": truth_id,
                                            "fusionId": tr.get("fusionId"),
                                            "ok": True,
                                            "note": "transitional_lost_at_terminate",
                                            "trackStatus": st_name,
                                            "positionMode": pos_mode,
                                            "gap_s": life_gap,
                                            "at": pt,
                                            "phase": phase_name,
                                            **meta,
                                        }
                                    )
                                continue
                            status_ok = st_name in band["trackStatus"]
                            pos_ok = pos_mode in pos_allowed
                            if not status_ok or not pos_ok:
                                _fail(
                                    {
                                        "truth_id": truth_id,
                                        "fusionId": tr.get("fusionId"),
                                        "error": "lifecycle_state_mismatch",
                                        "actual": {
                                            "trackStatus": st_name,
                                            "positionMode": pos_mode,
                                            "sources": sorted(active_srcs),
                                        },
                                        "expected": {
                                            "band": band["band"],
                                            "trackStatus": sorted(band["trackStatus"]),
                                            "positionMode": sorted(pos_allowed),
                                            "forbid_fresh_sources": band["forbid_fresh_sources"],
                                        },
                                        "gap_s": life_gap,
                                        "display_gap_s": disp_gap,
                                        "at": pt,
                                        "phase": phase_name,
                                        **meta,
                                    }
                                )
                                continue
                            details.append(
                                {
                                    "truth_id": truth_id,
                                    "fusionId": tr.get("fusionId"),
                                    "ok": True,
                                    "trackStatus": st_name,
                                    "positionMode": pos_mode,
                                    "band": band["band"],
                                    "gap_s": life_gap,
                                    "display_gap_s": disp_gap,
                                    "at": pt,
                                    "phase": phase_name,
                                    **meta,
                                }
                            )
                            # Do not skip active-source TTL checks on outage/lifecycle phases.

                        # Active set (full + lifecycle): sources field only; bidirectional vs TTL.
                        have = active_srcs
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
                        src_diff = _diff_active_sources(need_active, have)
                        if ambiguous:
                            _undetermined(
                                {
                                    "truth_id": truth_id,
                                    "fusionId": tr["fusionId"],
                                    "error": "ambiguous_source_key_at_lastSeen",
                                    "at": pt,
                                    "phase": phase_name,
                                    "mode": mode,
                                    **meta,
                                }
                            )
                        elif foreign:
                            _fail(
                                {
                                    "truth_id": truth_id,
                                    "fusionId": tr["fusionId"],
                                    "error": "sources_mismatch_or_foreign",
                                    "foreign": True,
                                    "need": sorted(need_active),
                                    "have": sorted(have),
                                    "bound_sources_ignored": sorted(_bound_sources(tr)),
                                    "emitting_sources": sorted(schedule_now),
                                    "at": pt,
                                    "phase": phase_name,
                                    "mode": mode,
                                    **meta,
                                }
                            )
                        elif not src_diff["ok"]:
                            _fail(
                                {
                                    "truth_id": truth_id,
                                    "fusionId": tr["fusionId"],
                                    "error": "active_sources_mismatch",
                                    "missing_active": src_diff["missing_active"],
                                    "unexpected_active": src_diff["unexpected_active"],
                                    "expected_active": src_diff["expected_active"],
                                    "actual_active": src_diff["actual_active"],
                                    "bound_sources_ignored": sorted(_bound_sources(tr)),
                                    "emitting_sources": sorted(schedule_now),
                                    "rid_fresh_s": rid_fresh_s,
                                    "coast_s": coast_s,
                                    "at": pt,
                                    "phase": phase_name,
                                    "mode": mode,
                                    **meta,
                                }
                            )
                        else:
                            details.append(
                                {
                                    "truth_id": truth_id,
                                    "fusionId": tr["fusionId"],
                                    "sources": sorted(have),
                                    "expected_active": sorted(need_active),
                                    "ok": True,
                                    "at": pt,
                                    "phase": phase_name,
                                    "mode": mode,
                                    **meta,
                                }
                            )

                if mode == "full":
                    extras = [
                        t
                        for t in eval_tracks
                        if f2t.get(t["fusionId"]) not in expected_stable_entities
                        and (t.get("aircraftId") or f2t.get(t["fusionId"]))
                    ]
                    anon_extras = [
                        t
                        for t in eval_tracks
                        if f2t.get(t["fusionId"]) not in expected_stable_entities
                        and not t.get("aircraftId")
                        and not f2t.get(t["fusionId"])
                        and (t.get("sourceTracks") or t.get("sources"))
                    ]
                    extras = extras + [t for t in anon_extras if t not in extras]
                    if extras:
                        _fail(
                            {
                                "error": "extra_entities",
                                "fusionIds": [t["fusionId"] for t in extras],
                                "at": pt,
                                "phase": phase_name,
                                "mode": mode,
                                **_clock_meta(life_clk, disp_clk, None),
                            }
                        )
            return status, details

        def _deliveries_in_window(t0: str, t1: str) -> int:
            n = 0
            for o in delivered_obs:
                mt = o.get("measurementTime")
                if mt and t0 <= mt <= t1:
                    n += 1
            return n

        phase_statuses: list[str] = []
        for ph in phases:
            pname = str(ph.get("name") or "phase")
            mode = str(ph.get("mode") or "full")
            if not ph.get("available", True):
                missing_required = True
                phase_cover.append(
                    {
                        "name": pname,
                        "available": False,
                        "reason": ph.get("reason"),
                        "result": "NOT_TESTED",
                        "mode": mode,
                    }
                )
                entity_check["details"].append(
                    {"error": "phase_unavailable", "phase": pname, "reason": ph.get("reason")}
                )
                phase_statuses.append("NOT_TESTED")
                continue
            win = ph.get("window")
            if win:
                t0, t1 = win
                windowed = [
                    s
                    for s in snaps
                    if s.get("processingTime") and t0 <= s["processingTime"] <= t1
                ]
                if not windowed:
                    # No snapshots: NOT_TESTED when no deliveries expected; else FAIL.
                    if _deliveries_in_window(t0, t1) == 0 and mode == "lifecycle":
                        pst, pdet = "NOT_TESTED", [
                            {
                                "error": "no_frames_no_deliveries",
                                "window": [t0, t1],
                                "phase": pname,
                                "mode": mode,
                                "note": "startup/outage with no observations yet — not algorithm FAIL",
                            }
                        ]
                    else:
                        pst, pdet = "FAIL", [
                            {"error": "stable_window_no_frames", "window": [t0, t1], "phase": pname, "mode": mode}
                        ]
                    nframes = 0
                else:
                    pst, pdet = _check_snaps(windowed, pname, mode=mode)
                    nframes = len(windowed)
                entity_check["details"].extend(pdet)
                phase_cover.append(
                    {
                        "name": pname,
                        "window": [t0, t1],
                        "frames": nframes,
                        "result": pst,
                        "mode": mode,
                    }
                )
                phase_statuses.append(pst)
            else:
                pst, pdet = _check_snaps([last], pname, mode=mode)
                entity_check["details"].extend(pdet)
                phase_cover.append({"name": pname, "window": None, "result": pst, "mode": mode})
                phase_statuses.append(pst)

        entity_check["phases"] = phase_cover
        entity_check["lifecycle_thresholds"] = life
        # Aggregate independently computed phase results
        if any(s == "FAIL" for s in phase_statuses):
            entity_check["ok"] = False
            entity_check["status"] = "FAIL"
        elif missing_required or any(s == "NOT_TESTED" for s in phase_statuses):
            # Pure NOT_TESTED phases alone must not claim whole-run PASS.
            # If other phases all PASS and missing is only startup-no-evidence, still NOT_TESTED overall
            # when any required phase is untested — except we allow PASS if the only NOT_TESTED are
            # explicitly no_frames_no_deliveries and at least one full/recovery PASS exists.
            only_startup_gaps = all(
                p.get("result") != "NOT_TESTED"
                or any(
                    d.get("error") == "no_frames_no_deliveries" and d.get("phase") == p.get("name")
                    for d in entity_check["details"]
                )
                for p in phase_cover
            )
            has_pass_phase = any(s == "PASS" for s in phase_statuses)
            if only_startup_gaps and has_pass_phase and not missing_required:
                # Startup outage NOT_TESTED + recovery PASS → overall PASS (no algorithm failure)
                if entity_check.get("status") == "PASS":
                    pass
            else:
                entity_check["ok"] = False
                if entity_check.get("status") == "PASS":
                    entity_check["status"] = "NOT_TESTED"
                entity_check["details"].append(
                    {
                        "error": "incomplete_phase_coverage",
                        "note": "required phase unavailable or untested; cannot claim whole-run PASS",
                        "phases": phase_cover,
                    }
                )
        elif any(s == "UNDETERMINED" for s in phase_statuses):
            entity_check["ok"] = False
            if entity_check.get("status") == "PASS":
                entity_check["status"] = "UNDETERMINED"

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
    max_truth_gap_s: float = 0.75,
) -> list[dict]:
    """Eval-side position error only (never fed to frozen engine).

    - committed: last committedHistory lat/lon vs truth at that commit stateTime
    - display: top-level lat/lon vs truth at displayStateTime
    Outside truth time span / beyond max_truth_gap_s → skip (not reported as 0).
    """
    out: list[dict] = []
    by_truth = {k: v for k, v in truth_timeline.items()}
    for tr in tracks_at:
        tid = fusion_to_truth.get(tr["fusionId"])
        if not tid or tid not in by_truth:
            continue
        if mode == "committed":
            hist = tr.get("committedHistory") or []
            if not hist:
                continue
            last = hist[-1]
            ts = last.get("stateTime") or last.get("measurementTime")
            lat = last.get("latitude")
            lon = last.get("longitude")
            scope = "last_committed_point"
        else:
            ts = tr.get("displayStateTime") or tr.get("stateTime")
            lat = tr.get("latitude")
            lon = tr.get("longitude")
            scope = "display_predicted"
        if not ts or lat is None or lon is None:
            continue
        t = _parse(ts).timestamp()
        samples = by_truth[tid]
        if not samples:
            continue
        times = [_parse(s["time"]).timestamp() for s in samples]
        t_min, t_max = min(times), max(times)
        if t < t_min - 1e-9 or t > t_max + 1e-9:
            out.append(
                {
                    "truth_id": tid,
                    "fusionId": tr["fusionId"],
                    "error_m": None,
                    "mode": mode,
                    "scope": scope,
                    "computable": False,
                    "reason": "estimate_time_outside_truth_span",
                }
            )
            continue
        best = min(samples, key=lambda s: abs(_parse(s["time"]).timestamp() - t))
        gap = abs(_parse(best["time"]).timestamp() - t)
        if gap > max_truth_gap_s:
            out.append(
                {
                    "truth_id": tid,
                    "fusionId": tr["fusionId"],
                    "error_m": None,
                    "mode": mode,
                    "scope": scope,
                    "computable": False,
                    "reason": f"truth_gap_{gap:.3f}s_exceeds_{max_truth_gap_s}s",
                }
            )
            continue
        dlat = (float(lat) - best["lat"]) * 111_320.0
        dlon = (float(lon) - best["lon"]) * 111_320.0 * math.cos(math.radians(best["lat"]))
        err = math.hypot(dlat, dlon)
        out.append(
            {
                "truth_id": tid,
                "fusionId": tr["fusionId"],
                "error_m": err,
                "mode": mode,
                "scope": scope,
                "computable": True,
                "truth_gap_s": gap,
            }
        )
    return out


def count_id_exchanges(
    snapshots: list[dict],
    *,
    sn_to_truth: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Timeline ID exchange from snapshot tracks (not reason-string heuristics).

    Cross-machine exchange: two truths swap fusionIds between consecutive evaluated frames.
    Same-truth recreate: truth changes fusionId without reciprocal swap (split/rebuild).

    Scope: only tracks with aircraftId→sn_to_truth mapping. Anonymous / unmapped
    targets are outside this metric. Fewer than 2 mappable frames → null (not 0).
    """
    scope_note = (
        "统计范围=仅 aircraftId→sn_to_truth 可映射子集；"
        "匿名/未映射目标不在本指标内，不得解读为全场景已验证0交换"
    )
    if not snapshots:
        return {
            "id_exchange_count": None,
            "cross_exchange_count": None,
            "recreate_count": None,
            "frames_mapped": 0,
            "computable": False,
            "note": f"不可计算：无快照；{scope_note}",
        }
    sn_to_truth = sn_to_truth or {}
    # truth_id -> fusionId per frame (only when aircraftId maps)
    series: list[dict[str, str]] = []
    for snap in snapshots:
        own: dict[str, str] = {}
        for tr in snap.get("tracks") or []:
            aid = tr.get("aircraftId")
            fid = tr.get("fusionId")
            if not aid or not fid:
                continue
            tid = sn_to_truth.get(aid)
            if not tid:
                continue
            # first wins; ambiguous same-truth multi-fid → skip counting that frame for this truth
            if tid in own and own[tid] != fid:
                own.pop(tid, None)
                continue
            own[tid] = fid
        if own:
            series.append(own)
    if len(series) < 2:
        reason = (
            "无可映射身份（frames_mapped=0）"
            if len(series) == 0
            else "可映射帧不足2、无有效时间转换（frames_mapped=1）"
        )
        return {
            "id_exchange_count": None,
            "cross_exchange_count": None,
            "recreate_count": None,
            "frames_mapped": len(series),
            "computable": False,
            "note": f"不可计算：{reason}；有快照≠已完成测量；{scope_note}",
        }
    cross = 0
    recreate = 0
    for i in range(1, len(series)):
        prev, cur = series[i - 1], series[i]
        changed = []
        for tid, fid in cur.items():
            if tid in prev and prev[tid] != fid:
                changed.append((tid, prev[tid], fid))
        used = set()
        for tid_a, old_a, new_a in changed:
            if tid_a in used:
                continue
            partner = None
            for tid_b, old_b, new_b in changed:
                if tid_b == tid_a or tid_b in used:
                    continue
                if old_b == new_a and new_b == old_a:
                    partner = tid_b
                    break
            if partner is not None:
                cross += 1
                used.add(tid_a)
                used.add(partner)
            else:
                recreate += 1
                used.add(tid_a)
    return {
        "id_exchange_count": cross,
        "cross_exchange_count": cross,
        "recreate_count": recreate,
        "frames_mapped": len(series),
        "computable": True,
        "note": (
            f"跨机交换=互为对换的 fusionId；同机重建计入 recreate_count，不并入 id_exchange_count；"
            f"frames_mapped={len(series)}；{scope_note}"
        ),
    }
