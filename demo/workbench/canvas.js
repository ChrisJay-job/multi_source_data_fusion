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

export class MapView {
  constructor(canvas) {
    this.cv = canvas;
    this.ctx = canvas.getContext("2d");
    this.scale = 1.2;
    this.ox = canvas.width / 2;
    this.oy = canvas.height / 2;
    this.layers = { rid: true, spectrum: true, radar: true, fused: true, pred: true, truth: true, plan: true };
    this.targetFilter = null; // Set of labels / ids from UI
    this.displayIndex = new Map();
    this.state = null;
    this.tIndex = 0;
    this.drag = null;
    this.onPick = null;
    this.routeEdit = null; // { aircraftIndex, points: [{x_m,y_m}], dragging }
    this._fitted = false;
    this._cssScale = () => {
      const r = this.cv.getBoundingClientRect();
      return { sx: this.cv.width / Math.max(1, r.width), sy: this.cv.height / Math.max(1, r.height) };
    };

    canvas.addEventListener("mousedown", (e) => this._onDown(e));
    canvas.addEventListener("mousemove", (e) => this._onMove(e));
    canvas.addEventListener("mouseup", () => {
      this.drag = null;
      if (this.routeEdit) {
        if (this.routeEdit.moved || this.routeEdit.dragging != null) {
          this.routeEdit.suppressClick = true;
        }
        this.routeEdit.dragging = null;
      }
    });
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      this.scale *= e.deltaY > 0 ? 0.9 : 1.1;
      this.draw();
    }, { passive: false });
    canvas.addEventListener("click", (e) => this._onClick(e));
  }

  setLayers(layers) { Object.assign(this.layers, layers); this.draw(); }
  setTargetFilter(set) { this.targetFilter = set; this.draw(); }
  setState(state, { fit = true, resetTime = true } = {}) {
    this.state = state;
    this.displayIndex = buildDisplayIndex(state || {});
    this._fitted = false;
    if (resetTime) this.tIndex = 0;
    if (fit) this.fitToData();
    this.draw();
  }
  setTimeIndex(i) {
    const n = this.state?.snapshots?.length || 1;
    this.tIndex = Math.max(0, Math.min(i, n - 1));
    this.draw();
  }
  resetView() { this.fitToData(); this.draw(); }

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

  fitToData() {
    const pts = [];
    const s = this.state;
    if (!s) return;
    for (const o of s.observations || []) {
      const xy = this._llToXY(o.latitude, o.longitude);
      if (Number.isFinite(xy[0])) pts.push(xy);
    }
    for (const arr of Object.values(s.truth_polyline || {})) {
      for (const p of arr) pts.push([p.x_m, p.y_m]);
    }
    for (const snap of s.snapshots || []) {
      for (const tr of snap.tracks || []) {
        pts.push(this._llToXY(tr.latitude, tr.longitude));
      }
    }
    if (!pts.length) return;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const [x, y] of pts) {
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
    const dx = Math.max(50, maxX - minX);
    const dy = Math.max(50, maxY - minY);
    this.scale = Math.min(this.cv.width / (dx * 1.3), this.cv.height / (dy * 1.3));
    this.ox = this.cv.width / 2 - ((minX + maxX) / 2) * this.scale;
    this.oy = this.cv.height / 2 + ((minY + maxY) / 2) * this.scale;
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
        for (const seg of segs) {
          const pts = seg.map((o) => this._llToXY(o.latitude, o.longitude));
          this._points(pts, color);
          if (pts.length >= 2) this._poly(pts, color, false, null, 2);
        }
      }
    }

    // Fused history: measured solid / predicted dashed; hide pred removes predicted segments entirely
    if ((this.layers.fused || this.layers.pred) && s.snapshots) {
      const hist = new Map(); // fusionId -> [{xy, mode, seg}]
      for (let i = 0; i <= this.tIndex; i++) {
        const snap = s.snapshots[i];
        for (const tr of snap.tracks || []) {
          if (!this._allowedByFilter("fusion", tr)) continue;
          const xy = this._llToXY(tr.latitude, tr.longitude);
          const mode = tr.positionMode || "measured_assisted";
          const seg = tr.trackSegmentId || "0";
          if (!hist.has(tr.fusionId)) hist.set(tr.fusionId, []);
          const arr = hist.get(tr.fusionId);
          const last = arr[arr.length - 1];
          if (!last || last.xy[0] !== xy[0] || last.xy[1] !== xy[1] || last.mode !== mode) {
            arr.push({ xy, mode, seg });
          }
        }
      }
      for (const [, pts] of hist) {
        // split into contiguous same-mode segments; never solid-bridge across predicted when pred hidden
        let run = [];
        let runMode = null;
        const flush = () => {
          if (run.length < 2) { run = []; return; }
          const pred = isPredicted(runMode);
          if (pred && !this.layers.pred) { run = []; return; }
          if (!pred && !this.layers.fused) { run = []; return; }
          this._poly(run.map((p) => p.xy), pred ? COLORS.pred : COLORS.fused, pred, null, 2);
          run = [];
        };
        for (const p of pts) {
          if (runMode == null) runMode = p.mode;
          if (p.mode !== runMode || (run.length && p.seg !== run[run.length - 1].seg)) {
            flush();
            runMode = p.mode;
          }
          // skip predicted samples entirely when pred off (no bridging)
          if (isPredicted(p.mode) && !this.layers.pred) {
            flush();
            runMode = null;
            continue;
          }
          if (isMeasured(p.mode) && !this.layers.fused) {
            flush();
            runMode = null;
            continue;
          }
          run.push(p);
        }
        flush();
      }
      const snap = s.snapshots[this.tIndex];
      for (const tr of snap?.tracks || []) {
        if (!this._allowedByFilter("fusion", tr)) continue;
        const xy = this._llToXY(tr.latitude, tr.longitude);
        const pred = isPredicted(tr.positionMode);
        if (pred && !this.layers.pred) continue;
        if (!pred && !this.layers.fused) continue;
        this._point(xy[0], xy[1], pred ? COLORS.pred : COLORS.fused, pred ? "diamond" : "square", (tr.aircraftId || tr.fusionId || "").slice(0, 8));
        // Direction hint ONLY — not algorithm prediction trajectory
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
    if (el) el.textContent = `比例尺 ${(50 / this.scale).toFixed(0)} m / 50px`;
  }

  _eventXY(e) {
    const { sx, sy } = this._cssScale();
    return { x: e.offsetX * sx, y: e.offsetY * sy };
  }

  _onDown(e) {
    const { x, y } = this._eventXY(e);
    if (this.routeEdit) {
      // keep suppressClick until _onClick consumes it (drag must not add a point)
      this.routeEdit.moved = false;
      const hit = this._hitRoutePoint(x, y);
      if (hit >= 0) {
        this.routeEdit.dragging = hit;
        this.routeEdit.down = { x, y };
        return;
      }
      this.routeEdit.down = { x, y };
    }
    this.drag = { x, y, ox: this.ox, oy: this.oy };
  }

  _onMove(e) {
    const { x, y } = this._eventXY(e);
    if (this.routeEdit?.dragging != null) {
      const dist = this.routeEdit.down
        ? Math.hypot(x - this.routeEdit.down.x, y - this.routeEdit.down.y)
        : 0;
      if (dist > 4) {
        this.routeEdit.moved = true;
        this.routeEdit.suppressClick = true;
      }
      const [wx, wy] = this.screenToWorld(x, y);
      this.routeEdit.points[this.routeEdit.dragging] = {
        x_m: wx,
        y_m: wy,
        dwell_s: this.routeEdit.points[this.routeEdit.dragging].dwell_s || 0,
      };
      this.draw();
      if (this.routeEdit.onChange) this.routeEdit.onChange(this.routeEdit.points);
      return;
    }
    if (this.routeEdit?.down && !this.routeEdit.dragging) {
      const dist = Math.hypot(x - this.routeEdit.down.x, y - this.routeEdit.down.y);
      if (dist > 6) {
        this.routeEdit.moved = true;
        this.routeEdit.suppressClick = true;
      }
    }
    if (!this.drag) return;
    this.ox = this.drag.ox + (x - this.drag.x);
    this.oy = this.drag.oy + (y - this.drag.y);
    this.draw();
  }

  _onClick(e) {
    const { x, y } = this._eventXY(e);
    if (this.routeEdit && this.routeEdit.mode === "add") {
      if (this.routeEdit.suppressClick || this.routeEdit.moved) {
        this.routeEdit.suppressClick = false;
        this.routeEdit.moved = false;
        this.routeEdit.down = null;
        return;
      }
      // blank click adds a point; clicking existing point without move does not add
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

  _poly(pts, color, dashed, label, width = 2) {
    if (!pts || pts.length < 2) return;
    const { ctx } = this;
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
  }

  _points(pts, color) {
    for (const p of pts) this._point(p[0], p[1], color, "circle");
  }

  _point(wx, wy, color, shape, label) {
    const [x, y] = this.worldToScreen(wx, wy);
    const { ctx } = this;
    ctx.fillStyle = color;
    ctx.beginPath();
    if (shape === "square") ctx.rect(x - 4, y - 4, 8, 8);
    else if (shape === "diamond") {
      ctx.moveTo(x, y - 5); ctx.lineTo(x + 5, y); ctx.lineTo(x, y + 5); ctx.lineTo(x - 5, y); ctx.closePath();
    } else ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
    if (label) {
      ctx.fillStyle = "#cfd8e6";
      ctx.font = "10px sans-serif";
      ctx.fillText(label, x + 6, y + 3);
    }
  }

  _pick(sx, sy) {
    if (!this.state || !this.onPick) return;
    const now = this.currentTimeMs();
    let best = null, bestD = 12, kind = null;
    for (const o of this.state.observations || []) {
      if (parseT(o.measurementTime) > now + 1) continue;
      if (!this._allowedByFilter("obs", o)) continue;
      const [x, y] = this._llToXY(o.latitude, o.longitude);
      const [px, py] = this.worldToScreen(x, y);
      const d = Math.hypot(px - sx, py - sy);
      if (d < bestD) { bestD = d; best = o; kind = "obs"; }
    }
    const snap = this.state.snapshots?.[this.tIndex];
    for (const tr of snap?.tracks || []) {
      if (!this._allowedByFilter("fusion", tr)) continue;
      const [x, y] = this._llToXY(tr.latitude, tr.longitude);
      const [px, py] = this.worldToScreen(x, y);
      const d = Math.hypot(px - sx, py - sy);
      if (d < bestD) { bestD = d; best = tr; kind = "track"; }
    }
    if (best) this.onPick(best, kind);
  }
}
