"""Phase 13 — the player signal: weights, the keyless path, and who was out (P13.1–P13.4).

The rule every file in this phase follows is the same one: **the feature must be honest about what it
does not have.** A player signal assembled from league minutes alone is a league-level player signal, and
a model whose availability is unknown is not a model with nobody injured. Most of these tests exist to
pin that distinction, because it is the one that erodes silently — a missing value that reads as a zero
looks exactly like data.

The other half is the keyless promise. The user this is built for has no card and no account, so the
whole chain has to run from files: `tests/test_wave13_players.py` builds a form table, an availability
capture and a competition-weighted index from drop files alone, and asserts every one of them works.
"""
import csv
import json
import os
import subprocess
import sys
import tempfile

from _util import ROOT, skip

DATA = os.path.join(ROOT, "data")
sys.path.insert(0, ROOT)

import competition_weights as CW      # noqa: E402
import player_form                    # noqa: E402
import availability as AV             # noqa: E402


def _check(condition, message):
    if not condition:
        raise AssertionError(message)


def _read(path, base=None):
    with open(os.path.join(base, path) if base else path, encoding="utf-8") as fh:
        return fh.read()


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  P13.4 — the weights are data, and the unknown case is flagged
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_weight_table_loads_and_is_anchored_to_the_league():
    rows = CW.table()
    _check(len(rows) >= 15, "the competition table has shrunk to %d rows" % len(rows))
    _check(rows["premier_league"]["weight"] == 1.0,
           "the Premier League is no longer the 1.00 reference everything else is read against")
    for key, row in rows.items():
        _check(0.3 <= row["weight"] <= 1.5,
               "%s has a weight of %s, which is outside any defensible range" % (key, row["weight"]))
        _check(row["note"].strip(), "%s carries no note — a weight without a reason is a guess" % key)


def test_the_weights_live_in_data_not_in_the_loader():
    """A table a reviewer can diff. If the numbers move into the module, this fails."""
    source = _read("competition_weights.py")
    for suspicious in ("1.08", "0.95", "0.88", "1.12"):
        _check('"%s"' % suspicious not in source and "'%s'" % suspicious not in source,
               "the loader contains the literal weight %s — the table belongs in the CSV" % suspicious)
    _check(os.path.exists(os.path.join(DATA, "competition_weights.csv")), "the table file is missing")


def test_every_competition_the_sources_return_has_an_entry():
    """The names the providers actually use, including the ones that need an alias rather than a match."""
    cases = {
        "Premier League": "premier_league", "PL": "premier_league",
        "UEFA Champions League": "champions_league", "Champions League": "champions_league",
        "UEFA Champions League Qualification": "champions_league_qualification",
        "Champions League Qualification": "champions_league_qualification",
        "FA Cup": "fa_cup", "EFL Cup": "efl_cup", "Carabao Cup": "efl_cup",
        "WC Qualification": "world_cup_qualification",
        "WC Qualification Europe": "world_cup_qualification",
        "UEFA Nations League": "nations_league", "Friendlies": "friendlies",
        "World Cup": "world_cup", "UEFA European Championship": "euro",
        "Africa Cup of Nations": "afcon", "FIFA Club World Cup": "fifa_club_world_cup",
    }
    for name, expected in cases.items():
        weight, key, matched = CW.lookup(name)
        _check(matched, "'%s' was not matched by the table" % name)
        _check(key == expected, "'%s' resolved to %s, expected %s" % (name, key, expected))


def test_qualification_is_not_swallowed_by_the_tournament_it_qualifies_for():
    """The substring matcher's own trap: 'Qualification' contains 'Champions League'."""
    _, key, _ = CW.lookup("UEFA Champions League Qualification")
    _check(key == "champions_league_qualification",
           "Champions League Qualification resolved to %s — the longest match must win" % key)
    league, _, _ = CW.lookup("UEFA Champions League")
    _check(league == CW.table()["champions_league"]["weight"], "the tournament itself stopped matching")


