#!/bin/bash
set -euo pipefail
cd /work
pip install -q -r requirements.txt
python - <<'PY'
from fusion_mvp.workbench.scenario import get_preset, PRESET_BUILDERS
print('presets', len(PRESET_BUILDERS))
sc = get_preset('seven_plus_challenges_with_id')
print('aircraft', len(sc.aircraft), sc.name)
from fusion_mvp.workbench.scenario_challenges import validate_challenge_geometry
print('geo', validate_challenge_geometry(get_preset('challenge_simultaneous_cross_with_id')))
PY
pytest -q tests/test_task005_challenges.py --tb=short
python scripts/run_task005_challenge_matrix.py
