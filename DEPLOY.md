# DEPLOY — the warm-start runbook (P1.4)

Everything here is a command you can paste. Nothing in this file needs editing before you run it
except the two placeholders in the Fly/Render sections.

---

## 1. What actually ships

```
Dockerfile          two-stage build: deps cached, runtime non-root, cache pre-warmed
.dockerignore       keeps proofs, screenshots and the machine-specific cache out of the image
fly.toml            Fly.io: readiness check on /readyz, liveness on /healthz
render.yaml         Render blueprint: healthCheckPath /readyz
server.py           binds in ~3 ms, warms the engine in the background, /healthz + /readyz
artifacts/          the model cache (built, not committed — see step 3)
```

## 2. Cold start, measured

The problem P3.1/P3.2 existed to fix: a deploy used to answer its first request after ~7.3 s of
training, which on a cold host is a blank page big enough to lose a visitor.

| | before | after |
|---|---|---|
| bind to the port | 7.27 s (engine built at import) | **3 ms** |
| first `/` request | 7.27 s | **21 ms** (`X-Engine: warming`) |
| first `/api/baseline` | 7.27 s | **1 ms** (disk snapshot, `X-Data-Source: disk-cache`) |
| engine usable | — | **1.04 s** (`X-Data-Source: engine`) |
| engine boot from artifact cache | 4.50 s training | **0.02 s** |

Reproduce locally:

```bash
python3 - <<'PY'
import subprocess, sys, time, urllib.request
p = subprocess.Popen([sys.executable, "server.py"], env={**__import__("os").environ, "PORT": "8401"})
time.sleep(0.4)
t = time.perf_counter()
urllib.request.urlopen("http://127.0.0.1:8401/").read()
print("first byte after %.0f ms" % ((time.perf_counter() - t) * 1000))
p.terminate()
PY
```

## 3. The artifact cache (P3.1)

`ml_engine.py` hashes its five input CSVs **and its own source** into a cache key, then either loads
`artifacts/engine-<key>.pkl` or trains and writes it. A change to the data or the maths changes the
key, so a stale model can never be served silently.

```bash
python3 ml_engine.py                   # load from cache (0.02 s) or train + write it (4.5 s)
python3 ml_engine.py --force-retrain   # deliberate rebuild, ignores the cache
NT90_FORCE_RETRAIN=1 python3 run_all.py --retrain   # full pipeline, fresh models
```

`artifacts/` is gitignored and `.dockerignore`d, because the Docker build regenerates it inside the
image. Cost of the cache: one ~1 MB file. Benefit: the 4.5 s training step happens at build time, not
in front of a visitor.

## 4. Local production-shaped run

```bash
python3 run_all.py            # fixtures -> data -> models -> backtest -> tests (gate) -> dashboard
PORT=8000 python3 server.py   # bind fast, warm in the background
```

Check the two health endpoints and the warm path:

```bash
curl -s localhost:8000/healthz | python3 -m json.tool     # {"status":"ok", ...}
curl -si localhost:8000/readyz   | head -1                # HTTP/1.1 503 while warming, 200 when warm
curl -si localhost:8000/api/baseline | grep -i x-data-source
```

`--preload` (`NT90_PRELOAD=1`) builds the engine *before* binding: the port only opens once the model
can serve. Use it when a load balancer already gates traffic; leave it off when the platform needs a
fast port bind.

## 5. Deploy to Fly.io

```bash
fly launch --no-deploy --copy-config   # accept fly.toml; set a unique app name if "ninety-plus" is taken
fly deploy                             # builds the image (pre-warms the cache), then health-gates
fly open
```

Rollback, logs, scale, secrets — the four commands you will actually reach for:

```bash
fly releases                           # find the previous version number
fly releases rollback 3                # roll back to version 3
fly logs -a ninety-plus                # tail stdout (NT90_ACCESS_LOG=1 enables per-request lines)
fly scale count 2 --max-per-region 2   # two machines; the readiness check keeps traffic off cold ones
fly secrets set NT90_ACCESS_LOG=1      # any env var in §7 can be set this way
```

## 6. Deploy to Render

1. Push the repo to GitHub.
2. Render → **New → Blueprint** → select the repo. `render.yaml` is picked up automatically.
3. `healthCheckPath: /readyz` means Render holds traffic until the model is warm — the deploy looks
   instant to a visitor even though the first build trains.
4. Logs: service → **Logs**. Rollback: service → **Events** → pick the previous deploy → **Rollback**.
5. Free/starter instances sleep; the first request after a sleep is a cold *process*, not a cold
   *model* — `ml_engine` still loads in ~1 s from the image's pre-warmed cache.

## 7. Environment variables

