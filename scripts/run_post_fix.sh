#!/bin/bash
set -e
pip install -q -r requirements.txt
mkdir -p reports/rework_round1
set +e
pytest -q tests/test_review_regressions.py tests/test_t01_t12.py --tb=short 2>&1 | tee reports/rework_round1/post_fix_all.log
echo EXIT:${PIPESTATUS[0]}
