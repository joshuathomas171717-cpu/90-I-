# NINETY+ — start here

Predicts the rest of the **2026–27 Premier League season** from live state (Matchweek 5 complete):
final table, title/relegation probabilities, Golden Boot, assists, clean sheets, Player of the Season,
per-fixture scorelines, and a what-if simulator for injuries, form swings and points deductions.

## 1. Just want to look at it?

Open **`static/index.html`** in any browser. That's the whole dashboard in one file — fonts and club
crests are embedded, there are no external requests, and it works with no internet connection.
It ships with the model's output baked in, plus a client-side Monte Carlo so the What-If tab works offline.

## 2. Want the live Python engine (richer predictions, real API)?

```bash
pip install -r requirements.txt

python3 run_all.py          # ~10s: validate fixtures → build data → train → backtest → build dashboard
PORT=8000 python3 server.py # then open http://localhost:8000  (health: /healthz, /readyz)
```

The page auto-detects the server and switches from "offline preview" to **live engine**.
Rebuild with `python3 build_dashboard.py` after changing anything in `static/src/`.

The site also ships as real pages: `static/gameweek/mw6.html`, `static/club/arsenal.html`,
`static/table.html` and `static/model.html` are generated HTML with the numbers as text, for search
engines and for anyone who wants to read rather than click. `python3 site_pages.py` regenerates them.

To run the checks: `python3 tests/run_tests.py` — no test dependencies needed. If you would rather use
pytest, `pip install -r requirements-dev.txt` first. `run_all.py` already runs the suite, and finishes
by checking that the published page carries the numbers the committed dataset describes.

## 3. Keeping it up to date

```bash
python3 update_week.py --dry-run   # see what would change — fetches, validates, writes nothing
python3 update_week.py             # promote the results, retrain, snapshot the gameweek, score it
```

The dataset gate runs first, so a bad pull is rejected into `data/staging/` and never reaches the model.
Full detail: [README.md](README.md#keeping-it-current--the-weekly-loop).

## 4. Individual pieces

| Command | What it does |
|---|---|
| `python3 fixtures_official.py` | Validates the official 2026–27 calendar (380 pairings, MW1–MW38) |
| `python3 data_builder.py` | Builds `data/*.csv` — matches, fixtures, club ratings, 52 players |
| `python3 ml_engine.py` | Trains the models, runs the 5,000-season Monte Carlo, exports projections |
| `python3 backtest.py` | Replays all 380 matches of 2025–26 with pre-season information only |
| `python3 build_dashboard.py` | Compiles `static/src/*` + payload → `static/index.html` |

## Headline baseline (5,000 simulated seasons, 2 Oct 2026)

- **Title:** Man City 82.4 pts (52.5%) · Arsenal 81.2 (43.1%) · Brighton 67.4 (2.1%)
- **Relegation:** Coventry 88.2% · Ipswich 40.0% · Fulham 36.9% · Tottenham 31.0%
- **Golden Boot:** Haaland 29.4 (65.9%) — **Assists:** Pascal Groß 13.8 (20.7%) — **Glove:** David Raya 18.5 CS (70.0%)
- **Blind 2025–26 replay:** 46.3% 1X2 accuracy, +8.8% RPS skill vs the prior-table baseline

Honest limitations are in `README.md` and on the dashboard's Model tab — read the backtest before
trusting a number. This is analysis, not betting advice.

---

**Publishing or updating this?** [PUBLISH.md](PUBLISH.md) has the copy-paste commands for GitHub
(including a free public URL via Pages), and [LICENSE](LICENSE) explains what the MIT licence does and
does not cover — the code is yours to reuse, the football data is not ours to give away.

## Two pages for a reader who has never seen this before

Once the server is running, `http://localhost:8000/method.html` explains how the model works, what it
scores on a season it has never seen, and where it fails. `http://localhost:8000/privacy.html` says what
the site stores, which is nothing. Both are generated from the data at build time, like every other
page in `static/`.
