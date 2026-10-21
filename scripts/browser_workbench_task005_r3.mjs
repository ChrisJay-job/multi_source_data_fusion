/**
 * TASK-005 REWORK Round3 — only ID-exchange null vs measured display.
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.WORKBENCH_URL || "http://127.0.0.1:18089";
const OUT = path.resolve("reports/task005_rework_round3/browser");
fs.mkdirSync(OUT, { recursive: true });
const steps = [];
function assert(step, cond, detail) {
  const d = detail == null ? "" : String(detail);
  steps.push({ step, ok: !!cond, detail: d || null, at: new Date().toISOString() });
  console.log(`${cond ? "OK" : "FAIL"} ${step}${d ? " " + d : ""}`);
  if (!cond) throw new Error(`ASSERT ${step}: ${d || ""}`);
}

async function waitReady(page) {
  const t0 = Date.now();
  while (Date.now() - t0 < 90000) {
    try {
      await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 15000 });
      await page.click("#btnHealth");
      await page.waitForTimeout(400);
      if (((await page.textContent("#svcStatus")) || "").includes("ready")) return;
    } catch (_) {}
    await page.waitForTimeout(800);
  }
  throw new Error("workbench not ready");
}

async function runAndAwait(page, expectScenarioSubstring) {
  const before = await page.evaluate(() => ({
    id: window.__wb?.runState?.runId || null,
    n: window.__wb?.runState?.snapshots?.length || 0,
  }));
  await page.click("#btnRunSim");
  const t0 = Date.now();
  while (Date.now() - t0 < 180000) {
    const cur = await page.evaluate(() => {
      const rs = window.__wb?.runState;
      const banner = document.getElementById("runBanner")?.textContent || "";
      return {
        id: rs?.runId || rs?.sessionId || null,
        n: rs?.snapshots?.length || 0,
        sc: rs?.scenario?.name || "",
        banner,
        md: rs?.evaluation?.metrics_display || null,
      };
    });
    if (
      cur.sc.includes(expectScenarioSubstring) &&
      cur.n > 1 &&
      /当前运行结果/.test(cur.banner) &&
      (cur.id !== before.id || cur.n !== before.n)
    ) {
      return cur;
    }
    await page.waitForTimeout(400);
  }
  assert(`run_${expectScenarioSubstring}`, false, "timeout");
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1366, height: 768 } });
  try {
    await waitReady(page);
    // Anonymous 2m: expect ID交换=不可计算 (or null in metrics_display)
    await page.selectOption("#scenarioSelect", "challenge_near_parallel_2m_anon");
    await page.click("#btnLoadSc");
    await page.waitForTimeout(400);
    const anon = await runAndAwait(page, "near_parallel_2m_anon");
    const anonTxt = await page.textContent("#metricsDisplay");
    const anonMd = anon.md || {};
    assert(
      "anon_id_exchange_null_api",
      anonMd.id_exchange_count == null,
      JSON.stringify({ c: anonMd.id_exchange_count, note: anonMd.id_exchange_note })
    );
    assert("anon_ui_not_zero", /ID交换=不可计算/.test(anonTxt || "") && !/ID交换=0/.test(anonTxt || ""), anonTxt?.slice(0, 200));

    // With-id seven: if computable, may show measured number (0 is ok when frames_mapped>=2)
    await page.selectOption("#scenarioSelect", "seven_aircraft_combinations");
    await page.click("#btnLoadSc");
    await page.waitForTimeout(400);
    const seven = await runAndAwait(page, "seven_aircraft");
    const sevenTxt = await page.textContent("#metricsDisplay");
    const sevenMd = seven.md || {};
    if (sevenMd.id_exchange_computable === true || (sevenMd.id_exchange_frames_mapped || 0) >= 2) {
      assert("id_mode_shows_number", sevenMd.id_exchange_count != null && /ID交换=\d+/.test(sevenTxt || ""), sevenTxt?.slice(0, 200));
    } else {
      assert("id_mode_null_ok", sevenMd.id_exchange_count == null && /ID交换=不可计算/.test(sevenTxt || ""), sevenTxt?.slice(0, 200));
    }

    await page.screenshot({ path: path.join(OUT, "viewport_1366.png"), fullPage: true });
  } finally {
    await browser.close();
  }
  const hardFail = steps.filter((s) => !s.ok).length;
  fs.writeFileSync(path.join(OUT, "browser_evidence.json"), JSON.stringify({ pass: hardFail === 0, hardFail, steps }, null, 2));
  console.log("hardFail", hardFail);
  if (hardFail) process.exit(1);
}

main().catch((e) => {
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(path.join(OUT, "browser_evidence.json"), JSON.stringify({ pass: false, error: String(e), steps }, null, 2));
  console.error(e);
  process.exit(1);
});
