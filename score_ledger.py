"""The prediction ledger — a public, append-only record of what was predicted before kickoff.

This is P10.2, and it is the part of the project that is supposed to be believable rather than
merely accurate. A prediction site can quietly regenerate last week's forecast once the results are
known and nobody would ever see it happen, so the ledger's whole job is to make that impossible to do
without leaving a trace:

  * **Locked before kickoff.** `lock_gameweek()` records a SHA-256 of the published predictions,
    the moment they were locked, and which snapshot they came from. The snapshot itself is written
    by the weekly job *before* a ball is kicked, so the hash is of something the world could have
    read at that time.
  * **Never edited, only added to.** Scoring appends. Re-scoring a gameweek whose numbers moved
    (a corrected result, a bug) keeps the old entry in `revisions` and says what changed; nothing is
    deleted. The weekly job still sees one current entry per gameweek, which is what its tests pin.
  * **Verifiable by anyone.** Every write extends a hash chain, and `verify()` recomputes both the
    chain and each lock's hash straight from the snapshot files on disk. Tampering with a published
    prediction, or with an old score, breaks verification — no trust in the author required.
  * **Honest about being empty.** The ledger starts with the first gameweek locked after this module
    existed. It does not back-fill gameweeks whose predictions were never published, because inventing
    a pre-match record after the match is exactly the failure this file exists to prevent. The 2025-26
    season replay is the historical receipts, and it is labelled as a replay everywhere it appears.

The staleness note from P2.6 still applies to the scored rows: the model is refit weekly and the
artefact cache is keyed on its inputs, so a ledger entry always reflects the model as published.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("NT90_DATA_DIR") or os.path.join(BASE_DIR, "data")
LEDGER_PATH = os.path.join(DATA_DIR, "ledger_2026_27.json")
SNAPSHOT_DIR = os.path.join(DATA_DIR, "snapshots")

sys.path.insert(0, BASE_DIR)
from standings import outcome_of  # noqa: E402  (single source of truth for H/D/A)


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  Scoring — the standard RPS, in one place
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def score_prediction(probs, actual):
    """(hit, rps) for one match. probs = {"home","draw","away"} in %, actual in {"H","D","A"}.

    RPS (ranked probability score) is the right metric for a three-way football result because it
    rewards being *close*: calling a home win at 90% is punished harder than calling it at 45% when
    the away side wins. Lower is better; a coin toss scores about 0.24.
    """
    p = [probs["home"] / 100.0, probs["draw"] / 100.0, probs["away"] / 100.0]
    total = sum(p) or 1.0
    p = [x / total for x in p]
    order = {"H": 0, "D": 1, "A": 2}
    hit = max(range(3), key=lambda i: p[i]) == order[actual]          # argmax over [home, draw, away]
    cumulative_p = [p[0], p[0] + p[1]]
    actual_vec = [1.0 if order[actual] == 0 else 0.0, 1.0 if order[actual] <= 1 else 0.0]
    rps = 0.5 * sum((cp - ca) ** 2 for cp, ca in zip(cumulative_p, actual_vec))
    return hit, round(rps, 4)


def score_gameweek(predictions, results):
    """Score a published set of predictions against the results that have since arrived.

    `predictions` come from the snapshot as published (never re-derived — that is the point), and
    `results` are rows with home/away/home_goals/away_goals. Fixtures with no result yet are skipped,
    so a partially played gameweek scores as far as it has got.
    """
    by_key = {(r["home"], r["away"]): r for r in results}
    rows, hits = [], 0
    for pred in predictions:
        actual = by_key.get((pred["home"], pred["away"]))
        if not actual:
            continue
        hg, ag = int(actual["home_goals"]), int(actual["away_goals"])
        hit, rps = score_prediction(
            {"home": pred["prob_home"], "draw": pred["prob_draw"], "away": pred["prob_away"]},
            outcome_of(hg, ag))
        hits += 1 if hit else 0
        rows.append({"home": pred["home"], "away": pred["away"],
                     "predicted": {"home": pred["prob_home"], "draw": pred["prob_draw"], "away": pred["prob_away"]},
                     "predicted_score": (pred.get("top_scorelines") or [{}])[0].get("score"),
                     "actual": outcome_of(hg, ag), "actual_score": "%d-%d" % (hg, ag),
                     "hit": hit, "rps": rps})
    if not rows:
        return None
    return {"matches": len(rows), "hits": hits, "accuracy_pct": round(hits / len(rows) * 100, 1),
            "mean_rps": round(sum(r["rps"] for r in rows) / len(rows), 4), "rows": rows}


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  Hashing — what makes a lock worth anything
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def canonical(blob):
    """A stable byte-for-byte representation, so the same predictions always hash the same.

    Key order is irrelevant in JSON, floats are not: 68.5 and 68.50000000000001 are the same number
    to a reader and different bytes to a hasher. Rounding to four decimals before serialising keeps a
    lock verifiable after a round trip through a file.
    """
    def norm(value):
        if isinstance(value, dict):
            return {k: norm(value[k]) for k in sorted(value)}
        if isinstance(value, list):
            return [norm(v) for v in value]
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, float):
            return round(value, 4)
        if isinstance(value, int):
            return float(value) if abs(value) < 1e15 else value
        return value

    return json.dumps(norm(blob), sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_hash(predictions):
    """The SHA-256 a reader can recompute from `data/snapshots/gwNN.json` themselves."""
    return hashlib.sha256(canonical(predictions)).hexdigest()


def _chain_hash(prev, record):
    payload = json.dumps({k: v for k, v in record.items() if k != "hash"},
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256((prev or "").encode("utf-8") + payload).hexdigest()


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  The ledger file
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def empty_ledger():
    return {
        "season": "2026-27",
        "note": ("Predictions are locked before kickoff and scored after. Locks and revisions are "
                 "append-only: run `python3 score_ledger.py --verify` to check this file against the "
                 "published snapshots yourself."),
        "entries": [],        # the current score for each gameweek — what the site reads
        "locks": [],          # what was published, when, and the hash of it. Never rewritten.
        "revisions": [],      # every write, chained. Never rewritten.
        "summary": {"gameweeks": 0, "matches": 0, "hits": 0, "accuracy_pct": None, "mean_rps": None},
    }


def load(path=LEDGER_PATH):
    if not os.path.exists(path):
        return empty_ledger()
    try:
        with open(path, encoding="utf-8") as fh:
            ledger = json.load(fh)
    except (OSError, ValueError):
        return empty_ledger()
    for key, default in empty_ledger().items():
        ledger.setdefault(key, default)
    return ledger


def save(ledger, path=LEDGER_PATH):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    ledger["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(ledger, fh, indent=2)
        fh.write("\n")
    return ledger


def _append_revision(ledger, event, gameweek, detail, digest):
    """Extend the hash chain. `prev` is the previous record's hash, so any edit breaks every link."""
    chain = ledger.setdefault("revisions", [])
    prev = chain[-1]["hash"] if chain else ""
    record = {"seq": len(chain), "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "event": event, "gameweek": gameweek, "detail": detail, "content": digest,
              "prev": prev}
    record["hash"] = _chain_hash(prev, record)
    chain.append(record)
    return record


