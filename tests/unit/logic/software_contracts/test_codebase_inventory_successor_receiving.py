"""Real immutable CAS custody with explicitly inert source/model protocols.

These controls verify the new one-operation closer and callback ordering. They
never fit or infer, and are not native lineage or 300-member qualification.
The separately admitted completed-source fixture qualifies those native APIs.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import os
from types import SimpleNamespace
import threading

import pytest

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebasePublicationReceipt, REQUEST_SCHEMA
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_resume as scan
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_receiving as ordinary
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_successor as delta
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_successor_model as successor
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_successor_receiving as receive
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes, cid_for_structured
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import SnapshotEntry
from tests.unit.logic.software_contracts.test_codebase_inventory_resume import (
    completion, page_body, page_record, root_body, root_record,
)
from tests.unit.logic.software_contracts.test_codebase_inventory_resume_lineage import inert_target


def publication(generation, previous=None):
    manifest, snapshot = (cid_for_structured({"inert": name, "generation": generation})
                          for name in ("manifest", "snapshot"))
    repository = "test:successor-paired-protocol"
    return CodebasePublicationReceipt(operation_id=f"inert-{generation}",
        request_cid=cid_for_structured({"schema": REQUEST_SCHEMA, "repository_id": repository,
            "manifest_cid": manifest, "expected_head": previous.to_dict() if previous else None}),
        previous_head=previous, repository_id=repository, generation=generation,
        manifest_cid=manifest, snapshot_cid=snapshot,
        ast_revision_id=f"rev:{repository}:snapshot:{snapshot}")


def protocol(monkeypatch, tmp_path, *, optimized=True, count=3):
    """Genuine typed/CAS chain; native source and checkpoint fences are inert."""
    cas = ImmutableCAS(tmp_path / "source-artifacts", max_object_bytes=16 * 1024 * 1024)
    previous, current = publication(1), publication(2, publication(1).head)
    value = root_body(count, page_entries=32)
    value.update(head=current.head.to_dict(), head_cid=cid_for_structured(current.head.to_dict()),
                 optimized=optimized)
    parent = deepcopy(value["model"])
    parent["version_id"] = parent["ancestry"][0]["version_id"] = "inert-parent"
    value["model"]["version_id"] = value["model"]["ancestry"][0]["version_id"] = "inert-child"
    value["model"]["ancestry"] += deepcopy(parent["ancestry"])
    root = root_record(value)
    cas.put(value)
    pages, prior = [], None
    for offset in range(0, count, 32):
        page = page_record(page_body(root, offset, prior))
        cas.put_bytes(page._payload)
        pages.append(page)
        prior = page.artifact_cid
    complete = completion(root, pages)
    cas.put(complete.to_dict())
    ledger = []
    for member in value["members"]:
        entry = SnapshotEntry(member["path"], "source", member["source_size_bytes"], member["source_cid"])
        side = {"entry": entry.to_dict(), "member": deepcopy(member)}
        ledger.append({"source_key": member["source_key"], "classification": "retained",
            "previous": deepcopy(side), "current": side, "source_bytes_comparison": "equal",
            "ast_identity_comparison": "equal"})
    d = {"schema": delta.SCHEMA, "previous_head": previous.head.to_dict(), "current_head": current.head.to_dict(),
        "previous_publication_receipt": previous.to_dict(), "current_publication_receipt": current.to_dict(),
        "previous_membership_cid": value["membership_cid"], "current_membership_cid": value["membership_cid"],
        "capture_policy": {"max_entries": 1024, "max_file_bytes": 65536, "exclusions": []},
        "ledger": ledger, "coverage": delta._coverage(ledger), "limits": delta.CodebaseSourceDeltaLimits().to_dict(),
        "optimized": optimized, "implementation": deepcopy(value["implementation"]), "authority": dict(scan._FALSE),
        "numerical_reuse": False, "model_advanced": False, "physical_absence_verified": False,
        "removal_scope": "absent_from_current_complete_capture"}
    source_delta = delta.CodebaseSourceDeltaRecord.from_dict(cid_for_structured(d), d)
    cas.put(d)
    s = {"schema": successor.SCHEMA, "source_delta_cid": source_delta.artifact_cid,
        "previous_head": d["previous_head"], "current_head": d["current_head"],
        "previous_membership_cid": d["previous_membership_cid"], "current_membership_cid": d["current_membership_cid"],
        "previous_training_record_cid": cid_for_structured({"inert-training": "parent"}),
        "training_record_cid": cid_for_structured({"inert-training": "child"}),
        "previous_model": parent, "model": value["model"], "root_cid": root.artifact_cid,
        "scan_limits": value["limits"], "optimized": optimized, "implementation": deepcopy(value["implementation"]),
        "authority": dict(scan._FALSE), **{name: False for name in successor._FALSE}}
    selection = successor.CodebaseSuccessorScanRecord.from_dict(cid_for_structured(s), s)
    cas.put(s)
    store = SimpleNamespace(_connection=object(), _lock=object())
    index = SimpleNamespace(artifacts=cas, ingestor=SimpleNamespace(store=store),
        catalog=SimpleNamespace(_database_path=tmp_path / "source.duckdb", _pid=os.getpid()), load=lambda _: object())
    registry = SimpleNamespace(database_path=tmp_path / "model.duckdb", artifact_root=tmp_path / "model-artifacts",
        _manager=object(), _lock=object(), _pid=os.getpid(), owner_generation=2, _closed=False)
    registry.database_path.write_bytes(b"inert-model-owner")
    registry.artifact_root.mkdir()
    registry._owner_file = registry.database_path.with_name("model.duckdb.owner.lock").open("a+b")
    target = inert_target()
    chain = [({"version_id": name}, {"state": {"weights": [1]}}, {"head": head.to_dict()},
        [target], [target], [target], [target]) for name, head in (("child", current.head), ("parent", previous.head))]
    baseline = b"exact-inert-registry-generation-two"
    calls = {"entry": 0, "replay": [], "history": 0, "source": 0, "model": 0, "exit": 0,
             "reference_selection": 0, "reference_completion": 0, "scopes": []}
    control = SimpleNamespace(error=None, history_hook=None, source_hook=None, model_hook=None, exit_hook=None)
    lease, signal = SimpleNamespace(released=False), threading.Event()
    def remaining():
        if control.error is not None:
            raise control.error
        return 30.0
    @contextmanager
    def scope(*args, **kwargs):
        calls["scopes"].append(kwargs)
        try:
            remaining()
            yield lease, signal, remaining
            remaining()
        finally:
            lease.released = True
    def entry(*args):
        calls["entry"] += 1
        return object(), object(), chain, baseline
    def replay(*args):
        calls["replay"].append(args[5].artifact_cid)
    def phase(name):
        def run(*args, **kwargs):
            calls[name] += 1
            hook = getattr(control, name + "_hook")
            if hook is not None:
                hook()
            return source_delta.to_dict() if name == "source" else None
        return run
    def reference(name):
        def run(actual, *args, **kwargs):
            calls[name] += 1
            assert kwargs["parent_lease"] is lease and kwargs["cancel_event"] is signal
            assert 0 < kwargs["timeout_seconds"] <= 30
            return actual
        return run
    monkeypatch.setattr(scan, "_scope", scope)
    monkeypatch.setattr(receive, "_entry_successor", entry)
    monkeypatch.setattr(scan, "_replay_page", replay)
    monkeypatch.setattr(scan, "_history_fence", phase("history"))
    # These targets are explicitly inert. Preserve the historical callback
    # branch with a typed extra head; native target binding is not tested here.
    monkeypatch.setattr(scan.legacy, "_history_heads", lambda unused:
        (previous.head, current.head, publication(3, current.head).head))
    monkeypatch.setattr(scan, "_owners", lambda *args: None)
    monkeypatch.setattr(scan, "_implementation", lambda: value["implementation"])
    monkeypatch.setattr(scan.legacy, "_registry_inventory", lambda *args: baseline)
    monkeypatch.setattr(scan.legacy, "_model_fence", phase("model"))
    monkeypatch.setattr(delta, "_receive", lambda *args: None)
    monkeypatch.setattr(delta, "_observe", phase("source"))
    monkeypatch.setattr(successor, "_implementation", lambda: s["implementation"])
    monkeypatch.setattr(successor, "_source_exit", phase("exit"))
    monkeypatch.setattr(receive, "_selection_binding", lambda *args: None)
    monkeypatch.setattr(successor, "validate_current_codebase_successor_scan", reference("reference_selection"))
    monkeypatch.setattr(scan, "validate_current_codebase_scan_completion", reference("reference_completion"))
    return SimpleNamespace(cas=cas, root=root, pages=pages, completion=complete, selection=selection,
        delta=source_delta, index=index, registry=registry, chain=chain, lease=lease, signal=signal,
        control=control, calls=calls)


def paired(fixture, **kwargs):
    return receive._paired_current_codebase_successor_completion(fixture.selection, fixture.completion,
        fixture.index, ".", root=fixture.root, registry=fixture.registry, **kwargs)


def test_default_full_entry_and_byte_only_closer_cover_257_members(monkeypatch, tmp_path):
    f = protocol(monkeypatch, tmp_path, count=257)
    with paired(f, parent_lease="outer", timeout_seconds=45) as close:
        assert f.calls["replay"] == [page.artifact_cid for page in f.pages]
        assert f.calls["source"] == f.calls["model"] == f.calls["exit"] == 1
        assert close() is f.completion
        assert len(f.calls["replay"]) == 9
    assert f.calls["entry"] == 1 and f.calls["source"] == f.calls["model"] == f.calls["exit"] == 2
    assert f.lease.released and f.calls["reference_completion"] == 0
    assert f.calls["scopes"][0]["parent_lease"] == "outer"
    assert f.calls["scopes"][0]["timeout_seconds"] == 45


def test_default_closes_structural_delta_after_pages_without_earlier_duplicate_receiver(monkeypatch, tmp_path):
    f = protocol(monkeypatch, tmp_path)
    def duplicate(*args, **kwargs):
        pytest.fail("optimized operation repeated the earlier public delta receiver")
    monkeypatch.setattr(delta, "_receive", duplicate)
    def source_observation():
        assert f.calls["replay"] == [page.artifact_cid for page in f.pages]
    f.control.source_hook = source_observation
    with paired(f) as close:
        assert f.calls["source"] == 1
        close()
    assert f.calls["source"] == f.calls["exit"] == 2


def test_optout_preserves_both_public_receivers_twice(monkeypatch, tmp_path):
    f = protocol(monkeypatch, tmp_path, optimized=False)
    with paired(f) as close:
        assert close() is f.completion
    assert f.calls["reference_selection"] == f.calls["reference_completion"] == 2
    assert f.calls["entry"] == f.calls["source"] == f.calls["model"] == 0 and not f.calls["replay"]


def test_complete_delta_heads_avoid_only_duplicate_closing_history(monkeypatch, tmp_path):
    f = protocol(monkeypatch, tmp_path)
    value = f.delta.to_dict()
    heads = tuple(scan._head(value[name]) for name in ("previous_head", "current_head"))
    monkeypatch.setattr(scan.legacy, "_history_heads", lambda chain: heads)
    with paired(f) as close:
        assert f.calls["history"] == 0 and f.calls["source"] == 1
        close()
    assert f.calls["history"] == 0 and f.calls["source"] == f.calls["model"] == f.calls["exit"] == 2


def test_other_ancestral_replay_head_keeps_full_historical_fence(monkeypatch, tmp_path):
    f = protocol(monkeypatch, tmp_path)
    value = f.delta.to_dict()
    current = scan._head(value["current_head"])
    heads = tuple(scan._head(value[name]) for name in ("previous_head", "current_head")) + (publication(3, current).head,)
    monkeypatch.setattr(scan.legacy, "_history_heads", lambda chain: heads)
    with paired(f) as close:
        assert f.calls["history"] == f.calls["source"] == 1
        close()
    assert f.calls["history"] == f.calls["source"] == 2


@pytest.mark.parametrize("failure", ["unused", "duplicate", "expired", "thread", "cancel", "deadline", "released"])
def test_one_operation_closer_lifetime_and_shared_expiry(monkeypatch, tmp_path, failure):
    f = protocol(monkeypatch, tmp_path)
    if failure == "expired":
        with paired(f) as close:
            close()
        with pytest.raises(scan.CodebaseScanResumeError, match="inactive"):
            close()
    elif failure == "thread":
        errors = []
        with pytest.raises(scan.CodebaseScanResumeError, match="not completed"):
            with paired(f) as close:
                def other():
                    try:
                        close()
                    except BaseException as error:
                        errors.append(error)
                thread = threading.Thread(target=other)
                thread.start()
                thread.join()
        assert len(errors) == 1 and "ownership" in str(errors[0])
    else:
        with pytest.raises((RuntimeError, scan.CodebaseScanResumeError)):
            with paired(f) as close:
                if failure == "unused":
                    pass
                elif failure == "duplicate":
                    close()
                    close()
                else:
                    if failure == "released":
                        f.lease.released = True
                    else:
                        f.control.error = RuntimeError(failure)
                    close()
    assert f.lease.released


@pytest.mark.parametrize("phase", ["before", "after"])
def test_exception_cleanup_performs_no_native_replay(monkeypatch, tmp_path, phase):
    f = protocol(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match="caller"):
        with paired(f) as close:
            if phase == "after":
                close()
            f.control.source_hook = lambda: pytest.fail("cleanup replayed native source")
            raise RuntimeError("caller")
    assert f.calls["source"] == (2 if phase == "after" else 1) and f.lease.released


@pytest.mark.parametrize("record", ["selection", "delta", "root", "completion", "page"])
def test_late_durable_cas_changes_refuse(monkeypatch, tmp_path, record):
    f = protocol(monkeypatch, tmp_path)
    actual = f.pages[0] if record == "page" else getattr(f, record)
    with pytest.raises(ValueError):
        with paired(f) as close:
            f.cas.path_for(actual.artifact_cid, source=record == "page").write_bytes(b"corrupt")
            close()
    assert f.lease.released


@pytest.mark.parametrize("record", ["selection", "delta", "root", "completion", "page"])
def test_final_model_callback_cannot_mutate_already_read_cas(monkeypatch, tmp_path, record):
    f = protocol(monkeypatch, tmp_path)
    actual = f.pages[0] if record == "page" else getattr(f, record)
    with pytest.raises(scan.CodebaseScanResumeError, match="CAS"):
        with paired(f) as close:
            f.control.model_hook = lambda: f.cas.path_for(actual.artifact_cid,
                source=record == "page").write_bytes(b"late callback corruption")
            close()
    assert f.calls["exit"] == 1 and f.lease.released


@pytest.mark.parametrize("alias", ["symlink", "hardlink"])
def test_direct_streaming_custody_rejects_aliases(monkeypatch, tmp_path, alias):
    f = protocol(monkeypatch, tmp_path)
    with pytest.raises((OSError, scan.CodebaseScanResumeError)):
        with paired(f) as close:
            path = f.cas.path_for(f.pages[0].artifact_cid, source=True)
            other = tmp_path / "alias"
            other.write_bytes(path.read_bytes())
            path.unlink()
            if alias == "symlink":
                path.symlink_to(other)
            else:
                path.hardlink_to(other)
            close()
    assert f.lease.released


@pytest.mark.parametrize("part", ["row", "saved", "target", "baseline", "generation", "manager", "producer"])
def test_private_native_snapshots_and_owners_remain_bound(monkeypatch, tmp_path, part):
    f = protocol(monkeypatch, tmp_path)
    with pytest.raises(scan.CodebaseScanResumeError):
        with paired(f) as close:
            if part == "row":
                f.chain[0][0]["version_id"] = "forged"
            elif part == "saved":
                f.chain[0][1]["state"]["weights"].append(2)
            elif part == "target":
                object.__setattr__(f.chain[0][3][0], "canonical_bytes", inert_target(2).canonical_bytes)
            elif part == "baseline":
                dict(zip(close.__code__.co_freevars, close.__closure__))["before"].cell_contents = b"forged-owner"
            elif part == "generation":
                f.registry.owner_generation += 1
            elif part == "manager":
                f.registry._manager = object()
            else:
                monkeypatch.setattr(receive, "_pins", lambda: "forged-source-generation")
            close()
    assert f.lease.released


def test_final_source_fence_runs_after_model_callback(monkeypatch, tmp_path):
    f = protocol(monkeypatch, tmp_path)
    order = []
    with pytest.raises(RuntimeError, match="fresh source drift"):
        with paired(f) as close:
            f.control.model_hook = lambda: order.append("changed checkout")
            def final_source():
                assert order == ["changed checkout"]
                raise RuntimeError("fresh source drift")
            f.control.exit_hook = final_source
            close()
    assert f.calls["model"] == f.calls["exit"] == 2 and f.lease.released


def test_streaming_custody_checks_each_entry_validated_digest_and_cancellation(tmp_path):
    cas = ImmutableCAS(tmp_path / "cas")
    raw = b"x" * 200000
    cid = cas.put_bytes(raw)
    guard = (True, (cid, len(raw), hashlib.sha256(raw).hexdigest()))
    calls = []
    receive._direct_cas_guards(cas, (guard,), lambda: calls.append(True))
    assert len(calls) >= 5
    with pytest.raises(scan.CodebaseScanResumeError, match="bytes changed"):
        receive._direct_cas_guards(cas, ((True, (cid, len(raw), "0" * 64)),), lambda: None)
    def cancel():
        raise RuntimeError("cancelled streaming read")
    with pytest.raises(RuntimeError, match="cancelled"):
        receive._direct_cas_guards(cas, (guard,), cancel)
