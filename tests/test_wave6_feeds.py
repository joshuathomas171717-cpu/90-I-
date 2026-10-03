"""Wave 6 — the calendar feeds (P8.3).

The lesson from Wave 5 is written into this file: assert the *right* thing, not merely that a string
is present somewhere. For a feed that means parsing it, not grepping it — an .ics that contains the
word BEGIN:VEVENT ten times and no CRLFs is still a broken subscription.

Written as module-level functions because that is what tests/run_tests.py collects; the first draft of
this file was a unittest.TestCase and the runner — which is deliberately dependency-free and does its
own discovery — did not see it at all. Twenty-nine tests reported as zero.
"""
import datetime
import os
import re
import sys

from _util import ROOT   # noqa: E402

sys.path.insert(0, ROOT)
import feeds  # noqa: E402

STATIC = os.path.join(ROOT, "static")


def _check(condition, message):
    if not condition:
        raise AssertionError(message)


def _summary():
    return feeds.load_summary()


def _fixtures():
    return feeds.load_fixtures()


def parse_ics(text):
    """A deliberately strict reader: unfold, then return the components as list-of-dicts.

    Strict because the point is to prove a real calendar client can read this. Unfolding is RFC 5545
    §3.1 — a CRLF followed by a single space continues the previous line — and property names are
    compared case-insensitively, as the spec requires.
    """
    _check("\r\n" in text, "no CRLF line endings anywhere")
    _check("\n" not in text.replace("\r\n", ""), "a bare LF survived")
    lines = text.split("\r\n")
    if lines and lines[-1] == "":
        lines.pop()
    # The octet limit applies to the lines as they appear in the file, before unfolding — an unfolded
    # line is long by construction, which is the whole reason folding exists.
    for line in lines:
        _check(len(line.encode("utf-8")) <= 75, "line over 75 octets: %r" % line[:80])
    unfolded = []
    for line in lines:
        if line.startswith((" ", "\t")):
            _check(unfolded, "continuation line with nothing to continue")
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    for line in unfolded:
        _check(":" in line, "not a content line: %r" % line)
    components, stack = [], []
    for line in unfolded:
        name, _, value = line.partition(":")
        name = name.split(";")[0].upper()
        if name == "BEGIN":
            stack.append({"_type": value.strip().upper()})
        elif name == "END":
            done = stack.pop()
            _check(done["_type"] == value.strip().upper(),
                   "END %s closed %s" % (value, done["_type"]))
            if stack:
                stack[-1].setdefault("_children", []).append(done)
            else:
                components.append(done)
        else:
            stack[-1][name] = value
            stack[-1].setdefault("_params", {})[name] = line.split(":", 1)[0]
    _check(not stack, "unclosed component")
    return components


def _league():
    return feeds.build(_summary(), _fixtures(), site_url="https://example.test")


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  The document
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_league_feed_parses_as_a_calendar():
    comps = parse_ics(_league())
    _check(len(comps) == 1, "expected exactly one VCALENDAR")
    cal = comps[0]
    _check(cal["_type"] == "VCALENDAR", "wrong root component")
    _check(cal["VERSION"] == "2.0", "VERSION must be 2.0")
    _check(cal["CALSCALE"] == "GREGORIAN", "CALSCALE missing")
    _check(cal["PRODID"].startswith("-//"), "PRODID must be a text value beginning -//")
    _check("NINETY+" in cal["PRODID"], "PRODID should name the generator")


def test_every_remaining_matchweek_becomes_one_event():
    events = parse_ics(_league())[0]["_children"]
    _check(len(events) == 32, "MW6..MW37 is 32 windows; got %d" % len(events))
    titles = []
    for ev in events:
        _check(ev["_type"] == "VEVENT", "child is not a VEVENT")
        for prop in ("UID", "DTSTAMP", "DTSTART", "DTEND", "SUMMARY", "DESCRIPTION", "URL"):
            _check(prop in ev, "event is missing %s" % prop)
        _check(re.fullmatch(r"\d{8}", ev["DTSTART"]), "DTSTART is not a date: %s" % ev["DTSTART"])
        _check(re.fullmatch(r"\d{8}", ev["DTEND"]), "DTEND is not a date")
        _check("VALUE=DATE" in ev["_params"]["DTSTART"], "all-day events need VALUE=DATE")
        _check("T" not in ev["DTSTART"], "a time was invented for a fixture window")
        titles.append(ev["SUMMARY"])
    _check(len(set(titles)) == len(titles), "two events share a title")


def test_the_window_is_the_event_not_an_invented_kick_off_time():
    """The honest bit. The dataset has matchweek windows, not kick-off times, so the feed must not
    invent ten Saturday 15:00s — three of them would be wrong and nobody could tell which."""
    first = parse_ics(_league())[0]["_children"][0]
    _check(first["DTSTART"] == "20261010", "MW6 starts 10 October: %s" % first["DTSTART"])
    _check(first["DTEND"] == "20261013", "DTEND is exclusive — 12 Oct means the 13th")
    _check("Matchweek 6" in first["SUMMARY"], "title should name the matchweek")


def test_re_subscribing_updates_rather_than_duplicates():
    """Same season, same club, same matchweek -> same UID, whatever else changes between builds."""
    a = feeds.build(_summary(), _fixtures(), club="ARS", site_url="https://one.test")
    b = feeds.build(_summary(), _fixtures(), club="ARS", site_url="https://two.test")
    uids_a = [e["UID"] for e in parse_ics(a)[0]["_children"]]
    uids_b = [e["UID"] for e in parse_ics(b)[0]["_children"]]
    _check(uids_a == uids_b, "UIDs must not depend on anything that varies per build")
    _check(len(set(uids_a)) == len(uids_a), "duplicate UID inside one feed")
    league_uids = {e["UID"] for e in parse_ics(_league())[0]["_children"]}
    _check(not (league_uids & set(uids_a)),
           "a club feed and the league feed must not claim the same identity")


