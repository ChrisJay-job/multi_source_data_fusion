import { MapView, computeZoomAt, MAP_ZOOM_FACTOR, MAP_MIN_SCALE, MAP_MAX_SCALE } from "./canvas.js";

const api = "";
const DEFAULT_SCENARIO = "seven_aircraft_combinations";
const SRC_LABEL = { rid: "RID", spectrum: "频谱", radar: "雷达" };
const map = new MapView(document.getElementById("cv"));
let runState = null;
let playTimer = null;
let importMeta = null;
let draftScenario = null;
let selectedAcIndex = 0;
let pinnedDetail = null;
let dirtyDraft = false;
let runReqSeq = 0;
let staleRunKeep = null; // previous run kept visibly as "旧运行"

map.onPick = (obj, kind) => {
  if (kind === "track" || obj.fusionId) {
    pinnedDetail = obj;
    map.setSelectedFusionId(obj.fusionId || null);
  } else {
    map.setSelectedFusionId(null);
  }
  renderInspector(obj, kind);
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

function setFocusStatus(msg, ok = true) {
  const el = document.getElementById("focusStatus");
  if (!el) return;
  el.textContent = msg || "";
  el.style.color = ok ? "#90be6d" : "#f9c74f";
}

/** Resolve a real fusionId from pin / checkbox / explicit id (exact fusionId or sim label→id). */
function resolveFusionId(explicit) {
  const tryMap = (id) => {
    if (!id) return null;
    const s = String(id);
    const hit = (runState?.final_tracks || []).find((t) => t.fusionId === s);
    if (hit) return hit.fusionId;
    const byLabel = (runState?.final_tracks || []).find((t) =>
      (runState?.scenario?.aircraft || []).some((a) =>
        a.label === s && (
          (runState?.evaluation?.fusion_to_truth || {})[t.fusionId] === a.truth_id ||
          (a.rid_sn && t.aircraftId === a.rid_sn)
        )
      )
    );
    if (byLabel) return byLabel.fusionId;
    // Real-data keys are full fusionIds; accept as-is when no scenario mapping.
    if (s.includes("-") || s.length > 8) return s;
    return null;
  };
  if (explicit) return tryMap(explicit);
  if (pinnedDetail?.fusionId) return String(pinnedDetail.fusionId);
  const checked = [...document.querySelectorAll(".tfilt:checked")].map((c) => c.dataset.id).filter(Boolean);
  if (checked.length === 1) return tryMap(checked[0]);
  return null;
}

function locateSelectedTrack(explicitFid) {
  const fid = resolveFusionId(explicitFid);
  if (!fid) {
    setFocusStatus("请先选中一条真实融合目标", false);
    return;
  }
  map.setSelectedFusionId(fid);
  const r = map.centerOnFusionId(fid);
  setFocusStatus(r.message || (r.ok ? "定位完成" : "定位失败"), !!r.ok);
}

function viewSelectedTrackHistory(explicitFid) {
  const fid = resolveFusionId(explicitFid);
  if (!fid) {
    setFocusStatus("请先选中一条真实融合目标", false);
    return;
  }
  map.setSelectedFusionId(fid);
  const r = map.fitFusionTrackHistory(fid);
  setFocusStatus(r.message || (r.ok ? "航迹聚焦完成" : "航迹聚焦失败"), !!r.ok);
}

function parseT(s) {
  if (!s) return 0;
  return Date.parse(String(s).replace("Z", "+00:00"));
}

function setStatus(ok, text) {
  const el = document.getElementById("svcStatus");
  el.textContent = text;
  el.style.background = ok ? "rgba(144,190,109,.25)" : "rgba(249,199,79,.25)";
}

function enabledSources(ac) {
  return Object.entries(ac.sources || {}).filter(([, v]) => v?.enabled).map(([k]) => k);
}

function sourceChipsHtml(ac) {
  return ["rid", "spectrum", "radar"].map((s) => {
    const on = !!(ac.sources?.[s]?.enabled);
    return `<span class="chip ${on ? "on " + s : "off"}">${SRC_LABEL[s]}</span>`;
  }).join("");
}

function emptyField(v) {
  return v === null || v === undefined || v === "" || (typeof v === "number" && Number.isNaN(v));
}

function fmtObsField(v, { generated } = {}) {
  if (emptyField(v)) {
    return `<span class="empty">未提供</span><span class="tag">未提供/待设备确认</span>`;
  }
  const tag = generated ? `<span class="tag">自动生成</span>` : `<span class="tag">观测值</span>`;
  return `${v}${tag}`;
}

function renderInspector(obj, kind) {
  const box = document.getElementById("inspector");
  if (!obj) {
    box.innerHTML = "点击轨迹点查看";
    return;
  }
  if (kind === "obs") {
    // Never substitute aircraft motion speed for device-reported speed
    const rows = [
      ["source", obj.source],
      ["sourceTrackId", obj.sourceTrackId],
      ["aircraftId", emptyField(obj.aircraftId) ? null : obj.aircraftId],
      ["observationId", obj.observationId],
      ["measurementTime", obj.measurementTime],
      ["longitude", obj.longitude],
      ["latitude", obj.latitude],
      ["altitude", obj.altitude],
      ["speed", obj.speed],
      ["heading", obj.heading],
      ["verticalSpeed", obj.verticalSpeed],
      ["detectorId", obj.detectorId],
      ["receivedAt", obj.receivedAt],
    ];
    box.innerHTML = `<div><b>观测检查器</b> <span class="tag">${SRC_LABEL[obj.source] || obj.source}</span></div>` +
      rows.map(([k, v]) => {
        const isMotion = k === "altitude" || k === "speed" || k === "heading" || k === "verticalSpeed";
        if (isMotion) return `<div><span class="k">${k}</span>：${fmtObsField(v)}</div>`;
        if (emptyField(v)) return `<div><span class="k">${k}</span>：${fmtObsField(null)}</div>`;
        return `<div><span class="k">${k}</span>：${v}</div>`;
      }).join("");
    // Always refresh/clear explain when clicking a new observation (R1-04).
    renderExplainAssoc(obj, kind);
    return;
  }
  const srcs = (obj.sourceTracks || []).map((s) => {
    const role = s.usedForPosition || s.primaryPosition || s.bindingStatus || "";
    return `${SRC_LABEL[s.source] || s.source}:${s.sourceTrackId || "-"}(${s.bindingStatus || role || "?"})`;
  }).join("；") || "无";
  const primary = obj.primaryPositionSource || obj.positionSource ||
    (obj.sourceTracks || []).find((s) => s.usedForPosition || s.primaryPosition)?.source || "—";
  const active = activeSourcesOnTrack(obj, runState?.snapshots?.[map.tIndex]?.processingTime);
  const hist = historicalSourceRows(obj, runState?.snapshots?.[map.tIndex]?.processingTime);
  const lastObs = obj.lastObservedAt || "—";
  const snap = runState?.snapshots?.[map.tIndex];
  const now = parseT(snap?.processingTime);
  const lastMs = parseT(lastObs);
  const lag = now && lastMs ? ((now - lastMs) / 1000).toFixed(1) + "s" : "—";
  const labelHint = (runState?.scenario?.aircraft || []).find((a) =>
    (a.rid_sn && a.rid_sn === obj.aircraftId) ||
    (runState?.evaluation?.fusion_to_truth || {})[obj.fusionId] === a.truth_id
  )?.label || "—";
  box.innerHTML = [
    `<div><b>目标</b> 机=${labelHint} · SN=${obj.aircraftId || "(无)"} · fusionId=<span class="k">${obj.fusionId || ""}</span></div>`,
    `<div class="row tight track-focus-actions">` +
      `<button type="button" id="btnLocateTrack" data-fid="${obj.fusionId || ""}">定位</button>` +
      `<button type="button" id="btnViewTrackHist" data-fid="${obj.fusionId || ""}">查看航迹</button>` +
    `</div>`,
    `<div><span class="k">trackStatus</span>：${obj.trackStatus || "—"} · <span class="k">positionMode</span>：${obj.positionMode || "—"}</div>`,
    `<div><span class="k">主位置来源</span>：${SRC_LABEL[primary] || primary}</div>`,
    `<div><span class="k">活跃源</span>：${active.map((s) => SRC_LABEL[s] || s).join("+") || "—"}</div>`,
    `<div><span class="k">历史绑定</span>：${hist.map((s) => `${SRC_LABEL[s.source] || s.source}:${s.sourceTrackId}(${s.bindingStatus || "?"})`).join("；") || "—"}</div>`,
    `<div><span class="k">来源清单</span>：${srcs}</div>`,
    `<div><span class="k">最近观测</span>：${lastObs} · 时差=${lag}</div>`,
    `<div><span class="k">seg</span>：${obj.trackSegmentId ?? "—"} · stateTime=${obj.stateTime || "—"}</div>`,
  ].join("");
  document.getElementById("btnLocateTrack")?.addEventListener("click", (ev) => {
    ev.preventDefault();
    locateSelectedTrack(ev.currentTarget.dataset.fid);
  });
  document.getElementById("btnViewTrackHist")?.addEventListener("click", (ev) => {
    ev.preventDefault();
    viewSelectedTrackHistory(ev.currentTarget.dataset.fid);
  });
  renderExplainAssoc(obj, kind);
}

function playTimeMs() {
  return parseT(runState?.snapshots?.[map.tIndex]?.processingTime);
}

function eventTimeMs(e) {
  return parseT(e?.time || e?.eventTime || e?.ts || e?.at);
}

function renderExplainAssoc(obj, kind) {
  const box = document.getElementById("explainAssoc");
  if (!box) return;
  const now = playTimeMs();
  if (!obj) {
    box.innerHTML = "点击目标或观测后显示解释";
    return;
  }
  if (kind === "obs") {
    box.innerHTML = [
      `<div><b>当前时刻解释（观测）</b> ${SRC_LABEL[obj.source] || obj.source} · id=${obj.observationId || "—"}</div>`,
      `<div>局部源 ID：${obj.sourceTrackId || "—"} · 身份：${obj.aircraftId || "(无)"}</div>`,
      `<div>候选距离／代价：<b>当前未输出</b>（冻结引擎未暴露；前端不推测）</div>`,
      `<div class="muted">整次评估结论：见结果摘要；本面板不保留上一目标解释。</div>`,
    ].join("");
    return;
  }
  const fid = obj.fusionId;
  const evs = (runState?.events || []).filter((e) => {
    if (e.fusionId !== fid) return false;
    const t = eventTimeMs(e);
    return !now || !t || t <= now + 1;
  }).slice(-8);
  const relatedRej = [];
  const globalUnscoped = [];
  for (const r of (runState?.rejected || [])) {
    const t = eventTimeMs(r) || parseT(r.measurementTime || r.receivedAt);
    if (now && t && t > now + 1) continue; // no future
    const sameFid = r.fusionId && r.fusionId === fid;
    const sameObs = r.observationId && r.observationId === obj.observationId;
    const sameSt = r.sourceTrackId && (obj.sourceTracks || []).some((s) => s.sourceTrackId === r.sourceTrackId);
    if (sameFid || sameObs || sameSt) relatedRej.push(r);
    else if (r.fusionId || r.observationId || r.sourceTrackId) globalUnscoped.push({ ...r, _tag: "未提供归属" });
    else globalUnscoped.push({ ...r, _tag: "未提供归属" });
  }
  const verd = evalVerdict(runState?.evaluation);
  const amb = (runState?.evaluation?.undetermined || []).filter((u) => u.fusionId === fid);
  const fm = (runState?.evaluation?.false_merges || []).filter((u) => u.fusionId === fid);
  const cap = document.getElementById("capabilityNote");
  const scName = runState?.scenario?.name || "";
  const idMode = runState?.scenario?.identity_mode || runState?.identity_audit?.identity_mode || "";
  if (cap) {
    if (/near_parallel_2m|near2|spacing_m.: 2/.test(scName + JSON.stringify(runState?.scenario?.focus_hint || {}))) {
      cap.innerHTML = "可辨识性：2m≪仿真噪声尺度时可能<strong>不可唯一裁决</strong>；下方评估仍如实显示算法 FAIL／误合并，不会标绿掩盖。";
    } else {
      cap.textContent = `评估裁决与算法输出分列；identity_mode=${idMode || "—"}；场景可辨识性说明不覆盖原始 FAIL。`;
    }
  }
  box.innerHTML = [
    `<div><b>当前时刻解释</b> fusionId=${fid || "—"} · 主位置=${SRC_LABEL[primaryPositionSource(obj)] || primaryPositionSource(obj)}</div>`,
    `<div>活跃源 vs 历史绑定：见检查器；门控／歧义候选距离：<b>当前未输出</b></div>`,
    `<div>截至播放时刻的事件：${evs.map((e) => e.type).join(", ") || "—"}</div>`,
    `<div>与本目标相关的拒绝：${relatedRej.slice(-5).map((r) => r.reason || r.message || "?").join(", ") || "—"}</div>`,
    `<div><b>整次评估结论</b>：${verd}${fm.length ? " · 误合并=" + fm.length : ""}${amb.length ? " · 未判定=" + amb.length : ""}</div>`,
    `<div class="muted">全局拒绝（未提供归属，不归因当前目标）：${globalUnscoped.slice(-5).map((r) => (r.reason || "?") + "/" + (r._tag || "")).join(", ") || "—"}</div>`,
  ].join("");
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

function syncLayersFromUi() {
  const layers = {};
  document.querySelectorAll(".layer").forEach((c) => { layers[c.dataset.layer] = c.checked; });
  map.setLayers(layers);
  maybeWarnRawLayersHidden();
}
document.querySelectorAll(".layer").forEach((cb) => {
  cb.onchange = syncLayersFromUi;
});
syncLayersFromUi();

function maybeWarnRawLayersHidden() {
  const hint = document.getElementById("layerHint");
  if (!hint) return;
  if (!runState?.preview_sample || !(runState.observations || []).length) {
    hint.textContent = "";
    return;
  }
  const present = new Set((runState.observations || []).map((o) => o.source));
  const anyOn = [...present].some((s) => map.layers[s]);
  if (!anyOn) {
    hint.textContent = "数据存在但来源图层已全部关闭 — 勾选 RID/频谱/雷达，或点「原始观测对比」恢复可见";
    hint.hidden = false;
  } else {
    hint.textContent = "";
    hint.hidden = true;
  }
}

function enableRawLayersForPreview(sample) {
  const present = new Set((sample || []).map((o) => o.source).filter(Boolean));
  for (const src of ["rid", "spectrum", "radar"]) {
    const el = document.querySelector(`.layer[data-layer="${src}"]`);
    if (el) el.checked = present.has(src);
  }
  for (const layer of ["truth", "plan"]) {
    const el = document.querySelector(`.layer[data-layer="${layer}"]`);
    if (el) el.checked = false;
  }
  // Preview is raw-obs focused: keep fused/current optional; open advanced layer panel
  const adv = document.getElementById("advLayers");
  if (adv) adv.open = true;
  map.setTargetFilter(null);
  const box = document.getElementById("targetFilters");
  if (box) box.querySelectorAll("input[type=checkbox]").forEach((c) => { c.checked = false; });
  syncLayersFromUi();
}

function seekToFrame(i) {
  map.setTimeIndex(i);
  updateTransport();
}

document.getElementById("btnResetView").onclick = () => {
  // 适配可见：尊重当前勾选目标与图层，不改播放时刻、不清空过滤。
  map.fitToData({ respectFilter: true });
  map._viewManual = false;
  map.draw();
  setFocusStatus("已适配当前可见范围（未改勾选／图层／播放时刻）", true);
};
document.getElementById("btnLocateTrackGlobal")?.addEventListener("click", () => locateSelectedTrack());
document.getElementById("btnViewTrackHistGlobal")?.addEventListener("click", () => viewSelectedTrackHistory());

function applyViewPreset(name) {
  const set = (layer, on) => {
    const el = document.querySelector(`.layer[data-layer="${layer}"]`);
    if (el) el.checked = !!on;
  };
  const adv = document.getElementById("advLayers");
  if (name === "simple") {
    set("fused", true); set("current", true); set("pred", false);
    set("plan", false); set("truth", true); set("rid", false); set("spectrum", false); set("radar", false);
    if (adv) adv.open = false;
  } else if (name === "obs") {
    set("fused", true); set("current", true); set("pred", false);
    set("plan", false); set("truth", true); set("rid", true); set("spectrum", true); set("radar", true);
    if (adv) adv.open = true;
  } else if (name === "assoc") {
    set("fused", true); set("current", true); set("pred", true);
    set("plan", false); set("truth", true); set("rid", true); set("spectrum", true); set("radar", true);
    if (adv) adv.open = true;
  }
  syncLayersFromUi();
}
document.getElementById("viewSimple")?.addEventListener("click", () => applyViewPreset("simple"));
document.getElementById("viewObs")?.addEventListener("click", () => applyViewPreset("obs"));
document.getElementById("viewAssoc")?.addEventListener("click", () => applyViewPreset("assoc"));

function focusLabelsForKey(key) {
  const sc = runState?.scenario || draftScenario;
  const groups = sc?.focus_hint?.groups || {};
  if (key && groups[key]) return groups[key];
  if (key === "seven") return list("ABCDEFG");
  if (key === "cross_sim") return ["H", "I"];
  if (key === "near2") return ["J", "K"];
  if (key === "overtake") return ["L", "M"];
  if (key === "all") return (sc?.aircraft || []).map((a) => a.label);
  // auto: use challenge_group mapping
  const g = sc?.challenge_group;
  if (g && groups[g]) return groups[g];
  if (g === "all") return (sc?.aircraft || []).filter((a) => !"ABCDEFG".includes(a.label)).map((a) => a.label);
  if (String(g || "").startsWith("near") || g === "cross_sim" || g === "overtake" || g === "cross_async" ||
      g === "cross_outage" || g === "cross_swap") {
    return (sc?.aircraft || []).map((a) => a.label);
  }
  return (sc?.aircraft || []).map((a) => a.label);
}
function list(s) { return [...s]; }

function focusChallengeGroup() {
  const sel = document.getElementById("focusGroupSelect")?.value || "auto";
  const labels = new Set(focusLabelsForKey(sel));
  const hint = (runState?.scenario || draftScenario)?.focus_hint || {};
  map.setTargetFilter(labels);
  const maxSpan = hint.spacing_m === 2 ? 60 : null;
  map.fitToLabels?.([...labels], {
    padding: 1.15,
    minSpanM: hint.spacing_m === 2 ? 20 : 80,
    maxSpanM: maxSpan,
  });
  map.draw();
}
document.getElementById("btnFocusGroup")?.addEventListener("click", focusChallengeGroup);
document.getElementById("btnFitAll")?.addEventListener("click", () => {
  // 适配可见范围：不暗中清空目标勾选。
  map.fitToData({ respectFilter: true });
  map._viewManual = false;
  map.draw();
  setFocusStatus("已适配当前勾选／图层可见范围", true);
});
document.getElementById("btnShowAllFit")?.addEventListener("click", () => {
  // 显示全部并适配：显式清空勾选后再总览。
  const box = document.getElementById("targetFilters");
  if (box) box.querySelectorAll(".tfilt").forEach((c) => { c.checked = false; });
  map.setTargetFilter(null);
  map.fitToData({ respectFilter: false });
  map._viewManual = false;
  map.draw();
  setFocusStatus("已显示全部目标并适配总览", true);
});
document.getElementById("btnZoomNear")?.addEventListener("click", () => {
  const sc = runState?.scenario || draftScenario;
  const hint = sc?.focus_hint || {};
  const pair = hint.pair_labels || ["J", "K"];
  const near = (sc?.aircraft || []).filter((a) => pair.includes(a.label) || /^N2/.test(a.label));
  const labels = near.length ? near.map((a) => a.label) : pair;
  map.setTargetFilter(new Set(labels));
  const geo = runState?.challenge_geometry || sc?.challenge_geometry;
  const pairGeo = pairDistanceInfo(geo, labels);
  // Zoom around current play time for the pair; optional jump to pair-min time syncs seek.
  let at = null;
  const jump = document.getElementById("chkJumpNearTime")?.checked;
  if (jump && pairGeo.at != null) {
    at = pairGeo.at;
    seekToSimTime(at);
  } else {
    const snap = runState?.snapshots?.[map.tIndex];
    const t0 = runState?.t0Ms || parseT(runState?.t0);
    const now = parseT(snap?.processingTime);
    if (t0 && now) at = (now - t0) / 1000;
  }
  map.fitToLabels?.(labels, { padding: 1.05, minSpanM: 12, maxSpanM: 40, atTimeS: at ?? pairGeo.at ?? null });
  updateNearDist(geo, labels, pairGeo);
  map.draw();
});

function pairDistanceInfo(geo, labels) {
  // No focus labels → report global min only (explicit scope).
  if (!labels || !labels.length) {
    return {
      min_d: geo?.min_truth_distance_m,
      at: geo?.min_truth_distance_at_s,
      pair: geo?.min_truth_distance_pair,
      scope: "global_min",
      kind: "global",
    };
  }
  const want = [...labels].map(String).sort();
  for (const c of geo?.checks || []) {
    if (!c.pair || c.min_d == null) continue;
    const p = [...c.pair].map(String).sort();
    if (p.length === want.length && p.every((x, i) => x === want[i])) {
      return { min_d: c.min_d, at: c.at, pair: c.pair, scope: "focused_pair", kind: c.kind };
    }
  }
  // Focused labels present but no matching check — never pretend global min is this pair.
  return {
    min_d: null,
    at: null,
    pair: labels,
    scope: "focused_pair_missing",
    kind: "missing",
    global_min_d: geo?.min_truth_distance_m,
    global_at: geo?.min_truth_distance_at_s,
    global_pair: geo?.min_truth_distance_pair,
  };
}

function seekToSimTime(simS) {
  if (!runState?.snapshots?.length) return;
  const t0 = runState.t0Ms || parseT(runState.t0);
  if (!t0) return;
  let best = 0;
  let bestAbs = Infinity;
  runState.snapshots.forEach((s, i) => {
    const t = parseT(s.processingTime);
    if (!t) return;
    const d = Math.abs((t - t0) / 1000 - simS);
    if (d < bestAbs) { bestAbs = d; best = i; }
  });
  map.setTimeIndex(best);
  updateTransport();
}

function updateNearDist(geo, labels, pairGeo) {
  const el = document.getElementById("nearDist");
  if (!el) return;
  // Prefer helper; keep inline fallback so function-level probes without pairDistanceInfo stay correct.
  let info = pairGeo;
  if (!info) {
    if (typeof pairDistanceInfo === "function") {
      info = pairDistanceInfo(geo, labels);
    } else if (labels && labels.length) {
      let hit = null;
      for (const c of geo?.checks || []) {
        if (!c.pair || c.min_d == null) continue;
        const p = [...c.pair].map(String).sort();
        const want = [...labels].map(String).sort();
        if (p.length === want.length && p.every((x, i) => x === want[i])) {
          hit = { min_d: c.min_d, at: c.at, pair: c.pair, scope: "focused_pair", kind: c.kind };
          break;
        }
      }
      info = hit || {
        min_d: null,
        at: null,
        pair: labels,
        scope: "focused_pair_missing",
        kind: "missing",
        global_min_d: geo?.min_truth_distance_m,
        global_at: geo?.min_truth_distance_at_s,
        global_pair: geo?.min_truth_distance_pair,
      };
    } else {
      info = {
        min_d: geo?.min_truth_distance_m,
        at: geo?.min_truth_distance_at_s,
        pair: geo?.min_truth_distance_pair,
        scope: "global_min",
        kind: "global",
      };
    }
  }
  const pair = (info.pair || labels || []).join("/");
  const g = info.global_min_d ?? geo?.min_truth_distance_m;
  const gPair = (info.global_pair || geo?.min_truth_distance_pair || []).join("/");
  const gAt = info.global_at ?? geo?.min_truth_distance_at_s;
  if (info.scope === "focused_pair_missing") {
    el.textContent =
      `真值最近距：聚焦对=${pair || "?"} 无专属几何校验（不可用全图最小冒充）` +
      (g != null
        ? `；全图最小=${Number(g).toFixed(2)}m(${gPair || "?"})${gAt != null ? "@" + Number(gAt).toFixed(1) + "s" : ""}（单独标记）`
        : "") +
      "（本条不被比例尺覆盖）";
    return;
  }
  if (info.min_d == null) {
    el.textContent = "真值最近距：—（无几何校验）";
    return;
  }
  const at = info.at;
  const scope = info.scope === "focused_pair" ? "聚焦对全程最小" : "全图最小（非聚焦对）";
  el.textContent =
    `真值最近距 ${Number(info.min_d).toFixed(2)} m · 对=${pair || "?"} · ` +
    `${scope}${at != null ? "@" + Number(at).toFixed(1) + "s" : ""}` +
    (info.scope === "focused_pair" && g != null
      ? `；全图最小=${Number(g).toFixed(2)}m(${gPair})${gAt != null ? "@" + Number(gAt).toFixed(1) + "s" : ""}`
      : "") +
    "（本条不被比例尺覆盖）";
}

function rebuildTargetFilters(result) {
  const box = document.getElementById("targetFilters");
  const groups = [];
  for (const a of result.scenario?.aircraft || []) {
    const tr = (result.final_tracks || []).find((t) =>
      (result.evaluation?.fusion_to_truth || {})[t.fusionId] === a.truth_id ||
      (a.rid_sn && t.aircraftId === a.rid_sn)
    );
    const srcIds = (tr?.sourceTracks || []).map((s) => `${s.source}:${s.sourceTrackId}`).join(", ") || "—";
    groups.push({
      key: a.label,
      title: `飞机 ${a.label}`,
      detail: `SN=${a.rid_sn || "(无)"} · fusionId=${tr?.fusionId || "—"} · 局部源=${srcIds}`,
    });
  }
  // Real-data style: fusion targets without aircraft mapping
  const mapped = new Set(groups.map((g) => {
    const tr = (result.final_tracks || []).find((t) => (result.evaluation?.fusion_to_truth || {})[t.fusionId]);
    return tr?.fusionId;
  }).filter(Boolean));
  for (const tr of result.final_tracks || []) {
    if (mapped.has(tr.fusionId)) continue;
    const hasAc = (result.scenario?.aircraft || []).some((a) =>
      (result.evaluation?.fusion_to_truth || {})[tr.fusionId] === a.truth_id ||
      (a.rid_sn && tr.aircraftId === a.rid_sn)
    );
    if (hasAc) continue;
    groups.push({
      key: tr.fusionId,
      title: `融合目标 ${String(tr.fusionId || "").slice(-8)}`,
      detail: `SN=${tr.aircraftId || "(无)"} · 局部源=${(tr.sourceTracks || []).map((s) => s.sourceTrackId).join(",") || "—"}`,
    });
  }
  // Real-file fallback: if final_tracks empty/omitted, list last-snapshot fusionIds for locate/history.
  if (!groups.length) {
    const last = (result.snapshots || [])[(result.snapshots || []).length - 1];
    const seen = new Set();
    for (const tr of last?.tracks || []) {
      if (!tr.fusionId || seen.has(tr.fusionId)) continue;
      seen.add(tr.fusionId);
      groups.push({
        key: tr.fusionId,
        title: `融合目标 ${String(tr.fusionId).slice(-8)}`,
        detail: `SN=${tr.aircraftId || "(无)"} · 局部源=${(tr.sourceTracks || []).map((s) => s.sourceTrackId).join(",") || "—"}`,
      });
    }
  }
  box.innerHTML = groups.map((g) =>
    `<details class="tfilt-group"><summary><label><input type="checkbox" class="tfilt" data-id="${g.key}" /> ${g.title}</label></summary>` +
    `<div class="hint">${g.detail}</div>` +
    (g.key && String(g.key).length > 2
      ? `<div class="row tight"><button type="button" class="btnLocTfilt" data-fid="${g.key}">定位</button>` +
        `<button type="button" class="btnHistTfilt" data-fid="${g.key}">查看航迹</button></div>`
      : "") +
    `</details>`
  ).join("") || "<span class='hint'>运行后出现目标</span>";
  box.querySelectorAll(".tfilt").forEach((cb) => {
    cb.onchange = () => {
      const checked = [...box.querySelectorAll(".tfilt:checked")].map((c) => c.dataset.id);
      map.setTargetFilter(checked.length ? new Set(checked) : null);
    };
  });
  box.querySelectorAll(".btnLocTfilt").forEach((btn) => {
    btn.onclick = (ev) => {
      ev.preventDefault();
      const key = btn.dataset.fid;
      const fid = resolveFusionId(key) || key;
      // Select matching track for inspector
      const tr = (runState?.final_tracks || []).find((t) => t.fusionId === fid)
        || (runState?.snapshots?.[map.tIndex]?.tracks || []).find((t) => t.fusionId === fid);
      if (tr) {
        pinnedDetail = tr;
        renderInspector(tr, "track");
      }
      locateSelectedTrack(fid);
    };
  });
  box.querySelectorAll(".btnHistTfilt").forEach((btn) => {
    btn.onclick = (ev) => {
      ev.preventDefault();
      const key = btn.dataset.fid;
      const fid = resolveFusionId(key) || key;
      const tr = (runState?.final_tracks || []).find((t) => t.fusionId === fid)
        || (runState?.snapshots?.[map.tIndex]?.tracks || []).find((t) => t.fusionId === fid);
      if (tr) {
        pinnedDetail = tr;
        renderInspector(tr, "track");
      }
      viewSelectedTrackHistory(fid);
    };
  });
}

function applySelectedAircraftFilter() {
  const ac = draftScenario?.aircraft?.[selectedAcIndex];
  if (!ac) return;
  // Prefer UI checkboxes if any checked; else filter by selected aircraft label
  const checked = [...document.querySelectorAll(".tfilt:checked")].map((c) => c.dataset.id);
  if (checked.length) {
    map.setTargetFilter(new Set(checked));
  } else {
    map.setTargetFilter(new Set([ac.label]));
  }
}

function countsUpTo(tIndex) {
  const snap = runState?.snapshots?.[tIndex];
  const final = runState?.counts || {};
  if (snap?.counts_at) {
    const c = snap.counts_at;
    return {
      delivered_at_t: c.delivered ?? 0,
      source_binds_at_t: c.source_binds ?? 0,
      bind_only_at_t: c.bind_only ?? final.bind_only ?? 0,
      rejected_at_t: c.rejected ?? 0,
      pending_buffer: c.pending_buffer ?? final.pending_buffer,
      processed_updates_at_t: c.processed_updates ?? 0,
      processed_observations_at_t: c.processed_observations, // may be null = 未提供
      run_total_updates: final.processed_updates || final.processed_hits || 0,
      run_total_delivered: final.delivered || 0,
      atSnapshot: tIndex,
      source: "snapshot.counts_at",
    };
  }
  const now = parseT(snap?.processingTime);
  const ev = runState?.events || [];
  let binds = 0;
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
    source_binds_at_t: binds,
    bind_only_at_t: final.bind_only ?? null,
    rejected_at_t: rejects,
    pending_buffer: final.pending_buffer ?? null,
    processed_updates_at_t: null, // fallback 不可靠 → UI 显示未提供
    processed_observations_at_t: null,
    run_total_updates: final.processed_updates || final.processed_hits || 0,
    run_total_delivered: final.delivered || 0,
    atSnapshot: tIndex,
    source: "fallback_timed_only",
  };
}

function expectedVisibleCount(scenario, snap) {
  const acs = scenario?.aircraft || [];
  if (!acs.length) return "—";
  // Heuristic: aircraft with takeoff_offset <= current elapsed and at least one source enabled
  const t0 = runState?.t0Ms || parseT(runState?.t0);
  const now = parseT(snap?.processingTime);
  const elapsed = t0 && now ? (now - t0) / 1000 : 0;
  return acs.filter((a) => {
    const srcs = enabledSources(a);
    if (!srcs.length) return false;
    return (a.takeoff_offset_s || 0) <= elapsed + 0.05;
  }).length;
}

function activeSourcesOnTrack(tr, snapTime) {
  // Algorithm snapshot `sources` is the active set; do not invent from stale sourceTracks.
  if (Array.isArray(tr.sources) && tr.sources.length) {
    return [...new Set(tr.sources.filter(Boolean))];
  }
  const now = parseT(snapTime);
  const rows = tr.sourceTracks || [];
  const fresh = rows.filter((s) => {
    const st = String(s.bindingStatus || "").toLowerCase();
    if (st.includes("expir") || st === "candidate" || st.includes("候选")) return false;
    if (!now) return st.includes("confirm") || st.includes("bound") || st.includes("active");
    const seen = parseT(s.lastSeen);
    if (!seen) return false;
    return now - seen <= 12000; // stale / historical beyond ~12s → not active
  });
  return [...new Set(fresh.map((s) => s.source).filter(Boolean))];
}

function historicalSourceRows(tr, snapTime) {
  const active = new Set(activeSourcesOnTrack(tr, snapTime));
  const now = parseT(snapTime);
  return (tr.sourceTracks || []).filter((s) => {
    if (!s.source) return false;
    if (!active.has(s.source)) return true;
    const seen = parseT(s.lastSeen);
    if (now && seen && now - seen > 12000) return true;
    const st = String(s.bindingStatus || "").toLowerCase();
    return st === "candidate" || st.includes("expir");
  });
}

function primaryPositionSource(tr) {
  // Direct field from algorithm — do not guess RID priority on the client
  if (tr.positionSource) return tr.positionSource;
  if (tr.primaryPositionSource) return tr.primaryPositionSource;
  return "—";
}

function evalVerdict(ev) {
  if (!ev) return "—";
  return ev.entity_check?.status || ev.verdict || ev.status || "—";
}

function matchTrackForAircraft(ac, tracks, run) {
  const sn = ac.rid_sn;
  const truth = ac.truth_id;
  let hit = tracks.find((t) => sn && t.aircraftId === sn);
  if (hit) return hit;
  // Explicit display/eval mapping from run (never invent via opaque sourceTrackId substrings)
  const f2t = run?.evaluation?.fusion_to_truth || {};
  if (truth) {
    const fid = Object.keys(f2t).find((k) => f2t[k] === truth);
    if (fid) {
      hit = tracks.find((t) => t.fusionId === fid);
      if (hit) return hit;
    }
  }
  const lab = ac.label;
  if (map.displayIndex?.get(lab)?.fusionIds) {
    for (const t of tracks) {
      if (map.displayIndex.get(lab).fusionIds.has(t.fusionId)) return t;
    }
  }
  return null;
}

function renderResultPanels() {
  const snap = runState?.snapshots?.[map.tIndex];
  const tracks = snap?.tracks || [];
  const scenario = runState?.scenario || draftScenario;
  const exp = expectedVisibleCount(scenario, snap);
  const algoN = tracks.length;
  const sum = document.getElementById("resultSummary");
  const pt = snap?.processingTime;
  const targetLines = tracks.map((tr) => {
    const srcs = activeSourcesOnTrack(tr, pt).map((s) => SRC_LABEL[s] || s).join("+") || "—";
    const hist = historicalSourceRows(tr, pt);
    const histTxt = hist.length
      ? ` · 历史/候选=${hist.map((s) => `${SRC_LABEL[s.source] || s.source}:${s.bindingStatus || "?"}`).join(",")}`
      : "";
    const prim = SRC_LABEL[primaryPositionSource(tr)] || primaryPositionSource(tr);
    const name = tr.aircraftId || map._readableName?.(tr) || "(匿名)";
    const short = String(tr.fusionId || "").split(/[-_]/).pop()?.slice(-6) || "";
    return `<div>${name}${short ? " · " + short : ""}：活跃源=${srcs} · 主位置=${prim}${histTxt}</div>`;
  }).join("");
  const ev = runState?.evaluation;
  const verdict = evalVerdict(ev);
  sum.innerHTML = [
    `<div>当前时刻：预期可见 <b>${exp}</b> · 算法目标 <b>${algoN}</b></div>`,
    `<div class="muted">整次评估（仿真，非现场准确率）：<b>${verdict}</b>${ev?.entity_check?.ok === false ? " · ok=false" : ""}</div>`,
    targetLines || `<div class="muted">无目标</div>`,
  ].join("");

  const body = document.getElementById("acResultBody");
  const acs = scenario?.aircraft || [];
  body.innerHTML = acs.map((a, i) => {
    const tr = matchTrackForAircraft(a, tracks, runState);
    const expSrc = enabledSources(a).map((s) => SRC_LABEL[s] || s).join("+") || "—";
    const actSrc = tr ? activeSourcesOnTrack(tr, pt).map((s) => SRC_LABEL[s] || s).join("+") : "—";
    const fid = tr?.fusionId ? String(tr.fusionId).split(/[-_]/).pop()?.slice(-8) : "—";
    const st = tr ? (tr.positionMode || "active") : "未见";
    return `<tr class="${i === selectedAcIndex ? "sel" : ""}" data-i="${i}">
      <td>${a.label}</td><td>${expSrc}</td><td>${actSrc}</td><td title="${tr?.fusionId || ""}">${fid}</td><td>${st}</td></tr>`;
  }).join("") || `<tr><td colspan="5" class="hint">无飞机</td></tr>`;
  body.querySelectorAll("tr[data-i]").forEach((tr) => {
    tr.onclick = () => {
      selectedAcIndex = Number(tr.dataset.i);
      renderAircraftList();
      openDrawerForSelected();
      applySelectedAircraftFilter();
    };
  });

  renderAnomalies();
}

function formatEvalIssue(iss, kind) {
  if (kind === "false_merge") {
    const ids = (iss.truth_ids || []).join("/");
    return `误关联 ${iss.fusionId || ""}：${ids}${iss.via ? " via " + iss.via : ""}${iss.at ? " @ " + iss.at : ""}`;
  }
  if (kind === "attribution") {
    return `归属错误 ${iss.fusionId || ""}：${iss.reason || ""} ${iss.sourceKey || ""} → ${(iss.obs_truths || iss.truths || []).join("/")}${iss.at ? " @ " + iss.at : ""}`;
  }
  if (kind === "duplicate") {
    return `重复目标 ${iss.truth_id}：${(iss.fusionIds || []).join(",")}${iss.at ? " @ " + iss.at : ""}`;
  }
  if (kind === "detail") {
    return `${iss.error || iss.note || "评估明细"} ${iss.truth_id || ""} ${iss.fusionId || ""}${iss.at ? " @ " + iss.at : ""}`;
  }
  return iss.message || iss.detail || JSON.stringify(iss).slice(0, 140);
}

function renderAnomalies() {
  const ul = document.getElementById("anomalyList");
  const snap = runState?.snapshots?.[map.tIndex];
  const now = parseT(snap?.processingTime);
  const items = [];
  const ev = runState?.evaluation || {};

  for (const fm of ev.false_merges || []) {
    items.push({ e: fm, t: parseT(fm.at), text: formatEvalIssue(fm, "false_merge"), seek: fm.at, fid: fm.fusionId });
  }
  for (const ae of ev.attribution_errors || []) {
    items.push({ e: ae, t: parseT(ae.at), text: formatEvalIssue(ae, "attribution"), seek: ae.at, fid: ae.fusionId });
  }
  for (const d of ev.duplicate_targets || []) {
    items.push({ e: d, t: parseT(d.at), text: formatEvalIssue(d, "duplicate"), seek: d.at });
  }
  for (const u of ev.undetermined || []) {
    items.push({ e: u, t: parseT(u.at), text: `未判定 ${u.reason || ""} ${u.fusionId || ""}`, seek: u.at, fid: u.fusionId });
  }
  for (const d of ev.entity_check?.details || []) {
    if (d.ok === true) continue;
    if (!d.error && !d.note) continue;
    items.push({ e: d, t: parseT(d.at), text: formatEvalIssue(d, "detail"), seek: d.at, fid: d.fusionId });
  }

  for (const e of runState?.events || []) {
    const t = parseT(e.time || e.eventTime || e.ts);
    if (t && now && t > now + 1) continue;
    const typ = e.type || e.eventType || "";
    if (/mis|wrong|conflict|anomaly|fail|unbind|ambigu|jump_reject|identity_hard/i.test(typ) || e.severity || e.level === "error") {
      items.push({ e, t, text: formatAnomaly(e), seek: e.time || e.eventTime, fid: e.fusionId });
    }
  }
  // de-dupe by text
  const seen = new Set();
  const uniq = [];
  for (const it of items) {
    if (seen.has(it.text)) continue;
    seen.add(it.text);
    uniq.push(it);
  }
  if (!uniq.length) {
    ul.innerHTML = `<li class="hint">当前时刻无明显异常条目</li>`;
    return;
  }
  ul.innerHTML = uniq.slice(-40).map((it, idx) =>
    `<li data-ai="${idx}" data-seek="${it.seek || ""}" data-t="${it.t || ""}" data-fid="${it.fid || ""}">${it.text}</li>`
  ).join("");
  ul.querySelectorAll("li[data-ai]").forEach((li) => {
    li.onclick = () => {
      if (!runState?.snapshots) return;
      const seekIso = li.dataset.seek;
      const t = seekIso ? parseT(seekIso) : Number(li.dataset.t);
      if (!t) return;
      let best = 0, bestD = Infinity;
      runState.snapshots.forEach((s, i) => {
        const d = Math.abs(parseT(s.processingTime) - t);
        if (d < bestD) { bestD = d; best = i; }
      });
      map.setTimeIndex(best);
      const fid = li.dataset.fid;
      if (fid && runState.snapshots[best]?.tracks) {
        const tr = runState.snapshots[best].tracks.find((x) => x.fusionId === fid);
        if (tr) pinnedDetail = tr;
      }
      updateTransport();
      renderResultPanels();
    };
  });
}

function formatAnomaly(e) {
  const typ = e.type || e.eventType || "event";
  const p = e.payload || e.detail || {};
  const bits = [typ];
  const key = p.key || e.sourceTrackId || p.sourceTrackId;
  if (key) bits.push(key);
  if (p.sourceTrackId && p.sourceTrackId !== key) bits.push(p.sourceTrackId);
  if (p.aircraftId || e.aircraftId) bits.push("→" + (p.aircraftId || e.aircraftId));
  if (e.fusionId) bits.push(String(e.fusionId).slice(-8));
  if (p.dist != null) bits.push(`dist=${Number(p.dist).toFixed?.(1) ?? p.dist}`);
  if (p.innov != null) bits.push(`innov=${Number(p.innov).toFixed?.(2) ?? p.innov}`);
  if (e.time || e.eventTime) bits.push("@" + (e.time || e.eventTime));
  if (e.message) bits.push(e.message);
  return bits.join(" ");
}

function updateTransport() {
  if (!runState?.snapshots?.length) {
    const seek = document.getElementById("seek");
    if (seek) { seek.max = "0"; seek.value = "0"; }
    const sl = document.getElementById("seekLabel");
    if (sl) sl.textContent = "0/0";
    const clock = document.getElementById("clock");
    if (clock) clock.textContent = "无当前运行／预览";
    const counts = document.getElementById("counts");
    if (counts) counts.textContent = "—";
    const events = document.getElementById("events");
    if (events) events.textContent = "—";
    return;
  }
  const seek = document.getElementById("seek");
  seek.max = String(Math.max(0, runState.snapshots.length - 1));
  seek.value = String(map.tIndex);
  document.getElementById("seekLabel").textContent = `${map.tIndex + 1}/${runState.snapshots.length}`;
  const snap = runState.snapshots[map.tIndex];
  if (runState.preview_sample) {
    const nObs = (runState.observations || []).length;
    document.getElementById("clock").textContent =
      `原始观测预览时刻=${snap?.processingTime || "—"} · 未执行融合 · 样本 ${runState.t0 || "—"} → ${nObs ? (runState.observations[nObs - 1].measurementTime) : "—"}`;
    document.getElementById("counts").textContent =
      `预览样本点数=${nObs}／帧=${map.tIndex + 1}/${runState.snapshots.length}／融合主位置更新=不适用／来源绑定=不适用／拒绝=见导入报告`;
  } else {
  let lastMeas = "—";
  for (const tr of snap?.tracks || []) {
    if (tr.lastObservedAt && (lastMeas === "—" || String(tr.lastObservedAt) > lastMeas)) lastMeas = tr.lastObservedAt;
  }
  document.getElementById("clock").textContent =
    `播放时刻(processingTime)=${snap?.processingTime || "—"} · 已提交水位(watermark)=${snap?.watermark || "—"} · 最后实测=${lastMeas}`;
  const c = countsUpTo(map.tIndex);
  const procObs = c.processed_observations_at_t;
  const procObsTxt = procObs == null ? "未提供可靠计数" : String(procObs);
  document.getElementById("counts").textContent =
    `观测接收=${c.delivered_at_t ?? "—"}／快照帧索引=${map.tIndex}（≠处理批）／` +
    `已处理观测数=${procObsTxt}／主位置更新(至本帧)=${c.processed_updates_at_t ?? "—"}／` +
    `来源新绑定(source_bound)=${c.source_binds_at_t ?? "—"}／仅绑定(secondary_bind_only)=${c.bind_only_at_t ?? "—"}／` +
    `缓冲=${c.pending_buffer ?? "未提供"}／拒绝=${c.rejected_at_t ?? "—"}` +
    `（分列，勿互比当漏数）`;
  }
  const now = parseT(snap?.processingTime);
  const ev = (runState.events || []).filter((e) => {
    const t = parseT(e.time || e.eventTime || e.ts);
    return !t || t <= now + 1;
  }).slice(-40);
  document.getElementById("events").textContent = ev.map((e) => e.type || JSON.stringify(e)).join(", ") || "—";
  let tr = null;
  const pinKind = pinnedDetail?.source && !pinnedDetail?.fusionId ? "obs" : "track";
  if (pinKind === "obs" && pinnedDetail) {
    // Observation pin: keep only if id belongs to this run's observations
    const oid = pinnedDetail.observationId;
    const inRun = !oid || (runState.observations || []).some((o) => o.observationId === oid);
    if (inRun) {
      renderInspector(pinnedDetail, "obs");
      document.getElementById("detail").textContent = JSON.stringify({ kind: "obs@clock", ...pinnedDetail }, null, 2);
      document.getElementById("assoc").innerHTML =
        `<div>观测 ${pinnedDetail.source} / ${pinnedDetail.sourceTrackId} / ${pinnedDetail.aircraftId || "-"}</div>`;
      renderResultPanels();
      return;
    }
    pinnedDetail = null;
  }
  if (pinnedDetail?.fusionId && snap?.tracks) {
    tr = snap.tracks.find((t) => t.fusionId === pinnedDetail.fusionId) || null;
  }
  if (!tr && map.targetFilter?.size && snap?.tracks) {
    tr = snap.tracks.find((t) => map._allowedByFilter("fusion", t)) || null;
  }
  // Do not auto-pick first track when pin cleared — empty means empty.
  if (tr) {
    pinnedDetail = tr;
    renderInspector(tr, "track");
    document.getElementById("detail").textContent = JSON.stringify({ kind: "track@clock", ...tr }, null, 2);
    const rows = (tr.sourceTracks || []).map((s) =>
      `<div>${s.source} · ${s.sourceTrackId} · ${s.aircraftId || "-"} · ${s.bindingStatus || "?"}</div>`
    );
    document.getElementById("assoc").innerHTML = rows.join("") || "无";
  } else {
    // Inline clear so function-level VM probes (only updateTransport) still wipe stale panels.
    const msg = "当前时刻无目标";
    const inspector = document.getElementById("inspector");
    const explain = document.getElementById("explainAssoc");
    const detail = document.getElementById("detail");
    const assoc = document.getElementById("assoc");
    if (inspector) inspector.innerHTML = msg;
    if (explain) explain.innerHTML = msg;
    if (detail) detail.textContent = msg;
    if (assoc) assoc.innerHTML = "无";
    pinnedDetail = null;
  }
  renderResultPanels();
}

function clearInspectorPanels(msg) {
  const text = msg || "当前时刻无目标";
  const inspector = document.getElementById("inspector");
  const explain = document.getElementById("explainAssoc");
  const detail = document.getElementById("detail");
  const assoc = document.getElementById("assoc");
  if (inspector) inspector.innerHTML = text;
  if (explain) explain.innerHTML = text;
  if (detail) detail.textContent = text;
  if (assoc) assoc.innerHTML = "无";
}

function updateRunBanner(result, { stale = false } = {}) {
  const el = document.getElementById("runBanner");
  if (!el) return;
  const scName = result?.scenario?.name || result?.runScenarioName || "—";
  const rid = result?.runId || result?.sessionId || "—";
  const idMode = result?.scenario?.identity_mode || result?.identity_audit?.identity_mode || "—";
  const profile = result?.fusionProfile ? ` · profile=${result.fusionProfile}` : "";
  const ver = result?.algorithmVersion ? ` · ${result.algorithmVersion}` : "";
  const realFile = !!(result?.import_summary || result?.real_file);
  if (realFile) {
    el.textContent = stale
      ? `旧文件运行（未替换）：${scName}`
      : `当前文件：${scName} · runId=${rid} · 融合输出${profile}${ver}`;
  } else if (result?.preview_sample) {
    el.textContent = `原始观测预览，未执行融合 · ${scName}`;
  } else {
    el.textContent = stale
      ? `旧运行（未替换）：场景=${scName} · runId=${rid} · identity_mode=${idMode}`
      : `当前运行结果：场景=${scName} · runId=${rid} · identity_mode=${idMode}${profile}${ver}${result?.fusionProfile === "multisensor-v1" ? "" : ` · 草稿=${draftScenario?.name || "—"}`}`;
  }
  el.dataset.runId = rid;
  el.dataset.scenario = scName;
}

function renderMetricsDisplay(result) {
  const box = document.getElementById("metricsDisplay");
  if (!box) return;
  const md = result?.evaluation?.metrics_display;
  const verd = evalVerdict(result?.evaluation);
  if (!md) {
    box.innerHTML = `<div>指标：未提供 metrics_display</div><div>整次评估：${verd}</div>`;
    return;
  }
  const cov = md.last_snapshot_entity_coverage ?? md.association_coverage;
  const rmse = md.position_rmse_m_committed;
  const rmseD = md.position_rmse_m_display;
  const idEx = md.id_exchange_count;
  const idExTxt = idEx == null ? "不可计算" : String(idEx);
  const recre = md.recreate_count;
  const recreTxt = recre == null ? "不可计算" : String(recre);
  box.innerHTML = [
    `<div><b>整次评估</b>：${verd}（硬错误保留原始 FAIL；能力边界不覆盖）</div>`,
    `<div>目标数=${md.n_targets_last_snapshot ?? "—"} · 误合并=${md.false_merge_count ?? "—"} · 拆轨/重复=${md.duplicate_target_count ?? "—"} · ID交换=${idExTxt} · 重建=${recreTxt} · 错绑=${md.hard_attribution_error_count ?? "—"}</div>`,
    `<div class="muted">${md.id_exchange_note || ""}</div>`,
    `<div>末快照实体覆盖率=${cov == null ? "不可计算" : (cov * 100).toFixed(1) + "%"} · ${md.last_snapshot_entity_coverage_note || md.association_coverage_note || ""}</div>`,
    `<div>二维RMSE(已提交末点)=${rmse == null ? "不可计算" : Number(rmse).toFixed(2) + " m"} · ${md.position_rmse_note || ""}</div>`,
    `<div>二维RMSE(展示预测)=${rmseD == null ? "不可计算" : Number(rmseD).toFixed(2) + " m"} · ${md.position_rmse_display_note || ""}</div>`,
    `<div class="muted">${md.denominator_note || ""}</div>`,
  ].join("");
}

function showRun(result, { reqToken = null } = {}) {
  if (reqToken != null && reqToken !== runReqSeq) {
    // Stale response must not overwrite newer run.
    return;
  }
  if (playTimer) { clearTimeout(playTimer); playTimer = null; }
  if (runState && runState.runId && runState.runId !== result.runId) {
    staleRunKeep = runState;
  }
  // New run: never keep previous target/obs inspector across runs (R2-04).
  pinnedDetail = null;
  clearInspectorPanels("新运行已加载 · 当前时刻待选择");
  result.runId = result.runId || result.sessionId || `run-${Date.now()}`;
  result.runScenarioName = result.scenario?.name || result.runScenarioName;
  runState = result;
  if (result.t0) runState.t0Ms = parseT(result.t0);
  map.setState(result, { fit: true, resetTime: true });
  updateTransport();
  updateRunBanner(result);
  if (result.preview_sample || result.import_summary || result.real_file) {
    const box = document.getElementById("metricsDisplay");
    if (box) box.innerHTML = `<div>${result.accuracy_note || "真实文件默认无真值，不显示虚假关联准确率"}</div>`;
    if (result.import_summary || result.real_file) enableRawLayersForPreview(result.observations || []);
  } else {
    renderMetricsDisplay(result);
  }
  updateNearDist(result.challenge_geometry, null);
  document.getElementById("eval").textContent = (result.preview_sample || result.import_summary || result.real_file)
    ? (result.accuracy_note || "真实文件默认无真值，不显示虚假关联准确率")
    : (result.evaluation
      ? JSON.stringify(result.evaluation, null, 2)
      : (result.accuracy_note || "无评估／无真值"));
  if (result.scenario?.aircraft) {
    if (!draftScenario) draftScenario = JSON.parse(JSON.stringify(result.scenario));
  }
  renderAircraftList();
  rebuildTargetFilters(result);
}

/* ---------- scenario load / seven default ---------- */

async function fetchSevenFallback() {
  const urls = [
    "/workbench-static/seven_aircraft_combinations.json",
    "/scenarios/seven_aircraft_combinations.json",
  ];
  for (const u of urls) {
    try {
      const r = await fetch(u);
      if (r.ok) return await r.json();
    } catch (_) { /* try next */ }
  }
  return null;
}

async function loadScenarioByName(name, { warnOverwrite = false } = {}) {
  if (warnOverwrite && dirtyDraft) {
    if (!confirm("恢复默认七机将覆盖未保存的编辑，是否继续？")) return false;
  }
  let sc = null;
  try {
    const r = await fetch(api + `/v1/workbench/scenarios/${encodeURIComponent(name)}`);
    if (r.ok) sc = await r.json();
  } catch (_) { /* fall through */ }
  if (!sc && name === DEFAULT_SCENARIO) {
    sc = await fetchSevenFallback();
  }
  if (!sc) {
    setStatus(false, `场景 ${name} 不可用`);
    return false;
  }
  draftScenario = sc;
  dirtyDraft = false;
  document.getElementById("seed").value = draftScenario.seed ?? 20261019;
  document.getElementById("duration").value = draftScenario.duration_s ?? 40;
  const sel = document.getElementById("scenarioSelect");
  if (sel && ![...sel.options].some((o) => o.value === name)) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name + (sc.notes ? " — " + String(sc.notes).slice(0, 28) : "");
    sel.appendChild(opt);
  }
  if (sel) sel.value = name;
  selectedAcIndex = 0;
  renderAircraftList();
  openDrawerForSelected();
  // Draft changed: keep previous run visible only as stale (R1-06).
  if (runState) {
    staleRunKeep = runState;
    updateRunBanner(runState, { stale: true });
    const b = document.getElementById("runBanner");
    if (b) b.textContent += ` · 草稿已切换为 ${sc.name || name}（尚未运行）`;
  } else {
    const b = document.getElementById("runBanner");
    if (b) b.textContent = `草稿场景=${sc.name || name} · 尚未运行`;
  }
  return true;
}

