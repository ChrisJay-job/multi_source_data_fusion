import { MapView } from "./canvas.js";

const api = "";
const map = new MapView(document.getElementById("cv"));
let runState = null;
let playTimer = null;
let importMeta = null;
let draftScenario = null;

map.onPick = (obj, kind) => {
  if (kind === "track" || obj.fusionId) pinnedDetail = obj;
  document.getElementById("detail").textContent = JSON.stringify({ kind: kind || "track", ...obj }, null, 2);
  const rows = (obj.sourceTracks || []).map((s) =>
    `<div>${s.source} · ${s.sourceTrackId} · ${s.aircraftId || "-"} · ${s.bindingStatus || "?"}</div>`
  );
  if (kind === "obs") {
    document.getElementById("assoc").innerHTML =
      `<div>观测 ${obj.source} / ${obj.sourceTrackId} / ${obj.aircraftId || "-"}</div>`;
  } else {
    document.getElementById("assoc").innerHTML = rows.join("") || "无";
  }
};

function parseT(s) {
  if (!s) return 0;
  return Date.parse(String(s).replace("Z", "+00:00"));
}

function setStatus(ok, text) {
  const el = document.getElementById("svcStatus");
  el.textContent = text;
  el.style.background = ok ? "rgba(144,190,109,.25)" : "rgba(249,199,79,.25)";
}

document.getElementById("btnHealth").onclick = async () => {
  try {
    const r = await fetch(api + "/ready");
    const j = await r.json();
    setStatus(r.ok, r.ok ? `ready ${j.algorithmVersion}` : `HTTP ${r.status}`);
  } catch (e) {
    setStatus(false, String(e));
  }
};

document.querySelectorAll(".tab").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const mode = btn.dataset.mode;
    document.getElementById("simPanel").classList.toggle("hidden", mode !== "sim");
    document.getElementById("realPanel").classList.toggle("hidden", mode !== "real");
    if (mode === "real") loadLocalFiles();
  };
});

document.querySelectorAll(".layer").forEach((cb) => {
  cb.onchange = () => {
    const layers = {};
    document.querySelectorAll(".layer").forEach((c) => { layers[c.dataset.layer] = c.checked; });
    map.setLayers(layers);
  };
});

document.getElementById("btnResetView").onclick = () => map.resetView();

function rebuildTargetFilters(result) {
  const box = document.getElementById("targetFilters");
  const labels = new Set();
  for (const a of result.scenario?.aircraft || []) labels.add(a.label);
  for (const tid of Object.keys(result.truth_polyline || {})) labels.add(tid.replace("TRUTH-", ""));
  for (const tr of result.final_tracks || []) {
    if (tr.aircraftId) labels.add(tr.aircraftId);
    labels.add(tr.fusionId);
  }
  const arr = [...labels].filter(Boolean).sort();
  box.innerHTML = arr.map((id) =>
    `<label><input type="checkbox" class="tfilt" data-id="${id}" /> ${id}</label>`
  ).join("") || "<span class='hint'>运行后出现目标</span>";
  box.querySelectorAll(".tfilt").forEach((cb) => {
    cb.onchange = () => {
      const checked = [...box.querySelectorAll(".tfilt:checked")].map((c) => c.dataset.id);
      map.setTargetFilter(checked.length ? new Set(checked) : null);
    };
  });
}

let pinnedDetail = null; // keep selected target across time steps

function countsUpTo(tIndex) {
  const snap = runState?.snapshots?.[tIndex];
  const final = runState?.counts || {};
  // Prefer runner-recorded cumulative counts at this snapshot (no future foresight)
  if (snap?.counts_at) {
    const c = snap.counts_at;
    return {
      delivered_at_t: c.delivered ?? 0,
      binds_at_t: c.source_binds ?? 0,
      rejected_at_t: c.rejected ?? 0,
      pending_buffer: c.pending_buffer ?? final.pending_buffer,
      run_total_updates: final.processed_updates || final.processed_hits || 0,
      run_total_delivered: final.delivered || 0,
      atSnapshot: tIndex,
      source: "snapshot.counts_at",
    };
  }
  const now = parseT(snap?.processingTime);
  const ev = runState?.events || [];
  let binds = 0;
  // Rejected contract has no time — never count untimed rejects at early frames
  let rejects = (runState?.rejected || []).filter((r) => {
    const t = parseT(r.time || r.measurementTime || r.detail?.measurementTime);
    if (!t) return false;
    return t <= now + 1;
  }).length;
  for (const e of ev) {
    const t = parseT(e.time || e.eventTime);
    if (t && t > now + 1) continue;
    if (e.type === "source_bound") binds += 1;
  }
  const deliveredApprox = (runState?.observations || []).filter((o) => {
    const t = parseT(o.receivedAt || o.measurementTime);
    if (!t) return false;
    return t <= now + 1;
  }).length;
  return {
    delivered_at_t: deliveredApprox,
    binds_at_t: binds,
    rejected_at_t: rejects,
    pending_buffer: final.pending_buffer,
    run_total_updates: final.processed_updates || final.processed_hits || 0,
    run_total_delivered: final.delivered || 0,
    atSnapshot: tIndex,
    source: "fallback_timed_only",
  };
}

