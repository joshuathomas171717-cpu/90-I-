"""P14.2 — two absence tiers, explicitly accounting for a replacement.

Tier 1 is a share-of-club-output prior, not a star multiplier or an estimate from a partial squad's
sum. GK/defender defensive role shares are stated assumptions. Ranges are replacement scenarios, not
statistical confidence intervals.

Tier 2 compares opponent/home-adjusted output residuals with and without the player. Only explicit
zero-minute records count as absence; a missing row is UNKNOWN, not injured. It is an association,
not a causal injury effect. Everything after the caller's cutoff is excluded before fitting.
"""
import math
import statistics

from player_data import fold, number, policy, timestamp
from player_index import position


def replacement_prior(player, club, records=None, settings=None):
    settings = settings or policy()
    role = position(player.get("pos") or player.get("position"))
    # Existing squad entries use mins_curr/goals_curr; a provider history uses minutes/goals.
    league_rows = [r for r in (records or []) if (r.get("competition") or "Premier League") == "Premier League"]
    goals = sum(number(r.get("goals")) for r in league_rows) if league_rows else number(player.get("goals_curr"))
    assists = sum(number(r.get("assists")) for r in league_rows) if league_rows else number(player.get("assists_curr"))
    minutes = sum(number(r.get("minutes")) for r in league_rows) if league_rows else number(player.get("mins_curr"))
    matches = number(club.get("P") or club.get("played"))
    club_goals = number(club.get("GF") or club.get("gf"))
    participation = min(1., max(0., minutes / (90 * matches))) if matches else 0.
    output_share = min(1., max(0., (goals + settings["assist_value"] * assists) / club_goals)) if club_goals > 0 else None
    attack_share = (output_share or 0) * settings["attack_role"].get(role, 0)
    defence_share = participation * settings["defence_role_share"].get(role, 0)

    def impact(retained):
        return {"attack_loss_pct": round(min(settings["absence_attack_cap_pct"], 100 * attack_share * (1-retained)), 3),
                "defence_cost_pct": round(min(settings["absence_defence_cap_pct"], 100 * defence_share * (1-retained)), 3)}
    low, high = settings["replacement_range"]
    usable = role != "UNKNOWN" and minutes > 0 and matches > 0
    status = "prior" if usable else "insufficient-data"
    return {"tier": 1, "label": "replacement-share prior", "status": status, "measured": False,
            **impact(settings["replacement_retained"]),
            "range": {"low": impact(high), "high": impact(low), "kind": "replacement assumptions, not a confidence interval"},
            "replacement_retained": settings["replacement_retained"],
            "output_share": round(output_share, 4) if output_share is not None else None,
            "participation_share": round(participation, 4), "position": role,
            "basis": "club league goals, not the sum of the tracked squad sample",
            "defence_basis": "position-share assumption; goalkeeper/defender impact is not measured",
            "causal": False}


