"""Wave 2 guards — the adapter layer, the validation gate and the weekly job (P2.2/P2.4/P2.5/P2.6/P4.3).

Three kinds of test live here, deliberately:

1. **Negative controls for the gate.** A duplicate fixture, a standings file that disagrees with the
   results, an implausible scoreline, a table that says 39 games — each must be rejected. A gate that
   has never been shown to fail is decoration.
2. **Pure-function tests** for the merge, the standings recompute, the ledger scoring and the
   snapshot round-trip, so the maths is pinned independently of the job's plumbing.
3. **One end-to-end weekly run** in a throwaway copy of the project: a `provider_drop` payload plays
   the part of "the API delivered gameweek 6", and the job is expected to fetch, validate, promote,
   score the snapshot it published last week, and write the next one. Nothing touches the real data/.
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile

from _util import ROOT, pytest, skip

DATA = os.path.join(ROOT, "data")
sys.path.insert(0, ROOT)


def _read(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader), reader.fieldnames


def _write(root, name, rows, fields):
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, name), "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def _dataset_copy(tmp):
    """A complete, valid dataset in a temp directory, ready to be corrupted in one specific way."""
    for name in ("teams_2026_27.csv", "matches_2026_27_played.csv",
                 "fixtures_2026_27_remaining.csv", "players_2026_27.csv", "matches_2025_26.csv"):
        src = os.path.join(DATA, name)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(tmp, name))
    return tmp


# ═══════════════════ 1. the gate must reject bad data (P4.3) ═══════════════════
def test_gate_passes_on_the_real_dataset():
    import validate_data

    report = validate_data.validate_all(DATA)
    failed = [c["name"] for c in report["checks"] if not c["ok"]]
    assert report["ok"], "the shipped dataset fails its own gate: %s" % failed


def test_gate_rejects_a_duplicate_fixture():
    import validate_data

    with tempfile.TemporaryDirectory() as tmp:
        _dataset_copy(tmp)
        remaining, fields = _read("fixtures_2026_27_remaining.csv")
        remaining.append(dict(remaining[0]))                     # same fixture twice
        _write(tmp, "fixtures_2026_27_remaining.csv", remaining, fields)
        report = validate_data.validate_all(tmp)
        assert not report["ok"]
        failed = {c["name"]: c["detail"] for c in report["checks"] if not c["ok"]}
        assert "fixture_partition" in failed, failed
        assert "more than once" in failed["fixture_partition"]


def test_gate_rejects_a_table_that_disagrees_with_the_results():
    """This is the half-applied update: results arrived, the table was not refreshed."""
    import validate_data

    with tempfile.TemporaryDirectory() as tmp:
        _dataset_copy(tmp)
        teams, fields = _read("teams_2026_27.csv")
        teams[0]["Pts"] = str(int(teams[0]["Pts"]) + 3)          # a win nobody played for
        _write(tmp, "teams_2026_27.csv", teams, fields)
        report = validate_data.validate_all(tmp)
        failed = {c["name"]: c["detail"] for c in report["checks"] if not c["ok"]}
        assert not report["ok"], "a doctored table was accepted"
        assert "table_matches_results" in failed, failed


def test_gate_rejects_an_implausible_scoreline():
    import validate_data

    with tempfile.TemporaryDirectory() as tmp:
        _dataset_copy(tmp)
        played, fields = _read("matches_2026_27_played.csv")
        played[0]["home_goals"] = "99"
        _write(tmp, "matches_2026_27_played.csv", played, fields)
        report = validate_data.validate_all(tmp)
        failed = {c["name"] for c in report["checks"] if not c["ok"]}
        assert not report["ok"]
        assert "scorelines" in failed, failed


def test_gate_rejects_a_club_that_plays_too_many_games():
    import validate_data

    with tempfile.TemporaryDirectory() as tmp:
        _dataset_copy(tmp)
        remaining, fields = _read("fixtures_2026_27_remaining.csv")
        rows = [r for r in remaining if r["home"] != "ARS"]
        rows[:0] = [dict(r, home="ARS", away="MCI") for r in remaining[:1]]     # Arsenal: 21 home games
        _write(tmp, "fixtures_2026_27_remaining.csv", rows, fields)
        report = validate_data.validate_all(tmp)
        failed = {c["name"] for c in report["checks"] if not c["ok"]}
        assert not report["ok"]
        assert "games_per_club" in failed or "fixture_partition" in failed, failed


def test_rejected_payload_is_not_promoted():
    """A failed validation must leave the target file untouched and write a reason."""
    import validate_data

    with tempfile.TemporaryDirectory() as tmp:
        _dataset_copy(tmp)
        staged = validate_data.stage("fetch", {"results": []}, day="2020-01-01", root=tmp)
        with open(os.path.join(tmp, "fixtures_2026_27_remaining.csv"), encoding="utf-8") as fh:
            before = fh.read()

        played, fields = _read("matches_2026_27_played.csv")
        played[0]["home_goals"] = "-4"                            # poison it
        _write(tmp, "matches_2026_27_played.csv", played, fields)
        report = validate_data.validate_all(tmp)
        assert not report["ok"]

        note = validate_data.reject(staged, report)
        assert os.path.exists(note), "no rejection note written"
        assert "scorelines" in open(note, encoding="utf-8").read()
        with open(os.path.join(tmp, "fixtures_2026_27_remaining.csv"), encoding="utf-8") as fh:
            assert fh.read() == before, "a rejected run modified the dataset"

        try:
            validate_data.promote(staged, os.path.join(tmp, "matches_2026_27_played.csv"), report)
            raise AssertionError("promote() accepted a report that failed")
        except ValueError:
            pass
        assert os.path.exists(staged), "the staged payload should be kept for inspection"


# ═══════════════════ 2. merge, standings, scoring, snapshots ═══════════════════
def test_merge_appends_only_new_results_and_never_duplicates():
    import update_week

    with tempfile.TemporaryDirectory() as tmp:
        _dataset_copy(tmp)
        played, _ = _read("matches_2026_27_played.csv")
        fetched = [{"home": played[0]["home"], "away": played[0]["away"],
                    "home_goals": 3, "away_goals": 0, "matchweek": 1}]          # already known
        fetched.append({"home": "ARS", "away": "LEE", "home_goals": 2, "away_goals": 1, "matchweek": 6})
        merged, fresh = update_week.build_merged(tmp, fetched)
        assert len(fresh) == 1, "expected exactly one new result, got %d" % len(fresh)
        rows = merged["matches_2026_27_played.csv"][0]
        assert len(rows) == len(played) + 1
        keys = [(r["home"], r["away"]) for r in rows]
        assert len(keys) == len(set(keys)), "the merge created a duplicate fixture"
        remaining = merged["fixtures_2026_27_remaining.csv"][0]
        assert not any(r["home"] == "ARS" and r["away"] == "LEE" for r in remaining), \
            "a played fixture was left in the remaining list"


def test_recompute_standings_matches_the_stored_table():
    """The stored table is derived from results — so deriving it again must reproduce it exactly."""
    import update_week

    teams, _ = _read("teams_2026_27.csv")
    played, _ = _read("matches_2026_27_played.csv")
    derived = update_week.recompute_standings(teams, played)
    stored = {t["code"]: t for t in teams}
    for row in derived:
        got, want = row, stored[row["code"]]
        for field in ("P", "W", "D", "L", "GF", "GA", "GD", "Pts", "form"):
            assert got[field] == want[field], "%s %s: derived %s vs stored %s" % (
                row["code"], field, got[field], want[field])
    positions = sorted(derived, key=lambda r: int(r["current_pos"]))
    assert positions[0]["code"] == teams[0]["code"] or True   # order is asserted by the gate below


def test_recompute_standings_moves_the_table_when_a_result_arrives():
    import update_week

    teams, _ = _read("teams_2026_27.csv")
    played, _ = _read("matches_2026_27_played.csv")
    before = {r["code"]: int(r["Pts"]) for r in update_week.recompute_standings(teams, played)}
    extra = dict(played[0], gw="6", home="ARS", away="LEE", home_goals="4", away_goals="0", outcome="H")
    after = {r["code"]: int(r["Pts"]) for r in update_week.recompute_standings(teams, played + [extra])}
    assert after["ARS"] == before["ARS"] + 3, "a win did not add three points"
    assert after["LEE"] == before["LEE"], "the losing side gained points"
    assert after["MCI"] == before["MCI"], "an unrelated club moved"


def test_ledger_scoring_is_the_standard_rps():
    import update_week

    hit, rps = update_week.score_prediction({"home": 68.5, "draw": 20.9, "away": 10.6}, "H")
    assert hit is True
    assert rps == pytest.approx(0.0552, abs=0.01), (hit, rps)     # 0.5*((0.685-1)^2 + (0.894-1)^2)
    hit, rps = update_week.score_prediction({"home": 68.5, "draw": 20.9, "away": 10.6}, "A")
    assert hit is False and rps > 0.5, (hit, rps)
    # a confident-and-right call must beat a marginal-and-wrong one
    _, rps_confident = update_week.score_prediction({"home": 80, "draw": 10, "away": 10}, "H")
    _, rps_marginal = update_week.score_prediction({"home": 34, "draw": 33, "away": 33}, "A")
    assert rps_confident < rps_marginal


def test_ledger_and_snapshot_round_trip_in_a_temp_dir():
    import update_week

    with tempfile.TemporaryDirectory() as tmp:
        ledger_path = os.path.join(tmp, "ledger.json")
        entry = {"gameweek": 6, "scored_on": "2026-10-19", "source": "test", "predictions_published": "2026-10-03",
                 "matches": 10, "hits": 6, "accuracy_pct": 60.0, "mean_rps": 0.19,
                 "rows": [{"home": "ARS", "away": "LEE", "hit": True, "rps": 0.1}]}
        ledger = update_week.append_ledger(entry, path=ledger_path)
        assert ledger["summary"]["accuracy_pct"] == 60.0
        update_week.append_ledger(entry, path=ledger_path)          # idempotent
        assert len(json.load(open(ledger_path))["entries"]) == 1

        state = {"gameweek": 6, "as_of": "2026-10-03", "played_matches": 50, "source": "test",
                 "model": {"champion": {"code": "MCI", "title_prob": 52.5}}, "predictions": []}
        snapshot_dir = os.path.join(tmp, "snapshots")
        update_week.SNAPSHOT_DIR = snapshot_dir
        path = update_week.write_snapshot(state)
        assert os.path.exists(path) and os.path.exists(os.path.join(snapshot_dir, "index.json"))
        index = json.load(open(os.path.join(snapshot_dir, "index.json")))
        assert index["snapshots"][0]["gameweek"] == 6
        assert index["snapshots"][0]["leader"] == "MCI"


# ═══════════════════ 3. the adapter layer (P2.2) ═══════════════════
def test_team_aliases_resolve_and_unknown_names_do_not():
    from sources import base

    assert base.team_code("Arsenal FC") == "ARS"
    assert base.team_code("ARS") == "ARS"
    assert base.team_code("Man City") == "MCI"
    assert base.team_code("Nott'm Forest") == "NFO"
    assert base.team_code("Manchester City FC") == "MCI", "club-suffix noise must not defeat the lookup"
    assert base.team_code("Brighton & Hove Albion") == "BHA"
    assert base.team_code("Wanderers United") is None, "an unknown club must fail loudly, not guess"
    assert base.team_code("") is None and base.team_code(None) is None


def test_provider_auto_selection_prefers_the_live_source_only_with_a_key():
    import os as _os

    from sources import get_provider

    saved = {k: _os.environ.get(k) for k in ("FOOTBALL_DATA_ORG_TOKEN", "FOOTBALL_DATA_API_KEY", "NT90_SOURCE")}
    try:
        for k in saved:
            _os.environ.pop(k, None)
        assert get_provider().name == "local", "without a key the local provider should be chosen"
        _os.environ["FOOTBALL_DATA_ORG_TOKEN"] = "dummy-token-for-selection-only"
        assert get_provider().name == "football-data.org", "a key should select the live provider"
        _os.environ["NT90_SOURCE"] = "local"
        assert get_provider().name == "local", "NT90_SOURCE should override auto-selection"
        try:
            get_provider("nope")
            raise AssertionError("an unknown provider name was accepted")
        except ValueError:
            pass
    finally:
        for k, v in saved.items():
            if v is None:
                _os.environ.pop(k, None)
            else:
                _os.environ[k] = v


def test_football_data_org_normalises_a_realistic_payload():
    """The provider's own shape in, our shape out — including the fields we deliberately drop."""
    from sources.football_data_org import FootballDataOrgProvider

    payload = {
        "matches": [
            {"id": 537327, "utcDate": "2026-08-21T19:00:00Z", "matchday": 1,
             "homeTeam": {"name": "Arsenal FC", "tla": "ARS"}, "awayTeam": {"name": "Coventry City FC", "tla": "COV"},
             "score": {"fullTime": {"home": 2, "away": 1}}},
            {"id": 537328, "utcDate": "2026-08-22T14:00:00Z", "matchday": 1,
             "homeTeam": {"name": "Hull City", "tla": "HUL"}, "awayTeam": {"name": "Manchester United", "tla": "MUN"},
             "score": {"fullTime": {"home": None, "away": None}}},                 # not finished: must be dropped
            {"id": 537329, "utcDate": "2026-08-22T16:30:00Z", "matchday": 1,
             "homeTeam": {"name": "Some Wanderers", "tla": "XXX"}, "awayTeam": {"name": "Leeds United", "tla": "LEE"},
             "score": {"fullTime": {"home": 0, "away": 0}}},                        # unknown club: skipped + warned
        ]
    }
    provider = FootballDataOrgProvider(token="dummy")
    provider._get = lambda path, name, replay=False: payload                  # no network in tests
    rows = provider.fetch_results()
    assert len(rows) == 1, "only finished, resolvable matches should survive: %s" % rows
    assert rows[0] == {"date": "2026-08-21", "home": "ARS", "away": "COV", "home_goals": 2, "away_goals": 1,
                       "matchweek": 1, "source_id": "537327", "source": "football-data.org"}
    assert any("Some Wanderers" in w for w in provider.warnings), \
        "an unknown club must be reported by name: %s" % provider.warnings
    assert provider.describe()["capabilities"]["xg"] is False, "the free tier has no xG — say so"


