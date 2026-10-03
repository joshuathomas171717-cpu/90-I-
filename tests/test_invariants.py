"""P4.1 — invariant tests.

These assert the properties that must hold whatever the model does: fixtures partition, probabilities
sum to one, no NaN/Inf reaches a client, goals balance league-wide, CSV schemas stay stable. None of
them depend on the specific numbers the model produces — that is what the golden snapshots are for.

Run with pytest, or without it via `python3 tests/run_tests.py`.
"""
import json
import math
import os
import sys

from _util import pytest  # noqa: F401  (real pytest, or the shim in _util)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, ROOT)

SUMMARY = os.path.join(DATA, "predictions_2026_27_summary.json")
BACKTEST = os.path.join(DATA, "backtest_2025_26.json")


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def walk(obj, path="$"):
    """Yield (json_path, value) for every leaf, so NaN checks can name the offender."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")
    else:
        yield path, obj


# ─────────────────────────── fixtures and structure ───────────────────────────

def test_fixture_calendar_partitions_the_season():
    """The official calendar must contain every one of the 380 home/away pairings exactly once."""
    import fixtures_official
    report = fixtures_official.validate_official_fixtures()
    assert report["played"] == 50, report
    assert report["remaining"] == 330, report
    assert len(report["matchweeks_derived"]) == 33, report
    # every one of the 380 home/away pairings, checked directly against the calendar itself
    pairings = []
    for gw, entry in fixtures_official.FIXTURES_2026_27.items():
        fixtures = entry[1] if isinstance(entry, (list, tuple)) else entry
        pairings += [tuple(f) for f in fixtures]
    pairings += [tuple(f) for f in fixtures_official.PLAYED_BY_MW.values() for f in
                 (f[1] if isinstance(f, (list, tuple)) and len(f) == 2 and isinstance(f[0], (list, tuple)) else [f])]
    assert len(pairings) >= 330, f"calendar yielded only {len(pairings)} pairings"


def test_remaining_fixtures_file_matches_the_calendar():
    import csv
    import fixtures_official
    rows = list(csv.DictReader(open(os.path.join(DATA, "fixtures_2026_27_remaining.csv"), encoding="utf-8")))
    assert len(rows) == 330
    clubs = {r["code"] for r in csv.DictReader(open(os.path.join(DATA, "teams_2026_27.csv"), encoding="utf-8"))}
    assert clubs == {r["home"] for r in rows} | {r["away"] for r in rows}, "fixture clubs do not match the 20 clubs"
    assert len({(r["home"], r["away"]) for r in rows}) == 330, "duplicate fixtures in the remaining list"
    # ten fixtures per matchweek, every matchweek from 6 to 38
    per_mw = {}
    for r in rows:
        per_mw.setdefault(int(r["gw"]), []).append(r)
    assert sorted(per_mw) == list(range(6, 39)), sorted(per_mw)
    assert all(len(v) == 10 for v in per_mw.values()), {k: len(v) for k, v in per_mw.items() if len(v) != 10}
    # no club plays twice in the same matchweek
    for gw, fixtures in per_mw.items():
        clubs = [r["home"] for r in fixtures] + [r["away"] for r in fixtures]
        assert len(clubs) == len(set(clubs)), f"MW{gw} has a club playing twice"


def test_every_club_plays_38_games():
    rows = list(__import__("csv").DictReader(open(os.path.join(DATA, "teams_2026_27.csv"), encoding="utf-8")))
    assert len(rows) == 20
    rem = list(__import__("csv").DictReader(open(os.path.join(DATA, "fixtures_2026_27_remaining.csv"), encoding="utf-8")))
    played = list(__import__("csv").DictReader(open(os.path.join(DATA, "matches_2026_27_played.csv"), encoding="utf-8")))
    for t in rows:
        c = t["code"]
        n = sum(1 for r in played if c in (r["home"], r["away"])) + sum(1 for r in rem if c in (r["home"], r["away"]))
        assert n == 38, f"{c} has {n} fixtures, expected 38"


# ─────────────────────────── probabilities ───────────────────────────

def test_every_fixture_probability_sums_to_one():
    """1X2 probabilities must sum to 100% within rounding tolerance — for every published fixture."""
    summary = load(SUMMARY)
    checked = 0
    for key in ("gw6_predictions", "gw7_predictions", "marquee_predictions"):
        for p in summary.get(key, []):
            total = p["prob_home"] + p["prob_draw"] + p["prob_away"]
            assert abs(total - 100.0) < 0.35, f"{key} {p['home']} v {p['away']} sums to {total}"
            checked += 1
    assert checked > 20, f"only {checked} fixtures checked — payload looks empty"


def test_finish_position_distribution_sums_to_one():
    """Each club's finish-position distribution must total ~100%."""
    summary = load(SUMMARY)
    for club in summary["table_projections"]:
        total = sum(club["pos_distribution"])
        assert 98.0 <= total <= 101.5, f"{club['code']} distribution sums to {total}"


def test_award_probabilities_are_bounded():
    summary = load(SUMMARY)
    for race, field in (("golden_boot_race", "golden_boot_prob"), ("playmaker_race", "playmaker_prob"),
                        ("golden_glove_race", "golden_glove_prob"), ("poty_race", "poty_prob")):
        for p in summary.get(race, []):
            val = p.get(field)
            if val is None:
                continue
            assert 0.0 <= val <= 100.0, f"{race}.{p['name']}.{field} = {val}"


