const COLORS = {
  rid: "#4cc9f0",
  spectrum: "#90be6d",
  radar: "#f9c74f",
  fused: "#f72585",
  truth: "#c77dff",
  pred: "#ff6b6b",
  plan: "#6c757d",
  hint: "#adb5bd",
};

function trackKey(o) {
  return `${o.source}|${o.detectorId || ""}|${o.sourceTrackId || ""}`;
}

function parseT(s) {
  if (!s) return 0;
  return Date.parse(String(s).replace("Z", "+00:00"));
}

function isPredicted(mode) {
  return mode === "predicted";
}

function isMeasured(mode) {
  return mode === "measured_assisted" || mode === "measured" || !mode;
}

/**
 * Build display identity index from scenario / truth / observations.
 * Label "A" maps to truth TRUTH-A, SN-A-*, sourceTrack keys, fusionIds seen in state.
 */
export function buildDisplayIndex(state) {
  const byLabel = new Map(); // label -> { truths, sns, trackKeys, fusionIds }
  const ensure = (lab) => {
    if (!byLabel.has(lab)) byLabel.set(lab, { truths: new Set(), sns: new Set(), trackKeys: new Set(), fusionIds: new Set() });
    return byLabel.get(lab);
  };
  for (const a of state?.scenario?.aircraft || []) {
    const lab = String(a.label);
    const e = ensure(lab);
    if (a.truth_id) e.truths.add(a.truth_id);
    if (a.rid_sn) e.sns.add(a.rid_sn);
    for (const [src, cfg] of Object.entries(a.sources || {})) {
      if (!cfg?.enabled) continue;
      const stid = src === "radar" ? `${src}-${lab}` : (a.rid_sn || `${src}-${lab}`);
      e.trackKeys.add(`${src}|DET-${src.toUpperCase()}|${stid}`);
      // also common detector variants
      e.trackKeys.add(`${src}||${stid}`);
    }
  }
  for (const tid of Object.keys(state?.truth_polyline || {})) {
    const lab = String(tid).replace(/^TRUTH-/, "");
    ensure(lab).truths.add(tid);
  }
  if (state?.obs_truth_map && state?.observations) {
    for (const o of state.observations) {
      const tid = state.obs_truth_map[o.observationId];
      if (!tid) continue;
      const lab = String(tid).replace(/^TRUTH-/, "");
      const e = ensure(lab);
      e.truths.add(tid);
      if (o.aircraftId) e.sns.add(o.aircraftId);
      e.trackKeys.add(trackKey(o));
    }
  }
  for (const snap of state?.snapshots || []) {
    for (const tr of snap.tracks || []) {
      let lab = null;
      if (tr.aircraftId) {
        for (const [L, e] of byLabel) {
          if (e.sns.has(tr.aircraftId)) { lab = L; break; }
        }
        if (!lab && /^SN-([A-Za-z0-9]+)/.test(tr.aircraftId)) {
          lab = RegExp.$1.split("-")[0];
        }
      }
      if (lab) {
        const e = ensure(lab);
        e.fusionIds.add(tr.fusionId);
        if (tr.aircraftId) e.sns.add(tr.aircraftId);
        for (const st of tr.sourceTracks || []) e.trackKeys.add(trackKey(st));
      }
    }
  }
  return byLabel;
}

/** Pure zoom-at helper (exported for targeted tests). */
export function computeZoomAt({ ox, oy, scale, px, py, factor, minScale, maxScale }) {
  if (!Number.isFinite(factor) || factor <= 0) {
    return { ox, oy, scale, ok: false, reason: "bad_factor" };
  }
  if (!Number.isFinite(scale) || scale <= 0) {
    return { ox, oy, scale, ok: false, reason: "bad_scale" };
  }
  const wx = (px - ox) / scale;
  const wy = (oy - py) / scale;
  let next = scale * factor;
  next = Math.min(maxScale, Math.max(minScale, next));
  if (!Number.isFinite(next) || next <= 0) {
    return { ox, oy, scale, ok: false, reason: "clamp_illegal" };
  }
  return {
    ox: px - wx * next,
    oy: py + wy * next,
    scale: next,
    ok: true,
    world: [wx, wy],
  };
}

export const MAP_ZOOM_FACTOR = 1.1;
export const MAP_MIN_SCALE = 1e-4;
export const MAP_MAX_SCALE = 200;

export class MapView {
  constructor(canvas) {
    this.cv = canvas;
    this.ctx = canvas.getContext("2d");
    this.scale = 1.2;
    this.ox = canvas.width / 2;
    this.oy = canvas.height / 2;
    this.MIN_SCALE = MAP_MIN_SCALE;
    this.MAX_SCALE = MAP_MAX_SCALE;
    this.ZOOM_FACTOR = MAP_ZOOM_FACTOR;
    this.DRAG_CLICK_PX = 5; // CSS pixels
    // current = marker at clock; fused = measured history; obs layers drawn dimmer by default
    this.layers = {
      rid: true, spectrum: true, radar: true,
      fused: true, current: true, pred: true, truth: true, plan: true,
    };
    this.obsAlpha = 0.35;
    this.targetFilter = null; // Set of labels / ids from UI
    this.displayIndex = new Map();
    this.state = null;
    this.tIndex = 0;
    this.drag = null;
    this.onPick = null;
    this.routeEdit = null; // { aircraftIndex, points: [{x_m,y_m}], dragging }
    this.lastDrawStats = { drawn_points: 0, drawn_lines: 0, by_source: {} };
    this._fitted = false;
    this.selectedFusionId = null;
    this._suppressClick = false;
    this._drawRaf = 0;
    this._viewManual = false; // user zoom/pan/locate — seek must not auto-fit
    this._lastClient = null; // fallback for wheel events missing clientX/Y (some synthesizers)
    this._cssScale = () => {
      const r = this.cv.getBoundingClientRect();
      return { sx: this.cv.width / Math.max(1, r.width), sy: this.cv.height / Math.max(1, r.height), rect: r };
    };

    canvas.addEventListener("pointerdown", (e) => this._onPointerDown(e));
    canvas.addEventListener("pointermove", (e) => this._onPointerMove(e));
    canvas.addEventListener("pointerup", (e) => this._onPointerUp(e));
    canvas.addEventListener("pointercancel", (e) => this._onPointerUp(e));
    canvas.addEventListener("lostpointercapture", () => this._endPointerGesture());
    window.addEventListener("blur", () => this._endPointerGesture());
    canvas.addEventListener("wheel", (e) => this._onWheel(e), { passive: false });
    canvas.addEventListener("mousemove", (e) => {
      if (Number.isFinite(e.clientX) && Number.isFinite(e.clientY)) {
        this._lastClient = { x: e.clientX, y: e.clientY };
      }
    });
    canvas.addEventListener("click", (e) => this._onClick(e));

    // Keep world center stable when CSS box / DPR layout changes (no auto fit-all).
    if (typeof ResizeObserver !== "undefined") {
      this._ro = new ResizeObserver(() => this._onCssResize());
      this._ro.observe(canvas);
      this._lastCss = canvas.getBoundingClientRect();
    }
  }

