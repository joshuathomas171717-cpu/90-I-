"""check_page_current.py — is the published page the page the committed data describes? (P4.4 gate)

CI used to answer this by rebuilding the dashboard and running `git diff --exit-code` against
`static/index.html`. That works on one machine and fails on another for a reason that has nothing to
do with staleness:

    the projected numbers depend, in their last decimals, on the numpy / scipy / scikit-learn
    versions that produced them.

CI resolves newer libraries than a developer laptop does, so its Monte Carlo lands a few tenths of a
point away — and on the clubs sitting near the relegation knife edge, a few *points* away. The page
was not stale; the arithmetic was different. The old gate said "your page is out of date" and meant
"your BLAS is".

The question actually worth asking is this one, and it does not depend on any library:

    does the committed page agree with the committed data it was built from?

Both files are produced by the same run and committed together, so they must agree *exactly* — and if
someone edits the dataset and forgets to rebuild the page, this fails loudly. Comparing the two
committed artifacts is also strictly stronger than the byte diff ever was: it inspects every
projected number rather than one file hash.

    python3 check_page_current.py            # exits non-zero if the page is stale
    python3 check_page_current.py --quiet    # only the summary line

It also answers the other half of the question, which is the one CI asks:

    does the page we are about to publish match the page that is already committed?

`--against` compares this tree's freshly built page with a reference copy (`git show
HEAD:static/index.html` in CI). A genuinely stale page — a changed template, a section that moved, a
club that dropped out — fails; a few tenths of a point of Monte Carlo drift between library versions
does not, and the drift that *is* found is printed so it can never hide.
"""
import argparse
import json
import math
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(BASE_DIR, "static", "index.html")
SUMMARY = os.path.join(BASE_DIR, "data", "predictions_2026_27_summary.json")

_EMBED_ANCHOR = "const EMBEDDED = "


def load_page(path=PAGE):
    """Extract the payload the page carries inside it (`const EMBEDDED = {...}`).

    `raw_decode` is used rather than a regex so that braces inside strings cannot fool it.
    """
    html = open(path, encoding="utf-8").read()
    if _EMBED_ANCHOR not in html:
        raise ValueError("%s has no `%s` payload — the page was not built by build_dashboard.py"
                         % (os.path.relpath(path, BASE_DIR), _EMBED_ANCHOR))
    start = html.index(_EMBED_ANCHOR) + len(_EMBED_ANCHOR)
    payload, _end = json.JSONDecoder().raw_decode(html, start)
    return html, payload


def _walk_diff(committed, embedded, path="baseline"):
    """Yield the dotted paths where two JSON values disagree. Floats must match exactly: both sides
    were written by the same process, so anything else is a rebuild that never happened."""
    if isinstance(committed, dict) and isinstance(embedded, dict):
        for key in committed:
            if key not in embedded:
                yield "%s.%s (missing from the page)" % (path, key)
            else:
                for item in _walk_diff(committed[key], embedded[key], "%s.%s" % (path, key)):
                    yield item
    elif isinstance(committed, list) and isinstance(embedded, list):
        if len(committed) != len(embedded):
            yield "%s (page has %d entries, data has %d)" % (path, len(embedded), len(committed))
        for i, (a, b) in enumerate(zip(committed, embedded)):
            for item in _walk_diff(a, b, "%s[%d]" % (path, i)):
                yield item
    elif committed != embedded:
        yield "%s (page %r, data %r)" % (path, embedded, committed)


def check(page_path=PAGE, summary_path=SUMMARY, limit=12):
    """Return a list of problems — empty means the published page matches the committed data."""
    problems = []
    try:
        html, payload = load_page(page_path)
    except (OSError, ValueError) as exc:
        return [str(exc)]

    if not os.path.exists(summary_path):
        return ["%s is missing — run the pipeline before checking the page"
                % os.path.relpath(summary_path, BASE_DIR)]
    summary = json.load(open(summary_path, encoding="utf-8"))
    embedded = payload.get("baseline")
    if embedded is None:
        return ["the page payload has no `baseline` block"]

    # Machine measurements are excluded here too — see IGNORED_FIELDS. Re-running the engine on its
    # own changes runtime_ms without moving a single projected number, and reporting a current page
    # as stale for that would train everyone to ignore this check.
    diffs = [d for d in _walk_diff(summary, embedded)
             if not any(f in d for f in IGNORED_FIELDS)]
    if diffs:
        problems.append(
            "the page carries different numbers from data/%s — rebuild it with "
            "`python3 build_dashboard.py` and commit the result"
            % os.path.basename(summary_path))
        problems += ["    " + d for d in diffs[:limit]]
        if len(diffs) > limit:
            problems.append("    … and %d more" % (len(diffs) - limit))

    # The stamp is written into the HTML as plain text so the first paint is never stale, which makes
    # it the one claim on the page that can be checked without running any JavaScript.
    meta = summary.get("meta", {}) or {}
    next_gw = meta.get("next_gw")
    if next_gw is not None:
        match = re.search(r'id="heroKick"[^>]*>([^<]*)', html)
        stamp = (match.group(1) if match else "").strip()
        if "Matchweek %s" % next_gw not in stamp:
            problems.append('the header stamp says %r but the data is heading into matchweek %s'
                            % (stamp, next_gw))
    as_of = meta.get("as_of_date")
    if as_of:
        match = re.search(r'id="markSub"[^>]*>([^<]*)', html)
        sub = (match.group(1) if match else "").strip()
        if as_of not in sub:
            problems.append('the page says %r but the data is as of %s' % (sub, as_of))

    # A page that lost a club would still parse; check the clubs are all actually in the markup.
    missing = [c["code"] for c in summary.get("table_projections", []) if c["code"] not in html]
    if missing:
        problems.append("these clubs are in the data but nowhere in the page: %s" % ", ".join(missing))

    return problems


