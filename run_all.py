"""One-command rebuild: validate -> datasets -> ML engine -> backtest -> tests -> dashboard.

Both the data gate (validate_data.py) and the test suite are gates, not courtesies: a dataset that
fails 20-clubs/380-fixtures/table-reproduced checks, or an invariant, golden snapshot or portability
guard, stops the build before a dashboard is generated from suspect data.

Usage:  python3 run_all.py            # full run
        python3 run_all.py --fast     # skip the slow subprocess tests
        python3 run_all.py --retrain  # ignore the model artifact cache and train from scratch
Then:   PORT=8000 python3 server.py
"""
import subprocess
import sys
import os

BASE = os.path.dirname(os.path.abspath(__file__))
STEPS = [
    ("validate_data.py", "gating the dataset (20 clubs, 380 fixtures, table reproduced from results)"),
    ("fixtures_official.py", "validating the official 2026-27 fixture calendar"),
    ("data_builder.py", "building datasets (matches, fixtures, teams, players)"),
    ("ml_engine.py", "training models + running the baseline Monte Carlo"),
    ("backtest.py", "replaying the 2025-26 season for out-of-sample scoring"),
    # The pages are built *before* the tests, not after. Two of the checks read the generated site —
    # that its fixture text matches the projected-fixtures table, that a club page states its club's
    # projection — and a page built from the previous run's data is not a product bug, it is the
    # pipeline testing itself out of order. Building first and verifying second is also the order that
    # makes the checks mean something: nothing downstream of a test can be published unverified,
    # because run_all exits non-zero and CI goes red on the first failure either way.
    ("build_dashboard.py", "rebuilding static/index.html"),
    ("feeds.py", "writing the calendar feeds (league + one per club)"),
    ("site_pages.py", "writing crawlable pages, icons, previews and the sitemap"),
    ("tests/run_tests.py", "verifying invariants, golden snapshots, the generated site and portability"),
    # Last, because it can only be answered once the page has been rebuilt: does the page carry the
    # numbers the committed dataset describes? The library versions running here cannot affect the
    # answer, which is the point — see check_page_current.py.
    ("check_page_current.py", "checking the published page against the committed data"),
]


def main():
    fast = "--fast" in sys.argv
    retrain = "--retrain" in sys.argv
    for script, label in STEPS:
        if retrain and script == "ml_engine.py":
            label += " (forcing a retrain — artifact cache ignored)"
        print(f"\n▶ {script} — {label}")
        cmd = [sys.executable, os.path.join(BASE, script)]
        if fast and script.endswith("run_tests.py"):
            cmd.append("--fast")
        if retrain and script == "ml_engine.py":
            cmd.append("--force-retrain")
        r = subprocess.run(cmd, cwd=BASE)
        if r.returncode != 0:
            print(f"✗ {script} failed (exit {r.returncode})")
            return r.returncode
    print("\n✓ Rebuild complete. Serve it with:  PORT=8000 python3 server.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
