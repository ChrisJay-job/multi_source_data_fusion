"""TASK-005 hard challenge scenario builders + geometry validation.

Does not modify association/KF. Truth IDs stay evaluator-only.
Geometry uses structured challenge_intent — never parse scenario names for spacing.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from .scenario import (
    AircraftSpec,
    Scenario,
    SourceNoise,
    Waypoint,
    _path_at,
    generate_observations,
    preset_seven_aircraft,
)


# Isolated region origins (meters) — keep groups far apart vs gate distances.
REG = {
    "cross_sim": (3000.0, 0.0),
    "cross_async": (3000.0, 2500.0),
    "near2": (0.0, 3500.0),
    "near5": (800.0, 3500.0),
    "near10": (1600.0, 3500.0),
    "near30": (2400.0, 3500.0),
    "near100": (3600.0, 3500.0),
    "overtake": (0.0, 5000.0),
    "cross_outage": (5500.0, 0.0),
    "cross_swap": (5500.0, 2500.0),
}


def _src(
    *,
    rid: bool = False,
    spectrum: bool = False,
    radar: bool = False,
    rid_id: bool = True,
    spectrum_id: bool = True,
    radar_swap: Optional[float] = None,
    rid_outage: Optional[list[tuple[float, float]]] = None,
    noise_scale: float = 1.0,
) -> dict[str, SourceNoise]:
    return {
        "rid": SourceNoise(
            period_s=1.0,
            pos_noise_m=3.0 * noise_scale,
            enabled=rid,
            emit_aircraft_id=rid_id,
            outage=list(rid_outage or []),
        ),
        "spectrum": SourceNoise(
            period_s=1.2,
            pos_noise_m=8.0 * noise_scale,
            bias_east_m=2.0 if spectrum else 0.0,
            enabled=spectrum,
            emit_aircraft_id=spectrum_id,
        ),
        "radar": SourceNoise(
            period_s=2.0,
            pos_noise_m=15.0 * noise_scale,
            enabled=radar,
            emit_aircraft_id=False,
            radar_id_swap_at_s=radar_swap,
        ),
    }


def _shift(wps: list[Waypoint], ox: float, oy: float) -> list[Waypoint]:
    return [Waypoint(w.x_m + ox, w.y_m + oy, w.dwell_s) for w in wps]


def _pair_min_distance(
    positions: dict[str, list[tuple[float, float, float]]],
    la: str,
    lb: str,
) -> tuple[Optional[float], Optional[float]]:
    min_d, min_at = None, None
    for (t1, x1, y1), (_t2, x2, y2) in zip(positions[la], positions[lb]):
        d = math.hypot(x1 - x2, y1 - y2)
        if min_d is None or d < min_d:
            min_d, min_at = d, t1
    return min_d, min_at


def _arrival_at_point(
    positions: dict[str, list[tuple[float, float, float]]],
    label: str,
    ox: float,
    oy: float,
) -> Optional[float]:
    best_t, best_d = None, None
    for t, x, y in positions[label]:
        d = math.hypot(x - ox, y - oy)
        if best_d is None or d < best_d:
            best_d, best_t = d, t
    return best_t


def _sample_positions(scenario: Scenario, step: float = 0.1) -> dict[str, list[tuple[float, float, float]]]:
    times: list[float] = []
    t = 0.0
    while t <= scenario.duration_s + 1e-9:
        times.append(t)
        t += step
    positions: dict[str, list[tuple[float, float, float]]] = {a.label: [] for a in scenario.aircraft}
    for ac in scenario.aircraft:
        for tt in times:
            x, y = _path_at(ac, tt - ac.takeoff_offset_s)
            positions[ac.label].append((tt, x, y))
    return positions


def validate_challenge_geometry(scenario: Scenario) -> dict[str, Any]:
    """Validate geometry from challenge_intent metadata (not scenario name tokens)."""
    intent = scenario.challenge_intent or {}
    out: dict[str, Any] = {
        "name": scenario.name,
        "ok": True,
        "checks": [],
        "verification_status": "verified",
        "identity_mode": scenario.identity_mode,
    }
    positions = _sample_positions(scenario)

    labels = [a.label for a in scenario.aircraft]
    min_d = None
    min_at = None
    min_pair = None
    for i, la in enumerate(labels):
        for lb in labels[i + 1 :]:
            d, at = _pair_min_distance(positions, la, lb)
            if d is not None and (min_d is None or d < min_d):
                min_d, min_at, min_pair = d, at, (la, lb)
    out["min_truth_distance_m"] = min_d
    out["min_truth_distance_at_s"] = min_at
    out["min_truth_distance_pair"] = list(min_pair) if min_pair else None

    kinds = intent.get("groups") or ([intent] if intent.get("kind") else [])
    if not kinds:
        out["ok"] = False
        out["verification_status"] = "unverified"
        out["checks"].append(
            {
                "kind": "missing_challenge_intent",
                "ok": False,
                "note": "checks 为空→未验证；不宣称挑战已验证",
            }
        )
        return out

    for g in kinds:
        kind = g.get("kind")
        pair = list(g.get("pair_labels") or g.get("labels") or [])
        if kind == "simultaneous_cross" and len(pair) >= 2:
            d, at = _pair_min_distance(positions, pair[0], pair[1])
            meet = g.get("meet_xy") or [0.0, 0.0]
            t_a = _arrival_at_point(positions, pair[0], meet[0], meet[1])
            t_b = _arrival_at_point(positions, pair[1], meet[0], meet[1])
            ok = d is not None and d < float(g.get("max_min_distance_m", 1.0))
            if t_a is not None and t_b is not None:
                ok = ok and abs(t_a - t_b) <= float(g.get("max_arrival_delta_s", 0.5))
            out["checks"].append(
                {
                    "kind": "simultaneous_cross",
                    "ok": ok,
                    "pair": pair,
                    "min_d": d,
                    "at": at,
                    "arrival_a_s": t_a,
                    "arrival_b_s": t_b,
                    "arrival_delta_s": None if t_a is None or t_b is None else abs(t_a - t_b),
                }
            )
            out["ok"] = out["ok"] and ok
        elif kind == "async_cross" and len(pair) >= 2:
            d, at = _pair_min_distance(positions, pair[0], pair[1])
            meet = g.get("meet_xy") or [0.0, 0.0]
            t_a = _arrival_at_point(positions, pair[0], meet[0], meet[1])
            t_b = _arrival_at_point(positions, pair[1], meet[0], meet[1])
            delta = None if t_a is None or t_b is None else abs(t_a - t_b)
            ok = (
                d is not None
                and d > float(g.get("min_min_distance_m", 15.0))
                and delta is not None
                and delta >= float(g.get("min_arrival_delta_s", 4.0))
            )
            out["checks"].append(
                {
                    "kind": "async_cross",
                    "ok": ok,
                    "pair": pair,
                    "min_d": d,
                    "at": at,
                    "arrival_delta_s": delta,
                }
            )
            out["ok"] = out["ok"] and ok
        elif kind == "near_parallel" and len(pair) >= 2:
            target = float(g.get("spacing_m", 2.0))
            d, at = _pair_min_distance(positions, pair[0], pair[1])
            ok = d is not None and abs(d - target) < float(g.get("tol_m", 0.5))
            out["checks"].append(
                {
                    "kind": "near_parallel_spacing",
                    "ok": ok,
                    "pair": pair,
                    "min_d": d,
                    "target": target,
                    "at": at,
                }
            )
            out["ok"] = out["ok"] and ok
        elif kind == "overtake" and len(pair) >= 2:
            a, b = pair[0], pair[1]
            xs_a = [p[1] for p in positions[a]]
            xs_b = [p[1] for p in positions[b]]
            early = xs_b[5] < xs_a[5]
            late = xs_b[-5] > xs_a[-5]
            ok = early and late
            out["checks"].append(
                {
                    "kind": "overtake_order_swap",
                    "ok": ok,
                    "pair": pair,
                    "early_behind": early,
                    "late_ahead": late,
                }
            )
            out["ok"] = out["ok"] and ok
        elif kind == "rid_outage_near_cross":
            win = g.get("outage_window_s") or [10.0, 16.0]
            ac = next((x for x in scenario.aircraft if x.label == g.get("aircraft")), None)
            outages = list((ac.sources.get("rid").outage if ac and ac.sources.get("rid") else []) or [])
            ok = any(abs(o[0] - win[0]) < 0.5 and abs(o[1] - win[1]) < 0.5 for o in outages)
            if ok and ac is not None:
                from datetime import datetime

                bundle = generate_observations(scenario)
                t0 = datetime.fromisoformat(bundle["t0"])
                omap = bundle.get("obs_truth_map") or {}
                rid_ts = []
                for o in bundle["observations"]:
                    if o.get("source") != "rid":
                        continue
                    if omap.get(o["observationId"]) != ac.truth_id:
                        continue
                    mt = datetime.fromisoformat(o["measurementTime"])
                    rid_ts.append((mt - t0).total_seconds())
                gap_ok = not any(win[0] <= t <= win[1] for t in rid_ts)
                ok = ok and gap_ok
            out["checks"].append(
                {
                    "kind": "rid_outage_near_cross",
                    "ok": ok,
                    "aircraft": g.get("aircraft"),
                    "outage_window_s": win,
                }
            )
            out["ok"] = out["ok"] and ok
        elif kind == "radar_id_swap_near_cross":
            swap_at = float(g.get("swap_at_s", 11.0))
            ac = next((x for x in scenario.aircraft if x.label == g.get("aircraft")), None)
            cfg_swap = ac.sources.get("radar").radar_id_swap_at_s if ac and ac.sources.get("radar") else None
            ok = cfg_swap is not None and abs(float(cfg_swap) - swap_at) < 0.5
            if ok and ac is not None:
                bundle = generate_observations(scenario)
                omap = bundle.get("obs_truth_map") or {}
                tids = [
                    o.get("sourceTrackId")
                    for o in bundle["observations"]
                    if o.get("source") == "radar" and omap.get(o["observationId"]) == ac.truth_id
                ]
                ok = ok and len(set(tids)) >= 2
            out["checks"].append(
                {
                    "kind": "radar_id_swap_near_cross",
                    "ok": ok,
                    "aircraft": g.get("aircraft"),
                    "swap_at_s": swap_at,
                }
            )
            out["ok"] = out["ok"] and ok
        else:
            out["checks"].append({"kind": kind or "unknown", "ok": False, "note": "未识别的 intent"})
            out["ok"] = False

    if not out["checks"]:
        out["ok"] = False
        out["verification_status"] = "unverified"
    elif not out["ok"]:
        out["verification_status"] = "failed"
    return out


def actual_identity_sets(scenario: Scenario) -> dict[str, Any]:
    """AircraftId sets that actually enter the algorithm (not just config flags)."""
    bundle = generate_observations(scenario)
    by_ac: dict[str, set] = {a.label: set() for a in scenario.aircraft}
    tid_to_label = {a.truth_id: a.label for a in scenario.aircraft}
    omap = bundle.get("obs_truth_map") or {}
    for o in bundle["observations"]:
        lab = tid_to_label.get(omap.get(o["observationId"]) or "")
        if not lab:
            continue
        aid = o.get("aircraftId")
        if aid:
            by_ac[lab].add(aid)
    return {
        "identity_mode": scenario.identity_mode,
        "per_aircraft_ids": {k: sorted(v) for k, v in by_ac.items()},
        "aircraft_with_id": sorted(k for k, v in by_ac.items() if v),
        "aircraft_without_id": sorted(k for k, v in by_ac.items() if not v),
    }


def _cross_pair(
    *,
    labels: tuple[str, str],
    truths: tuple[str, str],
    ox: float,
    oy: float,
    speed: float,
    half: float,
    t_meet: float,
    identity_mode: str,
    rid_outage_h: Optional[list[tuple[float, float]]] = None,
    radar_swap_at: Optional[float] = None,
    async_delta_s: float = 0.0,
) -> list[AircraftSpec]:
    dist = half
    travel = dist / max(speed, 1e-3)
    h_takeoff = max(0.0, t_meet - travel)
    i_takeoff = max(0.0, t_meet + async_delta_s - travel)
    h_lab, i_lab = labels
    h_tid, i_tid = truths

    if identity_mode == "mixed":
        # Meaningful: identity aircraft + anonymous radar (labeled mixed, not both_id).
        h_sn = f"SN-{h_lab}-H"
        i_sn = None
        h_sources = _src(rid=True, spectrum=False, radar=False, rid_id=True, rid_outage=rid_outage_h)
        i_sources = _src(rid=False, spectrum=False, radar=True, rid_id=False, radar_swap=radar_swap_at)
    elif identity_mode == "both_id":
        # Same source mix on both; only reliable distinct RIDs.
        h_sn, i_sn = f"SN-{h_lab}-H", f"SN-{i_lab}-I"
        h_sources = _src(rid=True, spectrum=True, radar=False, rid_id=True, spectrum_id=False, rid_outage=rid_outage_h)
        i_sources = _src(rid=True, spectrum=True, radar=False, rid_id=True, spectrum_id=False)
    else:  # both_anon — same sources/noise/period as both_id; only emit_aircraft_id off
        h_sn, i_sn = None, None
        h_sources = _src(rid=True, spectrum=True, radar=False, rid_id=False, spectrum_id=False, rid_outage=rid_outage_h)
        i_sources = _src(rid=True, spectrum=True, radar=False, rid_id=False, spectrum_id=False)

    return [
        AircraftSpec(
            label=h_lab,
            truth_id=h_tid,
            rid_sn=h_sn,
            waypoints=_shift([Waypoint(-half, 0), Waypoint(half, 0)], ox, oy),
            speed_mps=speed,
            takeoff_offset_s=h_takeoff,
            sources=h_sources,
        ),
        AircraftSpec(
            label=i_lab,
            truth_id=i_tid,
            rid_sn=i_sn,
            waypoints=_shift([Waypoint(0, -half), Waypoint(0, half)], ox, oy),
            speed_mps=speed,
            takeoff_offset_s=i_takeoff,
            sources=i_sources,
        ),
    ]


def _parallel_pair(
    *,
    labels: tuple[str, str],
    truths: tuple[str, str],
    ox: float,
    oy: float,
    spacing_m: float,
    speed: float = 10.0,
    length: float = 400.0,
    identity_mode: str,
) -> list[AircraftSpec]:
    a, b = labels
    ta, tb = truths
    if identity_mode == "mixed":
        # Keep radar-pair contrast as mixed (not a fair identity A/B).
        return [
            AircraftSpec(
                label=a,
                truth_id=ta,
                rid_sn=f"SN-{a}",
                waypoints=_shift([Waypoint(0, 0), Waypoint(length, 0)], ox, oy),
                speed_mps=speed,
                sources=_src(rid=True, spectrum=False, radar=False, rid_id=True),
            ),
            AircraftSpec(
                label=b,
                truth_id=tb,
                rid_sn=None,
                waypoints=_shift([Waypoint(0, spacing_m), Waypoint(length, spacing_m)], ox, oy),
                speed_mps=speed,
                sources=_src(rid=False, spectrum=False, radar=True, rid_id=False),
            ),
        ]
    emit = identity_mode == "both_id"
    # Fair compare: identical RID+radar sources/noise/period; only emit_aircraft_id + rid_sn differ.
    return [
        AircraftSpec(
            label=a,
            truth_id=ta,
            rid_sn=f"SN-{a}" if emit else None,
            waypoints=_shift([Waypoint(0, 0), Waypoint(length, 0)], ox, oy),
            speed_mps=speed,
            sources=_src(rid=True, spectrum=False, radar=True, rid_id=emit),
        ),
        AircraftSpec(
            label=b,
            truth_id=tb,
            rid_sn=f"SN-{b}" if emit else None,
            waypoints=_shift([Waypoint(0, spacing_m), Waypoint(length, spacing_m)], ox, oy),
            speed_mps=speed,
            sources=_src(rid=True, spectrum=False, radar=True, rid_id=emit),
        ),
    ]


def _overtake_pair(
    *,
    labels: tuple[str, str],
    truths: tuple[str, str],
    ox: float,
    oy: float,
    identity_mode: str,
) -> list[AircraftSpec]:
    a, b = labels
    ta, tb = truths
    length = 600.0
    v_slow, v_fast = 8.0, 14.0
    if identity_mode == "mixed":
        return [
            AircraftSpec(
                label=a,
                truth_id=ta,
                rid_sn=f"SN-{a}",
                waypoints=_shift([Waypoint(0, 0), Waypoint(length, 0)], ox, oy),
                speed_mps=v_slow,
                sources=_src(rid=True, spectrum=True, radar=False, rid_id=True, spectrum_id=False),
            ),
            AircraftSpec(
                label=b,
                truth_id=tb,
                rid_sn=None,
                waypoints=_shift([Waypoint(-80, 0), Waypoint(length - 80, 0)], ox, oy),
                speed_mps=v_fast,
                sources=_src(rid=False, spectrum=False, radar=True, rid_id=False),
            ),
        ]
    emit = identity_mode == "both_id"
    return [
        AircraftSpec(
            label=a,
            truth_id=ta,
            rid_sn=f"SN-{a}" if emit else None,
            waypoints=_shift([Waypoint(0, 0), Waypoint(length, 0)], ox, oy),
            speed_mps=v_slow,
            sources=_src(rid=True, spectrum=True, radar=False, rid_id=emit, spectrum_id=False),
        ),
        AircraftSpec(
            label=b,
            truth_id=tb,
            rid_sn=f"SN-{b}" if emit else None,
            waypoints=_shift([Waypoint(-80, 0), Waypoint(length - 80, 0)], ox, oy),
            speed_mps=v_fast,
            sources=_src(rid=True, spectrum=True, radar=False, rid_id=emit, spectrum_id=False),
        ),
    ]


def _tag(mode: str) -> str:
    return {"both_id": "with_id", "both_anon": "anon", "mixed": "mixed"}.get(mode, mode)


def preset_challenge_simultaneous_cross(*, identity_mode: str = "both_id", seed: int = 20261020) -> Scenario:
    ox, oy = REG["cross_sim"]
    ac = _cross_pair(
        labels=("H", "I"),
        truths=("TRUTH-H", "TRUTH-I"),
        ox=ox,
        oy=oy,
        speed=12.0,
        half=120.0,
        t_meet=12.0,
        identity_mode=identity_mode,
    )
    return Scenario(
        name=f"challenge_simultaneous_cross_{_tag(identity_mode)}",
        seed=seed,
        duration_s=30.0,
        opaque_track_ids=True,
        notes=f"同时交叉 H×I；identity_mode={identity_mode}（mixed=身份机+匿名雷达）。仿真参数≠设备精度。",
        aircraft=ac,
        challenge_group="cross_sim",
        identity_mode=identity_mode,
        challenge_intent={
            "kind": "simultaneous_cross",
            "pair_labels": ["H", "I"],
            "meet_xy": [ox, oy],
            "max_min_distance_m": 1.0,
            "max_arrival_delta_s": 0.5,
        },
    )


def preset_challenge_async_cross(*, identity_mode: str = "both_id", seed: int = 20261021) -> Scenario:
    ox, oy = REG["cross_async"]
    ac = _cross_pair(
        labels=("H2", "I2"),
        truths=("TRUTH-H2", "TRUTH-I2"),
        ox=ox,
        oy=oy,
        speed=12.0,
        half=120.0,
        t_meet=12.0,
        identity_mode=identity_mode,
        async_delta_s=6.0,
    )
    return Scenario(
        name=f"challenge_async_cross_{_tag(identity_mode)}",
        seed=seed,
        duration_s=32.0,
        opaque_track_ids=True,
        notes=f"错时交叉：几何交点相同，到达差≈6s；identity_mode={identity_mode}",
        aircraft=ac,
        challenge_group="cross_async",
        identity_mode=identity_mode,
        challenge_intent={
            "kind": "async_cross",
            "pair_labels": ["H2", "I2"],
            "meet_xy": [ox, oy],
            "min_min_distance_m": 15.0,
            "min_arrival_delta_s": 4.0,
        },
    )


def preset_challenge_near_parallel(
    *,
    spacing_m: float = 2.0,
    identity_mode: str = "both_id",
    seed: int = 20261022,
) -> Scenario:
    key = {2.0: "near2", 5.0: "near5", 10.0: "near10", 30.0: "near30", 100.0: "near100"}.get(spacing_m, "near2")
    ox, oy = REG[key]
    lab = f"N{int(spacing_m)}"
    pair = (f"{lab}a", f"{lab}b")
    return Scenario(
        name=f"challenge_near_parallel_{int(spacing_m)}m_{_tag(identity_mode)}",
        seed=seed,
        duration_s=35.0,
        opaque_track_ids=True,
        notes=(
            f"近距平行 {spacing_m}m 同向同速；identity_mode={identity_mode}。"
            "both_id/both_anon 同源组合仅切换 emit_aircraft_id；mixed 为 RID+匿名雷达对照。"
            "2m 小于仿真噪声尺度时可能不可唯一裁决。"
        ),
        aircraft=_parallel_pair(
            labels=pair,
            truths=(f"TRUTH-{lab}A", f"TRUTH-{lab}B"),
            ox=ox,
            oy=oy,
            spacing_m=spacing_m,
            identity_mode=identity_mode,
        ),
        challenge_group=key,
        focus_hint={"spacing_m": spacing_m, "zoom": "local", "pair_labels": list(pair)},
        identity_mode=identity_mode,
        challenge_intent={
            "kind": "near_parallel",
            "spacing_m": spacing_m,
            "pair_labels": list(pair),
            "tol_m": 0.5,
        },
    )


def preset_challenge_overtake(*, identity_mode: str = "both_id", seed: int = 20261023) -> Scenario:
    ox, oy = REG["overtake"]
    return Scenario(
        name=f"challenge_overtake_{_tag(identity_mode)}",
        seed=seed,
        duration_s=45.0,
        opaque_track_ids=True,
        notes=f"同向追越 L 慢 / M 快；identity_mode={identity_mode}",
        aircraft=_overtake_pair(
            labels=("L", "M"),
            truths=("TRUTH-L", "TRUTH-M"),
            ox=ox,
            oy=oy,
            identity_mode=identity_mode,
        ),
        challenge_group="overtake",
        identity_mode=identity_mode,
        challenge_intent={"kind": "overtake", "pair_labels": ["L", "M"]},
    )


def preset_challenge_cross_rid_outage(*, identity_mode: str = "mixed", seed: int = 20261024) -> Scenario:
    ox, oy = REG["cross_outage"]
    # Outage challenges keep mixed geometry (RID outage + other sources); mode label explicit.
    ac = _cross_pair(
        labels=("Ho", "Io"),
        truths=("TRUTH-Ho", "TRUTH-Io"),
        ox=ox,
        oy=oy,
        speed=12.0,
        half=120.0,
        t_meet=12.0,
        identity_mode="mixed" if identity_mode != "both_anon" else "both_anon",
        rid_outage_h=[(10.0, 16.0)],
    )
    if identity_mode == "both_id":
        ac = _cross_pair(
            labels=("Ho", "Io"),
            truths=("TRUTH-Ho", "TRUTH-Io"),
            ox=ox,
            oy=oy,
            speed=12.0,
            half=120.0,
            t_meet=12.0,
            identity_mode="both_id",
            rid_outage_h=[(10.0, 16.0)],
        )
    # Spectrum remains during RID outage
    ac[0].sources["spectrum"] = SourceNoise(
        period_s=1.2, pos_noise_m=8.0, bias_east_m=2.0, enabled=True, emit_aircraft_id=False
    )
    mode = identity_mode
    return Scenario(
        name=f"challenge_cross_rid_outage_{_tag(mode)}",
        seed=seed,
        duration_s=30.0,
        opaque_track_ids=True,
        notes=f"交叉邻域 RID 短暂停报(10–16s)，保留频谱/他机源；identity_mode={mode}",
        aircraft=ac,
        challenge_group="cross_outage",
        identity_mode=mode,
        challenge_intent={
            "groups": [
                {
                    "kind": "simultaneous_cross",
                    "pair_labels": ["Ho", "Io"],
                    "meet_xy": [ox, oy],
                    "max_min_distance_m": 1.0,
                    "max_arrival_delta_s": 0.5,
                },
                {"kind": "rid_outage_near_cross", "aircraft": "Ho", "outage_window_s": [10.0, 16.0]},
            ]
        },
    )


def preset_challenge_cross_radar_swap(*, identity_mode: str = "mixed", seed: int = 20261025) -> Scenario:
    ox, oy = REG["cross_swap"]
    # Radar swap requires a radar aircraft → use mixed geometry; both_id/anon use mixed sources but still swap on Io.
    ac = _cross_pair(
        labels=("Hs", "Is"),
        truths=("TRUTH-Hs", "TRUTH-Is"),
        ox=ox,
        oy=oy,
        speed=12.0,
        half=120.0,
        t_meet=12.0,
        identity_mode="mixed",
        radar_swap_at=11.0,
    )
    if identity_mode == "both_anon":
        ac[0].rid_sn = None
        ac[0].sources["rid"].emit_aircraft_id = False
    mode = "mixed" if identity_mode == "both_id" else identity_mode
    # Keep name with_id for legacy matrix key when both_id requested → label as mixed in metadata
    tag = _tag(identity_mode if identity_mode != "both_id" else "mixed")
    if identity_mode == "both_id":
        tag = "with_id"  # legacy key; identity_mode field says mixed
        mode = "mixed"
    return Scenario(
        name=f"challenge_cross_radar_swap_{tag}",
        seed=seed,
        duration_s=30.0,
        opaque_track_ids=True,
        notes=f"交叉时雷达局部号更换；identity_mode={mode}（雷达挑战不做伪造 SN）",
        aircraft=ac,
        challenge_group="cross_swap",
        identity_mode=mode,
        challenge_intent={
            "groups": [
                {
                    "kind": "simultaneous_cross",
                    "pair_labels": ["Hs", "Is"],
                    "meet_xy": [ox, oy],
                    "max_min_distance_m": 1.0,
                    "max_arrival_delta_s": 0.5,
                },
                {"kind": "radar_id_swap_near_cross", "aircraft": "Is", "swap_at_s": 11.0},
            ]
        },
    )


def preset_seven_plus_challenges(*, identity_mode: str = "both_id", seed: int = 20261026) -> Scenario:
    base = preset_seven_aircraft()
    ox, oy = REG["cross_sim"]
    hi = _cross_pair(
        labels=("H", "I"),
        truths=("TRUTH-H", "TRUTH-I"),
        ox=ox,
        oy=oy,
        speed=12.0,
        half=100.0,
        t_meet=14.0,
        identity_mode=identity_mode,
    )
    ox2, oy2 = REG["near2"]
    jk = _parallel_pair(
        labels=("J", "K"),
        truths=("TRUTH-J", "TRUTH-K"),
        ox=ox2,
        oy=oy2,
        spacing_m=2.0,
        identity_mode=identity_mode,
    )
    ox3, oy3 = REG["overtake"]
    lm = _overtake_pair(
        labels=("L", "M"),
        truths=("TRUTH-L", "TRUTH-M"),
        ox=ox3,
        oy=oy3,
        identity_mode=identity_mode,
    )
    return Scenario(
        name=f"seven_plus_challenges_{_tag(identity_mode)}",
        seed=seed,
        duration_s=45.0,
        opaque_track_ids=True,
        notes=(
            "七机 A–G 保留 + 挑战组 H/I 同时交叉、J/K 2m 平行、L/M 追越；"
            "各组区域隔离。页面提供基础七机/H-I/J-K/L-M/全图聚焦。"
        ),
        aircraft=list(base.aircraft) + hi + jk + lm,
        challenge_group="all",
        focus_hint={
            "groups": {
                "seven": list("ABCDEFG"),
                "cross_sim": ["H", "I"],
                "near2": ["J", "K"],
                "overtake": ["L", "M"],
                "all": list("ABCDEFGHIJKLM"),
            },
            "spacing_m": 2.0,
            "pair_labels": ["J", "K"],
        },
        identity_mode=identity_mode,
        challenge_intent={
            "groups": [
                {
                    "kind": "simultaneous_cross",
                    "pair_labels": ["H", "I"],
                    "meet_xy": [ox, oy],
                    "max_min_distance_m": 1.0,
                    "max_arrival_delta_s": 0.5,
                },
                {"kind": "near_parallel", "spacing_m": 2.0, "pair_labels": ["J", "K"], "tol_m": 0.5},
                {"kind": "overtake", "pair_labels": ["L", "M"]},
            ]
        },
    )


def _near_builders():
    out = {}
    seeds = {
        2.0: (20261022, 20261022),
        5.0: (20261027, 20261028),
        10.0: (20261029, 20261030),
        30.0: (20261031, 20261032),
        100.0: (20261033, 20261034),
    }
    for sp, (s_id, s_anon) in seeds.items():
        out[f"challenge_near_parallel_{int(sp)}m_with_id"] = (
            lambda sp=sp, s=s_id: preset_challenge_near_parallel(spacing_m=sp, identity_mode="both_id", seed=s)
        )
        out[f"challenge_near_parallel_{int(sp)}m_anon"] = (
            lambda sp=sp, s=s_anon: preset_challenge_near_parallel(spacing_m=sp, identity_mode="both_anon", seed=s)
        )
        out[f"challenge_near_parallel_{int(sp)}m_mixed"] = (
            lambda sp=sp, s=s_id + 50: preset_challenge_near_parallel(spacing_m=sp, identity_mode="mixed", seed=s)
        )
    return out


CHALLENGE_PRESET_BUILDERS = {
    "challenge_simultaneous_cross_with_id": lambda: preset_challenge_simultaneous_cross(identity_mode="both_id"),
    "challenge_simultaneous_cross_anon": lambda: preset_challenge_simultaneous_cross(identity_mode="both_anon"),
    "challenge_simultaneous_cross_mixed": lambda: preset_challenge_simultaneous_cross(identity_mode="mixed", seed=20261040),
    "challenge_async_cross_with_id": lambda: preset_challenge_async_cross(identity_mode="both_id"),
    "challenge_async_cross_anon": lambda: preset_challenge_async_cross(identity_mode="both_anon"),
    "challenge_async_cross_mixed": lambda: preset_challenge_async_cross(identity_mode="mixed", seed=20261041),
    **_near_builders(),
    "challenge_overtake_with_id": lambda: preset_challenge_overtake(identity_mode="both_id"),
    "challenge_overtake_anon": lambda: preset_challenge_overtake(identity_mode="both_anon"),
    "challenge_overtake_mixed": lambda: preset_challenge_overtake(identity_mode="mixed", seed=20261042),
    "challenge_cross_rid_outage_with_id": lambda: preset_challenge_cross_rid_outage(identity_mode="both_id"),
    "challenge_cross_rid_outage_anon": lambda: preset_challenge_cross_rid_outage(identity_mode="both_anon"),
    "challenge_cross_rid_outage_mixed": lambda: preset_challenge_cross_rid_outage(identity_mode="mixed", seed=20261043),
    "challenge_cross_radar_swap_with_id": lambda: preset_challenge_cross_radar_swap(identity_mode="both_id"),
    "challenge_cross_radar_swap_anon": lambda: preset_challenge_cross_radar_swap(identity_mode="both_anon"),
    "challenge_cross_radar_swap_mixed": lambda: preset_challenge_cross_radar_swap(identity_mode="mixed", seed=20261044),
    "seven_plus_challenges_with_id": lambda: preset_seven_plus_challenges(identity_mode="both_id"),
    "seven_plus_challenges_anon": lambda: preset_seven_plus_challenges(identity_mode="both_anon"),
    "seven_plus_challenges_mixed": lambda: preset_seven_plus_challenges(identity_mode="mixed", seed=20261045),
}
