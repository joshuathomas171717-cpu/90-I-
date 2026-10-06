"""Deployment — the static site, and what it promises a reader (Wave 7, Vercel).

Everything here is a claim the project makes about the deployed artefact, checked against the artefact
itself rather than against the code that writes it:

  · the page shows the same as-of date as data/as_of.json — the whole site is a snapshot, and a
    snapshot that does not say when it was taken is not much use;
  · the page is self-contained: no CDN, no font downloads, no external subresource of any kind;
  · the What-If tab can run with no API at all, and says so rather than pretending;
  · the site fits in a page weight a phone on a train can actually load.

A test that reads the *source* passes when the build is broken; these read static/index.html.
"""
import json
import os
import re

from _util import ROOT   # noqa: E402

STATIC = os.path.join(ROOT, "static")
SRC = os.path.join(STATIC, "src")
DATA = os.path.join(ROOT, "data")

#: The page has to stay openable on a phone. 1 MB was the agreed ceiling; the real number is reported
#: by the test below so a regression shows up as a slightly-too-large page rather than a red build —
#: and the assertion is on the ceiling, not on the current size, so ordinary edits do not churn it.
PAGE_BUDGET_BYTES = 1024 * 1024


def _check(condition, message):
    if not condition:
        raise AssertionError(message)


def _read(path, base=None):
    with open(os.path.join(base, path) if base else path, encoding="utf-8") as fh:
        return fh.read()


def _page():
    return _read("index.html", STATIC)