  setLayers(layers, { draw = true } = {}) {
    Object.assign(this.layers, layers);
    if (draw) this.draw();
  }
  setTargetFilter(set, { draw = true } = {}) {
    this.targetFilter = set;
    if (draw) this.draw();
  }
  setSelectedFusionId(fid, { draw = true } = {}) {
    this.selectedFusionId = fid || null;
    if (draw) this.draw();
  }
  setState(state, { fit = true, resetTime = true, draw = true } = {}) {
    this.state = state;
    this.displayIndex = buildDisplayIndex(state || {});
    this._fitted = false;
    this._viewManual = false;
    if (resetTime) this.tIndex = 0;
    if (fit) this.fitToData();
    if (draw) this.draw();
  }
  setTimeIndex(i) {
    const n = this.state?.snapshots?.length || 1;
    this.tIndex = Math.max(0, Math.min(i, n - 1));
    // Do not reset camera on seek/play — only redraw.
    this.draw();
  }
  resetView() { this.fitToData(); this._viewManual = false; this.draw(); }

  _scheduleDraw() {
    if (this._drawRaf) return;
    this._drawRaf = requestAnimationFrame(() => {
      this._drawRaf = 0;
      this.draw();
    });
  }

  _onCssResize() {
    const r = this.cv.getBoundingClientRect();
    const prev = this._lastCss;
    this._lastCss = r;
    if (!prev || !prev.width || !r.width) return;
    // Internal buffer size is fixed; CSS scale change does not alter ox/oy in buffer space.
    // Preserve world point under previous CSS center.
    if (Math.abs(prev.width - r.width) < 0.5 && Math.abs(prev.height - r.height) < 0.5) return;
    const { sx: sx0, sy: sy0 } = {
      sx: this.cv.width / Math.max(1, prev.width),
      sy: this.cv.height / Math.max(1, prev.height),
    };
    const { sx, sy } = this._cssScale();
    const [wx, wy] = this.screenToWorld((prev.width / 2) * sx0, (prev.height / 2) * sy0);
    this.ox = (r.width / 2) * sx - wx * this.scale;
    this.oy = (r.height / 2) * sy + wy * this.scale;
    this._scheduleDraw();
  }

  /** Normalize wheel delta to a reciprocal zoom factor (or null if no-op). */
  _wheelFactor(e) {
    let dy = e.deltaY;
    if (!Number.isFinite(dy) || dy === 0) return null;
    if (e.deltaMode === 1) dy *= 16; // lines → px
    else if (e.deltaMode === 2) dy *= this.cv.height || 800; // pages
    // Continuous reciprocal: factor = exp(-k*dy) with k so |dy|=100 → ZOOM_FACTOR.
    // Trackpad 1px ≠ 100px; equal reverse deltas restore scale/view.
    const k = Math.log(this.ZOOM_FACTOR) / 100;
    let factor = Math.exp(-k * dy);
    const maxStep = Math.pow(this.ZOOM_FACTOR, 4);
    if (!Number.isFinite(factor) || factor <= 0) return null;
    return Math.min(maxStep, Math.max(1 / maxStep, factor));
  }

  zoomAt(px, py, factor) {
    const r = computeZoomAt({
      ox: this.ox, oy: this.oy, scale: this.scale,
      px, py, factor,
      minScale: this.MIN_SCALE, maxScale: this.MAX_SCALE,
    });
    if (!r.ok) return r;
    this.ox = r.ox;
    this.oy = r.oy;
    this.scale = r.scale;
    this._viewManual = true;
    return r;
  }

  _onWheel(e) {
    e.preventDefault();
    e.stopPropagation();
    const factor = this._wheelFactor(e);
    if (factor == null) return;
    // Prefer last known pointer on the canvas as the zoom anchor. Native wheel
    // usually matches; some synthesizers (or off-canvas values) do not.
    // Build a plain coord object — spreading Event instances is unreliable.
    const clientX = (this._lastClient && Number.isFinite(this._lastClient.x))
      ? this._lastClient.x
      : e.clientX;
    const clientY = (this._lastClient && Number.isFinite(this._lastClient.y))
      ? this._lastClient.y
      : e.clientY;
    const { x, y } = this._eventXY({ type: "wheel", clientX, clientY });
    this.zoomAt(x, y, factor);
    this._scheduleDraw();
  }

  fitToLabels(labels, { padding = 1.3, minSpanM = 50, maxSpanM = null, atTimeS = null } = {}) {
    const want = new Set((labels || []).map(String));
    const pts = [];
    const s = this.state;
    if (!s) return { ok: false, reason: "no_state" };
    const idx = this.displayIndex || new Map();
    // Real fusionId tokens: collect from committed history / current snap, never silent fit-all.
    const fusionIds = [...want].filter((t) => t && (t.includes("-") || t.startsWith("F") || String(t).length > 8));
    for (const fid of fusionIds) {
      const got = this.collectFusionTrackPoints(fid, { includeFuture: false });
      for (const p of got.pts) pts.push(p.xy);
      if (got.current) pts.push(got.current.xy);
    }
    for (const [lab, info] of idx.entries()) {
      if (want.size && !want.has(lab) && ![...(info.truths || info.truthIds || [])].some((t) => want.has(t))) continue;
      for (const tid of info.truths || info.truthIds || []) {
        for (const p of s.truth_polyline?.[tid] || []) {
          if (atTimeS != null && p.t != null && Math.abs(p.t - atTimeS) > 1.0) continue;
          pts.push([p.x_m, p.y_m]);
        }
      }
    }
    for (const a of s.scenario?.aircraft || []) {
      if (want.size && !want.has(a.label)) continue;
      for (const p of s.truth_polyline?.[a.truth_id] || []) {
        if (atTimeS != null && p.t != null && Math.abs(p.t - atTimeS) > 1.0) continue;
        pts.push([p.x_m, p.y_m]);
      }
      if (atTimeS == null) {
        for (const w of a.waypoints || []) pts.push([w.x_m, w.y_m]);
      }
    }
    if (!pts.length) {
      // Do not pretend success by fitting everything when the requested labels are missing.
      return { ok: false, reason: "no_points_for_labels" };
    }
    this._fitPoints(pts, { padding, minSpanM, maxSpanM });
    this._fitted = true;
    this._viewManual = true;
    return { ok: true, n: pts.length };
  }

  _isValidLatLon(lat, lon) {
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;
    if (Math.abs(lat) < 1e-8 && Math.abs(lon) < 1e-8) return false;
    return true;
  }

