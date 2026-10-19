"""Pack TASK-003 attempt-001 review bundle (no 2GB SQL / uploads / secrets / caches)."""
from __future__ import annotations

import hashlib
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_ZIP = ROOT / "TASK-003-attempt-001-review-bundle.zip"
REPORT = ROOT / "reports" / "task003"

INCLUDE_DIRS = [
    "src",
    "tests",
    "demo/workbench",
    "scenarios",
    "samples/workbench",
    "config",
    "docs/interface",
    "reports/task003",
]
INCLUDE_FILES = [
    "requirements.txt",
    "pytest.ini",
    "docker-compose.yml",
    "package.json",
    "README.md",
    ".gitignore",
    "review_zip/TASK-003_attempt-001_Seven_Aircraft_Usability_and_Association.md",
    "scripts/browser_workbench_task003.mjs",
    "scripts/task003_pre_fix_capture.py",
    "scripts/pack_task003_bundle.py",
]
EXCLUDE_PARTS = {
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".git",
    "pgdata",
    "uploads",
}


def _ok(p: Path) -> bool:
    if not p.is_file():
        return False
    if any(part in EXCLUDE_PARTS for part in p.parts):
        return False
    if p.suffix.lower() == ".zip":
        return False
    if p.suffix.lower() == ".sql" and "aircraft_flight" in p.name:
        return False
    return True


def iter_files() -> list[Path]:
    files: set[Path] = set()
    for d in INCLUDE_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if _ok(p):
                files.add(p)
    for rel in INCLUDE_FILES:
        p = ROOT / rel
        if _ok(p):
            files.add(p)
    return sorted(files, key=lambda x: x.as_posix())


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        return f"(git unavailable: {exc})\n"


def main() -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    files = iter_files()
    sha_lines = []
    for p in files:
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        sha_lines.append(f"{h}  {p.relative_to(ROOT).as_posix()}")
    (REPORT / "source_sha256.txt").write_text("\n".join(sha_lines) + "\n", encoding="utf-8")

    # Prefer host-injected git_status if present; else try git
    status = _git("status", "-sb")
    branch = _git("branch", "--show-current").strip()
    head = _git("rev-parse", "HEAD").strip()
    tag = _git("rev-list", "-n", "1", "task-002-fusion-validation-workbench-v1").strip()
    git_txt = REPORT / "git_status.txt"
    if "(git unavailable" in head or not head or head.startswith("(git"):
        # leave existing host-written file if any
        if not git_txt.exists():
            git_txt.write_text(
                f"branch={branch}\nHEAD={head}\ntask-002-tag-peel={tag}\n\n{status}\n",
                encoding="utf-8",
            )
    else:
        git_txt.write_text(
            f"branch={branch}\nHEAD={head}\ntask-002-tag-peel={tag}\n\n{status}\n",
            encoding="utf-8",
        )

    # ensure meta files included
    for meta in ("source_sha256.txt", "git_status.txt", "bundle_sha256.txt"):
        mp = REPORT / meta
        if mp.exists():
            files = sorted(set(files) | {mp}, key=lambda x: x.as_posix())

    if OUT_ZIP.exists():
        OUT_ZIP.unlink()
    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, p.relative_to(ROOT).as_posix())

    digest = hashlib.sha256(OUT_ZIP.read_bytes()).hexdigest()
    (REPORT / "bundle_sha256.txt").write_text(f"{digest}  {OUT_ZIP.name}\n", encoding="utf-8")
    # append updated hash file into zip
    with zipfile.ZipFile(OUT_ZIP, "a", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(REPORT / "bundle_sha256.txt", "reports/task003/bundle_sha256.txt")
    digest = hashlib.sha256(OUT_ZIP.read_bytes()).hexdigest()
    (REPORT / "bundle_sha256.txt").write_text(f"{digest}  {OUT_ZIP.name}\n", encoding="utf-8")
    print(OUT_ZIP)
    print("sha256", digest)
    print("files", len(files))


if __name__ == "__main__":
    main()