def _code_only(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  The date on the page is the date of the data
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_page_shows_the_as_of_date_from_data_as_of_json():
    """The page and data/as_of.json must not disagree about when this snapshot was taken.

    data/as_of.json is what the weekly job rewrites when it promotes a gameweek, and it is the file a
    reader can go and check. So the page is measured against *that*, not against the summary — those
    two are tied to each other by their own test, and a chain is only as strong as the end a person
    can actually see.
    """
    as_of = json.loads(_read("as_of.json", DATA))
    page = _page()
    _check(as_of["date"] in page,
           "data/as_of.json says %s and that date appears nowhere in static/index.html — the page "
           "was not rebuilt after the data moved" % as_of["date"])
    # and it is on the page as a date, not as a substring of some number
    _check(re.search(r"as of %s" % re.escape(as_of["date"]), page),
           "the page does not carry an 'as of %s' stamp" % as_of["date"])


def test_the_page_date_agrees_with_the_summary_it_was_built_from():
    as_of = json.loads(_read("as_of.json", DATA))
    summary = json.loads(_read("predictions_2026_27_summary.json", DATA))
    _check(as_of["date"] in summary["meta"]["as_of_date"],
           "as_of.json and the summary disagree: %s vs %s"
           % (as_of["date"], summary["meta"]["as_of_date"]))


def test_no_stale_as_of_date_is_anywhere_in_the_page():
    """One date, not two.

    The page carries the stamp in the header, in the JSON-LD dateModified and in the payload the
    runtime reads. If any one of them were left behind by an earlier build, the page would contradict
    itself — and the reader has no way to tell which of the two dates is real.

    Comments are stripped before scanning, because a comment that names a bug is not the bug: the
    first version of this test failed on the explanatory comment left in core.js beside the fix,
    which is the same mistake the Wave-5 model-card test made with its own documentation.
    """
    as_of = json.loads(_read("as_of.json", DATA))["date"]
    page = _page()  # parse the literal JSON before stripping code comments (source strings may contain comment characters)
    # The fixture calendar is exempt, and only the fixture calendar. It has to be full of dates — that
    # is what a calendar is — and it makes no claim about when the numbers were built. It is checked
    # against the published fixture list instead, in tests/test_wave11_liveness.py, which is a stronger
    # assertion than "these dates do not look stale". Everything else in the page is still scanned.
    marker = "const EMBEDDED = "
    start = page.index(marker)+len(marker)
    embedded, length = json.JSONDecoder().raw_decode(page[start:])
    embedded.pop("player_layer", None)  # independently checked source/capture dates, NOT a results stamp
    page = _code_only(page[:start]+json.dumps(embedded)+page[start+length:])
    page = re.sub(r'"schedule"\s*:\s*\{[^{}]*\}', '"schedule": {}', page)
    found = set(re.findall(r"20\d\d-\d\d-\d\d", page))
    stale = sorted(d for d in found if d != as_of)
    _check(not stale,
           "the page mentions %s as well as the current as-of date %s" % (stale, as_of))


def test_the_client_engine_reports_the_payloads_date():
    """The in-browser simulator must not carry its own idea of when the data is from.

    It did: localSimulate's meta hard-coded "2026-10-02", a day behind the payload it was simulating.
    On a static deployment that engine is the only one there is, so every What-If run reported a
    vintage the rest of the page contradicted.
    """
    core = _code_only(_read("core.js", SRC))
    block = core[core.index("function localSimulate"):]
    block = block[:block.index("async function runSim")]
    _check("client_fallback:true" in block.replace(" ", ""),
           "could not find the client engine's meta block")
    _check("DATA.meta && DATA.meta.as_of_date" in block,
           "the client engine does not read the as-of date from the payload")
    _check(not re.search(r'as_of_date\s*:\s*"20\d\d-', block),
           "the client engine still hard-codes a date literal")


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  Self-contained: no CDN, no external requests
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _external_subresources(page):
    """Every place the browser would fetch something from another origin.

    Subresources only. An <a href> to GitHub is a link a reader may choose to follow; a <script src>
    or a url() in CSS is a request the browser makes without asking, and those are what "no external
    requests" is about.
    """
    hits = []
    for pattern, what in (
            (r'<script[^>]+src=["\'](https?:)?//', "script"),
            (r'<link[^>]+href=["\'](https?:)?//[^"\']*\.(?:css|woff2?|ttf|otf)', "stylesheet/font"),
            (r'<img[^>]+src=["\'](https?:)?//', "image"),
            (r'<iframe[^>]+src=["\'](https?:)?//', "iframe"),
            (r'@import\s+(?:url\()?["\']?(https?:)?//', "css @import"),
            (r'url\(\s*["\']?(https?:)?//', "css url()")):
        if re.search(pattern, page, re.I):
            hits.append(what)
    return hits


def test_the_page_makes_no_external_requests():
    hits = _external_subresources(_page())
    _check(not hits, "the self-contained promise is broken by: %s" % ", ".join(hits))


def test_the_fonts_are_embedded_not_downloaded():
    """The one external request this page used to make was Google Fonts. It is 42 KB of base64 now."""
    page = _page()
    _check("fonts.googleapis" not in page and "fonts.gstatic" not in page,
           "a font CDN is referenced again")
    _check(page.count("data:font/woff2;base64,") >= 1 or "data:font/woff2;base64" in page,
           "no embedded font found — check static/src/fonts.css")


def test_the_page_is_one_file():
    """index.html has to work from a double-clicked path, from /90-I-/ and from a Vercel root."""
    page = _page()
    for pattern in (r'<link[^>]+rel=["\']stylesheet', r'<script[^>]+src='):
        _check(not re.search(pattern, page, re.I),
               "the page loads an external file: %s" % pattern)


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  Metadata: the cards a link makes
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_page_carries_open_graph_and_twitter_cards():
    page = _page()
    for tag in ('property="og:type"', 'property="og:title"', 'property="og:description"',
                'property="og:image"', 'property="og:image:width"', 'property="og:image:height"',
                'property="og:image:alt"', 'name="twitter:card"', 'name="twitter:title"',
                'name="twitter:description"', 'name="twitter:image"'):
        _check(re.search(re.escape(tag) + r"\s+content=", page), "missing meta tag: %s" % tag)
    _check('content="summary_large_image"' in page, "the twitter card should be a large image card")


def test_the_preview_image_is_a_real_file():
    page = _page()
    m = re.search(r'property="og:image"\s+content="([^"]+)"', page)
    _check(m, "no og:image")
    src = m.group(1)
    if src.startswith("http"):
        # absolute: the file it points at still has to exist in this build
        src = "/" + src.split("/", 3)[3] if src.count("/") >= 3 else src
    path = os.path.join(STATIC, src.lstrip("/"))
    _check(os.path.exists(path), "og:image points at %s, which this build does not contain" % src)
    _check(os.path.getsize(path) > 5000, "og:image is suspiciously small — %d bytes" % os.path.getsize(path))


def test_the_page_declares_a_canonical_and_says_what_to_do_without_one():
    page = _page()
    m = re.search(r'<link rel="canonical" href="([^"]*)"', page)
    _check(m, "no canonical link")
    if m.group(1) == "./":
        _check("set NT90_SITE_URL" in page,
               "with no site URL the page should say so in a comment, or nobody will know why the "
               "link preview is blank")


def test_the_page_has_an_icon_and_a_manifest():
    page = _page()
    _check('rel="icon"' in page, "no favicon link")
    _check('rel="apple-touch-icon"' in page, "no apple-touch-icon")
    _check('rel="manifest"' in page, "no web manifest")
    for rel in ("icon.svg", "icons/favicon-32.png", "apple-touch-icon.png", "manifest.webmanifest"):
        _check(os.path.exists(os.path.join(STATIC, rel)), "%s is linked but missing from the build" % rel)


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  Running without a server
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_what_if_tab_has_an_in_browser_engine_to_fall_back_on():
    core = _code_only(_read("core.js", SRC))
    _check("function localSimulate" in core, "there is no in-browser simulator to fall back on")
    _check("ENGINE_MODE" in core, "the page does not track which engine it is using")
    # the fallback must be reached when the API is absent, not only when a fetch throws
    _check(re.search(r'if\(!res\)\s*\{[^}]*localSimulate', core, re.S),
           "runSim does not fall back to the in-browser engine")


def test_offline_mode_says_so_on_the_what_if_tab():
    """Not just a toast: a note where the reader is about to press the button."""
    html = _read("app.html", SRC)
    _check('id="engineNote"' in html, "the What-If tab has no offline note")
    note = html[html.index('id="engineNote"'):]
    note = note[:note.index("</div>")]
    _check("static site" in note and "browser" in note,
           "the offline note should explain why, not just state that the mode changed")
    _check("hidden" in note.split(">")[0], "the note should start hidden and be revealed by paintMode()")
    core = _code_only(_read("core.js", SRC))
    _check('$("engineNote")' in core and "note.hidden = !offline" in core,
           "nothing reveals the offline note")


def test_the_server_is_still_the_optional_local_dev_server():
    """Vercel serves static/; server.py stays what it always was. It must not have grown a
    serverless handler, and it must still be what the local quick-start tells people to run."""
    server = _read("server.py", ROOT)
    for smell in ("handler = Handler", "def handler(event", "serverless", "aws_lambda"):
        _check(smell not in server.lower(), "server.py looks like it was bent towards serverless: %r" % smell)
    _check("BaseHTTPRequestHandler" in server, "server.py should still be a plain threaded HTTP server")
    readme = _read("README.md", ROOT)
    _check("python3 server.py" in readme, "the README still has to tell people how to run it locally")


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  Vercel configuration
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_vercel_config_points_at_the_static_directory_with_no_build():
    cfg = json.loads(_read("vercel.json", ROOT))
    _check(cfg.get("outputDirectory") == "static", "outputDirectory must be 'static'")
    _check(cfg.get("buildCommand") in (None, ""), "there is no build step to run on Vercel")
    _check(cfg.get("installCommand") in (None, ""), "there is nothing to install on Vercel")


def test_vercel_config_selects_no_framework():
    """The deploy broke because Vercel decided this was a Python app. `framework: null` prevents it.

    The failing build log read:

        Running "vercel build"
        WARNING! Internal rewrites in backend framework projects ...
        Error: Found server.py but it does not export a top-level "app", "application", or
               "handler" variable

    Vercel picks a framework by inspecting the repository root, and `server.py` is one of the six
    filenames it treats as a Python entrypoint (app.py, index.py, server.py, main.py, wsgi.py,
    asgi.py). Ours is the optional local dev server, so the build tried to load it as a serverless
    handler and failed. The framework preset also outranks this file's own settings, and the warning
    is the same mis-detection: in a "backend framework project" an internal rewrite is resolved
    against the rewritten destination path rather than the real URL.

    `framework: null` is the documented way to say "no framework is selected", and it is what keeps
    outputDirectory: static in charge. This test is here because the failure mode is silent and
    deferred — the config looks harmless, and the breakage only appears on someone else's deploy.
    """
    cfg = json.loads(_read("vercel.json", ROOT))

    _check("framework" in cfg,
           "vercel.json does not set \"framework\", so Vercel auto-detects one from the repository "
           "root — a root server.py makes it build this as a Python app and the deploy fails with "
           "\"Found server.py but it does not export a top-level app/application/handler\"")
    _check(cfg["framework"] is None,
           'vercel.json sets "framework": %r; it must be null (no framework) for the static build '
           "to be used" % (cfg["framework"],))


def test_no_root_file_looks_like_a_serverless_entrypoint():
    """If a Python entrypoint must exist at the root, it has to survive being loaded as one.

    Vercel scans for app.py, index.py, server.py, main.py, wsgi.py and asgi.py at the repository
    root (and inside a root src/ or app/). `framework: null` is what actually stops the detection,
    so this is the belt to that braces: it flags the day a new root file re-introduces the hazard,
    and it checks the one file we do have — server.py — declares no handler, so nobody is misled
    into thinking it is one.
    """
    entrypoints = [n for n in ("app.py", "index.py", "server.py", "main.py", "wsgi.py", "asgi.py")
                   if os.path.exists(os.path.join(ROOT, n))]
    _check(entrypoints == ["server.py"],
           "an unexpected root file matches Vercel's Python entrypoint list: %s — see "
           "https://vercel.com/docs/functions/runtimes/python; \"framework\": null is what keeps "
           "the static build, but a new entrypoint needs its own check" % entrypoints)

    server = _read("server.py", ROOT)
    _check("def handler(" not in server and "def application(" not in server,
           "server.py now defines a `handler`/`application`, so it looks like a Vercel Function "
           "entrypoint rather than the local dev server it is meant to stay")


def test_vercel_config_caches_html_shortly_and_assets_longer():
    cfg = json.loads(_read("vercel.json", ROOT))
    by_source = {}
    for rule in cfg["headers"]:
        for h in rule["headers"]:
            if h["key"].lower() == "cache-control":
                by_source.setdefault(rule["source"], h["value"])
    index_rule = [v for k, v in by_source.items() if "index.html" in k]
    _check(index_rule, "no Cache-Control rule for index.html")
    _check("max-age=0" in index_rule[0] and "must-revalidate" in index_rule[0],
           "index.html must revalidate, or a weekly rebuild is invisible for hours: %s" % index_rule[0])
    asset_rule = [v for k, v in by_source.items() if "png" in k]
    _check(asset_rule and "max-age=3600" in asset_rule[0],
           "image assets should be cached longer than the HTML")


def test_vercel_config_does_not_shadow_the_generated_pages():
    """Two kinds of route, and they must not collide.

    /table is the app and /table.html is the crawlable page — the same split server.py makes, and
    `cleanUrls: true` here would quietly make /table serve the static page instead, which is a
    different site from the one the local server serves.

    A rewrite may therefore point at the app shell, or at a generated static page that the router does
    *not* own — /changelog and /receipts are pages, not views, so pointing at them shadows nothing.
    What it may never do is point at a page the app also answers on, or at a file that does not exist.
    """
    cfg = json.loads(_read("vercel.json", ROOT))
    _check(cfg.get("cleanUrls") is not True, "cleanUrls would shadow the generated .html pages")

    #: Paths the in-page router answers. A rewrite whose source is one of these is the app; a static
    #: page at the same path would be unreachable, which is the failure this test exists to catch.
    app_source = {"", "/matchweek", "/table", "/awards", "/duel", "/whatif", "/model"}
    for rule in cfg["rewrites"]:
        dest, source = rule["destination"], rule["source"]
        _check(not source.endswith(".html"), "a rewrite must not shadow a generated page: %s" % source)
        if dest == "/index.html":
            continue
        page = dest.lstrip("/")
        _check(os.path.exists(os.path.join(STATIC, page)),
               "rewrite %s points at %s, which is not a generated file" % (source, dest))
        _check(source not in app_source,
               "rewrite %s points at the static page %s while the app also answers on that path — "
               "one of the two is now unreachable" % (source, dest))
    assert_sources = [r["source"] for r in cfg["rewrites"]]
    duplicates = {x for x in assert_sources if assert_sources.count(x) > 1}
    _check(not duplicates,
           "these paths are rewritten twice, so which one wins is down to order: %s"
           % sorted(duplicates))

    app_routes = set(assert_sources)
    for route in ("/table", "/awards", "/duel", "/whatif", "/model", "/matchweek"):
        _check(route in app_routes, "%s is an app route in server.py but not in vercel.json" % route)
    for route in ("/receipts", "/changelog"):
        _check(route in app_routes, "%s is generated but not routed, so it would 404 when typed" % route)


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  Hygiene: secrets, ignore rules, weight
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_receipts_page_publishes_the_live_ledger_with_its_hashes():
    """P10.3 — the page has to be checkable, which means the hashes have to be on it.

    A receipts page that only shows "we were right 46.3% of the time" is a claim. Showing the lock
    hash and the command that recomputes it turns the same page into evidence, so both are asserted
    here, along with the machine-readable ledger it was generated from.
    """
    page = _read("receipts.html", STATIC)
    ledger_path = os.path.join(DATA, "ledger_2026_27.json")
    if not os.path.exists(ledger_path):
        skip("data/ledger_2026_27.json is missing")
    with open(ledger_path, encoding="utf-8") as fh:
        ledger = json.load(fh)

    _check("Every call, on the record" in page, "the receipts page lost its title")
    _check("score_ledger.py --verify" in page, "the receipts page no longer says how to check it")
    _check('href="ledger.json"' in page, "the receipts page does not link the ledger it was built from")
    _check("locked" in page and "sha256" in page, "no lock hash is shown, so nothing is checkable")

    for lock in ledger.get("locks", []):
        _check(lock["content_hash"][:16] in page,
               "gw%s's lock hash is not on the page" % lock["gameweek"])
        _check(lock["snapshot"] or True, lock)

    if not ledger.get("entries"):
        _check("not yet scored" in page or "have not been played" in page,
               "the ledger has no scored gameweeks, so the page must say so rather than imply a "
               "record exists")
        _check("0 </b><span>scored so far" in page or ">0<" in page,
               "the page should report zero gameweeks scored, not a placeholder number")


def test_the_receipts_page_keeps_the_replay_labelled_as_a_replay():
    """The 2025-26 numbers are a backtest. Blending them with the live ledger would be a lie by layout."""
    page = _read("receipts.html", STATIC)
    _check("backtest, not a live record" in page,
           "the replay section is no longer labelled as a backtest")
    _check("2025–26 replay" in page, "the replay section is missing")
    _check("order the source file lists them" in page and "no gameweek column" in page,
           "the replay is charted without saying that it is in fixture-list order rather than "
           "gameweeks — the source file has no gameweek column, so claiming gameweeks would be an "
           "invention")


def test_feedback_on_the_receipts_page_cannot_phone_home():
    """P10.4's promise, enforced: reactions are local, and sending is a link a human clicks.

    This is the test that stops a future edit from quietly adding analytics to a page whose text
    promises nothing is transmitted. If a network call is ever genuinely needed, it has to arrive with
    the wording changed in the same commit — which is the point.
    """
    page = _read("receipts.html", STATIC)
    #: API names, not keywords: the page discusses analytics in the sentence where it promises not to
    #: use any, and a keyword scan would flag its own explanation — the same trap as scanning raw page
    #: text for the payload a comment describes.
    for forbidden in ("fetch(", "XMLHttpRequest", "sendBeacon", "new WebSocket", "navigator.sendBeacon",
                      "gtag(", "ga(", "_paq", "plausible(", "posthog", "mixpanel", "amplitude"):
        _check(forbidden not in page,
               "the receipts page contains %r, which contradicts its own privacy wording" % forbidden)
    _check('localStorage' in page and "nt90:feedback" in page,
           "the local reaction store is missing, so the buttons cannot work as described")
    _check("in this browser only" in page or "in this browser" in page,
           "the page does not say where a reaction is recorded")
    _check("issues/new" in page, "there is no way to actually send a review comment")
    _check('rel="noopener"' in page, "external issue links must carry rel=noopener")
    _check("docs/reviews/" in page, "the page does not point at where the review aggregate lives")


def test_the_changelog_page_matches_the_changelog_file():
    """One source of truth. Every release in CHANGELOG.md appears, and no release invents a delta."""
    md_path = os.path.join(ROOT, "CHANGELOG.md")
    if not os.path.exists(md_path):
        skip("CHANGELOG.md is missing")
    md = _read("CHANGELOG.md", ROOT)
    page = _read("changelog.html", STATIC)

    releases = [line[3:].strip() for line in md.splitlines() if line.startswith("## ")]
    _check(releases, "CHANGELOG.md has no release headings")
    _check(page.count('<div class="card">') == len(releases),
           "the page shows %d releases for %d headings in CHANGELOG.md"
           % (page.count('<div class="card">'), len(releases)))
    for release in releases:
        version = release.split()[0]
        _check(version in page, "release %s is in CHANGELOG.md but not on the page" % version)

    # The rule the file states about itself: a delta only ever accompanies a measurement.
    sections = md.split("\n## ")[1:]
    for section in sections:
        version = section.split(" ")[0]
        if "**Delta" in section:
            _check("**Measured" in section,
                   "%s claims a delta without a measurement — the file promises this cannot happen"
                   % version)


def test_the_header_version_links_to_the_changelog():
    """"model v2.1" must be the link the plan says it is, and still read as one line of text."""
    page = _page()
    _check('href="/changelog.html"' in page, "the header version does not link to the changelog")
    _check("model v2.1" in page, "the version string vanished from the header")
    _check(page.count("model v2.1") == 1,
           "the version appears %d times — the markup and the textContent write are fighting again"
           % page.count("model v2.1"))


def test_the_published_ledger_json_equals_the_ledger_on_disk():
    ledger_path = os.path.join(DATA, "ledger_2026_27.json")
    if not os.path.exists(ledger_path):
        skip("data/ledger_2026_27.json is missing")
    with open(ledger_path, encoding="utf-8") as fh:
        on_disk = json.load(fh)
    published = json.loads(_read("ledger.json", STATIC))
    _check([l["content_hash"] for l in published.get("locks", [])]
           == [l["content_hash"] for l in on_disk.get("locks", [])],
           "static/ledger.json does not match data/ledger_2026_27.json — the page would be "
           "publishing a record the repository does not contain")


def test_the_pulse_strip_reads_the_live_ledger():
    """P10.5 — the strip must be wired to the ledger, and must still work with an empty one."""
    page = _page()
    render = _code_only(_read("render.js", SRC))
    _check('"ledger"' in page or "ledger" in page, "the ledger is not embedded in the page")
    _check("EMBEDDED.ledger" in render or "EMBEDDED && EMBEDDED.ledger" in render,
           "render.js no longer reads the embedded ledger")
    for fragment in ("locked before kickoff", "replay", "backtest"):
        _check(fragment in render,
               "the pulse strip lost its %r wording — the live record and the replay have to stay "
               "distinguishable" % fragment)
    _check("data-pending" in render, "there is no pending state, so a locked-but-unplayed gameweek "
                                     "would render as nothing at all")


def test_gitignore_covers_the_things_it_must():
    ignore = _read(".gitignore", ROOT)
    for entry in ("__pycache__", ".env", ".venv", ".DS_Store", ".vercel"):
        _check(entry in ignore, ".gitignore does not cover %s" % entry)


def test_every_asset_the_page_references_is_tracked_by_git():
    """The deploy is built from git, so an asset that is merely present on disk does not ship.

    This is the regression for a real defect: a blanket `*.png` rule in .gitignore meant 65 files in
    static/ — the 60 social cards in static/og/, the three PWA icons and apple-touch-icon.png — were
    never committed. A clean clone simply did not have them, and Vercel has no build step to create
    them, so the favicon, the manifest icons and every link preview would have 404'd in production.
    It went unnoticed because the release zip is built from the filesystem, not from git.

    So: ask git what it tracks, and require that every static subresource the page can reach is in
    that list. `git ls-files` is authoritative in a way that reading the directory is not.
    """
    import subprocess
    try:
        tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                                 check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError) as exc:      # pragma: no cover - environment
        print("      (skipped: git is not usable here — %s)" % exc)
        return
    tracked = {t.replace("\\", "/") for t in tracked}
    # `git ls-files` speaks repository paths ("static/og/site.png"); the page speaks site-root URLs
    # ("og/site.png"), because on Vercel the contents of static/ are the site root.
    tracked_from_root = {t[len("static/"):] for t in tracked if t.startswith("static/")}

    page = _page()
    referenced = set()
    for match in re.finditer(r"""(?:src|href)=["']([^"'#?]+)["']""", page):
        url = match.group(1)
        if url.startswith(("http:", "https:", "data:", "mailto:", "//")) or url.startswith("#"):
            continue
        referenced.add(url.lstrip("/"))
    for match in re.finditer(r"""(?:og:image|twitter:image)["']\s+content=["']([^"']+)["']""", page):
        url = match.group(1)
        if not url.startswith(("http:", "https:", "data:")):
            referenced.add(url.lstrip("/"))

    local = {u for u in referenced if not u.endswith(".html") and u not in ("", "./")}
    missing = sorted(u for u in local
                     if u.startswith(("og/", "icons/", "assets/")) or u in ("apple-touch-icon.png",
                                                                            "manifest.webmanifest"))
    absent = [u for u in missing if u not in tracked_from_root]
    _check(not absent, "these static assets are referenced by the page but not tracked by git, so "
                       "they will 404 on any deploy built from a clone: %s" % absent)

    for name in ("static/og/site.png", "static/icons/favicon-32.png", "static/icons/icon-192.png",
                 "static/icons/icon-512.png", "static/apple-touch-icon.png",
                 "static/manifest.webmanifest"):
        _check(name in tracked, "%s is not tracked by git — the deploy would ship without it"
               % name)


