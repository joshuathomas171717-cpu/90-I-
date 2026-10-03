# Which football data source (P2.1)

**Decision: football-data.org is the primary source. The pipeline runs without it, always.**

One page, one recommendation, and the fallback stated up front. Researched 3 October 2026; every limit
below is the provider's published free-tier limit at that date, not a guess.

## The shortlist

| Provider | Free tier | Results | Standings | Players | xG | Fit |
|---|---|---|---|---|---|---|
| **football-data.org** | **10 req/min**, key by email | ✅ fixtures + results | ✅ | ✅ top scorers | ❌ | **Primary** |
| API-Football (API-Sports) | 100 req/**day** | ✅ | ✅ | ✅ | ⚠️ unreliable | Too tight |
| TheSportsDB | 30 req/min, v2 is paid | ✅ basic | ✅ | ⚠️ partial | ❌ | Metadata fallback |
| bigballsdata | 250 req/day | ✅ | ✅ | ✅ | ✅ match-level | Interesting, unproven |
| SportMonks / TheStatsAPI | paid (€/$ per month) | ✅ | ✅ | ✅ | ✅ proper xG | Wave 2 budget: no |

## Why football-data.org wins for this project

1. **The quota fits the job.** A weekly run needs roughly six calls — a dozen at most during a
   double gameweek. Ten requests a minute is not a constraint; 100 requests a *day* (API-Football) is a
   real one the moment I fetch per-fixture detail, because a single "update everything" run can burn it.
2. **It has the three things the pipeline actually consumes:** results (for the feedback loop),
   standings (a cross-check the gate uses), and top scorers (goals + assists).
3. **It is honest about what it does not have.** No xG on the free tier — which is exactly what
   `docs/xg-strategy.md` plans around rather than pretending otherwise.
4. **The failure mode is explicit.** Exceed the limit and you get HTTP 429 with retry headers, which
   `sources/base.py` already handles: the client sleeps out the window and retries.

Known constraints, stated plainly: the free tier is **personal/non-commercial use only**, and
commercial use starts at €10/month. One request in flight at a time is fine; hammering it is not.

## How it is wired

```
sources/__init__.py::get_provider()          selection order:
    1. NT90_SOURCE env var                       explicit name always wins
    2. football-data.org                          if FOOTBALL_DATA_ORG_TOKEN is set
    3. local                                     the pipeline's own CSVs — no account, no network
```

* `sources/football_data_org.py` — the live provider. Caches every raw payload to
  `data/raw/<date>/football-data-org-*.json` **before** parsing, so any published number can be traced
  back to the bytes that produced it.
* `sources/local_snapshot.py` — the fallback and the manual path. It reads the pipeline's CSVs, or a
  JSON export dropped in `data/provider_drop/`. The full weekly chain runs against it, which is why
  the job can be tested end to end in this repo with no key at all.
* `sources/base.py` — the normalised shapes, the club-name resolver (`team_code()`, suffix-tolerant
  but never fuzzy: an unknown club fails loudly) and a rate-limited HTTP client.

## The fallback plan, in order

1. **No key yet** → `local`. Results are typed or pasted into `data/provider_drop/results.json`.
2. **Key present but the provider is down** → the job fails loudly (exit 2) *before* touching `data/`;
   the last validated dataset keeps serving. A re-run uses `--replay` to work from cached payloads.
3. **Provider returns something structurally wrong** (half a standings table, a duplicate fixture) →
   the validation gate rejects it into `data/staging/<date>/` and the run stops. See `validate_data.py`.
4. **Provider permanently unsuitable** → API-Football is the drop-in replacement: same interface,
   different `sources/*.py`, quota managed by fetching once per gameweek instead of per day.

## Terms and attribution — what you may actually republish

Checked 3 October 2026. Terms change; re-read them before you rely on this.

* **Free tier = non-commercial.** football-data.org's own blog states the API is "only free for
  non-commercial use"; commercial use needs a paid plan (from €10/month).
* **Attribution is asked for.** Their FAQ asks for a visible credit in "a visible section of your
  application or website". This project therefore credits them in the dashboard footer and in
  `README.md` → Credits. A credit buried in a source comment would not satisfy that reading.
* **Raw responses are not redistributed here.** `data/raw/` (the payload cache) is gitignored, and so
  is `data/staging/`. What this repository commits is the derived dataset — results, tables and the
  model's own outputs. If you fork this and republish the raw feed itself, that is your call to
  justify, not something this project already has permission for.
* **The MIT licence covers the code, not the football.** `LICENSE` says so explicitly, because it is
  the sort of thing that is easy to assume and expensive to be wrong about.
* **Club marks.** Crests in the dashboard are abstract shields generated from club colours. Official
  badges and Premier League trademarks are not used, and the footer disclaims affiliation.

## What would change this decision

* Wanting player-level xG/xA (then a paid feed is the only honest route — see the xG document);
* needing live in-play data (TheSportsDB and API-Football both advertise it; football-data.org's
  free tier is near-real-time, not live);
* going commercial, at which point the licence question outranks every technical consideration.

## Ask

Nothing to decide unless you disagree with the source. To switch it on:

1. Register free at <https://www.football-data.org/client/register>;
2. `export FOOTBALL_DATA_ORG_TOKEN=...` (or set it as a host secret — DEPLOY.md §7);
3. `python3 update_week.py` — it will print `provider football-data.org` and fetch for real.

Without that key the project stays fully functional: `update_week.py --source local` is the manual
weekly path, and everything still validates, rebuilds, snapshots and scores.
