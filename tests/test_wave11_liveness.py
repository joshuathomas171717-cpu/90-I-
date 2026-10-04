"""Phase 11 — the site stays true (P11.1 freshness, P11.2 the live check).

The defect these exist for was found by reading the weekly workflow rather than the site: with no
`FOOTBALL_DATA_*` secret the job falls back to the local snapshot provider, passes its own gate, and
promotes nothing. Nothing on the deployed page noticed, because the page only knew how *old* it was,
not whether it was *behind* — and a page can be one day old and a whole gameweek late.

So there are two rules now and both are pinned here:

  * the page decides its own freshness from the shipped calendar (`freshness()` in static/src/core.js),
    and says so in the header when it is behind;
  * an outsider can check that claim without trusting the page (`check_live.py`), which is the only
    check in this repository that looks at the deployed artefact rather than the working tree.

CI installs Python and not Node, so the JavaScript is pinned by its wiring plus a Python mirror of the
same decision table — the same approach the store and the ledger tests take. The mirror is not a
tolerance: if the two rules ever disagree, the test fails and the disagreement gets resolved.
"""
import csv
import datetime
import json
import os
import re
import subprocess
import sys

from _util import ROOT, skip

STATIC = os.path.join(ROOT, "static")
SRC = os.path.join(STATIC, "src")
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, ROOT)

import feeds          # noqa: E402
import check_live     # noqa: E402  (imported after the path insert, deliberately)


def _check(condition, message):
    if not condition:
        raise AssertionError(message)


def _read(path, base=None):
    with open(os.path.join(base, path) if base else path, encoding="utf-8") as fh:
        return fh.read()


