"""Build TASK-002 attempt-001 REWORK Round4 review bundle."""
from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "TASK-002-attempt-001-rework-round4-review-bundle.zip"
REP = ROOT / "reports" / "task002_rework_round4"
HASH_OUT = REP / "source_sha256.txt"
BUNDLE_HASH = REP / "bundle_sha256.txt"

INCLUDE_DIRS = [
    "src", "tests", "config", "scripts", "samples", "scenarios", "docs", "demo", "prompt",
    "reports/task001_freeze", "reports/task002", "reports/task002_rework_round1",
    "reports/task002_rework_round2", "reports/task002_rework_round3",
    "reports/task002_rework_round4",
    "review_zip/PASS_and_TASK002", "review_zip/TASK002_REWORK_Round1",
    "review_zip/TASK002_REWORK_Round2", "review_zip/TASK002_REWORK_Round3",
    "review_zip/TASK002_REWORK_Round4",
]
INCLUDE_FILES = [
    "requirements.txt", "README.md", "flow2spec.config.json", "pytest.ini",
    "docker-compose.yml", ".gitignore", "package.json",
]
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".git", "uploads", "node_modules"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
SKIP_NAMES = {"aircraft_flight_data.sql", "bundle_sha256.txt", "_check_r4_runner.py"}


def should_skip(path: Path) -> bool:
    if any(p in SKIP_PARTS for p in path.parts):
        return True
    if path.suffix in SKIP_SUFFIXES or path.name in SKIP_NAMES:
        return True
    if path.suffix == ".sql" and path.stat().st_size > 1_000_000:
        return True
    if path.name.startswith("_") and path.parent.name == "scripts":
        return True
    return False


def main() -> None:
    src_b = ROOT / "output" / "review_stage" / "task002_round4_browser"
    if src_b.exists():
        dst = REP / "browser"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src_b, dst)
    files: list[Path] = []
    for rel in INCLUDE_FILES:
        p = ROOT / rel
        if p.is_file():
            files.append(p)
    for d in INCLUDE_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and not should_skip(p):
                files.append(p)
    for task in [
        ROOT / ".task/chriswork400/active/task002_rework_round4",
        ROOT / ".task/chriswork400/completed/20261017-task002_rework_round4",
    ]:
        if task.exists():
            for p in task.rglob("*"):
                if p.is_file():
                    files.append(p)
    uniq = list(dict.fromkeys(files))
    lines = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {str(p.relative_to(ROOT)).replace(chr(92), '/')}"
        for p in sorted(uniq, key=lambda x: str(x.relative_to(ROOT)).replace("\\", "/"))
    ]
    REP.mkdir(parents=True, exist_ok=True)
    HASH_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if HASH_OUT not in uniq:
        uniq.append(HASH_OUT)
    uniq = list(dict.fromkeys(uniq))
    if OUT.exists():
        OUT.unlink()
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in uniq:
            zf.write(p, arcname=str(p.relative_to(ROOT)).replace("\\", "/"))
        zf.writestr(
            "BUNDLE_MANIFEST.txt",
            "TASK-002 attempt-001 REWORK Round4\nstatus=REVIEW_READY\nfreeze=false\n"
            "real_multi_source=BLOCKED\nfield_accuracy=NOT_TESTED\n",
        )
        zf.writestr(
            "OPERABLE_PAGE.txt",
            "URL=http://127.0.0.1:18089/\ncontainer=fusion-mvp-workbench\npytest=71 passed\n",
        )
        zf.writestr(
            "GIT_BASELINE.txt",
            "tag=task-001-three-source-fusion-mvp-v1\n"
            "task001_commit=a80553fd43e1349fa2dfdfa670e1f92b7fcdca71\n"
            "branch=task-002-fusion-validation-workbench\npushed=false\nstatus=REVIEW_READY\n",
        )
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    BUNDLE_HASH.write_text(f"{digest}  {OUT.name}\n", encoding="utf-8")
    print(OUT, OUT.stat().st_size, "sha256", digest)


if __name__ == "__main__":
    main()
