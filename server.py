"""NINETY+ prediction server.

Design notes (P3.1 + P3.2 + P1.3/P1.4):

* **Nothing blocks the socket.** `ml_engine` is imported inside the warm-up thread, so the process
  binds and starts answering in milliseconds. The dashboard and `/api/baseline` are served from disk
  until the engine is warm — stale-while-revalidate, in the truest sense: a visitor never meets a
  seven-second blank page.
* **Two health endpoints, two different jobs.** `/healthz` is liveness — it answers 200 as long as the
  process is up, and deliberately does not touch the engine, so a slow warm-up can never cause a
  restart loop. `/readyz` is readiness — 200 only once the model can actually serve, and the body
  says exactly what state it is in.
* **The engine warms from the artifact cache** (`--force-retrain` / `NT90_FORCE_RETRAIN=1` to bypass),
  then a scheduled refresh re-runs the baseline so the process never holds a stale model.
* **Transport (P3.3).** The 500 KB dashboard goes out gzipped (~100 KB) with a strong ETag, so a
  returning visitor revalidates with a 304 and transfers nothing. Security headers ride on every
  response — including error pages — and CORS is an allowlist rather than `*`.
* **Simulation protection (P3.4).** `/api/simulate` is the only endpoint that costs real CPU, so it is
  the only one that is guarded: the payload is schema-checked and normalised before it reaches the
  model, `n_sims` is clamped to a ceiling, a per-IP token bucket stops a loop, and identical scenarios
  are answered from an LRU cache. `/api/stats` publishes what happened.

Run:   PORT=8000 python3 server.py            # bind instantly, warm in the background
       PORT=8000 python3 server.py --preload  # build the engine *before* binding (readiness gate)
"""
import gzip
import hashlib
import json
import math
import os
import re
import sys
import threading
import time
from collections import OrderedDict, deque
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.path.join(BASE_DIR, "data")
BASELINE_SNAPSHOT = os.path.join(DATA_DIR, "predictions_2026_27_summary.json")

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
PRELOAD = ("--preload" in sys.argv) or os.environ.get("NT90_PRELOAD", "").lower() in ("1", "true", "yes", "on")
REFRESH_SECONDS = int(os.environ.get("NT90_REFRESH_SECONDS", str(6 * 3600)))
REQUEST_WAIT_S = float(os.environ.get("NT90_REQUEST_WAIT_S", "20"))
ACCESS_LOG = os.environ.get("NT90_ACCESS_LOG", "").lower() in ("1", "true", "yes", "on")
BASELINE_SIMS = int(os.environ.get("NT90_BASELINE_SIMS", "5000"))

# ── transport (P3.3) ─────────────────────────────────────────────────────────
COMPRESS_MIN_BYTES = int(os.environ.get("NT90_COMPRESS_MIN_BYTES", "1024"))
MAX_BODY_BYTES = int(os.environ.get("NT90_MAX_BODY_BYTES", str(64 * 1024)))
MAX_URL_CHARS = int(os.environ.get("NT90_MAX_URL_CHARS", "2048"))
MAX_THREADS = int(os.environ.get("NT90_MAX_THREADS", "64"))
# CORS: browsers only need this when the page and the API are on different origins. Same-origin
# requests (including everything through the preview proxy) need nothing. The default list therefore
# covers exactly the two legitimate cross-origin cases: a preview host, and local development.
ALLOWED_ORIGINS = os.environ.get("NT90_ALLOWED_ORIGINS", "*.e2b.app,localhost,127.0.0.1")
CSP = os.environ.get("NT90_CSP",
                     "default-src 'self' data: blob: 'unsafe-inline'; connect-src 'self'; "
                     "img-src 'self' data: blob:; base-uri 'none'; form-action 'none'; frame-ancestors *")

# ── simulation protection (P3.4) ─────────────────────────────────────────────
MIN_SIMS = int(os.environ.get("NT90_MIN_SIMS", "500"))
MAX_SIMS = int(os.environ.get("NT90_MAX_SIMS", "10000"))
SIM_CACHE_SIZE = int(os.environ.get("NT90_SIM_CACHE", "64"))
RATE_BURST = int(os.environ.get("NT90_RATE_BURST", "30"))          # tokens available at once, per IP
# How many Monte Carlo runs may be in flight at once. This is the memory guard as much as the CPU one:
# a single 2,500-sim run peaks around 260 MB, so on a small box this is the difference between queuing
# and being OOM-killed. Default to the core count, capped at 4.
SIM_CONCURRENCY = int(os.environ.get("NT90_SIM_CONCURRENCY", str(max(1, min(4, os.cpu_count() or 2)))))
SIM_WAIT_S = float(os.environ.get("NT90_SIM_WAIT_S", "15"))        # how long a request may queue for a slot
RATE_REFILL = float(os.environ.get("NT90_RATE_REFILL", "0.5"))     # tokens per second, per IP
TRUST_PROXY = os.environ.get("NT90_TRUST_PROXY", "").lower() in ("1", "true", "yes", "on")


# ════════════════════════════════════════════════════════════════════════════
#  transport + protection primitives
# ════════════════════════════════════════════════════════════════════════════
def origin_allowed(origin):
    """Is this Origin allowed to call us? Empty origin (same-origin, curl, tests) is always fine."""
    if not origin:
        return True
    rules = [r.strip().lower() for r in ALLOWED_ORIGINS.split(",") if r.strip()]
    if "*" in rules:
        return True
    host = origin.split("//")[-1].split(":")[0].lower()
    for rule in rules:
        rule = rule.split("//")[-1].split(":")[0]
        if rule.startswith("*."):
            if host == rule[2:] or host.endswith("." + rule[2:]):
                return True
        elif host == rule:
            return True
    return False


