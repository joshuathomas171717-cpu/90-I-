# Operating NINETY+

For the part of a season that happens after launch. Everything here is about one property: **the site is
either true, or it says plainly that it is not.** A prediction site that serves last month's numbers with
confidence is worse than one that is visibly down, because the whole argument is that the record can be
checked.

Three commands answer almost every question:

```bash
python3 check_live.py                 # is the deployed site current? (exit 0 ok, 1 behind, 2 unreadable, 3 record tampered)
python3 update_week.py --dry-run       # what would this week's refresh do, without changing anything
python3 tests/run_tests.py -k weekly   # rehearse a whole week on a throwaway copy, commit and all
```

---

## 1. The weekly refresh

| | |
|---|---|
| Runs | Mondays 06:00 UTC (`0 6 * * 1`), plus manual dispatch |
| Workflow | `.github/workflows/weekly-update.yml` → "Weekly update" |
| Does | fetch → validate → promote → optional player refresh → rebuild → snapshot → lock → score → commit `data/` + `static/` → verify deployment |
| Commits as | `chore(data): weekly refresh <date>` |
| Deploys | Vercel rebuilds from the push. The last step waits for and verifies the deployed vintage and player-context fingerprint |
| Artifacts | `weekly-audit` — `data/raw/` and `data/staging/`, kept 30 days |

**With no `FOOTBALL_DATA_KEY` secret** the job falls back to the repository's own snapshot and promotes
nothing — it runs green and commits nothing. That is by design (a broken feed must never overwrite good
data) and it is also the most dangerous normal state this project has: from the outside, "worked fine,
nothing to do" and "has not updated in two months" look identical. `check_live.py` is what tells them
apart, and the page itself says **out of date** in its header when its data predates the last completed
gameweek.

### The website checks run even when nobody pushes

The independent **Site is current** workflow (`.github/workflows/site-current.yml`) is scheduled for
Mondays 08:00 UTC, two hours after the 06:00 refresh. Both schedules can be delayed by GitHub's queue;
they are not a real-time service. It holds no secret and writes nothing, and goes red with a readable
reason if the site is behind, unreadable or the published record is broken.

```bash
python3 tools/verify_deployment.py                   # committed vintage + player-context fingerprint vs live
python3 tools/verify_deployment.py --retries 6 --wait 30  # wait up to 3 minutes for a new Vercel build
```

The fingerprint matters when only player context changed: matching the matchweek and data date alone
cannot prove those updates landed. The first successful automated live refresh still needs a real
dispatch/results source; installing a schedule is not evidence that a scheduled run already worked.
The failing GitHub Pages workflow is separate from this Vercel deployment.

### Optional player sources do not control publication

`API_FOOTBALL_KEY` is an optional, separate free-provider secret. Missing/failed or partial player
pulls retain good files. The results key also fetches exact PL/UCL calendar timestamps; cup/national
calendars accept manual drops. A captured availability list says which clubs were checked, failed or
remain unknown. The snapshot and rebuilt player card use the same collection, rather than fetching
team news a second time after publication. Player-source changes keep the rebuild even when the
headline probabilities do not move.

Historical match backfills are opt-in (`player_history.py`), not part of this job. The player layer
stays context-only until a genuine temporal comparison is available; see
[player-model-card.md](player-model-card.md). Never use a season-total or post-match lineup as a
retrospective pre-kickoff feature.

### If the site is stale

```bash
python3 check_live.py           # prints the gameweek that is missing, and exits 1
```

Then, in order of preference:

1. **Set the key.** football-data.org (free, non-commercial): register, copy the token, then
   **Settings → Secrets and variables → Actions → New repository secret** named `FOOTBALL_DATA_KEY`.
   Nothing else needs changing — the provider is chosen automatically when the secret exists.
2. **Drop the results in by hand.** Write `data/provider_drop/gw07.json`:
   ```json
   {"results": [{"date": "2026-10-17", "matchweek": 7, "home": "ARS", "away": "LEE",
                 "home_goals": 2, "away_goals": 0}]}
   ```
   Push it, or dispatch the workflow with `provider` left empty. The local provider reads that directory
   and the same validation, promotion, scoring and commit path runs. The drop file is deliberate: it is
   the escape hatch that does not require an account.
3. **Check the run.** Actions → "Weekly update" → the last run. Failed at *validate* means the payload
   was refused and nothing was promoted (good — read `weekly-audit` for the offending row). Failed
   *after* promotion means the data changed and the site did not: re-run the workflow; the churn-discard
   step is idempotent and a second run commits only what is genuinely different.

### If the run is green but nothing was committed

Expected when no new results exist: the churn-discard step reverts `static/` and the six projected
datasets *together* when the rebuilt numbers match within tolerance, so library drift never becomes a
commit. A green run that promotes nothing for **two consecutive matchweeks** means the results are not
arriving: treat it as stale and follow the section above.

---

## 2. The record

The ledger (`data/ledger_2026_27.json`, mirrored to `/ledger.json` on the site) is the part that makes
the claims checkable, and it is only worth what its deadlines are worth.

* **Lock.** Every published gameweek is hashed and locked *before its first kickoff*. A lock is never
  rewritten; a changed publication appends a new lock with `supersedes`.
* **Score.** When results arrive, the gameweek is scored against the locked predictions. A corrected
  result moves the old entry to `history` and appends a chained revision — history is appended to, never
  edited.
