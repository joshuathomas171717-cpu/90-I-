"""Wave 6 — following clubs, saving scenarios, remembering the last view (P8.1, P8.2).

These are assertions about the *shipped page*, because CI installs Python and not Node: the behaviour
of store.js in a real browser is exercised by tools/setup_browser_tools.sh plus tests/a11y/*.mjs,
which are dev instruments and deliberately outside this suite. What this file proves is the wiring —
that the page a reader downloads contains the store, that the store is emitted before the code that
reads it, that the controls the code reaches for exist, and that what the project says about privacy is
true of the code that ships.

The Wave-5 lesson applies: assert the right binding is present *and* the wrong one absent, and strip
comments before a negative check so an explanatory comment cannot pass for code.
"""
import os
import re

from _util import ROOT   # noqa: E402

SRC = os.path.join(ROOT, "static", "src")
STATIC = os.path.join(ROOT, "static")


def _check(condition, message):
    if not condition:
        raise AssertionError(message)


def _read(path, base=None):
    with open(os.path.join(base, path) if base else path, encoding="utf-8") as fh:
        return fh.read()


def _src(name):
    return _read(name, SRC)


def _index():
    return _read("index.html", STATIC)


def _code_only(text):
    """Strip // comments and /* */ blocks so a negative assertion is about code, not prose."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  The store reaches the page, in the right order
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_built_page_contains_the_store():
    index = _index()
    _check("NT90_STORE" in index, "store.js was not emitted into the page")
    _check(re.search(r'NAMESPACE\s*=\s*"nt90"', index),
           "the store's namespace is missing from the built page")


def test_the_store_is_emitted_before_the_code_that_uses_it():
    """Ordering is load-bearing: render.js reads window.NT90_STORE at call time, not at definition
    time, so a wrong order here is a page that silently forgets everything."""
    index = _index()
    _check(index.index("NT90_STORE") < index.index("function renderFollowState"),
           "store.js must come before render.js in the built page")


def test_the_parts_tuple_lists_the_store_first():
    build = _read("build_dashboard.py", ROOT)
    parts = re.search(r'PARTS\s*=\s*\((.*?)\)', build, re.S) or \
        re.search(r'parts\s*=\s*\{(.*?)\}', build, re.S)
    _check(parts is not None, "could not find the parts definition in build_dashboard.py")
    _check("store.js" in parts.group(1), "store.js is not among the parts")


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  The controls
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_every_id_the_code_reaches_for_is_defined_somewhere():
    """Every $("…") and getElementById("…") in render.js and router.js, against every id defined
    anywhere in the sources.

    A missing id is not a crash here — $() returns null and the optional chaining swallows it — which
    is exactly why it needs a test: the failure mode is silence, and it is how "the star buttons do
    nothing" would have shipped. The first cut looked only at app.html and reported five false
    positives, because render.js legitimately creates ids in the markup it generates
    (#resetScenTop, #pulseMore, #kbdBtn, #mineOnlyBtn …). The question is whether an id is defined
    anywhere, not whether it is in the shell.
    """
    wanted = set()
    for source in (_code_only(_src("render.js")), _code_only(_src("router.js"))):
        wanted |= set(re.findall(r'\$\("([A-Za-z0-9_\-]+)"\)', source))
        wanted |= set(re.findall(r'getElementById\("([A-Za-z0-9_\-]+)"\)', source))
    defined = set()
    for part in sorted(os.listdir(SRC)):
        if part.endswith((".js", ".html")):
            defined |= set(re.findall(r'id="([A-Za-z0-9_\-]+)"', _src(part)))
    missing = sorted(w for w in wanted if w not in defined)
    _check(not missing, "ids the code looks up that nothing ever defines: %s" % missing)


def test_the_wave_six_controls_are_present():
    app = _src("app.html")
    have = set(re.findall(r'id="([^"]+)"', app))
    for need in ("myClubsToggle", "gwMineNote", "savedPanel", "scenName", "saveScen",
                 "savedList", "storeState", "forgetAll"):
        _check(need in have, "missing control: #%s" % need)
    _check('aria-pressed' in app, "the club filter is a toggle and must say so")


def test_the_follow_filter_is_wired_to_the_render_state():
    render = _code_only(_src("render.js"))
    for needle in ("function renderFollowState", "function wireStars",
                   'wireStars($("fullTable"))', "renderFollowState()"):
        _check(needle in render, "render.js is missing %s" % needle)
    _check(re.search(r"starButton\(r\.code, r\.short\)", render),
           "the standings rows do not carry a star")


def test_the_last_view_is_remembered_and_restored():
    router = _code_only(_src("router.js"))
    _check("function restoreLastView" in router, "no restoreLastView")
    _check('store.set("lastView"' in router, "the view is never remembered")
    _check('store.get("lastView"' in router, "the remembered view is never read")


def test_restore_guards_on_the_url_not_the_view():
    """A URL that names a view must beat the remembered one, and the guard has to be on the URL:
    "/" and "/matchweek" both parse to {view:"matchweek"}, so a view-based test sent an explicit
    /matchweek link to whatever was last remembered — it rewrote the address bar to /table. That
    shipped in the first cut and was caught by driving the real page, not by reading the code.
    """
    router = _code_only(_src("router.js"))
    tail = router[router.index("const route = parse(location.pathname);"):]
    _check("const bare = " in tail, "the restore branch must test the URL, not the parsed view")
    _check("if(!bare){" in tail, "the explicit-route branch should key off `bare`")
    _check(tail.index("const bare = ") < tail.index("restoreLastView()"),
           "the URL must be inspected before anything is restored")
    body = router[router.index("function restoreLastView"):]
    _check('getElementById("tab-" + last)' in body,
           "a remembered view that is not on the page must not be switched to")


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  What the project says about itself
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_privacy_describes_local_storage():
    """The store made three true statements on the privacy page false; it has to stay in step."""
    privacy = _read("privacy.html", STATIC).lower()
    _check("local storage" in privacy, "the privacy page does not mention local storage")
    for thing in ("follow", "what-if", "view"):
        _check(thing in privacy, "the privacy page does not name what is stored (%s)" % thing)
    _check("nothing persistent" not in privacy, "the page still claims nothing is stored")
    _check("it starts fresh" not in privacy, "the page still claims a reload resets everything")


def test_the_store_only_ever_writes_namespaced_keys():
    """No cookie, no stray second key, no throwing the session somewhere else.

    Every write goes to KEY (the state blob), KEY + ":corrupt" (the quarantine copy of data the store
    refused to parse) or the one-off probe that discovers whether localStorage works at all — all
    three built from the single NAMESPACE. (The first version of this pattern was '"[a-z]+"', which
    cannot match '":corrupt"' because of the colon. It reported the store as writing an unrecognised
    key, which was the regex's fault and not the store's.)
    """
    store = _src("store.js")
    targets = re.findall(r'\.(?:setItem|removeItem)\(\s*([A-Za-z0-9_]+(?:\s*\+\s*"[^"]*")?)', store)
    _check(targets, "the store should write something")
    _check(sorted(set(targets)) == ['KEY', 'KEY + ":corrupt"', 'probe'],
           "an unexpected storage target: %s" % sorted(set(targets)))
    _check(re.search(r'KEY\s*=\s*NAMESPACE\s*\+', store), "KEY is not namespaced")
    _check(re.search(r'probe\s*=\s*NAMESPACE\s*\+', store), "the probe key is not namespaced")
    _check("document.cookie" not in store, "the store must not set cookies")


def test_forgetting_really_forgets():
    """A quarantined copy of the reader's data must not outlive "Forget everything"."""
    store = _src("store.js")
    clear = store[store.index("clear: function"):]
    clear = clear[:clear.index("favourites: function")]
    _check('removeItem(KEY + ":corrupt")' in clear,
           "clear() leaves the quarantined copy of the reader's data behind")


def test_the_store_degrades_instead_of_throwing():
    """Preview iframes, private windows and full quotas all throw. A memory fallback, not a crash.

    There is no memoryStorage *function* to look for — the fallback is a plain object written to
    whenever the real backend is missing or refuses a write — so this asserts the mechanism. (The
    first version of this test looked for a function that never existed, which is the same mistake as
    asserting a wrong-string-is-present: it proved nothing.)
    """
    store = _src("store.js")
    _check(re.search(r'if\s*\(\s*!\s*store\s*\)\s*\{[^}]*memory', store),
           "no in-memory fallback when storage is unavailable")
    _check(re.search(r'degraded: function \(\) \{ return !backend\(\)', store),
           "degraded() does not report an absent backend")
    _check(re.search(r'catch \([a-z0-9]+\) \{', store), "storage access is not wrapped in try/catch")


def test_the_calendar_page_is_discoverable_from_the_dashboard():
    app = _src("app.html")
    _check('href="/calendar.html"' in app, "nothing links to the calendar page")
    _check('href="/method.html"' in app, "the absolute-link rule from earlier waves")
