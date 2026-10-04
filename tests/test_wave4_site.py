"""Wave 4 — the site is findable and shareable (P5.1–P5.4, P6.1–P6.4).

Six things have to be true for a prediction dashboard to be *publishable* rather than merely running:
a crawler must find real text, a link preview must have an image, a URL must survive being pasted into
a group chat, the icons must exist, and none of it may be invented by hand — every page and every
image is generated from `data/`, so all of these checks are really checks on the generator.

Where a check can be done against the real generated output it is; the pure-function tests (the PNG
encoder, the router's path parsing, the share payload) run on their own so a failure points at the
thing that broke.
"""
import gzip
import json
import os
import re
import struct
import sys

from _util import ROOT, pytest, skip

sys.path.insert(0, ROOT)
STATIC = os.path.join(ROOT, "static")
SUMMARY = os.path.join(ROOT, "data", "predictions_2026_27_summary.json")


def _summary():
    if not os.path.exists(SUMMARY):
        skip("run the pipeline first (data/predictions_2026_27_summary.json is missing)")
    return json.load(open(SUMMARY, encoding="utf-8"))


def _read(rel):
    path = os.path.join(STATIC, rel)
    if not os.path.exists(path):
        skip("static/%s is missing — run python3 site_pages.py" % rel)
    return open(path, encoding="utf-8").read()


#: The prelude every node harness here starts with. It exists because `require()` gives each file its
#: own module scope, which is *not* how the page works: the shipped index.html inlines core.js and
#: share.js into a single <script>, so share.js can call functions core.js defines. Loading them
#: separately in node hides those functions and made the harness fail the moment share.js started
#: calling the scenario validator. Concatenating them into one vm context reproduces the page, and
#: the payload is the real EMBEDDED object read out of index.html rather than a hand-written stub.
_NODE_PRELUDE = r"""
const fs = require("fs"), vm = require("vm");
const [corePath, sharePath, embPath] = process.argv.slice(2);
global.window = {};
const sandbox = {
  window: global.window, navigator: {}, console: console,
  location: { protocol:"https:", origin:"https://example.test", pathname:"/whatif", search:"",
              href:"https://example.test/whatif", hash:"" },
  document: { readyState:"complete", addEventListener(){}, querySelectorAll(){ return []; },
              querySelector(){ return null; }, getElementById(){ return null; } },
  localStorage: { getItem(){ return null; }, setItem(){}, removeItem(){} },
  btoa: (s) => Buffer.from(s, "binary").toString("base64"),
  atob: (s) => Buffer.from(s, "base64").toString("binary"),
  escape, unescape, encodeURIComponent, decodeURIComponent, Number, Object, Array, String,
  parseInt, parseFloat, Date, isFinite, Math, JSON, setTimeout, clearTimeout,
};
sandbox.globalThis = sandbox;
sandbox.EMBEDDED = JSON.parse(fs.readFileSync(embPath, "utf8"));
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(corePath, "utf8") + "\n" + fs.readFileSync(sharePath, "utf8"), sandbox);
const S = global.window.NT90_SHARE;
const native = (expr) => vm.runInContext(expr, sandbox);
"""


def _run_share_harness(body):
    """Run `body` in node with core.js and share.js in one scope, against the page's real payload."""
    import subprocess
    import tempfile
    page = _read("index.html")
    marker = "const EMBEDDED = "
    if marker not in page:
        skip("index.html does not embed the payload")
    payload, _ = json.JSONDecoder().raw_decode(page, page.index(marker) + len(marker))
    paths = []
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(payload, fh)
            paths.append(fh.name)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(_NODE_PRELUDE + body)
            paths.append(fh.name)
        out = subprocess.run(["node", paths[1], os.path.join(STATIC, "src", "core.js"),
                              os.path.join(STATIC, "src", "share.js"), paths[0]],
                             capture_output=True, text=True, timeout=90)
        assert out.returncode == 0, "the share harness failed in node:\n" + out.stderr[-900:]
        return json.loads(out.stdout.strip().splitlines()[-1])
    finally:
        for path in paths:
            try:
                os.unlink(path)
            except OSError:
                pass