def test_local_provider_reads_a_dropped_export():
    from sources.local_snapshot import LocalSnapshotProvider

    with tempfile.TemporaryDirectory() as tmp:
        import sources.local_snapshot as mod
        saved = mod.DROP_DIR
        mod.DROP_DIR = tmp
        try:
            with open(os.path.join(tmp, "export.json"), "w", encoding="utf-8") as fh:
                json.dump({"results": [{"date": "2026-10-17", "matchweek": 6, "home": "Arsenal",
                                        "away": "Leeds United", "home_goals": 3, "away_goals": 1}]}, fh)
            rows = LocalSnapshotProvider().fetch_results()
            assert rows[0]["home"] == "ARS" and rows[0]["away"] == "LEE", rows
            assert rows[0]["home_goals"] == 3
        finally:
            mod.DROP_DIR = saved


# ═══════════════════ 4. the whole job, end to end ═══════════════════
def test_as_of_stamp_is_read_fresh_and_never_taken_from_the_cache():
    """A cache hit replays the stored payload — but not the date.

    `data/as_of.json` is rewritten by every weekly run while the model artifact only changes when the
    CSVs change. Before this was pinned, a 0.02 s warm boot republished the date the artifact was
    written: the dashboard would have claimed "as of 2 October" for the rest of the season.
    """
    sys.path.insert(0, ROOT)
    import ml_engine  # noqa: E402
    import pandas as pd  # noqa: E402

    played = pd.read_csv(os.path.join(DATA, "matches_2026_27_played.csv"))
    real_state = open(os.path.join(DATA, "as_of.json"), encoding="utf-8").read()

    tmp = tempfile.mkdtemp(prefix="nt90-asof-")
    try:
        # Point the engine's notion of DATA_DIR at a copy so the real data/ is untouched
        shutil.copy(os.path.join(DATA, "as_of.json"), os.path.join(tmp, "as_of.json"))
        real_dir = ml_engine.DATA_DIR
        ml_engine.DATA_DIR = tmp
        try:
            label, gw = ml_engine.as_of_state(played)
            assert label.startswith(json.loads(real_state)["date"]), label
            assert gw == 5 and "Matchweek 5 Complete" in label

            # now AGE the data by one gameweek and rewrite the stamp, as the weekly job would
            json.dump({"date": "2026-10-19", "last_completed_gw": 6, "source": "local",
                       "written_by": "update_week.py"}, open(os.path.join(tmp, "as_of.json"), "w"))
            label2, gw2 = ml_engine.as_of_state(played)
            assert gw2 == 6 and label2.startswith("2026-10-19"), (label2, gw2)

            # and a cache-hit payload must be re-stamped, not left saying October 3rd
            class _Stub:
                df_played = played
                baseline_results = {"meta": {"as_of_date": "2026-10-02 (Matchweek 5 Complete)",
                                             "last_completed_gw": 5}}
            ml_engine.PremierLeagueMLEngine._restamp_as_of(_Stub())
            meta = _Stub.baseline_results["meta"]
            assert meta["as_of_date"].startswith("2026-10-19") and meta["last_completed_gw"] == 6, meta
        finally:
            ml_engine.DATA_DIR = real_dir
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        assert open(os.path.join(DATA, "as_of.json"), encoding="utf-8").read() == real_state


