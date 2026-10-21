#!/usr/bin/env bash
set -euo pipefail
cd /work
mkdir -p reports/task005_rework_round1

# Freeze check
python <<'PY'
import hashlib, json
from pathlib import Path
root = Path(".")
paths = [
    "src/fusion_mvp/engine.py",
    "src/fusion_mvp/kalman.py",
    "src/fusion_mvp/mapping.py",
    "src/fusion_mvp/models.py",
    "config/fusion.yaml",
]
out = {rel: hashlib.sha256((root / rel).read_bytes()).hexdigest() for rel in paths if (root / rel).exists()}
(root / "reports/task005_rework_round1/frozen_algo_sha256.json").write_text(
    json.dumps(out, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(out, indent=2))
PY

# Full pytest log (worktree)
PYTHONPATH=/work/src python -m pytest -q --tb=line 2>&1 | tee reports/task005_rework_round1/full_pytest_worktree.log

# Pack
python scripts/pack_task005_rework_round1_bundle.py

# Clean extract verify (no unzip binary — use Python zipfile)
ZIP=/work/TASK-005-attempt-001-rework-round1-review-bundle.zip
TMP=/tmp/task005_r1_clean_$$
rm -rf "$TMP"
mkdir -p "$TMP"
python - <<PY
import zipfile
from pathlib import Path
zipfile.ZipFile("$ZIP").extractall("$TMP")
print("extracted", len(list(Path("$TMP").rglob("*"))), "paths")
PY
cd "$TMP"
export PYTHONPATH="$TMP/src"
python - <<'PY'
import fusion_mvp.api  # noqa: F401
print("import_ok fusion_mvp.api")
PY
python -m pytest -q tests/test_task005_challenges.py --tb=line
python -m pytest -q --tb=line 2>&1 | tee /work/reports/task005_rework_round1/clean_extract_full_pytest.log
echo CLEAN_EXTRACT_OK
cd /work
# Re-pack so clean log is inside zip
python scripts/pack_task005_rework_round1_bundle.py
