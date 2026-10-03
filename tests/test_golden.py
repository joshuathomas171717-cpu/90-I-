"""P4.2 — golden regression snapshots.

Freezes today's headline numbers so that a code or data change cannot silently move them. Unit tests
prove the model is *valid*; these prove it is still *the same model*.

Two things move a simulated number, and only one of them is a bug:

1. **A change to the code or the data.** That is what this file is for.
2. **The numerical environment.** Different numpy / scipy / scikit-learn releases produce slightly
   different coefficients from the same training rows — a handful of floating-point operations
   deeper, but enough to reshuffle the clubs sitting on the knife edge of relegation. The model is
   otherwise identical: when CI first ran on numpy 2.5 / scikit-learn 1.9, Manchester City's
   projected points and title probability did not move at all, while Ipswich's relegation chance
   wandered 3.7 points.

So the snapshot records the environment it was taken in (`"environment"` in golden.json) and this
file compares:

* **tightly** when the environment matches — a real regression is caught at ±2.5pp;
* **with a documented wider band** when it does not, printing a note so nobody mistakes a library
  difference for a model change. Long-lived regressions are still caught in whichever environment
  generated the snapshot, which is where they are introduced.

`GOLDEN_STRICT=1` forces the tight band everywhere (useful when you want to see the drift).
`python3 tests/make_golden.py` regenerates the snapshot deliberately.
"""
import math
import os

from _util import backtest, env_versions, golden, summary  # noqa: E402  (test-local helper module)

# ── tolerances ───────────────────────────────────────────────────────────────────────────────────
# Within one environment the projection is seeded and deterministic, so these bands only have to
# cover Monte Carlo noise; anything beyond them is a real change.
PTS_TOL = 1.5        # projected points
PCT_TOL = 2.5        # percentage-point probabilities, used as a floor for the scaled band below
GOALS_TOL = 1.0      # projected player goals
PCT_REL = 0.10       # extra band for knife-edge probabilities (see _prob_tol)

#: How much wider to compare when the running libraries differ from the snapshot's.
ENV_DRIFT = 1.5

_GOLDEN_ENV = golden().get("environment") or {}
_RUN_ENV = env_versions()
_ENV_MATCH = all(_GOLDEN_ENV.get(k) == v for k, v in _RUN_ENV.items()) if _GOLDEN_ENV else False
_STRICT = os.environ.get("GOLDEN_STRICT") == "1"
_DRIFT = 1.0 if (_ENV_MATCH or _STRICT) else ENV_DRIFT


def _note():
    if _ENV_MATCH or _STRICT:
        return ""
    differing = {k: (_GOLDEN_ENV.get(k), v) for k, v in _RUN_ENV.items() if _GOLDEN_ENV.get(k) != v}
    pretty = ", ".join("%s %s→%s" % (k, g, r) for k, (g, r) in sorted(differing.items()))
    return ("\n  note: golden.json was written under different libraries (%s); comparing with a "
            "%.1f× band. Run `python3 tests/make_golden.py` in this environment to re-freeze it."
            % (pretty, _DRIFT))


def _prob_tol(p_golden):
    """Tolerance for a simulated probability, in percentage points.

    Monte Carlo noise shrinks as 1/sqrt(n) and is small at 5,000 seasons. A coefficient shift from a
    different library version does not shrink at all, and it is felt almost entirely by clubs whose
    fate sits near a 50/50 — Ipswich at 40% relegation is decided by a few dozen simulated seasons,
    so a hair's difference in the log-odds reshuffles them, while a club at 0.5% barely moves.
    Hence a band that widens near 50% and stays tight at the extremes, on top of the flat floor.
    """
    return max(PCT_TOL, PCT_REL * math.sqrt(max(p_golden, 0.0) * (100.0 - max(p_golden, 0.0)))) * _DRIFT


def test_champion_projection_unchanged():
    golden_, summary_ = golden(), summary()
    g = golden_["table"][0]
    c = summary_["table_projections"][0]
    assert c["code"] == g["code"], (
        "projected champion moved from %s to %s" % (g["code"], c["code"]) + _note())
    assert abs(c["proj_pts"] - g["proj_pts"]) <= PTS_TOL, (
        "%s projected %.2f pts vs golden %.2f (Δ %+.2f, tol ±%.2f)%s"
        % (c["code"], c["proj_pts"], g["proj_pts"], c["proj_pts"] - g["proj_pts"], PTS_TOL, _note()))
    assert abs(c["title_prob"] - g["title_prob"]) <= _prob_tol(g["title_prob"]), (
        "%s title prob %.2f%% vs golden %.2f%% (Δ %+.2fpp, tol ±%.2fpp)%s"
        % (c["code"], c["title_prob"], g["title_prob"], c["title_prob"] - g["title_prob"],
           _prob_tol(g["title_prob"]), _note()))