class Metrics:
    """Counters and a latency ring buffer. Cheap enough to leave on, honest enough to publish."""

    def __init__(self, ring=1024):
        self.lock = threading.Lock()
        self.by_route = {}
        self.by_code = {}
        self.total = 0
        self.latency = {}
        self.ring = ring
        self.started = time.time()

    def observe(self, route, method, code, ms):
        with self.lock:
            self.total += 1
            key = "%s %s" % (method, route)
            self.by_route[key] = self.by_route.get(key, 0) + 1
            self.by_code[str(code)] = self.by_code.get(str(code), 0) + 1
            buf = self.latency.get(key)
            if buf is None:
                buf = self.latency[key] = deque(maxlen=self.ring)
            buf.append(ms)

    @staticmethod
    def _pct(sorted_vals, q):
        if not sorted_vals:
            return None
        idx = min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1))))
        return round(sorted_vals[idx], 1)

    def snapshot(self):
        with self.lock:
            lat = {}
            for key, buf in self.latency.items():
                vals = sorted(buf)
                lat[key] = {"n": len(vals), "p50_ms": self._pct(vals, 0.50),
                            "p95_ms": self._pct(vals, 0.95), "p99_ms": self._pct(vals, 0.99),
                            "max_ms": round(vals[-1], 1)}
            return {"uptime_s": round(time.time() - self.started, 1), "requests_total": self.total,
                    "by_route": dict(sorted(self.by_route.items())),
                    "by_status": dict(sorted(self.by_code.items())),
                    "latency_ms": lat}


