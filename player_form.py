"""player_form.py — the player signal: who played where, how much, and how well (P13.2).

One row per player per competition. That shape is the whole point of the phase: it is what lets the form
index ask "how much of this was the Premier League, how much was the Champions League, how much was a
Tuesday in the EFL Cup", and it is why a plain goals-and-assists table was not enough.

Two ways in, and they write the **same file**:

    python3 player_form.py --source api-football     # free key, ~21 requests of a 100/day allowance
    python3 player_form.py --source local            # data/provider_drop/players/*.json, no account

The second is not a fallback in name only. It is how the feature is developed, tested and reviewed
without spending quota or holding a secret, and a test builds a form table end to end from drop files
alone. If the drop path ever diverges from the fetch path, the feature has quietly stopped being
key-free.

What is written:
  data/players_form_2026_27.csv     one row per player per competition
  data/players_form_2026_27.meta.json   where it came from, when, how much of the quota it cost, and
                                        which competitions are present — the provenance P15.4 will show
"""
import argparse
import csv
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sources.base import RAW_DIR, SEASON_LABEL, team_code  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
FORM_CSV = os.path.join(DATA, "players_form_2026_27.csv")
META_JSON = os.path.join(DATA, "players_form_2026_27.meta.json")
DROP_DIR = os.path.join(DATA, "provider_drop", "players")

COLUMNS = ["player", "player_id", "club", "competition", "competition_id", "minutes", "starts",
           "appearances", "goals", "assists", "rating", "yellow", "red", "season", "source",
           "fetched_at"]


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  Manual drop — the path with no account
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def drop_files(directory=DROP_DIR):
    if not os.path.isdir(directory):
        return []
    return [os.path.join(directory, f) for f in sorted(os.listdir(directory))
            if f.endswith(".json")]


