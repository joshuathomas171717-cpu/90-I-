"""site_pages.py — real pages, real URLs, real content in the HTML (P5.3, P5.4, P5.1, P5.2).

`static/index.html` is one file that draws itself with JavaScript. That is the right way to make a
dashboard that works offline and from a file:// path, and the wrong way to make something a search
engine or a link preview can read — the crawler sees a shell, not a table.

This module writes the same content a second time, as plain HTML:

    static/gameweek/mw1../mw38.html   the fixtures, the model's pick, the probabilities as text
    static/club/arsenal.html          one club's strip, its projections, its remaining fixtures
    static/table.html                 the projected final table
    static/model.html                 what the model is and how it was measured
    static/404.html                   a page that tells you where to go
    static/sitemap.xml, robots.txt    discovery
    static/icon.svg, favicon.ico, apple-touch-icon.png, icons/*.png, og/*.png   identity and previews

Each page carries its own `<head>` — title, description, canonical, Open Graph, Twitter card — and
JSON-LD describing what it is. The interactive dashboard stays at `/`; these pages link into it, so a
crawler that follows them finds the whole site and a human who lands on one is one click from the app.

Two constraints worth stating, because they shape all of this:

* **No absolute URLs are invented.** The canonical host comes from `NT90_SITE_URL` (a build-time
  environment variable), and every generated path is relative. That is what lets the same tree serve
  from `https://user.github.io/90-I-/`, from a custom domain, or from `file://` in a zip — which is
  exactly how this project is meant to run.
* **No new dependencies.** `og_image.py` draws the cards, standard library does the rest.

Run it directly (`python3 site_pages.py`) or as part of `run_all.py`.
"""
import csv
import html
import json
import os
import re

import og_image

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
STATIC = os.path.join(BASE, "static")

SITE_NAME = "NINETY+"
SITE_TAGLINE = "Premier League 2026–27 predictions, simulated 5,000 times"
#: Set NT90_SITE_URL to the deployed origin (e.g. https://user.github.io/90-I) and every canonical,
#: og:url and sitemap entry becomes absolute. Unset — the default, and what a zip or a local server
#: gets — the pages are self-relative and still correct, just without absolute canonicals.
SITE_URL = (os.environ.get("NT90_SITE_URL") or "").rstrip("/")

#: Where the source lives. Used by the method page, which invites readers to check the code or report a
#: projection that looks wrong — an invitation that has to point somewhere real.
REPO_URL = os.environ.get("NT90_REPO_URL", "https://github.com/joshuathomas171717-cpu/90-I-")

#: The dashboard's six views, in the order the app presents them. Used for linking back into the app.
VIEWS = ("matchweek", "table", "awards", "duel", "whatif", "model")

PAGE_CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#0B0F1A;color:#ECF1FB;
     font:16px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:#6ee7ff;text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:960px;margin:0 auto;padding:28px 20px 64px}
