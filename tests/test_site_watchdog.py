"""Keeping the deployment honest — the watchdogs, and the changelog's own rule.

Two machines now exist to answer one question that nothing in the repository can answer about itself:
*is the live site serving what we think it is?*

* the weekly job's last step compares the deployment with the checkout it just committed (P11.2's tool,
  used where it actually matters);
* a separate weekly workflow asks the same question when nobody pushed anything at all — because the
  failure this project is built around is a green job that promotes nothing while the site keeps serving
  an old vintage.

Both are only worth having if they fail when they should, so the tool is tested against a page that is
deliberately behind, and the workflows are tested for the properties that make them watchdogs rather than
decoration: a schedule, no credentials, and no second copy of the freshness logic.

The last test here pins the changelog's own rule — a release that says the model did not change must not
carry a non-zero delta. That rule was written in prose at the top of CHANGELOG.md; prose does not fail.
"""
import json
import os
import re
import subprocess
import sys

from _util import ROOT

DATA = os.path.join(ROOT, "data")
STATIC = os.path.join(ROOT, "static")
WORKFLOWS = os.path.join(ROOT, ".github", "workflows")
sys.path.insert(0, os.path.join(ROOT, "tools"))


def _check(condition, message):
    if not condition:
        raise AssertionError(message)


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def _run_tool(*args):
    return subprocess.run([sys.executable, os.path.join(ROOT, "tools", "verify_deployment.py"), *args],
                          capture_output=True, text=True, cwd=ROOT)


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  The deployment check, proved in both directions
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_it_agrees_when_the_page_matches_the_checkout():
    out = _run_tool("--page", os.path.join(STATIC, "index.html"))
    _check(out.returncode == 0, "a build of this checkout did not match it: %s" % (out.stdout or out.stderr))
    _check("MATCHES" in out.stdout, "the happy path does not say so plainly: %r" % out.stdout[:120])


def test_it_catches_a_deployment_one_gameweek_behind():
    """The real failure: the site is up, serving, and showing last week. Built by doctoring a real page
    rather than by asserting on a fixture, so the field names are the ones the page actually uses."""
    page = _read(STATIC, "index.html")
    published = json.loads(_read(DATA, "predictions_2026_27_summary.json"))
    next_gw = int(published["meta"]["next_gw"])
    # the payload is written compactly ("next_gw":6, no space) — match what is there, and then prove the
    # change actually reached the payload rather than trusting a string replace that may have missed
    needle = '"next_gw":%d' % next_gw
    _check(needle in page, "could not find the matchweek in the built page — the payload shape changed")
    behind = page.replace(needle, '"next_gw":%d' % (next_gw - 1), 1)
    doctored, _ = json.JSONDecoder().raw_decode(behind, behind.index("const EMBEDDED = ")
                                                + len("const EMBEDDED = "))
    _check(doctored["baseline"]["meta"]["next_gw"] == next_gw - 1,
           "the doctored page still claims matchweek %s" % next_gw)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "behind.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(behind)
        out = _run_tool("--page", path)
    _check(out.returncode == 1, "a page a gameweek behind exited %d, not 1" % out.returncode)
    _check("MISMATCH" in out.stdout, "the mismatch was not reported: %r" % out.stdout[:200])
    _check("matchweek" in out.stdout, "the differing field was not named: %r" % out.stdout[:200])


def test_it_reports_a_page_it_cannot_read_rather_than_calling_it_a_match():
    out = _run_tool("--page", os.path.join(ROOT, "README.md"))
    _check(out.returncode == 2, "an unreadable page exited %d, not 2" % out.returncode)
    _check("UNREADABLE" in out.stdout, "nothing said the page could not be judged")


def test_it_does_not_compare_build_settings():
    """n_simulations is a build choice, not a fact about the data. Comparing it would make a retuned
    simulation count look like a failed deployment."""
    sys.path.insert(0, ROOT)
    import importlib
    import tools.verify_deployment as vd
    fields = [c[0] for c in vd.compare({"matchweek": 6, "as_of": "2026-10-03", "season": "x",
                                       "n_simulations": 5000},
                                      {"matchweek": 6, "as_of": "2026-10-03", "season": "x",
                                       "n_simulations": 1000})]
    _check("n_simulations" not in fields, "the comparison includes a build setting")
    _check(all(ok for *_r, ok in vd.compare({"matchweek": 6, "as_of": "a", "season": "s"},
                                            {"matchweek": 6, "as_of": "a", "season": "s"})),
           "matching values were reported as differing")
    _check(not all(ok for *_r, ok in vd.compare({"matchweek": 6, "as_of": "a", "season": "s"},
                                                {"matchweek": 7, "as_of": "a", "season": "s"})),
           "a differing matchweek was accepted")


