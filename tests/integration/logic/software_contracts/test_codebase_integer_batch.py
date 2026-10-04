"""Native joined owner, bounded workers and durable historical evidence index."""
from dataclasses import replace
import shutil
import sys
import threading

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_integer_profile as profile
from ipfs_datasets_py.logic.software_contracts.codebase_integer_verification import CodebaseIntegerVerifier, CodebaseVerificationError
from ipfs_datasets_py.logic.software_contracts.codebase_ir import StaleCodebaseError
from ipfs_datasets_py.logic.software_contracts.codebase_property_cache import CodebasePropertyCache
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError, LeaseTimeoutError
from .test_codebase_current import repository, scheduler, current_index, publish, change

NATIVE = pytest.mark.skipif(not sys.platform.startswith("linux") or not shutil.which("z3") or not shutil.which("cvc5"),
                           reason="native Linux Z3 and CVC5 required")


def contract(offset=1, path="counter.py", function="increment"):
    return profile.IntegerOffsetContract(path, function, "n", offset)


@pytest.fixture
def prepared(repository, scheduler, current_index, tmp_path):
    owner, _, _ = scheduler
    index, _, _ = current_index
    head = publish(index, repository, owner, "initial").head
    verifier = CodebaseIntegerVerifier(index, CodebasePropertyCache(tmp_path / "properties"))
    return verifier, head