header.site{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;padding:18px 20px;
        border-bottom:1px solid #232b42;max-width:960px;margin:0 auto}
header.site .brand{font-weight:800;letter-spacing:.14em;font-size:18px}
header.site .tag{color:#8E9BB8;font-size:13px}
nav.crumbs{color:#8E9BB8;font-size:13px;margin:0 0 18px}
nav.crumbs a{color:#8E9BB8}
h1{font-size:30px;line-height:1.15;margin:14px 0 6px;letter-spacing:-.01em}
h2{font-size:19px;margin:30px 0 10px;letter-spacing:.01em}
p.lede{color:#B9C4DC;margin:0 0 22px}
/* the method page's tables and notes (P9.2): same palette as the rest of the generated site */
.mtable{width:100%;border-collapse:collapse;margin:14px 0 18px;font-size:13px}
.mtable caption{text-align:left;color:#97A1B3;font-size:11.5px;padding-bottom:7px}
.mtable th{text-align:left;font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;color:#97A1B3;
  border-bottom:1px solid rgba(255,255,255,.12);padding:6px 10px 7px 0;font-weight:600}
.mtable td{padding:7px 10px 7px 0;border-bottom:1px solid rgba(255,255,255,.05);color:#C9D2E3;vertical-align:top}
.mtable tr.hl td{color:#F3F6FA;font-weight:600}
.mtable .num{text-align:right;font-variant-numeric:tabular-nums}
p.note{color:#97A1B3;font-size:12.5px;border-left:2px solid rgba(45,212,191,.45);padding-left:11px;margin:0 0 18px}
h2{margin-top:26px}
.card{background:#12182A;border:1px solid #232b42;border-radius:14px;padding:18px 18px 8px;margin:0 0 18px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #1d2437;font-size:14px}
th{color:#8E9BB8;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.08em}
td.num,th.num{text-align:right}
tr:last-child td{border-bottom:0}
.chip{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;
      letter-spacing:.06em;text-transform:uppercase}
.chip.ucl{background:rgba(34,211,238,.14);color:#6ee7ff}
.chip.rel{background:rgba(229,75,154,.16);color:#ff8fc4}
.bar{height:7px;border-radius:4px;background:#232b42;overflow:hidden;min-width:60px}
.bar>i{display:block;height:100%;background:#22D3EE}
.bar.rel>i{background:#E54B9A}
.muted{color:#8E9BB8}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}
.kv{background:#0f1626;border:1px solid #1d2437;border-radius:12px;padding:12px 14px}
.kv b{display:block;font-size:22px;letter-spacing:-.01em}
.kv span{color:#8E9BB8;font-size:12px;text-transform:uppercase;letter-spacing:.08em}
footer.site{border-top:1px solid #232b42;margin-top:40px;padding-top:18px;color:#8E9BB8;font-size:13px}
.cta{display:inline-block;background:#22D3EE;color:#062028;font-weight:700;padding:10px 18px;
     border-radius:10px;margin:6px 0 0}
.cta:hover{text-decoration:none;filter:brightness(1.08)}
.fixture{display:flex;justify-content:space-between;gap:14px;align-items:baseline;
         padding:9px 0;border-bottom:1px solid #1d2437}
.fixture:last-child{border-bottom:0}
.fixture .pick{color:#6ee7ff;font-weight:700;font-size:13px}
.fixture .score{color:#8E9BB8;font-size:13px}
ul.plain{padding-left:18px}ul.plain li{margin:4px 0}
"""


def _esc(t):
    return html.escape(str(t if t is not None else ""))


def _rel(depth, target):
    """A path back to the site root from a page `depth` levels down."""
    return ("../" * depth) + target if depth else target


def page(title, description, body, depth=0, canonical=None, og_image_rel=None, jsonld=None):
    """One HTML page: head, identity, body, footer, structured data."""
    canonical_tag = ""
    if canonical:
        canonical_tag = '<link rel="canonical" href="%s">' % _esc(
            (SITE_URL + "/" + canonical.lstrip("/")) if SITE_URL else canonical)
    # og:url has to be absolute to mean anything, so it is only emitted when the build knows its own
    # host (`NT90_SITE_URL`). A canonical is fine as a relative href — every crawler resolves it
    # against the page URL, which is the same thing — but a relative og:url is simply ignored.
    og_url = (SITE_URL + "/" + canonical.lstrip("/")) if (canonical and SITE_URL) else ""
    image_meta = ""
    if og_image_rel:
        image_meta = (
            '\n<meta property="og:image" content="%s">'
            '\n<meta property="og:image:width" content="1200">'
            '\n<meta property="og:image:height" content="630">'
            '\n<meta property="og:image:alt" content="%s">'
            '\n<meta name="twitter:image" content="%s">'
            % (_esc(og_image_rel), _esc(title), _esc(og_image_rel)))
    ld = ""
    if jsonld:
        graph = jsonld if isinstance(jsonld, list) else [jsonld]
        # Always wrapped, even for a single node: the first version emitted a lone node without a
        # @context, which is valid JSON and invalid JSON-LD — a validator rejects it and a consumer
        # has no way to know what vocabulary it is in.
        ld = ('\n<script type="application/ld+json">%s</script>'
              % json.dumps({"@context": "https://schema.org", "@graph": graph},
                           separators=(",", ":"), ensure_ascii=False))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(description)}">
<meta name="theme-color" content="#0B0F1A">
<link rel="icon" href="{_rel(depth, "icon.svg")}" type="image/svg+xml">
<link rel="apple-touch-icon" href="{_rel(depth, "apple-touch-icon.png")}">
<link rel="icon" href="{_rel(depth, "icons/favicon-32.png")}" sizes="32x32" type="image/png">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{_esc(SITE_NAME)}">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(description)}">
{f'<meta property="og:url" content="{_esc(og_url)}">' if og_url else ''}{image_meta}
<meta name="twitter:card" content="{'summary_large_image' if og_image_rel else 'summary'}">
<meta name="twitter:title" content="{_esc(title)}">
<meta name="twitter:description" content="{_esc(description)}">
{canonical_tag}{ld}
<style>{PAGE_CSS}</style>
</head>
<body>
<header class="site">
  <a class="brand" href="{_rel(depth, "index.html")}">NINETY+</a>
  <span class="tag">{_esc(SITE_TAGLINE)}</span>
</header>
<main class="wrap">
{body}
<footer class="site">
  <p><a href="{_rel(depth, "index.html")}">Open the interactive dashboard</a> — six views, a
  What-If simulator and the full model breakdown. Everything on this page is generated from
  <code>data/</code> at build time; nothing here is hand-written.</p>
  <p class="muted">Model output is a probabilistic forecast, not advice. Not affiliated with the
  Premier League or any club. Results data from the official fixture list and
  football-data.org; see <a href="{_rel(depth, "model.html")}">the model page</a> for sources and
  limitations.</p>
</footer>
</main>
</body>
</html>
"""


# ── helpers for the numbers ──────────────────────────────────────────────────────────────────────
def _pct(v):
    return "%.0f%%" % float(v or 0)


def _bar(v, cls=""):
    width = max(0.0, min(100.0, float(v or 0)))
    return '<span class="bar %s" title="%s"><i style="width:%.0f%%"></i></span>' % (
        cls, _pct(v), width)


def _result_rows(fixtures, teams):
    out = []
    for r in fixtures:
        h, a = r["home"], r["away"]
        out.append(
            '<div class="fixture"><span><b>%s</b> <span class="score">%s–%s</span> <b>%s</b></span>'
            '<span class="pick">%s</span></div>'
            % (_esc(teams.get(h, {}).get("short", h)), _esc(r["home_goals"]), _esc(r["away_goals"]),
               _esc(teams.get(a, {}).get("short", a)),
               {"H": "home win", "A": "away win", "D": "draw"}.get(r.get("outcome", ""), "")))
    return "\n".join(out)


def _fixture_rows(fixtures, teams):
    out = []
    for f in fixtures:
        h, a = f["home"], f["away"]
        ph, pd, pa = f.get("prob_home", 0), f.get("prob_draw", 0), f.get("prob_away", 0)
        pick = h if ph > max(pd, pa) else (a if pa > pd else "Draw")
        out.append(
            '<div class="fixture"><span><b>%s</b> <span class="score">v</span> <b>%s</b> '
            '<span class="score">— %s / %s / %s</span></span>'
            '<span class="pick">%s</span></div>'
            % (_esc(teams.get(h, {}).get("short", h)), _esc(teams.get(a, {}).get("short", a)),
               _pct(ph), _pct(pd), _pct(pa),
               _esc(teams.get(pick, {}).get("short", pick))))
    return "\n".join(out)


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


# ════════════════════════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════════════════════════
#  P9.2 · P9.3 — the pages that explain the project to a stranger
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
def _method_page(summary, backtest):
    """The method page (P9.2).

    Written for a reader who arrived from a search result, has no idea who made this, and wants to know
    whether to believe it. So it leads with what the model is, states the error bars in the model's own
    measured numbers, names the things it cannot see, and says how to report a result it got wrong —
    which is the part most model write-ups leave out, and the part that makes the rest credible.
    """
    m = (backtest or {}).get("model", {})
    skill = (backtest or {}).get("skill_vs_prior_table", {})
    table = (backtest or {}).get("table_level", {})
    bases = (backtest or {}).get("baselines", {}) or {}
    base_rows = "".join(
        "<tr><td>%s</td><td class=\"num\">%.1f%%</td><td class=\"num\">%.4f</td><td class=\"num\">%.4f</td></tr>"
        % (_esc(name.split(" (")[0]), v.get("accuracy", 0), v.get("rps", 0), v.get("log_loss", 0))
        for name, v in sorted(bases.items(), key=lambda kv: kv[1].get("rps", 9)))

    body = """
<h1>How NINETY+ predicts the Premier League</h1>
<p class="lede">NINETY+ predicts the rest of the 2026-27 Premier League season: every remaining fixture,
the final table, and the individual awards. This page says how, and how well — including where it fails.</p>

<h2>What the model actually is</h2>
<p>Two layers. First a <b>Dixon-Coles</b> scoreline model: for each fixture it estimates the expected
goals for each side, from attacking and defensive strength, home advantage and the fixture list, with the
1997 Dixon-Coles correction for the fact that low-scoring games (0-0, 1-0, 1-1) happen more often than an
independent Poisson process predicts. Gradient-boosted regressors refine those expectations from form,
opponent strength and rest. The corrected scoreline grid then gives the 1X2 probabilities.</p>
<p>Second, a <b>Monte Carlo</b> layer: those per-fixture probabilities are played out %s times, which is
what turns "Arsenal are 68%% to win on Saturday" into "Arsenal finish with 82 points in a third of
seasons". Every number on the dashboard that says "probability of finishing" is a count of simulated
seasons, not an opinion.</p>

<h2>How well it does, measured honestly</h2>
<p>The only test that means anything is a season the model has not seen. The model was rebuilt using only
2024-25 data and asked to predict <b>all 380 matches of 2025-26</b>, one at a time, with no knowledge of
how they turned out.</p>
<table class="mtable">
  <caption>Out-of-sample results, 2025-26 season</caption>
  <thead><tr><th scope="col">Forecaster</th><th scope="col">Matches called</th><th scope="col">RPS (lower is better)</th><th scope="col">Log-loss</th></tr></thead>
  <tbody>
    <tr class="hl"><td>NINETY+</td><td class="num">%.1f%%</td><td class="num">%.4f</td><td class="num">%.4f</td></tr>
    %s
  </tbody>
</table>
<p class="note">RPS (ranked probability score) is the right metric for football, because a 1X2 forecast is
an ordered set of three outcomes and RPS penalises being confidently wrong about the shape of the
match, not just the winner. Against the prior-season table — the obvious baseline of "pick whoever
finished higher" — the model improves RPS by <b>%.1f%%</b>. Over a single season that is a real but
modest edge: it is a better-than-average forecaster, not a clairvoyant.</p>
<p>At the level of the whole table the picture is messier, and worth stating plainly: rank correlation
with the actual final table was <b>%.2f</b>, average points error <b>±%.1f</b>, and the projected
champion was <b>%s</b> rather than the actual <b>%s</b>. Predicting a 38-game table is harder than
predicting matches, because small per-match errors compound.</p>

<h2>What it cannot know</h2>
<ul>
  <li><b>Team news.</b> Injuries, suspensions and illness are invisible to it until they have already
  affected results. A side missing its striker is not priced in.</li>
  <li><b>Transfers and managerial change.</b> The model learns each squad's strength from matches
  played. A January signing or a new manager is a different team from the one it has data on.</li>
  <li><b>Motivation and context.</b> A dead rubber in May, a relegation six-pointer, a European tie on
  the Thursday: none of it is in the data.</li>
  <li><b>Refereeing and weather.</b> No model of a red card in the eighth minute or a waterlogged
  pitch.</li>
  <li><b>Everything after the last update.</b> The dataset is a snapshot. The header states its date,
  and says so out loud when it is overdue.</li>
</ul>

<h2>Where the numbers come from</h2>
<table class="mtable">
  <caption>Data sources</caption>
  <thead><tr><th scope="col">What</th><th scope="col">Source</th><th scope="col">Notes</th></tr></thead>
  <tbody>
    <tr><td>2026-27 fixture calendar</td><td>Official Premier League fixture release</td>
      <td>All 380 fixtures, kick-off dates and times</td></tr>
    <tr><td>2025-26 season (training)</td><td>Published match results and tables</td>
      <td>Every result, plus goals for and against per club</td></tr>
    <tr><td>2026-27 results so far</td><td>football-data.org API (free tier)</td>
      <td>Refreshed weekly by the pipeline; the free tier is non-commercial use</td></tr>
    <tr><td>Squads and awards</td><td>Publicly published squad and scorer records</td>
      <td>Player-level projections need minutes, positions and current totals</td></tr>
  </tbody>
</table>
<p class="note">No licensed expected-goals feed is used. xG is <i>modelled</i> — derived from the shot
and result data the model already has — rather than bought. That is a deliberate trade: an unlicensed
modelled xG is free and reproducible, and it is weaker than the real thing, which is one reason the
accuracy above is 46%% rather than 55%%.</p>

<h2>How to check the code, or report a bad result</h2>
<p>The whole pipeline is open: the model, the backtest, the data build and this site. If a projection
looks wrong, the useful report is the club, the fixture and the number you expected —
<a href="{repo}/issues">open an issue</a> and it will get looked at. Corrections to the data are the
most valuable kind, because every downstream number inherits them.</p>
<p class="note">Predictions here are analysis for interest. They are not betting advice, and nothing on
this site is a guarantee about a football match. If you are going to have a bet, do it somewhere that
tells you the odds are against you — because they are.</p>
""".replace("%%", "%%") % (
        "{:,}".format(summary["meta"].get("n_simulations", 5000)),
        m.get("accuracy", 0), m.get("rps", 0), m.get("log_loss", 0), base_rows,
        skill.get("rps", 0), table.get("spearman_rank_correlation", 0), table.get("points_mae", 0),
        _esc(table.get("projected_champion", "—")), _esc(table.get("actual_champion", "—")),
    )
    body = body.replace("{repo}", REPO_URL or "https://github.com")
    # The literal %% escapes above are for the format string; the prose wants single percent signs.
    body = body.replace("%%", "%")
    return page("Method: how the NINETY+ Premier League model works, and how well it scores",
                "The Dixon-Coles and Monte Carlo model behind NINETY+, its measured accuracy over a "
                "full out-of-sample season, its data sources and its known blind spots.",
                body, canonical="method.html",
                jsonld={"@type": "Article", "headline": "How the NINETY+ model works",
                        "about": "Premier League forecasting methodology"})


def _calendar_page(summary):
    """P8.3: the page that makes the feeds findable.

    A calendar feed nobody can discover is not a feature. This lists every subscription with a
    subscribe link, the raw URL to paste into a calendar app by hand, and — the part that matters —
    an honest note that the Premier League's own kick-off times are not in this dataset, so the feed
    puts one all-day entry against each matchweek window instead of inventing ten Saturday 15:00s.
    """
    import feeds as _feeds

    teams = {t["code"]: t for t in summary["table_projections"]}
    fixtures = _feeds.load_fixtures()
    league = _feeds.build(summary, fixtures)
    events = league.count("BEGIN:VEVENT")
    codes = sorted({f["home"] for f in fixtures} | {f["away"] for f in fixtures},
                   key=lambda c: teams.get(c, {}).get("name", c))

    def sub_row(code):
        team = teams.get(code, {})
        name = team.get("name", code)
        short = team.get("short", name)
        color = team.get("primary_color", "#2dd4bf")
        slug = _feeds.club_slug(code)
        n = _feeds.build(summary, fixtures, club=code).count("BEGIN:VEVENT")
        return """
<a class="cal" href="/calendar/%s.ics" style="--c:%s">
  <span class="dot" style="background:%s"></span>
  <span class="nm">%s</span>
  <span class="ct">%d matchweeks</span>
  <span class="go">subscribe →</span>
</a>""" % (slug, color, color, _esc(name), n)

    # NB: this body is %-formatted at the end, so a literal percent sign has to be written %% —
    # `border-radius:50%` in the CSS below is what raised "unsupported format character ';'".
    body = """
<style>
  .cal{display:flex;align-items:center;gap:11px;padding:11px 13px;border:1px solid #202a3d;
       border-radius:12px;background:#111726;color:inherit;transition:border-color .15s,transform .15s}
  .cal:hover{text-decoration:none;border-color:var(--c,#2dd4bf);transform:translateY(-1px)}
  .cal .dot{width:9px;height:9px;border-radius:999px;flex:0 0 auto}
  .cal .nm{font-weight:600}
  .cal .ct{color:#8b98b3;font-size:12.5px;margin-left:auto;white-space:nowrap}
  .cal .go{color:#6ee7ff;font-size:12.5px;white-space:nowrap}
  .cal .dot,.cal .go{flex:0 0 auto}
  a.big{display:block;padding:18px;background:linear-gradient(135deg,#122033,#0e1626);
        border:1px solid #24405c;border-radius:16px;color:inherit;margin:20px 0 26px}
  a.big:hover{text-decoration:none;border-color:#3d6f96;transform:translateY(-1px)}
  a.big .t{display:block;font-size:19px;font-weight:700}
  a.big .s{display:block;color:#9fb0cc;font-size:13.5px;margin-top:3px}
  a.big .go{display:inline-block;margin-top:11px;color:#6ee7ff;font-weight:600}
  .note{border-left:3px solid #fbbf24;background:#1b1607;padding:13px 15px;border-radius:0 10px 10px 0;
        font-size:14px;color:#e8dfc6;margin:18px 0}
  h2{margin:30px 0 12px;font-size:18px}
  pre{background:#0e1421;border:1px solid #202a3d;border-radius:10px;padding:11px 13px;overflow-x:auto;
      font-size:13px;color:#c7d3e8}
</style>
<h1 style="margin:0 0 6px">Fixtures in your calendar</h1>
<p class="lede">Subscribe once and every remaining matchweek appears in whatever calendar app you
already use — with the model's probabilities written into each entry. No account, no email, no
tracking; the URL below is the whole subscription.</p>

<div class="note">
  <b>Read this before you subscribe.</b> The Premier League publishes each matchweek as a window
  — “10–12 October 2026” — and confirms exact kick-off times only when television picks its slots.
  This project has the windows, not the slots, so each entry is an <b>all-day event covering the
  window</b> rather than a guess at the exact time. A calendar that confidently says Saturday 15:00
  for ten fixtures would be wrong for the two or three that move to Sunday. Entries are updated in
  place — each one has a stable identity — so re-subscribing refines them instead of duplicating them.
</div>

<a class="big" href="/calendar/league.ics">
  <span class="t">The whole league</span>
  <span class="s">%d matchweeks · every remaining fixture, %d still to play</span>
  <span class="go">Subscribe →</span>
</a>

<h2>Or follow one club</h2>
<div class="grid">%s</div>

<h2>Adding it by hand</h2>
<p class="small muted">Google Calendar, Outlook, Fantastical and Apple Calendar all accept a
subscription URL rather than a downloaded file. Paste this one:</p>
<pre>%s</pre>
<p class="small muted">The path is what a calendar app refetches when it refreshes. How often that
happens is up to your app rather than us — Apple Calendar is typically daily, and Google can be a
day slower.</p>

<h2>What is in each entry</h2>
<p class="small muted">The fixtures in that matchweek with the model's home/draw/away probabilities
and its single most likely scoreline — for one club only, in a club feed — plus a link back to the
matchweek page. Entries are marked <b>free</b> rather than busy, so subscribing will not block
anything in your calendar.</p>
""" % (events, len(fixtures), "".join(sub_row(c) for c in codes),
       (SITE_URL + "/calendar/league.ics") if SITE_URL else
       "/calendar/league.ics  (relative — no NT90_SITE_URL at build time, so prepend your own origin)")

    return page("Premier League 2026–27 fixtures in your calendar — NINETY+",
                "Subscribe to the remaining 2026–27 Premier League fixtures as a calendar feed — the "
                "whole league or a single club, with the model's probabilities in every entry.",
                body, jsonld={"@type": "WebPage", "name": "Calendar feeds",
                              "about": "Premier League fixture calendar subscriptions"})


def _privacy_page():
    """The privacy note (P9.3). Written to be true of the software as it stands: no accounts, no
    cookies, no third-party scripts. If analytics are ever added, this page has to change in the same
    commit — a privacy page that describes a different site from the one being served is worse than
    none, because it is a specific claim that happens to be false.
    """
    body = """
<h1>Privacy</h1>
<p class="lede">The short version: this site sets no cookies, runs no third-party scripts, has no
accounts and no sign-in, and does not try to identify you.</p>

<h2>What is stored on your device</h2>
<p>The dashboard runs entirely in the page you loaded — the data is embedded in the HTML and the
model's offline engine runs in your browser. Nothing about you is sent anywhere to make it work.</p>
<p>Three things you do are remembered <b>in this browser</b>, using local storage, so that the page
is still yours when you come back: the clubs you follow, the What-If scenarios you save, and the view
you were last looking at. That is all of it — no cookie is set, nothing is sent to the server, and
there is no identifier that follows you between sites. Your What-If settings also live in the URL you
share if you use the share button, which is a link rather than storage.</p>
<p>You can clear all three with <b>Forget everything</b> in the What-If panel, or erase them the
usual way by clearing site data. If your browser blocks local storage — private windows and some
embedded frames do — the dashboard says so and keeps your session in memory instead: everything still
works, but it will not survive a reload.</p>

<h2>What the server sees</h2>
<p>Any web server sees the requests made to it: the page you asked for, roughly when, and the IP address
making the request. This one keeps a minimal access log for the same reason every server does — to spot
breakage and abuse — and does not build profiles, sell data or share logs with anyone. The API endpoints
that run simulations see only the simulation settings you send them.</p>

<h2>Analytics</h2>
<p>None are used on this deployment. No Google Analytics, no pixels, no advertising identifiers. If
cookieless, aggregate counting is ever switched on (to answer "is anyone reading this?"), it will be a
privacy-respecting counter that stores no personal data, and this page will say so before it happens.</p>

<h2>Third parties</h2>
<p>The fonts are embedded in the page rather than loaded from a font service, so viewing this site sends
no request to Google Fonts or anyone else. The only outbound links are to the project's own source
repository and to the data provider credited in the footer; following them takes you to their sites,
under their privacy policies.</p>

<h2>Children, and legal</h2>
<p>Nothing here is directed at children, and nothing here is betting advice. If a deployment ever
adds analytics, accounts or email, this page must be updated in the same change — and in that order,
not afterwards.</p>

<h2>Contact</h2>
<p>Questions, corrections or a request to remove something: open an issue on the repository linked in the
footer. If you are a rights holder with a concern about how club names, colours or publicly published
statistics are used here, that link is the fastest route to a human.</p>
"""
    return page("Privacy — NINETY+", "No cookies, no trackers, no accounts. What NINETY+ does and does "
                "not store, in plain language.", body, canonical="privacy.html")


def build(summary=None):
    """Write every generated page, image and feed. Returns a list of (path, kind) that it wrote."""
    summary = summary or json.load(open(os.path.join(DATA, "predictions_2026_27_summary.json"),
                                      encoding="utf-8"))
    teams = {t["code"]: t for t in summary["table_projections"]}
    meta = summary["meta"]
    written = []

    def w(path, content, kind="page", binary=False):
        full = os.path.join(STATIC, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        if binary:
            with open(full, "wb") as fh:
                fh.write(content)
        else:
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(content)
        written.append((os.path.relpath(full, BASE), kind))

    # ── the site card, the clubs and the icons (P5.1, P6.3) ──────────────────────────────────────
    champion = max(summary["table_projections"], key=lambda t: t["title_prob"])
    runner = sorted(summary["table_projections"], key=lambda t: -t["title_prob"])[1]
    w("og/site.png", open(og_image.site_card(
        champion, "%s · %s projected · %s title" % (SITE_TAGLINE, champion["name"],
                                                    _pct(champion["title_prob"])),
        os.path.join(STATIC, "og", "site.png")), "rb").read(), "image", binary=True)
    w("og/club-" + champion["code"].lower() + ".png", open(og_image.club_card(champion, os.path.join(
        STATIC, "og", "club-%s.png" % champion["code"].lower())), "rb").read(), "image", binary=True)
    w("og/duel.png", open(og_image.duel_card(champion, runner, os.path.join(
        STATIC, "og", "duel.png")), "rb").read(), "image", binary=True)
    w("og/table.png", open(og_image.table_card(summary["table_projections"], os.path.join(
        STATIC, "og", "table.png")), "rb").read(), "image", binary=True)
    w("icon.svg", og_image.FAVICON_SVG, "image")
    for size in (32, 180, 192, 512):
        name = "apple-touch-icon.png" if size == 180 else "icons/%s.png" % (
            "favicon-32" if size == 32 else "icon-%d" % size)
        blob = open(og_image.icon_png(size, os.path.join(STATIC, name)), "rb").read()
        # The legacy probe path: /favicon.ico. Nothing in the page links it — browsers decide to ask
        # for it on their own, so it is invisible to every check that reads the HTML. Written from the
        # 32 px icon rather than re-drawn, so the tab icon and the fallback cannot drift apart.
        if size == 32:
            with open(os.path.join(STATIC, "favicon.ico"), "wb") as fh:
                fh.write(og_image.ico_bytes(os.path.join(STATIC, name), 32))
        w(name, blob, "image", binary=True)

    # ── one page per gameweek: results once played, projections while to come (P5.3, P5.4) ───────
    projected, played = _projected_fixtures(), _played_fixtures()
    # Every remaining fixture, indexed by club: a club page that only knew about the next two
    # gameweeks would say "Remaining fixtures (2)" in October, which is simply wrong.
    projected_club_index = {}
    for rows in projected.values():
        for r in rows:
            for side in ("home", "away"):
                projected_club_index.setdefault(r[side], []).append(r)
    for rows in projected_club_index.values():
        rows.sort(key=lambda r: (r["gw"], r["home"]))
    gw_pages = []
    for gw in range(1, 39):
        is_played = gw in played and bool(played[gw])
        fixtures = played[gw] if is_played else projected.get(gw, [])
        if not fixtures:
            continue
        dates = _gw_dates(projected, played, gw)
        path = "gameweek/mw%d.html" % gw
        card_name = "og/mw%d.png" % gw

        if is_played:
            rows = [{"home": f["home"], "away": f["away"], "score": "%s-%s" % (f["home_goals"], f["away_goals"])}
                    for f in fixtures]
            card = og_image.gameweek_card(gw, dates, [], os.path.join(STATIC, card_name), mode="result")
            # the card needs the rows, so draw it through the same function with them attached
            for f, r in zip(fixtures, rows):
                f["result"] = r["score"]
            card = og_image.gameweek_card(gw, _played_dates(summary, gw), fixtures,
                                          os.path.join(STATIC, card_name), mode="result")
            w(card_name, open(card, "rb").read(), "image", binary=True)
            goals = sum(int(f["home_goals"]) + int(f["away_goals"]) for f in fixtures)
            body = f"""
<nav class="crumbs"><a href="../index.html">Dashboard</a> › Matchweek {gw}</nav>
<h1>Premier League matchweek {gw} results</h1>
<p class="lede">Played. {len(fixtures)} fixtures, {goals} goals.</p>
<div class="card">
{_result_rows(fixtures, teams)}
</div>
<h2>After this week</h2>
<div class="grid">
  <div class="kv"><span>Projected champion</span><b>{_esc(champion['short'])}</b>{_pct(champion['title_prob'])} title</div>
  <div class="kv"><span>Still to play</span><b>{summary['ml_metrics']['remaining_fixtures']}</b>fixtures this season</div>
</div>
<p style="margin-top:18px"><a class="cta" href="../index.html">See what happens next</a></p>
"""
        else:
            card = og_image.gameweek_card(gw, dates, [dict(f, pick=_pick(f)) for f in fixtures[:7]],
                                          os.path.join(STATIC, card_name))
            w(card_name, open(card, "rb").read(), "image", binary=True)
            body = f"""
<nav class="crumbs"><a href="../index.html">Dashboard</a> › Matchweek {gw}</nav>
<h1>Premier League matchweek {gw} predictions</h1>
<p class="lede">{_esc(dates or "Dates to be confirmed")}. Home/draw/away probabilities come from
5,000 simulated seasons; the pick is the highest of the three.</p>
<div class="card">
{_fixture_rows(fixtures, teams)}
</div>
<h2>Where this leaves the league</h2>
<div class="grid">
  <div class="kv"><span>Projected champion</span><b>{_esc(champion['short'])}</b>{_pct(champion['title_prob'])} title</div>
  <div class="kv"><span>Projected points</span><b>{champion['proj_pts']:.1f}</b>for {_esc(champion['short'])}</div>
  <div class="kv"><span>Remaining fixtures</span><b>{summary['ml_metrics']['remaining_fixtures']}</b>after matchweek {meta['last_completed_gw']}</div>
  <div class="kv"><span>Model accuracy</span><b>{summary['ml_metrics']['rps']:.4f}</b>RPS, 2025-26 replay</div>
</div>
<p style="margin-top:18px"><a class="cta" href="../index.html">Run a What-If scenario on these fixtures</a></p>
"""
            w(card_name, open(card, "rb").read(), "image", binary=True)

        jsonld = [{
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Dashboard", "item": _abs("index.html")},
                {"@type": "ListItem", "position": 2, "name": "Matchweek %d" % gw, "item": _abs(path)},
            ],
        }, {
            "@type": "ItemList",
            "name": "Premier League matchweek %d fixtures" % gw,
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1,
                 "item": {"@type": "SportsEvent",
                          "name": "%s vs %s" % (teams.get(f["home"], {}).get("name", f["home"]),
                                                teams.get(f["away"], {}).get("name", f["away"])),
                          "eventStatus": "https://schema.org/EventScheduled" if not is_played
                                         else "https://schema.org/EventScheduled",
                          "competitor": [
                              {"@type": "SportsTeam", "name": teams.get(f["home"], {}).get("name", f["home"])},
                              {"@type": "SportsTeam", "name": teams.get(f["away"], {}).get("name", f["away"])}],
                          "location": {"@type": "Place", "name": teams.get(f["home"], {}).get("stadium", "")},
                          "description": (
                              "Result: %s-%s" % (f["home_goals"], f["away_goals"]) if is_played else
                              "Model probabilities — home %s, draw %s, away %s" % (
                                  _pct(f.get("prob_home")), _pct(f.get("prob_draw")), _pct(f.get("prob_away"))))},
                 } for i, f in enumerate(fixtures)],
        }]
        title = ("Premier League matchweek %d results — NINETY+" % gw if is_played else
                 "Premier League matchweek %d predictions — NINETY+" % gw)
        desc = ("Every matchweek %d result: %d fixtures, %d goals." % (gw, len(fixtures), goals)
                if is_played else
                "Model predictions for all %d matchweek %d fixtures: win/draw/loss probabilities "
                "and the projected table impact." % (len(fixtures), gw))
        w(path, page(title, desc, body, depth=1, canonical=path,
                     og_image_rel=_rel(1, card_name), jsonld=jsonld))
        gw_pages.append((gw, dates, path))

    # ── one page per club ────────────────────────────────────────────────────────────────────────
    club_pages = []
    for t in summary["table_projections"]:
        code = t["code"]
        path = "club/%s.html" % _slug(t["name"])
        card_name = "og/club-%s.png" % code.lower()
        if not os.path.exists(os.path.join(STATIC, card_name)):
            blob = open(og_image.club_card(t, os.path.join(STATIC, card_name)), "rb").read()
            w(card_name, blob, "image", binary=True)
        remaining = _fixtures_for_club(projected_club_index, t)
        body = f"""
<nav class="crumbs"><a href="../index.html">Dashboard</a> › {_esc(t['name'])}</nav>
<h1>{_esc(t['name'])} — 2026–27 projection</h1>
<p class="lede">{_esc(t['stadium'])} · {_esc(t['manager'])} · currently
{_ordinal(t['current_pos'])} on {t['curr_pts']} points after {t['curr_p']} games.</p>
<div class="card"><div class="grid">
  <div class="kv"><span>Projected points</span><b>{t['proj_pts']:.1f}</b>final total</div>
  <div class="kv"><span>Title</span><b>{_pct(t['title_prob'])}</b>{_bar(t['title_prob'])}</div>
  <div class="kv"><span>Top four</span><b>{_pct(t['top4_prob'])}</b>{_bar(t['top4_prob'])}</div>
  <div class="kv"><span>Relegation</span><b>{_pct(t['relegation_prob'])}</b>{_bar(t['relegation_prob'], 'rel')}</div>
</div></div>
<h2>Projected goals and defence</h2>
<div class="card"><table>
<tr><th>Metric</th><th class="num">Projected</th></tr>
<tr><td>Goals for</td><td class="num">{t.get('proj_gf', 0):.1f}</td></tr>
<tr><td>Goals against</td><td class="num">{t.get('proj_ga', 0):.1f}</td></tr>
<tr><td>Goal difference</td><td class="num">{t.get('proj_gd', 0):+.1f}</td></tr>
<tr><td>Win / draw / loss</td><td class="num">{t.get('proj_w', 0):.1f} / {t.get('proj_d', 0):.1f} / {t.get('proj_l', 0):.1f}</td></tr>
</table></div>
<h2>Remaining fixtures ({len(remaining)})</h2>
<div class="card">{_fixture_rows(remaining[:10], teams) or '<p class="muted">None left.</p>'}</div>
{"" if len(remaining) <= 10 else '<p class="muted">Showing the next 10; every fixture is listed on its matchweek page.</p>'}
<p style="margin-top:18px"><a class="cta" href="../index.html">Open {_esc(t['short'])} in the dashboard</a></p>
"""
        jsonld = [{
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Dashboard", "item": _abs("index.html")},
                {"@type": "ListItem", "position": 2, "name": t["name"], "item": _abs(path)}],
        }, {
            "@type": "SportsTeam",
            "name": t["name"],
            "sport": "Association football",
            "location": {"@type": "Place", "name": t["stadium"]},
        }]
        w(path, page("%s 2026–27 projection — NINETY+" % t["name"],
                     "%s are projected %.1f points with a %s chance of the title. Remaining fixtures "
                     "and probabilities from 5,000 simulated seasons." % (t["name"], t["proj_pts"],
                                                                          _pct(t["title_prob"])),
                     body, depth=1, canonical=path, og_image_rel=_rel(1, card_name), jsonld=jsonld))
        club_pages.append((t, path))

    # ── the projected table, on its own URL ──────────────────────────────────────────────────────
    rows = []
    for i, t in enumerate(summary["table_projections"]):
        chip = ('<span class="chip ucl">UCL</span>' if i < 4 else
                ('<span class="chip rel">REL</span>' if i >= 17 else ""))
        rows.append(
            "<tr><td class='num'>%d</td><td><b>%s</b></td><td>%s</td><td class='num'>%.1f</td>"
            "<td class='num'>%s</td><td class='num'>%s</td><td>%s</td></tr>"
            % (i + 1, _esc(t["code"]), _esc(t["name"]), t["proj_pts"], _pct(t["title_prob"]),
               _pct(t["relegation_prob"]), chip))
    body = f"""
<nav class="crumbs"><a href="index.html">Dashboard</a> › Table</nav>
<h1>Projected final table — Premier League 2026–27</h1>
<p class="lede">Every remaining fixture simulated 5,000 times. As of {_esc(meta['as_of_date'])},
{summary['ml_metrics']['remaining_fixtures']} fixtures still to play.</p>
<div class="card"><table>
<tr><th class="num">#</th><th>Club</th><th>Name</th><th class="num">Pts</th>
<th class="num">Title</th><th class="num">Relegation</th><th></th></tr>
{''.join(rows)}
</table></div>
<p style="margin-top:18px"><a class="cta" href="index.html">Open the dashboard</a></p>
"""
    # P9.2 / P9.3 — the pages a stranger needs. Regenerated with the numbers, not written once and left
    # to rot: the method page quotes the backtest that the same build just produced.
    _backtest = {}
    _bt_path = os.path.join(DATA, "backtest_2025_26.json")
    if os.path.exists(_bt_path):
        with open(_bt_path, encoding="utf-8") as fh:
            _backtest = json.load(fh)
    w("method.html", _method_page(summary, _backtest))
    w("privacy.html", _privacy_page())
    w("calendar.html", _calendar_page(summary))

    w("table.html", page("Projected Premier League table 2026–27 — NINETY+",
                         "The full projected final table: points, title probability and relegation "
                         "risk for all 20 clubs, from 5,000 simulated seasons.",
                         body, depth=0, canonical="table.html", og_image_rel="og/table.png",
                         jsonld={"@type": "Dataset", "name": "NINETY+ projected table 2026-27",
                                 "description": "Projected final Premier League table, 5000 simulated seasons",
                                 "creator": {"@type": "Organization", "name": SITE_NAME},
                                 "variableMeasured": ["Points", "Title probability", "Relegation probability"]}))

    # ── the model page: what this is, how it was measured, what it cannot do ─────────────────────
    ml = summary["ml_metrics"]
    body = f"""
<nav class="crumbs"><a href="index.html">Dashboard</a> › Model</nav>
<h1>How the model works, and how well it does</h1>
<p class="lede">A short, plain account of what produced every number on this site — including the
parts that are not flattering.</p>
<div class="card"><div class="grid">
  <div class="kv"><span>Matches trained on</span><b>{ml['matches_trained']}</b>{ml['matches_2025_26']} from 2025-26 + {ml['matches_2026_27_live']} live</div>
  <div class="kv"><span>Ranked probability score</span><b>{ml['rps']:.4f}</b>lower is better, 0.25 = coin-flip</div>
  <div class="kv"><span>Brier score</span><b>{ml['brier_score']:.4f}</b>3-outcome, 0.667 = always guessing</div>
  <div class="kv"><span>Simulations per refresh</span><b>5,000</b>full-season Monte Carlo</div>
</div></div>
<h2>What it does</h2>
<ul class="plain">
  <li>Estimates each club's attack and defence from goals, shots and shot quality, then projects a
      scoreline for every remaining fixture with a bivariate-Poisson model (Dixon-Coles correction
      for the low-score cells).</li>
  <li>Simulates the rest of the season 5,000 times, carrying the live table forward, to get title,
      top-four and relegation probabilities rather than a single guess.</li>
  <li>Scores players separately — minutes, shot volume, conversion, penalties and assists — to project
      the Golden Boot, the playmaker race and the Golden Glove.</li>
  <li>Replays the whole 2025-26 season blind (only data available before each kickoff) to produce the
      scores above.</li>
</ul>
<h2>What it does not do</h2>
<ul class="plain">
  <li>It does not know about injuries, suspensions or a manager being sacked — unless you put them in
      the What-If simulator yourself.</li>
  <li>The free data tier publishes goals, not expected goals, for the live season; the xG columns are
      derived from shot data and carry that uncertainty.</li>
  <li>Football is low-scoring and high-variance. A 40% favourite loses more often than a 40% favourite
      sounds like it should.</li>
</ul>
<p class="muted">Forecasts, not advice. Not affiliated with the Premier League or any club. Result
data from the official fixture list and football-data.org.</p>
<p style="margin-top:18px"><a class="cta" href="index.html">Back to the dashboard</a></p>
"""
    w("model.html", page("How the NINETY+ model works — method, accuracy and limits",
                         "The method behind the projections, the measured accuracy on a blind "
                         "2025-26 replay, and an honest list of what the model cannot know.",
                         body, depth=0, canonical="model.html",
                         jsonld={"@type": "WebPage", "name": "The NINETY+ model",
                                 "about": {"@type": "Dataset", "name": "Premier League 2026-27 predictions"}}))

    # ── a 404 that helps instead of apologising ──────────────────────────────────────────────────
    body = """
<nav class="crumbs">Not found</nav>
<h1>That page isn't here</h1>
<p class="lede">Every prediction on this site lives at one of these:</p>
<div class="card"><table>
<tr><th>Page</th><th>What it shows</th></tr>
<tr><td><a href="index.html">Dashboard</a></td><td>All six views, the What-If simulator, the model</td></tr>
<tr><td><a href="table.html">Projected table</a></td><td>Where all 20 clubs finish, 5,000 seasons</td></tr>
<tr><td><a href="club/arsenal.html">Club pages</a></td><td><code>/club/&#8203;&lt;name&gt;.html</code> — projection, fixtures, probabilities</td></tr>
<tr><td><a href="gameweek/mw6.html">Gameweek pages</a></td><td><code>/gameweek/&#8203;mw&lt;n&gt;.html</code> — every fixture and pick</td></tr>
<tr><td><a href="model.html">Model</a></td><td>Method, measured accuracy, limitations</td></tr>
</table></div>
"""
    w("404.html", page("Not found — NINETY+", "That page isn't here. These are.", body))

    # ── discovery: sitemap and robots ────────────────────────────────────────────────────────────
    urls = [("index.html", "1.0"), ("table.html", "0.9"), ("model.html", "0.6"),
            ("method.html", "0.8"), ("calendar.html", "0.7"), ("privacy.html", "0.2")]
    urls += [(p, "0.7") for _gw, _d, p in gw_pages]
    urls += [(p, "0.6") for _t, p in club_pages]
    lastmod = _lastmod(meta.get("as_of_date", ""))
    entries = []
    for path, prio in urls:
        loc = (SITE_URL + "/" + path) if SITE_URL else path
        entries.append('  <url><loc>%s</loc><lastmod>%s</lastmod><priority>%s</priority></url>'
                       % (_esc(loc), lastmod, prio))
    w("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n'
                     '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n%s\n</urlset>\n'
                     % "\n".join(entries), "feed")
    w("robots.txt", "User-agent: *\n"
                    "Allow: /\n"
                    "Disallow: /api/\n"
                    "Disallow: /healthz\n"
                    "Disallow: /readyz\n"
                    "%s"
                    % (("Sitemap: %s/sitemap.xml\n" % SITE_URL) if SITE_URL else
                       "# Set NT90_SITE_URL at build time to emit an absolute Sitemap: line.\n"), "feed")

    return written


def _pick(f):
    return f["home"] if f.get("prob_home", 0) > max(f.get("prob_draw", 0), f.get("prob_away", 0)) else (
        f["away"] if f.get("prob_away", 0) > f.get("prob_draw", 0) else "Draw")


def _played_dates(summary, gw):
    """A label for a completed gameweek. The played CSV has no dates, so the calendar is used if it
    knows the week and a plain label is the honest fallback."""
    cal = summary.get("_fixture_dates_by_gw") or {}
    return cal.get(str(gw)) or ("Matchweek %d" % gw)


def _abs(path):
    return (SITE_URL + "/" + path) if SITE_URL else path


def _ordinal(n):
    n = int(n)
    return "%d%s" % (n, "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def _lastmod(as_of):
    """Turn '2026-10-03 (Matchweek 5 Complete)' into an ISO date."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", as_of or "")
    return m.group(1) if m else "2026-08-21"


def _projected_fixtures():
    """Every remaining fixture with its projection — data/projected_fixtures_2026_27.csv.

    Written by ml_engine.py. The summary JSON deliberately carries only the next two gameweeks (a
    visitor downloads that file on every page load), so the 38 crawlable gameweek pages are built
    from this instead.
    """
    path = os.path.join(DATA, "projected_fixtures_2026_27.csv")
    if not os.path.exists(path):
        return {}
    by_gw = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            row["gw"] = int(row["gw"])
            for k in ("lambda_home", "lambda_away", "prob_home", "prob_draw", "prob_away",
                      "clean_sheet_home", "clean_sheet_away", "btts_prob", "over_2_5_prob",
                      "top_score_prob"):
                try:
                    row[k] = float(row[k])
                except (TypeError, ValueError):
                    row[k] = None
            by_gw.setdefault(row["gw"], []).append(row)
    for rows in by_gw.values():
        rows.sort(key=lambda r: (r["dates"], r["home"]))
    return by_gw


def _played_fixtures():
    """Gameweeks already completed, with results — data/matches_2026_27_played.csv."""
    path = os.path.join(DATA, "matches_2026_27_played.csv")
    if not os.path.exists(path):
        return {}
    by_gw = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            row["gw"] = int(row["gw"])
            by_gw.setdefault(row["gw"], []).append(row)
    for rows in by_gw.values():
        rows.sort(key=lambda r: (r["home"], r["away"]))
    return by_gw


def _gw_dates(projected, played, gw):
    if gw in projected and projected[gw]:
        return projected[gw][0].get("dates", "")
    for other, rows in ((g, r) for g, r in played.items() if g == gw):
        if other == gw and rows:
            return "Matchweek %d" % gw
    return ""


def _dates_for_gw(summary, gw):
    nxt = (summary.get("meta") or {}).get("next_matchweek") or {}
    if nxt.get("gw") == gw:
        return nxt.get("dates", "")
    return ""


def _fixtures_for_club(index, team):
    """This club's remaining fixtures, from the full projected-fixtures table."""
    return index.get(team["code"], [])


if __name__ == "__main__":
    for path, kind in build():
        print("  %-34s %s" % (path, kind))
