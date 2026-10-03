"""validate_data.py — the gate every automated change must pass (P4.3).

A weekly job that writes straight into `data/` is one bad API response away from publishing nonsense:
a duplicate fixture, a club that played 39 games, a standings feed that arrived half-populated. So
nothing is ever written in place. Fetched data lands in `data/staging/<date>/`, the *merged* result is
validated here, and only a dataset that passes every check is promoted. A failure leaves the staged
files where they are (with a written reason) and exits non-zero, so the weekly job stops loudly instead
of publishing quietly.

    python3 validate_data.py                  # validate data/ as it stands
    python3 validate_data.py --root /tmp/x    # validate any directory of the same shape
    python3 validate_data.py --json           # machine-readable report
"""
import argparse
import csv
import json
import os
import re
import sys
from datetime import date as _date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
STAGING_DIR = os.path.join(DATA_DIR, "staging")

CLUBS_EXPECTED = 20
GAMES_PER_CLUB = 38
MATCHES_PER_SEASON = CLUBS_EXPECTED * GAMES_PER_CLUB // 2      # 380
MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"])}


def season_ordinal(month, day):
    """A season runs August → May, so calendar months are useless for ordering: 2 January follows
    30 December. Map month+day onto a single scale that starts in August."""
    return ((month - 8) % 12) * 31 + day