def measured_impact(player_id, club, observations, cutoff, settings=None):
    """Observation: {club, player_id, kickoff, minutes, gf, ga, expected_gf, expected_ga}.

    Expected goals here mean the opponent-adjusted *baseline forecast*, NOT a licensed xG feed.
    They must have been computed from pre-match priors by the caller. Match statistics are safe to
    use only after their availability time (default: conservatively the following UTC day).
    """
    settings = settings or policy()
    end = timestamp(cutoff)
    if end is None:
        raise ValueError("absence fit needs a cutoff")
    present, absent = [], []
    seen = set()
    for row in observations:
        if str(row.get("player_id")) != str(player_id) or row.get("club") != club:
            continue
        date = timestamp(row.get("kickoff"))
        if date is None or date >= end:
            continue
        ready = timestamp(row.get("stats_available_at"))
        if ready is None:
            import datetime as dt
            ready = date + dt.timedelta(days=1)
        if ready >= end or row.get("minutes") is None or row.get("minutes") == "":
            continue
        fixture = str(row.get("fixture_id") or date.isoformat())
        if fixture in seen:
            continue
        egf, ega = number(row.get("expected_gf")), number(row.get("expected_ga"))
        if egf <= 0 or ega <= 0:
            continue
        seen.add(fixture)
        residual = (math.log((max(0, number(row.get("gf"))) + .5) / (egf + .5)),
                    math.log((max(0, number(row.get("ga"))) + .5) / (ega + .5)))
        (present if number(row["minutes"]) > 0 else absent).append(residual)
    if len(present) < settings["tier2_min_present"] or len(absent) < settings["tier2_min_absent"]:
        return None
    shrink = len(absent) / (len(absent) + settings["tier2_shrink_matches"])
    diff_gf = statistics.mean(r[0] for r in absent) - statistics.mean(r[0] for r in present)
    diff_ga = statistics.mean(r[1] for r in absent) - statistics.mean(r[1] for r in present)
    attack = max(-10., min(settings["absence_attack_cap_pct"], 100 * (1-math.exp(diff_gf * shrink))))
    defence = max(-10., min(settings["absence_defence_cap_pct"], 100 * (math.exp(diff_ga * shrink)-1)))
    # A normal-approximation descriptive interval, not a claim of random injury assignment.
    def span(column, diff, defence=False):
        se = math.sqrt(statistics.variance(r[column] for r in absent) / len(absent)
                       + statistics.variance(r[column] for r in present) / len(present))
        vals = [100*(math.exp((diff+s*1.96*se)*shrink)-1) if defence
                else 100*(1-math.exp((diff+s*1.96*se)*shrink)) for s in (-1, 1)]
        return [round(max(-10., min(30., v)), 3) for v in sorted(vals)]
    return {"tier": 2, "label": "opponent-adjusted with/without association", "status": "measured-association",
            "measured": True, "attack_loss_pct": round(attack, 3), "defence_cost_pct": round(defence, 3),
            "present_matches": len(present), "absent_matches": len(absent), "shrinkage": round(shrink, 4),
            "range": {"attack_loss_pct": span(0, diff_gf), "defence_cost_pct": span(1, diff_ga, True),
                      "kind": "descriptive 95% normal approximation; not a causal confidence claim"},
            "cutoff": end.isoformat(), "causal": False,
            "note": "not playing can reflect rotation, selection or injury; missing records never count as absence"}


def choose_impact(player, club, records=None, observations=None, cutoff=None):
    fitted = measured_impact(player.get("player_id"), player.get("club"), observations or [], cutoff) if cutoff else None
    return fitted or replacement_prior(player, club, records=records)


def combine_absences(players, capture):
    """Club adjustments only for explicitly listed people. Unknown coverage remains unknown."""
    settings = policy()
    by_name = {(p["club"], fold(p["name"])): p for p in players}
    by_id = {(p["club"], str(p["player_id"])): p for p in players}
    out = {}
    for club, missing in (capture.get("clubs") or {}).items():
        seen, matched, unmapped = set(), [], []
        for record in missing:
            player = (by_id.get((club, str(record.get("player_id"))))
                      or by_name.get((club, fold(record.get("player")))))
            if not player:
                unmapped.append(record.get("player") or record.get("player_id"))
                continue
            if player["player_id"] in seen:
                continue
            seen.add(player["player_id"])
            matched.append(player)
        tracked = bool(capture.get("tracked"))
        club_status = (capture.get("coverage") or {}).get(club)
        if club_status in ("unknown", "failed"):
            tracked = False
        # A listed-player-only manual capture does not prove every other club has been checked.
        if not capture.get("coverage") and not missing:
            tracked = False
        out[club] = {"tracked": tracked, "mapped_absences": len(matched), "unmapped": unmapped,
                     "attack_loss_pct": round(min(settings["absence_attack_cap_pct"],
                         sum(p["absence"]["attack_loss_pct"] for p in matched)), 3) if tracked else None,
                     "defence_cost_pct": round(min(settings["absence_defence_cap_pct"],
                         sum(p["absence"]["defence_cost_pct"] for p in matched)), 3) if tracked else None,
                     "tiers": sorted({p["absence"]["tier"] for p in matched}),
                     "players": [p["player_id"] for p in matched]}
    return out
