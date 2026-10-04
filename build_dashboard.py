"""Assemble the dashboard: payload + club identity + source parts → static/index.html

The front-end lives in static/src/ as separate parts (theme, shell, logic, motion, ux, render) and is
compiled into ONE self-contained HTML file — no external requests, so it works offline and inside
sandboxed previews. Fonts are embedded as base64 WOFF2 for the same reason.
"""
import json
import os
from datetime import datetime
import re
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
STATIC = os.path.join(BASE, "static")
SRC = os.path.join(STATIC, "src")

def json_safe(obj):
    """Browsers' JSON.parse() rejects bare NaN/Infinity — strip them before embedding."""
    import math
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj


summary = json.load(open(os.path.join(DATA, "predictions_2026_27_summary.json")))
teams = pd.read_csv(os.path.join(DATA, "teams_2026_27.csv"))
fixtures = pd.read_csv(os.path.join(DATA, "fixtures_2026_27_remaining.csv"))
players = pd.read_csv(os.path.join(DATA, "players_2026_27.csv"))

# ── club identity: secondary kit colour + shirt pattern, used to draw inline SVG crests ──────────
CLUB_EXTRAS = {
    "ARS": ("#ffffff", "shoulders"), "AVL": ("#95bfe5", "shoulders"), "BOU": ("#000000", "stripes"),
    "BRE": ("#ffffff", "stripes"),   "BHA": ("#ffffff", "stripes"),   "CHE": ("#ffffff", "plain"),
    "COV": ("#ffffff", "plain"),     "CRY": ("#c4122e", "stripes"),   "EVE": ("#ffffff", "plain"),
    "FUL": ("#0a0a0a", "chest"),     "HUL": ("#000000", "stripes"),   "IPS": ("#ffffff", "plain"),
    "LEE": ("#1d428a", "chest"),     "LIV": ("#f6eb61", "plain"),     "MCI": ("#ffffff", "plain"),
    "MUN": ("#ffe500", "plain"),     "NEW": ("#ffffff", "stripes"),   "NFO": ("#ffffff", "plain"),
    "SUN": ("#ffffff", "stripes"),   "TOT": ("#ffffff", "plain"),
}

teams_in = []
for _, t in teams.iterrows():
    sec, pat = CLUB_EXTRAS.get(t["code"], ("#ffffff", "plain"))
    teams_in.append({
        "code": t["code"], "name": t["name"], "short": t["short"], "manager": t["manager"],
        "stadium": t["stadium"], "color": t["primary_color"], "europe": t["europe"],
        "xg": float(round(t["xg_90_live"], 3)), "xga": float(round(t["xga_90_live"], 3)),
        "elo": float(t["elo_live"]), "home_adv": float(t["home_adv"]), "ppg": float(t["ppg_current"]),
        "value_m": int(t["squad_value_m"]), "ppda": float(t["ppda"]), "set_piece": float(t["set_piece_xg"]),
        "capacity": int(t["capacity"]), "promoted": int(t["promoted"]),
        "current_pos": int(t["current_pos"]),
        "curr_p": int(t["P"]), "curr_w": int(t["W"]), "curr_d": int(t["D"]), "curr_l": int(t["L"]),
        "curr_gf": int(t["GF"]), "curr_ga": int(t["GA"]), "curr_gd": int(t["GD"]), "curr_pts": int(t["Pts"]),
        "form": t["form"],
    })

club_extras = {c: {"secondary": s, "pattern": p} for c, (s, p) in CLUB_EXTRAS.items()}

fixtures_in = [[r["home"], r["away"]] for _, r in fixtures.iterrows()]

