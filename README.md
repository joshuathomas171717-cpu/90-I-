# NINETY+ — Premier League 2026–27 Machine Learning Predictor

A dark, broadcast-grade prediction dashboard — **NINETY+** — on top of a full machine-learning
pipeline that predicts the **2026–27 Premier League season** from live state (Matchweek 5 complete, 2 October 2026): final table, title/relegation probabilities, the **Golden Boot**, the **Playmaker award (most assists)**, the **Golden Glove (clean sheets)**, Player of the Season, individual fixture scorelines and a **"what-if" simulator** for injuries, form swings and points deductions.

---

## Quick start

```bash
cd ninety-plus-pl-predictor      # or whatever this repo is called where you cloned it
                                # (the GitHub repo is github.com/joshuathomas171717-cpu/90-I-)

# everything in one command (data gate → calendar validation → datasets → models → backtest → dashboard)
python3 run_all.py

# ...or step by step:
python3 fixtures_official.py   # 1. validates the official 2026-27 calendar (all 380 pairings, MW1-MW38)
python3 data_builder.py        # 2. datasets: 380 matches of 2025-26, 50 played 2026-27, 330 remaining fixtures, 52 players
python3 ml_engine.py           # 3. loads the model artifact cache (0.02s) or trains once (4.5s), exports CSV/JSON
python3 backtest.py            # 4. replays the whole 2025-26 season for out-of-sample scoring
python3 build_dashboard.py     # 5. regenerates static/index.html

# 6. serve the interactive dashboard + live prediction API
PORT=8000 python3 server.py     # → http://localhost:8000  (binds in ~3ms, engine warms in ~1s)
```

`run_all.py` **gates the build on the data**: `validate_data.py` must pass (20 clubs, 380 fixtures,
the stored table reproduced from the results) before anything downstream runs. `--retrain` ignores the
artifact cache and trains from scratch; `server.py --preload` builds the engine before opening the port. Deployment (Docker, Fly.io, Render, logs, rollback, uptime
checks) is documented in [DEPLOY.md](DEPLOY.md).

Publishing it, or keeping a deployed copy current for free, is covered in
[PUBLISH.md](PUBLISH.md) — including a static GitHub Pages URL and the scheduled weekly refresh.

### Tests

```bash
python3 tests/run_tests.py      # 90 checks, no test dependencies at all — open this one by name
pytest -m "not slow"            # the same suite under pytest, if you prefer it (requirements-dev.txt)
```

The suite is written to run on a bare interpreter, so `requirements.txt` carries only the pipeline's
own dependencies and pytest lives in `requirements-dev.txt`. Two checks are worth knowing about
because they will stop a build: `tests/test_golden.py` freezes the headline numbers, and
`check_page_current.py` (the last step of `run_all.py`) fails if the published page no longer carries
the numbers the committed dataset describes.

`static/index.html` is **self-contained**: fonts are embedded as base64 WOFF2, club crests are generated
inline as SVG, and there are no external requests at all — so it renders identically offline, inside
sandboxed previews, and from the server. When the Python server *is* reachable the front-end detects it,
labels itself "live engine", and re-renders with the fresher API payload — falling back to a client-side
structural Monte Carlo otherwise.

### Front-end source layout

The UI is compiled from small parts into one file — edit a part, re-run `build_dashboard.py`:

```
static/src/
├── fonts.css     # Archivo (display), Inter (body), JetBrains Mono (numbers) — base64 embedded
├── theme.css     # design tokens: surfaces, accents, elevation, motion curves, responsive rules
├── app.html      # the shell: header, six views, panels, tabs
├── core.js       # data layer, model maths (λ / Dixon-Coles / Monte Carlo), scenario state, API bridge
├── motion.js     # counters, bar/ring fills, scroll-driven reveals, tab choreography
└── render.js     # every view, including 20-club crest generator and the H2H/backtest visuals
```

---

## Keeping it current — the weekly loop

The season moves; the model moves with it. One command does the whole weekly cycle:

```bash
python3 update_week.py --dry-run      # fetch + validate, print what WOULD change, touch nothing
python3 update_week.py                # promote, rebuild the model, snapshot the gameweek, score it
```

