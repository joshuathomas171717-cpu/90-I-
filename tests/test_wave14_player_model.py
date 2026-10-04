"""Phase 14: actual arithmetic and temporal boundaries, with no key/network.

Synthetic fixtures below are labelled test-only and never written to the shipped data. They prove
the gate machinery, not football accuracy. The real-data gate must remain not-measured until dated
history and genuine pre-kickoff captures exist.
"""
import copy
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

from _util import ROOT
from absence_model import choose_impact, combine_absences, measured_impact, replacement_prior
from congestion import normalise as normalise_calendar, rest_context
from player_data import exact_time, load_json, policy
from player_gate import (assess, candidate_lambdas, capture_for, eligible_history, evaluate,
                         features_for_fixture)
from player_history import dated_rows, from_provider, merge, normalise_fixture
from player_index import build_indices, form_index, squad_index


UTC = dt.timezone.utc


def row(**kwargs):
    return {"player": "Example Player", "player_id": "test-player", "club": "ARS",
            "position": "FWD", "competition": "Premier League", "minutes": 90,
            "goals": 1, "assists": 0, "source": "synthetic-test-only", **kwargs}


def fixture(**kwargs):
    return {"fixture_id": "test-one", "kickoff": "2025-08-16T14:00:00Z", "season": "2025-26",
            "home": "ARS", "away": "AVL", "home_goals": 1, "away_goals": 0,
            "competition": "Premier League", "source": "synthetic-test-only",
            "players": [row(), row(player_id="test-villa", club="AVL", goals=0)], **kwargs}


def test_recency_is_from_match_dates_not_fetch_timestamps():
    old = form_index([row(match_date="2026-08-01", fetched_at="2026-10-03")], "2026-10-03", "FWD")
    recent = form_index([row(match_date="2026-10-01", fetched_at="2026-10-01")], "2026-10-03", "FWD")
    assert recent["effective_minutes"] > old["effective_minutes"]*2
    assert old["recency"] == "dated-matches"


def test_season_totals_never_claim_per_match_recency():
    a = form_index([row(minutes=450, goals=5, fetched_at="2026-10-03")], "2026-10-03", "FWD")
    b = form_index([row(minutes=450, goals=5, fetched_at="2025-01-01")], "2026-10-03", "FWD")
    assert a["score"] == b["score"]
    assert "unavailable" in a["recency"] and a["detail"][0]["decay"] is None


def test_dated_matches_replace_instead_of_double_counting_season_totals():
    got = form_index([row(minutes=450, goals=5), row(match_date="2026-10-01", goals=1)], "2026-10-03", "FWD")
    assert got["raw_minutes"] == 90 and got["aggregate_rows"] == 0
    assert any("replaced" in e["reason"] for e in got["excluded"])


def test_future_match_and_future_aggregate_are_excluded():
    got = form_index([row(match_date="2026-10-10"), row(aggregate_through="2026-10-20")], "2026-10-03", "FWD")
    assert got["score"] is None and got["effective_minutes"] == 0 and len(got["excluded"]) == 2


def test_competition_adjustment_and_exclusions_are_read_from_the_table():
    league = form_index([row()], "2026-10-03", "FWD")
    europe = form_index([row(competition="UEFA Champions League")], "2026-10-03", "FWD")
    youth = form_index([row(competition="Youth or age-group")], "2026-10-03", "FWD")
    assert europe["effective_minutes"] > league["effective_minutes"]
    assert youth["score"] is None
    unknown = form_index([row(competition="Unlisted Competition")], "2026-10-03", "FWD")
    assert unknown["detail"][0]["matched"] is False


def test_unverified_international_minutes_do_not_sneak_into_form():
    unproven = form_index([row(competition="World Cup")], "2026-10-03", "FWD")
    verified = form_index([row(competition="World Cup", international_verified=True)], "2026-10-03", "FWD")
    assert unproven["score"] is None and verified["score"] is not None