  _isValidXY(xy) {
    if (!xy || !Number.isFinite(xy[0]) || !Number.isFinite(xy[1])) return false;
    return true;
  }

  _fitPoints(pts, { padding = 1.3, minSpanM = 50, maxSpanM = null } = {}) {
    const valid = pts.filter((p) => this._isValidXY(p));
    if (!valid.length) return false;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const [x, y] of valid) {
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
    let cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
    let dx = Math.max(minSpanM, maxX - minX);
    let dy = Math.max(minSpanM, maxY - minY);
    if (maxSpanM != null && Number.isFinite(maxSpanM)) {
      dx = Math.min(Math.max(dx, minSpanM), maxSpanM);
      dy = Math.min(Math.max(dy, minSpanM), maxSpanM);
    }
    // Guard: single point / degenerate line — still focusable, no divide-by-zero.
    if (!Number.isFinite(dx) || dx <= 0) dx = minSpanM;
    if (!Number.isFinite(dy) || dy <= 0) dy = minSpanM;
    let next = Math.min(this.cv.width / (dx * padding), this.cv.height / (dy * padding));
    next = Math.min(this.MAX_SCALE, Math.max(this.MIN_SCALE, next));
    if (!Number.isFinite(next) || next <= 0) return false;
    this.scale = next;
    this.ox = this.cv.width / 2 - cx * this.scale;
    this.oy = this.cv.height / 2 + cy * this.scale;
    return true;
  }

  _commitXY(c) {
    if (c.east_m != null && c.north_m != null) return [Number(c.east_m), Number(c.north_m)];
    if (this._isValidLatLon(c.latitude, c.longitude)) return this._llToXY(c.latitude, c.longitude);
    return null;
  }

  /** Stable dedupe key for a committed point belonging to fusionId. Prefer pointId. */
  _commitPointKey(c, fusionId) {
    if (c.pointId != null && c.pointId !== "") return `pid:${c.pointId}`;
    const ct = parseT(c.stateTime || c.measurementTime);
    const xy = this._commitXY(c);
    if (!xy) return null;
    const oids = (c.observationIds || (c.observationId ? [c.observationId] : [])).join(",");
    return `fid:${fusionId}|t:${ct}|x:${xy[0].toFixed(4)}|y:${xy[1].toFixed(4)}|o:${oids}`;
  }

  /**
   * Collect a fusion track's already-occurred geometry up to the play clock.
   * Fusion geometry = union of this fusionId's committedHistory (deduped); never bestHist-only.
   * Raw observations are listed separately and only when observationId is claimed by this
   * fusionId's committed points — source-triple equality alone is insufficient.
   */
  collectFusionTrackPoints(fusionId, { includeFuture = false } = {}) {
    const out = {
      pts: [], // fusion committed (+ current) only
      obsPts: [], // proven-linked observations; not mixed into fusion history count
      current: null,
      reason: null,
      nFusion: 0,
      nObs: 0,
    };
    const s = this.state;
    if (!s || !fusionId) {
      out.reason = "no_state";
      return out;
    }
    const nowT = this.currentTimeMs();
    const endIdx = Math.min(this.tIndex, (s.snapshots?.length || 1) - 1);
    const seenCommit = new Set();
    const claimedObsIds = new Set();

    const pushFusion = (xy, t, meta = {}) => {
      if (!this._isValidXY(xy)) return;
      const key = meta.key || `xy:${xy[0].toFixed(4)},${xy[1].toFixed(4)},${t || 0}`;
      if (seenCommit.has(key)) return;
      seenCommit.add(key);
      out.pts.push({ xy, t: t || 0, kind: "fusion", ...meta });
    };

    // Merge ALL already-occurred committed histories for this fusionId (rolling windows).
    for (let i = 0; i <= endIdx; i++) {
      for (const tr of s.snapshots[i]?.tracks || []) {
        if (tr.fusionId !== fusionId) continue;
        const hist = tr.committedHistory || tr.committed_updates || [];
        for (const c of hist) {
          // Reject commits stamped with a different fusionId when present.
          if (c.fusionId && c.fusionId !== fusionId) continue;
          const ct = parseT(c.stateTime || c.measurementTime);
          if (!includeFuture && nowT && Number.isFinite(ct) && ct > nowT + 1) continue;
          const xy = this._commitXY(c);
          if (!xy) continue;
          const key = this._commitPointKey(c, fusionId);
          if (!key) continue;
          pushFusion(xy, ct, { key, pointId: c.pointId || null });
          for (const oid of c.observationIds || []) if (oid) claimedObsIds.add(String(oid));
          if (c.observationId) claimedObsIds.add(String(c.observationId));
        }
      }
    }

    // Optional observation overlay: only observationIds proven via this target's commits.
    const seenObs = new Set();
    if (claimedObsIds.size && s.observations) {
      for (const o of s.observations) {
        const oid = o.observationId != null ? String(o.observationId) : "";
        if (!oid || !claimedObsIds.has(oid)) continue;
        const ot = parseT(o.measurementTime);
        if (!includeFuture && nowT && Number.isFinite(ot) && ot > nowT + 1) continue;
        if (!this._isValidLatLon(o.latitude, o.longitude)) continue;
        if (seenObs.has(oid)) continue;
        seenObs.add(oid);
        out.obsPts.push({
          xy: this._llToXY(o.latitude, o.longitude),
          t: ot || 0,
          kind: "obs",
          observationId: oid,
        });
      }
    }

    const snap = s.snapshots?.[this.tIndex];
    const trNow = snap?.tracks?.find((t) => t.fusionId === fusionId) || null;
    if (trNow && this._isValidLatLon(trNow.latitude, trNow.longitude)) {
      const xy = this._llToXY(trNow.latitude, trNow.longitude);
      out.current = { xy, t: parseT(trNow.stateTime || trNow.displayStateTime) || nowT };
      // Do not double-count when current coincides with an already-merged commit.
      const already = out.pts.some((p) => Math.hypot(p.xy[0] - xy[0], p.xy[1] - xy[1]) < 1e-3);
      if (!already) pushFusion(xy, out.current.t, { key: `current:${fusionId}` });
    }
    out.nFusion = out.pts.length;
    out.nObs = out.obsPts.length;
    if (!out.pts.length && !out.current) out.reason = "no_history";
    return out;
  }

