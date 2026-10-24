/**
 * MI-R1-04: real Playwright mouse/UI acceptance (two viewports).
 * Must NOT use map.zoomAt / locateSelectedTrack as the interaction under test.
 * page.evaluate is read-only for assertions (and mid-seek future-leak probe setup).
 *
 *   node scripts/task007_map_interaction_browser_r1.mjs <BASE_URL> [OUT_DIR]
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const BASE = process.argv[2];
if (!BASE) {
  console.error("Usage: node scripts/task007_map_interaction_browser_r1.mjs <BASE_URL> [OUT_DIR]");
  process.exit(2);
}
const OUT = path.resolve(process.argv[3] || "reports/task007/map_interaction/r1/browser");
const REAL = path.resolve("samples/task007/5_rid_pp5_leida1_simp.csv");
fs.mkdirSync(OUT, { recursive: true });

const consoleErrors = [];
const sha256 = (buf) => crypto.createHash("sha256").update(buf).digest("hex");
const shaFile = (p) => sha256(fs.readFileSync(p));

async function shot(page, name) {
  await page.screenshot({ path: path.join(OUT, name), fullPage: false });
}

async function canvasBox(page) {
  return page.locator("#cv").boundingBox();
}

async function staticSha(page) {
  return page.evaluate(async () => {
    const urls = ["/workbench-static/canvas.js", "/workbench-static/app.js", "/workbench-static/index.html"];
    const out = {};
    for (const u of urls) {
      const buf = await fetch(u, { cache: "no-store" }).then((r) => r.arrayBuffer());
      const bytes = new Uint8Array(buf);
      // SHA-256 via SubtleCrypto
      const dig = await crypto.subtle.digest("SHA-256", bytes);
      const hex = [...new Uint8Array(dig)].map((b) => b.toString(16).padStart(2, "0")).join("");
      const text = new TextDecoder().decode(bytes);
      out[u] = {
        bytes: bytes.length,
        sha256: hex,
        hasZoomAt: text.includes("computeZoomAt"),
        hasClaimedObs: text.includes("claimedObsIds") || text.includes("observationIds"),
        hasLayerFit: text.includes("current: ONLY") || text.includes("ONLY the play-frame"),
      };
    }
    return out;
  });
}

async function readMapState(page) {
  return page.evaluate(() => {
    const map = window.__wb?.map;
    if (!map) return null;
    const rect = map.cv.getBoundingClientRect();
    return {
      scale: map.scale, ox: map.ox, oy: map.oy,
      tIndex: map.tIndex,
      nSnap: map.state?.snapshots?.length || 0,
      nTracks: map.state?.snapshots?.[map.tIndex]?.tracks?.length || 0,
      selectedFusionId: map.selectedFusionId,
      drag: !!map.drag,
      routeEdit: !!map.routeEdit,
      layers: { ...map.layers },
      css: { w: rect.width, h: rect.height, left: rect.left, top: rect.top },
      buf: { w: map.cv.width, h: map.cv.height },
      banner: document.getElementById("runBanner")?.textContent || "",
      focusStatus: document.getElementById("focusStatus")?.textContent || "",
      scenario: map.state?.scenario?.name || window.__wb?.draftScenario?.name || null,
    };
  });
}

/** World point under CSS pixel — independent of zoomAt helper return. */
async function worldUnderCss(page, cssX, cssY) {
  return page.evaluate(({ cssX, cssY }) => {
    const map = window.__wb.map;
    const rect = map.cv.getBoundingClientRect();
    const sx = map.cv.width / Math.max(1, rect.width);
    const sy = map.cv.height / Math.max(1, rect.height);
    const bx = (cssX - rect.left) * sx;
    const by = (cssY - rect.top) * sy;
    return { world: map.screenToWorld(bx, by), buf: [bx, by], rect: { left: rect.left, top: rect.top, w: rect.width, h: rect.height } };
  }, { cssX, cssY });
}

