# Changelog

What changed, when, and — where it was measured — what it did to accuracy. This file is the source
for [`/changelog`](static/changelog.html); the page is generated from it at build time, so the two
cannot drift apart.

**A rule this file follows:** a version carries an accuracy delta only when a blind replay was run
for it. Where a change was not measured, the entry says *not separately measured* rather than
offering an estimate dressed as a result. Half the value of publishing numbers is not publishing the
ones you do not have.

---

## v2.4 — 6 October 2026

**Model** — unchanged from v2.3 for automatic forecasts. The player gate remains closed; the new UI
never auto-prices actual injury news or season-total form into a match call.

**Site** — tracked squad panels on all 20 club pages and the dashboard Table view: form/trend, competition
minutes, availability, source/fetch date and absence tier. Season totals say trend unavailable; untracked
availability is unknown, not healthy. All 38 matchweek pages and the dashboard now carry snapshot-derived
missing-player digests. The lightweight embedded preview is bounded; complete generated pages and
`players.json` retain the full source context. Mobile table/header/tick-strip overflow and generated-page
link/contrast issues found in the browser check were repaired without changing the semantic colours.

**What-If** — 52 searchable named players with explicit out/in hypotheses and replacement-aware input
ranges. New v2 links and v3 local saves retain names, coefficients, ranges, source dates and baseline
vintage. Existing v1/unversioned links keep the legacy formula; they are not silently re-priced. A new
baseline can change simulated outcomes, but the saved assumption coefficients remain frozen. These are
scenario input ranges, not confidence intervals on wins/points, and their accuracy is not separately measured.

**Record** — future availability captures are sealed with their prediction locks and bound to the
revision chain. Receipts/public/local checks detect changed capture bytes and deleted/altered seals.
Old MW6 stays not recorded at lock: later news cannot fill its history retroactively.

**Security and publication** — HTML-script-safe JSON, bounded known-player profiles, prototype-key
rejection and an offline credential guard before commit/push and public artifact uploads. Every finished
wave commits, pushes and verifies the website unless a known security risk requires a hold. The guard
redacts values and is not a complete security audit. No new paid API, site account or runtime dependency.

**Measured** — existing structural baseline: 46.3% 1X2 · RPS 0.2184 · rank correlation 0.566.
**Delta vs v2.3** — 0.0 points, 0.0000 RPS for unchanged automatic forecasts. UI/explicit scenario work,
not a claimed predictive accuracy gain; the new manual scenario assumptions are not accuracy-tested.

---

## v2.3 — 5 October 2026

**Model** — unchanged from v2.2. The production forecaster and the existing What-If injury assumptions
are unchanged. The new player layer is context, not an extra feature slipped into the ensemble.

**Player layer** — role-relative form with minute shrinkage, competition adjustment and a 35-day decay
only when real match dates exist. Season aggregates say recency unavailable. Replacement-aware absence
priors count a substitute as something, and a second tier fits opponent-adjusted with/without output
where at least ten appearances and five explicit zero-minute records exist. Missing rows are not injuries;
these fitted effects are associations, not causal claims. Exact rest and supplied travel replace the
congestion candidate's membership proxy, not the active model's unvalidated feature.

**Gate** — the 2025–26 matrix has no dates or lineups. The real-data candidate has therefore **not been
measured**, and its RPS/hit-rate deltas are **not available**, not a measured zero. A resumable free-key
or manual-drop backfill accepts actual match dates, but pre-kickoff availability captures must be supplied
separately: fetching old lineups today does not make them pre-match evidence. The chronological shadow
compares the structural replay head, not the live ML ensemble; even a good shadow cannot promote the
latter without validation of that actual head.

**Site** — player model card v3.0, a downloadable context/gate report, and a Model-tab input-status notice.
Source, fetch date, partial-squad coverage and absence tier are visible. Weekly optional sources refresh
before the rebuild, per-club availability distinguishes checked/unknown/failed, and deployment verification
now also compares the player-context content fingerprint. Squad panels and named-player What-If ranges
remain Phase 15, not features this release pretends to have shipped.