async function loadScenarioList() {
  const sel = document.getElementById("scenarioSelect");
  let scenarios = [];
  try {
    const r = await fetch(api + "/v1/workbench/scenarios");
    const j = await r.json();
    scenarios = j.scenarios || [];
  } catch (_) { /* offline */ }
  const names = new Set(scenarios.map((s) => s.name));
  if (!names.has(DEFAULT_SCENARIO)) {
    scenarios = [{ name: DEFAULT_SCENARIO, notes: "默认七机组合（本地回退）" }, ...scenarios];
  }
  if (!names.has("three_aircraft_primary")) {
    scenarios.push({ name: "three_aircraft_primary", notes: "原三机预置" });
  }
  // ensure three stays in list; seven first
  scenarios.sort((a, b) => {
    if (a.name === DEFAULT_SCENARIO) return -1;
    if (b.name === DEFAULT_SCENARIO) return 1;
    if (a.name === "three_aircraft_primary") return -1;
    if (b.name === "three_aircraft_primary") return 1;
    return a.name.localeCompare(b.name);
  });
  sel.innerHTML = scenarios.map((s) =>
    `<option value="${s.name}">${s.name}${s.notes ? " — " + String(s.notes).slice(0, 28) : ""}</option>`
  ).join("");
  sel.value = DEFAULT_SCENARIO;
}