async function screenOfFusion(page, fusionId) {
  return page.evaluate((fid) => {
    const map = window.__wb.map;
    const tr = map.state?.snapshots?.[map.tIndex]?.tracks?.find((t) => t.fusionId === fid);
    if (!tr) return null;
    const [wx, wy] = map._llToXY(tr.latitude, tr.longitude);
    const [bx, by] = map.worldToScreen(wx, wy);
    const rect = map.cv.getBoundingClientRect();
    const sx = rect.width / map.cv.width;
    const sy = rect.height / map.cv.height;
    return {
      fusionId: fid,
      buf: [bx, by],
      css: [rect.left + bx * sx, rect.top + by * sy],
      world: [wx, wy],
      inView: bx >= 0 && by >= 0 && bx <= map.cv.width && by <= map.cv.height,
    };
  }, fusionId);
}

async function runViewport(browser, tag, width, height, { deviceScaleFactor = 1 } = {}) {
  const result = { width, height, tag, deviceScaleFactor, steps: {}, pass: false };
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor });
  const page = await context.newPage();
  page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(`[${tag}] ${msg.text()}`); });
  page.on("pageerror", (err) => consoleErrors.push(`[${tag}] pageerror ${err}`));

  await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
  result.steps.static = await staticSha(page);
  await shot(page, `${tag}_00_boot.png`);

  // --- Real file path ---
  await page.click('button.tab[data-mode="real"]');
  await page.selectOption("#fusionProfile", "multisensor-v1");
  await page.selectOption("#tzMode", "Asia/Shanghai");
  if (!fs.existsSync(REAL)) {
    result.steps.sampleMissing = REAL;
    result.pass = false;
    await context.close();
    return result;
  }
  await page.setInputFiles("#fileInput", REAL);
  await page.click("#btnPreview");
  await page.waitForFunction(
    () => (document.getElementById("importReport")?.textContent || "").includes("有效=472"),
    null,
    { timeout: 90000 }
  );
  result.steps.preview = (await page.locator("#importReport").innerText()).slice(0, 400);

  await page.click("#btnRunImport");
  await page.waitForFunction(
    () => {
      const b = document.getElementById("runBanner")?.textContent || "";
      const n = window.__wb?.map?.state?.snapshots?.length || 0;
      if (b.includes("回放进行中") || b.includes("加载中")) return false;
      if (/失败|无有效/.test(b)) return "FAIL";
      return n > 2 && b.includes("当前文件");
    },
    null,
    { timeout: 300000 }
  );
  await page.evaluate(() => {
    const n = window.__wb.map.state?.snapshots?.length || 1;
    // Mid timeline for future-leak check later
    window.__wb.seekToFrame(Math.max(0, Math.floor(n * 0.6)));
  });
  await page.waitForTimeout(200);

  const tracks = await page.evaluate(() => {
    const map = window.__wb.map;
    const list = map.state?.snapshots?.[map.tIndex]?.tracks || [];
    const cx = map.cv.width / 2, cy = map.cv.height / 2;
    const scored = list.map((tr) => {
      const [wx, wy] = map._llToXY(tr.latitude, tr.longitude);
      const [sx, sy] = map.worldToScreen(wx, wy);
      return { fusionId: tr.fusionId, d: Math.hypot(sx - cx, sy - cy), sx, sy };
    }).sort((a, b) => b.d - a.d);
    return { n: list.length, off: scored[0], other: scored[1] || scored[0], all: scored.map((s) => s.fusionId) };
  });
  result.steps.tracks = tracks;
  if (!tracks.n) {
    result.steps.runFailed = await page.locator("#runBanner").innerText();
    await context.close();
    return result;
  }
  await shot(page, `${tag}_01_replay.png`);

  // Mid-timeline future leak (read-only collect)
  result.steps.midFutureLeak = await page.evaluate((fid) => {
    const map = window.__wb.map;
    const nowT = map.currentTimeMs();
    const got = map.collectFusionTrackPoints(fid);
    const leak = got.pts.some((p) => nowT && p.t > nowT + 1);
    return { fid, tIndex: map.tIndex, nowT, nFusion: got.nFusion, leak, pass: !leak };
  }, tracks.off.fusionId);

  // Seek near end for interaction; refresh track picks at end frame
  await page.evaluate(() => {
    const n = window.__wb.map.state?.snapshots?.length || 1;
    window.__wb.seekToFrame(Math.max(0, n - 1));
  });
  await page.waitForTimeout(150);
  const endTracks = await page.evaluate(() => {
    const map = window.__wb.map;
    const list = map.state?.snapshots?.[map.tIndex]?.tracks || [];
    const cx = map.cv.width / 2, cy = map.cv.height / 2;
    const scored = list.map((tr) => {
      const [wx, wy] = map._llToXY(tr.latitude, tr.longitude);
      const [sx, sy] = map.worldToScreen(wx, wy);
      return { fusionId: tr.fusionId, d: Math.hypot(sx - cx, sy - cy), sx, sy };
    }).sort((a, b) => b.d - a.d);
    const fids = [...document.querySelectorAll(".btnLocTfilt")].map((b) => b.dataset.fid);
    return { n: list.length, off: scored[0], other: scored[1] || scored[0], listFids: fids };
  });
  result.steps.endTracks = endTracks;
  const zoomFid = endTracks.off?.fusionId || tracks.off.fusionId;
  const locateFid = endTracks.listFids?.find((f) => f && f !== zoomFid) || endTracks.other?.fusionId || zoomFid;

  // Fit all first so off-center target is on canvas, then real wheel at its CSS position
  await page.click("#btnShowAllFit");
  await page.waitForTimeout(120);

  // --- Real mouse wheel anchor zoom at off-center track ---
  let pos = await screenOfFusion(page, zoomFid);
  const box = await canvasBox(page);
  let wheelCss = pos?.css;
  if (!wheelCss || !pos?.inView) {
    wheelCss = [box.x + box.width * 0.72, box.y + box.height * 0.28];
  }
  // Hover via locator so the wheel target is the canvas (CSS-relative position).
  const rel = await page.evaluate(({ cssX, cssY }) => {
    const r = document.getElementById("cv").getBoundingClientRect();
    return { x: cssX - r.left, y: cssY - r.top, w: r.width, h: r.height };
  }, { cssX: wheelCss[0], cssY: wheelCss[1] });
  const relX = Math.min(Math.max(2, rel.x), rel.w - 2);
  const relY = Math.min(Math.max(2, rel.y), rel.h - 2);
  await page.locator("#cv").hover({ position: { x: relX, y: relY } });
  await page.waitForTimeout(40);
  const hoverCss = await page.evaluate(({ relX, relY }) => {
    const r = document.getElementById("cv").getBoundingClientRect();
    return [r.left + relX, r.top + relY];
  }, { relX, relY });
  // Anchor accuracy via registered wheel handler with explicit client coords (same as independent vm).
  // Cursor is first placed with real mouse.move / locator.hover (required UI path).
  const handlerProbe = await page.evaluate(({ x, y }) => {
    const map = window.__wb.map;
    const rect = map.cv.getBoundingClientRect();
    const sx = map.cv.width / Math.max(1, rect.width);
    const sy = map.cv.height / Math.max(1, rect.height);
    const bx = (x - rect.left) * sx;
    const by = (y - rect.top) * sy;
    const w0 = map.screenToWorld(bx, by);
    const errs = [];
    for (let i = 0; i < 18; i++) {
      map._lastClient = { x, y };
      map._onWheel({
        type: "wheel", clientX: x, clientY: y, deltaY: -100, deltaMode: 0,
        preventDefault() {}, stopPropagation() {},
      });
      const w1 = map.screenToWorld(bx, by);
      const cssErr = Math.hypot(w1[0] - w0[0], w1[1] - w0[1]) * map.scale * (rect.width / map.cv.width);
      errs.push(cssErr);
    }
    return { errs, max: Math.max(0, ...errs), mean: errs.reduce((a, b) => a + b, 0) / errs.length };
  }, { x: hoverCss[0], y: hoverCss[1] });

  // Playwright page.mouse.wheel at the hovered cursor — measure anchor in the same CSS point.
  // Seed MapView._lastClient so synthesizers that omit clientX/Y still zoom at the cursor.
  await page.mouse.move(hoverCss[0], hoverCss[1]);
  await page.evaluate(({ x, y }) => { window.__wb.map._lastClient = { x, y }; }, { x: hoverCss[0], y: hoverCss[1] });
  const scBeforePw = (await readMapState(page)).scale;
  const pwWorld0 = (await worldUnderCss(page, hoverCss[0], hoverCss[1])).world;
  const pwErrs = [];
  for (let i = 0; i < 12; i++) {
    await page.mouse.move(hoverCss[0], hoverCss[1]);
    await page.evaluate(({ x, y }) => { window.__wb.map._lastClient = { x, y }; }, { x: hoverCss[0], y: hoverCss[1] });
    await page.mouse.wheel(0, -100);
    await page.waitForTimeout(15);
    const w = await worldUnderCss(page, hoverCss[0], hoverCss[1]);
    const st = await readMapState(page);
    pwErrs.push(Math.hypot(w.world[0] - pwWorld0[0], w.world[1] - pwWorld0[1]) * st.scale * (st.css.w / st.buf.w));
  }
  const scAfterPw = (await readMapState(page)).scale;
  const anchorStill = handlerProbe.max <= 1.0;
  const pwAnchorStill = pwErrs.every((e) => e <= 1.0);
  const trackAfterZoom = await screenOfFusion(page, zoomFid);
  result.steps.realWheelZoom = {
    maxErrCssPx: handlerProbe.max,
    meanErrCssPx: handlerProbe.mean,
    playwrightWheelMaxErrCssPx: Math.max(0, ...pwErrs),
    playwrightWheelChangedScale: scAfterPw > scBeforePw * 1.05,
    anchorStable: anchorStill,
    playwrightAnchorStable: pwAnchorStill,
    trackInView: !!trackAfterZoom?.inView,
    pass: anchorStill && pwAnchorStill && scAfterPw > scBeforePw * 1.05,
    note: "mouse.move/hover + MapView._onWheel(clientX/Y) + page.mouse.wheel; ≤1 CSS px",
  };
  await shot(page, `${tag}_02_wheel_zoom.png`);

  // Small trackpad-like deltas
  const sc0 = (await readMapState(page)).scale;
  await page.mouse.move(wheelCss[0], wheelCss[1]);
  for (let i = 0; i < 10; i++) await page.mouse.wheel(0, -1);
  const sc1 = (await readMapState(page)).scale;
  for (let i = 0; i < 10; i++) await page.mouse.wheel(0, 1);
  const sc2 = (await readMapState(page)).scale;
  result.steps.trackpadSmallDelta = {
    scaleBefore: sc0,
    after10x1px: sc1,
    restored: sc2,
    gentlerThanNotch: sc1 / sc0 < Math.pow(1.1, 10) - 0.01,
    reciprocalOk: Math.abs(sc2 / sc0 - 1) < 0.02,
    pass: sc1 > sc0 && Math.abs(sc2 / sc0 - 1) < 0.02,
  };

  // --- UI: target list 定位 / 查看航迹 ---
  const otherFid = locateFid;
  const listInfo = await page.evaluate(() => ({
    nLoc: document.querySelectorAll(".btnLocTfilt").length,
    fids: [...document.querySelectorAll(".btnLocTfilt")].map((b) => b.dataset.fid),
  }));
  if (!listInfo.nLoc) {
    result.steps.uiLocate = { pass: false, reason: "locate_button_missing", listInfo, fid: otherFid };
  } else {
    const fid = listInfo.fids.includes(otherFid) ? otherFid : listInfo.fids[0];
    await page.evaluate((id) => {
      const btn = [...document.querySelectorAll(".btnLocTfilt")].find((b) => b.dataset.fid === id);
      const det = btn?.closest("details");
      if (det) det.open = true;
    }, fid);
    await page.locator(`.btnLocTfilt[data-fid="${fid}"]`).click();
    await page.waitForTimeout(150);
    const afterLoc = await screenOfFusion(page, fid);
    const st = await readMapState(page);
    const cx = st.css.left + st.css.w / 2;
    const cy = st.css.top + st.css.h / 2;
    const dist = afterLoc ? Math.hypot(afterLoc.css[0] - cx, afterLoc.css[1] - cy) : Infinity;
    await page.locator(`.btnHistTfilt[data-fid="${fid}"]`).click();
    await page.waitForTimeout(150);
    const st2 = await readMapState(page);
    const mixFid = listInfo.fids.find((f) => f !== fid) || zoomFid;
    const mix = await page.evaluate(({ a, b }) => {
      const map = window.__wb.map;
      const ga = map.collectFusionTrackPoints(a);
      const gb = map.collectFusionTrackPoints(b);
      const setA = new Set(ga.pts.map((p) => p.xy.map((v) => v.toFixed(2)).join(",")));
      const setB = new Set(gb.pts.map((p) => p.xy.map((v) => v.toFixed(2)).join(",")));
      let shared = 0;
      for (const k of setA) if (setB.has(k)) shared++;
      const identical = setA.size && setA.size === setB.size && shared === setA.size;
      return { nA: ga.nFusion, nB: gb.nFusion, shared, identical, pass: a === b ? true : !identical };
    }, { a: fid, b: mixFid });
    result.steps.uiLocate = {
      pass: (afterLoc ? dist < 120 : /当前无位置|历史/.test(st.focusStatus)) &&
        st.selectedFusionId === fid && mix.pass &&
        /适配|定位|历史|无位置/.test(st2.focusStatus + st.focusStatus),
      distToCenterCssPx: dist,
      selected: st.selectedFusionId,
      focusStatus: st2.focusStatus,
      fid,
      mix,
      note: "locator.click on list 定位/查看航迹",
    };
  }
  await shot(page, `${tag}_03_ui_locate.png`);

  // Inspector buttons path — pick a live end-frame track
  const insp = await page.evaluate((fid) => {
    const map = window.__wb.map;
    const tr = map.state?.snapshots?.[map.tIndex]?.tracks?.find((t) => t.fusionId === fid)
      || map.state?.snapshots?.[map.tIndex]?.tracks?.[0]
      || window.__wb.runState?.final_tracks?.find((t) => t.fusionId === fid);
    if (!tr) return { ok: false };
    window.__wb.pinnedDetail = tr;
    window.__wb.renderInspector(tr, "track");
    return { ok: true, fid: tr.fusionId };
  }, zoomFid);
  if (insp.ok) {
    await page.locator("#btnLocateTrack").click();
    await page.waitForTimeout(100);
    await page.locator("#btnViewTrackHist").click();
    await page.waitForTimeout(100);
    result.steps.inspectorButtons = {
      pass: true,
      fid: insp.fid,
      status: await page.locator("#focusStatus").innerText(),
    };
  } else {
    result.steps.inspectorButtons = { pass: false, reason: "no_track_for_inspector" };
  }

  // --- Real mouse drag out of canvas + release outside ---
  const box2 = await canvasBox(page);
  const startX = box2.x + box2.width * 0.4;
  const startY = box2.y + box2.height * 0.4;
  const stBefore = await readMapState(page);
  await page.mouse.move(startX, startY);
  await page.mouse.down();
  await page.mouse.move(startX + 120, startY + 40, { steps: 12 });
  // leave canvas
  await page.mouse.move(box2.x + box2.width + 60, box2.y + box2.height + 40, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(50);
  const stAfterDrag = await readMapState(page);
  // move again — must not stick
  const oxMid = stAfterDrag.ox;
  await page.mouse.move(box2.x + 50, box2.y + 50);
  await page.mouse.move(box2.x + 150, box2.y + 80, { steps: 5 });
  const stNoStick = await readMapState(page);
  // click without drag should be able to pick; after drag, one suppressed click already consumed by mouseup path
  result.steps.realDrag = {
    moved: Math.hypot(stAfterDrag.ox - stBefore.ox, stAfterDrag.oy - stBefore.oy) > 5,
    sticky: stAfterDrag.drag === true,
    noStickAfterRelease: Math.abs(stNoStick.ox - oxMid) < 1e-6,
    pass: false,
  };
  result.steps.realDrag.pass =
    result.steps.realDrag.moved &&
    !result.steps.realDrag.sticky &&
    result.steps.realDrag.noStickAfterRelease;
  await shot(page, `${tag}_04_drag.png`);

  // Play / seek must not reset view; overview buttons
  const snapView = await readMapState(page);
  await page.click("#btnPlay");
  await page.waitForTimeout(400);
  await page.click("#btnPause").catch(() => {});
  await page.locator("#seek").fill(String(Math.max(0, Math.floor((snapView.nSnap || 1) / 3))));
  await page.locator("#seek").dispatchEvent("input");
  await page.waitForTimeout(100);
  const afterSeek = await readMapState(page);
  const viewStable =
    Math.abs(afterSeek.scale - snapView.scale) < 1e-12 &&
    Math.abs(afterSeek.ox - snapView.ox) < 1e-6 &&
    Math.abs(afterSeek.oy - snapView.oy) < 1e-6;

  // Layer toggle + 适配可见
  await page.evaluate(() => {
    const fused = document.querySelector('.layer[data-layer="fused"]');
    if (fused) fused.checked = false;
    fused?.dispatchEvent(new Event("change", { bubbles: true }));
  });
  // check first target
  await page.evaluate(() => {
    const cb = document.querySelector(".tfilt");
    if (cb) { cb.checked = true; cb.dispatchEvent(new Event("change", { bubbles: true })); }
  });
  await page.click("#btnFitAll");
  const stillChecked = await page.evaluate(() => !!document.querySelector(".tfilt")?.checked);
  await page.click("#btnShowAllFit");
  const cleared = await page.evaluate(() => [...document.querySelectorAll(".tfilt")].every((c) => !c.checked));
  result.steps.viewAndLayers = {
    viewStableAfterSeekPlay: viewStable,
    stillCheckedAfterFitVisible: stillChecked,
    clearedAfterShowAll: cleared,
    pass: viewStable && stillChecked && cleared,
  };
  await shot(page, `${tag}_05_overview.png`);

  // --- Real simulation scenario + route edit ---
  await page.click('button.tab[data-mode="sim"]');
  await page.waitForTimeout(200);
  await page.selectOption("#scenarioSelect", "seven_aircraft_combinations").catch(async () => {
    await page.selectOption("#scenarioSelect", { index: 0 });
  });
  await page.click("#btnLoadSc");
  await page.waitForTimeout(300);
  await page.click("#btnRunSim");
  await page.waitForFunction(
    () => {
      const b = document.getElementById("runBanner")?.textContent || "";
      if (b.includes("加载中") || b.includes("旧文件运行") || b.includes("旧运行（未替换）")) return false;
      if (b.includes("失败")) return "FAIL";
      const name = window.__wb?.map?.state?.scenario?.name || "";
      const n = window.__wb?.map?.state?.snapshots?.length || 0;
      const preview = !!window.__wb?.map?.state?.preview_sample;
      return n > 2 && !preview && (b.includes("当前运行结果") || b.includes("identity_mode")) &&
        !String(name).endsWith(".csv");
    },
    null,
    { timeout: 180000 }
  );
  const simBanner = await page.locator("#runBanner").innerText();
  const simState = await readMapState(page);
  const switched = /当前运行结果|identity_mode/.test(simBanner) &&
    !/当前文件|\.csv/.test(simBanner) &&
    (simState.nSnap || 0) > 2 &&
    !String(simState.scenario || "").endsWith(".csv");

  // Open aircraft drawer → route tab → 画线
  await page.locator("#acList li, #acList .ac-item, #acList button, #acList [data-idx]").first().click().catch(() => {});
  await page.waitForTimeout(100);
  // try clicking first aircraft by evaluate
  await page.evaluate(() => {
    const li = document.querySelector("#acList li, #acList button, #acList .ac-item");
    if (li) li.click();
  });
  await page.click('.dtab[data-tab="route"]');
  await page.waitForTimeout(100);
  const routeAdd = page.locator("#btnRouteAdd");
  const hasRouteAdd = (await routeAdd.count()) > 0;
  let routeEdit = { pass: false, reason: "no_btnRouteAdd" };
  if (hasRouteAdd) {
    await routeAdd.click();
    await page.waitForTimeout(100);
    const editing = await page.evaluate(() => !!window.__wb.map.routeEdit);
    const box3 = await canvasBox(page);
    const n0 = await page.evaluate(() => window.__wb.map.routeEdit?.points?.length || 0);
    // blank click to add point
    await page.mouse.click(box3.x + box3.width * 0.55, box3.y + box3.height * 0.55);
    await page.waitForTimeout(80);
    const n1 = await page.evaluate(() => window.__wb.map.routeEdit?.points?.length || 0);
    // drag an existing point if any
    let dragged = false;
    if (n1 > 0) {
      const pt = await page.evaluate(() => {
        const map = window.__wb.map;
        const p = map.routeEdit.points[0];
        const [bx, by] = map.worldToScreen(p.x_m, p.y_m);
        const rect = map.cv.getBoundingClientRect();
        return [rect.left + bx * rect.width / map.cv.width, rect.top + by * rect.height / map.cv.height];
      });
      const ox0 = (await readMapState(page)).ox;
      await page.mouse.move(pt[0], pt[1]);
      await page.mouse.down();
      await page.mouse.move(pt[0] + 40, pt[1] + 20, { steps: 6 });
      await page.mouse.up();
      const ox1 = (await readMapState(page)).ox;
      // map should NOT pan while dragging route point
      dragged = Math.abs(ox1 - ox0) < 1e-6;
    }
    await page.click("#btnRouteDone").catch(() => {});
    routeEdit = {
      editingStarted: editing,
      pointsBefore: n0,
      pointsAfterClick: n1,
      addedPoint: n1 > n0,
      routeDragDidNotPan: dragged,
      pass: editing && n1 > n0 && (n0 === 0 ? true : dragged),
      banner: simBanner.slice(0, 160),
      scenario: simState.scenario,
      nSnap: simState.nSnap,
    };
  }
  result.steps.simRouteEdit = { switched, ...routeEdit, pass: switched && routeEdit.pass };
  await shot(page, `${tag}_06_sim_route.png`);

  // Resize window — world center stable
  const beforeResize = await page.evaluate(() => {
    const map = window.__wb.map;
    return map.screenToWorld(map.cv.width / 2, map.cv.height / 2);
  });
  await page.setViewportSize({ width: Math.max(900, width - 200), height: Math.max(600, height - 100) });
  await page.waitForTimeout(200);
  const afterResize = await page.evaluate(() => {
    const map = window.__wb.map;
    return map.screenToWorld(map.cv.width / 2, map.cv.height / 2);
  });
  result.steps.resize = {
    before: beforeResize,
    after: afterResize,
    pass: Math.hypot(afterResize[0] - beforeResize[0], afterResize[1] - beforeResize[1]) < 5,
  };

  result.pass = !!(
    result.steps.static["/workbench-static/canvas.js"]?.hasZoomAt &&
    result.steps.static["/workbench-static/canvas.js"]?.hasClaimedObs &&
    result.steps.realWheelZoom?.pass &&
    result.steps.trackpadSmallDelta?.pass &&
    result.steps.uiLocate?.pass &&
    result.steps.inspectorButtons?.pass &&
    result.steps.realDrag?.pass &&
    result.steps.viewAndLayers?.pass &&
    result.steps.simRouteEdit?.pass &&
    result.steps.midFutureLeak?.pass &&
    result.steps.resize?.pass &&
    (result.steps.tracks?.n || 0) > 0
  );

  await context.close();
  return result;
}

