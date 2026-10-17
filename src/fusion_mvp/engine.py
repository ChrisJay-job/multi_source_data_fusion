from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import numpy as np
import yaml
from scipy.optimize import linear_sum_assignment

from .geo import LocalENU
from .kalman import ConstantVelocityKF
from .mapping import iso, normalize_row, parse_dt
from .models import (
    FusionEvent,
    Observation,
    ProcessResponse,
    Rejected,
    SourceKind,
    SourceTrackRef,
    TargetSnapshot,
)


def load_config(path: str | Path | None = None) -> dict:
    p = Path(path or Path(__file__).resolve().parents[2] / "config" / "fusion.yaml")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _request_fingerprint(batch_id: str, processing_time: str, mode: str, observations: list[dict]) -> str:
    blob = json.dumps(
        {"batchId": batch_id, "processingTime": processing_time, "mode": mode, "observations": observations},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _obs_content_hash(raw: dict) -> str:
    return hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


@dataclass
class BoundSource:
    source: SourceKind
    detectorId: str
    sourceTrackId: str
    aircraftId: Optional[str]
    lastSeen: datetime
    hits: int = 1
    confirmed: bool = False


@dataclass
class Track:
    fusionId: str
    segmentId: str
    kf: ConstantVelocityKF
    status: str = "tentative"
    aircraftId: Optional[str] = None
    createdAt: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    lastObservedAt: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    stateTime: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    positionMode: str = "measured_assisted"
    positionSource: Optional[SourceKind] = None
    bindings: dict[str, BoundSource] = field(default_factory=dict)
    hits: int = 0
    aliases: list[str] = field(default_factory=list)
    qualityFlags: list[str] = field(default_factory=list)
    lastAlt: Optional[float] = None
    lastHeading: Optional[float] = None
    lastSpeed: Optional[float] = None
    altitudeDatum: Optional[str] = "unknown"
    terminatedAt: Optional[datetime] = None

    def bind_key(self, source: str, detector: str, tid: str) -> str:
        return f"{source}|{detector}|{tid}"


@dataclass
class CacheEntry:
    fingerprint: str
    stored_at: datetime
    response: Optional[ProcessResponse] = None
    status: str = "complete"  # complete | evicted | expired


class FusionSession:
    def __init__(self, session_id: str, cfg: dict, epoch: str | None = None):
        self.session_id = session_id
        self.cfg = cfg
        self.epoch = epoch or uuid4().hex[:12]
        self.seq = 0
        self.geo = LocalENU(cfg["origin"]["latitude"], cfg["origin"]["longitude"])
        self.tracks: dict[str, Track] = {}
        self.buffer: list[tuple[datetime, Observation, dict]] = []
        self.event_watermark: Optional[datetime] = None
        self.reported_watermark: Optional[datetime] = None
        self.last_processing: Optional[datetime] = None
        self.mode: Optional[str] = None
        self.cache: dict[str, CacheEntry] = {}
        self.seen_obs: dict[str, str] = {}
        self.next_id = 1
        self.event_seq = 0
        self.created = datetime.now(timezone.utc)
        self.lock = threading.RLock()
        self._reject_identity_pairs: set[tuple[str, str]] = set()

    def _fid(self) -> str:
        v = f"F{self.epoch}-{self.next_id:05d}"
        self.next_id += 1
        return v

    def _event(self, typ: str, t: datetime, fid: Optional[str], **payload) -> FusionEvent:
        self.event_seq += 1
        eid = f"E{self.epoch}-{self.event_seq:06d}"
        return FusionEvent(type=typ, time=iso(t), fusionId=fid, payload={"eventId": eid, **payload})

    def _snapshot_state(self) -> dict:
        return {
            "tracks": copy.deepcopy(self.tracks),
            "buffer": copy.deepcopy(self.buffer),
            "event_watermark": self.event_watermark,
            "reported_watermark": self.reported_watermark,
            "last_processing": self.last_processing,
            "next_id": self.next_id,
            "event_seq": self.event_seq,
            "seq": self.seq,
            "seen_obs": dict(self.seen_obs),
            "reject_identity_pairs": set(self._reject_identity_pairs),
            "cache": copy.deepcopy(self.cache),
        }

    def _restore_state(self, snap: dict) -> None:
        self.tracks = snap["tracks"]
        self.buffer = snap["buffer"]
        self.event_watermark = snap["event_watermark"]
        self.reported_watermark = snap["reported_watermark"]
        self.last_processing = snap["last_processing"]
        self.next_id = snap["next_id"]
        self.event_seq = snap["event_seq"]
        self.seq = snap["seq"]
        self.seen_obs = snap["seen_obs"]
        self._reject_identity_pairs = snap["reject_identity_pairs"]
        self.cache = snap.get("cache", self.cache)

    def _commit_reported_watermark(self) -> str:
        if self.event_watermark is not None:
            if self.reported_watermark is None:
                self.reported_watermark = self.event_watermark
            else:
                self.reported_watermark = max(self.reported_watermark, self.event_watermark)
            return iso(self.reported_watermark)
        # Still only buffering: hold a floor watermark that cannot later regress
        # when the first event time (in the past relative to wall clock) commits.
        if self.reported_watermark is None:
            self.reported_watermark = datetime(1970, 1, 1, tzinfo=timezone.utc)
        return iso(self.reported_watermark)

    def process(
        self,
        batch_id: str,
        processing_time: str,
        observations: list[dict[str, Any]],
        mode: str = "realtime",
    ) -> ProcessResponse:
        with self.lock:
            return self._process_locked(batch_id, processing_time, observations, mode)

    def _empty_error(
        self,
        batch_id: str,
        processing_time: str,
        error: str,
        rejected: list[Rejected] | None = None,
    ) -> ProcessResponse:
        return ProcessResponse(
            sessionId=self.session_id,
            batchId=batch_id,
            epoch=self.epoch,
            snapshotSeq=self.seq,
            algorithmVersion=self.cfg["algorithmVersion"],
            configVersion=self.cfg["configVersion"],
            watermark=iso(self.event_watermark) if self.event_watermark else processing_time,
            tracks=self._snapshots(),
            rejected=rejected or [Rejected(reason=error)],
            events=[],
            error=error,
        )

    def _lookup_cache(self, batch_id: str, fp: str, processing_time: str) -> Optional[ProcessResponse]:
        entry = self.cache.get(batch_id)
        if entry is None:
            return None
        ttl = float(self.cfg.get("idempotency_ttl_s", 1800))
        age = (datetime.now(timezone.utc) - entry.stored_at).total_seconds()
        if age > ttl or entry.status == "expired":
            entry.status = "expired"
            entry.response = None
            return self._empty_error(batch_id, processing_time, "idempotency_expired")
        if entry.fingerprint != fp:
            return self._empty_error(
                batch_id,
                processing_time,
                "batch_id_conflict",
                [Rejected(reason="batch_id_conflict", detail="same batchId different fingerprint")],
            )
        if entry.status == "evicted" or entry.response is None:
            return self._empty_error(batch_id, processing_time, "idempotency_evicted")
        return entry.response

    def _process_locked(
        self,
        batch_id: str,
        processing_time: str,
        observations: list[dict[str, Any]],
        mode: str,
    ) -> ProcessResponse:
        self._purge_expired(datetime.now(timezone.utc))
        fp = _request_fingerprint(batch_id, processing_time, mode, observations)
        cached = self._lookup_cache(batch_id, fp, processing_time)
        if cached is not None:
            return cached

        if self.mode is None:
            self.mode = mode
        elif self.mode != mode:
            return self._empty_error(batch_id, processing_time, "session_mode_conflict")

        pt, _ = parse_dt(processing_time, allow_naive=True, assume_utc=True)
        if pt is None:
            return self._empty_error(batch_id, processing_time, "invalid_processing_time")
        if self.last_processing and pt < self.last_processing:
            return self._empty_error(batch_id, processing_time, "processing_time_not_monotonic")

        window = timedelta(seconds=float(self.cfg["reorder_window_s"]))

        # ---- atomic preflight for observation identity (no mutation) ----
        soft_rejected: list[Rejected] = []
        candidates: list[tuple[Observation, dict, str]] = []
        batch_map: dict[str, str] = {}
        for raw in observations:
            obs, rej = normalize_row(raw)
            if obs is None:
                if rej:
                    soft_rejected.append(rej)
                continue
            ch = _obs_content_hash(raw)
            if obs.observationId in batch_map:
                if batch_map[obs.observationId] != ch:
                    return self._empty_error(batch_id, processing_time, "observation_id_conflict")
                soft_rejected.append(Rejected(observationId=obs.observationId, reason="duplicate_observation"))
                continue
            batch_map[obs.observationId] = ch

            prev = self.seen_obs.get(obs.observationId)
            if prev is not None:
                if prev == ch:
                    soft_rejected.append(Rejected(observationId=obs.observationId, reason="duplicate_observation"))
                    continue
                return self._empty_error(batch_id, processing_time, "observation_id_conflict")

            buffered_hit = False
            for _mt, bobs, braw in self.buffer:
                if bobs.observationId == obs.observationId:
                    if _obs_content_hash(braw) != ch:
                        return self._empty_error(batch_id, processing_time, "observation_id_conflict")
                    soft_rejected.append(Rejected(observationId=obs.observationId, reason="duplicate_observation"))
                    buffered_hit = True
                    break
            if buffered_hit:
                continue
            candidates.append((obs, raw, ch))

        snap = self._snapshot_state()
        events: list[FusionEvent] = []
        rejected = list(soft_rejected)
        try:
            if mode == "realtime":
                cutoff = pt - window
            else:
                cutoff = pt

            def flush_ready() -> list[tuple[Observation, dict, str]]:
                ready_local: list[tuple[Observation, dict, str]] = []
                remain_local: list[tuple[datetime, Observation, dict]] = []
                for mt, obs, raw in self.buffer:
                    if mt <= cutoff:
                        ready_local.append((obs, raw, _obs_content_hash(raw)))
                    else:
                        remain_local.append((mt, obs, raw))
                self.buffer = remain_local
                return ready_local

            def commit_ready(ready_items: list[tuple[Observation, dict, str]]) -> None:
                nonlocal events
                if not ready_items:
                    return
                events.extend(self._ingest_microbatches([(o, r) for o, r, _ in ready_items]))
                max_mt = max(parse_dt(o.measurementTime)[0] or pt for o, _, _ in ready_items)
                # lifecycle only along committed event time
                events.extend(self._advance_lifecycle(max_mt, mutate_filter=True))
                self.event_watermark = max_mt if self.event_watermark is None else max(self.event_watermark, max_mt)
                for o, _r, ch in ready_items:
                    self.seen_obs[o.observationId] = ch

            # Admit against the previously committed event frontier before draining.
            # A mature item buffered earlier must not jump ahead of a legal new arrival.
            prior_watermark = self.event_watermark
            for obs, raw, ch in candidates:
                mt, _ = parse_dt(obs.measurementTime)
                assert mt is not None
                if prior_watermark is not None and mt < prior_watermark:
                    rejected.append(Rejected(observationId=obs.observationId, reason="late_beyond_reorder_window"))
                    continue
                self.buffer.append((mt, obs, raw))
            self.buffer.sort(key=lambda x: x[0])
            commit_ready(flush_ready())

            # Commit a time frontier, not merely the newest measurement timestamp.
            # In realtime cutoff=processingTime-reorder_window even when the buffer is empty.
            # In replay cutoff=processingTime (virtual clock).
            frontier = cutoff if self.event_watermark is None else max(self.event_watermark, cutoff)
            if self.tracks:
                events.extend(self._advance_lifecycle(frontier, mutate_filter=True))
            self.event_watermark = frontier

        except Exception as exc:
            self._restore_state(snap)
            return self._empty_error(
                batch_id,
                processing_time,
                "batch_rollback",
                rejected + [Rejected(reason="batch_rollback", detail=str(exc))],
            )

        self.last_processing = pt
        self.seq += 1
        resp = ProcessResponse(
            sessionId=self.session_id,
            batchId=batch_id,
            epoch=self.epoch,
            snapshotSeq=self.seq,
            algorithmVersion=self.cfg["algorithmVersion"],
            configVersion=self.cfg["configVersion"],
            watermark=self._commit_reported_watermark(),
            tracks=self._snapshots(display_time=pt),
            rejected=rejected,
            events=events,
        )
        self._store_cache(batch_id, fp, resp)
        return resp

    def _store_cache(self, batch_id: str, fp: str, resp: ProcessResponse) -> None:
        max_cache = int(self.cfg.get("max_cache", 200))
        now = datetime.now(timezone.utc)
        # mark TTL-expired completes as expired tombstones (keep fingerprint)
        ttl = float(self.cfg.get("idempotency_ttl_s", 1800))
        for k, entry in list(self.cache.items()):
            if entry.status == "complete" and (now - entry.stored_at).total_seconds() > ttl:
                entry.status = "expired"
                entry.response = None
        # capacity: evict oldest complete bodies to tombstones
        completes = [k for k, e in self.cache.items() if e.status == "complete" and e.response is not None]
        while len(completes) >= max_cache and completes:
            oldest = min(completes, key=lambda k: self.cache[k].stored_at)
            self.cache[oldest].status = "evicted"
            self.cache[oldest].response = None
            completes = [k for k, e in self.cache.items() if e.status == "complete" and e.response is not None]
        self.cache[batch_id] = CacheEntry(fingerprint=fp, stored_at=now, response=resp, status="complete")

    def _purge_expired(self, now: datetime) -> None:
        track_ttl = float(self.cfg.get("track_ttl_s", 600))
        drop = []
        for fid, tr in self.tracks.items():
            if tr.status == "terminated":
                t0 = tr.terminatedAt or tr.stateTime
                if (now - t0).total_seconds() > track_ttl:
                    drop.append(fid)
        for fid in drop:
            self.tracks.pop(fid, None)
        max_tracks = int(self.cfg.get("max_tracks", 400))
        if len(self.tracks) > max_tracks:
            ordered = sorted(self.tracks.values(), key=lambda t: t.lastObservedAt)
            for tr in ordered[: len(self.tracks) - max_tracks]:
                self.tracks.pop(tr.fusionId, None)
        # bound seen_obs
        max_seen = int(self.cfg.get("max_cache", 200)) * 50
        if len(self.seen_obs) > max_seen:
            for k in list(self.seen_obs)[: len(self.seen_obs) - max_seen]:
                self.seen_obs.pop(k, None)

    def _primary_source_rank(self) -> dict[str, int]:
        order = self.cfg.get("primary_source_order") or ["rid", "spectrum", "radar"]
        return {str(s): i for i, s in enumerate(order)}

    def _ingest_microbatches(self, ready: list[tuple[Observation, dict]]) -> list[FusionEvent]:
        """Ingest ready observations grouped by event time.

        Same-time identity-bearing observations are ordered by configured primary
        source priority (default RID > spectrum > radar) so input array order cannot
        change which observation initializes or updates the main filter.
        """
        events: list[FusionEvent] = []
        by_time: dict[datetime, list[tuple[Observation, dict]]] = {}
        for obs, raw in ready:
            mt, _ = parse_dt(obs.measurementTime)
            assert mt is not None
            by_time.setdefault(mt, []).append((obs, raw))
        rank = self._primary_source_rank()
        for mt in sorted(by_time):
            items = by_time[mt]
            by_aircraft: dict[str, list[tuple[Observation, dict]]] = {}
            others: list[tuple[Observation, dict]] = []
            for obs, raw in items:
                if obs.source in ("rid", "spectrum") and obs.aircraftId:
                    by_aircraft.setdefault(obs.aircraftId, []).append((obs, raw))
                else:
                    others.append((obs, raw))
            for acid in sorted(by_aircraft):
                group = by_aircraft[acid]
                group.sort(
                    key=lambda ir: (
                        rank.get(ir[0].source, 99),
                        ir[0].observationId or "",
                    )
                )
                for obs, raw in group:
                    events.extend(self._ingest(obs))
            events.extend(self._assign_and_ingest(others, mt))
        return events

    def _ingest(self, obs: Observation) -> list[FusionEvent]:
        return self._ingest_one(obs, {})

    def _birth(self, obs: Observation) -> list[FusionEvent]:
        """Create a new track without falling back to gated nearest-neighbour."""
        events: list[FusionEvent] = []
        t, _ = parse_dt(obs.measurementTime)
        assert t and obs.latitude is not None and obs.longitude is not None
        x, y = self.geo.to_xy(obs.latitude, obs.longitude)
        track = self._spawn(obs, t, x, y)
        events.append(self._event("track_born", t, track.fusionId, source=obs.source, sourceTrackId=obs.sourceTrackId))
        events.extend(self._apply_update(track, obs, t, primary_forced=obs.source, is_birth=True))
        return events

    def _assign_and_ingest(self, items: list[tuple[Observation, dict]], mt: datetime) -> list[FusionEvent]:
        events: list[FusionEvent] = []
        if not items:
            return events
        by_det: dict[tuple[str, str], list[tuple[Observation, dict]]] = {}
        for obs, raw in items:
            by_det.setdefault((obs.source, obs.detectorId), []).append((obs, raw))
        for (source, detector), group in by_det.items():
            if source == "radar":
                events.extend(self._global_assign_radar(group, mt, detector))
            else:
                for obs, raw in group:
                    events.extend(self._ingest(obs))
        return events

    def _predicted_xy(self, tr: Track, t: datetime) -> tuple[float, float]:
        dt = (t - tr.stateTime).total_seconds()
        x, y = tr.kf.pos
        vx, vy = tr.kf.vel
        if dt <= 0:
            return x, y
        return x + vx * dt, y + vy * dt

    def _mahalanobis(self, tr: Track, zx: float, zy: float, r: float, t: Optional[datetime] = None) -> float:
        """Innovation distance at time t using predicted position and inflated covariance."""
        t = t or tr.stateTime
        px, py = self._predicted_xy(tr, t)
        dt = max(0.0, (t - tr.stateTime).total_seconds())
        q = float(self.cfg["kalman"]["q_pos"])
        sx = float(tr.kf.P[0, 0]) + float(r) + q * dt
        sy = float(tr.kf.P[1, 1]) + float(r) + q * dt
        return math.sqrt(((zx - px) ** 2) / max(sx, 1e-6) + ((zy - py) ** 2) / max(sy, 1e-6))

    def _radar_innov_limit(self, tr: Track) -> float:
        # Identified / RID-anchored tracks allow slightly larger secondary radar innov;
        # anonymous radar-radar stays strict so LSA unmatch at ~86m cannot fall back loosely.
        if tr.aircraftId or any(b.source == "rid" for b in tr.bindings.values()):
            return 11.0
        return 6.0

    def _global_assign_radar(self, group: list[tuple[Observation, dict]], mt: datetime, detector: str) -> list[FusionEvent]:
        events: list[FusionEvent] = []
        gates = self.cfg["gates"]
        r_meas = float(self.cfg["kalman"]["r_radar"])
        tracks = [tr for tr in self.tracks.values() if tr.status != "terminated"]
        remaining: list[tuple[Observation, dict]] = []
        for obs, raw in group:
            key = f"radar|{obs.detectorId}|{obs.sourceTrackId}"
            bound = None
            for tr in tracks:
                if key in tr.bindings:
                    x, y = self.geo.to_xy(obs.latitude, obs.longitude)  # type: ignore[arg-type]
                    px, py = self._predicted_xy(tr, mt)
                    dist = math.hypot(px - x, py - y)
                    dt = abs((mt - tr.stateTime).total_seconds())
                    innov = self._mahalanobis(tr, x, y, r_meas, t=mt)
                    innov_limit = self._radar_innov_limit(tr)
                    if dist <= float(gates["radar_dist_m"]) + dt * 35 and innov <= innov_limit:
                        bound = tr
                    else:
                        events.append(self._event("bind_regate_fail", mt, tr.fusionId, key=key, dist=dist))
                        del tr.bindings[key]
                    break
            if bound is not None:
                events.extend(self._apply_update(bound, obs, mt, primary_forced=None))
            else:
                remaining.append((obs, raw))

        if not remaining:
            return events

        batch_ids = {o.sourceTrackId for o, _ in remaining}
        cand_tracks = []
        for tr in tracks:
            same_det = [b for b in tr.bindings.values() if b.source == "radar" and b.detectorId == detector]
            if any(b.sourceTrackId in batch_ids for b in same_det):
                continue
            parallel = [
                b for b in same_det
                if b.sourceTrackId not in batch_ids and b.lastSeen >= mt - timedelta(milliseconds=1)
            ]
            if parallel:
                continue
            cand_tracks.append(tr)

        n_obs = len(remaining)
        n_tr = len(cand_tracks)
        unmatch_cost = float(gates["radar_dist_m"]) * 1.5
        cost = np.full((n_obs, n_tr + n_obs), unmatch_cost, dtype=float)
        for i, (obs, _) in enumerate(remaining):
            x, y = self.geo.to_xy(obs.latitude, obs.longitude)  # type: ignore[arg-type]
            for j, tr in enumerate(cand_tracks):
                px, py = self._predicted_xy(tr, mt)
                dist = math.hypot(px - x, py - y)
                dt = abs((mt - tr.stateTime).total_seconds())
                limit = float(gates["radar_dist_m"]) + dt * 35
                innov = self._mahalanobis(tr, x, y, r_meas, t=mt)
                innov_limit = self._radar_innov_limit(tr)
                if dist > limit or innov > innov_limit:
                    cost[i, j] = 1e6
                else:
                    cost[i, j] = dist + innov * 10.0
            for k in range(n_obs):
                cost[i, n_tr + k] = unmatch_cost

        assigned_tracks: set[int] = set()
        if n_tr + n_obs > 0:
            rows, cols = linear_sum_assignment(cost)
            for i, j in zip(rows, cols):
                obs, raw = remaining[i]
                if j >= n_tr or cost[i, j] >= 1e5:
                    # LSA explicit unmatch → independent birth (no looser gated_pick fallback)
                    events.extend(self._birth(obs))
                    continue
                if j in assigned_tracks:
                    events.append(self._event("association_ambiguous", mt, None))
                    events.extend(self._birth(obs))
                    continue
                row_costs = [(cost[i, jj], jj) for jj in range(n_tr) if cost[i, jj] < 1e5]
                row_costs.sort()
                if len(row_costs) >= 2:
                    best, second = row_costs[0][0], row_costs[1][0]
                    if second <= best * float(gates["ambiguity_ratio"]) and (second - best) < 15:
                        events.append(self._event("association_ambiguous", mt, None, best=best, second=second))
                        events.extend(self._birth(obs))
                        continue
                assigned_tracks.add(j)
                events.extend(self._apply_update(cand_tracks[j], obs, mt, primary_forced=None))
        return events

    def _ingest_one(self, obs: Observation, raw: dict) -> list[FusionEvent]:
        events: list[FusionEvent] = []
        t, _ = parse_dt(obs.measurementTime)
        assert t and obs.latitude is not None and obs.longitude is not None
        x, y = self.geo.to_xy(obs.latitude, obs.longitude)
        # Radar must only enter via global assign / birth; keep gated_pick for non-radar leftovers.
        if obs.source == "radar":
            return self._birth(obs)
        track = self._associate(obs, t, x, y, events)
        if track is None:
            return self._birth(obs)
        events.extend(self._apply_update(track, obs, t, primary_forced=None))
        return events

    def _spawn(self, obs: Observation, t: datetime, x: float, y: float) -> Track:
        if len(self.tracks) >= int(self.cfg.get("max_tracks", 400)):
            raise RuntimeError("max_tracks_exceeded")
        kcfg = self.cfg["kalman"]
        r = {"rid": kcfg["r_rid"], "spectrum": kcfg["r_spectrum"], "radar": kcfg["r_radar"]}[obs.source]
        tr = Track(
            fusionId=self._fid(),
            segmentId="S1",
            kf=ConstantVelocityKF(x, y, kcfg["q_pos"], kcfg["q_vel"], r),
            aircraftId=obs.aircraftId,
            createdAt=t,
            lastObservedAt=t,
            stateTime=t,
            positionSource=obs.source,
            altitudeDatum=obs.altitudeDatum or "unknown",
        )
        self.tracks[tr.fusionId] = tr
        return tr

    def _associate(self, obs: Observation, t: datetime, x: float, y: float, events: list[FusionEvent]) -> Optional[Track]:
        key = f"{obs.source}|{obs.detectorId}|{obs.sourceTrackId}"
        for tr in self.tracks.values():
            if tr.status == "terminated":
                continue
            if key in tr.bindings and obs.aircraftId and tr.aircraftId and obs.aircraftId != tr.aircraftId:
                events.append(self._event("identity_hard_conflict", t, tr.fusionId, have=tr.aircraftId, got=obs.aircraftId))
                del tr.bindings[key]
                return None

        if obs.aircraftId:
            same = [tr for tr in self.tracks.values() if tr.status != "terminated" and tr.aircraftId == obs.aircraftId]
            if len(same) == 1:
                tr = same[0]
                if self._physically_ok(tr, t, x, y):
                    return tr
                events.append(self._event("identity_physics_reject", t, tr.fusionId, aircraftId=obs.aircraftId))
                self._reject_identity_pairs.add((obs.aircraftId, tr.fusionId))
            elif len(same) > 1:
                events.append(self._event("identity_ambiguous", t, None, aircraftId=obs.aircraftId))

            anonymous = [tr for tr in self.tracks.values() if tr.status != "terminated" and tr.aircraftId is None]
            cands = []
            for tr in anonymous:
                if self._physically_ok(tr, t, x, y):
                    cands.append((self._dist_xy(tr, t, x, y), tr))
            cands.sort(key=lambda z: z[0])
            if len(cands) == 1:
                return cands[0][1]
            if len(cands) > 1 and cands[1][0] > cands[0][0] * float(self.cfg["gates"]["ambiguity_ratio"]):
                return cands[0][1]
            if len(cands) > 1:
                events.append(self._event("identity_fill_ambiguous", t, None, aircraftId=obs.aircraftId))
                return None
            if same and (obs.aircraftId, same[0].fusionId) in self._reject_identity_pairs:
                return None
            if obs.source in ("rid", "spectrum"):
                return None

        for tr in self.tracks.values():
            if tr.status == "terminated":
                continue
            if key in tr.bindings:
                if self._physically_ok(tr, t, x, y):
                    return tr
                events.append(self._event("bind_regate_fail", t, tr.fusionId, key=key))
                del tr.bindings[key]
                return None

        if obs.source in ("rid", "spectrum") and obs.aircraftId:
            return None
        return self._gated_pick(obs, t, x, y, events)

    def _physically_ok(self, tr: Track, t: datetime, x: float, y: float) -> bool:
        dt = abs((t - tr.stateTime).total_seconds())
        dist = self._dist_xy(tr, t, x, y)
        if dist > float(self.cfg["gates"]["identity_dist_m"]) + max(0.0, dt) * 40:
            return False
        return True

    def _dist_xy(self, tr: Track, t: datetime, x: float, y: float) -> float:
        px, py = self._predicted_xy(tr, t)
        return math.hypot(px - x, py - y)

    def _gated_pick(self, obs: Observation, t: datetime, x: float, y: float, events: list[FusionEvent]) -> Optional[Track]:
        """Non-radar fallback only. Radar must not use this path after LSA."""
        if obs.source == "radar":
            return None
        gates = self.cfg["gates"]
        cands: list[tuple[float, Track]] = []
        for tr in self.tracks.values():
            if tr.status == "terminated":
                continue
            if obs.aircraftId and tr.aircraftId and obs.aircraftId != tr.aircraftId:
                continue
            if obs.aircraftId and (obs.aircraftId, tr.fusionId) in self._reject_identity_pairs:
                continue
            dt = abs((t - tr.stateTime).total_seconds())
            dist = self._dist_xy(tr, t, x, y)
            limit = float(gates["radar_dist_m"]) + dt * 35
            if dist > limit:
                continue
            cands.append((dist, tr))
        if not cands:
            return None
        cands.sort(key=lambda z: z[0])
        best, tr = cands[0]
        if len(cands) > 1:
            second = cands[1][0]
            if second <= best * float(gates["ambiguity_ratio"]) and (second - best) < 15:
                events.append(self._event("association_ambiguous", t, None, best=best, second=second))
                return None
        return tr

    def _choose_primary(self, tr: Track, obs: Observation, t: datetime) -> SourceKind:
        rid_fresh = float(self.cfg["rid_fresh_s"])
        if obs.source == "rid":
            return "rid"
        for b in tr.bindings.values():
            if b.source == "rid" and (t - b.lastSeen).total_seconds() <= rid_fresh:
                return "rid"
        if tr.positionSource == "rid" and (t - tr.lastObservedAt).total_seconds() <= rid_fresh:
            return "rid"
        return obs.source

    def _apply_update(
        self,
        tr: Track,
        obs: Observation,
        t: datetime,
        primary_forced: Optional[SourceKind],
        is_birth: bool = False,
    ) -> list[FusionEvent]:
        events: list[FusionEvent] = []
        if t < tr.stateTime - timedelta(milliseconds=1):
            events.append(self._event("stale_obs_ignored", t, tr.fusionId))
            return events

        if obs.aircraftId and tr.aircraftId and obs.aircraftId != tr.aircraftId:
            events.append(self._event("identity_hard_conflict", t, tr.fusionId, have=tr.aircraftId, got=obs.aircraftId))
            key = tr.bind_key(obs.source, obs.detectorId, obs.sourceTrackId)
            tr.bindings.pop(key, None)
            return events

        x, y = self.geo.to_xy(obs.latitude, obs.longitude)  # type: ignore[arg-type]
        dt = (t - tr.stateTime).total_seconds()

        # bind metadata first (does not move KF)
        key = tr.bind_key(obs.source, obs.detectorId, obs.sourceTrackId)
        if key in tr.bindings:
            tr.bindings[key].lastSeen = t
            tr.bindings[key].hits += 1
            if tr.bindings[key].hits >= int(self.cfg["gates"]["confirm_hits"]):
                tr.bindings[key].confirmed = True
        else:
            confirm_need = int(self.cfg["gates"]["confirm_hits"])
            tr.bindings[key] = BoundSource(
                obs.source, obs.detectorId, obs.sourceTrackId, obs.aircraftId, t,
                hits=1, confirmed=(confirm_need <= 1),
            )
            events.append(self._event("source_bound", t, tr.fusionId, key=key))

        if obs.aircraftId and tr.aircraftId is None:
            tr.aircraftId = obs.aircraftId
            events.append(self._event("identity_filled", t, tr.fusionId, aircraftId=obs.aircraftId))

        primary = primary_forced or self._choose_primary(tr, obs, t)

        # innov on predicted copy — do not mutate KF yet
        px, py = self._predicted_xy(tr, t)
        innov = math.hypot(px - x, py - y)
        jump = float(self.cfg["gates"]["radar_innov_m"]) * (2.0 if obs.source != "radar" else 1.0)
        if not is_birth and innov > jump + 80 and obs.source == primary:
            events.append(self._event("jump_reject", t, tr.fusionId, innov=innov, source=obs.source))
            tr.bindings.pop(key, None)
            events.append(self._event("unbind", t, tr.fusionId, key=key))
            return events

        kcfg = self.cfg["kalman"]
        r = {"rid": kcfg["r_rid"], "spectrum": kcfg["r_spectrum"], "radar": kcfg["r_radar"]}[obs.source]

        if obs.source == primary:
            if dt > 0 and not is_birth:
                tr.kf.predict(dt)
            if not is_birth:
                tr.kf.update(x, y, r)
            tr.positionSource = primary
            tr.positionMode = "measured_assisted"
            tr.stateTime = t
            tr.lastObservedAt = t
            tr.hits += 1
            tr.qualityFlags = [f for f in tr.qualityFlags if f != "predicted"]
        else:
            # secondary: binding only — never predict/update main KF here
            events.append(self._event("secondary_bind_only", t, tr.fusionId, source=obs.source, primary=primary))

        if tr.hits >= int(self.cfg["lifecycle"]["tentative_to_tracked"]):
            if tr.status == "tentative":
                events.append(self._event("promoted", t, tr.fusionId))
            tr.status = "tracked"
        if tr.status in ("coasting", "lost") and obs.source == primary:
            tr.status = "tracked"
            events.append(self._event("reacquired", t, tr.fusionId, source=obs.source))

        if obs.heading is not None and obs.source == primary:
            tr.lastHeading = obs.heading
        if obs.speed is not None and obs.source == primary:
            tr.lastSpeed = obs.speed
        if obs.altitude is not None:
            tr.lastAlt = obs.altitude
        tr.altitudeDatum = obs.altitudeDatum or tr.altitudeDatum
        for f in obs.qualityFlags:
            if f not in tr.qualityFlags:
                tr.qualityFlags.append(f)

        events.extend(self._maybe_merge(tr, t))
        return events

    def _maybe_merge(self, tr: Track, t: datetime) -> list[FusionEvent]:
        events: list[FusionEvent] = []
        if not tr.aircraftId:
            return events
        for other in list(self.tracks.values()):
            if other.fusionId == tr.fusionId or other.status == "terminated":
                continue
            if other.aircraftId != tr.aircraftId:
                continue
            if (tr.aircraftId, other.fusionId) in self._reject_identity_pairs or (
                other.aircraftId, tr.fusionId
            ) in self._reject_identity_pairs:
                continue
            ox, oy = other.kf.pos
            if not self._physically_ok(tr, t, ox, oy):
                continue
            keep, drop = (tr, other) if tr.createdAt <= other.createdAt else (other, tr)
            drop.status = "terminated"
            drop.terminatedAt = t
            keep.aliases.append(drop.fusionId)
            for k, b in drop.bindings.items():
                keep.bindings.setdefault(k, b)
            if keep.aircraftId is None:
                keep.aircraftId = drop.aircraftId
            events.append(self._event("alias_merge", t, keep.fusionId, dropped=drop.fusionId, rule="oldest_kept"))
        return events

    def _advance_lifecycle(self, now: datetime, mutate_filter: bool = True) -> list[FusionEvent]:
        """Advance statuses on the event / processing clock.

        When mutate_filter is False (realtime empty-buffer path), only status /
        lost / terminate flags move — main KF and stateTime stay on last commit so
        in-window delayed observations remain applicable.
        """
        events: list[FusionEvent] = []
        life = self.cfg["lifecycle"]
        for tr in self.tracks.values():
            if tr.status == "terminated":
                continue
            gap = (now - tr.lastObservedAt).total_seconds()
            if gap <= 1e-6:
                continue
            horizon = float(life["predict_horizon_s"])
            if gap <= horizon:
                if mutate_filter:
                    dt = (now - tr.stateTime).total_seconds()
                    if dt > 0:
                        tr.kf.predict(dt)
                        tr.stateTime = now
                    tr.positionMode = "predicted"
                    tr.status = "coasting"
                    if "predicted" not in tr.qualityFlags:
                        tr.qualityFlags.append("predicted")
                    events.append(self._event("predicted", now, tr.fusionId, gap=gap))
                # else: leave KF/stateTime; display copy coasts in _snapshots
            elif gap <= float(life["lost_s"]):
                tr.positionMode = "stale"
                tr.status = "coasting"
                tr.qualityFlags = [f for f in tr.qualityFlags if f != "predicted"]
            elif gap <= float(life["terminate_s"]):
                if tr.status != "lost":
                    events.append(self._event("lost", now, tr.fusionId))
                tr.status = "lost"
                tr.positionMode = "stale"
                tr.qualityFlags = [f for f in tr.qualityFlags if f != "predicted"]
            else:
                tr.status = "terminated"
                tr.terminatedAt = now
                tr.positionMode = "stale"
                events.append(self._event("terminated", now, tr.fusionId))
        return events

    def _active_sources(self, tr: Track, now: datetime) -> list[SourceKind]:
        rid_fresh = float(self.cfg["rid_fresh_s"])
        coast = float(self.cfg["lifecycle"]["coast_s"])
        out: list[SourceKind] = []
        for b in tr.bindings.values():
            age = (now - b.lastSeen).total_seconds()
            limit = rid_fresh if b.source == "rid" else coast
            if age <= limit and b.confirmed:
                if b.source not in out:
                    out.append(b.source)
        return out

    def _snapshots(self, display_time: Optional[datetime] = None) -> list[TargetSnapshot]:
        out: list[TargetSnapshot] = []
        now = self.event_watermark or display_time or datetime.now(timezone.utc)
        horizon = float(self.cfg["lifecycle"]["predict_horizon_s"])
        for tr in self.tracks.values():
            if tr.status == "terminated":
                continue
            kf = copy.deepcopy(tr.kf)
            disp_t = tr.stateTime
            mode = tr.positionMode
            gap_obs = 0.0
            if display_time is not None:
                gap_obs = (display_time - tr.lastObservedAt).total_seconds()
                if display_time > tr.stateTime and gap_obs <= horizon and mode in ("predicted", "measured_assisted", "stale"):
                    # display-only coast copy; stop moving after predict horizon
                    if tr.positionMode == "predicted" or gap_obs > 1e-6:
                        dt = (display_time - tr.stateTime).total_seconds()
                        if 0 < dt and gap_obs <= horizon:
                            kf.predict(dt)
                            disp_t = display_time
                            mode = "predicted"
                        elif gap_obs > horizon:
                            mode = "stale"
                            disp_t = tr.stateTime
            if display_time is not None and gap_obs > horizon:
                mode = "stale"
                disp_t = tr.stateTime
            x, y = kf.pos
            lat, lon = self.geo.to_ll(x, y)
            vx, vy = kf.vel
            spd = math.hypot(vx, vy)
            hdg = (math.degrees(math.atan2(vx, vy)) + 360) % 360 if spd > 0.3 else tr.lastHeading
            srcs = self._active_sources(tr, now)
            out.append(
                TargetSnapshot(
                    fusionId=tr.fusionId,
                    trackSegmentId=tr.segmentId,
                    aircraftId=tr.aircraftId,
                    longitude=lon,
                    latitude=lat,
                    altitude=tr.lastAlt,
                    altitudeDatum=tr.altitudeDatum,
                    speed=spd if spd > 0.05 else tr.lastSpeed,
                    heading=hdg,
                    stateTime=iso(tr.stateTime),
                    lastObservedAt=iso(tr.lastObservedAt),
                    displayStateTime=iso(disp_t),
                    trackStatus=tr.status,  # type: ignore[arg-type]
                    positionMode=mode,  # type: ignore[arg-type]
                    positionSource=tr.positionSource,
                    sources=srcs,  # type: ignore[arg-type]
                    sourceTracks=[
                        SourceTrackRef(
                            source=b.source, detectorId=b.detectorId, sourceTrackId=b.sourceTrackId,
                            aircraftId=b.aircraftId, lastSeen=iso(b.lastSeen),
                        )
                        for b in tr.bindings.values()
                    ],
                    qualityFlags=list(tr.qualityFlags),
                    aliases=list(tr.aliases),
                )
            )
        return out


class SessionStore:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.sessions: dict[str, FusionSession] = {}
        self.session_created: dict[str, datetime] = {}
        self.lock = threading.RLock()

    def get(self, session_id: str) -> FusionSession:
        with self.lock:
            self._evict_sessions()
            s = self.sessions.get(session_id)
            if s is None:
                s = FusionSession(session_id, self.cfg)
                self.sessions[session_id] = s
                self.session_created[session_id] = datetime.now(timezone.utc)
            return s

    def drop(self, session_id: str) -> None:
        with self.lock:
            self.sessions.pop(session_id, None)
            self.session_created.pop(session_id, None)

    def _evict_sessions(self) -> None:
        ttl = float(self.cfg.get("session_ttl_s", 3600))
        now = datetime.now(timezone.utc)
        dead = [sid for sid, t0 in self.session_created.items() if (now - t0).total_seconds() > ttl]
        for sid in dead:
            self.sessions.pop(sid, None)
            self.session_created.pop(sid, None)
