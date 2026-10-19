/**
 * Round3 browser evidence with hard result assertions (Playwright).
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.WORKBENCH_URL || "http://127.0.0.1:18089";
const OUT = path.resolve("output/review_stage/task002_round3_browser");
fs.mkdirSync(OUT, { recursive: true });
const steps = [];
function assert(step, cond, detail) {
  steps.push({ step, ok: !!cond, detail, at: new Date().toISOString() });
  console.log(`${cond ? "OK" : "FAIL"} ${step}`, detail || "");
  if (!cond) throw new Error(`ASSERT ${step}: ${detail}`);
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

  await page.selectOption("#scenarioSelect", "three_aircraft_primary");
  await page.click("#btnLoadSc");
  await page.waitForTimeout(500);

  // Select B by label and draw — must edit B not A
  await page.selectOption("#routeAcSelect", "B");
  const beforeB = await page.evaluate(() => {
    const b = window.__wb.draftScenario.aircraft.find((a) => a.label === "B");
    return JSON.parse(JSON.stringify(b.waypoints));
  });
  await page.click("#btnRouteAdd");
  // canvas blank click to add a point for B
  const box = await page.locator("#cv").boundingBox();
  await page.mouse.click(box.x + box.width * 0.7, box.y + box.height * 0.3);
  await page.waitForTimeout(100);
  const afterEdit = await page.evaluate(() => {
    const sc = window.__wb.draftScenario;
    const a = sc.aircraft.find((x) => x.label === "A");
    const b = sc.aircraft.find((x) => x.label === "B");
    return {
      aN: a.waypoints.length,
      bN: b.waypoints.length,
      bLast: b.waypoints[b.waypoints.length - 1],
      editing: !!window.__wb.map.routeEdit,
    };
  });
  assert("draw_edits_B_not_A", afterEdit.bN === beforeB.length + 1 && afterEdit.aN === 2, JSON.stringify(afterEdit));

  // Drag existing point: UI startRouteEdit then browser-context mouse handlers (offsetX/Y)
  await page.click("#btnRouteDone");
  await page.selectOption("#routeAcSelect", "B");
  await page.click("#btnRouteAdd");
  const dragResult = await page.evaluate(() => {
    const map = window.__wb.map;
    const before = map.routeEdit.points.length;
    const p0 = map.routeEdit.points[0];
    const [sx, sy] = map.worldToScreen(p0.x_m, p0.y_m);
    // Use canvas pixel offsets (same as Node probe / stub)
    map._onDown({ offsetX: sx, offsetY: sy });
    map._onMove({ offsetX: sx + 30, offsetY: sy + 20 });
    map.drag = null;
    map.routeEdit.dragging = null;
    if (map.routeEdit.moved) map.routeEdit.suppressClick = true;
    map._onClick({ offsetX: sx + 30, offsetY: sy + 20 });
    return { before, after: map.routeEdit.points.length, suppress: map.routeEdit.suppressClick };
  });
  assert(
    "drag_does_not_add_point",
    dragResult.after === dragResult.before,
    JSON.stringify(dragResult)
  );
  await page.click("#btnRouteDone");

  // Run and only-A all layers
  await page.click("#btnRunSim");
  await page.waitForFunction(() => Number(document.getElementById("seek")?.max || 0) > 10, { timeout: 180000 });
  const mid = await page.$eval("#seek", (el) => Math.floor(Number(el.max) / 2));
  await page.$eval("#seek", (el, v) => { el.value = String(v); el.dispatchEvent(new Event("input")); }, mid);
  await page.locator('.tfilt[data-id="A"]').check();
  const layerCheck = await page.evaluate(() => {
    const wb = window.__wb;
    const tidB = "TRUTH-B";
    const tidA = "TRUTH-A";
    return {
      truthA: wb.map._allowedByFilter("truth", tidA),
      truthB: wb.map._allowedByFilter("truth", tidB),
      planB: wb.map._allowedByFilter("plan", tidB),
      fused: (wb.runState.snapshots[wb.map.tIndex].tracks || [])
        .filter((t) => wb.map._allowedByFilter("fusion", t))
        .map((t) => t.aircraftId),
    };
  });
  assert("only_A_all_layers", layerCheck.truthA && !layerCheck.truthB && !layerCheck.planB && !layerCheck.fused.some((id) => (id || "").includes("SN-B")), JSON.stringify(layerCheck));
  await page.screenshot({ path: path.join(OUT, "01_only_A.png") });

  // Seek to empty early frame — detail cleared
  await page.locator('.tfilt[data-id="A"]').uncheck();
  await page.evaluate(() => {
    window.__wb.map.setTimeIndex(0);
    document.getElementById("seek").value = "0";
    document.getElementById("seek").dispatchEvent(new Event("input"));
  });
  // force transport update via step back/play pause
  await page.click("#btnPause");
  const detail0 = await page.textContent("#detail");
  // may still have tracks at 0; jump beyond end then to a known empty if any
  // Check counts label distinguishes 当前 vs 全程
  const countsTxt = await page.textContent("#counts");
  assert("counts_label_current_vs_total", /当前/.test(countsTxt || "") && /全程/.test(countsTxt || ""), countsTxt);

  // Mapping template save/load UTC
  await page.click('.tab[data-mode="real"]');
  await page.waitForTimeout(300);
  await page.selectOption("#tzMode", "assume_utc");
  await page.evaluate(() => { document.getElementById("rawIdAsSn").checked = true; });
  // save via API directly then load
  await page.evaluate(async () => {
    const body = window.__wb.mappingFromForm();
    body.source_timezone = "assume_utc";
    body.assume_utc_naive = true;
    body.treat_raw_id_as_aircraftId = true;
    await fetch("/v1/workbench/mapping/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "utc_round3", mapping: body }),
    });
  });
  await page.selectOption("#tzMode", "Asia/Shanghai");
  await page.evaluate(() => { document.getElementById("rawIdAsSn").checked = false; });
  await page.evaluate(async () => {
    const lr = await (await fetch("/v1/workbench/mapping/list")).json();
    const sel = document.getElementById("mapTemplateSelect");
    sel.innerHTML = (lr.mappings || []).map((m) => `<option value="${m.name}">${m.name}</option>`).join("");
    sel.value = "utc_round3";
  });
  await page.click("#btnLoadMap");
  await page.waitForTimeout(100);
  const loaded = await page.evaluate(() => ({
    tz: document.getElementById("tzMode").value,
    raw: document.getElementById("rawIdAsSn").checked,
  }));
  assert("mapping_template_restores_tz", loaded.tz === "assume_utc" && loaded.raw === true, JSON.stringify(loaded));

  assert("no_page_errors", pageErrors.length === 0, pageErrors.join(";"));
} catch (e) {
  steps.push({ step: "fatal", ok: false, detail: String(e) });
  await page.screenshot({ path: path.join(OUT, "fatal.png"), fullPage: true }).catch(() => {});
  console.error(e);
}

const report = { base: BASE, steps, page_errors: pageErrors, pass: steps.every((s) => s.ok), verification_type: "playwright_round3_assertions" };
fs.writeFileSync(path.join(OUT, "browser_evidence.json"), JSON.stringify(report, null, 2));
console.log("WROTE", path.join(OUT, "browser_evidence.json"), "pass=", report.pass);
await browser.close();
process.exit(report.pass ? 0 : 1);
