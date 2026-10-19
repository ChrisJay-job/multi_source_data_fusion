/**
 * TASK-003 real browser assertions: seven defaults, layout, canvas draw cmds, anomalies.
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.WORKBENCH_URL || "http://127.0.0.1:18089";
const OUT = path.resolve("reports/task003/browser");
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

async function runViewport(width, height) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width, height } });
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(String(e)));
  const drawLog = [];
  await page.addInitScript(() => {
    window.__drawCmds = [];
    const wrap = (proto, name, tag) => {
      const orig = proto[name];
      proto[name] = function (...args) {
        try {
          window.__drawCmds.push({ tag, n: args?.length });
        } catch (_) {}
        return orig.apply(this, args);
      };
    };
    // patch after canvas module loads — also expose helper
    window.__wbCaptureDraw = () => {
      const c = document.getElementById("cv");
      if (!c || c.__patched) return;
      c.__patched = true;
      const ctx = c.getContext("2d");
      const p = Object.getPrototypeOf(ctx);
      ["stroke", "fill", "fillText", "beginPath"].forEach((fn) => {
        const orig = p[fn];
        p[fn] = function (...a) {
          window.__drawCmds.push({ fn, t: Date.now() });
          return orig.apply(this, a);
        };
      });
    };
  });

  try {
    await page.goto(BASE + "/", { waitUntil: "networkidle", timeout: 90000 });
    await page.click("#btnHealth");
    await page.waitForTimeout(400);
    assert(`ready_${width}`, (await page.textContent("#svcStatus") || "").includes("ready"));

    // seven aircraft list
    await page.waitForSelector("#acList li.ac-item", { timeout: 15000 });
    const nAc = await page.locator("#acList li.ac-item").count();
    assert(`default_seven_${width}`, nAc === 7, `n=${nAc}`);

    const overflow = await page.evaluate(() => {
      const de = document.documentElement;
      return { scrollWidth: de.scrollWidth, clientWidth: de.clientWidth, bodyScroll: document.body.scrollWidth };
    });
    assert(
      `no_h_overflow_${width}`,
      overflow.scrollWidth <= overflow.clientWidth + 2,
      JSON.stringify(overflow)
    );

    // edit only G
    const g = page.locator("#acList li.ac-item").filter({ hasText: /^G\b|G ·|G（/ }).first();
    if ((await g.count()) === 0) {
      await page.locator("#acList li.ac-item").nth(6).click();
    } else {
      await g.click();
    }
    await page.waitForTimeout(200);
    await page.click('.dtab[data-tab="basic"]');
    const speedBefore = await page.locator('#tabBasic input[data-f="speed_mps"]').inputValue().catch(() => null);
    if (speedBefore != null) {
      await page.fill('#tabBasic input[data-f="speed_mps"]', "13");
    }
    // canvas route: add point if route tab supports
    await page.click('.dtab[data-tab="route"]');
    await page.waitForTimeout(100);
    const addBtn = page.locator("#btnRouteAdd");
    if (await addBtn.count()) {
      await addBtn.click();
      const box = await page.locator("#cv").boundingBox();
      if (box) {
        await page.mouse.click(box.x + box.width * 0.4, box.y + box.height * 0.4);
        await page.mouse.click(box.x + box.width * 0.55, box.y + box.height * 0.42);
      }
      const done = page.locator("#btnRouteDone");
      if (await done.count()) await done.click();
    }
    note(`edit_g_${width}`, `speedBefore=${speedBefore}`);

    await page.evaluate(() => window.__wbCaptureDraw && window.__wbCaptureDraw());
    await page.click("#btnRunSim");
    await page.waitForFunction(() => (window.__wb?.runState?.snapshots?.length || 0) > 5, { timeout: 120000 });
    await page.waitForTimeout(500);

    // fused-only layers
    await page.evaluate(() => {
      document.querySelectorAll(".layer").forEach((c) => {
        const L = c.dataset.layer;
        c.checked = L === "fused" || L === "current";
        c.dispatchEvent(new Event("change", { bubbles: true }));
      });
    });
    await page.waitForTimeout(300);
    const drawAfter = await page.evaluate(() => (window.__drawCmds || []).length);
    assert(`draw_cmds_fused_${width}`, drawAfter > 0, `cmds=${drawAfter}`);

    // seek via anomaly if any
    const anomaly = page.locator("#anomalyList button, #anomalyList .anomaly, #resultAnomalies button").first();
    if (await anomaly.count()) {
      await anomaly.click();
      await page.waitForTimeout(200);
      note(`anomaly_click_${width}`, "clicked");
    } else {
      note(`anomaly_click_${width}`, "none");
    }

    // reset seven
    page.once("dialog", (d) => d.accept());
    await page.click("#btnResetSeven");
    await page.waitForTimeout(500);
    const n2 = await page.locator("#acList li.ac-item").count();
    assert(`reset_seven_${width}`, n2 === 7, `n=${n2}`);

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
fs.writeFileSync(path.join(OUT, "browser_evidence.json"), JSON.stringify({ steps, results }, null, 2));
console.log("DONE", OUT);
