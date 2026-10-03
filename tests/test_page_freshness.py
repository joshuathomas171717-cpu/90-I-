"""The published page is the page the committed data describes (P4.4).

These tests exercise the *logic* of check_page_current.py on small synthetic pages, deliberately.
The gate itself runs against the real repository as the final step of `run_all.py` — it cannot run
from in here, because during a full pipeline run the dataset has already been regenerated while the
committed page has not yet been rebuilt, and the mismatch is the expected state at that moment, not a
failure.

Two bugs found by running the real thing against a real CI environment are frozen as tests below,
because both of them were silent and both would have come back:

* entries in a ranked list were compared position by position, so a reshuffled near-tie compared one
  player's numbers against another's;
* an entry missing from one side was reported as sitting at rank 1, which turned routine tail churn
  in a race into "the top five changed".
"""
import json
import os
import sys

from _util import ROOT, skip

sys.path.insert(0, ROOT)
import check_page_current as gate  # noqa: E402


# ── a small stand-in for the real payload ────────────────────────────────────────────────────────
def _payload(title_prob=52.5, relegation=40.0, goals=29.4, goals_p90=40, next_gw=6,
             as_of="2026-10-03 (Matchweek 5 Complete)", clubs=("MCI", "IPS"), scoreline_prob=12.8):
    return {
        "baseline": {
            "meta": {"next_gw": next_gw, "as_of_date": as_of},
            "ml_metrics": {"remaining_fixtures": 330, "runtime_ms": 500.7},
            "table_projections": [
                {"code": code,
                 "proj_pts": 82.4 if code == "MCI" else 29.2,
                 "title_prob": title_prob if code == "MCI" else 0.0,
                 "relegation_prob": 0.0 if code == "MCI" else relegation,
                 "pos_distribution": [61.7, 2.1] if code == "MCI" else [0.4, 61.2]}
                for code in clubs],
            "golden_boot_race": [
                {"player_id": "haaland", "name": "Erling Haaland", "proj_goals": goals, "goals_p90": goals_p90},
                {"player_id": "isak", "name": "Alexander Isak", "proj_goals": 18.2, "goals_p90": 26},
                {"player_id": "gyokeres", "name": "Viktor Gyökeres", "proj_goals": 12.1, "goals_p90": 19},
            ],
            "gw6_predictions": [
                {"home": "ARS", "away": "LEE", "prob_home": 68.5, "lambda_home": 2.12,
                 "top_scorelines": [{"score": "1-1", "home_goals": 1, "away_goals": 1, "prob": scoreline_prob},
                                    {"score": "2-1", "home_goals": 2, "away_goals": 1, "prob": 9.5}]},
            ],
        },
        "inputs": {"teams": [{"code": "MCI", "value_m": 1280}]},
        "h2h": {"MCI-IPS": {"home_wins": 3, "away_wins": 1}},
    }


def _page(payload, hero="Matchweek 6 · 10-12 October 2026",
          sub="Premier League 2026–27 · model v2.1 · as of 2026-10-03 (Matchweek 5 Complete)"):
    return ("<!DOCTYPE html><html><body>"
            '<p id="heroKick">%s</p><p id="markSub">%s</p>'
            "<script>const EMBEDDED = %s;</script>"
            "</body></html>" % (hero, sub, json.dumps(payload, separators=(",", ":"))))


def _write(tmp_path, name, payload, **kw):
    path = os.path.join(str(tmp_path), name)
    open(path, "w", encoding="utf-8").write(_page(payload, **kw))
    return path


def _write_summary(tmp_path, payload, name="summary.json"):
    path = os.path.join(str(tmp_path), name)
    json.dump(payload["baseline"], open(path, "w", encoding="utf-8"))
    return path


# ════════════════════════════════════════════════════════════════════════════
#  the exact half: the page against the data it was built from
# ════════════════════════════════════════════════════════════════════════════
def test_a_page_that_carries_its_own_data_passes(tmp_path):
    payload = _payload()
    page = _write(tmp_path, "index.html", payload)
    summary = _write_summary(tmp_path, payload)
    assert gate.check(page, summary) == []


def test_a_page_that_was_never_rebuilt_is_caught(tmp_path):
    payload = _payload()
    page = _write(tmp_path, "index.html", payload)
    # the dataset moved on; the page did not
    changed = _payload(title_prob=48.0, relegation=44.1)
    summary = _write_summary(tmp_path, changed)
    problems = gate.check(page, summary)
    assert problems, "a page whose numbers no longer match the data must not pass"
    assert "rebuild" in problems[0].lower(), problems
    assert any("title_prob" in p for p in problems), problems


def test_a_stale_header_stamp_is_caught(tmp_path):
    """The stamp is plain text in the HTML, so it is the one claim checkable without running JS."""
    payload = _payload(next_gw=7)
    page = _write(tmp_path, "index.html", payload, hero="Matchweek 6 · 10-12 October 2026")
    summary = _write_summary(tmp_path, payload)
    problems = gate.check(page, summary)
    assert any("matchweek 7" in p for p in problems), problems


def test_a_page_without_a_payload_is_reported_not_crashed(tmp_path):
    page = os.path.join(str(tmp_path), "index.html")
    open(page, "w", encoding="utf-8").write("<html><body>no payload here</body></html>")
    problems = gate.check(page, _write_summary(tmp_path, _payload()))
    assert problems and "EMBEDDED" in problems[0], problems


