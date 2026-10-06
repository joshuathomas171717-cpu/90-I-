"""verify_deployment.py — is the live site serving *this* checkout? (the deploy half of P11.2)

`check_live.py` answers "is the site current?" — a question about the calendar. This answers a different
and narrower one, which is the question an owner actually asks after a push:

    the repository says matchweek 7 and data to 13 October. Does the live site say the same, or is it
    still serving the build before my commit?

Those are different failures and they need different words. A site can be perfectly current and still be
serving last week's build (nothing changed, so nothing to redeploy); it can also be behind on data
because the weekly job promoted nothing, while the *deployment* is perfectly up to date. This tool
compares the deployment against the working tree, field by field, and says which of the two is wrong.

    python3 tools/verify_deployment.py                          # compare production with this checkout
    python3 tools/verify_deployment.py --url <site>             # somewhere else (a preview, a fork)
    python3 tools/verify_deployment.py --page static/index.html  # compare a local build, no network
    python3 tools/verify_deployment.py --retries 6 --wait 30     # wait for a deploy to finish (CI does this)

Exit codes: 0 the deployment matches this checkout · 1 it does not · 2 the page could not be read.

Used by the weekly job as its last step — everything before it proves the repository is right, and
nothing before it proves the deployment changed.
"""
import argparse
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))          # .../tools
ROOT = os.path.dirname(BASE)                                # the project
sys.path.insert(0, ROOT)

import check_live  # noqa: E402  (the inspection logic lives there and is shared, not copied)

SUMMARY = os.path.join(ROOT, "data", "predictions_2026_27_summary.json")
LEDGER = os.path.join(ROOT, "data", "ledger_2026_27.json")


def committed():
    """What this checkout says about itself — the values the deployment should be showing."""
    out = {"matchweek": None, "as_of": None, "n_simulations": None, "season": None, "locks": None, "player_context": None, "player_ui": None, "playground": None}
    if os.path.exists(SUMMARY):
        with open(SUMMARY, encoding="utf-8") as fh:
            meta = (json.load(fh) or {}).get("meta") or {}
        out["matchweek"] = meta.get("next_gw")
        out["as_of"] = str(meta.get("as_of_date") or "")[:10] or None
        out["n_simulations"] = meta.get("n_simulations")
        out["season"] = meta.get("season")
        out["player_context"] = (meta.get("player_signal") or {}).get("fingerprint")
        out["player_ui"] = (meta.get("player_ui") or {}).get("fingerprint")
    _game = os.path.join(ROOT, "data", "playground_manifest.json")
    if os.path.exists(_game):
        with open(_game, encoding="utf-8") as fh: out["playground"] = json.load(fh).get("fingerprint")
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8") as fh:
            out["locks"] = len((json.load(fh) or {}).get("locks") or [])
    return out


def deployed(html):
    """What the live page says about itself."""
    blob = check_live.payload_from(html)
    if blob is None:
        return None
    meta = ((blob or {}).get("baseline") or {}).get("meta") or {}
    return {
        "matchweek": meta.get("next_gw"),
        "as_of": str(meta.get("as_of_date") or "")[:10] or None,
        "n_simulations": meta.get("n_simulations"),
        "season": meta.get("season"),
        "player_context": (meta.get("player_signal") or {}).get("fingerprint"),
        "player_ui": (meta.get("player_ui") or {}).get("fingerprint"),
        "playground": (blob.get("playground") or {}).get("fingerprint"),
        "locks": len((blob.get("ledger") or {}).get("locks")
                     or ((blob.get("ledger") or {}).get("entries") or [])),
    }


def compare(want, got):
    """The fields that must agree, and why each one is on the list.

    `n_simulations` is deliberately *not* compared: it is a build setting rather than a fact about the
    data, and a retuned simulation count would show up as a spurious deployment failure.
    """
    checks = []
    for field, label in (("matchweek", "the matchweek the numbers are for"),
                         ("as_of", "the date the numbers were built from"),
                         ("season", "the season label"),
                         ("player_context", "the player-context content fingerprint"),
                         ("player_ui", "the squad/digest presentation fingerprint"),
                         ("playground", "the career/challenge build fingerprint")):
        checks.append((field, label, want.get(field), got.get(field), want.get(field) == got.get(field)))
    return checks


def read_once(url=None, page=None):
    """(payload, error). Never raises: a monitor says 'I could not look'."""
    try:
        if page:
            with open(page, encoding="utf-8") as fh:
                html = fh.read()
        else:
            html = check_live.fetch(url)
    except Exception as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)
    payload = deployed(html)
    if payload is None:
        return None, "the page carries no embedded payload, so it cannot be judged"
    return payload, None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Is the live site serving this checkout?")
    ap.add_argument("--url", default=os.environ.get("NT90_SITE_URL") or check_live.PRODUCTION)
    ap.add_argument("--page", help="compare a local build instead of fetching")
    ap.add_argument("--retries", type=int, default=1, help="attempts before giving up (CI waits for Vercel)")
    ap.add_argument("--wait", type=int, default=30, help="seconds between attempts")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)

    want = committed()
    target = args.page or args.url
    attempts, last_error = max(1, args.retries), None
    for attempt in range(1, attempts + 1):
        got, error = read_once(url=None if args.page else args.url, page=args.page)
        if got is None:
            last_error = error
            if attempt < attempts:
                if not args.as_json:
                    print("  ...not readable yet (%s); attempt %d of %d" % (error, attempt, attempts))
                time.sleep(args.wait)
                continue
            print("UNREADABLE — %s\n  %s" % (target, error))
            return 2
        checks = compare(want, got)
        if all(ok for *_rest, ok in checks):
            if args.as_json:
                print(json.dumps({"target": target, "matches": True, "deployed": got,
                                  "committed": want}, indent=2, sort_keys=True))
            else:
                print("MATCHES — %s is serving this checkout" % target)
                print("  matchweek %s · data %s · %s" % (got.get("matchweek"), got.get("as_of"),
                                                         got.get("season") or ""))
            return 0
        if attempt < attempts:
            if not args.as_json:
                print("  ...not yet (attempt %d of %d) — Vercel may still be building" % (attempt, attempts))
            time.sleep(args.wait)

    # out of attempts: say exactly which field disagrees, because "deployment failed" is not actionable
    if args.as_json:
        print(json.dumps({"target": target, "matches": False, "deployed": got, "committed": want,
                          "error": last_error}, indent=2, sort_keys=True))
    else:
        print("MISMATCH — %s is not serving this checkout" % target)
        for field, label, mine, theirs, ok in checks:
            print("  %-6s %-42s committed %-22s deployed %s"
                  % ("ok" if ok else "DIFF", label, mine, theirs))
        print("\n  Either Vercel has not finished building, or its build failed. Both are visible in the"
              "\n  Vercel dashboard; docs/operations.md section 3 covers what to do about each.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
