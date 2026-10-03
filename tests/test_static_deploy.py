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
    page = _code_only(_page())
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
    """The app routes are rewrites to the dashboard; the generated .html pages are real files.

    /table is the app and /table.html is the crawlable page — the same split server.py makes. A
    `cleanUrls: true` here would quietly make /table serve the static page instead, which is a
    different site from the one the local server serves.
    """
    cfg = json.loads(_read("vercel.json", ROOT))
    _check(cfg.get("cleanUrls") is not True, "cleanUrls would shadow the generated .html pages")
    for rule in cfg["rewrites"]:
        dest = rule["destination"]
        _check(dest == "/index.html", "unexpected rewrite destination: %s" % dest)
        _check(not rule["source"].endswith(".html"),
               "a rewrite must not shadow a generated page: %s" % rule["source"])
    app_routes = {r["source"] for r in cfg["rewrites"]}
    for route in ("/table", "/awards", "/duel", "/whatif", "/model", "/matchweek"):
        _check(route in app_routes, "%s is an app route in server.py but not in vercel.json" % route)


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  Hygiene: secrets, ignore rules, weight
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_gitignore_covers_the_things_it_must():
    ignore = _read(".gitignore", ROOT)
    for entry in ("__pycache__", ".env", ".venv", ".DS_Store", ".vercel"):
        _check(entry in ignore, ".gitignore does not cover %s" % entry)


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
