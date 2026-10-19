// Actual submitted JavaScript with DOM/canvas stubs. Not browser E2E.
// Exit non-zero on behaviour failures (Round1).
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const root = process.argv[2];
const runFile = process.argv[3];
if (!root || !runFile) {
  console.error("usage: node probe_task003_ui.cjs <projectRoot> <seven_run.json>");
  process.exit(2);
}

const nodes = {};
function el(id) {
  return (
    nodes[id] ||
    (nodes[id] = {
      value: "",
      textContent: "",
      innerHTML: "",
      style: {},
      dataset: {},
      checked: false,
      classList: { add() {}, remove() {}, toggle() {} },
      addEventListener() {},
      querySelectorAll() {
        return [];
      },
      querySelector() {
        return null;
      },
      click() {},
    })
  );
}
const doc = {
  getElementById: el,
  querySelectorAll() {
    return [];
  },
  querySelector() {
    return null;
  },
  addEventListener() {},
};
const c = { document: doc, console, setTimeout, clearTimeout, window: {}, alert() {} };
vm.createContext(c);
vm.runInContext(
  fs.readFileSync(path.join(root, "demo/workbench/canvas.js"), "utf8").replaceAll("export ", "") +
    ";globalThis.MapView=MapView;",
  c
);
const ctx = new Proxy(
  {},
  {
    get(t, k) {
      return t[k] || (t[k] = () => {});
    },
  }
);
const v = new c.MapView({ width: 1100, height: 720, getContext() { return ctx; }, addEventListener() {} });
v._grid = () => {};
let lines = [];
let pts = [];
v._poly = (p, col, dash) => lines.push({ n: p.length, color: col, dash: !!dash });
v._point = (x, y, color) => pts.push({ color });
v.state = JSON.parse(fs.readFileSync(runFile, "utf8"));
// Mid/late frame with enough commits — not empty first frame
v.tIndex = Math.max(0, Math.floor((v.state.snapshots || []).length * 0.85));
v.layers = {
  rid: false,
  spectrum: false,
  radar: false,
  fused: true,
  pred: false,
  current: false,
  truth: false,
  plan: false,
};
lines = [];
pts = [];
v.draw();
const histLines = lines.filter((x) => x.color === "#f72585" && x.n >= 2 && !x.dash);
const pinkPts = pts.filter((x) => x.color === "#f72585");
const result = {
  verification_type: "actual JS with stubs, not browser E2E",
  fused_only: {
    tIndex: v.tIndex,
    history_lines: histLines,
    history_line_count: histLines.length,
    history_and_current_points: pinkPts.length,
    snapshots: (v.state.snapshots || []).length,
  },
};

class DummyMap {
  setLayers() {}
  constructor() {
    this.tIndex = 0;
    this.displayIndex = new Map();
  }
}
c.DummyMap = DummyMap;
let js = fs
  .readFileSync(path.join(root, "demo/workbench/app.js"), "utf8")
  .replace(/^import.*\n/, "")
  .replace("new MapView(", "new DummyMap(")
  .split("// Boot: list presets")[0];
vm.runInContext(js, c);
vm.runInContext(
  `runState={scenario:{aircraft:[]},snapshots:[{processingTime:'2026-04-09T12:00:02Z',tracks:[]}],events:[],evaluation:{entity_check:{status:'FAIL',ok:false},false_merges:[{fusionId:'F-A',truth_ids:['TRUTH-A','TRUTH-C'],at:'2026-04-09T12:00:01Z'}]}};renderResultPanels();`,
  c
);
result.result_panel = {
  html: el("resultSummary").innerHTML,
  shows_FAIL: el("resultSummary").innerHTML.includes("FAIL"),
  anomaly_html: el("anomalyList").innerHTML,
  anomaly_has_merge: /误关联|TRUTH-A|TRUTH-C|false_merge/i.test(el("anomalyList").innerHTML),
};
const active = vm.runInContext(
  `activeSourcesOnTrack({sources:[],sourceTracks:[{source:'radar',bindingStatus:'confirmed',lastSeen:'2026-04-09T11:00:00Z'}]}, '2026-04-09T12:00:02Z')`,
  c
);
result.expired_sources = { algorithm_active: [], page_active: active };

const fails = [];
if (histLines.length < 1) fails.push(`fused_history_lines=${histLines.length} (need >=1 solid commit polyline)`);
if (!result.result_panel.shows_FAIL) fails.push("result panel missing FAIL verdict");
if (!result.result_panel.anomaly_has_merge) fails.push("anomaly list missing false_merge text");
if ((active || []).includes("radar")) fails.push(`stale radar still active: ${JSON.stringify(active)}`);

console.log(JSON.stringify(result, null, 2));
if (fails.length) {
  console.error("PROBE_FAIL", fails);
  process.exit(1);
}
console.error("PROBE_PASS");
process.exit(0);
