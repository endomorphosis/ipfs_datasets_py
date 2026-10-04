"""Native batch-query integrity, retention bounds, and operation isolation."""

from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
import json
import subprocess
import threading

import pytest

from ipfs_datasets_py.duckdb_control import codebase_verification_catalog as module
from ipfs_datasets_py.duckdb_control.codebase_verification_projection import DOMAIN
from ipfs_datasets_py.duckdb_control.codebase_verification_queries import (
    CodebaseVerificationQueryCursor as Cursor,
    CodebaseVerificationQueryEntry as Entry,
    CodebaseVerificationQueryPage as Page,
    CodebaseVerificationQueryRequest as Request,
    CodebaseVerificationSelector as Selector,
)
from ipfs_datasets_py.logic.software_contracts import codebase_verification as verifier
from ipfs_datasets_py.logic.software_contracts.codebase_ir import StaleCodebaseError
from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_verification.pipeline import ContractSpec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    LeaseCancelledError,
)
from tests.unit.duckdb_control.test_codebase_verification_catalog import prepared, publish  # noqa: F401


def query_many(prepared, requests=None, **kwargs):
    catalog, _, repository, head, _, _, owner, _, _ = prepared
    options = dict(expected_head=head, requests=requests or (Request(Selector()),), scheduler=owner)
    options.update(kwargs)
    return catalog.query_many_current(repository, **options)


def append_projection(prepared, offset=7):
    _, index, repository, head, _, _, owner, _, _ = prepared
    record = verifier.verify_current_codebase_unit(
        index, repository, expected_head=head, path="counter.py",
        contracts=[ContractSpec("increment", postconditions=(f"result == n + {offset}",))],
        scheduler=owner,
    )
    return publish(prepared, verification_cid=record.artifact_cid, operation_id=f"append:{offset}")


def forbid_observation(monkeypatch, prepared):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid batch reached resource admission or source observation")
    monkeypatch.setattr(module, "acquire_codebase_resources", forbidden)
    monkeypatch.setattr(prepared[1], "observe_current", forbidden)


def test_request_round_trip_is_closed_and_detached():
    selector = Selector(path="counter.py", contract_id="contract:increment")
    cid = cid_for_structured({"fixture": "batch cursor"})
    request = Request(selector, 2, Cursor(cid, cid, 1, selector.cid, cid))
    value = json.loads(json.dumps(request.to_dict()))
    assert Request.from_dict(value) == request
    value["selector"]["path"] = "other.py"
    assert request.selector.path == "counter.py"
    assert Request.from_dict(value).selector.path == "other.py"
    for changed in ({**request.to_dict(), "unexpected": True},
                    {**request.to_dict(), "schema": "unrecognized@1"},
                    {key: val for key, val in request.to_dict().items() if key != "cursor"}):
        with pytest.raises(module.CodebaseVerificationCatalogError):
            Request.from_dict(changed)


@pytest.mark.parametrize("page_size", [True, 0, -1, 1.5, "2"])
def test_request_rejects_non_positive_exact_page_size(page_size):
    with pytest.raises(module.CodebaseVerificationCatalogError):
        Request(Selector(), page_size)


@pytest.mark.parametrize("kind", ["empty", "list", "iterator", "tuple_subclass", "too_many", "dict_request"])
def test_batch_shape_bound_is_checked_before_admission(prepared, monkeypatch, kind):
    class TupleSubclass(tuple):
        pass
    request = Request(Selector())
    value = {
        "empty": (), "list": [request], "iterator": iter((request,)),
        "tuple_subclass": TupleSubclass((request,)),
        "too_many": (request,) * (prepared[0].limits.max_query_requests + 1),
        "dict_request": (request.to_dict(),),
    }[kind]
    forbid_observation(monkeypatch, prepared)
    catalog, _, repository, head, _, _, owner, _, _ = prepared
    with pytest.raises(module.CodebaseVerificationCatalogError):
        catalog.query_many_current(repository, expected_head=head, requests=value, scheduler=owner)


@pytest.mark.parametrize("field,value", [
    ("selector", {}), ("cursor", {}), ("page_size", True), ("page_size", 65),
])
def test_mutated_native_request_is_rechecked_before_admission(prepared, monkeypatch, field, value):
    request = Request(Selector())
    object.__setattr__(request, field, value)
    forbid_observation(monkeypatch, prepared)
    with pytest.raises(module.CodebaseVerificationCatalogError):
        query_many(prepared, (request,))


