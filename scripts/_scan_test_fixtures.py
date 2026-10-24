"""List sample/review_zip paths referenced by tests that are missing on disk."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
missing: list[str] = []
found: list[str] = []
for p in (ROOT / "tests").glob("*.py"):
    t = p.read_text(encoding="utf-8", errors="ignore")
    # ROOT / "a" / "b" chains — rough collect of quoted segments after ROOT
    for m in re.finditer(r'ROOT\s*/\s*((?:\s*/\s*)?(?:"[^"]+"|\'[^\']+\'))+', t):
        parts = re.findall(r'"([^"]+)"|\'([^\']+)\'', m.group(0))
        segs = [a or b for a, b in parts]
        if not segs:
            continue
        rel = "/".join(segs)
        if rel.startswith("reports/"):
            continue
        path = ROOT.joinpath(*segs)
        item = str(path.relative_to(ROOT)).replace("\\", "/")
        if path.exists():
            if item not in found:
                found.append(item)
        else:
            if item not in missing:
                missing.append(item)
print("FOUND", len(found))
for x in sorted(found):
    print("  ok", x)
print("MISSING", len(missing))
for x in sorted(missing):
    print("  miss", x)
