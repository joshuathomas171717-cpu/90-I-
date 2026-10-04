"""P14.4 — pre-kickoff, expanding-history shadow comparison. Missing evidence is NOT a zero delta.

The old 2025–26 result matrix is alphabetical fixture order, without dates or lineups. It cannot
support player recency/absence testing. This gate joins a dated intake against that matrix, verifies
scores, orders by exact kickoff, and uses only statistics whose embargo ended before the target.
Target absences require a separately timestamped pre-match capture; post-match lineups never qualify.

Constants are fixed in player_signal_policy.json. First 120 fixtures are warm-up, the remaining
fixtures are untouched chronological evaluation. Confidence intervals resample seven-day blocks.
A missing-data run exits 0 and publishes context-only, not an invented improvement.

The comparison uses the existing structural backtest head, NOT the live ML ensemble. Even a positive
shadow test cannot silently authorize an untested production head; live_input_allowed remains false.
The report names that limitation and the model card publishes it.
"""
import argparse
import datetime as dt
import os

import numpy as np

from absence_model import choose_impact, combine_absences
from backtest import (HOME_ADVANTAGE, LEAGUE_AVG_GOALS_PER_TEAM, build_priors, dc_matrix, metrics,
                      outcome_probs)
from congestion import rest_context
from player_data import DATA, atomic_json, exact_time, load_csv, load_json, number, policy, timestamp
from player_history import dated_rows, history_path, merge
from player_index import build_indices, squad_index

OUT = os.path.join(DATA, "player_gate_2025_26.json")
OUTCOMES = {"H": 0, "D": 1, "A": 2}


def structural_calibration(ratings):
    values = []
    for home in ratings:
        for away in ratings:
            if home != away:
                values.extend((ratings[home]["attack"]*ratings[away]["defence"]*HOME_ADVANTAGE,
                               ratings[away]["attack"]*ratings[home]["defence"]/HOME_ADVANTAGE))
    return LEAGUE_AVG_GOALS_PER_TEAM / float(np.mean(values))


def base_lambdas(home, away, ratings, calibration):
    return (ratings[home]["attack"]*ratings[away]["defence"]*HOME_ADVANTAGE*calibration,
            ratings[away]["attack"]*ratings[home]["defence"]/HOME_ADVANTAGE*calibration)


def eligible_history(fixtures, kickoff):
    target = exact_time(kickoff)
    if target is None:
        return []
    return [f for f in fixtures if exact_time(f.get("kickoff")) is not None
            and exact_time(f["kickoff"]) < target
            and exact_time(f.get("stats_available_at")) is not None
            and exact_time(f["stats_available_at"]) < target]


def observations(fixtures, ratings=None):
    ratings = ratings or build_priors()
    calibration = structural_calibration(ratings)
    rows = []
    for fixture in fixtures:
        h, a = fixture["home"], fixture["away"]
        if h not in ratings or a not in ratings:
            continue
        lh, la = base_lambdas(h, a, ratings, calibration)
        for player in fixture.get("players") or []:
            home = player["club"] == h
            rows.append({"fixture_id": fixture["fixture_id"], "club": player["club"],
                         "player_id": str(player["player_id"]), "minutes": player.get("minutes"),
                         "kickoff": fixture["kickoff"], "stats_available_at": fixture.get("stats_available_at"),
                         "gf": fixture["home_goals"] if home else fixture["away_goals"],
                         "ga": fixture["away_goals"] if home else fixture["home_goals"],
                         "expected_gf": lh if home else la, "expected_ga": la if home else lh})
    return rows