function updateTransport() {
  if (!runState?.snapshots) return;
  const seek = document.getElementById("seek");
  seek.max = String(Math.max(0, runState.snapshots.length - 1));
  seek.value = String(map.tIndex);
  document.getElementById("seekLabel").textContent = `${map.tIndex + 1}/${runState.snapshots.length}`;
  const snap = runState.snapshots[map.tIndex];
  document.getElementById("clock").textContent = `pt=${snap?.processingTime || "—"} wm=${snap?.watermark || "—"}`;
  const c = countsUpTo(map.tIndex);
  document.getElementById("counts").textContent =
    `当前投递${c.delivered_at_t}／绑定${c.binds_at_t}／拒绝${c.rejected_at_t}｜全程更新${c.run_total_updates}／投递${c.run_total_delivered} @${map.tIndex}`;
  const now = parseT(snap?.processingTime);
  const ev = (runState.events || []).filter((e) => {
    const t = parseT(e.time || e.eventTime || e.ts);
    return !t || t <= now + 1;
  }).slice(-40);
  document.getElementById("events").textContent = ev.map((e) => e.type || JSON.stringify(e)).join(", ") || "—";
  let tr = null;
  if (pinnedDetail?.fusionId && snap?.tracks) {
    tr = snap.tracks.find((t) => t.fusionId === pinnedDetail.fusionId) || null;
  }
  if (!tr && map.targetFilter?.size && snap?.tracks) {
    tr = snap.tracks.find((t) => map._allowedByFilter("fusion", t)) || null;
  }
  if (!tr && snap?.tracks?.length) tr = snap.tracks[0];
  if (tr) {
    document.getElementById("detail").textContent = JSON.stringify({ kind: "track@clock", ...tr }, null, 2);
    const rows = (tr.sourceTracks || []).map((s) =>
      `<div>${s.source} · ${s.sourceTrackId} · ${s.aircraftId || "-"} · ${s.bindingStatus || "?"}</div>`
    );
    document.getElementById("assoc").innerHTML = rows.join("") || "无";
  } else {
    // No track at this clock — clear future-frame residue
    document.getElementById("detail").textContent = "当前时刻无目标";
    document.getElementById("assoc").innerHTML = "无";
    pinnedDetail = null;
  }
}

function showRun(result) {
  if (playTimer) { clearTimeout(playTimer); playTimer = null; }
  runState = result;
  if (result.t0) runState.t0Ms = parseT(result.t0);
  map.setState(result, { fit: true, resetTime: true });
  updateTransport();
  document.getElementById("eval").textContent = result.evaluation
    ? JSON.stringify(result.evaluation, null, 2)
    : (result.accuracy_note || "无评估／无真值");
  const ac = result.scenario?.aircraft || [];
  document.getElementById("acList").innerHTML = ac.map((a) =>
    `<li><b>${a.label}</b> SN=${a.rid_sn || "-"} 源=${Object.entries(a.sources || {}).filter(([, v]) => v.enabled).map(([k]) => k).join("+") || "无"}</li>`
  ).join("");
  rebuildTargetFilters(result);
}

async function loadScenarioList() {
  const r = await fetch(api + "/v1/workbench/scenarios");
  const j = await r.json();
  const sel = document.getElementById("scenarioSelect");
  sel.innerHTML = (j.scenarios || []).map((s) =>
    `<option value="${s.name}">${s.name}${s.notes ? " — " + s.notes.slice(0, 28) : ""}</option>`
  ).join("");
}

