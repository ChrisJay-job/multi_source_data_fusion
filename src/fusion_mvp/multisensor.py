"""Explicit multisensor-v1 profile.

Legacy FusionSession stays the default. This module is used only when a
request sets fusionProfile=multisensor-v1. positionStdM is a horizontal
standard deviation in metres; the Kalman update consumes variance = std^2.
Default noise values are uncalibrated and are flagged on every track.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from scipy.optimize import linear_sum_assignment

from .geo import LocalENU
from .kalman import ConstantVelocity1D, ConstantVelocityKF
from .mapping import SOURCE_MAP
from .models import (
    FusionEvent,
    ProcessResponse,
    Rejected,
    ReplayResponse,
    SourceTrackRef,
    TargetSnapshot,
)

PROFILE = "multisensor-v1"
PROFILE_3D = "multisensor-3d-v1"
SUPPORTED_PROFILES = {PROFILE, PROFILE_3D}
_MSL_DATUMS = {"MSL", "msl", "mean_sea_level"}
_INF = 1.0e6
_GENERIC_DETECTORS = {"radar", "spectrum", "rid", "pp", "leida", "雷达", "频谱"}
_CLASSES = {"unknown", "drone", "bird", "other"}


def _iso(dt: datetime) -> str:
    # Keep microseconds. Truncating to milliseconds made distinct times and
    # committed stateTime disagree with the parsed measurement instant.
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _aware(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def _finite(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return num


def _blank(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _ang_diff(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _fingerprint(
    batch_id: str,
    processing_time: str,
    mode: str,
    observations: list[dict],
    *,
    fusion_profile: str = PROFILE,
) -> str:
    blob = json.dumps(
        {
            "batchId": batch_id,
            "processingTime": processing_time,
            "mode": mode,
            "fusionProfile": fusion_profile,
            "observations": observations,
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _datum_ok_for_3d(datum: Optional[str]) -> bool:
    if datum is None:
        return False
    return datum.strip() in _MSL_DATUMS or datum.strip().upper() == "MSL"


def _content_hash(raw: dict) -> str:
    return hashlib.sha256(
        json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


@dataclass
class _Obs:
    raw: dict
    observation_id: str
    source: str
    detector_id: str
    scan_id: Optional[str]
    source_track_id: Optional[str]
    origin: str
    aircraft_id: Optional[str]
    mt: datetime
    x: float
    y: float
    lon: float
    lat: float
    altitude: Optional[float]
    altitude_datum: Optional[str]
    speed: Optional[float]
    heading: Optional[float]
    vertical_speed: Optional[float]
    std_m: float
    object_class: str
    flags: list[str]


@dataclass
class _Bind:
    source: str
    detector_id: str
    source_track_id: str
    origin: str
    times: set[str] = field(default_factory=set)
    last_seen: Optional[datetime] = None
    confirmed: bool = False
    aircraft_id: Optional[str] = None


@dataclass
class _Track:
    fusion_id: str
    created: datetime
    kf: ConstantVelocityKF
    state_time: datetime
    last_observed: datetime
    status: str = "tentative"
    aircraft_id: Optional[str] = None
    identity: str = "unknown"
    object_class: str = "unknown"
    fusion_method: str = "multi_sensor_estimate"
    binds: dict[tuple[str, str, str], _Bind] = field(default_factory=dict)
    distinct_times: set[str] = field(default_factory=set)
    contributing: set[str] = field(default_factory=set)
    flags: set[str] = field(default_factory=lambda: {"noise_uncalibrated", "identity_unknown"})
    aliases: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    recent_xy: list[tuple[float, float]] = field(default_factory=list)
    last_speed: Optional[float] = None
    last_heading: Optional[float] = None
    last_altitude: Optional[float] = None
    last_datum: Optional[str] = None
    vertical_speed: Optional[float] = None
    consumed: list[str] = field(default_factory=list)
    updated_this_batch: bool = False
    contrib_time: dict[str, datetime] = field(default_factory=dict)
    active_primary: Optional[str] = None
    # Vertical state (multisensor-3d-v1 only)
    vkf: Optional[ConstantVelocity1D] = None
    altitude_state_time: Optional[datetime] = None
    last_altitude_observed_at: Optional[datetime] = None
    altitude_mode: str = "unknown"  # measured_filtered | predicted | unknown | expired
    altitude_observation_ids: list[str] = field(default_factory=list)
    # Raw altitude that must NOT become fused output (unsupported datum / rejected).
    raw_altitude_evidence: list[dict] = field(default_factory=list)
    altitude_sigma_m: Optional[float] = None


class MultisensorSession:
    def __init__(self, session_id: str, cfg: dict, *, profile: str = PROFILE, clock=None):
        if profile not in SUPPORTED_PROFILES:
            raise ValueError(f"unsupported_profile:{profile}")
        self.session_id = session_id
        self.cfg = cfg
        self.profile = profile
        self.enable_vertical = profile == PROFILE_3D
        self.ms = cfg.get("multisensor_v1") or {}
        self.ms3 = cfg.get("multisensor_3d_v1") or {}
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        origin = cfg.get("origin") or {}
        self.enu = LocalENU(float(origin.get("latitude", 0.0)), float(origin.get("longitude", 0.0)))
        self.epoch = uuid.uuid4().hex
        self.mode: Optional[str] = None
        self.tracks: dict[str, _Track] = {}
        self.buffer: list[_Obs] = []
        self.seen: dict[str, str] = {}
        self.cache: dict[str, tuple[str, datetime, ProcessResponse]] = {}
        self.evicted_batches: dict[str, datetime] = {}
        self.closed_scans: dict[tuple[str, str], tuple[datetime, set[str]]] = {}
        # Logical spawn slots for a scan reserved before the track exists.
        self.open_slots: dict[str, dict[str, Any]] = {}
        self.seq = 0
        self._ids = 0
        self._gen = 0
        self._alt_ids = 0
        self.watermark: Optional[datetime] = None
        self.last_pt: Optional[datetime] = None
        self._event_buf: list[FusionEvent] = []
        self._update_buf: list[dict] = []
        self._alt_update_buf: list[dict] = []
        self._reject_buf: list[Rejected] = []
        self.lock = threading.RLock()
        self.reorder_s = float(cfg.get("reorder_window_s", 2.0))
        self.q_pos = float((cfg.get("kalman") or {}).get("q_pos", 2.0))
        self.q_vel = float((cfg.get("kalman") or {}).get("q_vel", 1.5))
        self.q_alt = float(self.ms3.get("q_alt", 1.0))
        self.q_vspeed = float(self.ms3.get("q_vspeed", 0.5))

    def process(
        self,
        batch_id: str,
        processing_time: str,
        observations: list[dict],
        mode: str,
        *,
        retain_idempotency: bool = True,
    ) -> ProcessResponse:
        with self.lock:
            pt = _aware(processing_time)
            if pt is None:
                return self._respond(batch_id, processing_time, error="invalid_processing_time")
            limit = int(self.ms.get("max_observations_per_request", 5000))
            if len(observations) > limit:
                return self._respond(batch_id, _iso(pt), error="too_many_observations")
            fp = _fingerprint(batch_id, processing_time, mode, observations, fusion_profile=self.profile)
            # Public /v1/fusion/process keeps idempotency for realtime and replay.
            # Only the internal temporary replay_job path opts out.
            use_idem = retain_idempotency
            if use_idem:
                # TTL expire before capacity so a full table of elapsed ids can admit new work.
                # Do not apply max_cache eviction here — that must stay inside the transactional section.
                self._expire_idempotency()
            if use_idem and batch_id in self.evicted_batches:
                return self._respond(batch_id, _iso(pt), error="idempotency_expired")
            cached = self.cache.get(batch_id) if use_idem else None
            if cached is not None:
                old_fp, stored_at, resp = cached
                ttl = float(self.cfg.get("idempotency_ttl_s", 1800))
                if (self._clock() - stored_at).total_seconds() > ttl:
                    return self._respond(batch_id, _iso(pt), error="idempotency_expired")
                if old_fp != fp:
                    return self._respond(batch_id, _iso(pt), error="batch_id_conflict")
                return resp
            force_flush = mode == "flush"
            if not force_flush and self.mode is not None and mode != self.mode:
                return self._respond(batch_id, _iso(pt), error="session_mode_conflict")
            if self.last_pt is not None and pt < self.last_pt:
                return self._respond(batch_id, _iso(pt), error="processing_time_not_monotonic")
            id_cap = int(self.ms.get("max_idempotency_ids", 4096))
            if use_idem and len(self.cache) + len(self.evicted_batches) >= id_cap:
                return self._respond(batch_id, _iso(pt), error="idempotency_capacity")
            backup = self._backup()
            try:
                rejected, accepted, conflict = self._validate(observations, pt)
                if conflict:
                    self._restore(backup)
                    return self._respond(batch_id, _iso(pt), error="observation_id_conflict", rejected=rejected)
                if force_flush:
                    if self.mode is None:
                        self.mode = "realtime"
                else:
                    self.mode = mode
                self.last_pt = pt
                accepted, rejected = self._admit_buffer(accepted, rejected)
                for obs in accepted:
                    self.seen[obs.observation_id] = _content_hash(obs.raw)
                    self.buffer.append(obs)
                self._trim_seen(pt)
                self._release(pt, force_all=force_flush)
                self._lifecycle(pt)
                if use_idem:
                    self._trim_cache(pt)
                self.seq += 1
                updates = self._take_updates()
                alt_updates = self._take_alt_updates()
                resp = self._respond(
                    batch_id, _iso(pt), rejected=rejected, updates=updates, altitude_updates=alt_updates
                )
                if use_idem:
                    self.cache[batch_id] = (fp, self._clock(), resp)
                return resp
            except Exception:
                self._restore(backup)
                return self._respond(batch_id, _iso(pt), error="batch_rollback")

    def _backup(self) -> dict:
        return {
            "tracks": copy.deepcopy(self.tracks),
            "buffer": copy.deepcopy(self.buffer),
            "seen": dict(self.seen),
            "seq": self.seq,
            "ids": self._ids,
            "gen": self._gen,
            "watermark": self.watermark,
            "last_pt": self.last_pt,
            "mode": self.mode,
            "evicted": dict(self.evicted_batches),
            "cache": dict(self.cache),
            "closed_scans": {key: (when, set(locals_)) for key, (when, locals_) in self.closed_scans.items()},
            "open_slots": copy.deepcopy(self.open_slots),
            "alt_ids": self._alt_ids,
        }

    def _restore(self, snap: dict) -> None:
        self.tracks = snap["tracks"]
        self.buffer = snap["buffer"]
        self.seen = snap["seen"]
        self.seq = snap["seq"]
        self._ids = snap["ids"]
        self._gen = snap["gen"]
        self.watermark = snap["watermark"]
        self.last_pt = snap["last_pt"]
        self.mode = snap["mode"]
        self.evicted_batches = snap.get("evicted", {})
        self.cache = snap.get("cache", self.cache)
        self.closed_scans = snap.get("closed_scans", {})
        self.open_slots = snap.get("open_slots", {})
        self._alt_ids = snap.get("alt_ids", 0)
        self._event_buf = []
        self._update_buf = []
        self._alt_update_buf = []
        self._reject_buf = []

    def _admit_buffer(self, accepted: list[_Obs], rejected: list[Rejected]) -> tuple[list[_Obs], list[Rejected]]:
        cap = int(self.ms.get("max_observations_per_request", 5000))
        room = max(0, cap - len(self.buffer))
        if len(accepted) > room:
            for obs in accepted[room:]:
                rejected.append(Rejected(observationId=obs.observation_id, reason="reorder_buffer_limit"))
            self._event_buf.append(self._event("memory_bounded", self.last_pt or accepted[0].mt, None, {"reason": "reorder_buffer_limit"}))
            accepted = accepted[:room]
        return accepted, rejected

    def _trim_seen(self, pt: datetime) -> None:
        cap = int(self.ms.get("max_seen", 20000))
        if len(self.seen) <= cap:
            return
        drop = len(self.seen) - cap
        for key in list(self.seen)[:drop]:
            self.seen.pop(key, None)
        self._event_buf.append(self._event("memory_bounded", pt, None, {"reason": "seen_cap", "dropped": drop}))

    def _expire_idempotency(self) -> None:
        ttl = float(self.cfg.get("idempotency_ttl_s", 1800))
        now = self._clock()
        for key, (_fp, stored_at, _resp) in list(self.cache.items()):
            if (now - stored_at).total_seconds() > ttl:
                self.evicted_batches[key] = stored_at
                self.cache.pop(key, None)
        for key, stored_at in list(self.evicted_batches.items()):
            if (now - stored_at).total_seconds() > ttl:
                self.evicted_batches.pop(key, None)

    def _trim_cache(self, pt: datetime) -> None:
        max_cache = int(self.cfg.get("max_cache", 200))
        now = self._clock()
        self._expire_idempotency()
        while len(self.cache) >= max_cache:
            oldest = min(self.cache, key=lambda key: self.cache[key][1])
            self.evicted_batches[oldest] = now
            self.cache.pop(oldest, None)
            self._event_buf.append(self._event("memory_bounded", pt, None, {"reason": "idempotency_cache_cap"}))
        # Evicted ids stay until the idempotency TTL. Dropping them early made
        # a retry look like a brand-new batch. The id cap rejects further work
        # instead of forgetting an in-window batch.

    def _validate(self, rows: list[dict], pt: datetime) -> tuple[list[Rejected], list[_Obs], bool]:
        rejected: list[Rejected] = []
        accepted: list[_Obs] = []
        conflict = False
        seen_in_batch: dict[str, str] = {}
        for raw in rows:
            if not isinstance(raw, dict):
                rejected.append(Rejected(reason="observation_not_object"))
                continue
            oid = _blank(raw.get("observationId"))
            if oid is None:
                rejected.append(Rejected(reason="missing_observation_id"))
                continue
            digest = _content_hash(raw)
            prev = self.seen.get(oid)
            if prev is not None and prev != digest:
                rejected.append(Rejected(observationId=oid, reason="observation_id_conflict"))
                conflict = True
                continue
            if prev == digest or seen_in_batch.get(oid) == digest:
                continue
            if oid in seen_in_batch and seen_in_batch[oid] != digest:
                rejected.append(Rejected(observationId=oid, reason="observation_id_conflict"))
                conflict = True
                continue
            obs, reason = self._parse(raw, oid, pt)
            if reason:
                rejected.append(Rejected(observationId=oid, reason=reason))
                continue
            seen_in_batch[oid] = digest
            accepted.append(obs)
        return rejected, accepted, conflict

    def _parse(self, raw: dict, oid: str, pt: datetime) -> tuple[Optional[_Obs], Optional[str]]:
        kind = SOURCE_MAP.get(str(raw.get("source") or "").strip().lower())
        if kind is None:
            return None, "unknown_source"
        detector = _blank(raw.get("detectorId"))
        if detector is None:
            return None, "missing_detector_id"
        if detector.lower() in _GENERIC_DETECTORS:
            return None, "detector_id_not_specific"
        mt = _aware(raw.get("measurementTime"))
        if mt is None:
            return None, "invalid_measurement_time"
        future_skew = float(self.ms.get("future_skew_s", 2.0))
        if mt > pt + timedelta(seconds=future_skew):
            return None, "future_timestamp"
        if self.watermark is not None and mt < self.watermark:
            return None, "late_after_frontier"
        lon = _finite(raw.get("longitude"))
        lat = _finite(raw.get("latitude"))
        if lon is None or lat is None:
            return None, "non_finite_position"
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            return None, "position_out_of_range"
        if abs(lon) < 1e-12 and abs(lat) < 1e-12:
            return None, "position_placeholder_0_0"
        flags = [str(x) for x in (raw.get("qualityFlags") or []) if str(x)]
        heading = _finite(raw.get("heading"))
        if heading is not None and not (0.0 <= heading < 360.0):
            flags.append("heading_out_of_range")
            heading = None
        speed = _finite(raw.get("speed"))
        if raw.get("speed") is not None and speed is None:
            return None, "non_finite_speed"
        alt = _finite(raw.get("altitude"))
        datum = _blank(raw.get("altitudeDatum")) or "unknown"
        if datum == "unknown":
            flags.append("altitude_datum_unknown")
        local = _blank(raw.get("sourceTrackId"))
        scan = _blank(raw.get("scanId"))
        if scan and self._scan_closed(detector, scan, local, mt):
            return None, "scan_closed"
        origin = "device"
        if local is None:
            self._gen += 1
            local = f"gen-{self.epoch[:8]}-{self._gen}"
            origin = "generated"
            flags.append("generated_local_track_id")
        std = _finite(raw.get("positionStdM"))
        if std is None or std <= 0:
            defaults = self.ms.get("position_std_m") or {}
            std = float(defaults.get(kind, 40.0))
            flags.append("position_std_default_uncalibrated")
        else:
            flags.append("position_std_uncalibrated")
        obj = _blank(raw.get("objectClass")) or "unknown"
        if obj not in _CLASSES:
            flags.append("object_class_unrecognized")
            obj = "unknown"
        x, y = self.enu.to_xy(lat, lon)
        return _Obs(
            raw=raw,
            observation_id=oid,
            source=kind,
            detector_id=detector,
            scan_id=scan,
            source_track_id=local,
            origin=origin,
            aircraft_id=_blank(raw.get("aircraftId")),
            mt=mt,
            x=x,
            y=y,
            lon=lon,
            lat=lat,
            altitude=alt,
            altitude_datum=datum,
            speed=speed,
            heading=heading,
            vertical_speed=_finite(raw.get("verticalSpeed")),
            std_m=float(std),
            object_class=obj,
            flags=flags,
        ), None

    def _obs_group_key(self, obs: _Obs) -> tuple:
        if obs.scan_id:
            return ("scan", obs.detector_id, obs.scan_id)
        bucket_ms = max(1, int(self.ms.get("noscan_bucket_ms", 50)))
        bucket = int(obs.mt.timestamp() * 1000) // bucket_ms
        return ("bucket", obs.detector_id, bucket)

    def _scan_closed(self, detector: str, scan: str, local: Optional[str], mt: datetime) -> bool:
        key = (detector, scan)
        rec = self.closed_scans.get(key)
        if rec is None:
            return False
        when, locals_ = rec
        window = float(self.ms.get("closed_scan_reject_s", 4.0))
        if (mt - when).total_seconds() > window:
            self.closed_scans.pop(key, None)
            return False
        if local and local in locals_:
            return False
        return True

    def _remember_closed_scan(self, detector: str, scan: str, group: list[_Obs]) -> None:
        locals_ = {o.source_track_id for o in group if o.origin == "device" and o.source_track_id}
        when = max(o.mt for o in group)
        key = (detector, scan)
        prev = self.closed_scans.get(key)
        if prev is not None:
            when = max(when, prev[0])
            locals_ = locals_ | prev[1]
        self.closed_scans[key] = (when, locals_)
        cap = int(self.ms.get("max_closed_scans", 4096))
        while len(self.closed_scans) > cap:
            oldest = min(self.closed_scans, key=lambda item: self.closed_scans[item][0])
            self.closed_scans.pop(oldest, None)

    def _scan_members(self, detector: str, scan: str) -> list[_Obs]:
        return [o for o in self.buffer if o.scan_id == scan and o.detector_id == detector]

    def _held_scan_partition(self, ready: list[_Obs], future: list[_Obs]) -> tuple[set[tuple[str, str]], list[tuple[datetime, datetime]]]:
        """Hold whole named scans transitively when any member waits on a held span."""
        held_scans = {(o.detector_id, o.scan_id) for o in future if o.scan_id}
        changed = True
        while changed:
            changed = False
            spans: list[tuple[datetime, datetime]] = []
            for det, scan in held_scans:
                members = self._scan_members(det, scan)
                if members:
                    spans.append((min(o.mt for o in members), max(o.mt for o in members)))
            for obs in ready:
                if not any(lo <= obs.mt <= hi for lo, hi in spans):
                    continue
                if obs.scan_id:
                    key = (obs.detector_id, obs.scan_id)
                    if key not in held_scans:
                        held_scans.add(key)
                        changed = True
        spans = []
        for det, scan in held_scans:
            members = self._scan_members(det, scan)
            if members:
                spans.append((min(o.mt for o in members), max(o.mt for o in members)))
        return held_scans, spans

    def _release(self, pt: datetime, *, force_all: bool = False) -> None:
        if force_all:
            # Terminal / control flush: release entire reorder buffer at current PT.
            horizon = pt
            future: list[_Obs] = []
            ready = list(self.buffer)
        else:
            horizon = pt - timedelta(seconds=self.reorder_s)
            future = [o for o in self.buffer if o.mt > horizon]
            ready = [o for o in self.buffer if o.mt <= horizon]
        # Named scans stay whole. Overlapping held spans pull related scans in
        # until the wait/release partition is stable.
        held_scans, held_spans = self._held_scan_partition(ready, future)
        still: list[_Obs] = []
        releasing: list[_Obs] = []
        for obs in ready:
            if obs.scan_id and (obs.detector_id, obs.scan_id) in held_scans:
                still.append(obs)
            elif any(lo <= obs.mt <= hi for lo, hi in held_spans):
                still.append(obs)
            else:
                releasing.append(obs)
        self.buffer = still + future
        groups: dict[tuple, list[_Obs]] = {}
        for obs in releasing:
            groups.setdefault(self._obs_group_key(obs), []).append(obs)
        # Reserve each whole scan once (including spawn slots), then apply in
        # measurement time. Input order must not move the filter clock.
        planned: dict[str, tuple] = {}
        seen_groups: set[tuple] = set()
        for obs in sorted(releasing, key=lambda o: (o.mt, o.detector_id, o.observation_id)):
            key = self._obs_group_key(obs)
            if key not in seen_groups:
                self._assign_group(groups[key], planned)
                seen_groups.add(key)
            self._apply_planned(obs, planned)
        for key, group in groups.items():
            if key[0] == "scan":
                self._remember_closed_scan(key[1], str(key[2]), group)
        # Slots from this release are consumed; keep none across releases.
        self.open_slots.clear()
        self._try_merge()
        self._promote()
        if releasing or self.tracks or self.watermark is not None:
            self.watermark = horizon if self.watermark is None else max(self.watermark, horizon)

    def _assignment_targets(self) -> list[tuple[str, str, Any]]:
        """Live tracks plus unresolved spawn slots from earlier groups in this release."""
        targets: list[tuple[str, str, Any]] = []
        tracks = [t for t in self.tracks.values() if t.status != "terminated"]
        tracks.sort(key=lambda t: t.fusion_id)
        for tr in tracks:
            targets.append(("track", tr.fusion_id, tr))
        for slot_id, slot in sorted(self.open_slots.items()):
            if slot.get("fusion_id"):
                continue
            targets.append(("slot", slot_id, slot))
        return targets

    def _slot_aircraft_id(self, slot: dict[str, Any]) -> Optional[str]:
        return slot.get("aircraft_id") or None

    def _slot_predicted_xy(self, slot: dict[str, Any], when: datetime) -> tuple[float, float]:
        """Compare pending-slot anchors at a common instant. Not a committed KF clock."""
        x, y = float(slot["x"]), float(slot["y"])
        slot_mt = slot.get("mt")
        if not isinstance(slot_mt, datetime):
            return x, y
        dt = (when - slot_mt).total_seconds()
        speed = slot.get("speed")
        heading = slot.get("heading")
        if speed is None or heading is None or abs(dt) < 1e-12:
            return x, y
        rad = math.radians(float(heading))
        return x + float(speed) * math.sin(rad) * dt, y + float(speed) * math.cos(rad) * dt

    def _cost_target(self, kind: str, target: Any, obs: _Obs) -> float:
        if kind == "track":
            return self._cost(target, obs)
        slot_sn = self._slot_aircraft_id(target)
        if slot_sn and obs.aircraft_id and slot_sn != obs.aircraft_id:
            return _INF
        gate = float(self.ms.get("gate_m", 80.0))
        # A pending slot's measurementTime is only a reference anchor. An earlier
        # interleaved device observation is not a late update of a committed KF.
        pred_x, pred_y = self._slot_predicted_xy(target, obs.mt)
        innov = math.hypot(obs.x - pred_x, obs.y - pred_y)
        if innov > gate:
            return _INF
        hover = float(self.ms.get("hover_speed_mps", 1.5))
        heading_gate = float(self.ms.get("heading_gate_deg", 70.0))
        slot_heading = target.get("heading")
        slot_speed = target.get("speed")
        if (
            slot_heading is not None
            and obs.heading is not None
            and (obs.speed or 0.0) > hover
            and (slot_speed or 0.0) > hover
            and _ang_diff(float(slot_heading), obs.heading) > heading_gate
        ):
            return _INF
        return innov

    def _target_aircraft_id(self, kind: str, target: Any) -> Optional[str]:
        if kind == "track":
            return target.aircraft_id
        return self._slot_aircraft_id(target)

    def _register_open_slot(self, obs: _Obs) -> str:
        slot_id = f"slot-{obs.observation_id}"
        self.open_slots[slot_id] = {
            "x": obs.x,
            "y": obs.y,
            "mt": obs.mt,
            "fusion_id": None,
            "observation_id": obs.observation_id,
            "aircraft_id": obs.aircraft_id,
            "speed": obs.speed,
            "heading": obs.heading,
            "source": obs.source,
            "detector_id": obs.detector_id,
            "scan_id": obs.scan_id,
            "source_track_id": obs.source_track_id,
        }
        return slot_id

    def _assign_group(self, group: list[_Obs], planned: dict[str, tuple]) -> None:
        group.sort(key=lambda o: (o.mt, o.observation_id))
        targets = self._assignment_targets()
        n = len(group)
        m = len(targets)
        ambiguous: set[int] = set()
        assigned: set[int] = set()
        ratio = float(self.ms.get("ambiguity_ratio", 1.15))
        if m and n:
            cost = [[_INF for _ in range(m)] for _ in range(n)]
            forced_pairs: list[tuple[int, int]] = []
            for i, obs in enumerate(group):
                for j, (kind, _tid, target) in enumerate(targets):
                    cost[i][j] = self._cost_target(kind, target, obs)
                if not obs.aircraft_id:
                    continue
                in_gate = [
                    j
                    for j, (kind, _tid, target) in enumerate(targets)
                    if self._target_aircraft_id(kind, target) == obs.aircraft_id and cost[i][j] < _INF / 2
                ]
                owners = [
                    j
                    for j, (kind, _tid, target) in enumerate(targets)
                    if self._target_aircraft_id(kind, target) == obs.aircraft_id
                ]
                if len(in_gate) == 1:
                    forced_pairs.append((i, in_gate[0]))
                elif len(in_gate) > 1:
                    self._event_buf.append(
                        self._event(
                            "identity_ambiguous",
                            obs.mt,
                            None,
                            {"observationId": obs.observation_id, "aircraftId": obs.aircraft_id},
                        )
                    )
                    for j, (kind, _tid, target) in enumerate(targets):
                        if self._target_aircraft_id(kind, target) != obs.aircraft_id:
                            cost[i][j] = _INF
                elif owners:
                    self._event_buf.append(
                        self._event(
                            "identity_out_of_gate",
                            obs.mt,
                            None,
                            {"observationId": obs.observation_id, "aircraftId": obs.aircraft_id},
                        )
                    )
                    for j in range(m):
                        cost[i][j] = _INF
            # Unique in-gate SN claims are one-to-one: a column may be forced once.
            claimers: dict[int, list[int]] = {}
            for i, j in forced_pairs:
                claimers.setdefault(j, []).append(i)
            reserved_cols: set[int] = set()
            for j, rows in claimers.items():
                if len(rows) == 1:
                    i = rows[0]
                    kind, tid, _target = targets[j]
                    planned[group[i].observation_id] = ("track" if kind == "track" else "slot", tid)
                    assigned.add(i)
                    reserved_cols.add(j)
                    for ii in range(n):
                        cost[ii][j] = _INF
                    for jj in range(m):
                        cost[i][jj] = _INF
                    continue
                # Several same-SN rows competed for one column in this scan.
                reserved_cols.add(j)
                for ii in range(n):
                    cost[ii][j] = _INF
                for i in rows:
                    self._event_buf.append(
                        self._event(
                            "identity_ambiguous",
                            group[i].mt,
                            None,
                            {
                                "observationId": group[i].observation_id,
                                "aircraftId": group[i].aircraft_id,
                                "reason": "forced_column_contention",
                            },
                        )
                    )
                    ambiguous.add(i)
            for i, obs in enumerate(group):
                if i in assigned or i in ambiguous:
                    continue
                finite = sorted(c for c in cost[i] if c < _INF / 2)
                if len(finite) >= 2 and finite[1] <= finite[0] * ratio:
                    ambiguous.add(i)
                    for j in range(m):
                        cost[i][j] = _INF
            import numpy as np

            remaining_rows = [i for i in range(n) if i not in assigned and i not in ambiguous]
            remaining_cols = [j for j in range(m) if j not in reserved_cols]
            if remaining_rows and remaining_cols:
                sub = np.array([[cost[i][j] for j in remaining_cols] for i in remaining_rows], dtype=float)
                rows, cols = linear_sum_assignment(sub)
                for r_i, c_i in zip(rows, cols):
                    i = remaining_rows[r_i]
                    j = remaining_cols[c_i]
                    if cost[i][j] < _INF / 2:
                        kind, tid, _target = targets[j]
                        planned[group[i].observation_id] = ("track" if kind == "track" else "slot", tid)
                        assigned.add(i)
                        if kind == "slot":
                            reserved_cols.add(j)
        for i, obs in enumerate(group):
            if i in assigned:
                continue
            if i in ambiguous:
                planned[obs.observation_id] = ("ambiguous",)
                continue
            slot_id = self._register_open_slot(obs)
            planned[obs.observation_id] = ("slot", slot_id)

    def _apply_planned(self, obs: _Obs, planned: dict[str, tuple]) -> None:
        action = planned.get(obs.observation_id)
        if action is None:
            return
        if action[0] == "ambiguous":
            self._event_buf.append(
                self._event("association_ambiguous", obs.mt, None, {"observationId": obs.observation_id})
            )
            return
        if action[0] == "track":
            tr = self.tracks.get(action[1])
            if tr is not None and tr.status != "terminated" and self._cost(tr, obs) < _INF / 2:
                self._apply(tr, obs, update_filter=True)
                return
            self._spawn(obs)
            return
        if action[0] == "slot":
            slot = self.open_slots.get(action[1])
            if slot is None:
                self._spawn(obs)
                return
            if self._cost_target("slot", slot, obs) >= _INF / 2:
                # Slot metadata rejects this observation; isolate instead of mixing.
                self._spawn(obs)
                return
            fid = slot.get("fusion_id")
            if fid and fid in self.tracks and self.tracks[fid].status != "terminated":
                tr = self.tracks[fid]
                if self._cost(tr, obs) < _INF / 2:
                    self._apply(tr, obs, update_filter=True)
                    return
                self._spawn(obs)
                return
            created = self._spawn(obs)
            if created is not None:
                slot["fusion_id"] = created
            return
        self._spawn(obs)

    def _cost(self, tr: _Track, obs: _Obs) -> float:
        if tr.aircraft_id and obs.aircraft_id and tr.aircraft_id != obs.aircraft_id:
            return _INF
        gate = float(self.ms.get("gate_m", 80.0))
        dt = (obs.mt - tr.state_time).total_seconds()
        if dt < -1.0:
            return _INF
        x, y, vx, vy = (float(v) for v in tr.kf.x)
        innov = math.hypot(obs.x - (x + vx * dt), obs.y - (y + vy * dt))
        if innov > gate:
            return _INF
        hover = float(self.ms.get("hover_speed_mps", 1.5))
        heading_gate = float(self.ms.get("heading_gate_deg", 70.0))
        tr_heading = self._motion_heading(tr)
        if (
            tr_heading is not None
            and obs.heading is not None
            and (obs.speed or 0.0) > hover
            and (tr.last_speed or 0.0) > hover
            and _ang_diff(tr_heading, obs.heading) > heading_gate
        ):
            return _INF
        # Same detector cannot hold two local tracks on one global target inside a scan.
        # The Hungarian matrix already enforces one row per observation; a local-id
        # bonus stays inside the motion gate and is not an identity key.
        cost = innov
        # A device local id is a continuity hint inside the motion gate.
        # A different spelling is not exclusion by itself: renumber without a
        # concurrent rival must still associate. Same-scan rivals are separate
        # rows in one assignment group. Generated ids are not device identity.
        key = (obs.source, obs.detector_id, obs.source_track_id or "")
        if obs.origin == "device" and key in tr.binds:
            cost *= 0.85
        return cost

    def _motion_heading(self, tr: _Track) -> Optional[float]:
        vx, vy = float(tr.kf.x[2]), float(tr.kf.x[3])
        spd = math.hypot(vx, vy)
        if spd <= float(self.ms.get("hover_speed_mps", 1.5)):
            return None
        deg = math.degrees(math.atan2(vx, vy))
        return deg % 360.0

    def _spawn(self, obs: _Obs) -> Optional[str]:
        if len([t for t in self.tracks.values() if t.status != "terminated"]) >= int(self.cfg.get("max_tracks", 400)):
            self._reject_buf.append(Rejected(observationId=obs.observation_id, reason="max_tracks"))
            self._event_buf.append(self._event("capacity", obs.mt, None, {"reason": "max_tracks"}))
            return None
        self._ids += 1
        fid = f"ms-{self.epoch[:8]}-{self._ids:04d}"
        variance = obs.std_m ** 2
        kf = ConstantVelocityKF(obs.x, obs.y, self.q_pos, self.q_vel, variance)
        self._seed_velocity(kf, obs)
        init_alt = None
        init_datum = None
        init_vspeed = None if self.enable_vertical else obs.vertical_speed
        if self.enable_vertical:
            if obs.altitude is not None and _datum_ok_for_3d(obs.altitude_datum):
                init_alt = obs.altitude
                init_datum = "MSL"
        elif obs.altitude is not None:
            init_alt = obs.altitude
            init_datum = obs.altitude_datum
        tr = _Track(
            fusion_id=fid,
            created=obs.mt,
            kf=kf,
            state_time=obs.mt,
            last_observed=obs.mt,
            last_speed=obs.speed,
            last_heading=obs.heading,
            last_altitude=init_alt,
            last_datum=init_datum,
            vertical_speed=init_vspeed,
        )
        tr.contributing.add(obs.source)
        tr.contrib_time[obs.source] = obs.mt
        self.tracks[fid] = tr
        self._apply(tr, obs, update_filter=False)
        tr.updated_this_batch = True
        self._record_point(tr, obs)
        return fid

    def _seed_velocity(self, kf: ConstantVelocityKF, obs: _Obs) -> None:
        if obs.speed is None or obs.heading is None:
            return
        rad = math.radians(obs.heading)
        kf.x[2] = obs.speed * math.sin(rad)
        kf.x[3] = obs.speed * math.cos(rad)

    def _apply(self, tr: _Track, obs: _Obs, *, update_filter: bool) -> None:
        dt = (obs.mt - tr.state_time).total_seconds() if update_filter else 0.0
        # A reserved scan match is applied at its own time. An older measurement
        # must not rewind a filter that a later event has already moved.
        if update_filter and dt < -1e-6:
            filtered = False
        elif update_filter and self._should_filter(tr, obs):
            if dt > 1e-6:
                tr.kf.predict(max(dt, 1e-3))
            variance = self._measurement_variance(tr, obs)
            tr.kf.update(obs.x, obs.y, variance)
            self._floor_covariance(tr)
            self._touch_contrib(tr, obs.source, obs.mt)
            tr.state_time = obs.mt
            tr.updated_this_batch = True
            # Bind metadata + this-obs altitude must land before the committed point
            # so 2D pass-through does not copy the previous altitude onto a new point.
            self._touch_bind_and_kinematics(tr, obs, filtered_horizontal=True)
            self._record_point(tr, obs)
            filtered = True
        else:
            filtered = False
            self._touch_bind_and_kinematics(tr, obs, filtered_horizontal=False)
        if filtered:
            confirm_n = int(self.ms.get("confirm_distinct_times", 3))
            if tr.status in {"lost", "coasting"}:
                previous = tr.status
                tr.status = "tracked" if len(tr.distinct_times) >= confirm_n else "tentative"
                self._event_buf.append(self._event("track_reacquired", obs.mt, tr.fusion_id, {"from": previous}))
            xy = tr.kf.pos
            tr.recent_xy.append((float(xy[0]), float(xy[1])))
            tr.recent_xy = tr.recent_xy[-6:]

    def _touch_bind_and_kinematics(self, tr: _Track, obs: _Obs, *, filtered_horizontal: bool) -> None:
        if obs.origin == "generated":
            key = (obs.source, obs.detector_id, "")
        else:
            key = (obs.source, obs.detector_id, obs.source_track_id or "")
        bind = tr.binds.get(key)
        if bind is None:
            bind = _Bind(
                source=obs.source,
                detector_id=obs.detector_id,
                source_track_id=obs.source_track_id or "",
                origin=obs.origin,
                aircraft_id=obs.aircraft_id,
            )
            tr.binds[key] = bind
        if obs.origin == "generated":
            bind.origin = "generated"
            bind.source_track_id = obs.source_track_id or bind.source_track_id
        self._note_time(bind.times, obs.mt, int(self.ms.get("max_bind_times", 8)))
        bind.last_seen = obs.mt
        bind.aircraft_id = obs.aircraft_id or bind.aircraft_id
        need = int(self.ms.get("bind_confirm_times", 2))
        bind.confirmed = len(bind.times) >= need
        self._note_time(tr.distinct_times, obs.mt, int(self.ms.get("max_distinct_times", 32)))
        tr.last_observed = max(tr.last_observed, obs.mt)
        tr.consumed.append(obs.observation_id)
        consumed_cap = int(self.ms.get("max_consumed", 64))
        if len(tr.consumed) > consumed_cap:
            del tr.consumed[:-consumed_cap]
        self._cap_binds(tr, key)
        tr.flags.update(obs.flags)
        if obs.speed is not None:
            tr.last_speed = obs.speed
        if obs.heading is not None:
            tr.last_heading = obs.heading
        # 2D may pass through raw verticalSpeed; 3D keeps filtered estimate only.
        if (not self.enable_vertical) and obs.vertical_speed is not None:
            tr.vertical_speed = obs.vertical_speed
        # 2D: pass-through this observation's altitude onto the track before point record.
        # 3D: vertical KF consumes unique associated altitude; secondary may contribute
        # without advancing horizontal KF / status (filtered_horizontal=False).
        if self.enable_vertical:
            self._update_vertical(tr, obs, bind_confirmed=bind.confirmed, horizontal_commit=filtered_horizontal)
        elif obs.altitude is not None:
            tr.last_altitude = obs.altitude
            tr.last_datum = obs.altitude_datum
        if obs.object_class != "unknown":
            if tr.object_class in (None, "unknown"):
                tr.object_class = obs.object_class
            elif tr.object_class != obs.object_class:
                tr.object_class = "unknown"
                tr.flags.add("class_conflict")
        self._apply_identity(tr, obs)

    def _note_time(self, holder: set[str], when: datetime, cap: int) -> None:
        key = when.astimezone(timezone.utc).isoformat(timespec="microseconds")
        if key in holder:
            return
        if len(holder) >= cap:
            holder.pop()
        holder.add(key)

    def _cap_binds(self, tr: _Track, keep: tuple) -> None:
        cap = int(self.ms.get("max_binds_per_track", 24))
        if len(tr.binds) <= cap:
            return
        ranked = sorted(
            tr.binds,
            key=lambda k: (tr.binds[k].confirmed, tr.binds[k].last_seen or tr.created, k == keep),
        )
        for key in ranked:
            if len(tr.binds) <= cap:
                break
            if key == keep:
                continue
            tr.binds.pop(key, None)

    def _promote(self) -> None:
        confirm_n = int(self.ms.get("confirm_distinct_times", 3))
        for tr in self.tracks.values():
            if tr.status == "tentative" and len(tr.distinct_times) >= confirm_n:
                tr.status = "tracked"
                self._event_buf.append(self._event("track_confirmed", tr.state_time, tr.fusion_id, {}))

    def _should_filter(self, tr: _Track, obs: _Obs) -> bool:
        if not tr.aircraft_id:
            return True
        self._drop_stale_contrib(tr, obs.mt)
        chosen = self._primary_source(tr, obs)
        if tr.active_primary and tr.active_primary != chosen:
            self._event_buf.append(
                self._event(
                    "strategy_changed",
                    obs.mt,
                    tr.fusion_id,
                    {"fusionMethod": "primary_source", "reason": "primary_source_failover", "from": tr.active_primary, "to": chosen},
                )
            )
        tr.active_primary = chosen
        return obs.source == chosen

    def _touch_contrib(self, tr: _Track, source: str, when: datetime) -> None:
        tr.contrib_time[source] = when
        tr.contributing.add(source)
        if tr.aircraft_id:
            self._drop_stale_contrib(tr, when)

    def _drop_stale_contrib(self, tr: _Track, when: datetime) -> None:
        fresh_s = float(self.ms.get("primary_fresh_s", 4.0))
        for src, seen in list(tr.contrib_time.items()):
            if (when - seen).total_seconds() > fresh_s:
                tr.contributing.discard(src)

    def _primary_source(self, tr: _Track, obs: _Obs) -> str:
        fresh_s = float(self.ms.get("primary_fresh_s", 4.0))
        order = list(self.ms.get("primary_source_order") or ["rid", "spectrum", "radar"])
        eligible = set(tr.contributing)
        eligible.add(obs.source)
        for src, seen in tr.contrib_time.items():
            if (obs.mt - seen).total_seconds() <= fresh_s:
                eligible.add(src)
        for src in order:
            if src in eligible:
                return src
        return obs.source

    def _measurement_variance(self, tr: _Track, obs: _Obs) -> float:
        var = obs.std_m ** 2
        # Same-source reports a few milliseconds apart are not independent samples.
        for other in tr.history[-6:]:
            if other.get("source") != obs.source:
                continue
            if abs((obs.mt - _aware(other["stateTime"])).total_seconds()) <= 0.05:
                var *= 4.0
                tr.flags.add("repeated_physical_measurement")
                break
        return var

    def _floor_covariance(self, tr: _Track) -> None:
        floor_std = float(self.ms.get("variance_floor_std_m", 1.0))
        floor = floor_std ** 2
        if float(tr.kf.P[0, 0]) < floor:
            tr.kf.P[0, 0] = floor
        if float(tr.kf.P[1, 1]) < floor:
            tr.kf.P[1, 1] = floor

    def _apply_identity(self, tr: _Track, obs: _Obs) -> None:
        if not obs.aircraft_id:
            return
        if tr.aircraft_id is None:
            tr.aircraft_id = obs.aircraft_id
            tr.identity = "identified"
            tr.flags.discard("identity_unknown")
            if tr.fusion_method != "primary_source":
                tr.fusion_method = "primary_source"
                self._event_buf.append(
                    self._event("strategy_changed", obs.mt, tr.fusion_id, {"fusionMethod": "primary_source"})
                )
            tr.active_primary = self._primary_source(tr, obs)
            self._event_buf.append(
                self._event("identity_attached", obs.mt, tr.fusion_id, {"aircraftId": obs.aircraft_id})
            )
            return
        if tr.aircraft_id != obs.aircraft_id:
            tr.identity = "conflict"
            tr.flags.add("identity_conflict")
            self._event_buf.append(
                self._event("identity_conflict", obs.mt, tr.fusion_id, {"aircraftId": obs.aircraft_id})
            )

    def _altitude_at(
        self, tr: _Track, when: datetime, *, direct_oid: Optional[str] = None
    ) -> tuple[Optional[float], Optional[str], str, list[str], Optional[float]]:
        """Query fused altitude at event time without advancing the vertical KF clock.

        Returns (altitude, datum, mode, direct_altitude_observation_ids, sigma_m).
        """
        if not self.enable_vertical:
            return None, None, "unknown", [], None
        if tr.vkf is None or tr.altitude_state_time is None or tr.last_altitude_observed_at is None:
            return None, None, "unknown", [], None
        dt_state = (when - tr.altitude_state_time).total_seconds()
        if dt_state < -1e-6:
            # Do not read a future filter state for a past query time.
            return None, None, "unknown", [], None
        horizon = float(self.ms3.get("altitude_predict_horizon_s", 4.0))
        age_obs = (when - tr.last_altitude_observed_at).total_seconds()
        if age_obs > horizon + 1e-9:
            return None, None, "expired", [], None
        alt = float(tr.vkf.alt) + float(tr.vkf.vspeed) * dt_state
        if abs(age_obs) <= 1e-6 and direct_oid:
            mode = "measured_filtered"
            oids = [direct_oid]
        elif abs(dt_state) <= 1e-6 and direct_oid and direct_oid in tr.altitude_observation_ids[-1:]:
            mode = "measured_filtered"
            oids = [direct_oid]
        else:
            mode = "predicted"
            oids = []  # prediction: no new direct altitude observation for this point
        try:
            import numpy as np

            P = np.array(tr.vkf.P, dtype=float, copy=True)
            if dt_state > 1e-9:
                F = np.array([[1.0, dt_state], [0.0, 1.0]], dtype=float)
                Q = np.diag([float(tr.vkf.q_pos) * dt_state, float(tr.vkf.q_vel) * dt_state])
                P = F @ P @ F.T + Q
            sigma = float(P[0, 0]) ** 0.5
        except Exception:  # noqa: BLE001
            sigma = tr.altitude_sigma_m
        return alt, "MSL", mode, oids, sigma

    def _point_altitude_for_obs(
        self, tr: _Track, obs: _Obs
    ) -> tuple[Optional[float], Optional[str], str, list[str], Optional[float]]:
        """Altitude attached to a newly committed horizontal point at obs.mt."""
        if self.enable_vertical:
            direct = None
            if (
                obs.altitude is not None
                and _datum_ok_for_3d(obs.altitude_datum)
                and tr.last_altitude_observed_at is not None
                and abs((obs.mt - tr.last_altitude_observed_at).total_seconds()) <= 1e-6
                and tr.altitude_observation_ids
                and tr.altitude_observation_ids[-1] == obs.observation_id
            ):
                direct = obs.observation_id
            return self._altitude_at(tr, obs.mt, direct_oid=direct)
        if obs.altitude is not None and obs.altitude_datum not in (None, "unknown"):
            return obs.altitude, obs.altitude_datum, "passthrough", [obs.observation_id], None
        return None, None, "unknown", [], None

    def _record_point(self, tr: _Track, obs: _Obs) -> None:
        lat, lon = self.enu.to_ll(*tr.kf.pos)
        point_id = hashlib.sha256(
            f"{self.epoch}|{tr.fusion_id}|{_iso(obs.mt)}|{obs.observation_id}".encode("utf-8")
        ).hexdigest()[:16]
        alt, datum, alt_mode, alt_oids, sigma = self._point_altitude_for_obs(tr, obs)
        point = {
            "pointId": point_id,
            "fusionId": tr.fusion_id,
            "trackSegmentId": tr.fusion_id,
            "stateTime": _iso(obs.mt),
            "longitude": lon,
            "latitude": lat,
            "altitude": alt,
            "altitudeDatum": datum,
            "altitudeMode": alt_mode,
            "altitudeSigmaM": sigma,
            "positionMode": "measured_assisted",
            "contributingSources": sorted(tr.contributing or {obs.source}),
            "observationIds": [obs.observation_id],
            "altitudeObservationIds": alt_oids,
            "altitudePriorNote": "filter_state_may_include_earlier_measurements"
            if self.enable_vertical and alt is not None
            else None,
            "source": obs.source,
        }
        cap = int(self.ms.get("committed_history_cap", 80))
        tr.history.append(point)
        if len(tr.history) > cap:
            tr.history = tr.history[-cap:]
            tr.flags.add("history_capped")
        self._update_buf.append(point)

    def _alt_r(self, source: str) -> float:
        std = (self.ms3.get("altitude_std_m") or {}).get(source)
        if std is None:
            std = {"rid": 5.0, "spectrum": 15.0, "radar": 25.0}.get(source, 20.0)
        return float(std) ** 2

    def _update_vertical(
        self,
        tr: _Track,
        obs: _Obs,
        *,
        bind_confirmed: bool,
        horizontal_commit: bool,
    ) -> None:
        if not self.enable_vertical:
            return
        if obs.altitude is None:
            return
        if not _datum_ok_for_3d(obs.altitude_datum):
            tr.raw_altitude_evidence.append(
                {
                    "observationId": obs.observation_id,
                    "altitude": obs.altitude,
                    "altitudeDatum": obs.altitude_datum,
                    "reason": "unsupported_datum",
                    "measurementTime": _iso(obs.mt),
                }
            )
            if len(tr.raw_altitude_evidence) > 32:
                tr.raw_altitude_evidence = tr.raw_altitude_evidence[-32:]
            self._event_buf.append(
                self._event(
                    "altitude_datum_unsupported",
                    obs.mt,
                    tr.fusion_id,
                    {"observationId": obs.observation_id, "altitudeDatum": obs.altitude_datum},
                )
            )
            # Never promote unsupported raw altitude into fused last_altitude / snapshot.
            return
        # Ambiguous / unconfirmed bind must not update vertical state.
        # Exception: same confirmed SN on an already-bound track may contribute altitude
        # from a newly seen detector on the first hit (secondary vertical-only path).
        if not bind_confirmed and len(tr.binds) > 1:
            same_sn = bool(tr.aircraft_id and obs.aircraft_id and tr.aircraft_id == obs.aircraft_id)
            has_confirmed_peer = any(b.confirmed for b in tr.binds.values())
            if not (same_sn and has_confirmed_peer):
                return
        innov_gate = float(self.ms3.get("altitude_innov_m", 80.0))
        horizon = float(self.ms3.get("altitude_predict_horizon_s", 4.0))
        expired = (
            tr.last_altitude_observed_at is not None
            and (obs.mt - tr.last_altitude_observed_at).total_seconds() > horizon + 1e-9
        )
        if tr.vkf is None or expired:
            # Fresh init, or re-init after altitude expiry so stale velocity cannot lock out recovery.
            tr.vkf = ConstantVelocity1D(obs.altitude, self.q_alt, self.q_vspeed, self._alt_r(obs.source))
            tr.altitude_state_time = obs.mt
            tr.last_altitude_observed_at = obs.mt
            tr.last_altitude = float(tr.vkf.alt)
            tr.last_datum = "MSL"
            tr.altitude_mode = "measured_filtered"
            tr.vertical_speed = float(tr.vkf.vspeed)
            tr.altitude_sigma_m = float(tr.vkf.P[0, 0]) ** 0.5
            tr.altitude_observation_ids = [obs.observation_id]
            if expired:
                self._event_buf.append(
                    self._event(
                        "altitude_reinitialized",
                        obs.mt,
                        tr.fusion_id,
                        {"observationId": obs.observation_id, "reason": "expired_gap"},
                    )
                )
            if not horizontal_commit:
                self._emit_altitude_update(tr, obs, role="init" if not expired else "reinit_after_expiry")
            return
        assert tr.altitude_state_time is not None
        dt = (obs.mt - tr.altitude_state_time).total_seconds()
        if dt < -1e-6:
            self._event_buf.append(
                self._event("altitude_negative_dt", obs.mt, tr.fusion_id, {"observationId": obs.observation_id})
            )
            return
        # Gate on predicted residual before mutating the filter.
        pred_alt = float(tr.vkf.alt)
        if dt > 1e-6:
            pred_alt = pred_alt + float(tr.vkf.vspeed) * dt
        innov = abs(float(obs.altitude) - pred_alt)
        if innov > innov_gate:
            tr.raw_altitude_evidence.append(
                {
                    "observationId": obs.observation_id,
                    "altitude": obs.altitude,
                    "altitudeDatum": obs.altitude_datum,
                    "reason": "innovation_rejected",
                    "innovM": innov,
                    "measurementTime": _iso(obs.mt),
                }
            )
            if len(tr.raw_altitude_evidence) > 32:
                tr.raw_altitude_evidence = tr.raw_altitude_evidence[-32:]
            self._event_buf.append(
                self._event(
                    "altitude_innovation_rejected",
                    obs.mt,
                    tr.fusion_id,
                    {"observationId": obs.observation_id, "innovM": innov},
                )
            )
            return
        if dt > 1e-6:
            tr.vkf.predict(max(dt, 1e-3))
        tr.vkf.update(obs.altitude, self._alt_r(obs.source))
        tr.altitude_state_time = obs.mt
        tr.last_altitude_observed_at = obs.mt
        tr.last_altitude = float(tr.vkf.alt)
        tr.last_datum = "MSL"
        tr.vertical_speed = float(tr.vkf.vspeed)
        tr.altitude_sigma_m = float(tr.vkf.P[0, 0]) ** 0.5
        tr.altitude_mode = "measured_filtered"
        tr.altitude_observation_ids.append(obs.observation_id)
        if len(tr.altitude_observation_ids) > 32:
            tr.altitude_observation_ids = tr.altitude_observation_ids[-32:]
        if not horizontal_commit:
            self._emit_altitude_update(tr, obs, role="secondary_or_vertical_only")

    def _emit_altitude_update(self, tr: _Track, obs: _Obs, *, role: str) -> None:
        self._alt_ids += 1
        upd = {
            "altitudeUpdateId": f"alt-{self.epoch[:8]}-{self._alt_ids:06d}",
            "fusionId": tr.fusion_id,
            "trackSegmentId": tr.fusion_id,
            "epoch": self.epoch,
            "stateTime": _iso(obs.mt),
            "altitude": tr.last_altitude,
            "altitudeDatum": "MSL",
            "altitudeMode": tr.altitude_mode,
            "verticalSpeed": tr.vertical_speed,
            "altitudeStateTime": _iso(tr.altitude_state_time) if tr.altitude_state_time else None,
            "lastAltitudeObservedAt": _iso(tr.last_altitude_observed_at) if tr.last_altitude_observed_at else None,
            "altitudeObservationIds": [obs.observation_id],
            "role": role,
            "source": obs.source,
        }
        self._alt_update_buf.append(upd)

    def _take_alt_updates(self) -> list[dict]:
        updates = list(self._alt_update_buf)
        self._alt_update_buf = []
        return updates

    def _try_merge(self) -> None:
        gate = float(self.ms.get("merge_gate_m", 30.0))
        need = int(self.ms.get("merge_min_times", 3))
        live = [t for t in self.tracks.values() if t.status == "tentative"]
        live.sort(key=lambda t: t.created)
        removed: set[str] = set()
        for i, a in enumerate(live):
            if a.fusion_id in removed or len(a.distinct_times) < need or len(a.recent_xy) < need:
                continue
            dets_a = {b.detector_id for b in a.binds.values()}
            for b in live[i + 1 :]:
                if b.fusion_id in removed or len(b.distinct_times) < need or len(b.recent_xy) < need:
                    continue
                if a.aircraft_id and b.aircraft_id and a.aircraft_id != b.aircraft_id:
                    continue
                dets_b = {bind.detector_id for bind in b.binds.values()}
                if dets_a & dets_b:
                    continue
                n = min(len(a.recent_xy), len(b.recent_xy), need)
                close = True
                for k in range(1, n + 1):
                    ax, ay = a.recent_xy[-k]
                    bx, by = b.recent_xy[-k]
                    if math.hypot(ax - bx, ay - by) > gate:
                        close = False
                        break
                if not close:
                    continue
                ha, hb = self._motion_heading(a), self._motion_heading(b)
                if ha is not None and hb is not None and _ang_diff(ha, hb) > float(self.ms.get("heading_gate_deg", 70)):
                    continue
                self._merge_into(a, b)
                removed.add(b.fusion_id)

    def _merge_into(self, keep: _Track, drop: _Track) -> None:
        keep.aliases.append(drop.fusion_id)
        keep.aliases.extend(drop.aliases)
        keep.binds.update(drop.binds)
        keep.contributing.update(drop.contributing)
        keep.distinct_times.update(drop.distinct_times)
        keep.consumed.extend(drop.consumed)
        while len(keep.distinct_times) > int(self.ms.get("max_distinct_times", 32)):
            keep.distinct_times.pop()
        consumed_cap = int(self.ms.get("max_consumed", 64))
        if len(keep.consumed) > consumed_cap:
            del keep.consumed[:-consumed_cap]
        self._cap_binds(keep, next(iter(keep.binds)))
        if keep.aircraft_id is None and drop.aircraft_id:
            keep.aircraft_id = drop.aircraft_id
            keep.identity = drop.identity
        drop.status = "terminated"
        self.tracks.pop(drop.fusion_id, None)
        self._event_buf.append(
            self._event("alias", keep.state_time, keep.fusion_id, {"aliasOf": drop.fusion_id})
        )

    def _lifecycle(self, pt: datetime) -> None:
        coast = float(self.ms.get("coast_s", 4.0))
        lost = float(self.ms.get("lost_s", 12.0))
        end = float(self.ms.get("terminate_s", 30.0))
        for tr in list(self.tracks.values()):
            age = (pt - tr.state_time).total_seconds()
            if tr.status == "terminated":
                continue
            bind_ttl = end
            for key, bind in list(tr.binds.items()):
                if bind.last_seen is not None and (pt - bind.last_seen).total_seconds() > bind_ttl:
                    tr.binds.pop(key, None)
            if age > end:
                tr.status = "terminated"
                self._event_buf.append(self._event("track_ended", pt, tr.fusion_id, {}))
                self.tracks.pop(tr.fusion_id, None)
                continue
            if age > lost and tr.status != "lost":
                tr.status = "lost"
                self._event_buf.append(self._event("track_lost", pt, tr.fusion_id, {}))
            elif age > coast and tr.status == "tracked":
                tr.status = "coasting"

    def _take_updates(self) -> list[dict]:
        updates = list(self._update_buf)
        self._update_buf = []
        return updates

    def _event(self, kind: str, when: datetime, fusion_id: Optional[str], payload: dict) -> FusionEvent:
        return FusionEvent(type=kind, time=_iso(when), fusionId=fusion_id, payload=payload)

    def _respond(
        self,
        batch_id: str,
        watermark: str,
        *,
        rejected: Optional[list[Rejected]] = None,
        updates: Optional[list[dict]] = None,
        altitude_updates: Optional[list[dict]] = None,
        error: Optional[str] = None,
    ) -> ProcessResponse:
        if not hasattr(self, "_event_buf"):
            self._event_buf = []
        if not hasattr(self, "_update_buf"):
            self._update_buf = []
        if not hasattr(self, "_reject_buf"):
            self._reject_buf = []
        events = list(self._event_buf)
        extra_rejected = list(self._reject_buf)
        self._event_buf = []
        self._reject_buf = []
        wm = self.watermark
        wm_text = _iso(wm) if wm is not None else watermark
        return ProcessResponse(
            sessionId=self.session_id,
            batchId=batch_id,
            epoch=self.epoch,
            snapshotSeq=self.seq,
            algorithmVersion=str(self.cfg.get("algorithmVersion")),
            configVersion=str(self.cfg.get("configVersion")),
            watermark=wm_text,
            tracks=self._snapshots(),
            rejected=list(rejected or []) + extra_rejected,
            events=events,
            error=error,
            fusionProfile=self.profile,
            trajectoryUpdates=list(updates or []),
            altitudeUpdates=list(altitude_updates or []),
        )

    def _snapshots(self) -> list[TargetSnapshot]:
        horizon = float(self.ms.get("predict_horizon_s", 4.0))
        now = self.last_pt
        out: list[TargetSnapshot] = []
        order = list(self.ms.get("primary_source_order") or ["rid", "spectrum", "radar"])
        for tr in sorted(self.tracks.values(), key=lambda t: t.fusion_id):
            if tr.status == "terminated":
                continue
            age = 0.0 if now is None else max(0.0, (now - tr.state_time).total_seconds())
            x, y = tr.kf.pos
            mode = "measured_assisted"
            if age > horizon:
                mode = "stale"
            elif age > 0.5 and not tr.updated_this_batch:
                mode = "predicted"
                vx, vy = tr.kf.vel
                step = min(age, horizon)
                x += vx * step
                y += vy * step
            tr.updated_this_batch = False
            lat, lon = self.enu.to_ll(x, y)
            sources = sorted({b.source for b in tr.binds.values()})
            contributing = [s for s in order if s in tr.contributing]
            position_source = contributing[0] if contributing else (sources[0] if sources else None)
            spd, hdg = self._display_kinematics(tr)
            flags = sorted(tr.flags)
            if mode == "predicted":
                flags = sorted(set(flags) | {"predicted_display"})
            query_t = now or tr.state_time
            if self.enable_vertical:
                snap_alt, snap_datum, snap_amode, _oids, snap_sigma = self._altitude_at(tr, query_t)
                if snap_alt is None:
                    snap_datum = None
                if snap_sigma is not None:
                    flags = sorted(set(flags) | {f"altitude_sigma_m:{snap_sigma:.3f}"})
                elif tr.vkf is None:
                    flags = sorted(set(flags) | {"altitude_uncertainty_not_available"})
                if tr.raw_altitude_evidence:
                    flags = sorted(set(flags) | {"raw_altitude_evidence_present_not_fused"})
            else:
                snap_alt = tr.last_altitude if tr.last_datum not in (None, "unknown") else None
                snap_datum = tr.last_datum if tr.last_datum not in (None, "unknown") else None
                snap_amode = None
            refs = []
            for bind in sorted(tr.binds.values(), key=lambda b: (b.detector_id, b.source_track_id)):
                refs.append(
                    SourceTrackRef(
                        source=bind.source,  # type: ignore[arg-type]
                        detectorId=bind.detector_id,
                        sourceTrackId=bind.source_track_id,
                        aircraftId=bind.aircraft_id,
                        lastSeen=_iso(bind.last_seen or tr.last_observed),
                        bindingStatus="confirmed" if bind.confirmed else "candidate",
                        origin=bind.origin,  # type: ignore[arg-type]
                    )
                )
            out.append(
                TargetSnapshot(
                    fusionId=tr.fusion_id,
                    trackSegmentId=tr.fusion_id,
                    aircraftId=tr.aircraft_id,
                    longitude=lon,
                    latitude=lat,
                    altitude=snap_alt,
                    altitudeDatum=snap_datum,
                    altitudeMode=snap_amode,
                    altitudeStateTime=_iso(tr.altitude_state_time) if tr.altitude_state_time else None,
                    lastAltitudeObservedAt=_iso(tr.last_altitude_observed_at) if tr.last_altitude_observed_at else None,
                    altitudeObservationIds=list(tr.altitude_observation_ids[-8:]) if self.enable_vertical else [],
                    speed=spd,
                    heading=hdg,
                    verticalSpeed=tr.vertical_speed,
                    stateTime=_iso(tr.state_time),
                    lastObservedAt=_iso(tr.last_observed),
                    displayStateTime=_iso(now or tr.state_time),
                    trackStatus=tr.status,  # type: ignore[arg-type]
                    positionMode=mode,  # type: ignore[arg-type]
                    positionSource=position_source,  # type: ignore[arg-type]
                    sources=sources,  # type: ignore[arg-type]
                    sourceTracks=refs,
                    qualityFlags=flags,
                    aliases=list(tr.aliases),
                    committedHistory=list(tr.history),
                    identityStatus=tr.identity,  # type: ignore[arg-type]
                    objectClass=tr.object_class,  # type: ignore[arg-type]
                    fusionMethod=tr.fusion_method,  # type: ignore[arg-type]
                    contributingSources=contributing,  # type: ignore[arg-type]
                )
            )
        return out

    def _display_kinematics(self, tr: _Track) -> tuple[Optional[float], Optional[float]]:
        vx, vy = tr.kf.vel
        spd = math.hypot(vx, vy)
        hover = float(self.ms.get("hover_speed_mps", 1.5))
        if spd > hover:
            heading = math.degrees(math.atan2(vx, vy)) % 360.0
            tr.flags.add("speed_from_filter")
            return spd, heading
        tr.flags.add("speed_passthrough_or_unknown")
        if tr.last_speed is not None and tr.last_speed <= hover:
            return tr.last_speed, None
        return tr.last_speed, tr.last_heading


class MultisensorStore:
    def __init__(self, cfg: dict, *, clock=None):
        self.cfg = cfg
        self.sessions: dict[str, MultisensorSession] = {}
        self.profiles: dict[str, str] = {}
        self.created: dict[str, datetime] = {}
        self.last_active: dict[str, datetime] = {}
        self.lock = threading.RLock()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get(self, session_id: str, *, profile: str = PROFILE) -> MultisensorSession:
        with self.lock:
            self._evict()
            sess = self.sessions.get(session_id)
            if sess is None:
                sess = MultisensorSession(session_id, self.cfg, profile=profile, clock=self._clock)
                self.sessions[session_id] = sess
                self.profiles[session_id] = profile
                now = self._clock()
                self.created[session_id] = now
                self.last_active[session_id] = now
            else:
                existing = self.profiles.get(session_id, PROFILE)
                if existing != profile:
                    # Caller maps this to HTTP 409 session_profile_conflict.
                    raise ValueError("session_profile_conflict")
                self.last_active[session_id] = self._clock()
            return sess

    def drop(self, session_id: str) -> None:
        with self.lock:
            self.sessions.pop(session_id, None)
            self.profiles.pop(session_id, None)
            self.created.pop(session_id, None)
            self.last_active.pop(session_id, None)

    def _evict(self) -> None:
        # Idle TTL: recycle only sessions that have not been touched recently.
        idle_ttl = float(self.cfg.get("session_idle_ttl_s", self.cfg.get("session_ttl_s", 3600)))
        max_life = self.cfg.get("session_max_lifetime_s")
        now = self._clock()
        dead: list[str] = []
        for sid, last in list(self.last_active.items()):
            if (now - last).total_seconds() > idle_ttl:
                dead.append(sid)
                continue
            if max_life is not None:
                created = self.created.get(sid, last)
                if (now - created).total_seconds() > float(max_life):
                    dead.append(sid)
        for sid in dead:
            self.sessions.pop(sid, None)
            self.profiles.pop(sid, None)
            self.created.pop(sid, None)
            self.last_active.pop(sid, None)


def _chunks_keeping_scans(ordered: list[dict]) -> list[list[dict]]:
    """Emit time-ordered slices that do not split an explicit detector scan."""
    last_index: dict[tuple[str, str], int] = {}
    for i, row in enumerate(ordered):
        scan = _blank(row.get("scanId"))
        det = _blank(row.get("detectorId")) or ""
        if scan:
            last_index[(det, scan)] = i
    chunks: list[list[dict]] = []
    start = 0
    i = 0
    n = len(ordered)
    while i < n:
        i += 1
        closed = True
        for j in range(start, i):
            row = ordered[j]
            scan = _blank(row.get("scanId"))
            det = _blank(row.get("detectorId")) or ""
            if scan and last_index.get((det, scan), j) >= i:
                closed = False
                break
        if closed:
            chunks.append(ordered[start:i])
            start = i
    if start < n:
        chunks.append(ordered[start:])
    return chunks


def _max_instant(rows: list[dict]) -> Optional[datetime]:
    times = [_aware(row.get("measurementTime")) for row in rows]
    times = [item for item in times if item is not None]
    return max(times) if times else None


def replay_job(
    cfg: dict,
    job_id: str,
    observations: list[dict],
    max_snapshots: int,
    *,
    fusion_profile: str = PROFILE,
) -> ReplayResponse:
    if fusion_profile not in SUPPORTED_PROFILES:
        return ReplayResponse(
            jobId=job_id,
            fusionProfile=fusion_profile,
            algorithmVersion=str(cfg.get("algorithmVersion")),
            configVersion=str(cfg.get("configVersion")),
            summary={"input": len(observations), "error": "unsupported_profile"},
            snapshots=[],
            trajectory=[],
            events=[],
            rejected=[],
            error="unsupported_profile",
        )
    ms = cfg.get("multisensor_v1") or {}
    limit = int(ms.get("max_replay_observations", 20000))
    version = str(cfg.get("algorithmVersion"))
    config_version = str(cfg.get("configVersion"))
    if len(observations) > limit:
        return ReplayResponse(
            jobId=job_id,
            fusionProfile=fusion_profile,
            algorithmVersion=version,
            configVersion=config_version,
            summary={"input": len(observations), "error": "too_many_observations"},
            snapshots=[],
            trajectory=[],
            events=[],
            rejected=[],
            error="too_many_observations",
        )
    sess = MultisensorSession(job_id, cfg, profile=fusion_profile)
    ordered = sorted(
        observations,
        key=lambda r: (
            _aware(r.get("measurementTime")) or datetime.max.replace(tzinfo=timezone.utc),
            str(r.get("observationId") or ""),
        ),
    )
    groups = _chunks_keeping_scans(ordered)
    snapshots: list[dict] = []
    trajectory: list[dict] = []
    altitude_updates: list[dict] = []
    rejected: list[dict] = []
    events: list[dict] = []
    seen_points: set[str] = set()
    seen_alt: set[str] = set()

    def _collect(resp: ProcessResponse, pt: str) -> None:
        if resp.error:
            return
        snapshots.append(
            {
                "batchId": resp.batchId,
                "processingTime": pt,
                "watermark": resp.watermark,
                "tracks": [t.model_dump() for t in resp.tracks],
                "altitudeUpdates": list(resp.altitudeUpdates or []),
            }
        )
        for point in resp.trajectoryUpdates:
            if point["pointId"] not in seen_points:
                seen_points.add(point["pointId"])
                trajectory.append(point)
        for upd in resp.altitudeUpdates or []:
            uid = upd.get("altitudeUpdateId")
            if uid and uid not in seen_alt:
                seen_alt.add(uid)
                altitude_updates.append(upd)
        rejected.extend(item.model_dump() for item in resp.rejected)
        events.extend(item.model_dump() for item in resp.events)

    error = None
    processed_rows = 0
    for i, rows in enumerate(groups):
        mt = _max_instant(rows)
        pt = _iso(mt + timedelta(seconds=sess.reorder_s)) if mt is not None else str(rows[0].get("measurementTime"))
        resp = sess.process(f"{job_id}-{i}", pt, rows, "replay", retain_idempotency=False)
        if resp.error:
            error = resp.error
            rejected.extend(item.model_dump() for item in resp.rejected)
            break
        processed_rows += len(rows)
        _collect(resp, pt)
    if error is None and groups:
        last_mt = _max_instant(ordered) or datetime.now(timezone.utc)
        pt = _iso(last_mt + timedelta(seconds=sess.reorder_s + 0.25))
        resp = sess.process(f"{job_id}-flush", pt, [], "replay", retain_idempotency=False)
        if resp.error:
            error = resp.error
        else:
            _collect(resp, pt)
    note = None
    distinct_ids: set[str] = set()
    for snap in snapshots:
        for tr in snap["tracks"]:
            distinct_ids.add(tr["fusionId"])
            distinct_ids.update(tr.get("aliases") or [])
    if error:
        note = "replay_stopped_before_all_observations_processed"
    elif max_snapshots > 0 and len(snapshots) > max_snapshots:
        if max_snapshots == 1:
            snapshots = [snapshots[-1]]
        else:
            head = snapshots[:-1]
            keep = max_snapshots - 1
            step = max(1, math.ceil(len(head) / keep)) if head else 1
            snapshots = head[::step][:keep] + [snapshots[-1]]
            if len(snapshots) > max_snapshots:
                snapshots = snapshots[-max_snapshots:]
        note = "snapshots_sampled_all_observations_processed_last_snapshot_kept"
    by_source: dict[str, int] = {}
    for row in observations:
        kind = SOURCE_MAP.get(str(row.get("source") or "").lower(), "unknown")
        by_source[kind] = by_source.get(kind, 0) + 1
    times = [_aware(r.get("measurementTime")) for r in observations]
    times = [t for t in times if t is not None]
    rejected_ids = {item.get("observationId") for item in rejected if item.get("observationId")}
    unprocessed = max(0, len(observations) - processed_rows)
    summary = {
        "input": len(observations),
        "processed": processed_rows,
        "valid": len(observations) - len(rejected_ids),
        "rejected": len(rejected),
        "unprocessed": unprocessed,
        "by_source": by_source,
        "time_range": [_iso(min(times)), _iso(max(times))] if times else None,
        "tracks_in_last_snapshot": len(snapshots[-1]["tracks"]) if snapshots else 0,
        "distinct_fusion_ids": len(distinct_ids),
        "last_snapshot_track_count_is_not_total_targets": True,
        "trajectory_points": len(trajectory),
        "altitude_updates": len(altitude_updates),
        "note": note or "sorted_replay_not_rts_smoother",
        "offline_vs_realtime": "offline sorts by measurementTime and flushes; realtime rejects observations behind the committed frontier",
    }
    return ReplayResponse(
        jobId=job_id,
        fusionProfile=fusion_profile,
        algorithmVersion=version,
        configVersion=config_version,
        summary=summary,
        snapshots=snapshots,
        trajectory=trajectory,
        altitudeUpdates=altitude_updates,
        events=events,
        rejected=rejected,
        error=error,
    )
