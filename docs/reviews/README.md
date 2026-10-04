# Gameweek reviews

One review per gameweek, published after the results land. This folder is the other half of
[the ledger](../../score_ledger.py): the ledger records *what* the model said and what happened, and
a review is where that gets read for meaning — which misses were variance and which look like a
pattern the model does not know about yet.

Reviews are dated and never rewritten. If a later gameweek overturns a conclusion, the new review
says so and links back; it does not edit the old one.

## The cadence

**Weekly, after the last match of the gameweek**, and it takes about ten minutes because the
mechanical parts are already done:

1. `python3 score_ledger.py --score` — appends the completed gameweek to the ledger.
2. `python3 score_ledger.py --verify` — confirms every lock still matches its published snapshot.
3. Read the new entry against the checklist below and write it up as `docs/reviews/YYYY-MM-DD-MW{N}.md`.
4. If the review concludes something must change, the change goes in [`CHANGELOG.md`](../../CHANGELOG.md)
   as a new version with its own measured delta — not as a silent edit to the model.

The reactions on the [receipts page](../receipts) are an input to step 3, not a substitute for it:
they tell you which calls annoyed people, which is a decent proxy for which calls were surprising,
and surprise is worth investigating. They are not a vote on whether the model is right.

## The checklist

For each completed gameweek, look at four things. Three of them are about *calibration* (does 40%
mean 40%?) and only one is about accuracy (did the favourite win?), because with ten matches a week
accuracy is mostly noise and calibration is not.

| Check | What it catches | What would be worrying |
|---|---|---|
| **Draw calibration** | The model's known bias: draws are rarely its single most likely outcome, so it can under-predict them while still being well calibrated. Track whether a stated 25% draw actually lands about a quarter of the time. | Draws landing well below their stated probability across 40+ matches. |
| **Confidence bands** | Overconfidence at the top, timidity in the middle. Group calls by stated probability (35–45, 45–55, 55–65, 65%+) and compare stated with observed. | The 65%+ bucket landing under 55%, or the 35–45% bucket landing over 50%. |
| **Home/away/outcome splits** | A systematic lean in one direction — a home-advantage factor that is too strong, or promoted-club factors that do not transfer. | Home calls at a materially different rate from the league's own home-win base rate. |
| **The modal scoreline** | The scoreline column is the mode of the goal distribution, which is often 1-1 even in a match that ends 3-0. It is a summary of the distribution, not a second prediction. | Using the scoreline as evidence of confidence. If it is never close, it is decoration and the page should say so. |

## Template

```markdown
# Matchweek N — <date>

**Ledger**: <x>/10 correct, mean RPS <r>. Season: <x>/<y> (<p>%), mean RPS <r>.
**Lock**: <previous gameweek> was hashed as <sha256 prefix> before kickoff; `--verify` passes.

## What happened
The calls that landed, the calls that did not, and whether the results were close.

## What it means
Against the checklist above: any drift in a confidence band, the draw rate, or a club split.
Explicitly: is this variance or signal? Both answers are acceptable; an unexplained answer is not.

## What changes
Either "nothing — variance" or the specific change, its own measured effect, and the CHANGELOG entry.

## Carried forward
Hypotheses that this gameweek could not settle, with the number of matches still needed.
```

## Why this exists at all

A prediction model with no published reviews is asking to be trusted on its summary statistics alone,
and those hide every interesting failure. The reviews are the part that says *here is where it is
wrong, and here is what we are watching* — which is the only version of this project worth
publishing.
