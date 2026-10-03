# Accessibility and weight baseline — phase 07

Written 2026-10-03, at the end of Wave 5. This is the "before and after" the plan asked for in P7.1:
measured first, fixed second, so every claim below is a number that came off an instrument rather than
a judgement about how the page looks.

## The instruments

Two development tools, in `tests/a11y/`. They need node, a headless Chromium and an npm install, so
they are **not** part of the shipped test suite and cannot run in CI. What they found is pinned down
afterwards by `tests/test_wave5_a11y.py`, which runs on the standard library alone.

```bash
# once, anywhere with node and a couple of hundred megabytes to spare
npm i playwright axe-core && npx playwright install chromium

# with the site running:  PORT=8000 python3 server.py
node tests/a11y/sweep.mjs --reduce-motion        # axe-core across all six views + timings
node tests/a11y/contrast.mjs --sample 30         # pixel-true contrast + colour-vision separation
```

`sweep.mjs` drives each view by clicking its tab, runs axe-core 4.13 with the WCAG 2.0/2.1 A and AA
rule sets plus best-practice rules, walks the keyboard tab order, and measures first paint both
unthrottled and on a simulated slow 4G connection with 4× CPU throttling.

`contrast.mjs` exists because axe returned `color-contrast` as **incomplete for 1,385 nodes** — the
design sits on translucent panels over gradients and axe will not guess a background it cannot resolve,
which is honest but is not a pass. So it measures the screen instead: hide the glyphs, screenshot,
sample the pixels under each text box, compute the WCAG 2.1 ratio, then **verify every flagged element
individually** by scrolling it into view and re-measuring. It also simulates protanopia, deuteranopia
and tritanopia over the semantic colours.

## Before → after

| Measurement | Before Wave 5 | After | Notes |
|---|---|---|---|
| axe violations, all six views | **28 rule-instances · 563 nodes** | **0 · 0** | aria-allowed-role, landmark-one-main, page-has-heading-one, region, label, select-name, link-in-text-block, nested-interactive, heading-order, scrollable-region-focusable |
| Contrast failures (verified pixels) | **1,778** | **0** | token change; see below |
| Text elements measured | 4,984 (see note) | 1,618 | the earlier figure counted stacked views — see "the bug the counting found" |
| `prefers-reduced-motion` animations still running | **8** | **0** | all eight were on `::before`/`::after` |
| Embedded font payload | 111.9 KB (149 KB base64) | **80.2 KB** (106.9 KB base64) | subset to the 156 characters the page can render |
| `static/index.html` | 539 KB | **500 KB** | −42 KB of base64 fonts, +3 KB of new panels |
| First contentful paint, unthrottled | 588 ms | **612 ms** | noise-level; DOM grew by ~35 nodes |
| First contentful paint, slow 4G + 4× CPU | 1,532 ms | **1,060 ms** | the font saving |
| Keyboard tab stops with a visible focus ring | not measured before | see below | no gaps found; tabs are arrow-navigable |

### The contrast numbers, and why they were not guessed

The text tokens `--ink-3` (#6d7789) and `--ink-4` (#464e5e) carried 1,547 of the 1,778 failures. The
measured backgrounds behind them ran from about `rgb(7,9,13)` to `rgb(43,46,43)` — the brighter end
being green- and warm-tinted panels. Against those, the tokens scored **4.05:1** and **2.19:1** on a
typical panel and **3.16:1 / 1.71:1** on the brightest one, against a 4.5:1 requirement for small text.

The replacements are derived from those measurements, not chosen by eye:

| Token | Was | Now | Worst measured surface |
|---|---|---|---|
| `--ink-2` | #a7b0c0 | unchanged | 6.53:1 |
| `--ink-3` | #6d7789 | **#97a1b3** | 5.48:1 |
| `--ink-4` | #464e5e | **#8b93a3** | 4.62:1 |

The hierarchy is preserved — primary `#f3f6fa`, body `#a7b0c0`, labels `#97a1b3`, quietest `#8b93a3` —
and a test asserts both the ratios and that the four tones still step down in order.

Two chips carried white text on bright gradients: the warm "edge" chip at **2.22:1** and one `.dim`
line on a mint surface at **1.4:1**. The chips now use dark text the way their cyan siblings always had.

### Colour independence

The outcome bars said home/draw/away in mint, grey and magenta and nothing else — the most important
graphic on the page, unreadable to a reader who cannot separate the first colour from the third. Each
band now carries **H**, **D** or **A**, always in that order, with a spoken equivalent on the bar
(`role="img"` + label). The certainty chips carry a letter mark too. Measured separation between the
win and loss colours is 1.52:1 normally and 1.35:1 under deuteranopia — close enough that colour alone
was never going to be enough, which is the argument for the letters.

### The bug the counting found

Chasing an unexplained drop in "text elements measured" (4,984 → 1,618) turned up a **product bug, not
a measurement artefact**: `switchTab` removed the `.on` class from the outgoing view only inside its
150 ms slide-animation timeout. Under `prefers-reduced-motion: reduce` that branch is skipped — so the
new view appeared and the old one was never hidden. Every view a reader opened stayed on the page:
**six dashboards stacked vertically**. Invisible in a default browser, permanent for anyone with
reduced motion enabled, which is a group that includes people using assistive technology.

The first version of the accessibility fix made it worse before it made it better: syncing
`aria-hidden` while the stacking bug was live meant the *visible* panel was the one marked hidden. Both
are fixed, and `test_switching_views_always_hides_the_one_it_replaced` refuses to let the stacking
return. The lower element count is the fix: only the active view is on screen, so only the active
view's text is measured.

## What is still not done

Stated plainly, because a baseline that only lists wins is a brochure:

- **No screen-reader testing with an actual screen reader.** Everything here is programmatic: axe rules
  and rendered pixels. NVDA, VoiceOver and TalkBack have their own opinions, and the honest description
  of the current state is "passes the automated rules and the measured contrast", not "verified with
  users".
- **No user testing of any kind.** No keyboard-only user has tried the six views; the arrow-key tablist
  and the focus hand-off work as designed, not as observed.
- **Charts are described, not navigable.** The heat-map and probability grids carry labels and text
  tables nearby; they are not exposed as an accessible data structure in their own right.
- **Lighthouse was not run.** The plan said "axe-core plus Lighthouse"; Chromium runs here but the
  Lighthouse audit needs a full browser and a network profile it could not have in this sandbox. The
  throttle numbers above are CDP network + CPU emulation in the same family, not a Lighthouse score.
  Anyone with a normal machine can run it against the deployed site in a minute, and the number should
  be recorded here when they do.
- **`prefers-contrast` and forced-colours modes are untested.** The design assumes a dark background;
  Windows high-contrast mode may flatten it.

## Budgets

Set now so they can be argued with rather than rediscovered:

- `static/index.html` under **640 KB** uncompressed (currently 500 KB; ~170 KB gzipped over the wire).
- Embedded fonts under **90 KB** (currently 80.2 KB). `python3 tools/subset_fonts.py` rebuilds them;
  it needs `fontTools` and `brotli`, both dev-time only.
- Zero axe violations at WCAG 2.1 AA, and zero verified contrast failures.

All three are asserted in `tests/test_wave5_a11y.py`, so a future change that breaks one fails the
suite rather than quietly shipping.