@pytest.mark.parametrize("bound", ["max_query_batch_entries", "max_query_request_bytes"])
def test_aggregate_input_bound_refuses_whole_batch_before_admission(prepared, monkeypatch, bound):
    catalog, index, repository, head, _, _, owner, _, _ = prepared
    requests = (Request(Selector(), 2), Request(Selector(), 2))
    size = 3 if bound == "max_query_batch_entries" else len(canonical_dag_json_bytes([r.to_dict() for r in requests])) - 1
    bounded = module.CodebaseVerificationCatalog(index, limits=replace(catalog.limits, **{bound: size}))
    forbid_observation(monkeypatch, prepared)
    with pytest.raises(module.CodebaseVerificationCatalogError):
        bounded.query_many_current(repository, expected_head=head, requests=requests, scheduler=owner)


@pytest.mark.parametrize("bound", ["max_query_request_bytes", "max_query_response_bytes"])
def test_batch_byte_budget_must_fit_the_admitted_memory(prepared, monkeypatch, bound):
    catalog, index, repository, head, _, _, owner, _, _ = prepared
    bounded = module.CodebaseVerificationCatalog(
        index, limits=replace(catalog.limits, **{bound: 64 * 1024 * 1024 + 1}))
    forbid_observation(monkeypatch, prepared)
    with pytest.raises(module.CodebaseVerificationCatalogError):
        bounded.query_many_current(repository, expected_head=head, requests=(Request(Selector()),),
                                   scheduler=owner, memory_mb=512)


def test_full_batch_shares_one_inventory_replay_and_two_source_observations(prepared, monkeypatch):
    projected = publish(prepared)
    catalog, index, _, _, _, _, owner, _, _ = prepared
    calls = Counter()
    observing = [False]
    for target, name, label in ((catalog, "_resources", "resources"),
                                (catalog._queries, "validate_inventory", "inventory"),
                                (catalog, "_read", "replay"),
                                (index, "observe_current", "source")):
        original = getattr(target, name)
        def counted(*args, _original=original, _label=label, **kwargs):
            calls[_label] += 1
            if _label != "source":
                return _original(*args, **kwargs)
            observing[0] = True
            try:
                return _original(*args, **kwargs)
            finally:
                observing[0] = False
        monkeypatch.setattr(target, name, counted)
    original_transaction = catalog.store._transaction
    @contextmanager
    def counted_transaction():
        # Each source observation separately validates the structural catalog
        # in its own transactions; count only the batched query's transaction.
        if not observing[0]:
            calls["transaction"] += 1
        with original_transaction():
            yield
    monkeypatch.setattr(catalog.store, "_transaction", counted_transaction)
    original_run = subprocess.run
    def git_only(args, *a, **kw):
        assert args[0] == "git", "historical batched queries must not launch a solver"
        return original_run(args, *a, **kw)
    monkeypatch.setattr(subprocess, "run", git_only)
    requests = tuple(Request(Selector(path="counter.py"), 1) for _ in range(32))
    pages = query_many(prepared, requests)
    assert type(pages) is tuple and len(pages) == 32
    assert all(page.entries[0].projection.projection_cid == projected.projection_cid for page in pages)
    assert all(page.entries[0].projection is pages[0].entries[0].projection for page in pages)
    assert calls == Counter(resources=1, inventory=1, replay=1, source=2, transaction=1)
    assert owner.snapshot()["active_lease_count"] == 0
    assert all(not page.entries[0].projection.verification.observed_live for page in pages)
    assert all(not page.to_dict()["authority"]["completion_authority"] for page in pages)


