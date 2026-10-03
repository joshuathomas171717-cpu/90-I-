/* The What-If scenario XSS probe (dev-only, like its neighbours in this folder).
 *
 * Why this file exists: the scenario form was exploitable and the code looked fine. `esc()` was being
 * applied to every *name* it printed, which is exactly what a reviewer checks — but the numeric-
 * looking fields (slider `value`, `aria-valuetext`, the `.val` spans) were interpolated raw, and a
 * share link, a duel URL parameter or a saved scenario could all carry markup into them. Reading the
 * source did not reveal it; putting `<img src=x onerror=...>` through a real browser did.
 *
 * So this attacks the built page the way an attacker would, from every entry point that accepts
 * outside data, and reports what executed. It is not part of `python3 tests/run_tests.py`: the suite
 * is stdlib-only Python and this needs node plus a browser. Run it by hand before shipping a change
 * to scenario handling.
 *
 *   python3 tools/setup_browser_tools.sh          # once per machine, ~30s
 *   export LD_LIBRARY_PATH=/tmp/chromelibs/usr/lib/x86_64-linux-gnu
 *   export NT90_PLAYWRIGHT_MODULES=/tmp/a11y/node_modules
 *   cd static && python3 -m http.server 8950 &
 *   NT90_BASE=http://127.0.0.1:8950 node tests/a11y/xss.mjs
 *
 * Exits non-zero if any payload executes, injects a node, or is echoed raw.
 */
import { createRequire } from "module";

const require = createRequire(import.meta.url);
const mods = process.env.NT90_PLAYWRIGHT_MODULES;
const { chromium } = mods ? require(mods + "/playwright") : await import("playwright");

const BASE = process.env.NT90_BASE || "http://127.0.0.1:8000";
const PAYLOAD = '<img src=x onerror="window.__pwned=1">';

/** base64url, the way a share link carries a scenario. */
const token = (obj) => Buffer.from(JSON.stringify(obj)).toString("base64url");

/** Each case: a name, the URL to open, and what the attacker is trying to reach. */
const CASES = [
  ["team_boost value",   "/whatif#s=" + token({ b: { ARS: [PAYLOAD, 0] } })],
  ["team_boost defence", "/whatif#s=" + token({ b: { ARS: [0, PAYLOAD] } })],
  ["points_deduction",   "/whatif#s=" + token({ d: { MCI: PAYLOAD } })],
  ["injury value",       "/whatif#s=" + token({ i: { haaland: PAYLOAD } })],
  ["injury key",         "/whatif#s=" + token({ i: { [PAYLOAD]: 5 } })],
  ["custom_score",       "/whatif#s=" + token({ c: { [PAYLOAD]: [PAYLOAD, 3] } })],
  ["versioned link",     "/whatif#s=v1-" + token({ b: { ARS: [PAYLOAD, 0] } })],
  ["duel parameter",     "/duel?h=" + encodeURIComponent(PAYLOAD) + "&a=ARS"],
  ["club slug",          "/club/" + encodeURIComponent(PAYLOAD)],
];

const browser = await chromium.launch();
let failures = 0;

for (const [name, path] of CASES) {
  const page = await (await browser.newContext()).newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 80)));
  await page.goto(BASE + path, { waitUntil: "load" });
  await page.waitForTimeout(1800);
  const probe = await page.evaluate(() => ({
    executed: !!window.__pwned,
    polluted: ({}).polluted !== undefined || Object.prototype.polluted !== undefined,
    injectedImg: document.querySelectorAll('img[src="x"]').length,
    // Live attributes on live elements. Deliberately *not* a text scan of innerHTML: that includes
    // the page's own inline script and its comments, one of which discusses the very payload being
    // tested, so a text search reports a vulnerability that is not there.
    liveHandlers: document.querySelectorAll("[onerror], [onload], [onmouseover]").length,
    toast: (document.querySelector("#toast, .toast")?.textContent || "").trim().slice(0, 40),
  }));
  const bad = probe.executed || probe.polluted || probe.injectedImg > 0 || probe.liveHandlers > 0;
  if (bad) failures++;
  const verdict = (bad ? "VULNERABLE" : "ok").padEnd(11);
  const counts = "exec=" + (+probe.executed) + " proto=" + (+probe.polluted)
    + " injectedImg=" + probe.injectedImg + " liveHandlers=" + probe.liveHandlers;
  console.log("  " + verdict + name.padEnd(19) + counts + "  " + (probe.toast || errors[0] || ""));
  await page.close();
}