def test_sparse_form_shrinks_more_than_a_regular_starters_sample():
    small = form_index([row(minutes=30, goals=1)], "2026-10-03", "FWD")
    large = form_index([row(minutes=900, goals=30)], "2026-10-03", "FWD")
    assert abs(small["score"]-50) < abs(large["score"]-50)
    huge = form_index([row(minutes=9000, goals=300)], "2026-10-03", "FWD")
    assert huge["effective_minutes"] == 1800 and huge["uncapped_effective_minutes"] == 9000


def test_a_goalkeeper_with_no_goals_is_not_labelled_in_bad_form():
    unknown = form_index([row(goals=0)], "2026-10-03", "GK")
    rated = form_index([row(goals=0, rating=8.1)], "2026-10-03", "Goalkeeper")
    assert unknown["score"] is None and rated["score"] > 50


def test_duplicate_match_rows_do_not_double_minutes():
    got = form_index([row(match_date="2026-10-01", fixture_id="1")]*2, "2026-10-03", "FWD")
    assert got["raw_minutes"] == 90 and got["dated_matches"] == 1


def test_identity_join_is_exact_name_and_club_not_fuzzy():
    roster = [{"player_id": "saka", "name": "Bukayo Saka", "club": "ARS", "pos": "FWD"}]
    good = build_indices([row(player="Bukayo Saka", player_id="7")], roster, "2026-10-03")[0]
    bad = build_indices([row(player="B. Saka", player_id="7", position=None)], roster, "2026-10-03")[0]
    assert good["player_id"] == "saka" and good["identity_match"] == "exact"
    assert bad["identity_match"] == "unmapped" and bad["position"] == "UNKNOWN"


def test_squad_aggregation_is_minutes_weighted_and_marked_partial():
    players = [{"club": "ARS", "score": 80., "effective_minutes": 300., "aggregate_rows": 0},
               {"club": "ARS", "score": 20., "effective_minutes": 100., "aggregate_rows": 0}]
    got = squad_index(players)["ARS"]
    assert got["index"] == 65 and "partial" in got["coverage"] and got["recency_available"]


def test_replacement_prior_uses_club_goals_not_the_partial_sample_sum():
    player = {"pos": "FWD", "mins_curr": 450, "goals_curr": 5, "assists_curr": 0}
    out = replacement_prior(player, {"P": 5, "GF": 20})
    assert out["output_share"] == .25 and out["attack_loss_pct"] == 7.5
    assert out["measured"] is False and out["replacement_retained"] == .70
    assert out["range"]["low"]["attack_loss_pct"] < out["attack_loss_pct"] < out["range"]["high"]["attack_loss_pct"]


def test_goalkeeper_and_defender_priors_include_defensive_roles():
    for role in ("GK", "DEF"):
        got = replacement_prior({"pos": role, "mins_curr": 450}, {"P": 5, "GF": 10})
        assert got["defence_cost_pct"] > 0 and "assumption" in got["defence_basis"]
    assert replacement_prior({"pos": "GK", "mins_curr": 450}, {"P": 5, "GF": 10})["attack_loss_pct"] == 0


def obs(i, **kw):
    return {"fixture_id": str(i), "club": "ARS", "player_id": "test-player",
            "kickoff": "2025-08-%02dT14:00:00Z" % (i+1), "minutes": 90 if i < 10 else 0,
            "gf": 3 if i < 10 else 1, "ga": 1 if i < 10 else 2,
            "expected_gf": 2., "expected_ga": 1., **kw}


def test_tier2_requires_enough_explicit_present_and_absent_games():
    rows = [obs(i) for i in range(15)]
    measured = measured_impact("test-player", "ARS", rows, "2025-10-01")
    assert measured["tier"] == 2 and measured["present_matches"] == 10 and measured["absent_matches"] == 5
    assert measured["attack_loss_pct"] > 0 and measured["defence_cost_pct"] > 0 and not measured["causal"]
    assert measured_impact("test-player", "ARS", rows[:14], "2025-10-01") is None


