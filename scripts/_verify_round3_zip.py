import zipfile
from pathlib import Path

zpath = Path("TASK-001-attempt-001-rework-round3-review-bundle.zip")
with zipfile.ZipFile(zpath) as z:
    n = z.namelist()
print("count", len(n))
for label, pred in [
    ("pytest.ini", lambda: "pytest.ini" in n),
    ("demo", lambda: any(x.startswith("demo/") for x in n)),
    ("docker-compose.yml", lambda: "docker-compose.yml" in n),
    ("engine.py", lambda: "src/fusion_mvp/engine.py" in n),
    ("round3 tests", lambda: "tests/test_round3_regressions.py" in n),
    ("post_audit", lambda: any("post_audit_realtime.json" in x for x in n)),
]:
    print(label, pred())
