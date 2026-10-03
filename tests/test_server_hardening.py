"""Wave 3 guards — transport hardening and simulation protection (P3.3 / P3.4 / P3.5).

Split in two, following the same logic as the weekly-job tests:

1. **Pure units.** The scenario contract, the origin allowlist, the encoding cache, the token bucket
   and the LRU all have exact behaviours that can be asserted without a socket.
2. **One live server**, booted in a subprocess on a free port, then attacked: gzip, ETag/304, size
   caps, schema rejection, the rate limiter, the simulation cache and the stats route. Everything the
   load test measured but nothing the load test can *guard*.

The live test is marked slow: it waits for a real warm-up.
"""
import gzip
import json
import os
import re
import socket
import subprocess
import sys
import time
import http.client

import pytest

from _util import ROOT, skip

sys.path.insert(0, ROOT)

import server  # noqa: E402  (the module under test)


# ════════════════════════════════════════════════════════════════════════════
#  1. pure units
# ════════════════════════════════════════════════════════════════════════════
CODES = {"ARS", "MCI", "LIV", "NEW"}
PLAYERS = {"haaland", "saka", "isak"}


def test_the_scenario_contract_accepts_what_the_ui_actually_sends():
    """The dashboard posts exactly this shape — including `defence`, British spelling. It must pass
    validation *and* be normalised to one canonical form, because the engine reading only `defense`
    was a silent bug for as long as nobody validated the payload."""
    body = {"n_sims": 3000,
            "player_injuries": {"haaland": 4},
            "team_boosts": {"ARS": {"attack": 6, "defence": 4}},
            "points_deductions": {"MCI": 10},
            "custom_scores": {"LIV-NEW": [2, 1]}}
    scenario, n_sims, errors = server.validate_scenario(body, CODES, PLAYERS)
    assert errors == [], errors
    assert n_sims == 3000
    assert scenario["player_injuries"] == {"haaland": 4}
    assert scenario["team_boosts"]["ARS"] == {"attack": 6.0, "defence": 4.0}
    assert scenario["points_deductions"] == {"MCI": 10}
    assert scenario["custom_scores"] == {"LIV-NEW": [2, 1]}

    # the American spelling is the same knob, not a second one
    american, _, err2 = server.validate_scenario({"team_boosts": {"ARS": {"defense": 7}}}, CODES, PLAYERS)
    assert err2 == []
    assert american["team_boosts"]["ARS"]["defence"] == 7.0


def test_the_scenario_contract_rejects_nonsense_with_readable_reasons():
    bad = {"n_sims": "many", "wat": 1,
           "player_injuries": {"nobody": 3},
           "team_boosts": {"ARS": {"attack": "lots"}, "ZZZ": {"attack": 5}},
           "points_deductions": {"MCI": "six"},
           "custom_scores": {"ARS-ARS": [1, 0], "LIV-NEW": [99, 0]}}
    scenario, n_sims, errors = server.validate_scenario(bad, CODES, PLAYERS)
    assert scenario is None and n_sims is None
    joined = " | ".join(errors)
    for expected in ("unknown field", "n_sims must be an integer", "unknown player_id",
                     "must be a number", "unknown club", "ARS-ARS", "between 0 and 12"):
        assert expected in joined, (expected, joined)


def test_clamping_is_a_clamp_not_a_rejection():
    """Out-of-range numbers are clamped and reported — only *shapes* are fatal."""
    scenario, n_sims, errors = server.validate_scenario(
        {"n_sims": 10 ** 9, "team_boosts": {"ARS": {"attack": 900}},
         "points_deductions": {"MCI": -5}, "player_injuries": {"saka": 99}}, CODES, PLAYERS)
    assert errors == []
    assert n_sims == server.MAX_SIMS
    assert scenario["team_boosts"]["ARS"]["attack"] == 25.0
    assert scenario["points_deductions"]["MCI"] == 0
    assert scenario["player_injuries"]["saka"] == 33


