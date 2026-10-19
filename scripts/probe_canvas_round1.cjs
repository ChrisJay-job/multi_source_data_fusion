/** Render-logic probe (not browser E2E). Expects time-filtered grouping. */
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const root = process.argv[2] || process.cwd();
const code =
  fs.readFileSync(path.join(root, "demo/workbench/canvas.js"), "utf8").replace("export class MapView", "class MapView") +
  "\nglobalThis.MapView=MapView;";
const sandbox = { document: { getElementById() { return { textContent: "" }; } } };
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const ctx = new Proxy({}, { get(t, k) { return t[k] || (t[k] = () => {}); }, set(t, k, v) { t[k] = v; return true; } });
const view = new sandbox.MapView({ width: 1100, height: 720, getContext() { return ctx; }, addEventListener() {} });
let polylines = [];
let rawPoints = 0;
let fusedHist = 0;
view._grid = () => {};
view._points = (pts) => { rawPoints += pts.length; };
view._poly = (pts, color, dashed) => { polylines.push({ n: pts.length, color, dashed: !!dashed }); if (color === "#f72585" && pts.length >= 2) fusedHist++; };
view._point = () => {};
view.state = {
  observations: [
    { source: "rid", detectorId: "D", sourceTrackId: "A", measurementTime: "2026-04-09T12:00:01Z", latitude: 39.13, longitude: 117.2 },
    { source: "rid", detectorId: "D", sourceTrackId: "B", measurementTime: "2026-04-09T12:00:01Z", latitude: 39.13, longitude: 117.21 },
    { source: "rid", detectorId: "D", sourceTrackId: "A", measurementTime: "2026-04-09T12:00:02Z", latitude: 39.13, longitude: 117.2001 },
  ],
  snapshots: [
    { processingTime: "2026-04-09T12:00:01Z", tracks: [{ fusionId: "F1", latitude: 39.13, longitude: 117.2, positionMode: "measured" }] },
    { processingTime: "2026-04-09T12:00:02Z", tracks: [{ fusionId: "F1", latitude: 39.13, longitude: 117.2001, positionMode: "measured" }] },
  ],
};
view.tIndex = 0;
view.draw();
const ok =
  rawPoints === 2 &&
  polylines.filter((p) => p.color === "#4cc9f0").every((p) => p.n <= 2) &&
  !polylines.some((p) => p.n === 3 && p.color === "#4cc9f0");
console.log(JSON.stringify({
  rendered_at_snapshot: 0,
  visible_raw_points: rawPoints,
  expected_visible_raw_points: 2,
  raw_polylines: polylines.filter((p) => p.color === "#4cc9f0"),
  pass_no_future_and_no_cross_track: ok,
  verification_type: "render-logic stub (not browser E2E)",
}, null, 2));
process.exit(ok ? 0 : 1);
