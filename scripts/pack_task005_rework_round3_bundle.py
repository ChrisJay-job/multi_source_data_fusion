"""Pack TASK-005 attempt-001 rework round3 review bundle. External SHA only."""
from __future__ import annotations

import hashlib
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_ZIP = ROOT / "TASK-005-attempt-001-rework-round3-review-bundle.zip"
REPORT = ROOT / "reports" / "task005_rework_round3"

INCLUDE_DIRS = [
    "src",
    "tests",
    "demo/workbench",
    "scenarios",
    "samples/workbench",
    "config",
    "docs/task005",
    "reports/task005_rework_round3",
    "reports/task005_rework_round2",
    "reports/task005_rework_round1",
    "reports/task005",
]
INCLUDE_FILES = [
    "requirements.txt",
    "pytest.ini",
    "docker-compose.yml",
    "package.json",
    "README.md",
    ".gitignore",
    "scripts/run_task005_challenge_matrix.py",
    "scripts/browser_workbench_task005.mjs",
    "scripts/browser_workbench_task005_r2.mjs",
    "scripts/browser_workbench_task005_r3.mjs",
    "scripts/pack_task005_rework_round3_bundle.py",
    "scripts/pack_task005_rework_round2_bundle.py",
    "scripts/pack_task005_rework_round1_bundle.py",
    "scripts/pack_task005_bundle.py",
    "scripts/_verify_clean_bundle_task005_r3.sh",
    "review_zip/TASK-005_高难场景与可解释验证台_执行要求.md",
    "review_zip/TASK005_REWORK_Round3/TASK-005_attempt-001_REWORK_Round3_ID指标收尾.md",
]
EXCLUDE_NAMES = {
    "aircraft_flight_data.sql",
    "bundle_sha256.txt",
    "source_sha256.txt",
    "git_status.txt",
}
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", "node_modules", ".git", "uploads"}


def _ok(p: Path) -> bool:
    if not p.is_file():
        return False
    if any(x in EXCLUDE_PARTS for x in p.parts):
        return False
    if p.name in EXCLUDE_NAMES or p.suffix.lower() == ".zip":
        return False
    if p.stat().st_size > 40 * 1024 * 1024:
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
        if p.is_file() and p.stat().st_size <= 40 * 1024 * 1024:
            if any(x in EXCLUDE_PARTS for x in p.parts):
                continue
            files.add(p)

    def _git(*a: str) -> str:
        try:
            return subprocess.check_output(["git", *a], cwd=ROOT, text=True)
        except Exception as exc:  # noqa: BLE001
            return f"(git unavailable: {exc})\n"

    git_status = REPORT / "git_status.txt"
    git_status.write_text(
        "branch="
        + _git("branch", "--show-current").strip()
        + "\nHEAD="
        + _git("rev-parse", "HEAD").strip()
        + "\n"
        + _git("status", "-sb")
        + "\n",
        encoding="utf-8",
    )

    hashable = {p for p in files if p.name not in EXCLUDE_NAMES}
    sha_lines = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(ROOT).as_posix()}"
        for p in sorted(hashable, key=lambda x: x.as_posix())
    ]
    manifest = REPORT / "source_sha256.txt"
    manifest.write_text("\n".join(sha_lines) + "\n", encoding="utf-8")

    if OUT_ZIP.exists():
        OUT_ZIP.unlink()
    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(hashable | {manifest, git_status}, key=lambda x: x.as_posix()):
            zf.write(p, p.relative_to(ROOT).as_posix())
    digest = hashlib.sha256(OUT_ZIP.read_bytes()).hexdigest()
    (REPORT / "bundle_sha256.txt").write_text(
        f"{digest}  {OUT_ZIP.name}\n# external hash only; not inside zip\n", encoding="utf-8"
    )
    print(OUT_ZIP)
    print("sha256", digest)
    print("files", len(sha_lines))


if __name__ == "__main__":
    main()
