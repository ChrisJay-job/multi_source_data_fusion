"""Run TASK-005 challenge × identity × seed matrix; geometry-first, all spacing bands."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fusion_mvp.workbench.runner import WorkbenchRunner
from fusion_mvp.workbench.scenario import generate_observations, get_preset, save_scenario
from fusion_mvp.workbench.scenario_challenges import (
    CHALLENGE_PRESET_BUILDERS,
    actual_identity_sets,
    validate_challenge_geometry,
)

OUT = ROOT / "reports" / "task005_rework_round1"
SEEDS = [101, 102, 103, 104, 105]

# All spacing bands + core challenges × identity modes used in fair compare / mixed
CORE = []
for sp in (2, 5, 10, 30, 100):
    CORE.append(f"challenge_near_parallel_{sp}m_with_id")
    CORE.append(f"challenge_near_parallel_{sp}m_anon")
    CORE.append(f"challenge_near_parallel_{sp}m_mixed")
CORE.extend(
    [
        "challenge_simultaneous_cross_with_id",
        "challenge_simultaneous_cross_anon",
        "challenge_simultaneous_cross_mixed",
        "challenge_async_cross_with_id",
        "challenge_async_cross_anon",
        "challenge_overtake_with_id",
        "challenge_overtake_anon",
        "challenge_cross_rid_outage_with_id",
        "challenge_cross_rid_outage_anon",
        "challenge_cross_rid_outage_mixed",
        "challenge_cross_radar_swap_with_id",
        "challenge_cross_radar_swap_anon",
        "challenge_cross_radar_swap_mixed",
    ]
)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    runner = WorkbenchRunner()
    rows = []
    geo_rows = []

    for name, builder in CHALLENGE_PRESET_BUILDERS.items():
        sc = builder()
        save_scenario(sc, ROOT / "scenarios" / f"{name}.json")
        geo = validate_challenge_geometry(sc)
        geo_rows.append({"scenario": name, **{k: geo.get(k) for k in ("ok", "verification_status", "checks", "identity_mode", "min_truth_distance_m")}})
        print("GEO", name, geo.get("ok"), geo.get("verification_status"), "checks", len(geo.get("checks") or []))

    (OUT / "geometry_precheck.json").write_text(
        json.dumps(geo_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    for name in CORE:
        for seed in SEEDS:
            sc = get_preset(name)
            sc.seed = seed
            geo = validate_challenge_geometry(sc)
            id_audit = actual_identity_sets(sc)
            if not geo.get("ok"):
                rows.append(
                    {
                        "scenario": name,
                        "seed": seed,
                        "geometry_ok": False,
                        "verification_status": geo.get("verification_status"),
                        "identity_mode": sc.identity_mode,
                        "identity_audit": id_audit,
                        "entity_status": None,
                        "skipped_reason": "geometry_invalid_not_used_as_success_evidence",
                        "checks": geo.get("checks"),
                    }
                )
                print(name, seed, "SKIP_GEO_FAIL")
                continue
            bundle = generate_observations(sc)
            out = runner.run_scenario_bundle(bundle, mode="replay")
            ev = out.get("evaluation") or {}
            ec = ev.get("entity_check") or {}
            seek = None
            err_types = []
            for fm in ev.get("false_merges") or []:
                err_types.append("false_merge")
                seek = seek or fm.get("at")
            for ae in ev.get("attribution_errors") or []:
                err_types.append(ae.get("reason") or "attribution")
                seek = seek or ae.get("at")
            for d in ev.get("duplicate_targets") or []:
                err_types.append("duplicate_target")
                seek = seek or d.get("at")
            rows.append(
                {
                    "scenario": name,
                    "seed": seed,
                    "geometry_ok": True,
                    "verification_status": geo.get("verification_status"),
                    "identity_mode": sc.identity_mode,
                    "identity_audit": id_audit,
                    "min_truth_distance_m": geo.get("min_truth_distance_m"),
                    "entity_status": ec.get("status"),
                    "entity_ok": ec.get("ok"),
                    "false_merges": len(ev.get("false_merges") or []),
                    "duplicates": len(ev.get("duplicate_targets") or []),
                    "undetermined": len(ev.get("undetermined") or []),
                    "error_types": sorted(set(err_types)),
                    "seek_time": seek,
                    "metrics_display": ev.get("metrics_display"),
                    "n_obs": len(bundle["observations"]),
                    "n_tracks_final": len(out.get("final_tracks") or []),
                }
            )
            print(name, seed, ec.get("status"), "fm", len(ev.get("false_merges") or []))

    (OUT / "challenge_matrix.json").write_text(
        json.dumps({"seeds": SEEDS, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    hashes = {}
    for rel in [
        "src/fusion_mvp/engine.py",
        "src/fusion_mvp/kalman.py",
        "src/fusion_mvp/mapping.py",
        "src/fusion_mvp/models.py",
        "config/fusion.yaml",
    ]:
        p = ROOT / rel
        if p.exists():
            hashes[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    (OUT / "frozen_algo_sha256.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT / "challenge_matrix.json", "rows", len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
