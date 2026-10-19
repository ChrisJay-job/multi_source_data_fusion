from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional  # noqa: F401 — Optional used by path helpers
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .engine import SessionStore, load_config
from .models import ProcessRequest, ProcessResponse
from .workbench.importer import MappingTemplate, ObsFilter, import_sql_stream, import_tabular, page_observations
from .workbench.runner import WorkbenchRunner
from .workbench.scenario import (
    generate_observations,
    get_preset,
    list_preset_names,
    load_scenario,
    PRESET_BUILDERS,
    save_scenario,
    scenario_from_dict,
)

CFG = load_config()
STORE = SessionStore(CFG)
RUNNER = WorkbenchRunner(CFG)
ROOT = Path(__file__).resolve().parents[2]
UPLOAD_DIR = ROOT / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
SCENARIO_DIR = ROOT / "scenarios"
SCENARIO_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="多源轨迹融合验证台", version=CFG["algorithmVersion"])

demo_dir = ROOT / "demo"
if demo_dir.exists():
    app.mount("/demo-static", StaticFiles(directory=str(demo_dir)), name="demo-static")
wb_dir = ROOT / "demo" / "workbench"
if wb_dir.exists():
    app.mount("/workbench-static", StaticFiles(directory=str(wb_dir)), name="workbench-static")


class ScenarioRunRequest(BaseModel):
    scenarioName: str = "three_aircraft_primary"
    mode: str = "realtime"
    seed: Optional[int] = None
    scenario: Optional[dict[str, Any]] = None  # editor body; overrides name when present


class ScenarioSaveRequest(BaseModel):
    name: str
    scenario: dict[str, Any]


class ImportRunRequest(BaseModel):
    path: str
    mode: str = "replay"
    mapping: dict[str, Any] = Field(default_factory=dict)
    maxRows: Optional[int] = 5000
    timeFrom: Optional[str] = None
    timeTo: Optional[str] = None
    detectorId: Optional[str] = None
    lonMin: Optional[float] = None
    lonMax: Optional[float] = None
    latMin: Optional[float] = None
    latMax: Optional[float] = None
    truncated: bool = False  # client acknowledges maxRows is a sample/window


class MultiImportRunRequest(BaseModel):
    """Combine RID/spectrum/radar files into one replay clock."""
    files: list[dict[str, Any]]  # [{path, mapping?, source?, maxRows?, detectorId?, ...}]
    mode: str = "replay"
    timeFrom: Optional[str] = None
    timeTo: Optional[str] = None
    detectorId: Optional[str] = None
    lonMin: Optional[float] = None
    lonMax: Optional[float] = None
    latMin: Optional[float] = None
    latMax: Optional[float] = None


class MappingSaveRequest(BaseModel):
    name: str
    mapping: dict[str, Any]


def _resolve_scenario(name: str, body: Optional[dict] = None, seed: Optional[int] = None):
    if body:
        sc = scenario_from_dict(body)
    elif name in PRESET_BUILDERS:
        sc = get_preset(name)
    else:
        path = SCENARIO_DIR / f"{name}.json"
        if not path.exists():
            raise HTTPException(404, detail="scenario_not_found")
        sc = load_scenario(path)
    if seed is not None:
        sc.seed = seed
    return sc


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


@app.get("/v1/workbench/scenarios")
def list_scenarios():
    items = list_preset_names()
    for p in sorted(SCENARIO_DIR.glob("*.json")):
        if not any(i["name"] == p.stem for i in items):
            items.append({"name": p.stem, "notes": "(saved file)", "path": str(p.relative_to(ROOT))})
    return {"scenarios": items}


@app.get("/v1/workbench/scenarios/{name}")
def get_scenario(name: str):
    try:
        return _resolve_scenario(name).to_dict()
    except HTTPException:
        raise
    except KeyError:
        raise HTTPException(404, detail="scenario_not_found")


@app.post("/v1/workbench/scenarios/save")
def save_scenario_api(req: ScenarioSaveRequest):
    safe = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in req.name)[:64]
    sc = scenario_from_dict(req.scenario)
    sc.name = safe
    path = SCENARIO_DIR / f"{safe}.json"
    save_scenario(sc, path)
    return {"ok": True, "name": safe, "path": str(path.relative_to(ROOT))}


