"""Leakage-free backtest: replay the 2025-26 Premier League season with the structural engine.

Method
------
Only information available BEFORE 2025-26 kicked off is used:
  * the 2024-25 final table (points / goals for / goals against for all 20 clubs)
  * fixed hyperparameters taken from Premier League history, documented below
Nothing from the 2025-26 season itself (no results, no form, no live table) is used to build the
ratings or pick the constants - so the 380 match predictions are genuinely out-of-sample.

The engine is then scored on:
  1. match level  - 1X2 accuracy, Ranked Probability Score, Brier score, log-loss vs three baselines
  2. table level  - projected final table (analytic expected points) vs the actual 2025-26 table
  3. market level - how the projected champion / top four / bottom three compare with reality

Note on difficulty: this replay tests a *pre-season* projection, which is a much harder task than
the live 2026-27 forecasts (which also carry five matchweeks of current-season information). It is
therefore a conservative floor on expected performance, not a like-for-like accuracy claim.
"""
import json
import os
import numpy as np
import pandas as pd
from scipy.stats import poisson, spearmanr

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

# ── Fixed hyperparameters (documented, not fitted on 2025-26) ─────────────────────────────────
LEAGUE_AVG_GOALS_PER_TEAM = 1115 / 20 / 38      # 2024-25 actual: 1,115 goals in 380 matches
HOME_ADVANTAGE = 1.12                            # PL long-run: home sides score ~12% more
DIXON_COLES_RHO = -0.11                          # Dixon-Coles (1997) low-score correlation, PL
PROMOTED_ATTACK_FACTOR = 0.78                    # promoted clubs score ~22% below league average
PROMOTED_DEFENCE_FACTOR = 1.28                   # ...and concede ~28% above it

# ── 2024-25 final table (verified: 1,115 goals, matches published standings) ──────────────────
TABLE_2024_25 = {
    "LIV": (86, 41, 84), "ARS": (69, 34, 74), "MCI": (72, 44, 71), "CHE": (64, 43, 69),
    "NEW": (68, 47, 66), "AVL": (58, 51, 66), "NFO": (58, 46, 65), "BHA": (66, 59, 61),
    "BOU": (58, 46, 56), "BRE": (66, 57, 56), "FUL": (54, 54, 54), "CRY": (51, 51, 53),
    "EVE": (42, 44, 48), "WHU": (46, 62, 43), "MUN": (44, 54, 42), "WOL": (54, 69, 42),
    "TOT": (64, 65, 38), "LEI": (33, 80, 25), "IPS": (36, 82, 22), "SOU": (26, 86, 12),
}
PROMOTED_2025_26 = ["LEE", "BUR", "SUN"]  # came up from the Championship for 2025-26
RELEGATED_2024_25 = ["LEI", "IPS", "SOU"]  # dropped out, so they are not in the 2025-26 field
CLUB_NAMES = {
    "LIV": "Liverpool", "ARS": "Arsenal", "MCI": "Manchester City", "CHE": "Chelsea",
    "NEW": "Newcastle United", "AVL": "Aston Villa", "NFO": "Nottingham Forest",
    "BHA": "Brighton & Hove Albion", "BOU": "Bournemouth", "BRE": "Brentford",
    "FUL": "Fulham", "CRY": "Crystal Palace", "EVE": "Everton", "WHU": "West Ham United",
    "MUN": "Manchester United", "WOL": "Wolverhampton Wanderers", "TOT": "Tottenham Hotspur",
    "LEE": "Leeds United", "BUR": "Burnley", "SUN": "Sunderland",
}


def build_priors():
    """Attack / defence / Elo-style strength ratings from the 2024-25 final table only."""
    ratings = {}
    avg = LEAGUE_AVG_GOALS_PER_TEAM
    for code, (gf, ga, pts) in TABLE_2024_25.items():
        if code in RELEGATED_2024_25:
            continue
        ratings[code] = {
            "attack": (gf / 38.0) / avg,
            "defence": (ga / 38.0) / avg,
            "prior_pts": pts,
            "source": "2024-25 PL table",
        }
    # Promoted clubs: shrink toward the documented promoted-side convention (Championship form is
    # not comparable to the PL, so no club-specific attack/defence is assumed).
    for code in PROMOTED_2025_26:
        ratings[code] = {
            "attack": PROMOTED_ATTACK_FACTOR,
            "defence": PROMOTED_DEFENCE_FACTOR,
            "prior_pts": 40.0,
            "source": "promoted-club convention",
        }
    return ratings


