# Publishing this to GitHub

Copy-paste, in order. Nothing here needs a hosting account or a domain, and nothing here has been
run against your account — these are the commands to run yourself.

## 1. Create the repository

On github.com: **New repository** → name it `ninety-plus-pl-predictor` → **no** README, no
`.gitignore`, no licence (this project already has all three; letting GitHub create them means a
merge conflict on the first push).

## 2. Push

From the folder you extracted this into (it should be named `ninety-plus-pl-predictor`):

```bash
cd ninety-plus-pl-predictor
git init
git add .
git commit -m "NINETY+ Premier League predictor"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/ninety-plus-pl-predictor.git
git push -u origin main
```

Check what you are about to publish first — it is a good habit and takes two seconds:

```bash
git status --short          # nothing unexpected, and no .env / artifacts/
git ls-files | wc -l        # expect ~55 files
```

`artifacts/` (8 MB of rebuildable model cache) and `data/raw/` (fetched provider payloads) are
gitignored on purpose. `data/*.csv` and `static/index.html` **are** committed: the data is the source
of truth, and the built page is what lets someone open the project without running anything.

## 3. A free public URL (optional)

GitHub Pages serves the dashboard with no server at all, because `static/index.html` is fully
self-contained — fonts and crests are inlined, there are zero external requests.

This repo ships `.github/workflows/pages.yml`, so it is one setting:

1. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
2. Push to `main` (or run the workflow by hand from the Actions tab).

The site lands at `https://YOUR-USERNAME.github.io/ninety-plus-pl-predictor/`.

**One honest caveat:** Pages serves a static file, so there is no Python API behind it. The dashboard
detects that and falls back to its in-browser engine — everything still works, but the What-If tab
runs the client-side Monte Carlo rather than the server one, and the header says "offline model"
instead of "live engine". For a first public version that is the right trade: no server, no bill, no
cold start.

To get the live engine as well, deploy the container (`DEPLOY.md` §5 Fly.io or §6 Render), then set
`NT90_API_BASE` in the page build to that URL — see the note at the bottom of DEPLOY.md.

## 4. Keep it current, for free

`.github/workflows/weekly.yml` already does the weekly loop — fetch, validate, promote, rebuild,
snapshot, score, commit — every Monday at 06:00 UTC. It only needs one thing: a repository secret.

**Settings → Secrets and variables → Actions → New repository secret:**

| Secret | Required? | What it does |
|---|---|---|
| `FOOTBALL_DATA_ORG_TOKEN` | optional | Live results. Without it the job runs the local path, which validates the committed dataset and rebuilds — useful, but it will not learn new results. |
| `NT90_ALERT_WEBHOOK` | optional | Slack/Discord webhook for "rejected", "crashed" or "published". |

The job is safe to enable immediately: it refuses to promote a dataset that fails any of the 11
validation checks, exits non-zero, and leaves the repository untouched. `Run workflow` in the Actions
tab triggers a **dry run** by hand — it fetches and validates and tells you what it would have done
without changing anything.

Pages redeploys automatically after the weekly commit (`pages.yml` also triggers on the weekly
workflow finishing), so the published site tracks the season without you touching it.

## 5. Before you make it public — the checklist

- [x] **`.gitignore`** covers `__pycache__/`, `*.pyc`, `.env`, `.venv/`, `.DS_Store`, `artifacts/`,
      `data/raw/`, `data/staging/`.
- [x] **`LICENSE`** (MIT) — without one, nobody is legally allowed to reuse the code.
- [x] **No keys in the tree.** `.env` is gitignored, `.env.example` documents what goes in it, and
      `tests/test_repo_hygiene.py` fails the test suite if a token-looking string appears in a
      tracked file.
- [x] **No absolute paths.** `tests/test_portability.py` guards this — the pipeline runs from any
      folder on any machine.
- [x] **Credits.** The dashboard footer and `README.md` carry the attribution the data sources ask
      for, and `LICENSE` states plainly that the licence covers the code and not the football data.
- [x] **Crests are ours.** Abstract SVG shields drawn from club colours. No official badges, no
      Premier League marks — those are trademarks and would not be yours to redistribute.

## 6. What "public" changes about the server

Nothing in the code, but two things about the world: a public URL gets scanned, and a public URL gets
crawled. Both are already accounted for:

* `/api/simulate` is the only expensive route and it is rate-limited per IP, cached by scenario, and
  capped at `NT90_SIM_CONCURRENCY` simultaneous runs (`docs/capacity.md` has the measured numbers).
* `static/robots.txt` already asks crawlers to keep out of `/api/` while leaving the dashboard
  indexable, and the Python server serves it at `/robots.txt` too. Change it if you'd rather the API
  were discoverable.