def lock_gameweek(snapshot, path=LEDGER_PATH, source_file=None):
    """Record that this gameweek's predictions were published, and hash them.

    Idempotent for identical predictions, so the weekly job can call it every run. If the hash for a
    gameweek *changes*, the old lock stays and a new one is appended that says what it supersedes —
    which is the honest way to handle a corrected publication, and a visible one.
    """
    gameweek = int(snapshot["gameweek"])
    predictions = snapshot["predictions"]
    digest = content_hash(predictions)
    ledger = load(path)

    existing = [l for l in ledger["locks"] if l["gameweek"] == gameweek]
    if existing and existing[-1]["content_hash"] == digest:
        return ledger, existing[-1], False

    lock = {
        "gameweek": gameweek,
        "locked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": snapshot.get("as_of"),
        "generated": snapshot.get("generated"),
        "snapshot": source_file or os.path.basename(
            os.path.join(SNAPSHOT_DIR, "gw%02d.json" % gameweek)),
        "predictions": len(predictions),
        "content_hash": digest,
        "supersedes": existing[-1]["content_hash"] if existing else None,
    }
    ledger["locks"].append(lock)
    _append_revision(ledger, "superseded" if existing else "locked", gameweek,
                     "%d predictions, hash %s%s" % (len(predictions), digest[:12],
                                                    " (replaces %s)" % existing[-1]["content_hash"][:12]
                                                    if existing else ""), digest)
    save(ledger, path)
    return ledger, lock, True