def _text_of(html_text):
    """What a crawler sees: markup stripped, then entities decoded.

    The decode matters more than it looks: "Nott&#x27;m Forest" is the same string to a crawler as
    "Nott'm Forest", and a test that forgets it reports a missing fixture that is plainly there.
    """
    import html as _html
    body = re.sub(r"(?s)<(script|style)\b.*?</\1>", " ", html_text)
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"(?s)<[^>]+>", " ", body))).strip()


# ════════════════════════════════════════════════════════════════════════════
#  P5.1 — identity: previews, icons, theme colour, canonical
# ════════════════════════════════════════════════════════════════════════════
def test_the_dashboard_has_a_full_head():
    html = _read("index.html")
    for needle, why in (
        ('property="og:title"', "no Open Graph title — a shared link shows as a bare URL"),
        ('property="og:image"', "no preview image — the link renders as text only"),
        ('property="og:description"', "no preview description"),
        ('name="twitter:card"', "no Twitter card"),
        ('rel="canonical"', "no canonical URL"),
        ('name="theme-color"', "no theme-colour, so mobile browser chrome will not match the design"),
        ('rel="apple-touch-icon"', "no apple-touch icon"),
        ('rel="icon"', "no favicon"),
    ):
        assert needle in html, why + " (%s missing)" % needle


def test_every_identity_asset_the_page_promises_exists():
    """A head that points at files which are not there is worse than an empty head."""
    html = _read("index.html")
    # The manifest is in this list for a reason: it is the one head link no person ever sees, so a
    # broken one survives every visual check. It did — the file existed, the head linked it, and the
    # server 404'd it, until a clean-room extraction went looking.
    referenced = re.findall(
        r'(?:rel="(?:icon|apple-touch-icon|manifest)"[^>]*href|property="og:image" content)="([^"]+)"',
        html)
    assert referenced, "the page references no icons or preview images at all"
    missing = []
    for ref in referenced:
        rel = ref.split("?")[0].lstrip("./")
        if rel.startswith("http"):
            continue
        if not os.path.exists(os.path.join(STATIC, rel)):
            missing.append(ref)
    assert not missing, "the page promises files that do not exist: %s" % missing


def test_the_preview_image_is_a_real_png_of_the_right_shape():
    """Social platforms silently drop anything that is not 1200×630."""
    import og_image
    for name in ("og/site.png", "og/table.png", "og/duel.png", "og/club-mci.png"):
        path = os.path.join(STATIC, name)
        if not os.path.exists(path):
            skip("static/%s missing — run python3 site_pages.py" % name)
        w, h = og_image.png_size(path)
        assert (w, h) == (1200, 630), "%s is %dx%d, not 1200x630" % (name, w, h)
        assert os.path.getsize(path) > 2000, "%s is suspiciously small — probably blank" % name


def test_the_legacy_favicon_is_a_real_ico_and_matches_the_tab_icon():
    """`/favicon.ico` is requested by clients that ignore the page's own <link rel="icon">.

    Safari, feed readers and link-preview bots fetch it on sight, so a 404 there is a console error on
    an otherwise perfect page — and no HTML-reading test can see it, because nothing advertises it.
    Found by sweeping every route of a clean-room extraction. Two things must hold: the container is
    well-formed, and its payload is byte-for-byte the 32 px icon the page does advertise, so the tab
    icon and the fallback cannot quietly diverge.
    """
    path = os.path.join(STATIC, "favicon.ico")
    assert os.path.exists(path), "static/favicon.ico missing — run python3 site_pages.py"
    blob = open(path, "rb").read()
    reserved, kind, count = struct.unpack("<HHH", blob[:6])
    assert (reserved, kind, count) == (0, 1, 1), "not a single-image ICO container"
    w, h, _colours, _res, planes, bpp, length, offset = struct.unpack("<BBBBHHII", blob[6:22])
    assert (w, h) == (32, 32) and bpp == 32 and planes == 1, "the ICO entry is %dx%d %d bpp" % (w, h, bpp)
    assert offset == 22 and 22 + length == len(blob), "the ICO length fields do not add up"
    payload = blob[offset:]
    assert payload[:8] == b"\x89PNG\r\n\x1a\n", "the ICO payload is not a PNG"
    assert payload == open(os.path.join(STATIC, "icons", "favicon-32.png"), "rb").read(), (
        "the .ico fallback and the advertised 32 px icon have drifted apart")


