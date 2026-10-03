"""Zero-dependency test runner.

`python3 tests/run_tests.py`            — full run, including slow subprocess tests
`python3 tests/run_tests.py --fast`     — skip tests marked @pytest.mark.slow
`python3 tests/run_tests.py -k golden`  — filter by name

Works with or without pytest installed, so the safety net never depends on an extra package.
"""
import importlib.util
import os
import sys
import time
import traceback

import _util

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

SLOW_MARKER = "pytest.mark.slow"


def discover():
    for name in sorted(os.listdir(HERE)):
        if name.startswith("test_") and name.endswith(".py"):
            spec = importlib.util.spec_from_file_location(name[:-3], os.path.join(HERE, name))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            yield name, mod


def main(argv):
    fast = "--fast" in argv
    filt = None
    if "-k" in argv:
        filt = argv[argv.index("-k") + 1]

    passed, failed, skipped = [], [], []
    t0 = time.perf_counter()

    for filename, mod in discover():
        for attr in sorted(dir(mod)):
            if not attr.startswith("test_"):
                continue
            fn = getattr(mod, attr)
            if not callable(fn):
                continue
            full = f"{filename}::{attr}"
            if filt and filt not in full:
                continue
            src = ""
            try:
                src = __import__("inspect").getsource(fn)
            except Exception:
                pass
            if fast and SLOW_MARKER in src:
                skipped.append((full, "slow (--fast)"))
                continue
            # supply pytest's tmp_path fixture ourselves when needed
            kwargs = {}
            if "tmp_path" in __import__("inspect").signature(fn).parameters:
                import tempfile
                from pathlib import Path
                kwargs["tmp_path"] = Path(tempfile.mkdtemp(prefix="ntest-"))
            try:
                fn(**kwargs)
                passed.append(full)
                print(f"  ✓ {full}")
            except _util.Skipped as exc:
                skipped.append((full, str(exc)))
                print(f"  – {full}  (skipped: {exc})")
            except Exception as exc:  # noqa: BLE001
                # pytest.skip() raised directly (not via _util.skip) is still a skip, not a crash.
                if type(exc).__module__.startswith("_pytest") and "Skipped" in type(exc).__name__:
                    skipped.append((full, str(exc)))
                    print(f"  – {full}  (skipped: {exc})")
                    continue
                failed.append((full, exc))
                print(f"  ✗ {full}\n      {type(exc).__name__}: {str(exc)[:400]}")
                if os.environ.get("NTEST_TRACE"):
                    traceback.print_exc()

    dt = time.perf_counter() - t0
    print(f"\n{'─' * 62}")
    print(f"  {len(passed)} passed · {len(failed)} failed · {len(skipped)} skipped   ({dt:.1f}s)")
    if failed:
        print("\n  FAILURES")
        for full, exc in failed:
            print(f"    {full}\n      {type(exc).__name__}: {str(exc)[:220]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