def capture_for(fixture, captures):
    """Exactly this fixture, explicitly tracked, captured BEFORE kickoff. No retrospective inference."""
    target = exact_time(fixture["kickoff"])
    clubs, covered = {}, set()
    for capture in sorted(captures or [], key=lambda r: str(r.get("known_at") or "")):
        known = exact_time(capture.get("known_at"))
        club = capture.get("club")
        if str(capture.get("fixture_id")) != str(fixture["fixture_id"]) or club not in (fixture["home"], fixture["away"]):
            continue
        if known is None or known >= target or not capture.get("tracked"):
            continue
        if not isinstance(capture.get("players_out"), list):
            continue
        clubs[club] = capture["players_out"]
        covered.add(club)
    return {"tracked": bool(covered), "clubs": clubs,
            "coverage": {c: "checked" for c in covered}}, covered


def features_for_fixture(fixture, fixtures, captures, events, ratings=None, extra_rows=None):
    """No own-fixture goals, own-fixture appearances, or future season totals enter this function."""
    prior = eligible_history(fixtures, fixture["kickoff"])
    rows = dated_rows(prior)
    target_time = exact_time(fixture["kickoff"])
    for extra in extra_rows or []:
        played = timestamp(extra.get("match_date"))
        ready = timestamp(extra.get("stats_available_at")) or (played + dt.timedelta(days=1) if played else None)
        if played and ready and played < target_time and ready < target_time:
            rows.append(extra)
    # Completed league fixtures also prove past kickoff times; extra cup/national calendars add to them.
    prior_events = []
    for past in prior:
        for club, opponent, venue in ((past["home"], past["away"], "home"), (past["away"], past["home"], "away")):
            prior_events.append({"club": club, "opponent": opponent, "venue": venue,
                                 "kickoff": past["kickoff"], "known_at": past["stats_available_at"],
                                 "fixture_id": past["fixture_id"], "minutes": 90,
                                 "travel_km": 0 if venue == "home" else None})

    roster, clubs = {}, {}
    for row in rows:
        key = (row["club"], str(row["player_id"]))
        roster[key] = {"club": row["club"], "player_id": str(row["player_id"]),
                       "name": row.get("player"), "pos": row.get("position") or "UNKNOWN"}
    for past in prior:
        if past.get("competition") != "Premier League":
            continue
        for code, gf, ga in ((past["home"], past["home_goals"], past["away_goals"]),
                             (past["away"], past["away_goals"], past["home_goals"])):
            state = clubs.setdefault(code, {"P": 0, "GF": 0, "GA": 0})
            state["P"] += 1; state["GF"] += gf; state["GA"] += ga
    players = build_indices(rows, list(roster.values()), fixture["kickoff"])
    obs = observations(prior, ratings)
    for player in players:
        own = [r for r in rows if r["club"] == player["club"] and str(r["player_id"]) == player["player_id"]]
        player["absence"] = choose_impact(roster[(player["club"], player["player_id"])],
                                         clubs.get(player["club"]) or {}, own, obs, fixture["kickoff"])
    capture, covered = capture_for(fixture, captures)
    missing = combine_absences(players, capture)
    squads = squad_index(players)
    return {"squads": squads, "absences": missing,
            "rest": {c: rest_context(c, fixture["kickoff"], prior_events + list(events), known_by=fixture["kickoff"])
                     for c in (fixture["home"], fixture["away"])},
            "covered_clubs": sorted(covered), "history_matches": len(prior),
            "eligible_last_kickoff": max((f["kickoff"] for f in prior), default=None)}


def candidate_lambdas(lh, la, home, away, features, settings=None):
    """Shadow-only adjustments shared by the gate and scenario tests. No production side effects."""
    settings = settings or policy()
    def factors(club):
        squad = (features.get("squads") or {}).get(club) or {}
        absence = (features.get("absences") or {}).get(club) or {}
        rest = (features.get("rest") or {}).get(club) or {}
        index = squad.get("index")
        form_pct = (number(index, 50)-50)*settings["form_goal_scale_pct"] if index is not None else 0
        loss = number(absence.get("attack_loss_pct")) if absence.get("tracked") else 0
        defence = number(absence.get("defence_cost_pct")) if absence.get("tracked") else 0
        fatigue = number(rest.get("fatigue_pct"))
        return max(.6, min(1.2, (1+form_pct/100)*(1-loss/100)*(1-fatigue/100))), max(.8, 1+defence/100)
    ha, hd = factors(home); aa, ad = factors(away)
    return max(.1, min(5., lh*ha*ad)), max(.1, min(5., la*aa*hd))