  /** Center current play-time position of a real fusion track; does not change playhead. */
  centerOnFusionId(fusionId, { localSpanM = 400 } = {}) {
    if (!fusionId) return { ok: false, message: "未指定 fusionId" };
    this.selectedFusionId = fusionId;
    const got = this.collectFusionTrackPoints(fusionId, { includeFuture: false });
    if (got.current) {
      const spanOnScreen = Math.min(this.cv.width, this.cv.height) / this.scale;
      if (!Number.isFinite(this.scale) || this.scale <= 0 || spanOnScreen > 5000 || spanOnScreen < 5) {
        const next = Math.min(this.cv.width, this.cv.height) / Math.max(20, localSpanM);
        this.scale = Math.min(this.MAX_SCALE, Math.max(this.MIN_SCALE, next));
      }
      const [wx, wy] = got.current.xy;
      this.ox = this.cv.width / 2 - wx * this.scale;
      this.oy = this.cv.height / 2 + wy * this.scale;
      this._viewManual = true;
      this.draw();
      return { ok: true, hasCurrent: true, message: "已定位到当前时刻位置" };
    }
    if (got.pts.length) {
      this._fitPoints(got.pts.map((p) => p.xy), { padding: 1.2, minSpanM: 30 });
      this._viewManual = true;
      this.draw();
      return { ok: true, hasCurrent: false, hasHistory: true, message: "当前无位置；已展示已发生历史" };
    }
    this.draw();
    return { ok: false, hasCurrent: false, hasHistory: false, message: "该目标无已发生历史，无法定位" };
  }

  /** Fit bbox of already-occurred *fusion* track geometry for a fusionId (not raw obs mix). */
  fitFusionTrackHistory(fusionId) {
    if (!fusionId) return { ok: false, message: "未指定 fusionId" };
    this.selectedFusionId = fusionId;
    const got = this.collectFusionTrackPoints(fusionId, { includeFuture: false });
    // Use fusion committed (+ current) only — obsPts are separate and do not expand this fit.
    const pts = got.pts.map((p) => p.xy);
    if (!pts.length) {
      this.draw();
      return { ok: false, message: got.current ? "仅有当前点但几何无效" : "该目标无已发生历史，无法查看航迹" };
    }
    this._fitPoints(pts, { padding: 1.25, minSpanM: 30 });
    this._viewManual = true;
    this.draw();
    return {
      ok: true,
      n: pts.length,
      nFusion: got.nFusion,
      nObsLinked: got.nObs,
      hasCurrent: !!got.current,
      message: got.current
        ? `已适配融合历史 ${got.nFusion} 点` + (got.nObs ? `（另有已证明关联观测 ${got.nObs}，未混入计数）` : "")
        : `当前无位置；已适配融合历史 ${got.nFusion} 点`,
    };
  }

  currentTimeMs() {
    const snap = this.state?.snapshots?.[this.tIndex];
    return parseT(snap?.processingTime || snap?.watermark);
  }

  /** Unified membership: filter tokens are labels (A) or explicit ids. */
  _allowedByFilter(kind, obj) {
    if (!this.targetFilter || !this.targetFilter.size) return true;
    const tokens = [...this.targetFilter].map(String);
    for (const t of tokens) {
      if (kind === "fusion") {
        if (t === obj.fusionId || t === obj.aircraftId) return true;
      }
      if (kind === "obs") {
        if (t === obj.sourceTrackId || t === obj.aircraftId || t === trackKey(obj)) return true;
      }
      if (kind === "truth" || kind === "plan") {
        // Exact: token equals tid / label of THIS object only
        if (t === obj || t === String(obj).replace(/^TRUTH-/, "") || String(obj) === `TRUTH-${t}`) return true;
      }
    }
    for (const t of tokens) {
      const entry = this.displayIndex.get(t);
      if (!entry) continue;
      if (kind === "fusion") {
        if (entry.fusionIds.has(obj.fusionId)) return true;
        if (obj.aircraftId && entry.sns.has(obj.aircraftId)) return true;
        for (const st of obj.sourceTracks || []) {
          if (entry.trackKeys.has(trackKey(st))) return true;
        }
      }
      if (kind === "obs") {
        if (entry.trackKeys.has(trackKey(obj))) return true;
        if (obj.aircraftId && entry.sns.has(obj.aircraftId)) return true;
      }
      if (kind === "truth" || kind === "plan") {
        // Object must be a member of selected label's truth set (not "entry has TRUTH-A so allow TRUTH-B")
        if (entry.truths.has(obj)) return true;
      }
    }
    return false;
  }

  /**
   * Fit currently *drawn* / filtered geometry (layer semantics match draw()).
   * - current: only current-frame marker positions
   * - fused: committed history up to play clock
   * - pred: predicted history up to play clock
   * - source layers: observations with measurementTime ≤ play clock (same as draw)
   * Hidden layers / unchecked targets / (0,0) never expand bounds.
   * Does not clear targetFilter or layers.
   */
  fitToData({ respectFilter = true } = {}) {
    const pts = [];
    const s = this.state;
    if (!s) return;
    const allowFilter = respectFilter;
    const nowT = this.currentTimeMs();
    const endIdx = Math.min(this.tIndex, (s.snapshots?.length || 1) - 1);

    // Raw source layers: already-occurred observations only (matches draw cutoff).
    for (const o of s.observations || []) {
      if (!this.layers[o.source]) continue;
      if (allowFilter && !this._allowedByFilter("obs", o)) continue;
      const ot = parseT(o.measurementTime);
      if (nowT && Number.isFinite(ot) && ot > nowT + 1) continue;
      if (!this._isValidLatLon(o.latitude, o.longitude)) continue;
      const xy = this._llToXY(o.latitude, o.longitude);
      if (this._isValidXY(xy)) pts.push(xy);
    }

    if (this.layers.plan && s.truth_polyline) {
      for (const [tid, arr] of Object.entries(s.truth_polyline)) {
        if (allowFilter && !this._allowedByFilter("plan", tid)) continue;
        for (const p of arr) if (this._isValidXY([p.x_m, p.y_m])) pts.push([p.x_m, p.y_m]);
      }
    }
    if (this.layers.truth && s.truth_polyline) {
      for (const [tid, arr] of Object.entries(s.truth_polyline)) {
        if (allowFilter && !this._allowedByFilter("truth", tid)) continue;
        const timed = (s.truth_timeline?.[tid] || []).filter((p) => parseT(p.time) <= nowT + 1);
        if (timed.length) {
          for (const p of timed) {
            const xy = this._llToXY(p.lat, p.lon);
            if (this._isValidXY(xy)) pts.push(xy);
          }
        } else {
          for (const p of arr) {
            if (p.t != null && s.t0Ms != null && s.t0Ms + p.t * 1000 > nowT + 1) continue;
            if (this._isValidXY([p.x_m, p.y_m])) pts.push([p.x_m, p.y_m]);
          }
        }
      }
    }

    // current: ONLY the play-frame marker (no history).
    if (this.layers.current) {
      const snap = s.snapshots?.[this.tIndex];
      for (const tr of snap?.tracks || []) {
        if (allowFilter && !this._allowedByFilter("fusion", tr)) continue;
        if (!this._isValidLatLon(tr.latitude, tr.longitude)) continue;
        const xy = this._llToXY(tr.latitude, tr.longitude);
        if (this._isValidXY(xy)) pts.push(xy);
      }
    }

    // fused: committed history up to clock (matches draw fused layer).
    if (this.layers.fused) {
      const best = new Map();
      for (let i = 0; i <= endIdx; i++) {
        for (const tr of s.snapshots[i]?.tracks || []) {
          if (allowFilter && !this._allowedByFilter("fusion", tr)) continue;
          const hist = tr.committedHistory || tr.committed_updates || [];
          if (!hist.length) continue;
          const seg = String(tr.trackSegmentId ?? "0");
          const key = `${tr.fusionId}||${seg}`;
          // Merge all commits (do not discard earlier rolling windows).
          if (!best.has(key)) best.set(key, new Map());
          const bucket = best.get(key);
          for (const c of hist) {
            const ct = parseT(c.stateTime || c.measurementTime);
            if (nowT && Number.isFinite(ct) && ct > nowT + 1) continue;
            const xy = this._commitXY(c);
            if (!xy || !this._isValidXY(xy)) continue;
            const ck = this._commitPointKey(c, tr.fusionId) || `${ct}:${xy[0]}:${xy[1]}`;
            bucket.set(ck, xy);
          }
        }
      }
      for (const bucket of best.values()) {
        for (const xy of bucket.values()) pts.push(xy);
      }
    }

    // pred: predicted-history points up to clock (same episode rules as draw — simplified collect).
    if (this.layers.pred) {
      for (let i = 0; i <= endIdx; i++) {
        const snap = s.snapshots[i];
        const snapT = parseT(snap?.processingTime || snap?.watermark);
        for (const tr of snap?.tracks || []) {
          if (allowFilter && !this._allowedByFilter("fusion", tr)) continue;
          if (!isPredicted(tr.positionMode)) continue;
          const hist = tr.predictedHistory || tr.predicted_history || [];
          if (hist.length) {
            for (const p of hist) {
              const pt = parseT(p.displayStateTime || p.stateTime || p.time);
              if (nowT && Number.isFinite(pt) && pt > nowT + 1) continue;
              const xy = (p.east_m != null && p.north_m != null)
                ? [Number(p.east_m), Number(p.north_m)]
                : (this._isValidLatLon(p.latitude, p.longitude) ? this._llToXY(p.latitude, p.longitude) : null);
              if (xy && this._isValidXY(xy)) pts.push(xy);
            }
          } else if (this._isValidLatLon(tr.latitude, tr.longitude)) {
            const pt = parseT(tr.displayStateTime || tr.stateTime) || snapT;
            if (nowT && Number.isFinite(pt) && pt > nowT + 1) continue;
            pts.push(this._llToXY(tr.latitude, tr.longitude));
          }
        }
      }
    }

    if (!pts.length) return;
    this._fitPoints(pts, { padding: 1.3, minSpanM: 50 });
    this._fitted = true;
  }

