/**
 * MI-R1 independent counterexamples (from official REWORK-R1 appendix).
 * Loads actual canvas.js via vm — does not rewrite MapView methods.
 *
 *   node scripts/task007_map_interaction_independent_r1.mjs [canvas.js] [out.json]
 */
import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";

const file = process.argv[2] || "demo/workbench/canvas.js";
const outPath = process.argv[3] || "reports/task007/map_interaction/r1/independent_counterexamples.json";
fs.mkdirSync(path.dirname(path.resolve(outPath)), { recursive: true });

const src = fs.readFileSync(file, "utf8").replaceAll("export ", "");
const sandbox = { window: { addEventListener() {} }, requestAnimationFrame: () => 1, Math, Date, Number, String, Array, Map, Set, Object, JSON, parseFloat, isFinite: Number.isFinite.bind(Number), Infinity, NaN, console };
vm.createContext(sandbox);
vm.runInContext(src + ";\nglobalThis.MapView=MapView;\nglobalThis.computeZoomAt=computeZoomAt;\nglobalThis.MAP_ZOOM_FACTOR=MAP_ZOOM_FACTOR;", sandbox);

const mk = (cssW = 900, cssH = 600) => {
  const events = {};
  const cv = {
    width: 1200,
    height: 800,
    getContext: () => ({}),
    getBoundingClientRect: () => ({ left: 120, top: 80, width: cssW, height: cssH }),
    addEventListener: (n, f) => { events[n] = f; },
    setPointerCapture() {},
    releasePointerCapture() {},
  };
  const m = new sandbox.MapView(cv);
  m.draw = () => {};
  return { m, events, cv };
};

const out = {};
const parseT = (s) => Date.parse(String(s).replace("Z", "+00:00"));
const at = (sec) => new Date(Date.UTC(2026, 9, 24, 0, 0, sec)).toISOString();
const binding = { source: "radar", detectorId: "D1", sourceTrackId: "local-7" };
const obs = (id, sec, lon) => ({ observationId: id, ...binding, measurementTime: at(sec), latitude: 37, longitude: lon });
const track = (fid, sec, lon, hist = []) => ({
  fusionId: fid, latitude: 37, longitude: lon, stateTime: at(sec),
  sourceTracks: [binding], committedHistory: hist,
});
const h = (sec, lon) => ({ stateTime: at(sec), latitude: 37, longitude: lon });

{
  const runs = [];
  for (const cssW of [1200, 900, 600]) {
    const { m, events, cv } = mk(cssW, cssW * 2 / 3);
    m.scale = 0.01; m.ox = 600; m.oy = 400;
    const world = [20000, 15000];
    const anchor = [800, 250];
    // Place world point under anchor before zooms
    m.ox = anchor[0] - world[0] * m.scale;
    m.oy = anchor[1] + world[1] * m.scale;
    let maxErr = 0;
    for (let i = 0; i < 20; i++) {
      events.wheel({
        clientX: 120 + anchor[0] * cssW / 1200,
        clientY: 80 + anchor[1] * (cssW * 2 / 3) / 800,
        deltaY: -100, deltaMode: 0,
        preventDefault() {}, stopPropagation() {},
      });
      const xy = m.worldToScreen(...world);
      maxErr = Math.max(maxErr, Math.hypot((xy[0] - 800) * cssW / 1200, (xy[1] - 250) * (cssW * 2 / 3) / 800));
    }
    runs.push({ cssWidth: cssW, canvasWidth: cv.width, steps: 20, maxErrorCssPx: maxErr, pass: maxErr <= 1 });
  }
  out.wheel_handler_anchor = runs;
}

{
  const { m } = mk();
  m.state = {
    observations: [obs("belongs-A", 0, 118), obs("belongs-B", 20, 120)],
    snapshots: [
      { processingTime: at(0), tracks: [track("fusion-A", 0, 118, [h(0, 118)])] },
      { processingTime: at(20), tracks: [track("fusion-B", 20, 120, [h(20, 120)])] },
    ],
  };
  m.tIndex = 1;
  const got = m.collectFusionTrackPoints("fusion-B");
  const oldXY = m._llToXY(37, 118);
  const containsWrong = got.pts.some((p) => Math.hypot(p.xy[0] - oldXY[0], p.xy[1] - oldXY[1]) < 1e-6)
    || (got.obsPts || []).some((p) => Math.hypot(p.xy[0] - oldXY[0], p.xy[1] - oldXY[1]) < 1e-6);
  m.fitFusionTrackHistory("fusion-B");
  out.binding_reuse = {
    expected: "only fusion-B geometry, exclude old fusion-A observation",
    containsOtherFusionObservation: containsWrong,
    returnedPointTimes: got.pts.map((p) => p.t),
    nFusion: got.nFusion,
    nObs: got.nObs,
    scaleAfterFit: m.scale,
    pass: !containsWrong,
  };
}

