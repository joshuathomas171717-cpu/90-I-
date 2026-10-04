# Changelog

What changed, when, and — where it was measured — what it did to accuracy. This file is the source
for [`/changelog`](static/changelog.html); the page is generated from it at build time, so the two
cannot drift apart.

**A rule this file follows:** a version carries an accuracy delta only when a blind replay was run
for it. Where a change was not measured, the entry says *not separately measured* rather than
offering an estimate dressed as a result. Half the value of publishing numbers is not publishing the
ones you do not have.

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
