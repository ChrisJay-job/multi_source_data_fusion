"""Pack TASK-003 Round6 review bundle. Final SHA external only."""
from __future__ import annotations

import hashlib
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_ZIP = ROOT / "TASK-003-attempt-001-rework-round6-review-bundle.zip"
REPORT = ROOT / "reports" / "task003_rework_round6"

INCLUDE_DIRS = [
    "src",
    "tests",
    "demo/workbench",
    "scenarios",
    "samples/workbench",
    "config",
    "docs/interface",
    "reports/task003_rework_round6",
    "reports/task003_rework_round5",
    "reports/task003_rework_round4",
]
INCLUDE_FILES = [
    "requirements.txt",
    "pytest.ini",
    "docker-compose.yml",
    "package.json",
    "README.md",
    ".gitignore",
    "review_zip/TASK-003_attempt-001_REWORK_Round6.md",
    "review_zip/TASK003_REWORK_Round6/TASK-003_attempt-001_REWORK_Round6.md",
    "review_zip/TASK003_REWORK_Round6/test_partial_outage_sources_round6.py",
    "review_zip/TASK003_REWORK_Round6/independent_verification.json",
    "review_zip/TASK003_REWORK_Round6/normal_partial_outage.json",
    "review_zip/TASK003_REWORK_Round6/counterexamples.log",
    "scripts/pack_task003_rework_round6_bundle.py",
]
EXCLUDE = {"__pycache__", ".pytest_cache", "node_modules", ".git", "uploads"}


def _ok(p: Path) -> bool:
    if not p.is_file():
        return False
    if any(x in EXCLUDE for x in p.parts):
        return False
    if p.suffix.lower() == ".zip" or p.name == "bundle_sha256.txt":
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
        f"HEAD={_git('rev-parse', 'HEAD').strip()}\n\n{_git('status', '-sb')}\n",
        encoding="utf-8",
    )
    files.add(REPORT / "git_status.txt")
    sha_lines = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(ROOT).as_posix()}"
        for p in sorted(files, key=lambda x: x.as_posix())
    ]
    (REPORT / "source_sha256.txt").write_text("\n".join(sha_lines) + "\n", encoding="utf-8")
    files.add(REPORT / "source_sha256.txt")

    if OUT_ZIP.exists():
        OUT_ZIP.unlink()
    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        seen: set[str] = set()
        for p in sorted(files, key=lambda x: x.as_posix()):
            name = p.relative_to(ROOT).as_posix()
            if name in seen:
                continue
            seen.add(name)
            zf.write(p, name)
    digest = hashlib.sha256(OUT_ZIP.read_bytes()).hexdigest()
    (REPORT / "bundle_sha256.txt").write_text(
        f"{digest}  {OUT_ZIP.name}\n# external hash only; not embedded inside the zip\n",
        encoding="utf-8",
    )
    print(OUT_ZIP)
    print("sha256", digest)
    print("files", len(seen))


if __name__ == "__main__":
    main()
