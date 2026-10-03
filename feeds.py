#!/usr/bin/env python3
"""iCal feeds for the 2026-27 season — one per club, plus the whole league (P8.3).

This file is called feeds.py and not calendar.py on purpose. The project is flat — every module sits
in the project root, which the runner puts on sys.path — so a local calendar.py shadows the standard
library's calendar module for the whole process. It did, briefly: the simulation engine imports
calendar for date arithmetic, and naming this file after it took /api/simulate down with
"AttributeError: module 'calendar' has no attribute 'day_abbr'". The readiness endpoint caught it
before anything was pushed. Do not rename this back.

Why this and not accounts: a calendar feed is the one piece of "personalisation" that needs no
account, no email, no cookie and no server-side memory of who you are. The URL *is* the
subscription. That is why it ships before P8.4.

What the feed can honestly say
------------------------------
The Premier League publishes each matchweek as a window ("10-12 October 2026") and confirms exact
kick-off times closer to the date, when television picks its slots. The dataset this project holds has
the windows and not the slots, so the feed emits **one all-day event per matchweek** rather than
inventing a kick-off time. Ten events all claiming Saturday 15:00 would be wrong for the two or three
that move to Sunday, and a calendar that is confidently wrong is worse than one that is vague.

Each event carries the fixtures, the model's probabilities and a link to the gameweek page, so the
thing that lands in the calendar is worth reading on its own.

What it deliberately does not do
--------------------------------
No tracking parameters, no unique per-subscriber URL, no analytics. `build()` is a pure function of
the data: the same season produces byte-identical feeds, which is also what makes them testable.
"""
import datetime
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

#: Set NT90_SITE_URL to the deployed origin and every event carries an absolute link back.
SITE_URL = (os.environ.get("NT90_SITE_URL") or "").rstrip("/")
PRODID = "-//NINETY+//Premier League 2026-27 predictor//EN"
SEASON = "2026-27"

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"], start=1)}


def _esc(text):
    """RFC 5545 §3.3.11: backslash, semicolon, comma and newline are the four that must be escaped."""
    out = str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return out.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def _fold(line, limit=75):
    """RFC 5545 §3.1: content lines are folded at 75 octets, continuation lines start with a space.

    Folding is measured in octets, not characters, and this feed is full of em dashes and accented
    player names — so the measurement is done on the UTF-8 bytes while the split happens on character
    boundaries, because splitting a multi-byte character in half produces a file that parses in one
    calendar app and not another.
    """
    raw = line.encode("utf-8")
    if len(raw) <= limit:
        return [line]
    out, current, size = [], "", 0
    for ch in line:
        w = len(ch.encode("utf-8"))
        if size + w > limit:
            out.append(current)
            current, size = " " + ch, 1 + w
        else:
            current += ch
            size += w
    if current:
        out.append(current)
    return out


def parse_window(text):
    """'10-12 October 2026' -> (date(2026,10,10), date(2026,10,13)) — the end is exclusive, as iCal
    all-day events require. Handles '24-25 October 2026' and a window that crosses a month."""
    text = str(text or "").strip()
    m = re.match(r"^(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?\s+([A-Za-z]+)\s+(\d{4})$", text)
    if not m:
        return None, None
    start_day, end_day, month_name, year = m.groups()
    month = MONTHS.get(month_name.capitalize())
    if not month:
        return None, None
    start = datetime.date(int(year), month, int(start_day))
    if end_day:
        end = datetime.date(int(year), month, int(end_day))
    else:
        end = start
    if end < start:                      # a window that runs into the next month
        month = month % 12 + 1
        year = int(year) + (1 if month == 1 else 0)
        end = datetime.date(year, month, int(end_day))
    return start, end + datetime.timedelta(days=1)


def club_labels(summary):
    """CODE -> (full name, short name), from the season table the dashboard renders."""
    out = {}
    for row in (summary.get("table_projections") or []):
        code = row.get("code")
        if code:
            out[code] = (row.get("name") or code, row.get("short") or row.get("name") or code)
    return out


def fixture_events(summary, fixtures, club=None, site_url=None):
    """One event per matchweek — for the league, or for one club's fixtures within it.

    `fixtures` is a list of dicts with gw, dates, home, away, prob_home, prob_draw, prob_away, top_score.
    """
    site_url = (site_url if site_url is not None else SITE_URL).rstrip("/")
    events = []
    by_gw = {}
    for f in fixtures:
        by_gw.setdefault(int(f["gw"]), []).append(f)

    from fixtures_official import FIXTURES_2026_27    # the calendar of record, MW6 onward
    names = club_labels(summary)

    def nice(code):
        return names.get(code, (code, code))[0]

    for gw in sorted(by_gw):
        window = None
        if gw in FIXTURES_2026_27:
            window = FIXTURES_2026_27[gw][0]
        else:
            window = by_gw[gw][0].get("dates")
        start, end = parse_window(window)
        if not start:
            continue
        rows = by_gw[gw]
        if club:
            rows = [f for f in rows if f["home"] == club or f["away"] == club]
            if not rows:
                continue

        label = summary_club_label(rows, club, names)
        title = "Matchweek %d · %s" % (gw, label if club else "%d fixtures" % len(rows))
        lines = []
        for f in rows:
            home, away = f["home"], f["away"]
            probs = "%s%% home · %s%% draw · %s%% away" % (
                _num(f.get("prob_home")), _num(f.get("prob_draw")), _num(f.get("prob_away")))
            score = f.get("top_score")
            lines.append("%s vs %s — %s" % (nice(home), nice(away), probs) +
                         ((" (most likely %s)" % score) if score else ""))
        description = "\n".join(lines)
        if not club:
            description = "%d fixtures in this matchweek.\n\n" % len(rows) + description
        description += "\n\nProjections from NINETY+ — a statistical model with measured accuracy of " \
                       "about 46% on individual matches. Analysis, not betting advice."
        page = (site_url + "/gameweek/mw%d.html" % gw) if site_url else "gameweek/mw%d.html" % gw
        uid = "nt90-%s%s-mw%d@ninety-plus" % (
            (club.lower() + "-") if club else "", SEASON, gw)
        events.append({
            "uid": uid,
            "gw": gw,
            "start": start,
            "end": end,
            "summary": title,
            "description": description,
            "url": page,
            "stamp": "20260821T000000Z",     # the season's opening day: a fixed, reproducible DTSTAMP
        })
    return events


