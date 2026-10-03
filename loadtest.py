"""loadtest.py — does this instance hold up, and where does it bend? (P3.5)

Hammer a running NINETY+ server and report p50/p95/p99, throughput and status mix per phase. Stdlib
only, so it runs anywhere the server does. Point it at a *scratch* instance, never the one people are
using:

    # terminals 1 and 2
    PORT=8403 NT90_PRELOAD=1 NT90_RATE_BURST=100000 python3 server.py
    python3 loadtest.py --url http://127.0.0.1:8403 --phase all

Phases, because they fail in completely different ways:

    static     GET /                     the gzipped dashboard — CPU is gzip + socket, not the model
    revalidate GET / with If-None-Match  the cheap path a returning visitor actually takes
    baseline   GET /api/baseline         the warm engine serialising 105 KB of JSON
    simulate   POST /api/simulate        the only route that burns real CPU (Monte Carlo)
    cache      POST /api/simulate (same) whether the LRU makes a repeat scenario free
    overload   POST /api/simulate ×N     what happens past the thread-pool cap: 503, not a hang

429/503 are counted separately from errors on purpose: under a burst those are the server protecting
itself, which is the designed behaviour, not a failure. Only 5xx that are *not* the pool cap, and any
connection error, count against the run.
"""
import argparse
import http.client
import json
import statistics
import sys
import threading
import time
import urllib.parse

DEFAULT_SCENARIOS = [
    {"n_sims": 1000, "team_boosts": {"ARS": {"attack": 6, "defence": 0}}},
    {"n_sims": 1000, "points_deductions": {"MCI": 10}},
    {"n_sims": 1000, "player_injuries": {"haaland": 6}},
    {"n_sims": 1000, "custom_scores": {"LIV-MCI": [2, 1]}},
    {"n_sims": 1000, "team_boosts": {"NEW": {"attack": 0, "defence": 12}}},
    {"n_sims": 1000, "points_deductions": {"EVE": 6}, "custom_scores": {"ARS-TOT": [3, 0]}},
]


class Result:
    def __init__(self, phase):
        self.phase = phase
        self.lat = []
        self.status = {}
        self.errors = []
        self.lock = threading.Lock()
        self.headers = {}
        self.cache_hits = 0
        self.cache_misses = 0
        self.sims = 0

    def add(self, ms, code, headers=None, err=None):
        with self.lock:
            if err:
                self.errors.append(err)
            else:
                self.lat.append(ms)
                self.status[code] = self.status.get(code, 0) + 1
                if headers and not self.headers:
                    self.headers = headers
                if headers:
                    cache = headers.get("X-Sim-Cache")
                    if cache == "hit":
                        self.cache_hits += 1
                    elif cache == "miss":
                        self.cache_misses += 1
                    if headers.get("X-Sim-Sims"):
                        self.sims += int(headers["X-Sim-Sims"])

    def summary(self):
        vals = sorted(self.lat)
        def pct(q):
            if not vals:
                return None
            return round(vals[min(len(vals) - 1, int(round(q * (len(vals) - 1))))], 1)
        total = sum(self.status.values()) + len(self.errors)
        return {
            "phase": self.phase,
            "requests": total,
            "ok": sum(v for k, v in self.status.items() if 200 <= k < 300),
            "conn_errors": len(self.errors),
            "statuses": dict(sorted(self.status.items())),
            "p50_ms": pct(0.50), "p90_ms": pct(0.90), "p95_ms": pct(0.95), "p99_ms": pct(0.99),
            "max_ms": round(vals[-1], 1) if vals else None,
            "mean_ms": round(statistics.fmean(vals), 1) if vals else None,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "sims_requested": self.sims,
        }


def open_conn(url):
    parts = urllib.parse.urlparse(url)
    return http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=60)


def send(conn, method, path, body=None, headers=None, keep_alive=True):
    h = {"User-Agent": "ninety-loadtest", "Accept-Encoding": "gzip", "Connection": "keep-alive" if keep_alive else "close"}
    h.update(headers or {})
    payload = None
    if body is not None:
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()
        h["Content-Type"] = "application/json"
        h["Content-Length"] = str(len(payload))
    t0 = time.perf_counter()
    conn.request(method, path, body=payload, headers=h)
    resp = conn.getresponse()
    data = resp.read()
    ms = (time.perf_counter() - t0) * 1000.0
    return resp.status, dict(resp.getheaders()), data, ms


def run_phase(name, url, workers, per_worker, request_fn, out):
    """`workers` threads, each doing `per_worker` sequential requests on one keep-alive connection."""
    res = Result(name)
    barrier = threading.Barrier(workers)

    def worker(idx):
        try:
            conn = open_conn(url)
        except Exception as exc:
            res.add(0, 0, err="connect: %s" % exc)
            return
        try:
            barrier.wait(timeout=30)
        except Exception:
            pass
        for i in range(per_worker):
            try:
                code, headers, body, ms = request_fn(conn, idx, i)
                res.add(ms, code, headers)
            except Exception as exc:
                res.add(0, 0, err="%s: %s" % (type(exc).__name__, exc))
                try:
                    conn.close()
                except Exception:
                    pass
                conn = open_conn(url)
        try:
            conn.close()
        except Exception:
            pass

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(workers)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t0
    summary = res.summary()
    summary["wall_s"] = round(wall, 2)
    summary["rps"] = round(summary["requests"] / wall, 1) if wall > 0 else None
    # The capacity number for a Monte Carlo service is simulations per second, not requests per second:
    # one request can be 600 sims of real work or a cache hit that costs nothing.
    summary["sims_per_s"] = round(summary["sims_requested"] / wall, 0) if wall > 0 else None
    out.append((summary, res.headers))
    return summary, res.headers


