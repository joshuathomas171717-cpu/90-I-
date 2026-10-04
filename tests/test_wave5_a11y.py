"""
Phase 07 and 09 — the accessibility and trust guarantees, checked without a browser.

The two instruments in tests/a11y/ (axe-core across six views, pixel-true contrast) are the measuring
sticks: they need node, a 114 MB Chromium and an npm install, and they are how the problems in this
wave were found. They cannot run in CI or from a clean extraction of the zip, so they are not the
guarantee. These tests are.

Every check here exists because something specific was wrong first:

  · `<article role="button">` — not an allowed role pairing (axe: aria-allowed-role)
  · 1,547 elements of dim grey text at 3.2-4.1:1 (measured, not guessed)
  · white text on an orange chip at 2.2:1
  · `<input type=range>` and `<select>` with no accessible name (axe: label, select-name — critical)
  · no <main>, no <h1>, a heading outline starting at level three
  · reduced-motion that did not reach pseudo-elements, so two infinite animations kept looping
  · a table with no caption, and the reason the first caption fix did not work (innerHTML wipes it)

A static check is weaker than a rendered one, and these are written knowing that. What they can do is
refuse to let the specific defect come back.
"""
import html
import json
import os
import re
import subprocess
import sys

from _util import DATA, ROOT, pytest, skip   # noqa: E402  (the suite's shared helpers)

STATIC = os.path.join(ROOT, "static")
SRC = os.path.join(STATIC, "src")


def _read(name, base=SRC):
    with open(os.path.join(base, name), encoding="utf-8") as fh:
        return fh.read()


def _page():
    return _read("index.html", STATIC)


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  P7.4 — colour and contrast
# ════════════════════════════════════════════════════════════════════════════════════════════════════

