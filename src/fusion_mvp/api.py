from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .engine import SessionStore, load_config
from .models import ProcessRequest, ProcessResponse

CFG = load_config()
STORE = SessionStore(CFG)
ROOT = Path(__file__).resolve().parents[2]

app = FastAPI(title="三源融合 MVP", version=CFG["algorithmVersion"])
demo_dir = ROOT / "demo"
if demo_dir.exists():
    app.mount("/demo-static", StaticFiles(directory=str(demo_dir)), name="demo-static")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    required = ["algorithmVersion", "configVersion", "reorder_window_s", "gates", "lifecycle", "kalman"]
    missing = [k for k in required if k not in CFG]
    if missing:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "missing": missing})
    return {
        "status": "ready",
        "sessions": len(STORE.sessions),
        "algorithmVersion": CFG["algorithmVersion"],
        "configVersion": CFG["configVersion"],
        "stateOwner": "single-process-SessionStore",
    }


@app.post("/v1/fusion/process", response_model=ProcessResponse)
def process(req: ProcessRequest):
    sess = STORE.get(req.sessionId)
    resp = sess.process(req.batchId, req.processingTime, req.observations, req.mode)
    if resp.error in {
        "batch_id_conflict",
        "session_mode_conflict",
        "idempotency_expired",
        "idempotency_evicted",
        "observation_id_conflict",
    }:
        raise HTTPException(status_code=409, detail=resp.model_dump())
    if resp.error == "batch_rollback":
        raise HTTPException(status_code=500, detail=resp.model_dump())
    if resp.error in {"invalid_processing_time", "processing_time_not_monotonic"}:
        raise HTTPException(status_code=400, detail=resp.model_dump())
    return resp


@app.post("/v1/fusion/reset/{session_id}")
def reset(session_id: str):
    STORE.drop(session_id)
    return {"dropped": session_id}


@app.get("/")
def index():
    page = ROOT / "demo" / "index.html"
    if page.exists():
        return FileResponse(page)
    return JSONResponse({"service": "fusion-mvp"})
