"""Synthetic multi-aircraft scenarios. Truth IDs stay in evaluator metadata only."""
from __future__ import annotations

import json
import math
import random
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


ORIGIN_LAT = 39.13
ORIGIN_LON = 117.20
M_PER_DEG_LAT = 111_320.0


def _lon_scale(lat: float) -> float:
    return M_PER_DEG_LAT * math.cos(math.radians(lat))


@dataclass
class Waypoint:
    x_m: float
    y_m: float
    dwell_s: float = 0.0


@dataclass
class SourceNoise:
    period_s: float = 1.0
    pos_noise_m: float = 5.0
    bias_east_m: float = 0.0
    bias_north_m: float = 0.0
    delay_s: float = 0.0
    drop_prob: float = 0.0
    reorder_window_s: float = 0.0  # jitters receivedAt / delivery order only
    clock_bias_s: float = 0.0  # explicit measurement clock bias (separate from reorder)
    outage: list[tuple[float, float]] = field(default_factory=list)
    radar_id_swap_at_s: Optional[float] = None  # configurable radar track-id swap
    enabled: bool = True


@dataclass
class AircraftSpec:
    label: str
    truth_id: str  # evaluator-only; never sent to fusion
    rid_sn: Optional[str]
    waypoints: list[Waypoint]
    speed_mps: float = 12.0
    takeoff_offset_s: float = 0.0
    sources: dict[str, SourceNoise] = field(default_factory=dict)


@dataclass
class Scenario:
    name: str
    seed: int
    duration_s: float
    aircraft: list[AircraftSpec]
    algorithmHint: str = "mvp-0.1.0"
    notes: str = "合成参数，非设备实测"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "seed": self.seed,
            "duration_s": self.duration_s,
            "algorithmHint": self.algorithmHint,
            "notes": self.notes,
            "aircraft": [
                {
                    "label": a.label,
                    "truth_id": a.truth_id,
                    "rid_sn": a.rid_sn,
                    "speed_mps": a.speed_mps,
                    "takeoff_offset_s": a.takeoff_offset_s,
                    "waypoints": [asdict(w) for w in a.waypoints],
                    "sources": {k: asdict(v) for k, v in a.sources.items()},
                }
                for a in self.aircraft
            ],
        }


def load_scenario(path: str | Path) -> Scenario:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    aircraft = []
    for a in raw["aircraft"]:
        sources = {k: SourceNoise(**v) for k, v in a.get("sources", {}).items()}
        wps = [Waypoint(**w) for w in a["waypoints"]]
        aircraft.append(
            AircraftSpec(
                label=a["label"],
                truth_id=a["truth_id"],
                rid_sn=a.get("rid_sn"),
                waypoints=wps,
                speed_mps=float(a.get("speed_mps", 12)),
                takeoff_offset_s=float(a.get("takeoff_offset_s", 0)),
                sources=sources,
            )
        )
    return Scenario(
        name=raw["name"],
        seed=int(raw["seed"]),
        duration_s=float(raw["duration_s"]),
        aircraft=aircraft,
        algorithmHint=raw.get("algorithmHint", "mvp-0.1.0"),
        notes=raw.get("notes", ""),
    )


def _line(x0, y0, x1, y1) -> list[Waypoint]:
    return [Waypoint(x0, y0), Waypoint(x1, y1)]


def _src(
    *,
    rid: bool = False,
    spectrum: bool = False,
    radar: bool = False,
    radar_swap: Optional[float] = None,
) -> dict[str, SourceNoise]:
    return {
        "rid": SourceNoise(period_s=1.0, pos_noise_m=3.0, enabled=rid),
        "spectrum": SourceNoise(period_s=1.2, pos_noise_m=8.0, bias_east_m=2.0 if spectrum else 0.0, enabled=spectrum),
        "radar": SourceNoise(
            period_s=2.0,
            pos_noise_m=15.0,
            enabled=radar,
            radar_id_swap_at_s=radar_swap,
        ),
    }