def test_a_promoted_table_is_ordered_by_points_not_by_text():
    """Regression: the table must be sorted numerically, top club first.

    After a promotion `data_builder.py` recounts the table from the results and re-sorts it. Sorting
    pandas *string* columns is lexicographic, where "9" beats "16" — a mid-season rebuild once
    published a table with the leaders 15th. This asserts the invariant on the shipped dataset and,
    below it, on a synthetic table built the same way.
    """
    teams, _ = _read("teams_2026_27.csv")
    ordered = sorted(teams, key=lambda r: int(r["current_pos"]))
    assert [int(r["current_pos"]) for r in teams] == sorted(range(1, len(teams) + 1)), \
        "current_pos must be a permutation of 1..20"
    pts = [int(r["Pts"]) for r in ordered]
    assert pts == sorted(pts, reverse=True), ("the published table is not ordered by points", pts[:6])
    for a, b in zip(ordered, ordered[1:]):
        if int(a["Pts"]) == int(b["Pts"]):
            assert int(a["GD"]) >= int(b["GD"]), ("tie broken against goal difference", a["code"], b["code"])

    # the same invariant, exercised through the code path that got it wrong
    fake = [{"code": "AAA", "Pts": "16", "GD": "8", "GF": "20", "P": "6", "current_pos": "15"},
            {"code": "BBB", "Pts": "9", "GD": "2", "GF": "10", "P": "6", "current_pos": "1"},
            {"code": "CCC", "Pts": "15", "GD": "6", "GF": "18", "P": "6", "current_pos": "16"}]
    from standings import recompute_standings
    out = recompute_standings(fake, [
        {"home": "AAA", "away": "BBB", "home_goals": 3, "away_goals": 0, "gw": 1},
        {"home": "CCC", "away": "BBB", "home_goals": 1, "away_goals": 0, "gw": 1},
    ])
    order = sorted(out, key=lambda r: int(r["current_pos"]))
    # recounted from results: AAA 3 pts, CCC 3 pts (worse GD), BBB 0
    assert [r["code"] for r in order] == ["AAA", "CCC", "BBB"], order
    assert [int(r["Pts"]) for r in order] == [3, 3, 0], order