fetch → stage → **validate (11 checks)** → promote → ledger score → rebuild → snapshot `data/snapshots/gwNN.json`.

* **A bad pull cannot reach the model.** Results that fail validation land in `data/staging/<date>/`
  with a `.REJECTED.md` and the run exits non-zero; `data/` is untouched and the last good snapshot
  keeps serving.
* **Results survive rebuilds.** `data_builder.py` merges promoted results instead of regenerating
  its own match list, and recounts the table and Elo from the results via `standings.py` — the same
  code the weekly job uses, so both writers agree exactly.
* **It scores itself.** Every completed gameweek is graded against the prediction that was published
  for it before kick-off (hit rate + RPS) in `data/ledger_2026_27.json`; the dashboard's Record view
  reads that ledger.
* **The header follows the data.** Every "Matchweek N" label comes from the payload, so after a
  promotion the page says MW7 because it *is* MW7.

Two ways to feed it (details in [docs/data-sources.md](docs/data-sources.md)):

```bash
python3 update_week.py                            # auto: live if FOOTBALL_DATA_ORG_TOKEN is set, else local
python3 update_week.py --source local             # the pipeline's own CSVs / data/provider_drop/*.json
python3 update_week.py --replay                   # work from cached payloads, no network
```

A scheduled workflow ([.github/workflows/weekly.yml](.github/workflows/weekly.yml), Mondays 06:00 UTC)
runs it in CI and commits only when the gate passes. xG is a **manual, dated** input by design — see
[docs/xg-strategy.md](docs/xg-strategy.md) for why and for the upgrade path.

## Production behaviour — measured, not asserted (Wave 3)

The server is hardened and its limits are published, because "it felt fast" is not a capacity plan.

| | |
|---|---|
| **Transport** | The 500 KB dashboard goes out gzipped (**508 KB → 192 KB**) with a strong `ETag`, so a returning visitor revalidates in **1.2 ms** and transfers nothing. Security headers ride on every response, including error pages. CORS is an allowlist, not `*`. |
| **Latency** | `GET /` p50 **2.1 ms** · its 304 p50 **1.2 ms** · `/api/baseline` p50 **1.8 ms** — 3,500–5,700 req/s on two cores. |
| **Simulations** | Guarded: schema-validated payloads, an `n_sims` ceiling, a per-IP token bucket, an LRU over finished scenarios, and a concurrency cap that turns an OOM kill into a queue. A 48-way burst completed **192/192 with zero errors** and the process survived. |
| **Observability** | `GET /api/stats` publishes latency percentiles, cache hit rate, in-flight simulations, rate-limit rejections and RSS. |
| **Load test** | `python3 loadtest.py --url http://127.0.0.1:PORT` — phases for page, revalidation, baseline, cold simulations, cached simulations and an overload burst. Numbers and the four fixed-cost bugs it found: [docs/capacity.md](docs/capacity.md). |
| **CI** | [.github/workflows/ci.yml](.github/workflows/ci.yml) runs install → data gate → full pipeline → tests → "is the committed page current" → server smoke test on every push. |
| **Alerts** | The weekly job exits non-zero on failure and posts to `NT90_ALERT_WEBHOOK` (Slack/Discord) — a broken cron that fails silently looks exactly like a working one. |

Four real bugs came out of load-testing that no unit test would have found, each now fixed and pinned:
per-request gzip (111 ms → 2.1 ms), per-request re-serialisation of the baseline (72 ms → 1.8 ms),
**Nagle + delayed ACK adding a flat 44 ms to every JSON response**, and the stdlib's accept backlog of
5 turning a burst into connection errors.

## What the model is made of

