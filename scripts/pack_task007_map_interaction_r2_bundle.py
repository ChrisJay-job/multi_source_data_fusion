"""Pack TASK-007 map-interaction REWORK R2 self-contained review zip."""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "TASK-007-attempt-001-map-interaction-rework-r2-review-bundle.zip"
EXCLUDE_PARTS = {
    "__pycache__", ".pytest_cache", "node_modules", ".git", "uploads",
    ".venv", "venv", "dist", "build",
}
EXCLUDE_SUFFIX_ZIP = True
MAX_FILE = 20 * 1024 * 1024


def ok(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.suffix.lower() == ".zip":
        return False
    if path.name.endswith("bundle_sha256.txt"):
        return False
    if any(part in EXCLUDE_PARTS for part in path.parts):
        return False
    if path.stat().st_size > MAX_FILE:
        return False
    return True


def add_tree(found: set[Path], rel: str) -> None:
    base = ROOT / rel
    if not base.exists():
        return
    if base.is_file():
        if ok(base):
            found.add(base)
        return
    for path in base.rglob("*"):
        if ok(path):
            found.add(path)


def main() -> None:
    found: set[Path] = set()
    for rel in [
        "src",
        "tests",
        "config",
        "demo/workbench",
        "docs/task007",
        "reports/task007/map_interaction/r2",
        "reports/task007/map_interaction/history",
        "samples/workbench",
        "samples/task006",
        "samples/task007",
        "review_zip/TASK-007-approved-round5/TASK-007/examples",
        "scripts/task007_map_draw_probe_r2.mjs",
        "scripts/task007_map_interaction_independent_r1.mjs",
        "scripts/task007_map_interaction_browser_r1.mjs",
        "scripts/task007_map_interaction_browser_r2.mjs",
        "scripts/task007_map_zoom_unit.mjs",
        "scripts/pack_task007_map_interaction_r2_bundle.py",
        "scripts/_scan_test_fixtures.py",
        "requirements.txt",
        "package.json",
        "package-lock.json",
        "pytest.ini",
        "Dockerfile.task007",
        "docker-compose.task007.yml",
        "docker-compose.task007-mi-r1.yml",
    ]:
        add_tree(found, rel)

    items = sorted(((p, p.relative_to(ROOT).as_posix()) for p in found), key=lambda x: x[1])
    # Required fixtures must be present
    required = [
        "samples/workbench/mix_ok.csv",
        "samples/workbench/user_four_aircraft_20261019.json",
        "samples/workbench/user_four_aircraft_explicit_swap20.json",
        "samples/task006/csv/mini_mixed.csv",
        "samples/task006/10_M_rid_spectrum_radia_data_simp.json",
        "review_zip/TASK-007-approved-round5/TASK-007/examples/offline_single_target.json",
        "src/fusion_mvp/api.py",
        "demo/workbench/canvas.js",
    ]
    arcs = {arc for _, arc in items}
    miss = [r for r in required if r not in arcs]
    if miss:
        raise SystemExit(f"required fixtures missing from pack: {miss}")

    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {arc}" for p, arc in items]
    readme = """# TASK-007 map-interaction REWORK R2

## Closeouts
- MI-R2-01: fused HISTORY draw merges all commits (draw probe 81/81 & 400/400)
- MI-R2-02: pack includes tests fixtures under samples/ and review_zip/.../examples/

## Reproduce
```bash
unzip ... && cd <extract>
# fixtures check
python scripts/_scan_test_fixtures.py
# draw probe
node scripts/task007_map_draw_probe_r2.mjs demo/workbench/canvas.js /tmp/draw.json
# pytest (prefer python 3.11)
python -m pytest tests/ -q --tb=short
# isolated UI
export FUSION_PORT=18122 COMPOSE_PROJECT_NAME=task007-mi-r2
docker compose -f docker-compose.task007-mi-r1.yml up -d --build
node scripts/task007_map_interaction_browser_r2.mjs http://127.0.0.1:${FUSION_PORT} reports/task007/map_interaction/r2/browser_isolated
docker compose -f docker-compose.task007-mi-r1.yml down
```
Do not use host 18089. See docs/task007/map_interaction_rework_r2.md.
"""
    if OUT.exists():
        OUT.unlink()
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, arc in items:
            zf.write(path, arc)
        zf.writestr("source_sha256.txt", "\n".join(lines) + "\n")
        zf.writestr("README_MAP_INTERACTION_R2.md", readme)
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    side = ROOT / "TASK-007-attempt-001-map-interaction-rework-r2-review-bundle.sha256.txt"
    side.write_text(f"{digest}  {OUT.name}\nbytes={OUT.stat().st_size}\n", encoding="utf-8")
    print(f"{digest}  bytes={OUT.stat().st_size}  files={len(items)}  -> {OUT.name}")


if __name__ == "__main__":
    main()