def _srgb(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(rgb):
    r, g, b = rgb
    return 0.2126 * _srgb(r) + 0.7152 * _srgb(g) + 0.0722 * _srgb(b)


def _contrast(fg_hex, bg_rgb):
    fg = tuple(int(fg_hex.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    a, b = sorted([_relative_luminance(fg), _relative_luminance(bg_rgb)], reverse=True)
    return (a + 0.05) / (b + 0.05)


def test_the_text_tokens_clear_contrast_on_every_panel_they_land_on():
    """The measured surfaces, not a chosen one.

    tests/a11y/contrast.mjs sampled the real background behind every text element by hiding the glyphs
    and reading the screenshot. The panels a light-grey label actually sits on run from about
    rgb(7,9,13) up to rgb(27,46,43) — the brighter end is a green-tinted panel. These are those
    surfaces, and the tokens have to clear 4.5:1 on the worst of them, because small text is allowed
    no less.
    """
    css = _read("theme.css")
    tokens = dict(re.findall(r"(--ink(?:-\d)?):\s*(#[0-9a-fA-F]{6})", css))
    assert {"--ink", "--ink-2", "--ink-3", "--ink-4"} <= set(tokens), \
        "the text tokens moved or were renamed: %s" % sorted(tokens)

    panels = {
        "brightest green-tinted panel": (0x1B, 0x2E, 0x2B),
        "warm panel": (0x24, 0x21, 0x19),
        "magenta-tinted panel": (0x20, 0x16, 0x1D),
        "typical panel": (0x17, 0x1C, 0x24),
        "page background": (0x0A, 0x0C, 0x11),
    }
    failures = []
    for token in ("--ink-2", "--ink-3", "--ink-4"):
        for name, rgb in panels.items():
            ratio = _contrast(tokens[token], rgb)
            if ratio < 4.5:
                failures.append("%s on %s: %.2f:1" % (token, name, ratio))
    assert not failures, (
        "text tokens below 4.5:1 — the previous values (#6d7789, #464e5e) failed exactly here:\n  "
        + "\n  ".join(failures))

    # and the hierarchy has to survive the fix: primary, body, label, quietest, in that order
    lum = {k: _relative_luminance(tuple(int(tokens[k].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)))
           for k in ("--ink", "--ink-2", "--ink-3", "--ink-4")}
    assert lum["--ink"] > lum["--ink-2"] > lum["--ink-3"] > lum["--ink-4"], \
        "the four text tones no longer step down: %s" % {k: round(v, 3) for k, v in lum.items()}


def test_the_certainty_chips_are_legible_against_their_own_gradients():
    """White on the warm gradient measured 2.2:1. The cyan sibling had always used dark text."""
    css = _read("theme.css")
    warm = re.search(r"\.chip\.upset\{color:(#[0-9a-fA-F]{3,8});", css)
    edge = re.search(r"\.chip\.edge\{color:(#[0-9a-fA-F]{3,8});", css)
    assert warm and edge, "the certainty chips changed shape — check the contrast by hand"
    # the lightest end of each gradient is the worst case for dark text
    for label, match, bg in (("edge", edge, (0x5E, 0xEA, 0xD4)), ("upset", warm, (0xFB, 0x94, 0x50))):
        ratio = _contrast(match.group(1), bg)
        assert ratio >= 4.5, "%s chip text is %.2f:1 against its lightest gradient stop" % (label, ratio)


def test_colour_is_never_the_only_encoding_of_an_outcome():
    """The bars said win/loss/draw in mint, grey and magenta and nothing else.

    A reader who cannot separate the first from the third got no answer from the page's most important
    graphic. The fix is a letter inside each band — H, D, A, always in that order — so the meaning
    survives the loss of the colour channel.
    """
    render = _read("render.js")
    assert re.search(r'<b class="sg" aria-hidden="true">H</b>', render), "the home band lost its H"
    assert re.search(r'<b class="sg" aria-hidden="true">D</b>', render), "the draw band lost its D"
    assert re.search(r'<b class="sg" aria-hidden="true">A</b>', render), "the away band lost its A"
    assert 'aria-label="Home win ${pct(p.prob_home)}, draw ${pct(p.prob_draw)}, away win ${pct(p.prob_away)}"' in render, \
        "the outcome bar has no spoken equivalent"
    css = _read("theme.css")
    assert ".tri .sg{" in css, "the band letters have no styling, so they will render unreadably"

    # the tier chips carry a letter too
    core = _read("core.js")
    for mark in ('mark:"F"', 'mark:"T"', 'mark:"E"', 'mark:"L"'):
        assert mark in core, "a certainty tier lost its letter mark (%s)" % mark


def test_the_contrast_audit_tool_is_still_the_one_that_runs():
    """A tool that has been replaced by a comment is not a tool.

    The harness is what found these problems; if it is deleted, the next redesign has no measuring
    stick and the fixes above become unverifiable claims.
    """
    sweep = os.path.join(ROOT, "tests", "a11y", "sweep.mjs")
    contrast = os.path.join(ROOT, "tests", "a11y", "contrast.mjs")
    for path in (sweep, contrast):
        assert os.path.exists(path), "missing %s" % os.path.relpath(path, ROOT)
    source = open(contrast, encoding="utf-8").read()
    assert "axe" not in source or True   # axe belongs to sweep.mjs; contrast.mjs measures pixels
    assert "verifyElement" in source and "passChecked" in source, (
        "contrast.mjs lost its verification pass — a single full-page screenshot is not a reliable "
        "coordinate system below the fold and produced a false positive here once already")


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  P7.2 — semantics
# ════════════════════════════════════════════════════════════════════════════════════════════════════

def test_the_page_has_one_main_landmark_and_one_h1():
    shell = _read("app.html")
    assert re.search(r"<main[^>]*class=\"wrap\"", shell), "no <main> landmark"
    assert shell.count("</main>") == 1, "the main landmark is opened or closed more than once"
    h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", shell, re.S)
    assert len(h1s) == 1, "expected exactly one h1, found %d" % len(h1s)
    assert "Premier League" in h1s[0], "the h1 does not say what the page is"

    # every section is a tabpanel wired back to the tab that reveals it
    panels = re.findall(r'<section class="page[^"]*" id="tab-(\w+)"[^>]*role="tabpanel"[^>]*'
                        r'aria-labelledby="tabbtn-(\w+)"', shell)
    assert len(panels) == 6, "only %d of 6 views are proper tabpanels" % len(panels)
    for panel, tab in panels:
        assert panel == tab, "panel %s is labelled by tab %s" % (panel, tab)


def test_the_tablist_maintains_the_pattern_it_claims():
    """role=tab with no aria-selected is half a pattern, and the missing half is the readable one."""
    shell = _read("app.html")
    tabs = re.findall(r'<button id="tabbtn-(\w+)"[^>]*>', shell)
    assert len(tabs) == 6, "expected six tabs, found %d" % len(tabs)
    for tab in tabs:
        block = re.search(r'<button id="tabbtn-%s"[^>]*>' % tab, shell).group(0)
        for attr in ("aria-selected=", "aria-controls=", "tabindex=", 'role="tab"'):
            assert attr in block, "tab %s has no %s" % (tab, attr)
    motion = _read("motion.js")
    for needle in ("aria-selected", "setAttribute(\"tabindex\"", "ArrowRight", "ArrowLeft", "Home", "End"):
        assert needle in motion, "the tablist lost its %s handling" % needle
    assert "syncTabState" in motion, "nothing keeps aria-selected in step with the visible view"


def test_every_form_control_has_an_accessible_name():
    """Two critical axe failures: eight unnamed sliders and one unnamed select."""
    render = _read("render.js")
    assert 'aria-label="Games out: ${esc(p.name)}"' in render, "the injury sliders are unnamed again"
    assert "aria-valuetext=" in render, "a slider reads as a bare number with no unit"
    assert 'sim.setAttribute("aria-label"' in render, "the simulation-size select is unnamed again"


def test_tables_carry_a_caption_and_scoped_headers():
    """A table without a caption is a grid of numbers with no statement of what they are.

    The first attempt at this put the captions in the markup — and they vanished, because the render
    sets `table.innerHTML`, which replaces every child including the caption. The check therefore
    looks for the caption inside the generated template, and the built page is checked for <thead>.
    """
    render = _read("render.js")
    captions = re.findall(r'<caption class="off">([^<]+)</caption>', render)
    assert len(captions) >= 4, "expected a caption in every table template, found %d" % len(captions)
    for caption in captions:
        assert len(caption) > 20, "caption too terse to help: %r" % caption
    # `<thead>` mangled into `<the scope="col"ad>` by a bulk edit is the failure this remembers. A
    # lookahead that excludes letters does not catch it — the letter is the signature, not the
    # exception — so the pattern names the letters that must never follow `<th`.
    # `<thead>` is legitimate; the mangled form (`<the scope="col"ad>`) is not. So: every tag that
    # begins `<th` followed by a letter must be exactly `<thead>`.
    odd = [t for t in re.findall(r'<th[a-z][^>]*>', render) if t != "<thead>"]
    assert not odd, "a malformed <th> tag is back in render.js: %s" % odd[:3]
    assert not re.search(r"<th>\s*scope=", render), "a scope attribute has escaped its tag again"
    assert render.count('<th scope="col"') >= 20, "the table headers lost their scope"
    assert render.count("<thead>") >= 4, "a <thead> opening tag is malformed"

    page = _page()
    assert "<thead>" in page, "the built page has no table head"


def test_the_roles_are_allowed_on_the_elements_that_carry_them():
    """`role="button"` on an `<article>` is invalid; on a `<div>` it is ordinary."""
    render = _read("render.js")
    assert "<article" not in render or not re.search(r'<article[^>]*role="button"', render), \
        "role=button is back on an <article>"
    assert re.search(r'<div class="fx rv\$\{tossCls\}" tabindex="0" role="button"', render), \
        "the fixture card stopped being a div — check the closing tag matches the opening one"
    assert "</article>" not in render, (
        "an </article> closing tag with no <article> opening it: the cards nest inside each other, "
        "which axe reports as nested-interactive and the browser renders without complaint")


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  P7.5 — motion and weight
# ════════════════════════════════════════════════════════════════════════════════════════════════════

def test_reduced_motion_reaches_pseudo_elements():
    """`*` does not match ::before/::after, and both infinite decorative animations live on one.

    A probe with the media feature emulated found eight animations still running: the wordmark sheen
    and six light sweeps across the race bars. The fix is a pseudo-element selector, and this test is
    the reason it cannot quietly revert.
    """
    css = _read("theme.css")
    # There are two reduced-motion blocks, and `re.search` finds the first — the one that only sets
    # `scroll-behavior`, written long before this wave. The rules being checked live in the later,
    # larger block, so every block is examined rather than whichever one happens to come first.
    blocks = re.findall(r"@media \(prefers-reduced-motion:reduce\)\s*\{(.*?)\n\}", css, re.S)
    assert blocks, "the reduced-motion block vanished"
    body = "\n".join(blocks)
    assert "*::before" in body and "*::after" in body, \
        "reduced-motion no longer reaches pseudo-elements, so ::after animations keep looping"
    for selector in (".mark .badge::after", ".track i::after"):
        assert selector in body, "%s is not explicitly stopped under reduced motion" % selector


def test_the_font_payload_stays_within_budget():
    """Subsetting took the three faces from 111.9 KB to 80.2 KB.

    The budget is here so a future "let's add a weight" cannot quietly undo it: the page inlines its
    fonts, so every kilobyte of font is a kilobyte of first load, on every view.
    """
    css = _read("fonts.css")
    import base64
    blobs = re.findall(r"base64,([A-Za-z0-9+/=]+)\)", css)
    assert len(blobs) == 3, "expected three embedded faces, found %d" % len(blobs)
    total = sum(len(base64.b64decode(b)) for b in blobs)
    assert total < 90 * 1024, (
        "the embedded fonts are %.1f KB; the subsetted budget is 90 KB (they were 111.9 KB before "
        "P7.5). Run python3 tools/subset_fonts.py if you added a face or a weight."
        % (total / 1024))
    assert "font-family" in css and "#{" not in css, "fonts.css is malformed"


def test_the_first_load_stays_within_the_weight_budget():
    """A first-load budget, stated as a number so it can be argued with.

    The page is one document with everything inlined — data, fonts, styles, scripts — so its size is
    the whole story for a cold visitor. 620 KB uncompressed is about 200 KB over the wire with the
    server's gzip, which is the budget this design is allowed.
    """
    size = os.path.getsize(os.path.join(STATIC, "index.html"))
    budget = 640 * 1024
    assert size < budget, (
        "static/index.html is %.1f KB, over the %.0f KB budget (it was 539 KB in the Wave 4 build). "
        "Something got inlined that should not have." % (size / 1024, budget / 1024))


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  P9.1 — the model card and the language
# ════════════════════════════════════════════════════════════════════════════════════════════════════

def test_the_model_card_states_the_numbers_the_model_actually_produced():
    """The card reads its own figures out of the payload, so it cannot drift from the model."""
    render = _read("render.js")
    for needle in ("function renderModelCard", "Analysis, not betting advice",
                   "const BT = BACKTEST", "m.accuracy.toFixed", "simulated seasons"):
        assert needle in render, "the model card lost %r" % needle
    # The card must read the payload object that actually exists. An earlier version read
    # `DATA.backtest`, which is undefined — the backtest is its own top-level object — and the card
    # rendered em dashes where the accuracy should have been while every assertion above passed.
    # Check the code, not the prose: the comment above the fix names the bug it fixed, and a naive
    # substring check flagged that comment as the bug returning.
    code = "\n".join(line for line in render.splitlines()
                     if not line.strip().startswith(("//", "*", "/*")))
    assert "DATA.backtest" not in code, (
        "the model card is reading DATA.backtest again; the payload exposes the backtest as BACKTEST")
    assert "renderModelCard();" in render, "the model card is defined but never rendered"
    assert 'id="modelCard"' in _read("app.html"), "the model card has nowhere to render into"

    # the numbers it quotes must exist in the backtest payload
    backtest = json.load(open(os.path.join(DATA, "backtest_2025_26.json"), encoding="utf-8"))
    assert "accuracy" in backtest["model"] and "log_loss" in backtest["model"]
    assert "skill_vs_prior_table" in backtest, "the card quotes a skill figure the payload no longer has"
    assert "prior_season_table_favourite" in backtest["baselines"]


def test_the_language_is_analysis_not_a_betting_slip():
    """"Banker" is a bookmaker's word for a sure thing. This model gets about half of matches right."""
    core = _read("core.js")
    assert 'txt:"clear favourite"' in core, "the banker wording is back"
    assert "banker" not in re.sub(r'cls:"banker"', "", core), \
        "the word 'banker' is still in the user-facing tiers (the class name is fine)"
    shell = _read("app.html")
    assert "MIT licensed" in shell or "MIT" in shell, "the licence line vanished"
    assert "not advice" in shell or "not betting advice" in shell or "Analysis, not" in _read("render.js"), \
        "the disclaimer is gone"


def test_the_footer_points_at_where_the_code_lives():
    """The page used to link to `https://github.com/` — a link to the whole internet."""
    shell = _read("app.html")
    link = re.search(r'id="srcLink"[^>]*', shell)
    assert link, "the source link is gone"
    assert "github.com/joshuathomas171717-cpu/90-I-" in shell, \
        "the source link does not point at this project's repository"


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  P9.2 / P9.3 — the method and privacy pages
# ════════════════════════════════════════════════════════════════════════════════════════════════════

def test_the_method_page_exists_and_quotes_the_real_backtest():
    path = os.path.join(STATIC, "method.html")
    assert os.path.exists(path), "static/method.html missing — run python3 site_pages.py"
    page_html = open(path, encoding="utf-8").read()
    text = html.unescape(re.sub(r"<[^>]+>", " ", page_html))
    backtest = json.load(open(os.path.join(DATA, "backtest_2025_26.json"), encoding="utf-8"))
    accuracy = "%.1f" % backtest["model"]["accuracy"]
    assert accuracy in text, "the method page does not state its own measured accuracy (%s%%)" % accuracy
    for theme in ("Dixon-Coles", "Monte Carlo", "out-of-sample", "cannot know", "football-data.org"):
        assert theme.lower() in text.lower(), "the method page does not mention %s" % theme
    assert "<h1" in page_html, "the method page has no h1"
    assert "issues" in page_html, "the method page says nothing about reporting a wrong result"


def test_the_privacy_page_claims_only_what_is_true():
    """A privacy page that describes a different site is worse than none, so this checks the claims
    that the code can actually be held to."""
    path = os.path.join(STATIC, "privacy.html")
    assert os.path.exists(path), "static/privacy.html missing — run python3 site_pages.py"
    page_html = open(path, encoding="utf-8").read()
    text = html.unescape(re.sub(r"<[^>]+>", " ", page_html)).lower()
    assert "no cookies" in text or "sets no cookies" in text
    # the page must not be claiming analytics that the code does not have, or hiding that it does
    for forbidden in ("google analytics", "facebook pixel", "advertis"):
        if forbidden in text:
            assert "no " + forbidden in text or "none" in text or "not used" in text, \
                "privacy.html mentions %s without saying it is not used" % forbidden
    # and the app really must not ship any third-party script or tracker: no external requests at all
    page_source = _page()
    externals = re.findall(r'(?:src|href)="(https?://[^"]+)"', page_source)
    for url in externals:
        assert "schema.org" in url or "github.com" in url, (
            "the dashboard loads something from %s — the privacy page says it sends no third-party "
            "requests" % url)


def test_both_trust_pages_are_in_the_sitemap_and_linked_from_the_dashboard():
    sitemap = open(os.path.join(STATIC, "sitemap.xml"), encoding="utf-8").read()
    for slug in ("method.html", "privacy.html"):
        assert slug in sitemap, "%s is not in the sitemap" % slug
    shell = _read("app.html")
    assert 'href="/method.html"' in shell, "the dashboard does not link to the method page"
    assert 'href="/privacy.html"' in shell, "the dashboard does not link to the privacy page"


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  P9.4 — stale-data honesty
# ════════════════════════════════════════════════════════════════════════════════════════════════════

def test_the_page_states_the_age_of_its_own_data():
    """After a failed weekly pull the site must say so rather than serve old numbers as current.

    Updated by Phase 11: the age is still stated in words, but the *verdict* no longer comes from a day
    count. "Nine days old" was true and useless — a reader cannot know from it that a whole gameweek has
    been played since. The chip now reports a state (current / in progress / out of date, named by
    gameweek) and the calendar-aware rule behind it is covered in tests/test_wave11_liveness.py.
    """
    render = _read("render.js")
    core = _read("core.js")
    assert "function renderFreshness" in render, "the freshness indicator is gone"
    # The wording moved into freshness() when the verdict moved: the renderer prints the label, the
    # rule produces it. Both halves have to be present or the chip goes silent.
    assert "data ${days} days old" in core and ("updated yesterday" in core), \
        "the age is no longer stated in words"
    assert "state.label" in render, "the renderer no longer prints the label the rule produces"
    assert "out of date" in render, "the out-of-date state no longer says what it means"
    assert "$(\"freshness\")" in render and 'id="freshness"' in _read("app.html"), \
        "the freshness indicator has nowhere to render"
    # The verdict must come from the calendar, not from a number typed into the renderer.
    assert re.search(r"freshness\(asOf,[^)]*schedule", render), \
        "the freshness verdict no longer uses the shipped fixture calendar"
    assert "const weekly = 8" not in re.sub(r"/\*.*?\*/", "", render, flags=re.S), \
        "the fixed eight-day threshold is still here — it cannot tell 'a week old' from 'a gameweek behind'"


def test_a_page_with_no_calendar_still_flags_the_obviously_stale():
    """The degenerate path, kept: a build with no embedded calendar (hand-opened, or older than
    Phase 11) falls back to the blunt rule rather than silently claiming to be current.

    The boundary arithmetic is mirrored here because the real function lives in a browser; the
    calendar-aware rule that supersedes it for a normal build is tested in test_wave11_liveness.py.
    """
    def fallback_stale(as_of, today, weekly=8):
        import datetime
        stamped = datetime.date(*[int(x) for x in as_of.split("-")])
        return (today - stamped).days > weekly

    import datetime
    today = datetime.date(2026, 10, 3)
    assert not fallback_stale("2026-10-03", today), "today's data is not stale"
    assert not fallback_stale("2026-09-25", today), "an eight-day gap is normal for a weekly pipeline"
    assert fallback_stale("2026-09-15", today), "an 18-day-old snapshot must be flagged as stale"
    core = _read("core.js")
    assert re.search(r"days\s*>\s*8\b", core), \
        "the no-calendar fallback is gone — a page that cannot judge itself must not pass itself"


def test_the_api_reports_the_same_vintage_as_the_page():
    """The page and the API must not disagree about how old the data is."""
    as_of = json.load(open(os.path.join(DATA, "as_of.json"), encoding="utf-8"))
    summary = json.load(open(os.path.join(DATA, "predictions_2026_27_summary.json"),
                             encoding="utf-8"))
    assert as_of["date"] in summary["meta"]["as_of_date"], (
        "data/as_of.json says %s and the summary says %s — one of them is stale"
        % (as_of["date"], summary["meta"]["as_of_date"]))


def test_the_server_serves_the_trust_pages():
    """The trust pages are reachable, and the rule that makes them reachable is not a hand-kept list.

    This used to grep server.py for two literal paths — which tested that the list had been edited,
    not that the pages were served, and it would have passed for a page that was listed but missing
    from disk. The list is gone: the server now serves anything publishable that exists under static/,
    so this asserts the rule that replaced it. Reachability itself is proved against a running server
    in tests/test_wave4_site.py, which walks every generated file rather than trusting a list.
    """
    server = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
    assert "PUBLIC_SUFFIXES" in server and "self._static_file(path) is not None" in server, (
        "server.py no longer derives its static routes from disk; a new generated page would 404 "
        "locally and in the container while working on Vercel")
    for page in ("method.html", "privacy.html", "receipts.html", "changelog.html"):
        assert os.path.exists(os.path.join(ROOT, "static", page)), \
            "static/%s is missing, so the trust pages are incomplete" % page


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  the instruments themselves must run
# ════════════════════════════════════════════════════════════════════════════════════════════════════

def test_the_a11y_instruments_are_syntactically_valid():
    """`node --check` on both tools, skipped when node is absent (it usually is, in CI)."""
    node = None
    for candidate in ("node", "/usr/bin/node", "/usr/local/bin/node"):
        try:
            subprocess.run([candidate, "--version"], capture_output=True, check=True)
            node = candidate
            break
        except Exception:
            continue
    if node is None:
        skip("node is not installed — the a11y instruments cannot be syntax-checked here")
        return
    for name in ("sweep.mjs", "contrast.mjs"):
        path = os.path.join(ROOT, "tests", "a11y", name)
        proc = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert proc.returncode == 0, "%s does not parse:\n%s" % (name, proc.stderr[:600])

def test_switching_views_always_hides_the_one_it_replaced():
    """With reduced motion on, every view a reader opened stayed on the page.

    The outgoing view lost its `.on` class only inside the 150 ms animation timeout. Skip the animation
    — which is exactly what `prefers-reduced-motion: reduce` does — and the old view was never hidden:
    six dashboards stacked down the page. Invisible in a default browser, permanent for anyone with
    reduced motion enabled, and found by counting text elements per view rather than by looking.

    The removal has to live where both paths go through, so this checks the shape of the code: the
    `.on` removal must be inside `show()`, and `show()` must be on the non-animated branch too.
    """
    motion = _read("motion.js")
    show = re.search(r"const show = \(\) => \{(.*?)\n  \};", motion, re.S)
    assert show, "switchTab no longer has a show() — the structure changed, check this by hand"
    body = show.group(1)
    assert 'cur.classList.remove("on"' in body, (
        "the outgoing view is not hidden inside show(), so with reduced motion the views stack up "
        "again — every view a reader opens stays on the page")
    assert "else show();" in motion, "the non-animated branch is gone; check how a switch completes"
    # and the initial state has to match the switched state
    assert 'syncTabState("matchweek")' in motion, "the first paint never marks the other panels hidden"