def test_an_unknown_competition_is_flagged_and_priced_below_the_league():
    weight, key, matched = CW.lookup("Some Sunday League")
    _check(not matched, "an unlisted competition was silently accepted as known")
    _check(weight < 1.0, "an unknown competition is valued at or above the league (%s)" % weight)
    _check(key == "other_known", "the fallback key changed: %s" % key)


def test_excluded_competitions_are_recorded_rather_than_dropped():
    """Pre-season and age-group minutes do not count, and the caller is told why rather than left to
    wonder where 300 minutes went."""
    body = [{"competition": "Premier League", "minutes": 900},
            {"competition": "Club Friendlies", "minutes": 300},
            {"competition": "Youth or age-group", "minutes": 120}]
    result = CW.league_equivalent_minutes(body)
    _check(abs(result["raw"] - 900.0) < 1e-6,
           "excluded competitions leaked into the total: %s" % result["raw"])
    _check(len(result["excluded"]) == 2, "the excluded minutes were not reported: %s" % result["excluded"])
    for entry in result["excluded"]:
        _check(entry["why"].strip(), "an excluded competition carried no reason")


def test_the_minutes_cap_binds_and_says_so():
    body = [{"competition": "Premier League", "minutes": 3000}]
    result = CW.league_equivalent_minutes(body)
    _check(result["capped"] is True, "a 3000-minute body was not capped")
    _check(result["minutes"] == 1800, "the cap is no longer 1800: %s" % result["minutes"])
    _check(result["raw"] > result["minutes"], "the uncapped figure was not preserved for the record")


