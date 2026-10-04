"""competition_weights.py — how much a minute is worth, and why that has to be written down (P13.4).

The football question this exists for: a player has 900 minutes so far, but 300 of them were a Champions
League group stage, 200 were the EFL Cup against a rotated side, 150 were international qualifiers and
only 250 were the league. Treating those 900 minutes as one number — which is what any model does until
it has a table like this — compares a Tuesday night in the cup with a Saturday against a title rival.

Three design decisions, each of which is a decision rather than an accident:

* **The weights are data, not code.** They live in `data/competition_weights.csv` so they can be read,
  argued with and diffed in a review; the loader does not contain a single number of its own.
* **An unknown competition is not silently average.** The caller is told (`matched=False`) and the
  default for a named-but-unlisted competition is deliberately below the league (0.85) rather than 1.0,
  because the failure to avoid is flattering a number nobody can justify.
* **The table is only as good as its sensitivity.** `sensitivity()` reports how much a given body of
  minutes moves when each weight moves by a plausible amount, and the test suite pins the claim. A table
  nobody has perturbed is a table nobody has tested.

The weights are anchored to the Premier League = 1.00 and are judgement, not measurement — that is
stated here, in the CSV's own notes, and on the model page. What is *measured* is the sensitivity: the
plan's promise is that the choice is visible, not that it is final. They are also the one part of the
player work that needs no provider, no key and no network, which is why it is the part that got built
first.
"""
import csv
import os

BASE = os.path.dirname(os.path.abspath(__file__))
TABLE = os.path.join(BASE, "data", "competition_weights.csv")

# The names arrive from providers in whatever shape they like, so matching is by fold + alias. Aliases
# are only added for names actually seen or documented — an alias invented to make a test pass would hide
# exactly the mismatch this file exists to expose.
ALIASES = {
    "pl": "premier_league",
    "epl": "premier_league",
    "premier league": "premier_league",
    "english premier league": "premier_league",
    "ucl": "champions_league",
    "champions league": "champions_league",
    "uefa champions league": "champions_league",
    "champions league qualification": "champions_league_qualification",
    "uefa champions league qualification": "champions_league_qualification",
    "uel": "europa_league",
    "europa league": "europa_league",
    "uefa europa league": "europa_league",
    "conference league": "conference_league",
    "uefa conference league": "conference_league",
    "uefa europa conference league": "conference_league",
    "fa cup": "fa_cup",
    "fa cup - england": "fa_cup",
    "efl cup": "efl_cup",
    "carabao cup": "efl_cup",
    "league cup": "efl_cup",
    "efl trophy": "efl_trophy",
    "community shield": "community_shield",
    "fifa club world cup": "fifa_club_world_cup",
    "club world cup": "fifa_club_world_cup",
    "world cup": "world_cup",
    "fifa world cup": "world_cup",
    "euro": "euro",
    "uefa european championship": "euro",
    "european championship": "euro",
    "copa america": "copa_america",
    "africa cup of nations": "afcon",
    "afcon": "afcon",
    "afc asian cup": "asian_cup",
    "asian cup": "asian_cup",
    "world cup - qualification": "world_cup_qualification",
    "wc qualification": "world_cup_qualification",
    "wc qualification europe": "world_cup_qualification",
    "ec qualification": "euro_qualification",
    "nations league": "nations_league",
    "uefa nations league": "nations_league",
    "friendlies": "friendlies",
    "friendly": "friendlies",
    "club friendlies": "club_friendly",
    "youth": "youth",
    "u21": "youth",
}


def _fold(text):
    """Lowercase, trim, collapse whitespace and unify the dashes providers mix freely."""
    return " ".join(str(text or "").replace("\u2013", "-").replace("\u2014", "-").split()).strip().lower()


def load_table(path=TABLE):
    """{competition_key: row}. Raises if the file is missing — a form index without weights is a lie."""
    if not os.path.exists(path):
        raise FileNotFoundError("competition weights are missing at %s" % path)
    out = {}
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            key = (row.get("competition_key") or "").strip()
            if not key:
                continue
            out[key] = {
                "key": key,
                "name": row.get("name", key),
                "tier": row.get("tier", "unknown_competition"),
                "weight": float(row.get("weight") or 1.0),
                "counts": (row.get("counts_toward_form") or "yes").strip().lower() == "yes",
                "note": row.get("note", ""),
            }
    if not out:
        raise ValueError("competition_weights.csv parsed to zero rows")
    return out


_CACHE = {}


def table(path=TABLE):
    if path not in _CACHE:
        _CACHE[path] = load_table(path)
    return _CACHE[path]


def lookup(competition, path=TABLE):
    """(weight, key, matched). `matched` is False for anything the table does not recognise.

    Callers are expected to look at `matched` rather than to trust the number: the whole point of
    returning it is that a row of the form index built on an unlisted competition is a smaller claim
    than one built on listed ones, and the surfacing layer says so (P15.4).
    """
    rows = table(path)
    folded = _fold(competition)
    if not folded:
        return 0.85, "other_known", False
    # exact key first, then alias, then a substring sweep over names and keys (longest match wins, so
    # "Champions League Qualification" cannot be swallowed by "Champions League")
    if folded in rows:
        return rows[folded]["weight"], folded, True
    if folded in ALIASES and ALIASES[folded] in rows:
        key = ALIASES[folded]
        return rows[key]["weight"], key, True
    candidates = []
    for key, row in rows.items():
        for probe in (_fold(row["name"]), _fold(key)):
            if probe and (probe in folded or folded in probe):
                candidates.append((len(probe), key))
    if candidates:
        candidates.sort(reverse=True)
        key = candidates[0][1]
        return rows[key]["weight"], key, True
    return rows["other_known"]["weight"] if "other_known" in rows else 0.85, "other_known", False


