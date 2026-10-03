/**
 * Pixel-true contrast and colour-vision audit.
 *
 * Why this exists: axe-core returned `color-contrast` as *incomplete* for 1,385 text nodes, because the
 * design sits on translucent panels over gradients and axe will not guess a background it cannot
 * resolve. "Incomplete" is not a pass, and asserting a pass without measuring it is how contrast bugs
 * survive a redesign. So this measures the actual screen.
 *
 * ── the two passes, and why one is not enough ───────────────────────────────────────────────────
 * Pass 1 screens the whole view from a single full-page screenshot. It is fast and it is wrong below
 * the fold: taking that screenshot can trigger the page's own reveal animations, so the page renders
 * at a different height than the boxes were measured against. That produced a confident false
 * positive in this project — a player's nationality line reported as 1.4:1 against a mint-green bar
 * that was nowhere near it.
 *
 * Pass 2 verifies. Every element pass 1 flags is scrolled into view and measured from a screenshot of
 * its own box, which cannot drift. A random sample of *passing* rows is verified the same way, so the
 * method is proved in both directions and not only where it finds faults. A number in the report is
 * therefore either a verified finding or explicitly marked as unverified.
 *
 * Then it simulates protanopia, deuteranopia and tritanopia over the semantic colours — the green and
 * magenta that carry win/loss and top-four/relegation — because a chart that only says "green" says
 * nothing to a red-green colourblind reader, and no single-pixel check will catch that.
 *
 * Dev tool, like sweep.mjs: needs node, playwright and axe. The project ships as stdlib Python.
 * Usage:
 *   node tests/a11y/contrast.mjs [--url http://127.0.0.1:8000] [--out /tmp/a11y-contrast.json]
 *                                [--sample 40]   # passing rows to verify per view
 */
import { writeFileSync, mkdirSync } from 'node:fs';

const PLAYWRIGHT = process.env.NT90_PLAYWRIGHT_MODULES || '/tmp/a11y/node_modules';
const { chromium } = await import(`${PLAYWRIGHT}/playwright/index.mjs`);

const args = process.argv.slice(2);
const argOf = (n, d) => { const i = args.indexOf(n); return i === -1 ? d : args[i + 1]; };
const BASE = argOf('--url', process.env.NT90_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const OUT = argOf('--out', '/tmp/a11y-contrast.json');
const SAMPLE = Number(argOf('--sample', '40'));
const VIEWS = ['matchweek', 'table', 'awards', 'duel', 'whatif', 'model'];

// ── WCAG 2.1 relative luminance and contrast ─────────────────────────────────────────────────────
const srgb = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
const lum = ([r, g, b]) => 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b);
const contrast = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

// ── colour-vision-deficiency simulation ─────────────────────────────────────────────────────────
const CVD = {
  protanopia: [[0.1706, 0.8473, -0.0179], [0.1314, 0.8112, 0.0574], [0.0050, 0.0873, 0.9077]],
  deuteranopia: [[0.3810, 0.6181, 0.0009], [0.2345, 0.7444, 0.0211], [0.0043, 0.0451, 0.9506]],
  tritanopia: [[0.9595, 0.0642, -0.0237], [-0.0100, 0.8718, 0.1381], [0.0180, 0.1065, 0.8753]],
};
const simulate = (rgb, kind) => CVD[kind].map((row) => Math.max(0, Math.min(255,
  Math.round(row[0] * rgb[0] + row[1] * rgb[1] + row[2] * rgb[2]))));

const hexToRgb = (hex) => {
  const h = String(hex).replace('#', '').trim();
  const s = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
};
const rgbToHex = (c) => {
  const m = String(c).match(/rgba?\(([^)]+)\)/);
  if (!m) return String(c);
  return '#' + m[1].split(',').slice(0, 3).map((v) => Math.round(parseFloat(v)).toString(16).padStart(2, '0')).join('');
};
const thresholdFor = (fontSize, fontWeight) =>
  (fontSize >= 24 || (fontSize >= 18.66 && fontWeight >= 700)) ? 3.0 : 4.5;