**Measured** — existing structural baseline: 46.3% 1X2 · RPS 0.2184 · rank correlation 0.566 on the
blind 2025–26 replay. These are not new player-layer measurements.
**Delta vs v2.2** — 0.0 points, 0.0000 RPS for the unchanged production model. The new candidate's delta
is unmeasured; no accuracy improvement is claimed. Card v3.0 is not a promoted production-model version.

---

## v2.2 — 5 October 2026

**Model** — unchanged from v2.1. No inputs, weights or hyperparameters moved, and the measured figures
below are the ones that still apply.

**Site** — the page now judges its own freshness instead of reporting an age it cannot explain. It ships
the fixture calendar, so it knows whether its numbers predate a gameweek that has already been played,
and when they do it says so in the header and names the missing gameweek rather than presenting old
numbers with confidence. Alongside it: `check_live.py`, a command anyone can run against the deployed
site that reconciles it with the calendar and verifies the published ledger's hash chain as a reader
receives it; `docs/operations.md`, a runbook for what breaks and what to do about it; and the weekly job
now confirms its own deployment landed.

**Groundwork, not yet visible** — player data: a competition-strength table covering 22 competitions with
its sensitivity measured, a per-player form table that builds with no account at all (league minutes
only, and labelled as such), and a dated availability capture stored inside each gameweek's snapshot.
None of it changes a prediction yet; that is gated behind a backtest in the next phase, and the changelog
will say what it measured when it runs.

**Measured** — 46.3% 1X2 · RPS 0.2184 · rank correlation 0.566 on the blind 2025-26 replay.
**Delta vs v2.1** — 0.0 points, 0.0000 RPS. Site work, no model change. The player groundwork has no
delta here because it has not been allowed to touch a prediction yet.

---

## v2.1 — 4 October 2026

**Model** — unchanged from v2.0. No inputs, weights or hyperparameters moved, so the measured
figures below are still the ones that apply. Two structural fixes landed in the data path rather
than in the model: the fixture calendar now carries all 33 remaining matchweeks (Matchweek 9 was
missing — it fell across a month boundary and the window parser dropped it), and the weekly job
locks and scores predictions through the new ledger.

**Site** — the prediction ledger, the receipts page, and a model-pulse strip that reads the live
record instead of a frozen backtest. Scenario input is now validated at every boundary after a
stored cross-site scripting flaw was found in it, and the deployed site sends a Content-Security-
Policy. The Vercel build was also fixed: a repository-root `server.py` made Vercel treat the project
as a Python app, which is why the first deployment failed.

**Measured** — 46.3% 1X2 · RPS 0.2184 · rank correlation 0.566 on the blind 2025-26 replay.
**Delta vs v2.0** — 0.0 points, 0.0000 RPS. The model did not change, and saying otherwise would be
the exact dishonesty this changelog exists to avoid.

---

## v2.0 — 3 October 2026

**Model** — replaced the v1.0 approach with a Dixon-Coles bivariate Poisson model over Elo-derived
attack and defence strengths, with expected-goals information folded in, a fitted home-advantage
factor, a low-score correction (rho), and regression factors for promoted clubs. Season outcomes are
5,000 simulated seasons rather than a single projected table, which is where the ranges and the
percentages on the site come from.

**Measured** — 46.3% 1X2 · RPS 0.2184 · rank correlation 0.566, on a blind replay of all 380
matches of the 2025-26 season, using information available before that season started. Against the
baselines on the same fixtures: home-win-always 42.6% (RPS 0.2276), prior-season-table favourite
43.4% (RPS 0.2396), uniform 42.6% (RPS 0.2322). That is **+2.9 points and −0.0212 RPS** over the
strongest baseline, a 8.8% reduction in RPS.
**Delta vs v1.0** — not comparable. This is the first version with a saved replay artifact, so it is
the first version that can carry a number at all.

---

## v1.0 — 3 October 2026

**Model** — the first build: a Poisson goals model over goals-for/goals-against with a recent-form
adjustment, a 5,000-simulation season engine, and projections for the table, the Golden Boot, the
Golden Glove and the playmaker board.

**Measured** — not separately measured. No replay artifact was kept for this version, and
reconstructing a number for it now would be an invention; the v2.0 replay supersedes it and is what
the site quotes.
