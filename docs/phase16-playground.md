# Phase 16 — an original football playground

6 October 2026. The owner asked for a FIFA-career-inspired experience, not another passive statistics
page. This is a lightweight browser management game, **not the full EA/FIFA 3D game**, licensed assets,
live match commentary or a promoted prediction model. A second usable idea, **Beat the Model**, turns
the forecast into a personal matchday prediction challenge.

## Career Mode: what you can actually do

1. Choose any of the 20 current clubs. Start at its actual published table, with the first five weeks
   already played. The remaining 33 matchdays/330 fixtures become your simulated alternative season.
2. Choose balanced, attacking, defensive or high-press tactics. Pick recovery, finishing or defensive
   training. Fitness changes match chances; pressing/attacking use more energy.
3. Rest a tracked star for the next matchday. This is a game availability decision, not an actual
   injury claim. The 52-player sample is not a complete starting XI.
4. Sign a tracked player from another club with fictional credits. Both game clubs change. One signing
   or release per matchday; releasing a signed player refunds half and returns them to the original
   game club. Prices, the initial 100 credits and match rewards are game rules, not real fees/money.
5. Play a matchday, see a goal reveal, or fast-forward three weeks. Follow your alternate table,
   matchday notebook and board objective through the final report.
6. Keep up to three local careers. Reload/resume without rerolling. Export/import a validated JSON
   backup to preserve a frozen world. If browser storage is blocked, the game still runs in memory and
   visibly asks you to export before closing.

The homepage makes Career/Challenge actions prominent, with a club picker, rather than hiding them
behind an advanced tab. The game page is one self-contained file with embedded fonts, data and scripts;
it needs no network, API key, accounts, payments, backend session or Node runtime.

## Game rules and fair comparison

The frozen world includes its starting table, 52 tracked-player impact estimates, game prices, full
remaining fixture list and published expected-goal rates. Career sampling uses a 0–6 goal Dixon–Coles
score grid, calibrated from those rates, with fixed per-fixture pseudo-random draws. Tactics/training,
fitness, transfers and rest choices are explicitly assumed **game modifiers**, bounded at ±30% attack
and ±25% conceded-goal rate. They are not separately validated football effects.

Every career runs an untouched control season with the same draws and game sampler. The points delta
is against that same-engine control path, not the unrelated published Monte Carlo headline. A neutral
career equals its control path; the same world/seed/decisions give the same results. Save restoration
replays the journal and recomputes table points, credits, fitness and transfers; editable derived totals
are not trusted. Imported world inputs are schema-validated, not independently attested—this is a
single-player sandbox, not an anti-cheat competition.

Minute/scorer text in the goal reveal is a fictional narrative of the simulated final score. It is
never described as a real event and never enters real results, predictions or historical locks.

## Second idea: Beat the Model

* Select home/draw/away or exact scores for the next matchweek. Correct outcome earns 3 points;
  a correct exact score adds 2. The model keeps its highest-probability outcome, with a score pick
  consistent with that outcome for comparable challenge scoring.
* Play a simulated practice round immediately. Changing its seed is an explicit reroll. Practice
  results never enter the real-results scorecard.
* Optionally lock personal real picks before the displayed conservative start of the published
  matchweek window. This is a game deadline, **not a claimed exact kickoff**.
* Only published actual results score those frozen real picks. Missing results remain pending;
  the current MW6 record correctly has 0 actually played/10 pending.
* Local clocks and saves can be edited, so this is personal practice—not a verified public contest,
  tamper-proof timestamp, global leaderboard or betting slip. Resetting practice cannot rewrite a
  locked real record. Old records are scored from their frozen fixtures/picks against later actual data.

## Safety, accessibility and release evidence

* Full pipeline: **385 passed, 0 failed, 0 skipped** (including 45 new tests). The new unit/integration tests cover current-world joins, same-seed sampling, a complete neutral
  season, goal/point conservation, tactics/fitness/rest, transfer cost/caps, journal replay/tamper
  rejection, malformed/future schemas, challenge scoring/deadlines/separation, build paths and hashes.
* The existing official forecasts, MW6 snapshot/ledger and LICENSE are compared before shipping;
  this wave changes none of their actual prediction fields or lock records.
* Real Chromium exercised homepage entry, club choice, tactics/training/rest/signing, matchday play,
  save/reload, a full 33-round season, validated backup import, practice/real separation and immutable
  locked picks. No runtime errors or external requests; desktop/mobile fit the viewport.
* A poisoned imported player name injected no nodes, executed no handler and polluted no prototype.
  An illegal journal was held. Generated JSON is HTML-script-safe; rendered strings are escaped,
  imports have a 350 KB cap, identifiers/finite values and journal order are validated.
* Automated WCAG A/AA checks found no violations in setup/career/challenge at 1440 and 390px. Some
  contrast checks are incomplete and recorded, not advertised as full WCAG certification. Keyboard
  mode navigation and reduced-motion/skip reveal are supported.
* Storage v4 migrates earlier favourites/scenarios unchanged, adding local career/challenge fields.
  The existing Forget Everything action also clears the games.
* Game code/data have a deployment fingerprint checked independently of unchanged forecast dates.
  Every finished wave is committed, pushed and live-verified, with the redacted credential guard
  before publication/artifact uploads. Hold only for a known security risk, as the owner instructed.

Reproduce:

```bash
python3 run_all.py
python3 tests/run_tests.py -k wave16
python3 tools/publication_gate.py --staged
PORT=8000 python3 server.py
# Second terminal, dev-only browser tooling:
bash tools/setup_browser_tools.sh
NT90_PLAYWRIGHT_MODULES=/tmp/a11y/node_modules node tests/a11y/wave16.mjs
```

No paid data or runtime dependency was added. Historical player measurement/calendars remain P14's
open data gates; this game is not a claimed accuracy improvement and does not circumvent those gates
for automatic forecasts.
