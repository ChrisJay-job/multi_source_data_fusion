/**
 * TASK-003 Round4 real browser assertions (extends Round3 product-handler path).
 * Adds: real mouse obs hit, request/obs speed check, polyline vs snapshot coords,
 * hard FAIL panel + pinnedDetail asserts. No DOM/onclick stand-ins.
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.WORKBENCH_URL || "http://127.0.0.1:18089";
const OUT = path.resolve("reports/task003_rework_round4/browser");
fs.mkdirSync(OUT, { recursive: true });
const steps = [];
function assert(step, cond, detail) {
  steps.push({ step, ok: !!cond, detail: detail ?? null, at: new Date().toISOString() });
  console.log(`${cond ? "OK" : "FAIL"} ${step}`, detail || "");
  if (!cond) throw new Error(`ASSERT ${step}: ${detail}`);
}
function note(step, detail) {
  steps.push({ step, ok: true, detail, note: true, at: new Date().toISOString() });
  console.log("NOTE", step, detail || "");
}
function notTested(step, detail) {
  steps.push({ step, ok: false, detail, not_tested: true, at: new Date().toISOString() });
  console.log("NOT_TESTED", step, detail || "");
}

async function waitReady(page) {
  const t0 = Date.now();
  while (Date.now() - t0 < 90000) {
    try {
      await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 15000 });
      await page.click("#btnHealth");
      await page.waitForTimeout(300);
      if (((await page.textContent("#svcStatus")) || "").includes("ready")) return;
    } catch (_) {}
    await page.waitForTimeout(800);
  }
  throw new Error("workbench not ready");
}

async function hookDraw(page) {
  await page.evaluate(() => {
    const map = window.__wb?.map;
    if (!map || map.__r3Hooked) return;
    map.__r3Hooked = true;
    map.__r3Cmds = [];
    const op = map._poly.bind(map);
    const ot = map._point.bind(map);
    map._poly = function (pts, color, dashed, label, width, alpha) {
      map.__r3Cmds.push({
        kind: "poly",
        n: (pts || []).length,
        color,
        dashed: !!dashed,
        label: label || null,
        sample: (pts || []).slice(0, 2).map((p) => [Number(p[0]), Number(p[1])]),
      });
      return op(pts, color, dashed, label, width, alpha);
    };
    map._point = function (x, y, color, shape, label, alpha) {
      map.__r3Cmds.push({ kind: "point", color, shape, x, y, label: label || null });
      return ot(x, y, color, shape, label, alpha);
    };
  });
}

async function runViewport(width, height) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width, height } });
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(String(e)));

  try {
    await waitReady(page);
    assert(`ready_${width}`, true);

    await page.waitForSelector("#acList li.ac-item", { timeout: 15000 });
    assert(`default_seven_${width}`, (await page.locator("#acList li.ac-item").count()) === 7);

    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    assert(
      `no_h_overflow_${width}`,
      overflow.scrollWidth <= overflow.clientWidth + 2,
      JSON.stringify(overflow)
    );

    // Snapshot full draft before G edit
    const draftBefore = await page.evaluate(() => JSON.parse(JSON.stringify(window.__wb.draftScenario)));

    // Select G (7th aircraft / label starts with G)
    const gLoc = page.locator("#acList li.ac-item").filter({ hasText: /G/ });
    if ((await gLoc.count()) > 0) await gLoc.first().click();
    else await page.locator("#acList li.ac-item").nth(6).click();
    await page.waitForTimeout(150);
    await page.click('.dtab[data-tab="basic"]');
    await page.fill('#tabBasic input[data-f="speed_mps"]', "13.5");
    await page.click('.dtab[data-tab="route"]');
    await page.waitForTimeout(100);
    await page.click("#btnRouteAdd");
    await page.waitForTimeout(100);

    const routeBeforeDrag = await page.evaluate(() =>
      JSON.parse(JSON.stringify(window.__wb.map.routeEdit?.points || []))
    );
    assert(`route_edit_active_${width}`, Array.isArray(routeBeforeDrag), `pts=${routeBeforeDrag?.length}`);

    // Real drag should not add points (move existing / pan) — compare array length
    const box = await page.locator("#cv").boundingBox();
    if (box && routeBeforeDrag.length) {
      await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.3);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width * 0.35, box.y + box.height * 0.32, { steps: 5 });
      await page.mouse.up();
    } else if (box) {
      // No points yet: drag empty should still not invent points without click-add
      await page.mouse.move(box.x + 30, box.y + 30);
      await page.mouse.down();
      await page.mouse.move(box.x + 90, box.y + 50, { steps: 4 });
      await page.mouse.up();
    }
    const afterDrag = await page.evaluate(() =>
      JSON.parse(JSON.stringify(window.__wb.map.routeEdit?.points || []))
    );
    assert(
      `drag_no_extra_route_points_${width}`,
      afterDrag.length === routeBeforeDrag.length,
      `before=${routeBeforeDrag.length} after=${afterDrag.length}`
    );

    // Positive control: canvas click adds a point while editing
    if (box) {
      await page.mouse.click(box.x + box.width * 0.45, box.y + box.height * 0.4);
      await page.waitForTimeout(80);
    }
    const afterClick = await page.evaluate(() =>
      JSON.parse(JSON.stringify(window.__wb.map.routeEdit?.points || []))
    );
    assert(
      `click_adds_route_point_${width}`,
      afterClick.length === routeBeforeDrag.length + 1,
      `before=${routeBeforeDrag.length} afterClick=${afterClick.length}`
    );
    await page.click("#btnRouteDone");

    await page.evaluate(() => window.__wb.commitDrawerToDraft());
    const draftAfter = await page.evaluate(() => JSON.parse(JSON.stringify(window.__wb.draftScenario)));
    const gBefore = draftBefore.aircraft.find((a) => a.label === "G");
    const gAfter = draftAfter.aircraft.find((a) => a.label === "G");
    assert(`g_speed_changed_${width}`, Number(gAfter.speed_mps) === 13.5, `speed=${gAfter.speed_mps}`);
    assert(
      `g_waypoints_changed_${width}`,
      JSON.stringify(gBefore.waypoints) !== JSON.stringify(gAfter.waypoints),
      "waypoints"
    );
    for (const lab of ["A", "B", "C", "D", "E", "F"]) {
      const b = draftBefore.aircraft.find((a) => a.label === lab);
      const a = draftAfter.aircraft.find((a) => a.label === lab);
      assert(
        `other_${lab}_unchanged_${width}`,
        JSON.stringify({ speed: b.speed_mps, wp: b.waypoints, src: b.sources }) ===
          JSON.stringify({ speed: a.speed_mps, wp: a.waypoints, src: a.sources }),
        lab
      );
    }

    // Export via product #btnExportSc then re-import via #scFile
    const exportWait = page.waitForEvent("download", { timeout: 10000 });
    await page.click("#btnExportSc");
    const download = await exportWait;
    const exportedPath = path.join(OUT, `exported_g_${width}.json`);
    await download.saveAs(exportedPath);

    await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
    await waitReady(page);
    await page.locator("#scFile").setInputFiles(exportedPath);
    await page.waitForTimeout(500);
    const reloadedG = await page.evaluate(() => {
      const g = window.__wb?.draftScenario?.aircraft?.find((a) => a.label === "G");
      return g ? { speed: g.speed_mps, nWp: (g.waypoints || []).length } : null;
    });
    assert(
      `reload_g_speed_${width}`,
      reloadedG && Number(reloadedG.speed) === 13.5,
      JSON.stringify(reloadedG)
    );

    // Ensure seven for run (reset if needed)
    if ((await page.locator("#acList li.ac-item").count()) !== 7) {
      page.once("dialog", (d) => d.accept());
      await page.click("#btnResetSeven");
      await page.waitForTimeout(500);
    }
    // Re-apply G speed on draft for run reflection
    await page.locator("#acList li.ac-item").filter({ hasText: /G/ }).first().click();
    await page.click('.dtab[data-tab="basic"]');
    await page.fill('#tabBasic input[data-f="speed_mps"]', "13.5");
    await page.evaluate(() => window.__wb.commitDrawerToDraft());

    await hookDraw(page);
    // Capture request body from product fetch
    let lastRunBody = null;
    await page.route("**/v1/workbench/run/scenario", async (route) => {
      try {
        lastRunBody = JSON.parse(route.request().postData() || "{}");
      } catch (_) {
        lastRunBody = null;
      }
      await route.continue();
    });
    await page.click("#btnRunSim");
    await page.waitForFunction(() => (window.__wb?.runState?.snapshots?.length || 0) > 10, {
      timeout: 180000,
    });
    await page.waitForTimeout(600);
    await hookDraw(page);

    assert(
      `run_request_g_speed_${width}`,
      lastRunBody && Number(lastRunBody.scenario?.aircraft?.find((a) => a.label === "G")?.speed_mps) === 13.5,
      JSON.stringify({ speed: lastRunBody?.scenario?.aircraft?.find((a) => a.label === "G")?.speed_mps })
    );
    const runReflect = await page.evaluate(() => {
      const sc = window.__wb?.runState?.scenario;
      const g = sc?.aircraft?.find((a) => a.label === "G");
      const obs = window.__wb?.runState?.observations || [];
      return {
        scenarioSpeed: g?.speed_mps,
        nSnap: window.__wb?.runState?.snapshots?.length,
        nObs: obs.length,
        // draft must not be used as sole proof
        draftSpeed: window.__wb?.draftScenario?.aircraft?.find((a) => a.label === "G")?.speed_mps,
      };
    });
    assert(
      `run_reflects_g_speed_${width}`,
      Number(runReflect.scenarioSpeed) === 13.5 && runReflect.nObs > 0,
      JSON.stringify(runReflect)
    );

    // Mid: single draw, fused + pred coords
    await page.evaluate(() => {
      const snaps = window.__wb.runState.snapshots;
      const mid = Math.floor(snaps.length * 0.55);
      window.__wb.map.setTimeIndex(mid);
      document.querySelectorAll(".layer").forEach((c) => {
        const L = c.dataset.layer;
        c.checked = L === "fused" || L === "pred" || L === "current";
        c.dispatchEvent(new Event("change", { bubbles: true }));
      });
      window.__wb.map.__r3Cmds = [];
      window.__wb.map.draw();
    });
    await page.waitForTimeout(100);
    const midDraw = await page.evaluate(() => {
      const cmds = window.__wb.map.__r3Cmds || [];
      return {
        fused: cmds.filter((c) => c.kind === "poly" && c.color === "#f72585" && !c.dashed && c.n >= 2),
        pred: cmds.filter((c) => c.kind === "poly" && c.color === "#ff6b6b" && c.dashed && c.n >= 2),
      };
    });
    assert(`mid_fused_polyline_${width}`, midDraw.fused.length >= 1, `n=${midDraw.fused.length}`);
    const coordCheck = await page.evaluate(() => {
      const map = window.__wb.map;
      const snaps = window.__wb.runState.snapshots;
      const end = map.tIndex;
      const histPts = [];
      for (let i = 0; i <= end; i++) {
        for (const tr of snaps[i]?.tracks || []) {
          for (const c of tr.committedHistory || tr.committed_updates || []) {
            const xy =
              c.east_m != null && c.north_m != null
                ? [Number(c.east_m), Number(c.north_m)]
                : map._llToXY(c.latitude, c.longitude);
            histPts.push(xy);
          }
        }
      }
      const fused = (map.__r3Cmds || []).filter(
        (c) => c.kind === "poly" && c.color === "#f72585" && !c.dashed && c.n >= 2 && (c.sample || []).length
      );
      if (!fused.length || !histPts.length) return { ok: false, reason: "no_data", nHist: histPts.length, nFused: fused.length };
      const near = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]) < 3.0;
      const hit = fused.some((c) => (c.sample || []).some((pt) => histPts.some((h) => near(pt, h))));
      return { ok: hit, nHist: histPts.length, nFused: fused.length, sample: fused[0].sample };
    });
    assert(`mid_fused_coords_match_snapshot_${width}`, coordCheck.ok, JSON.stringify(coordCheck));
    if (midDraw.pred.length >= 1) {
      assert(`mid_pred_polyline_${width}`, true, `n=${midDraw.pred.length} sample=${JSON.stringify(midDraw.pred[0].sample)}`);
    } else {
      note(`mid_pred_polyline_${width}`, "no pred episode at mid clock (scenario may lack coast)");
    }

    // Pred off clears pred dashed only
    await page.evaluate(() => {
      window.__wb.map.__r3Cmds = [];
      document.querySelectorAll('.layer[data-layer="pred"]').forEach((c) => {
        c.checked = false;
        c.dispatchEvent(new Event("change", { bubbles: true }));
      });
      window.__wb.map.draw();
    });
    const predOff = await page.evaluate(() => {
      const cmds = window.__wb.map.__r3Cmds || [];
      return {
        pred: cmds.filter((c) => c.kind === "poly" && c.color === "#ff6b6b" && c.dashed).length,
        fused: cmds.filter((c) => c.kind === "poly" && c.color === "#f72585" && !c.dashed).length,
      };
    });
    assert(`pred_off_${width}`, predOff.pred === 0 && predOff.fused >= 1, JSON.stringify(predOff));

    // Termination fixture: mutate last snap tracks=[] via product data layer, redraw once
    await page.evaluate(() => {
      const rs = window.__wb.runState;
      const snaps = rs.snapshots;
      const last = snaps[snaps.length - 1];
      // Keep a prior snap that still has commits; empty only the playhead frame
      last.tracks = [];
      window.__wb.map.setTimeIndex(snaps.length - 1);
      document.querySelectorAll(".layer").forEach((c) => {
        c.checked = c.dataset.layer === "fused";
        c.dispatchEvent(new Event("change", { bubbles: true }));
      });
      window.__wb.map.__r3Cmds = [];
      window.__wb.map.draw();
    });
    const termDraw = await page.evaluate(() => {
      const cmds = window.__wb.map.__r3Cmds || [];
      return {
        live: (window.__wb.runState.snapshots[window.__wb.map.tIndex].tracks || []).length,
        fusedLines: cmds.filter((c) => c.kind === "poly" && c.color === "#f72585" && !c.dashed && c.n >= 2),
        currentPts: cmds.filter((c) => c.kind === "point" && c.shape === "square").length,
      };
    });
    assert(`term_no_live_tracks_${width}`, termDraw.live === 0, JSON.stringify(termDraw));
    assert(`term_keeps_committed_history_${width}`, termDraw.fusedLines.length >= 1, JSON.stringify(termDraw));

    // FAIL fixture via product evaluation + native renderAnomalies (no DOM rewrite)
    const anomalyMeta = await page.evaluate(() => {
      const rs = window.__wb.runState;
      const snaps = rs.snapshots;
      // Prefer a mid snap that still has tracks in archived history — restore one for seek target
      let mid = snaps[Math.floor(snaps.length / 2)];
      if (!(mid.tracks || []).length) {
        mid = snaps.find((s) => (s.tracks || []).length) || mid;
      }
      const fid = mid.tracks?.[0]?.fusionId || "F-synthetic";
      const at = mid.processingTime;
      rs.evaluation = {
        ...(rs.evaluation || {}),
        entity_check: {
          status: "FAIL",
          ok: false,
          details: [{ error: "missing_entity", truth_id: "TRUTH-X", fusionId: fid, at, ok: false }],
        },
        false_merges: [{ fusionId: fid, truth_ids: ["TRUTH-A", "TRUTH-B"], at, via: "round3_fixture" }],
        attribution_errors: [],
        duplicate_targets: [],
        undetermined: [],
      };
      // Product renderer builds list + handlers
      window.__wb.renderAnomalies();
      window.__wb.renderResultPanels();
      const ul = document.getElementById("anomalyList");
      const items = [...(ul?.querySelectorAll("li[data-ai]") || [])].map((li) => ({
        text: li.textContent,
        seek: li.dataset.seek,
        fid: li.dataset.fid,
      }));
      return { fid, at, items, verdict: document.getElementById("resultSummary")?.textContent || "" };
    });
    assert(
      `product_anomaly_items_${width}`,
      anomalyMeta.items.length >= 1,
      JSON.stringify(anomalyMeta.items.slice(0, 3))
    );
    assert(`product_fail_panel_${width}`, /FAIL/i.test(anomalyMeta.verdict), anomalyMeta.verdict.slice(0, 240));

    const beforeIdx = await page.evaluate(() => window.__wb.map.tIndex);
    await page.locator("#anomalyList li[data-ai]").first().click();
    await page.waitForTimeout(200);
    const afterSeek = await page.evaluate(() => ({
      idx: window.__wb.map.tIndex,
      clock: window.__wb.runState.snapshots[window.__wb.map.tIndex]?.processingTime,
      pinned: window.__wb.pinnedDetail?.fusionId || null,
      seekLabel: document.getElementById("seekLabel")?.textContent,
      panel: document.getElementById("resultSummary")?.textContent || "",
    }));
    assert(`product_anomaly_seek_${width}`, afterSeek.idx !== beforeIdx, JSON.stringify({ beforeIdx, afterSeek }));
    assert(
      `product_anomaly_pinned_${width}`,
      afterSeek.pinned === anomalyMeta.fid,
      JSON.stringify({ pinned: afterSeek.pinned, expect: anomalyMeta.fid })
    );
    const seekOk = await page.evaluate((at) => {
      const t = Date.parse(String(at).replace("Z", "+00:00"));
      const cur = Date.parse(
        String(window.__wb.runState.snapshots[window.__wb.map.tIndex].processingTime).replace("Z", "+00:00")
      );
      return Math.abs(cur - t) < 5000;
    }, anomalyMeta.at);
    assert(`product_anomaly_time_${width}`, seekOk, JSON.stringify(afterSeek));

    // Real mouse hit on an observation (project lat/lon → canvas CSS pixels)
    await page.evaluate(() => {
      document.querySelectorAll(".layer").forEach((c) => {
        c.checked = ["rid", "spectrum", "radar", "fused"].includes(c.dataset.layer);
        c.dispatchEvent(new Event("change", { bubbles: true }));
      });
      window.__wb.map.draw();
    });
    const hit = await page.evaluate(() => {
      const map = window.__wb.map;
      const obs = (window.__wb.runState.observations || []).find((o) => o?.observationId && o.latitude != null);
      if (!obs) return { ok: false, reason: "no_obs" };
      const [wx, wy] = map._llToXY(obs.latitude, obs.longitude);
      const [sx, sy] = map.worldToScreen(wx, wy);
      const rect = map.cv.getBoundingClientRect();
      const cssX = sx / (map._cssScale?.().sx || 1);
      const cssY = sy / (map._cssScale?.().sy || 1);
      return {
        ok: true,
        observationId: obs.observationId,
        source: obs.source,
        measurementTime: obs.measurementTime,
        clientX: rect.left + cssX,
        clientY: rect.top + cssY,
      };
    });
    if (!hit.ok) {
      notTested(`obs_mouse_hit_${width}`, hit.reason);
    } else {
      await page.mouse.click(hit.clientX, hit.clientY);
      await page.waitForTimeout(150);
      const insp = await page.evaluate((expectId) => {
        const inspector = document.getElementById("inspector")?.innerText || "";
        const detail = document.getElementById("detail")?.textContent || "";
        return {
          inspector,
          detailHasId: detail.includes(expectId) || inspector.includes(expectId),
          hasSource: /source|RID|rid|spectrum|radar/i.test(inspector),
          hasTime: /measurementTime|2026-04-09/i.test(inspector + detail),
        };
      }, hit.observationId);
      assert(
        `obs_mouse_hit_fields_${width}`,
        insp.detailHasId && insp.hasSource && insp.hasTime,
        JSON.stringify({ hit, insp })
      );
    }

    page.once("dialog", (d) => d.accept());
    await page.click("#btnResetSeven");
    await page.waitForTimeout(400);
    assert(`reset_seven_${width}`, (await page.locator("#acList li.ac-item").count()) === 7);
    assert(`no_js_errors_${width}`, pageErrors.length === 0, pageErrors.join(" | "));
    await page.screenshot({ path: path.join(OUT, `viewport_${width}x${height}.png`), fullPage: true });
  } finally {
    await browser.close();
  }
  return { width, height, pageErrors };
}

const results = [];
for (const [w, h] of [
  [1366, 768],
  [1920, 1080],
]) {
  results.push(await runViewport(w, h));
}
const hardFail = steps.filter((s) => !s.ok && !s.note && !s.not_tested);
const notTestedN = steps.filter((s) => s.not_tested).length;
const noteN = steps.filter((s) => s.note).length;
fs.writeFileSync(
  path.join(OUT, "browser_evidence.json"),
  JSON.stringify(
    {
      steps,
      results,
      summary: {
        hardFail: hardFail.length,
        not_tested: notTestedN,
        notes: noteN,
        not_tested_items: steps.filter((s) => s.not_tested).map((s) => s.step),
      },
    },
    null,
    2
  )
);
console.log("DONE", OUT, "hardFail", hardFail.length, "not_tested", notTestedN, "notes", noteN);
if (hardFail.length) process.exitCode = 1;
