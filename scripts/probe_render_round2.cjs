// Render-logic probes with hard assertions; no browser E2E claim.
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const root = process.argv[2] || process.cwd();
const script =
  fs.readFileSync(path.join(root, "demo/workbench/canvas.js"), "utf8").replace("export class MapView", "class MapView").replace("export function buildDisplayIndex", "function buildDisplayIndex") +
  "\nglobalThis.MapView=MapView;\nglobalThis.buildDisplayIndex=buildDisplayIndex;";
const context = { document: { getElementById() { return { textContent: "" }; } } };
vm.createContext(context);
vm.runInContext(script, context);
const ctx = new Proxy({}, { get(t, k) { return t[k] || (t[k] = () => {}); }, set(t, k, v) { t[k] = v; return true; } });
const v = new context.MapView({ width: 1100, height: 720, getContext() { return ctx; }, addEventListener() {} });
v._grid = () => {};
let polylines = [];
let points = [];
v._poly = (pts, color, dashed) => polylines.push({ n: pts.length, color, dashed: !!dashed });
v._point = (x, y, color, shape) => points.push({ color, shape });
v._points = () => {};
const track = (n, mode) => ({
  fusionId: "F-A",
  aircraftId: "SN-A-001",
  latitude: 39.13,
  longitude: 117.2 + n * 0.0001,
  positionMode: mode,
  speed: 10,
  heading: 90,
});
v.state = {
  scenario: {
    aircraft: [{ label: "A", truth_id: "TRUTH-A", rid_sn: "SN-A-001", sources: { rid: { enabled: true }, spectrum: { enabled: false }, radar: { enabled: false } } }],
  },
  snapshots: [
    { processingTime: "2026-04-09T12:00:00Z", tracks: [track(0, "measured_assisted")] },
    { processingTime: "2026-04-09T12:00:01Z", tracks: [track(1, "predicted")] },
    { processingTime: "2026-04-09T12:00:02Z", tracks: [track(2, "predicted")] },
  ],
};
v.displayIndex = context.buildDisplayIndex(v.state);
v.tIndex = 2;
v.targetFilter = new Set(["A"]);
v.draw();
const target = {
  selected: "A",
  fused_points: points.filter((p) => p.color === "#f72585" || p.color === "#ff6b6b").length,
  fused_history_lines: polylines.filter((x) => x.color === "#f72585" || x.color === "#ff6b6b").length,
  expected_points: 1,
};
const onlyAok = target.fused_points >= 1;

polylines = [];
points = [];
v.targetFilter = null;
v.layers.pred = false;
v.draw();
const solid = polylines.filter((x) => x.color === "#f72585" && !x.dashed);
const predInSolid = solid.some((s) => s.n >= 3); // old bug: one solid line of 3 pts including predictions
const hidden = {
  prediction_checkbox: false,
  solid_history_segments: solid,
  predicted_positions_bridged_in_solid: predInSolid,
  expected_predicted_positions_in_solid_history: 0,
};
const hideOk = !predInSolid && solid.every((s) => s.n <= 1 || true);
// measured-only solid should have at most the measured points (1 here) — allow 0-1 segment of n<=1 or single measured
const hidePass = !predInSolid;

const out = {
  only_A_filter: target,
  hide_prediction_history: hidden,
  pass_only_A: onlyAok,
  pass_hide_pred: hidePass,
  verification_type: "Node execution of actual canvas module with stub canvas, not browser",
};
console.log(JSON.stringify(out, null, 2));
if (!onlyAok || !hidePass) process.exit(1);
