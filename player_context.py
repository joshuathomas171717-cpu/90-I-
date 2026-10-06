"""Build the optional player context, entirely offline. P14's output; P15 will add squad/What-If UI.

    python3 player_context.py

Every output carries timing, source, sample coverage and absence tier. This never trains the live
model or fetches data. The form table, history, dated availability and exact calendar are independent
inputs, so a missing optional source degrades visibly without changing a prediction.
"""
import argparse
import datetime as dt
import os

import availability
from absence_model import choose_impact, combine_absences
from congestion import OUT as CALENDAR, rest_context
from player_data import DATA, atomic_json, fold, load_csv, load_json, season_label, timestamp
from player_gate import OUT as GATE, eligible_history, observations
from player_history import dated_rows, history_path
from player_index import build_indices, squad_index
from sources.base import team_code

OUT = os.path.join(DATA, "player_context_2026_27.json")


def build(data=DATA):
    state = load_json(os.path.join(data, "as_of.json"))
    date = state.get("date")
    if timestamp(date) is None:
        raise ValueError("player context needs the project's as_of.json date; never invent a data date")
    cutoff = timestamp(date) + dt.timedelta(days=1) - dt.timedelta(microseconds=1)
    rows = load_csv(os.path.join(data, "players_form_2026_27.csv"))
    rows = [r for r in rows if season_label(r.get("season")) == "2026-27"]
    roster = load_csv(os.path.join(data, "players_2026_27.csv"))
    teams = {r["code"]: r for r in load_csv(os.path.join(data, "teams_2026_27.csv"))}
    current_history = load_json(os.path.join(data, "player_history_2026_27.json"))
    current_fixtures = eligible_history(current_history.get("fixtures") or [], cutoff.isoformat())
    rows += dated_rows(current_fixtures)
    from player_history import normalise_match_rows
    _extra_rows, _extra_problems = normalise_match_rows(current_history.get("player_matches") or [], "2026-27")
    rows += _extra_rows
    indices = build_indices(rows, roster, cutoff.isoformat())
    old = load_json(os.path.join(data, "player_history_2025_26.json"))
    old_obs = observations(eligible_history(old.get("fixtures") or [], cutoff.isoformat()))
    # IDs change between providers. Only exact full-name/club joins may align a historical id.
    local = {(r["club"], fold(r["name"])): r["player_id"] for r in roster}
    historic_map = {}
    for fixture in old.get("fixtures") or []:
        for p in fixture.get("players") or []:
            pid = local.get((p.get("club"), fold(p.get("player") or p.get("name"))))
            if pid:
                historic_map[(p["club"], str(p["player_id"]))] = pid
    for r in old_obs:
        r["player_id"] = historic_map.get((r["club"], r["player_id"]), r["player_id"])
    members = {(r["club"], str(r["player_id"])): r for r in roster}
    for player in indices:
        member = members.get((player["club"], player["player_id"])) or {
            "player_id": player["player_id"], "club": player["club"], "position": player["position"]}
        own = [r for r in rows if r.get("club") == player["club"] and (
            str(r.get("player_id")) == player["player_id"] or fold(r.get("player")) == fold(player["name"]))]
        # Current dated rows replace their competition total for form, so do not sum both for absence.
        own_dates = [r for r in own if r.get("match_date")]
        own_totals = [r for r in own if not r.get("match_date")]
        player["absence"] = choose_impact(member, teams.get(player["club"]) or {},
                                         own_totals or own_dates, old_obs, cutoff.isoformat())
        player["absence"]["source"] = player["sources"]
        player["absence"]["fetched_at"] = player["fetched_at"]
        # A trend needs comparable DATED records. Season totals never acquire a fake sparkline.
        player["trend"] = {"delta": None, "previous_score": None, "days": 7,
                           "status": "unavailable; comparable dated history missing"}
        if player["aggregate_rows"] == 0 and player["dated_matches"] > 0:
            from player_index import form_index
            earlier = form_index(own, (cutoff-dt.timedelta(days=7)).isoformat(), player["position"])
            if earlier["score"] is not None and player["score"] is not None:
                player["trend"] = {"delta": round(player["score"]-earlier["score"], 2),
                                   "previous_score": earlier["score"], "days": 7, "status": "dated comparison"}
    capture = load_json(os.path.join(data, "availability_2026_27.json"))
    unavailable = combine_absences(indices, capture)
    squads = squad_index(indices)
    calendar = load_json(os.path.join(data, "player_calendar_2026_27.json"))
    events = calendar.get("events") or []
    remaining = load_csv(os.path.join(data, "fixtures_2026_27_remaining.csv"))
    next_fixtures = {}
    for fixture in remaining:
        for club, opponent, venue in ((fixture["home"], fixture["away"], "home"),
                                      (fixture["away"], fixture["home"], "away")):
            if club in next_fixtures:
                continue
            exact = [e for e in events if e.get("club") == club and e.get("competition") == "Premier League"
                     and team_code(e.get("opponent")) == opponent and e.get("venue") == venue
                     and timestamp(e.get("kickoff")) and timestamp(e["kickoff"]) > cutoff]
            kickoff = min((e["kickoff"] for e in exact), default=None)
            next_fixtures[club] = {"opponent": opponent, "gameweek": int(fixture["gw"]),
                                  "window": fixture["dates"], "kickoff": kickoff,
                                  **rest_context(club, kickoff, events)}
    gate = load_json(os.path.join(data, "player_gate_2025_26.json"))
    mode = "context"  # This layer has no authority to change the unvalidated production ML head.
    return {"version": "player-context/1", "model_card": "v3.0", "season": "2026-27", "as_of": date,
            "mode": mode, "input_enabled": False,
            "gate": {k: gate.get(k) for k in ("shadow_verdict", "delta", "test_matches", "reasons", "scope")},
            "coverage": {"players": len(indices), "clubs": len(squads),
                         "scored_players": sum(p["score"] is not None for p in indices),
                         "dated_players": sum(p["dated_matches"] > 0 for p in indices),
                         "tier2_players": sum(p["absence"]["tier"] == 2 for p in indices),
                         "exact_next_kickoffs": sum(r.get("kickoff") is not None for r in next_fixtures.values()),
                         "availability_tracked": bool(capture.get("tracked")),
                         "squad_scope": "tracked sample; complete-squad coverage not verified",
                         "competition_scope": sorted({c for p in indices for c in p["competitions"]}),
                         "international_scope": "unverified; excluded unless explicitly verified per record"},
            "players": indices, "squads": squads, "absences": unavailable, "next_fixture_context": next_fixtures,
            "availability": {k: capture.get(k) for k in ("captured_at", "source", "tracked", "coverage", "gameweek", "problems")},
            "problems": _extra_problems,
            "policy_notes": ["season totals have no per-match recency", "form index is not a win probability",
                             "absence priors price a replacement, not zero contribution",
                             "with/without statistics are associations, not causal injury effects",
                             "exact rest/travel candidate does not replace the active europe proxy until validated"],
            "legacy_europe_proxy_still_used": True}


def compact(payload):
    """Small, date-free status for the self-contained app. Detailed provenance lives on the model card."""
    import hashlib
    import json
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {"mode": "context", "input_enabled": False, "coverage": payload.get("coverage") or {},
            "shadow_verdict": (payload.get("gate") or {}).get("shadow_verdict") or "not-measured",
            "fingerprint": digest[:16], "model_card": "player-model.html"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build keyless player context; no live model changes.")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)
    payload = build()
    atomic_json(args.out, payload)
    if args.as_json:
        import json
        print(json.dumps(payload, indent=2, allow_nan=False))
    else:
        c = payload["coverage"]
        print("Player context: %d players, %d clubs, %d dated, %d Tier 2, %d exact next kickoffs; INPUT OFF" % (
            c["players"], c["clubs"], c["dated_players"], c["tier2_players"], c["exact_next_kickoffs"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