function renderAircraftList() {
  const ul = document.getElementById("acList");
  const acs = draftScenario?.aircraft || [];
  document.getElementById("acCountHint").textContent = acs.length ? `(${acs.length})` : "";
  ul.innerHTML = acs.map((a, i) => {
    const srcs = enabledSources(a);
    const status = srcs.length ? "可运行" : "无源";
    const anon = !a.rid_sn && srcs.includes("radar") ? "匿名" : (a.rid_sn || "—");
    return `<li class="ac-item ${i === selectedAcIndex ? "selected" : ""}" data-i="${i}">
      <span class="lab">${a.label}</span>
      <span class="meta">${anon} · ${status}</span>
      <span class="chip-row">${sourceChipsHtml(a)}</span>
    </li>`;
  }).join("") || `<li class="hint">无飞机 — 点「恢复默认七机」或添加</li>`;
  ul.querySelectorAll(".ac-item").forEach((li) => {
    li.onclick = () => {
      commitDrawerToDraft();
      const idx = Number(li.dataset.i);
      // click same selected row again → clear canvas filter (show all)
      if (idx === selectedAcIndex && map.targetFilter?.size === 1) {
        map.setTargetFilter(null);
        document.querySelectorAll(".tfilt").forEach((c) => { c.checked = false; });
        openDrawerForSelected();
        map.draw();
        return;
      }
      selectedAcIndex = idx;
      renderAircraftList();
      openDrawerForSelected();
      applySelectedAircraftFilter();
      map.draw();
    };
  });
}

