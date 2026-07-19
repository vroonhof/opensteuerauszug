// End-to-end smoke test for the standalone web app (dist/web/opensteuerauszug.html).
//
// Boots the built page in headless Chromium, waits for the Pyodide engine,
// uploads the IBKR + Kursliste samples, runs the pipeline, and checks that a
// PDF/XML download is produced.  It also fails if the page contacts any host
// other than its own origin and the pinned Pyodide CDN — the wheel-embedding
// build (scripts/build_web_app.py) exists precisely so that no PyPI request
// happens at runtime, and so that dependencies the build machine never saw
// (e.g. via emscripten-only markers) cannot sneak in unnoticed.
//
// Usage:  npm install playwright && npx playwright install chromium
//         python scripts/build_web_app.py
//         node scripts/web_app_smoke_test.js
const http = require("http");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const REPO = path.dirname(__dirname);
const HTML = REPO + "/dist/web/opensteuerauszug.html";

async function poll(page, deadline, fn, what) {
  let last = "";
  while (Date.now() < deadline) {
    const r = await fn();
    if (r.log && r.log !== last) { console.log(r.log); last = r.log; }
    if (r.done) return r;
    await new Promise((s) => setTimeout(s, 2000));
  }
  throw new Error("timed out waiting for " + what);
}

(async () => {
  const server = http.createServer((req, res) => {
    res.setHeader("Content-Type", "text/html");
    fs.createReadStream(HTML).pipe(res);
  }).listen(0);
  await new Promise((r) => server.once("listening", r));
  const url = `http://127.0.0.1:${server.address().port}/`;

  const browser = await chromium.launch();
  const page = await browser.newPage();
  page.on("console", (m) => {
    if (m.type() === "error") console.log("[console.error]", m.text().slice(0, 300));
  });
  const badHosts = new Set();
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (!u.protocol.startsWith("http")) return; // blob:/data: are page-internal
    if (u.host !== new URL(url).host && u.host !== "cdn.jsdelivr.net") badHosts.add(u.host);
  });
  await page.goto(url);

  // 1. Wait for the Python engine.
  await poll(page, Date.now() + 8 * 60 * 1000, async () => {
    const s = await page.evaluate(() => {
      const t = (id) => (document.getElementById(id) || {}).textContent || "";
      const c = (id) => (document.getElementById(id) || {}).className || "";
      return { pill: c("enginePill"), detail: t("engineDetail"), err: t("engineErrorBox") };
    });
    if (s.pill.includes("error")) throw new Error("engine error: " + s.detail + "\n" + s.err);
    return { done: s.pill.includes("ready"), log: s.detail };
  }, "engine ready");
  console.log("engine ready");

  // 2. Upload samples and go to the Generate step.
  await page.setInputFiles("#fileKursliste", [REPO + "/tests/samples/kursliste/kursliste_mini_2025.xml"]);
  await page.setInputFiles("#fileBroker", [REPO + "/tests/samples/import/ibkr/vtandchill_2025.xml"]);
  await page.evaluate(() => go(4));

  // 3. Run.
  await poll(page, Date.now() + 60 * 1000, async () => {
    const s = await page.evaluate(() => ({
      disabled: document.getElementById("btnRun").disabled,
      blockers: document.getElementById("runBlockers").textContent,
    }));
    return { done: !s.disabled, log: s.disabled ? "run blocked: " + s.blockers.replace(/\s+/g, " ").slice(0, 200) : "" };
  }, "run button enabled");
  await page.click("#btnRun");
  console.log("run started");

  const res = await poll(page, Date.now() + 6 * 60 * 1000, async () => {
    const s = await page.evaluate(() => ({
      running: document.getElementById("runStatus").style.display !== "none",
      log: document.getElementById("runLog").textContent,
      downloads: Array.from(document.querySelectorAll("#downloads a")).map((a) => a.textContent.trim()),
    }));
    const lines = s.log.trim().split("\n");
    return { done: !s.running && s.log.length > 0, log: lines[lines.length - 1], s };
  }, "pipeline run");

  const log = res.s.log;
  const ok = log.includes("Processing finished successfully.") && res.s.downloads.length > 0;
  console.log("downloads offered:", JSON.stringify(res.s.downloads));
  if (!ok) {
    console.log("--- last 40 log lines ---");
    console.log(log.trim().split("\n").slice(-40).join("\n"));
    console.log("SMOKE TEST FAILED");
    await browser.close(); server.close(); process.exit(1);
  }
  if (badHosts.size) {
    console.log("SMOKE TEST FAILED: unexpected network hosts contacted:", [...badHosts].join(", "));
    await browser.close(); server.close(); process.exit(1);
  }
  console.log("network check passed: only the page origin and cdn.jsdelivr.net were contacted");
  console.log("SMOKE TEST PASSED: pipeline ran in-browser and produced downloads");
  await browser.close(); server.close(); process.exit(0);
})().catch((e) => { console.log("SMOKE TEST FAILED:", e.message); process.exit(1); });
