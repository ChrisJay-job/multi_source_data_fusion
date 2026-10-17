#!/bin/bash
set -e
pip install -q -r requirements.txt
mkdir -p reports/rework_round2
python - <<'PY'
import sys,fastapi,numpy,scipy,pyproj,pydantic,pytest
print("python",sys.version)
print("fastapi",fastapi.__version__)
print("numpy",numpy.__version__)
print("scipy",scipy.__version__)
print("pyproj",pyproj.__version__)
print("pydantic",pydantic.__version__)
print("pytest",pytest.__version__)
open("reports/rework_round2/locked_env.txt","w",encoding="utf-8").write(
f"python={sys.version}\nfastapi={fastapi.__version__}\nnumpy={numpy.__version__}\nscipy={scipy.__version__}\npyproj={pyproj.__version__}\npydantic={pydantic.__version__}\npytest={pytest.__version__}\n"
)
PY
set +e
pytest -q tests/test_round2_regressions.py --tb=line 2>&1 | tee reports/rework_round2/pre_fix_round2.log
echo EXIT_R2:$?
python scripts/audit_continuous.py /work /work/reports/rework_round2/pre_audit_realtime.json realtime
python scripts/audit_continuous.py /work /work/reports/rework_round2/pre_audit_replay.json replay
