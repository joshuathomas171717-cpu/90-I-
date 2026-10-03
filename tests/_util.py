"""Shared helpers so the tests run identically under pytest and the zero-dep runner."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")

_CACHE = {}


class Skipped(Exception):
    pass


def skip(reason):
    """Skip a test in either runner."""
    try:
        import pytest
        pytest.skip(reason)
    except ImportError:
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
