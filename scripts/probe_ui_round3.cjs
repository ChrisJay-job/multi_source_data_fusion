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
  node("tzMode").value = "Asia/Shanghai";
  node("rawIdAsSn").checked = false;
  node("mapTemplateSelect").value = "utc_template";
  await node("btnLoadMap").onclick();
  result.load_mapping_template = {
    actual_tz: node("tzMode").value,
    expected_tz: "UTC",
    actual_raw_sn: node("rawIdAsSn").checked,
    expected_raw_sn: true,
  };
  vm.runInContext('multiQueue=[{path:"data/old.csv"}];', context);
  node("fileInput").files = [{ name: "new.csv" }];
  await node("btnRunMulti").onclick();
  const multi = calls.find((c) => String(c.url).endsWith("/run/import/multi"));
  const body = JSON.parse(multi.body);
  result.new_file_selection_after_previous_run = {
    sent_files: body.files.map((f) => f.path),
    selected: "new.csv",
    expected: "new dataset replaces old queue or explicit editable queue",
  };

  const pass =
    result.only_A_truth_filter.allows_B_truth === false &&
    result.only_A_truth_filter.allows_B_plan === false &&
    result.drag_waypoint.after_drag_point_count === 2 &&
    result.select_B_then_draw.edited_first_x === 99 &&
    result.load_mapping_template.actual_tz === "UTC" &&
    result.load_mapping_template.actual_raw_sn === true &&
    result.new_file_selection_after_previous_run.sent_files.some((p) => String(p).includes("new.csv")) &&
    !result.new_file_selection_after_previous_run.sent_files.includes("data/old.csv");
  result.pass = pass;
  console.log(JSON.stringify(result, null, 2));
  process.exit(pass ? 0 : 1);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
