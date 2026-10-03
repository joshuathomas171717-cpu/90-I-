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
    ("tests/run_tests.py", "verifying invariants, golden snapshots and portability"),
    ("build_dashboard.py", "rebuilding static/index.html"),
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
