/*
 * Browser smoke test for the standalone web app.
 *
 * Drives the whole wizard in headless Chromium against the *mock* Pyodide
 * runtime (web/dev/mock_pyodide.js), so it verifies the UI flow, the worker
 * protocol, file plumbing, settings persistence and download generation —
 * everything except Pyodide itself.  The Python pipeline is covered natively
 * by pytest (tests/util/test_web_runner.py).
 *
 * Usage (requires Node + playwright with a Chromium install):
 *   python scripts/build_web_app.py --output dist/web/opensteuerauszug.html
 *   node web/dev/e2e_smoke.mjs dist/web/opensteuerauszug.html
 */
import http from "node:http";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

// Resolve playwright from the local project, NODE_PATH, or a global install.
const require = createRequire(import.meta.url);
const { chromium } = (() => {
  const candidates = ["playwright", process.env.PLAYWRIGHT_MODULE].filter(Boolean);
  for (const candidate of candidates) {
    try { return require(candidate); } catch (e) { /* try next */ }
  }
  throw new Error("playwright not found — `npm install playwright` or set PLAYWRIGHT_MODULE");
})();

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..", "..");
const appHtml = path.resolve(process.argv[2] || "dist/web/opensteuerauszug.html");

const SAMPLE_BROKER = path.join(repoRoot, "tests/samples/import/ibkr/vtandchill_2025.xml");
const SAMPLE_KURSLISTE = path.join(repoRoot, "tests/samples/kursliste/kursliste_mini_2025.xml");

function fail(msg) {
  console.error("FAIL: " + msg);
  process.exit(1);
}
function ok(msg) {
  console.log("ok - " + msg);
}

// -- tiny static server ------------------------------------------------------
const routes = {
  "/app.html": { file: appHtml, type: "text/html; charset=utf-8" },
  "/mock/pyodide.js": { file: path.join(here, "mock_pyodide.js"), type: "text/javascript" },
};
const server = http.createServer(async (req, res) => {
  const route = routes[req.url.split("?")[0]];
  if (!route) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { "content-type": route.type });
  res.end(await readFile(route.file));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;
const url = `${base}/app.html?pyodide=${encodeURIComponent(base + "/mock/")}`;

const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  page.on("pageerror", (err) => fail("page error: " + err));
  await page.goto(url);

  // Step 1: disclaimer must gate the wizard.
  if (!(await page.locator("#btnStart").isDisabled())) fail("start not gated on disclaimer");
  await page.check("#ack");
  await page.click("#btnStart");
  ok("disclaimer gate");

  // Step 2: settings.
  await page.fill("#fullName", "Maxine Muster");
  await page.selectOption("#canton", "ZH");
  await page.fill("#taxYear", "2025");
  await page.selectOption("#importer", "ibkr");
  await page.locator("#fullName").blur();
  const toml = await page.inputValue("#tomlText");
  if (!toml.includes('full_name = "Maxine Muster"')) fail("generated TOML missing name:\n" + toml);
  ok("settings form generates config.toml");
  await page.click('section[data-step="1"] [data-nav="next"]');

  // Step 3: kursliste upload.
  await page.setInputFiles("#fileKursliste", SAMPLE_KURSLISTE);
  await page.waitForSelector("#listKursliste li");
  ok("kursliste added");
  await page.click('section[data-step="2"] [data-nav="next"]');

  // Step 4: broker file upload.
  await page.setInputFiles("#fileBroker", SAMPLE_BROKER);
  await page.waitForSelector("#listBroker li");
  ok("broker file added");
  await page.click('section[data-step="3"] [data-nav="next"]');

  // Step 5: wait for the (mock) engine, then run.
  await page.waitForSelector("#enginePill.ready", { timeout: 30000 });
  ok("engine ready");
  await page.waitForSelector("#btnRun:not([disabled])");
  await page.click("#btnRun");

  // Step 6: results.
  await page.waitForSelector('section[data-step="5"].active', { timeout: 30000 });
  const links = page.locator("#downloads a.dlbtn");
  if ((await links.count()) !== 2) fail("expected 2 download links");
  const pdfName = await links.first().getAttribute("download");
  if (pdfName !== "steuerauszug_2025.pdf") fail("bad pdf download name: " + pdfName);
  const log = await page.textContent("#resultLog");
  if (!log.includes("MOCK inputs: vtandchill_2025.xml")) fail("broker file did not reach engine:\n" + log);
  if (!log.includes("MOCK converted kursliste_mini_2025.xml -> kursliste_2025.sqlite"))
    fail("kursliste XML was not converted:\n" + log);
  if (!log.includes("MOCK kursliste: kursliste_2025.sqlite"))
    fail("pipeline did not receive the converted kursliste:\n" + log);
  if (!log.includes('full_name = "Maxine Muster"')) fail("config did not reach engine:\n" + log);
  ok("pipeline received files + config, downloads offered");

  // The converted sqlite must replace the XML in the kursliste list (and cache).
  const klName = await page.locator("#listKursliste li .name").textContent();
  if (!klName.includes("kursliste_2025.sqlite"))
    fail("converted sqlite did not replace the XML in the list: " + klName);
  ok("converted kursliste replaces the XML");

  // Download really contains the produced bytes.
  const [download] = await Promise.all([page.waitForEvent("download"), links.first().click()]);
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const c of stream) chunks.push(c);
  if (!Buffer.concat(chunks).toString().startsWith("%PDF")) fail("downloaded PDF has wrong content");
  ok("PDF download contains engine output");

  // Persistence: settings (localStorage) and kursliste (IndexedDB) survive reload.
  await page.reload();
  await page.waitForSelector("#enginePill");
  if ((await page.inputValue("#fullName")) !== "Maxine Muster") fail("settings not persisted");
  // The list lives in a not-yet-visible step section, so wait for attachment.
  await page.waitForSelector("#listKursliste li", { state: "attached", timeout: 10000 });
  const cached = await page.locator("#listKursliste li .meta").textContent();
  if (!cached.includes("cached")) fail("kursliste not restored from IndexedDB");
  const cachedName = await page.locator("#listKursliste li .name").textContent();
  if (!cachedName.includes("kursliste_2025.sqlite"))
    fail("cache should hold the converted sqlite, got: " + cachedName);
  ok("settings + converted kursliste persist across reload");

  console.log("\nAll web app smoke tests passed.");
} finally {
  await browser.close();
  server.close();
}