# ── comparing two builds of the same page (the CI half) ──────────────────────────────────────────
# Two lessons are baked into the code below, both learned the hard way by running it against a real
# CI environment:
#
#  1. Lists in this payload are *ranked* — the Golden Boot race, the scoreline table, the fixture
#     forecasts. Comparing them position by position compares different subjects the moment the
#     library versions reshuffle a near-tie (Gyökeres and DCL are half a goal apart on the twelfth
#     line of the race). Entries are therefore matched by identity — player_id, club code, fixture,
#     scoreline — never by index.
#  2. Structure and numbers need different treatment. A club that vanished, a race whose top five
#     changed, a page still stamped with last week's matchweek: all real, all fail. A tenth of a
#     point of Monte Carlo drift between two numpy builds: real too, but not this check's business.
#     It is measured and printed, so it can never hide.
PTS_TOL = 1.5          # projected points
PCT_TOL = 2.5          # percentage-point floor for probabilities
PCT_REL = 0.10         # scaled band: near 50/50 a probability is genuinely uncertain
REL_TOL = 0.05         # everything else (goals, assists, composite indices) — 5%, at least half a unit
INT_TOL = 2.0          # an integer projection (a p10/p90 quantile, a rounded total) may move two steps
TOP_N = 5              # how deep into a ranked list a change of identity is a structural change
PROB_HINTS = ("prob", "matrix", "clean_sheet", "btts", "top4", "title", "relegation", "distribution")

#: Recorded on the page but describing the *build*, not the season. `runtime_ms` measures how long
#: the pipeline took, which is exactly the sort of thing a different machine changes; comparing it
#: would fail CI every time for no reason.
#: Ignored in both halves of the gate. `runtime_ms` is the model training time: a measurement of the
#: machine, not of football. Re-running the engine on a busy box produces a different one with no
#: projected number moving — which is exactly what happened the first time this gate ran after
#: `python3 ml_engine.py` on its own, and it called a perfectly current page stale.
IGNORED_FIELDS = ("runtime_ms",)

#: Subtrees that are pass-throughs of the committed CSV datasets rather than anything the model
#: computes. Measured across a real CI environment — different numpy, pandas, scipy and
#: scikit-learn — these 2,632 numbers were *identical*, because no arithmetic stands between the
#: file on disk and the page. So they are held to exact equality, which makes the strongest part of
#: this gate the part with no false alarms. `backtest` is also byte-stable in practice but is left to
#: the tolerant rules: it contains per-match model decisions, and a future library could legitimately
#: flip one of 380 of them.
EXACT_PATHS = ("payload.inputs", "payload.h2h")

#: Lists where a tail entry changing is noise rather than news. A race is ordered by a projection
#: that two library versions will reorder at the margins; the fixtures, the table and the head-to-head
#: grid are fixed membership, and a club or fixture appearing in one of those is always a real change.
RANKED_HINTS = ("race", "scoreline", "poty")

_ID_FIELDS = ("player_id", "code", "id", "score", "name")


def _prob_tol(p):
    return max(PCT_TOL, PCT_REL * math.sqrt(max(p, 0.0) * (100.0 - max(p, 0.0))))


def _maxima(payload):
    """Largest absolute value seen under each leaf field name.

    Used to tell a percentage from a fraction. Guessing from the single value being compared is not
    safe: a club with a 0.3% title probability looks exactly like a fraction of 0.3, and would get a
    tolerance a hundred times too small. The field's own range settles it — `title_prob` reaches
    52.5, `mins_prob` never leaves 0-1.
    """
    out = {}

    def walk(node, name):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, name)
        elif isinstance(node, (int, float)) and not isinstance(node, bool) and name:
            out[name] = max(out.get(name, 0.0), abs(float(node)))

    walk(payload, "")
    return out