@NATIVE
def test_real_parallel_checks_owner_thread_and_exact_duplicate_join(prepared, repository, scheduler, monkeypatch):
    from ipfs_datasets_py.duckdb_control.codebase_evidence_index import CodebaseEvidenceIndex
    verifier, head = prepared
    owner, _, _ = scheduler
    main_thread = threading.get_ident()
    for target, names in ((verifier.index, ("observe_current",)),
                          (verifier.index.artifacts, ("get_bytes", "put", "get")),
                          (verifier.cache, ("put", "lookup")),
                          (verifier.index.catalog, ("current",))):
        for name in names:
            original = getattr(target, name)
            def checked(*args, _original=original, **kwargs):
                assert threading.get_ident() == main_thread, "worker touched an owner object"
                return _original(*args, **kwargs)
            monkeypatch.setattr(target, name, checked)
    active, peak = 0, 0
    lock = threading.Lock()
    native = profile.run_bounded_stdin_tool
    def counted(*args, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            return native(*args, **kwargs)
        finally:
            with lock:
                active -= 1
    monkeypatch.setattr(profile, "run_bounded_stdin_tool", counted)
    result = verifier.verify_many(repository, expected_head=head, contracts=[contract(), contract(2), contract()],
                                  scheduler=owner, max_workers=2)
    assert [row["status"] for row in result["results"]] == ["proved", "refuted", "proved"]
    assert result["max_workers"] == result["unique_contracts"] == result["solver_jobs"] == 2
    assert result["memory_mb"] == 1536
    assert result["results"][0] == result["results"][2]
    result["results"][2]["diagnostics"].append("caller mutation")
    assert result["results"][0]["diagnostics"] == []
    assert 1 < peak <= 2
    assert active == 0
    historical = CodebaseEvidenceIndex(verifier.index.catalog)
    for row in result["results"][:2]:
        record = historical.get(row["receipt_cid"], expected_head=head)
        assert record is not None
        assert verifier.index.artifacts.get(row["compiled_cid"])["source_cid"] == row["source_cid"]
    sealed = verifier.index.artifacts.get(result["receipt_cid"])
    assert sealed["evidence_receipt_cids"] == result["evidence_receipt_cids"]
    assert sealed["behavior_authority"] is sealed["completion_authority"] is False


@NATIVE
def test_repeat_rechecks_cache_and_indexes_current_generation(prepared, repository, scheduler):
    from ipfs_datasets_py.duckdb_control.codebase_evidence_index import CodebaseEvidenceIndex, CodebaseEvidenceIndexError
    verifier, head = prepared
    owner, _, _ = scheduler
    first = verifier.verify_many(repository, expected_head=head, contracts=[contract(), contract(2)], scheduler=owner)
    second = verifier.verify_many(repository, expected_head=head, contracts=[contract(), contract(2)], scheduler=owner)
    assert first["cache_history_hits"] == 0 and second["cache_history_hits"] == 2
    assert all(row["solver_replayed"] for row in second["results"])
    change(repository, 2)
    with pytest.raises(StaleCodebaseError):
        verifier.verify_many(repository, expected_head=head, contracts=[contract()], scheduler=owner)
    successor = publish(verifier.index, repository, owner, "edit", head).head
    current = verifier.verify_many(repository, expected_head=successor, contracts=[contract(2)], scheduler=owner)
    assert current["results"][0]["status"] == "proved" and current["cache_history_hits"] == 0
    index = CodebaseEvidenceIndex(verifier.index.catalog)
    with pytest.raises(CodebaseEvidenceIndexError, match="different snapshot"):
        index.lookup(first["results"][0]["cache_binding"], expected_head=successor)


def test_unsupported_and_absent_contracts_keep_complete_inventory(prepared, repository, scheduler):
    verifier, head = prepared
    owner, _, _ = scheduler
    result = verifier.verify_many(repository, expected_head=head,
        contracts=[contract(path="other.py", function="unchanged"), contract(path="absent.py")], scheduler=owner)
    assert [row["status"] for row in result["results"]] == ["unsupported", "unsupported"]
    assert not any(row["solver_check_attempted"] for row in result["results"])
    assert result["evidence_receipt_cids"] == []


@NATIVE
@pytest.mark.parametrize("stage", ["worker", "receipt", "publication"])
def test_source_drift_withholds_joined_batch(prepared, repository, scheduler, monkeypatch, stage):
    from ipfs_datasets_py.duckdb_control.codebase_evidence_index import CodebaseEvidenceIndex
    from ipfs_datasets_py.logic.software_contracts import codebase_integer_workers as workers
    verifier, head = prepared
    owner, _, _ = scheduler
    if stage == "worker":
        original = workers.run_integer_checks
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            change(repository, 2)
            return result
        monkeypatch.setattr(workers, "run_integer_checks", changed)
    elif stage == "receipt":
        original = verifier.index.artifacts.put
        def changed(value):
            cid = original(value)
            if value.get("schema") == "codebase-integer-batch@1":
                change(repository, 2)
            return cid
        monkeypatch.setattr(verifier.index.artifacts, "put", changed)
    else:
        original = CodebaseEvidenceIndex.publish_many
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            change(repository, 2)
            return result
        monkeypatch.setattr(CodebaseEvidenceIndex, "publish_many", changed)
    with pytest.raises(StaleCodebaseError):
        verifier.verify_many(repository, expected_head=head, contracts=[contract(), contract(2)], scheduler=owner)


def test_pressure_refuses_batch_before_source_reads(prepared, repository, scheduler, monkeypatch):
    verifier, head = prepared
    owner, pressure, healthy = scheduler
    pressure[0] = replace(healthy, memory_stall_percent=10)
    monkeypatch.setattr(verifier.index, "observe_current", lambda *a, **kw: pytest.fail("source read under pressure"))
    with pytest.raises(LeaseTimeoutError):
        verifier.verify_many(repository, expected_head=head, contracts=[contract()], scheduler=owner,
                             admission_timeout_seconds=0.03)


@NATIVE
def test_parent_budget_caps_width_and_is_retained(prepared, repository, scheduler):
    verifier, head = prepared
    owner, _, _ = scheduler
    with owner.acquire("orchestration", cpu_slots=2, child_process_slots=2, memory_mb=1536, timeout=0) as parent:
        result = verifier.verify_many(repository, expected_head=head, contracts=[contract(), contract(2), contract(3)],
                                      parent_lease=parent, max_workers=4)
        assert result["max_workers"] == 2 and result["memory_mb"] == 1536
        assert owner.snapshot()["active_lease_count"] == 1 and not parent.released


@pytest.mark.parametrize("controls", [
    {"contracts": []}, {"contracts": [contract()] * 65}, {"max_workers": True},
    {"max_workers": 33}, {"memory_mb": 512}, {"timeout_seconds": float("inf")},
])
def test_invalid_controls_reject_before_source_reads(prepared, repository, scheduler, monkeypatch, controls):
    verifier, head = prepared
    owner, _, _ = scheduler
    monkeypatch.setattr(verifier.index, "observe_current", lambda *a, **kw: pytest.fail("invalid input reached source"))
    arguments = {"contracts": [contract()], **controls}
    with pytest.raises((CodebaseVerificationError, ValueError)):
        verifier.verify_many(repository, expected_head=head, scheduler=owner, **arguments)


def test_cancelled_batch_leaves_no_waiters_or_partial_result(prepared, repository, scheduler):
    verifier, head = prepared
    owner, _, _ = scheduler
    event = threading.Event()
    event.set()
    with pytest.raises(LeaseCancelledError):
        verifier.verify_many(repository, expected_head=head, contracts=[contract()], scheduler=owner, cancel_event=event)