def test_tier2_excludes_future_and_null_minutes_not_assumed_absent():
    rows = [obs(i) for i in range(15)]
    rows[-1]["minutes"] = None
    rows.append(obs(16, kickoff="2027-01-01T14:00:00Z", gf=0, minutes=0))
    assert measured_impact("test-player", "ARS", rows, "2025-10-01") is None
    assert choose_impact({"player_id": "test-player", "club": "ARS", "pos": "FWD", "mins_curr": 450},
                         {"P": 5, "GF": 10}, observations=rows, cutoff="2025-10-01")["tier"] == 1


def test_opponent_adjustment_removes_a_schedule_only_output_difference():
    rows = [obs(i, gf=3 if i < 10 else 1, expected_gf=3 if i < 10 else 1,
                ga=1, expected_ga=1) for i in range(15)]
    got = measured_impact("test-player", "ARS", rows, "2025-10-01")
    assert abs(got["attack_loss_pct"]) < .0001 and abs(got["defence_cost_pct"]) < .0001


def test_same_day_statistics_embargo_prevents_in_match_lookahead():
    early = normalise_fixture(fixture())
    assert eligible_history([early], "2025-08-16T18:00:00Z") == []
    assert len(eligible_history([early], "2025-08-18T12:00:00Z")) == 1


def test_absence_combining_dedupes_and_keeps_unqueried_clubs_unknown():
    player = {"name": "Example Player", "player_id": "test-player", "club": "ARS",
              "absence": {"tier": 1, "attack_loss_pct": 10, "defence_cost_pct": 2}}
    capture = {"tracked": True, "clubs": {"ARS": [{"player": "Example Player"}]*2, "AVL": []},
               "coverage": {"ARS": "listed-only", "AVL": "unknown"}}
    got = combine_absences([player], capture)
    assert got["ARS"]["attack_loss_pct"] == 10 and got["ARS"]["mapped_absences"] == 1
    assert got["AVL"]["attack_loss_pct"] is None and got["AVL"]["tracked"] is False


def event(**kwargs):
    return {"club": "ARS", "fixture_id": "test", "kickoff": "2026-10-07T19:00:00Z",
            "known_at": "2026-10-01T12:00:00Z", "competition": "UEFA Champions League",
            "venue": "away", "travel_km": 1000., "minutes": 90., **kwargs}


def test_exact_rest_and_supplied_travel_beat_a_membership_flag():
    got = rest_context("ARS", "2026-10-10T19:00:00Z", [event()], known_by="2026-10-10T18:00:00Z")
    assert got["rest_days"] == 3 and got["travel_km"] == 1000 and got["fatigue_pct"] > 0
    earlier = rest_context("ARS", "2026-10-10T19:00:00Z", [event(kickoff="2026-10-01T19:00:00Z")])
    assert earlier["fatigue_pct"] == 0


def test_fixture_windows_are_not_made_into_fake_rest_days():
    got = rest_context("ARS", "10-12 October 2026", [event()])
    assert got["rest_days"] is None and got["fatigue_pct"] is None
    rows, problems = normalise_calendar([event(kickoff="2026-10-07")])
    assert rows == [] and problems
    assert exact_time("2026-10-07T19:00:00") is None


def test_future_unannounced_and_cancelled_calendar_events_do_not_count():
    got = rest_context("ARS", "2026-10-10T19:00:00Z", [event(kickoff="2026-10-11T19:00:00Z"),
        event(status="PST"), event(known_at="2026-10-10T20:00:00Z")], known_by="2026-10-10T18:00:00Z")
    assert got["rest_days"] is None


def test_unknown_away_travel_is_unknown_not_zero():
    rows, _ = normalise_calendar([event(travel_km=None)])
    got = rest_context("ARS", "2026-10-10T19:00:00Z", rows)
    assert got["travel_km"] is None and "incomplete" in got["status"]


