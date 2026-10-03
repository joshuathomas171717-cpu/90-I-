"""Repo hygiene guards — the things that are embarrassing to get wrong exactly once.

A public repository is a publication, and these are the four ways this particular project could
publish something it should not: a secret, a generated directory, an unlicensed copy of someone
else's data, or a README that tells a visitor to `cd` into a folder that does not exist.

None of this is model logic, so it lives on its own. Every check here is cheap, and each one is a
mistake that is invisible until a stranger finds it.
"""
import os
import re
import sys

from _util import ROOT, skip

GITHUB = os.path.join(ROOT, ".github", "workflows")


def _tracked_like():
    """Every file a `git add .` would pick up — approximated by walking the tree and applying the
    same ignores a human would expect, so the test works before `git init` and after."""
    ignore_dirs = {"__pycache__", ".git", "artifacts", "_design", ".pytest_cache", ".venv"}
    ignore_suffix = (".pyc", ".pyo", ".zip", ".png", ".DS_Store")
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in ignore_dirs]
        rel_dir = os.path.relpath(dirpath, ROOT)
        parts = set(rel_dir.split(os.sep))
        if {"raw", "staging", "provider_drop"} & parts and rel_dir.startswith("data"):
            continue
        for name in filenames:
            if name.endswith(ignore_suffix):
                continue
            yield os.path.join(dirpath, name), os.path.relpath(os.path.join(dirpath, name), ROOT)


# ════════════════════════════════════════════════════════════════════════════
#  1. no secrets
# ════════════════════════════════════════════════════════════════════════════
# Real keys, not the words "token" or "secret" — a documentation file full of variable names is fine.
SECRET_PATTERNS = [
    re.compile(r"""(?:TOKEN|API_?KEY|SECRET|PASSWORD|WEBHOOK)\s*[:=]\s*['"][A-Za-z0-9_\-]{16,}['"]"""),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),                       # GitHub personal access token
    re.compile(r"sk-[A-Za-z0-9]{32,}"),                        # OpenAI-style
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),               # Slack
    re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/]{20,}"),
    re.compile(r"https://discord\.com/api/webhooks/\d+/[A-Za-z0-9_-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def test_no_secret_is_waiting_to_be_committed():
    hits = []
    for path, rel in _tracked_like():
        if rel.endswith((".csv", ".json")) and rel.startswith("data"):      # data, not code
            continue
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            m = pattern.search(text)
            if m:
                hits.append("%s: %s" % (rel, m.group(0)[:40]))
    assert not hits, "possible secret(s) in tracked files:\n  " + "\n  ".join(hits)


def test_the_env_file_is_ignored_but_its_template_is_not():
    ignored = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
    assert ".env" in ignored.split("\n"), ".env must be gitignored"
    assert os.path.exists(os.path.join(ROOT, ".env.example")), \
        ".env.example should exist so people know what the variables are"
    assert not os.path.exists(os.path.join(ROOT, ".env")), \
        "a real .env is present — it must never be committed, and it is not needed to run anything"


# ════════════════════════════════════════════════════════════════════════════
#  2. generated things stay out
# ════════════════════════════════════════════════════════════════════════════
def test_generated_directories_are_gitignored():
    ignored = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
    for entry in ("artifacts/", "data/raw/", "data/staging/", "__pycache__/", ".venv/"):
        assert entry in ignored, "%s must be ignored (it is derived, and in artifacts' case 8 MB)" % entry


def test_the_tracked_data_is_the_data_that_matters():
    """data/ ships, and ships *derived* files only: no raw provider payloads (not ours to
    redistribute), no staging (a fetch in progress), no cache."""
    data = os.path.join(ROOT, "data")
    for must in ("teams_2026_27.csv", "matches_2026_27_played.csv",
                 "fixtures_2026_27_remaining.csv", "players_2026_27.csv",
                 "predictions_2026_27_summary.json", "as_of.json"):
        assert os.path.exists(os.path.join(data, must)), "data/%s is missing — it is committed on purpose" % must
    # Those three directories hold fetched payloads and in-progress fetches. They may legitimately
    # contain files while you are working (the staged payload *is* the audit trail for a run) — what
    # matters is that git never sees them, which the ignore rules above guarantee.
    ignored = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
    for name in ("raw", "staging", "provider_drop"):
        assert "data/%s/" % name in ignored, "data/%s/ must be gitignored" % name


# ════════════════════════════════════════════════════════════════════════════
#  3. the visitor's first command works
# ════════════════════════════════════════════════════════════════════════════
PROJECT_NAME = "ninety-plus-pl-predictor"


def test_readme_tells_visitors_to_cd_into_a_folder_that_exists():
    """The quick start must name a folder the reader could plausibly be standing in.

    Two names are legitimate: the folder actually checked out here, and the project's canonical name.
    They differ routinely — `actions/checkout` names the working copy after the *repository* (so CI
    runs inside `90-I-`), and anyone who clones or unzips gets the canonical name instead. Accepting
    both still catches the mistake this guards against: a `cd` into some folder that nothing creates.
    """
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    found = re.findall(r"^cd\s+(\S+)", readme, flags=re.M)
    assert found, "README has no `cd` line — the quick start should start by telling you where to be"
    folder = os.path.basename(ROOT.rstrip(os.sep))
    acceptable = {folder, PROJECT_NAME}
    for target in found:
        assert target in acceptable, (
            "README says `cd %s`, which is neither the checked-out folder (%s) nor the project name "
            "(%s) — a visitor copy-pastes that and hits an error" % (target, folder, PROJECT_NAME))


def test_the_licence_exists_and_says_what_it_does_not_cover():
    path = os.path.join(ROOT, "LICENSE")
    assert os.path.exists(path), "no LICENSE — nobody is legally allowed to reuse the code"
    text = open(path, encoding="utf-8").read()
    assert "MIT License" in text
    assert "does not cover" in text.lower(), \
        "the licence should be explicit that it covers the code and not the football data"


def test_attribution_appears_where_it_can_be_seen():
    """football-data.org's free tier asks for a visible credit. A comment in a source file is not a
    visible credit — it has to be in the page people actually look at, and in the README."""
    page = open(os.path.join(ROOT, "static", "index.html"), encoding="utf-8").read()
    assert "football-data.org" in page, "the published page must credit the live data source"
    assert "not affiliated" in page.lower(), "the page should disclaim any club/PL affiliation"
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    assert "Credits" in readme or "credits" in readme, "README should have a credits section"


# ════════════════════════════════════════════════════════════════════════════
#  4. CI and the scheduled job are wired
# ════════════════════════════════════════════════════════════════════════════
def test_the_workflows_exist_and_do_what_they_claim():
    for name in ("ci.yml", "weekly.yml", "pages.yml"):
        path = os.path.join(GITHUB, name)
        assert os.path.exists(path), "missing .github/workflows/%s" % name
        text = open(path, encoding="utf-8").read()
        assert "runs-on: ubuntu-latest" in text, "%s does not run anywhere" % name
    weekly = open(os.path.join(GITHUB, "weekly.yml"), encoding="utf-8").read()
    assert "schedule:" in weekly and "cron:" in weekly, "the weekly job is not scheduled"
    pages = open(os.path.join(GITHUB, "pages.yml"), encoding="utf-8").read()
    # a commit made with GITHUB_TOKEN does not trigger other workflows — the weekly refresh has to
    # wake the deploy explicitly, or the live site silently waits for the next human push
    assert "workflow_run" in pages, \
        "pages.yml must also trigger on the weekly job finishing, or its commit will not redeploy"
    assert "workflow_run" in pages and "Weekly update" in pages
