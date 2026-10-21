/**
 * TASK-005 REWORK Round1 browser assertions — product handlers, matching run await, export/reimport.
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.WORKBENCH_URL || "http://127.0.0.1:18089";
const OUT = path.resolve("reports/task005_rework_round1/browser");
fs.mkdirSync(OUT, { recursive: true });
console.log("browser_script_rev=r1-20261020c");
const steps = [];
function assert(step, cond, detail) {
  const d = detail == null ? "" : String(detail);
  steps.push({ step, ok: !!cond, detail: d || null, at: new Date().toISOString() });
  console.log(`${cond ? "OK" : "FAIL"} ${step}${d ? " " + d : ""}`);
  if (!cond) throw new Error(`ASSERT ${step}: ${d || "(no detail)"}`);
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
    id: window.__wb?.runState?.runId || window.__wb?.runState?.sessionId || null,
    n: window.__wb?.runState?.snapshots?.length || 0,
    sc: window.__wb?.runState?.scenario?.name || "",
  }));
  await page.click("#btnRunSim");
  // Poll product UI only — do not read huge /run/scenario response bodies (inspector eviction).
  const t0 = Date.now();
  let ok = false;
  while (Date.now() - t0 < 180000) {
    const cur = await page.evaluate(() => {
      const rs = window.__wb?.runState;
      const banner = document.getElementById("runBanner")?.textContent || "";
      return {
        id: rs?.runId || rs?.sessionId || null,
        n: rs?.snapshots?.length || 0,
        sc: rs?.scenario?.name || rs?.runScenarioName || "",
        banner,
      };
    });
    const fresh =
      cur.sc.includes(expectScenarioSubstring) &&
      cur.n > 1 &&
      /当前运行结果/.test(cur.banner) &&
      (cur.id !== before.id || cur.sc !== before.sc || cur.n !== before.n);
    if (fresh) {
      ok = true;
      break;
    }
    await page.waitForTimeout(400);
  }
  if (!ok) assert(`run_wait_${expectScenarioSubstring}`, false, "timeout waiting matching run in UI");
  else assert(`run_wait_${expectScenarioSubstring}`, true);
  const j = await page.evaluate(() => {
    const rs = window.__wb.runState;
    return {
      scenario: rs.scenario,
      snapshots: { length: (rs.snapshots || []).length },
      evaluation: rs.evaluation,
      runId: rs.runId || rs.sessionId,
      challenge_geometry: rs.challenge_geometry,
    };
  });
  assert(`run_resp_${expectScenarioSubstring}`, (j.scenario?.name || "").includes(expectScenarioSubstring), j.scenario?.name);
  return j;
}

async function runViewport(width, height) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width, height } });
  try {
    await waitReady(page);
    assert(`ready_${width}`, true);

    await page.waitForSelector("#acList li.ac-item", { timeout: 20000 });
    assert(`default_seven_${width}`, (await page.locator("#acList li.ac-item").count()) === 7);

    await page.selectOption("#scenarioSelect", "seven_plus_challenges_with_id");
    await page.click("#btnLoadSc");
    await page.waitForTimeout(500);
    assert(`expand_13_${width}`, (await page.locator("#acList li.ac-item").count()) === 13);

    const j13 = await runAndAwait(page, "seven_plus");
    assert(`run_13_${width}`, (j13.snapshots?.length || 0) > 2);
    const trackDiag = await page.evaluate(() => {
      const rs = window.__wb?.runState;
      const snaps = rs?.snapshots || [];
      return {
        n: snaps.length,
        t0: (snaps[0]?.tracks || []).length,
        tMid: (snaps[Math.floor(snaps.length / 2)]?.tracks || []).length,
        tLast: (snaps[snaps.length - 1]?.tracks || []).length,
        final: (rs?.final_tracks || []).length,
        keys0: snaps[0] ? Object.keys(snaps[0]).slice(0, 12) : [],
      };
    });
    console.log("trackDiag", JSON.stringify(trackDiag));
    assert(`has_tracks_${width}`, trackDiag.tLast > 0 || trackDiag.final > 0, JSON.stringify(trackDiag));

    await page.selectOption("#focusGroupSelect", "near2");
    await page.click("#btnFocusGroup");
    await page.waitForTimeout(200);
    await page.click("#btnZoomNear");
    await page.waitForTimeout(200);
    const nearTxt = await page.textContent("#nearDist");
    assert(`near_dist_${width}`, /真值最近距/.test(nearTxt || "") && /m/.test(nearTxt || ""));
    // Pixel spacing of 2m pair should be resolvable (scale large enough)
    const pxPerM = await page.evaluate(() => window.__wb.map.scale);
    assert(`zoom_scale_${width}`, pxPerM > 2, `scale=${pxPerM}`);

    await page.click("#viewSimple");
    let layers = await page.evaluate(() => window.__wb.map.layers);
    assert(`view_simple_hides_obs_${width}`, layers.rid === false && layers.fused === true);
    await page.click("#viewObs");
    layers = await page.evaluate(() => window.__wb.map.layers);
    assert(`view_obs_shows_rid_${width}`, layers.rid === true);

    const adv = page.locator("#advLayers");
    if (!(await adv.evaluate((el) => el.open))) await page.locator("#advLayers > summary").click();
    await page.locator('.layer[data-layer="radar"]').waitFor({ state: "visible", timeout: 5000 });
    await page.locator('.layer[data-layer="radar"]').uncheck();
    layers = await page.evaluate(() => window.__wb.map.layers);
    assert(`radar_layer_off_${width}`, layers.radar === false);

    // Seek near end so tracks exist, then product renderInspector
    await page.evaluate(() => {
      const n = window.__wb?.runState?.snapshots?.length || 0;
      if (n > 1) window.__wb.map.setTimeIndex(n - 1);
    });
    await page.waitForTimeout(100);
    const row = page.locator("#acResultBody tr[data-i]").first();
    if (await row.count()) await row.click();
    const explainProbe = await page.evaluate(() => {
      try {
        const rs = window.__wb?.runState;
        const snaps = rs?.snapshots || [];
        const counts = snaps.map((s) => (s.tracks || []).length);
        let idx = window.__wb.map.tIndex;
        let tracks = snaps[idx]?.tracks || [];
        if (!tracks.length) {
          for (let i = snaps.length - 1; i >= 0; i--) {
            if ((snaps[i].tracks || []).length) {
              tracks = snaps[i].tracks;
              idx = i;
              window.__wb.map.setTimeIndex(i);
              break;
            }
          }
        }
        const tr = tracks[0] || (rs?.final_tracks || [])[0];
        if (!tr) {
          return {
            ok: false,
            html: document.getElementById("explainAssoc")?.innerHTML || "",
            err: "no_track",
            nSnap: snaps.length,
            counts: counts.slice(-5),
            hasFinal: !!(rs?.final_tracks || []).length,
            sc: rs?.scenario?.name,
          };
        }
        window.__wb.renderInspector(tr, "track");
        return {
          ok: true,
          html: document.getElementById("explainAssoc")?.innerText || document.getElementById("explainAssoc")?.innerHTML || "",
          n: tracks.length,
          idx,
        };
      } catch (e) {
        return { ok: false, html: "", err: String(e) };
      }
    });
    assert(
      `explain_panel_${width}`,
      explainProbe.ok && /当前时刻解释|整次评估|候选距离|当前未输出/.test(explainProbe.html || ""),
      JSON.stringify(explainProbe).slice(0, 300)
    );

    // Seek then ensure no future-only pollution marker requirement: panel still current
    await page.fill("#seek", "2");
    await page.dispatchEvent("#seek", "input");
    await page.waitForTimeout(150);
    const explain2 = await page.textContent("#explainAssoc");
    assert(`explain_after_seek_${width}`, /当前时刻解释|整次评估/.test(explain2 || ""));

    // Switch to 2-aircraft challenge — must await NEW matching response
    await page.selectOption("#scenarioSelect", "challenge_near_parallel_2m_anon");
    await page.click("#btnLoadSc");
    await page.waitForTimeout(400);
    assert(`challenge_switch_${width}`, (await page.locator("#acList li.ac-item").count()) === 2);

    const j2 = await runAndAwait(page, "near_parallel_2m_anon");
    assert(`run_2ac_matched_${width}`, (j2.scenario?.aircraft || []).length === 2);
    // Must not show old A–G table
    const labels = await page.locator("#acResultBody tr[data-i] td:first-child").allTextContents();
    assert(`no_old_seven_rows_${width}`, labels.every((t) => !["A", "B", "C", "D", "E", "F", "G"].includes(t.trim())), labels.join(","));
    const verd = j2.evaluation?.entity_check?.status;
    const summary = await page.textContent("#resultSummary");
    const banner = await page.textContent("#runBanner");
    assert(`banner_matches_${width}`, /near_parallel_2m_anon/.test(banner || ""));
    if (verd === "FAIL") {
      assert(`no_greenwash_${width}`, /FAIL/.test(summary || "") || /FAIL/.test(await page.textContent("#metricsDisplay") || ""));
      assert(`fail_tied_to_run_${width}`, /FAIL/.test(await page.textContent("#metricsDisplay") || ""));
    } else {
      assert(`eval_status_recorded_${width}`, typeof verd === "string");
    }

    // Export download required + reimport + compare
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 20000 }),
      page.click("#btnExportSc"),
    ]);
    assert(`export_download_${width}`, !!download);
    const tmp = path.join(OUT, `exported_${width}.json`);
    await download.saveAs(tmp);
    const exported = JSON.parse(fs.readFileSync(tmp, "utf8"));
    assert(`export_has_identity_${width}`, exported.aircraft?.length === 2);
    assert(`export_emit_flags_${width}`, exported.aircraft.every((a) => a.sources?.rid || a.sources?.radar));

    await page.setInputFiles("#scFile", tmp);
    await page.waitForTimeout(400);
    assert(`reimport_name_${width}`, ((await page.evaluate(() => window.__wb.draftScenario?.name)) || "").includes("near_parallel"));

    // Re-run after reimport
    const j3 = await runAndAwait(page, "near_parallel");
    assert(`reimport_run_${width}`, (j3.scenario?.aircraft || []).length === 2);

    // Metrics panel uses metrics_display
    const metrics = await page.textContent("#metricsDisplay");
    assert(`metrics_ui_${width}`, /目标数|误合并|覆盖率|RMSE/.test(metrics || ""));

    await page.screenshot({ path: path.join(OUT, `viewport_${width}.png`), fullPage: true });
  } finally {
    await browser.close();
  }
}

async function main() {
  for (const [w, h] of [
    [1366, 768],
    [1920, 1080],
  ]) {
    await runViewport(w, h);
  }
  const hardFail = steps.filter((s) => !s.ok).length;
  fs.writeFileSync(path.join(OUT, "browser_evidence.json"), JSON.stringify({ pass: hardFail === 0, hardFail, steps }, null, 2));
  console.log("hardFail", hardFail);
  if (hardFail) process.exit(1);
}

main().catch((e) => {
  fs.writeFileSync(path.join(OUT, "browser_evidence.json"), JSON.stringify({ pass: false, error: String(e), steps }, null, 2));
  console.error(e);
  process.exit(1);
});
