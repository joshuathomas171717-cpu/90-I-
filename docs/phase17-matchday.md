# Phase 17 — the matchday is played, not skipped

6 October 2026. The owner's note on phase 16 was that the game was *too fast* and not interactive
enough: you chose settings, clicked, and got a result. This wave rebuilds the career loop around
decisions taken **during** a match and consequences that arrive **after** it.

## What is different now

| Before (v1) | Now (v2) |
|---|---|
| One button → a final score | Kick off → a ticking first half → **half time** → second half → full time |
| Nothing to do between kickoff and the result | A half-time instruction (stay calm / push / hold / press) **and** up to two substitutions |
| The score arrives unexplained | A decision report: what your call added or took away, and what the same world would have finished without it |
| The week ends when the ball stops | A manager's inbox with 1–4 decisions, each with a named, bounded effect |
| Formation of a habit: click again | Pressure, mood, budget, job offers and a rest/recover loop that carry into the next matchday |

Everything else that made phase 16 honest still holds: the world is frozen, the same world code and
the same decisions give the same score, and no simulated score ever becomes a real result, a prediction
or a ledger entry.

## The rules this wave added

* **The base score is never rerolled.** The full-time score is still the single draw phase 16 used.
  A half-time instruction can *add* or *remove* goals through a second, separate deterministic draw,
  bounded per match: each side's second-half mean moves by at most ±0.6 goals, so the swing on a given
  match is at most a few goals and usually none. `Stay calm` with no substitutions is byte-identical to
  phase 16's result — which is why an old save replays to exactly the scores its owner saw.
* **Substitutions are real but small.** A forward or midfielder brought on raises your second-half mean
  by ~0.12 goals; a goalkeeper or defender lowers the opponent's by ~0.10. At most two per match, only
  your own tracked players, and a rested player cannot be brought on.
* **Scorers respect your decisions.** Goal minutes come from the world seed and fixture id; the scorer
  is drawn from your tracked non-goalkeeper players, excluding anyone you rested. A player you rested
  will not appear in the goal feed.
* **Half-time statistics are honest.** Possession, shots and shots on target are derived from the same
  lambdas as the score and clipped to sane bands (32–68% possession, ≤12 on target). They are a
  description of the simulated match, not a licensed feed.
* **Inbox effects are bounded, disclosed and replayable.** Replies move at most +4 fitness, +6 credits,
  or a ±3% next-match modifier inside the existing ±8% cap. A "defensive drills" reply reduces the
  conceded-goal rate (`defence: -3`, a mixed sign) rather than handing out a free attacking bonus. Job
  offers swap your club, reset pressure and keep the same frozen fixtures.
* **The inbox is deterministic and part of the save.** Items are a function of the state *after* each
  match, so the journal stores the replies and `restore()` rebuilds the same week's inbox and replays
  them. A save that names an item that was never open, or an instruction that does not exist, is
  refused rather than silently accepted.
* **Phase-16 saves still open.** They are flagged as coming from the earlier rules, keep their recorded
  results, and use half-time decisions from the next matchday onward.

## The loop, in the reader's words

1. **Briefing** — fixture, kickoff window, weather, crowd, your form, your plan, who is available.
2. **First half** — the clock runs, the feed builds, goals land in minute order with a named scorer.
3. **Half time** — the match *stops* and asks you a question, with the score and the lead in front of you.
   Push, hold, press or stay calm; bring up to two players on. The panel says what each option does.
4. **Second half** — the consequences of your call play out; a second-half goal is tagged as such.
5. **Full time** — the decision report compares your call with the same world played without it, then
   the form, momentum, fitness and credit row moves.
6. **The inbox** — the fallout: the dressing room, a player whose performance is being talked about,
   the analyst's note about conceding after the break, the board's money, or a rival asking about you.

`Skip match (no instruction)`, `Fast-forward 3 weeks` and `Skip the animation` remain, because phase 16
users are allowed to want the fast path — but they are now the shortcut, not the game.

## Evidence

* Full pipeline: **411 passed, 0 failed, 0 skipped** (26 new phase-17 tests plus the phase-16 suite
  still green against the v2 engine; 45 of those cover the phase-16 contract unchanged).
* New tests cover: a calm no-sub half time reproducing phase 16 exactly; bounded, always-deterministic
  instruction deltas; the base-plus-delta identity; identical sessions from identical inputs; two-sub
  and own-club limits; direction of substitution effects; first-half goals confined to 1–45′ and to the
  half's share of the score; rested players never scoring; `beginMatch`/`firstHalf` returning null with
  no fixture left; inbox size, contents and effect bounds; a defensive drill not acting as an attack
  bonus; job offers moving club; boost expiry after exactly one matchday; inbox replay through
  `restore`, and rejection of invented items/instructions; a phase-16 save still opening.
* Real Chromium (dev-only harness, `tests/a11y/wave17.mjs`): a real ticking first half reaching half
  time; season controls locked while a match is live; instruction + substitution recorded; full-time
  report containing the comparison and no raw object text; inbox reply applied and its item cleared;
  reload replaying the decided match identically; the reduced-motion path stopping at the same decision
  points without the clock; the skip path still completing matchdays; 1440px and 390px with no document
  overflow; no runtime errors and no external requests; **0 automated WCAG A/AA violations** on the live
  match stage and inbox (one incomplete gradient contrast check recorded, not claimed as certification).
* Official predictions, the MW6 ledger/snapshot and `LICENSE` are untouched: the game writes only its
  own local save and its own generated page. Game code/data get a publication fingerprint so a
  game-only change is still detected on the live site.

## Reproduce

```bash
python3 run_all.py
python3 tests/run_tests.py -k wave17
python3 tools/publication_gate.py --staged
PORT=8000 python3 server.py
# dev-only browser harness, second terminal:
bash tools/setup_browser_tools.sh
NT90_PLAYWRIGHT_MODULES=/tmp/a11y/node_modules node tests/a11y/wave17.mjs
```

No account, API key, paid service, network call or runtime dependency was added. Rules are game
assumptions; the historical player-input gate for automatic forecasts remains closed, and nothing here
changes a published prediction.