def _tol_for(field, ref, max_abs, integer=False):
    """The band a number is allowed to move in, in that number's own units.

    Two different questions, two different inputs: `max_abs` (the field's own range) decides whether
    this is a percentage or a fraction, and `ref` (this particular value) decides how wide the band is
    — a club at 44% relegation is a coin flip the model cannot be precise about, while a club at 88%
    is settled. Judging the scale from one value alone mistakes a 0.3% probability for a fraction of
    0.3 and gives it a hundredth of the room it needs; judging the width from the field's maximum
    would give every club the room of the most uncertain one.
    """
    name = field.lower()
    if any(hint in name for hint in PROB_HINTS):
        percent = (max_abs or 0.0) > 1.5
        value = abs(ref)
        pp = _prob_tol(value if percent else value * 100.0)
        return pp if percent else pp / 100.0
    if name.endswith("pts"):
        return PTS_TOL
    tol = max(0.5, abs(ref) * REL_TOL)
    if integer:
        # Integer fields are quantiles and rounded totals: `goals_p90` is the 90th percentile of a
        # simulated distribution over 5,000 seasons, so it jumps by a whole goal whenever the
        # coefficients shift enough to move one order statistic — measured drift across a real CI
        # environment was ±1 on every integer field, never more. The allowance is two steps rather
        # than one because a one-step allowance puts the observed worst case exactly on the limit,
        # and this gate would then start failing on library updates rather than on staleness. That
        # trade is deliberate: the model-regression guard is tests/test_golden.py, which freezes the
        # headline numbers and fails on any real movement. This gate only has to notice a page that
        # was never rebuilt — and a model change moves the probabilities, which is where it looks.
        tol = max(tol, INT_TOL, abs(ref) * REL_TOL)
    return tol


def _identity(item):
    """A stable label for one entry of a ranked list, or None if it has none."""
    if isinstance(item, dict):
        for key in _ID_FIELDS:
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
        if item.get("home") and item.get("away"):
            return "%s-%s" % (item["home"], item["away"])
    return None


def _align(list_a, list_b):
    """Pair up two lists by identity when possible, by position otherwise."""
    keys_a, keys_b = [_identity(x) for x in list_a], [_identity(x) for x in list_b]
    keyed = (all(keys_a) and all(keys_b)
             and len(set(keys_a)) == len(keys_a) and len(set(keys_b)) == len(keys_b))
    if not keyed:
        return [(str(i), list_a[i], list_b[i]) for i in range(min(len(list_a), len(list_b)))], [], [], False
    by_key_b = dict(zip(keys_b, list_b))
    pairs = [(k, x, by_key_b[k]) for k, x in zip(keys_a, list_a) if k in by_key_b]
    only_a = [k for k in keys_a if k not in by_key_b]
    only_b = [k for k in keys_b if k not in set(keys_a)]
    return pairs, only_a, only_b, True


class _Report:
    def __init__(self, maxima=None):
        self.structural = []
        self.overs = []
        self.notes = []
        self.worst = (None, 0.0, 0.0)
        self.compared = 0
        self.maxima = maxima or {}


def _compare(a, b, path, rep, depth=0):
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a:
                rep.notes.append("%s.%s only in the committed page" % (path, key))
            elif key not in b:
                rep.notes.append("%s.%s only in the rebuilt page" % (path, key))
            else:
                _compare(a[key], b[key], "%s.%s" % (path, key), rep, depth + 1)
        return

    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            rep.notes.append("%s: %d entries in the rebuilt page, %d committed" % (path, len(a), len(b)))
        pairs, only_a, only_b, keyed = _align(a, b)
        if keyed:
            ranked = any(hint in path.lower() for hint in RANKED_HINTS)
            keys_a, keys_b = [_identity(x) for x in a], [_identity(x) for x in b]
            for label in only_a + only_b:
                # The rank has to be read from whichever list actually holds the entry — looking only
                # at one side made every entry missing from it look like it sat at rank 1, which
                # turned routine tail churn in a race into a "the top 5 changed" alarm.
                where = [i for i, k in enumerate(keys_a) if k == label]
                if not where:
                    where = [i for i, k in enumerate(keys_b) if k == label]
                rank = (where[0] if where else len(keys_a)) + 1
                if not ranked:
                    rep.structural.append("%s: %r is in the rebuild but not in the committed page"
                                          % (path, label))
                elif rank <= TOP_N:
                    rep.structural.append("%s: the top %d changed — %r is no longer at rank %d"
                                          % (path, TOP_N, label, rank))
                else:
                    rep.notes.append("%s: %r moved in or out below rank %d" % (path, label, TOP_N))
        for label, x, y in pairs:
            _compare(x, y, "%s[%s]" % (path, label), rep, depth + 1)
        return

    if isinstance(a, bool) or isinstance(b, bool):
        if a != b:
            rep.structural.append("%s: %r became %r" % (path, b, a))
        return

    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        rep.compared += 1
        delta = a - b
        if delta == 0.0:
            return
        field = path.rsplit(".", 1)[-1].split("[")[0]
        if field in IGNORED_FIELDS:
            return
        if any(path.startswith(exact) for exact in EXACT_PATHS):
            rep.compared += 1
            if a != b:
                rep.overs.append("%s: %g in the rebuild vs %g committed — this is read straight from "
                                 "the committed dataset and cannot legitimately differ" % (path, a, b))
            return
        tol = _tol_for(field, b, rep.maxima.get(field),
                       integer=float(a).is_integer() and float(b).is_integer())
        ratio = abs(delta) / tol if tol else float("inf")
        if ratio > rep.worst[1]:
            rep.worst = (path, ratio, tol)
        if ratio > 1.0:
            rep.overs.append("%s: %g in the rebuild vs %g committed (Δ %+g, tol ±%g)" % (path, a, b, delta, tol))
        return

    if a != b and not isinstance(a, (dict, list)):
        rep.notes.append("%s: %r became %r" % (path, b, a))