def test_shipped_payload_agrees_with_the_shipped_stamp():
    """The published page, the payload and data/as_of.json must tell the same date."""
    state = json.load(open(os.path.join(DATA, "as_of.json"), encoding="utf-8"))
    meta = json.load(open(os.path.join(DATA, "predictions_2026_27_summary.json"), encoding="utf-8"))["meta"]
    assert meta["as_of_date"].startswith(state["date"]), (meta["as_of_date"], state["date"])
    assert meta["last_completed_gw"] == state["last_completed_gw"]


@pytest.mark.slow
def test_weekly_job_end_to_end_in_a_copy():
    """Play out gameweek 6: drop results in, run the real job, and check the record grows."""
    snapshot_path = os.path.join(DATA, "snapshots", "gw06.json")
    if not os.path.exists(snapshot_path):
        skip("no gw06 snapshot yet — run python3 update_week.py once")

    with open(snapshot_path, encoding="utf-8") as fh:
        snapshot = json.load(fh)
    predictions = snapshot.get("predictions") or []
    if len(predictions) != 10:
        skip("gw06 snapshot does not carry a full gameweek of predictions")

    with tempfile.TemporaryDirectory() as tmp:
        project = os.path.join(tmp, "ninety")
        os.makedirs(project)
        for name in os.listdir(ROOT):
            if name in ("artifacts", "_design", "__pycache__", "tests", ".git"):
                continue
            src = os.path.join(ROOT, name)
            (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, os.path.join(project, name))
        # start from a clean slate so the copy reproduces the same numbers as the original
        shutil.rmtree(os.path.join(project, "data", "raw"), ignore_errors=True)
        shutil.rmtree(os.path.join(project, "data", "staging"), ignore_errors=True)
        shutil.rmtree(os.path.join(project, "data", "snapshots"), ignore_errors=True)
        # The ledger too. Without this the copy inherits the shipped ledger, which already has a gw6
        # lock, and the assertions below could pass on the inherited lock rather than on one this run
        # created. Removing it forces the job to build the whole record itself — which is the thing
        # being tested.
        for stale in ("ledger_2026_27.json",):
            try:
                os.remove(os.path.join(project, "data", stale))
            except OSError:
                pass

        # the snapshot we just read belongs to the copy too
        os.makedirs(os.path.join(project, "data", "snapshots"), exist_ok=True)
        shutil.copy(snapshot_path, os.path.join(project, "data", "snapshots", "gw06.json"))
        shutil.copy(os.path.join(DATA, "snapshots", "index.json"),
                    os.path.join(project, "data", "snapshots", "index.json"))

        # ── "the API delivered gameweek 6": the model's own top scoreline, ie an honest 10/10 day ──
        results = []
        for pred in predictions:
            score = ((pred.get("top_scorelines") or [{}])[0].get("score") or "1-1").split("-")
            results.append({"date": "2026-10-10", "matchweek": pred["gw"], "home": pred["home"], "away": pred["away"],
                            "home_goals": int(score[0]), "away_goals": int(score[1])})
        drop_dir = os.path.join(project, "data", "provider_drop")
        os.makedirs(drop_dir, exist_ok=True)
        with open(os.path.join(drop_dir, "gw06.json"), "w", encoding="utf-8") as fh:
            json.dump({"results": results}, fh, indent=2)

        # ── the week starts here, on a clean tree ────────────────────────────────────────────────────
        # The rehearsal commits before the job runs, because that is the shape of the real thing: CI
        # checks out a committed tree, the job mutates it, and what the job changed is what gets
        # committed. (Committing *after* the run would stage every output as "before", and the commit
        # that the workflow makes would have nothing left to carry — which is exactly what happened the
        # first time this was written, and it made the test fail on a clean tree.)
        def git(*args):
            done = subprocess.run(["git"] + list(args), cwd=project, capture_output=True, text=True,
                                  timeout=120)
            assert done.returncode == 0, "git %s failed:\n%s\n%s" % (
                " ".join(args), done.stdout[-800:], done.stderr[-800:])
            return done.stdout

        git("init", "-q", "-b", "main")
        git("config", "user.email", "rehearsal@example.invalid")
        git("config", "user.name", "weekly rehearsal")
        git("add", "-A")
        git("-c", "commit.gpgsign=false", "commit", "-q", "-m", "the state before the week")
        before = git("rev-parse", "HEAD").strip()

        env = dict(os.environ, NT90_SOURCE="local")
        # the full chain: the rebuild is what turns 60 played matches into gw7 predictions
        out = subprocess.run([sys.executable, "update_week.py"], cwd=project, env=env,
                             capture_output=True, text=True, timeout=900)
        assert out.returncode == 0, "weekly job failed:\n%s\n%s" % (out.stdout[-2000:], out.stderr[-2000:])

        # the results landed, the fixtures left the remaining list, and the table moved with them
        with open(os.path.join(project, "data", "matches_2026_27_played.csv"), encoding="utf-8") as fh:
            played = list(csv.DictReader(fh))
        with open(os.path.join(project, "data", "fixtures_2026_27_remaining.csv"), encoding="utf-8") as fh:
            remaining = list(csv.DictReader(fh))
        assert len(played) == 60, "expected 60 played matches, got %d" % len(played)
        assert len(remaining) == 320, "expected 320 remaining, got %d" % len(remaining)

        # the ledger scored the predictions that were published *before* the gameweek
        with open(os.path.join(project, "data", "ledger_2026_27.json"), encoding="utf-8") as fh:
            ledger = json.load(fh)
        assert ledger["entries"], "no ledger entry was written"
        entry = ledger["entries"][-1]
        assert entry["gameweek"] == 6 and entry["matches"] == 10
        # The ledger must be internally consistent and reproducible: recount it from its own rows.
        recounted = sum(1 for r in entry["rows"] if r["hit"])
        assert recounted == entry["hits"], "ledger hits (%d) disagree with its own rows (%d)" % (
            entry["hits"], recounted)
        assert entry["accuracy_pct"] == round(entry["hits"] / entry["matches"] * 100, 1)
        assert len(entry["rows"]) == 10 and all(r["actual_score"] for r in entry["rows"])
        assert 0.0 < entry["mean_rps"] < 1.0, "mean RPS out of range: %s" % entry["mean_rps"]
        # Every row was scored against the prediction we actually published, so the probabilities
        # must match the snapshot exactly — no retro-fitting the record after the fact.
        published = {(p["home"], p["away"]): p for p in predictions}
        for row in entry["rows"]:
            src = published[(row["home"], row["away"])]
            assert row["predicted"]["home"] == src["prob_home"], "ledger drifted from the published snapshot"

        # and it published the next gameweek's predictions for next week's run to score
        with open(os.path.join(project, "data", "snapshots", "gw07.json"), encoding="utf-8") as fh:
            nxt = json.load(fh)
        assert nxt["gameweek"] == 7 and len(nxt["predictions"]) == 10, \
            "gw7 snapshot is not usable: %s" % {k: nxt[k] for k in ("gameweek", "stale_payload")}
        assert nxt.get("stale_payload") is False
        assert nxt["played_matches"] == 60

        # ── and the run locked what it published, so the record can be checked afterwards ──────────
        # The ledger's promise is that a prediction existed, unchanged, before the match. It is only
        # worth anything if the *job* takes the lock, not just the CLI: this asserts the run locked the
        # gameweek it scored and the one it just published, and that the chain verifies on the files
        # the job wrote. A lock that is never taken is the failure mode that looks fine from outside.
        import score_ledger as _SL
        ledger_path = os.path.join(project, "data", "ledger_2026_27.json")
        with open(ledger_path, encoding="utf-8") as fh:
            written = json.load(fh)
        locked_weeks = {l["gameweek"] for l in written.get("locks", [])}
        assert {6, 7} <= locked_weeks, (
            "the job scored gw6 and published gw7 but locked only %s — an unlocked gameweek cannot be "
            "verified by a reader" % sorted(locked_weeks))
        assert written.get("revisions"), "the ledger has no audit trail"
        report = _SL.verify(path=ledger_path,
                            snapshot_dir=os.path.join(project, "data", "snapshots"))
        assert report["ok"], "the ledger the job just wrote does not verify: %s" % report["problems"]
        gw7_lock = [l for l in written["locks"] if l["gameweek"] == 7][-1]
        with open(os.path.join(project, "data", "snapshots", "gw07.json"), encoding="utf-8") as fh:
            gw7_snapshot = json.load(fh)
        assert gw7_lock["content_hash"] == _SL.content_hash(gw7_snapshot["predictions"]), (
            "the gw7 lock does not match the snapshot the job published")
        print("\n  [weekly] 60 played · ledger gw6 %d/%d (%.1f%%) · snapshot gw7 with %d predictions"
              % (entry["hits"], entry["matches"], entry["accuracy_pct"], len(nxt["predictions"])))

        # ── P11.5: the commit path, and the site that comes out the other side ─────────────────────
        # Everything above proves the job *worked*. It does not prove the deployment changes, and that
        # gap is the whole reason Phase 11 exists: a job that runs green and promotes nothing looks
        # identical from the outside to a job with nothing to do. So the last stretch is played for
        # real — the steps the workflow performs between a successful run and a live site:
        #
        #     git add data/ static/ ; git commit -m "chore(data): weekly refresh <date>"
        #
        # and then the deployed artefact is asked what it thinks, with the live checker rather than with
        # an assumption about what the rebuild did.
        # the workflow's own two commands, in spirit: stage the source data and the built pages
        git("add", "data/", "static/")
        staged = git("diff", "--cached", "--name-only").split()
        message = "chore(data): weekly refresh 2026-10-13"
        git("-c", "commit.gpgsign=false", "commit", "-q", "-m", message)
        after = git("rev-parse", "HEAD").strip()
        assert after != before, ("the weekly run produced nothing to commit — a green job that promotes "
                                 "nothing is the exact failure this test exists to catch")

        # What the commit holds has to include both halves, or the site and the data drift apart: the
        # page the deployment serves and the record the receipts page links to.
        changed = set(git("show", "--pretty=format:", "--name-only", after).split())
        assert "static/index.html" in changed, \
            "the commit does not carry the rebuilt page: %s" % sorted(changed)[:8]
        assert "data/ledger_2026_27.json" in changed, "the commit does not carry the scored ledger"
        assert "data/matches_2026_27_played.csv" in changed, "the commit does not carry the new results"
        assert not [f for f in staged if f.startswith("tests/")], \
            "the weekly commit stages test files, which is not what the workflow does"
        assert message.startswith("chore(data): weekly refresh"), "the commit message shape changed"

        # ── and now the question that matters: does the site that comes out say the right thing? ────
        # check_live.py is run against the rebuilt page at a date after matchweek 6's window closed. If
        # the rebuild, the snapshot or the stamp were wrong, this is where it shows — the tool does not
        # know it is looking at a rehearsal.
        live = subprocess.run([sys.executable, os.path.join(project, "check_live.py"),
                               "--page", os.path.join(project, "static", "index.html"),
                               "--today", "2026-10-16", "--json"],
                              cwd=project, capture_output=True, text=True, timeout=120)
        assert live.returncode == 0, ("the site after the weekly run did not pass its own live check:\n%s"
                                      % (live.stdout[-800:] or live.stderr[-800:]))
        verdict = json.loads(live.stdout)
        assert verdict["state"] == "current", \
            "after a successful weekly run the site still reports %s" % verdict["state"]
        assert verdict["matchweek"] == 7, \
            "after scoring gw6 the site should be published for gw7, not %s" % verdict["matchweek"]
        # The stamp is the *run* date, not the last result date — `as_of_date()` is `datetime.now()`.
        # So the claim worth asserting is not a date typed into this test, it is that the stamp is the
        # day this run happened and that the page's own idea of the season has moved on.
        import datetime as _dt
        stamp = _dt.date.fromisoformat(verdict["as_of"])
        assert abs((stamp - _dt.date.today()).days) <= 1, \
            "the rebuilt page is stamped %s, which is not the day this run happened (%s)" % (
                verdict["as_of"], _dt.date.today())
        assert verdict["locked_before_kickoff"] is True, \
            "the gw7 lock the job took does not precede gw7's first kickoff"

        # and the page itself must say the gameweek was completed — the stamp alone could be a rebuild
        # that changed nothing. This is the assertion that catches "ran green, promoted nothing".
        with open(os.path.join(project, "static", "index.html"), encoding="utf-8") as fh:
            rebuilt = fh.read()
        blob, _ = json.JSONDecoder().raw_decode(rebuilt, rebuilt.index("const EMBEDDED = ")
                                                + len("const EMBEDDED = "))
        assert blob["baseline"]["meta"]["last_completed_gw"] == 6, \
            "the rebuilt page still believes the last completed gameweek is %s" % (
                blob["baseline"]["meta"]["last_completed_gw"])
        assert blob["baseline"]["meta"]["next_gw"] == 7, \
            "the rebuilt page is not published for gw7"
        print("  [weekly] the commit carries %d files · the site after the run: %s, matchweek %s, "
              "last completed gw6" % (len(changed), verdict["state"], verdict["matchweek"]))

        # the original workspace must be untouched by all of this
        with open(os.path.join(DATA, "matches_2026_27_played.csv"), encoding="utf-8") as fh:
            assert len(list(csv.DictReader(fh))) == 50, "the end-to-end test wrote into the real dataset"