  worldToScreen(x, y) {
    return [this.ox + x * this.scale, this.oy - y * this.scale];
  }
  screenToWorld(sx, sy) {
    return [(sx - this.ox) / this.scale, (this.oy - sy) / this.scale];
  }

  draw() {
    const { ctx, cv } = this;
    ctx.clearRect(0, 0, cv.width, cv.height);
    this._grid();
    this.lastDrawStats = { drawn_points: 0, drawn_lines: 0, by_source: {} };
    if (!this.state && !this.routeEdit) return;
    const now = this.currentTimeMs();
    const s = this.state || {};

    if (this.layers.plan && s.truth_polyline) {
      for (const [tid, pts] of Object.entries(s.truth_polyline)) {
        if (!this._allowedByFilter("plan", tid)) continue;
        this._poly(pts.map((p) => [p.x_m, p.y_m]), COLORS.plan, true, null, 1);
      }
    }

    if (this.layers.truth && s.truth_polyline) {
      for (const [tid, pts] of Object.entries(s.truth_polyline)) {
        if (!this._allowedByFilter("truth", tid)) continue;
        const timed = (s.truth_timeline?.[tid] || []).filter((p) => parseT(p.time) <= now + 1);
        const flown = pts.filter((p) => (p.t == null ? true : (s.t0Ms != null ? s.t0Ms + p.t * 1000 <= now + 1 : true)));
        const use = timed.length ? timed.map((p) => this._llToXY(p.lat, p.lon)) : flown.map((p) => [p.x_m, p.y_m]);
        if (use.length) this._poly(use, COLORS.truth, false, tid, 2);
      }
    }

    if (s.observations) {
      const groups = new Map();
      for (const o of s.observations) {
        if (!this.layers[o.source]) continue;
        if (parseT(o.measurementTime) > now + 1) continue;
        if (!this._allowedByFilter("obs", o)) continue;
        const k = trackKey(o);
        if (!groups.has(k)) groups.set(k, []);
        groups.get(k).push(o);
      }
      for (const [, rows] of groups) {
        rows.sort((a, b) => parseT(a.measurementTime) - parseT(b.measurementTime));
        const segs = [];
        let cur = [];
        for (const o of rows) {
          if (cur.length) {
            const dt = parseT(o.measurementTime) - parseT(cur[cur.length - 1].measurementTime);
            if (dt > 30000) { segs.push(cur); cur = []; }
          }
          cur.push(o);
        }
        if (cur.length) segs.push(cur);
        const color = COLORS[rows[0].source];
        const src = rows[0].source;
        for (const seg of segs) {
          const pts = seg.map((o) => this._llToXY(o.latitude, o.longitude));
          this._points(pts, color, this.obsAlpha);
          this.lastDrawStats.drawn_points += pts.length;
          this.lastDrawStats.by_source[src] = (this.lastDrawStats.by_source[src] || 0) + pts.length;
          if (pts.length >= 2) {
            this._poly(pts, color, false, null, 1.5, this.obsAlpha);
            this.lastDrawStats.drawn_lines += 1;
          } else if (pts.length === 1) {
            this._point(pts[0][0], pts[0][1], color, "circle", null, this.obsAlpha);
          }
        }
      }
    }

    // Fused HISTORY from committed KF updates (archived across snaps; survives termination).
    // Pred layer draws actual predicted-history dashed polylines (not last-4 scatter / hint).
    if ((this.layers.fused || this.layers.pred || this.layers.current) && s.snapshots) {
      const nowSnap = s.snapshots[this.tIndex];
      const nowT = parseT(nowSnap?.processingTime || nowSnap?.watermark);
      const GAP_MS = 8000; // break polyline on long absence / re-birth
      const endIdx = Math.min(this.tIndex, (s.snapshots.length || 1) - 1);

      const flushRuns = (pts, color, dashed, width) => {
        pts.sort((a, b) => a.t - b.t);
        let run = [];
        const flush = () => {
          if (run.length >= 2) this._poly(run.map((p) => p.xy), color, dashed, null, width);
          else if (run.length === 1) this._point(run[0].xy[0], run[0].xy[1], color, dashed ? "diamond" : "square", null, dashed ? 0.7 : 1);
          run = [];
        };
        for (const p of pts) {
          if (run.length && p.t - run[run.length - 1].t > GAP_MS) flush();
          run.push(p);
        }
        flush();
      };

      if (this.layers.fused) {
        // Union of already-occurred commits per fusionId||segment (same semantics as
        // collectCommittedGeometry / collectFusionTrackPoints — never "longest hist only").
        const byKey = new Map(); // fusionId||seg -> Map(dedupeKey -> {xy,t})
        for (let i = 0; i <= endIdx; i++) {
          const snap = s.snapshots[i];
          for (const tr of snap?.tracks || []) {
            if (!this._allowedByFilter("fusion", tr)) continue;
            const fid = tr.fusionId;
            if (!fid) continue;
            const hist = tr.committedHistory || tr.committed_updates || [];
            for (const c of hist) {
              if (c.fusionId && c.fusionId !== fid) continue;
              const ct = parseT(c.stateTime || c.measurementTime);
              if (!Number.isFinite(ct)) continue;
              if (nowT && Number.isFinite(nowT) && ct > nowT + 1) continue;
              const xy = this._commitXY(c);
              if (!xy || !this._isValidXY(xy)) continue;
              const seg = String(c.trackSegmentId ?? tr.trackSegmentId ?? "0");
              const trackKey = `${fid}||${seg}`;
              if (!byKey.has(trackKey)) byKey.set(trackKey, new Map());
              const bucket = byKey.get(trackKey);
              const dk = this._commitPointKey(c, fid) || `${ct}:${xy[0]}:${xy[1]}`;
              if (!bucket.has(dk)) bucket.set(dk, { xy, t: ct });
            }
          }
        }
        for (const [, bucket] of byKey) {
          flushRuns([...bucket.values()], COLORS.fused, false, 2.5);
        }
      }

      // Predicted history by episode: enter/exit predicted boundaries (never bridge across measured).
      if (this.layers.pred) {
        const episodes = []; // {key, pts:[{xy,t}]}
        const open = new Map(); // key -> current episode pts
        const closeKey = (key) => {
          const pts = open.get(key);
          if (pts && pts.length) episodes.push({ key, pts: pts.slice() });
          open.delete(key);
        };
        for (let i = 0; i <= endIdx; i++) {
          const snap = s.snapshots[i];
          const snapT = parseT(snap?.processingTime || snap?.watermark);
          const seen = new Set();
          for (const tr of snap?.tracks || []) {
            if (!this._allowedByFilter("fusion", tr)) continue;
            const seg = String(tr.trackSegmentId ?? "0");
            const key = `${tr.fusionId}||${seg}`;
            seen.add(key);
            if (!isPredicted(tr.positionMode)) {
              closeKey(key); // measured/stale restores break the prediction episode
              continue;
            }
            const hist = tr.predictedHistory || tr.predicted_history || [];
            if (hist.length) {
              // Prefer explicit episode points if present; still respect measured interrupts above.
              if (!open.has(key)) open.set(key, []);
              const arr = open.get(key);
              for (const p of hist) {
                const pt = parseT(p.displayStateTime || p.stateTime || p.time);
                if (!Number.isFinite(pt)) continue;
                if (nowT && Number.isFinite(nowT) && pt > nowT + 1) continue;
                const xy = (p.east_m != null && p.north_m != null)
                  ? [Number(p.east_m), Number(p.north_m)]
                  : this._llToXY(p.latitude, p.longitude);
                const last = arr[arr.length - 1];
                if (last && last.t === pt && last.xy[0] === xy[0] && last.xy[1] === xy[1]) continue;
                arr.push({ xy, t: pt });
              }
            } else {
              const pt = parseT(tr.displayStateTime || tr.stateTime) || snapT;
              if (!Number.isFinite(pt)) continue;
              if (nowT && Number.isFinite(nowT) && pt > nowT + 1) continue;
              if (!open.has(key)) open.set(key, []);
              const arr = open.get(key);
              const xy = this._llToXY(tr.latitude, tr.longitude);
              const last = arr[arr.length - 1];
              if (last && Math.abs(last.t - pt) < 1 && last.xy[0] === xy[0] && last.xy[1] === xy[1]) continue;
              // Also break on long gaps inside a continuous predicted run
              if (last && pt - last.t > GAP_MS) {
                closeKey(key);
                open.set(key, [{ xy, t: pt }]);
              } else {
                arr.push({ xy, t: pt });
              }
            }
          }
          // Tracks absent this snap for an open episode → close (rebirth / termination boundary)
          for (const key of [...open.keys()]) {
            if (!seen.has(key)) closeKey(key);
          }
        }
        for (const key of [...open.keys()]) closeKey(key);
        for (const ep of episodes) flushRuns(ep.pts, COLORS.pred, true, 1.5);
      }

      const snap = s.snapshots[this.tIndex];
      for (const tr of snap?.tracks || []) {
        if (!this._allowedByFilter("fusion", tr)) continue;
        if (!this._isValidLatLon(tr.latitude, tr.longitude)) continue;
        const xy = this._llToXY(tr.latitude, tr.longitude);
        const pred = isPredicted(tr.positionMode);
        const showCurrent = this.layers.current !== false;
        if (!showCurrent) continue;
        const label = this._trackLabel(tr);
        const selected = this.selectedFusionId && tr.fusionId === this.selectedFusionId;
        this._point(xy[0], xy[1], pred ? COLORS.pred : COLORS.fused, pred ? "diamond" : "square", label, 1, selected);
        // Direction hint is NOT predicted-history evidence (separate color/label).
        if (this.layers.pred && pred && tr.speed != null && tr.heading != null) {
          const rad = (tr.heading * Math.PI) / 180;
          const dist = Math.min(40, (tr.speed || 0) * 2);
          const x2 = xy[0] + Math.sin(rad) * dist;
          const y2 = xy[1] + Math.cos(rad) * dist;
          this._poly([xy, [x2, y2]], COLORS.hint, true, "方向示意", 1);
        }
      }
    }

    // route edit overlay
    if (this.routeEdit?.points?.length) {
      const pts = this.routeEdit.points.map((p) => [p.x_m, p.y_m]);
      if (pts.length >= 2) this._poly(pts, "#ffe066", false, "edit", 2);
      for (const p of this.routeEdit.points) this._point(p.x_m, p.y_m, "#ffe066", "circle");
    }

    const el = document.getElementById("scale");
    if (el) {
      const { sx } = this._cssScale();
      const barCanvasPx = 50;
      const barCssPx = barCanvasPx / Math.max(1e-9, sx);
      const meters = barCanvasPx / Math.max(1e-12, this.scale);
      el.textContent = `比例尺 ${meters.toFixed(0)} m / ${barCssPx.toFixed(0)} CSS px`;
    }
  }

