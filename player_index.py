"""P14.1 — competition-adjusted, minutes-weighted form, with honest timing limitations.

Dated match records decay with a 35-day half-life. Season aggregates DO NOT: their fetch date says
when a file was read, not when a player played. An aggregate-only output therefore says season-to-date,
recency unavailable. Dated rows replace (never add to) the same competition's season total.

The 0–100 index is role-relative, shrunk toward 50 for small samples. It is a descriptive index, not a
win probability. Policy priors live in data/player_signal_policy.json and are untrained judgement.
"""
import math
from collections import defaultdict

import competition_weights as weights
from player_data import fold, identity, number, policy, timestamp

POSITION = {"f": "FWD", "m": "MID", "d": "DEF", "g": "GK", "attacker": "FWD", "forward": "FWD", "fwd": "FWD", "midfielder": "MID",
            "mid": "MID", "defender": "DEF", "def": "DEF", "goalkeeper": "GK", "gk": "GK"}


def position(value):
    return POSITION.get(fold(value), "UNKNOWN")


def form_index(rows, as_of, pos="UNKNOWN", settings=None, internationals_verified=False):
    settings = settings or policy()
    cutoff = timestamp(as_of)
    if cutoff is None:
        raise ValueError("form index needs a valid as-of date")
    role = position(pos)
    candidates, excluded = [], []
    for incoming in rows:
        row = dict(incoming)
        date = timestamp(row.get("match_date") or row.get("date"))
        through = timestamp(row.get("aggregate_through"))
        if date and date > cutoff or through and through > cutoff:
            excluded.append({"competition": row.get("competition"), "reason": "after the cutoff"})
            continue
        if (row.get("match_date") or row.get("date")) and date is None:
            excluded.append({"competition": row.get("competition"), "reason": "invalid match date"})
            continue
        weight, key, matched = weights.lookup(row.get("competition"))
        spec = weights.table().get(key, {})
        if not spec.get("counts", True):
            excluded.append({"competition": row.get("competition"), "reason": "excluded competition"})
            continue
        if spec.get("tier", "").startswith("international") and not (
                internationals_verified or row.get("international_verified") is True):
            excluded.append({"competition": row.get("competition"), "reason": "international coverage unverified"})
            continue
        minutes = max(0, number(row.get("minutes")))
        if minutes <= 0:
            continue
        candidates.append((row, date, minutes, weight, key, matched))

    dated_keys = {key for _r, date, _m, _w, key, _known in candidates if date is not None}
    # Dedup by match, or by competition for a cumulative row. Corrections do not double a player's form.
    best = {}
    for item in candidates:
        row, date, minutes, _weight, key, _matched = item
        if date is None and key in dated_keys:
            excluded.append({"competition": row.get("competition"), "reason": "replaced by dated match sample"})
            continue
        unit = (key, str(row.get("fixture_id") or (date.isoformat() if date else "aggregate")))
        if unit not in best or minutes > best[unit][2]:
            best[unit] = item

    effective, raw_minutes, output, rating_sum, rating_minutes = 0., 0., 0., 0., 0.
    detail, dated_count, aggregate_count = [], 0, 0
    for row, date, minutes, weight, key, matched in best.values():
        decay = math.exp(-math.log(2) * max(0, (cutoff - date).total_seconds() / 86400)
                         / settings["half_life_days"]) if date else 1.0
        eff = minutes * weight * decay
        contribution = (max(0, number(row.get("goals")))
                        + settings["assist_value"] * max(0, number(row.get("assists")))) * weight * decay
        effective += eff
        raw_minutes += minutes
        output += contribution
        rating = number(row.get("rating"), default=-1)
        if 0 <= rating <= 10:
            rating_sum += rating * eff
            rating_minutes += eff
        dated_count += int(date is not None)
        aggregate_count += int(date is None)
        detail.append({"competition": row.get("competition"), "key": key, "minutes": minutes,
                       "weight": weight, "matched": matched,
                       "decay": round(decay, 5) if date else None,
                       "match_date": date.isoformat() if date else None})

    capped = min(effective, settings["minutes_cap"])
    reliability = capped / (capped + settings["shrink_minutes"]) if capped else 0.0
    rate = 90 * output / effective if effective else None
    prior = settings["position_output_prior_90"].get(role)
    output_score = (50 + 30 * math.log(max(0.05, rate / prior))) if prior and rate is not None else None
    rating = rating_sum / rating_minutes if rating_minutes else None
    rating_score = 50 + (rating - 6.7) * 20 if rating is not None else None
    if role == "GK":
        raw_score = rating_score   # A keeper with no goals has not, by definition, played badly.
    elif output_score is not None and rating_score is not None:
        raw_score = 0.6 * output_score + 0.4 * rating_score
    else:
        raw_score = output_score if output_score is not None else rating_score
    score = None if raw_score is None else settings["neutral_index"] + reliability * (
        max(0, min(100, raw_score)) - settings["neutral_index"])
    recency = "dated-matches" if dated_count and not aggregate_count else (
        "mixed-dated-and-season-totals" if dated_count else "season-totals; recency unavailable")
    competitions = sorted({d["competition"] for d in detail})
    return {"score": round(score, 2) if score is not None else None,
            "position": role, "effective_minutes": round(capped, 2),
            "uncapped_effective_minutes": round(effective, 2), "raw_minutes": raw_minutes,
            "reliability": round(reliability, 4), "output_90": round(rate, 4) if rate is not None else None,
            "rating": round(rating, 2) if rating is not None else None,
            "recency": recency, "dated_matches": dated_count, "aggregate_rows": aggregate_count,
            "scope": "league-only" if competitions == ["Premier League"] else "recorded competitions only",
            "competitions": competitions, "detail": detail, "excluded": excluded,
            "sources": sorted({r.get("source") or "unknown" for r, *_ in best.values()}),
            "fetched_at": max((str(r.get("fetched_at") or "") for r, *_ in best.values()), default="") or None,
            "note": "descriptive output index, not a probability; goalkeeper index needs ratings"}