function openDrawerForSelected() {
  const drawer = document.getElementById("acDrawer");
  const ac = draftScenario?.aircraft?.[selectedAcIndex];
  if (!ac) {
    drawer.classList.add("hidden");
    return;
  }
  drawer.classList.remove("hidden");
  document.getElementById("drawerTitle").textContent = `编辑飞机 ${ac.label}`;
  renderDrawerTabs(ac);
}

document.getElementById("btnCloseDrawer").onclick = () => {
  commitDrawerToDraft();
  document.getElementById("acDrawer").classList.add("hidden");
};

const TAB_IDS = { basic: "tabBasic", route: "tabRoute", sensor: "tabSensor", fault: "tabFault" };
document.querySelectorAll(".dtab").forEach((btn) => {
  btn.onclick = () => {
    commitDrawerToDraft();
    document.querySelectorAll(".dtab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const tab = btn.dataset.tab;
    Object.entries(TAB_IDS).forEach(([t, id]) => {
      document.getElementById(id).classList.toggle("hidden", t !== tab);
    });
  };
});

function renderDrawerTabs(ac) {
  const src = (s) => ac.sources?.[s] || {};
  document.getElementById("tabBasic").innerHTML = `
    <label>标签 <input data-f="label" value="${ac.label || ""}"/></label>
    <label>可信仿真 SN <input data-f="rid_sn" value="${ac.rid_sn || ""}" placeholder="匿名单源可留空"/></label>
    <label>truth_id（仅评估） <input data-f="truth_id" value="${ac.truth_id || ""}"/></label>
    <label>速度 m/s（航线仿真，≠设备上报速度） <input type="number" data-f="speed_mps" value="${ac.speed_mps ?? 10}" step="0.5"/></label>
    <label>起飞偏移 s <input type="number" data-f="takeoff_offset_s" value="${ac.takeoff_offset_s ?? 0}" step="0.5"/></label>
  `;
  document.getElementById("tabRoute").innerHTML = `
    <label>航点 JSON [{x_m,y_m,dwell_s}]
      <textarea data-f="waypoints" rows="4">${JSON.stringify(ac.waypoints || [], null, 0)}</textarea>
    </label>
    <div class="route-btns">
      <button type="button" id="btnRouteAdd">画布加点</button>
      <button type="button" id="btnRouteDel">删末点</button>
      <button type="button" id="btnRouteDone">结束画线</button>
    </div>
    <p class="hint">在画布点击加点、拖动改点；改完须「生成并融合」。</p>
  `;
  document.getElementById("tabSensor").innerHTML = `
    <div class="src-enable-row">
      ${["rid", "spectrum", "radar"].map((s) => `
        <label><input type="checkbox" data-k="enabled" data-src="${s}" ${src(s).enabled ? "checked" : ""}/> ${SRC_LABEL[s]} 数据源</label>
      `).join("")}
    </div>
    <p class="hint">以下为各源周期／噪声（算法输入参数，不是显示图层）。</p>
    ${["rid", "spectrum", "radar"].map((s) => `
      <details class="srcblk" ${src(s).enabled ? "open" : ""}>
        <summary>${SRC_LABEL[s]} 参数</summary>
        <label>周期s <input type="number" data-k="period_s" data-src="${s}" value="${src(s).period_s ?? 1}" step="0.1"/></label>
        <label>噪声m <input type="number" data-k="pos_noise_m" data-src="${s}" value="${src(s).pos_noise_m ?? 5}" step="0.1"/></label>
        <label>东偏m <input type="number" data-k="bias_east_m" data-src="${s}" value="${src(s).bias_east_m ?? 0}" step="0.1"/></label>
        <label>北偏m <input type="number" data-k="bias_north_m" data-src="${s}" value="${src(s).bias_north_m ?? 0}" step="0.1"/></label>
        <label><input type="checkbox" data-k="emit_aircraft_id" data-src="${s}" ${src(s).emit_aircraft_id !== false ? "checked" : ""}/> 上报身份 aircraftId（雷达通常关闭）</label>
      </details>
    `).join("")}
  `;
  document.getElementById("tabFault").innerHTML = `
    <p class="hint">高级模拟：未填写表示未配置（换号 null＝不换号）。</p>
    ${["rid", "spectrum", "radar"].map((s) => `
      <details class="srcblk">
        <summary>${SRC_LABEL[s]} 故障</summary>
        <label>延迟s <input type="number" data-k="delay_s" data-src="${s}" value="${src(s).delay_s ?? 0}" step="0.1"/></label>
        <label>丢点概率 <input type="number" data-k="drop_prob" data-src="${s}" value="${src(s).drop_prob ?? 0}" step="0.05" min="0" max="1"/></label>
        <label>乱序窗s <input type="number" data-k="reorder_window_s" data-src="${s}" value="${src(s).reorder_window_s ?? 0}" step="0.1"/></label>
        <label>时钟偏差s <input type="number" data-k="clock_bias_s" data-src="${s}" value="${src(s).clock_bias_s ?? 0}" step="0.1"/></label>
        <label>雷达换号时刻s <input type="number" data-k="radar_id_swap_at_s" data-src="${s}" value="${src(s).radar_id_swap_at_s ?? ""}" step="1" placeholder="空=不换号"/></label>
        <label>失联 outage [[a,b],…] <input type="text" data-k="outage" data-src="${s}" value='${JSON.stringify(src(s).outage || [])}'/></label>
      </details>
    `).join("")}
  `;
  wireRouteButtons();
  // mark dirty on input
  document.getElementById("acDrawer").querySelectorAll("input, textarea").forEach((el) => {
    el.addEventListener("change", () => { dirtyDraft = true; });
  });
  // source enable immediate chip refresh
  document.getElementById("tabSensor").querySelectorAll('[data-k="enabled"]').forEach((cb) => {
    cb.onchange = () => {
      commitDrawerToDraft();
      renderAircraftList();
      openDrawerForSelected();
    };
  });
}

function wireRouteButtons() {
  const add = document.getElementById("btnRouteAdd");
  const del = document.getElementById("btnRouteDel");
  const done = document.getElementById("btnRouteDone");
  if (add) add.onclick = () => {
    commitDrawerToDraft();
    const ac = draftScenario?.aircraft?.[selectedAcIndex];
    if (!ac) return alert("请先选择飞机");
    map.startRouteEdit(ac.waypoints || [], (pts) => {
      ac.waypoints = pts;
      dirtyDraft = true;
      const ta = document.querySelector('#tabRoute textarea[data-f="waypoints"]');
      if (ta) ta.value = JSON.stringify(pts);
    });
    setStatus(true, `画线中：${ac.label}（点击加点／拖动改点）`);
  };
  if (del) del.onclick = () => {
    if (!map.routeEdit?.points?.length) return;
    map.routeEdit.points.pop();
    map.draw();
    if (map.routeEdit.onChange) map.routeEdit.onChange(map.routeEdit.points);
  };
  if (done) done.onclick = () => {
    map.stopRouteEdit();
    setStatus(true, "画线结束");
  };
}

function commitDrawerToDraft() {
  if (!draftScenario) return null;
  draftScenario.seed = Number(document.getElementById("seed").value);
  draftScenario.duration_s = Number(document.getElementById("duration").value);
  const name = document.getElementById("scenarioSelect").value;
  if (name) draftScenario.name = name;
  const ac = draftScenario.aircraft?.[selectedAcIndex];
  if (!ac) return draftScenario;
  const drawer = document.getElementById("acDrawer");
  if (drawer.classList.contains("hidden")) return draftScenario;
  const getF = (f) => drawer.querySelector(`[data-f="${f}"]`);
  if (getF("label")) ac.label = getF("label").value;
  if (getF("truth_id")) ac.truth_id = getF("truth_id").value;
  if (getF("rid_sn")) ac.rid_sn = getF("rid_sn").value || null;
  if (getF("speed_mps")) ac.speed_mps = Number(getF("speed_mps").value);
  if (getF("takeoff_offset_s")) ac.takeoff_offset_s = Number(getF("takeoff_offset_s").value);
  const wp = getF("waypoints");
  if (wp) {
    try { ac.waypoints = JSON.parse(wp.value); } catch (_) { /* keep */ }
  }
  ac.sources = ac.sources || {};
  for (const src of ["rid", "spectrum", "radar"]) {
    const base = ac.sources[src] || { enabled: false };
    const get = (k) => drawer.querySelector(`[data-k="${k}"][data-src="${src}"]`);
    const en = get("enabled");
    if (en) base.enabled = !!en.checked;
    const emitId = get("emit_aircraft_id");
    if (emitId) base.emit_aircraft_id = !!emitId.checked;
    for (const k of ["period_s", "pos_noise_m", "bias_east_m", "bias_north_m", "delay_s", "drop_prob", "reorder_window_s", "clock_bias_s"]) {
      const inp = get(k);
      if (inp) base[k] = Number(inp.value);
    }
    const swap = get("radar_id_swap_at_s");
    if (swap) base.radar_id_swap_at_s = swap.value === "" ? null : Number(swap.value);
    const out = get("outage");
    if (out) {
      try { base.outage = JSON.parse(out.value || "[]"); } catch (_) { base.outage = []; }
    }
    ac.sources[src] = base;
  }
  return draftScenario;
}

function readEditorIntoDraft() {
  return commitDrawerToDraft();
}

document.getElementById("btnLoadSc").onclick = async () => {
  if (dirtyDraft && !confirm("加载将覆盖未保存编辑，是否继续？")) return;
  const name = document.getElementById("scenarioSelect").value;
  await loadScenarioByName(name);
};

document.getElementById("btnResetSeven").onclick = async () => {
  await loadScenarioByName(DEFAULT_SCENARIO, { warnOverwrite: true });
  setStatus(true, "已恢复默认七机");
};

document.getElementById("btnAddAc").onclick = () => {
  if (!draftScenario) draftScenario = { name: "custom", seed: 1, duration_s: 40, aircraft: [] };
  commitDrawerToDraft();
  const n = draftScenario.aircraft.length + 1;
  const lab = String.fromCharCode(64 + Math.min(n, 26));
  draftScenario.aircraft.push({
    label: lab,
    truth_id: `TRUTH-${lab}`,
    rid_sn: `SN-X-${n}`,
    speed_mps: 12,
    takeoff_offset_s: 0,
    waypoints: [{ x_m: 0, y_m: n * 40, dwell_s: 0 }, { x_m: 300, y_m: n * 40, dwell_s: 0 }],
    sources: {
      rid: { enabled: true, period_s: 1, pos_noise_m: 3, delay_s: 0, drop_prob: 0, reorder_window_s: 0, outage: [], radar_id_swap_at_s: null },
      spectrum: { enabled: false, period_s: 1, pos_noise_m: 8, delay_s: 0, drop_prob: 0, reorder_window_s: 0, outage: [], radar_id_swap_at_s: null },
      radar: { enabled: false, period_s: 2, pos_noise_m: 15, delay_s: 0, drop_prob: 0, reorder_window_s: 0, outage: [], radar_id_swap_at_s: null },
    },
  });
  dirtyDraft = true;
  selectedAcIndex = draftScenario.aircraft.length - 1;
  renderAircraftList();
  openDrawerForSelected();
};

document.getElementById("btnDelSelAc").onclick = () => {
  if (!draftScenario?.aircraft?.length) return;
  commitDrawerToDraft();
  draftScenario.aircraft.splice(selectedAcIndex, 1);
  dirtyDraft = true;
  selectedAcIndex = Math.max(0, selectedAcIndex - 1);
  renderAircraftList();
  openDrawerForSelected();
};

document.getElementById("btnSaveSc").onclick = async () => {
  const sc = readEditorIntoDraft();
  if (!sc) return alert("请先加载场景");
  const name = prompt("保存名称", sc.name || "custom_scenario");
  if (!name) return;
  const r = await fetch(api + "/v1/workbench/scenarios/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, scenario: sc }),
  });
  const j = await r.json();
  setStatus(r.ok, r.ok ? `saved ${j.name}` : `save fail ${r.status}`);
  dirtyDraft = false;
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
  // Import custom JSON as-is — do NOT auto-append seven aircraft
  draftScenario = JSON.parse(await f.text());
  dirtyDraft = true;
  document.getElementById("seed").value = draftScenario.seed;
  document.getElementById("duration").value = draftScenario.duration_s;
  selectedAcIndex = 0;
  renderAircraftList();
  openDrawerForSelected();
  setStatus(true, `已导入 ${draftScenario.name || f.name}（未追加七机）`);
  e.target.value = "";
};