def test_the_check_uses_the_same_inspection_as_the_live_check():
    """One definition of what the page says, not two that can drift."""
    source = _read(ROOT, "tools", "verify_deployment.py")
    _check("import check_live" in source, "the deployment check does not reuse check_live's parser")
    _check("payload_from" in source, "it parses the payload itself instead of sharing the parser")
    _check("def inspect" not in source, "a second copy of the inspection logic has appeared")


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  The workflows that do it without being asked
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_weekly_job_confirms_its_own_deployment_after_committing():
    text = _read(WORKFLOWS, "weekly-update.yml")
    _check("tools/verify_deployment.py" in text,
           "the weekly job never checks that its commit reached the live site")
    commit_at = text.index("Commit the refreshed dataset")
    check_at = text.index("Confirm the deployment is serving this commit")
    _check(check_at > commit_at, "the deployment check runs before the commit it is meant to verify")
    _check("--retries" in text and "--wait" in text,
           "the check does not wait for Vercel, so it would fail on every successful deploy")


def test_the_watchdog_runs_on_its_own_schedule():
    text = _read(WORKFLOWS, "site-current.yml")
    _check("check_live.py" in text, "the watchdog does not run the live check")
    _check("schedule:" in text and "cron:" in text, "the watchdog is not scheduled — it would only run if asked")
    _check("workflow_dispatch" in text, "the watchdog cannot be run by hand")
    weekly = _read(WORKFLOWS, "weekly-update.yml")
    mine = set(re.findall(r'cron:\s*"([^"]+)"', text))
    theirs = set(re.findall(r'cron:\s*"([^"]+)"', weekly))
    _check(not (mine & theirs),
           "the watchdog shares a cron with the weekly job (%s) — the two would race" % (mine & theirs))
    _check(mine, "the watchdog has no cron expression")


def test_the_watchdog_holds_no_credentials_and_writes_nothing():
    """It reads the public site and the public repository. A monitor that needs a key is a monitor that
    stops working the day the key rotates."""
    text = _read(WORKFLOWS, "site-current.yml")
    _check("secrets." not in text, "the watchdog asks for a secret, which it has no need of")
    _check(re.search(r"permissions:\s*\n\s*contents:\s*read", text),
           "the watchdog does not declare read-only permissions")
    _check("git push" not in text and "git commit" not in text, "the watchdog writes to the repository")
    _check("update_week" not in text, "the watchdog runs the data job — it is a check, not a second job")


def test_the_watchdog_explains_a_stale_site_instead_of_leaving_a_red_x():
    text = _read(WORKFLOWS, "site-current.yml")
    _check("FOOTBALL_DATA_KEY" in text, "the watchdog does not name the two-minute fix")
    _check("provider_drop" in text, "the watchdog does not mention the keyless fix")
    _check("docs/operations.md" in text, "the watchdog does not point at the runbook")


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  The changelog's own rule, enforced rather than described
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_a_release_that_says_the_model_did_not_change_carries_a_zero_delta():
    """CHANGELOG.md states this rule in prose at the top. Prose does not fail; this does."""
    path = os.path.join(ROOT, "CHANGELOG.md")
    if not os.path.exists(path):
        return
    text = _read(path)
    sections = text.split("\n## ")[1:]
    _check(sections, "the changelog has no releases")
    checked = 0
    for section in sections:
        version = section.split(" ")[0]
        model_line = re.search(r"\*\*Model\*\*\s*—\s*([^\n]+)", section)
        delta_line = re.search(r"\*\*Delta[^\n]*\*\*\s*—\s*([^\n]+)", section)
        if not model_line or not delta_line:
            continue
        unchanged = "unchanged" in model_line.group(1).lower()
        delta = delta_line.group(1).lower()
        if unchanged:
            checked += 1
            zero_points = "0.0 points" in delta or "0 points" in delta
            _check(zero_points,
                   "%s says the model did not change and then reports a delta of %r — the file promises "
                   "this cannot happen" % (version, delta_line.group(1)))
    _check(checked >= 1, "no release was found that declares an unchanged model, so nothing was checked")
