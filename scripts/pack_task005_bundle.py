"""Pack TASK-005 review bundle. External SHA only."""
from __future__ import annotations

import hashlib
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_ZIP = ROOT / "TASK-005-attempt-001-review-bundle.zip"
REPORT = ROOT / "reports" / "task005"

INCLUDE_DIRS = [
    "src/fusion_mvp/workbench",
    "demo/workbench",
    "docs/task005",
    "scenarios",
    "tests",
    "reports/task005",
    "config",
]
INCLUDE_FILES = [
    "src/fusion_mvp/api.py",
    "src/fusion_mvp/engine.py",
    "src/fusion_mvp/kalman.py",
    "src/fusion_mvp/mapping.py",
    "src/fusion_mvp/models.py",
    "requirements.txt",
    "pytest.ini",
    "docker-compose.yml",
    "README.md",
    "package.json",
    "scripts/run_task005_challenge_matrix.py",
    "scripts/browser_workbench_task005.mjs",
    "scripts/pack_task005_bundle.py",
    "review_zip/TASK-005_高难场景与可解释验证台_执行要求.md",
]
EXCLUDE_NAMES = {"aircraft_flight_data.sql", "bundle_sha256.txt", "source_sha256.txt", "git_status.txt"}
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", "node_modules", ".git"}


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
        if _ok(p):
            files.add(p)

    def _git(*a: str) -> str:
        try:
            return subprocess.check_output(["git", *a], cwd=ROOT, text=True)
        except Exception as exc:  # noqa: BLE001
            return f"(git unavailable: {exc})\n"

    git_status = REPORT / "git_status.txt"
    git_status.write_text(
        "branch=" + _git("branch", "--show-current").strip()
        + "\nHEAD=" + _git("rev-parse", "HEAD").strip()
        + "\n" + _git("status", "-sb") + "\n",
        encoding="utf-8",
    )

    sha_lines = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(ROOT).as_posix()}"
        for p in sorted(files, key=lambda x: x.as_posix())
    ]
    manifest = REPORT / "source_sha256.txt"
    manifest.write_text("\n".join(sha_lines) + "\n", encoding="utf-8")
    bad = []
    for line in sha_lines:
        d, rel = line.split("  ", 1)
        if hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() != d:
            bad.append(rel)
    if bad:
        raise SystemExit("manifest mismatch: " + ", ".join(bad))

    if OUT_ZIP.exists():
        OUT_ZIP.unlink()
    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(files | {manifest, git_status}, key=lambda x: x.as_posix()):
            zf.write(p, p.relative_to(ROOT).as_posix())
    digest = hashlib.sha256(OUT_ZIP.read_bytes()).hexdigest()
    (REPORT / "bundle_sha256.txt").write_text(
        f"{digest}  {OUT_ZIP.name}\n# external hash only\n", encoding="utf-8"
    )
    print(OUT_ZIP)
    print("sha256", digest)
    print("files", len(sha_lines))


if __name__ == "__main__":
    main()