function sourceBlock(src, cfg) {
  cfg = cfg || { enabled: false, period_s: 1, pos_noise_m: 5, delay_s: 0, drop_prob: 0, reorder_window_s: 0 };
  return `<details class="srcblk" open>
    <summary><label><input type="checkbox" data-k="enabled" data-src="${src}" ${cfg.enabled ? "checked" : ""}/> ${src} 数据源</label></summary>
    <label>周期s <input type="number" data-k="period_s" data-src="${src}" value="${cfg.period_s ?? 1}" step="0.1"/></label>
    <label>噪声m <input type="number" data-k="pos_noise_m" data-src="${src}" value="${cfg.pos_noise_m ?? 5}" step="0.1"/></label>
    <label>延迟s <input type="number" data-k="delay_s" data-src="${src}" value="${cfg.delay_s ?? 0}" step="0.1"/></label>
    <label>丢点概率 <input type="number" data-k="drop_prob" data-src="${src}" value="${cfg.drop_prob ?? 0}" step="0.05" min="0" max="1"/></label>
    <label>乱序窗s <input type="number" data-k="reorder_window_s" data-src="${src}" value="${cfg.reorder_window_s ?? 0}" step="0.1"/></label>
    <label>雷达换号时刻s <input type="number" data-k="radar_id_swap_at_s" data-src="${src}" value="${cfg.radar_id_swap_at_s ?? ""}" step="1"/></label>
    <label>失联区间 outage [[a,b],…] <input type="text" data-k="outage" data-src="${src}" value='${JSON.stringify(cfg.outage || [])}'/></label>
  </details>`;
}

function renderEditor() {
  const el = document.getElementById("editor");
  if (!draftScenario) { el.innerHTML = "<p class='hint'>点「加载编辑」拉取场景</p>"; return; }
  el.innerHTML = (draftScenario.aircraft || []).map((a, i) => `
    <fieldset class="acedit" data-i="${i}">
      <legend>飞机 ${a.label}
        <button type="button" data-act="del" data-i="${i}">删除</button>
      </legend>
      <label>标签 <input data-f="label" value="${a.label}"/></label>
      <label>truth_id(仅评估) <input data-f="truth_id" value="${a.truth_id}"/></label>
      <label>RID SN <input data-f="rid_sn" value="${a.rid_sn || ""}"/></label>
      <label>速度 m/s <input type="number" data-f="speed_mps" value="${a.speed_mps}" step="0.5"/></label>
      <label>起飞偏移 s <input type="number" data-f="takeoff_offset_s" value="${a.takeoff_offset_s}" step="0.5"/></label>
      <label>航点 JSON [{x_m,y_m,dwell_s}]
        <textarea data-f="waypoints" rows="3">${JSON.stringify(a.waypoints || [], null, 0)}</textarea>
      </label>
      ${["rid", "spectrum", "radar"].map((s) => sourceBlock(s, (a.sources || {})[s])).join("")}
    </fieldset>
  `).join("");
  el.querySelectorAll("[data-act=del]").forEach((btn) => {
    btn.onclick = () => {
      draftScenario.aircraft.splice(Number(btn.dataset.i), 1);
      renderEditor();
    };
  });
}

function readEditorIntoDraft() {
  if (!draftScenario) return null;
  draftScenario.seed = Number(document.getElementById("seed").value);
  draftScenario.duration_s = Number(document.getElementById("duration").value);
  draftScenario.name = document.getElementById("scenarioSelect").value || draftScenario.name;
  const fields = document.querySelectorAll(".acedit");
  fields.forEach((fs) => {
    const i = Number(fs.dataset.i);
    const a = draftScenario.aircraft[i];
    if (!a) return;
    a.label = fs.querySelector('[data-f="label"]').value;
    a.truth_id = fs.querySelector('[data-f="truth_id"]').value;
    a.rid_sn = fs.querySelector('[data-f="rid_sn"]').value || null;
    a.speed_mps = Number(fs.querySelector('[data-f="speed_mps"]').value);
    a.takeoff_offset_s = Number(fs.querySelector('[data-f="takeoff_offset_s"]').value);
    try { a.waypoints = JSON.parse(fs.querySelector('[data-f="waypoints"]').value); } catch (_) {}
    a.sources = a.sources || {};
    for (const src of ["rid", "spectrum", "radar"]) {
      const base = a.sources[src] || { enabled: false };
      const get = (k) => fs.querySelector(`[data-k="${k}"][data-src="${src}"]`);
      const en = get("enabled");
      base.enabled = !!(en && en.checked);
      for (const k of ["period_s", "pos_noise_m", "delay_s", "drop_prob", "reorder_window_s"]) {
        const inp = get(k);
        if (inp) base[k] = Number(inp.value);
      }
      const swap = get("radar_id_swap_at_s");
      if (swap) base.radar_id_swap_at_s = swap.value === "" ? null : Number(swap.value);
      const out = get("outage");
      if (out) {
        try { base.outage = JSON.parse(out.value || "[]"); } catch (_) { base.outage = []; }
      }
      a.sources[src] = base;
    }
  });
  return draftScenario;
}

