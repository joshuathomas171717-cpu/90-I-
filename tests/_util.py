"""Shared helpers so the tests run identically under pytest and the zero-dep runner."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")

_CACHE = {}


# One exception that BOTH runners understand.
#
# The zero-dep runner (tests/run_tests.py) catches `Skipped`; pytest catches its own exception class.
# Making ours a subclass of pytest's means a skipped test is a skip under either — which is the whole
# point of the shared helper. It was neither before: the helper raised pytest's exception
# unconditionally when pytest was importable, so the zero-dep runner crashed outright the first time
# a test wanted to skip (a fresh clone with no artifacts/ built yet — exactly the case a new reader
# hits when they run the tests before running the pipeline).
try:
    import pytest as _pytest

    _SkipBase = _pytest.skip.Exception
except Exception:                                    # pytest not installed: fine, below is enough
    _SkipBase = Exception


class Skipped(_SkipBase):
    """Raised by skip(). A skip under pytest *and* under tests/run_tests.py."""


def skip(reason):
    """Skip a test in either runner."""
    raise Skipped(reason)


def load_json(path):
    if path not in _CACHE:
        _CACHE[path] = json.load(open(path, encoding="utf-8"))
    return _CACHE[path]


def summary():
    return load_json(os.path.join(DATA, "predictions_2026_27_summary.json"))


def backtest():
    return load_json(os.path.join(DATA, "backtest_2025_26.json"))


def golden():
    path = os.path.join(HERE, "golden", "golden.json")
    if not os.path.exists(path):
        skip("no golden snapshot yet - run python3 tests/make_golden.py")
    return load_json(path)


def read_csv(name):
    import csv
    return list(csv.DictReader(open(os.path.join(DATA, name), encoding="utf-8")))
