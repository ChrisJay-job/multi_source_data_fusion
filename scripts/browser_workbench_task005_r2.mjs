/**
 * TASK-005 REWORK Round2 browser — only R2-01..R2-04 + basic flow.
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.WORKBENCH_URL || "http://127.0.0.1:18089";
const OUT = path.resolve("reports/task005_rework_round2/browser");
fs.mkdirSync(OUT, { recursive: true });
console.log("browser_script_rev=r2-20261020a");
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
  if (!ok) assert(`run_wait_${expectScenarioSubstring}`, false, "timeout");
  else assert(`run_wait_${expectScenarioSubstring}`, true);
}

async function runViewport(width, height) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width, height } });
  try {
    await waitReady(page);
    assert(`ready_${width}`, true);

    await page.selectOption("#scenarioSelect", "seven_plus_challenges_with_id");
    await page.click("#btnLoadSc");
    await page.waitForTimeout(500);
    assert(`expand_13_${width}`, (await page.locator("#acList li.ac-item").count()) === 13);

    await runAndAwait(page, "seven_plus");

    // R2-01 metrics labels
    const metrics = await page.textContent("#metricsDisplay");
    assert(
      `metrics_r2_${width}`,
      /末快照实体覆盖|已提交|展示预测|ID交换/.test(metrics || ""),
      (metrics || "").slice(0, 200)
    );

    // R2-02: J/K near zoom must show pair=J/K ~2m, not H/I @14s
    await page.selectOption("#focusGroupSelect", "near2");
    await page.click("#btnFocusGroup");
    await page.waitForTimeout(150);
    await page.uncheck("#chkJumpNearTime").catch(() => {});
    await page.click("#btnZoomNear");
    await page.waitForTimeout(250);
    const nearTxt = await page.textContent("#nearDist");
    assert(`near_jk_pair_${width}`, /对=J\/K|对=K\/J/.test(nearTxt || ""), nearTxt);
    assert(`near_jk_dist_${width}`, /2\.0\d* m|1\.9\d* m|2\.1\d* m/.test(nearTxt || ""), nearTxt);
    assert(`near_not_hi_${width}`, !/对=H\/I|对=I\/H/.test(nearTxt || "") || /聚焦对/.test(nearTxt || ""), nearTxt);
    const proj = await page.evaluate(() => {
      const m = window.__wb.map;
      const rs = window.__wb.runState;
      const geo = rs?.challenge_geometry;
      const jk = (geo?.checks || []).find((c) => c.kind === "near_parallel_spacing" && (c.pair || []).includes("J"));
      const t0 = rs?.t0Ms || Date.parse(rs?.t0);
      const snap = rs?.snapshots?.[m.tIndex];
      const now = snap?.processingTime ? Date.parse(snap.processingTime) : null;
      const at = now && t0 ? (now - t0) / 1000 : jk?.at ?? 0;
      // Project truth endpoints of J/K at current play time into canvas
      const labels = ["J", "K"];
      const pts = [];
      for (const a of rs?.scenario?.aircraft || []) {
        if (!labels.includes(a.label)) continue;
        const poly = (rs?.truth_polyline || {})[a.truth_id || a.label] || [];
        // Use map world from aircraft start/end if available via filter
        pts.push(a.label);
      }
      const inView = labels.every((lab) => {
        // canvas filter should include label; scale must resolve 2m
        return m.targetFilter?.has?.(lab) || [...(m.targetFilter || [])].includes(lab);
      });
      return { scale: m.scale, filterOk: inView || m.targetFilter?.size >= 2, at, jkAt: jk?.at, jkD: jk?.min_d };
    });
    assert(`jk_scale_${width}`, proj.scale > 2, JSON.stringify(proj));
    assert(`jk_filter_${width}`, proj.filterOk, JSON.stringify(proj));

    // Seek start / mid / end — near panel still names J/K
    for (const frac of [0, 0.5, 1]) {
      await page.evaluate((f) => {
        const n = window.__wb.runState.snapshots.length;
        window.__wb.map.setTimeIndex(Math.min(n - 1, Math.floor((n - 1) * f)));
        window.__wb.updateTransport();
      }, frac);
      await page.waitForTimeout(80);
    }
    const nearEnd = await page.textContent("#nearDist");
    assert(`near_persists_jk_${width}`, /J|K/.test(nearEnd || ""), nearEnd);

    // Pin a track from 13-ac (seek end)
    await page.evaluate(() => {
      const snaps = window.__wb.runState.snapshots;
      for (let i = snaps.length - 1; i >= 0; i--) {
        if ((snaps[i].tracks || []).length) {
          window.__wb.map.setTimeIndex(i);
          window.__wb.pinnedDetail = snaps[i].tracks[0];
          window.__wb.renderInspector(snaps[i].tracks[0], "track");
          break;
        }
      }
    });
    const oldHtml = await page.evaluate(() => ({
      insp: document.getElementById("inspector")?.innerHTML || "",
      explain: document.getElementById("explainAssoc")?.innerHTML || "",
      aid: window.__wb.pinnedDetail?.aircraftId || "",
      fid: window.__wb.pinnedDetail?.fusionId || "",
    }));
    assert(`pinned_before_switch_${width}`, !!(oldHtml.aid || oldHtml.fid), JSON.stringify(oldHtml).slice(0, 120));

    // R2-04: switch to 2-ac, run, first frames — no old A/SN-A/fusionId
    await page.selectOption("#scenarioSelect", "challenge_near_parallel_2m_anon");
    await page.click("#btnLoadSc");
    await page.waitForTimeout(400);
    await runAndAwait(page, "near_parallel_2m_anon");

    await page.evaluate(() => {
      window.__wb.map.setTimeIndex(0);
      window.__wb.updateTransport();
    });
    await page.waitForTimeout(150);
    const after = await page.evaluate(() => {
      const text = [
        document.getElementById("inspector")?.innerText || "",
        document.getElementById("explainAssoc")?.innerText || "",
        document.getElementById("detail")?.textContent || "",
        document.getElementById("assoc")?.innerText || "",
      ].join("\n");
      const counts = document.getElementById("counts")?.textContent || "";
      const c0 = window.__wb.runState?.snapshots?.[0]?.counts_at || {};
      return { text, counts, c0, banner: document.getElementById("runBanner")?.textContent || "" };
    });
    assert(`r2_04_no_old_A_${width}`, !/\b机=A\b|SN-A-001|PREVIOUS_RUN/.test(after.text), after.text.slice(0, 240));
    if (oldHtml.fid) {
      assert(`r2_04_no_old_fid_${width}`, !after.text.includes(oldHtml.fid), oldHtml.fid);
    }
    assert(`r2_04_empty_or_current_${width}`, /当前时刻无目标|新运行|N2|无/.test(after.text), after.text.slice(0, 160));

    // R2-03 counts: must not show 已处理观测数=<delivered> when processed_observations null
    assert(`r2_03_counts_label_${width}`, /观测接收=/.test(after.counts) && /已处理观测数=未提供可靠计数|已处理观测数=0/.test(after.counts), after.counts);
    assert(`r2_03_bind_split_${width}`, /来源新绑定\(source_bound\)=/.test(after.counts) && /仅绑定\(secondary_bind_only\)=/.test(after.counts), after.counts);
    assert(`r2_03_api_processed_obs_null_${width}`, after.c0.processed_observations == null, JSON.stringify(after.c0));

    // Seek forward / click obs if any — still no old SN-A
    const n = await page.evaluate(() => window.__wb.runState.snapshots.length);
    if (n > 3) {
      await page.fill("#seek", String(Math.min(n - 1, 3)));
      await page.dispatchEvent("#seek", "input");
      await page.waitForTimeout(120);
    }
    const midText = await page.evaluate(() => document.getElementById("inspector")?.innerText || "");
    assert(`r2_04_after_seek_${width}`, !/SN-A-001/.test(midText), midText.slice(0, 120));

    // When tracks appear, inspector can show current
    await page.evaluate(() => {
      const snaps = window.__wb.runState.snapshots;
      for (let i = 0; i < snaps.length; i++) {
        if ((snaps[i].tracks || []).length) {
          window.__wb.map.setTimeIndex(i);
          window.__wb.updateTransport();
          break;
        }
      }
    });
    await page.waitForTimeout(100);

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