def test_international_appearance_affects_one_player_not_the_whole_team():
    target = "2026-10-10T19:00:00Z"
    domestic = event(kickoff="2026-10-02T19:00:00Z", venue="home", travel_km=0)
    intl = event(fixture_id="national", international=True, player_id="test-player", travel_km=1000)
    got = rest_context("ARS", target, [domestic, intl])
    whole_team = rest_context("ARS", target, [event()])
    assert got["rest_days"] == 8 and got["fatigue_pct"] < whole_team["fatigue_pct"]
    assert len(got["international_players"]) == 1
    rejected, _ = normalise_calendar([event(international=True, player_id=None)])
    assert rejected == []


def test_history_intake_requires_real_dates_and_preserves_explicit_zeros():
    got = normalise_fixture(fixture(players=[row(minutes=0), row(player_id="null", minutes=None)]))
    assert got["players"][0]["minutes"] == 0 and got["players"][1]["minutes"] is None
    assert len(dated_rows([got])) == 1
    fixtures, problems = merge([], [fixture(kickoff="2025-08-16")], "2025-26")
    assert fixtures == [] and problems


def test_history_intake_rejects_future_statistics_claimed_before_kickoff():
    try:
        normalise_fixture(fixture(stats_available_at="2025-08-16T12:00:00Z"))
    except ValueError:
        return
    raise AssertionError("post-match stats claimed before kickoff were accepted")


def test_history_duplicates_correct_by_id_never_sum_results():
    old = fixture()
    fixtures, problems = merge([old], [{**old, "home_goals": 2}], "2025-26")
    assert len(fixtures) == 1 and fixtures[0]["home_goals"] == 2 and not problems
    duplicate, problems = merge([old], [fixture(fixture_id="different-id")], "2025-26")
    assert len(duplicate) == 1 and problems


def test_free_backfill_resumes_after_a_quota_stop_without_refetching_done_matches():
    import player_history
    from sources.api_football import QuotaExceeded
    first = fixture()
    second = fixture(fixture_id="two", home="MCI", away="CHE", kickoff="2025-08-18T14:00:00Z")
    class Provider:
        season = "2025"; name = "synthetic-test-only"
        def __init__(self, stopped): self.calls=[]; self.stopped=stopped
        def available(self): return True
        def fetch_match_history(self, replay=False): return [first, second]
        def fetch_fixture_players(self, fixture_id, replay=False):
            self.calls.append(fixture_id)
            if fixture_id == "two" and self.stopped: raise QuotaExceeded("test budget spent")
            return [row(club="ARS" if fixture_id == "test-one" else "MCI"),
                    row(player_id="other", club="AVL" if fixture_id == "test-one" else "CHE")]
    with tempfile.TemporaryDirectory() as tmp:
        original = player_history.history_path
        player_history.history_path = lambda season: os.path.join(tmp, "history.json")
        try:
            one = Provider(True); partial = from_provider(one, max_fixtures=10)
            assert len(partial["fixtures"]) == 1 and partial["problems"]
            two = Provider(False); resumed = from_provider(two, max_fixtures=10)
            assert len(resumed["fixtures"]) == 2 and two.calls == ["two"]
        finally:
            player_history.history_path = original


def test_no_key_backfill_is_inert_and_does_not_erase_existing_history():
    class Provider:
        season = "2025"
        def available(self): return False
        def unavailable_reason(self): return "no free key"
        def fetch_match_history(self, **kwargs): raise AssertionError("a socket would have opened")
    got = from_provider(Provider(), existing={"fixtures": [normalise_fixture(fixture())]})
    assert len(got["fixtures"]) == 1 and got["collected"] == 0


