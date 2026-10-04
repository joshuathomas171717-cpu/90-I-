"""The prediction ledger (P10.2) — what it must never allow, and how to tell if it did.

The ledger's value is entirely in claims an adversary would like to break: that a published
prediction was not edited afterwards, and that a scored record was not rewritten. Those are testable
without trusting the author, so they are tested here by *doing* the tampering and requiring the
verifier to catch it. A verification routine that has only ever seen honest data has proved nothing.

The shipped ledger is also checked against the shipped snapshot, so a lock that no longer matches the
published predictions fails the suite rather than sitting on the site.
"""

import json
import os
import shutil
import sys
import tempfile

from _util import ROOT, skip

DATA = os.path.join(ROOT, "data")
sys.path.insert(0, ROOT)

import score_ledger as SL   # noqa: E402  (imported after the path insert, deliberately)


def _snapshot(name="gw06.json"):
    path = os.path.join(DATA, "snapshots", name)
    if not os.path.exists(path):
        skip("data/snapshots/%s is missing" % name)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _sandbox():
    """A throwaway directory holding a copy of a real snapshot, so nothing touches data/."""
    tmp = tempfile.mkdtemp(prefix="nt90-ledger-")
    snaps = os.path.join(tmp, "snapshots")
    os.makedirs(snaps)
    shutil.copy(os.path.join(DATA, "snapshots", "gw06.json"), os.path.join(snaps, "gw06.json"))
    return tmp, snaps, os.path.join(tmp, "ledger.json")


def _results_for(snapshot, home_goals=2, away_goals=1):
    return [{"home": p["home"], "away": p["away"], "home_goals": home_goals, "away_goals": away_goals}
            for p in snapshot["predictions"]]


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  What the shipped ledger asserts, checked against the shipped files
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_shipped_ledger_verifies_against_the_shipped_snapshots():
    """The published record must pass its own verifier — that is the whole promise of the page."""
    path = os.path.join(DATA, "ledger_2026_27.json")
    if not os.path.exists(path):
        skip("data/ledger_2026_27.json is missing")
    report = SL.verify(path=path, snapshot_dir=os.path.join(DATA, "snapshots"))
    assert report["ok"], "the shipped ledger does not verify: %s" % report["problems"]
    assert report["checked"] >= 1, "no lock was actually checked"
    assert report["chain"] >= 1, "the ledger has no audit trail, so edits would be invisible"
    for lock in report["locks"]:
        assert lock["status"] == "verified", lock


def test_every_lock_names_a_prediction_that_is_still_in_the_snapshot():
    """Stronger than the hash check: the lock's gameweek and fixture count must match its file."""
    path = os.path.join(DATA, "ledger_2026_27.json")
    if not os.path.exists(path):
        skip("data/ledger_2026_27.json is missing")
    ledger = SL.load(path)
    for lock in ledger.get("locks", []):
        snap_path = os.path.join(DATA, "snapshots", lock["snapshot"])
        assert os.path.exists(snap_path), "%s is missing" % lock["snapshot"]
        with open(snap_path, encoding="utf-8") as fh:
            snapshot = json.load(fh)
        assert snapshot["gameweek"] == lock["gameweek"], lock
        assert len(snapshot["predictions"]) == lock["predictions"], (
            "the snapshot now holds %d predictions but the lock recorded %d"
            % (len(snapshot["predictions"]), lock["predictions"]))
        assert lock["content_hash"] == SL.content_hash(snapshot["predictions"])


def test_the_ledger_never_claims_a_gameweek_it_could_not_have_published():
    """No back-filling: the ledger's first lock is the first gameweek locked by this code.

    The failure this prevents is the tempting one — reconstructing a pre-match record for gameweeks
    whose predictions were never published, which would make the whole record worthless while looking
    complete. Every lock must therefore point at a snapshot file, and the snapshot's own `generated`
    timestamp must predate the lock.
    """
    path = os.path.join(DATA, "ledger_2026_27.json")
    if not os.path.exists(path):
        skip("data/ledger_2026_27.json is missing")
    for lock in SL.load(path).get("locks", []):
        assert lock.get("snapshot"), "a lock with no snapshot file cannot be checked by a reader"
        assert lock.get("generated"), (
            "lock for gw%s carries no snapshot generation time, so nobody can tell when the "
            "predictions were actually made" % lock["gameweek"])
        assert lock["generated"][:10] <= lock["locked_at"][:10], (
            "gw%s claims to be locked before its own predictions existed (%s vs %s)"
            % (lock["gameweek"], lock["locked_at"], lock["generated"]))
        assert lock.get("content_hash") and len(lock["content_hash"]) == 64


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  Tampering, done for real
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_editing_a_published_prediction_is_detected():
    tmp, snaps, ledger_path = _sandbox()
    SL.lock_gameweek(_snapshot(), path=ledger_path)
    assert SL.verify(path=ledger_path, snapshot_dir=snaps)["ok"]

    snap_path = os.path.join(snaps, "gw06.json")
    with open(snap_path, encoding="utf-8") as fh:
        edited = json.load(fh)
    edited["predictions"][0]["prob_home"] = 92.0            # "we always fancied Arsenal"
    with open(snap_path, "w", encoding="utf-8") as fh:
        json.dump(edited, fh)

    report = SL.verify(path=ledger_path, snapshot_dir=snaps)
    assert not report["ok"], "editing a published prediction was not detected"
    assert report["locks"][0]["status"] == "MISMATCH"
    assert any("changed after they were locked" in p for p in report["problems"]), report["problems"]


