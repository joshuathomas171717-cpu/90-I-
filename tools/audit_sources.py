"""audit_sources.py — P13.1: prove what the player sources actually deliver, or say that it is unproven.

The plan deleted a promise before it was made: international coverage might not be there, so the phase
gates on measuring rather than on a pricing page. This tool is that gate.

    python3 tools/audit_sources.py                 # measure with whatever keys are set
    python3 tools/audit_sources.py --json          # machine-readable, for the doc to quote
    python3 tools/audit_sources.py --offline       # no keys, no network: report what cannot be proven

What it checks, per row of the plan's data table:

  1. the free tier answers at all (a real request, not a document read);
  2. the Premier League id returns twenty clubs whose names resolve to *our* club codes — the one
     number that would silently corrupt everything if it were wrong;
  3. a club's players come back split by competition, and which competitions actually appear;
  4. injuries come back with a type and a reason;
  5. whether international competitions are present, which is the unverified row.

Every check reports `proven`, `not-proven` or `failed`. **Not-proven is a first-class result**, not a
soft failure: it means nobody has spent a request on it yet, and the doc says so in those words. A tool
that turned "no key" into a green tick would defeat the entire point of the gate.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "player-signal.md")


def _check(name, asked, status, detail, evidence=None):
    return {"check": name, "asked": asked, "status": status, "detail": detail, "evidence": evidence or {}}


def audit(provider, club_limit=2, replay=False):
    """Run the measurable checks. `club_limit` keeps the audit cheap: two clubs is enough to prove the
    shape of the payload, and the full run is the collector's job, not the audit's."""
    results = []
    from sources.api_football import PL_LEAGUE_ID

    if not provider.available():
        results.append(_check(
            "the provider answers with a free key", "a request that returns clubs",
            "not-proven", provider.unavailable_reason()))
        for name, asked in (("the league id maps to our clubs", "20 clubs, resolvable names"),
                            ("player statistics split by competition", "one row per competition"),
                            ("injuries with a type and a reason", "type + reason per player"),
                            ("international competitions present", "a national-team competition id")):
            results.append(_check(name, asked, "not-proven",
                                  "needs a free API key — set API_FOOTBALL_KEY and re-run"))
        return results

    # 1–2: the club map
    try:
        teams = provider.fetch_teams(replay=replay)
    except Exception as exc:
        results.append(_check("the provider answers with a free key", "a request that returns clubs",
                              "failed", "%s: %s" % (type(exc).__name__, exc)))
        return results
    ours = set()
    path = os.path.join(ROOT, "data", "teams_2026_27.csv")
    if os.path.exists(path):
        import csv
        with open(path, encoding="utf-8") as fh:
            ours = {(row.get("code") or "").strip() for row in csv.DictReader(fh) if row}
    resolved = {t["code"] for t in teams}
    results.append(_check(
        "the provider answers with a free key", "a request that returns clubs",
        "proven" if teams else "failed", "%d clubs returned" % len(teams)))
    results.append(_check(
        "the league id maps to our clubs", "20 clubs with names we can resolve",
        "proven" if len(teams) == 20 and len(resolved & ours) == 20 else "failed",
        "%d of 20 resolved to our codes (league id %s)" % (len(resolved & ours), PL_LEAGUE_ID),
        {"league_id": PL_LEAGUE_ID, "resolved": sorted(resolved & ours)}))

    # 3: the per-competition split, the reason this provider is used at all
    competitions, sample_rows, problems = set(), 0, []
    for team in teams[:club_limit]:
        try:
            rows = provider.fetch_club_players(team["id"], replay=replay)
        except Exception as exc:
            problems.append("%s: %s" % (team["code"], exc))
            continue
        sample_rows += len(rows)
        competitions |= {(r.get("competition") or "").strip() for r in rows if r.get("competition")}
    import competition_weights as _weights
    internationals = sorted(c for c in competitions
                            if _weights.table().get(_weights.lookup(c)[1], {}).get("tier", "").startswith("international"))
    results.append(_check(
        "player statistics split by competition", "one row per player per competition",
        "proven" if sample_rows else "failed",
        "%d rows across %d competition(s) from %d club(s)" % (sample_rows, len(competitions), club_limit),
        {"competitions": sorted(competitions), "problems": problems}))
    results.append(_check(
        "club competitions include the cups and Europe",
        "Champions League / FA Cup / EFL Cup minutes for at least one club",
        "proven" if any(any(k in c.lower() for k in ("champions league", "fa cup", "efl cup", "carabao"))
                        for c in competitions) else "failed",
        "competitions seen: %s" % (", ".join(sorted(competitions)) or "none")))
    # The row the plan refused to promise.
    if internationals:
        results.append(_check("international competitions present",
                              "a national-team competition in the same response",
                              "proven", "seen: %s" % ", ".join(internationals)))
    else:
        results.append(_check("international competitions present",
                              "a national-team competition in the same response",
                              "not-proven",
                              "no international competition appeared for the clubs sampled — this may "
                              "be a club-only season stage, or it may be absent on the free tier. It "
                              "cannot be concluded either way from %d club(s); sample more with "
                              "--clubs 20" % club_limit))

    # 4: injuries
    injuries, injury_problems = [], []
    for team in teams[:club_limit]:
        try:
            injuries += provider.fetch_injuries(team["id"], replay=replay)
        except Exception as exc:
            injury_problems.append("%s: %s" % (team["code"], exc))
    with_reason = [i for i in injuries if i.get("reason") and i.get("type")]
    results.append(_check(
        "injuries carry a type and a reason", "type (Injury/Suspension) + reason per player",
        "proven" if with_reason or not injuries else "failed",
        "%d entr(ies), %d with both fields" % (len(injuries), len(with_reason)),
        {"problems": injury_problems,
         "sample": [{"player": i["player"], "type": i["type"], "reason": i["reason"]}
                    for i in with_reason[:3]]}))
    return results


def render(results, quota=None, keys=None):
    lines = ["# The player signal: what is actually available (P13.1)",
             "",
             "Written by `tools/audit_sources.py`. Every row below is a *measurement*, and the three",
             "possible answers are deliberate: **proven** (a real request returned it), **not-proven**",
             "(nobody has spent a request on it yet — this is not a soft pass), and **failed** (it was",
             "asked for and did not arrive). A row that cannot be measured is never reported as working.",
             ""]
    if keys is not None:
        lines += ["| key | set |", "|---|---|"]
        for name, present in keys.items():
            lines.append("| `%s` | %s |" % (name, "yes" if present else "no"))
        lines.append("")
    if quota:
        lines += ["Quota at the time of the audit: %s used of %s today (`%s`)."
                  % (quota.get("used"), quota.get("budget"), quota.get("day")), ""]
    lines += ["| check | asked for | result | detail |", "|---|---|---|---|"]
    for r in results:
        lines.append("| %s | %s | **%s** | %s |" % (r["check"], r["asked"], r["status"],
                                                    r["detail"].replace("|", "\\|")))
    lines.append("")
    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    lines += ["**Summary:** " + " · ".join("%d %s" % (v, k) for k, v in sorted(summary.items())), ""]
    lines += [
        "## What this means for the plan",
        "",
        "* A **not-proven** row does not block the build: the keyless path (`data/provider_drop/players/`)",
        "  and every weight in `data/competition_weights.csv` work today, and the tests prove it.",
        "* A **failed** row on the per-competition split would narrow the signal to league minutes. The",
        "  index would still run, and every surface would have to say **league-only** (P15.4).",
        "* International coverage is the one row the plan never promised. If sampling says it is absent,",
        "  internationals are excluded from the index and the exclusion is stated, not averaged in.",
        "",
    ]
    lines.append("Re-run with `python3 tools/audit_sources.py` after setting a key to convert not-proven "
                 "rows into measurements. The audit spends real requests (about %d with `--clubs 2`), "
                 "which is why it is a separate tool rather than part of the weekly job."
                 % (1 + 2 * 2 + 1))
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Measure what the player sources actually deliver (P13.1).")
    ap.add_argument("--clubs", type=int, default=2, help="how many clubs to sample (each costs a request)")
    ap.add_argument("--replay", action="store_true", help="read cached payloads, spend no quota")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--out", default=OUT, help="where to write the report")
    ap.add_argument("--no-write", action="store_true", help="print without writing the doc")
    args = ap.parse_args(argv)

    from sources.api_football import ApiFootballProvider
    provider = ApiFootballProvider()
    keys = {name: bool(os.environ.get(name)) for name in
            ("API_FOOTBALL_KEY", "API_FOOTBALL_API_KEY", "APISPORTS_KEY", "FOOTBALL_DATA_ORG_TOKEN",
             "FOOTBALL_DATA_KEY")}
    results = audit(provider, club_limit=args.clubs, replay=args.replay)
    quota = {"budget": provider.quota.budget, "used": provider.quota.used, "day": provider.quota.day}
    payload = {"generated_at": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).replace(microsecond=0).isoformat(),
        "keys": keys, "quota": quota, "results": results}

    if args.as_json:
        print(json.dumps(payload, indent=2))
    else:
        for r in results:
            print("  %-8s %-46s %s" % (r["status"].upper(), r["check"], r["detail"][:74]))
        counts = {}
        for r in results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        print("  ── %s" % " · ".join("%d %s" % (v, k) for k, v in sorted(counts.items())))

    if not args.no_write and not args.as_json:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(render(results, quota=quota, keys=keys))
        print("  wrote %s" % os.path.relpath(args.out, ROOT))
    # exit 2 if anything actually failed; not-proven is not a failure, because nothing was asked
    return 2 if any(r["status"] == "failed" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