async function settleScroll(page) {
  // Tab switches animate `scrollTo({behavior:'smooth'})`, and a measurement taken mid-scroll lands in
  // the wrong place. Pin to the top with smooth scrolling off before every measurement.
  await page.evaluate(() => { document.documentElement.style.scrollBehavior = 'auto'; window.scrollTo(0, 0); });
  await page.waitForFunction(() => window.scrollY === 0, null, { timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(120);
}

async function collectText(page, view) {
  return page.evaluate((view) => {
    const out = [];
    const seen = new Set();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const text = (node.textContent || '').replace(/\s+/g, ' ').trim();
      if (text.length < 2) continue;
      const el = node.parentElement;
      if (!el || seen.has(el)) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) < 0.35) continue;
      if (el.closest('[aria-hidden="true"]')) continue;
      // A child of a `display:none` section still reports its own display as `block`, so an element
      // check alone lets hidden views through — and a hidden view has stale coordinates.
      if (el.checkVisibility && !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
      if (el.offsetParent === null && cs.position !== 'fixed') continue;
      // background-clip:text takes the glyph colour from a gradient, so the computed colour is not
      // what the eye sees; those are skipped rather than reported wrongly.
      if (cs.webkitBackgroundClip === 'text' || cs.backgroundClip === 'text') continue;
      const box = el.getBoundingClientRect();
      if (box.width < 4 || box.height < 4) continue;
      seen.add(el);
      const i = out.length;
      el.dataset.nt90i = String(i);
      out.push({
        i, view, text: text.slice(0, 48),
        html: el.outerHTML.replace(/\s+/g, ' ').slice(0, 150),
        cls: (el.className || '').toString().slice(0, 48),
        id: el.id || null,
        color: cs.color,
        fontSize: Math.round(parseFloat(cs.fontSize) * 10) / 10,
        fontWeight: parseInt(cs.fontWeight, 10) || 400,
        x: Math.round(box.left + window.scrollX), y: Math.round(box.top + window.scrollY),
        w: Math.round(box.width), h: Math.round(box.height),
      });
    }
    return out;
  }, view);
}

/** Read the median and mean pixel of a base64 PNG. Median ignores stray glyph/neighbour pixels;
 *  the mean catches a bright band crossing only part of the box. */
async function statsFrom(page, b64) {
  return page.evaluate(async (data) => {
    const img = new Image();
    img.src = 'data:image/png;base64,' + data;
    await img.decode();
    const c = document.createElement('canvas');
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    const ctx = c.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    const px = ctx.getImageData(0, 0, c.width, c.height).data;
    const chans = [[], [], []];
    for (let i = 0; i < px.length; i += 4) {
      if (px[i + 3] < 200) continue;
      chans[0].push(px[i]); chans[1].push(px[i + 1]); chans[2].push(px[i + 2]);
    }
    if (!chans[0].length) return null;
    const median = chans.map((a) => { a.sort((p, q) => p - q); return a[Math.floor(a.length / 2)]; });
    const mean = chans.map((a) => Math.round(a.reduce((s, v) => s + v, 0) / a.length));
    const crop = document.createElement('canvas');
    crop.width = Math.min(300, c.width); crop.height = Math.min(56, c.height);
    crop.getContext('2d').drawImage(c, 0, 0, crop.width, crop.height, 0, 0, crop.width, crop.height);
    return { median, mean, crop: crop.toDataURL('image/png') };
  }, b64);
}