class TokenBucketLimiter:
    """Per-IP token bucket. Deliberately small: a visitor clicking "Run" never hits it, a loop does."""

    def __init__(self, burst, refill_per_s, max_keys=4096):
        self.burst = float(burst)
        self.refill = float(refill_per_s)
        self.max_keys = max_keys
        self.lock = threading.Lock()
        self.buckets = {}
        self.rejections = 0

    def check(self, key):
        """(allowed, remaining, retry_after_s). Consumes one token when allowed."""
        now = time.time()
        with self.lock:
            tokens, last = self.buckets.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.refill)
            if tokens >= 1.0:
                self.buckets[key] = (tokens - 1.0, now)
                return True, int(tokens - 1.0), 0.0
            self.buckets[key] = (tokens, now)
            self.rejections += 1
            wait = (1.0 - tokens) / self.refill if self.refill > 0 else 60.0
            if len(self.buckets) > self.max_keys:                    # prune the coldest entries
                for k, _ in sorted(self.buckets.items(), key=lambda kv: kv[1][1])[:self.max_keys // 4]:
                    self.buckets.pop(k, None)
            return False, 0, round(wait, 1)

    def refund(self, key):
        """Give the whole token back.

        A cache hit costs no CPU, and the promise made in the 429 body — "identical scenarios are
        served from cache and are never limited" — has to be literally true. Refunding 0.75 of a token
        looked thrifty and would have rate-limited a visitor repeating one scenario after ~40 clicks,
        which is exactly the behaviour the promise rules out.
        """
        with self.lock:
            tokens, last = self.buckets.get(key, (self.burst, time.time()))
            self.buckets[key] = (min(self.burst, tokens + 1.0), last)


class ResponseCache:
    """LRU over finished simulation payloads, keyed on the scenario *and* the model that produced it."""

    def __init__(self, maxsize=64):
        self.maxsize = maxsize
        self.lock = threading.Lock()
        self.data = OrderedDict()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key_for(scenario, n_sims, model_key):
        blob = json.dumps([scenario, int(n_sims), model_key], sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, key):
        with self.lock:
            if key in self.data:
                self.data.move_to_end(key)
                self.hits += 1
                return self.data[key]
            self.misses += 1
            return None

    def peek(self, key):
        """Like get(), without touching the hit/miss counters (used by the stats route)."""
        with self.lock:
            return self.data.get(key)

    def put(self, key, payload):
        with self.lock:
            self.data[key] = payload
            self.data.move_to_end(key)
            while len(self.data) > self.maxsize:
                self.data.popitem(last=False)

    def stats(self):
        with self.lock:
            total = self.hits + self.misses
            return {"size": len(self.data), "maxsize": self.maxsize, "hits": self.hits,
                    "misses": self.misses,
                    "hit_rate_pct": round(100.0 * self.hits / total, 1) if total else None}


METRICS = Metrics()
LIMITER = TokenBucketLimiter(RATE_BURST, RATE_REFILL)
SIM_CACHE = ResponseCache(SIM_CACHE_SIZE)
SIM_SLOTS = threading.BoundedSemaphore(SIM_CONCURRENCY)
SIM_STATE = {"in_flight": 0, "busy_rejections": 0, "lock": threading.Lock()}


def sim_slot_acquire(timeout):
    """Wait for the right to run a simulation. False means "queue full" — answer 503, stay alive."""
    if not SIM_SLOTS.acquire(timeout=timeout):
        with SIM_STATE["lock"]:
            SIM_STATE["busy_rejections"] += 1
        return False
    with SIM_STATE["lock"]:
        SIM_STATE["in_flight"] += 1
    return True


def sim_slot_release():
    with SIM_STATE["lock"]:
        SIM_STATE["in_flight"] -= 1
    SIM_SLOTS.release()


class Prepared:
    """One body, encoded once: the bytes we send for gzip and for identity clients.

    Encoding per request is the sort of cost that looks free until a load test prices it: gzipping the
    dashboard on every hit measured 110 ms p50, and re-serialising the baseline 72 ms. Neither input
    changes between requests, so neither should the output.
    """

    __slots__ = ("raw", "gzipped", "etag")

    def __init__(self, raw, etag=None, compress=True):
        self.raw = raw
        self.etag = etag
        self.gzipped = (gzip.compress(raw, 6)
                        if (compress and len(raw) >= COMPRESS_MIN_BYTES) else None)

    def body_for(self, accept_encoding):
        if self.gzipped is not None and "gzip" in accept_encoding:
            return self.gzipped, "gzip"
        return self.raw, ""

    @property
    def wire_bytes(self):
        return len(self.gzipped or self.raw)

    def __len__(self):
        return len(self.raw)


def dumps_prepared(obj, etag=None):
    return Prepared(dumps(obj), etag=etag)


def client_key(handler):
    """Who to charge. X-Forwarded-For is only believed when NT90_TRUST_PROXY is set — otherwise a
    caller could mint itself unlimited buckets by spoofing the header."""
    if TRUST_PROXY:
        fwd = handler.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return handler.client_address[0]


# ── the scenario contract ────────────────────────────────────────────────────
SCENARIO_KEYS = ("player_injuries", "team_boosts", "points_deductions", "custom_scores")
_CODE_RE = None


def rss_mb():
    """Resident memory of this process. Cheap to read, and the number that actually kills servers."""
    try:
        with open("/proc/self/statm") as fh:
            return round(int(fh.read().split()[1]) * 4096 / 1024 / 1024, 1)
    except Exception:
        return None


def validate_scenario(body, known_codes, known_players):
    """Normalise a what-if request, or explain exactly why it is not one.

    Returns (scenario, n_sims, errors). Errors are strings meant to be read by a human, because the
    usual cause is a client sending a shape the engine does not have a branch for — which is precisely
    how the `defence`/`defense` mismatch survived: nothing rejected it, so nothing noticed.
    """
    import re
    errors = []
    if not isinstance(body, dict):
        return None, None, ["body must be a JSON object"]

    unknown = [k for k in body if k not in ("n_sims",) + SCENARIO_KEYS]
    if unknown:
        errors.append("unknown field(s): %s" % ", ".join(sorted(unknown)))

    n_sims = body.get("n_sims", 3000)
    if isinstance(n_sims, bool) or not isinstance(n_sims, int):
        errors.append("n_sims must be an integer")
        n_sims = None
    elif not (MIN_SIMS <= n_sims <= MAX_SIMS):
        n_sims = max(MIN_SIMS, min(MAX_SIMS, n_sims))          # clamp, and say so in the response

    scenario = {}

    inj = body.get("player_injuries", {})
    if not isinstance(inj, dict):
        errors.append("player_injuries must be an object of {player_id: games_out}")
    else:
        clean = {}
        for pid, games in inj.items():
            if pid not in known_players:
                errors.append("unknown player_id %r" % pid)
                continue
            if isinstance(games, bool) or not isinstance(games, (int, float)):
                errors.append("player_injuries[%s] must be a number" % pid)
                continue
            clean[pid] = int(max(0, min(33, games)))
        scenario["player_injuries"] = clean

    boosts = body.get("team_boosts", {})
    if not isinstance(boosts, dict):
        errors.append("team_boosts must be an object of {club_code: {attack, defence}}")
    else:
        clean = {}
        for code, b in boosts.items():
            code = str(code).upper()
            if code not in known_codes:
                errors.append("unknown club in team_boosts: %s" % code)
                continue
            if not isinstance(b, dict):
                errors.append("team_boosts[%s] must be an object" % code)
                continue
            entry = {}
            for field in ("attack", "defence", "defense"):
                if field in b:
                    v = b[field]
                    if isinstance(v, bool) or not isinstance(v, (int, float)):
                        errors.append("team_boosts[%s].%s must be a number" % (code, field))
                        continue
                    entry["defence" if field in ("defence", "defense") else "attack"] = max(-25.0, min(25.0, float(v)))
            clean[code] = {"attack": entry.get("attack", 0.0), "defence": entry.get("defence", 0.0)}
        scenario["team_boosts"] = clean

    ded = body.get("points_deductions", {})
    if not isinstance(ded, dict):
        errors.append("points_deductions must be an object of {club_code: points}")
    else:
        clean = {}
        for code, pts in ded.items():
            code = str(code).upper()
            if code not in known_codes:
                errors.append("unknown club in points_deductions: %s" % code)
                continue
            if isinstance(pts, bool) or not isinstance(pts, (int, float)):
                errors.append("points_deductions[%s] must be a number" % code)
                continue
            clean[code] = int(max(0, min(100, pts)))
        scenario["points_deductions"] = clean

    forced = body.get("custom_scores", {})
    if not isinstance(forced, dict):
        errors.append("custom_scores must be an object of {'HOME-AWAY': [home_goals, away_goals]}")
    else:
        clean = {}
        for key, val in forced.items():
            parts = str(key).upper().split("-")
            if len(parts) != 2 or parts[0] not in known_codes or parts[1] not in known_codes or parts[0] == parts[1]:
                errors.append("custom_scores key %r must be 'HOME-AWAY' with two different known clubs" % key)
                continue
            if isinstance(val, str) and "-" in val:
                val = val.split("-")
            if not isinstance(val, (list, tuple)) or len(val) != 2:
                errors.append("custom_scores[%s] must be [home_goals, away_goals]" % key)
                continue
            try:
                # "2" and 2 are the same scoreline; a string that is not a number is not.
                hg, ag = int(float(val[0])), int(float(val[1]))
            except (TypeError, ValueError):
                errors.append("custom_scores[%s] must be [home_goals, away_goals]" % key)
                continue
            if not (0 <= hg <= 12 and 0 <= ag <= 12):
                errors.append("custom_scores[%s] goals must be between 0 and 12" % key)
                continue
            clean["%s-%s" % (parts[0], parts[1])] = [hg, ag]
        scenario["custom_scores"] = clean

    total_entries = sum(len(v) for v in scenario.values())
    if total_entries > 200:
        errors.append("scenario too large: %d entries (limit 200)" % total_entries)

    return (scenario if not errors else None), n_sims, errors


def json_safe(obj):
    """Guarantee spec-valid JSON: browsers reject bare NaN/Infinity, which would silently
    push the dashboard onto its offline engine."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj


def dumps(obj):
    return json.dumps(json_safe(obj), allow_nan=False, separators=(",", ":")).encode("utf-8")


def atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


class EngineHost:
    """Owns the engine, its warm-up, and the freshness of the payload we hand out."""

    def __init__(self):
        self.lock = threading.Lock()
        self.engine = None
        self.ready = False
        self.error = None
        self.warm_ms = None
        self.boot_ms = None
        self.cache_hit = None
        self.cache_error = None
        self.refreshes = 0
        self.last_refresh = None
        self.started = time.time()
        self._warm_started = None
        self._evt = threading.Event()
        self._snapshot = None
        self._snapshot_mtime = None
        self._snapshot_served = None
        self._page = None
        self._page_stamp = None
        self._baseline_prepared = None
        self._baseline_obj = None

    # ── warm-up ──────────────────────────────────────────────────────────────
    def warm(self):
        """Import the engine and load it. Safe to call from a thread; idempotent."""
        with self.lock:
            if self.ready or self._warm_started:
                return
            self._warm_started = time.time()
        t0 = time.perf_counter()
        try:
            from ml_engine import PremierLeagueMLEngine          # imported here on purpose (see docstring)
            engine = PremierLeagueMLEngine(n_sims=BASELINE_SIMS)
            with self.lock:
                self.engine = engine
                self.boot_ms = engine.boot_ms
                self.cache_hit = engine.cache_hit
                self.cache_error = getattr(engine, "cache_error", None)
                self.ready = True
        except Exception as exc:                                  # keep serving the disk snapshot
            with self.lock:
                self.error = "%s: %s" % (type(exc).__name__, exc)
        finally:
            self.warm_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            self._evt.set()
            if ACCESS_LOG:
                print("[warm] %.0f ms ready=%s cache_hit=%s error=%s"
                      % (self.warm_ms, self.ready, self.cache_hit, self.error), flush=True)

    def start_background_warm(self):
        threading.Thread(target=self.warm, name="warm-engine", daemon=True).start()

    def wait(self, timeout=REQUEST_WAIT_S):
        """Block until the engine is usable. Returns the engine, or None on failure/timeout."""
        self._evt.wait(timeout)
        return self.engine if self.ready else None

    # ── the dashboard page, hashed once per rebuild ──────────────────────────
    def page(self):
        """The dashboard as a Prepared body. Re-read, re-hashed and re-gzipped only when the file
        changes — not per request. Returns a Prepared carrying its own ETag."""
        path = os.path.join(STATIC_DIR, "index.html")
        st = os.stat(path)
        stamp = (st.st_mtime_ns, st.st_size)
        with self.lock:
            if self._page_stamp != stamp:
                with open(path, "rb") as fh:
                    content = fh.read()
                self._page = Prepared(content, etag='"sha256-%s"' % hashlib.sha256(content).hexdigest()[:20])
                self._page_stamp = stamp
            return self._page

    # ── payload ──────────────────────────────────────────────────────────────
    def snapshot_bytes(self):
        """The on-disk baseline, re-read only when it changes."""
        try:
            mtime = os.path.getmtime(BASELINE_SNAPSHOT)
            if self._snapshot is None or mtime != self._snapshot_mtime:
                with open(BASELINE_SNAPSHOT, "rb") as fh:
                    self._snapshot = fh.read()
                self._snapshot_mtime = mtime
            return self._snapshot
        except Exception:
            return None

    def baseline_payload(self):
        """(Prepared, source). Warm engine wins; otherwise the last written snapshot — instantly.

        The serialised form is cached against the *object* the engine holds: after a refresh the engine
        swaps in a new results dict, identity changes, and the next request re-encodes exactly once.
        """
        if self.ready and self.engine is not None:
            try:
                results = self.engine.baseline_results
                with self.lock:
                    if self._baseline_prepared is None or self._baseline_obj is not results:
                        self._baseline_prepared = dumps_prepared(results)
                        self._baseline_obj = results
                    return self._baseline_prepared, "engine"
            except Exception as exc:
                self.error = "%s: %s" % (type(exc).__name__, exc)
        snap = self.snapshot_bytes()
        if not snap:
            return None, "unavailable"
        with self.lock:
            if self._baseline_prepared is None or self._snapshot_served != self._snapshot_mtime:
                self._baseline_prepared = Prepared(snap)
                self._snapshot_served = self._snapshot_mtime
            return self._baseline_prepared, "disk-cache"

    # ── scheduled refresh ────────────────────────────────────────────────────
    def start_refresh_loop(self):
        if REFRESH_SECONDS <= 0:
            return
        threading.Thread(target=self._refresh_loop, name="refresh", daemon=True).start()

    def _refresh_loop(self):
        while True:
            time.sleep(REFRESH_SECONDS)
            try:
                engine = self.engine
                if engine is None:
                    continue
                res = engine.run_simulation(n_sims=BASELINE_SIMS, scenario={})
                with self.lock:
                    engine.baseline_results = res
                    self.refreshes += 1
                    self.last_refresh = time.time()
                # keep the on-disk snapshot hot too, so the *next* restart is instant as well
                atomic_write(BASELINE_SNAPSHOT, json.dumps(json_safe(res), indent=2, allow_nan=False).encode("utf-8"))
                if ACCESS_LOG:
                    print("[refresh] baseline re-simulated (%d total)" % self.refreshes, flush=True)
            except Exception as exc:
                self.error = "%s: %s" % (type(exc).__name__, exc)

    # ── reporting ────────────────────────────────────────────────────────────
    def status(self):
        with self.lock:
            state = "warm" if self.ready else ("failed" if self.error and not self._warm_started is None and self._evt.is_set() else "warming")
            return {
                "ready": self.ready,
                "engine": state,
                "error": self.error,
                "warm_ms": self.warm_ms,
                "engine_boot_ms": self.boot_ms,
                "artifact_cache_hit": self.cache_hit,
                "artifact_cache_error": self.cache_error,
                "preloaded": PRELOAD,
                "refreshes": self.refreshes,
                "last_refresh_age_s": (round(time.time() - self.last_refresh, 1) if self.last_refresh else None),
                "refresh_interval_s": REFRESH_SECONDS,
                "baseline_snapshot": os.path.exists(BASELINE_SNAPSHOT),
                "uptime_s": round(time.time() - self.started, 1),
            }


HOST_STATE = EngineHost()


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Threaded, but not unbounded: past NT90_MAX_THREADS the server answers 503 instead of
    melting, which is a much better failure mode than a socket backlog nobody can diagnose."""

    daemon_threads = True
    allow_reuse_address = True
    # The stdlib default is 5. Under a burst that overflows instantly and the kernel refuses
    # connections — which looks like a crash and is impossible to diagnose from the client side.
    request_queue_size = int(os.environ.get("NT90_BACKLOG", "128"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._slots = threading.BoundedSemaphore(MAX_THREADS)
        self.overloaded = 0

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.overloaded += 1
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\n"
                                b"Content-Type: application/json\r\n"
                                b"Content-Length: 96\r\n"
                                b"Connection: close\r\n"
                                b"Retry-After: 1\r\n\r\n"
                                b'{"error":"server busy","detail":"thread pool saturated",'
                                b'"retry_after_s":1}')
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request, client_address):
        """A browser closing a keep-alive socket is normal, not an incident — don't spam the logs."""
        import sys as _sys
        exc = _sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


class PLRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 30                      # a stalled client cannot pin a worker thread forever
    # Nagle's algorithm waits for an ACK before sending a second small segment, and the peer's
    # delayed ACK waits ~40 ms to send one. The result is a hard 40 ms floor on *every* response
    # that goes out as two writes (headers, then body) — measured at 44.0 ms p50 on /api/baseline
    # in the first load test, and 0.5 ms with this off. Latency you cannot see in a browser tab
    # (the page is one big write) but that every API caller pays.
    disable_nagle_algorithm = True

    # ── plumbing ─────────────────────────────────────────────────────────────
    def send_response(self, code, message=None):
        # Reset per response: these handler objects survive across keep-alive requests.
        self._headers_injected = False
        self._code = code
        super().send_response(code, message)

    def end_headers(self):
        """Inject security + CORS headers on every response, error pages included.

        404s and 503s from send_error() never pass through `_send`, and a missing `nosniff` on an
        error page is exactly the kind of gap a scan finds and a reviewer asks about.
        """
        if not getattr(self, "_headers_injected", False):
            self._headers_injected = True
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-RateLimit-Policy", "simulate %d burst / %.2f per s" % (RATE_BURST, RATE_REFILL))
            if CSP:
                self.send_header("Content-Security-Policy", CSP)
            origin = self.headers.get("Origin")
            if origin and origin_allowed(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            elif origin:
                self.send_header("Vary", "Origin")
        super().end_headers()

    #: Extensions this server will serve out of static/. Nothing else leaves the directory.
    STATIC_TYPES = {
        ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
        ".xml": "application/xml; charset=utf-8", ".txt": "text/plain; charset=utf-8",
        ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
        ".woff2": "font/woff2", ".webmanifest": "application/manifest+json",
        # P8.3: the calendar feeds. "text/calendar" is the registered type; a browser offered this
        # download will hand it to whatever calendar app is registered for .ics.
        ".ics": "text/calendar; charset=utf-8",
    }

    def _static_file(self, path):
        """Resolve a URL path to a file inside static/, or None.

        The check is deliberately belt-and-braces: `os.path.normpath` collapses `..`, the resolved
        path must still be inside STATIC_DIR, and only known extensions are served. A page generator
        that writes hundreds of files should not also mean a directory-traversal surface.
        """
        rel = os.path.normpath(path.lstrip("/"))
        if rel.startswith("..") or os.path.isabs(rel):
            return None
        full = os.path.join(STATIC_DIR, rel)
        if not os.path.abspath(full).startswith(os.path.abspath(STATIC_DIR) + os.sep):
            return None
        if not os.path.isfile(full):
            return None
        ctype = self.STATIC_TYPES.get(os.path.splitext(full)[1].lower())
        if ctype is None:
            return None
        return full, ctype

    def _serve_static(self, path, head_only=False, code=200):
        hit = self._static_file(path)
        if hit is None:
            return False
        full, ctype = hit
        with open(full, "rb") as fh:
            blob = fh.read()
        if path.endswith(".ics"):
            # Calendar clients (and iOS/macOS in particular) can police how often a subscription is
            # refetched, so this one is not given a five-minute browser cache — a subscriber should
            # get the build they just asked for.
            return self._send(code, blob, ctype,
                              {"Cache-Control": "public, max-age=60, must-revalidate",
                               "X-Engine": HOST_STATE.status()["engine"]},
                              head_only=head_only)
        # These are rebuilt whenever the model is, so they are cacheable but must revalidate cheaply.
        return self._send(code, blob, ctype,
                          {"Cache-Control": "public, max-age=300", "X-Engine": HOST_STATE.status()["engine"]},
                          head_only=head_only)

    def _send(self, code, body, ctype, extra=None, head_only=False):
        if isinstance(body, str):
            body = body.encode("utf-8")
        encoding = ""
        if body and len(body) >= COMPRESS_MIN_BYTES and "gzip" in self.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body, 6)
            encoding = "gzip"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if encoding:
            self.send_header("Content-Encoding", encoding)
            self.send_header("Vary", "Accept-Encoding, Origin")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _send_prepared(self, code, prepared, ctype, extra=None, head_only=False):
        body, encoding = prepared.body_for(self.headers.get("Accept-Encoding", ""))
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if encoding:
            self.send_header("Content-Encoding", encoding)
            self.send_header("Vary", "Accept-Encoding, Origin")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _json(self, code, obj, extra=None):
        self._send(code, dumps(obj), "application/json; charset=utf-8", extra)

    def do_HEAD(self):
        self.do_GET(head_only=True)

    def do_GET(self, head_only=False):
        t0 = time.perf_counter()
        self._route = "other"
        try:
            self._route_get(head_only)
        finally:
            METRICS.observe(self._route, self.command, getattr(self, "_code", 0),
                            (time.perf_counter() - t0) * 1000.0)

    def _route_get(self, head_only=False):
        if len(self.path) > MAX_URL_CHARS:
            self._route = "reject"
            return self._json(414, {"error": "URI too long", "max_chars": MAX_URL_CHARS})
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        # ── liveness: never touches the engine ───────────────────────────────
        if path == "/healthz":
            return self._json(200, {"status": "ok", "uptime_s": round(time.time() - HOST_STATE.started, 1)})

        # ── readiness: the honest answer, 503 until the model can serve ──────
        if path == "/readyz":
            st = HOST_STATE.status()
            return self._json(200 if st["ready"] else 503, st)

        if path in ("/", "/index.html"):
            self._route = "/"
            index_path = os.path.join(STATIC_DIR, "index.html")
            if os.path.exists(index_path):
                prepared = HOST_STATE.page()
                etag = prepared.etag
                # no-cache + ETag is the right pair here: revalidate every time, but let a match
                # cost nothing. A 500 KB page that never changes between rebuilds should be free.
                if self.headers.get("If-None-Match") == etag:
                    return self._send(304, b"", "text/html; charset=utf-8",
                                      {"ETag": etag, "Cache-Control": "no-cache"}, head_only=True)
                engine = HOST_STATE.status()["engine"]
                return self._send_prepared(200, prepared, "text/html; charset=utf-8",
                                           {"Cache-Control": "no-cache", "ETag": etag, "X-Engine": engine},
                                           head_only=head_only)
            return self.send_error(404, "index.html not found")

        if path in ("/robots.txt", "/favicon.ico"):
            self._route = path
            fname = os.path.basename(path)
            fpath = os.path.join(STATIC_DIR, fname)
            if os.path.exists(fpath):
                with open(fpath, "rb") as fh:
                    blob = fh.read()
                ctype = "text/plain; charset=utf-8" if fname.endswith(".txt") else "image/x-icon"
                return self._send(200, blob, ctype, {"Cache-Control": "public, max-age=86400"},
                                  head_only=head_only)
            return self.send_error(404, "Not found")

        # ── generated pages, icons and preview cards (P5.1, P5.3, P5.4) ─────────────────────
        # /club/arsenal.html, /gameweek/mw6.html, /table.html, /model.html, /sitemap.xml, /og/*.png,
        # /icons/*, /apple-touch-icon.png, /icon.svg — all written by site_pages.py at build time.
        # /manifest.webmanifest belongs in this list even though nothing renders it: every page's
        # <head> links it, so a browser fetches it on first load and a 404 there is a visible error in
        # the console of a page that otherwise works. It was missing until a clean-room extraction
        # probed the links the generated pages actually advertise (tests/test_wave4_site.py).
        # This used to be a hand-written tuple of every generated page, which meant a page could exist
        # on disk, deploy fine on Vercel (which serves static/ directly) and 404 on the local server and
        # in the container — /receipts.html, /changelog.html and /ledger.json did exactly that when they
        # were added. The rule is derived now: anything publishable that exists under static/ is served,
        # so a new generated page works everywhere the moment site_pages.py writes it.
        #
        # What has to keep winning: the app's own routes below, so /table is the dashboard and
        # /table.html is the crawlable page even though both exist. The extensions are listed rather
        # than accepting anything, so a stray .md or .py in the build output stays private.
        PUBLIC_SUFFIXES = (".html", ".xml", ".txt", ".json", ".svg", ".png", ".ico", ".webmanifest",
                           ".ics", ".css", ".js")
        if (path not in ("", "/index.html")
                and path.lower().endswith(PUBLIC_SUFFIXES)
                and self._static_file(path) is not None):
            hit = self._static_file(path)
            if hit is not None:
                self._route = "static"
                return self._serve_static(path, head_only=head_only)

        # ── the app's own routes, rewritten to the dashboard (P5.3) ──────────────────────────
        # The server cannot know which view you want — only the client can — so every app route is
        # served the same single file, and router.js reads the path. This is what makes
        # /gameweek/6 and /club/arsenal real URLs you can paste anywhere.
        app_route = (
            path in ("/matchweek", "/table", "/awards", "/duel", "/whatif", "/model")
            or re.fullmatch(r"/gameweek/(?:mw)?\d{1,2}", path)
            or re.fullmatch(r"/club/[A-Za-z0-9'\-]+", path)
        )
        if app_route:
            self._route = "/app-route"
            index_path = os.path.join(STATIC_DIR, "index.html")
            if os.path.exists(index_path):
                prepared = HOST_STATE.page()
                return self._send_prepared(200, prepared, "text/html; charset=utf-8",
                                           {"Cache-Control": "no-cache", "ETag": prepared.etag,
                                            "X-Engine": HOST_STATE.status()["engine"]},
                                           head_only=head_only)

        if path == "/api/stats":
            self._route = "/api/stats"
            return self._json(200, {
                "metrics": METRICS.snapshot(),
                "simulation": {"cache": SIM_CACHE.stats(), "rate_limit_rejections": LIMITER.rejections,
                               "rate_burst": RATE_BURST, "rate_refill_per_s": RATE_REFILL,
                               "n_sims_range": [MIN_SIMS, MAX_SIMS],
                               "concurrency": SIM_CONCURRENCY, "in_flight": SIM_STATE["in_flight"],
                               "busy_rejections": SIM_STATE["busy_rejections"]},
                "limits": {"max_body_bytes": MAX_BODY_BYTES, "max_url_chars": MAX_URL_CHARS,
                           "max_threads": MAX_THREADS, "compress_min_bytes": COMPRESS_MIN_BYTES,
                           "allowed_origins": ALLOWED_ORIGINS, "csp_enabled": bool(CSP),
                           "sim_concurrency": SIM_CONCURRENCY, "sim_wait_s": SIM_WAIT_S,
                           "backlog": self.server.request_queue_size if getattr(self, "server", None) else None},
                "process": {"rss_mb": rss_mb(), "cpu_count": os.cpu_count()},
                "engine": HOST_STATE.status(),
            })

        if path == "/api/baseline":
            self._route = "/api/baseline"
            payload, source = HOST_STATE.baseline_payload()
            if payload is None:
                return self._json(503, {"error": "baseline unavailable", "reason": HOST_STATE.status()})
            # stale-while-revalidate, made explicit in the headers so it is observable from outside
            return self._send_prepared(200, payload, "application/json; charset=utf-8",
                                       {"X-Data-Source": source, "X-Engine": HOST_STATE.status()["engine"],
                                        "Cache-Control": "no-store"})

        if path == "/api/backtest":
            self._route = "/api/backtest"
            bt_path = os.path.join(DATA_DIR, "backtest_2025_26.json")
            if os.path.exists(bt_path):
                with open(bt_path, "rb") as f:
                    return self._send(200, f.read(), "application/json; charset=utf-8",
                                      {"Cache-Control": "no-store"})
            return self.send_error(404, "Run backtest.py first")

        if path == "/api/fixture":
            self._route = "/api/fixture"
            home = qs.get("home", ["ARS"])[0].upper()
            away = qs.get("away", ["MCI"])[0].upper()
            engine = HOST_STATE.wait()
            if engine is None:
                return self._json(503, {"error": "engine warming", "retry_after_s": 2, "state": HOST_STATE.status()})
            if home == away or home not in engine.teams_dict or away not in engine.teams_dict:
                return self.send_error(400, "Invalid home or away team code")
            return self._json(200, engine.predict_fixture(home, away), {"X-Engine": "warm"})

        if path.startswith("/api/download/"):
            self._route = "/api/download"
            fname = os.path.basename(path.replace("/api/download/", ""))
            fpath = os.path.join(DATA_DIR, fname)
            if os.path.exists(fpath) and os.path.isfile(fpath):
                with open(fpath, "rb") as f:
                    data = f.read()
                ctype = "text/csv" if fname.endswith(".csv") else "application/json"
                return self._send(200, data, f"{ctype}; charset=utf-8",
                                  {"Content-Disposition": f'attachment; filename="{fname}"'})
            return self.send_error(404, "File not found")

        # A 404 that is a page rather than a dead end: site_pages.py writes static/404.html, and it
        # lists every URL this site has. It is served with a 404 status, because that is the truth.
        # `Accept: */*` — what curl sends by default and what the first version of this check missed
        # — asks for anything, so it gets HTML like any other client that has not said it only wants
        # JSON.
        accept = (self.headers.get("Accept") or "*/*").lower()
        if "application/json" not in accept or "text/html" in accept or accept == "*/*":
            if self._static_file("/404.html") is not None:
                self._route = "404"
                return self._serve_static("/404.html", head_only=head_only, code=404)
        self._route = "404"
        return self.send_error(404, "Not found")

    def do_POST(self):
        t0 = time.perf_counter()
        self._route = "other"
        try:
            self._route_post()
        finally:
            METRICS.observe(self._route, self.command, getattr(self, "_code", 0),
                            (time.perf_counter() - t0) * 1000.0)

    def _route_post(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/simulate":
            self._route = "404"
            return self.send_error(404, "Not found")
        self._route = "/api/simulate"

        # ── size caps, before a single byte is parsed ────────────────────────
        declared = self.headers.get("Content-Length")
        if declared is None:
            return self._json(411, {"error": "Content-Length required"})
        try:
            length = int(declared)
        except ValueError:
            return self._json(400, {"error": "bad Content-Length"})
        if length > MAX_BODY_BYTES:
            return self._json(413, {"error": "request body too large", "max_body_bytes": MAX_BODY_BYTES})
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            return self._json(400, {"error": "body is not valid JSON", "detail": str(exc)[:120]})

        engine = HOST_STATE.wait()
        if engine is None:
            return self._json(503, {"error": "engine warming", "retry_after_s": 2, "state": HOST_STATE.status()})

        known_codes = set(engine.df_teams["code"].values)
        known_players = set(engine.df_players["player_id"].values)
        scenario, n_sims, errors = validate_scenario(body, known_codes, known_players)
        if errors:
            return self._json(400, {"error": "invalid scenario", "details": errors,
                                    "expected": {"n_sims": "int %d-%d" % (MIN_SIMS, MAX_SIMS),
                                                 "player_injuries": "{player_id: games_out}",
                                                 "team_boosts": "{club: {attack, defence}} (-25..25 %%)",
                                                 "points_deductions": "{club: points}",
                                                 "custom_scores": "{'HOME-AWAY': [home_goals, away_goals]}"}})

        # ── cache first: a repeat scenario costs no CPU, so it costs no token ─
        key = ResponseCache.key_for(scenario, n_sims, getattr(engine, "cache_key", ""))
        cached = SIM_CACHE.get(key)
        if cached is not None:
            return self._send_prepared(200, cached, "application/json; charset=utf-8",
                                       {"X-Sim-Cache": "hit", "X-Sim-Sims": str(n_sims)})

        who = client_key(self)
        allowed, remaining, retry_after = LIMITER.check(who)
        if not allowed:
            return self._json(429, {"error": "rate limited", "retry_after_s": retry_after,
                                    "note": "identical scenarios are served from cache and are never limited"},
                              {"Retry-After": str(max(1, int(math.ceil(retry_after)))),
                               "X-RateLimit-Limit": str(RATE_BURST),
                               "X-RateLimit-Remaining": "0"})

        if not sim_slot_acquire(SIM_WAIT_S):
            LIMITER.refund(who)                       # it never ran, so it should not cost a token
            return self._json(503, {"error": "simulation queue full",
                                    "detail": "%d simulation(s) already running" % SIM_CONCURRENCY,
                                    "retry_after_s": 3},
                              {"Retry-After": "3"})
        try:
            payload = engine.run_simulation(n_sims=n_sims, scenario=scenario)
        finally:
            sim_slot_release()
        prepared = dumps_prepared(payload)
        SIM_CACHE.put(key, prepared)
        return self._send_prepared(200, prepared, "application/json; charset=utf-8",
                                   {"X-Sim-Cache": "miss", "X-Sim-Sims": str(n_sims),
                                    "X-RateLimit-Limit": str(RATE_BURST),
                                    "X-RateLimit-Remaining": str(remaining)})

    def do_OPTIONS(self):
        # Content-Length is mandatory here: with HTTP/1.1 keep-alive and no body length, the client
        # has no way to know the response ended and simply waits until it times out.
        self._route = "preflight"
        origin = self.headers.get("Origin")
        self.send_response(204)
        if origin and origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()
        METRICS.observe(self._route, self.command, 204, 0.0)

    def log_message(self, fmt, *args):
        if ACCESS_LOG:
            print("[http] %s %s" % (self.address_string(), fmt % args), flush=True)


def main():
    t0 = time.perf_counter()
    if PRELOAD:
        HOST_STATE.warm()                       # readiness gate: engine is up before the port opens
    else:
        HOST_STATE.start_background_warm()      # bind first, warm in parallel
    HOST_STATE.start_refresh_loop()

    server = ThreadingHTTPServer((HOST, PORT), PLRequestHandler)
    print("NINETY+ server on http://%s:%d  (engine=%s, preload=%s, refresh=%ss)"
          % (HOST, PORT, HOST_STATE.status()["engine"], PRELOAD,
             REFRESH_SECONDS if REFRESH_SECONDS > 0 else "off"), flush=True)
    print("   bound in %.0f ms — dashboard and /api/baseline are already being served"
          % ((time.perf_counter() - t0) * 1000.0), flush=True)
    print("   limits: simulate %d-%d sims · %d concurrent · %d-token bucket @ %.2f/s · %d-entry LRU · "
          "%d KB body · gzip>%d B · backlog %d · CORS %s"
          % (MIN_SIMS, MAX_SIMS, SIM_CONCURRENCY, RATE_BURST, RATE_REFILL, SIM_CACHE_SIZE,
             MAX_BODY_BYTES // 1024, COMPRESS_MIN_BYTES, ThreadingHTTPServer.request_queue_size,
             ALLOWED_ORIGINS), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