def test_pre_match_captures_cannot_be_replaced_by_post_match_lineup_data():
    target = normalise_fixture(fixture())
    valid = {"fixture_id": "test-one", "club": "ARS", "known_at": "2025-08-16T12:00:00Z",
             "tracked": True, "players_out": []}
    _, covered = capture_for(target, [valid, {**valid, "club": "AVL", "known_at": "2025-08-16T18:00:00Z"}])
    assert covered == {"ARS"}
    _, covered = capture_for(target, [{**valid, "known_at": None}])
    assert not covered


def test_future_results_and_own_fixture_appearances_do_not_change_features():
    prior = normalise_fixture(fixture())
    target = normalise_fixture(fixture(fixture_id="target", home="ARS", away="CHE", kickoff="2025-08-24T14:00:00Z"))
    future = normalise_fixture(fixture(fixture_id="future", home="ARS", away="MCI", kickoff="2025-09-01T14:00:00Z"))
    before = features_for_fixture(target, [prior, target, future], [], [])
    tampered = copy.deepcopy([prior, target, future])
    for f in tampered[1:]:
        f["home_goals"] = 99
        f["players"][0]["goals"] = 99
        f["players"][0]["minutes"] = 0
    after = features_for_fixture(target, tampered, [], [])
    assert before == after and before["history_matches"] == 1


def test_shadow_candidate_moves_goals_only_for_explicit_assumptions():
    empty = {"squads": {}, "absences": {}, "rest": {}}
    assert candidate_lambdas(2., 1., "ARS", "AVL", empty) == (2., 1.)
    missing = {**empty, "absences": {"ARS": {"tracked": True, "attack_loss_pct": 10, "defence_cost_pct": 5}}}
    got = candidate_lambdas(2., 1., "ARS", "AVL", missing)
    assert got[0] < 2 and got[1] > 1


def test_real_missing_history_reports_null_delta_not_a_fake_zero():
    got = evaluate(history={})
    assert got["mode"] == "context" and got["live_input_allowed"] is False
    assert got["shadow_verdict"] == "not-measured" and got["candidate"] is None
    assert got["delta"]["rps"] is None and got["test_matches"] == 0 and len(got["reasons"]) >= 3