def entry_hash(entry):
    return content_hash({k: entry[k] for k in sorted(entry) if k != "locked"})


def append_ledger(entry, path=LEDGER_PATH):
    """Append a scored gameweek. Idempotent when nothing changed; every change is recorded.

    This is the function the weekly job calls, and it keeps that job's contract: the ledger carries
    exactly one current entry per gameweek, and its `summary` is the season to date. What is new is
    what happens on a *change* — the previous numbers are kept in `revisions` rather than dropped, so
    a score can be corrected without the correction being invisible.
    """
    ledger = load(path)
    entry = dict(entry)
    entry.setdefault("locked", next(
        (l for l in ledger["locks"] if l["gameweek"] == entry.get("gameweek")), None))
    digest = entry_hash(entry)

    previous = next((e for e in ledger["entries"] if e.get("gameweek") == entry["gameweek"]), None)
    if previous and entry_hash(previous) == digest:
        return ledger                                   # nothing to do; the record already matches

    if previous:
        ledger.setdefault("history", []).append(previous)
        _append_revision(ledger, "rescore", entry["gameweek"],
                         "previous %d/%d (%.1f%%) → %d/%d (%.1f%%)"
                         % (previous["hits"], previous["matches"], previous["accuracy_pct"],
                            entry["hits"], entry["matches"], entry["accuracy_pct"]), digest)
    else:
        _append_revision(ledger, "scored", entry["gameweek"],
                         "%d/%d correct (%.1f%%), mean RPS %.4f"
                         % (entry["hits"], entry["matches"], entry["accuracy_pct"], entry["mean_rps"]),
                         digest)

    ledger["entries"] = [e for e in ledger["entries"] if e.get("gameweek") != entry["gameweek"]]
    ledger["entries"].append(entry)
    ledger["entries"].sort(key=lambda e: e["gameweek"])

    total_m = sum(e["matches"] for e in ledger["entries"])
    total_h = sum(e["hits"] for e in ledger["entries"])
    ledger["summary"] = {
        "gameweeks": len(ledger["entries"]), "matches": total_m, "hits": total_h,
        "accuracy_pct": round(total_h / total_m * 100, 1) if total_m else None,
        "mean_rps": (round(sum(e["mean_rps"] * e["matches"] for e in ledger["entries"]) / total_m, 4)
                     if total_m else None),
    }
    save(ledger, path)
    return ledger


