"""KGP-011: ipfs_kit_py GraphStore adapter contract tests.

Acceptance coverage (shared with KGP-010 direct adapter vectors):

* put / get / stat / pin / unpin / CAR / cancellation
* CID verification after every fetch
* typed errors
* restart / corruption / idempotency
* **explicit capability negotiation** — unavailable capabilities reported
  before mutation (no import-time silent fallback)
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Iterator

import pytest

from ipfs_datasets_py.knowledge_graphs.contracts.manifest import (
    ContentChecksum,
    GraphCounts,
    PartitionDescriptor,
    ProvenanceDescriptor,
    build_graph_revision_manifest,
)
from ipfs_datasets_py.knowledge_graphs.storage.ipfs_kit import (
    STORAGE_PROFILE,
    TYPED_ERROR_CODES,
    DeterministicKitClient,
    GraphStoreError,
    IpfsKitBlockBackend,
    IpfsKitGraphStore,
    KitCapabilities,
    PutResult,
    compute_cid_v1,
    create_ipfs_kit_graph_store,
    decode_car,
    encode_car,
    encode_dag_cbor,
    full_capabilities,
    kit_package_available,
    map_kit_error,
    probe_kit_client_capabilities,
    verify_bytes_against_cid,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def memory_store() -> Iterator[IpfsKitGraphStore]:
    store = IpfsKitGraphStore.open_memory(pin_by_default=True)
    try:
        yield store
    finally:
        store.close()


@pytest.fixture
def tmp_store(tmp_path: Path) -> Iterator[IpfsKitGraphStore]:
    store = IpfsKitGraphStore.open_directory(tmp_path / "kit-blocks", pin_by_default=True)
    try:
        yield store
    finally:
        store.close()


def _sample_manifest(**overrides: Any):
    part = PartitionDescriptor(
        partition_id="part-nodes",
        kind="nodes",
        path="partitions/nodes.parquet",
        codec="parquet",
        checksum=ContentChecksum.of_bytes(b"nodes-payload-v1"),
        row_count=3,
        size_bytes=16,
    )
    kwargs = dict(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-001",
        graph_kind="knowledge",
        schema_id="kg-schema",
        schema_version="1",
        ontology_id="skos",
        ontology_version="1",
        storage_profile="ipfs_kit",
        codec="dag-cbor",
        counts=GraphCounts(node_count=3, edge_count=0, document_count=0),
        partitions=(part,),
        provenance=ProvenanceDescriptor(
            producer_id="kgp-011-tests",
            producer_version="1",
            source="contract",
            created_at="2026-07-29T00:00:00Z",
        ),
    )
    kwargs.update(overrides)
    return build_graph_revision_manifest(**kwargs)


# ---------------------------------------------------------------------------
# Capability negotiation
# ---------------------------------------------------------------------------


def test_deterministic_client_probes_full_capabilities() -> None:
    client = DeterministicKitClient()
    caps = probe_kit_client_capabilities(client)
    assert caps.is_fully_capable()
    assert caps.source == "probe"
    assert caps.put and caps.get and caps.pin and caps.unpin
    assert caps.car_export and caps.car_import and caps.stat


def test_partial_client_reports_missing_before_mutation() -> None:
    """Capability negotiation must not grant put based on import alone."""

    class GetOnlyClient:
        def block_get(self, cid: str) -> bytes:
            raise FileNotFoundError("not found")

    caps = probe_kit_client_capabilities(GetOnlyClient())
    assert caps.get is True
    assert caps.put is False
    assert "put" in caps.missing()

    store = IpfsKitGraphStore(
        kit_client=GetOnlyClient(),
        capabilities=caps,
        pin_by_default=False,
    )
    try:
        report = store.report_capabilities()
        assert report["fully_capable"] is False
        assert "put" in report["missing"]
        with pytest.raises(GraphStoreError) as ei:
            store.put(b"should-fail", codec="raw", pin=False)
        assert ei.value.code == "NOT_IMPLEMENTED"
        assert ei.value.cause_code == "KIT_CAPABILITY_UNAVAILABLE"
        assert "put" in ei.value.details["missing"]
    finally:
        store.close()


def test_pin_capability_required_before_pinning_put(memory_store: IpfsKitGraphStore) -> None:
    # Force a store whose capabilities claim pin is missing.
    store = IpfsKitGraphStore.open_memory(pin_by_default=False)
    store.capabilities = KitCapabilities(
        put=True,
        get=True,
        stat=True,
        pin=False,
        unpin=True,
        car_export=True,
        car_import=True,
        cancel=True,
        source="declared",
    )
    try:
        with pytest.raises(GraphStoreError) as ei:
            store.put(b"x", codec="raw", pin=True)
        assert ei.value.code == "NOT_IMPLEMENTED"
        assert "pin" in ei.value.details["missing"]
        # pin=False must still succeed when put is available.
        result = store.put(b"x", codec="raw", pin=False)
        assert result.cid
        assert result.pinned is False
    finally:
        store.close()


def test_require_full_capabilities_on_open() -> None:
    class EmptyClient:
        pass

    with pytest.raises(GraphStoreError) as ei:
        IpfsKitGraphStore(
            kit_client=EmptyClient(),
            require_full_capabilities=True,
        )
    assert ei.value.code == "NOT_IMPLEMENTED"
    assert ei.value.cause_code == "KIT_CAPABILITIES_INCOMPLETE"


def test_open_kit_without_package_is_typed_storage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPFS_KIT_DISABLE", "1")
    # kit_package_available respects IPFS_KIT_DISABLE.
    assert kit_package_available() is False
    with pytest.raises(GraphStoreError) as ei:
        IpfsKitGraphStore.open_kit()
    assert ei.value.code == "STORAGE"
    assert ei.value.cause_code == "KIT_PACKAGE_UNAVAILABLE"


def test_full_capabilities_helper() -> None:
    caps = full_capabilities(source="test")
    assert caps.is_fully_capable()
    assert caps.as_dict()["source"] == "test"
    assert not caps.missing()


def test_memory_store_reports_capabilities(memory_store: IpfsKitGraphStore) -> None:
    report = memory_store.report_capabilities()
    assert report["storage_profile"] == "ipfs_kit"
    assert report["fully_capable"] is True
    assert report["missing"] == []
    assert "put" in report["available"]


# ---------------------------------------------------------------------------
# CID verification
# ---------------------------------------------------------------------------


def test_compute_cid_v1_dag_cbor_is_stable() -> None:
    payload = encode_dag_cbor({"hello": "world"})
    cid_a = compute_cid_v1(payload, codec="dag-cbor")
    cid_b = compute_cid_v1(payload, codec="dag-cbor")
    assert cid_a == cid_b
    assert cid_a.startswith("b")


def test_verify_bytes_against_cid_accepts_match() -> None:
    data = b"payload-bytes"
    cid = compute_cid_v1(data, codec="raw")
    assert verify_bytes_against_cid(cid, data) == cid


def test_verify_bytes_against_cid_rejects_mismatch() -> None:
    data = b"payload-bytes"
    cid = compute_cid_v1(data, codec="raw")
    with pytest.raises(GraphStoreError) as ei:
        verify_bytes_against_cid(cid, b"tampered")
    assert ei.value.code == "INTEGRITY"
    assert ei.value.cause_code == "CID_MISMATCH"
    assert ei.value.retryable is False


def test_get_verifies_cid_after_fetch(memory_store: IpfsKitGraphStore) -> None:
    result = memory_store.put(b"abc", codec="raw", pin=False)
    # Corrupt the deterministic kit backend behind the store.
    client = memory_store._kit_client
    assert isinstance(client, DeterministicKitClient)
    backend = client._backend
    backend._blocks[result.cid] = b"CORRUPT"  # type: ignore[attr-defined]
    with pytest.raises(GraphStoreError) as ei:
        memory_store.get(result.cid)
    assert ei.value.code == "INTEGRITY"


# ---------------------------------------------------------------------------
# DAG-CBOR manifests / indexes
# ---------------------------------------------------------------------------


def test_put_get_dag_cbor_round_trip(memory_store: IpfsKitGraphStore) -> None:
    value = {"a": 1, "b": ["x", "y"], "nested": {"k": True}}
    put = memory_store.put_dag_cbor(value)
    assert isinstance(put, PutResult)
    assert put.codec == "dag-cbor"
    assert put.size > 0
    assert put.pinned is True
    loaded = memory_store.get_dag_cbor(put.cid)
    assert loaded == value


def test_put_get_manifest_canonical(memory_store: IpfsKitGraphStore) -> None:
    manifest = _sample_manifest()
    put = memory_store.put_manifest(manifest)
    loaded = memory_store.get_manifest(put.cid)
    assert loaded["tenant"] == "acme"
    assert loaded["graph_id"] == "skills"
    assert loaded["revision_id"] == "rev-001"
    assert loaded["storage_profile"] == "ipfs_kit"
    assert loaded["codec"] == "dag-cbor"
    assert loaded["checksum"]["hex_digest"] == manifest.checksum.hex_digest
    assert loaded["counts"]["node_count"] == 3


def test_put_get_index_page(memory_store: IpfsKitGraphStore) -> None:
    index = {
        "index_id": "idx-type",
        "kind": "type",
        "entries": [{"type": "Person", "count": 12}, {"type": "Org", "count": 4}],
        "schema_version": "1",
    }
    put = memory_store.put_index(index)
    loaded = memory_store.get_index(put.cid)
    assert loaded["index_id"] == "idx-type"
    assert loaded["entries"][0]["type"] == "Person"


def test_put_index_rejects_non_mapping(memory_store: IpfsKitGraphStore) -> None:
    with pytest.raises(GraphStoreError) as ei:
        memory_store.put_index(["not", "a", "map"])  # type: ignore[arg-type]
    assert ei.value.code == "INVALID_REQUEST"


def test_manifest_as_mapping_is_accepted(memory_store: IpfsKitGraphStore) -> None:
    manifest = _sample_manifest()
    put = memory_store.put_manifest(manifest.to_dict())
    loaded = memory_store.get_manifest(put.cid)
    assert loaded["revision_id"] == "rev-001"


# ---------------------------------------------------------------------------
# CAR payload objects + offline multi-block CAR
# ---------------------------------------------------------------------------


def test_put_get_car_object(memory_store: IpfsKitGraphStore) -> None:
    leaf = memory_store.put_dag_cbor({"leaf": True})
    root = memory_store.put_dag_cbor({"child": leaf.cid, "kind": "root"})
    car_bytes = memory_store.export_car(root.cid)
    assert len(car_bytes) > 0

    car_put = memory_store.put_car_object(car_bytes)
    assert car_put.codec == "raw"
    fetched = memory_store.get_car_object(car_put.cid)
    assert fetched == car_bytes
    roots, blocks = decode_car(fetched)
    assert root.cid in roots
    assert any(b[0] == root.cid for b in blocks)


def test_offline_car_round_trip_between_stores() -> None:
    src = IpfsKitGraphStore.open_memory()
    try:
        leaf = src.put_dag_cbor({"n": 1})
        mid = src.put_dag_cbor({"link": leaf.cid, "n": 2})
        root = src.put_dag_cbor({"link": mid.cid, "n": 3})
        car = src.export_car(root.cid)
    finally:
        src.close()

    dst = IpfsKitGraphStore.open_memory()
    try:
        roots = dst.import_car(car)
        assert roots == [root.cid]
        assert dst.get_dag_cbor(root.cid)["n"] == 3
        assert dst.get_dag_cbor(mid.cid)["link"] == leaf.cid
        assert dst.get_dag_cbor(leaf.cid)["n"] == 1
        assert dst.is_pinned(root.cid)
    finally:
        dst.close()


def test_export_car_single_root_without_reachable() -> None:
    store = IpfsKitGraphStore.open_memory()
    try:
        leaf = store.put_dag_cbor({"only": "leaf"})
        root = store.put_dag_cbor({"child": leaf.cid})
        car = store.export_car(root.cid, include_reachable=False)
        roots, blocks = decode_car(car)
        assert roots == [root.cid]
        assert len(blocks) == 1
        assert blocks[0][0] == root.cid
    finally:
        store.close()


def test_import_car_rejects_tampered_block() -> None:
    store = IpfsKitGraphStore.open_memory()
    try:
        put = store.put_dag_cbor({"ok": True})
        car = store.export_car(put.cid)
        roots, blocks = decode_car(car)
        bad_blocks = [(cid, (b"\x00" + data) if cid == put.cid else data) for cid, data in blocks]
        try:
            bad_car = encode_car(roots, bad_blocks)
        except Exception:
            pytest.skip("cannot re-encode tampered CAR in this environment")
        victim = IpfsKitGraphStore.open_memory()
        try:
            with pytest.raises(GraphStoreError) as ei:
                victim.import_car(bad_car)
            assert ei.value.code == "INTEGRITY"
        finally:
            victim.close()
    finally:
        store.close()


def test_car_export_requires_capability() -> None:
    store = IpfsKitGraphStore.open_memory()
    store.capabilities = KitCapabilities(
        put=True,
        get=True,
        stat=True,
        pin=True,
        unpin=True,
        car_export=False,
        car_import=True,
        cancel=True,
        source="declared",
    )
    try:
        put = store.put_dag_cbor({"x": 1})
        with pytest.raises(GraphStoreError) as ei:
            store.export_car(put.cid)
        assert ei.value.code == "NOT_IMPLEMENTED"
        assert "car_export" in ei.value.details["missing"]
    finally:
        store.close()


# ---------------------------------------------------------------------------
# pin / unpin / stat
# ---------------------------------------------------------------------------


def test_pin_unpin_stat(memory_store: IpfsKitGraphStore) -> None:
    put = memory_store.put(b"pin-me", codec="raw", pin=False)
    assert memory_store.is_pinned(put.cid) is False

    memory_store.pin(put.cid)
    assert memory_store.is_pinned(put.cid) is True

    st = memory_store.stat(put.cid)
    assert st.cid == put.cid
    assert st.size == len(b"pin-me")
    assert st.codec == "raw"
    assert st.pinned is True
    assert st.backend == "ipfs_kit"
    assert st.to_dict()["size"] == len(b"pin-me")

    memory_store.unpin(put.cid)
    assert memory_store.is_pinned(put.cid) is False
    assert memory_store.stat(put.cid).pinned is False


def test_pin_missing_is_not_found(memory_store: IpfsKitGraphStore) -> None:
    missing = compute_cid_v1(b"does-not-exist", codec="raw")
    with pytest.raises(GraphStoreError) as ei:
        memory_store.pin(missing)
    assert ei.value.code == "NOT_FOUND"


def test_stat_not_found(memory_store: IpfsKitGraphStore) -> None:
    missing = compute_cid_v1(b"absent", codec="raw")
    with pytest.raises(GraphStoreError) as ei:
        memory_store.stat(missing)
    assert ei.value.code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Typed error mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,code,retryable",
    [
        ("block was not found", "NOT_FOUND", False),
        ("merkledag: not found", "NOT_FOUND", False),
        ("cid mismatch in block", "INTEGRITY", False),
        ("connection refused", "STORAGE", True),
        ("context deadline exceeded", "STORAGE", True),
        ("invalid multihash length", "INTEGRITY", False),
        ("unknown codec foobar", "INVALID_REQUEST", False),
        ("something mysterious failed", "STORAGE", True),
    ],
)
def test_map_kit_error_codes(message: str, code: str, retryable: bool) -> None:
    err = map_kit_error(RuntimeError(message), operation="block_get", cid="bafytest")
    assert err.code == code
    assert err.retryable is retryable
    assert err.code in TYPED_ERROR_CODES
    typed = err.to_typed_dict()
    assert typed["code"] == code
    assert typed["details"]["operation"] == "block_get"
    assert "bafytest" in typed["details"]["cid"]
    assert typed["details"].get("adapter") == "ipfs_kit"


def test_map_kit_error_preserves_graph_store_error() -> None:
    original = GraphStoreError("NOT_FOUND", "already typed")
    assert map_kit_error(original, operation="x") is original


def test_graph_store_error_rejects_unknown_code() -> None:
    with pytest.raises(ValueError):
        GraphStoreError("NOT_A_REAL_CODE", "nope")


def test_timeout_error_maps_to_storage_retryable() -> None:
    err = map_kit_error(TimeoutError("timed out waiting"), operation="get")
    assert err.code == "STORAGE"
    assert err.retryable is True


# ---------------------------------------------------------------------------
# Restart / durable read (filesystem double)
# ---------------------------------------------------------------------------


def test_directory_backend_restart_read(tmp_path: Path) -> None:
    root = tmp_path / "store-a"
    store1 = IpfsKitGraphStore.open_directory(root)
    try:
        man = _sample_manifest(revision_id="rev-restart")
        put = store1.put_manifest(man)
        idx = store1.put_index({"index_id": "i1", "kind": "type", "entries": []})
        car = store1.export_car([put.cid, idx.cid])
        car_obj = store1.put_car_object(car)
        store1.pin(put.cid)
        cid_manifest = put.cid
        cid_index = idx.cid
        cid_car = car_obj.cid
    finally:
        store1.close()

    store2 = IpfsKitGraphStore.open_directory(root)
    try:
        loaded = store2.get_manifest(cid_manifest)
        assert loaded["revision_id"] == "rev-restart"
        assert store2.get_index(cid_index)["index_id"] == "i1"
        assert store2.get_car_object(cid_car) == car
        assert store2.is_pinned(cid_manifest) is True
        st = store2.stat(cid_manifest)
        assert st.pinned is True
        assert st.size > 0
    finally:
        store2.close()


def test_create_factory_directory_and_memory(tmp_path: Path) -> None:
    mem = create_ipfs_kit_graph_store(mode="memory")
    assert mem.storage_profile == STORAGE_PROFILE
    mem.close()

    disk = create_ipfs_kit_graph_store(mode="directory", root_dir=tmp_path / "d")
    r = disk.put(b"x", codec="raw")
    assert disk.get(r.cid) == b"x"
    disk.close()


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_cancel_check_aborts_put() -> None:
    cancelled = threading.Event()

    def check() -> None:
        if cancelled.is_set():
            raise GraphStoreError(
                "STORAGE",
                "operation cancelled",
                retryable=True,
                details={"cancelled": True},
                cause_code="CANCELLED",
            )

    store = IpfsKitGraphStore.open_memory(cancel_check=check)
    cancelled.set()
    with pytest.raises(GraphStoreError) as ei:
        store.put(b"nope", codec="raw")
    assert ei.value.cause_code == "CANCELLED"
    store.close()


# ---------------------------------------------------------------------------
# Idempotency / content addressing
# ---------------------------------------------------------------------------


def test_put_is_idempotent_same_cid(memory_store: IpfsKitGraphStore) -> None:
    a = memory_store.put_dag_cbor({"stable": True})
    b = memory_store.put_dag_cbor({"stable": True})
    assert a.cid == b.cid
    assert memory_store.get_dag_cbor(a.cid) == {"stable": True}


def test_storage_profile_constant() -> None:
    assert STORAGE_PROFILE == "ipfs_kit"
    assert IpfsKitGraphStore.storage_profile == "ipfs_kit"


# ---------------------------------------------------------------------------
# Encode helpers / validation
# ---------------------------------------------------------------------------


def test_get_missing_block_typed(memory_store: IpfsKitGraphStore) -> None:
    missing = compute_cid_v1(b"no-such-block", codec="raw")
    with pytest.raises(GraphStoreError) as ei:
        memory_store.get(missing)
    assert ei.value.code == "NOT_FOUND"
    assert ei.value.to_typed_dict()["retryable"] is False


def test_invalid_cid_argument(memory_store: IpfsKitGraphStore) -> None:
    with pytest.raises(GraphStoreError) as ei:
        memory_store.get("")
    assert ei.value.code == "INVALID_REQUEST"


def test_put_rejects_non_bytes(memory_store: IpfsKitGraphStore) -> None:
    with pytest.raises(GraphStoreError) as ei:
        memory_store.put("not-bytes")  # type: ignore[arg-type]
    assert ei.value.code == "INVALID_REQUEST"


def test_linked_manifest_and_index_car_bundle(memory_store: IpfsKitGraphStore) -> None:
    """End-to-end: index + manifest as DAG-CBOR, CAR payload object, offline import."""
    index_put = memory_store.put_index(
        {
            "index_id": "idx-entity",
            "kind": "type",
            "buckets": [{"key": "Person", "cids": []}],
        }
    )
    manifest = _sample_manifest(revision_id="rev-bundle")
    man_put = memory_store.put_manifest(manifest)
    root = memory_store.put_dag_cbor(
        {
            "type": "kg-revision-bundle",
            "manifest_cid": man_put.cid,
            "index_cids": [index_put.cid],
        }
    )
    car = memory_store.export_car(root.cid)
    car_obj = memory_store.put_car_object(car)

    other = IpfsKitGraphStore.open_memory()
    try:
        other.import_car(memory_store.get_car_object(car_obj.cid))
        bundle = other.get_dag_cbor(root.cid)
        assert bundle["manifest_cid"] == man_put.cid
        assert other.get_manifest(bundle["manifest_cid"])["revision_id"] == "rev-bundle"
        assert other.get_index(bundle["index_cids"][0])["index_id"] == "idx-entity"
    finally:
        other.close()


# ---------------------------------------------------------------------------
# Kit block backend + injected partial clients
# ---------------------------------------------------------------------------


def test_ipfs_kit_block_backend_round_trip() -> None:
    client = DeterministicKitClient()
    backend = IpfsKitBlockBackend(client)
    cid = backend.put_block(b"hello-kit", codec="raw")
    assert backend.get_block(cid) == b"hello-kit"
    backend.pin(cid)
    assert backend.is_pinned(cid) is True
    backend.unpin(cid)
    assert backend.is_pinned(cid) is False


def test_open_kit_with_injected_client() -> None:
    client = DeterministicKitClient()
    store = IpfsKitGraphStore.open_kit(client, pin_by_default=True)
    try:
        assert store.capabilities.put is True
        put = store.put_dag_cbor({"via": "injected-kit"})
        assert store.get_dag_cbor(put.cid)["via"] == "injected-kit"
    finally:
        store.close()


def test_negotiate_capabilities_refresh() -> None:
    store = IpfsKitGraphStore.open_memory()
    try:
        caps = store.negotiate_capabilities()
        assert caps.put is True
        assert store.capabilities.put is True
    finally:
        store.close()


def test_create_factory_with_injected_kit_client() -> None:
    client = DeterministicKitClient()
    store = create_ipfs_kit_graph_store(mode="kit", kit_client=client)
    try:
        r = store.put(b"z", codec="raw", pin=False)
        assert store.get(r.cid) == b"z"
    finally:
        store.close()


def test_unknown_mode_rejected() -> None:
    with pytest.raises(GraphStoreError) as ei:
        create_ipfs_kit_graph_store(mode="not-a-mode")
    assert ei.value.code == "INVALID_REQUEST"