document.getElementById("btnLoadSc").onclick = async () => {
  const name = document.getElementById("scenarioSelect").value;
  const r = await fetch(api + `/v1/workbench/scenarios/${encodeURIComponent(name)}`);
  draftScenario = await r.json();
  document.getElementById("seed").value = draftScenario.seed;
  document.getElementById("duration").value = draftScenario.duration_s;
  renderEditor();
};

document.getElementById("btnAddAc").onclick = () => {
  if (!draftScenario) draftScenario = { name: "custom", seed: 1, duration_s: 40, aircraft: [] };
  const n = draftScenario.aircraft.length + 1;
  draftScenario.aircraft.push({
    label: String.fromCharCode(64 + n),
    truth_id: `TRUTH-${String.fromCharCode(64 + n)}`,
    rid_sn: `SN-X-${n}`,
    speed_mps: 12,
    takeoff_offset_s: 0,
    waypoints: [{ x_m: 0, y_m: n * 40, dwell_s: 0 }, { x_m: 300, y_m: n * 40, dwell_s: 0 }],
    sources: {
      rid: { enabled: true, period_s: 1, pos_noise_m: 3, delay_s: 0, drop_prob: 0, reorder_window_s: 0, outage: [] },
      spectrum: { enabled: false, period_s: 1, pos_noise_m: 8, delay_s: 0, drop_prob: 0, reorder_window_s: 0, outage: [] },
      radar: { enabled: false, period_s: 2, pos_noise_m: 15, delay_s: 0, drop_prob: 0, reorder_window_s: 0, outage: [] },
    },
  });
  renderEditor();
};

document.getElementById("btnSaveSc").onclick = async () => {
  const sc = readEditorIntoDraft();
  if (!sc) return alert("请先加载编辑");
  const name = prompt("保存名称", sc.name || "custom_scenario");
  if (!name) return;
  const r = await fetch(api + "/v1/workbench/scenarios/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, scenario: sc }),
  });
  const j = await r.json();
  setStatus(r.ok, r.ok ? `saved ${j.name}` : `save fail ${r.status}`);
  await loadScenarioList();
};