def summary_club_label(rows, club, names=None):
    """What the event title says for a club feed: opponent, venue, and what the model expects."""
    names = names or {}
    for f in rows:
        other = f["away"] if f["home"] == club else f["home"]
        other = names.get(other, (other, other))[0]
        me = names.get(club, (club, club))[1]
        venue = "H" if f["home"] == club else "A"
        prob = f.get("prob_home") if f["home"] == club else f.get("prob_away")
        score = f.get("top_score") or ""
        bits = ["vs %s (%s)" % (other, venue)]
        if prob is not None:
            bits.append("%s%% %s win" % (_num(prob), me))
        if score:
            bits.append("most likely %s" % score)
        return " · ".join(bits)
    return "no fixture"


def _num(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "?"
    return ("%.1f" % v).rstrip("0").rstrip(".")


def build(summary, fixtures, club=None, site_url=None, calendar_name=None):
    """The whole .ics document. Pure: same inputs, same bytes."""
    events = fixture_events(summary, fixtures, club=club, site_url=site_url)
    # The name a subscriber sees in their sidebar. A club feed named "ARS" is a missed opportunity;
    # it is called by the club's name, which is what a person is looking for in a list of calendars.
    club_label = club_labels(summary).get(club, (club, club))[0] if club else None
    name = calendar_name or (("NINETY+ · %s — Premier League 2026-27" % club_label) if club
                             else "NINETY+ · Premier League 2026-27")
    description = ("Predicted fixtures and probabilities for the 2026-27 Premier League season" +
                   (", %s only" % club if club else "") + ". Generated by NINETY+.")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:" + PRODID,
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:" + _esc(name),
        "X-WR-CALDESC:" + _esc(description),
        "REFRESH-INTERVAL;VALUE=DURATION:P1D",
        "X-PUBLISHED-TTL:P1D",
    ]
    for ev in events:
        lines += [
            "BEGIN:VEVENT",
            "UID:" + _esc(ev["uid"]),
            "DTSTAMP:" + ev["stamp"],
            "DTSTART;VALUE=DATE:%s" % ev["start"].strftime("%Y%m%d"),
            "DTEND;VALUE=DATE:%s" % ev["end"].strftime("%Y%m%d"),
            "SUMMARY:" + _esc(ev["summary"]),
            "DESCRIPTION:" + _esc(ev["description"]),
            "URL:" + _esc(ev["url"]),
            "TRANSP:TRANSPARENT",
            "SEQUENCE:0",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")

    folded = []
    for line in lines:
        folded += _fold(line)
    return "\r\n".join(folded) + "\r\n"     # RFC 5545 §3.1: CRLF, always


# ── loading the data these feeds are built from ───────────────────────────────────────────────────
def load_fixtures():
    """Every remaining fixture with its projections, from the same table the dashboard uses."""
    import csv
    path = os.path.join(DATA, "projected_fixtures_2026_27.csv")
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_summary():
    import json
    with open(os.path.join(DATA, "predictions_2026_27_summary.json"), encoding="utf-8") as fh:
        return json.load(fh)


def club_slug(name):
    """The project's club code, lowercased — the same identifier the API and the scenario keys use."""
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")


def feed_name(club):
    return "%s.ics" % club_slug(club)


def write_static_feeds(out_dir=None, site_url=None, quiet=False):
    """Write every feed into static/calendar/ so a static deploy has them too.

    The server can generate these on demand (see server.py), but GitHub Pages cannot — so the feeds a
    reader actually subscribes to are written at build time, exactly like the gameweek pages.
    """
    out_dir = out_dir or os.path.join(BASE, "static", "calendar")
    os.makedirs(out_dir, exist_ok=True)
    summary = load_summary()
    fixtures = load_fixtures()
    written = []

    def w(name, text):
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        written.append((os.path.relpath(path, BASE), len(text)))

    w("league.ics", build(summary, fixtures, site_url=site_url))
    for club in sorted({f["home"] for f in fixtures} | {f["away"] for f in fixtures}):
        w("%s.ics" % club_slug(club), build(summary, fixtures, club=club, site_url=site_url))

    if not quiet:
        total = sum(size for _p, size in written)
        print("  calendar: %d feeds · %.1f KB (%d events in the league feed)"
              % (len(written), total / 1024,
                 build(summary, fixtures, site_url=site_url).count("BEGIN:VEVENT")))
    return written


def main():
    feeds = write_static_feeds()
    for path, size in feeds[:3]:
        print("    %-40s %6d B" % (path, size))
    if len(feeds) > 3:
        print("    … and %d more club feeds" % (len(feeds) - 3))
    return 0


if __name__ == "__main__":
    sys.exit(main())