{
  const { m } = mk();
  const history = Array.from({ length: 81 }, (_, i) => h(i, 118 + i * 0.00001));
  m.state = {
    observations: [],
    snapshots: [
      { processingTime: at(79), tracks: [track("fusion-H", 79, 118.00079, history.slice(0, 80))] },
      { processingTime: at(80), tracks: [track("fusion-H", 80, 118.00080, history.slice(1, 81))] },
    ],
  };
  m.tIndex = 1;
  const got = m.collectFusionTrackPoints("fusion-H");
  const firstXY = m._llToXY(37, 118);
  const keepsFirst = got.pts.some((p) => Math.hypot(p.xy[0] - firstXY[0], p.xy[1] - firstXY[1]) < 1e-6);
  out.rolling_history = {
    expected: "union 81 already-occurred points from two 80-point rolling histories",
    keepsFirstSnapshotPoint: keepsFirst,
    returnedPointCount: got.pts.length,
    pass: keepsFirst && got.pts.length === 81,
  };
}

{
  const { m } = mk();
  m.layers = { rid: false, spectrum: false, radar: false, fused: false, current: true, pred: false, truth: false, plan: false };
  m.state = {
    observations: [],
    snapshots: [
      { processingTime: at(0), tracks: [track("fusion-C", 0, 118, [h(0, 118)])] },
      { processingTime: at(20), tracks: [track("fusion-C", 20, 120, [h(0, 118), h(20, 120)])] },
    ],
  };
  m.tIndex = 1;
  m.fitToData();
  const cur = m.worldToScreen(...m._llToXY(37, 120));
  const dist = Math.hypot(cur[0] - 600, cur[1] - 400);
  out.current_only_fit = {
    expected: "current marker centered, hidden history must not expand bounds",
    distanceFromCenterCanvasPx: dist,
    scale: m.scale,
    pass: dist <= 1,
  };
}

{
  const { m } = mk();
  const d1 = m._wheelFactor({ deltaY: -1, deltaMode: 0 });
  const d100 = m._wheelFactor({ deltaY: -100, deltaMode: 0 });
  const d0 = m._wheelFactor({ deltaY: 0, deltaMode: 0 });
  out.trackpad_factor = {
    delta1: d1,
    delta100: d100,
    delta0: d0,
    distinct: d1 !== d100,
    pass: d0 == null && d1 != null && d100 != null && d1 !== d100 && d1 < d100,
    note: "1-pixel trackpad delta must be gentler than 100-pixel notch; reciprocal continuous factor",
  };
}

// Extra: mid-timeline future leak + no silent fit-all
{
  const { m } = mk();
  m.state = {
    observations: [],
    snapshots: [
      { processingTime: at(10), tracks: [track("fusion-F", 10, 119, [h(10, 119)])] },
      { processingTime: at(30), tracks: [track("fusion-F", 30, 121, [h(10, 119), h(30, 121)])] },
    ],
  };
  m.tIndex = 0; // mid — must not include t=30
  const got = m.collectFusionTrackPoints("fusion-F");
  const futureLeak = got.pts.some((p) => p.t > parseT(at(10)) + 1);
  const empty = m.collectFusionTrackPoints("fusion-NONE");
  const beforeScale = m.scale;
  const r = m.fitFusionTrackHistory("fusion-NONE");
  out.future_and_empty = {
    futureLeak,
    emptyReason: empty.reason,
    emptyFitOk: r.ok,
    scaleUnchangedOnEmpty: m.scale === beforeScale,
    pass: !futureLeak && empty.reason === "no_history" && r.ok === false && m.scale === beforeScale,
  };
}

const failures = ["binding_reuse", "rolling_history", "current_only_fit", "trackpad_factor", "future_and_empty"]
  .filter((k) => !out[k].pass);
out.summary = {
  blockingFailureCount: failures.length,
  blockingFailures: failures,
  anchorPass: out.wheel_handler_anchor.every((r) => r.pass),
};
fs.writeFileSync(outPath, JSON.stringify(out, null, 2));
console.log(JSON.stringify(out.summary, null, 2));
process.exitCode = failures.length || !out.summary.anchorPass ? 1 : 0;
if (!process.exitCode) console.log("INDEPENDENT_R1_OK");