def preset_three_aircraft() -> Scenario:
    """W01 primary: A=RID, B=spectrum, C=RID+spectrum+radar → 3 fused entities."""
    return Scenario(
        name="three_aircraft_primary",
        seed=20261017,
        duration_s=40.0,
        notes="首要验收：A仅RID、B仅频谱、C三源；稳定后3个实体且C同源归并",
        aircraft=[
            AircraftSpec(
                label="A",
                truth_id="TRUTH-A",
                rid_sn="SN-A-001",
                waypoints=_line(0, 0, 400, 40),
                speed_mps=10,
                sources={
                    "rid": SourceNoise(period_s=1.0, pos_noise_m=3.0, enabled=True),
                    "spectrum": SourceNoise(enabled=False),
                    "radar": SourceNoise(enabled=False),
                },
            ),
            AircraftSpec(
                label="B",
                truth_id="TRUTH-B",
                rid_sn="SN-B-002",
                waypoints=_line(0, 200, 400, 240),
                speed_mps=10,
                takeoff_offset_s=0.5,
                sources={
                    "rid": SourceNoise(enabled=False),
                    "spectrum": SourceNoise(period_s=1.2, pos_noise_m=8.0, bias_east_m=2.0, enabled=True),
                    "radar": SourceNoise(enabled=False),
                },
            ),
            AircraftSpec(
                label="C",
                truth_id="TRUTH-C",
                rid_sn="SN-C-003",
                waypoints=_line(50, 100, 450, 120),
                speed_mps=11,
                takeoff_offset_s=1.0,
                sources={
                    "rid": SourceNoise(period_s=1.0, pos_noise_m=3.0, enabled=True),
                    "spectrum": SourceNoise(period_s=1.5, pos_noise_m=10.0, bias_north_m=-3.0, enabled=True),
                    "radar": SourceNoise(period_s=2.0, pos_noise_m=15.0, enabled=True),
                },
            ),
        ],
    )


def preset_seven_aircraft() -> Scenario:
    """Default demo: seven source-combination aircraft on parallel routes (~300m spacing)."""
    # y = 0,300,...,1800 — ~300m lanes; length ~500m
    specs = [
        ("A", "TRUTH-A", "SN-A-001", 0.0, 0, True, False, False),
        ("B", "TRUTH-B", "SN-B-002", 0.5, 300, False, True, False),
        ("C", "TRUTH-C", None, 1.0, 600, False, False, True),  # anonymous radar; no forged SN
        ("D", "TRUTH-D", "SN-D-004", 0.2, 900, True, True, False),
        ("E", "TRUTH-E", "SN-E-005", 0.4, 1200, True, False, True),
        ("F", "TRUTH-F", "SN-F-006", 0.6, 1500, False, True, True),
        ("G", "TRUTH-G", "SN-G-007", 0.3, 1800, True, True, True),
    ]
    aircraft = []
    for label, tid, sn, takeoff, y0, rid, spectrum, radar in specs:
        aircraft.append(
            AircraftSpec(
                label=label,
                truth_id=tid,
                rid_sn=sn,
                waypoints=_line(0, y0, 500, y0 + 20),
                speed_mps=10 + (0 if label == "A" else 1),
                takeoff_offset_s=takeoff,
                sources=_src(rid=rid, spectrum=spectrum, radar=radar),
            )
        )
    return Scenario(
        name="seven_aircraft_combinations",
        seed=20261019,
        duration_s=40.0,
        notes="默认七机：A–G 覆盖 RID/频谱/雷达全部七种来源组合；平行航线间隔约300m",
        aircraft=aircraft,
    )


def _path_at(ac: AircraftSpec, t_rel: float) -> tuple[float, float]:
    """Piecewise-linear timed path including dwell."""
    if t_rel < 0 or not ac.waypoints:
        w = ac.waypoints[0] if ac.waypoints else Waypoint(0, 0)
        return w.x_m, w.y_m
    segs: list[tuple[float, float, float, float, float]] = []
    # each segment: start_t, end_t, x0,y0,x1,y1 travel; dwell after arrival
    t_cursor = 0.0
    for i in range(len(ac.waypoints) - 1):
        a, b = ac.waypoints[i], ac.waypoints[i + 1]
        dist = math.hypot(b.x_m - a.x_m, b.y_m - a.y_m)
        travel = dist / max(ac.speed_mps, 1e-3)
        segs.append((t_cursor, t_cursor + travel, a.x_m, a.y_m, b.x_m, b.y_m))
        t_cursor += travel
        if b.dwell_s > 0:
            segs.append((t_cursor, t_cursor + b.dwell_s, b.x_m, b.y_m, b.x_m, b.y_m))
            t_cursor += b.dwell_s
    if not segs:
        w = ac.waypoints[-1]
        return w.x_m, w.y_m
    if t_rel >= segs[-1][1]:
        return segs[-1][4], segs[-1][5]
    for t0, t1, x0, y0, x1, y1 in segs:
        if t0 <= t_rel <= t1:
            u = 0.0 if t1 <= t0 else (t_rel - t0) / (t1 - t0)
            return x0 + (x1 - x0) * u, y0 + (y1 - y0) * u
    return segs[-1][4], segs[-1][5]


