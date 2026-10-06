"""Phase 15: offline presentation data, squad panels and snapshot-derived team-news digests.

The rolling capture describes now. A locked gameweek may ONLY show its sealed capture, never the
rolling file or a field added to an old snapshot later. Lack of evidence is visible, not a healthy team.
"""
import datetime as dt
import hashlib
import html
import json
import os

from player_data import DATA, atomic_json, fold, load_json, timestamp
from player_context import compact
from player_scenarios import profile_from_player
from score_ledger import availability_evidence, availability_chain_problems

OUT = os.path.join(DATA, "player_ui_2026_27.json")


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def date_label(value):
    date = timestamp(value)
    return date.strftime("%d %b %Y, %H:%M UTC").lstrip("0") if date else "fetch date unavailable"


def player_status(player, capture, now=None):
    club = player["club"]
    covered = (capture.get("coverage") or {}).get(club, "unknown")
    if not capture.get("tracked") or covered in ("unknown", "failed"):
        return {"status": "unknown", "label": "Availability unknown", "reason": "This club has no complete current check."}
    date = timestamp(capture.get("captured_at"))
    now = now or dt.datetime.now(dt.timezone.utc)
    if date is None or date > now or now-date > dt.timedelta(days=3):
        return {"status": "stale", "label": "Availability capture stale", "reason": "Not a current team-news report."}
    for missing in (capture.get("clubs") or {}).get(club) or []:
        if str(missing.get("player_id") or "") == str(player["player_id"]) or fold(missing.get("player")) == fold(player["name"]):
            return {"status": "out", "label": "Listed in source: " + str(missing.get("type") or "absence"),
                    "reason": str(missing.get("reason") or "Reason not supplied") + "; specific match applicability is not verified."}
    if covered != "checked":
        return {"status": "unknown", "label": "No absence listed; coverage partial", "reason": "A partial list is not a clean bill of health."}
    return {"status": "not-listed", "label": "No absence listed", "reason": "Source checked; this is not a guarantee of selection."}


def gameweek_evidence(gameweek, ledger, rolling=None, snapshots=None):
    locks = [l for l in ledger.get("locks") or [] if int(l.get("gameweek", 0)) == int(gameweek)]
    if locks:
        lock = locks[-1]
        evidence = availability_evidence(lock)
        if evidence["status"] == "sealed-at-lock" and availability_chain_problems(ledger):
            return {"status": "mismatch", "capture": None, "note": "The availability seal/revision chain does not verify."}
        return evidence
    if snapshots:
        snap = snapshots.get(int(gameweek)) or {}
        capture = snap.get("availability")
        if isinstance(capture, dict):
            return {"status": "unlocked-snapshot", "capture": capture,
                    "note": "Dated snapshot, not sealed in a prediction lock yet."}
    if rolling and rolling.get("gameweek") == int(gameweek):
        return {"status": "current-unlocked-capture", "capture": rolling,
                "note": "Latest capture for this gameweek; not yet sealed at lock."}
    return {"status": "not-recorded", "capture": None, "note": "No availability snapshot for this matchweek. Missing is not healthy."}


def build(data=DATA):
    context = load_json(os.path.join(data, "player_context_2026_27.json"))
    capture = load_json(os.path.join(data, "availability_2026_27.json"))
    ledger = load_json(os.path.join(data, "ledger_2026_27.json"))
    fingerprint = compact(context)["fingerprint"]
    players = []
    for incoming in context.get("players") or []:
        p = dict(incoming)
        minutes = {}
        for detail in p.get("detail") or []:
            minutes[detail["competition"]] = minutes.get(detail["competition"], 0)+detail["minutes"]
        players.append({k: p.get(k) for k in ("player_id", "name", "club", "position", "score", "raw_minutes",
                                            "recency", "competitions", "sources", "fetched_at", "absence", "trend")}
                       | {"minutes_by_competition": minutes, "availability": player_status(p, capture),
                          "effect_profile": profile_from_player(p, context.get("as_of") or "", fingerprint)})
    snapshots = {}
    folder = os.path.join(data, "snapshots")
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            if name.startswith("gw") and name.endswith(".json"):
                snapshot = load_json(os.path.join(folder, name))
                if snapshot.get("gameweek"):
                    snapshots[int(snapshot["gameweek"])] = snapshot
    return {"version": "player-ui/1", "mode": "context", "input_enabled": False,
            "as_of": context.get("as_of"), "context_hash": fingerprint,
            "coverage": context.get("coverage") or {}, "players": players,
            "availability_capture": capture,
            "by_gameweek": {str(gw): gameweek_evidence(gw, ledger, capture, snapshots) for gw in range(1, 39)},
            "scenario_policy": {"model": "replacement-share/1", "attack_cap": 30, "defence_cap": 25,
                                "note": "Explicit user assumptions only. Frozen effect ranges, not win/points confidence intervals."}}


def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()[:16]


