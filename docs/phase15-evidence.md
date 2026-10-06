# Phase 15 — visible players, explicit scenarios and lock-safe evidence

Implementation completed 6 October 2026. Automatic forecasts remain unchanged and the historical
player-input gate remains closed. This wave makes the player layer useful and visible without inventing
missing data or claiming an accuracy improvement.

## What shipped

* **P15.1:** all 20 club pages have player form/trend, competition-minute splits, latest sourced
  availability, absence tier and per-player source/fetch labels. The dashboard Table view has a club
  picker and squad cards. Season aggregates say trend unavailable; a goalkeeper without ratings has no
  fake goals-based index. The self-contained preview preserves all 52 modelled players, bounds extra
  previews and points to the complete generated club pages/report where needed.
* **P15.2:** all 52 tracked scenario players, search/club filters, explicit out/in controls, and
  replacement-aware assumption ranges. New v2 links and v3 local saves preserve names, coefficients,
  ranges, source/fetch date, context hash and baseline vintage. Older v1/unversioned links preserve
  their original injury formula; they are not silently upgraded. A changed baseline may change future
  projections, but frozen profile coefficients are retained. The browser and Python use the same bounded
  aggregation/caps. Ranges describe input assumptions, not confidence intervals on wins or table points.
* **P15.3:** all 38 matchweek pages and the dashboard's current matchweek have snapshot-derived missing
  player digests. Unknown, failed, partial and checked-empty coverage are different facts. Injury source
  listings are not a guarantee of selection or of applicability to a specific fixture.
* **P15.4:** receipts show availability as sealed at a prediction lock. New locks bind capture bytes,
  prediction hash, snapshot name and lock time into an availability revision; local/public checks catch
  altered/deleted seals or later capture times. Old GW6 remains **not recorded at lock**—later rolling
  news and fields added to a snapshot cannot retroactively fill it. All player numbers have source/date
  context; current international coverage and true recency remain visibly unavailable.

## Security and publication

Inline JSON (including JSON-LD) escapes HTML-significant characters; escaping only after DOM rendering
would be too late for a closing-script injection. Named profiles are finite, capped, known-player/club
validated, versioned and bounded in size. Prototype names never become recognised players/clubs.
Malformed profiles remove the associated assumption rather than silently reprice it with legacy maths.

The new offline publication guard checks prospective source/static/index bytes and guarded CI artifacts
without echoing the credential. It is a targeted credential guard, not a complete security audit.
Every finished wave commits, pushes and verifies the live website unless a known security risk requires
holding publication; the procedure is in [publishing.md](publishing.md).

## Checks run

* Full keyless pipeline and suite: **340 tests passed**, no failures/skips at this checkpoint. Includes
  actual v2 profile round-trips, legacy compatibility, Python/browser effect parity, snapshot tamper
  drills, no retroactive seals, provenance/preview equality, missing/stale sources and redacted guard checks.
* Existing non-meta production prediction fields are identical to the pre-wave commit. Existing GW6
  snapshot/ledger bytes and `LICENSE` were compared and are unchanged.
* Real Chromium: 6/6 app views fit both desktop and 390px mobile document widths; no runtime JavaScript
  errors or unexpected external requests. Explicit save/share/reopen/in restore tested. Python API
  simulation accepted a frozen profile and reported the same aggregate input effects as the browser.
* Browser XSS fixture containing closing-script and image-handler strings: no execution, injected nodes
  or prototype pollution. The fixture is scratch/test-only, not shipped data.
* Automated WCAG A/AA checks on new squad/scenario regions and generated club/matchweek/receipts pages:
  no violations. Some gradient/hidden-content contrast checks remain incomplete and are recorded as
  such—not presented as a complete WCAG certification. Old header/table/tick-strip overflow and generated
  page link/contrast issues found during the checks were fixed without changing the semantic palette.
* Self-contained dashboard remains under the existing **640 KiB** budget; no budget was weakened.

## Reproduce

```bash
python3 run_all.py
python3 tests/run_tests.py -k wave15
python3 tools/publication_gate.py --staged
bash tools/setup_browser_tools.sh
# Start the local dev server, then use a second terminal (and the library path printed by setup):
PORT=8000 python3 server.py
NT90_PLAYWRIGHT_MODULES=/tmp/a11y/node_modules node tests/a11y/wave15.mjs
```

No Node runtime, external scripts, API key, paid tier, site account or database is required by the shipped
product. Node/browser dependencies are dev instruments only. Real historic measurements/calendars remain
P14's three open data checks; the UI implementation does not pretend they passed.
