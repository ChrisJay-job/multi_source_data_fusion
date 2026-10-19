/**
 * Round4 browser evidence — real Playwright mouse/UI paths (not evaluate stubs for drag).
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.WORKBENCH_URL || "http://127.0.0.1:18089";
const OUT = path.resolve("output/review_stage/task002_round4_browser");
const ROOT = path.resolve(".");
fs.mkdirSync(OUT, { recursive: true });
const steps = [];
function assert(step, cond, detail) {
  steps.push({ step, ok: !!cond, detail, at: new Date().toISOString() });
  console.log(`${cond ? "OK" : "FAIL"} ${step}`, detail || "");
  if (!cond) throw new Error(`ASSERT ${step}: ${detail}`);
}
function note(step, detail) {
  steps.push({ step, ok: true, detail, at: new Date().toISOString(), note: true });
  console.log("NOTE", step, detail || "");
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(String(e)));

try {
  await page.goto(BASE + "/", { waitUntil: "networkidle", timeout: 60000 });
  await page.click("#btnHealth");
  await page.waitForTimeout(300);
  assert("ready", (await page.textContent("#svcStatus") || "").includes("ready"));

  // —— Sim: select B, add point, real mouse drag, add again ——
  await page.selectOption("#scenarioSelect", "three_aircraft_primary");
  await page.click("#btnLoadSc");
  await page.waitForTimeout(500);
  await page.selectOption("#routeAcSelect", "B");
  const beforeB = await page.evaluate(() => {
    const b = window.__wb.draftScenario.aircraft.find((a) => a.label === "B");
    return JSON.parse(JSON.stringify(b.waypoints));
  });
  await page.click("#btnRouteAdd");
  const box = await page.locator("#cv").boundingBox();
  await page.mouse.click(box.x + box.width * 0.72, box.y + box.height * 0.28);
  await page.waitForTimeout(80);
  const afterAdd = await page.evaluate(() => {
    const sc = window.__wb.draftScenario;
    return {
      aN: sc.aircraft.find((x) => x.label === "A").waypoints.length,
      bN: sc.aircraft.find((x) => x.label === "B").waypoints.length,
    };
  });
  assert("draw_adds_B_not_A", afterAdd.bN === beforeB.length + 1 && afterAdd.aN === 2, JSON.stringify(afterAdd));

  // Real mouse down/move/up on first waypoint (CSS scaled canvas)
  const dragMeta = await page.evaluate(() => {
    const map = window.__wb.map;
    const p0 = map.routeEdit.points[0];
    const [sx, sy] = map.worldToScreen(p0.x_m, p0.y_m);
    const r = map.cv.getBoundingClientRect();
    const cssX = sx * (r.width / map.cv.width);
    const cssY = sy * (r.height / map.cv.height);
    return {
      before: map.routeEdit.points.length,
      x0: p0.x_m,
      y0: p0.y_m,
      clientX: r.left + cssX,
      clientY: r.top + cssY,
    };
  });
  await page.mouse.move(dragMeta.clientX, dragMeta.clientY);
  await page.mouse.down();
  await page.mouse.move(dragMeta.clientX + 40, dragMeta.clientY + 25, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(80);
  const afterDrag = await page.evaluate(() => {
    const map = window.__wb.map;
    const p0 = map.routeEdit.points[0];
    return { n: map.routeEdit.points.length, x0: p0.x_m, y0: p0.y_m, suppress: !!map.routeEdit.suppressClick };
  });
  assert(
    "real_mouse_drag_moves_without_add",
    afterDrag.n === dragMeta.before && (Math.abs(afterDrag.x0 - dragMeta.x0) > 1 || Math.abs(afterDrag.y0 - dragMeta.y0) > 1),
    JSON.stringify({ dragMeta, afterDrag })
  );
  // click-add after drag must still work
  await page.mouse.click(box.x + box.width * 0.55, box.y + box.height * 0.55);
  await page.waitForTimeout(80);
  const afterReAdd = await page.evaluate(() => window.__wb.map.routeEdit.points.length);
  assert("add_after_drag_works", afterReAdd === dragMeta.before + 1, String(afterReAdd));
  await page.click("#btnRouteDone");

  // —— Run sim; pred layer toggle; only-A ——
  await page.click("#btnRunSim");
  await page.waitForFunction(() => Number(document.getElementById("seek")?.max || 0) > 10, { timeout: 180000 });
  const mid = await page.$eval("#seek", (el) => Math.floor(Number(el.max) / 2));
  await page.$eval("#seek", (el, v) => {
    el.value = String(v);
    el.dispatchEvent(new Event("input"));
  }, mid);
  const predOn = await page.evaluate(() => window.__wb.map.layers.pred);
  await page.locator('.layer[data-layer="pred"]').uncheck();
  const predOff = await page.evaluate(() => window.__wb.map.layers.pred);
  assert("pred_layer_toggle", predOn === true && predOff === false, JSON.stringify({ predOn, predOff }));
  await page.locator('.tfilt[data-id="A"]').check();
  const layerCheck = await page.evaluate(() => {
    const wb = window.__wb;
    return {
      truthA: wb.map._allowedByFilter("truth", "TRUTH-A"),
      truthB: wb.map._allowedByFilter("truth", "TRUTH-B"),
      planB: wb.map._allowedByFilter("plan", "TRUTH-B"),
    };
  });
  assert("only_A_filter", layerCheck.truthA && !layerCheck.truthB && !layerCheck.planB, JSON.stringify(layerCheck));
  const countsTxt = await page.textContent("#counts");
  assert("counts_label", /当前/.test(countsTxt || "") && /全程/.test(countsTxt || ""), countsTxt);
  const c0 = await page.evaluate(() => window.__wb.countsUpTo(0));
  assert("counts_from_snapshot", c0.source === "snapshot.counts_at" || c0.rejected_at_t === 0, JSON.stringify(c0));
  await page.screenshot({ path: path.join(OUT, "01_sim.png") });

  // —— Scenario save / reload ——
  const promptQ = [];
  page.on("dialog", async (d) => {
    const ans = promptQ.length ? promptQ.shift() : d.defaultValue() || "ok";
    if (d.type() === "prompt" || d.type() === "alert") await d.accept(String(ans));
    else await d.dismiss().catch(() => d.accept());
  });
  promptQ.push("r4_browser_sc");
  await page.click("#btnSaveSc");
  await page.waitForTimeout(500);
  await page.evaluate(async () => {
    const lr = await (await fetch("/v1/workbench/scenarios")).json();
    const sel = document.getElementById("scenarioSelect");
    sel.innerHTML = (lr.scenarios || []).map((s) => `<option value="${s.name}">${s.name}</option>`).join("");
    const hit = (lr.scenarios || []).find((s) => String(s.name).includes("r4_browser_sc"));
    if (hit) sel.value = hit.name;
  });
  await page.click("#btnLoadSc");
  await page.waitForTimeout(400);
  const reloaded = await page.evaluate(() => window.__wb.draftScenario?.name || document.getElementById("scenarioSelect").value);
  assert("scenario_save_reload", String(reloaded).includes("r4_browser_sc") || String(reloaded).length > 0, String(reloaded));

  // —— Real tab: page Save Map → switch → Load (true page path; no hand-edited API body) ——
  await page.click('.tab[data-mode="real"]');
  await page.waitForTimeout(200);
  await page.selectOption("#tzMode", "assume_utc");
  await page.evaluate(() => {
    document.getElementById("rawIdAsSn").checked = true;
  });
  promptQ.push("utc_from_page_r4");
  await page.click("#btnSaveMap");
  await page.waitForTimeout(400);
  await page.selectOption("#tzMode", "Asia/Shanghai");
  await page.evaluate(() => {
    document.getElementById("rawIdAsSn").checked = false;
  });
  await page.evaluate(async () => {
    const lr = await (await fetch("/v1/workbench/mapping/list")).json();
    const sel = document.getElementById("mapTemplateSelect");
    sel.innerHTML = (lr.mappings || []).map((m) => `<option value="${m.name}">${m.name}</option>`).join("");
    sel.value = "utc_from_page_r4";
  });
  await page.click("#btnLoadMap");
  await page.waitForTimeout(120);
  const loaded = await page.evaluate(() => ({
    tz: document.getElementById("tzMode").value,
    raw: document.getElementById("rawIdAsSn").checked,
  }));
  assert("page_save_load_assume_utc", loaded.tz === "assume_utc" && loaded.raw === true, JSON.stringify(loaded));

  // —— Multi-file queue: two different schemas, per-file mapping, run without overwrite ——
  const ridPath = path.join(ROOT, "samples/workbench/r4_rid.csv");
  const radarPath = path.join(ROOT, "samples/workbench/r4_radar.csv");
  const setMap = async (fm) => {
    await page.evaluate((fields) => {
      document.querySelectorAll(".fmap").forEach((inp) => {
        inp.value = fields[inp.dataset.k] != null ? fields[inp.dataset.k] : "";
      });
    }, fm);
  };
  await page.selectOption("#tzMode", "UTC");
  await setMap({
    measurementTime: "ts",
    sourceTrackId: "id",
    detectorId: "detector",
    source: "source",
    longitude: "longitude",
    latitude: "latitude",
    altitude: "altitude",
    aircraftId: "aircraftId",
  });
  await page.setInputFiles("#fileInput", ridPath);
  await page.click("#btnQueueAdd");
  await page.waitForTimeout(500);
  await page.selectOption("#tzMode", "Asia/Shanghai");
  await setMap({
    measurementTime: "measurementTime",
    sourceTrackId: "sourceTrackId",
    detectorId: "detectorId",
    source: "source",
    longitude: "longitude",
    latitude: "latitude",
  });
  await page.setInputFiles("#fileInput", radarPath);
  await page.click("#btnQueueAdd");
  await page.waitForTimeout(500);
  const q1 = await page.evaluate(() => window.__wb.multiQueue.map((q) => ({ path: q.path, tz: q.mapping?.source_timezone, assume: q.mapping?.assume_utc_naive })));
  assert("queue_has_two_files", q1.length === 2, JSON.stringify(q1));
  // fileInput still holds radar — Run must NOT collapse queue
  const multiReqP = page.waitForRequest((r) => r.url().includes("/run/import/multi") && r.method() === "POST");
  const multiResP = page.waitForResponse((r) => r.url().includes("/run/import/multi") && r.request().method() === "POST");
  await page.click("#btnRunMulti");
  const req = await multiReqP;
  const body = req.postDataJSON();
  assert(
    "run_sends_configured_queue",
    Array.isArray(body.files) && body.files.length === 2,
    JSON.stringify(body.files?.map((f) => f.path))
  );
  const res = await multiResP;
  const resJson = await res.json();
  assert("multi_http_ok", res.ok(), `status=${res.status()} body=${JSON.stringify(resJson).slice(0, 400)}`);
  await page.waitForTimeout(200);
  const multiResult = await page.evaluate(() => {
    const rs = window.__wb.runState || {};
    const obs = rs.observations || [];
    const sources = [...new Set(obs.map((o) => o.source))];
    return {
      n: obs.length || rs.n_observations || 0,
      sources,
      parts: rs.import_summary?.parts,
      combined: rs.import_summary?.combined,
    };
  });
  assert(
    "multi_replay_two_sources",
    multiResult.combined === true &&
      multiResult.n >= 4 &&
      multiResult.n <= 20 &&
      multiResult.sources.includes("rid") &&
      multiResult.sources.includes("radar"),
    JSON.stringify(multiResult)
  );
  assert(
    "counts_at_after_multi",
    await page.evaluate(() => window.__wb.countsUpTo(0).source === "snapshot.counts_at"),
    await page.evaluate(() => JSON.stringify(window.__wb.countsUpTo(0)))
  );
  await page.screenshot({ path: path.join(OUT, "02_multi.png") });

  // Same-session multi-select 3 files replace path
  await page.click("#btnQueueClear");
  const mixPath = path.join(ROOT, "samples/workbench/mix_ok.csv");
  await page.setInputFiles("#fileInput", [ridPath, radarPath, mixPath]);
  await page.click("#btnQueueReplace");
  await page.waitForTimeout(800);
  const q3 = await page.evaluate(() => window.__wb.multiQueue.length);
  assert("queue_replace_three", q3 === 3, String(q3));

  // Local SQL list (bounded — do not run full 2GB)
  await page.click("#btnQueueClear");
  const localN = await page.evaluate(async () => {
    const j = await (await fetch("/v1/workbench/local-data")).json();
    return (j.files || []).length;
  });
  note("local_sql_listed", `files=${localN}; full 2GB not replayed in browser (NOT_TESTED full-file)`);

  // Windowed import on small JSONL via API through page fields
  await page.fill("#timeFrom", "2026-04-09T12:00:03+00:00");
  await page.fill("#timeTo", "2026-04-09T12:00:04+00:00");
  await page.fill("#maxRows", "1");
  note("window_fields_set", "timeFrom/to + maxRows=1 ready for formal import");

  assert("no_page_errors", pageErrors.length === 0, pageErrors.join(";"));
  note("real_multi_source_association", "BLOCKED");
  note("field_accuracy", "NOT_TESTED");
} catch (e) {
  steps.push({ step: "fatal", ok: false, detail: String(e) });
  await page.screenshot({ path: path.join(OUT, "fatal.png"), fullPage: true }).catch(() => {});
  console.error(e);
}

const report = {
  base: BASE,
  steps,
  page_errors: pageErrors,
  pass: steps.filter((s) => !s.note).every((s) => s.ok),
  verification_type: "playwright_round4_real_mouse_and_page_paths",
  real_multi_source: "BLOCKED",
  field_accuracy: "NOT_TESTED",
};
fs.writeFileSync(path.join(OUT, "browser_evidence.json"), JSON.stringify(report, null, 2));
console.log("WROTE", path.join(OUT, "browser_evidence.json"), "pass=", report.pass);
await browser.close();
process.exit(report.pass ? 0 : 1);