def test_a_custom_score_can_be_given_as_a_string_or_a_pair():
    for value in ("2-1", [2, 1], (2, 1)):
        scenario, _, errors = server.validate_scenario({"custom_scores": {"LIV-NEW": value}},
                                                       CODES, PLAYERS)
        assert errors == [], (value, errors)
        assert scenario["custom_scores"]["LIV-NEW"] == [2, 1]


def test_origin_allowlist_covers_the_preview_and_localhost_but_not_strangers():
    assert server.origin_allowed("") is True                                  # same-origin / curl
    assert server.origin_allowed("https://8123-abcdef.e2b.app") is True       # the preview host
    assert server.origin_allowed("http://localhost:8000") is True
    assert server.origin_allowed("http://127.0.0.1:5173") is True
    assert server.origin_allowed("https://evil.example.com") is False
    assert server.origin_allowed("https://e2b.app.evil.com") is False         # suffix, not substring


def test_prepared_bodies_compress_once_and_stay_byte_identical():
    raw = b"x" * 40 + b"the quick brown fox " * 400
    prepared = server.Prepared(raw)
    assert prepared.gzipped is not None
    assert gzip.decompress(prepared.gzipped) == raw
    body, enc = prepared.body_for("gzip, deflate, br")
    assert enc == "gzip" and body == prepared.gzipped
    body, enc = prepared.body_for("identity")
    assert enc == "" and body == raw
    # tiny bodies are not worth compressing
    small = server.Prepared(b"{}")
    assert small.gzipped is None and small.body_for("gzip") == (b"{}", "")


def test_the_cache_key_ignores_key_order_but_not_content():
    a = server.ResponseCache.key_for({"team_boosts": {"ARS": {"attack": 5, "defence": 1}}}, 3000, "model-x")
    b = server.ResponseCache.key_for({"team_boosts": {"ARS": {"defence": 1, "attack": 5}}}, 3000, "model-x")
    c = server.ResponseCache.key_for({"team_boosts": {"ARS": {"attack": 6, "defence": 1}}}, 3000, "model-x")
    d = server.ResponseCache.key_for({"team_boosts": {"ARS": {"attack": 5, "defence": 1}}}, 3001, "model-x")
    e = server.ResponseCache.key_for({"team_boosts": {"ARS": {"attack": 5, "defence": 1}}}, 3000, "model-y")
    assert a == b, "the same scenario in a different key order must hit the same cache entry"
    assert len({a, c, d, e}) == 4, "content, sample count and model version must each change the key"


def test_the_lru_evicts_the_oldest_and_counts_hits():
    cache = server.ResponseCache(maxsize=3)
    for i in range(3):
        cache.put("k%d" % i, server.Prepared(b"body-%d" % i, compress=False))
    cache.get("k0")                      # refresh k0's recency
    cache.put("k3", server.Prepared(b"body-3", compress=False))
    assert cache.get("k1") is None, "k1 was the least recently used and should be gone"
    assert cache.get("k0") is not None and cache.get("k3") is not None
    stats = cache.stats()
    assert stats["size"] == 3 and stats["hits"] == 3 and stats["misses"] == 1
    assert stats["hit_rate_pct"] == 75.0


def test_the_token_bucket_allows_a_burst_then_denies_then_refills():
    # Essentially no refill, so the burst is deterministic — with a fast refill the clock can hand
    # back a token between two calls and the assertion becomes a coin flip.
    limiter = server.TokenBucketLimiter(burst=3, refill_per_s=0.0001)
    assert [limiter.check("1.2.3.4")[0] for _ in range(3)] == [True, True, True]
    allowed, remaining, wait = limiter.check("1.2.3.4")
    assert allowed is False and remaining == 0 and wait > 0
    assert limiter.check("5.6.7.8")[0] is True, "buckets are per client, not global"
    assert limiter.rejections == 1

    # a token comes back in time, and a refund gives one back immediately
    fast = server.TokenBucketLimiter(burst=1, refill_per_s=500.0)
    assert fast.check("9.9.9.9")[0] is True
    assert fast.check("9.9.9.9")[0] is False
    time.sleep(0.01)
    assert fast.check("9.9.9.9")[0] is True
    assert fast.check("9.9.9.9")[0] is False
    fast.refund("9.9.9.9")
    assert fast.check("9.9.9.9")[0] is True, "a refunded token must be spendable"


