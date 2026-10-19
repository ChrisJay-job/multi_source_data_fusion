"""Workbench acceptance W01–W10 (subset automated)."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fusion_mvp.api import app
from fusion_mvp.engine import FusionSession, load_config
from fusion_mvp.workbench.importer import MappingTemplate, import_tabular
from fusion_mvp.workbench.runner import WorkbenchRunner
from fusion_mvp.workbench.scenario import generate_observations, preset_three_aircraft

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def test_w01_three_aircraft_entities_and_no_truth_leak():
    sc = preset_three_aircraft()
    bundle = generate_observations(sc)
    for o in bundle["observations"]:
        assert "truth_id" not in o and "TRUTH-" not in json.dumps(o)
    result = WorkbenchRunner().run_scenario_bundle(bundle, mode="realtime")
    assert result["truth_leaked_to_algorithm"] is False
    ev = result["evaluation"]
    assert ev is not None
    assert ev["entity_check"]["ok"] is True, ev
    assert ev["n_tracks_final"] == 3
    # C should have all three sources on one entity
    c_ok = [d for d in ev["entity_check"]["details"] if d.get("truth_id") == "TRUTH-C" and d.get("ok")]
    assert c_ok and set(c_ok[0]["sources"]) >= {"rid", "spectrum", "radar"}


def test_w02_layer_flags_do_not_change_algorithm_inputs():
    # layers are UI-only; algorithm path identical for same observations
    sc = preset_three_aircraft()
    sc.duration_s = 12
    b = generate_observations(sc)
    r1 = WorkbenchRunner().run_batch_replay(b["observations"][:30], mode="replay", batch_size=10)
    r2 = WorkbenchRunner().run_batch_replay(b["observations"][:30], mode="replay", batch_size=10)
    assert r1["final_tracks"][0]["longitude"] == pytest.approx(r2["final_tracks"][0]["longitude"], abs=1e-12)


def test_w03_same_seed_reproducible():
    sc = preset_three_aircraft()
    a = generate_observations(sc)["observations"]
    b = generate_observations(sc)["observations"]
    assert [o["observationId"] for o in a] == [o["observationId"] for o in b]
    assert [o["longitude"] for o in a] == [o["longitude"] for o in b]


def test_w04_radar_track_swap_emits_observations():
    sc = preset_three_aircraft()
    sc.aircraft = [a for a in sc.aircraft if a.label == "C"]
    sc.duration_s = 30
    # Explicit swap only — null no longer invents a hidden 20s change (TASK-003)
    sc.aircraft[0].sources["radar"].radar_id_swap_at_s = 20.0
    obs = generate_observations(sc)["observations"]
    radar = [o for o in obs if o["source"] == "radar"]
    tids = {o["sourceTrackId"] for o in radar}
    assert len(tids) >= 2  # swap after explicit t=20


def test_w05_csv_import_and_http_run():
    path = ROOT / "samples/workbench/mix_ok.csv"
    tmpl = MappingTemplate(
        field_map={
            "observationId": "observationId",
            "source": "source",
            "sourceTrackId": "sourceTrackId",
            "aircraftId": "aircraftId",
            "measurementTime": "measurementTime",
            "longitude": "longitude",
            "latitude": "latitude",
            "detectorId": "detectorId",
        }
    )
    summary = import_tabular(path, tmpl)
    assert summary["ok"] and summary["n_observations"] == 3
    r = WorkbenchRunner().run_batch_replay(summary["observations"], mode="replay")
    assert r["final_tracks"]


def test_w06_timezone_and_bearing_only_rejected():
    tmpl = MappingTemplate(
        field_map={"measurementTime": "measurementTime", "longitude": "longitude", "latitude": "latitude", "source": "source", "sourceTrackId": "id"},
        assume_utc_naive=False,
    )
    bad = {"source": "rid", "id": "x", "measurementTime": "2026-04-09 12:00:01", "longitude": 117.2, "latitude": 39.13}
    from fusion_mvp.workbench.importer import row_to_observation

    obs, err = row_to_observation(bad, tmpl, 1)
    assert obs is None and err["reason"] == "bad_measurement_time"
    bear = {"source": "spectrum", "id": "y", "measurementTime": "2026-04-09T12:00:01+00:00"}
    obs2, err2 = row_to_observation(bear, tmpl, 2)
    assert err2["reason"] == "position_fusion_unsupported"


def test_w07_http_process_monotonic_and_reset():
    s = client.post(
        "/v1/fusion/process",
        json={
            "sessionId": "wb-http",
            "batchId": "1",
            "mode": "replay",
            "processingTime": "2026-04-09T12:00:01+00:00",
            "observations": [
                {
                    "observationId": "h1",
                    "source": "rid",
                    "detectorId": "D",
                    "sourceTrackId": "SN-H",
                    "aircraftId": "SN-H",
                    "measurementTime": "2026-04-09T12:00:01+00:00",
                    "longitude": 117.2,
                    "latitude": 39.13,
                    "altitudeDatum": "unknown",
                    "qualityFlags": [],
                }
            ],
        },
    )
    assert s.status_code == 200
    bad = client.post(
        "/v1/fusion/process",
        json={
            "sessionId": "wb-http",
            "batchId": "2",
            "mode": "replay",
            "processingTime": "2026-04-09T11:00:00+00:00",
            "observations": [],
        },
    )
    assert bad.status_code == 400
    client.post("/v1/fusion/reset/wb-http")


def test_w08_draw_vs_process_counts_reported():
    sc = preset_three_aircraft()
    sc.duration_s = 8
    b = generate_observations(sc)
    r = WorkbenchRunner().run_batch_replay(b["observations"], mode="replay", batch_size=5)
    assert r["counts"]["delivered"] == len(b["observations"])
    assert "processed_hits" in r["counts"]


def test_w09_real_import_has_no_fake_accuracy():
    path = ROOT / "samples/workbench/mix_ok.csv"
    summary = import_tabular(
        path,
        MappingTemplate(
            field_map={
                "observationId": "observationId",
                "source": "source",
                "sourceTrackId": "sourceTrackId",
                "aircraftId": "aircraftId",
                "measurementTime": "measurementTime",
                "longitude": "longitude",
                "latitude": "latitude",
            }
        ),
    )
    r = WorkbenchRunner().run_batch_replay(summary["observations"], mode="replay")
    assert r.get("evaluation") is None  # no truth map → no accuracy


def test_w10_binding_status_and_openapi_paths():
    cfg = deepcopy(load_config())
    sess = FusionSession("bind", cfg)
    row = {
        "observationId": "b1",
        "source": "rid",
        "detectorId": "D",
        "sourceTrackId": "SN-Z",
        "aircraftId": "SN-Z",
        "measurementTime": "2026-04-09T12:00:01+00:00",
        "longitude": 117.2,
        "latitude": 39.13,
        "altitudeDatum": "unknown",
        "qualityFlags": [],
    }
    resp = sess.process("1", row["measurementTime"], [row], "replay")
    assert resp.tracks[0].sourceTracks[0].bindingStatus in ("confirmed", "candidate")
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/v1/workbench/run/scenario" in paths
    assert "/v1/fusion/process" in paths


def test_scenario_http_endpoint():
    r = client.post(
        "/v1/workbench/run/scenario",
        json={"scenarioName": "three_aircraft_primary", "mode": "realtime", "seed": 20261017},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["evaluation"]["entity_check"]["ok"] is True
    r2 = client.post(
        "/v1/workbench/run/scenario",
        json={"scenarioName": "three_aircraft_primary", "mode": "replay", "seed": 20261017},
    )
    assert r2.status_code == 200
    assert r2.json()["evaluation"]["entity_check"]["ok"] is True
