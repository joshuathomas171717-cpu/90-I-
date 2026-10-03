"""Regenerate tests/golden/golden.json from the current model output.

Run this only when a change to the numbers is intended and understood — the whole point of the
snapshot is that unexpected movement fails the build.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import env_versions  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

summary = json.load(open(os.path.join(ROOT, "data", "predictions_2026_27_summary.json"), encoding="utf-8"))
bt = json.load(open(os.path.join(ROOT, "data", "backtest_2025_26.json"), encoding="utf-8"))

golden = {
    "_note": "Frozen headline numbers. Regenerate with python3 tests/make_golden.py only for intended changes.",
    # Which library versions produced these numbers. tests/test_golden.py compares tightly inside
    # this environment and with a documented, wider band outside it — see the comment there.
    "environment": env_versions(),
    "as_of": summary["meta"]["as_of_date"],
    "model_version": "2.1",
    "lambda_scale": summary["meta"]["lambda_scale"],
    "matches_trained": summary["ml_metrics"]["matches_trained"],
    "remaining_fixtures": summary["ml_metrics"]["remaining_fixtures"],
    "table": [{"code": c["code"], "name": c["name"], "proj_pts": c["proj_pts"],
               "title_prob": c["title_prob"], "top4_prob": c["top4_prob"],
               "relegation_prob": c["relegation_prob"]} for c in summary["table_projections"]],
    "headline": {k: {"player_id": v.get("player_id"), "name": v.get("name")}
                 for k, v in summary["headline_predictions"].items() if isinstance(v, dict)},
    "golden_boot_race": [{"player_id": p["player_id"], "name": p["name"], "proj_goals": p["proj_goals"]}
                         for p in summary["golden_boot_race"][:8]],
    "playmaker_race": [{"player_id": p["player_id"], "name": p["name"], "proj_assists": p["proj_assists"]}
                       for p in summary["playmaker_race"][:8]],
    "golden_glove_race": [{"player_id": p["player_id"], "name": p["name"], "proj_cs": p["proj_cs"]}
                          for p in summary["golden_glove_race"][:8]],
    "backtest": {"accuracy": bt["model"]["accuracy"], "rps": bt["model"]["rps"],
                 "skill_rps": bt["skill_vs_prior_table"]["rps"],
                 "spearman": bt["table_level"]["spearman_rank_correlation"]},
}

path = os.path.join(HERE, "golden", "golden.json")
with open(path, "w", encoding="utf-8") as fh:
    json.dump(golden, fh, indent=2)
print(f"wrote {path}")
print(f"  champion      {golden['table'][0]['name']} {golden['table'][0]['proj_pts']} pts "
      f"({golden['table'][0]['title_prob']}%)")
print(f"  golden boot   {golden['golden_boot_race'][0]['name']} {golden['golden_boot_race'][0]['proj_goals']}")
print(f"  backtest      {golden['backtest']['accuracy']}% acc · RPS {golden['backtest']['rps']}")
