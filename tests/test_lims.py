import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lims"))
from registry import _HASH_HEX_LEN, LimsError, Registry  # noqa: E402


@pytest.fixture
def reg():
    return Registry(":memory:")


def test_status_machine_forward_only(reg):
    reg.create_experiment("E1", "test")
    reg.transition("E1", "queued")
    with pytest.raises(LimsError):
        reg.transition("E1", "analyzed")  # skips states
    with pytest.raises(LimsError):
        reg.transition("E1", "registered")  # backwards
    reg.transition("E1", "assigned")


def test_locked_experiment_refuses_mutation(reg):
    reg.create_experiment("E1", "test")
    for s in ("queued", "assigned", "processed", "analyzed", "locked"):
        reg.transition("E1", s)
    reg.register_sample("S1", "rna")
    with pytest.raises(LimsError):
        reg.assign_well("E1", "P1", "A01", "S1")
    with pytest.raises(LimsError):
        reg.attach_result("E1", "q.sf", b"x")


def test_well_conflict_and_unknown_sample(reg):
    reg.create_experiment("E1", "t")
    reg.transition("E1", "queued")
    reg.transition("E1", "assigned")
    reg.register_sample("S1", "rna")
    reg.assign_well("E1", "P1", "A01", "S1")
    reg.register_sample("S2", "rna")
    with pytest.raises(LimsError):
        reg.assign_well("E1", "P1", "A01", "S2")  # occupied
    with pytest.raises(LimsError):
        reg.assign_well("E1", "P1", "A02", "NOPE")  # unregistered
    assert reg.plate_map("E1", "P1") == {"A01": "S1"}


def test_result_stores_content_hash(reg):
    reg.create_experiment("E1", "t")
    rid = reg.attach_result("E1", "quant.sf", b"contents-here")
    row = reg.db.execute(
        "SELECT content_sha256 FROM results WHERE result_id=?",
        (rid,)).fetchone()
    assert len(row["content_sha256"]) == _HASH_HEX_LEN
    assert row["content_sha256"] != b"contents-here"


def test_audit_chain_verifies_and_detects_tamper(reg):
    reg.create_experiment("E1", "t")
    reg.register_sample("S1", "rna")
    reg.transition("E1", "queued")
    assert reg.verify_audit_chain()["ok"]

    reg.db.execute(  # tamper: rewrite history
        "UPDATE audit_log SET action='deleted' WHERE action='register'")
    assert not reg.verify_audit_chain()["ok"]

    reg2 = Registry(":memory:")
    reg2.create_experiment("E1", "t")
    reg2.register_sample("S1", "rna")
    reg2.transition("E1", "queued")
    reg2.db.execute("DELETE FROM audit_log WHERE seq=2")  # mid-chain gap
    assert not reg2.verify_audit_chain()["ok"]


def test_history_traces_entity(reg):
    reg.create_experiment("E1", "t")
    reg.transition("E1", "queued")
    h = reg.history("E1")
    assert [r["action"] for r in h] == ["create", "transition"]


def test_audit_failure_rolls_back_domain_row(reg, monkeypatch):
    def boom(*args, **kwargs):
        raise LimsError("audit write failed")
    monkeypatch.setattr(reg, "_audit", boom)
    with pytest.raises(LimsError):
        reg.register_sample("S1", "rna")
    assert reg.db.execute(
        "SELECT COUNT(*) AS n FROM samples").fetchone()["n"] == 0
    monkeypatch.undo()
    reg.register_sample("S1", "rna")
    assert reg.db.execute(
        "SELECT COUNT(*) AS n FROM samples").fetchone()["n"] == 1


def test_concurrent_writer_blocked_during_attach(tmp_path, monkeypatch):
    p = str(tmp_path / "fixture.sqlite")
    a, b = Registry(p), Registry(p)
    b.db.execute("PRAGMA busy_timeout=0")
    a.create_experiment("E1", "t")
    for s in ("queued", "assigned", "processed", "analyzed"):
        a.transition("E1", s)
    original = a._require_unlocked

    def lock_after_check(experiment_id):
        original(experiment_id)
        with pytest.raises(sqlite3.OperationalError):
            b.transition(experiment_id, "locked")

    monkeypatch.setattr(a, "_require_unlocked", lock_after_check)
    a.attach_result("E1", "late", b"fixture")
    assert a._status("E1") == "analyzed"
    assert a.db.execute(
        "SELECT COUNT(*) FROM results").fetchone()[0] == 1
    monkeypatch.undo()
    a.transition("E1", "locked")
    with pytest.raises(LimsError):
        a.attach_result("E1", "late2", b"x")
    a.db.close()
    b.db.close()


def test_concurrent_writer_blocked_during_assign(tmp_path, monkeypatch):
    p = str(tmp_path / "fixture2.sqlite")
    a, b = Registry(p), Registry(p)
    b.db.execute("PRAGMA busy_timeout=0")
    a.create_experiment("E1", "t")
    for s in ("queued", "assigned", "processed", "analyzed"):
        a.transition("E1", s)
    a.register_sample("S1", "rna")
    original = a._require_unlocked

    def lock_after_check(experiment_id):
        original(experiment_id)
        with pytest.raises(sqlite3.OperationalError):
            b.transition(experiment_id, "locked")

    monkeypatch.setattr(a, "_require_unlocked", lock_after_check)
    a.assign_well("E1", "P1", "A01", "S1")
    assert a.plate_map("E1", "P1") == {"A01": "S1"}
    monkeypatch.undo()
    a.transition("E1", "locked")
    with pytest.raises(LimsError):
        a.assign_well("E1", "P1", "A02", "S1")
    a.db.close()
    b.db.close()


def test_audit_checkpoint_anchors_tail_truncation(reg):
    reg.create_experiment("E1", "t")
    reg.register_sample("S1", "rna")
    cp = reg.audit_checkpoint()
    assert cp["rows"] == 2 and len(cp["head"]) == _HASH_HEX_LEN
    assert reg.verify_audit_chain(
        expected_head=cp["head"], expected_rows=cp["rows"]) == {
        "ok": True, "rows": 2}
    reg.db.execute(
        "DELETE FROM audit_log WHERE seq=(SELECT MAX(seq) FROM audit_log)")
    reg.db.commit()
    assert reg.verify_audit_chain()["ok"]
    anchored = reg.verify_audit_chain(
        expected_head=cp["head"], expected_rows=cp["rows"])
    assert not anchored["ok"] and anchored["reason"] == "head_mismatch"


def test_audit_checkpoint_anchors_whole_log_truncation(reg):
    reg.create_experiment("E1", "t")
    cp = reg.audit_checkpoint()
    reg.db.execute("DELETE FROM audit_log")
    reg.db.commit()
    assert reg.verify_audit_chain() == {"ok": True, "rows": 0}
    anchored = reg.verify_audit_chain(
        expected_head=cp["head"], expected_rows=cp["rows"])
    assert not anchored["ok"] and anchored["reason"] == "head_mismatch"


def test_audit_checkpoint_wrong_row_count_fails(reg):
    reg.create_experiment("E1", "t")
    cp = reg.audit_checkpoint()
    anchored = reg.verify_audit_chain(expected_rows=cp["rows"] + 1)
    assert anchored == {"ok": False, "rows": 1,
                        "reason": "row_count_mismatch"}