# ════════════════════════════════════════════════════════════════════════════
#  2. one live server, attacked politely
# ════════════════════════════════════════════════════════════════════════════
LIVE_MAX_SIMS = 1200        # the ceiling the Live instance below is started with
LIVE_RATE_BURST = 4         # ...and its token bucket size


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Live:
    """A real server process with test-sized limits, torn down whatever happens."""

    def __init__(self):
        self.port = _free_port()
        self.proc = None

    def __enter__(self):
        env = dict(os.environ, PORT=str(self.port), NT90_PRELOAD="1",
                   NT90_RATE_BURST=str(LIVE_RATE_BURST),
                   NT90_RATE_REFILL="0.5", NT90_SIM_CONCURRENCY="1", NT90_MAX_SIMS=str(LIVE_MAX_SIMS),
                   NT90_MIN_SIMS="500", NT90_MAX_BODY_BYTES="4096", NT90_MAX_URL_CHARS="512",
                   NT90_BACKLOG="32")
        self.proc = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        deadline = time.time() + 90
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError("server died during warm-up:\n" + self.proc.stdout.read()[-800:])
            try:
                code, _, _ = self.call("/readyz")
                if code == 200:
                    return self
            except Exception:
                pass
            time.sleep(0.5)
        raise AssertionError("server never became ready")

    def __exit__(self, *exc):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        return False

    def call(self, path, method="GET", body=None, headers=None, timeout=90):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        h = {"User-Agent": "test", "Accept-Encoding": "gzip"}
        h.update(headers or {})
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=h)
        resp = conn.getresponse()
        payload = resp.read()
        head = dict(resp.getheaders())
        head["_wire_bytes"] = len(payload)             # what actually crossed the socket
        if head.get("Content-Encoding") == "gzip":      # the helper's job, not each caller's
            payload = gzip.decompress(payload)
        conn.close()
        return resp.status, head, payload