players_in, gks_in = [], []
for _, p in players.iterrows():
    base = {
        "player_id": p["player_id"], "name": p["name"], "club": p["club"], "pos": p["pos"],
        "nation": p["nation"], "goals_curr": int(p["goals_curr"]), "assists_curr": int(p["assists_curr"]),
        "cs_curr": int(p["cs_curr"]), "goals_prev": int(p["goals_prev"]), "assists_prev": int(p["assists_prev"]),
        "goals_prev_verified": bool(p.get("goals_prev_verified", False)),
        "assists_prev_verified": bool(p.get("assists_prev_verified", False)),
        "mins_prob": float(p["mins_prob"]),
    }
    if p["pos"] == "GK":
        gks_in.append({**base, "cs_prev": int(p["cs_prev"]), "gk_psxg_diff": float(p["gk_psxg_diff"]),
                       "save_pct": float(p["save_pct"])})
    else:
        players_in.append({
            **base,
            "xg_90": float(p["xg_90"]), "xa_90": float(p["xa_90"]), "kp_90": float(p["kp_90"]),
            "shot_conv": round(float(p["shot_conv"]) * 100.0, 1),
            "pen_share": round(float(p["pen_share"]) * 100.0, 1),
        })

# ── head-to-head: real meetings inside the training window, both orderings ──────────────────────
h2h = {}
for path, label in ((os.path.join(DATA, "matches_2025_26.csv"), "2025–26"),
                    (os.path.join(DATA, "matches_2026_27_played.csv"), "2026–27")):
    df = pd.read_csv(path)
    for _, r in df.iterrows():
        rec = [r["home"], r["away"], int(r["home_goals"]), int(r["away_goals"]), label]
        h2h.setdefault(f'{r["home"]}-{r["away"]}', []).insert(0, rec)
        h2h.setdefault(f'{r["away"]}-{r["home"]}', []).insert(0, [r["home"], r["away"],
                                                                 int(r["home_goals"]), int(r["away_goals"]), label])

# ── backtest: per-match hit strip + rolling accuracy for the trust visual ───────────────────────
backtest_path = os.path.join(DATA, "backtest_2025_26.json")
backtest = None
if os.path.exists(backtest_path):
    backtest = json.load(open(backtest_path))
    preds = backtest.pop("predictions", [])
    backtest["hits"] = [1 if p.get("hit") else 0 for p in preds]
    win, step = 40, 10
    roll = []
    for i in range(win, len(preds) + 1, step):
        chunk = backtest["hits"][i - win:i]
        roll.append(round(sum(chunk) / win * 100, 1))
    backtest["rolling_accuracy"] = roll
    backtest["meta"]["rolling_window"] = win

def _ledger_digest(path):
    """A compact view of the live ledger for the page's pulse strip (P10.5).

    Deliberately not the whole file: the strip needs one tick per fixture — a boolean — plus the
    totals. Embedding every scored row would add a few KB per gameweek to a page with a 1 MB budget,
    for data the receipts page already renders in full.
    """
    if not os.path.exists(path):
        return {"locks": [], "scored": [], "summary": {}}
    with open(path, encoding="utf-8") as fh:
        ledger = json.load(fh)
    def _label(iso):
        """'2026-10-04T08:57:22+00:00' → '4 Oct'.

        The pulse says "locked 4 Oct", so it carries the fact a reader needs without a second ISO
        timestamp in the payload. That matters beyond tidiness: the page is checked for stray dates,
        because a leftover as-of date from an earlier build is a contradiction the reader cannot
        resolve — and a deliberate second date, written as raw ISO, trips exactly that guard.
        """
        try:
            return datetime.strptime(str(iso)[:10], "%Y-%m-%d").strftime("%d %b").lstrip("0")
        except (ValueError, TypeError):
            return ""

    digest = {
        "locks": [{"gameweek": lock.get("gameweek"), "predictions": lock.get("predictions"),
                   "locked_label": _label(lock.get("locked_at"))}
                  for lock in ledger.get("locks", [])],
        "scored": [{"gameweek": e.get("gameweek"), "matches": e.get("matches"), "hits": e.get("hits"),
                    "accuracy_pct": e.get("accuracy_pct"), "mean_rps": e.get("mean_rps"),
                    "ticks": [1 if r.get("hit") else 0 for r in e.get("rows", [])]}
                   for e in ledger.get("entries", [])],
        "summary": ledger.get("summary", {}),
        "verified": bool(ledger.get("locks")),
    }
    return digest


payload = json_safe({
    "baseline": summary, "backtest": backtest, "club_extras": club_extras, "h2h": h2h,
    "inputs": {"teams": teams_in, "fixtures": fixtures_in, "players": players_in, "gks": gks_in},
    "ledger": _ledger_digest(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "data", "ledger_2026_27.json")),
})

