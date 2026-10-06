"""Optional weekly player inputs. Failures keep the last good files; no key remains supported.

Called BEFORE the offline rebuild so the model card and the gameweek capture describe the same
collection. Match-history backfills are never started here; they are deliberately opt-in and resumable.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import availability
import congestion
import player_form
from player_data import atomic_json, load_json
from sources.api_football import ApiFootballProvider


def refresh(quiet=False, gameweek=None):
    notes = []
    provider = ApiFootballProvider()
    player_incoming = provider.available() or bool(player_form.drop_files())
    if player_incoming:
        try:
            if provider.available():
                rows, report = player_form.collect_from_provider(provider, quiet=True)
                problems = report.get("problems") or []
            else:
                rows, problems = player_form.rows_from_drop()
                report = {"calls": 0, "note": "manual drop"}
            rows = player_form.normalise(rows)
            prior = player_form.load_form()
            # An incomplete/quota-limited pull must not replace a fuller committed table.
            prior_clubs = {r["club"] for r in prior}
            new_clubs = {r["club"] for r in rows}
            if not rows or problems or not prior_clubs.issubset(new_clubs):
                notes.append("player form retained: empty, partial or failed collection")
            else:
                player_form.write(rows, player_form.summarise(rows, report, problems))
                notes.append("player form refreshed: %d rows" % len(rows))
        except Exception as exc:
            notes.append("player form retained: %s" % exc)
    else:
        notes.append("player form retained: no key and no incoming drop")

    # Local dated bundles are optional too. This imports files; it never starts a provider backfill.
    import player_history
    import contextlib
    import io
    for season in ("2025-26", "2026-27"):
        incoming = player_history.from_drop(season=season)
        if incoming.get("fixtures") or incoming.get("player_matches") or incoming.get("availability"):
            with contextlib.redirect_stdout(io.StringIO()):
                player_history.main(["--source", "local", "--season", season])
            notes.append("manual dated history imported: " + season)

    try:
        rows, problems, source = availability._collect(source="auto", quiet=True)
        capture = availability.build(rows, source, problems=problems, gameweek=gameweek)
    except Exception as exc:
        capture = availability.build([], "none", problems=["collection failed: %s" % exc], gameweek=gameweek)
    previous = availability.load()
    if capture.get("tracked") or not previous.get("tracked"):
        availability.write(capture)
    else:
        notes.append("rolling availability retained; this run's snapshot explicitly records untracked")

    try:
        calendar = congestion.collect(source="auto")
        if calendar.get("events"):
            previous_calendar = load_json(congestion.OUT)
            calendar["events"], bad = congestion.normalise((previous_calendar.get("events") or []) + calendar["events"])
            calendar["problems"].extend(bad)
            atomic_json(congestion.OUT, calendar)
            notes.append("calendar refreshed: %d exact events" % len(calendar["events"]))
        else:
            notes.append("calendar retained: no exact events collected")
    except Exception as exc:
        notes.append("calendar retained: %s" % exc)
    if not quiet:
        for note in notes:
            print("  " + note)
    return {"availability": capture, "notes": notes}


if __name__ == "__main__":
    refresh()