def test_full_table_projection_unchanged():
    golden_, summary_ = golden(), summary()
    by_code = {c["code"]: c for c in summary_["table_projections"]}
    for g in golden_["table"]:
        c = by_code[g["code"]]
        assert abs(c["proj_pts"] - g["proj_pts"]) <= PTS_TOL, (
            "%s: %.2f pts vs golden %.2f (Δ %+.2f, tol ±%.2f)"
            % (g["code"], c["proj_pts"], g["proj_pts"], c["proj_pts"] - g["proj_pts"], PTS_TOL))
        for field, label in (("title_prob", "title"), ("top4_prob", "top-4"),
                             ("relegation_prob", "relegation")):
            tol = _prob_tol(g[field])
            delta = c[field] - g[field]
            assert abs(delta) <= tol, (
                "%s %s prob %.2f%% vs golden %.2f%% (Δ %+.2fpp, tol ±%.2fpp)%s"
                % (g["code"], label, c[field], g[field], delta, tol, _note()))


def test_award_races_unchanged():
    golden_, summary_ = golden(), summary()
    for race, field in (("golden_boot_race", "proj_goals"), ("playmaker_race", "proj_assists"),
                        ("golden_glove_race", "proj_cs")):
        for g in golden_[race]:
            rows = {p["player_id"]: p for p in summary_[race]}
            assert g["player_id"] in rows, f"{g['name']} vanished from {race}"
            got = rows[g["player_id"]][field]
            assert abs(got - g[field]) <= GOALS_TOL, (
                "%s %s: %.2f vs golden %.2f (Δ %+.2f, tol ±%.2f)%s"
                % (g["name"], field, got, g[field], got - g[field], GOALS_TOL, _note()))


def test_headline_awards_unchanged():
    golden_, summary_ = golden(), summary()
    h = summary_["headline_predictions"]
    for slot in ("golden_boot", "playmaker", "golden_glove"):
        assert h[slot]["player_id"] == golden_["headline"][slot]["player_id"], (
            "%s winner moved from %s to %s" % (slot, golden_["headline"][slot]["name"], h[slot]["name"]) + _note())


def test_backtest_metrics_unchanged():
    bt = backtest()
    g = golden()["backtest"]
    # The backtest is deterministic given the same inputs, so it gets a tight tolerance.
    assert abs(bt["model"]["accuracy"] - g["accuracy"]) <= 0.6, (
        "accuracy %.1f vs golden %.1f (Δ %+.1f)" % (bt["model"]["accuracy"], g["accuracy"], bt["model"]["accuracy"] - g["accuracy"]) + _note())
    assert abs(bt["model"]["rps"] - g["rps"]) <= 0.004, (
        "RPS %.4f vs golden %.4f (Δ %+.4f)" % (bt["model"]["rps"], g["rps"], bt["model"]["rps"] - g["rps"]) + _note())
    assert abs(bt["skill_vs_prior_table"]["rps"] - g["skill_rps"]) <= 0.8 + (0.4 * (_DRIFT - 1.0)), (
        "RPS skill %.1f vs golden %.1f" % (bt["skill_vs_prior_table"]["rps"], g["skill_rps"]) + _note())
    assert abs(bt["table_level"]["spearman_rank_correlation"] - g["spearman"]) <= 0.03 * _DRIFT, (
        "Spearman %.4f vs golden %.4f" % (bt["table_level"]["spearman_rank_correlation"], g["spearman"]) + _note())


def test_league_environment_unchanged():
    golden_, summary_ = golden(), summary()
    assert summary_["ml_metrics"]["matches_trained"] == golden_["matches_trained"]
    assert summary_["ml_metrics"]["remaining_fixtures"] == golden_["remaining_fixtures"]
    assert abs(summary_["meta"]["lambda_scale"] - golden_["lambda_scale"]) <= 0.005


def test_the_snapshot_says_which_environment_it_came_from():
    """A snapshot without its environment cannot be interpreted — this is the guard that keeps it there."""
    g = golden()
    assert g.get("environment"), "golden.json must record the library versions it was written under"
    assert _RUN_ENV.keys() == g["environment"].keys()
    if not _ENV_MATCH:
        print("  [golden] different environment — comparing with a %.1f× band%s" % (_DRIFT, _note()))
