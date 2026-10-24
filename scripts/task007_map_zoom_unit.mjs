/**
 * Targeted zoom tests against the LIVE workbench module (real computeZoomAt via page).
 * Also records independent screen-position checks (not reusing only the helper return).
 *
 *   node scripts/task007_map_zoom_unit.mjs [BASE_URL]
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.argv[2] || "http://127.0.0.1:18089";
const OUT = path.resolve("reports/task007/map_interaction");
fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
await page.waitForFunction(() => window.__wb?.computeZoomAt && window.__wb?.map, null, { timeout: 30000 });

const summary = await page.evaluate(() => {
  const { computeZoomAt, MAP_ZOOM_FACTOR, MAP_MIN_SCALE, MAP_MAX_SCALE, map } = window.__wb;
  const worldToScreen = (ox, oy, scale, wx, wy) => [ox + wx * scale, oy - wy * scale];
  const cases = [];
  const run = (name, fn) => {
    try {
      cases.push({ name, ok: true, ...fn() });
    } catch (e) {
      cases.push({ name, ok: false, error: String(e?.message || e) });
    }
  };

  const anchors = [
    { name: "center", px: 600, py: 400 },
    { name: "near_tl", px: 40, py: 40 },
    { name: "near_tr", px: 1160, py: 40 },
    { name: "near_bl", px: 40, py: 760 },
    { name: "near_br", px: 1160, py: 760 },
    { name: "off_origin_target", px: 800, py: 250 },
  ];
  for (const a of anchors) {
    run(`anchor_20x_${a.name}`, () => {
      let ox = 600, oy = 400, scale = 1.2;
      const worldUnderMouse = [(a.px - ox) / scale, (oy - a.py) / scale];
      const errs = [];
      for (let i = 0; i < 20; i++) {
        const r = computeZoomAt({
          ox, oy, scale, px: a.px, py: a.py,
          factor: MAP_ZOOM_FACTOR, minScale: MAP_MIN_SCALE, maxScale: MAP_MAX_SCALE,
        });
        if (!r.ok) throw new Error("zoom failed");
        ox = r.ox; oy = r.oy; scale = r.scale;
        // Independent projection (not reading r.world alone)
        const after = worldToScreen(ox, oy, scale, worldUnderMouse[0], worldUnderMouse[1]);
        const err = Math.hypot(after[0] - a.px, after[1] - a.py);
        errs.push(err);
        if (err > 1.0) throw new Error(`step ${i} err=${err}`);
      }
      // Also verify live MapView.zoomAt mutates the same way
      const oxB = map.ox, oyB = map.oy, scB = map.scale;
      map.ox = 600; map.oy = 400; map.scale = 1.2;
      const w2 = [(a.px - map.ox) / map.scale, (map.oy - a.py) / map.scale];
      for (let i = 0; i < 5; i++) map.zoomAt(a.px, a.py, MAP_ZOOM_FACTOR);
      const live = map.worldToScreen(w2[0], w2[1]);
      const liveErr = Math.hypot(live[0] - a.px, live[1] - a.py);
      map.ox = oxB; map.oy = oyB; map.scale = scB;
      if (liveErr > 1.0) throw new Error(`live MapView err=${liveErr}`);
      return { maxErr: Math.max(...errs), meanErr: errs.reduce((s, v) => s + v, 0) / errs.length, liveErr, finalScale: scale };
    });
  }

  run("reciprocal_restore", () => {
    let ox = 500, oy = 350, scale = 2.5;
    const px = 720, py = 180;
    const s0 = scale, o0 = ox, y0 = oy;
    for (let i = 0; i < 8; i++) {
      const r = computeZoomAt({ ox, oy, scale, px, py, factor: MAP_ZOOM_FACTOR, minScale: MAP_MIN_SCALE, maxScale: MAP_MAX_SCALE });
      ox = r.ox; oy = r.oy; scale = r.scale;
    }
    for (let i = 0; i < 8; i++) {
      const r = computeZoomAt({ ox, oy, scale, px, py, factor: 1 / MAP_ZOOM_FACTOR, minScale: MAP_MIN_SCALE, maxScale: MAP_MAX_SCALE });
      ox = r.ox; oy = r.oy; scale = r.scale;
    }
    if (Math.abs(scale - s0) > 1e-9) throw new Error(`scale ${scale} != ${s0}`);
    if (Math.abs(ox - o0) > 1e-6 || Math.abs(oy - y0) > 1e-6) throw new Error("offset drift");
    return { scale, ox, oy };
  });

  run("deltaY0_and_bad_factor", () => {
    const base = { ox: 10, oy: 20, scale: 1.5, px: 100, py: 100, minScale: MAP_MIN_SCALE, maxScale: MAP_MAX_SCALE };
    for (const factor of [0, -1, NaN, Infinity]) {
      const r = computeZoomAt({ ...base, factor });
      if (r.ok || r.scale !== base.scale) throw new Error(`factor=${factor}`);
    }
    // MapView wheel with deltaY=0
    const sc0 = map.scale;
    map._onWheel({ deltaY: 0, deltaMode: 0, preventDefault() {}, stopPropagation() {}, clientX: 0, clientY: 0 });
    if (map.scale !== sc0) throw new Error("deltaY=0 changed scale");
    return {};
  });

  run("clamp_limits", () => {
    let r = computeZoomAt({
      ox: 0, oy: 0, scale: MAP_MAX_SCALE * 0.9, px: 100, py: 100,
      factor: 100, minScale: MAP_MIN_SCALE, maxScale: MAP_MAX_SCALE,
    });
    if (!r.ok || r.scale !== MAP_MAX_SCALE) throw new Error(`max ${r.scale}`);
    r = computeZoomAt({
      ox: 0, oy: 0, scale: MAP_MIN_SCALE * 1.1, px: 100, py: 100,
      factor: 1e-12, minScale: MAP_MIN_SCALE, maxScale: MAP_MAX_SCALE,
    });
    if (!r.ok || r.scale !== MAP_MIN_SCALE) throw new Error(`min ${r.scale}`);
    return { max: MAP_MAX_SCALE, min: MAP_MIN_SCALE };
  });

  run("css_dpr_event_xy", () => {
    const cv = map.cv;
    const rect = cv.getBoundingClientRect();
    // Fake a client coordinate at CSS center and compare buffer mapping
    const e = { clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
    const xy = map._eventXY(e);
    const expectedX = (cv.width / 2);
    const expectedY = (cv.height / 2);
    const err = Math.hypot(xy.x - expectedX, xy.y - expectedY);
    if (err > 2) throw new Error(`eventXY center err=${err} got=${xy.x},${xy.y} exp=${expectedX},${expectedY}`);
    return { err, cssW: rect.width, bufW: cv.width, dpr: window.devicePixelRatio };
  });

  run("legacy_bug_repro_baseline", () => {
    let scale = 1.2, ox = 600, oy = 400;
    const wx = (800 - ox) / scale, wy = (oy - 250) / scale;
    for (let i = 0; i < 15; i++) scale *= 1.1;
    const sx = ox + wx * scale, sy = oy - wy * scale;
    if (!(sx > 1200 || sy < 0 || sx < 0 || sy > 800)) throw new Error("legacy should drift out");
    return { afterScreen: [sx, sy] };
  });

  return {
    generatedAt: new Date().toISOString(),
    cases,
    pass: cases.every((c) => c.ok),
    failCount: cases.filter((c) => !c.ok).length,
  };
});

await browser.close();
fs.writeFileSync(path.join(OUT, "zoom_unit_results.json"), JSON.stringify(summary, null, 2));
console.log(JSON.stringify({ pass: summary.pass, failCount: summary.failCount, n: summary.cases.length }, null, 2));
if (!summary.pass) {
  console.error(summary.cases.filter((c) => !c.ok));
  process.exit(1);
}
console.log("ZOOM_UNIT_OK");
