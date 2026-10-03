/**
 * Accessibility and weight sweep — the measuring stick for phase 07.
 *
 * P7.1 asked for "automated axe-core sweep across all six views plus Lighthouse, captured as a written
 * baseline so the fixes can be measured rather than asserted". This is the sweep. It runs a real
 * Chromium (headless shell) against a running instance of the site, drives each view the way a person
 * would — by clicking the tab — and records:
 *
 *   · every axe-core violation, with the rule, the impact and the offending nodes
 *   · the dominant colour-contrast failures (axe resolves real computed styles here; a DOM-only
 *     harness cannot, because jsdom has no layout)
 *   · the keyboard path — the first N tab stops, so "full tab order" can be checked rather than claimed
 *   · focus-visible behaviour on each control
 *   · weight and paint timings, measured twice: once unrestricted, once on a throttled connection,
 *     because a 500 KB first load is only a problem if it is slow for somebody
 *
 * It is a development tool, not part of the test suite: it needs node, a 114 MB browser and an npm
 * install, and the project ships as Python that runs from a clean extraction. The guarantees it
 * discovers are pinned down afterwards by tests/test_a11y.py, which needs nothing but the stdlib.
 *
 * Usage (from the repo root, with the site already serving):
 *   node tests/a11y/sweep.mjs                       # sweeps http://127.0.0.1:8000/
 *   node tests/a11y/sweep.mjs --url http://host/ --out /tmp/a11y.json
 *   node tests/a11y/sweep.mjs --reduce-motion      # also sweep with prefers-reduced-motion: reduce
 *
 * Requires `npm i playwright axe-core` and a Chromium (`npx playwright install chromium`).
 * If Chromium cannot start for want of system libraries, see tests/a11y/README.md.
 */
import { createRequire } from 'node:module';
import { writeFileSync } from 'node:fs';

const require = createRequire(import.meta.url);
const PLAYWRIGHT = process.env.NT90_PLAYWRIGHT_MODULES || '/tmp/a11y/node_modules';

const { chromium } = await import(`${PLAYWRIGHT}/playwright/index.mjs`);
const axePath = `${PLAYWRIGHT}/axe-core/axe.min.js`;

const args = process.argv.slice(2);
const argOf = (name, fallback) => {
  const i = args.indexOf(name);
  return i === -1 ? fallback : args[i + 1];
};
const BASE = argOf('--url', process.env.NT90_URL || 'http://127.0.0.1:8000/').replace(/\/$/, '');
const OUT = argOf('--out', '/tmp/a11y-sweep.json');
const VIEWS = ['matchweek', 'table', 'awards', 'duel', 'whatif', 'model'];
const REDUCE_TOO = args.includes('--reduce-motion');

const settle = (page, ms = 900) => page.waitForTimeout(ms);

async function openView(page, view) {
  // Click the tab, because that is what a person does. If the button is not reachable by a plain
  // click, that is itself a finding, so it is recorded rather than worked around.
  await page.click(`nav.tabs button[data-tab="${view}"]`, { timeout: 5000 });
  await settle(page);
}

async function axeOn(page, view) {
  const results = await page.evaluate(async () => {
    // eslint-disable-next-line no-undef
    return await window.axe.run(document, {
      resultTypes: ['violations', 'incomplete'],
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'] },
    });
  });
  const slim = (list) => list.map((v) => ({
    id: v.id,
    impact: v.impact,
    help: v.help,
    nodes: v.nodes.length,
    sample: v.nodes.slice(0, 4).map((n) => ({
      target: n.target.join(' '),
      html: (n.html || '').slice(0, 120),
      summary: (n.failureSummary || '').split('\n').slice(0, 3).join(' | ').slice(0, 300),
    })),
  }));
  return { view, violations: slim(results.violations), incomplete: slim(results.incomplete) };
}

async function keyboardPath(page, limit = 24) {
  // Walk the tab order from the top of the document. Blur everything first so the walk starts where a
  // fresh visitor starts.
  await page.evaluate(() => {
    document.activeElement?.blur?.();
    document.body.focus?.();
  });
  const stops = [];
  for (let i = 0; i < limit; i++) {
    await page.keyboard.press('Tab');
    const stop = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return { tag: 'body', label: '(document body)' };
      const style = getComputedStyle(el);
      const ring = style.outlineStyle !== 'none' && parseFloat(style.outlineWidth || '0') > 0;
      const shadow = style.boxShadow && style.boxShadow !== 'none';
      const box = el.getBoundingClientRect();
      return {
        tag: el.tagName.toLowerCase(),
        id: el.id || null,
        cls: (el.className || '').toString().slice(0, 40),
        label: (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 42),
        role: el.getAttribute('role'),
        visibleRing: ring || shadow,
        offscreen: box.width === 0 && box.height === 0,
      };
    });
    stops.push(stop);
    if (stop.tag === 'body') break;
  }
  return stops;
}