def build_indices(rows, roster, as_of, internationals_verified=False):
    """Join by exact id OR exact full name plus club. No abbreviation/fuzzy joins or inferred positions."""
    id_map = {(r.get("club"), str(r.get("player_id"))): r for r in roster if r.get("player_id")}
    name_map = {(r.get("club"), fold(r.get("name") or r.get("player"))): r for r in roster}
    groups, metadata = defaultdict(list), {}
    for row in rows:
        club = row.get("club")
        member = id_map.get((club, str(row.get("player_id")))) or name_map.get(
            (club, fold(row.get("player") or row.get("name")))) or {}
        pid = str(member.get("player_id") or identity(row))
        key = (club, pid)
        groups[key].append(row)
        metadata[key] = {"player_id": pid, "name": member.get("name") or row.get("player") or pid,
                         "club": club, "position": member.get("pos") or row.get("position") or "UNKNOWN",
                         "identity_match": "exact" if member else "unmapped"}
    out = []
    for key, records in sorted(groups.items()):
        meta = metadata[key]
        signal = form_index(records, as_of, meta["position"], internationals_verified=internationals_verified)
        out.append({**meta, **signal})
    return out


def squad_index(players):
    """A minutes-weighted tracked-player index, NOT a complete-squad strength claim."""
    groups = defaultdict(list)
    for row in players:
        groups[row["club"]].append(row)
    out = {}
    for club, members in sorted(groups.items()):
        usable = [r for r in members if r["score"] is not None and r["effective_minutes"] > 0]
        minutes = sum(r["effective_minutes"] for r in usable)
        out[club] = {"index": round(sum(r["score"] * r["effective_minutes"] for r in usable) / minutes, 2)
                    if minutes else None, "tracked_players": len(members), "scored_players": len(usable),
                    "coverage": "partial-squad sample; completeness not verified",
                    "effective_minutes": round(minutes, 2),
                    "recency_available": bool(usable) and all(r["aggregate_rows"] == 0 for r in usable)}
    return out