def rows_from_drop(directory=DROP_DIR):
    """Read the drop directory into our row shape.

    Two shapes are accepted, because the reader writing one by hand should not have to guess:
    a bare list of rows, or `{"players": [...]}`. Each row needs a player and a club; everything else
    is optional and defaults to zero, so a partial export still produces a usable, honest table.
    """
    rows, problems = [], []
    for path in drop_files(directory):
        try:
            with open(path, encoding="utf-8") as fh:
                blob = json.load(fh)
        except (OSError, ValueError) as exc:
            problems.append("%s: %s" % (os.path.basename(path), exc))
            continue
        entries = blob.get("players") if isinstance(blob, dict) else blob
        # A drop file may name its own provenance ("project-dataset", "fotmob-export", "typed by hand"),
        # and it should win over our generic label: the point of the provenance file is that a reader can
        # tell a real fetch from an export from someone's memory, and a blanket "manual-drop" hides that.
        declared = (blob.get("source") if isinstance(blob, dict) else None)
        if not isinstance(entries, list):
            problems.append("%s: expected a list, or an object with a 'players' list" % os.path.basename(path))
            continue
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("player"):
                problems.append("%s: a row with no player name was skipped" % os.path.basename(path))
                continue
            club = team_code(entry.get("club") or entry.get("team") or "")
            if not club:
                problems.append("%s: '%s' has no club we recognise (%r)"
                                % (os.path.basename(path), entry.get("player"),
                                   entry.get("club") or entry.get("team")))
                continue
            rows.append({
                "player": str(entry["player"]).strip(),
                "player_id": str(entry.get("player_id") or ""),
                "club": club,
                "competition": entry.get("competition") or "Premier League",
                "competition_id": str(entry.get("competition_id") or ""),
                "minutes": int(entry.get("minutes") or 0),
                "starts": int(entry.get("starts") or 0),
                "appearances": int(entry.get("appearances") or 0),
                "goals": int(entry.get("goals") or 0),
                "assists": int(entry.get("assists") or 0),
                "rating": entry.get("rating") or "",
                "yellow": int(entry.get("yellow") or 0),
                "red": int(entry.get("red") or 0),
                "season": entry.get("season") or SEASON_LABEL,
                "source": str(entry.get("source") or declared or "manual-drop"),
                "fetched_at": now_iso(),
            })
    return rows, problems


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  The provider path
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _cached_today(cache_name):
    """A payload fetched earlier today is read rather than re-bought.

    This is what makes the fetch resumable at all: if a run stops after fourteen clubs — out of quota,
    Ctrl-C, a flaky connection — the next run pays for six, not twenty-one. It does mean a same-day
    refresh is a no-op; `--fresh` overrides that, and spends the requests knowingly.
    """
    day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(RAW_DIR, day, "api-football-%s.json" % cache_name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def collect_from_provider(provider, fresh=False, replay=False, quiet=False):
    """Every club's players, one request per club. Returns (rows, report)."""
    report = {"clubs": 0, "calls": 0, "skipped_cached": 0, "unmapped": [], "quota": None, "problems": []}
    teams = provider.fetch_teams(replay=replay)
    if not teams:
        report["problems"].append("no clubs came back from the provider — nothing was collected")
        return [], report
    report["calls"] += 1

    rows = []
    for team in teams:
        cache_name = "players-%s-%s" % (team["id"], provider.season)
        cached = None if (fresh or replay) else _cached_today(cache_name)
        if cached is not None:
            from sources.api_football import ApiFootballProvider
            entries = ApiFootballProvider._entries(cached)
            report["skipped_cached"] += 1
        else:
            try:
                payload = provider._get("players", {"team": team["id"], "season": provider.season},
                                        cache_name, replay=replay)
            except Exception as exc:                      # quota, network, provider error
                report["problems"].append("%s: %s" % (team["code"], exc))
                continue
            report["calls"] += 1
            from sources.api_football import ApiFootballProvider
            entries = ApiFootballProvider._entries(payload)
        for entry in entries:
            player = entry.get("player") or {}
            for stat in entry.get("statistics") or []:
                league = stat.get("league") or {}
                games = stat.get("games") or {}
                goals = stat.get("goals") or {}
                cards = stat.get("cards") or {}
                rows.append({
                    "player": player.get("name"),
                    "player_id": str(player.get("id") or ""),
                    "club": team["code"],
                    "competition": league.get("name"),
                    "competition_id": str(league.get("id") or ""),
                    "minutes": int(games.get("minutes") or 0),
                    "starts": int(games.get("lineups") or 0),
                    "appearances": int(games.get("appearences") or 0),
                    "goals": int(goals.get("total") or 0),
                    "assists": int(goals.get("assists") or 0),
                    "rating": games.get("rating") or "",
                    "yellow": int(cards.get("yellow") or 0),
                    "red": int(cards.get("red") or 0),
                    "season": SEASON_LABEL,
                    "source": provider.name,
                    "fetched_at": now_iso(),
                })
        report["clubs"] += 1
        if not quiet:
            print("    %-4s %3d row(s)" % (team["code"], sum(1 for r in rows if r["club"] == team["code"])))
    report["quota"] = {"budget": provider.quota.budget, "used": provider.quota.used,
                       "left": provider.quota.left, "day": provider.quota.day}
    return rows, report


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  Normalise, check, write
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def normalise(rows):
    """Dedupe to one row per player+club+competition, keeping the largest minutes.

    Duplicates are real: a provider can return a player twice for the same competition across two
    payloads (a January move, a corrected feed). Keeping the largest minutes is the conservative choice —
    it prefers the record that has seen more football rather than summing two partial ones into a total
    nobody played.
    """
    best = {}
    for row in rows:
        if not row.get("player") or not row.get("club"):
            continue
        key = (str(row["player"]).strip().lower(), row["club"], str(row.get("competition") or "").lower())
        if key not in best or row.get("minutes", 0) > best[key].get("minutes", 0):
            best[key] = row
    out = list(best.values())
    out.sort(key=lambda r: (r["club"], -int(r.get("minutes") or 0), r["player"]))
    return out


def summarise(rows, report=None, problems=None):
    """The provenance file. Every number here is something the page will be able to show (P15.4)."""
    competitions = {}
    for row in rows:
        key = row.get("competition") or "unknown"
        entry = competitions.setdefault(key, {"rows": 0, "minutes": 0, "players": set()})
        entry["rows"] += 1
        entry["minutes"] += int(row.get("minutes") or 0)
        entry["players"].add(str(row.get("player")).lower())
    clubs = sorted({row["club"] for row in rows})
    return {
        "generated_at": now_iso(),
        "season": SEASON_LABEL,
        "rows": len(rows),
        "players": len({str(row.get("player")).lower() for row in rows}),
        "clubs": clubs,
        "clubs_missing": [c for c in CLUB_CODES if c not in clubs],
        "sources": sorted({row.get("source") or "unknown" for row in rows}),
        "problems": problems or [],
        "report": report or {},
        "competitions": {k: {"rows": v["rows"], "minutes": v["minutes"], "players": len(v["players"])}
                         for k, v in sorted(competitions.items())},
    }


# The twenty clubs, read from the dataset rather than typed, so a promoted club cannot be forgotten.
def _club_codes():
    path = os.path.join(DATA, "teams_2026_27.csv")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return sorted({(row.get("code") or row.get("team") or "").strip()
                       for row in csv.DictReader(fh) if row})


CLUB_CODES = _club_codes()


def write(rows, meta, out_csv=FORM_CSV, out_meta=META_JSON):
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in COLUMNS})
    with open(out_meta, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)
    return out_csv, out_meta