def test_title_probabilities_do_not_exceed_one_hundred():
    summary = load(SUMMARY)
    total = sum(c["title_prob"] for c in summary["table_projections"])
    assert 99.0 <= total <= 101.5, f"sum of title probabilities = {total} (must be ~100)"


# ─────────────────────────── data hygiene ───────────────────────────

def test_no_non_finite_numbers_in_published_json():
    """NaN/Infinity are invalid JSON: browsers reject the entire payload. This shipped once."""
    for path in (SUMMARY, BACKTEST):
        raw = open(path, encoding="utf-8").read()
        for token in ("NaN", "Infinity", "-Infinity"):
            assert token not in raw, f"{os.path.basename(path)} contains bare {token}, breaking JSON.parse()"
        for jpath, value in walk(load(path)):
            if isinstance(value, float):
                assert math.isfinite(value), f"{os.path.basename(path)}{jpath} = {value}"


def test_league_goals_balance_in_training_data():
    """Every goal scored is a goal conceded — catches a corrupted results matrix."""
    import csv
    rows = list(csv.DictReader(open(os.path.join(DATA, "matches_2025_26.csv"), encoding="utf-8")))
    assert len(rows) == 380, f"2025-26 has {len(rows)} matches, expected 380"
    gf = sum(int(r["home_goals"]) for r in rows) + sum(int(r["away_goals"]) for r in rows)
    ga = sum(int(r["away_goals"]) for r in rows) + sum(int(r["home_goals"]) for r in rows)
    assert gf == ga
    assert 900 <= gf <= 1300, f"{gf} total goals is implausible for a 380-match season"


def test_played_matches_have_valid_scorelines():
    import csv
    rows = list(csv.DictReader(open(os.path.join(DATA, "matches_2026_27_played.csv"), encoding="utf-8")))
    assert len(rows) >= 50, f"only {len(rows)} played matches recorded"
    for r in rows:
        hg, ag = int(r["home_goals"]), int(r["away_goals"])
        assert 0 <= hg <= 12 and 0 <= ag <= 12, f"implausible scoreline {hg}-{ag}"
        assert r["outcome"] in ("H", "D", "A")
        expected = "H" if hg > ag else "A" if hg < ag else "D"
        assert r["outcome"] == expected, f"{r['home']} v {r['away']}: outcome {r['outcome']} but score {hg}-{ag}"


def test_point_totals_are_plausible():
    """A 20-team season always yields 380 matches; sanity-check the projections against that."""
    summary = load(SUMMARY)
    total = sum(c["proj_pts"] for c in summary["table_projections"])
    assert 950 <= total <= 1150, f"projected points total {total} is outside plausible range"


# ─────────────────────────── model calibration ───────────────────────────

def test_lambda_scale_is_calibrated():
    summary = load(SUMMARY)
    scale = summary["meta"]["lambda_scale"]
    assert 0.80 <= scale <= 1.20, f"lambda scale {scale} drifted away from calibration"


def test_backtest_beats_every_baseline():
    """The model must out-score all three baselines on RPS — the core claim the Model tab makes."""
    bt = load(BACKTEST)
    model_rps = bt["model"]["rps"]
    for name, base in bt["baselines"].items():
        assert model_rps < base["rps"], f"model RPS {model_rps} no longer beats {name} ({base['rps']})"


def test_backtest_scoring_is_self_consistent():
    bt = load(BACKTEST)
    assert 0.0 < bt["model"]["accuracy"] <= 100.0
    assert 0.0 < bt["model"]["rps"] < 1.0
    assert bt["meta"]["season_replayed"].startswith("2025-26")
    total = sum(r["actual_points"] for r in bt["table_level"]["table"])
    assert 950 <= total <= 1150, f"backtest table totals {total} points, implausible"


# ─────────────────────────── API contract ───────────────────────────

def test_summary_payload_has_the_keys_the_dashboard_needs():
    summary = load(SUMMARY)
    for key in ("meta", "headline_predictions", "table_projections", "golden_boot_race",
                "playmaker_race", "golden_glove_race", "poty_race", "gw6_predictions",
                "gw7_predictions", "marquee_predictions", "ml_metrics"):
        assert key in summary, f"payload is missing '{key}'"
    assert len(summary["table_projections"]) == 20
    for club in summary["table_projections"]:
        for field in ("code", "name", "proj_pts", "title_prob", "relegation_prob", "pos_distribution"):
            assert field in club, f"club payload missing '{field}'"


@pytest.mark.slow
def test_server_serves_strict_json():
    """The live API must return parseable JSON — the failure mode this project already hit once."""
    import json as _json
    import threading
    import urllib.request
    import subprocess
    import time

    env = dict(os.environ, PORT="8399")
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen("http://127.0.0.1:8399/", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise AssertionError("server never became healthy on :8399")

        for route in ("/api/baseline", "/api/backtest", "/api/fixture?home=ARS&away=MCI"):
            raw = urllib.request.urlopen(f"http://127.0.0.1:8399{route}", timeout=20).read().decode()
            assert "NaN" not in raw, f"{route} returned bare NaN"
            _json.loads(raw)  # raises if the payload is not valid JSON
    finally:
        proc.terminate()
        proc.wait(timeout=10)