/** Pass 1: one screenshot of the whole view, sampled for every text box. Screening only. */
async function screenView(page, items) {
  await page.evaluate(() => document.getAnimations().forEach((a) => { try { a.pause(); } catch { /* already paused */ } }));
  await page.addStyleTag({ content: 'html.__probe *, html.__probe *::before, html.__probe *::after { color: transparent !important; text-shadow: none !important; }' });
  await page.evaluate(() => document.documentElement.classList.add('__probe'));
  await page.waitForTimeout(120);
  const shot = (await page.screenshot({ fullPage: true, type: 'png' })).toString('base64');
  await page.evaluate(() => document.documentElement.classList.remove('__probe'));

  const sampled = await page.evaluate(async ({ b64, items }) => {
    const img = new Image();
    img.src = 'data:image/png;base64,' + b64;
    await img.decode();
    const c = document.createElement('canvas');
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    const ctx = c.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    const sx = c.width / document.documentElement.scrollWidth;
    const sy = c.height / document.documentElement.scrollHeight;
    const out = [];
    for (const it of items) {
      const x0 = Math.max(0, Math.floor(it.x * sx)), y0 = Math.max(0, Math.floor(it.y * sy));
      const x1 = Math.min(c.width, Math.ceil((it.x + it.w) * sx)), y1 = Math.min(c.height, Math.ceil((it.y + it.h) * sy));
      if (x1 <= x0 || y1 <= y0) { out.push({ i: it.i, unresolved: 'off the captured page' }); continue; }
      const data = ctx.getImageData(x0, y0, x1 - x0, y1 - y0).data;
      const chans = [[], [], []];
      for (let k = 0; k < data.length; k += 4) {
        if (data[k + 3] < 200) continue;
        chans[0].push(data[k]); chans[1].push(data[k + 1]); chans[2].push(data[k + 2]);
      }
      if (!chans[0].length) { out.push({ i: it.i, unresolved: 'no opaque pixels' }); continue; }
      const median = chans.map((a) => { a.sort((p, q) => p - q); return a[Math.floor(a.length / 2)]; });
      const mean = chans.map((a) => Math.round(a.reduce((s, v) => s + v, 0) / a.length));
      out.push({ i: it.i, median, mean });
    }
    return out;
  }, { b64: shot, items });
  return new Map(sampled.map((s) => [s.i, s]));
}

/** Pass 2: scroll one element into view, hide only its glyphs, screenshot only its box. */
async function verifyElement(page, i) {
  const box = await page.evaluate(async (i) => {
    const el = document.querySelector(`[data-nt90i="${i}"]`);
    if (!el) return null;
    el.scrollIntoView({ block: 'center', behavior: 'instant' });
    await new Promise((r) => setTimeout(r, 140));
    el.style.setProperty('color', 'transparent', 'important');
    el.style.setProperty('text-shadow', 'none', 'important');
    const r = el.getBoundingClientRect();
    return { x: Math.max(0, Math.round(r.x) - 1), y: Math.max(0, Math.round(r.y) - 1), width: Math.round(r.width) + 2, height: Math.round(r.height) + 2 };
  }, i);
  if (!box || box.width < 2 || box.height < 2) return null;
  const shot = (await page.screenshot({ clip: box, type: 'png' })).toString('base64');
  const stats = await statsFrom(page, shot);
  await page.evaluate((i) => {
    const el = document.querySelector(`[data-nt90i="${i}"]`);
    if (el) { el.style.removeProperty('color'); el.style.removeProperty('text-shadow'); }
  }, i);
  return stats ? { ...stats, box } : null;
}

async function semanticColours(page) {
  const tokens = await page.evaluate(() => {
    const cs = getComputedStyle(document.documentElement);
    const names = ['--win', '--win-d', '--loss', '--loss-d', '--accent', '--gold', '--violet', '--ink-2', '--ink-3', '--ink-4', '--mid'];
    return Object.fromEntries(names.map((n) => [n, cs.getPropertyValue(n).trim()]));
  });
  const out = {};
  for (const [name, hex] of Object.entries(tokens)) {
    if (!hex || !hex.startsWith('#')) continue;
    const rgb = hexToRgb(hex);
    out[name] = { hex, ...Object.fromEntries(Object.keys(CVD).map((k) => [k, rgbToHex('rgb(' + simulate(rgb, k).join(',') + ')')])) };
  }
  return out;
}