| Variable | Default | What it does |
|---|---|---|
| `HOST` | `0.0.0.0` | Interface to bind. |
| `PORT` | `8000` | Port to bind. |
| `NT90_PRELOAD` | off | Build the engine before binding (readiness gate on startup). |
| `NT90_FORCE_RETRAIN` | off | Ignore the artifact cache; retrain and rewrite it. |
| `NT90_REFRESH_SECONDS` | `21600` (6 h) | How often the scheduled refresh re-simulates the baseline. `0` disables. |
| `NT90_REQUEST_WAIT_S` | `20` | How long an engine-dependent request waits for warm-up before returning 503. |
| `NT90_BASELINE_SIMS` | `5000` | Simulations per baseline run (refresh and warm-up both use it). |
| `NT90_ACCESS_LOG` | off | Per-request access log lines, plus warm/refresh lines. |
| **Transport (P3.3)** | | |
| `NT90_MAX_BODY_BYTES` | `65536` | Largest accepted POST body. Bigger → `413`. |
| `NT90_MAX_URL_CHARS` | `2048` | Longest accepted URL. Longer → `414`. |
| `NT90_MAX_THREADS` | `64` | Connection ceiling; past it the server answers `503` instead of queueing forever. |
| `NT90_BACKLOG` | `128` | Listen backlog. The stdlib default of 5 was a real outage under a burst. |
| `NT90_COMPRESS_MIN_BYTES` | `1024` | Below this, responses are not gzipped. |
| `NT90_ALLOWED_ORIGINS` | `*.e2b.app,localhost,127.0.0.1` | CORS allowlist (`*` to allow everything). Same-origin needs no CORS at all. |
| `NT90_CSP` | a self-contained policy | `Content-Security-Policy` header; empty string disables it. |
| **Simulation protection (P3.4)** | | |
| `NT90_SIM_CONCURRENCY` | core count, max 4 | **How many simulations may run at once.** The memory guard: a 2,500-sim run peaks ~260 MB, so an uncapped burst is an OOM kill. |
| `NT90_SIM_WAIT_S` | `15` | How long a request may wait for a simulation slot before `503 simulation queue full`. |
| `NT90_SIM_CACHE` | `64` | LRU entries of finished scenario payloads. Identical scenarios are free and never rate-limited. |
| `NT90_RATE_BURST` | `30` | Token bucket size per IP (cache hits are refunded). |
| `NT90_RATE_REFILL` | `0.5` | Tokens per second per IP. |
| `NT90_MIN_SIMS` / `NT90_MAX_SIMS` | `500` / `10000` | Accepted `n_sims` range; values outside are clamped, not rejected. |
| `NT90_TRUST_PROXY` | off | Believe `X-Forwarded-For` for rate limiting (only behind a proxy you control). |
| **Alerts (P4.5)** | | |
| `NT90_ALERT_WEBHOOK` | unset | Slack/Discord-style incoming webhook. Posted on rejection, crash or non-zero exit. |
| `NT90_ALERT_ON_SUCCESS` | off | Also post a short "published gwN" message. |

### What the limits do to a visitor

Nothing, unless they are trying to. The page, its 304 and `/api/baseline` are never limited; a repeated
scenario is served from the LRU cache and refunds its rate-limit token; only *new* simulation work
consumes a token or a concurrency slot. The load test in `docs/capacity.md` is the evidence.

## 8. Uptime check

Point any free monitor (UptimeRobot, Better Stack, Healthchecks.io) at:

```
https://<your-domain>/readyz      expect 200 + "ready": true
https://<your-domain>/healthz     expect 200 (liveness — alerts if the process itself dies)
```

Or check it by hand every morning:

```bash
curl -s https://<your-domain>/readyz | python3 -m json.tool
```

A healthy body looks like:

```json
{
  "ready": true,
  "engine": "warm",
  "warm_ms": 1035.6,
  "engine_boot_ms": 21.3,
  "artifact_cache_hit": true,
  "refreshes": 2,
  "last_refresh_age_s": 431.2,
  "refresh_interval_s": 21600,
  "baseline_snapshot": true,
  "uptime_s": 18432.7
}
```

If `ready` is false for more than a minute, read `error` — it carries the exception from warm-up, and
the process keeps serving the last good snapshot from disk rather than falling over.

## 9. What is left for you (P1.5)

The four steps in this runbook are autonomous, but the last mile is not — it needs your accounts:

1. **Hosting account** — Fly.io or Render (both have a usable free/starter tier for this).
2. **A domain** (optional but wanted) — then `fly certs add <domain>` or Render → **Custom Domain**,
   and point the DNS record at the host. TLS certificates are issued automatically by both.
3. **First deploy** — run §5 or §6 with your app name.
4. **Verify from a phone on mobile data**, not localhost: load the site, open the What-If tab, run a
   scenario, and check `/readyz` shows `"ready": true`.

Once that is done, the deploy is genuinely finished — and Wave 2 (the live data adapter) needs the
football-data.org API key to make the numbers update themselves.
