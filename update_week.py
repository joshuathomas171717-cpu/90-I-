"""update_week.py — the weekly job: fetch, validate, promote, rebuild, snapshot, score (P2.4/P2.5/P2.6).

The order matters, and so does what is *not* allowed to happen:

  1. fetch      — via the sources layer; raw payloads cached under data/raw/<date>/
  2. stage      — the fetched payload is written to data/staging/<date>/, never into data/ directly
  3. merge      — prospective played/remaining/teams files are built in memory
  4. validate   — the gate runs against the merged dataset; a failure rejects the pull and exits 1
  5. promote    — only a dataset that passed is written over data/
  6. ledger     — the gameweek that just completed is scored against the predictions we published for it
  7. rebuild    — data_builder -> ml_engine -> backtest -> build_dashboard
  8. snapshot   — data/snapshots/gwNN.json records the new state and the predictions for the next one

Usage
    python3 update_week.py --dry-run              # fetch + validate, write nothing outside staging/
    python3 update_week.py --source local         # no key, no network: the manual weekly path
    python3 update_week.py --source football-data.org
    python3 update_week.py --replay               # use the newest cached payloads instead of the network
    python3 update_week.py --skip-build           # data only, no retrain (fast, for checking a pull)
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ALERT_WEBHOOK = os.environ.get("NT90_ALERT_WEBHOOK", "").strip()
ALERT_ON_SUCCESS = os.environ.get("NT90_ALERT_ON_SUCCESS", "").lower() in ("1", "true", "yes", "on")
_ALERTED = False        # set once any alert is delivered, so one failure produces one alert
# NT90_DATA_DIR lets the job run against a staged copy — used by the end-to-end test, and useful for
# rehearsing a pull before letting it near the real dataset.
DATA_DIR = os.environ.get("NT90_DATA_DIR") or os.path.join(BASE_DIR, "data")
SNAPSHOT_DIR = os.path.join(DATA_DIR, "snapshots")
LEDGER_PATH = os.path.join(DATA_DIR, "ledger_2026_27.json")
as_of_date = lambda: datetime.now().strftime("%Y-%m-%d")

sys.path.insert(0, BASE_DIR)


# ════════════════════════════════════════════════════════════════════════════
#  merge logic — pure functions, so tests can prove they are correct
# ════════════════════════════════════════════════════════════════════════════
from standings import outcome_of, recompute_standings   # noqa: E402  (single source of truth)


from dataset_io import (read_csv, same_content as _same_content, same_value as _same_value,   # noqa: E402
                        write_dataset)


def new_results_only(played_rows, fetched):
    """Which fetched results are genuinely new? Keyed on the fixture, not on the source's id."""
    known = {(r["home"], r["away"]) for r in played_rows}
    seen, fresh = set(), []
    for row in fetched:
        key = (row["home"], row["away"])
        if key in known or key in seen:
            continue
        seen.add(key)
        fresh.append(row)
    return fresh


def build_merged(root=DATA_DIR, fetched=None):
    """Prospective {filename: (rows, fieldnames)} for a pull. Nothing is written here."""
    played, played_fields = read_csv(os.path.join(root, "matches_2026_27_played.csv"))
    remaining, remaining_fields = read_csv(os.path.join(root, "fixtures_2026_27_remaining.csv"))
    teams, team_fields = read_csv(os.path.join(root, "teams_2026_27.csv"))

    fresh = new_results_only(played, fetched or [])
    for row in fresh:
        played.append({
            "season": "2026-27",
            "gw": str(row.get("matchweek") or ""),
            "home": row["home"], "away": row["away"],
            "home_goals": str(row["home_goals"]), "away_goals": str(row["away_goals"]),
            "outcome": outcome_of(row["home_goals"], row["away_goals"]),
        })
    played.sort(key=lambda r: (int(r["gw"] or 0), r["home"]))
    played = [dict(r) for r in played]

    done = {(r["home"], r["away"]) for r in played}
    remaining = [r for r in remaining if (r["home"], r["away"]) not in done]

    teams = recompute_standings(teams, played)
    return {
        "matches_2026_27_played.csv": (played, played_fields),
        "fixtures_2026_27_remaining.csv": (remaining, remaining_fields),
        "teams_2026_27.csv": (teams, team_fields),
    }, fresh