@pytest.mark.slow
def test_live_transport_and_protection():
    with Live() as srv:
        # ── compression ─────────────────────────────────────────────────────
        code, head, body = srv.call("/")
        assert code == 200
        assert head.get("Content-Encoding") == "gzip", "the 500 KB page must go out gzipped"
        assert head["_wire_bytes"] < 400_000, "gzip barely helped: %d bytes on the wire" % head["_wire_bytes"]
        assert len(body) > 400_000, "the decoded page should still be the ~500 KB document"
        raw = body                       # the helper already decoded the gzip envelope
        assert raw.startswith(b"<!DOCTYPE html>")
        assert "Accept-Encoding" in head.get("Vary", "")

        # identity clients still get the same bytes
        code, head, plain = srv.call("/", headers={"Accept-Encoding": "identity"})
        assert head.get("Content-Encoding") is None and plain == raw

        # ── ETag / 304 ──────────────────────────────────────────────────────
        etag = head.get("ETag")
        assert etag and len(etag) > 8
        code, head2, body2 = srv.call("/", headers={"If-None-Match": etag})
        assert code == 304 and body2 == b""

        # ── security headers, including on an error page ────────────────────
        for path in ("/", "/nope"):
            _, head3, _ = srv.call(path)
            assert head3.get("X-Content-Type-Options") == "nosniff"
            assert head3.get("Referrer-Policy") == "no-referrer"
            assert "Content-Security-Policy" in head3
        assert not head.get("Access-Control-Allow-Origin"), "no Origin means no CORS header at all"
        _, h_ok, _ = srv.call("/", headers={"Origin": "https://9-8.e2b.app"})
        assert h_ok.get("Access-Control-Allow-Origin") == "https://9-8.e2b.app"
        _, h_bad, _ = srv.call("/", headers={"Origin": "https://evil.example"})
        assert h_bad.get("Access-Control-Allow-Origin") is None

        # ── size and length caps ────────────────────────────────────────────
        code, _, body = srv.call("/api/simulate", "POST", b"{" + b'"pad":"' + b"x" * 8000 + b'"}')
        assert code == 413, code
        code, _, _ = srv.call("/" + "y" * 600)
        assert code == 414, code

        # ── schema rejection, with reasons ──────────────────────────────────
        code, _, body = srv.call("/api/simulate", "POST",
                                 {"team_boosts": {"NOPE": {"attack": 1}}, "n_sims": "x"})
        assert code == 400, code
        details = json.loads(body)["details"]
        assert any("unknown club" in d for d in details) and any("n_sims" in d for d in details)

        # ── n_sims ceiling is enforced by the server, not the caller ────────
        code, head, body = srv.call("/api/simulate", "POST", {"n_sims": 999999,
                                                              "team_boosts": {"ARS": {"attack": 1}}})
        assert code == 200
        # the *server's* ceiling (1,200), not this process's default — that is the whole point
        assert json.loads(body)["meta"]["n_simulations"] == LIVE_MAX_SIMS
        assert head.get("X-Sim-Cache") == "miss"

        # ── the cache makes a repeat scenario free, and it is not rate limited ──
        code, head, _ = srv.call("/api/simulate", "POST", {"n_sims": 999999,
                                                           "team_boosts": {"ARS": {"attack": 1}}})
        assert code == 200 and head.get("X-Sim-Cache") == "hit"

        # ── the token bucket ────────────────────────────────────────────────
        statuses = []
        for i in range(LIVE_RATE_BURST * 3):
            code, head, body = srv.call("/api/simulate", "POST",
                                        {"points_deductions": {"ARS": 50 + i}})
            statuses.append(code)
            if code == 429:
                assert head.get("Retry-After") and head.get("X-RateLimit-Remaining") == "0"
                break
        assert 429 in statuses, statuses

        # ── stats publishes what happened ───────────────────────────────────
        code, _, body = srv.call("/api/stats")
        assert code == 200
        stats = json.loads(body)
        assert stats["simulation"]["cache"]["hits"] >= 1
        assert stats["simulation"]["rate_limit_rejections"] >= 1
        assert stats["limits"]["sim_concurrency"] == 1
        assert "GET /" in stats["metrics"]["latency_ms"]
        assert stats["process"]["rss_mb"] is None or stats["process"]["rss_mb"] > 0

        # ── the baseline is served from the cache and still parses ──────────
        code, head, body = srv.call("/api/baseline")
        assert code == 200 and head.get("X-Data-Source") in ("engine", "disk-cache")
        payload = json.loads(body)
        assert payload["meta"]["next_gw"] == 6


@pytest.mark.slow
def test_live_server_survives_concurrent_simulations():
    """The overload phase that killed the process before the concurrency cap existed.

    Twenty-four simultaneous simulations against one slot: the server must answer all of them (queued,
    slowly) or shed load with 503 — and above all it must still be alive at the end.
    """
    import threading
    with Live() as srv:
        results, lock = [], threading.Lock()

        def fire(i):
            try:
                code, head, _ = srv.call("/api/simulate", "POST", {"n_sims": 600,
                                                                   "points_deductions": {"ARS": 1 + i}})
            except Exception as exc:
                code = "err:%s" % type(exc).__name__
            with lock:
                results.append(code)

        threads = [threading.Thread(target=fire, args=(i,)) for i in range(24)]
        t0 = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall = time.perf_counter() - t0

        counts = {}
        for r in results:
            counts[r] = counts.get(r, 0) + 1
        assert len(results) == 24, counts
        assert not [r for r in results if isinstance(r, str) and r.startswith("err:")], counts
        assert all(r in (200, 429, 503) for r in results), counts

        # and it is still serving
        code, _, _ = srv.call("/healthz")
        assert code == 200, "the server did not survive the burst"
        print("     [overload] %s in %.1fs — still alive" % (counts, wall))
