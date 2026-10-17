#!/bin/bash
cd /work
mkdir -p reports/rework_round1
(
  find src tests config docs demo scripts -type f | sort | while read f; do
    sha256sum "$f"
  done
  sha256sum requirements.txt README.md docker-compose.yml pytest.ini 2>/dev/null
) > reports/rework_round1/source_sha256.txt
wc -l reports/rework_round1/source_sha256.txt