# ════════════════════════════════════════════════════════════════════════════
#  the tolerant half: two builds of the same page in different environments
# ════════════════════════════════════════════════════════════════════════════
def test_drift_of_the_size_a_real_ci_environment_produces_is_tolerated(tmp_path):
    """Every number below is what a real CI run moved, measured on 2026-10-03.

    numpy 2.5.3 / scipy 1.18.1 / scikit-learn 1.9.1 against the versions the page was built with:
    no structural change anywhere, probabilities inside a couple of points, integer quantiles one
    step. That build is a current page, and it must not be called stale.
    """
    committed = _payload()
    rebuilt = _payload(title_prob=52.4, relegation=43.7, goals=29.3, goals_p90=39,
                       scoreline_prob=12.5)
    # the tail of the race reshuffles on a near-tie, which is noise, not news
    rebuilt["baseline"]["golden_boot_race"][1], rebuilt["baseline"]["golden_boot_race"][2] = (
        rebuilt["baseline"]["golden_boot_race"][2], rebuilt["baseline"]["golden_boot_race"][1])
    problems = gate.compare_builds(_write(tmp_path, "rebuilt.html", rebuilt),
                                   _write(tmp_path, "committed.html", committed))
    assert problems == [], problems


def test_a_probability_moving_by_points_is_not_drift(tmp_path):
    committed = _payload(relegation=40.0)
    rebuilt = _payload(relegation=62.0)
    problems = gate.compare_builds(_write(tmp_path, "rebuilt.html", rebuilt),
                                   _write(tmp_path, "committed.html", committed))
    assert problems, "a 22-point move in a relegation probability is a change, not noise"


def test_a_club_appearing_or_vanishing_is_structural(tmp_path):
    committed = _payload(clubs=("MCI", "IPS"))
    rebuilt = _payload(clubs=("MCI", "IPS", "COV"))
    problems = gate.compare_builds(_write(tmp_path, "rebuilt.html", rebuilt),
                                   _write(tmp_path, "committed.html", committed))
    assert any("COV" in p for p in problems), problems


def test_a_different_matchweek_is_structural(tmp_path):
    """Integers are normally allowed a step of drift; a gameweek marker never is."""
    problems = gate.compare_builds(_write(tmp_path, "rebuilt.html", _payload(next_gw=7)),
                                   _write(tmp_path, "committed.html", _payload(next_gw=6)))
    assert any("next_gw" in p for p in problems), problems


def test_a_page_a_week_behind_is_never_dismissed_as_noise(tmp_path):
    """The likeliest way for this page to be wrong, and the one an integer tolerance would hide."""
    problems = gate.compare_builds(
        _write(tmp_path, "rebuilt.html", _payload(next_gw=7, as_of="2026-10-21 (Matchweek 6 Complete)")),
        _write(tmp_path, "committed.html", _payload(next_gw=6)))
    assert len(problems) >= 2, problems
    assert any("as_of_date" in p for p in problems), problems


def test_entries_are_compared_by_identity_not_by_position(tmp_path):
    """The regression test for the bug that made the first version of this gate useless.

    When a race reshuffles, comparing index 1 with index 1 compares Isak's numbers with Gyökeres's
    and reports a huge, entirely imaginary change. Aligned by player_id, the same reshuffle is a
    non-event — and the numbers themselves are untouched, so the gate is silent.
    """
    committed = _payload()
    rebuilt = _payload()
    race = rebuilt["baseline"]["golden_boot_race"]
    # same entries, same numbers, different order
    rebuilt["baseline"]["golden_boot_race"] = [race[2], race[0], race[1]]
    problems = gate.compare_builds(_write(tmp_path, "rebuilt.html", rebuilt),
                                   _write(tmp_path, "committed.html", committed))
    assert problems == [], problems


def test_a_change_at_the_top_of_a_race_is_still_structural(tmp_path):
    committed = _payload()
    rebuilt = _payload()
    rebuilt["baseline"]["golden_boot_race"] = rebuilt["baseline"]["golden_boot_race"][:2] + [
        {"player_id": "kowalski", "name": "A Newcomer", "proj_goals": 30.0, "goals_p90": 41}]
    problems = gate.compare_builds(_write(tmp_path, "rebuilt.html", rebuilt),
                                   _write(tmp_path, "committed.html", committed))
    assert any("kowalski" in p or "Gyökeres" in p for p in problems), problems


def test_the_build_timing_is_not_compared(tmp_path):
    """runtime_ms describes the machine, not the season. Comparing it would fail CI every week."""
    committed = _payload()
    rebuilt = _payload()
    rebuilt["baseline"]["ml_metrics"]["runtime_ms"] = 913.4
    problems = gate.compare_builds(_write(tmp_path, "rebuilt.html", rebuilt),
                                   _write(tmp_path, "committed.html", committed))
    assert problems == [], problems


def test_data_derived_numbers_are_compared_exactly(tmp_path):
    """`inputs` and `h2h` are pass-throughs of committed CSVs: they cannot legitimately differ.

    Measured across a real CI environment, all 2,632 of these numbers were identical while the
    projections around them drifted — which is what makes exactness here safe, and makes it the
    strongest signal in the gate. A single squad value moving by one unit is a real edit.
    """
    committed = _payload()
    rebuilt = _payload()
    rebuilt["inputs"]["teams"][0]["value_m"] = 1279
    problems = gate.compare_builds(_write(tmp_path, "rebuilt.html", rebuilt),
                                   _write(tmp_path, "committed.html", committed))
    assert problems and any("value_m" in p for p in problems), problems


def test_a_head_to_head_count_cannot_drift(tmp_path):
    committed = _payload()
    rebuilt = _payload()
    rebuilt["h2h"]["MCI-IPS"]["home_wins"] = 2
    problems = gate.compare_builds(_write(tmp_path, "rebuilt.html", rebuilt),
                                   _write(tmp_path, "committed.html", committed))
    assert problems and any("home_wins" in p for p in problems), problems
