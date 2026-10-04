# The player signal: what is actually available (P13.1)

Written by `tools/audit_sources.py`. Every row below is a *measurement*, and the three
possible answers are deliberate: **proven** (a real request returned it), **not-proven**
(nobody has spent a request on it yet — this is not a soft pass), and **failed** (it was
asked for and did not arrive). A row that cannot be measured is never reported as working.

| key | set |
|---|---|
| `API_FOOTBALL_KEY` | no |
| `API_FOOTBALL_API_KEY` | no |
| `APISPORTS_KEY` | no |
| `FOOTBALL_DATA_ORG_TOKEN` | no |
| `FOOTBALL_DATA_KEY` | no |

Quota at the time of the audit: 0 used of 25 today (`2026-10-04`).

| check | asked for | result | detail |
|---|---|---|---|
| the provider answers with a free key | a request that returns clubs | **not-proven** | no API key — set API_FOOTBALL_KEY (free: https://dashboard.api-football.com/register, 100 requests/day, no card). Without it the player signal comes from data/provider_drop/players/ instead |
| the league id maps to our clubs | 20 clubs, resolvable names | **not-proven** | needs a free API key — set API_FOOTBALL_KEY and re-run |
| player statistics split by competition | one row per competition | **not-proven** | needs a free API key — set API_FOOTBALL_KEY and re-run |
| injuries with a type and a reason | type + reason per player | **not-proven** | needs a free API key — set API_FOOTBALL_KEY and re-run |
| international competitions present | a national-team competition id | **not-proven** | needs a free API key — set API_FOOTBALL_KEY and re-run |

**Summary:** 5 not-proven

## What this means for the plan

* A **not-proven** row does not block the build: the keyless path (`data/provider_drop/players/`)
  and every weight in `data/competition_weights.csv` work today, and the tests prove it.
* A **failed** row on the per-competition split would narrow the signal to league minutes. The
  index would still run, and every surface would have to say **league-only** (P15.4).
* International coverage is the one row the plan never promised. If sampling says it is absent,
  internationals are excluded from the index and the exclusion is stated, not averaged in.

Re-run with `python3 tools/audit_sources.py` after setting a key to convert not-proven rows into measurements. The audit spends real requests (about 6 with `--clubs 2`), which is why it is a separate tool rather than part of the weekly job.

## What the signal can and cannot claim today

Written 2026-10-05, before the audit could be run, so that the limit is on the record rather than
discovered later. Everything here is about the *keyless* state of the repository, which is the state a
reader cloning it will find.

**What works with no key and no network, and is tested:**

* the competition-strength table (22 competitions, 20 rows of judgement and their reasons) with a
  sensitivity check that reports the biggest lever (the league itself, ±7.5% for a domestic-only player);
* a form table built from `data/provider_drop/players/`, which is what `tools/export_players_drop.py`
  writes from the project's own squad dataset — 52 players across all 20 clubs;
* availability capture from `data/provider_drop/injuries/`, stored inside the gameweek snapshot and dated;
* every one of the above covered by `tests/test_wave13_players.py`, including a run with the key absent.

**What the keyless path cannot do, and says so:**

* **No competition split.** The project's own dataset has league minutes only. A form index built from it
  is a *league* form index: no Champions League nights, no FA Cup ties, no international windows.
  Surfaces showing it must say **league-only** — this is the row P15.4 exists for.
* **No verified international coverage.** The provider's own documentation does not settle whether
  national-team competitions appear on the free tier for a given season. The audit reports it as
  **not-proven** until somebody samples it, and the index excludes internationals until then rather than
  guessing at a weight for matches it cannot see.
* **No injury history.** `/sidelined` is reachable, but durability is not modelled in Phase 14 and a
  signal that is fetched but unused is a signal nobody has tested. It stays out.

**What a key adds — and nothing else.** `API_FOOTBALL_KEY` (free, 100 requests/day, no card) converts the
league-only table into a per-competition one and the untracked availability into a real capture. It does
not add xG, because no plan at that provider has any (see `docs/xg-strategy.md` for what that costs the
model and why the trade is documented rather than papered over). It does not change the weights, the
index, or any surface — those are built and tested without it.