parts = {p: open(os.path.join(SRC, p), encoding="utf-8").read()
         for p in ("fonts.css", "theme.css", "app.html", "core.js", "motion.js", "ux.js", "store.js",
                   "render.js", "share.js", "router.js")}

# ── identity, previews and structured data for the app page itself (P5.1, P5.2) ────────────────
# Everything here is relative on purpose: the same file has to work from GitHub Pages under /90-I-/,
# from a local server at /, and from a double-clicked file:// path. `NT90_SITE_URL` upgrades the
# canonical and og:url to absolute when a build knows its own host — social platforms ignore a
# relative og:url, but a canonical is resolved against the page, so relative is honest and portable.
_site_url = (os.environ.get("NT90_SITE_URL") or "").rstrip("/")


def _abs(path):
    """Absolute URL when the build knows its host, otherwise the relative path.

    og:image and twitter:image have to be absolute — both Facebook and Twitter discard a relative
    one, so a link preview shows a blank card — while a canonical is resolved against the page URL
    by every crawler, so relative is honest there and keeps the file portable. Before this existed,
    every one of these was emitted relative, which meant previews silently never rendered.
    """
    return ("%s/%s" % (_site_url, path.lstrip("/"))) if _site_url else path


_canonical = (_site_url + "/") if _site_url else "./"
_og_url = (_site_url + "/") if _site_url else ""
# A placeholder rather than nothing: left unset, the tags say so in the markup, so the next person
# to view-source sees why their preview is blank instead of hunting for a missing tag.
_canonical_note = ("" if _site_url else
                   "<!-- canonical and og:image are relative: set NT90_SITE_URL at build time "
                   "(e.g. NT90_SITE_URL=https://example.vercel.app python3 build_dashboard.py) to "
                   "make them absolute. Social platforms ignore a relative og:image. -->")
_champion = max(summary["table_projections"], key=lambda t: t.get("title_prob", 0))
_runner = sorted(summary["table_projections"], key=lambda t: -t.get("title_prob", 0))[1]
_head_meta = f"""<meta name="description" content="Machine-learning predictions for the 2026–27 Premier League: title race, relegation, Golden Boot, assists, clean sheets and every remaining fixture.">
<meta name="theme-color" content="#0B0F1A">
<meta name="color-scheme" content="dark">
{_canonical_note}
<link rel="canonical" href="{_canonical}">
<link rel="icon" href="icon.svg" type="image/svg+xml">
<link rel="icon" href="icons/favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="manifest" href="manifest.webmanifest">
<meta property="og:type" content="website">
<meta property="og:site_name" content="NINETY+">
<meta property="og:title" content="Premier League 2026–27 predictions — NINETY+">
<meta property="og:description" content="{_champion['name']} to win the league at {_champion['title_prob']:.0f}%, projected {_champion['proj_pts']:.0f} points. {summary['ml_metrics']['remaining_fixtures']} fixtures simulated 5,000 times.">
<meta property="og:image" content="{_abs('og/site.png')}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="NINETY+ — {_champion['name']} projected to win the 2026-27 Premier League">
{"" if not _og_url else f'<meta property="og:url" content="{_og_url}">'}
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Premier League 2026–27 predictions — NINETY+">
<meta name="twitter:description" content="{_champion['name']} to win the league at {_champion['title_prob']:.0f}%, projected {_champion['proj_pts']:.0f} points.">
<meta name="twitter:image" content="{_abs('og/site.png')}">"""