document.getElementById("btnRunSim").onclick = async () => {
  const body = {
    scenarioName: document.getElementById("scenarioSelect").value || DEFAULT_SCENARIO,
    mode: document.getElementById("runMode").value,
    seed: Number(document.getElementById("seed").value),
  };
  if (draftScenario) {
    body.scenario = readEditorIntoDraft();
  }
  const expectName = body.scenario?.name || body.scenarioName;
  const token = ++runReqSeq;
  const banner = document.getElementById("runBanner");
  if (banner) banner.textContent = `加载中… 请求#${token} 场景=${expectName}（旧结果保留至返回）`;
  setStatus(true, `running #${token}…`);
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
    const gotName = j.scenario?.name || expectName;
    if (gotName && expectName && gotName !== expectName && !body.scenario) {
      setStatus(false, `场景名不一致 expect=${expectName} got=${gotName}`);
    }
    j.runScenarioName = gotName;
    showRun(j, { reqToken: token });
    setStatus(true, `run ${j.sessionId || j.runId} #${token}`);
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

/* ---------- real file panel (TASK-002) ---------- */

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

function clearImportVisualization(reason) {
  if (playTimer) { clearTimeout(playTimer); playTimer = null; }
  pinnedDetail = null;
  clearInspectorPanels(reason || "已清空预览/运行可视化");
  runState = null;
  staleRunKeep = null;
  map.setTargetFilter(null);
  map.setState(
    { observations: [], snapshots: [], final_tracks: [], scenario: { name: "empty", aircraft: [] }, preview_sample: false },
    { fit: false, resetTime: true }
  );
  updateTransport();
  maybeWarnRawLayersHidden();
  const banner = document.getElementById("runBanner");
  if (banner) banner.textContent = reason || "无当前运行";
  const evalEl = document.getElementById("eval");
  if (evalEl) evalEl.textContent = reason || "无评估／无真值";
}

function buildPreviewSnapshots(sample) {
  // Static preview: cover full sample span so all points are drawable.
  // Also emit sparse intermediate snaps so transport can scrub/play to end.
  const snaps = [];
  const n = sample.length;
  const idxs = new Set([0, n - 1]);
  const step = Math.max(1, Math.floor((n - 1) / 12));
  for (let i = 0; i < n; i += step) idxs.add(i);
  const ordered = [...idxs].sort((a, b) => a - b);
  for (const i of ordered) {
    const t = sample[i].measurementTime;
    snaps.push({ processingTime: t, watermark: t, tracks: [], counts_at: {}, preview_frame: true });
  }
  return snaps;
}

function importStatusProse(j) {
  const src = (j && j.detail && typeof j.detail === "object") ? j.detail : (j || {});
  const summary = src.summary && typeof src.summary === "object" ? src.summary : src;
  const name = summary.datasetId || summary.filename || summary.stored_as || summary.path || "未命名文件";
  const container = summary.json_container || summary.suffix || "表格/文本";
  const scanned = summary.scanned_rows ?? summary.scanned ?? "—";
  const valid = summary.n_observations ?? "—";
  const rejected = summary.n_errors ?? summary.error_count ?? "—";
  const by = summary.by_source
    ? Object.entries(summary.by_source).map(([k, v]) => `${k}=${v}`).join("，")
    : "无";
  const tr = Array.isArray(summary.time_range) ? `${summary.time_range[0]} .. ${summary.time_range[1]}` : "无";
  const reasons = [...new Set((summary.errors_sample || []).map((e) => e.reason || e.detail).filter(Boolean))].slice(0, 6);
  let kind = "已读入";
  if (summary.ok === false || summary.error === "json_structure" || String(summary.error || "").startsWith("json_")) {
    kind = "解析失败";
  } else if (summary.empty_record_set) {
    kind = "空文件/空记录集";
  } else if (Number(summary.n_observations || 0) === 0 && Number(summary.n_errors || 0) > 0) {
    kind = "记录已读入，全部被校验拒绝";
  } else if (Number(summary.n_observations || 0) === 0 && Number(summary.skipped_outside_window || 0) > 0) {
    kind = "筛选零匹配";
  }
  return [
    `文件：${name}`,
    `容器：${container}`,
    `结果：${kind}`,
    `扫描=${scanned} 有效=${valid} 拒绝=${rejected}`,
    `来源：${by}`,
    `时间：${tr}`,
    `拒绝原因：${reasons.join("；") || "无"}`,
    summary.detail ? `说明：${summary.detail}` : "",
    summary.error ? `错误：${summary.error}` : "",
  ].filter(Boolean).join("\n");
}

function renderImportPreviewReport(j, { reqToken = null } = {}) {
  if (reqToken != null && reqToken !== runReqSeq) return;
  importMeta = j && j.stored_as ? j : importMeta;
  const box = document.getElementById("importReport");
  const prose = importStatusProse(j);
  if (!j || j.ok === false) {
    clearImportVisualization(j?.error || j?.detail?.error || "预览失败");
    box.textContent = `${prose}\n\n${JSON.stringify(j, null, 2)}`;
    return;
  }
  const sample = [...(j.observations_sample || j.preview || [])].filter((o) => o && o.measurementTime);
  sample.sort((a, b) => parseT(a.measurementTime) - parseT(b.measurementTime));
  const tFirst = sample[0]?.measurementTime || null;
  const tLast = sample[sample.length - 1]?.measurementTime || null;
  box.textContent = `${prose}\n\n${JSON.stringify(
    {
      file_read_ok: j.file_read_ok,
      ok: j.ok,
      n_observations: j.n_observations,
      scanned_rows: j.scanned_rows,
      n_errors: j.n_errors,
      by_source: j.by_source,
      time_range: j.time_range || (tFirst && tLast ? [tFirst, tLast] : null),
      json_container: j.json_container,
      empty_record_set: j.empty_record_set,
      preview_sample_drawn: sample.length,
      preview_mode: "static_sample_cover_end",
      preview_label: "原始观测预览，未执行融合",
      raw_columns: j.raw_columns,
      raw_preview_rows: j.raw_preview_rows,
      sample_errors: j.errors_sample,
      stored_as: j.stored_as,
      preview_only: j.preview_only,
      truncated: j.truncated,
      note: "预览行有限额；全量扫描见 reports/task006，不等于本预览行数",
    },
    null,
    2
  )}`;
  if (!sample.length) {
    const emptyKind = j.empty_record_set
      ? "空文件/空记录集"
      : (Number(j.n_errors || 0) > 0 ? "记录已读入，全部被校验拒绝" : "筛选零匹配");
    clearImportVisualization(emptyKind);
    return;
  }
  // Prefer full preview summary sources so layers match file content, not just sample slice.
  const layerSample = sample.slice();
  for (const src of Object.keys(j.by_source || {})) {
    if (["rid", "spectrum", "radar"].includes(src) && !layerSample.some((o) => o.source === src)) {
      layerSample.push({ source: src });
    }
  }
  enableRawLayersForPreview(layerSample);
  showRun(
    {
      runId: `preview-${reqToken ?? Date.now()}`,
      scenario: { name: (j.stored_as || "import-preview") + " · 原始观测预览", aircraft: [] },
      observations: sample,
      snapshots: buildPreviewSnapshots(sample),
      final_tracks: [],
      evaluation: null,
      t0: tFirst,
      preview_sample: true,
      accuracy_note: "原始观测预览，未执行融合",
    },
    { reqToken }
  );
  // Unified seek: canvas + transport/clock/seek label stay in sync at sample end.
  const nSnap = (map.state?.snapshots || []).length;
  if (nSnap > 0) seekToFrame(nSnap - 1);
  maybeWarnRawLayersHidden();
  const banner = document.getElementById("runBanner");
  if (banner) {
    banner.textContent = `原始观测预览，未执行融合 · ${j.stored_as || ""} · 样本点=${sample.length} · 来源层已按样本开启`;
  }
}

document.getElementById("btnPreview").onclick = async () => {
  const f = document.getElementById("fileInput").files[0];
  if (!f) { alert("请选择文件"); return; }
  const token = ++runReqSeq;
  const fd = new FormData();
  fd.append("file", f);
  fd.append("mapping_json", JSON.stringify(mappingFromForm()));
  fd.append("max_rows", String(Number(document.getElementById("maxRows").value || 2000)));
  document.getElementById("importReport").textContent = "上传并预览中…";
  clearImportVisualization("新上传预览进行中…");
  try {
    const r = await fetch(api + "/v1/workbench/import/preview", { method: "POST", body: fd });
    let j;
    try { j = await r.json(); } catch (_) { j = { ok: false, error: `HTTP ${r.status}` }; }
    if (!r.ok) {
      j.ok = false;
      j.error = j.error || j.detail?.error || `HTTP ${r.status}`;
    }
    renderImportPreviewReport(j, { reqToken: token });
  } catch (err) {
    if (token !== runReqSeq) return;
    clearImportVisualization("预览请求失败");
    document.getElementById("importReport").textContent = `预览请求失败：${err.message || err}`;
  }
};

let localSelectedPath = null;
document.getElementById("btnLocalPreview")?.addEventListener("click", async () => {
  if (!localSelectedPath) {
    alert("请先在「本地 data/」列表点选择");
    return;
  }
  const token = ++runReqSeq;
  document.getElementById("importReport").textContent = `本地预览 ${localSelectedPath}…`;
  clearImportVisualization("新本地预览进行中…");
  const filters = selectionFilters();
  try {
    const r = await fetch(api + "/v1/workbench/import/local-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path: localSelectedPath,
        mapping: mappingFromForm(),
        maxRows: Number(document.getElementById("maxRows").value || 2000),
        ...filters,
      }),
    });
    let j;
    try { j = await r.json(); } catch (_) { j = { ok: false, error: `HTTP ${r.status}` }; }
    if (!r.ok) {
      j.ok = false;
      j.error = j.error || `HTTP ${r.status}`;
    }
    renderImportPreviewReport(j, { reqToken: token });
  } catch (err) {
    if (token !== runReqSeq) return;
    clearImportVisualization("本地预览请求失败");
    document.getElementById("importReport").textContent = `本地预览请求失败：${err.message || err}`;
  }
});

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
  const token = ++runReqSeq;
  const path = importMeta.stored_as;
  const maxRows = Number(document.getElementById("maxRows").value || 5000);
  const filters = selectionFilters();
  clearImportVisualization("回放进行中…");
  importMeta = { stored_as: path };
  document.getElementById("importReport").textContent = `回放 ${path} …`;
  try {
    const r = await fetch(api + "/v1/workbench/run/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path,
        mode: "replay",
        mapping: mappingFromForm(),
        maxRows,
        fusionProfile: document.getElementById("fusionProfile")?.value || "legacy",
        ...filters,
        truncated: true,
      }),
    });
    let j;
    try { j = await r.json(); } catch (_) { j = { ok: false, error: `HTTP ${r.status}` }; }
    if (token !== runReqSeq) return;
    if (!r.ok || !j.observations?.length) {
      const reason = !r.ok ? `回放失败 HTTP ${r.status}` : "回放无有效观测";
      document.getElementById("importReport").textContent = `${reason}\n${importStatusProse(j)}\n\n${JSON.stringify(j, null, 2)}`;
      clearImportVisualization(reason);
      importMeta = { stored_as: path };
      setStatus(false, reason);
      return;
    }
    showRun(j, { reqToken: token });
    document.getElementById("importReport").textContent = `${importStatusProse({
      filename: j.scenario?.name,
      stored_as: path,
      n_observations: j.n_observations,
      scanned_rows: j.import_summary?.scanned,
      n_errors: j.import_summary?.n_errors,
      by_source: j.import_summary?.by_source,
      errors_sample: j.import_summary?.errors_sample,
      json_container: j.import_summary?.json_container ? `JSON/${j.import_summary.json_container}` : undefined,
      time_range: j.import_summary?.time_range,
      empty_record_set: j.import_summary?.empty_record_set,
      ok: true,
    })}\n\n${JSON.stringify({
      n: j.n_observations,
      import_summary: j.import_summary,
      filters: j.import_summary?.filters,
      window_note: j.import_summary?.window_note,
    }, null, 2)}`;
  } catch (err) {
    if (token !== runReqSeq) return;
    document.getElementById("importReport").textContent = `回放请求失败：${err.message || err}`;
    clearImportVisualization("回放请求失败");
    importMeta = { stored_as: path };
  }
};