def test_build_is_pure():
    """Same inputs, byte-identical output — so a diff means the data moved, not the clock."""
    one = feeds.build(_summary(), _fixtures(), club="LIV")
    two = feeds.build(_summary(), _fixtures(), club="LIV")
    _check(one == two, "two builds of the same feed differ")
    _check(_league() != one, "the league feed and a club feed should not be identical")


def test_folding_is_by_octets_not_characters():
    event = parse_ics(feeds.build(_summary(), _fixtures(), club="BHA"))[0]["_children"][0]
    _check("Brighton" in event["DESCRIPTION"], "splitting a multi-byte character corrupts the line")
    _check("\u2014" in event["DESCRIPTION"], "the em dash should survive folding intact")


def test_escaping_protects_the_structure():
    nasty = [{"gw": 6, "dates": "10-12 October 2026", "home": "A, B", "away": "C; D",
              "prob_home": 50, "prob_draw": 25, "prob_away": 25, "top_score": "1-0"}]
    ev = parse_ics(feeds.build(_summary(), nasty))[0]["_children"][0]
    _check("A\\, B vs C\\; D" in ev["DESCRIPTION"], "commas and semicolons must be escaped")
    _check("\n" not in ev["SUMMARY"], "a real newline must never reach a property value")


def test_no_tracking_parameters_anywhere():
    """A subscription URL is the only identifier this feature is allowed to have."""
    for text in (_league(), feeds.build(_summary(), _fixtures(), club="MCI",
                                        site_url="https://example.test")):
        lowered = text.lower()
        for needle in ("utm_", "?id=", "&user", "analytics", "ref="):
            _check(needle not in lowered, "tracking parameter %r found in a feed" % needle)


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  The data in them
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_club_feed_carries_only_that_clubs_fixtures():
    comps = parse_ics(feeds.build(_summary(), _fixtures(), club="ARS"))
    events = comps[0]["_children"]
    _check(events, "Arsenal have no fixtures left")
    for ev in events:
        _check("Arsenal" in ev["SUMMARY"], "a rival's fixture leaked into a club feed: %s" % ev["SUMMARY"])
    _check("Arsenal" in comps[0]["X-WR-CALNAME"],
           "the calendar name should be the club's name, not its code: %s" % comps[0]["X-WR-CALNAME"])


def test_every_club_has_a_feed_of_remaining_fixtures_only():
    fixtures = _fixtures()
    codes = {f["home"] for f in fixtures} | {f["away"] for f in fixtures}
    _check(len(codes) == 20, "expected 20 clubs, found %d" % len(codes))
    for code in sorted(codes):
        events = parse_ics(feeds.build(_summary(), fixtures, club=code))[0]["_children"]
        _check(events, "%s has no fixtures left" % code)
        gws = sorted(int(re.search(r"Matchweek (\d+)", e["SUMMARY"]).group(1)) for e in events)
        _check(gws[0] == 6, "%s's feed starts at matchweek %d, not the next one" % (code, gws[0]))
        _check(gws == sorted(set(gws)), "%s has a duplicated matchweek" % code)


def test_the_page_that_lists_the_feeds_exists_and_is_crawlable():
    path = os.path.join(STATIC, "calendar.html")
    _check(os.path.exists(path), "site_pages.py must write the calendar page")
    with open(path, encoding="utf-8") as fh:
        page = fh.read()
    _check('href="/calendar/league.ics"' in page, "no league subscribe link")
    _check(page.count('href="/calendar/') == 21, "expected league + 20 club links")
    _check("all-day" in page, "the page must say what an entry actually is")
    with open(os.path.join(STATIC, "sitemap.xml"), encoding="utf-8") as fh:
        _check("calendar.html" in fh.read(), "the calendar page is missing from the sitemap")


def test_the_feeds_written_to_disk_match_the_builder():
    for name, kwargs in (("league.ics", {}), ("ars.ics", {"club": "ARS"}),
                         ("cov.ics", {"club": "COV"})):
        path = os.path.join(STATIC, "calendar", name)
        _check(os.path.exists(path), "%s was not written — run feeds.py" % name)
        with open(path, encoding="utf-8", newline="") as fh:
            on_disk = fh.read()
        _check(on_disk == feeds.build(_summary(), _fixtures(), **kwargs),
               "%s on disk is stale — the build did not rerun feeds.py" % name)


def test_parse_window_handles_the_shapes_in_the_calendar():
    start, end = feeds.parse_window("10-12 October 2026")
    _check((start, end) == (datetime.date(2026, 10, 10), datetime.date(2026, 10, 13)),
           "10-12 October should be the 10th to the 13th (exclusive end)")
    start, end = feeds.parse_window("24-25 October 2026")
    _check((end - start).days == 2, "a two-day window is two days long")
    _check(feeds.parse_window("nonsense")[0] is None, "rubbish should return None, not raise")
    _check(feeds.parse_window("")[0] is None, "empty input should return None")


def test_stdlib_calendar_is_not_shadowed():
    """feeds.py was called calendar.py for about ten minutes, and took /api/simulate down.

    The engine imports the standard library's calendar for date arithmetic, and a module in the
    project root wins over the stdlib. This fails if the file is ever renamed back.
    """
    _check(not os.path.exists(os.path.join(ROOT, "calendar.py")),
           "calendar.py shadows the stdlib module the engine imports")
    _check(ROOT in sys.path, "the project root is on sys.path, which is why it matters")
    import calendar as stdcal
    _check(hasattr(stdcal, "day_abbr") and hasattr(stdcal, "monthrange"),
           "the stdlib calendar module is not the real one")