def test_editing_the_ledgers_own_history_is_detected():
    tmp, snaps, ledger_path = _sandbox()
    SL.lock_gameweek(_snapshot(), path=ledger_path)

    with open(ledger_path, encoding="utf-8") as fh:
        ledger = json.load(fh)
    ledger["revisions"][0]["detail"] = "nothing to see here"
    with open(ledger_path, "w", encoding="utf-8") as fh:
        json.dump(ledger, fh)

    report = SL.verify(path=ledger_path, snapshot_dir=snaps)
    assert not report["ok"], "an edited audit trail passed verification"
    assert any("does not recompute" in p or "prev link broken" in p for p in report["problems"]), \
        report["problems"]


def test_deleting_a_revision_breaks_the_chain():
    """A hash chain catches removals, not just edits — the link is checked, not only the record."""
    tmp, snaps, ledger_path = _sandbox()
    SL.lock_gameweek(_snapshot(), path=ledger_path)
    SL.score_and_append(_results_for(_snapshot()), path=ledger_path, snapshot_dir=snaps)

    with open(ledger_path, encoding="utf-8") as fh:
        ledger = json.load(fh)
    assert len(ledger["revisions"]) >= 2, "expected a lock and a score revision"
    del ledger["revisions"][-2]
    with open(ledger_path, "w", encoding="utf-8") as fh:
        json.dump(ledger, fh)

    assert not SL.verify(path=ledger_path, snapshot_dir=snaps)["ok"], \
        "deleting a revision went unnoticed"


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  Locking and scoring behaviour the weekly job depends on
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_locking_is_idempotent_and_a_changed_publication_is_visible():
    tmp, snaps, ledger_path = _sandbox()
    snapshot = _snapshot()

    _, lock, changed = SL.lock_gameweek(snapshot, path=ledger_path)
    assert changed and lock["gameweek"] == 6

    _, same, changed_again = SL.lock_gameweek(snapshot, path=ledger_path)
    assert not changed_again, "re-locking identical predictions should be a no-op"
    assert same["content_hash"] == lock["content_hash"]
    assert len(SL.load(ledger_path)["locks"]) == 1

    moved = json.loads(json.dumps(snapshot))
    moved["predictions"][0]["prob_home"] = 70.0
    _, second, changed_thrice = SL.lock_gameweek(moved, path=ledger_path)
    assert changed_thrice
    locks = SL.load(ledger_path)["locks"]
    assert len(locks) == 2, "a re-publication must be added, never swapped in"
    assert second["supersedes"] == lock["content_hash"], "the new lock must name what it replaces"
    assert locks[0]["content_hash"] == lock["content_hash"], "the original lock was overwritten"


def test_scoring_is_idempotent_but_a_corrected_result_is_recorded():
    tmp, snaps, ledger_path = _sandbox()
    snapshot = _snapshot()
    SL.lock_gameweek(snapshot, path=ledger_path)

    ledger, written = SL.score_and_append(_results_for(snapshot), path=ledger_path, snapshot_dir=snaps)
    assert written and ledger["entries"], "scoring a played gameweek wrote nothing"
    first = ledger["entries"][0]
    assert first["matches"] == len(snapshot["predictions"])
    assert first["hits"] + (first["matches"] - first["hits"]) == first["matches"]

    again, written_again = SL.score_and_append(_results_for(snapshot), path=ledger_path,
                                              snapshot_dir=snaps)
    assert not written_again, "re-scoring identical results should not rewrite the entry"
    assert len(again["entries"]) == 1

    # A corrected scoreline: the entry updates, and the old numbers survive in the audit trail.
    corrected, written_thrice = SL.score_and_append(_results_for(snapshot, 0, 0), path=ledger_path,
                                                   snapshot_dir=snaps)
    assert written_thrice, "a corrected result should be recorded as a change"
    assert corrected["entries"][0]["hits"] != first["hits"]
    assert corrected.get("history"), "the previous scoring was dropped instead of kept"
    assert any(r["event"] == "rescore" for r in corrected["revisions"]), corrected["revisions"]
    assert SL.verify(path=ledger_path, snapshot_dir=snaps)["ok"], "the chain broke during a rescore"


def test_a_gameweek_with_no_result_yet_scores_nothing():
    tmp, snaps, ledger_path = _sandbox()
    SL.lock_gameweek(_snapshot(), path=ledger_path)
    ledger, written = SL.score_and_append([], path=ledger_path, snapshot_dir=snaps)
    assert not written and not ledger["entries"], "an unplayed gameweek produced a score"
    assert ledger["summary"]["accuracy_pct"] is None
    assert SL.verify(path=ledger_path, snapshot_dir=snaps)["ok"]


def test_the_hash_ignores_key_order_and_float_noise():
    """Two representations of the same predictions must hash the same, or locks break on re-serialisation."""
    a = [{"prob_home": 68.5, "home": "ARS"}, {"prob_home": 40.0, "home": "MCI"}]
    b = [{"home": "ARS", "prob_home": 68.5}, {"home": "MCI", "prob_home": 40.0}]
    c = [{"prob_home": 68.50000000000001, "home": "ARS"}, {"prob_home": 40, "home": "MCI"}]
    assert SL.content_hash(a) == SL.content_hash(b) == SL.content_hash(c)
    d = [{"prob_home": 68.6, "home": "ARS"}, {"prob_home": 40.0, "home": "MCI"}]
    assert SL.content_hash(a) != SL.content_hash(d), "a real change must change the hash"