async function main() {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/`, { waitUntil: 'load' });
  await page.waitForTimeout(1500);

  const report = { url: BASE, at: new Date().toISOString().replace('T', ' ').slice(0, 19), views: [], palette: null, cropDir: null };
  const crops = [];

  for (const view of VIEWS) {
    if (view !== 'matchweek') { await page.click(`nav.tabs button[data-tab="${view}"]`); await page.waitForTimeout(900); }
    await settleScroll(page);
    const items = await collectText(page, view);
    const screened = await screenView(page, items);

    const record = (it) => ({
      view, selector: it.id ? '#' + it.id : '.' + it.cls.split(' ').filter(Boolean).slice(0, 2).join('.'),
      text: it.text, html: it.html, fontSize: it.fontSize, fontWeight: it.fontWeight,
      color: rgbToHex(it.color), threshold: thresholdFor(it.fontSize, it.fontWeight), large: it.fontSize >= 24,
    });

    const suspects = [];
    for (const it of items) {
      const s = screened.get(it.i);
      if (!s || s.unresolved) { suspects.push({ it, reason: s ? s.unresolved : 'not screened' }); continue; }
      const fg = hexToRgb(it.color);
      const worst = Math.min(contrast(fg, s.median), contrast(fg, s.mean));
      if (worst < thresholdFor(it.fontSize, it.fontWeight)) suspects.push({ it, screened: s, worst });
    }

    // verify all flagged, plus a random sample of the rest
    const passing = items.filter((it) => !suspects.some((x) => x.it.i === it.i));
    const shuffled = passing.slice().sort(() => Math.random() - 0.5).slice(0, SAMPLE);

    const failures = [], unresolved = [];
    for (const { it, reason, screened: s } of suspects) {
      const v = await verifyElement(page, it.i);
      if (!v) { unresolved.push({ ...record(it), note: reason || 'could not re-measure' }); continue; }
      const fg = hexToRgb(it.color);
      const ratio = contrast(fg, v.median), ratioMean = contrast(fg, v.mean);
      if (Math.min(ratio, ratioMean) < thresholdFor(it.fontSize, it.fontWeight)) {
        const rec = { ...record(it), bg: 'rgb(' + v.median.join(', ') + ')', bgMean: v.mean,
                      ratio: Math.round(ratio * 100) / 100, ratioMean: Math.round(ratioMean * 100) / 100,
                      verified: true, screenedRatio: s ? Math.round(Math.min(contrast(fg, s.median), contrast(fg, s.mean)) * 100) / 100 : null };
        failures.push(rec);
        crops.push({ view, selector: rec.selector, text: rec.text, crop: v.crop });
      }
      await settleScroll(page);
    }

    // spot-check the pass side: a sampling method that only ever looks where it suspects a fault
    // cannot tell you it was right everywhere else.
    let passChecked = 0, passActuallyFailing = [];
    for (const it of shuffled) {
      const v = await verifyElement(page, it.i);
      await settleScroll(page);
      if (!v) continue;
      passChecked++;
      const fg = hexToRgb(it.color);
      const worst = Math.min(contrast(fg, v.median), contrast(fg, v.mean));
      if (worst < thresholdFor(it.fontSize, it.fontWeight)) {
        const rec = { ...record(it), bg: 'rgb(' + v.median.join(', ') + ')', bgMean: v.mean,
                      ratio: Math.round(contrast(fg, v.median) * 100) / 100,
                      ratioMean: Math.round(contrast(fg, v.mean) * 100) / 100, verified: true, missedByScreen: true };
        failures.push(rec); passActuallyFailing.push(rec);
        crops.push({ view, selector: rec.selector, text: rec.text, crop: v.crop });
      }
    }

    report.views.push({ view, sampled: items.length, failures, unresolved, passChecked, passActuallyFailing: passActuallyFailing.length });
    await settleScroll(page);
  }

  await page.click('nav.tabs button[data-tab="matchweek"]');
  await page.waitForTimeout(600);
  report.palette = await semanticColours(page);
  report.paletteSeparations = {};
  for (const [a, b] of [['--win', '--loss'], ['--win', '--gold'], ['--accent', '--loss'], ['--win', '--accent'], ['--win', '--ink-2']]) {
    if (!report.palette[a] || !report.palette[b]) continue;
    const row = { pair: `${a} vs ${b}` };
    const pairs = { normal: [report.palette[a].hex, report.palette[b].hex] };
    for (const kind of Object.keys(CVD)) pairs[kind] = [report.palette[a][kind], report.palette[b][kind]];
    for (const [k, [x, y]] of Object.entries(pairs)) row[k] = Math.round(contrast(hexToRgb(x), hexToRgb(y)) * 100) / 100;
    report.paletteSeparations[`${a}|${b}`] = row;
  }

  await browser.close();

  if (crops.length) {
    const dir = OUT.replace(/\.json$/, '') + '-crops';
    mkdirSync(dir, { recursive: true });
    crops.slice(0, 30).forEach((c, i) => {
      const safe = `${String(i).padStart(2, '0')}-${c.view}-${c.selector.replace(/[^a-z0-9.-]/gi, '_')}.png`;
      writeFileSync(`${dir}/${safe}`, Buffer.from(c.crop.split(',')[1], 'base64'));
    });
    report.cropDir = dir;
  }
  writeFileSync(OUT, JSON.stringify(report, null, 1));

  // ── the summary ───────────────────────────────────────────────────────────────────────────────
  const line = (s) => process.stdout.write(s + '\n');
  line('');
  line('══════════════════════════════════════════════════════════════');
  line('  contrast audit (verified pixels) — ' + report.url);
  line('══════════════════════════════════════════════════════════════');
  let total = 0, sampled = 0, checked = 0;
  for (const v of report.views) {
    total += v.failures.length; sampled += v.sampled; checked += v.passChecked;
    line(`  ${v.view.padEnd(11)} ${String(v.failures.length).padStart(3)} verified failing of ${String(v.sampled).padStart(4)} text elements` +
         `  ·  ${v.passChecked} passing rows spot-checked` + (v.passActuallyFailing ? `, ${v.passActuallyFailing} were actually failing` : ''));
  }
  line('  ────────────────────────────────────────────────');
  line(`  TOTAL: ${total} verified failures of ${sampled} text elements · ${checked} of the rest independently re-measured`);
  if (total) {
    line('');
    line('  worst offenders:');
    const flat = report.views.flatMap((v) => v.failures).sort((a, b) => a.ratio - b.ratio).slice(0, 14);
    for (const f of flat) {
      line(`    ${String(f.ratio).padStart(5)}:1 (needs ${f.threshold})  ${f.selector.padEnd(24)} ${f.fontSize}px  "${f.text.slice(0, 30)}"`);
      line(`           ${f.color} on ${f.bg}  ·  ${f.html.replace(/</g, '&lt;').slice(0, 96)}`);
    }
  }
  line('');
  line('  colour-vision separation (contrast between the paired colours; lower = harder to tell apart):');
  for (const v of Object.values(report.paletteSeparations)) {
    line(`    ${v.pair.padEnd(22)} normal ${String(v.normal).padStart(5)} · protanopia ${String(v.protanopia).padStart(5)} · deuteranopia ${String(v.deuteranopia).padStart(5)} · tritanopia ${String(v.tritanopia).padStart(5)}`);
  }
  if (report.cropDir) line(`\n  crops of every failing box -> ${report.cropDir}`);
  line(`  full detail -> ${OUT}`);
  line('');
}

await main();