def test_sensitivity_moves_and_is_reported_per_competition():
    """A perturbation check that cannot move has proved nothing, so the body is a real one."""
    body = [{"competition": "Premier League", "minutes": 720},
            {"competition": "UEFA Champions League", "minutes": 420},
            {"competition": "FA Cup", "minutes": 90}]
    scores = CW.sensitivity([body])
    _check(scores.get("premier_league", 0) > 0.01,
           "moving the league weight by 10%% moved the index by %s — the check is inert"
           % scores.get("premier_league"))
    _check(scores.get("champions_league", 0) > 0.01, "the European weight had no effect on the index")
    _check(scores.get("fa_cup", 0) < scores.get("premier_league", 1),
           "a 90-minute cup contribution moved the index more than 720 league minutes — the sensitivity "
           "function is not measuring what it says")
    key, worst = CW.largest_lever(scores)
    _check(key and worst > 0, "no largest lever was identified")


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  P13.2 — the keyless path produces the same table shape as the fetch path
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_a_drop_file_produces_a_form_table_with_no_key_and_no_network():
    with tempfile.TemporaryDirectory() as tmp:
        drop = os.path.join(tmp, "players")
        os.makedirs(drop)
        payload = {"source": "typed-by-hand", "players": [
            {"player": "A Striker", "club": "ARS", "competition": "Premier League", "minutes": 810,
             "goals": 6, "assists": 2},
            {"player": "A Striker", "club": "ARS", "competition": "UEFA Champions League", "minutes": 360,
             "goals": 3, "assists": 1},
            {"player": "A Cup Keeper", "club": "ARS", "competition": "EFL Cup", "minutes": 180},
        ]}
        with open(os.path.join(drop, "hand.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

        rows, problems = player_form.rows_from_drop(drop)
        _check(not problems, "a well-formed drop file produced problems: %s" % problems)
        _check(len(rows) == 3, "expected three rows, got %d" % len(rows))
        _check(all(r["club"] == "ARS" for r in rows), "the club code was not resolved")
        _check(rows[0]["source"] == "typed-by-hand",
               "the drop file's declared source was ignored (got %r) — provenance has to be exact"
               % rows[0]["source"])
        table = player_form.normalise(rows)
        _check(len(table) == 3, "normalise changed the row count: %d" % len(table))
        meta = player_form.summarise(table)
        _check(meta["players"] == 2 and meta["clubs"] == ["ARS"], "the summary miscounted: %s" % meta)
        _check("ARS" not in meta["clubs_missing"],
               "ARS supplied the only data and is still listed as missing")
        _check(len(meta["clubs_missing"]) == 19, "expected 19 clubs with no data, got %d"
               % len(meta["clubs_missing"]))


def test_duplicate_rows_collapse_to_the_largest_innings():
    rows = [{"player": "X", "club": "ARS", "competition": "Premier League", "minutes": 100},
            {"player": "x", "club": "ARS", "competition": "Premier League", "minutes": 640}]
    table = player_form.normalise(rows)
    _check(len(table) == 1, "a player+competition duplicate survived: %d rows" % len(table))
    _check(table[0]["minutes"] == 640,
           "the smaller record won (%s) — partial records must not be summed or preferred"
           % table[0]["minutes"])


def test_a_bad_drop_row_is_reported_not_swallowed():
    with tempfile.TemporaryDirectory() as tmp:
        drop = os.path.join(tmp, "players")
        os.makedirs(drop)
        with open(os.path.join(drop, "bad.json"), "w", encoding="utf-8") as fh:
            json.dump({"players": [{"player": "No Club", "minutes": 90},
                                   {"club": "ARS", "minutes": 90},
                                   {"player": "Fine", "club": "ARS", "minutes": 90}]}, fh)
        rows, problems = player_form.rows_from_drop(drop)
        _check(len(rows) == 1, "expected exactly one good row, got %d" % len(rows))
        _check(len(problems) == 2, "expected two problems to be reported, got %s" % problems)
        _check(any("no club" in p for p in problems), "the unmatched-club reason was not given")


def test_the_shipped_form_table_is_real_and_declares_its_scope():
    """Whatever is committed must be internally consistent and must not claim more than it has."""
    meta = player_form.load_meta()
    rows = player_form.load_form()
    if not rows:
        skip("no form table committed yet — run tools/export_players_drop.py")
    _check(meta.get("rows") == len(rows),
           "the provenance says %s rows and the table has %d" % (meta.get("rows"), len(rows)))
    _check(meta.get("generated_at"), "the provenance carries no timestamp")
    _check(meta.get("sources"), "the provenance does not say where the rows came from")
    for row in rows:
        _check(row["competition"], "a row with no competition cannot be weighted")
        _check(int(row["minutes"] or 0) > 0 or row["minutes"] == "0",
               "a non-numeric minute count reached the table: %r" % row["minutes"])
    # the league-only limit is the honest one to state, and it is stated in the provenance
    league_only = set(meta.get("competitions") or {}) == {"Premier League"}
    declared = " ".join(meta.get("sources") or [])
    if league_only:
        _check("dataset" in declared or "drop" in declared or "manual" in declared,
               "a league-only table is claiming a source that would have supplied more")


def test_the_bootstrap_exporter_writes_rows_the_loader_accepts():
    """Round trip: our own dataset -> drop file -> form table. This is the path with no key in it."""
    out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "export_players_drop.py"),
                          "--stdout"], capture_output=True, text=True, cwd=ROOT)
    _check(out.returncode == 0, "the exporter failed: %s" % (out.stderr or out.stdout))
    payload = json.loads(out.stdout)
    _check(payload["players"], "the exporter produced no players")
    _check(payload.get("competition_scope") == ["Premier League"],
           "the exporter no longer declares its league-only scope: %r" % payload.get("competition_scope"))
    with tempfile.TemporaryDirectory() as tmp:
        drop = os.path.join(tmp, "players")
        os.makedirs(drop)
        with open(os.path.join(drop, "dataset.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        rows, problems = player_form.rows_from_drop(drop)
        _check(not problems, "the exporter's own output was rejected: %s" % problems)
        _check(len(rows) >= 40, "the exporter produced only %d players" % len(rows))


def test_an_empty_collection_never_empties_an_existing_table():
    """Prove both guard and explicit override in a disposable project, never the real dataset."""
    import shutil
    with tempfile.TemporaryDirectory() as tmp:
        project = os.path.join(tmp, "project")
        shutil.copytree(ROOT, project, ignore=shutil.ignore_patterns(
            ".git", "artifacts", "__pycache__", "node_modules", "raw", "staging", "provider_drop"))
        table = os.path.join(project, "data", "players_form_2026_27.csv")
        meta = os.path.join(project, "data", "players_form_2026_27.meta.json")
        player_form.write([{"player": "X", "club": "ARS", "competition": "Premier League",
                            "minutes": 90}], {"rows": 1}, out_csv=table, out_meta=meta)
        script = os.path.join(project, "player_form.py")
        out = subprocess.run([sys.executable, script, "--source", "local", "--quiet"],
                             capture_output=True, text=True, cwd=tmp)
        _check(out.returncode == 1, "an empty pull did not refuse to overwrite a good table")
        _check(len(player_form.load_form(table)) == 1, "the rejected empty pull erased the good table")
        out = subprocess.run([sys.executable, script, "--source", "local", "--force", "--quiet"],
                             capture_output=True, text=True, cwd=tmp)
        _check(out.returncode == 0, "the explicit forced empty write failed")
        _check(player_form.load_form(table) == [], "--force did not perform the requested empty write")


def test_the_provider_is_inert_without_a_key():
    """No key: no calls, no crash, and a reason a reader can act on."""
    from sources.api_football import ApiFootballProvider
    provider = ApiFootballProvider(token=None)
    provider.token = None
    _check(provider.available() is False, "the provider claims to be available with no key")
    reason = provider.unavailable_reason()
    _check("API_FOOTBALL_KEY" in reason, "the reason does not name the variable to set")
    _check("free" in reason.lower() or "100" in reason, "the reason does not say how to get one free")
    described = provider.describe()
    _check(described["available"] is False, "describe() disagrees with available()")


def test_the_daily_budget_stops_the_run_and_persists_across_processes():
    """The free tier's real limit is 100 requests a day. The budget is lower, and it is a hard stop."""
    from sources.api_football import Quota
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "quota.json")
        quota = Quota(path=path, budget=3, day="2026-10-05")
        _check([quota.spend() for _ in range(3)] == [True, True, True], "the budget stopped too early")
        _check(quota.spend() is False, "a fourth request went ahead on a budget of three")
        # a new process on the same day must not get a fresh allowance
        again = Quota(path=path, budget=3, day="2026-10-05")
        _check(again.left == 0, "a second process re-spent the same day's budget: left=%d" % again.left)
        # and a new day does reset, because the provider's does
        tomorrow = Quota(path=path, budget=3, day="2026-10-06")
        _check(tomorrow.left == 3, "the allowance did not reset on a new UTC day")


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  P13.3 — availability, dated, and never confused with "nobody is out"
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_an_untracked_capture_says_untracked_rather_than_empty():
    payload = AV.build([], "none", problems=[], gameweek=6)
    _check(payload["tracked"] is False, "an empty capture claims to be tracked")
    _check(payload["source"] == "none", "the source of an empty capture is not 'none': %r" % payload["source"])
    _check(len(payload["clubs"]) == 20,
           "clubs were omitted rather than listed with nothing — 'checked' and 'not checked' must differ")
    text = AV.summarise(payload)
    _check("not tracked" in text, "the summary does not say the capture is untracked: %r" % text)


def test_a_capture_from_a_drop_file_is_dated_and_per_club():
    with tempfile.TemporaryDirectory() as tmp:
        drop = os.path.join(tmp, "injuries")
        os.makedirs(drop)
        with open(os.path.join(drop, "gw6.json"), "w", encoding="utf-8") as fh:
            json.dump({"source": "club-website", "injuries": [
                {"player": "A Defender", "club": "ARS", "type": "Injury", "reason": "Hamstring",
                 "since": "2026-10-01"},
                {"player": "A Midfielder", "club": "MCI", "type": "Suspension", "reason": "5 yellows",
                 "since": "2026-10-05"},
            ]}, fh)
        rows, problems = AV.from_drop(drop)
        _check(not problems, "a good capture produced problems: %s" % problems)
        _check(len(rows) == 2, "expected two absentees, got %d" % len(rows))
        _check(rows[0]["source"] == "club-website", "the declared source was ignored")
        payload = AV.build(rows, "manual-drop", gameweek=6)
        _check(payload["tracked"] is True, "a real capture is marked untracked")
        _check(payload["totals"]["players_out"] == 2, "totals miscounted: %s" % payload["totals"])
        _check(payload["totals"]["clubs_reporting"] == 2, "reporting clubs miscounted")
        _check(len(payload["clubs"]["ARS"]) == 1 and payload["clubs"]["ARS"][0]["reason"] == "Hamstring",
               "the injury detail did not land on the club")
        _check(len(payload["clubs"]["TOT"]) == 0, "a club with nobody out was not listed as empty")
        line = AV.summarise(payload, club="ARS")
        _check("A Defender" in line and "Injury" in line, "the per-club summary is not readable: %r" % line)


def test_availability_is_attached_inside_the_snapshot_it_belongs_to():
    snapshot = {"gameweek": 6, "predictions": [{"home": "ARS"}]}
    payload = AV.build([{"player": "A Defender", "club": "ARS", "type": "Injury",
                         "reason": "Hamstring", "since": "2026-10-01"}], "manual-drop", gameweek=6)
    attached = AV.attach(snapshot, payload)
    _check(attached["availability"]["gameweek"] == 6, "the capture is not stamped with its gameweek")
    _check(attached["availability"]["clubs"]["ARS"], "the capture lost its content on attach")
    _check(attached["predictions"] == [{"home": "ARS"}], "attaching availability damaged the snapshot")


def test_an_untracked_capture_never_overwrites_a_tracked_one():
    """Re-running the job offline must not erase what was known at lock time."""
    tracked = {"gameweek": 6, "availability": {"tracked": True, "source": "api-football",
                                               "clubs": {"ARS": [{"player": "A Defender"}]},
                                               "totals": {"players_out": 1, "clubs_reporting": 1}}}
    untracked = AV.build([], "none", gameweek=7)
    kept = AV.attach(json.loads(json.dumps(tracked)), untracked)
    _check(kept["availability"]["source"] == "api-football",
           "an offline re-run replaced a tracked capture with an untracked one")
    _check(kept["availability"]["clubs"]["ARS"], "the recorded absences were lost")
    # and a real capture does replace one, which is the point of re-running it online
    fresh = AV.build([{"player": "B Striker", "club": "MCI", "type": "Injury", "reason": "Ankle",
                       "since": "2026-10-05"}], "api-football", gameweek=7)
    replaced = AV.attach(json.loads(json.dumps(tracked)), fresh)
    _check(replaced["availability"]["source"] == "api-football"
           and replaced["availability"]["clubs"]["MCI"], "a fresh capture was not applied")


def test_a_missing_club_in_an_injury_drop_is_reported():
    with tempfile.TemporaryDirectory() as tmp:
        drop = os.path.join(tmp, "injuries")
        os.makedirs(drop)
        with open(os.path.join(drop, "x.json"), "w", encoding="utf-8") as fh:
            json.dump([{"player": "Someone", "club": "NOPE", "reason": "Knee"}], fh)
        rows, problems = AV.from_drop(drop)
        _check(not rows and problems, "an unrecognised club was accepted silently")
        _check("NOPE" in problems[0], "the problem does not name the offending club: %s" % problems[0])


def test_the_weekly_job_captures_availability_without_being_able_to_fail_on_it():
    """The wiring that makes P13.3 real: the snapshot the job writes carries the capture, and a failure
    in that step cannot take the weekly run down with it."""
    source = _read("update_week.py")
    _check("import availability" in source, "the weekly job does not capture availability")
    _check('state = _avail.attach(state, _payload)' in source,
           "the capture is not attached to the snapshot the job writes")
    _check("never fail the weekly job over this" in source,
           "there is no guard around the availability step — a fetch failure would fail the run")
    # and the snapshot it writes must therefore carry the field, which the end-to-end job test asserts
    # by reading a real snapshot back (tests/test_weekly_job.py)


def test_the_availability_module_reads_back_what_it_wrote():
    payload = AV.load()
    if not payload:
        skip("availability has never been captured in this workspace")
    _check("tracked" in payload, "the stored capture does not say whether it is tracked")
    _check("captured_at" in payload, "the stored capture is not dated")
    _check(isinstance(payload.get("clubs"), dict), "the stored capture has no per-club structure")
    assert AV.summarise(payload)