def _jsonld_blocks():
    """WebSite + Dataset + the club list. Enough for a search engine to know what this is."""
    base = _site_url + "/" if _site_url else "./"
    graph = [
        {"@type": "WebSite", "name": "NINETY+", "url": base,
         "description": "Premier League 2026-27 machine-learning predictions",
         "inLanguage": "en"},
        {"@type": "Dataset", "name": "NINETY+ Premier League 2026-27 projections",
         "description": ("Projected final table, title/top-four/relegation probabilities and player "
                         "award races for the 2026-27 Premier League, from 5,000 simulated seasons."),
         "creator": {"@type": "Organization", "name": "NINETY+"},
         "dateModified": (summary.get("meta", {}).get("as_of_date") or "")[:10],
         "variableMeasured": ["Projected points", "Title probability", "Top-four probability",
                              "Relegation probability", "Projected goals", "Projected assists",
                              "Projected clean sheets"],
         "license": "https://opensource.org/licenses/MIT"},
        {"@type": "ItemList", "name": "Projected 2026-27 Premier League table",
         "itemListElement": [
             {"@type": "ListItem", "position": i + 1,
              "item": {"@type": "SportsTeam", "name": t["name"],
                       "location": {"@type": "Place", "name": t.get("stadium", "")}}}
             for i, t in enumerate(summary["table_projections"])]},
    ]
    return json.dumps({"@context": "https://schema.org", "@graph": graph},
                      separators=(",", ":"), ensure_ascii=False)

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NINETY+ · Premier League 2026–27 Predictions</title>
{_head_meta}
<script type="application/ld+json">{_jsonld_blocks()}</script>
<style>
{parts['fonts.css']}
{parts['theme.css']}
</style>
</head>
<body>
{parts['app.html']}
<script>
const EMBEDDED = {json.dumps(payload, separators=(",", ":"), allow_nan=False)};
{parts['store.js']}
{parts['core.js']}
{parts['motion.js']}
{parts['ux.js']}
{parts['render.js']}
{parts['share.js']}
{parts['router.js']}
</script>
</body>
</html>
"""

# A web app manifest, so "add to home screen" produces something better than a bookmark.
_manifest = {
    "name": "NINETY+ — Premier League Predictions",
    "short_name": "NINETY+",
    "description": "Premier League 2026-27 predictions, simulated 5,000 times.",
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "background_color": "#0B0F1A",
    "theme_color": "#0B0F1A",
    "icons": [
        {"src": "icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
        {"src": "icon.svg", "sizes": "any", "type": "image/svg+xml"},
    ],
}
with open(os.path.join(STATIC, "manifest.webmanifest"), "w", encoding="utf-8") as fh:
    json.dump(_manifest, fh, indent=2)

out = os.path.join(STATIC, "index.html")
open(out, "w", encoding="utf-8").write(html)
print(f"Wrote {out} ({len(html)/1024:.0f} KB) — {len(teams_in)} clubs, {len(fixtures_in)} fixtures, "
      f"{len(players_in)} outfield players, {len(gks_in)} keepers, {len(h2h)//2} H2H pairings, "
      f"{len(backtest['hits']) if backtest else 0} backtest calls")


# ── stamp the payload's own matchweek into the static HTML ───────────────────
# The runtime derives these from DATA.meta as well (render.js). Stamping them here too means the very
# first paint — before a byte of JavaScript runs — is never stale after the weekly job promotes a
# gameweek. P2.5.
def _stamp(html):
    meta = summary.get("meta", {}) or {}
    next_gw = meta.get("next_gw", 6)
    dates = (meta.get("next_matchweek") or {}).get("dates", "")
    months = ("January February March April May June July August September October November December").split()
    short = dates
    for name in months:
        short = short.replace(name, name[:3])
    short = re.sub(r"\s*\d{4}\s*$", "", short).strip()
    chip = f"Matchweek {next_gw}" + (f" · {short}" if short else "")
    full = f"Matchweek {next_gw}" + (f" · {dates}" if dates else "")
    # No version here: "model v2.1" is its own anchor in the markup and links to the changelog.
    sub = "Premier League 2026–27" + (f" · as of {meta['as_of_date']}" if meta.get("as_of_date") else "")
    for el, text in (("heroKick", full), ("gwKick", f"Matchweek {next_gw} — every fixture, model view"),
                     ("markSub", sub)):
        # NB: "hstat" is deliberately absent — that element's text is a runtime-computed chip
        # (nextGwChip() in render.js) and must not be chased with a regex.
        html = re.sub(r'(id="%s"[^>]*>)[^<]*' % el, lambda mm, t=text: mm.group(1) + t, html, count=1)
    return html


with open(out, encoding="utf-8") as fh:
    _page = fh.read()
_page = _stamp(_page)
with open(out, "w", encoding="utf-8") as fh:
    fh.write(_page)
print("Stamped matchweek %s into the static page." % (summary.get("meta", {}) or {}).get("next_gw", "?"))
