#!/usr/bin/env bash
# Clean-extract verification for TASK-005 rework round2 bundle (Python 3.11).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ZIP="${1:-$ROOT/TASK-005-attempt-001-rework-round2-review-bundle.zip}"
TMP="${TMPDIR:-/tmp}/task005_r2_clean_$$"
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT
unzip -q "$ZIP" -d "$TMP"
cd "$TMP"
export PYTHONPATH="$TMP/src"
python - <<'PY'
import fusion_mvp.api  # noqa: F401
print("import_ok fusion_mvp.api")
PY
python -m pytest -q tests/test_task005_challenges.py tests/test_task005_rework_round2.py --tb=line
python -m pytest -q --tb=line 2>&1 | tee "$ROOT/reports/task005_rework_round2/clean_extract_full_pytest.log"
echo "CLEAN_EXTRACT_OK"
