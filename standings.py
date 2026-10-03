"""standings.py — results in, table and Elo out. One implementation, used by both writers.

`data_builder.py` and `update_week.py` both need to turn a list of played matches into a league table.
Before Wave 2 they each had their own idea of that, which is how promoted results got quietly clobbered
by the next rebuild. This module is the single source of truth:

    recompute_standings(team_rows, played_rows)

* table fields (P/W/D/L/GF/GA/GD/Pts/form/ppg/current_pos) are recounted from the matches, so a
  half-applied update cannot survive;
* `elo_live` is a *form* adjustment on the club's base rating:

      elo_live = elo_base + (Pts - 1.36 x P) x 3.8 + GD x 1.4

  1.36 points per game is par, so this says "how far above or below an average season is this club,
  expressed in Elo". It is scale-free — the same formula is right after five games and after
  thirty-eight — and, importantly, it is the definition the published numbers were tuned on.

  This module used to walk the results with a sequential Elo update (K=20, goal-difference weighted)
  instead. That is the textbook approach and it measured *worse*: the model's cross-validated 1X2
  accuracy fell from 49.8% to 48.1% because a five-game walk barely moves a club from its base
  rating, while the tuned form term uses the whole season's points and goal difference. It also
  invalidated every published figure. The lesson is in the numbers, not the theory: share the
  definition that was tuned, and share it from one place.
* the xG ratings deliberately do **not** move here. Results do not contain xG; that is the whole
  point of docs/xg-strategy.md.
"""
CLUBS = 20
PAR_PPG = 1.36         # league-average points per game: par is 6.8 points after five games
ELO_PER_POINT = 3.8    # Elo points per point-per-game above/below par
ELO_PER_GOAL_DIFF = 1.4


def live_elo(elo_base, points, goal_diff, played):
    """The live rating: base strength plus this season's form, expressed in Elo points."""
    if played <= 0:
        return round(float(elo_base), 1)
    return round(float(elo_base) + (points - PAR_PPG * played) * ELO_PER_POINT
                 + goal_diff * ELO_PER_GOAL_DIFF, 1)


def outcome_of(home_goals, away_goals):
    return "H" if home_goals > away_goals else "A" if away_goals > home_goals else "D"


def recompute_standings(teams, played_rows):
    """teams: list of dicts (as read from teams_2026_27.csv). played_rows: list of
    {"home","away","home_goals","away_goals"} in any order. Returns new dicts; inputs are untouched."""
    tally = {t["code"]: {"P": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "pts": 0, "form": []}
             for t in teams}

    def ordered(rows):
        def key(row):
            try:
                return (int(row.get("gw") or 0), row["home"])
            except (TypeError, ValueError):
                return (0, row["home"])
        return sorted(rows, key=key)

    for row in ordered(played_rows):
        h, a = row["home"], row["away"]
        hg, ag = int(row["home_goals"]), int(row["away_goals"])
        if h not in tally or a not in tally:
            continue
        for code, gf, ga in ((h, hg, ag), (a, ag, hg)):
            t = tally[code]
            t["P"] += 1
            t["GF"] += gf
            t["GA"] += ga
            if gf > ga:
                t["W"] += 1; t["pts"] += 3; t["form"].append("W")
            elif gf == ga:
                t["D"] += 1; t["pts"] += 1; t["form"].append("D")
            else:
                t["L"] += 1; t["form"].append("L")

    ranking = sorted(tally, key=lambda c: (-tally[c]["pts"],
                                           -(tally[c]["GF"] - tally[c]["GA"]),
                                           -tally[c]["GF"], c))
    position = {code: i + 1 for i, code in enumerate(ranking)}

    out = []
    for team in teams:
        code = team["code"]
        t = tally[code]
        row = dict(team)
        row["P"], row["W"], row["D"], row["L"] = str(t["P"]), str(t["W"]), str(t["D"]), str(t["L"])
        row["GF"], row["GA"] = str(t["GF"]), str(t["GA"])
        row["GD"] = str(t["GF"] - t["GA"])
        row["Pts"] = str(t["pts"])
        row["form"] = "".join(t["form"][-5:])
        if t["P"]:
            row["ppg_current"] = "%.2f" % (t["pts"] / t["P"])
        row["elo_live"] = "%.1f" % live_elo(row.get("elo_base", row.get("elo_live", 1500)),
                                           t["pts"], t["GF"] - t["GA"], t["P"])
        row["current_pos"] = str(position[code])
        out.append(row)
    return out
