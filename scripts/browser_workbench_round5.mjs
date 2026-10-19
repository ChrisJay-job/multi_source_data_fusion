/**
 * Round5 browser: filter→page→formal replay consistency; small SQL local path.
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.WORKBENCH_URL || "http://127.0.0.1:18089";
const OUT = path.resolve("output/review_stage/task002_round5_browser");
const ROOT = path.resolve(".");
fs.mkdirSync(OUT, { recursive: true });
const steps = [];
function assert(step, cond, detail) {
  steps.push({ step, ok: !!cond, detail, at: new Date().toISOString() });
  console.log(`${cond ? "OK" : "FAIL"} ${step}`, detail || "");
  if (!cond) throw new Error(`ASSERT ${step}: ${detail}`);
}
function note(step, detail) {
  steps.push({ step, ok: true, detail, note: true, at: new Date().toISOString() });
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

  await page.click('.tab[data-mode="real"]');
  await page.waitForTimeout(200);

  // Upload 3-row filter sample
  const rowsPath = path.join(ROOT, "samples/workbench/r5_filter_rows.jsonl");
  await page.setInputFiles("#fileInput", rowsPath);
  await page.click("#btnPreview");
  await page.waitForTimeout(500);
  const stored = await page.evaluate(() => {
    try {
      return JSON.parse(document.getElementById("importReport").textContent || "{}").stored_as;
    } catch {
      return null;
    }
  });
  assert("preview_stored", !!stored, String(stored));

  // Filter D2 — page 0 limit 1 → o2; next → o3; formal replay → 2 rows both D2
  await page.fill("#filterDetector", "D2");
  await page.fill("#lonMin", "");
  await page.fill("#maxRows", "10");
  const p0 = await page.evaluate(async () => window.__wb.fetchPage(0, 1));
  assert(
    "page0_detector_D2",
    p0 && p0.n === 1 && p0.observations?.[0]?.observationId === "o2" && p0.has_more === true,
    JSON.stringify({ n: p0?.n, id: p0?.observations?.[0]?.observationId, has_more: p0?.has_more, limit: p0?.limit })
  );
  await page.click("#btnPageNext");
  await page.waitForTimeout(200);
  const p1 = await page.evaluate(() => {
    try {
      return JSON.parse(document.getElementById("importReport").textContent || "{}");
    } catch {
      return null;
    }
  });
  assert(
    "page1_detector_D2",
    p1 && p1.n === 1 && p1.observations?.[0]?.observationId === "o3",
    JSON.stringify(p1)
  );

  await page.click("#btnRunImport");
  await page.waitForFunction(() => (window.__wb.runState?.n_observations || 0) > 0, { timeout: 30000 });
  const formal = await page.evaluate(() => {
    const rs = window.__wb.runState || {};
    const obs = rs.observations || [];
    return {
      n: rs.n_observations || obs.length,
      dets: [...new Set(obs.map((o) => o.detectorId))],
      ids: obs.map((o) => o.observationId),
      filters: rs.import_summary?.filters,
    };
  });
  assert(
    "formal_replay_D2_only",
    formal.n === 2 && formal.dets.length === 1 && formal.dets[0] === "D2" && !formal.ids.includes("o1"),
    JSON.stringify(formal)
  );
  await page.screenshot({ path: path.join(OUT, "01_filter_D2.png") });

  // Region filter lonMin=117.2 → first page o2
  await page.fill("#filterDetector", "");
  await page.fill("#lonMin", "117.2");
  const preg = await page.evaluate(async () => window.__wb.fetchPage(0));
  assert(
    "page_region_lonMin",
    preg && preg.n >= 1 && preg.observations[0].observationId === "o2",
    JSON.stringify(preg)
  );
  await page.click("#btnRunImport");
  await page.waitForTimeout(800);
  const formalR = await page.evaluate(() => {
    const obs = window.__wb.runState?.observations || [];
    return { n: obs.length, ids: obs.map((o) => o.observationId), minLon: Math.min(...obs.map((o) => o.longitude)) };
  });
  assert(
    "formal_replay_region",
    formalR.n === 2 && !formalR.ids.includes("o1") && formalR.minLon >= 117.2,
    JSON.stringify(formalR)
  );

  // Late time window on same file
  await page.fill("#lonMin", "");
  await page.fill("#timeFrom", "2026-04-09T12:00:03+00:00");
  await page.fill("#timeTo", "2026-04-09T12:00:04+00:00");
  await page.fill("#maxRows", "1");
  await page.click("#btnRunImport");
  await page.waitForTimeout(800);
  const late = await page.evaluate(() => {
    const obs = window.__wb.runState?.observations || [];
    return { n: obs.length, id: obs[0]?.observationId };
  });
  assert("formal_late_window", late.n === 1 && late.id === "o3", JSON.stringify(late));

  // Local mini SQL: select → filter D2 → replay
  await page.fill("#timeFrom", "");
  await page.fill("#timeTo", "");
  await page.fill("#filterDetector", "D2");
  await page.fill("#maxRows", "10");
  await page.evaluate(async () => {
    // refresh local list
    const r = await fetch("/v1/workbench/local-data");
    const j = await r.json();
    const hit = (j.files || []).find((f) => String(f.path).includes("r5_mini.sql"));
    if (!hit) throw new Error("r5_mini.sql not listed");
    const btn = document.createElement("button");
    btn.className = "localpick";
    btn.dataset.path = hit.path;
    document.getElementById("localFiles").appendChild(btn);
  });
  // click via evaluate calling same handler path as UI: run/local
  const sqlRun = await page.evaluate(async () => {
    const filters = window.__wb.selectionFilters();
    const r = await fetch("/v1/workbench/run/local", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path: "data/r5_mini.sql",
        mode: "replay",
        mapping: window.__wb.mappingFromForm(),
        maxRows: 10,
        ...filters,
        truncated: true,
      }),
    });
    const j = await r.json();
    if (r.ok) {
      // mirror showRun effects for assertion
      window.__wb.runState = j;
    }
    return { ok: r.ok, n: j.n_observations, dets: (j.observations || []).map((o) => o.detectorId), filters: j.import_summary?.filters, tracks: (j.final_tracks || j.snapshots?.slice(-1)?.[0]?.tracks || []).length };
  });
  assert(
    "local_sql_filter_D2",
    sqlRun.ok && sqlRun.n === 2 && sqlRun.dets.every((d) => d === "D2"),
    JSON.stringify(sqlRun)
  );
  note("local_sql_to_fusion", `n=${sqlRun.n} tracks_final≈${sqlRun.tracks}; full 2GB NOT_TESTED`);
  await page.screenshot({ path: path.join(OUT, "02_sql_mini.png") });

  // Queue still intact path (smoke): clear filters and confirm two-file add still works
  await page.fill("#filterDetector", "");
  await page.click("#btnQueueClear");
  await page.setInputFiles("#fileInput", path.join(ROOT, "samples/workbench/r4_rid.csv"));
  await page.click("#btnQueueAdd");
  await page.waitForTimeout(400);
  await page.setInputFiles("#fileInput", path.join(ROOT, "samples/workbench/r4_radar.csv"));
  await page.click("#btnQueueAdd");
  await page.waitForTimeout(400);
  const qn = await page.evaluate(() => window.__wb.multiQueue.length);
  assert("queue_still_two", qn === 2, String(qn));

  assert("no_page_errors", pageErrors.length === 0, pageErrors.join(";"));
  note("real_multi_source", "BLOCKED");
  note("field_accuracy", "NOT_TESTED");
  note("full_2gb_sql", "NOT_TESTED");
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
  verification_type: "playwright_round5_filter_page_replay",
  real_multi_source: "BLOCKED",
  field_accuracy: "NOT_TESTED",
};
fs.writeFileSync(path.join(OUT, "browser_evidence.json"), JSON.stringify(report, null, 2));
console.log("WROTE", path.join(OUT, "browser_evidence.json"), "pass=", report.pass);
await browser.close();
process.exit(report.pass ? 0 : 1);