def test_batch_pages_match_independent_native_receipts_and_single_cursor_bytes(prepared):
    projections = (publish(prepared), append_projection(prepared), append_projection(prepared, 9))
    catalog, _, repository, head, _, contract, owner, _, _ = prepared
    selector = Selector(path="counter.py", contract_id=contract.contract_id)
    requests = (Request(selector, 2), Request(Selector(path="absent.py"), 1),
                Request(Selector(verification_cid=projections[1].verification.artifact_cid), 1))
    pages = query_many(prepared, requests)
    entries = tuple(sorted((Entry(cid_for_structured({"projection_cid": p.projection_cid,
        "contract_id": contract.contract_id}), contract.contract_id, p) for p in projections),
        key=lambda entry: entry.entry_id))
    first = pages[0]
    continuation = Cursor(cid_for_structured(head.to_dict()), first.inventory_cid,
                          first.epoch, selector.cid, entries[1].entry_id)
    expected = Page(selector, head, first.inventory_cid, first.epoch, entries[:2], continuation)
    assert canonical_dag_json_bytes(first.to_dict()) == canonical_dag_json_bytes(expected.to_dict())
    assert pages[1].complete and pages[1].entries == ()
    assert pages[2].entries[0].projection.projection_cid == projections[1].projection_cid
    for request, page in zip(requests, pages):
        single = catalog.query_current(repository, expected_head=head, selector=request.selector,
                                       page_size=request.page_size, cursor=request.cursor, scheduler=owner)
        assert canonical_dag_json_bytes(page.to_dict()) == canonical_dag_json_bytes(single.to_dict())
    tail_request = Request(selector, 2, Cursor.from_dict(json.loads(json.dumps(continuation.to_dict()))))
    tail = query_many(prepared, (tail_request,))[0]
    expected_tail = Page(selector, head, first.inventory_cid, first.epoch, entries[2:], start_cursor=continuation)
    assert canonical_dag_json_bytes(tail.to_dict()) == canonical_dag_json_bytes(expected_tail.to_dict())


@pytest.mark.parametrize("mutation", ["delete_entry", "repoint_entry", "delete_dependency", "corrupt_dependency", "delete_record", "corrupt_projection"])
def test_unselected_inventory_corruption_refuses_every_page(prepared, mutation):
    selected = publish(prepared)
    unselected = append_projection(prepared)
    _, index, _, _, _, _, _, connection, _ = prepared
    entry_id = cid_for_structured({"projection_cid": unselected.projection_cid,
                                   "contract_id": prepared[5].contract_id})
    if mutation == "delete_entry":
        connection.execute(f"DELETE FROM {DOMAIN}.entries WHERE entry_id=?", [entry_id])
    elif mutation == "repoint_entry":
        connection.execute(f"UPDATE {DOMAIN}.entries SET path='unselected.py' WHERE entry_id=?", [entry_id])
    elif mutation == "delete_dependency":
        connection.execute(f"DELETE FROM {DOMAIN}.dependencies WHERE entry_id=? AND kind='source'", [entry_id])
    elif mutation == "corrupt_dependency":
        connection.execute(f"UPDATE {DOMAIN}.dependencies SET value='hidden' WHERE entry_id=? AND kind='source'", [entry_id])
    elif mutation == "delete_record":
        connection.execute("DELETE FROM codebase_verification_control.records WHERE projection_cid=?", [unselected.projection_cid])
    else:
        index.artifacts.path_for(unselected.projection_cid).write_bytes(b"{}")
    with pytest.raises((module.CodebaseVerificationCatalogError, ValueError)):
        query_many(prepared, (Request(Selector(verification_cid=selected.verification.artifact_cid)),
                              Request(Selector(path="absent.py"))))


@pytest.mark.parametrize("target", ["verification", "projection", "normalized_dependency"])
def test_next_batch_rechecks_artifacts_and_inventory_without_cross_call_cache(prepared, target):
    projected = publish(prepared)
    requests = (Request(Selector()), Request(Selector(path="counter.py")))
    previous = query_many(prepared, requests)
    assert len(previous) == 2
    if target == "normalized_dependency":
        prepared[7].execute(f"DELETE FROM {DOMAIN}.dependencies WHERE kind='source'")
    else:
        cid = projected.verification.artifact_cid if target == "verification" else projected.projection_cid
        prepared[1].artifacts.path_for(cid).write_bytes(b"{}")
    with pytest.raises((module.CodebaseVerificationCatalogError, ValueError)):
        query_many(prepared, requests)
    # Previously returned immutable historical values retain only their old,
    # non-authoritative receipt; they cannot make the next observation succeed.
    assert previous[0].entries[0].projection.verification.observed_live is False