  /** Buffer-space XY from client coordinates (works outside canvas with pointer capture). */
  _eventXY(e) {
    const { sx, sy, rect } = this._cssScale();
    let clientX = e.clientX;
    let clientY = e.clientY;
    const finite = Number.isFinite(clientX) && Number.isFinite(clientY);
    const outside = finite && (
      clientX < rect.left - 1 || clientX > rect.right + 1 ||
      clientY < rect.top - 1 || clientY > rect.bottom + 1
    );
    // Wheel synthesizers may omit client coords or place them at (0,0)/off-canvas.
    if (!finite || (clientX === 0 && clientY === 0) || (e.type === "wheel" && outside)) {
      clientX = this._lastClient?.x ?? (rect.left + rect.width / 2);
      clientY = this._lastClient?.y ?? (rect.top + rect.height / 2);
    } else {
      this._lastClient = { x: clientX, y: clientY };
    }
    const cssX = clientX - rect.left;
    const cssY = clientY - rect.top;
    return { x: cssX * sx, y: cssY * sy, cssX, cssY };
  }

  _endPointerGesture() {
    if (this.drag?.moved) this._suppressClick = true;
    if (this.routeEdit) {
      if (this.routeEdit.moved || this.routeEdit.dragging != null) {
        this.routeEdit.suppressClick = true;
      }
      this.routeEdit.dragging = null;
    }
    this.drag = null;
  }

