"""export_players_drop.py — turn our own squad dataset into drop files, so the player path runs keyless.

Why this exists. The player signal has two ways in: a free provider key (~21 requests) or a manual drop.
The drop path is the one that has to work for a student with no card, for CI, and for anyone reading this
repository who does not want to hold a secret — so it needs a *realistic* file to read, not a fixture
invented inside a test.

This writes that file from what the project already has: `data/players_2026_27.csv`, which carries each
player's league minutes, goals and assists for the current season. What it cannot produce is the split
across competitions — the dataset has no cup or European minutes, because our own pipeline never needed
them before this phase. So the rows carry `competition: "Premier League"` and the source is recorded as
`project-dataset`, which is what the provenance file will say on the page.

That is the honest limit of the keyless path, stated rather than papered over:

    League-only. A form index built from these rows is a *league* form index, and every surface that
    shows it must say so (P15.4). Fetching with a key adds the Champions League, the FA Cup, the EFL
    Cup and internationals — that is what the key buys, and it is nothing else.

    python3 tools/export_players_drop.py             # write data/provider_drop/players/dataset.json
    python3 tools/export_players_drop.py --stdout ]  # inspect without writing
"""
import argparse
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SOURCE_CSV = os.path.join(ROOT, "data", "players_2026_27.csv")
OUT = os.path.join(ROOT, "data", "provider_drop", "players", "dataset.json")


def rows_from_dataset(path=SOURCE_CSV):
    if not os.path.exists(path):
        raise SystemExit("no %s — run the pipeline once first (python3 run_all.py)" % path)
    out = []
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("name") or "").strip()
            club = (row.get("club") or "").strip()
            if not name or not club:
                continue
            minutes = _int(row.get("mins_curr"))
            if minutes <= 0:
                # A player with no minutes has no form. Including him as a zero would dilute every
                # average built on top of this file.
                continue
            out.append({
                "player": name,
                "player_id": (row.get("player_id") or "").strip(),
                "club": club,
                "competition": "Premier League",
                "minutes": minutes,
                "goals": _int(row.get("goals_curr")),
                "assists": _int(row.get("assists_curr")),
                "season": "2026-27",
                # Deliberately not filled in: the dataset has no starts, appearances or ratings, and a
                # guessed 1.0 rating would be indistinguishable from a real one downstream.
                "starts": "",
                "appearances": "",
                "rating": "",
            })
    return out


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Export league-only player rows as a drop file.")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--stdout", action="store_true", help="print the payload instead of writing it")
    args = ap.parse_args(argv)

    rows = rows_from_dataset()
    payload = {
        "note": ("Exported from data/players_2026_27.csv by tools/export_players_drop.py. League-only: "
                 "no cup, European or international minutes. Replace or extend by fetching with a free "
                 "API-Football key (python3 player_form.py) for the full split."),
        "source": "project-dataset",
        "competition_scope": ["Premier League"],
        "players": rows,
    }
    if args.stdout:
        # The whole payload. This used to be truncated to 2000 characters for readability, which made it
        # invalid JSON to anything that parsed it — a pipe-friendly flag that could not be piped.
        print(json.dumps(payload, indent=2))
        return 0
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    clubs = sorted({r["club"] for r in rows})
    print("  wrote %s" % os.path.relpath(args.out, ROOT))
    print("  %d player(s) across %d club(s) · league minutes only" % (len(rows), len(clubs)))
    print("  next: python3 player_form.py --source local")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