def load_meta(path=META_JSON):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def load_form(path=FORM_CSV):
    """The rows, or nothing. Absence is a normal state, not an error: the pipeline runs without this."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Collect the player signal: per player, per competition.")
    ap.add_argument("--source", default="auto", choices=("auto", "api-football", "local"),
                    help="auto = provider when a key is set, else the manual drop")
    ap.add_argument("--replay", action="store_true", help="read cached payloads, spend no quota")
    ap.add_argument("--fresh", action="store_true", help="re-fetch even if today's cache exists")
    ap.add_argument("--dry-run", action="store_true", help="collect and report, write nothing")
    ap.add_argument("--force", action="store_true",
                    help="write even when nothing was collected (this empties the table)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    from sources.api_football import ApiFootballProvider
    provider = ApiFootballProvider()
    source = args.source
    if source == "auto":
        source = "api-football" if provider.available() else "local"

    problems, report = [], {}
    if source == "api-football" and provider.available():
        if not args.quiet:
            print("  collecting from %s (%s requests/day, %d left today)"
                  % (provider.name, provider.quota.budget, provider.quota.left))
        rows, report = collect_from_provider(provider, fresh=args.fresh, replay=args.replay,
                                             quiet=args.quiet)
        problems += report.get("problems", [])
    else:
        if source == "api-football":
            problems.append(provider.unavailable_reason())
        rows, drop_problems = rows_from_drop()
        problems += drop_problems
        report = {"clubs": len({r["club"] for r in rows}), "calls": 0,
                  "note": "read from %s" % os.path.relpath(DROP_DIR, BASE)}

    rows = normalise(rows)
    meta = summarise(rows, report, problems)
    if not args.quiet:
        print("  %d row(s) · %d player(s) · %d club(s) · %d competition(s)"
              % (meta["rows"], meta["players"], len(meta["clubs"]), len(meta["competitions"])))
        for comp, info in meta["competitions"].items():
            print("    %-34s %4d rows · %6d minutes" % (comp, info["rows"], info["minutes"]))
        for note in problems:
            print("    ! %s" % note)
        if meta["clubs_missing"]:
            print("    · no data yet for: %s" % ", ".join(meta["clubs_missing"]))
    if args.dry_run:
        print("  dry run — nothing written")
        return 0

    # Never replace a good table with an empty one. This is the weekly job's own rule ("a pull that fails
    # validation is never promoted") applied to the player signal: a network blip or a spent quota must
    # not empty a table four other things read. Forcing it is possible, and deliberately loud.
    existing = load_form()
    if not rows and existing and not args.force:
        print("  refusing to write: 0 rows collected, and the existing table has %d — the signal is "
              "unchanged rather than emptied (--force to overwrite anyway)" % len(existing))
        return 1
    write(rows, meta)
    if not args.quiet:
        print("  wrote %s + %s" % (os.path.relpath(FORM_CSV, BASE), os.path.relpath(META_JSON, BASE)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