  _onPointerDown(e) {
    if (e.button != null && e.button !== 0) return;
    const { x, y, cssX, cssY } = this._eventXY(e);
    try { this.cv.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ }
    if (this.routeEdit) {
      this.routeEdit.moved = false;
      const hit = this._hitRoutePoint(x, y);
      if (hit >= 0) {
        this.routeEdit.dragging = hit;
        this.routeEdit.down = { x, y, cssX, cssY };
        return;
      }
      this.routeEdit.down = { x, y, cssX, cssY };
    }
    this.drag = { x, y, cssX, cssY, ox: this.ox, oy: this.oy, moved: false, pointerId: e.pointerId };
  }

  _onPointerMove(e) {
    const { x, y, cssX, cssY } = this._eventXY(e);
    if (this.routeEdit?.dragging != null) {
      const distCss = this.routeEdit.down
        ? Math.hypot(cssX - this.routeEdit.down.cssX, cssY - this.routeEdit.down.cssY)
        : 0;
      if (distCss > this.DRAG_CLICK_PX) {
        this.routeEdit.moved = true;
        this.routeEdit.suppressClick = true;
      }
      const [wx, wy] = this.screenToWorld(x, y);
      this.routeEdit.points[this.routeEdit.dragging] = {
        x_m: wx,
        y_m: wy,
        dwell_s: this.routeEdit.points[this.routeEdit.dragging].dwell_s || 0,
      };
      this._scheduleDraw();
      if (this.routeEdit.onChange) this.routeEdit.onChange(this.routeEdit.points);
      return;
    }
    if (this.routeEdit?.down && this.routeEdit.dragging == null) {
      const distCss = Math.hypot(cssX - this.routeEdit.down.cssX, cssY - this.routeEdit.down.cssY);
      if (distCss > this.DRAG_CLICK_PX) {
        this.routeEdit.moved = true;
        this.routeEdit.suppressClick = true;
      }
    }
    if (!this.drag) return;
    const distCss = Math.hypot(cssX - this.drag.cssX, cssY - this.drag.cssY);
    if (distCss > this.DRAG_CLICK_PX) this.drag.moved = true;
    if (!this.drag.moved) return;
    this.ox = this.drag.ox + (x - this.drag.x);
    this.oy = this.drag.oy + (y - this.drag.y);
    this._viewManual = true;
    this._scheduleDraw();
  }

  _onPointerUp(e) {
    try {
      if (e?.pointerId != null) this.cv.releasePointerCapture(e.pointerId);
    } catch (_) { /* ignore */ }
    this._endPointerGesture();
  }

  _onClick(e) {
    if (this._suppressClick) {
      this._suppressClick = false;
      return;
    }
    const { x, y } = this._eventXY(e);
    if (this.routeEdit && this.routeEdit.mode === "add") {
      if (this.routeEdit.suppressClick || this.routeEdit.moved) {
        this.routeEdit.suppressClick = false;
        this.routeEdit.moved = false;
        this.routeEdit.down = null;
        return;
      }
      if (this._hitRoutePoint(x, y) >= 0) return;
      const [wx, wy] = this.screenToWorld(x, y);
      this.routeEdit.points.push({ x_m: wx, y_m: wy, dwell_s: 0 });
      this.draw();
      if (this.routeEdit.onChange) this.routeEdit.onChange(this.routeEdit.points);
      return;
    }
    this._pick(x, y);
  }

  _hitRoutePoint(sx, sy) {
    if (!this.routeEdit) return -1;
    for (let i = 0; i < this.routeEdit.points.length; i++) {
      const p = this.routeEdit.points[i];
      const [px, py] = this.worldToScreen(p.x_m, p.y_m);
      if (Math.hypot(px - sx, py - sy) < 10) return i;
    }
    return -1;
  }

  startRouteEdit(points, onChange) {
    this.routeEdit = {
      points: points.map((p) => ({ ...p })),
      mode: "add",
      dragging: null,
      onChange,
      suppressClick: false,
      moved: false,
    };
    this.draw();
  }
  stopRouteEdit() { this.routeEdit = null; this.draw(); }

  _grid() {
    const { ctx, cv } = this;
    ctx.strokeStyle = "#1c2838";
    ctx.lineWidth = 1;
    for (let i = -40; i <= 40; i++) {
      const [x0, y0] = this.worldToScreen(i * 50, -2000);
      const [x1, y1] = this.worldToScreen(i * 50, 2000);
      ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
      const [a0, b0] = this.worldToScreen(-2000, i * 50);
      const [a1, b1] = this.worldToScreen(2000, i * 50);
      ctx.beginPath(); ctx.moveTo(a0, b0); ctx.lineTo(a1, b1); ctx.stroke();
    }
    ctx.strokeStyle = "#8fa3bf";
    ctx.beginPath();
    ctx.moveTo(20, cv.height - 20);
    ctx.lineTo(70, cv.height - 20);
    ctx.stroke();
  }

  _llToXY(lat, lon) {
    const ORIGIN_LAT = 39.13, ORIGIN_LON = 117.20, M = 111320;
    const y = (lat - ORIGIN_LAT) * M;
    const x = (lon - ORIGIN_LON) * M * Math.cos((ORIGIN_LAT * Math.PI) / 180);
    return [x, y];
  }

