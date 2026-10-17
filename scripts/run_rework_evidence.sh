#!/bin/bash
set -e
pip install -q -r requirements.txt
mkdir -p reports/rework_round1 samples/continuous
pytest -q tests/ --tb=line 2>&1 | tee reports/rework_round1/post_fix_all.log
python scripts/extract_continuous_segment.py
python scripts/replay_continuous.py
flow2spec doctor > reports/rework_round1/flow2spec_doctor.txt 2>&1 || true
flow2spec version > reports/rework_round1/flow2spec_version.txt 2>&1 || true