| Layer | Implementation |
|---|---|
| **Goal model** | Poisson GLM (L2, α = 0.8) blended 55/45 with `HistGradientBoostingRegressor(loss="poisson", depth=3)` for home and away goals |
| **Structural prior** | attack × defence matchup rates (xG/90 vs opponent xGA/90), home-fortress multiplier — blended 60/40 with the ML layer |
| **Scoreline grid** | Dixon-Coles (1997) low-score correction (ρ = −0.11) on a 7×7 bivariate Poisson grid |
| **Outcome layer** | soft-voting 1X2 ensemble: logistic regression 45% + random forest 30% + gradient boosting 25% (also powers feature importance) |
| **Calibration** | λ scaled so the league averages ≈ 2.86 goals per game (live 2026-27 rate: 2.82) |
| **Season engine** | vectorised Monte Carlo over all 330 remaining fixtures × N seasons, ranked by points → goal difference → goals for |
| **Player engine** | Gamma-Poisson (overdispersed) goal/assist sampling with availability, penalty duty, conversion skill and team-strength multipliers; binomial clean-sheet draws for goalkeepers |
| **Training data** | all 380 matches of 2025-26 + all 50 played 2026-27 matches (current season weighted 1.6×) = **430 real matches** |
| **Validation** | 5-fold stratified CV → RPS 0.204 · Brier 0.609 · log-loss 1.012 · 1X2 accuracy 49.8% (out-of-fold) |

### The nine engineered match features

1. Elo & tactical strength differential (home-adjusted)
2. Home attack (xG/90) vs away defence (xGA/90)
3. Away attack vs home defence
4. Squad depth / market value log-ratio
5. Set-piece threat differential
6. High-pressing intensity (PPDA differential)
7. UEFA midweek congestion & fatigue (UCL / UEL / UECL)
8. Stadium home-fortress advantage
9. Current-season 5-match form momentum (PPG)

Player side: xG/90, xA/90, key passes/90, shot conversion, penalty duty, minutes probability, injury games out, and for keepers post-shot xG minus goals conceded (PSxG−GA) and save percentage.

---

## Baseline projections (5,000 simulated seasons, 2 Oct 2026)

**Title race**

| # | Club | Current | Projected | Title % |
|---|---|---|---|---|
| 1 | Manchester City | 15 pts (5-0-0) | **82.4** | 52.5% |
| 2 | Arsenal | 12 pts | **81.2** | 43.1% |
| 3 | Brighton & Hove Albion | 10 pts | 67.4 | 2.1% |
| 4 | Liverpool | 9 pts | 67.0 | 2.0% |
| 5 | Brentford | 9 pts | 58.4 | 0.1% |

**Bottom three (relegation probability):** Coventry City 88.2% · Ipswich Town 40.0% · Fulham 36.9% · Tottenham Hotspur 31.0%

**Awards**

| Award | Winner | Projection | Win probability |
|---|---|---|---|
| Golden Boot | Erling Haaland (MCI) | 29.4 goals | 65.9% |
| Playmaker (assists) | Pascal Groß (BHA) | 13.8 assists | 20.4% |
| Golden Glove | David Raya (ARS) | 18.5 clean sheets | 70.0% |
| Player of the Season | Bukayo Saka (ARS) | — | composite index |

---

## Backtest — the 2025-26 season replayed blind

`backtest.py` predicts all 380 matches of **2025-26** using **only information available before that season kicked off**: the 2024-25 final table (points, GF, GA for all 20 clubs) plus fixed hyperparameters drawn from Premier League history (home advantage 1.12×, Dixon-Coles ρ = −0.11, promoted-club convention 0.78× attack / 1.28× defence). No 2025-26 result, form or table is used to build the ratings or tune the constants — every one of the 380 predictions is genuinely out-of-sample.

| Forecaster | 1X2 accuracy | RPS ↓ | Brier ↓ | Log-loss ↓ |
|---|---|---|---|---|
| **This model** | **46.3%** | **0.2184** | **0.6372** | **1.0561** |
| Home-win base rates (45/24/31) | 42.6% | 0.2276 | 0.6551 | 1.0824 |
| Prior-season-table favourite | 43.4% | 0.2396 | 0.6791 | 1.1503 |
| Uniform 1/3 each | 42.6% | 0.2322 | 0.6667 | 1.0986 |

**Skill vs the strongest baseline (prior-season table): RPS +8.8%, Brier +6.2%, log-loss +8.2%.**

Table projection: Spearman ρ **0.566**, points MAE **10.3**, position MAE **4.0 places**, 45% of clubs within ±2 positions.
Champion called as Liverpool; Arsenal won it. Top-4 overlap 2/4. Actual relegated clubs (West Ham, Burnley, Wolves) all finished in the model's projected bottom six — but promoted Sunderland (projected 19th, finished 7th) is the model's clear blind spot, because a promoted-club prior cannot see a £150m summer rebuild.

