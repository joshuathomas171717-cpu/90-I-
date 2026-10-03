"""P4.2 — golden regression snapshots.

Freezes today's headline numbers so that a code or data change cannot silently move them. Unit tests
prove the model is *valid*; these prove it is still *the same model*. Tolerances are deliberately
tight enough to catch drift but loose enough to survive Monte Carlo noise (the baseline is a random
simulation, so exact equality is not a meaningful target).

Regenerate deliberately with:  python3 tests/make_golden.py
"""
import sys

from _util import backtest, golden, summary  # noqa: E402  (test-local helper module)

# Monte Carlo noise on 5,000 seasons; anything beyond this is a real change, not sampling variance.
PTS_TOL = 1.5        # projected points
PCT_TOL = 2.5        # percentage-point probabilities
GOALS_TOL = 1.0      # projected player goals


def test_champion_projection_unchanged():
    golden_, summary_ = golden(), summary()
    g = golden_["table"][0]
    c = summary_["table_projections"][0]
    assert c["code"] == g["code"], f"projected champion moved from {g['code']} to {c['code']}"
    assert abs(c["proj_pts"] - g["proj_pts"]) <= PTS_TOL, f"{c['code']} projected {c['proj_pts']} vs golden {g['proj_pts']}"
    assert abs(c["title_prob"] - g["title_prob"]) <= PCT_TOL, f"title prob moved {g['title_prob']} -> {c['title_prob']}"


def test_full_table_projection_unchanged():
    golden_, summary_ = golden(), summary()
    by_code = {c["code"]: c for c in summary_["table_projections"]}
    for g in golden_["table"]:
        c = by_code[g["code"]]
        assert abs(c["proj_pts"] - g["proj_pts"]) <= PTS_TOL, (
            f"{g['code']}: {c['proj_pts']} pts vs golden {g['proj_pts']} (Δ {c['proj_pts'] - g['proj_pts']:+.2f})")
        assert abs(c["title_prob"] - g["title_prob"]) <= PCT_TOL
        assert abs(c["relegation_prob"] - g["relegation_prob"]) <= PCT_TOL


def test_award_races_unchanged():
    golden_, summary_ = golden(), summary()
    for race, field in (("golden_boot_race", "proj_goals"), ("playmaker_race", "proj_assists"),
                        ("golden_glove_race", "proj_cs")):
        for g in golden_[race]:
            rows = {p["player_id"]: p for p in summary_[race]}
            assert g["player_id"] in rows, f"{g['name']} vanished from {race}"
            got = rows[g["player_id"]][field]
            assert abs(got - g[field]) <= GOALS_TOL, f"{g['name']} {field}: {got} vs golden {g[field]}"


def test_headline_awards_unchanged():
    golden_, summary_ = golden(), summary()
    h = summary_["headline_predictions"]
    for slot in ("golden_boot", "playmaker", "golden_glove"):
        assert h[slot]["player_id"] == golden_["headline"][slot]["player_id"], (
            f"{slot} winner moved from {golden_['headline'][slot]['name']} to {h[slot]['name']}")


def test_backtest_metrics_unchanged():
    bt = backtest()
    g = golden()["backtest"]
    # The backtest is deterministic given the same inputs, so it gets a tight tolerance.
    assert abs(bt["model"]["accuracy"] - g["accuracy"]) <= 0.6, f"accuracy {bt['model']['accuracy']} vs {g['accuracy']}"
    assert abs(bt["model"]["rps"] - g["rps"]) <= 0.004, f"RPS {bt['model']['rps']} vs {g['rps']}"
    assert abs(bt["skill_vs_prior_table"]["rps"] - g["skill_rps"]) <= 0.8
    assert abs(bt["table_level"]["spearman_rank_correlation"] - g["spearman"]) <= 0.03


def test_league_environment_unchanged():
    golden_, summary_ = golden(), summary()
    assert summary_["ml_metrics"]["matches_trained"] == golden_["matches_trained"]
    assert summary_["ml_metrics"]["remaining_fixtures"] == golden_["remaining_fixtures"]
    assert abs(summary_["meta"]["lambda_scale"] - golden_["lambda_scale"]) <= 0.005