* **Verify.**
  ```bash
  python3 score_ledger.py --verify          # recomputes every lock against data/snapshots/ and walks the chain
  python3 check_live.py                     # ...and checks the deployed ledger.json as a reader receives it
  ```

### If the ledger does not verify

Exit 3 means the published record was edited after it was written, or a snapshot no longer hashes to its
lock. This is the one failure that cannot be fixed by re-running anything.

1. **Do not "fix" the ledger.** Recomputing the hashes would destroy the only evidence that something
   happened, and the record is the product.
2. **Find out what changed.** `python3 score_ledger.py --verify` names the gameweek; `git log -p
   data/ledger_2026_27.json data/snapshots/` shows every commit that touched either file.
3. **Repair forward, in public.** Restore the snapshot from git (`git checkout <commit> --
   data/snapshots/gwNN.json`), which restores the lock's validity without touching the chain; if the
   ledger itself was edited, restore it and re-apply any legitimate scoring with
   `python3 score_ledger.py --score` so the correction lands as a new, chained revision.
4. **If it was a real publication change** (a late team-news edit, say), that is what the `supersedes`
   lock is for: `score_ledger.py --lock` appends the new hash rather than replacing the old one, and the
   receipts page shows both.

The tamper drills in `tests/test_ledger.py` are the specification: an edited published prediction, an
edited revision and a deleted revision must all be caught. If a repair path cannot be distinguished from
tampering by the verifier, the repair is wrong.

### If a lock was missed

`tests/test_wave11_liveness.py` fails if any shipped lock is dated at or after its gameweek's first
kickoff. If it fires, the affected gameweek's calls are **not** a prediction and must not be presented as
one: delete that lock rather than backdate it, and say so in the changelog. Backdating a lock to keep a
test green would make the whole record worthless.

---

## 3. The site

| Symptom | Check | Fix |
|---|---|---|
| Numbers look old | `python3 check_live.py` | Section 1. The header chip says "out of date" and names the gameweek |
| A page 404s on the deployed site but works locally | Vercel rewrites (12 of them in `vercel.json`) vs the local resolver | add the route to `vercel.json`, or let the derived static rule serve it locally — never a hand-kept list in `server.py` |
| The site is up but stale-looking (CSS/fonts) | everything is inlined; there are no external requests by design | a missing glyph means `tools/subset_fonts.py` needs re-running, not a CDN |
| A bad commit went out | `git log --oneline -5`, then Vercel → Deployments → *Promote to Production* on the previous good one | roll the site back first, then revert the commit (`git revert <sha>`) so the repository and the deployment agree |
| Social preview images are blank | `NT90_SITE_URL` repository variable is unset | set it to `https://90plus-cyan.vercel.app` — without it the canonicals are relative and no crawler can fetch the card |

**The one rule for changes:** `static/index.html` is generated. Edit `static/src/*` or the Python that
renders it, rebuild (`python3 run_all.py`), and commit both, or CI's page check will fail on the
mismatch.

---

## 4. The cadence

After the last match of a gameweek (the owner's job — the site does not do this part):

1. `python3 check_live.py` — did the refresh land, and does the record verify?
2. Read `docs/reviews/README.md`'s four-point checklist against the gameweek that just finished: were the
   calls locked before kickoff, did the probabilities move for a reason, did the misses have an
   explanation, is the changelog entry honest?
3. Write `docs/reviews/YYYY-MM-DD-MW<n>.md` and update `CHANGELOG.md` with the accuracy delta. A delta
   appears only where a blind replay was measured — never invent one.
4. React to the fixtures with the buttons on `/receipts`: they are stored in the reader's browser and sent
   nowhere. Passing them on means opening the pre-filled issue the page links to.

The first real test of this loop is the matchweek 6 review after 12 October 2026.

## 5. Every finished wave must reach GitHub and the website

The standing release procedure is [publishing.md](publishing.md): rebuild/test, credential/XSS checks,
stage and guard the prospective commit, commit, push, wait for Vercel and compare actual published
feature pages/data plus context/UI fingerprints. A successful push is not proof of a website update.
Only a known security risk is a reason to hold a finished release; explain the risk, fix/rotate any
exposed credential and rerun. An unfinished failing build must be repaired, not presented as done.

Future availability seals bind the exact capture to its prediction lock/revision chain. Never add a
current capture to an old lock to make receipts look complete. For MW6 the correct label is **not
recorded at lock**. New named-player scenario links carry explicit hypotheses, not injury diagnoses;
legacy links keep their old method and saved coefficients are never silently re-priced.

## 6. Career/Challenge game publication

`python3 playground.py` builds the self-contained `static/play.html` plus its code/data fingerprint.
Both normal and weekly rebuilds run it before the dashboard, which embeds that fingerprint. Never
revert generated game pages while keeping a changed `data/playground_manifest.json`; the weekly
change guard covers the manifest. The deployment verifier compares it even when forecast dates and
numbers do not change. Verify actual game-page bytes and play/resume/practice on Vercel after push.

Games are local, hypothetical worlds. They never write actual results or prediction locks. New data
must not replace an existing career's frozen world, and practice cannot rewrite real locked challenge
picks. No account/global leaderboard is provided; client saves/clocks are not independently trusted.
