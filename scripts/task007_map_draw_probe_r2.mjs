/**
 * MI-R2-01: intercept MapView.draw geometry (appendix of REWORK-R2).
 *   node scripts/task007_map_draw_probe_r2.mjs [canvas.js] [out.json]
 */
import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";

const file = process.argv[2] || "demo/workbench/canvas.js";
const outPath = process.argv[3] || "reports/task007/map_interaction/r2/draw_probe_result.json";
fs.mkdirSync(path.dirname(path.resolve(outPath)), { recursive: true });

const code = fs.readFileSync(file, "utf8").replaceAll("export ", "");
const box = {
  window: { addEventListener() {} },
  document: { getElementById() { return null; } },
  requestAnimationFrame: () => 1,
  Math, Date, Number, String, Array, Map, Set, Object, JSON, Infinity, NaN, console,
  isFinite: Number.isFinite.bind(Number),
};
vm.createContext(box);
vm.runInContext(code + ";\nglobalThis.MapView=MapView;", box);

const cv = {
  width: 1200, height: 800,
  getContext: () => ({ clearRect() {} }),
  getBoundingClientRect: () => ({ left: 0, top: 0, width: 1200, height: 800 }),
  addEventListener() {},
  setPointerCapture() {}, releasePointerCapture() {},
};
const at = (i) => new Date(Date.UTC(2026, 9, 24, 0, 0, i)).toISOString();
const tr = (hist, i) => ({
  fusionId: "fusion-H", trackSegmentId: "seg-1",
  latitude: 39.13, longitude: 117.20 + i / 100000, stateTime: at(i),
  committedHistory: hist,
});

const cases = [];
for (const [n, ends] of [[81, [79, 80]], [400, [79, 159, 239, 319, 399]]]) {
  const m = new box.MapView(cv);
  m.layers = { rid: false, spectrum: false, radar: false, current: false, pred: false, fused: true, truth: false, plan: false };
  m._grid = () => {};
  const history = Array.from({ length: n }, (_, i) => ({
    pointId: "point-" + i, fusionId: "fusion-H", trackSegmentId: "seg-1",
    stateTime: at(i), east_m: i, north_m: 0,
  }));
  m.state = {
    observations: [],
    snapshots: ends.map((i) => ({
      processingTime: at(i),
      tracks: [tr(history.slice(Math.max(0, i - 79), i + 1), i)],
    })),
  };
  m.tIndex = ends.length - 1;
  const rendered = [];
  m._poly = (pts) => { rendered.push(...pts); };
  m._point = (x, y) => { rendered.push([x, y]); };
  m.draw();
  const got = m.collectFusionTrackPoints("fusion-H");
  const renderedDistinct = [...new Set(rendered.map((p) => p.join(",")))];
  const r = {
    expectedCommittedPoints: n,
    collectorCommittedPoints: got.pts.filter((p) => p.pointId).length,
    renderedDistinctPoints: renderedDistinct.length,
    firstPointCollected: got.pts.some((p) => p.pointId === "point-0"),
    firstPointRendered: renderedDistinct.includes("0,0"),
  };
  r.pass = r.firstPointCollected && r.firstPointRendered && r.renderedDistinctPoints === n;
  cases.push(r);
}

const result = { module: file, cases, pass: cases.every((c) => c.pass) };
fs.writeFileSync(outPath, JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
process.exitCode = result.pass ? 0 : 1;
if (result.pass) console.log("DRAW_PROBE_R2_OK");