document.getElementById("btnMsDemo").onclick = async () => {
  const token = ++runReqSeq;
  clearImportVisualization("无SN多设备演示加载中…");
  try {
    const sampleResp = await fetch("/workbench-static/task007_offline_single_target.json");
    if (!sampleResp.ok) throw new Error("演示样本不可用");
    const sample = await sampleResp.json();
    sample.jobId = "ui-ms-" + Date.now();
    const r = await fetch(api + "/v1/fusion/replay", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(sample),
    });
    const j = await r.json();
    if (token !== runReqSeq) return;
    if (!r.ok || j.error) {
      document.getElementById("importReport").textContent = `演示失败 HTTP ${r.status}\n${JSON.stringify(j, null, 2)}`;
      clearImportVisualization("演示失败");
      return;
    }
    const snaps = (j.snapshots || []).map((s) => ({
      batchId: s.batchId,
      processingTime: s.processingTime,
      watermark: s.watermark,
      tracks: s.tracks || [],
    }));
    const last = snaps.length ? snaps[snaps.length - 1].tracks : [];
    const binds = last.flatMap((t) => t.sourceTracks || []);
    showRun({
      runId: j.jobId,
      sessionId: j.jobId,
      fusionProfile: j.fusionProfile,
      algorithmVersion: j.algorithmVersion,
      configVersion: j.configVersion,
      scenario: { name: "multisensor-v1-demo", aircraft: [], identity_mode: "anonymous" },
      observations: sample.observations,
      snapshots: snaps,
      final_tracks: last,
      rejected: j.rejected || [],
      events: j.events || [],
      accuracy_note: "合成无SN演示，不是现场精度",
    });
    document.getElementById("importReport").textContent = [
      `profile=${j.fusionProfile} version=${j.algorithmVersion}`,
      `轨迹 ${last.length} · 绑定 ${binds.length} · 已确认 ${binds.filter((b) => b.bindingStatus === "confirmed").length} · 候选 ${binds.filter((b) => b.bindingStatus !== "confirmed").length}`,
      `拒绝 ${ (j.rejected || []).length } · 历史点 ${ (j.trajectory || []).length }`,
      "预测仅在配置的预测窗内显示，不把平滑点写成实测真值",
    ].join("\n");
  } catch (err) {
    if (token !== runReqSeq) return;
    document.getElementById("importReport").textContent = `演示请求失败：${err.message || err}`;
    clearImportVisualization("演示请求失败");
  }
};

