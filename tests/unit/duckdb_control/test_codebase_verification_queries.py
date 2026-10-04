"""Public query contracts and complete traversal beyond the legacy result cap."""

from dataclasses import replace
import json
import threading
import time

import pytest

from ipfs_datasets_py.duckdb_control.codebase_verification_catalog import CodebaseVerificationCatalogError
from ipfs_datasets_py.duckdb_control.codebase_verification_queries import (
    CodebaseVerificationSelector as Selector,
    CodebaseVerificationQueryCursor as Cursor,
    CodebaseVerificationQueryEntry as Entry,
    CodebaseVerificationQueryPage as Page,
)
from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
from ipfs_datasets_py.logic.software_contracts import codebase_verification as verifier
from ipfs_datasets_py.logic.software_verification.pipeline import ContractSpec
from tests.unit.duckdb_control.test_codebase_verification_catalog import prepared, publish  # noqa: F401


@pytest.mark.parametrize("kwargs", [
    {"path": "../outside.py"}, {"path": "/absolute.py"}, {"path": "./file.py"},
    {"path": "a//file.py"}, {"path": "a\\file.py"}, {"path": "file.txt"},
    {"path": "x" * 2048 + ".py"}, {"contract_id": True}, {"contract_id": ""},
    {"requested_domain_id": " leading"}, {"expected_contract_cid": "invented"},
    {"verification_cid": "invented"}, {"requested_domain_cid": "invented"},
    {"canonical_key_id": "canonical-proof-cache-key:sha256:" + "f" * 63},
    {"canonical_key_id": "x" * 100000}, {"dependency_kind": "source"},
    {"dependency_value": "invented"}, {"dependency_kind": "invented", "dependency_value": "x"},
])
def test_exact_selector_rejects_malformed_or_unbounded_inputs(kwargs):
    with pytest.raises((TypeError, ValueError)):
        Selector(**kwargs)


def test_selector_and_cursor_detached_closed_serialization():
    selector = Selector(path="a.py", contract_id="contract:a")
    assert Selector.from_dict(json.loads(json.dumps(selector.to_dict()))) == selector
    changed = selector.to_dict()
    changed["path"] = "b.py"
    assert selector.path == "a.py" and Selector.from_dict(changed).cid != selector.cid
    with pytest.raises(CodebaseVerificationCatalogError):
        Selector.from_dict({**selector.to_dict(), "extra": True})
    cid = cid_for_structured({"test": "cursor"})
    cursor = Cursor(cid, cid, 1, selector.cid, cid)
    assert Cursor.from_dict(json.loads(json.dumps(cursor.to_dict()))) == cursor
    for value in (True, 0, -1, 2**63, 1.5):
        with pytest.raises(CodebaseVerificationCatalogError):
            replace(cursor, epoch=value)
    with pytest.raises(CodebaseVerificationCatalogError):
        Cursor.from_dict({**cursor.to_dict(), "schema": "other@1"})


def query(prepared, **kwargs):
    catalog, _, repository, head, _, _, owner, _, _ = prepared
    options = dict(expected_head=head, selector=Selector(), scheduler=owner)
    options.update(kwargs)
    return catalog.query_current(repository, **options)


def test_native_entry_page_receipts_bind_exact_selector_head_and_cursor(prepared):
    projection = publish(prepared)
    page = query(prepared)
    assert type(page) is Page and page.complete and page.next_cursor is None
    assert len(page.entries) == 1
    row = page.entries[0]
    assert row.projection.projection_cid == projection.projection_cid
    receipt = page.to_dict()
    assert receipt.pop("page_cid") == cid_for_structured(receipt)
    receipt["authority"]["kernel_checked"] = True
    assert page.to_dict()["authority"]["kernel_checked"] is False
    with pytest.raises(CodebaseVerificationCatalogError, match="bind"):
        Entry(cid_for_structured("wrong"), row.contract_id, projection)
    with pytest.raises(CodebaseVerificationCatalogError, match="selector"):
        replace(page, selector=Selector(path="other.py"))
    with pytest.raises(CodebaseVerificationCatalogError, match="unique and ordered"):
        replace(page, entries=(row, row))
    cursor = Cursor(cid_for_structured(page.head.to_dict()), page.inventory_cid,
                    page.epoch, page.selector.cid, row.entry_id)
    assert replace(page, next_cursor=cursor).complete is False
    with pytest.raises(CodebaseVerificationCatalogError, match="continuation"):
        replace(page, next_cursor=replace(cursor, epoch=page.epoch + 1))
    # Frozen types can still be deliberately mutated through object.__setattr__;
    # serialization rechecks native bindings before a consumer hashes a receipt.
    changed = replace(page)
    object.__setattr__(changed, "selector", Selector(path="wrong.py"))
    with pytest.raises(CodebaseVerificationCatalogError, match="selector"):
        changed.to_dict()


