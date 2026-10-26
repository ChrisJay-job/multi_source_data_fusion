import { colorFromFusionId, distPointSeg, shortFid } from "./ux_helpers.js";

/**
 * Lightweight ENU+MSL track inspection view (rotate / pan / zoom).
 * Not a globe; Z is altitude_m (MSL) with optional exaggerate factor.
 * Gaps / segment boundaries break measured polylines; invalid altitudes are not drawn as 0/MSL.
 */
export class Track3DView {
  constructor(canvas) {
    this.cv = canvas;
    this.ctx = canvas.getContext("2d");
    this.yaw = 0.6;
    this.pitch = 0.55;
    this.scale = 0.08;
    this.ox = canvas.width / 2;
    this.oy = canvas.height / 2 + 40;
    this.zExag = 1;
    this.origin = null; // {lat0, lon0}
    /** @type {{fusionId:string,trackSegmentId:string,pts:any[]}[]} */
    this.tracks = [];
    this.selectedPointId = null;
    /** @type {string|null} selected full fusionId (highlight whole track) */
    this.selectedFusionId = null;
    this.compare = [];
    this.onPick = null;
    /** @type {(cands:any[], best?:any)=>void} */
    this.onPickCandidates = () => {};
    /** @type {(fid:string, meta?:object)=>void} */
    this.onPickTrack = null;
    this._overlapCycle = [];
    this._overlapIdx = 0;
    this._drag = null;
    this._untilTimeMs = null;
    /** @type {object|null} last runState object bound — camera fit only on new run / explicit fit */
    this._boundRun = null;
    this._hasFitted = false;
    /** @type {{fused?:boolean,current?:boolean,pred?:boolean,rid?:boolean,spectrum?:boolean,radar?:boolean}} */
    this.layers = { fused: true, current: true, pred: true };
    /** Cached visible fused screen segments for pick (rebuilt on draw). */
    this._segCache = [];
    this._bind();
  }