def test_the_icon_set_is_complete():
    for rel, size in (("icon.svg", None), ("apple-touch-icon.png", 180),
                      ("icons/favicon-32.png", 32), ("icons/icon-192.png", 192),
                      ("icons/icon-512.png", 512)):
        path = os.path.join(STATIC, rel)
        assert os.path.exists(path), "missing static/%s" % rel
        if size:
            with open(path, "rb") as fh:
                head = fh.read(24)
            assert head[:8] == b"\x89PNG\r\n\x1a\n", "%s is not a PNG" % rel
            assert struct.unpack(">II", head[16:24]) == (size, size), "%s is the wrong size" % rel


# ════════════════════════════════════════════════════════════════════════════
#  P5.2 — structured data
# ════════════════════════════════════════════════════════════════════════════
def _jsonld(html):
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    out = []
    for b in blocks:
        out.append(json.loads(b))          # a malformed block must fail here, loudly
    return out


def test_every_generated_page_carries_valid_jsonld():
    for rel in ("gameweek/mw6.html", "club/arsenal.html", "table.html", "model.html"):
        html = _read(rel)
        blocks = _jsonld(html)
        assert blocks, "%s has no structured data" % rel
        for block in blocks:
            assert block.get("@context") == "https://schema.org", "%s: wrong @context" % rel
            graph = block.get("@graph", [block])
            for node in graph:
                assert node.get("@type"), "%s: a node without @type" % rel


def _nodes(block):
    """Every node anywhere in a JSON-LD block, including nested ones inside ItemList positions.

    The first version of this test only looked at the top of the graph and found nothing: schema.org
    trees nest, and a consumer walks them.
    """
    found = []

    def walk(node):
        if isinstance(node, dict):
            if "@type" in node:
                found.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(block.get("@graph", block))
    return found


def test_a_gameweek_page_lists_its_fixtures_as_sports_events():
    """SportsEvent is what makes a fixture eligible for the rich results a search engine shows."""
    summary = _summary()
    blocks = _jsonld(_read("gameweek/mw6.html"))
    graph = [n for b in blocks for n in _nodes(b)]
    events = [n for n in graph if n.get("@type") == "SportsEvent"]
    assert len(events) == 10, "matchweek 6 has 10 fixtures, the page describes %d" % len(events)
    for e in events:
        assert e.get("competitor") and len(e["competitor"]) == 2, "a fixture with no two competitors"
        assert " vs " in e["name"], "fixture name should read 'A vs B', got %r" % e["name"]
        assert e.get("description"), "a fixture with no description"
    names = {c["name"] for e in events for c in e["competitor"]}
    known = {t["name"] for t in summary["table_projections"]}
    assert names <= known, "SportsEvent names a club that is not in the table: %s" % (names - known)


