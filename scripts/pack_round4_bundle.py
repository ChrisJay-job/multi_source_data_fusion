"""Build TASK-001 Round4 review bundle zip."""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "TASK-001-attempt-001-rework-round4-review-bundle.zip"
HASH_OUT = ROOT / "reports" / "rework_round4" / "source_sha256.txt"

INCLUDE_DIRS = [
    "src",
    "tests",
    "config",
    "scripts",
    "samples",
    "docs",
    "prompt",
    "demo",
    "reports/rework_round1",
    "reports/rework_round2",
    "reports/rework_round3",
    "reports/rework_round4",
    "review_zip/REWORK_Round4",
    ".task/chriswork400/completed/20261017-task001_rework_round4",
]
INCLUDE_FILES = [
    "requirements.txt",
    "README.md",
    "flow2spec.config.json",
    "pytest.ini",
    "docker-compose.yml",
]
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".git"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
SKIP_NAMES = {
    "aircraft_flight_data.sql",
    "bundle_sha256.txt",
    "bundle_verify.txt",
    "_env_probe.py",
    "_verify_round2_zip.py",
    "_verify_round3_zip.py",
    "_finalize_round2_hash.py",
    "_finalize_round3_hash.py",
    "_finalize_round4_hash.py",
}


def should_skip(path: Path) -> bool:
    if any(p in SKIP_PARTS for p in path.parts):
        return True
    if path.suffix in SKIP_SUFFIXES or path.name in SKIP_NAMES:
        return True
    if path.name.endswith(".sql") and path.stat().st_size > 10_000_000:
        return True
    return False


def collect() -> list[Path]:
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
    seen: set[Path] = set()
    out: list[Path] = []
    for p in files:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def main() -> None:
    files = collect()
    lines = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {str(p.relative_to(ROOT)).replace(chr(92), '/')}"
        for p in sorted(files, key=lambda x: str(x.relative_to(ROOT)).replace("\\", "/"))
    ]
    HASH_OUT.parent.mkdir(parents=True, exist_ok=True)
    HASH_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if HASH_OUT not in files:
        files.append(HASH_OUT)
    if OUT.exists():
        OUT.unlink()
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, arcname=str(p.relative_to(ROOT)).replace("\\", "/"))
        zf.writestr(
            "BUNDLE_MANIFEST.txt",
            "\n".join(
                [
                    "TASK-001 attempt-001 REWORK Round4 Event Frontier review bundle",
                    f"files={len(files)}",
                    "status=REVIEW_READY",
                    "exclude=data/*.sql __pycache__ .git",
                ]
            )
            + "\n",
        )
    print(OUT)
    print("bytes", OUT.stat().st_size)
    print("files", len(files))


if __name__ == "__main__":
    main()