document.getElementById("btnExportSc").onclick = () => {
  const sc = readEditorIntoDraft();
  if (!sc) return;
  const blob = new Blob([JSON.stringify(sc, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${sc.name || "scenario"}.json`;
  a.click();
};

document.getElementById("btnImportSc").onclick = () => document.getElementById("scFile").click();
document.getElementById("scFile").onchange = async (e) => {
  const f = e.target.files?.[0];
  if (!f) return;
  draftScenario = JSON.parse(await f.text());
  document.getElementById("seed").value = draftScenario.seed;
  document.getElementById("duration").value = draftScenario.duration_s;
  renderEditor();
};

document.getElementById("btnRunSim").onclick = async () => {
  const body = {
    scenarioName: document.getElementById("scenarioSelect").value,
    mode: document.getElementById("runMode").value,
    seed: Number(document.getElementById("seed").value),
  };
  if (draftScenario) {
    body.scenario = readEditorIntoDraft();
  }
  try {
    const r = await fetch(api + "/v1/workbench/run/scenario", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const j = await r.json();
    if (!r.ok) {
      document.getElementById("events").textContent = JSON.stringify(j, null, 2);
      setStatus(false, `错误 ${r.status}`);
      return;
    }
    showRun(j);
    setStatus(true, `run ${j.sessionId} @t0`);
  } catch (e) {
    setStatus(false, String(e));
  }
};

document.getElementById("seek").oninput = (e) => {
  map.setTimeIndex(Number(e.target.value));
  updateTransport();
};

document.getElementById("btnPause").onclick = () => {
  if (playTimer) { clearTimeout(playTimer); playTimer = null; }
};

function schedulePlay() {
  if (!runState?.snapshots?.length) return;
  if (map.tIndex >= runState.snapshots.length - 1) {
    playTimer = null;
    return;
  }
  const spd = Number(document.getElementById("speed").value) || 1;
  const t0 = parseT(runState.snapshots[map.tIndex].processingTime);
  const t1 = parseT(runState.snapshots[map.tIndex + 1].processingTime);
  const wait = Math.max(40, (t1 - t0) / spd);
  playTimer = setTimeout(() => {
    map.setTimeIndex(map.tIndex + 1);
    updateTransport();
    schedulePlay();
  }, wait);
}

document.getElementById("btnPlay").onclick = () => {
  if (playTimer) clearTimeout(playTimer);
  if (!runState?.snapshots?.length) return;
  if (map.tIndex >= runState.snapshots.length - 1) map.setTimeIndex(0);
  updateTransport();
  schedulePlay();
};

document.getElementById("btnStep").onclick = () => {
  if (!runState?.snapshots?.length) return;
  if (map.tIndex >= runState.snapshots.length - 1) map.setTimeIndex(0);
  else map.setTimeIndex(map.tIndex + 1);
  updateTransport();
};

const FIELD_KEYS = [
  "observationId", "source", "sourceTrackId", "aircraftId", "measurementTime",
  "longitude", "latitude", "altitude", "detectorId", "speed", "heading",
  "verticalSpeed", "altitudeDatum", "receivedAt",
];
let mappingCandidates = {};
let multiQueue = [];

async function initFieldMapForm() {
  const r = await fetch(api + "/v1/workbench/mapping/default");
  const j = await r.json();
  mappingCandidates = j.candidates || {};
  const def = j.mapping?.field_map || {};
  const box = document.getElementById("fieldMapForm");
  if (!box) return;
  box.innerHTML = FIELD_KEYS.map((k) => {
    const opts = (mappingCandidates[k] || [def[k] || k]).concat([k, ""]).filter((v, i, a) => a.indexOf(v) === i);
    const cur = def[k] || opts[0] || k;
    return `<label>${k}
      <input list="dl-${k}" class="fmap" data-k="${k}" value="${cur || ""}" />
      <datalist id="dl-${k}">${opts.map((o) => `<option value="${o}">`).join("")}</datalist>
    </label>`;
  }).join("");
  const ms = document.getElementById("mapTemplateSelect");
  const lr = await fetch(api + "/v1/workbench/mapping/list");
  const lj = await lr.json();
  ms.innerHTML = (lj.mappings || []).map((m) => `<option value="${m.name}">${m.name}</option>`).join("") || "<option value=''>无模板</option>";
}

function mappingFromForm() {
  const tz = document.getElementById("tzMode").value;
  const named = tz && tz !== "assume_utc" ? tz : null;
  const field_map = {};
  document.querySelectorAll(".fmap").forEach((inp) => {
    if (inp.value) field_map[inp.dataset.k] = inp.value;
  });
  if (!Object.keys(field_map).length) {
    // SQL page defaults
    Object.assign(field_map, {
      measurementTime: "created_at",
      sourceTrackId: "id",
      detectorId: "detector",
      source: "source",
      longitude: "longitude",
      latitude: "latitude",
      altitude: "altitude",
    });
  }
  return {
    field_map,
    source_timezone: named,
    assume_utc_naive: tz === "assume_utc",
    treat_raw_id_as_aircraftId: document.getElementById("rawIdAsSn").checked,
  };
}

document.getElementById("btnPreview").onclick = async () => {
  const f = document.getElementById("fileInput").files[0];
  if (!f) { alert("请选择文件"); return; }
  const fd = new FormData();
  fd.append("file", f);
  fd.append("mapping_json", JSON.stringify(mappingFromForm()));
  fd.append("max_rows", "2000");
  const r = await fetch(api + "/v1/workbench/import/preview", { method: "POST", body: fd });
  const j = await r.json();
  importMeta = j;
  document.getElementById("importReport").textContent = JSON.stringify({
    ok: j.ok, n: j.n_observations, errors: j.n_errors, by_source: j.by_source,
    time_range: j.time_range, sample_errors: j.errors_sample, stored_as: j.stored_as,
    preview_only: j.preview_only,
  }, null, 2);
};

function selectionFilters() {
  const num = (id) => {
    const v = document.getElementById(id)?.value;
    if (v === "" || v == null) return undefined;
    const n = Number(v);
    return Number.isFinite(n) ? n : undefined;
  };
  const s = (id) => {
    const v = document.getElementById(id)?.value?.trim();
    return v || undefined;
  };
  return {
    timeFrom: s("timeFrom"),
    timeTo: s("timeTo"),
    detectorId: s("filterDetector"),
    lonMin: num("lonMin"),
    lonMax: num("lonMax"),
    latMin: num("latMin"),
    latMax: num("latMax"),
  };
}

let pageState = { offset: 0, limit: 50, path: null, has_more: false, next_offset: null };

document.getElementById("btnRunImport").onclick = async () => {
  if (!importMeta?.stored_as) { alert("请先预览导入"); return; }
  const maxRows = Number(document.getElementById("maxRows").value || 5000);
  const filters = selectionFilters();
  const r = await fetch(api + "/v1/workbench/run/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      path: importMeta.stored_as,
      mode: "replay",
      mapping: mappingFromForm(),
      maxRows,
      ...filters,
      truncated: true,
    }),
  });
  const j = await r.json();
  if (!r.ok) {
    document.getElementById("importReport").textContent = JSON.stringify(j, null, 2);
    return;
  }
  if (!j.observations?.length) {
    document.getElementById("importReport").textContent = JSON.stringify({ error: "no_observations", ...j }, null, 2);
    setStatus(false, "无有效观测");
    return;
  }
  showRun(j);
  document.getElementById("importReport").textContent = JSON.stringify({
    n: j.n_observations,
    import_summary: j.import_summary,
    filters: j.import_summary?.filters,
    window_note: j.import_summary?.window_note,
  }, null, 2);
};

async function loadLocalFiles() {
  const r = await fetch(api + "/v1/workbench/local-data");
  const j = await r.json();
  document.getElementById("localFiles").innerHTML = (j.files || []).map((f) =>
    `<li><button type="button" class="localpick" data-path="${f.path}">选择</button> ${f.path} (${(f.bytes / 1e6).toFixed(2)} MB)</li>`
  ).join("") || "<li>无（将 SQL 放在 data/ 只读使用）</li>";
  document.querySelectorAll(".localpick").forEach((btn) => {
    btn.onclick = async () => {
      const path = btn.dataset.path;
      document.getElementById("importReport").textContent = `选中 ${path}，开始回放…`;
      const maxRows = Number(document.getElementById("maxRows").value || 5000);
      const filters = selectionFilters();
      const r2 = await fetch(api + "/v1/workbench/run/local", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path,
          mode: "replay",
          mapping: mappingFromForm(),
          maxRows,
          ...filters,
          truncated: true,
        }),
      });
      const j2 = await r2.json();
      if (!r2.ok) {
        document.getElementById("importReport").textContent = JSON.stringify(j2, null, 2);
        return;
      }
      importMeta = { stored_as: path };
      pageState = { offset: 0, limit: 50, path, has_more: false, next_offset: null };
      showRun(j2);
      document.getElementById("importReport").textContent = JSON.stringify({
        path, n: j2.n_observations, import_summary: j2.import_summary, filters: j2.import_summary?.filters,
      }, null, 2);
    };
  });
}

function refreshRouteAcSelect(preserveLabel) {
  const sel = document.getElementById("routeAcSelect");
  if (!sel || !draftScenario) return;
  let keep = preserveLabel;
  if (keep == null) {
    try {
      const idx = sel.selectedIndex;
      keep = (idx >= 0 && sel.options && sel.options[idx]) ? sel.options[idx].text : sel.value;
    } catch (_) {
      keep = sel.value;
    }
  }
  sel.innerHTML = (draftScenario.aircraft || []).map((a) =>
    `<option value="${a.label}">${a.label}</option>`
  ).join("");
  if (keep) {
    const opts = sel.options ? [...sel.options] : [];
    const opt = opts.find((o) => o.value === keep || o.text === keep);
    if (opt) sel.value = opt.value;
    else sel.value = keep;
  }
}

function aircraftByLabel(label) {
  return (draftScenario?.aircraft || []).find((a) => a.label === label);
}

document.getElementById("btnRouteAdd").onclick = () => {
  if (!draftScenario) return alert("请先加载场景");
  // Commit unsaved editor fields BEFORE redraw so draw does not wipe inputs
  readEditorIntoDraft();
  const label = document.getElementById("routeAcSelect").value
    || document.getElementById("routeAcSelect").options[document.getElementById("routeAcSelect").selectedIndex]?.text;
  // Do NOT rebuild select here — preserves user choice (R3-01)
  const ac = aircraftByLabel(label) || draftScenario.aircraft[Number(label)] || draftScenario.aircraft[0];
  if (!ac) return;
  map.startRouteEdit(ac.waypoints || [], (pts) => {
    ac.waypoints = pts;
    // update waypoints textarea only without full form rebuild when possible
    const idx = draftScenario.aircraft.indexOf(ac);
    const ta = document.querySelector(`.acedit[data-i="${idx}"] textarea[data-f="waypoints"]`);
    if (ta) ta.value = JSON.stringify(pts);
    else {
      readEditorIntoDraft();
      renderEditor();
      refreshRouteAcSelect(ac.label);
    }
  });
  setStatus(true, `画线中：${ac.label}（点击加点／拖动改点）`);
};

document.getElementById("btnRouteDel").onclick = () => {
  if (!map.routeEdit?.points?.length) return;
  map.routeEdit.points.pop();
  map.draw();
  if (map.routeEdit.onChange) map.routeEdit.onChange(map.routeEdit.points);
};

document.getElementById("btnRouteDone").onclick = () => {
  map.stopRouteEdit();
  setStatus(true, "画线结束");
};

document.getElementById("btnSaveMap").onclick = async () => {
  const name = prompt("映射模板名", "navicat_sql");
  if (!name) return;
  await fetch(api + "/v1/workbench/mapping/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, mapping: mappingFromForm() }),
  });
  await initFieldMapForm();
};

document.getElementById("btnLoadMap").onclick = async () => {
  const name = document.getElementById("mapTemplateSelect").value;
  if (!name) return;
  const j = await (await fetch(api + `/v1/workbench/mapping/${encodeURIComponent(name)}`)).json();
  const mapping = j.field_map ? j : (j.mapping || j);
  const fm = mapping.field_map || {};
  // Clear fields missing from template, then apply
  document.querySelectorAll(".fmap").forEach((inp) => {
    inp.value = fm[inp.dataset.k] != null ? fm[inp.dataset.k] : "";
  });
  const tz = document.getElementById("tzMode");
  // Page save path: assume_utc → {source_timezone:null, assume_utc_naive:true}
  if (mapping.assume_utc_naive || mapping.source_timezone === "assume_utc") {
    tz.value = "assume_utc";
  } else if (mapping.source_timezone) {
    tz.value = mapping.source_timezone;
  } else if ("source_timezone" in mapping || "assume_utc_naive" in mapping) {
    // Explicit null / strict-timezone template
    tz.value = "";
  }
  if (typeof mapping.treat_raw_id_as_aircraftId === "boolean") {
    document.getElementById("rawIdAsSn").checked = mapping.treat_raw_id_as_aircraftId;
  }
  document.getElementById("importReport").textContent = JSON.stringify({
    loaded_template: name,
    source_timezone: mapping.source_timezone,
    assume_utc_naive: mapping.assume_utc_naive,
    treat_raw_id_as_aircraftId: mapping.treat_raw_id_as_aircraftId,
    field_map: fm,
    tzMode: tz.value,
  }, null, 2);
};

function renderMultiQueue() {
  const el = document.getElementById("multiQueue");
  if (!el) return;
  el.innerHTML = multiQueue.map((q, i) =>
    `<li data-i="${i}"><b>${q.path}</b> src=${q.source || "auto"}
      <button type="button" class="qrm" data-i="${i}">移除</button></li>`
  ).join("") || "<li class='hint'>队列空 — 选择文件后点「加入队列」</li>";
  el.querySelectorAll(".qrm").forEach((btn) => {
    btn.onclick = () => {
      multiQueue.splice(Number(btn.dataset.i), 1);
      renderMultiQueue();
    };
  });
}

async function uploadFilesToQueue(files, { replace = false } = {}) {
  if (replace) multiQueue = [];
  const mapping = mappingFromForm();
  const maxRows = Number(document.getElementById("maxRows").value || 5000);
  const timeFrom = document.getElementById("timeFrom")?.value || null;
  const timeTo = document.getElementById("timeTo")?.value || null;
  const failures = [];
  for (const f of files) {
    const fd = new FormData();
    fd.append("file", f);
    fd.append("mapping_json", JSON.stringify(mapping));
    fd.append("max_rows", String(maxRows));
    const r = await fetch(api + "/v1/workbench/import/preview", { method: "POST", body: fd });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.stored_as) {
      failures.push({ name: f.name, error: j.error || j.detail || `http_${r.status}` });
      continue;
    }
    multiQueue.push({
      path: j.stored_as,
      mapping: JSON.parse(JSON.stringify(mapping)),
      maxRows,
      source: null,
      preview_n: j.n_observations,
      timeFrom: timeFrom || undefined,
      timeTo: timeTo || undefined,
    });
  }
  renderMultiQueue();
  if (failures.length) {
    document.getElementById("importReport").textContent = JSON.stringify(
      { queue_upload_failures: failures, queue_len: multiQueue.length },
      null,
      2
    );
  }
  return failures;
}

document.getElementById("btnQueueAdd")?.addEventListener("click", async () => {
  const files = document.getElementById("fileInput").files;
  if (!files?.length) return alert("请选择文件");
  await uploadFilesToQueue(files, { replace: false });
  window.__wbNewFilesSelected = false;
});
document.getElementById("btnQueueReplace")?.addEventListener("click", async () => {
  const files = document.getElementById("fileInput").files;
  if (!files?.length) return alert("请选择文件");
  await uploadFilesToQueue(files, { replace: true });
  window.__wbNewFilesSelected = false;
});
document.getElementById("btnQueueClear")?.addEventListener("click", () => {
  multiQueue = [];
  renderMultiQueue();
});
document.getElementById("fileInput")?.addEventListener("change", () => {
  // Marks that a new picker selection exists; does NOT auto-replace configured queue
  window.__wbNewFilesSelected = true;
});

document.getElementById("btnRunMulti").onclick = async () => {
  const files = document.getElementById("fileInput").files;
  // Replay uses the configured queue. Shortcut: empty queue + current selection → ingest once.
  // Never overwrite a non-empty configured queue from leftover fileInput.
  if (!multiQueue.length) {
    if (files?.length) {
      const fails = await uploadFilesToQueue(files, { replace: true });
      window.__wbNewFilesSelected = false;
      if (!multiQueue.length) {
        return alert(fails?.length ? "上传失败，队列仍空" : "队列为空：请选择文件并加入队列");
      }
    } else {
      return alert("队列为空：请选择文件并点「加入队列」；运行只回放当前队列，不会用文件框覆盖已配置项");
    }
  }
  renderMultiQueue();
  const filters = selectionFilters();
  const r = await fetch(api + "/v1/workbench/run/import/multi", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      files: multiQueue,
      mode: "replay",
      ...filters,
    }),
  });
  const j = await r.json();
  if (!r.ok) {
    document.getElementById("importReport").textContent = JSON.stringify(j, null, 2);
    return;
  }
  showRun(j);
  document.getElementById("importReport").textContent = JSON.stringify(j.import_summary, null, 2);
};

async function fetchPage(offset, limitOverride) {
  const path = importMeta?.stored_as || multiQueue[0]?.path || pageState.path;
  if (!path) return alert("请先预览导入、加入队列或选择本地文件");
  if (limitOverride != null) pageState.limit = Number(limitOverride) || pageState.limit;
  const filters = selectionFilters();
  const qs = new URLSearchParams({
    offset: String(Math.max(0, offset || 0)),
    limit: String(pageState.limit || 50),
    path,
  });
  Object.entries(filters).forEach(([k, v]) => {
    if (v != null && v !== "") qs.set(k, String(v));
  });
  // dataset_id is basename; path query keeps sandbox-relative local files
  const datasetId = path.split("/").pop();
  const r = await fetch(api + `/v1/workbench/datasets/${encodeURIComponent(datasetId)}/observations?` + qs);
  const j = await r.json();
  if (!r.ok) {
    document.getElementById("importReport").textContent = JSON.stringify(j, null, 2);
    return null;
  }
  pageState = {
    offset: j.offset ?? offset,
    limit: j.limit ?? 50,
    path,
    has_more: !!j.has_more,
    next_offset: j.next_offset,
  };
  const cur = document.getElementById("pageCursor");
  if (cur) cur.textContent = `offset=${pageState.offset} n=${j.n} has_more=${pageState.has_more}`;
  document.getElementById("importReport").textContent = JSON.stringify(j, null, 2);
  return j;
}

document.getElementById("btnPageObs")?.addEventListener("click", async () => {
  pageState.offset = 0;
  await fetchPage(0);
});
document.getElementById("btnPagePrev")?.addEventListener("click", async () => {
  const prev = Math.max(0, (pageState.offset || 0) - (pageState.limit || 50));
  await fetchPage(prev);
});
document.getElementById("btnPageNext")?.addEventListener("click", async () => {
  if (!pageState.has_more && pageState.next_offset == null) {
    return alert("没有下一页（has_more=false）");
  }
  const next = pageState.next_offset != null ? pageState.next_offset : (pageState.offset || 0) + (pageState.limit || 50);
  await fetchPage(next);
});

// expose for browser assertions
window.__wb = {
  get map() { return map; },
  get runState() { return runState; },
  get draftScenario() { return draftScenario; },
  get multiQueue() { return multiQueue; },
  get pageState() { return pageState; },
  mappingFromForm,
  selectionFilters,
  parseT,
  countsUpTo,
  fetchPage,
};

const _origLoad = document.getElementById("btnLoadSc").onclick;
document.getElementById("btnLoadSc").addEventListener("click", () => setTimeout(refreshRouteAcSelect, 300));

loadScenarioList().then(() => document.getElementById("btnLoadSc").click());
initFieldMapForm();
document.getElementById("btnHealth").click();
