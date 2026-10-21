#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ZIP="${1:-$ROOT/TASK-005-attempt-001-rework-round3-review-bundle.zip}"
TMP="${TMPDIR:-/tmp}/task005_r3_clean_$$"
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT
unzip -q "$ZIP" -d "$TMP"
cd "$TMP"
export PYTHONPATH="$TMP/src"
python - <<'PY'
import fusion_mvp.api  # noqa: F401
print("import_ok fusion_mvp.api")
PY
python -m pytest -q tests/test_task005_rework_round3.py tests/test_task005_rework_round2.py --tb=line
python -m pytest -q --tb=line 2>&1 | tee "$ROOT/reports/task005_rework_round3/clean_extract_full_pytest.log"
echo "CLEAN_EXTRACT_OK"