@app.post("/v1/workbench/scenarios/{name}/generate")
def generate_scenario(name: str, seed: Optional[int] = None):
    sc = _resolve_scenario(name, seed=seed)
    bundle = generate_observations(sc)
    if name in PRESET_BUILDERS:
        save_scenario(sc, SCENARIO_DIR / f"{name}.json")
    return {
        "scenario": bundle["scenario"],
        "observations": bundle["observations"],
        "truth_polyline": bundle["truth_polyline"],
        "truth_timeline": bundle["truth_timeline"],
        "obs_truth_map": bundle["obs_truth_map"],
        "t0": bundle["t0"],
        "warning": "truth_* 与 obs_truth_map 仅用于显示／评估，禁止并入 /v1/fusion/process",
    }


@app.post("/v1/workbench/run/scenario")
def run_scenario(req: ScenarioRunRequest):
    sc = _resolve_scenario(req.scenarioName, body=req.scenario, seed=req.seed)
    bundle = generate_observations(sc)
    result = RUNNER.run_scenario_bundle(bundle, mode=req.mode)
    result["truth_polyline"] = bundle["truth_polyline"]
    result["truth_timeline"] = bundle["truth_timeline"]
    result["t0"] = bundle["t0"]
    result["scenario"] = bundle["scenario"]
    result["observations"] = bundle["observations"]
    result["obs_truth_map"] = bundle["obs_truth_map"]
    return result


def _safe_upload_name(filename: str | None) -> str:
    base = Path(filename or "upload.bin").name
    base = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in base)[:80]
    return f"{uuid4().hex}_{base}"


def _resolve_data_path(rel_or_id: str) -> Path:
    """Only allow uploads/ or data/ relative paths; reject absolute and .. traversal."""
    raw = Path(rel_or_id)
    if raw.is_absolute() or ".." in raw.parts:
        raise HTTPException(400, detail="path_not_allowed")
    cand = (ROOT / rel_or_id).resolve()
    allowed = [(UPLOAD_DIR.resolve()), (ROOT / "data").resolve(), (ROOT / "samples").resolve()]
    if not any(str(cand).startswith(str(a)) for a in allowed):
        raise HTTPException(400, detail="path_outside_sandbox")
    if not cand.exists():
        raise HTTPException(404, detail="file_not_found")
    return cand


def _default_mapping(raw_map: dict) -> MappingTemplate:
    """
    Page default mapping for real SQL/Navicat dumps.
    Standard CSV with measurementTime/sourceTrackId/detectorId still works via
    import_sql_stream/import_tabular schema candidates + row fallbacks.
    """
    # SQL-first candidates (Round2 page path); explicit field_map overrides win
    base = {
        "observationId": "observationId",
        "source": "source",
        "sourceTrackId": "id",
        "aircraftId": "aircraftId",
        "measurementTime": "created_at",
        "longitude": "longitude",
        "latitude": "latitude",
        "altitude": "altitude",
        "detectorId": "detector",
        "speed": "speed",
        "heading": "heading",
        "verticalSpeed": "verticalSpeed",
        "altitudeDatum": "altitudeDatum",
        "receivedAt": "receivedAt",
        "created_at": "created_at",
        "id": "id",
    }
    fm = dict(base)
    fm.update((raw_map or {}).get("field_map") or {})
    return MappingTemplate(
        field_map=fm,
        assume_utc_naive=bool((raw_map or {}).get("assume_utc_naive")),
        source_timezone=(raw_map or {}).get("source_timezone"),
        treat_raw_id_as_aircraftId=bool((raw_map or {}).get("treat_raw_id_as_aircraftId")),
        detectorId=(raw_map or {}).get("detectorId"),
        time_unit=(raw_map or {}).get("time_unit") or "auto",
    )


def _filt_from_args(
    *,
    time_from: Optional[str] = None,
    time_to: Optional[str] = None,
    detector_id: Optional[str] = None,
    lon_min: Optional[float] = None,
    lon_max: Optional[float] = None,
    lat_min: Optional[float] = None,
    lat_max: Optional[float] = None,
) -> ObsFilter:
    return ObsFilter(
        time_from=time_from,
        time_to=time_to,
        detector_id=detector_id,
        lon_min=lon_min,
        lon_max=lon_max,
        lat_min=lat_min,
        lat_max=lat_max,
    )


