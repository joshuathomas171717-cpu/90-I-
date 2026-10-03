"""Wave 1 guards — deploy config, readiness, and the model artifact cache (P1.3, P1.4, P3.1, P3.2).

These tests exist because the headline deploy number is easy to *claim* and easy to regress: a future
change that builds the engine at import time would silently bring back the 7-second blank page. So the
properties that matter are asserted directly — the port opens before the model is ready, the API still
answers while it warms, and readiness tells the truth.
"""
import json
import os
import pickle
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest  # noqa: F401  (markers; also runs under tests/run_tests.py)

from _util import ROOT, skip

DATA = os.path.join(ROOT, "data")
SNAPSHOT = os.path.join(DATA, "predictions_2026_27_summary.json")
ARTIFACTS = os.path.join(ROOT, "artifacts")


# ── P1.3 container + host config ─────────────────────────────────────────────
def _read(name):
    path = os.path.join(ROOT, name)
    if not os.path.exists(path):
        raise AssertionError("%s is missing — the deploy story depends on it" % name)
    return open(path, encoding="utf-8").read()


def test_dockerfile_is_multi_stage_non_root_and_prewarms():
    df = _read("Dockerfile")
    assert len(re.findall(r"^FROM\s+\S+\s+AS\s+\S+", df, re.M)) >= 2, "expected a multi-stage build"
    assert re.search(r"^USER\s+(?!root)\S+", df, re.M), "container must not run as root"
    assert "HEALTHCHECK" in df, "no HEALTHCHECK"
    assert "/healthz" in df, "the Docker healthcheck should use liveness, not readiness"
    assert "ml_engine.py" in df, "the build should pre-warm the artifact cache"
    assert "requirements.txt" in df, "dependencies must be installed from requirements.txt (cached layer)"


def test_dockerignore_keeps_derived_files_out_of_the_image():
    ignore = _read(".dockerignore")
    for pattern in ("__pycache__", "artifacts", "*.zip", "_design"):
        assert pattern in ignore, ".dockerignore should exclude %s" % pattern


def test_host_configs_gate_traffic_on_readiness():
    import tomllib

    fly = tomllib.load(open(os.path.join(ROOT, "fly.toml"), "rb"))
    assert fly["http_service"]["internal_port"] == 8000
    paths = [c["path"] for c in fly["http_service"]["checks"]]
    assert "/readyz" in paths, "Fly needs the readiness check, not just liveness"
    assert fly["env"]["NT90_PRELOAD"] == "1", "Fly should preload so the model exists before the port opens"

    render = _read("render.yaml")
    assert "healthCheckPath: /readyz" in render
    assert "runtime: docker" in render and "dockerfilePath" in render


# ── P3.1 artifact cache ──────────────────────────────────────────────────────
def test_cache_key_moves_when_the_inputs_move(tmp_path=None):
    """The key must depend on the data and the engine source — otherwise a stale model gets served."""
    import ml_engine

    base = ml_engine.engine_fingerprint()
    assert base == ml_engine.engine_fingerprint(), "fingerprint must be deterministic"

    variant = os.path.join(DATA, "teams_2026_27.csv")
    tampered = str(variant) + ".probe"
    with open(variant, "rb") as fh:
        blob = fh.read()
    with open(tampered, "wb") as fh:                      # one extra byte == different league
        fh.write(blob + b"\n")
    try:
        assert ml_engine.engine_fingerprint(paths=[tampered] + [os.path.join(DATA, n)
                                                                for n in ml_engine.CACHE_INPUTS[1:]]) != base, \
            "a changed input file must change the cache key"
    finally:
        os.remove(tampered)

    assert ml_engine.engine_fingerprint(salt="v2") != base, "salt must change the key"


def test_artifact_cache_matches_the_published_numbers():
    """Whatever the model produced must survive the cache round-trip byte-for-byte in the headline figures."""
    if not os.path.exists(SNAPSHOT):
        skip("no published summary yet — run python3 run_all.py")
    import ml_engine

    key = ml_engine.engine_fingerprint()[:16]
    path = os.path.join(ARTIFACTS, "engine-%s.pkl" % key)
    if not os.path.exists(path):
        skip("no artifact cache for the current inputs — run python3 ml_engine.py")

    with open(path, "rb") as fh:
        blob = pickle.load(fh)
    assert blob["format"] == ml_engine.CACHE_FORMAT
    assert blob["key"] == ml_engine.engine_fingerprint(), "cache key must match the live inputs"
    for attr in ml_engine.CACHED_ATTRS:
        assert attr in blob["models"], "cache is missing the %s model" % attr

    published = json.load(open(SNAPSHOT, encoding="utf-8"))
    cached = blob["baseline_results"]
    assert cached["meta"]["n_simulations"] == published["meta"]["n_simulations"]
    for field in ("proj_pts", "title_prob", "relegation_prob"):
        got = {r["code"]: r[field] for r in cached["table_projections"]}
        want = {r["code"]: r[field] for r in published["table_projections"]}
        for code in want:
            assert abs(got[code] - want[code]) < 1e-9, \
                "%s changed across the cache boundary (%s: %s vs %s)" % (field, code, got[code], want[code])