That is the point of showing it: this is a **pre-season, cold-start** replay, which is deliberately harder than the live 2026-27 forecasts (those also carry five matchweeks of current-season data and re-calibrate to the live scoring rate). Treat ~46% as a floor, not the headline model's expected accuracy. Full report: `data/backtest_2025_26.json` and the dashboard's **Backtest** tab.

---

## Fixture calendar — official, not approximated

`fixtures_official.py` encodes the **official Premier League 2026-27 fixture release** (19 June 2026): all 330 remaining fixtures with real matchweek numbers and dates, MW6 (10–12 October 2026) through MW38 (30 May 2027). `validate_official_fixtures()` proves the calendar partitions all 380 home/away pairings exactly once, that the 50 played matches reproduce the published Matchweek 5 table (141 goals) precisely, and derives the final matchweek by elimination. Run it standalone any time to re-verify.

---

## The interface — six views

- **Matchweek** — a decisive hero ("Title race down to 1.2 points"), the headline awards, then every MW6 fixture as a card: club-coloured crests and rim glow, a three-way probability bar that fills on reveal, a certainty chip (*banker* / *edge* / *lean* / *toss-up*) so you can read the shape of a gameweek without reading a number, most likely scoreline and xG. A **Model pulse** panel shows the out-of-sample record as a tick strip where every correct call lights up. Clicking any card opens it in the Duel.
- **Table** — the full 20-club forecast: points ticking up to value, 80% ranges, finish-spread ribbons, then top-four and relegation market bars and top-six rings.
- **Awards** — Golden Boot, Playmaker, Golden Glove and Player of the Season, each with a podium, full race table (verified last-season figures marked ✓, estimates marked ~) and the inputs behind the board.
- **Duel** — two clubs head to head: a three-way split, a **stat battle** of six tug-of-war bars (attack, defence, Elo, form, squad value, home factor), the Dixon-Coles scoreline heat map with the mode highlighted, derived markets, real head-to-head results and both clubs' season context.
- **What-If** — injuries (0–33 games out), form sliders (±25% attack/defence), points deductions and forced scorelines, then re-simulate and read the deltas.
- **Model** — the metrics, the RPS comparison chart, a calibration plot, feature importance, and the full 2025–26 blind replay: rolling accuracy curve, a projected-vs-actual dumbbell for all 20 clubs, the baseline scoreboard and the honest limitations.

---

## Files

```
ninety-plus-pl-predictor/
├── run_all.py                 # one-command rebuild of the whole pipeline
├── fixtures_official.py       # official 2026-27 calendar (MW6-MW38, real dates) + validator
├── data_builder.py            # club metadata, 2025-26 results matrix, live 2026-27 state, players
├── ml_engine.py               # feature engineering, model training, CV, Monte Carlo, player awards
├── backtest.py                # leakage-free 2025-26 replay + scoring vs baselines
├── build_dashboard.py         # compiles payload + static/src/* into the single-file dashboard
├── check_page_current.py      # gate: is the published page the page the committed data describes?
├── server.py                  # threaded HTTP server: JSON API, /healthz + /readyz, background warm-up
├── Dockerfile                 # two-stage image, non-root, pre-warms the model cache at build time
├── fly.toml · render.yaml     # host configs; both gate traffic on /readyz
├── DEPLOY.md                  # deploy runbook: cold-start numbers, env vars, rollback, uptime check
├── artifacts/                 # model artifact cache (gitignored, rebuilt on demand)
├── static/
│   ├── src/                   # front-end source (fonts, theme, shell, core, motion, render)
│   └── index.html             # the built dashboard (open directly or via the server)
└── data/
    ├── matches_2025_26.csv                 # 380 training matches
    ├── matches_2026_27_played.csv          # 50 played matches, MW1–MW5
    ├── fixtures_2026_27_remaining.csv      # 330 remaining fixtures
    ├── teams_2026_27.csv                   # club ratings & live table state
    ├── players_2026_27.csv                 # 52 players (scorers, creators, keepers)
    ├── projected_table_2026_27.csv
    ├── projected_golden_boot_2026_27.csv
    ├── projected_playmaker_2026_27.csv
    ├── projected_golden_glove_2026_27.csv
    ├── predictions_2026_27_summary.json    # complete payload
    └── backtest_2025_26.json                # full 2025-26 replay report (metrics, table, calibration)
```