# ════════════════════════════════════════════════════════════════════════════
#  scoring + the public record — implemented in score_ledger.py (P10.2)
# ════════════════════════════════════════════════════════════════════════════
# One implementation, because two would eventually disagree about what a hit is. The ledger now
# hashes what was published, chains every write, and can be re-checked by a stranger
# (`python3 score_ledger.py --verify`), which is the whole point of publishing it.
import score_ledger as _ledger                                          # noqa: E402

score_prediction = _ledger.score_prediction
score_gameweek = _ledger.score_gameweek
lock_gameweek = _ledger.lock_gameweek
score_and_append = _ledger.score_and_append


def append_ledger(entry, path=LEDGER_PATH):
    """Thin wrapper so the ledger path still follows NT90_DATA_DIR (the end-to-end test uses it)."""
    return _ledger.append_ledger(entry, path=path)


def latest_snapshot():
    if not os.path.isdir(SNAPSHOT_DIR):
        return None
    files = sorted(f for f in os.listdir(SNAPSHOT_DIR) if f.startswith("gw") and f.endswith(".json"))
    if not files:
        return None
    with open(os.path.join(SNAPSHOT_DIR, files[-1]), encoding="utf-8") as fh:
        return json.load(fh)


def write_snapshot(state, path=None):
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    path = path or os.path.join(SNAPSHOT_DIR, "gw%02d.json" % state["gameweek"])
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    index = []
    for name in sorted(os.listdir(SNAPSHOT_DIR)):
        if name.startswith("gw") and name.endswith(".json"):
            with open(os.path.join(SNAPSHOT_DIR, name), encoding="utf-8") as fh:
                snap = json.load(fh)
            index.append({"file": name, "gameweek": snap.get("gameweek"), "as_of": snap.get("as_of"),
                          "played_matches": snap.get("played_matches"),
                          "leader": (snap.get("model", {}).get("champion") or {}).get("code"),
                          "title_prob": (snap.get("model", {}).get("champion") or {}).get("title_prob"),
                          "source": snap.get("source")})
    with open(os.path.join(SNAPSHOT_DIR, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"snapshots": index}, fh, indent=2)
    return path


