"""Build TASK-001 Round2 review bundle zip."""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "TASK-001-attempt-001-rework-round2-review-bundle.zip"
HASH_OUT = ROOT / "reports" / "rework_round2" / "source_sha256.txt"

INCLUDE_DIRS = [
    "src",
    "tests",
    "config",
    "scripts",
    "samples",
    "docs",
    "prompt",
    "reports/rework_round1",
    "reports/rework_round2",
    "review_zip/REWORK_Round2",
    ".task/chriswork400/completed/20261017-task001_rework_round2",
]
INCLUDE_FILES = [
    "requirements.txt",
    "README.md",
    "flow2spec.config.json",
]
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".git"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
SKIP_NAMES = {
    "_env_probe.py",
    "_verify_round2_zip.py",
    "aircraft_flight_data.sql",
    "bundle_sha256.txt",
    "bundle_verify.txt",
}


def should_skip(path: Path) -> bool:
    if any(p in SKIP_PARTS for p in path.parts):
        return True
    if path.suffix in SKIP_SUFFIXES:
        return True
    if path.name in SKIP_NAMES:
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
    # dedupe preserve order
    seen = set()
    out = []
    for p in files:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def main() -> None:
    files = collect()
    lines = []
    for p in sorted(files, key=lambda x: str(x.relative_to(ROOT)).replace("\\", "/")):
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        lines.append(f"{h}  {rel}")
    HASH_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if HASH_OUT not in files:
        files.append(HASH_OUT)

    if OUT.exists():
        OUT.unlink()
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            arc = str(p.relative_to(ROOT)).replace("\\", "/")
            zf.write(p, arcname=arc)
        # bundle manifest
        manifest = [
            "TASK-001 attempt-001 REWORK Round2 review bundle",
            f"files={len(files)}",
            "status=REVIEW_READY",
            "exclude=data/*.sql __pycache__ .git",
        ]
        zf.writestr("BUNDLE_MANIFEST.txt", "\n".join(manifest) + "\n")
    print(OUT)
    print("bytes", OUT.stat().st_size)
    print("files", len(files))


if __name__ == "__main__":
    main()
