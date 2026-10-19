"""Build TASK-002 review bundle."""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "TASK-002-attempt-001-review-bundle.zip"
HASH_OUT = ROOT / "reports" / "task002" / "source_sha256.txt"

INCLUDE_DIRS = [
    "src",
    "tests",
    "config",
    "scripts",
    "samples",
    "scenarios",
    "docs",
    "demo",
    "prompt",
    "reports/task001_freeze",
    "reports/task002",
    "reports/rework_round4",
    "review_zip/PASS_and_TASK002",
]
INCLUDE_FILES = [
    "requirements.txt",
    "README.md",
    "flow2spec.config.json",
    "pytest.ini",
    "docker-compose.yml",
    ".gitignore",
]
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".git", "uploads"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
SKIP_NAMES = {"aircraft_flight_data.sql", "bundle_sha256.txt"}


def should_skip(path: Path) -> bool:
    if any(p in SKIP_PARTS for p in path.parts):
        return True
    if path.suffix in SKIP_SUFFIXES or path.name in SKIP_NAMES:
        return True
    if path.name.endswith(".sql") and path.stat().st_size > 1_000_000:
        return True
    if path.name.startswith("_") and path.parent.name == "scripts" and "pack_task002" not in path.name and "pack_round" not in path.name:
        if path.name.startswith("_finalize") or path.name.startswith("_verify") or path.name.startswith("_env"):
            return True
    return False


def main() -> None:
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
    # task folder
    task = ROOT / ".task/chriswork400/completed/20261017-task002_validation_workbench"
    if task.exists():
        for p in task.rglob("*"):
            if p.is_file():
                files.append(p)
    seen = set()
    uniq = []
    for p in files:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    lines = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {str(p.relative_to(ROOT)).replace(chr(92), '/')}"
        for p in sorted(uniq, key=lambda x: str(x.relative_to(ROOT)).replace("\\", "/"))
    ]
    HASH_OUT.parent.mkdir(parents=True, exist_ok=True)
    HASH_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if HASH_OUT not in uniq:
        uniq.append(HASH_OUT)
    # refresh hash file content already written; avoid duplicate zip entries
    uniq = list(dict.fromkeys(uniq))
    if OUT.exists():
        OUT.unlink()
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in uniq:
            zf.write(p, arcname=str(p.relative_to(ROOT)).replace("\\", "/"))
        zf.writestr(
            "BUNDLE_MANIFEST.txt",
            "TASK-002 attempt-001 validation workbench\nstatus=REVIEW_READY\n",
        )
        # git freeze pointers
        zf.writestr(
            "GIT_BASELINE.txt",
            "tag=task-001-three-source-fusion-mvp-v1\n"
            "commit=a80553fd43e1349fa2dfdfa670e1f92b7fcdca71\n"
            "branch=task-002-fusion-validation-workbench\n"
            "pushed=false\n",
        )
    print(OUT, OUT.stat().st_size, "files", len(uniq))


if __name__ == "__main__":
    main()