/* A payload planted straight into storage, the way an older build or a shared machine could. */
{
  const page = await (await browser.newContext()).newPage();
  await page.goto(BASE + "/whatif", { waitUntil: "load" });
  await page.waitForTimeout(1200);
  await page.evaluate((pay) => {
    localStorage.setItem("nt90:state", JSON.stringify({ v: 2, created: new Date().toISOString(),
      data: { favourites: [], lastView: "whatif", scenarios: [{ id: "sx", name: "evil",
        saved: new Date().toISOString(), scenario: {
          player_injuries: { haaland: pay }, team_boosts: { ARS: [pay, 0] },
          points_deductions: { MCI: pay }, custom_scores: { "MCI-LIV": [pay, pay] } } }] } }));
  }, PAYLOAD);
  await page.reload({ waitUntil: "load" });
  await page.waitForTimeout(1500);
  const load = page.locator("[data-load]").first();
  if (await load.count()) { await load.click(); await page.waitForTimeout(2000); }
  const probe = await page.evaluate(() => ({
    executed: !!window.__pwned,
    injectedImg: document.querySelectorAll('img[src="x"]').length,
    liveHandlers: document.querySelectorAll("[onerror], [onload]").length,
    inForm: document.querySelectorAll("#tab-whatif [value*='<']").length,
  }));
  const bad = probe.executed || probe.injectedImg > 0 || probe.liveHandlers > 0 || probe.inForm > 0;
  if (bad) failures++;
  console.log("  " + (bad ? "VULNERABLE" : "ok").padEnd(11) + "saved scenario".padEnd(19)
    + "exec=" + (+probe.executed) + " injectedImg=" + probe.injectedImg
    + " liveHandlers=" + probe.liveHandlers + " markup in form=" + probe.inForm);
  await page.close();
}

/* And the other half of the contract: a legitimate link has to keep working. A sanitiser that also
   eats valid input is a regression the attack cases above would happily call "safe". */
{
  const page = await (await browser.newContext()).newPage();
  await page.goto(BASE + "/whatif", { waitUntil: "load" });
  await page.waitForTimeout(1500);
  const url = await page.evaluate(() => {
    SCENARIO.player_injuries = { haaland: 8, saka: 4 };
    SCENARIO.team_boosts = { ARS: { attack: 12, defence: -5 } };
    SCENARIO.points_deductions = { MCI: 10 };
    SCENARIO.custom_scores = { "MCI-LIV": [2, 1] };
    return NT90_SHARE.scenarioUrl(SCENARIO);
  });
  const back = await (await browser.newContext()).newPage();
  await back.goto(url, { waitUntil: "load" });
  await back.waitForTimeout(2000);
  const got = await back.evaluate(() => JSON.parse(JSON.stringify(SCENARIO)));
  const survived = got.player_injuries.haaland === 8 && got.player_injuries.saka === 4
    && got.team_boosts.ARS.attack === 12 && got.team_boosts.ARS.defence === -5
    && got.points_deductions.MCI === 10 && got.custom_scores["MCI-LIV"][0] === 2;
  if (!survived) failures++;
  console.log("  " + (survived ? "ok" : "BROKEN").padEnd(11) + "round trip".padEnd(19)
    + JSON.stringify(got).slice(0, 76));
  await back.close();
}

await browser.close();
console.log(failures ? `\n  ${failures} failing case(s)` : "\n  all cases clean");
process.exit(failures ? 1 : 0);