def score_inputs():
    truth = np.arange(240)%3
    baseline = np.full((240, 3), 1/3)
    good = np.full((240, 3), .02); good[np.arange(240), truth] = .96
    dates = [(dt.datetime(2025, 8, 16, 14, tzinfo=UTC)+dt.timedelta(days=(i//10)*7)).isoformat() for i in range(240)]
    settings = policy(); settings["gate_bootstrap_samples"] = 100
    return baseline, good, truth, dates, settings


def test_gate_rejects_no_movement_and_missing_coverage_even_when_predictions_improve():
    baseline, good, truth, dates, settings = score_inputs()
    no_change = assess(baseline, baseline, truth, dates, 1., settings)
    assert no_change["shadow_verdict"] == "no-go" and no_change["delta"]["rps"] == 0
    incomplete = assess(baseline, good, truth, dates, .2, settings)
    assert incomplete["shadow_verdict"] == "no-go" and not incomplete["requirements"]["enough_pre_match_coverage"]


def test_gate_requires_both_metrics_and_block_uncertainty_not_just_a_pretty_point_estimate():
    baseline, good, truth, dates, settings = score_inputs()
    got = assess(baseline, good, truth, dates, 1., settings)
    assert got["shadow_verdict"] == "go" and got["paired_rps_delta_95pct"][1] < 0
    assert got["delta"]["accuracy_percentage_points"] > 0 and got["delta"]["rps"] < -.002
    bad = np.roll(good, 1, axis=1)
    assert assess(baseline, bad, truth, dates, 1., settings)["shadow_verdict"] == "no-go"


def test_context_builder_runs_from_another_directory_with_no_key():
    with tempfile.TemporaryDirectory() as tmp:
        env = {k: v for k, v in os.environ.items() if k not in ("API_FOOTBALL_KEY", "API_FOOTBALL_API_KEY", "APISPORTS_KEY", "FOOTBALL_DATA_KEY")}
        target = os.path.join(tmp, "context.json")
        result = subprocess.run([sys.executable, os.path.join(ROOT, "player_context.py"), "--out", target],
                                cwd=tmp, env=env, text=True, capture_output=True, timeout=90)
        assert result.returncode == 0, result.stderr
        context = load_json(target)
        assert context["mode"] == "context" and context["input_enabled"] is False
        assert context["coverage"]["players"] >= 40 and context["coverage"]["clubs"] == 20


def test_offline_pipeline_and_weekly_job_keep_the_gate_before_publication():
    build = open(os.path.join(ROOT, "run_all.py")).read()
    assert build.index('(\"player_gate.py\"') < build.index('(\"ml_engine.py\"') < build.index('(\"build_dashboard.py\"')
    weekly = open(os.path.join(ROOT, "update_week.py")).read()
    assert "_refresh_players" in weekly and '"player_context.py"' in weekly and '"player_gate.py"' in weekly
    workflow = open(os.path.join(ROOT, ".github", "workflows", "weekly-update.yml")).read()
    assert "secrets.API_FOOTBALL_KEY" in workflow and "PLAYER_CHANGES" in workflow


def test_partial_provider_availability_is_not_a_clean_bill_of_health():
    import availability
    cap = availability.build([], "api-football", problems=["AVL: quota spent"])
    assert cap["coverage"]["ARS"] == "checked" and cap["coverage"]["AVL"] == "failed"
    assert cap["tracked"] is True and "unknown" in availability.summarise(cap, club="AVL")


def test_live_model_card_and_dashboard_publish_context_status_and_no_fake_delta():
    page = open(os.path.join(ROOT, "static", "player-model.html")).read()
    app = open(os.path.join(ROOT, "static", "src", "app.html")).read()
    report = load_json(os.path.join(ROOT, "static", "player-model.json"))
    assert "Model card v3.0" in page and "Context only" in page and "Not measured" in page
    assert "association, not a causal" in page and "not a squad ranking" in page
    assert 'href="player-model.html"' in app and 'id="playerGateStatus"' in app
    assert report["context"]["input_enabled"] is False and report["gate"]["live_input_allowed"] is False
    assert '"rps": null' in json.dumps(report)


def test_model_card_escapes_player_source_and_gate_reason_text():
    import site_pages
    html = site_pages._player_model_page({"players": [], "coverage": {}}, {"reasons": ['<img src=x onerror="alert(1)">']})
    assert "&lt;img" in html and "<img src=x" not in html


def test_normalised_historical_club_codes_round_trip_without_current_season_membership():
    got = normalise_fixture(fixture(home="WHU", away="BUR", players=[row(club="WHU")]))
    assert got["home"] == "WHU" and got["away"] == "BUR" and got["players"][0]["club"] == "WHU"


def test_individual_dated_cup_and_national_rows_need_no_invented_pl_opponent():
    from player_history import normalise_match_rows
    rows, problems = normalise_match_rows([
        row(competition="FA Cup", match_date="2026-09-01", season="2026-27"),
        row(competition="UEFA Champions League", match_date="2026-09-15", season="2026-27"),
        row(competition="World Cup - Qualification", match_date="2026-09-05", season="2026-27", international_verified=True),
    ], "2026-27")
    assert len(rows) == 3 and not problems
    got = form_index(rows, "2026-10-03", "FWD")
    assert got["dated_matches"] == 3 and got["aggregate_rows"] == 0


def test_full_shadow_replay_uses_chronology_and_never_promotes_the_untested_live_head():
    """Invented timestamps are strictly TEST FIXTURES, not a backfill of the real season."""
    from player_data import load_csv
    results = load_csv(os.path.join(ROOT, "data", "matches_2025_26.csv"))
    fixtures, captures = [], []
    for i, result in enumerate(results):
        date = dt.datetime(2025, 8, 16, 14, tzinfo=UTC)+dt.timedelta(days=(i//10)*7, hours=i%10)
        h, a = result["home"], result["away"]
        fixtures.append(fixture(fixture_id="test-%d" % i, kickoff=date.isoformat(), home=h, away=a,
            home_goals=int(result["home_goals"]), away_goals=int(result["away_goals"]),
            players=[row(player_id="synthetic-"+h, club=h, goals=int(result["home_goals"])),
                     row(player_id="synthetic-"+a, club=a, goals=int(result["away_goals"]))]))
        for club in (h, a):
            captures.append({"fixture_id": "test-%d" % i, "club": club, "tracked": True,
                             "known_at": (date-dt.timedelta(hours=2)).isoformat(), "players_out": []})
    report = evaluate(history={"fixtures": list(reversed(fixtures)), "availability": captures}, result_rows=results)
    assert report["dated_fixtures_joined"] == 380 and report["test_matches"] == 260
    assert report["candidate"] is not None and report["delta"]["rps"] is not None
    assert [p["kickoff"] for p in report["predictions"]] == sorted(p["kickoff"] for p in report["predictions"])
    assert report["mode"] == "context" and report["live_input_allowed"] is False
    assert report["shadow_verdict"] in ("go", "no-go") and "structural" in report["scope"]


def test_deploy_check_detects_new_context_even_if_matchweek_and_data_date_are_the_same():
    from tools.verify_deployment import compare
    want = {"matchweek": 6, "as_of": "2026-10-03", "season": "PL", "player_context": "new-hash"}
    got = {**want, "player_context": "old-hash"}
    checks = compare(want, got)
    assert not all(ok for *_, ok in checks)
    assert next(c for c in checks if c[0] == "player_context")[-1] is False


def test_audit_does_not_mislabel_europa_league_as_international_coverage():
    from tools.audit_sources import audit
    from player_data import load_csv
    clubs = load_csv(os.path.join(ROOT, "data", "teams_2026_27.csv"))
    class Provider:
        def available(self): return True
        def fetch_teams(self, **kwargs): return [{"code": c["code"], "id": i} for i,c in enumerate(clubs)]
        def fetch_club_players(self, team, **kwargs): return [row(competition="UEFA Europa League")]
        def fetch_injuries(self, team, **kwargs): return []
    results = audit(Provider())
    check = next(c for c in results if c["check"] == "international competitions present")
    assert check["status"] == "not-proven"


def test_new_model_card_scroll_regions_are_keyboard_accessible_and_prose_links_underlined():
    from html.parser import HTMLParser
    class Check(HTMLParser):
        def __init__(self): super().__init__(); self.tables=[]
        def handle_starttag(self, tag, attrs):
            props=dict(attrs)
            if tag=='div' and props.get('class')=='tablewrap': self.tables.append(props)
    page=open(os.path.join(ROOT,'static','player-model.html')).read()
    check=Check();check.feed(page)
    assert len(check.tables)==3
    assert all(p.get('tabindex')=='0' and p.get('aria-label') and p.get('role')=='region' for p in check.tables)
    assert '.player-layer p a,footer.site a{text-decoration:underline' in page


def test_a_measured_model_card_compares_the_same_holdout_not_full_season_to_holdout():
    import site_pages
    page = site_pages._player_model_page({"coverage": {}}, {
        "baseline_full_season": {"accuracy": 99.9, "rps": .9999},
        "baseline": {"accuracy": 40., "rps": .1111},
        "candidate": {"accuracy": 45., "rps": .1000}, "test_matches": 260,
        "fixtures_in_result_matrix": 380, "delta": {"rps": -.0111},
        "reasons": ["structural shadow only"]})
    assert "0.1111" in page and "0.9999" not in page
    assert '<td class="num">260</td><td class="num">260</td>' in page
    assert "matched chronological structural holdout" in page