def main(argv=None):
    ap = argparse.ArgumentParser(description="Load-test a running NINETY+ server (P3.5).")
    ap.add_argument("--url", default="http://127.0.0.1:8403")
    ap.add_argument("--phase", default="all",
                    choices=["all", "static", "revalidate", "baseline", "simulate", "cache", "overload"])
    ap.add_argument("--workers", type=int, default=16, help="concurrent connections per phase")
    ap.add_argument("--requests", type=int, default=40, help="requests per worker per phase")
    ap.add_argument("--overload-workers", type=int, default=48,
                    help="connections for the overload phase (should exceed NT90_MAX_THREADS)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    out = []
    summaries = []

    def run_all():
        etag = {}

        def req_static(conn, i, n):
            return send(conn, "GET", "/")

        def req_revalidate(conn, i, n):
            return send(conn, "GET", "/", headers={"If-None-Match": etag.get("v", '""')})

        def req_baseline(conn, i, n):
            return send(conn, "GET", "/api/baseline")

        def req_simulate(conn, i, n):
            # Distinct on every request, so this phase prices real Monte Carlo work rather than the
            # LRU. The deduction value doubles as the uniquifier.
            sc = json.loads(json.dumps(DEFAULT_SCENARIOS[(i + n) % len(DEFAULT_SCENARIOS)]))
            sc["n_sims"] = 600 + 50 * ((i + n) % 5)
            sc["points_deductions"] = {"ARS": 1 + ((i * 7 + n * 3) % 90)}
            return send(conn, "POST", "/api/simulate", body=sc)

        def req_cache(conn, i, n):
            return send(conn, "POST", "/api/simulate", body=DEFAULT_SCENARIOS[0])

        def req_overload(conn, i, n):
            sc = json.loads(json.dumps(DEFAULT_SCENARIOS[i % len(DEFAULT_SCENARIOS)]))
            sc["n_sims"] = 2500 + 50 * (i % 5)
            sc["points_deductions"] = {"ARS": 1 + (i % 20)}
            return send(conn, "POST", "/api/simulate", body=sc)

        want = args.phase
        if want in ("all", "static"):
            s, hdrs = run_phase("static GET /", args.url, args.workers, args.requests, req_static, out)
            summaries.append(s); etag["v"] = hdrs.get("ETag", '""')
            if not args.json: print("  static     %s" % json.dumps(s))
        if want in ("all", "revalidate"):
            s, _ = run_phase("revalidate 304", args.url, args.workers, args.requests, req_revalidate, out)
            summaries.append(s)
            if not args.json: print("  revalidate %s" % json.dumps(s))
        if want in ("all", "baseline"):
            s, _ = run_phase("baseline", args.url, args.workers, args.requests, req_baseline, out)
            summaries.append(s)
            if not args.json: print("  baseline   %s" % json.dumps(s))
        if want in ("all", "simulate"):
            s, _ = run_phase("simulate (cold)", args.url, min(args.workers, 8), max(3, args.requests // 6),
                             req_simulate, out)
            summaries.append(s)
            if not args.json: print("  simulate   %s" % json.dumps(s))
        if want in ("all", "cache"):
            s, _ = run_phase("simulate (cache)", args.url, args.workers, args.requests, req_cache, out)
            summaries.append(s)
            if not args.json: print("  cache      %s" % json.dumps(s))
        if want in ("all", "overload"):
            s, _ = run_phase("overload", args.url, args.overload_workers, 4, req_overload, out)
            summaries.append(s)
            if not args.json: print("  overload   %s" % json.dumps(s))

    if not args.json:
        print("NINETY+ load test — %s (workers=%d, requests/worker=%d)\n" % (args.url, args.workers, args.requests))
    t0 = time.perf_counter()
    run_all()
    wall = time.perf_counter() - t0

    if args.json:
        print(json.dumps({"url": args.url, "phases": summaries, "total_wall_s": round(wall, 2)}, indent=2))
        return 0

    # ── markdown table, ready to paste into docs/capacity.md ─────────────────
    print("\n| phase | req | hit/miss | 429/503 | p50 | p95 | p99 | max | req/s |")
    print("|---|---|---|---|---|---|---|---|---|")
    for s in summaries:
        capped = s["statuses"].get(429, 0) + s["statuses"].get(503, 0)
        hits = "%d/%d" % (s["cache_hits"], s["cache_misses"]) if (s["cache_hits"] or s["cache_misses"]) else "—"
        fmt = lambda v: "—" if v is None else "%s ms" % v
        print("| %s | %d | %s | %d | %s | %s | %s | %s | %s |"
              % (s["phase"], s["requests"], hits, capped, fmt(s["p50_ms"]), fmt(s["p95_ms"]),
                 fmt(s["p99_ms"]), fmt(s["max_ms"]), s["rps"]))
    simmed = [s for s in summaries if s["sims_requested"]]
    if simmed:
        print("\nMonte Carlo throughput: " + " · ".join("%s %.0f sims/s (%d sims)"
              % (s["phase"], s["sims_per_s"], s["sims_requested"]) for s in simmed))
    print("\ntotal wall: %.1fs" % wall)
    bad = [s for s in summaries if s["conn_errors"] or
           sum(v for k, v in s["statuses"].items() if k >= 500 and k != 503)]
    print("connection errors / unexpected 5xx: %d phase(s)" % len(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