@pytest.mark.slow
def test_engine_boots_from_cache_much_faster_than_training():
    """The whole point of P3.1. A cold boot trains; a warm boot must be an order of magnitude quicker."""
    if not os.path.isdir(ARTIFACTS) or not os.listdir(ARTIFACTS):
        skip("no artifact cache — run python3 ml_engine.py")
    code = (
        "import json, ml_engine, time;"
        "t=time.perf_counter();"
        "e=ml_engine.PremierLeagueMLEngine(n_sims=200);"
        "print(json.dumps({'hit': e.cache_hit, 'boot_ms': e.boot_ms, 'wall_ms': (time.perf_counter()-t)*1000}))"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert out.returncode == 0, out.stderr[-800:]
    res = json.loads(out.stdout.strip().splitlines()[-1])
    assert res["hit"] is True, "engine did not use the artifact cache"
    assert res["wall_ms"] < 1500, "cache boot took %.0f ms — target is under 1500 ms" % res["wall_ms"]


# ── P1.4 / P3.2 readiness + stale-while-revalidate ───────────────────────────
@pytest.mark.slow
def test_healthz_is_live_before_readyz_and_baseline_still_answers():
    """Port open first, model second, and a usable /api/baseline throughout."""
    if not os.path.exists(SNAPSHOT):
        skip("no baseline snapshot to serve while warming — run python3 run_all.py")

    # A fixed port is a trap: anything already listening there (a scratch server, a previous run)
    # silently becomes the thing under test. Ask the OS for a free one.
    _sock = socket.socket()
    _sock.bind(("127.0.0.1", 0))
    port = str(_sock.getsockname()[1])
    _sock.close()
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT,
                            env=dict(os.environ, PORT=port, NT90_ACCESS_LOG="0"),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def probe(path, timeout=10):
        try:
            r = urllib.request.urlopen("http://127.0.0.1:%s%s" % (port, path), timeout=timeout)
            return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace"), dict(exc.headers or {})
        except Exception as exc:
            return None, str(exc), {}

    try:
        # 1. the port must open well before the model is ready (that is the whole point)
        t0 = time.perf_counter()
        for _ in range(200):
            status, _, _ = probe("/healthz", timeout=1)
            if status == 200:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("server never answered /healthz on :%s" % port)
        port_open_ms = (time.perf_counter() - t0) * 1000

        health_body = json.loads(probe("/healthz")[1])
        assert health_body["status"] == "ok"

        # 2. /api/baseline must answer immediately — from the snapshot while the engine warms
        status, body, headers = probe("/api/baseline")
        assert status == 200, "/api/baseline returned %s while warming" % status
        assert json.loads(body)["table_projections"], "baseline payload was empty"
        first_source = headers.get("X-Data-Source")
        assert first_source in ("disk-cache", "engine"), "unexpected X-Data-Source: %r" % first_source

        # 3. readiness must converge, and say so honestly
        ready_ms = None
        t1 = time.perf_counter()
        for _ in range(120):
            status, body, _ = probe("/readyz", timeout=5)
            state = json.loads(body)
            if status == 200:
                assert state["ready"] is True and state["engine"] == "warm"
                ready_ms = (time.perf_counter() - t1) * 1000
                break
            assert status == 503 and state["ready"] is False, "readiness answered %s: %s" % (status, body)
            time.sleep(0.1)
        else:
            raise AssertionError("/readyz never became ready on :%s" % port)

        # 4. once warm, the engine itself serves the payload
        status, body, headers = probe("/api/baseline")
        assert status == 200 and headers.get("X-Data-Source") == "engine"
        assert len(body) > 1000

        # 5. CORS preflight must terminate promptly — an HTTP/1.1 response without Content-Length
        #    keeps the client waiting for a body that never comes (this shipped once already).
        #    Since P3.3 the answer is an allowlist rather than `*`: a stranger's origin gets nothing
        #    back, a legitimate one is echoed, and same-origin requests need no CORS header at all.
        def preflight(origin=None):
            headers = {"Access-Control-Request-Method": "POST"}
            if origin:
                headers["Origin"] = origin
            req = urllib.request.Request("http://127.0.0.1:%s/api/simulate" % port,
                                         method="OPTIONS", headers=headers)
            t = time.perf_counter()
            with urllib.request.urlopen(req, timeout=5) as resp:
                assert resp.status in (200, 204)
                assert resp.headers.get("Content-Length") == "0", "no Content-Length on the preflight"
                return dict(resp.headers), (time.perf_counter() - t)

        status, _, headers = probe("/api/simulate")   # warm the connection path first
        allowed, t2 = preflight("https://9-8.abcdef.e2b.app")
        assert allowed.get("Access-Control-Allow-Origin") == "https://9-8.abcdef.e2b.app"
        denied, _ = preflight("https://evil.example.com")
        assert denied.get("Access-Control-Allow-Origin") is None, "a stranger got CORS access"
        plain, _ = preflight()
        assert plain.get("Access-Control-Allow-Origin") is None, "same-origin needs no CORS header"
        assert t2 < 3, "OPTIONS preflight took too long — missing Content-Length?"

        # 6. the reported numbers are the published ones
        live = json.loads(body)
        published = json.load(open(SNAPSHOT, encoding="utf-8"))
        assert live["table_projections"][0]["code"] == published["table_projections"][0]["code"]
        assert abs(live["table_projections"][0]["proj_pts"] - published["table_projections"][0]["proj_pts"]) < 0.05

        print("\n  [timing] port open %.0f ms · first /api/baseline source=%s · ready %.0f ms"
              % (port_open_ms, first_source, ready_ms))
    finally:
        proc.terminate()
        proc.wait(timeout=10)
