# Phase 14 implementation — evidence, 5 October 2026

**Shipped as context. Live player input remains off.** This is not a successful historical accuracy
experiment: the required real data is absent. The implementation and its boundary tests are complete;
three data-dependent acceptance checks remain open in the plan/tracker.

| Part | Implementation | Remaining evidence |
|---|---|---|
| P14.1 form | Dated decay, role-aware output/rating index, minute shrinkage, competition adjustment, partial-squad aggregation | Current sample is 52 league-only season totals; no per-match recency claim |
| P14.2 absences | Replacement-share Tier 1 and opponent-adjusted with/without Tier 2, explicit missing/null handling and cutoff | Real Tier 2 estimates require dated appearances and ≥10 present/≥5 explicit absent games; 0 Tier 2 players now |
| P14.3 congestion | Exact rest, supplied travel, named international appearances, free PL/UCL calendar adapter | No exact next kickoffs collected in the keyless snapshot; old live proxy remains unchanged |
| P14.4 gate | Chronological walk-forward shadow, immutable policy, real-score join, timestamp checks, block-bootstrap gate and published card | 0/380 real dated fixtures joined, 0 test matches, no genuine pre-kickoff captures; candidate/deltas null |

## Checks actually run

* `python3 run_all.py`: full validation, data build, old replay, player gate/context, engine, dashboard,
  crawlable pages, suite and page/currentness check all passed.
* Final `python3 tests/run_tests.py`: **307 passed, 0 failed, 0 skipped**. Includes a 380-fixture
  **synthetic test** of the shadow machinery: invented test timestamps are never used in published
  history or called real accuracy evidence.
* Pre-phase vs post-phase output: all headline/table/fixture/award prediction fields identical.
  Only runtime metadata and the new descriptive player-status metadata changed. The existing forecast
  is not silently modified; neither is the current What-If injury formula.
* `python3 score_ledger.py --verify`: existing GW6 lock and revision chain verify; no historical locks
  or snapshots were rewritten.
* `python3 check_page_current.py`: exact payload/source agreement, header and cutoff agreement.
* `tests/a11y/player-layer.mjs`: real Chromium, dashboard Model tab → new card, JSON download, desktop
  1440×1000 and mobile 390×844. **0 runtime JS errors, 0 external requests, 0 automated WCAG A/AA
  violations**, JSON HTTP 200, no document-level horizontal overflow. Desktop audit had no incomplete
  checks; mobile color contrast had an incomplete check for horizontally clipped content. That is
  recorded, not presented as a full WCAG certification. Overflow tables have labelled, focusable regions.

## Reproduce the browser check

```bash
bash tools/setup_browser_tools.sh
PORT=8000 python3 server.py
# In a second terminal; use the LD_LIBRARY_PATH printed by setup if needed:
NT90_PLAYWRIGHT_MODULES=/tmp/a11y/node_modules node tests/a11y/player-layer.mjs
```

The browser harness is dev-only. No Node, browser downloads, accounts, database or external scripts
are required to run the shipped Python/static product.

## Website and publication

Generated deliverables: `static/player-model.html`, `static/player-model.json`, updated Model-tab
status notice, method link and changelog v2.3. The downloadable JSON reports the genuine real-data
state, not synthetic test output. A player-context content fingerprint is embedded in production
metadata and compared by the deployment checker, so a context-only change cannot pass merely because
matchweek and results date still match.

Free optional sources refresh before the weekly rebuild. Partial pulls retain good player data;
availability records checked/unknown/failed per club; historical provider backfills remain opt-in.
Phase 15's squad panels, named-player What-If ranges, missing-player digests and locked-snapshot receipts
are next and are not described as already shipped.