def dc_matrix(lam_h, lam_a, n=8, rho=DIXON_COLES_RHO):
    ph = poisson.pmf(np.arange(n + 1), lam_h)
    pa = poisson.pmf(np.arange(n + 1), lam_a)
    m = np.outer(ph, pa)
    m[0, 0] *= 1 - lam_h * lam_a * rho
    m[0, 1] *= 1 + lam_h * rho
    m[1, 0] *= 1 + lam_a * rho
    m[1, 1] *= 1 - rho
    m = np.clip(m, 0, None)
    return m / m.sum()


def outcome_probs(m):
    p_h = float(np.tril(m, -1).sum())
    p_d = float(np.diag(m).sum())
    p_a = float(np.triu(m, 1).sum())
    return np.array([p_h, p_d, p_a])


def rps(probs, truth):
    """Ranked Probability Score for a 3-way ordinal outcome (lower is better)."""
    cum_p = np.cumsum(probs, axis=1)
    cum_t = np.cumsum(np.eye(3)[truth], axis=1)
    return float(np.mean(0.5 * np.sum((cum_p[:, :2] - cum_t[:, :2]) ** 2, axis=1)))


def metrics(probs, truth):
    probs = np.asarray(probs)
    truth = np.asarray(truth)
    onehot = np.eye(3)[truth]
    ll = float(-np.mean(np.log(np.clip(probs[np.arange(len(truth)), truth], 1e-12, 1))))
    brier = float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))
    acc = float(np.mean(np.argmax(probs, axis=1) == truth) * 100.0)
    return {"accuracy": round(acc, 1), "rps": round(rps(probs, truth), 4),
            "brier": round(brier, 4), "log_loss": round(ll, 4)}


