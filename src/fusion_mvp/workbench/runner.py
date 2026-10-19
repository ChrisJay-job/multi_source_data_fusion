"""Run observations through the real FusionSession (same core as HTTP /process)."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

from fusion_mvp.engine import FusionSession, load_config
from fusion_mvp.workbench.evaluator import evaluate_run


def _assert_no_truth_leak(observations: list[dict]) -> bool:
    for o in observations:
        blob = json.dumps(o, ensure_ascii=False)
        if "TRUTH-" in blob or any(k in o for k in ("truth_id", "truthId", "expectedFusionId")):
            return False
    return True


class _CountCollector:
    """Unified collector for non-empty / empty-tick / flush process responses."""

    def __init__(self) -> None:
        self.counts = {
            "delivered": 0,
            "unique_received": 0,
            "pending_buffer": 0,
            "processed_updates": 0,  # cumulative primary position updates (never decreases)
            "source_binds": 0,
            "bind_only": 0,
            "rejected": 0,
            "duplicate_received": 0,
            "processed_hits": 0,  # alias of processed_updates
            "empty_ticks": 0,
            "flush_batches": 0,
        }
        self._seen_oids: set[str] = set()
        self._lifetime_hits = 0  # monotonic applied-update proxy

    def note_delivered(self, chunk: list[dict]) -> None:
        self.counts["delivered"] += len(chunk)
        for o in chunk:
            oid = o.get("observationId")
            if not oid:
                continue
            if oid in self._seen_oids:
                self.counts["duplicate_received"] += 1
            else:
                self._seen_oids.add(oid)
                self.counts["unique_received"] += 1

    def collect(self, sess: FusionSession, resp: Any, *, kind: str = "batch") -> None:
        before = self._lifetime_hits
        # Prefer engine track hits growth; also count bind-only / rejects from response
        live_hits = sum(tr.hits for tr in sess.tracks.values())
        # If purge reduced live hits, keep lifetime as max(live, previous) + positive delta from events
        delta_hits = 0
        if live_hits >= before:
            delta_hits = live_hits - before
            self._lifetime_hits = live_hits
        else:
            # tracks terminated — estimate from events in this response
            for e in resp.events:
                typ = e.type if hasattr(e, "type") else e.get("type")
                if typ in {"source_bound", "reacquired", "promoted", "identity_filled"}:
                    # weak signal; primary updates often come without new bind
                    pass
            # still try response tracks hits sum vs previous live — use resp.tracks
            resp_hits = sum(getattr(t, "hits", 0) for t in (resp.tracks or []))
            if resp_hits > before:
                delta_hits = resp_hits - before
                self._lifetime_hits = resp_hits
            else:
                self._lifetime_hits = before  # unchanged

        # Stronger signal: count primary-like events + hits delta
        for e in resp.events:
            ed = e.model_dump() if hasattr(e, "model_dump") else dict(e)
            typ = ed.get("type")
            if typ == "source_bound":
                self.counts["source_binds"] += 1
            elif typ == "secondary_bind_only":
                self.counts["bind_only"] += 1

        for r in resp.rejected or []:
            self.counts["rejected"] += 1

        if delta_hits > 0:
            self.counts["processed_updates"] += delta_hits
        elif kind == "tick":
            # empty tick may mature buffered obs: detect via events that imply update
            matured = sum(
                1
                for e in resp.events
                if (e.type if hasattr(e, "type") else e.get("type"))
                in {"source_bound", "reacquired", "promoted", "identity_filled", "track_born"}
            )
            # Also compare snapshot track hit totals encoded on tracks
            tick_hits = sum(getattr(t, "hits", 0) for t in (resp.tracks or []))
            if tick_hits > before:
                self.counts["processed_updates"] += tick_hits - before
                self._lifetime_hits = tick_hits
            elif matured and live_hits > before:
                self.counts["processed_updates"] += live_hits - before
                self._lifetime_hits = live_hits

        self.counts["processed_hits"] = self.counts["processed_updates"]
        self.counts["pending_buffer"] = len(sess.buffer)
        if kind == "tick":
            self.counts["empty_ticks"] += 1
        elif kind == "flush":
            self.counts["flush_batches"] += 1


class WorkbenchRunner:
    def __init__(self, cfg: Optional[dict] = None):
        self.cfg = cfg or load_config()

    def run_batch_replay(
        self,
        observations: list[dict],
        *,
        session_id: Optional[str] = None,
        batch_size: int = 20,
        mode: str = "replay",
        obs_truth_map: Optional[dict[str, str]] = None,
        expected_stable_entities: Optional[dict[str, set[str]]] = None,
        stable_window: Optional[tuple[str, str]] = None,
        eval_phases: Optional[list[dict[str, Any]]] = None,
        scenario: Optional[dict[str, Any]] = None,
        scenario_t0: Optional[str] = None,
        time_step_s: Optional[float] = None,
    ) -> dict[str, Any]:
        sid = session_id or f"wb-{uuid4().hex[:10]}"
        sess = FusionSession(sid, deepcopy(self.cfg))
        delivered: list[dict] = []
        rejected: list[dict] = []
        events: list[dict] = []
        snapshots: list[dict] = []
        coll = _CountCollector()
        leak_ok = _assert_no_truth_leak(observations)

        key = "receivedAt" if mode == "realtime" else "measurementTime"
        rows = sorted(observations, key=lambda o: (o.get(key) or o["measurementTime"], o["observationId"]))

        groups: list[list[dict]] = []
        for o in rows:
            t = o.get(key) or o["measurementTime"]
            if not groups or (groups[-1][-1].get(key) or groups[-1][-1]["measurementTime"]) != t:
                groups.append([o])
            else:
                groups[-1].append(o)

        batch_i = 0
        last_pt: Optional[datetime] = None

        def _snap(resp: Any, pt: str) -> dict:
            return {
                "batchId": resp.batchId,
                "processingTime": pt,
                "watermark": resp.watermark,
                "tracks": [t.model_dump() for t in resp.tracks],
                "error": resp.error,
                # Cumulative known at this snapshot — page must not invent future rejects
                "counts_at": {
                    "delivered": int(coll.counts.get("delivered", 0)),
                    "rejected": int(coll.counts.get("rejected", 0)),
                    "source_binds": int(coll.counts.get("source_binds", 0)),
                    "processed_updates": int(coll.counts.get("processed_updates", 0)),
                    "pending_buffer": int(coll.counts.get("pending_buffer", 0)),
                },
            }

        def _run_process(batch_id: str, pt: str, chunk: list[dict], kind: str) -> Any:
            nonlocal leak_ok
            before_hits = sum(tr.hits for tr in sess.tracks.values())
            # stash for collector lifetime baseline
            if coll._lifetime_hits < before_hits:
                coll._lifetime_hits = before_hits
            resp = sess.process(batch_id, pt, chunk, mode)
            if chunk and not _assert_no_truth_leak(chunk):
                leak_ok = False
            after_hits = sum(tr.hits for tr in sess.tracks.values())
            # Direct hits-delta path (authoritative when tracks retained)
            delta = max(0, after_hits - before_hits)
            if delta > 0:
                coll.counts["processed_updates"] += delta
                coll._lifetime_hits = max(coll._lifetime_hits, after_hits)
                coll.counts["processed_hits"] = coll.counts["processed_updates"]
            for r in resp.rejected:
                rejected.append(r.model_dump())
                coll.counts["rejected"] += 1
            for e in resp.events:
                ed = e.model_dump()
                events.append(ed)
                if ed.get("type") == "source_bound":
                    coll.counts["source_binds"] += 1
                elif ed.get("type") == "secondary_bind_only":
                    coll.counts["bind_only"] += 1
            coll.counts["pending_buffer"] = len(sess.buffer)
            if kind == "tick":
                coll.counts["empty_ticks"] += 1
            elif kind == "flush":
                coll.counts["flush_batches"] += 1
            snapshots.append(_snap(resp, pt))
            return resp

        for group in groups:
            for j in range(0, len(group), max(1, batch_size)):
                chunk = group[j : j + batch_size]
                batch_i += 1
                pt = chunk[-1].get(key) or chunk[-1]["measurementTime"]
                pt_dt = datetime.fromisoformat(pt.replace("Z", "+00:00"))
                if mode == "realtime" and last_pt is not None and time_step_s:
                    cursor = last_pt + timedelta(seconds=time_step_s)
                    while cursor < pt_dt - timedelta(milliseconds=1):
                        batch_i += 1
                        _run_process(f"tick{batch_i}", cursor.isoformat(), [], "tick")
                        cursor += timedelta(seconds=time_step_s)
                coll.note_delivered(chunk)
                delivered.extend(chunk)
                _run_process(f"b{batch_i}", pt, chunk, "batch")
                last_pt = pt_dt

        if rows:
            last_pt = datetime.fromisoformat((rows[-1].get(key) or rows[-1]["measurementTime"]).replace("Z", "+00:00"))
            flush_pt = (last_pt + timedelta(seconds=float(self.cfg.get("reorder_window_s", 2)) + 1)).isoformat()
            _run_process("flush", flush_pt, [], "flush")

        eval_out = None
        if obs_truth_map is not None:
            life = (self.cfg or {}).get("lifecycle") or {}
            eval_out = evaluate_run(
                snapshots_by_time=snapshots,
                obs_truth_map=obs_truth_map,
                delivered_obs=delivered,
                rejected=rejected,
                events=events,
                expected_stable_entities=expected_stable_entities,
                stable_window=stable_window,
                eval_phases=eval_phases,
                scenario=scenario,
                lifecycle_cfg=life,
                rid_fresh_s=float((self.cfg or {}).get("rid_fresh_s") or 2.5),
                scenario_t0=scenario_t0,
            )

        return {
            "sessionId": sid,
            "epoch": sess.epoch,
            "mode": mode,
            "counts": coll.counts,
            "snapshots": snapshots,
            "rejected": rejected,
            "events": events,
            "final_tracks": snapshots[-1]["tracks"] if snapshots else [],
            "evaluation": eval_out,
            "stable_window": list(stable_window) if stable_window else None,
            "eval_phases": eval_phases,
            "truth_leaked_to_algorithm": not leak_ok,
            "truth_leak_check": "scanned_process_inputs_for_truth_keys",
        }

    def run_scenario_bundle(self, bundle: dict[str, Any], *, mode: str = "realtime") -> dict[str, Any]:
        from .scenario import (
            evaluation_phases_from_bundle,
            expected_sources_from_scenario,
            stable_window_from_bundle,
        )

        sc = bundle.get("scenario") or {}
        expected = expected_sources_from_scenario(sc) or None
        clean = []
        for o in bundle["observations"]:
            row = {k: v for k, v in o.items() if k not in {"truth_id", "truthId", "expectedFusionId"}}
            clean.append(row)
        phases = evaluation_phases_from_bundle(bundle) if expected else []
        stable_window = stable_window_from_bundle(bundle) if expected else None
        # No meaningful evaluable phase → do not claim entity completeness PASS
        if expected and not any(p.get("available") and p.get("window") for p in phases):
            expected = None
            phases = []
            stable_window = None
        return self.run_batch_replay(
            clean,
            mode=mode,
            obs_truth_map=bundle.get("obs_truth_map"),
            expected_stable_entities=expected,
            stable_window=stable_window,
            eval_phases=phases or None,
            scenario=sc,
            scenario_t0=bundle.get("t0"),
            batch_size=40,
            time_step_s=1.0 if mode == "realtime" else None,
        )