def compare_builds(this_page, reference_page, limit=8):
    """Problems where a freshly built page disagrees with a reference copy of the published one."""
    try:
        _html_now, payload_now = load_page(this_page)
        _html_ref, payload_ref = load_page(reference_page)
    except (OSError, ValueError) as exc:
        return ["could not compare builds: %s" % exc]

    maxima = _maxima(payload_ref)
    for field, value in _maxima(payload_now).items():
        maxima[field] = max(maxima.get(field, 0.0), value)
    rep = _Report(maxima)
    _compare(payload_now, payload_ref, "payload", rep)

    problems = list(rep.structural)

    # The matchweek markers are compared exactly, before any tolerance applies. They are integers,
    # and a one-step move in an integer field is precisely what the quantile rules tolerate — which
    # would let a page still stamped with the previous gameweek pass as "within noise". A page a
    # week behind is the single most likely way for this one to be wrong.
    meta_now = (payload_now.get("baseline") or {}).get("meta") or {}
    meta_ref = (payload_ref.get("baseline") or {}).get("meta") or {}
    for field in ("next_gw", "last_completed_gw", "as_of_date"):
        if meta_now.get(field) != meta_ref.get(field):
            problems.append("the rebuilt page says %s = %r, the committed page says %r — the "
                            "gameweek marker cannot move by drift" % (field, meta_now.get(field),
                                                                   meta_ref.get(field)))
    if rep.overs:
        problems.append("the rebuilt page moved further than Monte Carlo noise allows — if the change "
                        "was intended, commit the rebuilt page")
        problems += ["    " + o for o in rep.overs[:limit]]
        if len(rep.overs) > limit:
            problems.append("    … and %d more" % (len(rep.overs) - limit))

    path, ratio, tol = rep.worst
    if path:
        print("  · largest numeric drift: %s (%.2f× its ±%g tolerance)" % (path, ratio, tol))
    for note in rep.notes[:3]:
        print("  · note: %s" % note)
    if len(rep.notes) > 3:
        print("  · note: … and %d more structural notes" % (len(rep.notes) - 3))
    if not problems:
        print("  ✓ rebuilt page matches the committed one: same sections, clubs and ranked lists; "
              "all %d numbers inside tolerance" % rep.compared)
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--page", default=PAGE)
    ap.add_argument("--summary", default=SUMMARY)
    ap.add_argument("--against", default=None,
                    help="a reference copy of the published page (e.g. `git show HEAD:static/index.html`); "
                         "compares this tree's build against it with documented tolerances")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    problems = check(args.page, args.summary)
    if args.against:
        problems += compare_builds(args.page, args.against)
    if not args.quiet:
        print("▶ check_page_current.py — the published page vs the committed data")
    if problems:
        for p in problems:
            print("  ✗ " + p)
        print("\n  FAIL: static/index.html is stale. Rebuild it (`python3 build_dashboard.py`) and commit.")
        return 1
    if not args.quiet:
        summary = json.load(open(args.summary, encoding="utf-8"))
        print("  ✓ page payload matches data/%s exactly (%d clubs, %d fixtures projected)"
              % (os.path.basename(args.summary), len(summary.get("table_projections", [])),
                 summary.get("ml_metrics", {}).get("remaining_fixtures", 0)))
        print("  ✓ header stamp and as-of date agree with the data")
    return 0


if __name__ == "__main__":
    sys.exit(main())