def test_seventeen_native_projections_traverse_without_legacy_candidate_limit(prepared):
    catalog, index, repository, head, _, contract, owner, _, _ = prepared
    expected = set()
    for offset in range(17):
        record = verifier.verify_current_codebase_unit(index, repository, expected_head=head,
            path="counter.py", contracts=[ContractSpec("increment", postconditions=(f"result == n + {offset}",))],
            scheduler=owner)
        projection = publish(prepared, verification_cid=record.artifact_cid, operation_id=f"many:{offset}")
        expected.add(projection.projection_cid)
    cursor = None
    seen = []
    first = None
    while True:
        page = query(prepared, selector=Selector(path="counter.py", contract_id=contract.contract_id),
                     page_size=4, cursor=cursor)
        assert page.start_cursor == cursor
        if first is None:
            first = page
        assert len(page.entries) <= 4
        seen.extend(page.entries)
        if page.complete:
            break
        cursor = Cursor.from_dict(json.loads(json.dumps(page.next_cursor.to_dict())))
    assert len(seen) == 17
    assert [e.entry_id for e in seen] == sorted({e.entry_id for e in seen})
    assert {e.projection.projection_cid for e in seen} == expected
    with pytest.raises(CodebaseVerificationCatalogError, match="result limit|inventory"):
        catalog.lookup_current(repository, expected_head=head, path="counter.py",
            contract_id=contract.contract_id, scheduler=owner)
    with pytest.raises(CodebaseVerificationCatalogError):
        query(prepared, selector=Selector(path="other.py"), cursor=first.next_cursor)
    with pytest.raises(CodebaseVerificationCatalogError):
        query(prepared, selector=first.selector,
              cursor=replace(first.next_cursor, after=cid_for_structured("invented marker")))


@pytest.mark.parametrize("page_size", [True, 0, -1, 65, 1.5, "2"])
def test_query_page_bound_rejects_before_source_observation(prepared, monkeypatch, page_size):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid page size reached repository observation")
    monkeypatch.setattr(prepared[1], "observe_current", forbidden)
    with pytest.raises(CodebaseVerificationCatalogError):
        query(prepared, page_size=page_size)


def test_exact_operation_replay_does_not_invalidate_a_continuation(prepared):
    catalog, index, repository, head, _, _, owner, _, _ = prepared
    publish(prepared)
    other = verifier.verify_current_codebase_unit(index, repository, expected_head=head,
        path="counter.py", contracts=[ContractSpec("increment", postconditions=("result == n + 8",))],
        scheduler=owner)
    publish(prepared, operation_id="other", verification_cid=other.artifact_cid)
    page = query(prepared, page_size=1)
    assert not page.complete
    publish(prepared)
    tail = query(prepared, page_size=1, cursor=page.next_cursor)
    assert tail.complete and tail.epoch == page.epoch and tail.inventory_cid == page.inventory_cid
    assert tail.start_cursor == page.next_cursor
    assert tail.entries[0].entry_id != page.entries[0].entry_id


@pytest.mark.parametrize("pressure,reason", [
    ({"available_memory_mb": 100}, "proof_memory_headroom"),
    ({"cpu_stall_percent": 75}, "proof_cpu_stall"),
    ({"memory_stall_percent": 5}, "proof_memory_stall"),
    ({"io_stall_percent": 20}, "proof_io_stall"),
])
def test_default_query_backs_off_external_pressure_and_recovers_on_owner_thread(
        prepared, monkeypatch, pressure, reason):
    from ipfs_datasets_py.logic.software_contracts import codebase_resources as resources
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
        GlobalResourceScheduler, ResourceSchedulerConfig,
    )
    publish(prepared)
    healthy = ProofHostResources(8, 8192, 8192)
    current = [replace(healthy, **pressure)]
    owner = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=prepared[-1] / "query-pressure.json", proof_resource_sampler=lambda: current[0],
        lane_reservations={}, auto_renew_leases=False, proof_backoff_seconds=0.02,
        poll_interval_seconds=0.005))
    monkeypatch.setattr(resources, "get_global_resource_scheduler", lambda: owner)
    backoff = []
    def relieve_external_pressure():
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = owner.snapshot()
            if state["proof_backoff"]:
                backoff.append(state["proof_backoff"]["reason"])
                current[0] = healthy
                return
            time.sleep(0.005)
    monitor = threading.Thread(target=relieve_external_pressure)
    monitor.start()
    try:
        # The DuckDB owner stays on this thread. Only external host pressure is
        # changed by the monitor; no connection or cursor crosses threads.
        page = query(prepared, scheduler=None, timeout_seconds=3, admission_timeout_seconds=2)
        assert page.complete and len(page.entries) == 1
    finally:
        current[0] = healthy
        monitor.join(3)
    assert backoff == [reason] and not monitor.is_alive()
    state = owner.snapshot()
    assert state["active_lease_count"] == state["waiting_request_count"] == 0


@pytest.mark.parametrize("cancel", [False, True])
def test_default_query_pressure_timeout_or_cancellation_never_observes_source(prepared, monkeypatch, cancel):
    from ipfs_datasets_py.logic.software_contracts import codebase_resources as resources
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
        GlobalResourceScheduler, ResourceSchedulerConfig, LeaseCancelledError, LeaseTimeoutError,
    )
    publish(prepared)
    owner = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=prepared[-1] / "query-pressure.json",
        proof_resource_sampler=lambda: ProofHostResources(8, 8192, 8192, memory_stall_percent=10),
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=0.005))
    monkeypatch.setattr(resources, "get_global_resource_scheduler", lambda: owner)
    def forbidden(*args, **kwargs):
        pytest.fail("unadmitted query reached source observation")
    monkeypatch.setattr(prepared[1], "observe_current", forbidden)
    event = threading.Event()
    if cancel:
        event.set()
    with pytest.raises(LeaseCancelledError if cancel else LeaseTimeoutError):
        query(prepared, scheduler=None, cancel_event=event, timeout_seconds=0.03,
              admission_timeout_seconds=1)
    state = owner.snapshot()
    assert state["active_lease_count"] == state["waiting_request_count"] == 0
