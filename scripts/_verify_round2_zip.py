import hashlib
import zipfile
from pathlib import Path

zpath = Path("TASK-001-attempt-001-rework-round2-review-bundle.zip")
data = zpath.read_bytes()
print("sha256", hashlib.sha256(data).hexdigest())
print("bytes", len(data))
with zipfile.ZipFile(zpath) as z:
    names = z.namelist()
print("count", len(names))
for n in names:
    if any(
        k in n
        for k in (
            "rework_round2/",
            "engine.py",
            "BUNDLE",
            "20261017-task001_rework_round2",
            "test_round2",
            "post_audit",
            "pre_fix",
        )
    ):
        print(n)