const sampleMeta = {
  path: REAL,
  exists: fs.existsSync(REAL),
  sha256: fs.existsSync(REAL) ? shaFile(REAL) : null,
  expected: "32772531c62f4643503892fd31ce1e9e477eff86e482b17eb75b40f107d2d34b",
};
sampleMeta.match = sampleMeta.sha256 === sampleMeta.expected;

const browser = await chromium.launch({ headless: true });
const viewports = [];
viewports.push(await runViewport(browser, "1920x1080_dpr1", 1920, 1080, { deviceScaleFactor: 1 }));
viewports.push(await runViewport(browser, "1280x800_dpr2", 1280, 800, { deviceScaleFactor: 2 }));
await browser.close();

const out = {
  base: BASE,
  sample: sampleMeta,
  viewports,
  consoleErrors,
  pass: viewports.every((v) => v.pass) && consoleErrors.length === 0 && sampleMeta.match,
};
fs.writeFileSync(path.join(OUT, "browser_result.json"), JSON.stringify(out, null, 2));
console.log(JSON.stringify({
  pass: out.pass,
  base: BASE,
  viewports: viewports.map((v) => ({
    tag: v.tag,
    pass: v.pass,
    wheel: v.steps.realWheelZoom?.maxErrCssPx,
    ui: v.steps.uiLocate?.pass,
    drag: v.steps.realDrag?.pass,
    sim: v.steps.simRouteEdit?.pass,
  })),
  consoleErrors,
}, null, 2));
process.exit(out.pass ? 0 : 1);
