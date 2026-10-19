// Executes submitted JS with DOM/canvas stubs. Logic evidence only, not browser E2E.
// Exit 0 only when all Round3 probes pass.
const fs = require("fs");
const vm = require("vm");
const path = require("path");
const root = process.argv[2] || ".";
const nodes = {};
function node(id) {
  return (
    nodes[id] ||
    (nodes[id] = {
      value: "",
      checked: false,
      textContent: "",
      style: {},
      classList: { toggle() {}, add() {}, remove() {} },
      addEventListener() {},
      querySelectorAll() { return []; },
      click() {},
      get innerHTML() { return this.html || ""; },
      set innerHTML(v) {
        this.html = v;
        if (id === "routeAcSelect") {
          this.value = (v.match(/value="([^"]+)"/) || [])[1] || "";
          this.options = [...v.matchAll(/value="([^"]+)"/g)].map((m) => ({ value: m[1], text: m[1] }));
          this.selectedIndex = 0;
        }
      },
    })
  );
}
const doc = { getElementById: node, querySelectorAll() { return []; } };
const context = { document: doc, console, setTimeout, clearTimeout, alert() {}, prompt() { return null; }, window: {}, FormData: class { append() {} } };
vm.createContext(context);
vm.runInContext(
  fs.readFileSync(path.join(root, "demo/workbench/canvas.js"), "utf8").replaceAll("export ", "") +
    "\nglobalThis.MapView=MapView;\nglobalThis.buildDisplayIndex=buildDisplayIndex;",
  context
);
const ctx = new Proxy({}, { get(t, k) { return t[k] || (t[k] = () => {}); } });
const cv = {
  width: 1100,
  height: 720,
  getContext() { return ctx; },
  addEventListener() {},
  getBoundingClientRect() { return { width: 1100, height: 720 }; },
};
const view = new context.MapView(cv);
view._grid = () => {};
view._poly = () => {};
view._point = () => {};
view.setState(
  {
    scenario: {
      aircraft: [
        { label: "A", truth_id: "TRUTH-A", rid_sn: "SN-A", sources: {} },
        { label: "B", truth_id: "TRUTH-B", rid_sn: "SN-B", sources: {} },
      ],
    },
    snapshots: [{ tracks: [] }],
  },
  { fit: false }
);
view.targetFilter = new Set(["A"]);
const result = { verification_type: "Actual JS with stub DOM/canvas, not browser E2E" };
result.only_A_truth_filter = {
  allows_B_truth: view._allowedByFilter("truth", "TRUTH-B"),
  allows_B_plan: view._allowedByFilter("plan", "TRUTH-B"),
  expected: false,
};
view.startRouteEdit([{ x_m: 0, y_m: 0 }, { x_m: 10, y_m: 0 }], () => {});
const [x, y] = view.worldToScreen(0, 0);
view._onDown({ offsetX: x, offsetY: y });
view._onMove({ offsetX: x + 30, offsetY: y + 20 });
view.drag = null;
view.routeEdit.dragging = null;
view._onClick({ offsetX: x + 30, offsetY: y + 20 });
result.drag_waypoint = { after_drag_point_count: view.routeEdit.points.length, expected: 2 };

class FakeMap {
  constructor() { this.tIndex = 0; }
  startRouteEdit(pts) { this.edited = pts; }
  stopRouteEdit() {}
  setState() {}
  currentTimeMs() { return 0; }
  setTargetFilter() {}
}
context.FakeMap = FakeMap;
let calls = [];
let loaded = {
  field_map: { measurementTime: "ts" },
  source_timezone: "UTC",
  assume_utc_naive: false,
  treat_raw_id_as_aircraftId: true,
};
context.fetch = async (url, opts = {}) => {
  calls.push({ url, body: opts.body });
  return {
    ok: true,
    json: async () =>
      url.includes("/mapping/") && !url.endsWith("/list") && !url.endsWith("/default") && !url.endsWith("/save")
        ? loaded
        : url.includes("/mapping/default")
          ? { mapping: { field_map: {} }, candidates: {} }
          : url.includes("/mapping/list")
            ? { mappings: [] }
            : { snapshots: [], import_summary: {}, stored_as: "data/new.csv", n_observations: 1 },
  };
};
let app = fs
  .readFileSync(path.join(root, "demo/workbench/app.js"), "utf8")
  .replace(/^import.*\n/, "")
  .replace("new MapView(", "new FakeMap(")
  .replace(/loadScenarioList\(\)\.then\([^\n]+\ninitFieldMapForm\(\);\ndocument.getElementById\("btnHealth"\)\.click\(\);/, "");
vm.runInContext(app, context);
vm.runInContext(
  'draftScenario={aircraft:[{label:"A",waypoints:[{x_m:1,y_m:1}]},{label:"B",waypoints:[{x_m:99,y_m:99}]}]};refreshRouteAcSelect();',
  context
);
node("routeAcSelect").value = "1";
node("btnRouteAdd").onclick();
result.select_B_then_draw = {
  edited_first_x: vm.runInContext("map.edited[0].x_m", context),
  expected: 99,
};

(async () => {
  node("maxRows").value="100";
  vm.runInContext('multiQueue=[{path:"data/rid.csv",mapping:{source_timezone:"UTC"}},{path:"data/radar.csv",mapping:{source_timezone:"Asia/Shanghai"}}];',context);
  node("fileInput").files=[{name:"radar.csv"}];
  context.window.__wbNewFilesSelected=false;
  await node("btnRunMulti").onclick();
  const req=calls.find(c=>c.url.endsWith("/run/import/multi"));
  const sent=JSON.parse(req.body).files;
  const queueOK=sent.length===2&&sent[0].path==="data/rid.csv"&&sent[1].path==="data/radar.csv";
  loaded={field_map:{},source_timezone:null,assume_utc_naive:true,treat_raw_id_as_aircraftId:false};
  node("tzMode").value="Asia/Shanghai";node("mapTemplateSelect").value="utc_from_page";
  await node("btnLoadMap").onclick();
  const templateOK=node("tzMode").value==="assume_utc";
  // Late rejection has no time field in actual response contract; cannot be counted at t0.
  vm.runInContext('runState={snapshots:[{processingTime:"2026-04-09T12:00:00Z"}],observations:[{observationId:"future",receivedAt:"2026-04-09T12:00:10Z",measurementTime:"2026-04-09T12:00:10Z"}],events:[],rejected:[{observationId:"future",reason:"bad_latitude"}],counts:{delivered:1,rejected:1}};',context);
  const c=vm.runInContext('countsUpTo(0)',context);
  const countsOK=c.rejected_at_t===0;
  console.log(JSON.stringify({verification_type:"Actual app.js event handlers with DOM/network stubs; not browser E2E",queue_preserves_configured_files:{pass:queueOK,expected_paths:["data/rid.csv","data/radar.csv"],sent},page_saved_utc_template:{pass:templateOK,template:loaded,actual_tz:node("tzMode").value,expected_tz:"assume_utc"},future_rejection_at_start:{pass:countsOK,actual:c.rejected_at_t,expected:0}},null,2));
  process.exit(queueOK&&templateOK&&countsOK?0:1);
})().catch(e=>{console.error(e);process.exit(1)});
