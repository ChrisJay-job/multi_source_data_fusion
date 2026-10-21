#!/bin/bash
set -euo pipefail
cd /work
pip install -q -r requirements.txt
# API in background
PYTHONPATH=/work/src uvicorn fusion_mvp.api:app --host 0.0.0.0 --port 18089 &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT
for i in $(seq 1 60); do
  if curl -sf http://127.0.0.1:18089/ready >/dev/null; then break; fi
  sleep 1
done
# Node + playwright (image has browsers if using playwright image; else npx)
if command -v node >/dev/null 2>&1; then
  npm install --no-fund --no-audit 2>/dev/null || true
  npx playwright install chromium 2>/dev/null || true
  WORKBENCH_URL=http://127.0.0.1:18089 node scripts/browser_workbench_task005.mjs
else
  echo "node missing; skip browser" >&2
  mkdir -p reports/task005/browser
  echo '{"pass":false,"error":"node_not_in_image","not_tested":true}' > reports/task005/browser/browser_evidence.json
  exit 2
fi
