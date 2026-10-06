"""check_live.py — is the site that is actually deployed actually current? (P11.2)

Every other check in this repository runs against the working tree, and that is exactly the wrong place
to look. The failure this exists for looks like this:

    the weekly job runs, passes its own gate, and promotes nothing
    the deployed site keeps serving the vintage it was built from
    nothing anywhere says so, and the site looks confident

A page cannot be caught doing that from inside the build, because the build is fine — it is the *gap*
between what is deployed and what the calendar says should exist by now that is wrong. So this fetches
the deployed page, reads the two things the page is willing to say about itself (the date its numbers
were built from, and the matchweek they are for), reconciles both against the published fixture
calendar, and checks the lock that the prediction record depends on.

    python3 check_live.py                      # check the deployed site
    python3 check_live.py --url <site>         # check somewhere else (a preview, a fork)
    python3 check_live.py --page static/index.html   # check a local build, no network
    python3 check_live.py --json               # machine-readable, for a monitor or a cron

Exit codes, because the point is to be usable from a monitor:

    0   current — the numbers cover every gameweek that has finished
    1   behind — a gameweek has finished and the deployed numbers predate it
    2   the page could not be read at all (unreachable, or no payload in it)
    3   the deployed ledger.json does not verify — the published record has been edited

The rule is the same one the page applies to itself in the browser (`freshness()` in static/src/core.js)
and it is duplicated here on purpose, in the same spirit as the ledger's verifier: the page telling a
reader it is stale is a courtesy, and the page telling *itself* it is stale is not evidence. The two
agree because both derive from the same published calendar, not because one calls the other — and the
test suite pins the agreement (`tests/test_wave11_liveness.py`).
"""
import argparse
import csv
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import feeds  # noqa: E402  (the same parser the iCal feed and the build use)

