import { MapView } from "./canvas.js";

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

map.onPick = (obj, kind) => {
  if (kind === "track" || obj.fusionId) pinnedDetail = obj;
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
    return;
  }
  const srcs = (obj.sourceTracks || []).map((s) => {
    const role = s.usedForPosition || s.primaryPosition || s.bindingStatus || "";
    return `${SRC_LABEL[s.source] || s.source}:${s.sourceTrackId || "-"}(${s.bindingStatus || role || "?"})`;
  }).join("；") || "无";
  const primary = obj.primaryPositionSource || obj.positionSource ||
    (obj.sourceTracks || []).find((s) => s.usedForPosition || s.primaryPosition)?.source || "—";
  box.innerHTML = [
    `<div><b>目标</b> ${obj.aircraftId || "(匿名)"} · <span class="k">${obj.fusionId || ""}</span></div>`,
    `<div><span class="k">positionMode</span>：${obj.positionMode || "—"}</div>`,
    `<div><span class="k">主位置来源</span>：${primary}</div>`,
    `<div><span class="k">来源</span>：${srcs}</div>`,
    `<div><span class="k">seg</span>：${obj.trackSegmentId ?? "—"} · stateTime=${obj.stateTime || "—"}</div>`,
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
}
document.querySelectorAll(".layer").forEach((cb) => {
  cb.onchange = syncLayersFromUi;
});
syncLayersFromUi();

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
    renderInspector(tr, "track");
    document.getElementById("detail").textContent = JSON.stringify({ kind: "track@clock", ...tr }, null, 2);
    const rows = (tr.sourceTracks || []).map((s) =>
      `<div>${s.source} · ${s.sourceTrackId} · ${s.aircraftId || "-"} · ${s.bindingStatus || "?"}</div>`
    );
    document.getElementById("assoc").innerHTML = rows.join("") || "无";
  } else {
    document.getElementById("detail").textContent = "当前时刻无目标";
    document.getElementById("assoc").innerHTML = "无";
    pinnedDetail = null;
  }
  renderResultPanels();
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
  if (result.scenario?.aircraft) {
    // keep draft in sync with run scenario labels for result table
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
  mappingFromForm,
  selectionFilters,
  parseT,
  countsUpTo,
  fetchPage,
  loadScenarioByName,
  commitDrawerToDraft,
  renderAnomalies,
  renderResultPanels,
  renderInspector,
  updateTransport,
  showRun,
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
