# Player layer — model card v3.0

**Status: context only. The production model is unchanged.** Written 5 October 2026.
This version numbers the player-layer card, not a newly promoted live forecaster.

## Intended use

Describe player output, replacement-aware absence exposure, and exact schedule/rest evidence alongside
team form. A form index is neither a win probability nor a whole-squad valuation. The committed sample
has 52 players at 20 clubs, not 20 complete squads.

## P14.1 — form

`player_index.py`: goals + 0.75 assists per 90, competition-adjusted, role-relative, minutes-weighted,
and shrunk toward a neutral 50 using 450 equivalent minutes. Dated matches decay with a 35-day half-life;
effective minutes cap at 1,800. Ratings, where supplied, contribute a separate role-aware component.
GK output needs ratings; zero goals does **not** mean a bad goalkeeper. Priors and sensitivity weights
are judgement, not fitted measurements (`data/player_signal_policy.json`, `data/competition_weights.csv`).

Season totals are not recency data. Fetch timestamps are not match timestamps. Dated rows replace,
not add to, the same competition's season aggregate. Future matches and aggregate-through dates are
excluded. The current keyless sample is league-only, season-to-date; recency is unavailable. Explicitly
verified international records may count; undocumented national-team coverage is excluded.

## P14.2 — how an absence is priced

**Tier 1:** share of the club's actual league goals, adjusted by role and a replacement retaining 70%
of the contribution. The denominator is club goals, never the sum of this partial player sample.
GK/defender defensive shares are assumptions, labelled as such. The 50–85% replacement-retention range
is a scenario range, **not** a statistical confidence interval. Multiple absences are deduped and capped.

**Tier 2:** opponent/home-adjusted log output residuals, comparing explicit appearance and zero-minute
records. At least 10 appearances and 5 explicit absences are needed; sparse estimates shrink toward
zero. Only matches whose statistics became available before the cutoff count. A missing row or null
minutes is not an absence. The result is a with/without **association, not a causal injury effect**:
rotation, selection, tactics and other absences are still confounders. Without adequate history Tier 1
remains in place.

## P14.3 — congestion/travel candidate

`congestion.py` measures exact kickoff intervals, last-seven-day workloads and supplied travel distances.
Date ranges are excluded rather than converted to invented kickoffs. A home fixture can have zero travel;
an unknown away distance is unknown. An international window is not a match: only named-player
appearances contribute, weighted by their minutes and one player's share of the team.

The two free calendar requests (PL and UCL) use football-data.org; cups and internationals also accept
manual calendar drops. Historical provider access and international completeness are unverified until
a real response proves them. The new schedule layer is a **candidate replacement**, not a silent change
to the live model's existing competition-membership proxy.

## P14.4 — gate and leakage boundaries

`player_gate.py` requires an exact dated 380-fixture historical calendar agreeing with the shipped
2025–26 result matrix, per-match appearances, and separate availability captures timestamped before
kickoff. The result matrix has no dates; its alphabetical fixture order is never called chronology.
The first 120 fixtures are warm-up; later fixtures are evaluated in actual kickoff order. Each call
uses only completed prior matches, with a conservative next-day statistics embargo where an actual
availability timestamp was not supplied. Target results, own-match appearances and 2026–27 player
statistics are excluded from feature construction. Policy constants are fixed, not tuned on holdout.

Pass requirements: at least 200 test matches, 80% pre-match coverage, RPS gain ≥0.002, improved hit rate,
and the upper endpoint of a paired seven-day-block bootstrap RPS-delta interval below zero. Gates that
lack input return context-only, **null** candidate/delta, and the missing-evidence reasons.

**Measured now:** existing structural baseline: 380 matches, 46.3% hit rate, RPS 0.2184.
**New candidate:** not measured — 0 joined dated fixtures, 0 evaluation matches, no pre-match captures.
**Candidate delta:** not available, not a measured zero.

This comparison tests the structural head used by the existing replay, not the live ML ensemble. Even
a passing shadow comparison cannot promote the latter without temporal validation of that actual head.
There is no automatic model-input switch. `input_enabled` remains false and production numbers stay
unchanged. The downloadable gate report and the live card publish these limitations.

## Reproduce without a key

```bash
python3 player_history.py --source local --season 2025-26
python3 backtest.py
python3 player_gate.py
python3 player_context.py
python3 tests/run_tests.py -k wave14
python3 run_all.py
```

The gate accepts a complete historical bundle in `data/provider_drop/player_history/*.json`, or a
quota-bound provider backfill:

```bash
python3 player_history.py --source api-football --season 2025-26 --max-fixtures 20
```

This is opt-in; it never starts in CI or in the weekly refresh. Free-tier historical coverage must
still be verified. With the default 25/day safety budget, one fixture-list request plus 380 player
requests requires at least 16 UTC days; with a 90/day budget, at least five. No payment or card required.
The tool saves after every successful fixture, skips completed fixtures, replays raw caches for free,
and preserves history when a request fails. Provider lineups retrieved today do **not** provide original
pre-match injury captures — supply real dated captures separately; never backdate them.

## Input examples (illustrative, not actual results or injuries)

A history drop is an object with `season`, `source`, `fixtures`, `availability` and optionally `calendar`
and `player_matches`. `player_matches` accepts individual dated records (player id/name, current club,
competition, minutes/goals/assists and `match_date`) for cups/nationals against non-PL opponents, without
inventing an internal opponent code. National-team rows additionally need `international_verified: true`.
Import current-season records with `python3 player_history.py --source local --season 2026-27`.
These records improve dated form coverage; they do not invent the missing 380 historical fixture dates.

The illustrated full-fixture shape is:

```json
{
  "season": "2025-26",
  "source": "your-verified-export",
  "fixtures": [{
    "fixture_id": "example-only",
    "kickoff": "2025-08-23T14:00:00Z",
    "home": "ARS", "away": "AVL", "home_goals": 1, "away_goals": 0,
    "players": [
      {"player_id": "example-player", "player": "Example Player", "club": "ARS",
       "position": "MID", "minutes": 90, "goals": 0, "assists": 1}
    ]
  }],
  "availability": [{
    "fixture_id": "example-only", "club": "ARS", "tracked": true,
    "known_at": "2025-08-23T12:00:00Z", "players_out": []
  }]
}
```

Real bundles must include both teams, all 380 calendar entries and real captures, not this example.
A calendar drop in `data/provider_drop/calendar/*.json` uses `{"calendar": [...]}` with a resolved
`club`, exact `kickoff`, `competition`, `fixture_id`, `venue`, optional `travel_km`, and `known_at`.
An international entry additionally needs `international: true`, `player_id`, and `minutes`.

## Live refresh

The optional sources refresh before the weekly offline rebuild. API failures retain good data;
partial player collections cannot replace a fuller committed table. Availability carries per-club
checked/unknown/failed coverage, so quota exhaustion never turns unqueried clubs into healthy ones.
`API_FOOTBALL_KEY` is an optional GitHub secret; the existing free results key also supplies PL/UCL
calendars. Source changes keep the site rebuild even when the headline predictions are unchanged.
Phase 15 will add the detailed squad panels, named-player scenario ranges and pre-match missing-player
digests; this phase publishes the card and an input-status notice, not those unbuilt features.