def _load_observations(
    path: Path,
    tmpl: MappingTemplate,
    max_rows: Optional[int],
    *,
    time_from: Optional[str] = None,
    time_to: Optional[str] = None,
    detector_id: Optional[str] = None,
    lon_min: Optional[float] = None,
    lon_max: Optional[float] = None,
    lat_min: Optional[float] = None,
    lat_max: Optional[float] = None,
    filt: Optional[ObsFilter] = None,
) -> dict:
    """Load observations; all filters applied while scanning so max_rows counts accepted rows."""
    f = filt or _filt_from_args(
        time_from=time_from,
        time_to=time_to,
        detector_id=detector_id,
        lon_min=lon_min,
        lon_max=lon_max,
        lat_min=lat_min,
        lat_max=lat_max,
    )
    if path.suffix.lower() == ".sql":
        return import_sql_stream(path, tmpl, max_rows=max_rows, filt=f)
    return import_tabular(path, tmpl, max_rows=max_rows, filt=f)


@app.post("/v1/workbench/import/preview")
async def import_preview(
    file: UploadFile = File(...),
    mapping_json: str = Form("{}"),
    max_rows: int = Form(2000),
):
    """Preview only — stores original upload; does not define the formal replay dataset."""
    raw_map = json.loads(mapping_json or "{}")
    tmpl = _default_mapping(raw_map)
    dest = UPLOAD_DIR / _safe_upload_name(file.filename)
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    meta = {
        "file": str(dest.relative_to(ROOT)),
        "mapping_fp": tmpl.fingerprint(),
        "mapping": tmpl.to_dict(),
        "preview_max_rows": max_rows,
    }
    (dest.with_suffix(dest.suffix + ".meta.json")).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    summary = _load_observations(dest, tmpl, max_rows=max_rows)
    obs = summary.pop("observations", [])
    summary["n_observations"] = len(obs)
    summary["stored_as"] = meta["file"]
    summary["datasetId"] = dest.name
    summary["preview_only"] = True
    summary["preview"] = obs[:5]
    summary["mapping_fp"] = meta["mapping_fp"]
    # do NOT write .obs.json as authoritative dataset
    return summary