def test_response_receipts_have_an_independent_aggregate_byte_bound(prepared):
    publish(prepared)
    catalog, index, repository, head, _, _, owner, _, _ = prepared
    request = Request(Selector())
    first = query_many(prepared, (request,))[0]
    encoded_size = len(canonical_dag_json_bytes(first.to_dict()))
    bounded = module.CodebaseVerificationCatalog(index, limits=replace(catalog.limits,
        max_query_response_bytes=encoded_size))
    one = bounded.query_many_current(repository, expected_head=head, requests=(request,), scheduler=owner)
    assert one[0].page_cid == first.page_cid
    with pytest.raises(module.CodebaseVerificationCatalogError, match="[Bb]yte|response|receipt"):
        bounded.query_many_current(repository, expected_head=head, requests=(request, request), scheduler=owner)


def test_shared_projection_counts_once_but_distinct_artifacts_exceed_batch_bound(prepared):
    first = publish(prepared)
    second = append_projection(prepared)
    catalog, index, repository, head, _, _, owner, _, _ = prepared
    artifact_bytes = len(first._payload) + len(first.verification._payload)
    bounded = module.CodebaseVerificationCatalog(index, limits=replace(catalog.limits,
        max_result_bytes=artifact_bytes))
    request = Request(Selector(verification_cid=first.verification.artifact_cid), 1)
    repeated = bounded.query_many_current(repository, expected_head=head, requests=(request,) * 32, scheduler=owner)
    assert len(repeated) == 32
    other = Request(Selector(verification_cid=second.verification.artifact_cid), 1)
    with pytest.raises(module.CodebaseVerificationCatalogError, match="aggregate exact results"):
        bounded.query_many_current(repository, expected_head=head, requests=(request, other), scheduler=owner)


def test_later_invalid_cursor_prevents_return_of_earlier_valid_page(prepared):
    publish(prepared)
    append_projection(prepared)
    first = query_many(prepared, (Request(Selector(), 1),))[0]
    invalid = replace(first.next_cursor, after=cid_for_structured("absent entry"))
    with pytest.raises(module.CodebaseVerificationCatalogError, match="cursor"):
        query_many(prepared, (Request(Selector(path="counter.py")), Request(Selector(), 1, invalid)))
    assert prepared[6].snapshot()["active_lease_count"] == 0
    append_projection(prepared, 9)
    with pytest.raises(module.CodebaseVerificationCatalogError, match="inventory"):
        query_many(prepared, (Request(Selector(path="counter.py")), Request(Selector(), 1, first.next_cursor)))


@pytest.mark.parametrize("race", ["source_edit", "cancel"])
def test_change_during_later_selector_discards_whole_batch_and_drains_owner(prepared, monkeypatch, race):
    publish(prepared)
    catalog, _, repository, _, _, _, owner, connection, _ = prepared
    original = catalog._queries.select_entries
    cancelled = threading.Event()
    calls = []
    before = connection.execute(f"SELECT * FROM {DOMAIN}.inventories").fetchall()
    def race_after_selection(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(1)
        if len(calls) == 2:
            if race == "source_edit":
                with (repository / "counter.py").open("a") as stream:
                    stream.write("# external change during batch\n")
            else:
                cancelled.set()
        return result
    monkeypatch.setattr(catalog._queries, "select_entries", race_after_selection)
    with pytest.raises(StaleCodebaseError if race == "source_edit" else LeaseCancelledError):
        query_many(prepared, (Request(Selector()), Request(Selector(path="counter.py"))), cancel_event=cancelled)
    assert len(calls) == 2
    assert connection.execute(f"SELECT * FROM {DOMAIN}.inventories").fetchall() == before
    state = owner.snapshot()
    assert state["active_lease_count"] == state["waiting_request_count"] == 0


def test_admitted_batch_uses_detached_requests_when_callers_mutate_frozen_objects(prepared, monkeypatch):
    publish(prepared)
    request = Request(Selector(path="counter.py"), 1)
    index = prepared[1]
    observe = index.observe_current
    def mutate_after_admission(*args, **kwargs):
        object.__setattr__(request.selector, "path", "other.py")
        object.__setattr__(request, "page_size", 64)
        return observe(*args, **kwargs)
    monkeypatch.setattr(index, "observe_current", mutate_after_admission)
    page = query_many(prepared, (request,))[0]
    assert page.selector.path == "counter.py" and len(page.entries) == 1
