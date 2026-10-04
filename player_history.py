"""P14.2: resumable, quota-bound match-history intake. No secret required for the manual path.

    python3 player_history.py --source local --season 2025-26
    python3 player_history.py --source api-football --season 2025-26 --max-fixtures 20

A free-provider backfill is deliberately explicit, never part of CI or the regular refresh: one
fixture-list call plus one /fixtures/players call per match. At a 25/day safety budget, 380 match
calls take at least 16 UTC days; at 90/day, at least five. A cache hit does not pay again. Free-tier
historical access is unverified until the provider actually returns it.

Crucially, missing players and null minutes are NOT absence records. A zero-minute record must be
explicit. Historical injury/lineup data retrieved today does not magically become a timestamped
pre-match capture: the gate requires those captures separately and never invents known_at.
"""
import argparse
import datetime as dt
import os

from player_data import DATA, atomic_json, exact_time, load_json, number, season_label
from sources.base import team_code

DROP = os.path.join(DATA, "provider_drop", "player_history")


def history_path(season="2025-26"):
    return os.path.join(DATA, "player_history_%s.json" % str(season).replace("-", "_"))


def normalise_fixture(entry, season=None):
    """A normalised historical fixture needs exact kickoff, goals, both clubs, and explicit players."""
    fixture = dict(entry)
    kickoff = exact_time(fixture.get("kickoff"))
    if kickoff is None:
        raise ValueError("fixture %s has no exact, timezone-aware kickoff" % fixture.get("fixture_id"))
    if not fixture.get("fixture_id"):
        raise ValueError("fixture has no fixture_id")
    home, away = team_code(fixture.get("home")), team_code(fixture.get("away"))
    if not home or not away or home == away:
        raise ValueError("fixture %s has unresolved clubs" % fixture["fixture_id"])
    for field in ("home_goals", "away_goals"):
        value = fixture.get(field)
        if value is None or number(value, -1) < 0 or number(value) != int(number(value)):
            raise ValueError("fixture %s has invalid %s" % (fixture["fixture_id"], field))
        fixture[field] = int(number(value))
    fixture.update(fixture_id=str(fixture["fixture_id"]), home=home, away=away,
                   kickoff=kickoff.isoformat(), season=season_label(fixture.get("season") or season),
                   competition=fixture.get("competition") or "Premier League")
    valid = []
    for record in fixture.get("players") or []:
        if not isinstance(record, dict):
            continue
        club = team_code(record.get("club"))
        if club not in (home, away) or not record.get("player_id"):
            continue
        minutes = record.get("minutes")
        if minutes is not None and (number(minutes, -1) < 0 or number(minutes) > 130):
            continue
        valid.append({**record, "club": club, "player_id": str(record["player_id"]),
                      "minutes": number(minutes) if minutes is not None else None,
                      "goals": max(0, number(record.get("goals"))),
                      "assists": max(0, number(record.get("assists")))})
    fixture["players"] = valid
    ready = exact_time(fixture.get("stats_available_at"))
    if ready is not None and ready <= kickoff:
        raise ValueError("post-match statistics cannot be available before kickoff")
    fixture["stats_available_at"] = (ready or kickoff + dt.timedelta(days=1)).isoformat()
    fixture["stats_timing_basis"] = "supplied timestamp" if ready else "conservative next-day embargo"
    return fixture


def merge(fixtures, incoming, season=None):
    """Correct by fixture id; refuse duplicate home/away pairings with different ids."""
    best, problems, pairs = {}, [], {}
    for entry in list(fixtures or []) + list(incoming or []):
        try:
            fixture = normalise_fixture(entry, season)
        except (ValueError, TypeError, AttributeError) as exc:
            problems.append(str(exc)); continue
        if season and fixture["season"] != season_label(season):
            problems.append("fixture %s belongs to a different season" % fixture["fixture_id"]); continue
        pair = (fixture["home"], fixture["away"], fixture["competition"])
        if pair in pairs and pairs[pair] != fixture["fixture_id"]:
            problems.append("duplicate home/away pairing %s-%s with a different id" % pair[:2]); continue
        pairs[pair] = fixture["fixture_id"]
        best[fixture["fixture_id"]] = fixture
    return sorted(best.values(), key=lambda r: (r["kickoff"], r["fixture_id"])), problems


def normalise_match_rows(rows, season):
    """Single-player match records can describe foreign cup/national opponents without fake PL codes."""
    from player_data import timestamp
    out, problems = [], []
    for incoming in rows or []:
        if not isinstance(incoming, dict):
            problems.append("player match row is not an object"); continue
        record = dict(incoming)
        club = team_code(record.get("club"))
        date = timestamp(record.get("match_date") or record.get("date"))
        if not club or date is None or not record.get("player_id") or not record.get("player"):
            problems.append("player match needs club, id, name and actual match date"); continue
        if season_label(record.get("season") or season) != season_label(season):
            continue
        if record.get("minutes") is None or number(record.get("minutes"), -1) < 0 or number(record.get("minutes")) > 130:
            problems.append("player match minutes missing/invalid"); continue
        out.append({**record, "club": club, "match_date": date.isoformat(),
                    "season": season_label(season), "minutes": number(record["minutes"]),
                    "competition": record.get("competition") or "Premier League"})
    return out, problems


