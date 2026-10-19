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


def preset_three_aircraft() -> Scenario:
    """W01 primary: A=RID, B=spectrum, C=RID+spectrum+radar → 3 fused entities."""
    def line(x0, y0, x1, y1):
        return [Waypoint(x0, y0), Waypoint(x1, y1)]

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
                waypoints=line(0, 0, 400, 40),
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
                waypoints=line(0, 200, 400, 240),
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
                waypoints=line(50, 100, 450, 120),
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
            radar_swap_at = cfg.radar_id_swap_at_s
            if radar_swap_at is None and source == "radar":
                radar_swap_at = 20.0  # default for C-radar scenario demos
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
    "three_aircraft_primary": preset_three_aircraft,
    "crossing_paths": preset_crossing,
    "identity_late": preset_identity_late,
    "source_takeover": preset_source_takeover,
    "all_source_outage": preset_all_outage,
    "radar_id_swap": preset_radar_swap,
    "delay_reorder": preset_delay_reorder,
    "identity_conflict": preset_identity_conflict,
}


def get_preset(name: str) -> Scenario:
    if name not in PRESET_BUILDERS:
        raise KeyError(name)
    return PRESET_BUILDERS[name]()


def list_preset_names() -> list[dict[str, str]]:
    return [{"name": k, "notes": PRESET_BUILDERS[k]().notes} for k in PRESET_BUILDERS]
