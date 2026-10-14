"""Real temporary catalog owner and opt-in private native endpoint contracts.

Fixtures are synthetic source identities and never qualify laws or models.
No active catalog is opened. Native tests require the isolated-storage opt-in.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import time
import threading

import pytest

from ipfs_datasets_py.duckdb_control import span_cache_claims_quack as transport
from ipfs_datasets_py.duckdb_control.autoencoder_quack import RegistryTransportError
from ipfs_datasets_py.duckdb_control.span_cache_claims_quack import (
    CLAIM, COMPLETE, READ, RELEASE, RESOLVE, SpanClaimWorkerScope,
    SpanClaimsQuackGateway, SpanClaimsTransportClient, _envelope,
)
from ipfs_datasets_py.duckdb_control.span_cache_quack import SpanCacheQuackError
from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache

REVISION = "hub:" + "a" * 40
TEXT = "The agency shall not disclose records."
SOURCE_SHA = hashlib.sha256(TEXT.encode()).hexdigest()
PATH_HASHES = {"ipfs_datasets_py/logic/legal_ir/canonical_compiler.py": "b" * 64}
NATIVE = pytest.mark.skipif(
    os.environ.get("IPFS_DATASETS_RUN_NATIVE_STORAGE_PROBE") != "1",
    reason="private native Quack endpoint tests require explicit isolated-storage opt-in",
)


def binding():
    return {"source_span_id": "span-a", "source_revision": REVISION,
            "source_sha256": SOURCE_SHA, "expected_binding": None}


def completion(claim):
    return {"rows": [{"claim": claim, "agrees": False, "decompiled": "",
                      "rule": {}, "repair": {}, "reason": "fixture compiler abstained"}],
            "code_identity": "fixture-compiler", "path_hashes": PATH_HASHES}


@pytest.fixture
def owner(tmp_path: Path):
    cache = SpanCache(tmp_path / "private-span-owner.duckdb")
    cache.enqueue([{"source_span_id": "span-a", "text": TEXT, "legal_id": "usc:us:5:552"},
                   {"source_span_id": "span-b", "text": TEXT, "legal_id": "usc:us:5:553"}])
    now = [100.0]
    claims = cache.fenced_claims(clock=lambda: now[0])
    gateway = SpanClaimsQuackGateway(cache, SpanClaimWorkerScope("worker-a", {"span-a"}),
                                    enable_prototype=True)
    try:
        yield cache, gateway, claims, now
    finally:
        gateway.close()
        cache.close()


def local_request(gateway, command, payload, operation_id):
    """Dispatch on worker thread, serve exclusively on original owner thread."""
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(gateway.dispatch, _envelope(command, payload, operation_id))
        deadline = time.monotonic() + 5
        while not future.done():
            assert time.monotonic() < deadline, "test owner command did not finish"
            gateway.serve(gateway._cache)
            time.sleep(0.001)
        return future.result()


def native_request(gateway, client, command, payload, operation_id):
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(client.request, command, payload, operation_id, timeout=3)
        deadline = time.monotonic() + 5
        while not future.done():
            assert time.monotonic() < deadline, "private endpoint command did not finish"
            gateway.serve(gateway._cache)
            time.sleep(0.002)
        return future.result()


def seed_binding(gateway):
    return gateway.bind_sources_fenced("fixture-source-bind", [binding()], owner_authorized=True)


def test_mutation_requires_explicit_owner_profile_and_source_binding_is_not_rpc(owner):
    cache, gateway, _, _ = owner
    with pytest.raises(SpanCacheQuackError, match="prototype opt-in"):
        SpanClaimsQuackGateway(cache, gateway.scope)
    with pytest.raises(SpanCacheQuackError, match="explicit authorization"):
        gateway.bind_sources_fenced("not-authorized", [binding()])
    with pytest.raises(SpanCacheQuackError, match="vocabulary"):
        _envelope("BindSpanSourcesFenced", {"bindings": [binding()]}, "worker-cannot-bind")
    assert seed_binding(gateway)["bound"] == 1
    assert cache.fenced_claims() is gateway._claims


@pytest.mark.parametrize("command,payload", [
    (CLAIM, {"span_ids": ["span-b"]}),
    (CLAIM, {"span_ids": ["span-a"], "worker_id": "worker-b"}),
    (CLAIM, {"span_ids": ["span-a"], "sql": "DELETE FROM span_cache"}),
    (READ, {"claim": {"claim_worker": "worker-b", "source_span_id": "span-a"}}),
    (RELEASE, {"claims": [{"claim_worker": "worker-a", "source_span_id": "span-b"}]}),
    (RESOLVE, {"operation_id": "other", "command": "BindSpanSourcesFenced", "payload": {}}),
])
def test_closed_worker_packets_cannot_change_assignment(owner, command, payload):
    _, gateway, _, _ = owner
    with pytest.raises(SpanCacheQuackError):
        local_request(gateway, command, payload, "denied")
    assert gateway.status()["pending"] == 0


def test_owner_thread_identity_cannot_be_replaced(owner):
    cache, gateway, _, _ = owner
    with ThreadPoolExecutor(max_workers=1) as workers:
        with pytest.raises(SpanCacheQuackError, match="original catalog owner thread"):
            workers.submit(gateway.serve, cache).result()
        with pytest.raises(SpanCacheQuackError, match="original catalog owner thread"):
            workers.submit(gateway.start).result()
        with pytest.raises(SpanCacheQuackError, match="original catalog owner thread"):
            workers.submit(gateway.bind_sources_fenced, "foreign", [binding()], owner_authorized=True).result()
    with pytest.raises(SpanCacheQuackError, match="different span catalog"):
        gateway.serve(object())


def test_foreign_process_cannot_serve_bind_or_close_inherited_gateway(owner, monkeypatch):
    cache, gateway, _, _ = owner
    # Simulate a fork identity without forking an active DuckDB connection.
    # The gateway must reject before calling either catalog or Quack cleanup.
    with monkeypatch.context() as changed:
        changed.setattr(gateway, "_owner_pid", os.getpid() + 1)
        for action in (gateway.start, lambda: gateway.serve(cache),
                       lambda: gateway.bind_sources_fenced("foreign", [binding()], owner_authorized=True),
                       gateway.close):
            with pytest.raises(SpanCacheQuackError, match="original catalog owner process"):
                action()
        assert gateway.status()["closed"] is False
    assert seed_binding(gateway)["bound"] == 1


def test_native_facade_receipts_replay_and_resolve_exact_worker_payload(owner):
    _, gateway, claims, _ = owner
    seed_binding(gateway)
    payload = {"span_ids": ["span-a"]}
    receipt = local_request(gateway, CLAIM, payload, "claim-a")
    assert receipt == local_request(gateway, CLAIM, payload, "claim-a")
    claim = receipt["claims"][0]
    assert claim["claim_worker"] == "worker-a"
    source = local_request(gateway, READ, {"claim": claim}, "read-a")
    assert source["text"] == TEXT
    resolved = local_request(gateway, RESOLVE,
        {"operation_id": "claim-a", "command": CLAIM, "payload": payload}, "resolve-a")
    assert resolved["receipt"] == receipt
    assert resolved["historical_receipt_only"] is True
    conflict = local_request(gateway, CLAIM, {"span_ids": ["span-a"], "lease_seconds": 9}, "claim-a")
    assert conflict["status"] == "refused"
    assert "operation ID conflicts" in conflict["refusal"]["reason"]
    output = completion(claim)
    completed = local_request(gateway, COMPLETE, output, "complete-a")
    assert completed == local_request(gateway, COMPLETE, output, "complete-a")
    assert completed["gaps"] == 1
    released = local_request(gateway, RELEASE, {"claims": [claim]}, "release-finished")
    assert released["status"] == "refused"
    assert local_request(gateway, RESOLVE,
        {"operation_id": "complete-a", "command": COMPLETE, "payload": output}, "resolve-complete")["receipt"] == completed
    assert claims.resolve_operation(gateway._durable_id("claim-a"), "ClaimSpans",
        {"worker_id": "worker-a", "span_ids": ["span-a"], "lease_seconds": 300}) == receipt
    for flag in ("qualified", "admitted", "formalized", "roundtrip_ok"):
        assert completed[flag] is False


@pytest.mark.parametrize("field,value", [
    ("claim_token", "forged-token"), ("fence", 999),
    ("source_revision", "hub:" + "c" * 40), ("source_sha256", "c" * 64),
])
def test_current_claim_fields_are_verified_by_native_owner(owner, field, value):
    _, gateway, _, _ = owner
    seed_binding(gateway)
    claim = local_request(gateway, CLAIM, {"span_ids": ["span-a"]}, "claim-a")["claims"][0]
    forged = dict(claim, **{field: value})
    result = local_request(gateway, COMPLETE, completion(forged), "forged-complete")
    assert result["status"] == "refused"
    assert result["admitted"] is False
    assert local_request(gateway, READ, {"claim": claim}, "still-readable")["text"] == TEXT


def test_expiry_is_structured_refusal_and_does_not_release_newer_claim(owner):
    _, gateway, _, now = owner
    seed_binding(gateway)
    old = local_request(gateway, CLAIM, {"span_ids": ["span-a"], "lease_seconds": 1}, "old")["claims"][0]
    now[0] = 102
    current = local_request(gateway, CLAIM, {"span_ids": ["span-a"]}, "new")["claims"][0]
    refusal = local_request(gateway, RELEASE, {"claims": [old]}, "late-release")
    assert refusal["status"] == "refused"
    assert "expired" in refusal["refusal"]["reason"]
    assert local_request(gateway, READ, {"claim": current}, "new-still-active")["text"] == TEXT


def test_owner_source_revision_update_retires_old_claim_without_rewriting_history(owner):
    _, gateway, _, _ = owner
    seed_binding(gateway)
    prior = local_request(gateway, CLAIM, {"span_ids": ["span-a"]}, "old-revision")
    claim = prior["claims"][0]
    updated = dict(binding(), source_revision="hub:" + "d" * 40,
                   expected_binding={"source_revision": REVISION, "source_sha256": SOURCE_SHA})
    bound = gateway.bind_sources_fenced("owner-source-update", [updated], owner_authorized=True)
    assert bound["retired_claims"] == ["span-a"]
    refused = local_request(gateway, COMPLETE, completion(claim), "old-source-completion")
    assert refused["status"] == "refused"
    resolved = local_request(gateway, RESOLVE,
        {"operation_id": "old-revision", "command": CLAIM, "payload": {"span_ids": ["span-a"]}},
        "resolve-old-revision")
    assert resolved["receipt"] == prior
    assert resolved["historical_receipt_only"] is True


def test_long_source_reply_refuses_without_truncating_original_span(tmp_path):
    text = "é" * 80_000
    cache = SpanCache(tmp_path / "long-source-owner.duckdb")
    cache.enqueue([{"source_span_id": "long-span", "text": text, "legal_id": "fixture:long"}])
    gateway = SpanClaimsQuackGateway(cache, SpanClaimWorkerScope("worker", {"long-span"}), enable_prototype=True)
    try:
        gateway.bind_sources_fenced("bind", [{"source_span_id": "long-span", "source_revision": REVISION,
            "source_sha256": hashlib.sha256(text.encode()).hexdigest(), "expected_binding": None}], owner_authorized=True)
        claim = local_request(gateway, CLAIM, {"span_ids": ["long-span"]}, "claim")["claims"][0]
        reply = local_request(gateway, READ, {"claim": claim}, "read-long")
        assert reply["status"] == "refused"
        assert reply["refusal"]["code"] == "reply_requires_data_plane"
        assert "text" not in reply
        assert gateway._claims.read_claim_source_fenced(claim)["text"] == text
    finally:
        gateway.close()
        cache.close()


def test_owner_timeout_cancels_unstarted_mutation(owner, monkeypatch):
    _, gateway, claims, _ = owner
    seed_binding(gateway)
    monkeypatch.setattr(transport, "OWNER_RESPONSE_SECONDS", 0.01)
    with ThreadPoolExecutor(max_workers=1) as workers:
        with pytest.raises(SpanCacheQuackError, match="cancelled before dispatch"):
            workers.submit(gateway.dispatch, _envelope(CLAIM, {"span_ids": ["span-a"]}, "cancelled")).result()
    assert gateway.serve(gateway._cache) == 0
    assert claims.resolve_operation(gateway._durable_id("cancelled"), "ClaimSpans",
        {"worker_id": "worker-a", "span_ids": ["span-a"], "lease_seconds": 300}) is None


def test_worker_operation_namespace_does_not_replace_another_workers_receipt(owner):
    cache, gateway, _, _ = owner
    other = SpanClaimsQuackGateway(cache, SpanClaimWorkerScope("worker-b", {"span-a"}), enable_prototype=True)
    try:
        assert gateway._durable_id("same") != other._durable_id("same")
        seed_binding(gateway)
        claim = local_request(gateway, CLAIM, {"span_ids": ["span-a"]}, "same")["claims"][0]
        result = local_request(other, CLAIM, {"span_ids": ["span-a"]}, "same")
        assert result["status"] == "refused"
        assert "live claim" in result["refusal"]["reason"]
        with pytest.raises(SpanCacheQuackError, match="assigned worker scope"):
            local_request(other, READ, {"claim": claim}, "steal")
    finally:
        other.close()


@pytest.mark.parametrize("cancelled", [False, True])
def test_owner_tick_yields_even_when_producer_continuously_refills_queue(owner, monkeypatch, cancelled):
    cache, gateway, claims, _ = owner
    seed_binding(gateway)
    def new_request():
        return {"request": _envelope(CLAIM, {"span_ids": ["span-a"]}, "repeated-claim"),
                "state": "cancelled" if cancelled else "queued", "event": threading.Event(),
                "lock": threading.Lock(), "result": None, "error": None}
    gateway._requests.put_nowait(new_request())
    actual_get = gateway._requests.get_nowait
    dequeued = []
    def producer_refilled_get():
        # A continuous producer supplies replacement work before every dequeue
        # finishes. An unbounded implementation fails at item 65, never hangs.
        assert len(dequeued) < transport.MAX_PENDING, "owner tick failed to yield to other owner work"
        item = actual_get()
        dequeued.append(item)
        gateway._requests.put_nowait(new_request())
        return item
    with monkeypatch.context() as altered:
        altered.setattr(gateway._requests, "get_nowait", producer_refilled_get)
        assert gateway.serve(cache) == (0 if cancelled else transport.MAX_PENDING)
    assert len(dequeued) == transport.MAX_PENDING
    assert gateway.status()["pending"] == 1
    assert all(item["state"] == ("cancelled" if cancelled else "finished") for item in dequeued)
    if not cancelled:
        receipt = dequeued[0]["result"]
        assert all(item["result"] == receipt for item in dequeued)
        assert claims.read_claim_source_fenced(receipt["claims"][0])["text"] == TEXT
    assert gateway.serve(cache) == (0 if cancelled else 1)
    assert gateway.status()["pending"] == 0


@NATIVE
def test_private_native_endpoint_claim_finish_resolve_and_sql_denials(owner, monkeypatch):
    import duckdb
    cache, gateway, _, _ = owner
    seed_binding(gateway)
    opened = []
    actual_connect = duckdb.connect
    def observed_connect(database=":memory:", *args, **kwargs):
        opened.append(str(database))
        return actual_connect(database, *args, **kwargs)
    monkeypatch.setattr(duckdb, "connect", observed_connect)
    gateway.start()
    params = gateway.connection_parameters()
    assert params["endpoint"].startswith("quack:127.0.0.1:")
    with SpanClaimsTransportClient(**params) as client:
        payload = {"span_ids": ["span-a"]}
        receipt = native_request(gateway, client, CLAIM, payload, "wire-claim")
        claim = receipt["claims"][0]
        assert native_request(gateway, client, READ, {"claim": claim}, "wire-read")["text"] == TEXT
        done = native_request(gateway, client, COMPLETE, completion(claim), "wire-finish")
        assert done["gaps"] == 1
        assert native_request(gateway, client, RESOLVE,
            {"operation_id": "wire-finish", "command": COMPLETE, "payload": completion(claim)},
            "wire-resolve")["receipt"] == done
        refusal = native_request(gateway, client, RELEASE, {"claims": [claim]}, "wire-late-release")
        assert refusal["status"] == "refused"
        assert refusal["roundtrip_ok"] is False
        with pytest.raises(RegistryTransportError):
            SpanClaimsTransportClient(params["endpoint"], "wrong-private-fixture-token-000000000")
        for sql in ("SELECT * FROM span_cache", "SELECT 1", "DELETE FROM command_inbox"):
            with pytest.raises(Exception):
                client._connection.execute(
                    "SELECT * FROM quack_query(?, ?, token := ?, disable_ssl := true)",
                    [params["endpoint"], sql, params["token"]]).fetchall()
    assert opened and set(opened) == {":memory:"}
    assert cache.fenced_claims() is gateway._claims
    assert gateway.status()["private_catalog_attached"] is False
    assert gateway.status()["failure"] is None


@NATIVE
def test_private_native_endpoint_cannot_add_worker_selected_source_or_sql(owner):
    _, gateway, _, _ = owner
    seed_binding(gateway)
    gateway.start()
    with SpanClaimsTransportClient(**gateway.connection_parameters()) as client:
        for payload in ({"span_ids": ["span-a"], "worker_id": "worker-b"},
                        {"span_ids": ["span-b"]},
                        {"span_ids": ["span-a"], "source_revision": REVISION},
                        {"span_ids": ["span-a"], "admitted": True}):
            with pytest.raises(RegistryTransportError):
                native_request(gateway, client, CLAIM, payload, "wire-denied")
    assert gateway.status()["pending"] == 0


@NATIVE
def test_two_private_worker_endpoints_share_one_native_catalog_owner(owner):
    cache, gateway, _, _ = owner
    other = SpanClaimsQuackGateway(cache, SpanClaimWorkerScope("worker-b", {"span-b"}), enable_prototype=True)
    try:
        seed_binding(gateway)
        other.bind_sources_fenced("bind-b", [dict(binding(), source_span_id="span-b")], owner_authorized=True)
        gateway.start()
        other.start()
        assert gateway._claims is other._claims
        with SpanClaimsTransportClient(**gateway.connection_parameters()) as client_a, \
             SpanClaimsTransportClient(**other.connection_parameters()) as client_b:
            with ThreadPoolExecutor(max_workers=2) as workers:
                future_a = workers.submit(client_a.request, CLAIM, {"span_ids": ["span-a"]}, "same-operation", timeout=3)
                future_b = workers.submit(client_b.request, CLAIM, {"span_ids": ["span-b"]}, "same-operation", timeout=3)
                deadline = time.monotonic() + 5
                while not (future_a.done() and future_b.done()):
                    assert time.monotonic() < deadline
                    gateway.serve(cache)
                    other.serve(cache)
                    time.sleep(0.002)
                receipt_a, receipt_b = future_a.result(), future_b.result()
            claim_a, claim_b = receipt_a["claims"][0], receipt_b["claims"][0]
            assert claim_a["claim_worker"] == "worker-a"
            assert claim_b["claim_worker"] == "worker-b"
            assert receipt_a["operation_id"] != receipt_b["operation_id"]
            assert native_request(gateway, client_a, READ, {"claim": claim_a}, "read-a")["text"] == TEXT
            assert native_request(other, client_b, READ, {"claim": claim_b}, "read-b")["text"] == TEXT
            assert native_request(gateway, client_a, RELEASE, {"claims": [claim_a]}, "release-a")["released"] == 1
            assert native_request(other, client_b, RELEASE, {"claims": [claim_b]}, "release-b")["released"] == 1
    finally:
        other.close()
