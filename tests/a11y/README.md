# Accessibility instruments

These are **development instruments, not part of the test suite**. `tests/run_tests.py` runs on a
stdlib Python interpreter and nothing else — that is a property worth keeping, because it means
`python3 run_all.py` works on a clean machine, in CI, and inside a downloaded zip. Chrome and Node
cannot be prerequisites for that.

So the checks that need a real browser live here, and they are run deliberately, by hand, when the
interface changes.

## Setting up

```bash
bash tools/setup_browser_tools.sh          # installs node deps + chromium, reports what is ready
bash tools/setup_browser_tools.sh --check  # report only, install nothing
```

The script prints the exact commands to run when it finishes. On a normal Linux or macOS machine
that is `NT90_PLAYWRIGHT_MODULES=/tmp/a11y/node_modules node tests/a11y/sweep.mjs`. In this sandbox
it also prints an `LD_LIBRARY_PATH` — the container has no root, so the nine shared libraries
Chromium wants are fetched with `apt-get download` and unpacked into `/tmp/chromelibs`.

Both `/tmp` and `~/.cache` sit outside the workspace snapshot, so the toolchain evaporates between
sessions. Re-running the script is the intended answer; it takes about thirty seconds.

## Running, with the site up

```bash
PORT=8000 NT90_PRELOAD=1 python3 server.py      # in another shell
node tests/a11y/sweep.mjs --reduce-motion       # axe-core over every view, plus motion checks
node tests/a11y/contrast.mjs --sample 30        # computed-contrast audit, all text elements
```

## What each instrument answers

| File | Question it answers | Notes |
| --- | --- | --- |
| `sweep.mjs` | Does axe-core report violations on any view, in normal and reduced-motion modes? | Drives every tab, runs the simulator, opens the model card. |
| `contrast.mjs` | Is every rendered text element above its WCAG threshold? | axe's own `color-contrast` rule is permanently `incomplete` in headless Chromium — it needs a real paint. This walks the elements itself and computes the ratio from the resolved colours. |
| `perf.mjs` | What does the page cost — transfer size, FCP, DOM nodes? | |

## Two things these instruments have taught us, twice each

**Sample the element's own box, after scrolling to it.** Measuring a below-the-fold element without
scrolling gives a screenshot of the wrong region, and the "failures" that fall out of that are
phantom. `.dim`-on-green and everything-about-`.num` were both this.

**Never trust a check that cannot fail.** The first version of the contrast sweep silently skipped
elements whose colour it could not resolve, and reported zero failures for a page with a genuinely
invisible label. Every sampler here now counts what it *skipped* as well as what it verified, and
prints both — "1,618 text elements, 0 failures, 0 unresolved" is a result; "0 failures" alone is not.