def _xy_to_ll(x: float, y: float) -> tuple[float, float]:
    lat = ORIGIN_LAT + y / M_PER_DEG_LAT
    lon = ORIGIN_LON + x / _lon_scale(ORIGIN_LAT)
    return lat, lon


def generate_observations(
    scenario: Scenario,
    *,
    t0: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Returns:
      observations: list of standard Observation dicts for fusion (no truth_id)
      truth_timeline: evaluator-only positions by truth_id
      obs_truth_map: observationId -> truth_id (evaluator-only)
      truth_polyline: display polylines
    """
    rng = random.Random(scenario.seed)
    t0 = t0 or datetime(2026, 4, 9, 12, tzinfo=timezone.utc)
    observations: list[dict] = []
    truth_timeline: dict[str, list[dict]] = {a.truth_id: [] for a in scenario.aircraft}
    obs_truth_map: dict[str, str] = {}
    truth_polyline: dict[str, list[dict]] = {a.truth_id: [] for a in scenario.aircraft}

    # sample truth at 0.5s for display/eval
    step = 0.5
    t = 0.0
    while t <= scenario.duration_s + 1e-9:
        for ac in scenario.aircraft:
            tr = t - ac.takeoff_offset_s
            x, y = _path_at(ac, tr)
            lat, lon = _xy_to_ll(x, y)
            truth_timeline[ac.truth_id].append(
                {"t": t, "time": (t0 + timedelta(seconds=t)).isoformat(), "x_m": x, "y_m": y, "lat": lat, "lon": lon}
            )
            truth_polyline[ac.truth_id].append({"x_m": x, "y_m": y, "t": t})
        t += step

    oid = 0
    for ac in scenario.aircraft:
        for source, cfg in ac.sources.items():
            if not cfg.enabled:
                continue
            period = max(cfg.period_s, 0.2)
            tick = ac.takeoff_offset_s
            local_tid = f"{source}-{ac.label}"
            # null = no swap; never invent a hidden 20s swap
            radar_swap_at = cfg.radar_id_swap_at_s
            while tick <= scenario.duration_s + 1e-9:
                if any(a <= tick <= b for a, b in cfg.outage):
                    tick += period
                    continue
                if rng.random() < cfg.drop_prob:
                    tick += period
                    continue
                x, y = _path_at(ac, tick - ac.takeoff_offset_s)
                x += cfg.bias_east_m + rng.gauss(0, cfg.pos_noise_m)
                y += cfg.bias_north_m + rng.gauss(0, cfg.pos_noise_m)
                lat, lon = _xy_to_ll(x, y)
                # measurement time matches measurement position; reorder only arrival
                mt = tick + cfg.clock_bias_s
                rt = tick + cfg.delay_s
                if cfg.reorder_window_s > 0:
                    rt = rt + rng.uniform(0, cfg.reorder_window_s)
                oid += 1
                obs_id = f"syn-{scenario.seed}-{oid:05d}"
                if source == "radar" and radar_swap_at is not None and tick >= radar_swap_at:
                    local_tid = f"radar-{ac.label}-v2"
                aircraft_id = None
                if source in ("rid", "spectrum") and ac.rid_sn:
                    aircraft_id = ac.rid_sn  # device-observable identity OK
                row = {
                    "observationId": obs_id,
                    "source": source,
                    "detectorId": f"DET-{source.upper()}",
                    "sourceTrackId": local_tid if source == "radar" else (ac.rid_sn or local_tid),
                    "aircraftId": aircraft_id,
                    "measurementTime": (t0 + timedelta(seconds=mt)).isoformat(),
                    "receivedAt": (t0 + timedelta(seconds=rt)).isoformat(),
                    "timeBasis": "measurement",
                    "longitude": lon,
                    "latitude": lat,
                    "altitude": None,
                    "altitudeDatum": "unknown",
                    "speed": None,
                    "heading": None,
                    "verticalSpeed": None,
                    "qualityFlags": ["synthetic"],
                }
                observations.append(row)
                obs_truth_map[obs_id] = ac.truth_id
                tick += period

    observations.sort(key=lambda r: (r["receivedAt"], r["measurementTime"], r["observationId"]))
    return {
        "scenario": scenario.to_dict(),
        "observations": observations,
        "truth_timeline": truth_timeline,
        "obs_truth_map": obs_truth_map,
        "truth_polyline": truth_polyline,
        "t0": t0.isoformat(),
    }


def save_scenario(scenario: Scenario, path: str | Path) -> None:
    Path(path).write_text(json.dumps(scenario.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def scenario_from_dict(raw: dict) -> Scenario:
    """Build Scenario from API/editor JSON (truth_id kept for eval only)."""
    aircraft = []
    for a in raw["aircraft"]:
        sources = {k: SourceNoise(**v) for k, v in a.get("sources", {}).items()}
        wps = [Waypoint(**w) for w in a["waypoints"]]
        aircraft.append(
            AircraftSpec(
                label=a["label"],
                truth_id=a["truth_id"],
                rid_sn=a.get("rid_sn"),
                waypoints=wps,
                speed_mps=float(a.get("speed_mps", 12)),
                takeoff_offset_s=float(a.get("takeoff_offset_s", 0)),
                sources=sources,
            )
        )
    return Scenario(
        name=raw["name"],
        seed=int(raw.get("seed", 0)),
        duration_s=float(raw["duration_s"]),
        aircraft=aircraft,
        algorithmHint=raw.get("algorithmHint", "mvp-0.1.0"),
        notes=raw.get("notes", ""),
    )


def _line(x0, y0, x1, y1, dwell=0.0):
    return [Waypoint(x0, y0), Waypoint(x1, y1, dwell_s=dwell)]


def preset_crossing() -> Scenario:
    """Two aircraft paths cross; each single-source."""
    return Scenario(
        name="crossing_paths",
        seed=20261017,
        duration_s=35.0,
        notes="交叉航线：A RID 横向、B 频谱纵向",
        aircraft=[
            AircraftSpec(
                label="A",
                truth_id="TRUTH-A",
                rid_sn="SN-A-001",
                waypoints=_line(-50, 100, 450, 100),
                speed_mps=12,
                sources={
                    "rid": SourceNoise(period_s=1.0, pos_noise_m=3.0, enabled=True),
                    "spectrum": SourceNoise(enabled=False),
                    "radar": SourceNoise(enabled=False),
                },
            ),
            AircraftSpec(
                label="B",
                truth_id="TRUTH-B",
                rid_sn="SN-B-002",
                waypoints=_line(200, -50, 200, 350),
                speed_mps=12,
                sources={
                    "rid": SourceNoise(enabled=False),
                    "spectrum": SourceNoise(period_s=1.0, pos_noise_m=8.0, enabled=True),
                    "radar": SourceNoise(enabled=False),
                },
            ),
        ],
    )


def preset_identity_late() -> Scenario:
    sc = preset_three_aircraft()
    sc.name = "identity_late"
    sc.notes = "身份后补：C 前 10s 无 SN，之后 RID 带 SN"
    # modeled by delaying RID start via takeoff + outage on rid for first 10s
    for a in sc.aircraft:
        if a.label == "C":
            a.sources["rid"].outage = [(0.0, 10.0)]
    return sc


def preset_source_takeover() -> Scenario:
    sc = preset_three_aircraft()
    sc.name = "source_takeover"
    sc.notes = "来源接管：C 前半仅雷达，后半 RID+频谱接入"
    for a in sc.aircraft:
        if a.label == "C":
            a.sources["rid"].outage = [(0.0, 18.0)]
            a.sources["spectrum"].outage = [(0.0, 18.0)]
    return sc


def preset_all_outage() -> Scenario:
    sc = preset_three_aircraft()
    sc.name = "all_source_outage"
    sc.notes = "全源失联：中段 12–22s 所有源 outage"
    for a in sc.aircraft:
        for cfg in a.sources.values():
            if cfg.enabled:
                cfg.outage = [(12.0, 22.0)]
    return sc


def preset_radar_swap() -> Scenario:
    sc = preset_three_aircraft()
    sc.name = "radar_id_swap"
    sc.notes = "雷达换号：C 雷达在 t=15s 换 sourceTrackId"
    for a in sc.aircraft:
        if a.label == "C":
            a.sources["radar"].radar_id_swap_at_s = 15.0
    return sc


def preset_delay_reorder() -> Scenario:
    sc = preset_three_aircraft()
    sc.name = "delay_reorder"
    sc.notes = "延迟／乱序：频谱 delay+reorder；不改 measurementTime"
    for a in sc.aircraft:
        for src, cfg in a.sources.items():
            if not cfg.enabled:
                continue
            if src == "spectrum":
                cfg.delay_s = 1.5
                cfg.reorder_window_s = 2.0
            if src == "radar":
                cfg.delay_s = 0.8
                cfg.reorder_window_s = 1.0
    return sc


def preset_identity_conflict() -> Scenario:
    sc = preset_three_aircraft()
    sc.name = "identity_conflict"
    sc.notes = "身份矛盾：B 频谱误用 A 的 SN（评估应检出）"
    for a in sc.aircraft:
        if a.label == "B":
            a.rid_sn = "SN-A-001"  # intentional conflict for eval demos
    return sc


PRESET_BUILDERS = {
    "seven_aircraft_combinations": preset_seven_aircraft,
    "three_aircraft_primary": preset_three_aircraft,
    "crossing_paths": preset_crossing,
    "identity_late": preset_identity_late,
    "source_takeover": preset_source_takeover,
    "all_source_outage": preset_all_outage,
    "radar_id_swap": preset_radar_swap,
    "delay_reorder": preset_delay_reorder,
    "identity_conflict": preset_identity_conflict,
}


def expected_sources_from_scenario(scenario: Scenario | dict) -> dict[str, set[str]]:
    """Derive truth_id → enabled sources from actual aircraft list (not name-hardcoded)."""
    aircraft = scenario.aircraft if isinstance(scenario, Scenario) else scenario.get("aircraft") or []
    out: dict[str, set[str]] = {}
    for a in aircraft:
        if isinstance(a, AircraftSpec):
            tid = a.truth_id
            sources = a.sources
            enabled = {k for k, cfg in sources.items() if cfg.enabled}
        else:
            tid = a.get("truth_id") or a.get("truthId")
            sources = a.get("sources") or {}
            enabled = {k for k, cfg in sources.items() if (cfg or {}).get("enabled")}
        if tid and enabled:
            out[str(tid)] = enabled
    return out


def _bundle_t0(bundle: dict[str, Any]) -> Optional[datetime]:
    t0_raw = bundle.get("t0")
    if t0_raw:
        return datetime.fromisoformat(str(t0_raw).replace("Z", "+00:00"))
    mts = [o.get("measurementTime") for o in (bundle.get("observations") or []) if o.get("measurementTime")]
    if not mts:
        return None
    return datetime.fromisoformat(min(mts).replace("Z", "+00:00"))


def _enabled_outages(aircraft: list) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a in aircraft:
        sources = a.get("sources") or {}
        for cfg in sources.values():
            if not (cfg or {}).get("enabled"):
                continue
            for pair in (cfg or {}).get("outage") or []:
                try:
                    a0, b0 = float(pair[0]), float(pair[1])
                except (TypeError, ValueError, IndexError):
                    continue
                out.append((a0, b0))
    return out


def _merge_outage_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Merge overlapping or contiguous [start,end] outage intervals."""
    if not intervals:
        return []
    xs = sorted((float(a), float(b)) for a, b in intervals if b > a)
    out: list[list[float]] = [[xs[0][0], xs[0][1]]]
    for a, b in xs[1:]:
        if a <= out[-1][1]:  # overlap or touch at boundary
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _adaptive_confirm_s(aircraft: list, default: float = 4.0) -> float:
    """Confirm delay after outage end: at least default, also ≥2× max enabled period."""
    periods: list[float] = []
    for a in aircraft:
        sources = a.get("sources") or {}
        for cfg in sources.values():
            if not (cfg or {}).get("enabled"):
                continue
            try:
                periods.append(float((cfg or {}).get("period_s") or 1.0))
            except (TypeError, ValueError):
                periods.append(1.0)
    max_p = max(periods) if periods else 1.0
    return max(float(default), 2.0 * max_p)


def evaluation_phases_from_bundle(
    bundle: dict[str, Any],
    *,
    confirm_s: Optional[float] = None,
    min_len_s: float = 3.0,
) -> list[dict[str, Any]]:
    """Build evaluable phases covering pre-outage, each outage (lifecycle), and each recovery.

    Uses all outage boundaries (merged), not only global earliest/latest extrema. Mid-run
    recoveries between multiple outages are first-class phases. A required recovery that
    cannot form a window is marked unavailable so the whole run cannot be labeled PASS
    from end fragments alone.
    """
    sc = bundle.get("scenario") or {}
    duration = float(sc.get("duration_s") or 40.0)
    aircraft = sc.get("aircraft") or []
    t0_dt = _bundle_t0(bundle)
    if t0_dt is None:
        return []
    max_takeoff = 0.0
    for a in aircraft:
        max_takeoff = max(max_takeoff, float(a.get("takeoff_offset_s") or 0.0))
    conf = float(confirm_s) if confirm_s is not None else _adaptive_confirm_s(aircraft)
    merged = _merge_outage_intervals(_enabled_outages(aircraft))
    phases: list[dict[str, Any]] = []
    start_s = max(8.0, max_takeoff + 8.0)

    def _win(a_s: float, b_s: float) -> tuple[str, str]:
        return (
            (t0_dt + timedelta(seconds=a_s)).isoformat(),
            (t0_dt + timedelta(seconds=b_s)).isoformat(),
        )

    def _add_full(name: str, a_s: float, b_s: float) -> None:
        if b_s - a_s < min_len_s:
            return
        phases.append({"name": name, "mode": "full", "window": _win(a_s, b_s), "available": True})

    def _add_outage(name: str, a_s: float, b_s: float) -> None:
        if b_s - a_s < 1.0:
            return
        # Lifecycle phases may be shorter than full min_len; still must be checked.
        phases.append(
            {
                "name": name,
                "mode": "lifecycle",
                "window": _win(a_s, b_s),
                "available": True,
                "outage_s": [a_s, b_s],
            }
        )

    if not merged:
        _add_full("stable", start_s, duration - 2.0)
        return phases

    # Pre-first-outage active window
    first_start = merged[0][0]
    if first_start > start_s:
        _add_full("pre_outage", start_s, min(duration - 2.0, first_start - 1.0))

    for i, (oa, ob) in enumerate(merged):
        _add_outage(f"outage_{i}", oa, min(ob, duration))
        # Recovery until next outage (or end)
        next_start = merged[i + 1][0] if i + 1 < len(merged) else None
        rec_a = ob + conf
        if next_start is not None:
            rec_b = next_start - 1.0
            if rec_b - rec_a >= min_len_s:
                _add_full(f"recovery_{i}", rec_a, rec_b)
            elif rec_b > rec_a:
                # Gap exists but too short — still mark coverage hole if mid recoveries matter
                phases.append(
                    {
                        "name": f"recovery_{i}",
                        "mode": "full",
                        "window": None,
                        "available": False,
                        "reason": "recovery_window_too_short",
                        "outage_end_s": ob,
                        "confirm_s": conf,
                        "next_outage_s": next_start,
                    }
                )
            # else: contiguous outages after merge — no mid recovery expected
        else:
            rec_b = duration - 2.0
            if rec_b - rec_a >= min_len_s:
                _add_full(f"recovery_{i}" if i > 0 else "recovery", rec_a, rec_b)
            else:
                phases.append(
                    {
                        "name": "recovery",
                        "mode": "full",
                        "window": None,
                        "available": False,
                        "reason": "recovery_window_too_short",
                        "outage_end_s": ob,
                        "confirm_s": conf,
                    }
                )
    return phases


def stable_window_from_bundle(bundle: dict[str, Any]) -> Optional[tuple[str, str]]:
    """Primary stable window (first available phase). Prefer evaluation_phases_from_bundle."""
    phases = evaluation_phases_from_bundle(bundle)
    for ph in phases:
        if ph.get("available") and ph.get("window"):
            return tuple(ph["window"])  # type: ignore[return-value]
    return None


def get_preset(name: str) -> Scenario:
    if name not in PRESET_BUILDERS:
        raise KeyError(name)
    return PRESET_BUILDERS[name]()


def list_preset_names() -> list[dict[str, str]]:
    return [{"name": k, "notes": PRESET_BUILDERS[k]().notes} for k in PRESET_BUILDERS]
