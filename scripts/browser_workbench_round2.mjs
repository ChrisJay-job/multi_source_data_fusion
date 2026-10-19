/**
 * Round2 browser evidence with hard assertions (Playwright).
 * Exit non-zero on any failed assertion. Screenshots are auxiliary only.
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.WORKBENCH_URL || "http://127.0.0.1:18089";
const OUT = path.resolve("output/review_stage/task002_round2_browser");
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
  assert("open", true, page.url());

  await page.click("#btnHealth");
  await page.waitForTimeout(400);
  assert("health", (await page.textContent("#svcStatus") || "").includes("ready"));

  await page.selectOption("#scenarioSelect", "three_aircraft_primary");
  await page.click("#btnLoadSc");
  await page.waitForTimeout(500);
  assert("editor_loaded", (await page.locator(".acedit").count()) >= 3);

  // Capture run request when disabling C spectrum
  let lastRunBody = null;
  page.on("request", (req) => {
    if (req.url().includes("/v1/workbench/run/scenario") && req.method() === "POST") {
      lastRunBody = req.postDataJSON();
    }
  });

  await page.click("#btnRunSim");
  await page.waitForFunction(() => Number(document.getElementById("seek")?.max || 0) > 10, { timeout: 180000 });
  assert("seek_starts_0", await page.$eval("#seek", (el) => el.value === "0"));

  // Jump to mid frame with fused entities
  const mid = await page.$eval("#seek", (el) => Math.floor(Number(el.max) / 2));
  await page.$eval("#seek", (el, v) => { el.value = String(v); el.dispatchEvent(new Event("input")); }, mid);
  await page.waitForTimeout(200);

  const midState = await page.evaluate(() => {
    const wb = window.__wb;
    const snap = wb.runState.snapshots[wb.map.tIndex];
    return {
      tIndex: wb.map.tIndex,
      nTracks: (snap?.tracks || []).length,
      labels: [...(wb.map.displayIndex?.keys?.() || [])],
      fusionIds: (snap?.tracks || []).map((t) => t.fusionId),
      aircraftIds: (snap?.tracks || []).map((t) => t.aircraftId),
    };
  });
  assert("mid_has_tracks", midState.nTracks >= 1, JSON.stringify(midState));

  // only A: model-level filter
  await page.locator('.tfilt[data-id="A"]').check();
  await page.waitForTimeout(100);
  const onlyA = await page.evaluate(() => {
    const wb = window.__wb;
    const snap = wb.runState.snapshots[wb.map.tIndex];
    const allowed = (snap?.tracks || []).filter((t) => wb.map._allowedByFilter("fusion", t));
    const obs = (wb.runState.observations || []).filter((o) =>
      wb.map._allowedByFilter("obs", o) && wb.map.parseT
        ? true
        : wb.map._allowedByFilter("obs", o)
    );
    const now = wb.map.currentTimeMs();
    const obsVisible = (wb.runState.observations || []).filter((o) => {
      const t = Date.parse(String(o.measurementTime).replace("Z", "+00:00"));
      return t <= now + 1 && wb.map._allowedByFilter("obs", o) && o.source === "rid";
    });
    return {
      allowedFusion: allowed.map((t) => t.aircraftId || t.fusionId),
      forbiddenPresent: allowed.some((t) => (t.aircraftId || "").includes("SN-B") || (t.aircraftId || "").includes("SN-C")),
      obsA: obsVisible.length,
    };
  });
  assert("only_A_fusion", onlyA.allowedFusion.length >= 1 && !onlyA.forbiddenPresent, JSON.stringify(onlyA));
  await page.screenshot({ path: path.join(OUT, "01_only_A_mid.png") });

  // pred on/off history model
  await page.locator('.tfilt[data-id="A"]').uncheck();
  const predProbe = await page.evaluate(() => {
    const wb = window.__wb;
    // find index with predicted mode if any
    let idx = wb.map.tIndex;
    for (let i = 0; i < wb.runState.snapshots.length; i++) {
      if ((wb.runState.snapshots[i].tracks || []).some((t) => t.positionMode === "predicted")) {
        idx = i;
        break;
      }
    }
    wb.map.setTimeIndex(idx);
    const snap = wb.runState.snapshots[idx];
    const hasPred = (snap?.tracks || []).some((t) => t.positionMode === "predicted");
    return { idx, hasPred, modes: (snap?.tracks || []).map((t) => t.positionMode) };
  });
  // toggle pred layer via checkbox and inspect layers flag
  await page.locator('.layer[data-layer="pred"]').uncheck();
  const predOff = await page.evaluate(() => window.__wb.map.layers.pred === false);
  assert("pred_layer_off", predOff, JSON.stringify(predProbe));
  await page.locator('.layer[data-layer="pred"]').check();

  // step advances strictly — set known index then click Step in one flow
  await page.click("#btnPause");
  await page.evaluate(() => {
    const wb = window.__wb;
    wb.map.setTimeIndex(10);
    document.getElementById("seek").value = "10";
  });
  const before = await page.evaluate(() => window.__wb.map.tIndex);
  await page.click("#btnStep");
  await page.waitForTimeout(80);
  const after = await page.evaluate(() => window.__wb.map.tIndex);
  assert("step_advances", before === 10 && after === 11, `before=${before} after=${after}`);

  // pause: clock frozen during wait
  await page.click("#btnPause");
  const p1 = await page.$eval("#seek", (el) => el.value);
  await page.waitForTimeout(600);
  const p2 = await page.$eval("#seek", (el) => el.value);
  assert("pause_holds", p1 === p2, `${p1} vs ${p2}`);

  // route edit + disable C spectrum then rerun — body must reflect
  await page.click("#btnLoadSc");
  await page.waitForTimeout(300);
  // uncheck C spectrum in editor
  const toggled = await page.evaluate(() => {
    const blocks = [...document.querySelectorAll(".acedit")];
    const c = blocks.find((b) => b.querySelector('[data-f="label"]')?.value === "C");
    if (!c) return false;
    const cb = c.querySelector('[data-k="enabled"][data-src="spectrum"]');
    if (cb && cb.checked) cb.click();
    return cb ? !cb.checked : false;
  });
  assert("disable_C_spectrum_ui", toggled);
  lastRunBody = null;
  await page.click("#btnRunSim");
  await page.waitForTimeout(2000);
  assert("run_body_has_scenario", !!(lastRunBody && lastRunBody.scenario), JSON.stringify(lastRunBody && Object.keys(lastRunBody)));
  const cSpec = lastRunBody?.scenario?.aircraft?.find((a) => a.label === "C")?.sources?.spectrum?.enabled;
  assert("run_body_C_spectrum_off", cSpec === false, `enabled=${cSpec}`);

  // real tab + mapping form + local list without meta
  await page.click('.tab[data-mode="real"]');
  await page.waitForTimeout(500);
  const fmap = await page.locator(".fmap").count();
  assert("field_map_form", fmap >= 5, `fmap=${fmap}`);
  const localTxt = await page.textContent("#localFiles");
  assert("local_no_meta", !/\.meta\.json/.test(localTxt || ""), localTxt?.slice(0, 200));

  // mapping default timezone Asia/Shanghai selected
  const tz = await page.$eval("#tzMode", (el) => el.value);
  assert("tz_shanghai_default", tz === "Asia/Shanghai", tz);

  await page.screenshot({ path: path.join(OUT, "02_real_mapping.png") });

  assert("no_page_errors", pageErrors.length === 0, pageErrors.join(";"));
} catch (e) {
  steps.push({ step: "fatal", ok: false, detail: String(e), at: new Date().toISOString() });
  await page.screenshot({ path: path.join(OUT, "fatal.png"), fullPage: true }).catch(() => {});
  console.error(e);
}

const report = {
  base: BASE,
  page_errors: pageErrors,
  steps,
  pass: steps.every((s) => s.ok),
  verification_type: "playwright_chromium_with_assertions",
};
fs.writeFileSync(path.join(OUT, "browser_evidence.json"), JSON.stringify(report, null, 2));
console.log("WROTE", path.join(OUT, "browser_evidence.json"), "pass=", report.pass);
await browser.close();
process.exit(report.pass ? 0 : 1);