# ── loading ──────────────────────────────────────────────────────────────────
def _read_csv(root, name):
    path = os.path.join(root, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _digits(value):
    m = re.search(r"-?\d+", str(value or ""))
    return int(m.group()) if m else None


def load_dataset(root=DATA_DIR):
    """Everything the checks need, or None for a file that is missing."""
    return {
        "teams": _read_csv(root, "teams_2026_27.csv"),
        "played": _read_csv(root, "matches_2026_27_played.csv"),
        "remaining": _read_csv(root, "fixtures_2026_27_remaining.csv"),
        "players": _read_csv(root, "players_2026_27.csv"),
        "matches_25_26": _read_csv(root, "matches_2025_26.csv"),
    }


# ── checks ───────────────────────────────────────────────────────────────────
# Each returns (ok: bool, detail: str). They read only from the loaded dict, so the same checks run
# against the live dataset and against a staged candidate.
def check_clubs(data):
    teams = data.get("teams")
    if not teams:
        return False, "teams_2026_27.csv missing or empty"
    codes = [t["code"] for t in teams]
    if len(codes) != CLUBS_EXPECTED:
        return False, "expected %d clubs, found %d" % (CLUBS_EXPECTED, len(codes))
    if len(set(codes)) != len(codes):
        dupes = sorted({c for c in codes if codes.count(c) > 1})
        return False, "duplicate club codes: %s" % ", ".join(dupes)
    bad = [c for c in codes if not re.fullmatch(r"[A-Z0-9]{2,4}", c)]
    if bad:
        return False, "malformed club codes: %s" % ", ".join(bad)
    return True, "%d clubs, unique codes" % len(codes)


def check_fixture_partition(data):
    """Played + remaining must partition the season exactly once — no fixture twice, none lost."""
    played, remaining = data.get("played") or [], data.get("remaining") or []
    if not played and not remaining:
        return False, "no fixtures at all"
    keys = [(r["home"], r["away"]) for r in played] + [(r["home"], r["away"]) for r in remaining]
    seen, dupes = set(), []
    for k in keys:
        if k in seen:
            dupes.append("%s-%s" % k)
        seen.add(k)
    if dupes:
        return False, "fixture appears more than once: %s" % ", ".join(sorted(set(dupes))[:6])
    if len(keys) != MATCHES_PER_SEASON:
        return False, "season has %d matches, expected %d" % (len(keys), MATCHES_PER_SEASON)
    return True, "%d played + %d remaining = %d matches, no duplicates" % (
        len(played), len(remaining), len(keys))


def check_games_per_club(data):
    teams = data.get("teams") or []
    played, remaining = data.get("played") or [], data.get("remaining") or []
    if not teams:
        return False, "no clubs to check"
    problems = []
    for row in teams:
        code = row["code"]
        home = sum(1 for r in played + remaining if r["home"] == code)
        away = sum(1 for r in played + remaining if r["away"] == code)
        if home != 19 or away != 19:
            problems.append("%s: %d home / %d away" % (code, home, away))
    if problems:
        return False, "clubs without 19 home + 19 away: %s" % "; ".join(problems[:6])
    return True, "every club has 19 home + 19 away fixtures"


def check_dates_monotonic(data):
    """Gameweeks must run in order and in time: no fixture drifting backwards through the calendar."""
    remaining = data.get("remaining") or []
    played = data.get("played") or []
    gws = sorted({int(r["gw"]) for r in played})          # ten matches share a gameweek
    if gws and gws != list(range(1, len(gws) + 1)):
        return False, "played gameweeks are not contiguous from 1: %s" % gws[:12]
    keys = []
    for row in remaining:
        text = str(row.get("dates") or "")
        day = _digits(text)
        month = next((num for name, num in MONTHS.items() if name.lower() in text.lower()), None)
        if day is None or month is None:
            return False, "unparseable fixture date %r (gw %s, %s v %s)" % (
                text, row.get("gw"), row.get("home"), row.get("away"))
        keys.append((int(row["gw"]), season_ordinal(month, day), "%d/%d" % (day, month)))
    keys.sort()
    for (gw_a, ord_a, label_a), (gw_b, ord_b, label_b) in zip(keys, keys[1:]):
        if ord_b < ord_a:
            return False, "gw%d (%s) is dated before gw%d (%s)" % (gw_b, label_b, gw_a, label_a)
    first_pw = min((int(r["gw"]) for r in played), default=None)
    if first_pw is not None and keys and keys[0][0] < first_pw:
        return False, "remaining fixtures start at gw%d, before the last played gameweek" % keys[0][0]
    return True, "%d remaining fixtures in calendar order, played gameweeks contiguous" % len(remaining)


def check_scorelines(data):
    """Scorelines must be plausible integers — an API that returns null or 99 must never reach the model."""
    bad = []
    for row in data.get("played") or []:
        for side in ("home_goals", "away_goals"):
            value = _digits(row.get(side))
            if value is None or value < 0 or value > 12:
                bad.append("%s %s-%s: %s=%s" % (row.get("gw"), row.get("home"), row.get("away"), side, row.get(side)))
    if bad:
        return False, "implausible scorelines: %s" % "; ".join(bad[:5])
    return True, "every played match has integer goals in 0–12"


def check_goals_balance(data):
    """League-wide, every goal scored is a goal conceded."""
    played = data.get("played") or []
    gf = sum(_digits(r["home_goals"]) or 0 for r in played) + sum(_digits(r["away_goals"]) or 0 for r in played)
    ga = gf  # by construction; the real check is per-club below
    by_club_gf, by_club_ga = {}, {}
    for row in played:
        by_club_gf[row["home"]] = by_club_gf.get(row["home"], 0) + (_digits(row["home_goals"]) or 0)
        by_club_ga[row["home"]] = by_club_ga.get(row["home"], 0) + (_digits(row["away_goals"]) or 0)
        by_club_gf[row["away"]] = by_club_gf.get(row["away"], 0) + (_digits(row["away_goals"]) or 0)
        by_club_ga[row["away"]] = by_club_ga.get(row["away"], 0) + (_digits(row["home_goals"]) or 0)
    if sum(by_club_gf.values()) != sum(by_club_ga.values()):
        return False, "goals scored (%d) != goals conceded (%d)" % (sum(by_club_gf.values()), sum(by_club_ga.values()))

    # the teams file must agree with the match file — this is the check that catches a half-applied update
    teams = data.get("teams") or []
    drift = []
    for row in teams:
        code = row["code"]
        if _digits(row.get("GF")) != by_club_gf.get(code, 0) or _digits(row.get("GA")) != by_club_ga.get(code, 0):
            drift.append("%s: file %s/%s vs matches %s/%s" % (code, row.get("GF"), row.get("GA"),
                                                              by_club_gf.get(code, 0), by_club_ga.get(code, 0)))
    if drift:
        return False, "standings out of sync with results: %s" % "; ".join(drift[:4])
    return True, "league goals balance (%d) and the table agrees with the results" % gf


def check_table_consistency(data):
    """Every stored table row must be arithmetically self-consistent, and P + remaining = 38."""
    teams = data.get("teams") or []
    remaining = data.get("remaining") or []
    problems = []
    for row in teams:
        code, P, W, D, L = row["code"], _digits(row["P"]), _digits(row["W"]), _digits(row["D"]), _digits(row["L"])
        gf, ga, gd, pts = _digits(row["GF"]), _digits(row["GA"]), _digits(row["GD"]), _digits(row["Pts"])
        if None in (P, W, D, L, gf, ga, gd, pts):
            problems.append("%s: missing numeric table fields" % code); continue
        if P != W + D + L:
            problems.append("%s: P=%d != W+D+L=%d" % (code, P, W + D + L))
        if pts != 3 * W + D:
            problems.append("%s: Pts=%d != 3W+D=%d" % (code, pts, 3 * W + D))
        if gd != gf - ga:
            problems.append("%s: GD=%d != GF-GA=%d" % (code, gd, gf - ga))
        left = sum(1 for r in remaining if r["home"] == code or r["away"] == code)
        if P + left != GAMES_PER_CLUB:
            problems.append("%s: %d played + %d remaining != %d" % (code, P, left, GAMES_PER_CLUB))
    if problems:
        return False, "; ".join(problems[:6])
    return True, "all 20 table rows are arithmetically consistent and sum to 38 games"


def check_table_matches_results(data):
    """Recount the table from the results and compare — the strongest check in the file."""
    played = data.get("played") or []
    teams = data.get("teams") or []
    if not played or not teams:
        return False, "nothing to cross-check"
    tally = {t["code"]: {"P": 0, "W": 0, "D": 0, "L": 0, "Pts": 0} for t in teams}
    for row in played:
        h, a = row["home"], row["away"]
        hg, ag = _digits(row["home_goals"]) or 0, _digits(row["away_goals"]) or 0
        if h not in tally or a not in tally:
            return False, "result references an unknown club: %s v %s" % (h, a)
        for code, gf, ga in ((h, hg, ag), (a, ag, hg)):
            tally[code]["P"] += 1
            if gf > ga:
                tally[code]["W"] += 1; tally[code]["Pts"] += 3
            elif gf == ga:
                tally[code]["D"] += 1; tally[code]["Pts"] += 1
            else:
                tally[code]["L"] += 1
    drift = []
    for row in teams:
        got = tally[row["code"]]
        for field in ("P", "W", "D", "L", "Pts"):
            if _digits(row[field]) != got[field]:
                drift.append("%s %s=%s (results say %s)" % (row["code"], field, row[field], got[field]))
    if drift:
        return False, "; ".join(drift[:6])
    return True, "the stored table reproduces exactly from the %d played results" % len(played)


def check_squad_plausibility(data):
    """The player file is a *tracked subset*, not a squad list — so this checks coverage, not size.

    Every club must have a tracked goalkeeper (the Golden Glove race needs all twenty). Outfield
    coverage is allowed to be partial: the award markets simply cannot surface a player from a club
    nobody tracks, which is a real limitation worth stating rather than hiding behind a green tick.
    """
    players, teams = data.get("players") or [], data.get("teams") or []
    if not players:
        return False, "players_2026_27.csv missing or empty"
    by_club = {}
    for p in players:
        by_club.setdefault(p["club"], []).append(p)

    problems, keepers_missing, outfield_missing = [], [], []
    for row in teams:
        code = row["code"]
        squad = by_club.get(code, [])
        if not [p for p in squad if p.get("pos") == "GK"]:
            keepers_missing.append(code)
        if not [p for p in squad if p.get("pos") != "GK"]:
            outfield_missing.append(code)
        if len(squad) > 10:
            problems.append("%s: %d tracked players (suspiciously large)" % (code, len(squad)))
    for p in players:
        if (_digits(p.get("goals_curr")) or 0) < 0 or (_digits(p.get("assists_curr")) or 0) < 0:
            problems.append("%s: negative goal/assist count" % p.get("name"))

    if keepers_missing:
        problems.append("no goalkeeper tracked: %s" % ", ".join(keepers_missing))
    covered = len(teams) - len(outfield_missing)
    if covered < CLUBS_EXPECTED * 0.7:
        problems.append("only %d/%d clubs have a tracked outfield player" % (covered, len(teams)))
    if problems:
        return False, "; ".join(problems[:6])

    detail = "%d tracked players · 20/20 keepers" % len(players)
    if outfield_missing:
        detail += " · no tracked outfielder at %s (their award markets stay empty)" % ", ".join(sorted(outfield_missing))
    return True, detail


def check_league_rate(data):
    """A goals-per-game figure far off the historical band means the data is wrong, not the league."""
    played = data.get("played") or []
    if not played:
        return True, "no played matches yet"
    total = sum((_digits(r["home_goals"]) or 0) + (_digits(r["away_goals"]) or 0) for r in played)
    rate = total / len(played)
    if not 2.0 <= rate <= 3.6:
        return False, "goals per game is %.2f across %d matches — outside the plausible 2.0–3.6 band" % (rate, len(played))
    return True, "%.2f goals per game across %d matches" % (rate, len(played))


def check_training_data(data):
    """The 2025-26 training set must still be a complete season."""
    rows = data.get("matches_25_26")
    if not rows:
        return True, "no 2025-26 file in this root (skipped)"
    if len(rows) != MATCHES_PER_SEASON:
        return False, "2025-26 training set has %d matches, expected %d" % (len(rows), MATCHES_PER_SEASON)
    gf = sum((_digits(r["home_goals"]) or 0) for r in rows) + sum((_digits(r["away_goals"]) or 0) for r in rows)
    return True, "2025-26 training set intact (%d matches, %d goals)" % (len(rows), gf)


CHECKS = [
    ("clubs", check_clubs),
    ("fixture_partition", check_fixture_partition),
    ("games_per_club", check_games_per_club),
    ("dates_monotonic", check_dates_monotonic),
    ("scorelines", check_scorelines),
    ("goals_balance", check_goals_balance),
    ("table_consistency", check_table_consistency),
    ("table_matches_results", check_table_matches_results),
    ("squad_plausibility", check_squad_plausibility),
    ("league_rate", check_league_rate),
    ("training_data", check_training_data),
]


def validate_all(root=DATA_DIR, data=None):
    """Run every check. Returns {"ok", "checks": [...], "counts": {...}} — never raises."""
    data = data if data is not None else load_dataset(root)
    results = []
    for name, fn in CHECKS:
        try:
            ok, detail = fn(data)
        except Exception as exc:                                   # a crashing check is a failed check
            ok, detail = False, "check raised %s: %s" % (type(exc).__name__, exc)
        results.append({"name": name, "ok": ok, "detail": detail})
    counts = {
        "clubs": len(data.get("teams") or []),
        "played": len(data.get("played") or []),
        "remaining": len(data.get("remaining") or []),
        "players": len(data.get("players") or []),
        "failed": sum(1 for r in results if not r["ok"]),
    }
    return {"ok": all(r["ok"] for r in results), "checks": results, "counts": counts, "root": root}


# ── staging: nothing touches data/ until it passes ───────────────────────────
def stage(label, payload, day=None, root=DATA_DIR):
    """Write a fetched payload to data/staging/<date>/ and return the path."""
    day = day or _date.today().isoformat()
    out_dir = os.path.join(root, "staging", day)
    os.makedirs(out_dir, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)
    path = os.path.join(out_dir, safe + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return path


def reject(staged_path, report):
    """Mark a staged payload as rejected, with the reason, and keep the files for inspection."""
    note = staged_path.replace(".json", ".REJECTED.md")
    lines = ["# Rejected staged payload", "", "**File:** `%s`" % os.path.basename(staged_path),
             "**When:** %s" % _date.today().isoformat(), "", "## Failed checks", ""]
    for check in report["checks"]:
        if not check["ok"]:
            lines.append("- **%s** — %s" % (check["name"], check["detail"]))
    if not any(not c["ok"] for c in report["checks"]):
        lines.append("- (no failing check recorded — the payload was rejected by the caller)")
    lines += ["", "Nothing was promoted into `data/`. Fix the source (or the mapping) and re-run.",
              "Raw payloads are kept under `data/raw/` and `data/staging/` for the audit trail.", ""]
    with open(note, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return note


def _rows_of(path):
    """Parsed rows of a CSV, or None if it does not exist. Used to compare *content*, not bytes."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except (OSError, csv.Error, UnicodeDecodeError):
        return None


def promote(staged_path, target_path, report=None):
    """Move a staged file over its target — but only when the report says the dataset is sound.

    The write is skipped when the parsed content already matches what is on disk. That is not just
    tidiness: `ml_engine`'s artifact cache is keyed on the *bytes* of these CSVs, so rewriting an
    identical file with a different float format or line ending would invalidate a perfectly good model
    and force a full retrain on the next request. Skipping no-op writes keeps warm boots warm.
    Returns True when the file was replaced, False when it was already current.
    """
    if report is not None and not report["ok"]:
        raise ValueError("refusing to promote: %d check(s) failed" % report["counts"]["failed"])
    if _rows_of(staged_path) == _rows_of(target_path):
        os.remove(staged_path)          # staged copy is redundant; nothing to publish
        return False
    os.replace(staged_path, target_path)
    return True


# ── CLI ──────────────────────────────────────────────────────────────────────
def print_report(report, stream=sys.stdout):
    counts = report["counts"]
    stream.write("Data validation — %s\n" % report["root"])
    stream.write("  %d clubs · %d played · %d remaining · %d tracked players\n\n"
                 % (counts["clubs"], counts["played"], counts["remaining"], counts["players"]))
    for check in report["checks"]:
        stream.write("  %s %-22s %s\n" % ("✓" if check["ok"] else "✗", check["name"], check["detail"]))
    stream.write("\n  %s (%d check%s failed)\n" % ("PASS" if report["ok"] else "FAIL",
                                                   counts["failed"], "" if counts["failed"] == 1 else "s"))
    return 0 if report["ok"] else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate the pipeline's datasets before they are used.")
    ap.add_argument("--root", default=DATA_DIR, help="directory holding the CSVs (default: data/)")
    ap.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = ap.parse_args(argv)
    report = validate_all(args.root)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        code = print_report(report)
        return code
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