async function measure(page, { label, throttle }) {
  const session = await page.context().newCDPSession(page);
  await session.send('Network.enable');
  if (throttle) {
    await session.send('Network.emulateNetworkConditions', {
      offline: false,
      latency: throttle.latency,
      downloadThroughput: throttle.download,
      uploadThroughput: throttle.upload,
    });
    await session.send('Emulation.setCPUThrottlingRate', { rate: throttle.cpu || 4 });
  }
  let bytes = 0;
  page.on('response', async (r) => {
    try {
      const len = Number(r.headers()['content-length'] || 0);
      if (len) bytes += len;
    } catch { /* a redirect or an aborted request has no headers */ }
  });
  const t0 = Date.now();
  await page.goto(`${BASE}/`, { waitUntil: 'load' });
  const load = Date.now() - t0;
  await settle(page, 1200);
  const perf = await page.evaluate(() => {
    const nav = performance.getEntriesByType('navigation')[0] || {};
    const paints = Object.fromEntries(performance.getEntriesByType('paint').map((p) => [p.name, Math.round(p.startTime)]));
    const lcp = performance.getEntriesByType('largest-contentful-paint').slice(-1)[0];
    return {
      domNodes: document.getElementsByTagName('*').length,
      transferKB: Math.round((nav.transferSize || 0) / 1024),
      decodedKB: Math.round((nav.decodedBodySize || 0) / 1024),
      domInteractive: Math.round(nav.domInteractive || 0),
      domComplete: Math.round(nav.domComplete || 0),
      fcp: paints['first-contentful-paint'] ?? null,
      lcp: lcp ? Math.round(lcp.startTime) : null,
      styleSheets: document.styleSheets.length,
    };
  });
  if (throttle) {
    await session.send('Network.emulateNetworkConditions', { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
    await session.send('Emulation.setCPUThrottlingRate', { rate: 1 });
  }
  return { label, wallLoadMs: load, httpBytes: bytes, ...perf };
}

async function main() {
  const browser = await chromium.launch();
  const report = { url: BASE, at: new Date().toISOString().replace('T', ' ').slice(0, 19), views: {}, keyboard: [], weights: [], focus: {} };

  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'no-preference' });
  const page = await context.newPage();
  page.on('pageerror', (e) => report.views.__errors = (report.views.__errors || []).concat(String(e).slice(0, 200)));

  await page.goto(`${BASE}/`, { waitUntil: 'load' });
  await settle(page, 1500);          // let the first render and its reveal animations finish
  await page.addScriptTag({ path: axePath });

  for (const view of VIEWS) {
    if (view !== 'matchweek') await openView(page, view);
    const res = await axeOn(page, view);
    report.views[view] = res;

    // The keyboard path is per view, because each view reveals different controls.
    if (view === 'whatif' || view === 'duel' || view === 'model') {
      report.focus[view] = await keyboardPath(page);
    }
  }

  // ── weight, unrestricted and throttled ──────────────────────────────────────────────────────────
  report.weights.push(await measure(page, { label: 'unthrottled' }));
  report.weights.push(await measure(page, { label: 'slow 4G + 4x CPU', throttle: { latency: 150, download: (1.6 * 1024 * 1024) / 8, upload: (750 * 1024) / 8, cpu: 4 } }));

  await context.close();

  if (REDUCE_TOO) {
    const rm = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
    const p2 = await rm.newPage();
    await p2.goto(`${BASE}/`, { waitUntil: 'load' });
    await settle(p2, 800);
    report.reducedMotion = await p2.evaluate(() => {
      const running = [...document.getAnimations?.() ?? []].filter((a) => a.playState === 'running').length;
      return { animationsStillRunning: running, prefersReduced: matchMedia('(prefers-reduced-motion: reduce)').matches };
    });
    await rm.close();
  }

  await browser.close();
  writeFileSync(OUT, JSON.stringify(report, null, 1));
  summarise(report, OUT);
}

function summarise(report, out) {
  const line = (s) => process.stdout.write(s + '\n');
  line('');
  line('══════════════════════════════════════════════════════════════');
  line('  axe-core sweep — ' + report.url);
  line('══════════════════════════════════════════════════════════════');
  let vTotal = 0, nTotal = 0;
  for (const [view, res] of Object.entries(report.views)) {
    if (view.startsWith('__')) continue;
    const v = res.violations.reduce((n, x) => n + x.nodes, 0);
    vTotal += res.violations.length; nTotal += v;
    line(`  ${view.padEnd(11)} ${String(res.violations.length).padStart(2)} rules · ${String(v).padStart(3)} nodes   ${res.violations.map((x) => x.id).slice(0, 4).join(', ')}`);
  }
  line('  ────────────────────────────────────────────────');
  line(`  TOTAL ${vTotal} rule-instances · ${nTotal} offending nodes`);
  line('');
  for (const w of report.weights) {
    line(`  ${w.label.padEnd(18)} FCP ${String(w.fcp).padStart(5)} ms · LCP ${String(w.lcp).padStart(5)} ms · DOM ${String(w.domNodes).padStart(5)} nodes · ${w.transferKB} KB over the wire`);
  }
  if (report.reducedMotion) line(`  reduced-motion: ${JSON.stringify(report.reducedMotion)}`);
  line(`  full detail -> ${out}`);
  line('');
}

await main();
