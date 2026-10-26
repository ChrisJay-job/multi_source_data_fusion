/**
 * TASK-009 right-panel helpers: paginated target list + compact result summary + track card.
 */
import { colorFromFusionId, escapeHtml, shortFid } from "./ux_helpers.js";

const PAGE_DEFAULT = 30;
const PAGE_MAX = 50;

export function buildTargetGroups(result) {
  const groups = [];
  for (const a of result.scenario?.aircraft || []) {
    const tr = (result.final_tracks || []).find(
      (t) =>
        (result.evaluation?.fusion_to_truth || {})[t.fusionId] === a.truth_id ||
        (a.rid_sn && t.aircraftId === a.rid_sn)
    );
    const srcIds =
      (tr?.sourceTracks || []).map((s) => `${s.source}:${s.sourceTrackId}`).join(", ") || "—";
    groups.push({
      key: a.label,
      fusionId: tr?.fusionId || null,
      sn: a.rid_sn || tr?.aircraftId || null,
      title: `飞机 ${a.label}`,
      detail: `SN=${a.rid_sn || "(无)"} · fusionId=${tr?.fusionId || "—"} · 局部源=${srcIds}`,
      sources: (tr?.sourceTracks || []).map((s) => s.source),
      status: tr?.trackStatus || tr?.positionMode || "",
    });
  }
  const mapped = new Set(
    groups.map((g) => g.fusionId).filter(Boolean)
  );
  for (const tr of result.final_tracks || []) {
    if (mapped.has(tr.fusionId)) continue;
    const hasAc = (result.scenario?.aircraft || []).some(
      (a) =>
        (result.evaluation?.fusion_to_truth || {})[tr.fusionId] === a.truth_id ||
        (a.rid_sn && tr.aircraftId === a.rid_sn)
    );
    if (hasAc) continue;
    groups.push({
      key: tr.fusionId,
      fusionId: tr.fusionId,
      sn: tr.aircraftId || null,
      title: `融合目标 ${shortFid(tr.fusionId)}`,
      detail: `SN=${tr.aircraftId || "(无)"} · 局部源=${
        (tr.sourceTracks || []).map((s) => s.sourceTrackId).join(",") || "—"
      }`,
      sources: (tr.sourceTracks || []).map((s) => s.source),
      status: tr.trackStatus || tr.positionMode || "",
    });
  }
  if (!groups.length) {
    const last = (result.snapshots || [])[(result.snapshots || []).length - 1];
    const seen = new Set();
    for (const tr of last?.tracks || []) {
      if (!tr.fusionId || seen.has(tr.fusionId)) continue;
      seen.add(tr.fusionId);
      groups.push({
        key: tr.fusionId,
        fusionId: tr.fusionId,
        sn: tr.aircraftId || null,
        title: `融合目标 ${shortFid(tr.fusionId)}`,
        detail: `SN=${tr.aircraftId || "(无)"} · 局部源=${
          (tr.sourceTracks || []).map((s) => s.sourceTrackId).join(",") || "—"
        }`,
        sources: (tr.sourceTracks || []).map((s) => s.source),
        status: tr.trackStatus || tr.positionMode || "",
      });
    }
  }
  return groups;
}

export function filterTargetGroups(groups, { q, status, source, onlySelected, selectedIds }) {
  let list = groups.slice();
  const qq = String(q || "")
    .trim()
    .toLowerCase();
  if (qq) {
    list = list.filter((g) => {
      const blob = [
        g.key,
        g.fusionId,
        g.sn,
        g.title,
        g.detail,
        ...(g.sources || []),
      ]
        .join(" ")
        .toLowerCase();
      return blob.includes(qq);
    });
  }
  if (status) {
    list = list.filter((g) => String(g.status || "").toLowerCase().includes(String(status).toLowerCase()));
  }
  if (source) {
    list = list.filter((g) => (g.sources || []).includes(source));
  }
  if (onlySelected && selectedIds?.size) {
    list = list.filter(
      (g) => selectedIds.has(g.key) || (g.fusionId && selectedIds.has(g.fusionId))
    );
  }
  return list;
}

export function pageSlice(list, page, pageSize) {
  const size = Math.max(1, Math.min(PAGE_MAX, pageSize || PAGE_DEFAULT));
  const total = list.length;
  const pages = Math.max(1, Math.ceil(total / size));
  const p = Math.max(1, Math.min(pages, page || 1));
  const start = (p - 1) * size;
  return {
    page: p,
    pageSize: size,
    pages,
    total,
    rows: list.slice(start, start + size),
  };
}