def score_and_append(results, path=LEDGER_PATH, snapshot_dir=SNAPSHOT_DIR):
    """Score every locked gameweek whose results are now in, and append what is new.

    A gameweek is scored when at least one of its fixtures has a result, and re-scored as the weekend
    progresses — which is why the entry carries a `scored_at` and the append is chain-recorded.
    """
    ledger = load(path)
    written = []
    for lock in list(ledger["locks"]):
        snapshot_path = os.path.join(snapshot_dir, lock["snapshot"])
        if not os.path.exists(snapshot_path):
            continue
        with open(snapshot_path, encoding="utf-8") as fh:
            snapshot = json.load(fh)
        scored = score_gameweek(snapshot["predictions"], results)
        if not scored:
            continue
        entry = dict(scored)
        entry["gameweek"] = lock["gameweek"]
        entry["scored_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        before = next((e for e in ledger["entries"] if e.get("gameweek") == lock["gameweek"]), None)
        was = before and {k: before.get(k) for k in ("matches", "hits", "mean_rps")}
        now = {k: entry.get(k) for k in ("matches", "hits", "mean_rps")}
        ledger = append_ledger(entry, path=path)
        if was != now:
            written.append(entry)
    return ledger, written


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  Verification — the part a reader is allowed not to take on trust
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def verify(path=LEDGER_PATH, snapshot_dir=SNAPSHOT_DIR):
    """Recompute every hash from the files on disk. Returns a report; never raises on bad data.

    Two independent checks, either of which fails loudly:
      1. the hash chain — every revision's `prev` must equal the previous revision's hash, and its own
         hash must recompute from its contents, so an edited or deleted record shows up;
      2. each lock — the SHA-256 recorded at lock time must equal the hash of the predictions in the
         snapshot file today, so an edited prediction shows up.
    """
    report = {"ok": True, "checked": 0, "problems": [], "locks": [], "chain": 0}

    if not os.path.exists(path):
        report["ok"] = False
        report["problems"].append("no ledger at %s" % path)
        return report

    ledger = load(path)

    prev = ""
    for i, record in enumerate(ledger.get("revisions", [])):
        expected = _chain_hash(prev, record)
        if record.get("prev") != prev:
            report["ok"] = False
            report["problems"].append("revision %d: prev link broken (%s ≠ %s)"
                                      % (i, record.get("prev"), prev))
        if record.get("hash") != expected:
            report["ok"] = False
            report["problems"].append("revision %d: record hash does not recompute — this file has "
                                      "been edited after it was written" % i)
        prev = record.get("hash", "")
    report["chain"] = len(ledger.get("revisions", []))

    for lock in ledger.get("locks", []):
        snapshot_path = os.path.join(snapshot_dir, lock.get("snapshot", ""))
        state = {"gameweek": lock["gameweek"], "hash": lock["content_hash"], "snapshot": lock.get("snapshot")}
        if not os.path.exists(snapshot_path):
            state["status"] = "snapshot missing"
            report["problems"].append("gw%s: snapshot %s is not on disk, so the lock cannot be checked"
                                      % (lock["gameweek"], lock.get("snapshot")))
            report["ok"] = False
        else:
            with open(snapshot_path, encoding="utf-8") as fh:
                snapshot = json.load(fh)
            actual = content_hash(snapshot["predictions"])
            report["checked"] += 1
            if actual == lock["content_hash"]:
                state["status"] = "verified"
            else:
                state["status"] = "MISMATCH"
                state["actual"] = actual
                report["ok"] = False
                report["problems"].append(
                    "gw%s: the published predictions hash to %s but the lock says %s — the predictions "
                    "changed after they were locked" % (lock["gameweek"], actual[:16],
                                                        lock["content_hash"][:16]))
        report["locks"].append(state)

    return report


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _load_results(data_dir=DATA_DIR):
    import csv
    path = os.path.join(data_dir, "matches_2026_27_played.csv")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lock, score and verify the public prediction ledger.")
    ap.add_argument("--path", default=LEDGER_PATH)
    ap.add_argument("--lock", action="store_true", help="lock the newest snapshot before kickoff")
    ap.add_argument("--score", action="store_true", help="score every locked gameweek with results in")
    ap.add_argument("--verify", action="store_true", help="recheck every hash against the snapshots")
    ap.add_argument("--json", action="store_true", help="print the ledger as JSON")
    args = ap.parse_args(argv)

    if args.lock:
        snapshot_dir = os.path.join(os.path.dirname(args.path) or ".", "snapshots")
        files = sorted(f for f in os.listdir(snapshot_dir)
                       if f.startswith("gw") and f.endswith(".json")) if os.path.isdir(snapshot_dir) else []
        if not files:
            print("  no snapshot to lock — run the weekly job first")
            return 1
        with open(os.path.join(snapshot_dir, files[-1]), encoding="utf-8") as fh:
            snapshot = json.load(fh)
        ledger, lock, changed = lock_gameweek(snapshot, path=args.path, source_file=files[-1])
        print("  gw%d %s · %d predictions · %s%s"
              % (lock["gameweek"], "locked" if changed else "already locked", lock["predictions"],
                 lock["content_hash"][:16], "" if changed else " (unchanged)"))
        return 0

    if args.score:
        ledger, written = score_and_append(_load_results(), path=args.path)
        if written:
            for entry in written:
                print("  gw%d scored: %d/%d (%.1f%%) · mean RPS %.4f"
                      % (entry["gameweek"], entry["hits"], entry["matches"],
                         entry["accuracy_pct"], entry["mean_rps"]))
        else:
            print("  nothing new to score · %d gameweek(s) in the ledger" % len(ledger["entries"]))
        return 0

    if args.verify:
        report = verify(path=args.path)
        for lock in report["locks"]:
            print("  gw%-3s %-16s %s" % (lock["gameweek"], lock["status"], lock["hash"][:16]))
        for problem in report["problems"]:
            print("  ✗ %s" % problem)
        print("  chain: %d revisions · locks verified: %d · %s"
              % (report["chain"], report["checked"], "OK" if report["ok"] else "PROBLEMS FOUND"))
        return 0 if report["ok"] else 1

    if args.json:
        print(json.dumps(load(args.path), indent=2))
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