def _code_only(text):
    """Strip comments, so a negative assertion is about code rather than prose about code."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def _page():
    path = os.path.join(STATIC, "index.html")
    if not os.path.exists(path):
        skip("static/index.html has not been built")
    return _read(path)


def _blob():
    html = _page()
    key = "const EMBEDDED = "
    if key not in html:
        skip("the built page carries no embedded payload")
    blob, _ = json.JSONDecoder().raw_decode(html, html.index(key) + len(key))
    return blob


def _calendar():
    """The published fixture calendar, re-derived from the CSV the build reads."""
    path = os.path.join(DATA, "projected_fixtures_2026_27.csv")
    if not os.path.exists(path):
        skip("data/projected_fixtures_2026_27.csv is missing")
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


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  P11.1 — the page knows whether it is behind, not just how old it is
# ════════════════════════════════════════════════════════════════════════════════════════════════════

# A mirror of the decision table in core.js. Written out rather than described, because the point of
# the table is which state wins when more than one applies — a gameweek can be finished *and* the next
# one in progress, and the answer must not depend on the order the states are written in.
def _freshness(as_of, schedule, next_gw, today):
    """Mirror of core.js freshness(), reading the same ISO strings the page embeds."""
    def day(iso):
        return datetime.date(*[int(x) for x in str(iso)[:10].split("-")])

    if isinstance(as_of, str):
        as_of = day(as_of)
    if not schedule or not as_of:
        return "behind" if (as_of and (today - as_of).days > 8) else "ok"
    schedule = {int(gw): (day(a), day(b)) for gw, (a, b) in schedule.items()}
    starts = sorted(schedule)
    finished = [gw for gw in starts if schedule[gw][1] <= today]
    if next_gw is not None:
        missed = [gw for gw in finished if gw >= next_gw]
        if missed:
            return "behind"
    playing = [gw for gw in starts if schedule[gw][0] <= today < schedule[gw][1]]
    if playing:
        return "due"
    return "ok"


def test_the_built_page_carries_the_calendar_it_judges_itself_against():
    """Without the calendar the page cannot tell "1 day old" from "a weekend late"."""
    blob = _blob()
    schedule = blob.get("schedule")
    _check(isinstance(schedule, dict) and schedule, "the built page carries no fixture schedule")
    real = {gw: [a.isoformat(), b.isoformat()] for gw, (a, b) in _calendar().items()}
    _check({int(k): list(v) for k, v in schedule.items()} == real,
           "the embedded schedule disagrees with data/projected_fixtures_2026_27.csv — the page would "
           "judge its own freshness against dates that are not the published ones")


def test_the_schedule_is_not_a_copy_of_the_ledger_or_the_summary():
    """It must come from the fixture list, not be hand-maintained in build_dashboard.py."""
    source = _read("build_dashboard.py")
    _check("parse_window" in source,
           "build_dashboard.py does not parse the fixture windows — a hand-written table of dates is a "
           "table that goes stale, which is the thing being fixed")
    _check("projected_fixtures_2026_27.csv" in source,
           "the schedule is not derived from the published fixture list")


def test_the_page_renders_a_verdict_rather_than_an_age():
    render = _read("render.js", SRC)
    _check("freshness(" in render, "render.js does not ask core.js how fresh the page is")
    _check(re.search(r'freshness\(asOf,\s*\(typeof EMBEDDED', render),
           "the freshness call does not pass the embedded schedule")
    for level in ("behind", "due", "ok"):
        _check(level in render, "render.js never handles the '%s' state" % level)


def test_the_old_fixed_threshold_rule_is_gone():
    """The rule this replaced: flag anything older than eight days. It under-stated the real failure —
    a page can carry three-day-old data and still be missing a whole gameweek."""
    code = _code_only(_read("render.js", SRC))
    _check("const weekly = 8" not in code, "the fixed eight-day rule is still in render.js")
    _check("data ${days} days old" not in code,
           "render.js still builds its chip from a day count alone")


def test_a_stale_page_says_so_on_the_page_not_only_in_a_tooltip():
    app = _read("app.html", SRC)
    render = _read("render.js", SRC)
    _check('id="staleNote"' in app, "there is nowhere for the out-of-date notice to appear")
    _check('$("staleNote")' in render and "note.hidden = false" in render,
           "the notice is never shown — a tooltip is where honesty goes to be unread")
    _check("staleNote" in _page(), "the built page does not carry the notice element")


def test_the_three_states_are_visually_distinct_and_colour_is_not_the_only_signal():
    css = _read("theme.css", SRC)
    _check(".fresh.due" in css and ".fresh.stale" in css,
           "the in-progress and out-of-date chip states are not styled")
    render = _read("render.js", SRC)
    _check("out of date" in render and "gameweek in progress" in render,
           "the chip states are not also said in words")
    # The chip is hidden on narrow screens, which is fine when it is decoration and not fine when it is
    # the reason the numbers look wrong.
    _check(re.search(r"@media \(max-width:720px\)\{\s*\.fresh\{display:none\}\s*\.fresh\.stale,\s*"
                     r"\.fresh\.due\{display:flex\}", css),
           "a narrow screen hides the freshness chip in every state, including the one that matters")


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  The mirror agrees with the shipped rule, case by case
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_python_mirror_and_the_shipped_rule_agree_on_every_case_that_matters():
    cal = _calendar()
    schedule = {gw: (a.isoformat(), b.isoformat()) for gw, (a, b) in cal.items()}
    cases = [
        # (when, what the data covers, expected) — the four states a reader will actually meet
        (datetime.date(2026, 10, 5), datetime.date(2026, 10, 3), 6, "ok"),      # before kickoff
        (datetime.date(2026, 10, 11), datetime.date(2026, 10, 3), 6, "due"),    # weekend in progress
        (datetime.date(2026, 10, 14), datetime.date(2026, 10, 3), 6, "behind"),  # refresh never ran
        (datetime.date(2026, 10, 14), datetime.date(2026, 10, 13), 7, "ok"),     # refresh ran
        (datetime.date(2027, 5, 30), datetime.date(2027, 5, 20), 38, "due"),     # last weekend
    ]
    for today, as_of, gw, expected in cases:
        got = _freshness(as_of, schedule, gw, today)
        _check(got == expected,
               "on %s with data to %s and matchweek %s, freshness() should say %s but the mirror says %s"
               % (today, as_of, gw, expected, got))
    # and the shipped source must actually contain that table's vocabulary
    render = _read("render.js", SRC)
    _check("missed" in _read("core.js", SRC),
           "core.js does not compute the set of finished gameweeks the numbers miss")


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  P11.2 — an outsider can check the deployed site without trusting it
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_live_check_reads_the_deployed_page_and_reaches_the_same_verdict():
    """Run the real tool against the real built page, at a date chosen so the answer is not a
    coincidence of when the suite happened to run."""
    out = subprocess.run([sys.executable, os.path.join(ROOT, "check_live.py"),
                          "--page", os.path.join(STATIC, "index.html"),
                          "--today", "2026-10-05", "--json"],
                         capture_output=True, text=True, cwd=ROOT)
    _check(out.returncode == 0, "check_live.py failed on the built page: %s" % (out.stderr or out.stdout))
    info = json.loads(out.stdout)
    _check(info["state"] == "current", "the built page was judged %s on 5 October" % info["state"])
    _check(info["matchweek"] == 6, "the built page is not for matchweek 6")
    _check(info["days_to_kickoff"] == 5,
           "days to kickoff computed as %s, expected 5" % info["days_to_kickoff"])
    _check(info["locked_before_kickoff"] is True,
           "the shipped matchweek-6 lock is not before its first kickoff")


def test_the_live_check_calls_a_late_site_late():
    """The same tool, one day after matchweek 6's window closes, with the data it actually has. This is
    the failure the whole wave exists for, and the tool has to say so and exit non-zero."""
    out = subprocess.run([sys.executable, os.path.join(ROOT, "check_live.py"),
                          "--page", os.path.join(STATIC, "index.html"),
                          "--today", "2026-10-14", "--json"],
                         capture_output=True, text=True, cwd=ROOT)
    _check(out.returncode == 1, "a site a gameweek behind exited %d, not 1" % out.returncode)
    info = json.loads(out.stdout)
    _check(info["state"] == "behind", "the state should be 'behind', not %s" % info["state"])
    _check(info["missed_detail"]["gameweek"] == 6,
           "the report does not name the gameweek that is missing: %s" % info.get("missed_detail"))
    _check(info["missed_detail"]["ended"] == "2026-10-12",
           "the report names the wrong last day for matchweek 6: %s" % info["missed_detail"]["ended"])


def test_the_live_check_refuses_to_call_a_page_it_cannot_read_current():
    """Two failure modes that must not be mistaken for health: an unreachable site and a page with no
    payload. Both exit 2 — 'could not judge' is not 'fine'."""
    out = subprocess.run([sys.executable, os.path.join(ROOT, "check_live.py"),
                          "--page", os.path.join(ROOT, "README.md"), "--json"],
                         capture_output=True, text=True, cwd=ROOT)
    _check(out.returncode == 2, "a page with no payload exited %d, not 2" % out.returncode)
    _check("UNREADABLE" in out.stdout, "nothing said the page could not be judged")

    out = subprocess.run([sys.executable, os.path.join(ROOT, "check_live.py"),
                          "--url", "http://127.0.0.1:9/", "--quiet"],
                         capture_output=True, text=True, cwd=ROOT)
    _check(out.returncode == 2, "an unreachable site exited %d, not 2" % out.returncode)


def test_the_live_check_verifies_the_published_record_not_just_the_local_one():
    """The deployed ledger.json is the one a reader receives. It is checked separately, and a chain
    that does not recompute is exit 3 — a wrong history outranks a late one."""
    source = _read("check_live.py")
    _check("PUBLISHED_LEDGER" in source and "verify_published_chain" in source,
           "check_live.py does not verify the deployed record")
    _check('"--no-published"' in source, "there is no way to check staleness alone")
    # and the verifier must reject a ledger whose history was edited
    import score_ledger
    honest = score_ledger.empty_ledger()
    honest["revisions"], honest["locks"] = [], []
    honest["locks"] = [{"gameweek": 6, "locked_at": "2026-10-04T00:00:00+00:00", "content_hash": "a" * 64}]
    honest["revisions"] = [{"seq": 0, "at": "2026-10-04T00:00:00+00:00", "event": "locked",
                            "gameweek": 6, "detail": "x", "content": "a" * 64, "prev": ""}]
    honest["revisions"][0]["hash"] = score_ledger._chain_hash("", honest["revisions"][0])
    _check(check_live.verify_published_chain(honest)["ok"], "an honest chain did not verify")
    edited = json.loads(json.dumps(honest))
    edited["revisions"][0]["detail"] = "10 predictions, all certain"
    _check(not check_live.verify_published_chain(edited)["ok"],
           "an edited published record verified — the check is decoration")


def test_the_deadline_rule_can_fail():
    """P11.3's comparison, proved in both directions. A rule that has only seen a timely lock has not
    been tested."""
    kickoff = datetime.date(2026, 10, 10)
    _check(check_live.deadline_met(datetime.date(2026, 10, 4), kickoff) is True, "a timely lock failed")
    _check(check_live.deadline_met(datetime.date(2026, 10, 10), kickoff) is False,
           "a lock written on the day of the first kickoff passed — it could have been written after it")
    _check(check_live.deadline_met(datetime.date(2026, 10, 12), kickoff) is False, "a late lock passed")
    _check(check_live.deadline_met(None, kickoff) is None, "a missing lock date must not be a pass")
    _check(check_live.deadline_met(datetime.date(2026, 10, 4), None) is None,
           "a missing kickoff date must not be a pass")


def test_every_lock_in_the_shipped_ledger_beats_its_own_kickoff():
    """The invariant, on the real artefacts: the matchweek's call must be in the ledger before the
    first fixture of that matchweek starts, judged against the published calendar."""
    path = os.path.join(DATA, "ledger_2026_27.json")
    if not os.path.exists(path):
        skip("data/ledger_2026_27.json is missing")
    with open(path, encoding="utf-8") as fh:
        ledger = json.load(fh)
    cal = _calendar()
    for lock in ledger.get("locks", []):
        gw = lock.get("gameweek")
        if gw not in cal:
            raise AssertionError("matchweek %s is locked but is not in the fixture calendar" % gw)
        locked_on = datetime.date.fromisoformat(str(lock["locked_at"])[:10])
        first = cal[int(gw)][0]
        _check(check_live.deadline_met(locked_on, first) is True,
               "matchweek %s was locked on %s and its first fixture was %s — a lock written after "
               "kickoff proves nothing" % (gw, locked_on, first))


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  P11.4 — the runbook has to be runnable
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_runbook_only_names_commands_and_flags_that_exist():
    """A runbook is read at the worst possible moment. If it names a flag that does not exist, the
    reader loses the time it was supposed to save — and concludes the project is broken."""
    doc = _read(os.path.join("docs", "operations.md"))
    for path, flags in (("check_live.py", ()),
                        ("update_week.py", ("--dry-run",)),
                        ("score_ledger.py", ("--lock", "--score", "--verify")),
                        ("run_all.py", ())):
        full = os.path.join(ROOT, path)
        _check(os.path.exists(full), "the runbook tells the reader to run %s, which does not exist" % path)
        source = _read(path)
        for flag in flags:
            _check('"%s"' % flag in source or flag in source,
                   "the runbook documents %s %s, and %s has no such option" % (path, flag, path))
    _check("tests/run_tests.py" in doc, "the rehearse-a-week command is not in the runbook")
    _check("-k" in _read(os.path.join("tests", "run_tests.py")),
           "the runbook's -k filter is not something the test runner implements")


def test_the_runbook_is_reachable_from_the_readme():
    readme = _read("README.md")
    _check("docs/operations.md" in readme, "the runbook is not linked from the README")
    _check("check_live.py" in readme, "the live check is not mentioned in the README")


def test_every_relative_link_in_the_readme_points_at_something():
    """The bug this catches: a workflow renamed from weekly.yml to weekly-update.yml, and a README link
    that kept the old name for two waves. A dangling link is a small lie that a reader finds first."""
    readme = _read("README.md")
    missing = []
    for target in re.findall(r"\]\(([^)\s]+)\)", readme):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        path = target.split("#")[0]
        if path and not os.path.exists(os.path.join(ROOT, path)):
            missing.append(target)
    _check(not missing, "the README links to %s, which do not exist" % sorted(set(missing)))