export function renderTargetListPage(box, pageInfo, { checkedIds, selectedFusionId, onCheck, onSelect, onLocate, onHist }) {
  if (!box) return;
  const rows = pageInfo.rows
    .map((g) => {
      const fid = g.fusionId || g.key;
      const col = colorFromFusionId(fid);
      const checked = checkedIds.has(g.key) || (g.fusionId && checkedIds.has(g.fusionId));
      const sel = selectedFusionId && (selectedFusionId === g.fusionId || selectedFusionId === g.key);
      return (
        `<div class="tfilt-row${sel ? " sel" : ""}" data-key="${escapeHtml(g.key)}" data-fid="${escapeHtml(fid || "")}">` +
        `<label class="tfilt-lab"><input type="checkbox" class="tfilt" data-id="${escapeHtml(g.key)}"${
          checked ? " checked" : ""
        } />` +
        `<span class="swatch" style="background:${col}"></span> ${escapeHtml(g.title)}</label>` +
        `<div class="hint">${escapeHtml(g.detail)}</div>` +
        `<div class="row tight">` +
        `<button type="button" class="btnSelTfilt" data-fid="${escapeHtml(fid || "")}">选中</button>` +
        `<button type="button" class="btnLocTfilt" data-fid="${escapeHtml(fid || "")}">定位</button>` +
        `<button type="button" class="btnHistTfilt" data-fid="${escapeHtml(fid || "")}">查看航迹</button>` +
        `<button type="button" class="btnOnlyTfilt" data-fid="${escapeHtml(fid || "")}">只看此航迹</button>` +
        `</div></div>`
      );
    })
    .join("");
  box.innerHTML =
    `<div class="tfilt-page-meta">共 ${pageInfo.total} · 第 ${pageInfo.page}/${pageInfo.pages} 页 · 每页 ${pageInfo.pageSize}</div>` +
    (rows || `<span class="hint">无匹配目标</span>`);
  box.querySelectorAll(".tfilt").forEach((cb) => {
    cb.onchange = () => onCheck?.();
  });
  box.querySelectorAll(".btnSelTfilt").forEach((btn) => {
    btn.onclick = (ev) => {
      ev.preventDefault();
      onSelect?.(btn.dataset.fid);
    };
  });
  box.querySelectorAll(".btnLocTfilt").forEach((btn) => {
    btn.onclick = (ev) => {
      ev.preventDefault();
      onLocate?.(btn.dataset.fid);
    };
  });
  box.querySelectorAll(".btnHistTfilt").forEach((btn) => {
    btn.onclick = (ev) => {
      ev.preventDefault();
      onHist?.(btn.dataset.fid);
    };
  });
  box.querySelectorAll(".btnOnlyTfilt").forEach((btn) => {
    btn.onclick = (ev) => {
      ev.preventDefault();
      onSelect?.(btn.dataset.fid, { only: true });
    };
  });
}

export function compactResultSummaryHtml({ exp, algoN, knownSn, statusCounts, historyGap, verdict }) {
  const st = Object.entries(statusCounts || {})
    .map(([k, v]) => `${escapeHtml(k)}=${v}`)
    .join(" · ");
  return [
    `<div>当前时刻：预期可见 <b>${exp}</b> · 算法航迹数 <b>${algoN}</b> · 已知 SN 数 <b>${knownSn}</b></div>`,
    `<div class="muted">说明：算法航迹数≠无人机台数；匿名/多段仍分别计数。</div>`,
    st ? `<div>状态分布：${st}</div>` : "",
    historyGap ? `<div class="warn">historyGap：当前为已保留尾部，非完整本次飞行。</div>` : "",
    verdict
      ? `<div class="muted">整次评估（仿真，非现场准确率）：<b>${escapeHtml(verdict)}</b></div>`
      : "",
  ]
    .filter(Boolean)
    .join("");
}

export function trackCardHtml(tr, { historyGap, rangeNote, summary, cursorNote } = {}) {
  if (!tr) return `<div class="hint">未选中航迹。点击三维线段或列表「选中」。</div>`;
  const sn = tr.aircraftId;
  const snLine = sn
    ? `业务 SN：<b>${escapeHtml(sn)}</b>`
    : `未识别 SN · fusionId ${escapeHtml(tr.fusionId || "")}`;
  const srcs = (tr.sourceTracks || [])
    .map((s) => {
      const radar = s.source === "radar";
      const idLab = radar ? "雷达局部号" : "sourceTrackId";
      return `${escapeHtml(s.source)} · detector=${escapeHtml(s.detectorId || "—")} · ${idLab}=${escapeHtml(
        s.sourceTrackId || "—"
      )}${s.aircraftId && !radar ? " · SN=" + escapeHtml(s.aircraftId) : ""}`;
    })
    .join("<br/>");
  const fmtT = (ms) =>
    ms != null && Number.isFinite(ms) ? new Date(ms).toISOString().replace("T", " ").slice(0, 19) + "Z" : "—";
  const sum = summary || {};
  const rangeBlock =
    sum.nHorizontal != null
      ? `<div>水平点 ${sum.nHorizontal} · 垂直更新 ${sum.nVertical ?? 0} · 分段 ${sum.nSegments ?? 0}</div>` +
        `<div>已保留起止：${fmtT(sum.t0)} → ${fmtT(sum.t1)}</div>` +
        `<div>有效海拔 MSL：${
          sum.altMin == null ? "无有效样本" : `${sum.altMin} … ${sum.altMax} m`
        }</div>`
      : "";
  return (
    `<div class="track-card">` +
    `<div>${snLine}</div>` +
    `<div>fusionId：<code class="k" title="点击复制" data-copy="${escapeHtml(
      tr.fusionId || ""
    )}">${escapeHtml(tr.fusionId || "—")}</code></div>` +
    `<div>状态：${escapeHtml(tr.trackStatus || tr.positionMode || "—")}</div>` +
    `<div>${escapeHtml(cursorNote || "当前位置（游标时刻）")}：${
      tr.longitude != null
        ? `${Number(tr.longitude).toFixed(6)}, ${Number(tr.latitude).toFixed(6)} · alt=${
            tr.altitude ?? "未知"
          } ${escapeHtml(tr.altitudeDatum || "")}/${escapeHtml(tr.altitudeMode || "")}`
        : "无当前点"
    }</div>` +
    `<div>来源：<br/>${srcs || "—"}</div>` +
    rangeBlock +
    `<div class="muted">${escapeHtml(rangeNote || "")}</div>` +
    (historyGap ? `<div class="warn">historyGap：不可写成完整本次飞行。</div>` : "") +
    `</div>`
  );
}

export { PAGE_DEFAULT, PAGE_MAX, colorFromFusionId, escapeHtml, shortFid };