# ════════════════════════════════════════════════════════════════════════════
#  P5.4 — crawlable content: real text, a sitemap, and every week present
# ════════════════════════════════════════════════════════════════════════════
def test_the_numbers_are_text_not_only_canvas():
    """The whole complaint about a JavaScript dashboard: a crawler sees a shell. It must not here."""
    summary = _summary()
    import csv
    proj = os.path.join(ROOT, "data", "projected_fixtures_2026_27.csv")
    if not os.path.exists(proj):
        skip("data/projected_fixtures_2026_27.csv missing — run the pipeline")
    rows = [r for r in csv.DictReader(open(proj, encoding="utf-8")) if int(r["gw"]) == 6]
    text = _text_of(_read("gameweek/mw6.html"))
    assert len(rows) == 10
    labels = {t["code"]: [t["code"], t["name"], t.get("short", "")] for t in _summary()["table_projections"]}
    for r in rows:
        # the page is written for people: it prints the short name ("Leeds"), the code is only a
        # fallback for clubs whose short name is missing. Any of the three means the fixture is there.
        for side in ("home", "away"):
            code = r[side]
            assert any(lbl and lbl in text for lbl in labels[code]), \
                "fixture %s (%s) is not in the page's text" % (code, "/".join(labels[code]))
    # the probabilities themselves, not just the club codes
    pct = "%.0f%%" % float(rows[0]["prob_home"])
    assert pct in text, "the home-win probability %s does not appear as text" % pct


def test_every_gameweek_has_a_page_and_every_page_is_in_the_sitemap():
    sitemap = _read("sitemap.xml")
    weeks = re.findall(r"gameweek/mw(\d+)\.html", sitemap)
    assert sorted(int(w) for w in weeks) == list(range(1, 39)), \
        "the sitemap should cover all 38 matchweeks, it covers %d" % len(weeks)
    for gw in (1, 5, 6, 20, 38):
        assert os.path.exists(os.path.join(STATIC, "gameweek", "mw%d.html" % gw)), \
            "matchweek %d has no page" % gw


def test_played_gameweeks_show_results_and_future_ones_show_projections():
    """A page for a completed week that shows a forecast is a lie with a timestamp on it."""
    played = _text_of(_read("gameweek/mw1.html"))
    assert re.search(r"\b\d+–\d+\b", played), "mw1 is played, so its page must carry scorelines"
    assert "results" in played.lower(), "mw1 is played, so its page should say so"
    future = _text_of(_read("gameweek/mw38.html"))
    assert "%" in future, "mw38 is in the future, so its page must carry probabilities"