def run_backtest():
    ratings = build_priors()
    teams = sorted(ratings)
    assert len(teams) == 20

    # Global calibration so the replay reproduces the *2024-25* league scoring rate (1,115 goals).
    lam_raw = []
    for h in teams:
        for a in teams:
            if h != a:
                lam_raw.append(ratings[h]["attack"] * ratings[a]["defence"] * HOME_ADVANTAGE)
                lam_raw.append(ratings[a]["attack"] * ratings[h]["defence"] / HOME_ADVANTAGE)
    calib = (2 * LEAGUE_AVG_GOALS_PER_TEAM) / (np.mean(lam_raw) * 2)

    results = pd.read_csv(os.path.join(DATA, "matches_2025_26.csv"))
    outcome_map = {"H": 0, "D": 1, "A": 2}

    model_probs, truth, detail = [], [], []
    base_home, base_prior, base_uniform = [], [], []
    exp_pts = {t: 0.0 for t in teams}
    exp_gf = {t: 0.0 for t in teams}
    exp_ga = {t: 0.0 for t in teams}
    prediction_log = []

    for _, row in results.iterrows():
        h, a = row["home"], row["away"]
        lam_h = ratings[h]["attack"] * ratings[a]["defence"] * HOME_ADVANTAGE * calib
        lam_a = ratings[a]["attack"] * ratings[h]["defence"] / HOME_ADVANTAGE * calib
        probs = outcome_probs(dc_matrix(lam_h, lam_a))
        model_probs.append(probs)
        truth.append(outcome_map[row["outcome"]])
        detail.append({"gameweek": None, "home": h, "away": a, "probs": probs.tolist(),
                       "actual": row["outcome"], "lam_h": lam_h, "lam_a": lam_a})

        # Analytic season projection: expected points / goals from the probability grid
        exp_pts[h] += 3 * probs[0] + probs[1]
        exp_pts[a] += 3 * probs[2] + probs[1]
        m = dc_matrix(lam_h, lam_a)
        exp_gf[h] += float(sum(i * m[i, j] for i in range(9) for j in range(9)))
        exp_ga[h] += float(sum(j * m[i, j] for i in range(9) for j in range(9)))
        exp_gf[a] += float(sum(j * m[i, j] for i in range(9) for j in range(9)))
        exp_ga[a] += float(sum(i * m[i, j] for i in range(9) for j in range(9)))

        prediction_log.append({"home": h, "away": a, "lam_h": round(lam_h, 2), "lam_a": round(lam_a, 2),
                               "p_home": round(probs[0] * 100, 1), "p_draw": round(probs[1] * 100, 1),
                               "p_away": round(probs[2] * 100, 1), "actual": row["outcome"],
                               "hit": bool(int(np.argmax(probs)) == outcome_map[row["outcome"]]),
                               "score": f"{row['home_goals']}-{row['away_goals']}"})

        # Baselines
        base_home.append([0.45, 0.24, 0.31])           # PL long-run home/draw/away base rates
        p_h = 1.0 / (1.0 + np.exp(-(ratings[h]["prior_pts"] - ratings[a]["prior_pts"]) / 11.0))
        p_a = 1.0 / (1.0 + np.exp((ratings[h]["prior_pts"] - ratings[a]["prior_pts"]) / 11.0))
        scale = (1 - 0.24) / (p_h + p_a)
        base_prior.append([p_h * scale, 0.24, p_a * scale])
        base_uniform.append([1 / 3, 1 / 3, 1 / 3])

    model_probs = np.array(model_probs)
    truth = np.array(truth)

    # ── 1. Match-level scoring ────────────────────────────────────────────────────────────────
    report = {
        "model": metrics(model_probs, truth),
        "baselines": {
            "home_win_always (PL base rates)": metrics(np.array(base_home), truth),
            "prior_season_table_favourite": metrics(np.array(base_prior), truth),
            "uniform_1x3": metrics(np.array(base_uniform), truth),
        },
    }
    report["skill_vs_prior_table"] = {
        k: round(100.0 * (1 - report["model"][k] / report["baselines"]["prior_season_table_favourite"][k]), 1)
        for k in ("rps", "brier", "log_loss")
    }

    # ── 2. Table-level: projected vs actual 2025-26 ───────────────────────────────────────────
    actual = pd.read_csv(os.path.join(DATA, "matches_2025_26.csv"))
    actual_tbl = {t: {"P": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "Pts": 0} for t in teams}
    for _, r in actual.iterrows():
        h, a, hg, ag = r["home"], r["away"], r["home_goals"], r["away_goals"]
        for t in (h, a):
            actual_tbl[t]["P"] += 1
        actual_tbl[h]["GF"] += hg; actual_tbl[h]["GA"] += ag
        actual_tbl[a]["GF"] += ag; actual_tbl[a]["GA"] += hg
        if hg > ag:
            actual_tbl[h]["W"] += 1; actual_tbl[a]["L"] += 1; actual_tbl[h]["Pts"] += 3
        elif hg < ag:
            actual_tbl[a]["W"] += 1; actual_tbl[h]["L"] += 1; actual_tbl[a]["Pts"] += 3
        else:
            actual_tbl[h]["D"] += 1; actual_tbl[a]["D"] += 1
            actual_tbl[h]["Pts"] += 1; actual_tbl[a]["Pts"] += 1

    proj_rank = sorted(teams, key=lambda t: (-exp_pts[t], -(exp_gf[t] - exp_ga[t])))
    actual_rank = sorted(teams, key=lambda t: (-actual_tbl[t]["Pts"],
                                               -(actual_tbl[t]["GF"] - actual_tbl[t]["GA"]),
                                               -actual_tbl[t]["GF"]))
    proj_pos = {t: i + 1 for i, t in enumerate(proj_rank)}
    actual_pos = {t: i + 1 for i, t in enumerate(actual_rank)}

    rho, _ = spearmanr([exp_pts[t] for t in teams], [actual_tbl[t]["Pts"] for t in teams])
    pts_mae = float(np.mean([abs(exp_pts[t] - actual_tbl[t]["Pts"]) for t in teams]))
    pos_mae = float(np.mean([abs(proj_pos[t] - actual_pos[t]) for t in teams]))
    within2 = float(np.mean([abs(proj_pos[t] - actual_pos[t]) <= 2 for t in teams]) * 100)

    table_rows = []
    for t in teams:
        table_rows.append({
            "code": t, "name": CLUB_NAMES[t],
            "prior_pts_2024_25": TABLE_2024_25.get(t, (0, 0, 40))[2],
            "proj_points": round(exp_pts[t], 1),
            "proj_gf": round(exp_gf[t], 1), "proj_ga": round(exp_ga[t], 1),
            "proj_pos": proj_pos[t],
            "actual_points": actual_tbl[t]["Pts"],
            "actual_gf": actual_tbl[t]["GF"], "actual_ga": actual_tbl[t]["GA"],
            "actual_pos": actual_pos[t],
            "pos_error": proj_pos[t] - actual_pos[t],
            "promoted": t in PROMOTED_2025_26,
        })
    table_rows.sort(key=lambda r: r["proj_pos"])

    report["table_level"] = {
        "spearman_rank_correlation": round(float(rho), 3),
        "points_mae": round(pts_mae, 1),
        "position_mae": round(pos_mae, 1),
        "positions_within_2": round(within2, 1),
        "champion_correct": proj_rank[0] == actual_rank[0],
        "projected_champion": CLUB_NAMES[proj_rank[0]],
        "actual_champion": CLUB_NAMES[actual_rank[0]],
        "top4_overlap": len(set(proj_rank[:4]) & set(actual_rank[:4])),
        "projected_top4": [CLUB_NAMES[t] for t in proj_rank[:4]],
        "actual_top4": [CLUB_NAMES[t] for t in actual_rank[:4]],
        "relegated_actual": [CLUB_NAMES[t] for t in actual_rank[-3:]],
        "projected_bottom3": [CLUB_NAMES[t] for t in proj_rank[-3:]],
        "promoted_clubs_actual_rank": {CLUB_NAMES[t]: actual_pos[t] for t in PROMOTED_2025_26},
        "promoted_clubs_proj_rank": {CLUB_NAMES[t]: proj_pos[t] for t in PROMOTED_2025_26},
        "table": table_rows,
    }

    # ── 3. Calibration of the backtest predictions ────────────────────────────────────────────
    conf = model_probs.max(axis=1)
    correct = (model_probs.argmax(axis=1) == truth).astype(float)
    calib_bins = []
    for lo, hi in [(0.33, 0.45), (0.45, 0.55), (0.55, 0.65), (0.65, 0.80), (0.80, 1.0)]:
        mask = (conf >= lo) & (conf < hi)
        if mask.sum() > 0:
            calib_bins.append({"bin": f"{int(lo*100)}-{int(hi*100)}%",
                          "predicted": round(float(conf[mask].mean()) * 100, 1),
                          "observed": round(float(correct[mask].mean()) * 100, 1),
                          "count": int(mask.sum())})
    report["calibration"] = calib_bins

    report["meta"] = {
        "season_replayed": "2025-26 Premier League (380 matches)",
        "information_used": "2024-25 final table + fixed PL hyperparameters (no 2025-26 data)",
        "home_advantage": HOME_ADVANTAGE,
        "dixon_coles_rho": DIXON_COLES_RHO,
        "promoted_attack_factor": PROMOTED_ATTACK_FACTOR,
        "promoted_defence_factor": PROMOTED_DEFENCE_FACTOR,
        "calibration_constant": round(float(calib), 4),
        "goals_per_game_target": round(LEAGUE_AVG_GOALS_PER_TEAM * 2, 3),
        "note": ("Pre-season replay: a deliberately harder test than the live 2026-27 forecasts, "
                 "which also use five matchweeks of current-season information."),
    }
    report["predictions"] = prediction_log

    with open(os.path.join(DATA, "backtest_2025_26.json"), "w") as f:
        json.dump(report, f, indent=2)
    return report


