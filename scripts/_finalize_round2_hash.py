import hashlib
from pathlib import Path

p = Path("TASK-001-attempt-001-rework-round2-review-bundle.zip")
h = hashlib.sha256(p.read_bytes()).hexdigest()
line = f"{h}  {p.name}\n"
Path("reports/rework_round2/bundle_sha256.txt").write_text(line, encoding="utf-8")
task = Path(".task/chriswork400/completed/20261017-task001_rework_round2/task.md")
text = task.read_text(encoding="utf-8")
marker = "SHA-256："
if marker in text:
    before, after = text.split(marker, 1)
    rest = after.split("\n", 1)
    tail = rest[1] if len(rest) > 1 else ""
    text = before + marker + h + "\n" + tail
    task.write_text(text, encoding="utf-8")
print(line.strip())
print("bytes", p.stat().st_size)