### API

| Endpoint | Method | Purpose |
|---|---|---|
| `/healthz` | GET | liveness — 200 whenever the process is up (never touches the engine) |
| `/readyz` | GET | readiness — 200 once the model can serve, 503 while warming, with state in the body |
| `/api/baseline` | GET | full baseline projection payload (served from the disk snapshot while warming) |
| `/api/fixture?home=ARS&away=MCI` | GET | single-fixture prediction (λ, 1X2, scoreline grid, features) |
| `/api/backtest` | GET | the 2025-26 replay report (metrics, table-level accuracy, calibration) |
| `/api/simulate` | POST | `{"n_sims":5000,"player_injuries":{"haaland":12},"team_boosts":{"ARS":{"attack":8,"defence":5}},"points_deductions":{"MCI":10},"custom_scores":{"MCI-ARS":[2,1]}}` |
| `/api/download/<file>` | GET | download any dataset in `data/` |

Every response passes through a `json_safe()` sanitiser that replaces non-finite floats with `null`.
Python's `json` happily emits bare `NaN`, which is **not valid JSON** — browsers reject the whole
payload and the dashboard silently drops to its offline engine. The sanitizer is applied in
`ml_engine.py`, `server.py` and `build_dashboard.py`, and the embedded payload is written with
`allow_nan=False` so a regression fails the build instead of degrading the app quietly.

### Warm starts

Training plus the baseline Monte Carlo is ~4.5s of a ~7.3s cold start, and every input is
deterministic — so `ml_engine.py` hashes its five CSVs *and its own source* into a cache key and stores
the trained models with the baseline payload in `artifacts/`. The engine then boots in **0.02s**, and
`server.py` imports it inside a warm-up thread, which means the port opens in **~3ms** and serves the
dashboard plus `/api/baseline` from the last good snapshot until the model is live. A visitor never
sees an empty page, and a failed warm-up degrades to the snapshot instead of a 500.

---

## Credits and licences

**Code:** MIT — see [LICENSE](LICENSE). Use it, fork it, ship it.

**Data:** the committed dataset (`data/*.csv`) was compiled from publicly published Premier League
results, tables and squad information for commentary and analysis. Live mode adds the
[football-data.org](https://www.football-data.org/) API, whose free tier is for **non-commercial** use
and asks for a visible credit — the dashboard footer carries one, and so does this file. Its raw
responses are never committed (`data/raw/` is gitignored); what ships is derived, not redistributed.

**The licence covers the code, not the football.** Match data, club names and club colours remain
subject to their own terms and owners. `LICENSE` says this explicitly, and
[docs/data-sources.md](docs/data-sources.md) records what each source was found to allow.

**Crests:** abstract shields drawn at build time as inline SVG from each club's colours
(`build_dashboard.py`). No official badges, no Premier League marks, no affiliation or endorsement
claimed.

**Model:** the Dixon-Coles / Poisson goal model, gradient-boosted scoreline calibration and Elo-style
ratings are standard published methods, implemented here from scratch on numpy + scikit-learn.

## Honest limitations

- Five matches is a tiny sample: the model deliberately shrinks current form toward last season's baseline (85/15) and long-run tactical ratings, and recalibrates league scoring to the observed rate.
- It cannot know January signings, sackings, dressing-room effects or fixture rearrangements — that's what the What-If simulator is for.
- The remaining 330 fixtures use the **official** published calendar (real matchweek numbers and dates); kick-off times are the standard weekend/midweek slots and individual TV rearrangements will move a handful of them.
- The blind 2025-26 backtest shows the model's real-world floor is ~46% 1X2 accuracy and a table rank correlation of ~0.57 over a full pre-season horizon — club-level rating error (especially for promoted sides) is the dominant source of that, not the match model.
- Player last-season figures are verified published totals for goal/assist leaders (marked ✓ in the dashboard) and model estimates for the rest (marked ~).
- Projections are analysis, not betting advice; a 52% title probability means "more likely than not", not "certain".
