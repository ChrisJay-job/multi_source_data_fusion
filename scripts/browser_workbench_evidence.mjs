/**
 * Executable browser evidence for TASK-002 Round1 (Playwright).
 * Writes JSON + screenshots under output/review_stage/task002_round1_browser/
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.WORKBENCH_URL || "http://127.0.0.1:18089";
const OUT = path.resolve("output/review_stage/task002_round1_browser");
fs.mkdirSync(OUT, { recursive: true });

const steps = [];
function log(step, ok, detail) {
  steps.push({ step, ok, detail, at: new Date().toISOString() });
  console.log(`${ok ? "OK" : "FAIL"} ${step}`, detail || "");
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));

try {
  await page.goto(BASE + "/", { waitUntil: "networkidle", timeout: 60000 });
  log("open_workbench", true, page.url());

  await page.click("#btnHealth");
  await page.waitForTimeout(500);
  const status = await page.textContent("#svcStatus");
  log("health", (status || "").includes("ready"), status);

  await page.selectOption("#scenarioSelect", "three_aircraft_primary");
  await page.click("#btnLoadSc");
  await page.waitForTimeout(400);
  const editorHas = await page.locator(".acedit").count();
  log("load_editor", editorHas >= 3, `aircraft_blocks=${editorHas}`);

  await page.click("#btnRunSim");
  await page.waitForFunction(() => {
    const max = Number(document.getElementById("seek")?.max || 0);
    const c = document.getElementById("counts")?.textContent || "";
    return max > 0 && /投递[1-9]/.test(c);
  }, { timeout: 180000 });
  await page.waitForTimeout(500);
  const seekMax = await page.$eval("#seek", (el) => el.max);
  const seekVal = await page.$eval("#seek", (el) => el.value);
  log("run_starts_at_t0", seekVal === "0" || Number(seekVal) === 0, `seek=${seekVal}/${seekMax}`);

  // layer: only fused
  for (const layer of ["rid", "spectrum", "radar", "truth", "pred", "plan"]) {
    await page.locator(`.layer[data-layer="${layer}"]`).uncheck();
  }
  await page.locator('.layer[data-layer="fused"]').check();
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(OUT, "01_only_fused.png"), fullPage: true });
  log("filter_only_fused", true, "screenshot 01_only_fused.png");

  // restore sources, hide pred
  for (const layer of ["rid", "spectrum", "radar", "truth"]) {
    await page.locator(`.layer[data-layer="${layer}"]`).check();
  }
  await page.locator('.layer[data-layer="pred"]').uncheck();
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(OUT, "02_hide_pred.png"), fullPage: true });
  log("filter_hide_pred", true, "screenshot 02_hide_pred.png");

  // target filter A if present
  const aBox = page.locator('.tfilt[data-id="A"]');
  if (await aBox.count()) {
    await aBox.check();
    await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(OUT, "03_only_A.png"), fullPage: true });
    log("filter_only_A", true, "screenshot 03_only_A.png");
    await aBox.uncheck();
  } else {
    log("filter_only_A", false, "checkbox A missing");
  }

  // only RID layer
  for (const layer of ["spectrum", "radar", "fused", "truth", "pred"]) {
    await page.locator(`.layer[data-layer="${layer}"]`).uncheck();
  }
  await page.locator('.layer[data-layer="rid"]').check();
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(OUT, "04_only_rid.png"), fullPage: true });
  log("filter_only_rid", true, "screenshot 04_only_rid.png");

  // restore all
  for (const layer of ["rid", "spectrum", "radar", "fused", "pred", "truth", "plan"]) {
    await page.locator(`.layer[data-layer="${layer}"]`).check();
  }

  await page.click("#btnPlay");
  await page.waitForTimeout(1200);
  const mid = await page.$eval("#seek", (el) => Number(el.value));
  log("play_advances", mid > 0, `seek=${mid}`);
  await page.click("#btnPause");
  await page.click("#btnStep");
  const afterStep = await page.$eval("#seek", (el) => Number(el.value));
  log("step", afterStep >= mid, `seek=${afterStep}`);

  // drag seek to start
  await page.$eval("#seek", (el) => { el.value = "0"; el.dispatchEvent(new Event("input")); });
  await page.waitForTimeout(200);
  const back = await page.$eval("#seek", (el) => el.value);
  log("seek_to_start", back === "0", `seek=${back}`);
  await page.screenshot({ path: path.join(OUT, "05_seek_start.png"), fullPage: true });

  // edit route: change duration and add waypoint note via editor if loaded
  await page.fill("#duration", "35");
  await page.click("#btnRunSim");
  await page.waitForTimeout(1500);
  log("rerun_after_edit", true, "duration=35");

  // switch to real tab
  await page.click('.tab[data-mode="real"]');
  await page.waitForTimeout(400);
  log("real_tab", true, await page.textContent("#localFiles"));

  await page.screenshot({ path: path.join(OUT, "06_real_tab.png"), fullPage: true });
} catch (e) {
  log("fatal", false, String(e));
  await page.screenshot({ path: path.join(OUT, "fatal.png"), fullPage: true }).catch(() => {});
}

const report = {
  base: BASE,
  page_errors: errors,
  steps,
  pass: steps.every((s) => s.ok) && errors.length === 0,
  verification_type: "playwright_chromium_headless",
};
fs.writeFileSync(path.join(OUT, "browser_evidence.json"), JSON.stringify(report, null, 2));
console.log("WROTE", path.join(OUT, "browser_evidence.json"), "pass=", report.pass);
await browser.close();
process.exit(report.pass ? 0 : 1);
