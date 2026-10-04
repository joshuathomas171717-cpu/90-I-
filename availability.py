"""availability.py — who was out, and when we knew it (P13.3).

The ledger already proves *what* was predicted. This is the other half of an honest record: **what the
model could see when it made the call.** "We had them down as favourites and their two centre-backs were
injured" is an explanation after the fact; the same sentence with a dated snapshot attached is evidence.

So availability is captured per gameweek and stored *inside that gameweek's snapshot*, not in a rolling
file that gets overwritten. Over a season that becomes the thing a reader can check: open matchweek 6,
see exactly which players were listed unavailable on 3 October, and compare it with what the model said.

    python3 availability.py                        # provider when a key is set, else the drop directory
    python3 availability.py --source local          # data/provider_drop/injuries/*.json
    python3 availability.py --gw 6 --dry-run        # count what would be captured, write nothing

Without a key or a drop file this is a clean no-op: it writes a snapshot that says `source: none` and
lists every club as unknown, which is truthful and which the surfaces render as "not tracked yet" rather
than as "nobody is injured" (P15.4).
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sources.base import SEASON_LABEL, team_code  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
OUT = os.path.join(DATA, "availability_2026_27.json")
DROP_DIR = os.path.join(DATA, "provider_drop", "injuries")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _club_codes():
    path = os.path.join(DATA, "teams_2026_27.csv")
    if not os.path.exists(path):
        return []
    import csv as _csv
    with open(path, encoding="utf-8") as fh:
        return sorted({(row.get("code") or row.get("team") or "").strip()
                       for row in _csv.DictReader(fh) if row})


CLUB_CODES = _club_codes()


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  Sources
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def from_drop(directory=DROP_DIR):
    """Rows from data/provider_drop/injuries/*.json — a list, or {"injuries": [...]}."""
    rows, problems = [], []
    if not os.path.isdir(directory):
        return rows, problems
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(directory, name)
        try:
            with open(path, encoding="utf-8") as fh:
                blob = json.load(fh)
        except (OSError, ValueError) as exc:
            problems.append("%s: %s" % (name, exc))
            continue
        entries = blob.get("injuries") if isinstance(blob, dict) else blob
        if not isinstance(entries, list):
            problems.append("%s: expected a list, or an object with an 'injuries' list" % name)
            continue
        declared = blob.get("source") if isinstance(blob, dict) else None
        for entry in entries or []:
            if not isinstance(entry, dict) or not entry.get("player"):
                problems.append("%s: a row with no player name was skipped" % name)
                continue
            club = team_code(entry.get("club") or entry.get("team") or "")
            if not club:
                problems.append("%s: '%s' has no club we recognise (%r)"
                                % (name, entry.get("player"), entry.get("club") or entry.get("team")))
                continue
            rows.append({"player": str(entry["player"]).strip(), "club": club,
                         "type": str(entry.get("type") or "Injury"),
                         "reason": str(entry.get("reason") or ""),
                         "since": (str(entry.get("since") or "")[:10]) or None,
                         "source": str(entry.get("source") or declared or "manual-drop")})
        if not entries:
            problems.append("%s: no entries (an empty export is recorded, not ignored)" % name)
    return rows, problems


def from_provider(provider, replay=False, quiet=False):
    """One request per club, plus the club map. Reuses the player provider's quota accounting."""
    rows, problems = [], []
    teams = provider.fetch_teams(replay=replay)
    if not teams:
        return rows, ["the provider returned no clubs"]
    for team in teams:
        try:
            for entry in provider.fetch_injuries(team["id"], replay=replay):
                rows.append({"player": entry.get("player"), "club": team["code"],
                             "type": entry.get("type") or "Injury",
                             "reason": entry.get("reason") or "",
                             "since": (entry.get("since") or None),
                             "source": provider.name})
        except Exception as exc:
            problems.append("%s: %s" % (team["code"], exc))
        if not quiet:
            out = sum(1 for r in rows if r["club"] == team["code"])
            print("    %-4s %2d out" % (team["code"], out))
    return rows, problems


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  Build, attach, read
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def build(rows, source, problems=None, gameweek=None):
    """The dated object. Clubs with no entries are listed as empty rather than omitted, because 'we
    checked and found nobody' and 'we did not check' are different facts and must not look the same."""
    by_club = {}
    for code in CLUB_CODES:
        by_club[code] = []
    for row in rows:
        by_club.setdefault(row["club"], []).append({
            "player": row["player"], "type": row["type"], "reason": row["reason"], "since": row["since"]})
    known = bool(rows)
    return {
        "captured_at": now_iso(),
        "season": SEASON_LABEL,
        "gameweek": gameweek,
        "source": source,
        "tracked": known,
        "clubs": by_club,
        "totals": {"players_out": len(rows), "clubs_reporting": sum(1 for v in by_club.values() if v)},
        "problems": problems or [],
    }


def load(path=OUT):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def write(payload, path=OUT):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)
    return path


def attach(snapshot, payload):
    """Put the availability *inside* the gameweek snapshot — that is what makes it dated evidence.

    Returns the snapshot with the field added; the caller decides whether to write it. Never overwrites an
    availability block that is already there with an untracked one: a snapshot that has real data keeps it,
    because the alternative is a re-run quietly erasing the evidence.
    """
    if not isinstance(snapshot, dict):
        return snapshot
    existing = snapshot.get("availability") or {}
    if existing.get("tracked") and not (payload or {}).get("tracked"):
        return snapshot
    snapshot["availability"] = payload
    return snapshot


def summarise(payload, club=None):
    """A one-line reading, for the CLI, the digest and the tests."""
    if not payload:
        return "availability has never been captured"
    totals = payload.get("totals") or {}
    if not payload.get("tracked"):
        return ("availability not tracked — no key and no drop file; %d club(s) unknown"
                % len(CLUB_CODES))
    if club:
        out = (payload.get("clubs") or {}).get(club) or []
        if not out:
            return "%s: nobody listed out" % club
        return "%s: %s" % (club, ", ".join(sorted("%s (%s)" % (o["player"], o["type"]) for o in out)))
    return ("%d player(s) out across %d club(s) · source %s · captured %s"
            % (totals.get("players_out", 0), totals.get("clubs_reporting", 0),
               payload.get("source"), str(payload.get("captured_at") or "")[:10]))


def snapshot_dir(path=None):
    return path or os.path.join(DATA, "snapshots")


def attach_to_latest(gameweek=None, directory=None):
    """Find the newest snapshot (optionally the one for a gameweek) and attach availability to it."""
    directory = snapshot_dir(directory)
    candidates = []
    if os.path.isdir(directory):
        for name in sorted(os.listdir(directory)):
            if name.startswith("gw") and name.endswith(".json"):
                candidates.append(os.path.join(directory, name))
    if not candidates:
        return None
    path = candidates[-1]
    if gameweek is not None:
        wanted = os.path.join(directory, "gw%02d.json" % int(gameweek))
        if os.path.exists(wanted):
            path = wanted
    with open(path, encoding="utf-8") as fh:
        snapshot = json.load(fh)
    payload = build(*_collect(source="local", quiet=True)[:2], problems=None,
                    gameweek=snapshot.get("gameweek"))
    return attach(snapshot, payload), path


def _collect(source="auto", replay=False, quiet=False):
    from sources.api_football import ApiFootballProvider
    provider = ApiFootballProvider()
    if source == "auto":
        source = "api-football" if provider.available() else "local"
    if source == "api-football" and provider.available():
        return from_provider(provider, replay=replay, quiet=quiet) + ("api-football",)
    rows, problems = from_drop()
    return rows, problems, "manual-drop" if rows else "none"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Capture who is unavailable, dated, for the gameweek.")
    ap.add_argument("--source", default="auto", choices=("auto", "api-football", "local"))
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--gw", type=int, help="gameweek this capture belongs to")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--show", action="store_true", help="read the stored capture back")
    args = ap.parse_args(argv)

    if args.show:
        payload = load()
        print("  " + summarise(payload))
        for club, outs in sorted((payload.get("clubs") or {}).items()):
            if outs:
                print("    %-4s %s" % (club, ", ".join("%s — %s" % (o["player"], o["reason"] or o["type"])
                                                       for o in outs)))
        return 0

    rows, problems, source = _collect(args.source, replay=args.replay, quiet=args.quiet)
    payload = build(rows, source, problems=problems, gameweek=args.gw)
    if not args.quiet:
        print("  %s" % summarise(payload))
        for note in problems:
            print("    ! %s" % note)
    if args.dry_run:
        print("  dry run — nothing written")
        return 0
    write(payload)
    if not args.quiet:
        print("  wrote %s" % os.path.relpath(OUT, BASE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