def assess(baseline, candidate, truth, kickoffs, coverage, settings=None):
    settings = settings or policy()
    baseline, candidate, truth = np.asarray(baseline), np.asarray(candidate), np.asarray(truth)
    onehot = np.eye(3)[truth]
    def losses(probs):
        return .5*np.sum((np.cumsum(probs, axis=1)[:, :2]-np.cumsum(onehot, axis=1)[:, :2])**2, axis=1)
    diff = losses(candidate)-losses(baseline)
    rps_delta = float(np.mean(diff))
    hit_delta = 100*float(np.mean(np.argmax(candidate, axis=1) == truth)-np.mean(np.argmax(baseline, axis=1) == truth))
    dates = [exact_time(t) for t in kickoffs]
    start = min(dates)
    groups = {}
    for i, date in enumerate(dates):
        groups.setdefault((date-start).days//7, []).append(i)
    blocks = list(groups.values())
    rng, samples = np.random.default_rng(42), []
    for _ in range(settings["gate_bootstrap_samples"]):
        ids = [i for b in rng.integers(0, len(blocks), size=len(blocks)) for i in blocks[int(b)]]
        samples.append(float(np.mean(diff[ids])))
    ci = [float(v) for v in np.quantile(samples, [.025, .975])]
    requirements = {"enough_test_matches": len(truth) >= settings["gate_min_test_matches"],
                    "enough_pre_match_coverage": coverage >= settings["gate_min_coverage"],
                    "rps_improves": rps_delta <= -settings["gate_min_rps_gain"],
                    "hit_rate_improves": hit_delta > 0,
                    "paired_interval_below_zero": ci[1] < 0,
                    "enough_time_blocks": len(blocks) >= 10}
    return {"baseline": metrics(baseline, truth), "candidate": metrics(candidate, truth),
            "delta": {"rps": round(rps_delta, 6), "accuracy_percentage_points": round(hit_delta, 3)},
            "paired_rps_delta_95pct": [round(v, 6) for v in ci],
            "bootstrap": "paired seven-day blocks; seed 42; fixed policy",
            "requirements": requirements, "shadow_verdict": "go" if all(requirements.values()) else "no-go"}


def evaluate(history=None, result_rows=None, baseline_report=None):
    settings = policy()
    history = history if history is not None else load_json(history_path())
    result_rows = result_rows if result_rows is not None else load_csv(os.path.join(DATA, "matches_2025_26.csv"))
    baseline_report = baseline_report if baseline_report is not None else load_json(os.path.join(DATA, "backtest_2025_26.json"))
    fixtures, problems = merge([], history.get("fixtures") or [], "2025-26")
    targets = {(r["home"], r["away"]): r for r in result_rows}
    joined, disagreements = [], []
    for fixture in fixtures:
        if fixture["competition"] != "Premier League":
            continue
        target = targets.get((fixture["home"], fixture["away"]))
        if not target:
            continue
        if (int(target["home_goals"]), int(target["away_goals"])) != (fixture["home_goals"], fixture["away_goals"]):
            disagreements.append("score mismatch %s-%s" % (fixture["home"], fixture["away"])); continue
        joined.append((fixture, target))
    dated_count = len(joined)
    base = {"version": "player-gate/1", "model_card": "v3.0", "season": "2025-26",
            "mode": "context", "live_input_allowed": False, "shadow_verdict": "not-measured",
            "scope": "structural shadow head only; the live ML ensemble is not validated by this comparison",
            "baseline_full_season": baseline_report.get("model") or {},
            "baseline": None, "candidate": None, "delta": {"rps": None, "accuracy_percentage_points": None},
            "paired_rps_delta_95pct": None, "fixtures_in_result_matrix": len(result_rows),
            "dated_fixtures_joined": dated_count, "test_matches": 0, "pre_match_coverage": 0.,
            "policy": settings["version"], "problems": problems+disagreements,
            "reasons": [], "method": "exact kickoff order; prior completed matches only; 120-fixture warm-up; fixed constants"}
    if dated_count != len(targets) or len(targets) != 380 or problems or disagreements:
        base["reasons"].append("A validated dated calendar for all 380 historical fixtures is missing or disagrees with the result matrix.")
    captures = history.get("availability") or []
    if not captures:
        base["reasons"].append("No timestamped pre-kickoff availability captures; post-match appearances cannot stand in for them.")
    if not any(f.get("players") for f, _r in joined):
        base["reasons"].append("No usable per-match player appearances; season totals cannot be walked backwards through time.")
    if base["reasons"]:
        base["reasons"].append("Missing evidence is not a measured zero delta. Keep player form, absence and rest/travel as context.")
        return base

    from player_history import normalise_match_rows
    extra_rows, extra_problems = normalise_match_rows(history.get("player_matches") or [], "2025-26")
    base["problems"].extend(extra_problems)
    ratings, calibration = build_priors(), structural_calibration(build_priors())
    baseline, candidate, truth, kickoffs, predictions, covered = [], [], [], [], [], 0
    for fixture, target in joined[120:]:
        lh, la = base_lambdas(fixture["home"], fixture["away"], ratings, calibration)
        features = features_for_fixture(fixture, fixtures, captures, history.get("calendar") or [], ratings, extra_rows)
        ch, ca = candidate_lambdas(lh, la, fixture["home"], fixture["away"], features, settings)
        before, after = outcome_probs(dc_matrix(lh, la)), outcome_probs(dc_matrix(ch, ca))
        baseline.append(before); candidate.append(after); truth.append(OUTCOMES[target["outcome"]]); kickoffs.append(fixture["kickoff"])
        good = len(features["covered_clubs"]) == 2 and all(
            (features["squads"].get(c) or {}).get("recency_available")
            and not (features["absences"].get(c) or {}).get("unmapped") for c in (fixture["home"], fixture["away"]))
        covered += int(bool(good))
        predictions.append({"fixture_id": fixture["fixture_id"], "kickoff": fixture["kickoff"],
                            "home": fixture["home"], "away": fixture["away"],
                            "baseline": [round(float(v), 6) for v in before], "candidate": [round(float(v), 6) for v in after],
                            "history_matches": features["history_matches"], "pre_match_covered": bool(good)})
    coverage = covered/max(1, len(truth))
    score = assess(baseline, candidate, truth, kickoffs, coverage, settings)
    base.update(score, test_matches=len(truth), pre_match_coverage=round(coverage, 4), predictions=predictions)
    base["reasons"] = (["Shadow evidence fails: " + ", ".join(k for k, ok in score["requirements"].items() if not ok)]
                       if score["shadow_verdict"] == "no-go" else ["Structural shadow passed; the live ML head still requires its own temporal validation."])
    base["reasons"].append("No automatic promotion from a structural comparison into the live ML ensemble.")
    return base


def main(argv=None):
    ap = argparse.ArgumentParser(description="Temporal player-signal gate; no evidence means context-only.")
    ap.add_argument("--history", default=history_path())
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--require-input", action="store_true", help="exit 1 unless the live input gate is open")
    args = ap.parse_args(argv)
    report = evaluate(load_json(args.history))
    atomic_json(args.out, report)
    if args.as_json:
        import json
        print(json.dumps(report, indent=2, allow_nan=False))
    else:
        print("Player gate: %s; shadow %s; %d/380 dated fixtures; %d test matches" % (
            report["mode"], report["shadow_verdict"], report["dated_fixtures_joined"], report["test_matches"]))
        for reason in report["reasons"]:
            print("  " + reason)
    return 1 if args.require_input and not report["live_input_allowed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