  _bind() {
    const cv = this.cv;
    cv.addEventListener("pointerdown", (e) => {
      cv.setPointerCapture(e.pointerId);
      this._drag = {
        x: e.clientX,
        y: e.clientY,
        yaw: this.yaw,
        pitch: this.pitch,
        ox: this.ox,
        oy: this.oy,
        pan: e.shiftKey || e.button === 1 || e.button === 2,
        moved: false,
      };
    });
    cv.addEventListener("pointermove", (e) => {
      if (!this._drag) return;
      const dx = e.clientX - this._drag.x;
      const dy = e.clientY - this._drag.y;
      if (Math.hypot(dx, dy) > 3) this._drag.moved = true;
      if (this._drag.pan) {
        // CSS delta → canvas pixels (DPR-safe): 100 CSS px must move 100 CSS on screen.
        const rect = this.cv.getBoundingClientRect();
        const sx = this.cv.width / (rect.width || 1);
        const sy = this.cv.height / (rect.height || 1);
        this.ox = this._drag.ox + dx * sx;
        this.oy = this._drag.oy + dy * sy;
      } else {
        // Orbit around selected world pivot (not distant empty origin).
        const pe = this._orbitE ?? this._cx ?? 0;
        const pn = this._orbitN ?? this._cy ?? 0;
        const pz = this._orbitZ ?? (this._cz || 0) / (this.zExag || 1);
        const before = this._project(pe, pn, pz);
        this.yaw = this._drag.yaw + dx * 0.01;
        this.pitch = Math.max(0.0, Math.min(1.45, this._drag.pitch + dy * 0.01));
        const after = this._project(pe, pn, pz);
        this.ox += before.x - after.x;
        this.oy += before.y - after.y;
      }
      this.draw();
    });
    const end = (e) => {
      if (!this._drag) return;
      const wasClick = !this._drag.moved;
      this._drag = null;
      try {
        cv.releasePointerCapture(e.pointerId);
      } catch (_) {}
      if (wasClick) {
        const { x, y } = this._eventToCanvas(e);
        this._pickAt(x, y);
      }
    };
    cv.addEventListener("pointerup", end);
    cv.addEventListener("pointercancel", end);
    cv.addEventListener("lostpointercapture", () => {
      this._drag = null;
    });
    cv.addEventListener("contextmenu", (e) => e.preventDefault());
    cv.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        let dy = e.deltaY;
        if (e.deltaMode === 1) dy *= 16;
        else if (e.deltaMode === 2) dy *= this.cv.height;
        // deltaY=0 must be a no-op; do not treat as zoom-out.
        if (!Number.isFinite(dy) || dy === 0) return;
        const f = dy < 0 ? 1.1 : 1 / 1.1;
        const MIN_SCALE = 0.005;
        const oldScale = this.scale;
        let next = oldScale * f;
        // Zoom-out at/below MIN must not reverse into a larger scale.
        if (f < 1 && oldScale <= MIN_SCALE) return;
        if (f < 1 && next < MIN_SCALE) next = MIN_SCALE;
        if (!(next > 0) || !Number.isFinite(next)) return;
        // Screen-space anchor (DPR-safe via _eventToCanvas): keep ray under cursor fixed.
        let mx;
        let my;
        if (e && (Number.isFinite(e.clientX) || Number.isFinite(e.offsetX))) {
          const p = this._eventToCanvas(e);
          mx = p.x;
          my = p.y;
        }
        if (!Number.isFinite(mx) || !Number.isFinite(my)) {
          mx = this.cv.width / 2;
          my = this.cv.height / 2;
        }
        if (oldScale > 0 && Number.isFinite(oldScale)) {
          const x1 = (mx - this.ox) / oldScale;
          const y2 = (this.oy - my) / oldScale;
          this.scale = next;
          this.ox = mx - x1 * this.scale;
          this.oy = my + y2 * this.scale;
        } else {
          this.scale = next;
        }
        this.draw();
      },
      { passive: false }
    );
  }

  _ptsForFusion(fid, opts = {}) {
    // Never fall back to another fusionId — missing target must fail clearly.
    // Altitude-estimated points stay in history (submitted XY); only skip horiz/future pred.
    // includePredicted (legacy probe name) maps to includeHorizPredicted.
    const includeHoriz =
      opts.includeHorizPredicted ?? opts.includePredicted ?? true;
    const match = (this.tracks || []).filter((t) => t.fusionId === fid);
    return match.flatMap((t) =>
      (t.pts || []).filter(
        (p) => !p.gap && !p.scatter && (includeHoriz || !p.predictedHoriz)
      )
    );
  }

  _worldSpanM(pts) {
    let minE = Infinity,
      maxE = -Infinity,
      minN = Infinity,
      maxN = -Infinity,
      minZ = Infinity,
      maxZ = -Infinity;
    for (const p of pts) {
      minE = Math.min(minE, p.e);
      maxE = Math.max(maxE, p.e);
      minN = Math.min(minN, p.n);
      maxN = Math.max(maxN, p.n);
      minZ = Math.min(minZ, p.z);
      maxZ = Math.max(maxZ, p.z);
    }
    return {
      e: maxE - minE,
      n: maxN - minN,
      z: maxZ - minZ,
      max: Math.max(maxE - minE, maxN - minN, (maxZ - minZ) * (this.zExag || 1)),
    };
  }

  /** Rebind without resetting play-clock to snapshot[0] (would drop almost all history). */
  _rebindPreservingClock(runState) {
    if (!runState) return;
    const untilIso =
      this._untilTimeMs != null && Number.isFinite(this._untilTimeMs)
        ? new Date(this._untilTimeMs).toISOString()
        : null;
    const lastIdx = (runState.snapshots || []).length
      ? (runState.snapshots || []).length - 1
      : 0;
    this.setRunState(runState, {
      fit: false,
      layers: this.layers,
      // Prefer current play clock; else end-of-run (already happened), never silent frame-0 trim.
      ...(untilIso
        ? { untilTime: untilIso }
        : { snapshotIndex: lastIdx }),
    });
  }

  centerOnFusionId(fid, runState) {
    let pts = this._ptsForFusion(fid, { includeHorizPredicted: true });
    if (!pts.length && runState) {
      this._rebindPreservingClock(runState);
      pts = this._ptsForFusion(fid, { includeHorizPredicted: true });
    }
    if (!pts.length) {
      return { ok: false, message: "三维无该目标有效位置（缺高度/未绘制）" };
    }
    return this._focusPts(pts, { local: true });
  }

  fitFusionTrackHistory(fid, runState) {
    // Do not call bare setRunState(runState) — default snapshotIndex=0 wipes history to tip.
    if (runState) this._rebindPreservingClock(runState);
    // Include altitude-estimated history; exclude only horiz/future prediction.
    const pts = this._ptsForFusion(fid, { includeHorizPredicted: false });
    if (!pts.length) {
      return { ok: false, message: "三维无该目标已发生历史点" };
    }
    return this._focusPts(pts, { local: false });
  }

  _focusPts(pts, { local }) {
    let minE = Infinity,
      maxE = -Infinity,
      minN = Infinity,
      maxN = -Infinity,
      minZ = Infinity,
      maxZ = -Infinity;
    for (const p of pts) {
      minE = Math.min(minE, p.e);
      maxE = Math.max(maxE, p.e);
      minN = Math.min(minN, p.n);
      maxN = Math.max(maxN, p.n);
      minZ = Math.min(minZ, p.z);
      maxZ = Math.max(maxZ, p.z);
    }
    this._cx = (minE + maxE) / 2;
    this._cy = (minN + maxN) / 2;
    this._cz = ((minZ + maxZ) / 2) * this.zExag;
    // Orbit pivot = selected target center (world).
    this._orbitE = this._cx;
    this._orbitN = this._cy;
    this._orbitZ = (minZ + maxZ) / 2;
    if (local) {
      const tip = pts[pts.length - 1];
      this._cx = tip.e;
      this._cy = tip.n;
      this._cz = tip.z * this.zExag;
      this._orbitE = tip.e;
      this._orbitN = tip.n;
      this._orbitZ = tip.z;
      this.scale = Math.min(this.cv.width, this.cv.height) / 80;
    }
    const fitInfo = this._fitProjected(pts, { focus: true });
    this.draw();
    const coincident = !!fitInfo?.coincident;
    return {
      ok: true,
      coincident,
      message: coincident
        ? local
          ? "三维定位完成（单点/静止）"
          : "三维航迹聚焦完成（单点/静止，无线段）"
        : local
          ? "三维定位完成"
          : "三维航迹聚焦完成",
    };
  }

  /** Fit so current yaw/pitch projection of pts stays inside canvas with padding. */
  _fitProjected(pts, { focus = false } = {}) {
    if (!pts?.length) return { coincident: false };
    const pad = 40;
    const MAX_SCALE = 2000;
    // Fit may go far below manual wheel floor so multi-km spans stay on canvas.
    const FIT_MIN_SCALE = 1e-7;
    const world = this._worldSpanM(pts);
    // True coincidence: world span < ~1 m (not merely sub-pixel at global scale).
    const coincidentWorld = world.max < 1.0;
    let coincident = coincidentWorld;
    // Iteratively adjust scale/ox/oy against projected bounds.
    for (let iter = 0; iter < 12; iter++) {
      let minX = Infinity,
        maxX = -Infinity,
        minY = Infinity,
        maxY = -Infinity;
      for (const p of pts) {
        const q = this._project(p.e, p.n, p.z);
        minX = Math.min(minX, q.x);
        maxX = Math.max(maxX, q.x);
        minY = Math.min(minY, q.y);
        maxY = Math.max(maxY, q.y);
      }
      const spanX = maxX - minX;
      const spanY = maxY - minY;
      if (spanX < 4 && spanY < 4) {
        if (coincidentWorld) {
          // Genuine single/stationary: modest local scale for visibility, center only.
          if (focus) {
            this.scale = Math.min(
              MAX_SCALE,
              Math.max(this.scale, Math.min(this.cv.width, this.cv.height) / 80)
            );
          }
          this.ox += this.cv.width / 2 - (minX + maxX) / 2;
          this.oy += this.cv.height / 2 - (minY + maxY) / 2;
          break;
        }
        // Sub-pixel but real world span: zoom so projected span fills ~60% of canvas.
        const target = Math.min(this.cv.width, this.cv.height) * 0.6;
        const cur = Math.max(spanX, spanY, 1e-12);
        const boost = target / cur;
        if (Number.isFinite(boost) && boost > 1.01) {
          this.scale = Math.min(MAX_SCALE, Math.max(FIT_MIN_SCALE, this.scale * boost));
          continue;
        }
        this.ox += this.cv.width / 2 - (minX + maxX) / 2;
        this.oy += this.cv.height / 2 - (minY + maxY) / 2;
        break;
      }
      const bw = Math.max(spanX, 1);
      const bh = Math.max(spanY, 1);
      const sx = (this.cv.width - 2 * pad) / bw;
      const sy = (this.cv.height - 2 * pad) / bh;
      // Focus mode allows larger per-step zoom to recover readable tracks from overview.
      const stepCap = focus ? 32 : 4;
      const f = Math.min(sx, sy, stepCap);
      if (Number.isFinite(f) && f > 0 && Math.abs(f - 1) > 0.01) {
        this.scale = Math.min(MAX_SCALE, Math.max(FIT_MIN_SCALE, this.scale * f));
      }
      let minX2 = Infinity,
        maxX2 = -Infinity,
        minY2 = Infinity,
        maxY2 = -Infinity;
      for (const p of pts) {
        const q = this._project(p.e, p.n, p.z);
        minX2 = Math.min(minX2, q.x);
        maxX2 = Math.max(maxX2, q.x);
        minY2 = Math.min(minY2, q.y);
        maxY2 = Math.max(maxY2, q.y);
      }
      const cx = (minX2 + maxX2) / 2;
      const cy = (minY2 + maxY2) / 2;
      this.ox += this.cv.width / 2 - cx;
      this.oy += this.cv.height / 2 - cy;
    }
    if (!Number.isFinite(this.scale) || this.scale > MAX_SCALE) this.scale = MAX_SCALE;
    if (this.scale < FIT_MIN_SCALE) this.scale = FIT_MIN_SCALE;
    return { coincident };
  }

  _eventToCanvas(e) {
    const rect = this.cv.getBoundingClientRect();
    const cssW = rect.width || 1;
    const cssH = rect.height || 1;
    let cssX = e.offsetX;
    let cssY = e.offsetY;
    if (!Number.isFinite(cssX) || !Number.isFinite(cssY)) {
      cssX = e.clientX - rect.left;
      cssY = e.clientY - rect.top;
    }
    return {
      x: (cssX / cssW) * this.cv.width,
      y: (cssY / cssH) * this.cv.height,
    };
  }

  setZExaggerate(x) {
    this.zExag = Math.max(0.25, Math.min(20, Number(x) || 1));
    this.draw();
  }

  setView(mode) {
    if (mode === "top") {
      // pitch=0 → look along -Z (plan view); ΔZ must not separate same-XY points.
      this.yaw = 0;
      this.pitch = 0;
      // Keep selected orbit context; re-fit current filtered projection.
      this.fit();
    } else if (mode === "side") {
      this.yaw = Math.PI / 2;
      this.pitch = Math.PI / 2;
      this.fit();
    } else if (mode === "reset") {
      this.yaw = 0.6;
      this.pitch = 0.55;
      this.scale = 0.08;
      this.ox = this.cv.width / 2;
      this.oy = this.cv.height / 2 + 40;
      this.fit();
    }
    this.draw();
  }

  _llToEnu(lat, lon) {
    if (!this.origin) this.origin = { lat0: lat, lon0: lon };
    const R = 6378137;
    const dLat = ((lat - this.origin.lat0) * Math.PI) / 180;
    const dLon = ((lon - this.origin.lon0) * Math.PI) / 180;
    const n = dLat * R;
    const e = dLon * R * Math.cos((this.origin.lat0 * Math.PI) / 180);
    return { e, n };
  }

  /**
   * @param {object|null} runState
   * @param {{fusionFilter?:string|null, untilTime?:string|null, snapshotIndex?:number|null}} [opts]
   */
  setRunState(runState, opts = {}) {
    const fusionFilter = opts.fusionFilter ?? null;
    // Duck-type Set (VM/cross-realm instanceof Set is unreliable).
    const rawIdSet = opts.fusionIdSet;
    /** @type {{has:(v:string)=>boolean,size:number}|null} */
    const fusionIdSet =
      rawIdSet && typeof rawIdSet.has === "function" && rawIdSet.size > 0
        ? rawIdSet
        : null;
    const layersIn = opts.layers && typeof opts.layers === "object" ? opts.layers : null;
    this.layers = layersIn
      ? {
          fused: !!layersIn.fused,
          current: !!layersIn.current,
          pred: !!layersIn.pred,
          rid: !!layersIn.rid,
          spectrum: !!layersIn.spectrum,
          radar: !!layersIn.radar,
        }
      : { fused: true, current: true, pred: true };
    let untilMs = null;
    // Default = "already happened" at current/first frame — not full future history.
    // Opt-in full history: { fullHistory: true } (must be labeled in UI if exposed).
    if (opts.fullHistory) {
      untilMs = null;
    } else if (opts.untilTime != null && opts.untilTime !== "") {
      const t = Date.parse(opts.untilTime);
      if (Number.isFinite(t)) untilMs = t;
    } else if (runState?.snapshots?.length) {
      const idx = Number.isFinite(opts.snapshotIndex) ? opts.snapshotIndex : 0;
      const snap = runState.snapshots[Math.max(0, Math.min(idx, runState.snapshots.length - 1))];
      if (snap?.processingTime) {
        const t = Date.parse(snap.processingTime);
        if (Number.isFinite(t)) untilMs = t;
      }
    }
    this._untilTimeMs = untilMs;
    this.tracks = [];
    this.origin = null;
    if (!runState) {
      this._boundRun = null;
      this._hasFitted = false;
      this.draw();
      return { n3d: 0, skipped: 0, reasons: {} };
    }
    if (runState !== this._boundRun) {
      this._boundRun = runState;
      this._hasFitted = false;
    }
    const reasons = {};
    let skipped = 0;
    /** @type {Map<string, any[]>} */
    const byKey = new Map();
    const pushGap = (fid, c, ptT, mode, extra = {}) => {
      const segId = c.trackSegmentId || "default";
      const key = `${fid}||${segId}`;
      if (!byKey.has(key)) byKey.set(key, []);
      byKey.get(key).push({
        gap: true,
        t: ptT,
        pointId: c.pointId,
        fusionId: fid,
        trackSegmentId: segId,
        mode,
        ...extra,
      });
    };
    const allowFid = (fid) => {
      if (fusionFilter && fid !== fusionFilter) return false;
      if (fusionIdSet && !fusionIdSet.has(fid)) return false;
      return true;
    };
    const snaps = runState.snapshots || [];
    const seen = new Set();
    for (const snap of snaps) {
      const snapT = Date.parse(snap.processingTime || "") || 0;
      if (untilMs != null && snapT > untilMs) continue;
      for (const tr of snap.tracks || []) {
        const fid = tr.fusionId;
        if (!allowFid(fid)) continue;
        for (const c of tr.committedHistory || []) {
          const pid = c.pointId;
          if (!pid || seen.has(pid)) continue;
          const ptT = Date.parse(c.stateTime || "") || 0;
          if (untilMs != null && ptT > untilMs) continue;
          seen.add(pid);
          const altRaw = c.altitude;
          const datum = c.altitudeDatum;
          const mode = c.altitudeMode || "";
          // Empty string / null / NaN are invalid (do not coerce to 0).
          if (altRaw === "" || altRaw == null || !Number.isFinite(Number(altRaw))) {
            skipped++;
            reasons.null_or_nan = (reasons.null_or_nan || 0) + 1;
            // Keep a gap marker in the segment stream so draw breaks (not deleted-then-joined).
            pushGap(fid, c, ptT, mode);
            continue;
          }
          if (!datum || String(datum).trim().toUpperCase() !== "MSL") {
            skipped++;
            reasons.unknown_datum = (reasons.unknown_datum || 0) + 1;
            pushGap(fid, c, ptT, mode);
            continue;
          }
          if (mode === "expired") {
            skipped++;
            reasons.expired = (reasons.expired || 0) + 1;
            pushGap(fid, c, ptT, "expired");
            continue;
          }
          if (c.latitude == null || c.longitude == null) {
            skipped++;
            reasons.no_xy = (reasons.no_xy || 0) + 1;
            pushGap(fid, c, ptT, mode);
            continue;
          }
          const { e, n } = this._llToEnu(c.latitude, c.longitude);
          const segId = c.trackSegmentId || "default";
          const key = `${fid}||${segId}`;
          if (!byKey.has(key)) byKey.set(key, []);
          // altitudeMode "predicted" = altitude estimate, NOT horizontal/future traj.
          // Keep submitted XY on fused history; mark altitudeEstimated for style/detail.
          const posMode = String(c.positionMode || tr.positionMode || "");
          const horizPred =
            posMode === "predicted" ||
            posMode === "future" ||
            posMode === "extrapolated";
          byKey.get(key).push({
            e,
            n,
            z: Number(altRaw),
            t: ptT,
            pointId: pid,
            mode,
            fusionId: fid,
            trackSegmentId: segId,
            latitude: c.latitude,
            longitude: c.longitude,
            altitude: Number(altRaw),
            altitudeDatum: datum === "msl" ? "MSL" : datum,
            stateTime: c.stateTime,
            altitudeEstimated: mode === "predicted",
            predictedHoriz: horizPred,
            // Legacy `predicted` = altitudeMode predicted (detail/counters); draw uses predictedHoriz.
            predicted: mode === "predicted",
            gap: false,
          });
        }
      }
    }
    const L = this.layers || {};
    const showFused = !!L.fused;
    const showCurrent = !!L.current;
    const showPred = !!L.pred;
    // Layer filter: only-current / only-pred must not keep full measured history polylines.
    // Altitude-estimated points remain part of measured history when fused is on.
    if (!showFused) {
      for (const [key, pts] of [...byKey.entries()]) {
        pts.sort((a, b) => a.t - b.t);
        const kept = [];
        if (showPred) {
          for (const p of pts) {
            if (p.gap || p.predictedHoriz || p.altitudeEstimated) kept.push(p);
          }
        }
        if (showCurrent) {
          const measured = pts.filter((p) => !p.gap && !p.predictedHoriz);
          const tip = measured.length ? measured[measured.length - 1] : null;
          if (tip && !kept.some((p) => p.pointId && p.pointId === tip.pointId)) kept.push(tip);
        }
        if (kept.length) byKey.set(key, kept);
        else byKey.delete(key);
      }
    }
    // Raw observation scatter (explicit MSL only); never polyline-join across targets.
    // Cursor: linked OIDs only from already-happened commits; obs.measurementTime <= untilMs.
    // showUnlinkedRaw changes ownership filter only — never skips the time cursor.
    const rawSources = ["rid", "spectrum", "radar"].filter((s) => !!L[s]);
    const showUnlinkedRaw = !!opts.showUnlinkedRaw;
    let linkedOidSet = null;
    if (rawSources.length && (fusionFilter || fusionIdSet) && !showUnlinkedRaw) {
      linkedOidSet = new Set();
      for (const snap of snaps) {
        const snapT = Date.parse(snap.processingTime || "");
        if (untilMs != null && Number.isFinite(snapT) && snapT > untilMs) continue;
        for (const tr of snap.tracks || []) {
          const fid = tr.fusionId;
          if (!allowFid(fid)) continue;
          for (const c of tr.committedHistory || []) {
            const ptT = Date.parse(c.stateTime || "");
            if (untilMs != null && Number.isFinite(ptT) && ptT > untilMs) continue;
            for (const id of c.observationIds || []) linkedOidSet.add(id);
            for (const id of c.altitudeObservationIds || []) linkedOidSet.add(id);
          }
        }
      }
      for (const u of runState.altitudeUpdates || []) {
        if (!allowFid(u.fusionId)) continue;
        const ut = Date.parse(u.stateTime || "");
        if (untilMs != null && (!Number.isFinite(ut) || ut > untilMs)) continue;
        for (const id of u.altitudeObservationIds || []) linkedOidSet.add(id);
      }
    }
    let rawSkippedUnlinked = 0;
    let rawSkippedFuture = 0;
    let rawSkippedBadTime = 0;
    if (rawSources.length) {
      for (const obs of runState.observations || []) {
        const src = String(obs.source || "");
        if (!rawSources.includes(src)) continue;
        if (linkedOidSet && !linkedOidSet.has(obs.observationId)) {
          rawSkippedUnlinked++;
          continue;
        }
        const mt = Date.parse(obs.measurementTime || "");
        if (!Number.isFinite(mt)) {
          rawSkippedBadTime++;
          skipped++;
          reasons.raw_bad_time = (reasons.raw_bad_time || 0) + 1;
          continue;
        }
        if (untilMs != null && mt > untilMs) {
          rawSkippedFuture++;
          continue;
        }
        const altRaw = obs.altitude;
        const datum = obs.altitudeDatum;
        if (altRaw === "" || altRaw == null || !Number.isFinite(Number(altRaw))) continue;
        // Strict explicit MSL only (same as ux_query.isMslDatum).
        if (!datum || String(datum).trim().toUpperCase() !== "MSL") continue;
        if (obs.latitude == null || obs.longitude == null) continue;
        const { e, n } = this._llToEnu(obs.latitude, obs.longitude);
        const oid = obs.observationId || `raw-${src}-${e}-${n}`;
        const key = `raw:${src}||scatter`;
        if (!byKey.has(key)) byKey.set(key, []);
        byKey.get(key).push({
          e,
          n,
          z: Number(altRaw),
          t: mt,
          pointId: oid,
          mode: "raw_observation",
          fusionId: `raw:${src}`,
          trackSegmentId: "scatter",
          latitude: obs.latitude,
          longitude: obs.longitude,
          altitude: Number(altRaw),
          altitudeDatum: "MSL",
          stateTime: obs.measurementTime,
          predicted: false,
          predictedHoriz: false,
          altitudeEstimated: false,
          scatter: true,
          gap: false,
          source: src,
          observationId: oid,
          detectorId: obs.detectorId,
          sourceTrackId: obs.sourceTrackId,
          aircraftId: obs.aircraftId,
        });
      }
    }
    if (rawSkippedUnlinked) {
      reasons.raw_unlinked_filtered = (reasons.raw_unlinked_filtered || 0) + rawSkippedUnlinked;
    }
    if (rawSkippedFuture) {
      reasons.raw_future_cursor = (reasons.raw_future_cursor || 0) + rawSkippedFuture;
    }
    for (const [key, pts] of byKey) {
      pts.sort((a, b) => a.t - b.t);
      const [fusionId, trackSegmentId] = key.split("||");
      this.tracks.push({ fusionId, trackSegmentId, pts });
    }
    const n3d = [...byKey.values()].reduce(
      (a, p) => a + p.filter((x) => !x.gap).length,
      0
    );
    // Fit only on first non-empty bind of a run, or when caller explicitly requests fit.
    // Live MQTT increments must not reset camera; empty first bind must not consume the fit token.
    if (opts.fit === true || (opts.fit !== false && !this._hasFitted)) {
      if (n3d > 0) {
        this.fit();
        this._hasFitted = true;
      }
    }
    this.draw();
    return {
      n3d,
      skipped,
      reasons,
      origin: this.origin,
      zExag: this.zExag,
    };
  }

  fit() {
    const all = this.tracks.flatMap((t) => t.pts.filter((p) => !p.gap));
    if (!all.length) return false;
    let minE = Infinity,
      maxE = -Infinity,
      minN = Infinity,
      maxN = -Infinity,
      minZ = Infinity,
      maxZ = -Infinity;
    for (const p of all) {
      minE = Math.min(minE, p.e);
      maxE = Math.max(maxE, p.e);
      minN = Math.min(minN, p.n);
      maxN = Math.max(maxN, p.n);
      minZ = Math.min(minZ, p.z);
      maxZ = Math.max(maxZ, p.z);
    }
    this._cx = (minE + maxE) / 2;
    this._cy = (minN + maxN) / 2;
    this._cz = ((minZ + maxZ) / 2) * this.zExag;
    // Prefer existing orbit pivot (selected target) when still inside current points.
    if (
      !Number.isFinite(this._orbitE) ||
      !all.some(
        (p) =>
          Math.abs(p.e - this._orbitE) < 1e-6 &&
          Math.abs(p.n - this._orbitN) < 1e-6 &&
          Math.abs(p.z - this._orbitZ) < 1e-6
      )
    ) {
      this._orbitE = this._cx;
      this._orbitN = this._cy;
      this._orbitZ = (minZ + maxZ) / 2;
    }
    // Seed scale from world span, then enforce current projected bounds + padding.
    const span = Math.max(maxE - minE, maxN - minN, (maxZ - minZ) * this.zExag, 20);
    this.scale = Math.min(this.cv.width, this.cv.height) / (span * 1.6);
    this.ox = this.cv.width / 2;
    this.oy = this.cv.height / 2;
    this._fitProjected(all);
    return true;
  }

  _project(e, n, z) {
    const x = e - (this._cx || 0);
    const y = n - (this._cy || 0);
    const zz = z * this.zExag - (this._cz || 0);
    const cy = Math.cos(this.yaw),
      sy = Math.sin(this.yaw);
    const cp = Math.cos(this.pitch),
      sp = Math.sin(this.pitch);
    const x1 = x * cy - y * sy;
    const y1 = x * sy + y * cy;
    const y2 = y1 * cp - zz * sp;
    const z2 = y1 * sp + zz * cp;
    return {
      x: this.ox + x1 * this.scale,
      y: this.oy - y2 * this.scale,
      depth: z2,
    };
  }

  draw() {
    const ctx = this.ctx;
    const { width: W, height: H } = this.cv;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#0b1220";
    ctx.fillRect(0, 0, W, H);
    const o = this._project(this._cx || 0, this._cy || 0, (this._cz || 0) / this.zExag);
    const ex = this._project((this._cx || 0) + 50 / this.scale, this._cy || 0, (this._cz || 0) / this.zExag);
    const ey = this._project(this._cx || 0, (this._cy || 0) + 50 / this.scale, (this._cz || 0) / this.zExag);
    const ez = this._project(this._cx || 0, this._cy || 0, (this._cz || 0) / this.zExag + 50 / this.scale);
    const axis = (a, b, color, label) => {
      ctx.strokeStyle = color;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
      ctx.fillStyle = color;
      ctx.fillText(label, b.x + 4, b.y);
    };
    axis(o, ex, "#ef476f", "E(m)");
    axis(o, ey, "#06d6a0", "N(m)");
    axis(o, ez, "#118ab2", "Z MSL(m)");
    ctx.fillStyle = "#adb5bd";
    ctx.fillText(`Z×${this.zExag} · origin lat/lon fixed · units meters`, 8, 16);

    const L = this.layers || { fused: true, current: true, pred: true };
    this._segCache = [];
    let selectedLabelAt = null;
    this.tracks.forEach((tr) => {
      const fid = tr.fusionId;
      const isSel = this.selectedFusionId && fid === this.selectedFusionId;
      const col = colorFromFusionId(fid);
      const lw = isSel ? 4.5 : 1.5;
      // Measured polyline — fused history includes altitude-estimated XY; never join raw scatter;
      // break on gap / segment boundary / horiz prediction; do not invent edges across breaks.
      if (L.fused && !String(fid).startsWith("raw:")) {
        let prev = null;
        ctx.strokeStyle = isSel ? "#ffffff" : col;
        ctx.lineWidth = lw;
        ctx.beginPath();
        let started = false;
        for (const p of tr.pts) {
          if (p.gap || p.predictedHoriz || p.scatter) {
            started = false;
            prev = null;
            continue;
          }
          const q = this._project(p.e, p.n, p.z);
          if (prev) {
            this._segCache.push({
              fusionId: fid,
              trackSegmentId: tr.trackSegmentId,
              x0: prev.x,
              y0: prev.y,
              x1: q.x,
              y1: q.y,
            });
          }
          if (!started) {
            ctx.moveTo(q.x, q.y);
            started = true;
          } else ctx.lineTo(q.x, q.y);
          prev = q;
          if (isSel) selectedLabelAt = q;
        }
        ctx.stroke();
        if (isSel) {
          // Underlay stroke for contrast
          ctx.strokeStyle = col;
          ctx.lineWidth = 2;
          // already stroked white thick; color tip via points below
        }
      }
      // Horiz/future prediction dashed — only when pred layer is on (not altitude estimate).
      if (L.pred && !String(fid).startsWith("raw:")) {
        let started = false;
        ctx.setLineDash([4, 3]);
        ctx.strokeStyle = col;
        ctx.lineWidth = isSel ? 3 : 1.5;
        ctx.beginPath();
        for (const p of tr.pts) {
          if (p.gap || !p.predictedHoriz || p.scatter) {
            started = false;
            continue;
          }
          const q = this._project(p.e, p.n, p.z);
          if (!started) {
            ctx.moveTo(q.x, q.y);
            started = true;
          } else ctx.lineTo(q.x, q.y);
        }
        ctx.stroke();
        ctx.setLineDash([]);
      }
      // Points: fused history (incl. altitude-estimated), current tip, horiz pred, or raw scatter.
      for (const p of tr.pts) {
        if (p.gap) continue;
        if (p.scatter) {
          /* raw obs always drawable when present in tracks */
        } else if (p.predictedHoriz && !L.pred) continue;
        else if (!p.predictedHoriz && !L.fused && !L.current) continue;
        // current-only: draw only last measured tip
        if (!L.fused && L.current && !p.scatter && !p.predictedHoriz) {
          const measured = tr.pts.filter((x) => !x.gap && !x.scatter && !x.predictedHoriz);
          const tip = measured[measured.length - 1];
          if (!tip || tip.pointId !== p.pointId) continue;
        }
        const q = this._project(p.e, p.n, p.z);
        const selected = p.pointId === this.selectedPointId;
        if (p.altitudeEstimated && L.fused) {
          ctx.strokeStyle = selected || isSel ? "#fff" : col;
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.arc(q.x, q.y, selected ? 5 : 3.5, 0, Math.PI * 2);
          ctx.stroke();
          ctx.fillStyle = selected ? "#fff" : "rgba(0,0,0,0.35)";
          ctx.beginPath();
          ctx.arc(q.x, q.y, selected ? 2 : 1.5, 0, Math.PI * 2);
          ctx.fill();
        } else {
          ctx.fillStyle = selected || isSel ? "#fff" : col;
          ctx.beginPath();
          ctx.arc(q.x, q.y, selected ? 4 : p.scatter ? 3 : isSel ? 3 : 2, 0, Math.PI * 2);
          ctx.fill();
        }
        if (isSel && !selectedLabelAt) selectedLabelAt = q;
      }
    });
    if (selectedLabelAt && this.selectedFusionId) {
      const label = shortFid(this.selectedFusionId);
      ctx.font = "12px sans-serif";
      const tw = ctx.measureText(label).width;
      const lx = Math.min(W - tw - 12, Math.max(8, selectedLabelAt.x + 8));
      const ly = Math.max(28, selectedLabelAt.y - 10);
      ctx.fillStyle = "rgba(0,0,0,0.65)";
      ctx.fillRect(lx - 4, ly - 12, tw + 8, 16);
      ctx.fillStyle = "#fff";
      ctx.fillText(label, lx, ly);
    }
    // Empty layers: axes only (already drawn); status left to caller.
    this.compare.forEach((pid, i) => {
      for (const tr of this.tracks) {
        const p = tr.pts.find((x) => x.pointId === pid && !x.gap);
        if (!p) continue;
        const q = this._project(p.e, p.n, p.z);
        ctx.strokeStyle = i === 0 ? "#fff" : "#ff9f1c";
        ctx.strokeRect(q.x - 6, q.y - 6, 12, 12);
      }
    });
  }

  _pickAt(x, y) {
    const L = this.layers || {};
    const cands = [];
    // Point hits first (prefer point detail).
    for (const tr of this.tracks) {
      for (const p of tr.pts) {
        if (p.gap) continue;
        if (p.scatter) {
          /* ok if raw layer on — scatter tracks only exist when layer on */
        } else if (p.predictedHoriz && !L.pred) continue;
        else if (!p.predictedHoriz && !L.fused && !L.current) continue;
        const q = this._project(p.e, p.n, p.z);
        const d = Math.hypot(q.x - x, q.y - y);
        if (d < 12) cands.push({ kind: "point", p, fusionId: p.fusionId || tr.fusionId, d });
      }
    }
    // Visible fused segment hits (CSS px via canvas coords; DPR already in canvas size).
    if (L.fused) {
      for (const seg of this._segCache || []) {
        const d = distPointSeg(x, y, seg.x0, seg.y0, seg.x1, seg.y1);
        if (d < 10) {
          cands.push({
            kind: "segment",
            fusionId: seg.fusionId,
            trackSegmentId: seg.trackSegmentId,
            d,
            p: {
              fusionId: seg.fusionId,
              trackSegmentId: seg.trackSegmentId,
              pointId: null,
              _pickKind: "track",
            },
          });
        }
      }
    }
    cands.sort((a, b) => a.d - b.d);
    if (!cands.length) return;

    // Deduplicate by fusionId for track cycling; keep point candidates with pointId.
    const uniq = [];
    const seen = new Set();
    for (const c of cands) {
      const key =
        c.kind === "point" && c.p?.pointId
          ? `pt:${c.p.pointId}`
          : `tr:${c.fusionId}`;
      if (seen.has(key)) continue;
      seen.add(key);
      uniq.push(c);
    }

    const ids = uniq.map((c) =>
      c.kind === "point" && c.p?.pointId ? c.p.pointId : `tr:${c.fusionId}`
    );
    const same =
      this._overlapCycle.length === ids.length &&
      this._overlapCycle.every((id, i) => id === ids[i]);
    if (!same) {
      this._overlapCycle = ids;
      this._overlapIdx = 0;
    } else {
      this._overlapIdx = (this._overlapIdx + 1) % ids.length;
    }
    const best = uniq[this._overlapIdx];
    if (best.kind === "point" && best.p?.pointId) {
      this.selectedPointId = best.p.pointId;
      this.selectedFusionId = best.fusionId || best.p.fusionId || null;
    } else {
      this.selectedPointId = null;
      this.selectedFusionId = best.fusionId || null;
    }
    this.draw();
    const mapped = uniq.map((c) =>
      c.kind === "point"
        ? { ...c.p, fusionId: c.fusionId || c.p?.fusionId, _pickKind: c.p?.scatter ? "raw" : "point" }
        : {
            fusionId: c.fusionId,
            trackSegmentId: c.trackSegmentId,
            pointId: null,
            _pickKind: "track",
          }
    );
    if (typeof this.onPickCandidates === "function" && mapped.length > 1) {
      this.onPickCandidates(mapped, best.kind === "point" ? best.p : mapped.find((m) => m._pickKind === "track"));
    }
    // Point vs track: mutually exclusive dispatch — avoid point then track double refresh.
    if (best.kind === "point") {
      if (typeof this.onPick === "function") this.onPick(best.p);
    } else if (typeof this.onPickTrack === "function" && this.selectedFusionId) {
      this.onPickTrack(this.selectedFusionId, { via: "segment", point: null });
    }
  }

  selectPointId(pid) {
    this.selectedPointId = pid || null;
    this.draw();
  }

  selectFusionId(fid) {
    this.selectedFusionId = fid || null;
    this.draw();
  }

  toggleCompare(pid) {
    if (!pid) return this.compare;
    const i = this.compare.indexOf(pid);
    if (i >= 0) this.compare.splice(i, 1);
    else {
      this.compare.push(pid);
      if (this.compare.length > 2) this.compare.shift();
    }
    this.draw();
    return this.compare.slice();
  }

  compareDelta() {
    if (this.compare.length < 2) return null;
    const find = (pid) => {
      for (const tr of this.tracks) {
        const p = tr.pts.find((x) => x.pointId === pid && !x.gap);
        if (p) return p;
      }
      return null;
    };
    const a = find(this.compare[0]);
    const b = find(this.compare[1]);
    if (!a || !b) return null;
    const sameDatum = a.altitudeDatum === b.altitudeDatum;
    return {
      a,
      b,
      dtMs: b.t - a.t,
      dAltM: sameDatum ? b.altitude - a.altitude : null,
      note: "双点比较不代表已找到交叉时刻/最近接近时刻",
    };
  }
}
