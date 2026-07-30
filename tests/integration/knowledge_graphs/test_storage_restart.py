"""KGP-046: Shared storage restart and corruption validator.

Acceptance coverage:

* Exercise the **Parquet**, **direct IPFS/IPLD**, and **ipfs_kit_py** profiles
  through one shared revision round-trip.
* Recreate the adapter **and** GraphService between write and read (no process
  caches).
* Verify canonical manifest identity and object bytes after restart.
* Prove corrupt or truncated persisted data **fails closed** (typed
  ``INTEGRITY``).
* Deterministic doubles run everywhere; optional live-daemon coverage is
  additive and must not replace the deterministic proof.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from ipfs_datasets_py.knowledge_graphs.contracts.manifest import (
    ContentChecksum,
    GraphCounts,
    PartitionDescriptor,
    ProvenanceDescriptor,
    build_graph_revision_manifest,
)
from ipfs_datasets_py.knowledge_graphs.service import GraphService, GraphTarget
from ipfs_datasets_py.knowledge_graphs.storage.ipfs_kit import (
    IpfsKitGraphStore,
    kit_package_available,
)
from ipfs_datasets_py.knowledge_graphs.storage.ipld_store import (
    GraphStoreError as CidGraphStoreError,
    IPLDGraphStore,
    kubo_available,
)
from ipfs_datasets_py.knowledge_graphs.storage.parquet import (
    GraphStoreError as ParquetGraphStoreError,
    ParquetGraphStore,
    detect_parquet_corruption,
)

# Parquet keeps a local GraphStoreError type; CID profiles share the IPLD one.
# Accept either in fail-closed assertions so the shared harness stays profile-neutral.
IntegrityError = (ParquetGraphStoreError, CidGraphStoreError)
# Alias used by CID-profile tests and optional additive paths.
GraphStoreError = CidGraphStoreError

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Shared revision fixture (identical logical content across profiles)
# ---------------------------------------------------------------------------

SHARED_TENANT = "acme"
SHARED_GRAPH_ID = "skills"
SHARED_REVISION_ID = "rev-shared-001"
SHARED_OBJECT_BYTES = b"kgp-046-shared-object-bytes-v1"
SHARED_NODE_PAYLOAD = b"nodes-payload-v1"
SHARED_PRODUCER = "kgp-046-storage-restart"
SHARED_CREATED_AT = "2026-07-30T00:00:00Z"

STORAGE_PROFILES: Tuple[str, ...] = ("parquet", "ipfs_ipld", "ipfs_kit")


def _sample_nodes() -> List[Dict[str, Any]]:
    return [
        {
            "id": "n1",
            "type": "Person",
            "name": "Alice",
            "properties": {"age": 30, "city": "SF"},
            "confidence": 0.95,
        },
        {
            "id": "n2",
            "type": "Org",
            "name": "Acme",
            "properties": {"city": "SF"},
        },
        {
            "id": "n3",
            "type": "Person",
            "name": "Bob",
            "properties": {"age": 25},
        },
    ]


def _sample_edges() -> List[Dict[str, Any]]:
    return [
        {
            "id": "e1",
            "type": "WORKS_AT",
            "source_id": "n1",
            "target_id": "n2",
            "properties": {"since": 2020},
        },
        {
            "id": "e2",
            "type": "KNOWS",
            "source_id": "n1",
            "target_id": "n3",
        },
    ]


def _shared_provenance() -> ProvenanceDescriptor:
    return ProvenanceDescriptor(
        producer_id=SHARED_PRODUCER,
        producer_version="1",
        source="integration",
        created_at=SHARED_CREATED_AT,
    )


def _shared_partition() -> PartitionDescriptor:
    return PartitionDescriptor(
        partition_id="part-nodes",
        kind="nodes",
        path="partitions/nodes.parquet",
        codec="parquet",
        checksum=ContentChecksum.of_bytes(SHARED_NODE_PAYLOAD),
        row_count=3,
        size_bytes=len(SHARED_NODE_PAYLOAD),
    )


def _shared_manifest(
    storage_profile: str,
    *,
    revision_id: str = SHARED_REVISION_ID,
    parent_revision: Optional[str] = None,
    codec: str = "dag-cbor",
) -> Any:
    """Build the same logical revision manifest for every profile under test."""
    return build_graph_revision_manifest(
        tenant=SHARED_TENANT,
        graph_id=SHARED_GRAPH_ID,
        revision_id=revision_id,
        graph_kind="knowledge",
        schema_id="kg-schema",
        schema_version="1",
        ontology_id="skos",
        ontology_version="1",
        storage_profile=storage_profile,
        codec=codec if storage_profile != "parquet" else "parquet",
        counts=GraphCounts(node_count=3, edge_count=2, document_count=0),
        partitions=(_shared_partition(),),
        provenance=_shared_provenance(),
        parent_revision=parent_revision,
    )


@dataclass(frozen=True)
class WrittenRevision:
    """Handles needed to re-open a written shared revision after restart."""

    profile: str
    revision_id: str
    manifest_cid: Optional[str]
    object_cid: Optional[str]
    object_bytes: bytes
    manifest_checksum: str
    revision_path: Optional[str] = None  # parquet revision directory
    partition_checksums: Optional[Dict[str, str]] = None


# ---------------------------------------------------------------------------
# Profile open / write / read helpers (deterministic doubles only)
# ---------------------------------------------------------------------------


def _open_adapter(profile: str, root: Path) -> Any:
    if profile == "parquet":
        return ParquetGraphStore.open(root, row_group_size=4)
    if profile == "ipfs_ipld":
        return IPLDGraphStore.open_directory(root, pin_by_default=True)
    if profile == "ipfs_kit":
        return IpfsKitGraphStore.open_directory(root, pin_by_default=True)
    raise AssertionError(f"unknown storage profile: {profile!r}")


def _write_shared_revision(adapter: Any, profile: str) -> WrittenRevision:
    """Persist the shared revision through the given profile adapter."""
    if profile == "parquet":
        result = adapter.publish_revision(
            tenant=SHARED_TENANT,
            graph_id=SHARED_GRAPH_ID,
            revision_id=SHARED_REVISION_ID,
            nodes=_sample_nodes(),
            edges=_sample_edges(),
            provenance={
                "producer_id": SHARED_PRODUCER,
                "producer_version": "1",
                "source": "integration",
                "created_at": SHARED_CREATED_AT,
            },
        )
        # Also store a raw object sidecar under the revision dir for byte checks.
        object_path = Path(result.path) / "shared_object.bin"
        object_path.write_bytes(SHARED_OBJECT_BYTES)
        return WrittenRevision(
            profile=profile,
            revision_id=result.revision_id,
            manifest_cid=result.manifest.get("root_cid") or result.manifest.get("checksum", {}).get(
                "hex_digest"
            ),
            object_cid=None,
            object_bytes=SHARED_OBJECT_BYTES,
            manifest_checksum=result.manifest["checksum"]["hex_digest"],
            revision_path=result.path,
            partition_checksums={
                name: part.checksum for name, part in result.partitions.items()
            },
        )

    # CID-addressed profiles: store canonical DAG-CBOR manifest + raw object.
    man = _shared_manifest(profile)
    put = adapter.put_manifest(man)
    obj = adapter.put(SHARED_OBJECT_BYTES, codec="raw", pin=True)
    adapter.pin(put.cid)
    return WrittenRevision(
        profile=profile,
        revision_id=SHARED_REVISION_ID,
        manifest_cid=put.cid,
        object_cid=obj.cid,
        object_bytes=SHARED_OBJECT_BYTES,
        manifest_checksum=man.checksum.hex_digest,
        revision_path=None,
        partition_checksums=None,
    )


def _verify_after_restart(adapter: Any, written: WrittenRevision) -> Dict[str, Any]:
    """Load canonical manifest + object bytes from a freshly opened adapter."""
    profile = written.profile
    if profile == "parquet":
        assert adapter.has_revision(
            SHARED_TENANT, SHARED_GRAPH_ID, written.revision_id
        )
        report = adapter.verify_revision(
            SHARED_TENANT, SHARED_GRAPH_ID, written.revision_id
        )
        assert report["ok"] is True
        handle = adapter.open_revision(
            SHARED_TENANT, SHARED_GRAPH_ID, written.revision_id, verify=True
        )
        man = handle.manifest
        assert man["revision_id"] == written.revision_id
        assert man["tenant"] == SHARED_TENANT
        assert man["graph_id"] == SHARED_GRAPH_ID
        assert man["storage_profile"] == "parquet"
        assert man["checksum"]["hex_digest"] == written.manifest_checksum
        assert man["counts"]["node_count"] == 3
        assert man["counts"]["edge_count"] == 2
        # Canonical partition checksums survive restart.
        for name, expected in (written.partition_checksums or {}).items():
            assert handle.checksums[f"{name}.parquet"] == expected
        nodes = handle.scan_nodes()
        assert {n["id"] for n in nodes} == {"n1", "n2", "n3"}
        # Sidecar object bytes.
        obj_path = Path(written.revision_path or "") / "shared_object.bin"
        assert obj_path.is_file()
        assert obj_path.read_bytes() == written.object_bytes
        return man

    assert written.manifest_cid is not None
    assert written.object_cid is not None
    man = adapter.get_manifest(written.manifest_cid)
    assert man["revision_id"] == written.revision_id
    assert man["tenant"] == SHARED_TENANT
    assert man["graph_id"] == SHARED_GRAPH_ID
    assert man["storage_profile"] == profile
    assert man["checksum"]["hex_digest"] == written.manifest_checksum
    assert man["counts"]["node_count"] == 3
    assert man["counts"]["edge_count"] == 2
    # Object bytes verified against CID on fetch.
    assert adapter.get(written.object_cid) == written.object_bytes
    assert adapter.is_pinned(written.manifest_cid) is True
    st = adapter.stat(written.manifest_cid)
    assert st.pinned is True
    assert st.size > 0
    return man


def _block_path(root: Path, cid: str) -> Path:
    return root / "blocks" / f"{cid}.bin"


def _corrupt_path_bytes(path: Path, mode: str) -> None:
    raw = path.read_bytes()
    if mode == "truncate":
        path.write_bytes(raw[: max(1, len(raw) // 4)])
    elif mode == "corrupt":
        data = bytearray(raw)
        mid = len(data) // 2
        data[mid] = (data[mid] + 1) % 256
        # If file is short, force a clear mismatch.
        if len(data) < 4:
            path.write_bytes(b"XXXX")
        else:
            path.write_bytes(bytes(data))
    else:
        raise AssertionError(f"unknown corruption mode: {mode!r}")


def _open_service(tmp_path: Path, profile: str) -> GraphService:
    catalog_path = tmp_path / f"kg-{profile}.sqlite"
    storage_path = tmp_path / f"kg-{profile}-payloads"
    return GraphService.open(catalog_path, storage_path=storage_path)


# ---------------------------------------------------------------------------
# Shared revision restart round-trip (all profiles)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", STORAGE_PROFILES)
def test_profile_restart_round_trip_deterministic(tmp_path: Path, profile: str) -> None:
    """Each profile: write → close → reopen → verify manifest + object bytes."""
    root = tmp_path / f"adapter-{profile}"
    adapter = _open_adapter(profile, root)
    try:
        written = _write_shared_revision(adapter, profile)
    finally:
        adapter.close()

    # Brand-new adapter instance over the same durable root (process restart).
    adapter2 = _open_adapter(profile, root)
    try:
        man = _verify_after_restart(adapter2, written)
        assert man["revision_id"] == SHARED_REVISION_ID
    finally:
        adapter2.close()


def test_all_profiles_share_one_logical_revision_round_trip(tmp_path: Path) -> None:
    """Single shared revision content exercised through every profile.

    Proves the three adapters honor the same logical identity (tenant / graph /
    revision / counts / provenance) after independent restarts.
    """
    results: Dict[str, Dict[str, Any]] = {}
    for profile in STORAGE_PROFILES:
        root = tmp_path / f"multi-{profile}"
        adapter = _open_adapter(profile, root)
        try:
            written = _write_shared_revision(adapter, profile)
        finally:
            adapter.close()
        adapter2 = _open_adapter(profile, root)
        try:
            man = _verify_after_restart(adapter2, written)
            results[profile] = {
                "revision_id": man["revision_id"],
                "tenant": man["tenant"],
                "graph_id": man["graph_id"],
                "node_count": man["counts"]["node_count"],
                "edge_count": man["counts"]["edge_count"],
                "producer_id": man["provenance"]["producer_id"],
                "storage_profile": man["storage_profile"],
            }
        finally:
            adapter2.close()

    assert set(results) == set(STORAGE_PROFILES)
    # Shared logical fields must agree across profiles.
    for profile, snap in results.items():
        assert snap["revision_id"] == SHARED_REVISION_ID
        assert snap["tenant"] == SHARED_TENANT
        assert snap["graph_id"] == SHARED_GRAPH_ID
        assert snap["node_count"] == 3
        assert snap["edge_count"] == 2
        assert snap["producer_id"] == SHARED_PRODUCER
        assert snap["storage_profile"] == profile


# ---------------------------------------------------------------------------
# Recreate adapter AND GraphService between write and read
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", STORAGE_PROFILES)
def test_adapter_and_service_restart_round_trip(tmp_path: Path, profile: str) -> None:
    """Write via adapter + catalog service; recreate both; verify head + bytes."""
    adapter_root = tmp_path / f"svc-adapter-{profile}"
    catalog_path = tmp_path / f"svc-{profile}.sqlite"
    storage_path = tmp_path / f"svc-{profile}-payloads"

    svc = GraphService.open(catalog_path, storage_path=storage_path)
    adapter = _open_adapter(profile, adapter_root)
    try:
        target = GraphTarget(
            tenant=SHARED_TENANT,
            graph_id=SHARED_GRAPH_ID,
            branch="main",
            storage_profile=profile,
        )
        created = svc.create(
            target,
            idempotency_key=f"create-{profile}",
            params={"graph_kind": "knowledge"},
        )
        assert created.ok, created.to_json_dict()
        boot = created.result["revision"]
        assert created.result["storage_profile"] == profile

        written = _write_shared_revision(adapter, profile)

        if profile == "parquet":
            man = adapter.get_manifest(
                SHARED_TENANT, SHARED_GRAPH_ID, written.revision_id
            )
            manifest_cid = man.get("root_cid") or man["checksum"]["hex_digest"]
            pin_root = manifest_cid
            checksum = man["checksum"]["hex_digest"]
            manifest_json = json.dumps(man, sort_keys=True, separators=(",", ":"))
        else:
            assert written.manifest_cid is not None
            man_obj = _shared_manifest(profile, parent_revision=boot)
            # Re-store with parent_revision so catalog parent matches bootstrap.
            put = adapter.put_manifest(man_obj)
            adapter.pin(put.cid)
            written = WrittenRevision(
                profile=profile,
                revision_id=SHARED_REVISION_ID,
                manifest_cid=put.cid,
                object_cid=written.object_cid,
                object_bytes=written.object_bytes,
                manifest_checksum=man_obj.checksum.hex_digest,
            )
            manifest_cid = put.cid
            pin_root = put.cid
            checksum = man_obj.checksum.hex_digest
            manifest_json = man_obj.to_json()

        svc.catalog.put_revision(
            SHARED_TENANT,
            SHARED_GRAPH_ID,
            written.revision_id,
            parent_revision=boot,
            manifest_cid=manifest_cid,
            manifest_json=manifest_json,
            pin_root=pin_root,
            checksum=checksum,
        )
        cas = svc.catalog.cas_set_head(
            SHARED_TENANT,
            SHARED_GRAPH_ID,
            "main",
            expected_revision=boot,
            new_revision=written.revision_id,
            pin_root=pin_root,
            idempotency_key=f"cas-{profile}-{written.revision_id}",
        )
        assert cas.head_revision == written.revision_id
        # Capture durable keys before teardown.
        expected_manifest_cid = manifest_cid
        expected_object_cid = written.object_cid
        expected_checksum = checksum
    finally:
        adapter.close()
        svc.close()

    # Full restart: brand-new service + brand-new adapter (no shared caches).
    svc2 = GraphService.open(catalog_path, storage_path=storage_path)
    adapter2 = _open_adapter(profile, adapter_root)
    try:
        assert svc2._open_handles == {}  # noqa: SLF001 — no ambient graph
        branch = svc2.catalog.get_branch(SHARED_TENANT, SHARED_GRAPH_ID, "main")
        assert branch.head_revision == SHARED_REVISION_ID
        rev = svc2.catalog.get_revision(
            SHARED_TENANT, SHARED_GRAPH_ID, SHARED_REVISION_ID
        )
        assert rev.manifest_cid == expected_manifest_cid
        assert rev.pin_root == expected_manifest_cid
        assert rev.checksum == expected_checksum

        opened = svc2.open_graph(
            GraphTarget(
                tenant=SHARED_TENANT,
                graph_id=SHARED_GRAPH_ID,
                branch="main",
                storage_profile=profile,
            )
        )
        assert opened.ok, opened.to_json_dict()
        assert opened.result["revision"] == SHARED_REVISION_ID
        assert opened.result["storage_profile"] == profile

        if profile == "parquet":
            man = _verify_after_restart(
                adapter2,
                WrittenRevision(
                    profile=profile,
                    revision_id=SHARED_REVISION_ID,
                    manifest_cid=expected_manifest_cid,
                    object_cid=None,
                    object_bytes=SHARED_OBJECT_BYTES,
                    manifest_checksum=expected_checksum,
                    revision_path=str(
                        adapter2.revision_dir(
                            SHARED_TENANT, SHARED_GRAPH_ID, SHARED_REVISION_ID
                        )
                    ),
                    partition_checksums=None,
                ),
            )
            # partition checksums may be empty in this reconstruction — still
            # verify_revision / open_revision already enforced integrity above
            # via has_revision path; re-run verify explicitly.
            report = adapter2.verify_revision(
                SHARED_TENANT, SHARED_GRAPH_ID, SHARED_REVISION_ID
            )
            assert report["ok"] is True
            assert man["checksum"]["hex_digest"] == expected_checksum
        else:
            man = adapter2.get_manifest(expected_manifest_cid)
            assert man["revision_id"] == SHARED_REVISION_ID
            assert man["checksum"]["hex_digest"] == expected_checksum
            assert adapter2.get(expected_object_cid) == SHARED_OBJECT_BYTES
            assert adapter2.is_pinned(expected_manifest_cid) is True
    finally:
        adapter2.close()
        svc2.close()


# ---------------------------------------------------------------------------
# Corrupt / truncated persisted data fails closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", STORAGE_PROFILES)
@pytest.mark.parametrize("mode", ("corrupt", "truncate"))
def test_corrupt_or_truncated_data_fails_closed(
    tmp_path: Path, profile: str, mode: str
) -> None:
    """After restart, tampered durable bytes must raise INTEGRITY (fail closed)."""
    root = tmp_path / f"corrupt-{profile}-{mode}"
    adapter = _open_adapter(profile, root)
    try:
        written = _write_shared_revision(adapter, profile)
    finally:
        adapter.close()

    if profile == "parquet":
        # Tamper a partition file on disk (nodes.parquet).
        assert written.revision_path is not None
        target = Path(written.revision_path) / "nodes.parquet"
        assert target.is_file()
        _corrupt_path_bytes(target, mode)
        # detect helper also surfaces truncation / bad magic without open.
        if mode == "truncate":
            kind = detect_parquet_corruption(target)
            assert kind is not None
            assert kind != "OK"
    else:
        # Tamper the raw object block so CID verification fails on fetch.
        assert written.object_cid is not None
        target = _block_path(root, written.object_cid)
        assert target.is_file(), f"missing block file: {target}"
        _corrupt_path_bytes(target, mode)

    adapter2 = _open_adapter(profile, root)
    try:
        if profile == "parquet":
            # Full integrity verification must fail closed on tamper.
            with pytest.raises(IntegrityError) as ei:
                adapter2.verify_revision(
                    SHARED_TENANT, SHARED_GRAPH_ID, written.revision_id
                )
            assert ei.value.code == "INTEGRITY"
            assert ei.value.retryable is False
            # Truncation / unreadable magic also rejects scan; subtle mid-file
            # bit flips may still decode but remain caught by verify above.
            if mode == "truncate":
                with pytest.raises(IntegrityError) as ei2:
                    adapter2.scan_nodes(
                        SHARED_TENANT, SHARED_GRAPH_ID, written.revision_id
                    )
                assert ei2.value.code == "INTEGRITY"
            else:
                # Force an unreadable partition and prove scan fails closed too.
                assert written.revision_path is not None
                bad = Path(written.revision_path) / "nodes.parquet"
                bad.write_bytes(b"PAR1XXXXPAR1")
                with pytest.raises(IntegrityError) as ei3:
                    adapter2.scan_nodes(
                        SHARED_TENANT, SHARED_GRAPH_ID, written.revision_id
                    )
                assert ei3.value.code == "INTEGRITY"
        else:
            assert written.object_cid is not None
            with pytest.raises(IntegrityError) as ei:
                adapter2.get(written.object_cid)
            assert ei.value.code == "INTEGRITY"
            assert ei.value.cause_code == "CID_MISMATCH"
            assert ei.value.retryable is False
    finally:
        adapter2.close()


@pytest.mark.parametrize("profile", ("ipfs_ipld", "ipfs_kit"))
def test_cid_profile_manifest_corruption_fails_closed(
    tmp_path: Path, profile: str
) -> None:
    """Corrupt the DAG-CBOR manifest block itself; reopen must fail closed."""
    root = tmp_path / f"man-corrupt-{profile}"
    adapter = _open_adapter(profile, root)
    try:
        written = _write_shared_revision(adapter, profile)
        assert written.manifest_cid is not None
        manifest_cid = written.manifest_cid
    finally:
        adapter.close()

    path = _block_path(root, manifest_cid)
    assert path.is_file()
    path.write_bytes(b"NOT-A-VALID-DAG-CBOR-MANIFEST")

    adapter2 = _open_adapter(profile, root)
    try:
        with pytest.raises(IntegrityError) as ei:
            adapter2.get_manifest(manifest_cid)
        assert ei.value.code == "INTEGRITY"
        assert ei.value.retryable is False
    finally:
        adapter2.close()


def test_parquet_truncated_manifest_json_fails_closed(tmp_path: Path) -> None:
    """Truncated parquet revision control files must not load silently."""
    root = tmp_path / "parquet-man-trunc"
    adapter = ParquetGraphStore.open(root, row_group_size=4)
    try:
        written = _write_shared_revision(adapter, "parquet")
    finally:
        adapter.close()

    assert written.revision_path is not None
    man_path = Path(written.revision_path) / "manifest.json"
    raw = man_path.read_text(encoding="utf-8")
    man_path.write_text(raw[: max(8, len(raw) // 5)], encoding="utf-8")

    adapter2 = ParquetGraphStore.open(root, row_group_size=4)
    try:
        with pytest.raises(
            (ParquetGraphStoreError, json.JSONDecodeError, ValueError, OSError)
        ):
            # Prefer typed GraphStoreError when the store wraps parse failures.
            try:
                adapter2.get_manifest(
                    SHARED_TENANT, SHARED_GRAPH_ID, written.revision_id
                )
                # If get_manifest returns, force verify which must fail closed.
                adapter2.verify_revision(
                    SHARED_TENANT, SHARED_GRAPH_ID, written.revision_id
                )
                raise AssertionError("truncated manifest must not verify cleanly")
            except ParquetGraphStoreError:
                raise
    finally:
        adapter2.close()


# ---------------------------------------------------------------------------
# Service-level fail-closed: head survives but corrupt payload is rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", ("ipfs_ipld", "ipfs_kit"))
def test_service_reopen_rejects_corrupt_adapter_payload(
    tmp_path: Path, profile: str
) -> None:
    """Catalog head remains, but adapter refuse corrupt CID payload after restart."""
    adapter_root = tmp_path / f"svc-corrupt-{profile}"
    catalog_path = tmp_path / f"svc-c-{profile}.sqlite"
    storage_path = tmp_path / f"svc-c-{profile}-payloads"

    svc = GraphService.open(catalog_path, storage_path=storage_path)
    adapter = _open_adapter(profile, adapter_root)
    try:
        target = GraphTarget(
            tenant=SHARED_TENANT,
            graph_id=SHARED_GRAPH_ID,
            branch="main",
            storage_profile=profile,
        )
        created = svc.create(target, idempotency_key=f"c-{profile}")
        assert created.ok
        boot = created.result["revision"]
        written = _write_shared_revision(adapter, profile)
        assert written.manifest_cid is not None
        man = _shared_manifest(profile, parent_revision=boot)
        put = adapter.put_manifest(man)
        adapter.pin(put.cid)
        svc.catalog.put_revision(
            SHARED_TENANT,
            SHARED_GRAPH_ID,
            SHARED_REVISION_ID,
            parent_revision=boot,
            manifest_cid=put.cid,
            manifest_json=man.to_json(),
            pin_root=put.cid,
            checksum=man.checksum.hex_digest,
        )
        svc.catalog.cas_set_head(
            SHARED_TENANT,
            SHARED_GRAPH_ID,
            "main",
            expected_revision=boot,
            new_revision=SHARED_REVISION_ID,
            pin_root=put.cid,
            idempotency_key=f"cas-c-{profile}",
        )
        object_cid = written.object_cid
        manifest_cid = put.cid
    finally:
        adapter.close()
        svc.close()

    # Corrupt object payload on durable medium.
    assert object_cid is not None
    _corrupt_path_bytes(_block_path(adapter_root, object_cid), "corrupt")

    svc2 = GraphService.open(catalog_path, storage_path=storage_path)
    adapter2 = _open_adapter(profile, adapter_root)
    try:
        # Control plane still knows the head (catalog is independent of payload).
        branch = svc2.catalog.get_branch(SHARED_TENANT, SHARED_GRAPH_ID, "main")
        assert branch.head_revision == SHARED_REVISION_ID
        opened = svc2.open_graph(
            GraphTarget(
                tenant=SHARED_TENANT,
                graph_id=SHARED_GRAPH_ID,
                branch="main",
                storage_profile=profile,
            )
        )
        assert opened.ok
        # Payload path fails closed.
        with pytest.raises(IntegrityError) as ei:
            adapter2.get(object_cid)
        assert ei.value.code == "INTEGRITY"
        # Manifest block still good (we only corrupted the object).
        loaded = adapter2.get_manifest(manifest_cid)
        assert loaded["revision_id"] == SHARED_REVISION_ID
    finally:
        adapter2.close()
        svc2.close()


# ---------------------------------------------------------------------------
# Profile constants / factory surface (deterministic)
# ---------------------------------------------------------------------------


def test_storage_profile_constants() -> None:
    assert ParquetGraphStore.storage_profile == "parquet"
    assert IPLDGraphStore.storage_profile == "ipfs_ipld"
    assert IpfsKitGraphStore.storage_profile == "ipfs_kit"


def test_idempotent_content_addressed_puts(tmp_path: Path) -> None:
    """IPLD + kit doubles: identical payloads yield identical CIDs across reopen."""
    for profile, open_fn in (
        ("ipfs_ipld", lambda r: IPLDGraphStore.open_directory(r)),
        ("ipfs_kit", lambda r: IpfsKitGraphStore.open_directory(r)),
    ):
        root = tmp_path / f"idemp-{profile}"
        s1 = open_fn(root)
        try:
            a = s1.put(SHARED_OBJECT_BYTES, codec="raw", pin=True)
            b = s1.put(SHARED_OBJECT_BYTES, codec="raw", pin=True)
            assert a.cid == b.cid
            cid = a.cid
        finally:
            s1.close()
        s2 = open_fn(root)
        try:
            c = s2.put(SHARED_OBJECT_BYTES, codec="raw", pin=True)
            assert c.cid == cid
            assert s2.get(cid) == SHARED_OBJECT_BYTES
        finally:
            s2.close()


# ---------------------------------------------------------------------------
# Optional live-daemon coverage (additive — never replaces deterministic proof)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not kubo_available(), reason="Kubo daemon / ipfs CLI not available")
def test_optional_kubo_daemon_restart_read_additive() -> None:
    """Additive live-daemon path for ipfs_ipld; deterministic tests remain primary."""
    man = _shared_manifest("ipfs_ipld", revision_id="rev-daemon-001")
    expected_checksum = man.checksum.hex_digest
    store = IPLDGraphStore.open_kubo(pin_by_default=True)
    try:
        put = store.put_manifest(man)
        obj = store.put(SHARED_OBJECT_BYTES, codec="raw", pin=True)
        store.pin(put.cid)
        cid_m, cid_o = put.cid, obj.cid
    finally:
        store.close()

    # Fresh client against the same durable daemon.
    store2 = IPLDGraphStore.open_kubo()
    try:
        loaded = store2.get_manifest(cid_m)
        assert loaded["revision_id"] == "rev-daemon-001"
        assert loaded["checksum"]["hex_digest"] == expected_checksum
        assert store2.get(cid_o) == SHARED_OBJECT_BYTES
        assert store2.is_pinned(cid_m) is True
    finally:
        store2.close()


@pytest.mark.skipif(
    not kit_package_available(),
    reason="ipfs_kit_py package not available / disabled",
)
def test_optional_ipfs_kit_package_path_additive() -> None:
    """Additive kit package path when present; doubles remain the contract proof.

    Live kit runtimes are often incomplete in CI (missing daemon attributes).
    This path only exercises successful puts when the runtime actually works;
    any STORAGE / NOT_IMPLEMENTED failure is an allowed skip — deterministic
    doubles above remain the authoritative restart/corruption proof.
    """
    try:
        store = IpfsKitGraphStore.open_kit(require_full_capabilities=False)
    except GraphStoreError as exc:
        assert exc.code in {"STORAGE", "NOT_IMPLEMENTED"}
        pytest.skip(f"ipfs_kit runtime unavailable: {exc}")
    try:
        report = store.report_capabilities()
        assert "missing" in report or "fully_capable" in report
        if not report.get("fully_capable"):
            pytest.skip(f"ipfs_kit capabilities incomplete: {report.get('missing')}")
        try:
            put = store.put(SHARED_OBJECT_BYTES, codec="raw", pin=False)
            assert store.get(put.cid) == SHARED_OBJECT_BYTES
        except GraphStoreError as exc:
            # Package importable but backend methods missing — additive only.
            assert exc.code in {"STORAGE", "NOT_IMPLEMENTED"}
            pytest.skip(f"ipfs_kit put/get unavailable at runtime: {exc}")
    finally:
        store.close()
