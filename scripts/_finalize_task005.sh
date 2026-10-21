#!/usr/bin/env bash
set -euo pipefail
cd /work

python <<'PY'
import hashlib, json
from pathlib import Path
root = Path(".")
frozen = json.loads((root / "reports/task005/frozen_algo_sha256.json").read_text())
ok = True
for rel, exp in frozen.items():
    got = hashlib.sha256((root / rel).read_bytes()).hexdigest()
    m = "MATCH" if got == exp else "DIFF"
    print(m, rel, got)
    if got != exp:
        ok = False
print("ALL_MATCH" if ok else "MISMATCH")
if not ok:
    raise SystemExit(2)
PY

python -m pytest tests/test_task005_challenges.py -q --tb=line 2>&1 | tee reports/task005/pytest_task005.log
python scripts/pack_task005_bundle.py
