# Capacity — what this instance takes before it needs more (P3.5)

Measured, not estimated. Every number below came from `loadtest.py` against a live server on
**2 vCPU / 2 GB RAM** (the sandbox that built this project, Debian 13, Python 3.13, containers sharing
an unknown host). Treat the *shape* of these results as the finding and the absolute values as
illustrative — your own host will be faster or slower, and the reproduction command is at the bottom.

## The numbers

| phase | req | hit/miss | 429/503 | p50 | p95 | p99 | max | req/s |
|---|---|---|---|---|---|---|---|---|
| static `GET /` (gzipped, 192 KB) | 640 | — | 0 | **2.1 ms** | 9.9 ms | 48.7 ms | 81.5 ms | 3,500 |
| revalidate `GET /` (`If-None-Match`) | 640 | — | 0 | **1.2 ms** | 5.0 ms | 11.7 ms | 77.3 ms | 5,691 |
| `GET /api/baseline` | 640 | — | 0 | **1.8 ms** | 6.7 ms | 25.5 ms | 41.5 ms | 4,876 |
| `POST /api/simulate` (all cold) | 48 | 0/48 | 0 | 1,715 ms | 1,830 ms | 1,852 ms | 1,852 ms | 4.6 |
| `POST /api/simulate` (repeat scenario) | 640 | **624/16** | 0 | **0.5 ms** | 5.5 ms | 2,323 ms | 3,644 ms | 175 |
| overload: 48 concurrent sims | 192 | 144/48 | **0** | 1.0 ms | 10,784 ms | 13,083 ms | 13,505 ms | 14.2 |

Monte Carlo throughput: **3,228 sims/s** cold (33,450 sims across 48 requests, 2-way concurrency) —
and a cache hit serves a whole scenario for free.

## What this actually says

**1. Read-side capacity is not the problem.** Everything cached — the page, its 304, the baseline
payload — answers in ~1–2 ms and the box does 3,500–5,700 req/s on two cores. A single server is two
orders of magnitude past what a link on a forum will produce.

**2. Write-side capacity is entirely the Monte Carlo.** One simulation is CPU-bound and allocates
~260 MB peak at 2,500 sims, so:
* **concurrency must be capped**, or the process gets OOM-killed. It happened: the first overload run
  (48 concurrent 2,500-sim requests, no cap) killed the server outright — the log ends mid-sentence
  and the port stops answering. `NT90_SIM_CONCURRENCY` (default = core count, max 4) is the fix, and
  it is a memory guard as much as a CPU one.
* **queueing replaces crashing.** With a 2-slot cap the same 48-way burst completed **192/192 requests
  with zero errors and zero deaths** — p95 latency 10.8 s while they waited their turn, which is bad
  UX and a correct trade against losing the process.
* **the rate limiter matters more than the thread pool.** 30 tokens per IP, refilling at 0.5/s, means
  one visitor cannot queue-bomb the service; identical scenarios are answered from the LRU cache and
  are *never* rate-limited, so a normal visitor clicking "Run" repeatedly pays nothing.

**3. Four fixed costs showed up in this measurement that had nothing to do with load.** Each was found
by load-testing, and each was worth more than any tuning:

| what | before | after | fix |
|---|---|---|---|
| gzip the 500 KB page per request | 111 ms p50 | **2.1 ms** | encode once, cache the gzipped bytes |
| re-serialise the 105 KB baseline per request | 72 ms p50 | **1.8 ms** | cache the encoded payload against the engine's results object |
| Nagle + delayed ACK on two-write responses | 44 ms p50 on *every* JSON reply | **0.6 ms** | `disable_nagle_algorithm = True` |
| accept backlog (stdlib default is 5) | 192/192 connection errors under a burst | 0 | `request_queue_size = 128` |

That 44 ms is the one worth remembering: it was invisible in a browser tab (the page is a single large
write) and applied to every API caller, on every request, forever.

## Where it bends, and what to do about it

| sign | what it means | what to do |
|---|---|---|
| `p95` on `/api/simulate` climbing past ~2 s | the 2-slot queue is saturated | raise `NT90_SIM_CONCURRENCY` only with more RAM (≈300 MB per slot), or run more processes |
| 503 `simulation queue full` | more demand than slots for `NT90_SIM_WAIT_S` | lower `n_sims` in the UI, raise the cap, or add a second instance |
| 503 `server busy` (thread pool) | more than `NT90_MAX_THREADS` connections held open | raise `NT90_MAX_THREADS`, or investigate why connections are slow |
| 429s from one address | the rate limiter working as designed | look at `X-RateLimit-*` and `Retry-After`; identical scenarios are still free |
| RSS climbing in `/api/stats` | concurrent sims with a big `n_sims` | cap `NT90_MAX_SIMS`, or lower `NT90_SIM_CONCURRENCY` |

**The honest summary for a single instance like this one:** it comfortably serves the dashboard to
thousands of visitors, and it comfortably serves maybe **one person clicking "Run" at a time** without
visible delay. The dashboard is the product; the simulator is a feature that costs real CPU, and the
limits exist so that cost can never take the dashboard down with it.

## Reproduce it

```bash
# terminal 1 — a scratch instance, generous limits so the limiter does not confuse the picture
PORT=8403 NT90_PRELOAD=1 NT90_RATE_BURST=1000000 NT90_RATE_REFILL=1000 \
  NT90_SIM_CONCURRENCY=2 NT90_SIM_CACHE=8 python3 server.py

# terminal 2
python3 loadtest.py --url http://127.0.0.1:8403 --phase all --workers 16 --requests 40
python3 loadtest.py --url http://127.0.0.1:8403 --phase all --json     # machine-readable
python3 loadtest.py --url http://127.0.0.1:8403 --phase overload --overload-workers 96
```

Watch it live: `curl -s localhost:8403/api/stats | python3 -m json.tool` publishes latency percentiles,
cache hit rate, in-flight simulations, rate-limit rejections and process RSS.
