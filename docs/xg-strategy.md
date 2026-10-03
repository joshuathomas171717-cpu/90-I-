# The xG gap (P2.3)

**Decision: keep xG manual and documented. Results update form, Elo and the table; they never touch the
xG ratings.** If a licensed feed is ever bought, the adapter is already shaped to take it.

## The problem, stated exactly

xG and xGA are roughly **35% of this model's feature importance** — the structural prior is literally
`attack(xG/90) × defence(xGA/90)` per club. The free sources publish **goals, not xG**:

| Source | Goals | Assists | **xG / xA** | Cost |
|---|---|---|---|---|
| football-data.org (free) | ✅ | ✅ | ❌ | free, 10 req/min |
| API-Football (free) | ✅ | ✅ | ⚠️ documented as inconsistent per league/plan — *verify before relying on it* | 100 req/day |
| bigballsdata (free) | ✅ | ✅ | ✅ match-level on `/stored/matches/:id/stats` | 250 req/day |
| SportMonks (paid add-on) | ✅ | ✅ | ✅ `/v3/football/expected/fixtures` + `/expected/lineups`; Basic = post-match, Advanced = live | subscription + add-on |
| TheStatsAPI (paid) | ✅ | ✅ | ✅ match / team / player / shot | from $50/mo, 7-day trial |

So there are three honest ways to close a 35% gap, and one dishonest way — quietly substituting goals
for xG and calling it the same model. This project does not do the dishonest one.

## The three options, scored

**A. Keep xG manual (chosen).** The ratings live in `data/teams_2026_27.csv` (`xg_90_base`,
`xga_90_base`, refreshed by hand from a published source), the live blend stays in `data_builder.py`,
and the weekly job **does not move them**. Consequences, accepted deliberately:

* the model's *structural* half stays anchored to a verified snapshot rather than drifting to whatever
  a goals-based feed implies;
* results still move the model — through form (`ppg`), the table, and Elo, which the feedback loop
  recomputes match by match (`standings.py`);
* a refresh is a documented manual step, and the file records the values it was built from.

*Cost:* the xG layer ages between refreshes. *Mitigation:* the backtest is re-scored every build, so a
stale xG layer shows up as degrading RPS rather than as silent nonsense.

**B. Derive a shots-based proxy.** Model xG from shots/shots-on-target rather than fetching it. Rejected
for now: the free tier does not publish shot counts either, so it would need a scraping dependency, and
a proxy fitted on one season of one league would be a liability dressed as a feature. Revisit only if
shot data arrives for free.

**C. Buy a feed.** SportMonks' expected-goals add-on or bigballsdata's free tier would close the gap
properly. bigballsdata is genuinely interesting — 250 requests/day with match-level xG is enough for a
weekly Premier League job — but it is a small provider with an unclear long-term licence, and the free
tier's commercial terms are not written down. **Recommendation: trial it for a gameweek or two before
trusting it**; if the numbers line up with the manual ratings we already hold, promote it to a second
provider behind the same interface.

## What the code does today

* `standings.py` — `recompute_standings()` recounts P/W/D/L/GF/GA/Pts/form **and** walks Elo
  (K=20, goal-difference weighted, 60 points home advantage). It deliberately does not touch
  `xg_90_live` / `xga_90_live`.
* `data_builder.py` — the live xG blend is `85% base rating + 15% actual scoring rate`, computed
  **per game played** (`GF / P`, not `GF / 5`), so the same formula keeps working after MW6 without
  re-tuning.
* `sources/base.py` — every provider declares `capabilities["xg"]`. `football-data.org` reports
  `False`. The pipeline reads that flag rather than assuming, so wiring an xG-capable provider in
  later is a new module, not a rewrite.
* `validate_data.py` — the plausibility checks (goals-per-game band 2.0–3.6, GF=GA, table reproduces
  from results) are what make a goals-only feed *safe* to accept: they catch a broken feed before it
  reaches the model.

## What would change this decision

1. **A budget for SportMonks or TheStatsAPI** → xG moves from manual to automated, per-match and (with
   the Advanced add-on) in-play. The adapter gains `fetch_xg()`; `capabilities["xg"]` becomes true; the
   manual column becomes a cross-check rather than the source.
2. **bigballsdata validating clean for two gameweeks** → free automated xG, no budget needed.
3. **A published CSV of xG per club per match** (some analytics blogs do this) → a file-based provider
   in the same `sources/` shape, refreshed manually each week.

## Ask

Nothing blocking. Two optional calls: (a) whether to trial bigballsdata's free xG tier for two
gameweeks, and (b) whether a paid xG feed is worth €/$ per month to you. Until then the model is
honest: it knows its xG is a manual, dated input, and it says so on the Model tab.
