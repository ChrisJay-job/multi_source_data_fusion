"""Pack TASK-003 Round1 review bundle."""
from __future__ import annotations

import hashlib
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_ZIP = ROOT / "TASK-003-attempt-001-rework-round1-review-bundle.zip"
REPORT = ROOT / "reports" / "task003_rework_round1"

INCLUDE_DIRS = [
    "src",
    "tests",
    "demo/workbench",
    "scenarios",
    "samples/workbench",
    "config",
    "docs/interface",
    "reports/task003_rework_round1",
    "reports/task003/pre_fix",
    "reports/task003/post_fix",
]
INCLUDE_FILES = [
    "requirements.txt",
    "pytest.ini",
    "docker-compose.yml",
    "package.json",
    "README.md",
    ".gitignore",
    "review_zip/TASK-003_attempt-001_REWORK_Round1.md",
    "review_zip/TASK003_REWORK_Round1/TASK-003_attempt-001_REWORK_Round1.md",
    "review_zip/TASK003_REWORK_Round1/test_task003_review.py",
    "review_zip/TASK003_REWORK_Round1/probe_task003_ui.cjs",
    "review_zip/TASK003_REWORK_Round1/make_seven_probe_run.py",
    "review_zip/TASK003_REWORK_Round1/ui_probe_results.json",
    "review_zip/TASK003_REWORK_Round1/independent_regressions.log",
    "review_zip/TASK003_REWORK_Round1/review_environment.json",
    "scripts/browser_workbench_task003.mjs",
    "scripts/probe_task003_ui.cjs",
    "scripts/make_seven_probe_run.py",
    "scripts/pack_task003_rework_round1_bundle.py",
    "scripts/task003_pre_fix_capture.py",
]
EXCLUDE = {"__pycache__", ".pytest_cache", "node_modules", ".git", "uploads"}


def _ok(p: Path) -> bool:
    if not p.is_file():
        return False
    if any(x in EXCLUDE for x in p.parts):
        return False
    if p.suffix.lower() in {".zip", ".sql"} and "aircraft_flight" in p.name:
        return False
    if p.suffix.lower() == ".zip":
        return False
    return True


def main() -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    files: set[Path] = set()
    for d in INCLUDE_DIRS:
        base = ROOT / d
        if base.exists():
            for p in base.rglob("*"):
                if _ok(p):
                    files.add(p)
    for rel in INCLUDE_FILES:
        p = ROOT / rel
        if _ok(p):
            files.add(p)

    def _git(*a: str) -> str:
        try:
            return subprocess.check_output(["git", *a], cwd=ROOT, text=True)
        except Exception as exc:  # noqa: BLE001
            return f"(git unavailable: {exc})\n"

    (REPORT / "git_status.txt").write_text(
        f"branch={_git('branch', '--show-current').strip()}\n"
        f"HEAD={_git('rev-parse', 'HEAD').strip()}\n"
        f"task-002-tag={_git('rev-list', '-n', '1', 'task-002-fusion-validation-workbench-v1').strip()}\n\n"
        f"{_git('status', '-sb')}\n",
        encoding="utf-8",
    )
    sha_lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(ROOT).as_posix()}" for p in sorted(files, key=lambda x: x.as_posix())]
    (REPORT / "source_sha256.txt").write_text("\n".join(sha_lines) + "\n", encoding="utf-8")
    files |= {REPORT / "git_status.txt", REPORT / "source_sha256.txt"}

    if OUT_ZIP.exists():
        OUT_ZIP.unlink()
    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(files, key=lambda x: x.as_posix()):
            zf.write(p, p.relative_to(ROOT).as_posix())
    digest = hashlib.sha256(OUT_ZIP.read_bytes()).hexdigest()
    (REPORT / "bundle_sha256.txt").write_text(f"{digest}  {OUT_ZIP.name}\n", encoding="utf-8")
    with zipfile.ZipFile(OUT_ZIP, "a", compression=zipfile.ZIP_DEFLATED) as zf:
        # replace single entry
        pass
    # rewrite zip without duplicate hash by rebuilding once more including hash file
    files.add(REPORT / "bundle_sha256.txt")
    tmp = OUT_ZIP.with_suffix(".tmp.zip")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        seen = set()
        for p in sorted(files, key=lambda x: x.as_posix()):
            name = p.relative_to(ROOT).as_posix()
            if name in seen:
                continue
            seen.add(name)
            zf.write(p, name)
    tmp.replace(OUT_ZIP)
    digest = hashlib.sha256(OUT_ZIP.read_bytes()).hexdigest()
    (REPORT / "bundle_sha256.txt").write_text(f"{digest}  {OUT_ZIP.name}\n", encoding="utf-8")
    print(OUT_ZIP)
    print("sha256", digest)
    print("files", len(seen))


if __name__ == "__main__":
    main()
