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
    # The folder a `git clone` of this README's own clone line would create. This is the name a
    # visitor actually ends up standing in — the repository is 90-I- even though the project inside
    # it is NINETY+ — and the quick start has to tell them to cd into it.
    clone = re.search(r"git clone\s+(\S+)", readme)
    if clone:
        acceptable.add(os.path.basename(clone.group(1)).removesuffix(".git"))
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
    for name in ("ci.yml", "weekly-update.yml", "pages.yml"):
        path = os.path.join(GITHUB, name)
        assert os.path.exists(path), "missing .github/workflows/%s" % name
        text = open(path, encoding="utf-8").read()
        assert "runs-on: ubuntu-latest" in text, "%s does not run anywhere" % name
    weekly = open(os.path.join(GITHUB, "weekly-update.yml"), encoding="utf-8").read()
    assert "schedule:" in weekly and "cron:" in weekly, "the weekly job is not scheduled"
    assert "workflow_dispatch:" in weekly, "the weekly job needs a manual trigger too"
    # Renamed from weekly.yml rather than added alongside it: two crons on the same schedule would
    # race each other and commit the same refresh twice.
    assert not os.path.exists(os.path.join(GITHUB, "weekly.yml")), \
        "weekly.yml and weekly-update.yml would both fire on the same cron"
    pages = open(os.path.join(GITHUB, "pages.yml"), encoding="utf-8").read()
    # a commit made with GITHUB_TOKEN does not trigger other workflows — the weekly refresh has to
    # wake the deploy explicitly, or the live site silently waits for the next human push
    assert "workflow_run" in pages, \
        "pages.yml must also trigger on the weekly job finishing, or its commit will not redeploy"
    assert "workflow_run" in pages and "Weekly update" in pages


# ════════════════════════════════════════════════════════════════════════════
#  5. the dependency declarations mean what they say
#
#  The first CI runs failed here, and the failure was invisible locally: requirements.txt carried
#  `pytest>=8.0 ; extra == "dev"`. Nothing declares extras for a requirements file, so the marker was
#  simply never true, pip installed nothing, and the test modules died on import in CI — while the
#  machine this was developed on already had pytest and never noticed. These checks are cheap and
#  they make that whole class of mistake impossible to repeat.
# ════════════════════════════════════════════════════════════════════════════
import ast  # noqa: E402  (kept next to the checks that use it)

REQ_FILES = ("requirements.txt", "requirements-dev.txt")
#: Import name → distribution name, where they differ.
DISTRIBUTION_NAMES = {"sklearn": "scikit-learn", "yaml": "pyyaml"}
#: Allowed to be imported and not declared, with a reason.
IMPORT_EXEMPTIONS = {"pytest": "optional test tooling, resolved by tests/_util.py with a fallback"}


def _requirements_text():
    for name in REQ_FILES:
        path = os.path.join(ROOT, name)
        if os.path.exists(path):
            yield name, open(path, encoding="utf-8").read()


def test_no_environment_markers_that_can_never_activate():
    """A requirements line ending in `; extra == "..."` is a line pip will never install.

    Extras are declared by a package's own metadata (setup.py / pyproject), never by a
    requirements file. `pip install -r requirements.txt` also installs nothing for such a line, and
    does not warn. If you want dev-only packages, put them in requirements-dev.txt.
    """
    for name, text in _requirements_text():
        for line in text.splitlines():
            code = line.split("#", 1)[0].strip()
            if not code:
                continue
            assert "extra ==" not in code, (
                "%s: %r can never be installed — nothing declares extras for a requirements file. "
                "Move it to requirements-dev.txt instead." % (name, code))
            assert "extra==" not in code, "%s: %r can never be installed" % (name, code)


def test_dev_requirements_include_the_runtime_requirements():
    """One command has to be enough: CI installs requirements-dev.txt and expects the pipeline too."""
    dev = open(os.path.join(ROOT, "requirements-dev.txt"), encoding="utf-8").read()
    assert re.search(r"^-r\s+requirements\.txt\s*$", dev, re.M), \
        "requirements-dev.txt must start from `-r requirements.txt`, or a single install misses the pipeline"


def test_pytest_is_only_imported_through_the_optional_resolver():
    """Test modules import pytest from tests/_util.py, which falls back to a shim when it is absent.

    A bare `import pytest` at module level turns a missing test dependency into a crashed test run,
    which is exactly what CI hit. Importing it from _util keeps the suite runnable on a bare
    interpreter — the promise `python3 tests/run_tests.py` makes and tests without pytest.
    """
    tests_dir = os.path.join(ROOT, "tests")
    for name in sorted(os.listdir(tests_dir)):
        if not (name.startswith("test_") and name.endswith(".py")):
            continue
        path = os.path.join(tests_dir, name)
        tree = ast.parse(open(path, encoding="utf-8").read(), path)
        for node in tree.body:  # module level only: imports inside a function are fine
            if isinstance(node, ast.Import):
                assert all(a.name.split(".")[0] != "pytest" for a in node.names), \
                    "tests/%s does a bare `import pytest` — use `from _util import pytest`" % name
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "pytest":
                assert False, "tests/%s imports pytest directly — use `from _util import pytest`" % name


def test_every_third_party_import_is_declared():
    """Every module-level import in the pipeline and the tests is either stdlib, local, or declared.

    This is the check that would have caught the missing pytest, and it will catch the next missing
    dependency before CI does. Import-time-only is deliberate: an import inside a function is a
    documented optional path, not a hard requirement.
    """
    declared = set()
    for _, text in _requirements_text():
        for line in text.splitlines():
            code = line.split("#", 1)[0].strip()
            if not code or code.startswith("-"):
                continue
            m = re.match(r"^([A-Za-z0-9_.\-]+)", code)
            if m:
                declared.add(m.group(1).lower().replace("_", "-"))

    local = {"__init__"}
    for dirname in (ROOT, os.path.join(ROOT, "tests"), os.path.join(ROOT, "sources")):
        if not os.path.isdir(dirname):
            continue
        for name in os.listdir(dirname):
            if name.endswith(".py"):
                local.add(name[:-3])
            elif os.path.isdir(os.path.join(dirname, name)):
                local.add(name)

    seen = {}
    scanned = [(ROOT, n) for n in sorted(os.listdir(ROOT)) if n.endswith(".py")]
    for sub in ("tests", "sources"):
        d = os.path.join(ROOT, sub)
        if os.path.isdir(d):
            scanned += [(d, n) for n in sorted(os.listdir(d)) if n.endswith(".py")]

    for d, name in scanned:
        path = os.path.join(d, name)
        tree = ast.parse(open(path, encoding="utf-8").read(), path)
        tops = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                tops |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                tops.add(node.module.split(".")[0])
        for top in tops:
            if top in sys.stdlib_module_names or top in local or top in IMPORT_EXEMPTIONS:
                continue
            seen.setdefault(top, []).append(os.path.relpath(path, ROOT))

    undeclared = {}
    for top, where in seen.items():
        dist = DISTRIBUTION_NAMES.get(top, top).lower().replace("_", "-")
        if dist not in declared and top.lower() not in declared:
            undeclared[top] = where
    assert not undeclared, (
        "imported at module level but not in %s: %s"
        % (" or ".join(REQ_FILES),
           ", ".join("%s (%s)" % (k, ", ".join(sorted(set(v)))) for k, v in sorted(undeclared.items()))))
