"""TASK-008 R1 MQTT adapter regressions (R1-04 .. R1-07)."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import yaml

from fusion_mvp.integration.mqtt_bridge import BridgeConfig, MqttBridge, PublishNotAcked
from fusion_mvp.integration.schemas import (
    content_fingerprint,
    map_http_error_to_ack_status,
    utc_now_iso,
)
from fusion_mvp.integration.store_sqlite import IntegrationStore
from fusion_mvp.multisensor import PROFILE_3D


T0 = datetime(2026, 10, 24, 1, 0, tzinfo=timezone.utc)


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="microseconds")


def _obs(oid: str, t: float = 0.0, alt: float = 100.0) -> dict:
    return {
        "observationId": oid,
        "source": "rid",
        "detectorId": "D-rid",
        "sourceTrackId": "L1",
        "aircraftId": "SN-A",
        "measurementTime": _iso(T0 + timedelta(seconds=t)),
        "receivedAt": _iso(T0 + timedelta(seconds=t)),
        "longitude": 118.7,
        "latitude": 37.45,
        "altitude": alt,
        "altitudeDatum": "MSL",
        "speed": 0,
        "heading": None,
    }


def _envelope(mid: str, sid: str = "session-A", oid: str = "o0", alt: float = 100.0) -> dict:
    return {
        "schemaVersion": "fusion-mqtt.v1",
        "messageType": "observations",
        "messageId": mid,
        "tenantId": "tenant-demo",
        "siteId": "site-demo",
        "sessionId": sid,
        "sentAt": utc_now_iso(),
        "payload": {
            "batchId": mid,
            "fusionProfile": PROFILE_3D,
            "mode": "realtime",
            "observations": [_obs(oid, 0, alt)],
        },
    }


@pytest.fixture()
def bridge(tmp_path: Path):
    b = MqttBridge(
        BridgeConfig(
            sqlite_path=str(tmp_path / "adapter.sqlite3"),
            max_session_workers=2,
            http_base_url="http://127.0.0.1:18099",
            idle_tick_s=3600,
        )
    )
    # Avoid starting real workers / MQTT in unit tests unless a test opts in.
    b._ensure_session_worker = lambda sid: "queued"  # type: ignore[method-assign]
    b._publish_status = lambda *a, **k: None  # type: ignore[method-assign]
    yield b
    close = getattr(b._http, "close", None)
    if callable(close):
        close()
    b.store.close()


def test_r1_04_control_tick_flush_run_end_ordering(bridge: MqttBridge):
    statuses: list[dict] = []

    def capture_status(state, detail=None, session_id="", **kw):
        statuses.append({"state": state, "detail": detail or {}, "session_id": session_id})

    bridge._enqueue_status = (  # type: ignore[method-assign]
        lambda state, detail=None, session_id="", **kw: capture_status(state, detail, session_id)
    )

    bridge._handle_input(_envelope("m-obs"))
    before = bridge.store.inbox_count()
    assert before >= 1
    assert bridge.store.get_inbox("m-obs")["status"] == "pending"

    for action in ("tick", "flush", "run.end"):
        ctrl = _envelope(f"control-{action}")
        ctrl["messageType"] = "control"
        ctrl["payload"] = {"action": action}
        bridge._handle_control(ctrl)

    after = bridge.store.inbox_count()
    assert after > before, "tick/flush/run.end must enqueue durable work items"
    for action in ("tick", "flush", "run.end"):
        row = bridge.store.get_inbox(f"control-{action}")
        assert row is not None
        wi = json.loads(row["work_item_json"])
        assert wi["kind"] == "control"
        assert wi["action"] == action

    # Must not publish drained/processed run_end while prior inbox still pending.
    assert not any(
        s["state"] == "run_end" and s["detail"].get("inboxStats", {}).get("pending")
        for s in statuses
    )

    outbox = bridge.store.claim_pending_outbox(50)
    ack_statuses = [
        json.loads(r["payload_json"])["payload"]["status"]
        for r in outbox
        if r["kind"] == "ack"
    ]
    assert "stored" in ack_statuses or "draining" in ack_statuses
    assert "drained" not in ack_statuses


def test_r1_04_run_end_waits_then_drained(tmp_path: Path):
    b = MqttBridge(
        BridgeConfig(sqlite_path=str(tmp_path / "drain.sqlite3"), idle_tick_s=3600)
    )
    b._ensure_session_worker = lambda sid: "queued"  # type: ignore[method-assign]
    published_status: list[str] = []
    b._enqueue_status = (  # type: ignore[method-assign]
        lambda state, detail=None, session_id="", **kw: published_status.append(state)
    )

    class HTTP:
        def post(self, url, json):  # noqa: A002
            return httpx.Response(
                200,
                json={
                    "sessionId": json.get("sessionId"),
                    "batchId": json["batchId"],
                    "epoch": "epoch-1",
                    "fusionProfile": json.get("fusionProfile"),
                    "snapshotSeq": 1,
                    "watermark": json.get("processingTime") or utc_now_iso(),
                    "algorithmVersion": "test-algo",
                    "configVersion": "test-config",
                    "tracks": [],
                    "trajectoryUpdates": [],
                    "altitudeUpdates": [],
                    "events": [],
                    "rejected": [],
                },
            )

        def close(self):
            return None

    b._http = HTTP()  # type: ignore[assignment]
    b._connected.set()
    b._handle_input(_envelope("m1", oid="o1"))
    row_obs = b.store.claim_next_for_session("session-A", utc_now_iso())
    assert row_obs is not None
    b._process_inbox_row(row_obs)

    ctrl = _envelope("control-run-end")
    ctrl["messageType"] = "control"
    ctrl["payload"] = {"action": "run.end"}
    b._handle_control(ctrl)
    # Simulate outbox PUBACK for observation + flush results so connected drain can complete.
    def _publish_all_results() -> None:
        for row in b.store.claim_pending_outbox(50):
            if row["kind"] == "result":
                b.store.mark_outbox_published(int(row["id"]), utc_now_iso())

    _publish_all_results()

    row_end = b.store.claim_next_for_session("session-A", utc_now_iso())
    assert row_end is not None
    assert row_end["message_id"] == "control-run-end"

    # While run.end waits for result delivery, publish any newly enqueued flush results.
    original_pending = b.store.session_pending_outbox_count

    def _pending_and_publish(session_id, kinds=None):  # noqa: ANN001
        n = original_pending(session_id, kinds=kinds)
        if n:
            _publish_all_results()
        return original_pending(session_id, kinds=kinds)

    b.store.session_pending_outbox_count = _pending_and_publish  # type: ignore[method-assign]
    b._process_inbox_row(row_end)

    assert "run_end" in published_status
    assert b.store.get_inbox("control-run-end")["status"] == "done"
    drained = [
        json.loads(r["payload_json"])["payload"]["status"]
        for r in b.store.claim_pending_outbox(50)
        if r["kind"] == "ack"
    ]
    assert "drained" in drained
    b.store.close()


def test_r1_05_publish_requires_is_published(bridge: MqttBridge):
    class Info:
        def wait_for_publish(self, timeout=None):
            return None

        def is_published(self):
            return False

    class Client:
        def publish(self, *a, **k):
            return Info()

    bridge._client = Client()  # type: ignore[assignment]
    with pytest.raises(PublishNotAcked):
        bridge._publish("result", {"demo": 1})


def test_r1_05_map_409_idempotency_distinct():
    assert (
        map_http_error_to_ack_status(409, {"detail": {"error": "idempotency_expired"}})
        == "idempotency_expired"
    )
    assert (
        map_http_error_to_ack_status(409, {"detail": {"error": "idempotency_capacity"}})
        == "idempotency_capacity"
    )
    assert (
        map_http_error_to_ack_status(409, {"detail": {"error": "batch_id_conflict"}})
        == "conflict"
    )


def test_r1_05_non_object_input_does_not_raise(bridge: MqttBridge):
    bridge._handle_input([])  # type: ignore[arg-type]
    acks = [
        json.loads(r["payload_json"])["payload"]["status"]
        for r in bridge.store.claim_pending_outbox(10)
    ]
    assert "rejected" in acks


def test_r1_06_session_dedup_isolation(bridge: MqttBridge):
    a = _envelope("same-mid", "session-A", "o0", 100)
    b = _envelope("same-mid", "session-B", "o0", 999)
    bridge._handle_input(a)
    bridge._handle_input(b)
    # Same messageId + different session fingerprint → conflict (no silent cross-session dedupe).
    acks = [json.loads(r["payload_json"]) for r in bridge.store.claim_pending_outbox(20)]
    statuses = [x["payload"]["status"] for x in acks]
    assert "conflict" in statuses or bridge.store.inbox_count() == 2
    fp_a = content_fingerprint(
        a["payload"], tenant_id="tenant-demo", site_id="site-demo", session_id="session-A"
    )
    fp_b = content_fingerprint(
        b["payload"], tenant_id="tenant-demo", site_id="site-demo", session_id="session-B"
    )
    assert fp_a != fp_b


def test_r1_06_observation_index_session_scoped(tmp_path: Path):
    st = IntegrationStore(tmp_path / "obs.sqlite3")
    st.index_observations(
        session_id="A",
        message_id="A",
        observations=[_obs("same-o", 0, 100)],
        now_iso=utc_now_iso(),
    )
    st.index_observations(
        session_id="B",
        message_id="B",
        observations=[_obs("same-o", 0, 999)],
        now_iso=utc_now_iso(),
    )
    got_a = st.lookup_observations(["same-o"], session_id="A")["same-o"]
    got_b = st.lookup_observations(["same-o"], session_id="B")["same-o"]
    assert got_a["altitude"] == 100
    assert got_b["altitude"] == 999
    st.close()


def test_r1_06_epoch_change_triggers_recovery(bridge: MqttBridge):
    reports: list[tuple] = []

    def capture(state, detail=None, session_id="", **kw):
        reports.append((state, detail, session_id))
        # Keep outbox path (fixture stubs _publish_status to no-op).
        MqttBridge._enqueue_status(bridge, state, detail, session_id)

    bridge._publish_status = capture  # type: ignore[method-assign]

    class HTTP:
        def __init__(self):
            self.i = 0

        def post(self, url, json):  # noqa: A002
            self.i += 1
            return httpx.Response(
                200,
                json={
                    "sessionId": json.get("sessionId"),
                    "batchId": json["batchId"],
                    "epoch": "epoch-A" if self.i == 1 else "epoch-B",
                    "fusionProfile": json.get("fusionProfile"),
                    "snapshotSeq": self.i,
                    "watermark": json.get("processingTime") or utc_now_iso(),
                    "algorithmVersion": "test-algo",
                    "configVersion": "test-config",
                    "tracks": [],
                    "trajectoryUpdates": [],
                    "altitudeUpdates": [],
                    "events": [],
                    "rejected": [],
                },
            )

        def close(self):
            return None

    bridge._http = HTTP()  # type: ignore[assignment]
    for i in range(2):
        bridge._handle_input(_envelope(f"m{i}", oid=f"o{i}"))
        row = bridge.store.claim_next_for_session("session-A", utc_now_iso())
        assert row is not None
        bridge._process_inbox_row(row)

    assert any(r[0] == "state_recovery_required" for r in reports)
    meta = bridge.store.get_session_meta("session-A")
    assert int(meta["paused"]) == 1


def test_r1_06_tenant_site_mismatch_rejected(bridge: MqttBridge):
    msg = _envelope("bad-site")
    msg["siteId"] = "other-site"
    bridge._handle_input(msg)
    acks = [
        json.loads(r["payload_json"])["payload"]
        for r in bridge.store.claim_pending_outbox(10)
        if r["kind"] == "ack"
    ]
    assert any(a["status"] == "rejected" and "site_mismatch" in str(a.get("detail")) for a in acks)


def test_r1_06_write_ownership_http_blocks_mqtt(bridge: MqttBridge):
    bridge.store.set_write_owner("session-A", "http", utc_now_iso())
    bridge._handle_input(_envelope("m-http-owned"))
    acks = [
        json.loads(r["payload_json"])["payload"]
        for r in bridge.store.claim_pending_outbox(10)
    ]
    assert any(a["status"] == "rejected" for a in acks)
    assert bridge.store.get_inbox("m-http-owned") is None


def test_r1_07_active_inbox_capacity_ignores_done(tmp_path: Path):
    st = IntegrationStore(tmp_path / "cap.sqlite3", max_inbox=2)
    statuses = []
    for i in range(3):
        statuses.append(
            st.try_insert_inbox(
                message_id=str(i),
                session_id="s",
                batch_id=str(i),
                content_hash=f"hash-{i}",
                raw={},
                now_iso=utc_now_iso(),
            )
        )
        st.mark_inbox_done(str(i), utc_now_iso())
    assert statuses[-1] != "capacity"
    assert st.active_inbox_count() == 0
    st.close()


def test_r1_07_worker_cap_not_exceeded(tmp_path: Path):
    b = MqttBridge(
        BridgeConfig(sqlite_path=str(tmp_path / "workers.sqlite3"), max_session_workers=1)
    )

    class DummyThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

    with patch("fusion_mvp.integration.mqtt_bridge.threading.Thread", DummyThread):
        for sid in ("a", "b", "c"):
            b._ensure_session_worker(sid)
    assert len(b._session_threads) <= 1
    assert len(b._waiting_sessions) >= 2
    b._http.close()
    b.store.close()


def test_r1_07_max_idempotency_ids_raised():
    cfg = yaml.safe_load(open("config/fusion.yaml", encoding="utf-8"))
    cap = int(cfg["multisensor_v1"]["max_idempotency_ids"])
    ttl = float(cfg["idempotency_ttl_s"])
    # 5 Hz * TTL * margin should fit under configured cap.
    assert cap >= 20000
    assert cap >= 5 * ttl * 1.2