async function loadLocalFiles() {
  const r = await fetch(api + "/v1/workbench/local-data");
  const j = await r.json();
  document.getElementById("localFiles").innerHTML = (j.files || []).map((f) =>
    `<li><button type="button" class="localpick" data-path="${f.path}" data-bytes="${f.bytes}">选择</button> ${f.path} (${(f.bytes / 1e6).toFixed(2)} MB)</li>`
  ).join("") || "<li>无（将 SQL/XLS 放在 data/ 只读使用）</li>";
  document.querySelectorAll(".localpick").forEach((btn) => {
    btn.onclick = () => {
      const path = btn.dataset.path;
      localSelectedPath = path;
      ++runReqSeq; // invalidate in-flight preview/run for previous file
      importMeta = { stored_as: path };
      pageState = { offset: 0, limit: 50, path, has_more: false, next_offset: null };
      clearImportVisualization("已切换本地文件，旧轨迹已清除");
      const mb = (Number(btn.dataset.bytes || 0) / 1e6).toFixed(2);
      document.getElementById("importReport").textContent =
        `已选中 ${path}（${mb} MB）。请点「预览本地选中」查看原始列与观测点；确认映射后再「回放融合」。大文件勿重复上传。`;
    };
  });
}

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
  document.querySelectorAll(".fmap").forEach((inp) => {
    inp.value = fm[inp.dataset.k] != null ? fm[inp.dataset.k] : "";
  });
  const tz = document.getElementById("tzMode");
  if (mapping.assume_utc_naive || mapping.source_timezone === "assume_utc") {
    tz.value = "assume_utc";
  } else if (mapping.source_timezone) {
    tz.value = mapping.source_timezone;
  } else if ("source_timezone" in mapping || "assume_utc_naive" in mapping) {
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
  window.__wbNewFilesSelected = true;
  ++runReqSeq;
  importMeta = {};
  clearImportVisualization("已更换上传文件，旧画面已清除。请重新预览。");
  const box = document.getElementById("importReport");
  if (box) box.textContent = "已更换文件，旧预览和融合画面已清除。请点「预览映射」。";
});