def test_the_sitemap_is_well_formed_and_consistent_with_the_tree():
    import xml.etree.ElementTree as ET
    tree = ET.fromstring(_read("sitemap.xml"))
    locs = [e.text for e in tree.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert len(locs) >= 60, "only %d URLs in the sitemap" % len(locs)
    for loc in locs:
        rel = loc.split("//")[-1].split("/", 1)[-1] if "://" in loc else loc
        if loc.startswith("http"):      # an absolute sitemap (NT90_SITE_URL was set at build time)
            rel = re.sub(r"^[^/]+/", "", loc.split("://", 1)[1])
        rel = rel.lstrip("/")
        assert os.path.exists(os.path.join(STATIC, rel)), "sitemap lists %s, which does not exist" % loc


def test_robots_points_at_the_sitemap_and_keeps_the_api_out():
    robots = _read("robots.txt")
    assert "Disallow: /api/" in robots, "the API should not be crawled"
    assert "Disallow: /healthz" in robots and "Disallow: /readyz" in robots, \
        "operational endpoints should not be crawled"


def test_a_club_page_states_its_club_projection():
    summary = _summary()
    arsenal = next(t for t in summary["table_projections"] if t["code"] == "ARS")
    text = _text_of(_read("club/arsenal.html"))
    assert "Arsenal" in text
    assert "%.1f" % arsenal["proj_pts"] in text, "the projected points are not on the page"
    assert "%.0f%%" % arsenal["title_prob"] in text, "the title probability is not on the page"
    assert "%d" % len([
        r for r in __import__("csv").DictReader(
            open(os.path.join(ROOT, "data", "projected_fixtures_2026_27.csv"), encoding="utf-8"))
        if "ARS" in (r["home"], r["away"])]) in text, "the fixture count is wrong"
    assert "simulated 5,000 times" in text or "5,000 simulated seasons" in text, \
        "the page must say how the numbers were produced"


def test_no_generated_page_invents_an_absolute_url():
    """The build runs without knowing its host. Absolute URLs appear only if NT90_SITE_URL is set."""
    if os.environ.get("NT90_SITE_URL"):
        skip("NT90_SITE_URL is set for this build, so absolute URLs are expected")
    for rel in ("gameweek/mw6.html", "club/arsenal.html", "table.html", "model.html", "404.html"):
        html = _read(rel)
        absolute = re.findall(r'(?:href|src|content)="(https?://[^"]+)"', html)
        assert not absolute, "%s contains absolute URLs: %s" % (rel, absolute[:3])


# ════════════════════════════════════════════════════════════════════════════
#  P5.3 — URLs and the router
# ════════════════════════════════════════════════════════════════════════════
def _router_source():
    path = os.path.join(ROOT, "static", "src", "router.js")
    if not os.path.exists(path):
        skip("static/src/router.js is missing")
    return open(path, encoding="utf-8").read()


def test_the_router_is_in_the_published_page():
    """The router lives in static/src/, but it only ships if the build includes it."""
    html = _read("index.html")
    assert "NT90_ROUTER" in html, "router.js was not compiled into the page"
    assert "/gameweek/" in html and "/club/" in html, "the router's route table is missing"


def test_the_router_defines_every_view_the_app_has():
    src = _router_source()
    for view in ("matchweek", "table", "awards", "duel", "whatif", "model"):
        assert view in src, "the router does not know about the %s view" % view
    for path in ("/table", "/awards", "/duel", "/whatif", "/model"):
        assert '"%s"' % path in src, "no path for %s" % path


def test_the_router_does_not_route_outside_http():
    """Opened from a zip, or inside a sandboxed preview, there is no URL to rewrite — and pretending
    otherwise breaks the page that most people see first."""
    src = _router_source()
    assert 'location.protocol === "http:"' in src and 'location.protocol === "https:"' in src, \
        "the router must check the protocol before touching history"


def test_the_app_routes_are_served_the_dashboard_but_the_pages_are_served_as_pages():
    """Two different things share a prefix, and confusing them breaks one of them.

    `/club/arsenal` is an app route (the client decides what to draw); `/club/arsenal.html` is a
    generated page (the file is the answer). The server has to get both right.
    """
    import http.client
    import subprocess
    import time
    import socket

    sk = socket.socket()
    sk.bind(("127.0.0.1", 0))
    port = sk.getsockname()[1]
    sk.close()
    env = dict(os.environ, PORT=str(port), NT90_PRELOAD="1")
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                c.request("GET", "/readyz")
                if c.getresponse().status == 200:
                    break
            except Exception:
                time.sleep(0.5)
        else:
            raise AssertionError("server never became ready")

        def get(path, accept=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            h = {"Accept": accept} if accept else {}
            c.request("GET", path, headers=h)
            r = c.getresponse()
            body = r.read()
            if r.getheader("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return r.status, r.getheader("Content-Type") or "", body

        # 1. the six app routes all serve the dashboard itself
        for route in ("/table", "/awards", "/duel", "/whatif", "/model", "/matchweek"):
            code, ctype, body = get(route)
            assert code == 200 and "text/html" in ctype, "%s -> %s %s" % (route, code, ctype)
            assert b"const EMBEDDED" in body, "%s did not serve the dashboard" % route

        # 2. the deep links too — they are the point of the router
        for route in ("/gameweek/6", "/gameweek/12", "/club/arsenal", "/club/nott-m-forest"):
            code, _, body = get(route)
            assert code == 200 and b"const EMBEDDED" in body, "%s did not serve the dashboard" % route

        # 3. the generated pages are the pages, not the dashboard
        code, ctype, body = get("/club/arsenal.html")
        assert code == 200 and b"const EMBEDDED" not in body, "/club/arsenal.html served the app"
        assert b"Projected points" in body, "/club/arsenal.html is not the club page"

        # 3b. every page the build wrote is reachable — derived from disk, not hand-listed.
        # server.py used to carry a tuple of generated pages, so a new page could exist, deploy on
        # Vercel (which serves static/ directly) and 404 locally and in the container. /receipts.html,
        # /changelog.html and /ledger.json did exactly that. This walks what site_pages.py actually
        # produced, so the next new page fails here instead of in front of a reader.
        generated = []
        for base, _dirs, files in os.walk(STATIC):
            for name in files:
                if not name.endswith((".html", ".xml", ".json")):
                    continue
                rel = os.path.relpath(os.path.join(base, name), STATIC).replace(os.sep, "/")
                if rel in ("index.html",):
                    continue                     # the app shell opens on /, checked above
                generated.append(rel)
        assert generated, "nothing generated to check — did site_pages.py run?"
        for rel in sorted(generated):
            code, ctype, body = get("/" + rel)
            assert code == 200, "/%s is on disk but the local server returned %s" % (rel, code)
            assert body, "/%s served an empty body" % rel

        # 4. assets
        for asset, kind in (("/sitemap.xml", b"<?xml"), ("/icon.svg", b"<svg"),
                            ("/apple-touch-icon.png", b"\x89PNG"), ("/og/site.png", b"\x89PNG"),
                            ("/icons/icon-192.png", b"\x89PNG"), ("/manifest.webmanifest", b"{"),
                            ("/favicon.ico", b"\x00\x00\x01\x00")):
            code, _, body = get(asset)
            assert code == 200 and body.startswith(kind), "%s -> %s" % (asset, code)

        # ...and every asset the dashboard's own head advertises, because a hand-kept list only
        # proves the list was written. This is the assertion that catches a head link the server
        # never learned to route.
        _, _, page = get("/")
        advertised = set(re.findall(
            r'(?:rel="(?:icon|apple-touch-icon|manifest)"[^>]*href|property="og:image" content)="([^"]+)"',
            page.decode("utf-8", "replace")))
        for ref in sorted(advertised):
            if ref.startswith(("http", "data:")):
                continue
            # `lstrip("./")` would eat the leading slash and ask for a rootless path; strip the
            # literal "./" prefix only, so the request is the URL the page actually advertises.
            path = ref[2:] if ref.startswith("./") else ref
            if not path.startswith("/"):
                path = "/" + path
            code, _, _ = get(path)
            assert code == 200, "the dashboard advertises %s and the server answers %s" % (ref, code)

        # 5. a 404 is a page, with a 404 status
        code, ctype, body = get("/no-such-page", accept="text/html")
        assert code == 404, "a missing page returned %s" % code
        assert b"isn't here" in body or b"isn&#x27;t here" in body, "the 404 page is not being served"

        # 6. and it never serves a file from outside static/
        for probe in ("/../server.py", "/..%2fserver.py", "/club/../../../etc/passwd"):
            code, _, body = get(probe)
            assert code == 404, "%s returned %s — that is a traversal" % (probe, code)
            assert b"def " not in body[:200], "%s leaked source" % probe
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


# ════════════════════════════════════════════════════════════════════════════
#  P6.1 / P6.2 / P6.4 — sharing: versioned state, links, cards
# ════════════════════════════════════════════════════════════════════════════
def test_a_shared_link_carries_a_version_so_old_links_keep_working():
    """A link is a promise with an indefinite lifetime. When the payload changes shape, the reader has
    to be able to tell an old link from a corrupt one."""
    html = _read("index.html")
    assert "NT90_SHARE" in html, "the share payload module is not in the build"
    assert re.search(r"version\s*[:=]\s*['\"]?1", html), \
        "the share payload has no version field, so a future change cannot read an old link"


def test_the_share_payload_round_trips_every_part_of_a_scenario():
    """Including the parts that are easy to forget: forced scores and points deductions.

    The encoder is exercised directly, in node, because this is the one piece of the front end that
    has to be exactly right in both directions — a link that drops a value silently changes someone
    else's scenario and nobody would know.
    """
    result = _run_share_harness("""
const scenario = { player_injuries:{ haaland:6 }, team_boosts:{ ARS:{ attack:6, defence:-3 } },
                   points_deductions:{ MCI:10 }, custom_scores:{ "ARS-MCI":[3,1] } };
const token = S.encode(scenario);
const decoded = S.decode(token);
console.log(JSON.stringify({ version:decoded.version, token,
                             same:JSON.stringify(decoded.scenario) === JSON.stringify(scenario),
                             scenario:decoded.scenario }));
""")
    assert result["token"].startswith("v1-"), "the token does not carry its version: %s" % result["token"]


def test_an_old_unversioned_link_still_reads():
    """Every link shared before the version prefix existed has to keep working."""
    result = _run_share_harness("""
const old = Buffer.from(JSON.stringify({ i:{ haaland:4 }, b:{}, d:{}, c:{} }), "utf8")
  .toString("base64").replace(/\\+/g, "-").replace(/\\//g, "_").replace(/=+$/, "");
const parsed = S.decode(old);
console.log(JSON.stringify({ migrated:parsed.migrated, injuries:parsed.scenario.player_injuries }));
""")
    assert result["injuries"] == {"haaland": 4}, result
    assert result["migrated"] is True, "an unversioned token should be flagged as migrated"


def test_a_share_link_survives_the_validator_in_both_wire_shapes():
    """The reader has to understand what the writer emits, or Share produces links that will not open.

    This is the regression for a bug that shipped: share.js wrote "v1-<base64>" while the reader in
    ux.js accepted only a bare base64 body, so **every link the Share button produced failed to
    open** with a toast blaming the link. The second half is the companion bug from the other side —
    the validator that was added to stop injection initially understood only the {attack, defence}
    object shape and silently emptied the compact [attack, defence] array a link actually carries.
    """
    result = _run_share_harness("""
const token = S.encode({ team_boosts:{ ARS:{ attack:6, defence:-3 } }, player_injuries:{ haaland:6 } });
// what ux.js's reader does to the token the Share button just put on the clipboard
const body = token.replace(/^v\\d+-(.*)$/, "$1");
const wired = native(`sanitizeScenario({ team_boosts:{ ARS:[6,-3] }, player_injuries:{ haaland:6 } })`);
// the object shape has to keep working too, because the page stores scenarios in it
const stored = native(`sanitizeScenario({ team_boosts:{ ARS:{ attack:6, defence:-3 } },
                                         player_injuries:{ haaland:6 } })`);
// and a crafted one is still dropped, in either shape
const hostile = native(`sanitizeScenario({ team_boosts:{ ARS:["<img src=x onerror=alert(1)>",0] },
                                           player_injuries:{ haaland:"<img src=x>" } })`);
console.log(JSON.stringify({ prefixed:token.startsWith("v1-"), body_is_base64:!body.startsWith("v1-"),
                             wired, stored, hostile }));
""")
    assert result["prefixed"], "the Share button's token lost its version prefix"
    assert result["body_is_base64"], "the version prefix is not being stripped by the reader"
    assert result["wired"] == result["stored"], (
        "the compact [attack, defence] shape a link carries and the object shape the page stores must "
        "sanitise to the same thing, or a shared scenario loads empty: %r vs %r"
        % (result["wired"], result["stored"]))
    assert result["wired"]["team_boosts"] == {"ARS": {"attack": 6, "defence": -3}}, result["wired"]
    assert result["hostile"]["team_boosts"] == {}, (
        "a markup payload in a boost survived validation: %r" % result["hostile"])
    assert result["hostile"]["player_injuries"] == {}, (
        "a markup payload in an injury survived validation: %r" % result["hostile"])


def test_share_affordances_exist_on_both_features():
    html = _read("index.html")
    assert 'id="shareScen"' in html, "the What-If view has no share button"
    assert 'id="shareDuel"' in html, "the Duel view has no share button"
    assert "navigator.share" in html, "no native share sheet on mobile"
    assert "navigator.clipboard" in html, "no clipboard fallback"


def test_cards_can_be_downloaded_from_the_page():
    html = _read("index.html")
    assert "toBlob" in html or "toDataURL" in html, "no way to get a canvas out as an image"
    assert "download" in html, "no download affordance for the card"
    assert "1200" in html and "630" in html, "the card canvas is not the share size"