  _poly(pts, color, dashed, label, width = 2, alpha = 1) {
    if (!pts || pts.length < 2) return;
    const { ctx } = this;
    ctx.save();
    if (alpha < 1) ctx.globalAlpha = alpha;
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.setLineDash(dashed ? [6, 4] : []);
    ctx.beginPath();
    pts.forEach((p, i) => {
      const [x, y] = this.worldToScreen(p[0], p[1]);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.setLineDash([]);
    if (label) {
      const [x, y] = this.worldToScreen(pts[0][0], pts[0][1]);
      ctx.fillStyle = color;
      ctx.font = "11px sans-serif";
      ctx.fillText(label, x + 6, y - 6);
    }
    ctx.restore();
  }

  _points(pts, color, alpha = 1) {
    for (const p of pts) this._point(p[0], p[1], color, "circle", null, alpha);
  }

  /** Readable name + short unique id (avoid truncating all fusionIds to the same F… prefix). */
  _trackLabel(tr) {
    const name = this._readableName(tr);
    const fid = String(tr.fusionId || "");
    let short = "";
    if (fid) {
      // Prefer trailing unique segment (e.g. after last '-' or last 6 chars)
      const parts = fid.split(/[-_]/);
      short = parts.length > 1 ? parts[parts.length - 1].slice(-6) : fid.slice(-6);
    }
    if (name && short) return `${name}·${short}`;
    return name || short || "?";
  }

  _readableName(tr) {
    if (tr.aircraftId) {
      for (const [lab, e] of this.displayIndex) {
        if (e.sns.has(tr.aircraftId)) return lab;
      }
      return String(tr.aircraftId);
    }
    for (const [lab, e] of this.displayIndex) {
      if (e.fusionIds.has(tr.fusionId)) {
        // anonymous radar: show sim label distinctly from device SN
        return `${lab}(仿真)`;
      }
      for (const st of tr.sourceTracks || []) {
        if (e.trackKeys.has(trackKey(st))) return e.sns.size ? lab : `${lab}(仿真)`;
      }
    }
    return null;
  }

  _point(wx, wy, color, shape, label, alpha = 1, selected = false) {
    const [x, y] = this.worldToScreen(wx, wy);
    const { ctx } = this;
    ctx.save();
    if (alpha < 1) ctx.globalAlpha = alpha;
    if (selected) {
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(x, y, 10, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.fillStyle = color;
    ctx.beginPath();
    if (shape === "square") ctx.rect(x - 4, y - 4, 8, 8);
    else if (shape === "diamond") {
      ctx.moveTo(x, y - 5); ctx.lineTo(x + 5, y); ctx.lineTo(x, y + 5); ctx.lineTo(x - 5, y); ctx.closePath();
    } else ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
    if (label) {
      ctx.globalAlpha = 1;
      ctx.fillStyle = selected ? "#ffffff" : "#cfd8e6";
      ctx.font = selected ? "bold 11px sans-serif" : "10px sans-serif";
      ctx.fillText(label, x + 6, y + 3);
    }
    ctx.restore();
  }

  _pick(sx, sy) {
    if (!this.state || !this.onPick) return;
    const now = this.currentTimeMs();
    // Hit radius is 12 CSS px, converted to buffer space (matches _eventXY).
    const { sx: cssSx } = this._cssScale();
    const hitR = 12 * Math.max(cssSx || 1, 1e-6);
    const candidates = [];
    const layers = this.layers || {};

    for (const o of this.state.observations || []) {
      if (parseT(o.measurementTime) > now + 1) continue;
      if (!this._allowedByFilter("obs", o)) continue;
      // Match draw: per-source layer (rid/spectrum/radar), not a generic "obs" flag.
      if (o.source && layers[o.source] === false) continue;
      const [x, y] = this._llToXY(o.latitude, o.longitude);
      const [px, py] = this.worldToScreen(x, y);
      const d = Math.hypot(px - sx, py - sy);
      if (d <= hitR) {
        candidates.push({ kind: "obs", d, obj: o, label: `obs ${o.observationId || ""}` });
      }
    }

    // Fusion history: same rolling union as draw (not last-80 snapshot alone).
    if (layers.fused !== false) {
      const fids = new Set();
      const endIdx = Math.min(this.tIndex, (this.state.snapshots?.length || 1) - 1);
      for (let i = 0; i <= endIdx; i++) {
        for (const tr of this.state.snapshots[i]?.tracks || []) {
          if (tr.fusionId && this._allowedByFilter("fusion", tr)) fids.add(tr.fusionId);
        }
      }
      for (const fid of fids) {
        const collected = this.collectFusionTrackPoints(fid, { includeFuture: false });
        for (const p of collected.pts) {
          if (!p.pointId) continue;
          const [px, py] = this.worldToScreen(p.xy[0], p.xy[1]);
          const d = Math.hypot(px - sx, py - sy);
          if (d > hitR) continue;
          // Recover full commit payload from any snapshot that still holds it.
          let ptObj = null;
          for (let i = endIdx; i >= 0 && !ptObj; i--) {
            for (const tr of this.state.snapshots[i]?.tracks || []) {
              if (tr.fusionId !== fid) continue;
              const hit = (tr.committedHistory || []).find((c) => c.pointId === p.pointId);
              if (hit) {
                ptObj = {
                  ...hit,
                  fusionId: hit.fusionId || fid,
                  _linkedObservations: (hit.observationIds || [])
                    .map((id) => (this.state.observations || []).find((o) => o.observationId === id))
                    .filter(Boolean),
                };
                break;
              }
            }
          }
          if (!ptObj) {
            ptObj = {
              pointId: p.pointId,
              fusionId: fid,
              stateTime: p.t,
              _linkedObservations: [],
            };
          }
          candidates.push({
            kind: "fusion_point",
            d,
            obj: ptObj,
            label: `fusionPoint ${p.pointId}`,
          });
        }
      }
    }

    // Current markers only when current layer is visible.
    if (layers.current !== false) {
      const snap = this.state.snapshots?.[this.tIndex];
      for (const tr of snap?.tracks || []) {
        if (!this._allowedByFilter("fusion", tr)) continue;
        if (!this._isValidLatLon(tr.latitude, tr.longitude)) continue;
        const [x, y] = this._llToXY(tr.latitude, tr.longitude);
        const [px, py] = this.worldToScreen(x, y);
        const d = Math.hypot(px - sx, py - sy);
        if (d <= hitR) {
          candidates.push({ kind: "track", d, obj: tr, label: `track ${tr.fusionId || ""}` });
        }
      }
    }

    if (!candidates.length) return;
    candidates.sort((a, b) => a.d - b.d);
    const best = candidates[0];
    if (candidates.length > 1 && this.onPickCandidates) {
      // Present chooser; do NOT auto-overwrite with onPick.
      this.onPickCandidates(candidates.slice(0, 8), best);
      return;
    }
    this.onPick(best.obj, best.kind);
  }
}
