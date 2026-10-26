/**
 * TASK-009 R1 shared display query: run + fusionId + cursor time + type.
 * Dedup by pointId (horizontal) / altitudeUpdateId (vertical). No snapshot-row counting.
 */

export function parseTimeMs(t) {
  if (t == null || t === "") return NaN;
  if (typeof t === "number" && Number.isFinite(t)) return t;
  const n = Date.parse(String(t));
  return Number.isFinite(n) ? n : NaN;
}

/**
 * Strict MSL datum for display axis (R2-01).
 * Empty/unknown/HAE/EGM aliases are NOT accepted — importer must emit explicit MSL
 * (incl. USER_ASSUMED DB→MSL). 0 and negative numeric altitudes remain valid when datum is MSL.
 */
export function isMslDatum(datum) {
  if (datum == null || datum === "") return false;
  const d = String(datum).trim().toUpperCase();
  return d === "MSL";
}

/** MSL axis usable: finite altitude (0/neg ok) + explicit MSL datum; expired/unknown excluded. */
export function isUsableMslAltitude(p) {
  if (!p) return false;
  const mode = String(p.altitudeMode || "").toLowerCase();
  if (mode === "expired" || mode === "unknown" || mode === "missing") return false;
  if (p.altitude == null || p.altitude === "") return false;
  if (!Number.isFinite(Number(p.altitude))) return false;
  return isMslDatum(p.altitudeDatum);
}

/**
 * @param {object} runState
 * @param {{ fusionId?: string|null, untilTimeMs?: number|null, fullHistory?: boolean, includeVertical?: boolean }} opts
 */
export function queryDisplayPoints(runState, opts = {}) {
  const fusionId = opts.fusionId || null;
  const fullHistory = !!opts.fullHistory;
  const until =
    opts.untilTimeMs != null && Number.isFinite(opts.untilTimeMs) ? opts.untilTimeMs : null;
  const includeVertical = opts.includeVertical !== false;
  const horiz = [];
  const seenH = new Set();
  const snaps = runState?.snapshots || [];
  for (const snap of snaps) {
    const snapT = parseTimeMs(snap.processingTime);
    if (!fullHistory && until != null && Number.isFinite(snapT) && snapT > until) continue;
    for (const tr of snap.tracks || []) {
      const fid = tr.fusionId;
      if (fusionId && fid !== fusionId) continue;
      for (const c of tr.committedHistory || []) {
        const pid = c.pointId;
        if (!pid || seenH.has(pid)) continue;
        const st = parseTimeMs(c.stateTime);
        if (!fullHistory && until != null && Number.isFinite(st) && st > until) continue;
        seenH.add(pid);
        horiz.push({
          ...c,
          fusionId: c.fusionId || fid,
          _kind: "horizontal",
        });
      }
    }
  }
  const vert = [];
  const seenV = new Set();
  if (includeVertical) {
    for (const u of runState?.altitudeUpdates || []) {
      const id = u.altitudeUpdateId;
      if (!id || seenV.has(id)) continue;
      if (fusionId && u.fusionId !== fusionId) continue;
      const st = parseTimeMs(u.stateTime);
      if (!fullHistory && until != null && Number.isFinite(st) && st > until) continue;
      seenV.add(id);
      vert.push({
        pointId: null,
        altitudeUpdateId: id,
        stateTime: u.stateTime,
        altitude: u.altitude,
        altitudeMode: u.altitudeMode,
        altitudeDatum: u.altitudeDatum,
        altitudeObservationIds: u.altitudeObservationIds,
        observationIds: u.altitudeObservationIds,
        source: u.source,
        fusionId: u.fusionId,
        trackSegmentId: u.trackSegmentId,
        _verticalOnly: true,
        _kind: "vertical",
      });
    }
  }
  const all = [...horiz, ...vert].sort(
    (a, b) => parseTimeMs(a.stateTime) - parseTimeMs(b.stateTime)
  );
  return { horizontal: horiz, vertical: vert, all, untilTimeMs: until, fullHistory };
}

/** Unique segment ids + time/alt ranges for card (horizontal only for XYZ counts). */
export function summarizeTrackDisplay(runState, fusionId, opts = {}) {
  const q = queryDisplayPoints(runState, { ...opts, fusionId, includeVertical: true });
  const segs = new Set();
  const times = [];
  const alts = [];
  for (const p of q.horizontal) {
    if (p.trackSegmentId) segs.add(p.trackSegmentId);
    const t = parseTimeMs(p.stateTime);
    if (Number.isFinite(t)) times.push(t);
    if (isUsableMslAltitude(p)) alts.push(Number(p.altitude));
  }
  for (const p of q.vertical) {
    if (p.trackSegmentId) segs.add(p.trackSegmentId);
    const t = parseTimeMs(p.stateTime);
    if (Number.isFinite(t)) times.push(t);
    if (isUsableMslAltitude(p)) alts.push(Number(p.altitude));
  }
  return {
    nHorizontal: q.horizontal.length,
    nVertical: q.vertical.length,
    nSegments: segs.size,
    t0: times.length ? Math.min(...times) : null,
    t1: times.length ? Math.max(...times) : null,
    altMin: alts.length ? Math.min(...alts) : null,
    altMax: alts.length ? Math.max(...alts) : null,
    fullHistory: !!opts.fullHistory,
  };
}