def squad_panel(layer, club):
    members = [p for p in layer.get("players") or [] if p["club"] == club]
    if not members:
        return '<section class="squad-panel"><h2>Squad context</h2><p>No player source available. Forecast uses the existing team model.</p></section>'
    rows = []
    for p in members:
        score = "Unavailable" if p.get("score") is None else "%.1f / 100" % p["score"]
        trend = p.get("trend") or {}
        trend_label = "%+.1f vs 7 days earlier" % trend["delta"] if trend.get("delta") is not None else "Trend unavailable: no comparable dated matches"
        minutes = " · ".join("%s: %d min" % (name, amount) for name, amount in (p.get("minutes_by_competition") or {}).items())
        a = p.get("absence") or {}
        status = p.get("availability") or {}
        rows.append('<tr><th scope="row">%s<br><span class="muted">%s</span></th><td>%s<br><span class="muted">%s</span></td>'
                    '<td>%s</td><td>%s<br><span class="muted">%s</span></td><td>Tier %s<br>%s</td></tr>' % (
                        esc(p["name"]), esc(p["position"]), score, esc(trend_label), esc(minutes),
                        esc(status.get("label")), esc(status.get("reason")), a.get("tier", "?"),
                        esc(a.get("label") or "not available")))
        rows.append('<tr><td colspan="5" class="muted" style="font-size:12px">Source: %s · Fetched/exported: %s · %s</td></tr>' % (
            esc(", ".join(p.get("sources") or []) or "unavailable"), esc(date_label(p.get("fetched_at"))), esc(p.get("recency"))))
    return ('<section class="squad-panel"><h2>Who is carrying the tracked squad?</h2>'
            '<p class="note">Context only; not automatic prediction input. %d tracked players, not a complete squad. '
            'Indices describe output, not winning chances. International coverage unverified unless explicitly recorded.</p>'
            '<div class="card"><div class="tablewrap" tabindex="0" role="region" aria-label="Squad form, minutes and availability; scroll horizontally" style="overflow-x:auto">'
            '<table style="min-width:710px"><caption style="text-align:left;padding-bottom:10px">Player data with source and fetch date on every row</caption>'
            '<thead><tr><th scope="col">Player</th><th scope="col">Form &amp; trend</th><th scope="col">Minutes by competition</th>'
            '<th scope="col">Latest availability</th><th scope="col">Absence estimate</th></tr></thead><tbody>%s</tbody></table></div></div>'
            '<p><a href="../player-model.html" style="text-decoration:underline">Method, tiers and limitations</a> · '
            '<a href="../index.html#whatif" style="text-decoration:underline">Try a named-player assumption</a></p></section>') % (len(members), "".join(rows))


def availability_digest(evidence, clubs, heading="Who is missing?", show_lock=False):
    evidence = evidence or {"status": "not-recorded", "capture": None, "note": "No capture available."}
    capture = evidence.get("capture")
    intro = evidence.get("note") or ""
    rows = []
    for club in sorted(set(clubs)):
        coverage = (capture or {}).get("coverage") or {}
        missing = ((capture or {}).get("clubs") or {}).get(club) or []
        if not capture or not capture.get("tracked") or coverage.get(club, "unknown") in ("unknown", "failed"):
            label = "Availability unknown — not a clean bill of health"
        elif missing:
            label = "; ".join("%s — %s%s" % (p.get("player") or "Unnamed player", p.get("type") or "Listed out",
                                            ": "+str(p["reason"]) if p.get("reason") else "") for p in missing)
        elif coverage.get(club) == "checked":
            label = "Source checked; no absence listed (selection not guaranteed)"
        else:
            label = "Partial list; no listed absence, coverage incomplete"
        rows.append('<li><b>%s</b> — %s</li>' % (esc(club), esc(label)))
    provenance = ('Source: %s · Captured: %s' % (esc(capture.get("source") or "unavailable"),
                   esc(date_label(capture.get("captured_at"))))) if capture else "No source or pre-lock capture recorded"
    seal = (' · Seal: <code>%s</code>' % esc(str(evidence.get("hash"))[:16])) if evidence.get("hash") else ""
    return ('<section class="missing-digest" data-evidence="%s"><h2>%s</h2><div class="card">'
            '<p class="note">%s</p><p class="muted">%s%s</p>'
            '<details><summary style="cursor:pointer">Availability for %d clubs</summary><ul>%s</ul></details>'
            '<p class="muted">Context only; injury news is not automatically priced into these probabilities. '
            'Later team news never replaces the evidence at an earlier lock.</p></div></section>') % (
                esc(evidence.get("status")), esc(heading), esc(intro), provenance, seal, len(set(clubs)), "".join(rows))


def main():
    layer = build()
    atomic_json(OUT, layer)
    print('Player UI: %d named players; source labels, frozen scenario profiles and lock-safe gameweek evidence' % len(layer['players']))
    return 0



def embedded(layer, gameweek, known_ids=None):
    """Keep the self-contained app small; complete squads/history remain on generated pages/JSON.

    Do not duplicate full absence calculations or profile provenance already on each player. Only the
    active matchweek needs an inline digest. Limit previews per club and disclose omissions; never
    silently claim that this preview is a complete squad.
    """
    preview = json.loads(json.dumps(layer))
    preview.pop('availability_capture', None)
    preview['by_gameweek'] = {str(gameweek): preview.get('by_gameweek', {}).get(str(gameweek))}
    known = set(known_ids or [])
    per_club, selected = {}, []
    ordered = sorted(preview.get('players') or [], key=lambda p: (p['club'], p['player_id'] not in known, p.get('name') or ''))
    for player in ordered:
        club = player['club']
        if per_club.get(club, 0) >= 4 and player['player_id'] not in known:
            continue
        per_club[club] = per_club.get(club, 0)+1
        player['absence'] = {k: (player.get('absence') or {}).get(k) for k in ('tier','label','status')}
        profile = player.get('effect_profile')
        if profile:
            player['effect_profile'] = {k: profile[k] for k in ('model','club','tier','attack','defence','attack_range','defence_range')}
        selected.append(player)
    preview['players'] = selected
    preview['omitted_players'] = len(layer.get('players') or [])-len(selected)
    return preview

if __name__ == '__main__':
    raise SystemExit(main())
