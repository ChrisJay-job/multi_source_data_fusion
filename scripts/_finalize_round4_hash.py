import hashlib
from pathlib import Path

p = Path("TASK-001-attempt-001-rework-round4-review-bundle.zip")
h = hashlib.sha256(p.read_bytes()).hexdigest()
Path("reports/rework_round4/bundle_sha256.txt").write_text(f"{h}  {p.name}\n", encoding="utf-8")
task = Path(".task/chriswork400/completed/20261017-task001_rework_round4/task.md")
if task.exists():
    text = task.read_text(encoding="utf-8")
    marker = "SHA-256："
    if marker in text:
        before, after = text.split(marker, 1)
        rest = after.split("\n", 1)
        tail = rest[1] if len(rest) > 1 else ""
        task.write_text(before + marker + h + "\n" + tail, encoding="utf-8")
print(f"{h}  {p.name}")
print("bytes", p.stat().st_size)
