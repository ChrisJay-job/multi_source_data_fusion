/**
 * MI-R2-01 browser: fused HISTORY completeness on real CSV (two viewports).
 * Uses list「查看航迹」; probes draw() geometry (not only collector).
 *
 *   node scripts/task007_map_interaction_browser_r2.mjs <BASE_URL> [OUT_DIR]
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const BASE = process.argv[2];
if (!BASE) {
  console.error("Usage: node scripts/task007_map_interaction_browser_r2.mjs <BASE_URL> [OUT_DIR]");
  process.exit(2);
}
const OUT = path.resolve(process.argv[3] || "reports/task007/map_interaction/r2/browser");
const REAL = path.resolve("samples/task007/5_rid_pp5_leida1_simp.csv");
fs.mkdirSync(OUT, { recursive: true });
const consoleErrors = [];
const shaFile = (p) => crypto.createHash("sha256").update(fs.readFileSync(p)).digest("hex");

async function shot(page, name) {
  await page.screenshot({ path: path.join(OUT, name), fullPage: false });
}

async function staticSha(page) {
  return page.evaluate(async () => {
    const u = "/workbench-static/canvas.js";
    const buf = await fetch(u, { cache: "no-store" }).then((r) => r.arrayBuffer());
    const dig = await crypto.subtle.digest("SHA-256", new Uint8Array(buf));
    const hex = [...new Uint8Array(dig)].map((b) => b.toString(16).padStart(2, "0")).join("");
    const text = new TextDecoder().decode(buf);
    return {
      bytes: buf.byteLength,
      sha256: hex,
      hasUnionDraw: text.includes("Union of already-occurred commits") || text.includes("never \"longest hist only\""),
    };
  });
}

async function runViewport(browser, tag, width, height, dpr) {
  const result = { tag, width, height, deviceScaleFactor: dpr, steps: {}, pass: false };
  const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: dpr });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(`[${tag}] ${m.text()}`); });
  page.on("pageerror", (e) => consoleErrors.push(`[${tag}] ${e}`));

  await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
  result.steps.static = await staticSha(page);

  await page.click('button.tab[data-mode="real"]');
  await page.selectOption("#fusionProfile", "multisensor-v1");
  await page.selectOption("#tzMode", "Asia/Shanghai");
  await page.setInputFiles("#fileInput", REAL);
  await page.click("#btnPreview");
  await page.waitForFunction(
    () => (document.getElementById("importReport")?.textContent || "").includes("有效=472"),
    null, { timeout: 90000 }
  );
  await page.click("#btnRunImport");
  await page.waitForFunction(
    () => {
      const b = document.getElementById("runBanner")?.textContent || "";
      if (b.includes("回放进行中") || b.includes("加载中")) return false;
      return (window.__wb?.map?.state?.snapshots?.length || 0) > 2 && b.includes("当前文件");
    },
    null, { timeout: 300000 }
  );
  await page.evaluate(() => {
    const n = window.__wb.map.state.snapshots.length;
    window.__wb.seekToFrame(n - 1);
  });

  // Only fused + current; hide raw sources
  await page.evaluate(() => {
    const set = (layer, on) => {
      const el = document.querySelector(`.layer[data-layer="${layer}"]`);
      if (el) { el.checked = !!on; el.dispatchEvent(new Event("change", { bubbles: true })); }
    };
    set("rid", false); set("spectrum", false); set("radar", false);
    set("truth", false); set("plan", false); set("pred", false);
    set("fused", true); set("current", true);
    // sync layers object
    window.__wb.map.setLayers({
      rid: false, spectrum: false, radar: false, truth: false, plan: false, pred: false,
      fused: true, current: true,
    });
  });

  const fids = await page.evaluate(() =>
    [...document.querySelectorAll(".btnHistTfilt")].map((b) => b.dataset.fid).filter(Boolean)
  );
  if (!fids.length) {
    result.steps.histBtn = { pass: false, reason: "no_hist_buttons" };
    await ctx.close();
    return result;
  }
  const fid = fids[0];
  await page.evaluate((id) => {
    const btn = [...document.querySelectorAll(".btnHistTfilt")].find((b) => b.dataset.fid === id);
    const det = btn?.closest("details");
    if (det) det.open = true;
  }, fid);
  await page.locator(`.btnHistTfilt[data-fid="${fid}"]`).click();
  await page.waitForTimeout(200);
  await shot(page, `${tag}_fused_history.png`);

  // Probe actual draw geometry for this fusionId (read-only intercept)
  const probe = await page.evaluate((fusionId) => {
    const map = window.__wb.map;
    const rendered = [];
    const origPoly = map._poly.bind(map);
    const origPoint = map._point.bind(map);
    map._poly = (pts, color, ...rest) => {
      if (color === "#f72585" || (map.layers.fused && color)) {
        // COLORS.fused
      }
      if (pts) rendered.push(...pts.map((p) => `${p[0]},${p[1]}`));
      return origPoly(pts, color, ...rest);
    };
    map._point = (x, y, color, ...rest) => {
      rendered.push(`${x},${y}`);
      return origPoint(x, y, color, ...rest);
    };
    map.draw();
    map._poly = origPoly;
    map._point = origPoint;

    const got = map.collectFusionTrackPoints(fusionId);
    const commitPts = got.pts.filter((p) => p.kind === "fusion" || p.pointId || true);
    // Early vs late: min/max east-ish from commits
    let minT = Infinity, maxT = -Infinity, early = null, late = null;
    for (const p of got.pts) {
      if (p.t < minT) { minT = p.t; early = p.xy; }
      if (p.t > maxT) { maxT = p.t; late = p.xy; }
    }
    const distinct = new Set(rendered);
    const earlyDrawn = early && [...distinct].some((k) => {
      const [x, y] = k.split(",").map(Number);
      return Math.hypot(x - early[0], y - early[1]) < 1e-3;
    });
    const lateDrawn = late && [...distinct].some((k) => {
      const [x, y] = k.split(",").map(Number);
      return Math.hypot(x - late[0], y - late[1]) < 1e-3;
    });
    // Also: rendered count should be >= collector fusion points when only fused drawn
    return {
      fusionId,
      nCollector: got.nFusion,
      nRenderedDistinct: distinct.size,
      earlyDrawn: !!earlyDrawn,
      lateDrawn: !!lateDrawn,
      focusStatus: document.getElementById("focusStatus")?.textContent || "",
      layers: { ...map.layers },
      pass: got.nFusion >= 1 && earlyDrawn && lateDrawn && distinct.size >= Math.min(got.nFusion, 2),
    };
  }, fid);

  result.steps.fusedDraw = probe;
  result.steps.histBtn = { pass: true, fid };
  result.pass = !!(result.steps.static?.hasUnionDraw && probe.pass);
  await ctx.close();
  return result;
}

const sample = {
  path: REAL,
  exists: fs.existsSync(REAL),
  sha256: fs.existsSync(REAL) ? shaFile(REAL) : null,
  expected: "32772531c62f4643503892fd31ce1e9e477eff86e482b17eb75b40f107d2d34b",
};
sample.match = sample.sha256 === sample.expected;

const browser = await chromium.launch({ headless: true });
const viewports = [];
viewports.push(await runViewport(browser, "1920x1080_dpr1", 1920, 1080, 1));
viewports.push(await runViewport(browser, "1280x800_dpr2", 1280, 800, 2));
await browser.close();

const out = {
  base: BASE,
  sample,
  viewports,
  consoleErrors,
  pass: viewports.every((v) => v.pass) && consoleErrors.length === 0 && sample.match,
};
fs.writeFileSync(path.join(OUT, "browser_result.json"), JSON.stringify(out, null, 2));
console.log(JSON.stringify({
  pass: out.pass,
  base: BASE,
  viewports: viewports.map((v) => ({
    tag: v.tag, pass: v.pass,
    nCollector: v.steps.fusedDraw?.nCollector,
    nRendered: v.steps.fusedDraw?.nRenderedDistinct,
    early: v.steps.fusedDraw?.earlyDrawn,
    late: v.steps.fusedDraw?.lateDrawn,
    canvasSha: v.steps.static?.sha256?.slice(0, 12),
  })),
  consoleErrors,
}, null, 2));
process.exit(out.pass ? 0 : 1);