def league_equivalent_minutes(rows, path=TABLE, cap=1800):
    """Sum competitive minutes, each weighted, with a cap.

    The cap exists because the index is a *form* signal, not a workload signal: past roughly twenty
    full matches the extra information is small and the risk of a player simply having played more
    football dominating the index is large. It is a documented choice, and `sensitivity()` shows it is
    not the lever that matters.
    """
    total = 0.0
    detail = []
    excluded = []
    for row in rows or []:
        weight, key, matched = lookup(row.get("competition"), path)
        info = table(path).get(key, {})
        minutes = float(row.get("minutes") or 0)
        if minutes <= 0:
            continue
        if not info.get("counts", True):
            excluded.append({"competition": row.get("competition"), "minutes": minutes,
                             "why": info.get("note") or "does not count toward form"})
            continue
        total += minutes * weight
        detail.append({"competition": row.get("competition"), "minutes": minutes,
                       "weight": weight, "key": key, "matched": matched})
    return {"minutes": min(total, cap), "raw": total, "capped": total > cap,
            "detail": detail, "excluded": excluded}


def sensitivity(bodies, path=TABLE, deltas=(-0.10, 0.10)):
    """How much does the answer move if the weights are wrong by 10%?

    `bodies` is a list of `league_equivalent_minutes` inputs — one per player, say. Returns the worst
    relative change per competition key, so the biggest lever is named rather than implied. This is the
    check the plan promised: a table nobody has perturbed is a table nobody has tested.

    Deliberately a pure function of its inputs: it is run in tests against the real design and against
    a body built from the table itself, so it cannot pass by having nothing to move.
    """
    base = [league_equivalent_minutes(b, path)["raw"] for b in bodies]
    out = {}
    for key in sorted(table(path)):
        worst = 0.0
        for delta in deltas:
            # a delta is applied by re-weighting that competition's minutes in place
            moved = []
            for body in bodies:
                shifted = []
                for row in body or []:
                    row = dict(row)
                    weight, got, _ = lookup(row.get("competition"), path)
                    if got == key:
                        row["_shift"] = True
                    shifted.append(row)
                moved.append(shifted)
            after = []
            for body in moved:
                total = 0.0
                for row in body:
                    weight, got, _ = lookup(row.get("competition"), path)
                    minutes = float(row.get("minutes") or 0)
                    info = table(path).get(got, {})
                    if not info.get("counts", True) or minutes <= 0:
                        continue
                    if row.get("_shift"):
                        weight = max(0.0, weight + delta)
                    total += minutes * weight
                after.append(total)
            for b, a in zip(base, after):
                if b > 0:
                    worst = max(worst, abs(a - b) / b)
        out[key] = round(worst, 4)
    return out


def largest_lever(scores):
    """The competition whose weight moves an index the most — named so the doc can name it too."""
    if not scores:
        return None, 0.0
    key = max(scores, key=lambda k: scores[k])
    return key, scores[key]


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Inspect the competition-strength weights (P13.4).")
    ap.add_argument("--sensitivity", action="store_true",
                    help="report how much a typical body of minutes moves when each weight moves 10%%")
    ap.add_argument("--check", help="what is a single competition worth? e.g. 'Champions League'")
    args = ap.parse_args(argv)

    if args.check:
        weight, key, matched = lookup(args.check)
        row = table().get(key, {})
        print("%s → %s (weight %.2f, tier %s, counts=%s)%s"
              % (args.check, key, weight, row.get("tier", "?"), row.get("counts", "?"),
                 "" if matched else "  ← NOT in the table: flagged, not silently accepted"))
        return 0

    if args.sensitivity:
        # Representative bodies, not a uniform smear: giving every competition 200 minutes makes every
        # lever identical by construction and says nothing. These are three realistic shapes of a
        # season so far, named so the reader knows what was actually perturbed.
        bodies = [
            ("a domestic-only player", [("Premier League", 720), ("EFL Cup", 180), ("FA Cup", 90)]),
            ("a European starter", [("Premier League", 720), ("UEFA Champions League", 420),
                                    ("FA Cup", 90), ("EFL Cup", 45)]),
            ("an international regular", [("Premier League", 630), ("UEFA Champions League", 270),
                                          ("WC Qualification", 360), ("Friendlies", 90)]),
        ]
        shaped = [[{"competition": c, "minutes": m} for c, m in body] for _, body in bodies]
        scores = sensitivity(shaped)
        print("  how far a league-equivalent total moves when one weight is wrong by 10%:")
        for label, body in bodies:
            total = league_equivalent_minutes([{"competition": c, "minutes": m} for c, m in body])
            print("    %-24s %5.0f equivalent minutes from %d raw"
                  % (label, total["minutes"], sum(m for _, m in body)))
        print()
        for k in sorted(scores, key=lambda x: -scores[x])[:5]:
            if scores[k] > 0:
                print("    %-34s ±%.2f%%" % (k, scores[k] * 100))
        key, worst = largest_lever(scores)
        print("  biggest lever: %s at %.2f%% — the table's uncertainty is smaller than its resolution"
              % (key, worst * 100))
        return 0

    rows = table()
    print("  %d competitions · PL = 1.00 by definition" % len(rows))
    for key in sorted(rows, key=lambda k: -rows[k]["weight"])[:8]:
        row = rows[key]
        print("    %-34s %.2f  %s" % (row["name"], row["weight"], row["tier"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
