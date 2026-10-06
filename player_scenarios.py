"""P15.2 — frozen, user-chosen player assumptions. Never automatic prediction inputs.

Old scenarios without player_effects keep their old injury formula. A new named-player scenario
carries bounded coefficients, ranges, names, provenance and baseline vintage, so a later data refresh
cannot silently re-price its injury assumptions. Probability/points outputs still depend on the new
baseline; ranges here describe input assumptions, not confidence intervals on wins.
"""
import math

VERSION = "replacement-share/1"


def _num(value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("effect values must be finite numbers")
    return round(max(lo, min(hi, float(value))), 4)


def sanitise_effects(raw, injuries, known_codes, known_players, player_clubs=None):
    if raw is None:
        return {}, []
    if not isinstance(raw, dict) or len(raw) > 52:
        return {}, ["player_effects must be an object with at most 52 profiles"]
    out, errors = {}, []
    for pid, p in raw.items():
        if pid not in known_players or not injuries.get(pid):
            errors.append("player effect has no known active absence"); continue
        if not isinstance(p, dict) or p.get("model") != VERSION:
            errors.append("unsupported player effect model"); continue
        club = p.get("club")
        if club not in known_codes or player_clubs and player_clubs.get(pid) != club:
            errors.append("player effect club does not match the roster"); continue
        try:
            attack = _num(p.get("attack"), -10, 30)
            defence = _num(p.get("defence"), -10, 25)
            ar, dr = p.get("attack_range"), p.get("defence_range")
            if not isinstance(ar, list) or len(ar) != 2 or not isinstance(dr, list) or len(dr) != 2:
                raise ValueError("effect ranges need two endpoints")
            ar = sorted([_num(v, -10, 30) for v in ar]); dr = sorted([_num(v, -10, 25) for v in dr])
            if not ar[0] <= attack <= ar[1] or not dr[0] <= defence <= dr[1]:
                raise ValueError("central effect must lie inside its supplied range")
            tier = p.get("tier")
            if tier not in (1, 2) or isinstance(tier, bool):
                raise ValueError("effect tier must be 1 or 2")
            out[pid] = {"model": VERSION, "club": club, "tier": tier, "attack": attack, "defence": defence,
                        "attack_range": ar, "defence_range": dr,
                        **{k: str(p.get(k) or "")[:limit] for k, limit in
                           (("name", 100), ("source", 160), ("fetched_at", 40), ("baseline_as_of", 80), ("context_hash", 64))}}
        except ValueError as exc:
            errors.append(str(exc))
    return out, errors


def club_effects(effects, injuries, remaining):
    """Aggregate partial-season loss once per club. A negative association may mean less output loss."""
    out = {}
    for pid, p in (effects or {}).items():
        club = p["club"]
        matches = max(1, int(remaining.get(club, 33)))
        fraction = min(matches, max(0, int(injuries.get(pid, 0)))) / matches
        if not fraction:
            continue
        entry = out.setdefault(club, {"attack": 0., "defence": 0., "attack_range": [0., 0.], "defence_range": [0., 0.], "players": []})
        entry["attack"] += p["attack"]*fraction; entry["defence"] += p["defence"]*fraction
        for i in (0, 1):
            entry["attack_range"][i] += p["attack_range"][i]*fraction
            entry["defence_range"][i] += p["defence_range"][i]*fraction
        entry["players"].append(pid)
    for entry in out.values():
        for field, cap in (("attack", 30), ("defence", 25)):
            entry[field] = round(max(-10, min(cap, entry[field])), 4)
            entry[field+"_range"] = [round(max(-10, min(cap, v)), 4) for v in entry[field+"_range"]]
    return out


def profile_from_player(player, baseline_as_of, context_hash):
    a = player.get("absence") or {}
    if a.get("status") == "insufficient-data" or not a:
        return None
    r = a.get("range") or {}
    if a.get("tier") == 2:
        ar, dr = r.get("attack_loss_pct"), r.get("defence_cost_pct")
    else:
        ar = [(r.get(k) or {}).get("attack_loss_pct", 0) for k in ("low", "high")]
        dr = [(r.get(k) or {}).get("defence_cost_pct", 0) for k in ("low", "high")]
    return {"model": VERSION, "name": player.get("name"), "club": player.get("club"), "tier": a.get("tier", 1),
            "attack": a.get("attack_loss_pct", 0), "defence": a.get("defence_cost_pct", 0),
            "attack_range": ar, "defence_range": dr, "source": ", ".join(player.get("sources") or []),
            "fetched_at": player.get("fetched_at") or "", "baseline_as_of": baseline_as_of,
            "context_hash": context_hash}