PRODUCTION = "https://90plus-cyan.vercel.app/"
CALENDAR = os.path.join(BASE_DIR, "data", "projected_fixtures_2026_27.csv")
LEDGER = os.path.join(BASE_DIR, "data", "ledger_2026_27.json")
PUBLISHED_LEDGER = "ledger.json"


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  Reading the page
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def fetch(url, timeout=30):
    """The deployed page as text. A monitor should say 'I could not look', not raise a stack trace."""
    req = urllib.request.Request(url, headers={"User-Agent": "ninety-plus-check-live/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", "replace")


def payload_from(html):
    """The embedded JSON blob, read the way the page reads it.

    `json.loads` cannot read this: the payload is a JavaScript object literal followed by more
    JavaScript, so the decoder has to stop where the object stops. raw_decode does exactly that and
    is what the server-side tests use too.
    """
    key = "const EMBEDDED = "
    i = html.find(key)
    if i < 0:
        return None
    try:
        blob, _ = json.JSONDecoder().raw_decode(html, i + len(key))
    except ValueError:
        return None
    return blob if isinstance(blob, dict) else None


def calendar(path=CALENDAR):
    """{gameweek: (first_kickoff, day_after_last_fixture)} from the published fixture list.

    The end is exclusive — the day after the last fixture — because that is when the refresh *can*
    have run. A gameweek whose window has passed and whose results are not in the deployed numbers is
    the failure this whole file is about.
    """
    out = {}
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                gw = int(row["gw"])
            except (KeyError, TypeError, ValueError):
                continue
            start, end = feeds.parse_window(row.get("dates"))
            if start:
                out[gw] = (start, end)
    return out


def locks(path=LEDGER):
    """{gameweek: locked_at date} from the committed ledger, plus the chain verdict if it can be had."""
    if not os.path.exists(path):
        return {}, None
    with open(path, encoding="utf-8") as fh:
        ledger = json.load(fh)
    out = {}
    for lock in ledger.get("locks") or []:
        stamp = str(lock.get("locked_at") or "")[:10]
        try:
            when = datetime.date.fromisoformat(stamp)
        except ValueError:
            continue
        gw = lock.get("gameweek")
        # The first lock wins: a re-lock supersedes, it does not move the deadline.
        out.setdefault(gw, when)
    verdict = None
    try:
        import score_ledger
        rep = score_ledger.verify(path)
        # verify() returns a report, not a flag: the problems are the useful part of it. The detail
        # line mirrors the CLI's, so a reader who runs either gets the same words.
        if rep.get("ok"):
            detail = "%s lock%s verified · chain: %s revision%s · OK" % (
                rep.get("checked", 0), "" if rep.get("checked") == 1 else "s",
                rep.get("chain", 0), "" if rep.get("chain") == 1 else "s")
        else:
            detail = "; ".join(rep.get("problems") or ["failed"])[:300]
        verdict = {"ok": bool(rep.get("ok")), "detail": detail,
                   "checked": rep.get("checked", 0), "chain": rep.get("chain", 0),
                   "problems": rep.get("problems") or []}
    except Exception as exc:                                    # pragma: no cover - defensive
        verdict = {"ok": False, "detail": "could not verify: %s" % exc, "problems": [str(exc)]}
    return out, verdict


def verify_published_chain(ledger):
    """Check the deployed ledger.json can only be what it says it is.

    The locks cannot be re-hashed out here — that needs the snapshot files, which are not deployed —
    but the revision chain can be, and it is the part that makes the record tamper-evident: every
    revision's `prev` must be the previous revision's hash, and each record's own hash must recompute
    from its contents. An edited or deleted entry that is not reflected in the chain shows up here.
    """
    import score_ledger
    problems, prev = [], ""
    revisions = ledger.get("revisions") or []
    for i, record in enumerate(revisions):
        if record.get("prev") != prev:
            problems.append("revision %d: prev link broken" % i)
        if record.get("hash") != score_ledger._chain_hash(prev, record):
            problems.append("revision %d: hash does not recompute — edited after it was written" % i)
        prev = record.get("hash", "")
    problems.extend(score_ledger.availability_chain_problems(ledger))
    return {"ok": not problems, "chain": len(revisions), "problems": problems,
            "locks": len(ledger.get("locks") or [])}


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  The verdict
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def deadline_met(locked_on, first_kickoff):
    """Was the call in the ledger before the ball was kicked? (P11.3)

    This is the one comparison that makes a prediction record mean anything: a call locked after
    kickoff, or after the result is known, is not a prediction. It lives here as a named function
    because the live check and the test suite must agree on it — if this rule only existed inside a
    report string, nothing would ever fail when it was broken.

    Returns True / False, or None when it cannot be judged (a missing date is not a pass).
    """
    if not locked_on or not first_kickoff:
        return None
    return locked_on < first_kickoff


def inspect(blob, cal, locked, today=None):
    """Everything the report needs, as data — so it can be asserted on in tests and printed as JSON."""
    today = today or datetime.date.today()
    meta = (blob or {}).get("baseline", {}).get("meta", {}) or {}
    as_of_raw = str(meta.get("as_of_date") or "")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", as_of_raw)
    as_of = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    next_gw = meta.get("next_gw")
    next_gw = int(next_gw) if isinstance(next_gw, (int, float, str)) and str(next_gw).isdigit() else None

    finished = sorted(gw for gw, (_a, b) in cal.items() if b <= today)
    playing = sorted(gw for gw, (a, b) in cal.items() if a <= today < b)
    upcoming = sorted(gw for gw in cal if cal[gw][0] > today)
    # A gameweek at or after the one these numbers are *for*, whose window has closed, is a gameweek
    # the numbers should already contain. This is the whole test.
    missed = [gw for gw in finished if next_gw is None or gw >= next_gw]

    state = "current"
    if not cal:
        state = "unknown"
    elif missed:
        state = "behind"
    elif playing:
        state = "in-play"

    missed_detail = None
    if missed and cal.get(missed[0]):
        a, b = cal[missed[0]]
        missed_detail = {"gameweek": missed[0], "start": a.isoformat(),
                         "ended": (b - datetime.timedelta(days=1)).isoformat()}

    first_next = cal.get(upcoming[0] if upcoming else (next_gw if next_gw in cal else None))
    days_to_kickoff = (first_next[0] - today).days if first_next else None
    age = (today - as_of).days if as_of else None
    lock = locked.get(next_gw) if next_gw is not None else None
    return {
        "state": state,
        "as_of": as_of.isoformat() if as_of else None,
        "age_days": age,
        "matchweek": next_gw,
        "playing": playing,
        "finished": finished[-1] if finished else None,
        "missed": missed[:3],
        "missed_detail": missed_detail,
        "next_kickoff": first_next[0].isoformat() if first_next else None,
        "days_to_kickoff": days_to_kickoff,
        "locked": lock.isoformat() if lock else None,
        # The deadline that makes a prediction record worth anything: the call has to be in the ledger
        # before the first ball is kicked, or scoring it later proves nothing.
        "locked_before_kickoff": deadline_met(lock, first_next[0] if first_next else None),
    }


def report(info, ledger_verdict, source, published=None, ledger_label="the local ledger"):
    lines = []
    state = info["state"]
    head = {"current": "CURRENT", "in-play": "IN PLAY", "behind": "BEHIND", "unknown": "UNKNOWN"}[state]
    lines.append("%s — %s" % (head, source))
    if info["as_of"]:
        age = info["age_days"]
        lines.append("  numbers built from results up to %s (%s)"
                     % (info["as_of"],
                        "today" if age == 0 else "1 day ago" if age == 1 else "%d days ago" % age))
    if info["matchweek"] is not None:
        lines.append("  published for matchweek %s%s"
                     % (info["matchweek"],
                        " (next to be played)" if state in ("current", "in-play")
                        else " — already played"))
    if info["playing"]:
        lines.append("  matchweek %s is being played now" % info["playing"][0])
    elif state == "behind" and info.get("missed_detail"):
        lines.append("  matchweek %s has been played and is not in these numbers"
                     % info["missed_detail"]["gameweek"])
    if info["next_kickoff"]:
        n = info["days_to_kickoff"]
        when = "today" if n == 0 else ("in %d day%s" % (n, "" if n == 1 else "s")) if n > 0 \
            else ("%d days ago" % -n)
        lines.append("  next kickoff %s — %s" % (info["next_kickoff"], when))
    if info["locked"]:
        verdict = {True: "before kickoff, which is the whole point",
                   False: "AFTER kickoff — the record is compromised",
                   None: "cannot be checked against a kickoff date"}[info["locked_before_kickoff"]]
        lines.append("  matchweek %s locked %s — %s" % (info["matchweek"], info["locked"], verdict))
    else:
        lines.append("  matchweek %s has no lock in the ledger" % info["matchweek"])
    if ledger_verdict:
        lines.append("  %s %s" % (ledger_label,
                                  "verifies: " + ledger_verdict["detail"] if ledger_verdict["ok"]
                                  else "DOES NOT VERIFY: " + ledger_verdict["detail"]))
    if published is not None:
        lines.append("  the deployed record %s" % (
            "verifies: chain of %d revision%s, %d lock%s — nothing has been edited since it was written"
            % (published["chain"], "" if published["chain"] == 1 else "s",
               published["locks"], "" if published["locks"] == 1 else "s")
            if published["ok"] else
            "DOES NOT VERIFY: " + "; ".join(published["problems"])))

    if state == "behind":
        d = info.get("missed_detail") or {}
        lines.append("")
        lines.append("  The deployed numbers do not include matchweek %s, which finished on %s."
                     % (d.get("gameweek", info["missed"][0]), d.get("ended", "a date already past")))
        lines.append("  The weekly job has not promoted anything since. Either it needs a data key")
        lines.append("  (Settings -> Secrets and variables -> Actions -> FOOTBALL_DATA_KEY), or a")
        lines.append("  results file in data/provider_drop/, or its last run failed.")
    elif state == "unknown":
        lines.append("  No fixture calendar was readable — cannot judge freshness.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Is the deployed site current?")
    ap.add_argument("--url", default=os.environ.get("NT90_SITE_URL") or PRODUCTION,
                    help="site to check (default: $NT90_SITE_URL, else the production URL)")
    ap.add_argument("--page", help="check a local HTML file instead of fetching")
    ap.add_argument("--calendar", default=CALENDAR, help="fixture calendar (CSV)")
    ap.add_argument("--ledger", default=LEDGER, help="ledger to check locks and chain in")
    ap.add_argument("--today", help="pretend it is this date (YYYY-MM-DD); for tests and for asking "
                                    "'would this have been caught on the 14th?'")
    ap.add_argument("--no-published", action="store_true",
                    help="do not fetch the site's ledger.json (only meaningful with --url)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    ap.add_argument("--quiet", action="store_true", help="one line, for cron")
    args = ap.parse_args(argv)

    today = datetime.date.fromisoformat(args.today) if args.today else None
    source = args.page or args.url
    try:
        html = open(args.page, encoding="utf-8").read() if args.page else fetch(args.url)
    except (OSError, urllib.error.URLError) as exc:
        print("UNREACHABLE — %s\n  %s" % (source, exc))
        return 2
    blob = payload_from(html)
    if blob is None:
        print("UNREADABLE — %s\n  the page carries no embedded payload, so it cannot be judged."
              % source)
        return 2

    cal = calendar(args.calendar)
    locked, verdict = locks(args.ledger)
    published = None
    if not args.page and not args.no_published:
        # The deployed record, checked against itself. A page that is current and a record that has
        # been edited is a worse state than either alone, and this is the only check in the repo that
        # looks at the record as a reader receives it rather than as the repository holds it.
        try:
            pub = json.loads(fetch(args.url.rstrip("/") + "/" + PUBLISHED_LEDGER))
            published = verify_published_chain(pub)
        except Exception as exc:
            published = {"ok": False, "chain": 0, "locks": 0,
                         "problems": ["could not fetch or read %s: %s" % (PUBLISHED_LEDGER, exc)]}
    info = inspect(blob, cal, locked, today=today)
    if args.as_json:
        print(json.dumps({"source": source, "ledger": verdict, "published": published,
                          **info}, indent=2, sort_keys=True))
    elif args.quiet:
        print("%s · data %s · matchweek %s · %s" % (info["state"], info["as_of"],
                                                    info["matchweek"], source))
    else:
        print(report(info, verdict, source, published=published,
                     ledger_label="ledger (%s)" % os.path.relpath(args.ledger, BASE_DIR)))
    # Exit code answers "would a monitor wake somebody up?" — so it is about staleness only. A ledger
    # that is out of date or a lock missing is reported and does not by itself page anyone; a deployed
    # page serving a gameweek that has already been played does.
    # "unknown" is not "behind": it means this tool could not judge, which is a different alarm.
    code = {"current": 0, "in-play": 0, "behind": 1, "unknown": 2}[info["state"]]
    # An edited published record outranks a stale page as a reason to look: one is late, the other is
    # wrong about its own history, and that is the thing the ledger exists to make impossible.
    if published is not None and not published["ok"]:
        return 3
    return code


if __name__ == "__main__":
    sys.exit(main())