# ════════════════════════════════════════════════════════════════════════════
#  the job
# ════════════════════════════════════════════════════════════════════════════
def notify(title, detail="", level="error"):
    """POST to NT90_ALERT_WEBHOOK. Slack and Discord both accept these two keys; each ignores the
    other's. Silent no-op when unset, and *never* raises: an alerting system that can take down the job
    it is watching is worse than no alerting at all."""
    if not ALERT_WEBHOOK:
        return False
    lines = ["%s %s" % ({"error": "x", "info": "ok"}.get(level, "-"), title)]
    if detail:
        lines.append(detail)
    lines.append("source: %s | %s" % (os.environ.get("NT90_SOURCE") or "auto", as_of_date()))
    text = "\n".join(lines)
    payload = json.dumps({"text": text, "content": text}).encode("utf-8")
    try:
        import urllib.request
        req = urllib.request.Request(ALERT_WEBHOOK, data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            log("notify", "%s alert delivered (%s)" % (level, resp.status))
        globals()["_ALERTED"] = True      # so the catch-all doesn't send a second, vaguer alert
        return True
    except Exception as exc:
        log("notify", "could not deliver the alert (%s: %s) - the run result is unchanged"
            % (type(exc).__name__, exc))
        return False


def log(step, message):
    print("  %-9s %s" % (step, message), flush=True)


def run_build(steps=("data_builder.py", "backtest.py", "player_gate.py", "player_context.py", "player_ui.py",
                     "ml_engine.py", "playground.py", "build_dashboard.py", "site_pages.py")):
    for script in steps:
        t0 = time.perf_counter()
        result = subprocess.run([sys.executable, os.path.join(BASE_DIR, script)], cwd=BASE_DIR,
                                capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stdout[-1500:]); print(result.stderr[-1500:], file=sys.stderr)
            raise RuntimeError("%s failed (exit %d)" % (script, result.returncode))
        log("rebuild", "%s ok (%.1fs)" % (script, time.perf_counter() - t0))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Weekly update: fetch, validate, promote, rebuild, snapshot.")
    ap.add_argument("--source", default=None, help="provider name (default: auto)")
    ap.add_argument("--dry-run", action="store_true", help="fetch and validate only; do not touch data/")
    ap.add_argument("--replay", action="store_true", help="use cached raw payloads, no network")
    ap.add_argument("--skip-build", action="store_true", help="skip the retrain/dashboard steps")
    ap.add_argument("--json", action="store_true", help="print a machine-readable summary")
    args = ap.parse_args(argv)

    import validate_data
    from sources import get_provider

    summary = {"started": datetime.now().isoformat(timespec="seconds"), "dry_run": args.dry_run}
    print("NINETY+ weekly update — %s" % summary["started"])

    # ── 1. provider ──
    try:
        provider = get_provider(args.source, offline=args.replay)
    except Exception as exc:
        print("✗ provider unavailable: %s" % exc, file=sys.stderr)
        return 2
    if not provider.available():
        print("✗ provider %r is not usable: %s" % (provider.name, provider.unavailable_reason()), file=sys.stderr)
        return 2
    log("provider", "%s — %s" % (provider.name, provider.notes or provider.capabilities))
    summary["provider"] = provider.name

    # ── 2. fetch ──
    try:
        results = provider.fetch_results()
        table = provider.fetch_table()
        player_stats = provider.fetch_player_stats()
    except Exception as exc:
        print("✗ fetch failed: %s" % exc, file=sys.stderr)
        return 2
    for warning in getattr(provider, "warnings", []):
        log("warning", warning)
    log("fetch", "%d results · %d table rows · %d scorer rows"
        % (len(results), len(table), sum(len(v) for v in player_stats.values())))
    summary["fetched"] = {"results": len(results), "table_rows": len(table)}

    # ── 3. stage ──
    staged = validate_data.stage("fetch", {"provider": provider.name, "results": results,
                                           "table": table, "player_stats": player_stats})
    log("stage", os.path.relpath(staged, BASE_DIR))

    # ── 4. merge + validate ──
    merged, fresh = build_merged(DATA_DIR, results)
    summary["new_results"] = len(fresh)
    log("merge", "%d new result(s) to apply" % len(fresh))

    import tempfile, shutil
    tmp_root = tempfile.mkdtemp(prefix="nt90-validate-")
    try:
        for name in ("matches_2025_26.csv", "players_2026_27.csv"):
            shutil.copy(os.path.join(DATA_DIR, name), os.path.join(tmp_root, name))
        write_dataset(tmp_root, merged)
        report = validate_data.validate_all(tmp_root)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    summary["validation"] = {"ok": report["ok"], "failed": report["counts"]["failed"]}

    for check in report["checks"]:
        if not check["ok"]:
            log("INVALID", "%s — %s" % (check["name"], check["detail"]))
    if not report["ok"]:
        note = validate_data.reject(staged, report)
        _failed = [c for c in report["checks"] if not c["ok"]]
        notify("weekly update REJECTED the pull - production keeps serving the last good snapshot",
               "%d of %d checks failed: %s" % (len(_failed), len(report["checks"]),
                                               "; ".join("%s - %s" % (c["name"], c["detail"])
                                                         for c in _failed[:3])),
               level="error")
        print("\n✗ Validation failed — nothing was promoted.")
        print("  staged payload kept at %s" % os.path.relpath(staged, BASE_DIR))
        print("  reason written to   %s" % os.path.relpath(note, BASE_DIR))
        return 1
    log("validate", "all %d checks passed" % len(report["checks"]))

    if args.dry_run:
        print("\n✓ Dry run complete — validated, nothing promoted.")
        if args.json:
            print(json.dumps(summary, indent=2))
        return 0

    # ── 5. promote ──
    changed = write_dataset(DATA_DIR, merged)
    played_rows, _ = read_csv(os.path.join(DATA_DIR, "matches_2026_27_played.csv"))
    last_gw = max((int(r["gw"]) for r in played_rows if r.get("gw")), default=0)
    summary["promoted"] = changed
    state_path = os.path.join(DATA_DIR, "as_of.json")
    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump({"date": as_of_date(), "last_completed_gw": last_gw, "source": provider.name,
                   "written_by": "update_week.py"}, fh, indent=2)
    log("promote", "%d of %d file(s) updated in data/%s · as_of -> %s (MW%d complete)"
        % (len(changed), len(merged),
           "" if changed else " (content already current — the model cache key is untouched)",
           as_of_date(), last_gw))

    # Optional player sources are collected once, before the rebuild. A missing key/error keeps
    # good files, and the exact same availability capture is attached to the gameweek below.
    _player_capture = None
    if not args.skip_build:
        try:
            from tools.refresh_player_sources import refresh as _refresh_players
            _refresh = _refresh_players(quiet=True, gameweek=last_gw + 1)
            _player_capture = _refresh.get("availability")
            for _note in _refresh.get("notes") or []:
                log("players", _note)
        except Exception as exc:
            log("warning", "optional player refresh retained previous files: %s" % exc)

    # ── 6. ledger: score the gameweek that just completed ──
    snap = latest_snapshot()
    if snap and snap.get("predictions"):
        # Lock before scoring, so what is scored is provably the bytes that were published. Locking
        # is idempotent, and a lock taken now carries its own timestamp — the snapshot's own
        # `generated` time is what says when the predictions were actually made.
        _ledger_file, lock, locked_now = lock_gameweek(snap, path=LEDGER_PATH)
        if locked_now:
            log("lock", "gw%d predictions locked · %d fixtures · sha256 %s"
                % (lock["gameweek"], lock["predictions"], lock["content_hash"][:16]))
        ledger, written = score_and_append(results, path=LEDGER_PATH,
                                           snapshot_dir=SNAPSHOT_DIR)
        if written:
            entry = written[-1]
            log("ledger", "gw%d: %d/%d correct (%.1f%%), mean RPS %.4f · season: %s"
                % (entry["gameweek"], entry["hits"], entry["matches"], entry["accuracy_pct"],
                   entry["mean_rps"], json.dumps(ledger["summary"])))
            summary["ledger"] = ledger["summary"]
        else:
            log("ledger", "gw%d locked, no new results yet · %d gameweek(s) scored so far"
                % (lock["gameweek"], ledger["summary"]["gameweeks"]))
    else:
        log("ledger", "no prior snapshot with predictions — nothing to score yet")

    # ── 7. rebuild ──
    if not args.skip_build:
        run_build()

    # ── 8. snapshot ──
    summary_path = os.path.join(DATA_DIR, "predictions_2026_27_summary.json")
    with open(summary_path, encoding="utf-8") as fh:
        payload = json.load(fh)
    # The snapshot's gameweek comes from the *data*, never from the payload: after a promotion the
    # payload is one rebuild behind, and a snapshot labelled with the wrong week would be scored
    # against the wrong fixtures next week.
    derived_next_gw = (max((int(r["gw"]) for r in played_rows if r.get("gw")), default=0) + 1)
    next_gw = derived_next_gw
    payload_gw = payload["meta"].get("next_gw")
    predictions = payload.get("next_gw_predictions") or payload.get("gw6_predictions") or []
    stale = payload_gw != derived_next_gw
    if stale:
        log("warning", "payload still says gw%s while the data says gw%s — snapshot will carry no "
                       "predictions (run without --skip-build to publish them)" % (payload_gw, derived_next_gw))
        predictions = []
    teams, _ = read_csv(os.path.join(DATA_DIR, "teams_2026_27.csv"))
    state = {
        "gameweek": next_gw,
        "as_of": as_of_date(),
        "generated": datetime.now().isoformat(timespec="seconds"),
        "source": provider.name,
        "played_matches": len(played_rows),
        # Derived, not read from the payload: the engine publishes no such key, so this used to be a
        # silent None in every snapshot. A season is 380 matches (20 clubs x 38), whatever the feed says.
        "remaining_matches": max(0, 380 - len(played_rows)),
        "table": [{"code": r["code"], "position": int(r["current_pos"]), "points": int(r["Pts"]),
                   "played": int(r["P"]), "gf": int(r["GF"]), "ga": int(r["GA"]), "form": r["form"]}
                  for r in sorted(teams, key=lambda r: int(r["current_pos"]))],
        "model": {
            "champion": {k: payload["headline_predictions"]["champion"][k] for k in ("code", "short", "proj_pts", "title_prob")},
            "golden_boot": {k: payload["headline_predictions"]["golden_boot"][k] for k in ("name", "club", "proj_goals")},
            "golden_glove": {k: payload["headline_predictions"]["golden_glove"][k] for k in ("name", "club", "proj_cs")},
            "n_simulations": payload["meta"]["n_simulations"],
            "as_of_date": payload["meta"]["as_of_date"],
        },
        "predictions": predictions,
        "stale_payload": stale,
        "validation": {"ok": report["ok"], "checks": len(report["checks"])},
    }
    # ── who was out, dated (P13.3) ──
    # Captured into the snapshot rather than a rolling file, so matchweek 6's record of who was
    # unavailable stays matchweek 6's record for the rest of the season. Offline, or with no key and no
    # drop file, this is a clean no-op that records itself as untracked — which is a fact, and one the
    # page renders as "not tracked yet" rather than as "nobody is injured".
    try:
        import availability as _avail
        if _player_capture is None:
            _rows, _problems, _source = _avail._collect(source="auto", quiet=True)
            _payload = _avail.build(_rows, _source, problems=_problems, gameweek=next_gw)
        else:
            _payload = dict(_player_capture)
            _payload["gameweek"] = next_gw
        state = _avail.attach(state, _payload)
        if _payload.get("tracked") or not _avail.load().get("tracked"):
            _avail.write(_payload)
        log("availability", _avail.summarise(_payload))
    except Exception as exc:                                  # never fail the weekly job over this
        state["availability"] = {"tracked": False, "source": "error", "captured_at": None, "clubs": {},
                                 "totals": {"players_out": 0, "clubs_reporting": 0},
                                 "problems": ["%s: %s" % (type(exc).__name__, exc)]}
        log("warning", "availability not captured: %s" % exc)
    path = write_snapshot(state)
    log("snapshot", os.path.relpath(path, BASE_DIR))
    # Locked here, right after publication, while the fixtures are still in the future. This is the
    # moment that makes the ledger worth reading: the hash exists before a ball is kicked, and
    # `score_ledger.py --verify` will fail if those predictions are ever edited afterwards.
    if state.get("predictions"):
        _f, lock, _new = lock_gameweek(state, path=LEDGER_PATH)
        log("lock", "gw%d locked before kickoff · sha256 %s" % (lock["gameweek"], lock["content_hash"][:16]))
    if ALERT_ON_SUCCESS:
        _leader = ("-", 0)
        for _row in state["table"]:
            if _row.get("position") == 1:
                _leader = (_row["code"], _row["points"])
                break
        notify("weekly update published gw%s via %s" % (next_gw, provider.name),
               "%d new result(s) | leader %s on %d pts | %d club(s) in the table"
               % (len(fresh), _leader[0], _leader[1], len(state["table"])), level="info")
    summary["snapshot"] = state["gameweek"]

    print("\n✓ Weekly update complete.")
    if args.json:
        print(json.dumps(summary, indent=2))
    return 0


def guarded_main():
    """main(), plus the two things a scheduled job must never skip: report a crash, and report success
    when asked to. Nothing else about the run changes."""
    try:
        code = main()
    except Exception as exc:
        notify("weekly update CRASHED", "%s: %s" % (type(exc).__name__, exc), level="error")
        raise
    if code != 0 and not globals().get("_ALERTED"):
        notify("weekly update exited %d - nothing was published" % code,
               "see the workflow log for the failing step", level="error")
    return code


if __name__ == "__main__":
    sys.exit(guarded_main())
