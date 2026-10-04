"""P14.3 — real rest and explicit travel, never a competition-membership proxy.

Only exact timezone-aware kickoff timestamps count. A fixture window ("10–12 October") is not a
kickoff. A national-team window is not proof that a player appeared. Club matches affect the team;
national-team appearances affect only the named player's share of the squad.

Missing travel is UNKNOWN, not zero kilometres. A known absence of travel (home fixture) may be zero.
Coefficients are transparent scenario priors, kept out of the live model until the gate earns input.

    python3 congestion.py --source local          # manual data/provider_drop/calendar/*.json
    python3 congestion.py --source auto           # free PL + UCL calendar if a results key exists
"""
import argparse
import datetime as dt
import os

from player_data import DATA, atomic_json, exact_time, load_json, number, policy, timestamp
from sources.base import team_code

OUT = os.path.join(DATA, "player_calendar_2026_27.json")
DROP = os.path.join(DATA, "provider_drop", "calendar")


def normalise(events):
    best, problems = {}, []
    for incoming in events or []:
        if not isinstance(incoming, dict):
            problems.append("calendar row is not an object"); continue
        row = dict(incoming)
        club = team_code(row.get("club"))
        kickoff = exact_time(row.get("kickoff"))
        if not club or kickoff is None:
            problems.append("calendar event needs a resolved club and an exact kickoff; windows excluded"); continue
        if row.get("status") in ("CANCELLED", "CANC", "PST", "POSTPONED", "ABD"):
            continue
        if row.get("international") and (not row.get("player_id") or row.get("minutes") is None):
            problems.append("international event has no named player/appearance minutes; excluded"); continue
        row.update(club=club, kickoff=kickoff.isoformat(), minutes=max(0, number(row.get("minutes"), 90)))
        distance = row.get("travel_km")
        if distance is None or distance == "":
            row["travel_km"] = 0.0 if row.get("venue") == "home" else None
        elif number(distance, -1) < 0:
            problems.append("negative/invalid travel distance excluded"); row["travel_km"] = None
        else:
            row["travel_km"] = number(distance)
        key = (club, str(row.get("fixture_id") or kickoff.isoformat()), str(row.get("player_id") or "club"))
        best[key] = row
    return sorted(best.values(), key=lambda r: r["kickoff"]), problems