def from_drop(directory=DROP, season="2025-26"):
    fixtures, captures, events, matches, problems = [], [], [], [], []
    if not os.path.isdir(directory):
        return {"fixtures": [], "availability": [], "calendar": [], "player_matches": [], "problems": []}
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        blob = load_json(os.path.join(directory, name), default=None)
        if not isinstance(blob, dict) or not (isinstance(blob.get("fixtures"), list) or isinstance(blob.get("player_matches"), list)):
            problems.append("%s: expected an object with a fixtures list" % name); continue
        blob_season = season_label(blob.get("season") or season)
        if blob_season != season_label(season):
            continue
        fixtures.extend({"source": blob.get("source") or "manual-drop", **f} for f in blob.get("fixtures") or [] if isinstance(f, dict))
        captures.extend(c for c in blob.get("availability", []) if isinstance(c, dict))
        events.extend(c for c in blob.get("calendar", []) if isinstance(c, dict))
        matches.extend({"source": blob.get("source") or "manual-drop", **r} for r in blob.get("player_matches") or [] if isinstance(r, dict))
    fixtures, bad = merge([], fixtures, season)
    matches, bad_matches = normalise_match_rows(matches, season)
    return {"fixtures": fixtures, "availability": captures, "calendar": events,
            "player_matches": matches, "problems": problems + bad + bad_matches}


def dated_rows(fixtures):
    out = []
    for fixture in fixtures or []:
        for player in fixture.get("players") or []:
            if player.get("minutes") is None:
                continue
            out.append({**player, "player": player.get("player") or player.get("name") or player["player_id"],
                        "match_date": fixture["kickoff"], "fixture_id": fixture["fixture_id"],
                        "competition": fixture.get("competition") or "Premier League",
                        "season": fixture.get("season"), "source": fixture.get("source") or "unknown",
                        "fetched_at": fixture.get("fetched_at")})
    return out


def from_provider(provider, existing=None, max_fixtures=20, replay=False):
    """Persist after each successful fixture; a mid-run quota/network error never erases history."""
    from sources.api_football import QuotaExceeded
    season = season_label(provider.season)
    path = history_path(season)
    payload = dict(existing or load_json(path))
    fixtures = list(payload.get("fixtures") or [])
    done = {str(f["fixture_id"]) for f in fixtures if f.get("players")}
    problems, collected = [], 0
    if not provider.available() and not replay:
        return {**payload, "season": season, "fixtures": fixtures,
                "problems": [provider.unavailable_reason()], "collected": 0}
    try:
        calendar = provider.fetch_match_history(replay=replay)
    except Exception as exc:
        return {**payload, "season": season, "fixtures": fixtures,
                "problems": ["%s: %s" % (type(exc).__name__, exc)], "collected": 0}
    for entry in calendar:
        if str(entry["fixture_id"]) in done:
            continue
        if collected >= max_fixtures:
            break
        try:
            players = provider.fetch_fixture_players(entry["fixture_id"], replay=replay)
            if not players or not {entry["home"], entry["away"]}.issubset({p["club"] for p in players}):
                problems.append("fixture %s: player coverage missing for one or both clubs" % entry["fixture_id"])
                break
            fixtures, bad = merge(fixtures, [{**entry, "players": players}], season)
            if bad:
                problems.extend(bad); break
            collected += 1
            payload.update(season=season, fixtures=fixtures, source=provider.name,
                           collected=collected, problems=problems,
                           availability=payload.get("availability") or [], calendar=payload.get("calendar") or [])
            atomic_json(path, payload)
        except QuotaExceeded as exc:
            problems.append(str(exc)); break
        except Exception as exc:
            problems.append("fixture %s: %s" % (entry["fixture_id"], exc)); break
    return {**payload, "season": season, "fixtures": fixtures, "collected": collected, "problems": problems}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Resumable player match history; manual drops or the free provider.")
    ap.add_argument("--source", choices=("local", "api-football"), default="local")
    ap.add_argument("--season", default="2025-26")
    ap.add_argument("--max-fixtures", type=int, default=20)
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    season = season_label(args.season)
    out = args.out or history_path(season)
    existing = load_json(out)
    if args.source == "api-football":
        from sources.api_football import ApiFootballProvider
        payload = from_provider(ApiFootballProvider(season=season[:4]), existing,
                                max_fixtures=max(0, args.max_fixtures), replay=args.replay)
    else:
        payload = from_drop(season=season)
        fixtures, bad = merge(existing.get("fixtures") or [], payload["fixtures"], season)
        payload.update(fixtures=fixtures, season=season, source="manual-drop", problems=payload["problems"] + bad)
        # A no-drop replay preserves captures/calendar too, not just the player rows.
        for name in ("availability", "calendar", "player_matches"):
            combined = list(existing.get(name) or []) + list(payload.get(name) or [])
            unique = {}
            for record in combined:
                if name == "availability":
                    key = (str(record.get("fixture_id")), record.get("club"), record.get("known_at"))
                elif name == "calendar":
                    key = (str(record.get("fixture_id")), record.get("club"), str(record.get("player_id") or "club"), record.get("kickoff"))
                else:
                    key = (record.get("club"), str(record.get("player_id")), record.get("competition"),
                           str(record.get("fixture_id") or record.get("match_date")))
                unique[key] = record
            payload[name] = list(unique.values())
    if payload.get("fixtures") or payload.get("player_matches"):
        atomic_json(out, payload)
    print("%s: %d dated fixtures, %d pre-match captures; %d problem(s)" % (
        season, len(payload.get("fixtures") or []), len(payload.get("availability") or []), len(payload.get("problems") or [])))
    for problem in payload.get("problems") or []:
        print("  " + problem)
    if not payload.get("fixtures"):
        print("No usable history; nothing overwritten. The player gate remains context-only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
