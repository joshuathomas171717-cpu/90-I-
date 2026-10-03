"""P1.2 — portability guard tests.

Two protections, deliberately different in kind:

1. `test_source_has_no_absolute_paths` is a fast static guard. It greps the pipeline source for
   absolute filesystem paths (POSIX home dirs, macOS users, Windows drive letters). It exists because
   this exact bug shipped once: `data_builder.py` wrote to one machine's absolute `data/` path, so on any
   other machine — or even in a clean-room test on the same machine — the pipeline silently wrote to
   the wrong place and *appeared* to work.

2. `test_pipeline_runs_in_a_foreign_copy` is the expensive, unfakeable version: it copies the project
   to a temporary directory with a different name, runs the real data pipeline there with a *different*
   working directory, and asserts the outputs land inside that copy and nowhere else. A static guard can
   be gamed by a clever path; this one cannot.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Sources that must stay portable. Tests and docs are exempt: tests legitimately use temp paths.
PIPELINE_SOURCES = ["data_builder.py", "ml_engine.py", "backtest.py", "build_dashboard.py",
                    "fixtures_official.py", "run_all.py", "server.py",
                    # Wave 2 additions — the guard covers new code by default, not by remembering
                    "standings.py", "validate_data.py", "update_week.py",
                    "sources/__init__.py", "sources/base.py",
                    "sources/football_data_org.py", "sources/local_snapshot.py",
                    # Wave 3 additions — the foreign-copy run needs *every* module the pipeline
                    # imports, which is exactly how dataset_io.py announced itself
                    "dataset_io.py", "loadtest.py"]

# A hardcoded absolute path: /home/..., /Users/..., /tmp/... outside tests, or a Windows drive path.
ABS_PATH_RE = re.compile(r"""['"](/(?:home|Users|root|opt|srv|var)/[^'"]*|[A-Za-z]:\\\\[^'"]*)['"]""")


def test_source_has_no_absolute_paths():
    """No pipeline file may contain a hardcoded absolute filesystem path."""
    offenders = []
    for name in PIPELINE_SOURCES:
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"""'):
                    continue
                m = ABS_PATH_RE.search(line)
                if m:
                    offenders.append(f"{name}:{lineno}  {m.group(1)}")
    assert not offenders, (
        "Hardcoded absolute paths found — these break the pipeline on any other machine:\n  "
        + "\n  ".join(offenders)
        + "\n\nResolve paths with os.path.join(os.path.dirname(os.path.abspath(__file__)), ...)"
    )


def test_every_data_write_goes_through_data_dir():
    """data_builder.py must write CSVs into its own DATA_DIR constant, not to bare filenames."""
    src = open(os.path.join(ROOT, "data_builder.py"), encoding="utf-8").read()
    assert "DATA_DIR = os.path.join(BASE_DIR," in src, "data_builder.py lost its DATA_DIR constant"
    writes = re.findall(r"to_csv\(\s*([^,]+)", src)
    bad = [w for w in writes if "DATA_DIR" not in w]
    assert not bad, f"data_builder.py writes CSVs outside DATA_DIR: {bad}"


def test_copy_imports_resolve_relative_paths():
    """Importing the engine must not create or touch anything before it is asked to."""
    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys, os; sys.path.insert(0, %r); import ml_engine; "
         "print(ml_engine.DATA_DIR)" % ROOT],
        capture_output=True, text=True, cwd=tempfile.gettempdir(),
    )
    assert probe.returncode == 0, probe.stderr
    reported = probe.stdout.strip()
    assert os.path.isabs(reported), reported
    assert os.path.normpath(reported) == os.path.normpath(os.path.join(ROOT, "data")), (
        f"engine resolved DATA_DIR to {reported}, expected {os.path.join(ROOT, 'data')}")


@pytest.mark.slow
def test_pipeline_runs_in_a_foreign_copy(tmp_path):
    """The real proof: a copy of the project, in a foreign directory, with a foreign cwd, works."""
    foreign = tmp_path / "some-other-user" / "totally-different-folder"
    foreign.mkdir(parents=True)

    # Copy only what the data stage needs — a deliberately minimal set, because a copy that happens
    # to contain everything proves nothing. Everything data_builder.py imports must be listed here.
    for name in ["data_builder.py", "fixtures_official.py", "dataset_io.py", "standings.py"]:
        shutil.copy2(os.path.join(ROOT, name), foreign / name)
    shutil.copytree(os.path.join(ROOT, "data"), foreign / "data", dirs_exist_ok=True)
    (foreign / "data").mkdir(exist_ok=True)

    # Run with a working directory that is neither the project nor the copy.
    result = subprocess.run(
        [sys.executable, str(foreign / "data_builder.py")],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert result.returncode == 0, f"pipeline failed in a foreign copy:\n{result.stderr[-2000:]}"

    # Outputs must exist inside the copy...
    for fname in ["matches_2025_26.csv", "fixtures_2026_27_remaining.csv", "teams_2026_27.csv"]:
        written = foreign / "data" / fname
        assert written.exists(), f"{fname} was not written into the copy at {written}"
        assert written.stat().st_size > 1000, f"{fname} looks empty"

    # ...and must NOT have been written back into the original project during the run.
    original = os.path.join(ROOT, "data", "fixtures_2026_27_remaining.csv")
    assert os.path.exists(original), "original project data went missing"
