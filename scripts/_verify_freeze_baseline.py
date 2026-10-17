import hashlib
import zipfile
from pathlib import Path

ROOT = Path(".")
engine = (ROOT / "src/fusion_mvp/engine.py").read_bytes()
print("workdir_engine", hashlib.sha256(engine).hexdigest())
expected = "6ce03fa4e732a470be7be531d5b80fd99393a121960ad02d3e7ecdc68bedc5a9"
print("expected_engine", expected)
print("engine_match", hashlib.sha256(engine).hexdigest() == expected)

zpath = ROOT / "TASK-001-attempt-001-rework-round4-review-bundle.zip"
print("bundle_sha256", hashlib.sha256(zpath.read_bytes()).hexdigest())
print("bundle_expected", "29370c0243104075832efee751666a20594b81253568c820ef4a68208b0f5d12")
with zipfile.ZipFile(zpath) as z:
    be = z.read("src/fusion_mvp/engine.py")
print("bundle_engine", hashlib.sha256(be).hexdigest())
print("workdir_vs_bundle_engine", hashlib.sha256(engine).hexdigest() == hashlib.sha256(be).hexdigest())