def rest_context(club, kickoff, events, known_by=None, settings=None):
    settings = settings or policy()
    target = exact_time(kickoff)
    if target is None:
        return {"status": "unknown", "rest_days": None, "last_kickoff": None,
                "travel_km": None, "fatigue_pct": None, "international_players": [],
                "reason": "exact kickoff unavailable; a fixture window is not a match date"}
    known = timestamp(known_by) if known_by else target
    if known is None:
        return {"status": "unknown", "rest_days": None, "last_kickoff": None,
                "travel_km": None, "fatigue_pct": None, "international_players": [],
                "reason": "invalid knowledge cutoff"}
    eligible = []
    for row in events or []:
        date = exact_time(row.get("kickoff"))
        declared = timestamp(row.get("known_at"))
        if row.get("club") != club or date is None or date >= target:
            continue
        if known_by and (declared is None or declared >= known):
            continue
        if row.get("status") in ("CANCELLED", "CANC", "PST", "POSTPONED", "ABD"):
            continue
        if row.get("international") and (not row.get("player_id") or number(row.get("minutes")) <= 0):
            continue
        eligible.append((date, row))
    domestic = [(d, r) for d, r in eligible if not r.get("international")]
    last = max(domestic, key=lambda r: r[0], default=None)
    rest = (target-last[0]).total_seconds()/86400 if last else None
    window = [(d, r) for d, r in eligible if target-d <= dt.timedelta(days=7)]
    club_matches = [r for _d, r in window if not r.get("international")]
    international, by_player = [], {}
    for date, row in window:
        if row.get("international"):
            pid = str(row["player_id"])
            if pid not in by_player or date > by_player[pid][0]:
                by_player[pid] = (date, row)
    intl_cost, intl_travel = 0., 0.
    for pid, (date, row) in sorted(by_player.items()):
        days = (target-date).total_seconds()/86400
        share = min(1., number(row.get("minutes"))/90)/11
        intl_cost += max(0., settings["rest_reference_days"]-days) * settings["short_rest_cost_per_day_pct"] * share
        if row.get("travel_km") is not None:
            intl_travel += number(row["travel_km"]) * share
        international.append({"player_id": pid, "rest_days": round(days, 3), "minutes": row["minutes"],
                              "travel_km": row.get("travel_km"), "squad_share": round(share, 4)})
    travel_known = bool(window) and all(r.get("travel_km") is not None for _d, r in window)
    travel = sum(number(r.get("travel_km")) for r in club_matches) + intl_travel
    rest_cost = max(0., settings["rest_reference_days"]-rest)*settings["short_rest_cost_per_day_pct"] if rest is not None else None
    cost = min(settings["congestion_cap_pct"], (rest_cost or 0)+intl_cost
               + travel/1000*settings["travel_cost_per_1000_km_pct"]) if rest is not None else None
    return {"status": "exact-rest; travel incomplete" if rest is not None and not travel_known else (
                "known" if rest is not None else "unknown"),
            "rest_days": round(rest, 3) if rest is not None else None,
            "last_kickoff": last[0].isoformat() if last else None,
            "matches_last_7_days": len(club_matches), "travel_km": round(travel, 2) if travel_known else None,
            "known_travel_component_km": round(travel, 2),
            "fatigue_pct": round(cost, 3) if cost is not None else None,
            "international_players": international,
            "reason": "actual kickoff intervals; fatigue coefficients are unmeasured priors",
            "coverage": "recorded fixtures only; missing cup/international schedules are not inferred"}


def from_drop(directory=DROP):
    events, problems = [], []
    if os.path.isdir(directory):
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".json"):
                continue
            blob = load_json(os.path.join(directory, name))
            rows = blob.get("calendar") if isinstance(blob, dict) else blob
            if not isinstance(rows, list):
                problems.append("%s: expected calendar list" % name); continue
            source = blob.get("source") if isinstance(blob, dict) else "manual-drop"
            events.extend({"source": source or "manual-drop", **r} for r in rows if isinstance(r, dict))
    rows, bad = normalise(events)
    return rows, problems + bad


def collect(source="local", provider=None):
    rows, problems = from_drop()
    if source != "local":
        if provider is None:
            from sources.football_data_org import FootballDataOrgProvider
            provider = FootballDataOrgProvider(token=os.environ.get("FOOTBALL_DATA_KEY") or None)
        if provider.available():
            for competition in ("PL", "CL"):
                try:
                    rows.extend(provider.fetch_calendar(competition=competition))
                except Exception as exc:
                    problems.append("%s calendar: %s" % (competition, exc))
        elif source != "auto":
            problems.append(provider.unavailable_reason())
    events, bad = normalise(rows)
    return {"season": "2026-27", "events": events, "problems": problems+bad,
            "source": "recorded calendars" if events else "none",
            "tracked": bool(events), "international_coverage": "only explicitly recorded named-player appearances"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Collect exact PL/UCL fixtures or a manual calendar drop.")
    ap.add_argument("--source", choices=("local", "auto", "football-data.org"), default="local")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    payload = collect(args.source)
    if payload["events"] and not args.dry_run:
        # Preserve known events on a partial fetch, but identify that coverage is not complete.
        existing = load_json(OUT)
        payload["events"], bad = normalise((existing.get("events") or [])+payload["events"])
        payload["problems"].extend(bad)
        atomic_json(OUT, payload)
    print("%d exact calendar events; %d problems; no invented rest/travel" % (len(payload["events"]), len(payload["problems"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