def _parse_obs_time(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _filter_obs_window(observations: list[dict], time_from: Optional[str], time_to: Optional[str]) -> list[dict]:
    """Filter by parsed instants (not raw RFC3339 string order)."""
    if not time_from and not time_to:
        return observations
    tf = _parse_obs_time(time_from)
    tt = _parse_obs_time(time_to)
    out = []
    for o in observations:
        t = _parse_obs_time(o.get("measurementTime"))
        if t is None:
            continue
        if tf and t < tf:
            continue
        if tt and t > tt:
            continue
        out.append(o)
    return out


@app.post("/v1/workbench/run/import")
def run_import(req: ImportRunRequest):
    """Formal replay: re-parse original file with request maxRows + mapping (ignore preview cache)."""
    path = _resolve_data_path(req.path)
    tmpl = _default_mapping(req.mapping or {})
    filt = _filt_from_args(
        time_from=req.timeFrom,
        time_to=req.timeTo,
        detector_id=req.detectorId,
        lon_min=req.lonMin,
        lon_max=req.lonMax,
        lat_min=req.latMin,
        lat_max=req.latMax,
    )
    # Filters while scanning; maxRows counts accepted-after-filter rows
    summary = _load_observations(path, tmpl, max_rows=req.maxRows, filt=filt)
    if not summary.get("ok", True) and summary.get("n_observations", 0) == 0:
        raise HTTPException(400, detail=summary)
    observations = summary.get("observations") or []
    if not observations:
        raise HTTPException(400, detail={"error": "no_valid_observations", "summary": summary})
    result = RUNNER.run_batch_replay(observations, mode=req.mode, batch_size=25)
    result["n_observations"] = len(observations)
    result["observations"] = observations
    result["import_summary"] = {
        "by_source": summary.get("by_source"),
        "n_errors": summary.get("n_errors"),
        "errors_sample": summary.get("errors_sample"),
        "mapping_fp": tmpl.fingerprint(),
        "preview_only": False,
        "maxRows": req.maxRows,
        "filters": filt.to_dict(),
        "scanned": summary.get("scanned_rows") or summary.get("scanned_inserts"),
        "skipped_outside_window": summary.get("skipped_outside_window"),
        "truncated": summary.get("truncated"),
        "window_note": "先按时间/设备/区域筛选，再累计 maxRows；maxRows 为命中上限，非完整文件保证",
        "field_map_applied": summary.get("field_map_applied"),
    }
    result["accuracy_note"] = "真实文件默认无真值，不显示虚假关联准确率"
    return result


@app.post("/v1/workbench/run/import/multi")
def run_import_multi(req: MultiImportRunRequest):
    """Merge multiple sandboxed files into one replay dataset (namespaced obs ids)."""
    if not req.files:
        raise HTTPException(400, detail="files_required")
    all_obs: list[dict] = []
    parts = []
    global_filt = _filt_from_args(
        time_from=req.timeFrom,
        time_to=req.timeTo,
        detector_id=req.detectorId,
        lon_min=req.lonMin,
        lon_max=req.lonMax,
        lat_min=req.latMin,
        lat_max=req.latMax,
    )
    for i, item in enumerate(req.files):
        path = _resolve_data_path(item["path"])
        tmpl = _default_mapping(item.get("mapping") or {})
        if item.get("source"):
            tmpl.source = item["source"]
        max_rows = item.get("maxRows", 5000)
        filt = _filt_from_args(
            time_from=item.get("timeFrom", req.timeFrom),
            time_to=item.get("timeTo", req.timeTo),
            detector_id=item.get("detectorId", req.detectorId),
            lon_min=item.get("lonMin", req.lonMin),
            lon_max=item.get("lonMax", req.lonMax),
            lat_min=item.get("latMin", req.latMin),
            lat_max=item.get("latMax", req.latMax),
        )
        summary = _load_observations(path, tmpl, max_rows=max_rows, filt=filt)
        obs = summary.get("observations") or []
        if item.get("source"):
            for o in obs:
                o["source"] = item["source"]
        # reinforce file namespace
        stem = path.stem[:20]
        for o in obs:
            oid = str(o.get("observationId") or f"row-{i}")
            if not oid.startswith(stem):
                o["observationId"] = f"{stem}-{oid}"
        all_obs.extend(obs)
        parts.append(
            {
                "path": item["path"],
                "n": len(obs),
                "n_errors": summary.get("n_errors"),
                "by_source": summary.get("by_source"),
                "ok": summary.get("ok", True),
                "scanned": summary.get("scanned_rows") or summary.get("scanned_inserts"),
                "skipped_outside_window": summary.get("skipped_outside_window"),
                "truncated": summary.get("truncated"),
                "filters": filt.to_dict(),
            }
        )
    all_obs.sort(key=lambda o: (o.get("measurementTime") or "", o.get("observationId") or ""))
    if not all_obs:
        raise HTTPException(400, detail={"error": "no_valid_observations", "parts": parts})
    result = RUNNER.run_batch_replay(all_obs, mode=req.mode, batch_size=25)
    result["n_observations"] = len(all_obs)
    result["observations"] = all_obs
    result["import_summary"] = {
        "parts": parts,
        "preview_only": False,
        "combined": True,
        "filters": global_filt.to_dict(),
    }
    result["accuracy_note"] = "多文件合成回放无真值准确率"
    return result


@app.get("/v1/workbench/mapping/default")
def mapping_default():
    tmpl = _default_mapping({"source_timezone": "Asia/Shanghai"})
    return {"mapping": tmpl.to_dict(), "candidates": {
        "measurementTime": ["created_at", "measurementTime", "source_data.trackTime"],
        "sourceTrackId": ["id", "sourceTrackId"],
        "detectorId": ["detector", "source_data.deviceId", "detectorId"],
        "source": ["source"],
        "longitude": ["longitude"],
        "latitude": ["latitude"],
        "altitude": ["altitude"],
        "aircraftId": ["aircraftId"],
        "receivedAt": ["receivedAt"],
    }, "note": "候选≠厂家已确认；aerial_sn/tcp 不作 SN"}


@app.post("/v1/workbench/mapping/save")
def mapping_save(req: MappingSaveRequest):
    safe = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in req.name)[:64]
    dest = ROOT / "scenarios" / "mappings"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{safe}.json"
    path.write_text(json.dumps(req.mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "name": safe, "path": str(path.relative_to(ROOT))}


@app.get("/v1/workbench/mapping/list")
def mapping_list():
    dest = ROOT / "scenarios" / "mappings"
    items = []
    if dest.exists():
        for p in sorted(dest.glob("*.json")):
            items.append({"name": p.stem, "path": str(p.relative_to(ROOT))})
    return {"mappings": items}


@app.get("/v1/workbench/mapping/{name}")
def mapping_get(name: str):
    safe = Path(name).name
    path = ROOT / "scenarios" / "mappings" / f"{safe}.json"
    if not path.exists():
        raise HTTPException(404, detail="mapping_not_found")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/v1/workbench/datasets/{dataset_id}/observations")
def dataset_observations(
    dataset_id: str,
    offset: int = 0,
    limit: int = 50,
    timeFrom: Optional[str] = None,
    timeTo: Optional[str] = None,
    detectorId: Optional[str] = None,
    lonMin: Optional[float] = None,
    lonMax: Optional[float] = None,
    latMin: Optional[float] = None,
    latMax: Optional[float] = None,
    path: Optional[str] = None,
):
    """
    Bounded page read via streaming iterator:
    normalize → filter (time/device/region) → skip offset hits → retain ≤limit (+hasMore peek).
    Does not call _load_observations (avoids materializing skipped prefix).
    """
    if offset < 0 or limit <= 0:
        raise HTTPException(400, detail={"error": "invalid_pagination", "offset": offset, "limit": limit})
    limit = min(int(limit), 2000)
    # Prefer explicit sandbox path (local data/); else uploads/<dataset_id>
    if path:
        file_path = _resolve_data_path(path)
        dataset_label = path
    else:
        safe = Path(dataset_id).name
        file_path = UPLOAD_DIR / safe
        dataset_label = safe
        if not file_path.exists():
            try:
                file_path = _resolve_data_path(dataset_id)
                dataset_label = dataset_id
            except HTTPException:
                raise HTTPException(404, detail="dataset_not_found") from None
            if not file_path.exists():
                raise HTTPException(404, detail="dataset_not_found")
    meta_path = file_path.with_suffix(file_path.suffix + ".meta.json")
    raw_map = {}
    if meta_path.exists():
        raw_map = json.loads(meta_path.read_text(encoding="utf-8")).get("mapping") or {}
    tmpl = _default_mapping(raw_map)
    filt = _filt_from_args(
        time_from=timeFrom,
        time_to=timeTo,
        detector_id=detectorId,
        lon_min=lonMin,
        lon_max=lonMax,
        lat_min=latMin,
        lat_max=latMax,
    )
    page = page_observations(file_path, tmpl, offset=offset, limit=limit, filt=filt)
    if not page.get("ok", True):
        raise HTTPException(400, detail=page)
    return {
        "datasetId": dataset_label,
        "path": str(file_path.relative_to(ROOT)).replace("\\", "/") if str(file_path).startswith(str(ROOT)) else dataset_label,
        "offset": page["offset"],
        "limit": page["limit"],
        "n": page["n"],
        "accepted": page.get("matched_so_far"),
        "scanned": page.get("scanned"),
        "skipped_filter": page.get("skipped_filter"),
        "skipped_offset": page.get("skipped_offset"),
        "has_more": page.get("has_more"),
        "next_offset": page.get("next_offset"),
        "materialized": page.get("materialized"),
        "truncated": page.get("truncated"),
        "filters": page.get("filters"),
        "observations": page.get("observations") or [],
        "n_errors": page.get("n_errors"),
        "errors_sample": page.get("errors_sample"),
    }


@app.get("/v1/workbench/local-data")
def list_local_data():
    """List files under data/ for local SQL selection (read-only)."""
    data = ROOT / "data"
    files = []
    if data.exists():
        for p in sorted(data.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix.lower() not in {".sql", ".csv", ".json", ".jsonl"}:
                continue
            name = p.name.lower()
            if name.endswith(".meta.json") or name.endswith(".obs.json"):
                continue
            files.append({"path": str(p.relative_to(ROOT)).replace("\\", "/"), "bytes": p.stat().st_size})
    return {"files": files, "note": "大 SQL 仅流式解析；选择 path 后走 /run/import（受限目录）；已过滤 .meta/.obs 缓存"}


@app.post("/v1/workbench/run/local")
def run_local(req: ImportRunRequest):
    """Run import from sandbox-relative data/ path."""
    return run_import(req)


@app.get("/")
def index():
    page = ROOT / "demo" / "workbench" / "index.html"
    if page.exists():
        return FileResponse(page)
    legacy = ROOT / "demo" / "index.html"
    if legacy.exists():
        return FileResponse(legacy)
    return JSONResponse({"service": "fusion-mvp"})


@app.get("/demo")
def legacy_demo():
    page = ROOT / "demo" / "index.html"
    if page.exists():
        return FileResponse(page)
    raise HTTPException(404)
