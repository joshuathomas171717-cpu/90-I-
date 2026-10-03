"""Shared helpers so the tests run identically under pytest and the zero-dep runner."""
import json
import os
import sys

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
# ── pytest is optional, and that is a promise the tests have to keep ──────────
#
# The suite is designed to run with no test dependencies at all (`python3 tests/run_tests.py`).
# But several test modules were doing a bare `import pytest` for the sake of `@pytest.mark.slow`,
# and requirements.txt never actually installed pytest — the marker on that line referred to an
# extra that was never declared, so pip silently skipped it. Locally pytest happened to be present;
# in CI the runner died at import with ModuleNotFoundError, before a single test ran.
#
# So: resolve pytest if it is there, otherwise provide a shim with just the three things the tests
# use (`mark`, `skip`, `approx`). Test modules import it from here rather than from the top level,
# which is why they work under both runners.
try:
    import pytest as _real_pytest

    pytest = _real_pytest
    _SkipBase = _real_pytest.skip.Exception
except Exception:                                    # no pytest: the shim below is enough
    import types as _types

    class _MarkShim:
        """`@pytest.mark.slow` and friends become no-ops — the runner discovers tests its own way."""

        def __getattr__(self, _name):
            def decorator(*args, **kwargs):
                if len(args) == 1 and callable(args[0]) and not kwargs:
                    return args[0]
                return lambda fn: fn
            return decorator

    class _Approx:
        """Enough of pytest.approx for `value == pytest.approx(expected, abs=tol)`."""

        def __init__(self, expected, rel=None, abs=None):   # noqa: A002 - mirrors pytest's API
            self.expected, self.rel, self.abs = expected, rel, abs

        def __eq__(self, other):
            try:
                tol = self.abs if self.abs is not None else 0.0
                if self.rel is not None:
                    tol = max(tol, abs(self.expected) * self.rel)
                return abs(float(other) - float(self.expected)) <= tol
            except (TypeError, ValueError):
                return NotImplemented

        def __repr__(self):
            return "approx(%r, abs=%r, rel=%r)" % (self.expected, self.abs, self.rel)

    class _SkipSignal(Exception):
        """What the shim's pytest.skip() raises. _util.Skipped subclasses this, so a skip is a skip."""

    def _shim_skip(reason=""):
        raise _SkipSignal(reason)

    pytest = _types.ModuleType("pytest")
    pytest.mark = _MarkShim()
    pytest.approx = _Approx
    pytest.skip = _shim_skip
    _SkipBase = _SkipSignal


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


# ── the numerical environment, for the golden snapshot ────────────────────────
def env_versions():
    """The versions that decide the last decimal of every projected number.

    Golden snapshots compare numbers produced by linear algebra. Different numpy/scipy/sklearn
    releases legitimately produce slightly different coefficients, so the snapshot records the
    environment it was taken in and tests/test_golden.py widens its band — with a visible note —
    when the running environment differs. Seeded and deterministic within one environment.
    """
    out = {"python": "%d.%d.%d" % sys.version_info[:3]}
    for mod in ("numpy", "pandas", "scipy", "sklearn"):
        try:
            out[mod] = __import__(mod).__version__
        except Exception:
            out[mod] = None
    return out