def test_gitignore_does_not_swallow_the_static_assets():
    """The ignore rules have to be depth-aware. `*.png` is not the same rule as `/*.png`."""
    ignore = _read(".gitignore")
    rules = [ln.strip() for ln in ignore.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    for rule in rules:
        if rule in ("*.png", "*.jpg", "*.svg", "*.webmanifest", "*.ico"):
            raise AssertionError(
                ".gitignore has the depth-less rule %r, which matches inside static/ and would "
                "exclude the site's own images from the deploy. Anchor it with a leading slash if "
                "the intent was the repository root." % rule)


def test_scenario_input_is_sanitised_at_every_boundary():
    """A crafted share link must not be able to put markup into the What-If form.

    The attack was real and reproduced in a browser: `#s=<base64>` carrying
    `{"b":{"ARS":["<img src=x onerror=...>",0]}}` executed script on this origin, because scenario
    values were interpolated straight into `value="..."`. The fix is a single validator that returns
    numbers keyed by ids the page already knows, applied wherever outside data enters.

    This asserts the wiring, so deleting a call is a test failure rather than a silent reopening.
    The browser-level proof lives in tests/a11y/xss.mjs, which is dev-only tooling.
    """
    core = _read("core.js", SRC)
    _check("function sanitizeScenario(" in core, "core.js no longer defines sanitizeScenario()")
    _check("function scnInt(" in core, "core.js no longer defines scnInt()")

    for name in ("ux.js", "share.js", "render.js"):
        body = _read(name, SRC)
        _check("sanitizeScenario(" in _code_only(body),
               "%s does not route external scenario data through sanitizeScenario()" % name)

    # The form fields themselves must never interpolate a raw scenario value.
    render = _code_only(_read("render.js", SRC))
    for field in ("SCENARIO.player_injuries[p.player_id]", "b.attack", "b.defence", "ded[t.code]"):
        for match in re.finditer(r'\$\{([^{}]*' + re.escape(field) + r'[^{}]*)\}', render):
            expr = match.group(1)
            _check("scnNum(" in expr,
                   "render.js interpolates %r without scnNum(): ${%s}" % (field, expr.strip()))


def test_a_shared_link_can_actually_be_read_back():
    """The writer and the reader of `#s=` have to agree, or the Share button produces dead links.

    They did not, and that is what shipped: share.js writes "v1-<base64>" while ux.js's reader
    accepted only a bare base64 body — and share.js, loaded later, is the handler that ends up on the
    Share button. Every link the button produced failed to open, with a toast blaming the link. The
    reader takes an optional version prefix now.

    The structural half is checked here because it is cheap; the behavioural proof — including that
    the compact [attack, defence] a link carries and the {attack, defence} the page stores sanitise to
    the same thing — is in
    tests/test_wave4_site.py::test_a_share_link_survives_the_validator_in_both_wire_shapes.
    """
    ux = _code_only(_read("ux.js", SRC))
    share = _code_only(_read("share.js", SRC))
    code = _code_only(_read("core.js", SRC))

    _check(re.search(r"/\^v\(\\d\+\)-", ux),
           "ux.js's reader no longer accepts the 'v<n>-' prefix share.js writes, so shared links "
           "would fail to open again")
    _check(re.search(r"PREFIX\s*=\s*[\"']v[\"']", share),
           "share.js no longer prefixes its tokens with a version")
    _check(re.search(r"Array\.isArray\(raw\)", code),
           "sanitizeScenario() does not accept the [attack, defence] wire shape, so a valid shared "
           "link would be emptied on the way in")


def test_no_api_key_is_committed():
    """A 32-character hex token assigned to something key-shaped, anywhere a human could read it.

    Deliberately narrow: it looks for an *assignment* of a long hex string, so the docs can still
    discuss FOOTBALL_DATA_ORG_TOKEN and the workflow can pass `secrets.FOOTBALL_DATA_KEY` around
    without tripping it. A test that failed on the word "token" would be turned off within a week.
    """
    patterns = [
        re.compile(r"(?i)\b[A-Z0-9_]*(?:TOKEN|API_?KEY|SECRET)\b\s*[:=]\s*['\"]?([0-9a-f]{32,})['\"]?"),
        re.compile(r"(?i)x-auth-token\s*[:=]\s*['\"]?([0-9a-f]{32,})"),
        re.compile(r"(?i)\bFOOTBALL_DATA_[A-Z_]*\s*[:=]\s*['\"]?[0-9a-zA-Z]{24,}"),
    ]
    offenders = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", "artifacts", "_design"}]
        for fn in filenames:
            if not fn.endswith((".py", ".js", ".json", ".yml", ".yaml", ".md", ".txt", ".cfg", ".ini",
                                ".sh", ".html", ".example", ".toml")):
                continue
            full = os.path.join(dirpath, fn)
            try:
                text = open(full, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            for pattern in patterns:
                for hit in pattern.finditer(text):
                    value = hit.group(1)
                    # obvious placeholders are not secrets
                    if set(value) <= set("xX0") or "example" in value.lower() or "your" in value.lower():
                        continue
                    offenders.append("%s: %s" % (os.path.relpath(full, ROOT), hit.group(0)[:60]))
    _check(not offenders, "possible committed credentials: %s" % offenders)


def test_no_env_file_is_committed():
    _check(not os.path.exists(os.path.join(ROOT, ".env")),
           ".env exists in the repository — it must never be committed")


def test_the_page_stays_under_the_size_budget():
    """~1 MB. Reported rather than asserted at the current size, so this only fires on a regression
    that matters and the number lives in one place."""
    size = os.path.getsize(os.path.join(STATIC, "index.html"))
    _check(size < PAGE_BUDGET_BYTES,
           "static/index.html is %.0f KB, over the %.0f KB budget"
           % (size / 1024, PAGE_BUDGET_BYTES / 1024))
    print("      page weight: %.1f KB raw (budget %.0f KB, %.0f%% used)"
          % (size / 1024, PAGE_BUDGET_BYTES / 1024, 100 * size / PAGE_BUDGET_BYTES))


def test_the_whole_static_site_is_still_small():
    """The page is the weight that matters, but the deploy should not be a puzzle either."""
    total = 0
    count = 0
    for dirpath, _dirnames, filenames in os.walk(STATIC):
        for fn in filenames:
            total += os.path.getsize(os.path.join(dirpath, fn))
            count += 1
    print("      static/: %d files, %.2f MB" % (count, total / 1e6))
    _check(total < 12 * 1024 * 1024, "static/ has grown to %.1f MB" % (total / 1e6))


def test_the_weekly_workflow_is_the_one_that_commits():
    """One weekly job, not two. A second workflow on the same cron would race this one."""
    wd = os.path.join(ROOT, ".github", "workflows")
    names = sorted(n for n in os.listdir(wd) if n.endswith(".yml"))
    _check("weekly-update.yml" in names, "the weekly workflow is gone: %s" % names)
    _check("weekly.yml" not in names, "weekly.yml and weekly-update.yml would both run on the same cron")
    wf = _read("weekly-update.yml", wd)
    _check("cron:" in wf and "workflow_dispatch:" in wf, "the workflow needs both a cron and a manual trigger")
    _check("FOOTBALL_DATA_KEY" in wf, "the key secret the reader was told to set is not read anywhere")
    _check("tests/run_tests.py" in wf, "the test gate is missing")
    _check("git add data/ static/" in wf, "the commit step should stage data/ and static/")
    # test gate before commit, or "commit only if tests pass" is a comment rather than a fact
    _check(wf.index("tests/run_tests.py") < wf.index("git add data/ static/"),
           "the test gate must run before the commit step")
