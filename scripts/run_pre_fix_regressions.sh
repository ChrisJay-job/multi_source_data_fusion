#!/bin/bash
set -e
pip install -q -r requirements.txt
python - <<'PY'
import sys, fastapi, numpy, scipy, pyproj, pydantic, pytest
print("python", sys.version)
print("fastapi", fastapi.__version__)
print("numpy", numpy.__version__)
print("scipy", scipy.__version__)
print("pyproj", pyproj.__version__)
print("pydantic", pydantic.__version__)
print("pytest", pytest.__version__)
PY
mkdir -p reports/rework_round1
set +e
pytest -q tests/test_review_regressions.py --tb=line 2>&1 | tee reports/rework_round1/pre_fix_regressions.log
echo EXIT:$?
pytest -q tests/test_t01_t12.py --tb=line 2>&1 | tee reports/rework_round1/pre_fix_t01_t12.log
echo EXIT_T:$?