document.getElementById("btnRunMulti").onclick = async () => {
  const files = document.getElementById("fileInput").files;
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

window.__wb = {
  get map() { return map; },
  get runState() { return runState; },
  set runState(v) { runState = v; },
  get draftScenario() { return draftScenario; },
  get multiQueue() { return multiQueue; },
  get pageState() { return pageState; },
  get selectedAcIndex() { return selectedAcIndex; },
  get pinnedDetail() { return pinnedDetail; },
  set pinnedDetail(v) { pinnedDetail = v; },
  computeZoomAt,
  MAP_ZOOM_FACTOR,
  MAP_MIN_SCALE,
  MAP_MAX_SCALE,
  mappingFromForm,
  selectionFilters,
  parseT,
  countsUpTo,
  pairDistanceInfo,
  updateNearDist,
  clearInspectorPanels,
  clearImportVisualization,
  renderImportPreviewReport,
  buildPreviewSnapshots,
  enableRawLayersForPreview,
  seekToFrame,
  fetchPage,
  loadScenarioByName,
  commitDrawerToDraft,
  renderAnomalies,
  renderResultPanels,
  renderInspector,
  updateTransport,
  showRun,
  locateSelectedTrack,
  viewSelectedTrackHistory,
  resolveFusionId,
  get runReqSeq() { return runReqSeq; },
  DEFAULT_SCENARIO,
};

// Boot: list presets (keep three_aircraft_primary), load default seven
loadScenarioList()
  .then(() => loadScenarioByName(DEFAULT_SCENARIO))
  .then((ok) => {
    if (!ok) setStatus(false, "默认七机加载失败，请点「恢复默认七机」或检查静态 JSON");
  });
initFieldMapForm();
document.getElementById("btnHealth").click();