if __name__ == "__main__":
    rep = run_backtest()
    m, b = rep["model"], rep["baselines"]
    print("=" * 78)
    print("BACKTEST — 2025-26 Premier League season replayed with pre-season information only")
    print("=" * 78)
    print(f"{'model':<34} acc {m['accuracy']:>5}%   RPS {m['rps']:<7} Brier {m['brier']:<7} log-loss {m['log_loss']}")
    for name, bm in b.items():
        print(f"{name:<34} acc {bm['accuracy']:>5}%   RPS {bm['rps']:<7} Brier {bm['brier']:<7} log-loss {bm['log_loss']}")
    print()
    sk = rep["skill_vs_prior_table"]
    print(f"Skill vs prior-table baseline: RPS {sk['rps']}%  Brier {sk['brier']}%  log-loss {sk['log_loss']}%")
    t = rep["table_level"]
    print()
    print(f"Table projection: Spearman ρ {t['spearman_rank_correlation']}, points MAE {t['points_mae']}, "
          f"position MAE {t['position_mae']}, within ±2 positions {t['positions_within_2']}%")
    print(f"  projected champion {t['projected_champion']} | actual {t['actual_champion']} | correct: {t['champion_correct']}")
    print(f"  top-4 overlap: {t['top4_overlap']}/4  (proj {t['projected_top4']})")
    print(f"  actual relegated: {t['relegated_actual']} | projected bottom 3: {t['projected_bottom3']}")
    print(f"  promoted clubs — projected {t['promoted_clubs_proj_rank']} vs actual {t['promoted_clubs_actual_rank']}")
    print()
    for c in rep["calibration"]:
        print(f"  confidence {c['bin']:>8}  predicted {c['predicted']:>5}%  observed {c['observed']:>5}%  (n={c['count']})")
