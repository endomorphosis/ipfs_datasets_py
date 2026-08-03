"""Unit tests for persistent content-addressed index snapshot contracts (PATLAW-144).

Covers:
* deterministic round-trips
* corrupt / cross-tenant manifests fail closed
* every record joins to a source CID and version
* resume, tombstone, compaction, rollback retain immutable prior roots
* unknown model or schema versions cannot open a snapshot
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.index_snapshot_contracts import (
    INDEX_SNAPSHOT_CODE_VERSION,
    INDEX_SNAPSHOT_INTERFACE,
    INDEX_SNAPSHOT_SCHEMA_VERSION,
    INDEX_STORE_INTERFACE,
    KNOWN_MODEL_PINS,
    CheckpointCursor,
    CodeIdentity,
    ConfigIdentity,
    ContentAddress,
    CorpusIdentity,
    CorruptManifestError,
    CrossTenantManifestError,
    IndexFamily,
    IndexSnapshotError,
    IndexSnapshotManifest,
    IndexSnapshotRecord,
    MissingSourceJoinError,
    ModelIdentity,
    PartitionClass,
    PatentIndexSnapshot,
    RecordOp,
    RootPointer,
    SnapshotIdentityBundle,
    SnapshotImmutabilityError,
    SnapshotKind,
    SourceJoin,
    UnknownModelVersionError,
    UnknownSchemaVersionError,
    assert_known_model_pin,
    assert_known_schema_version,
    build_tombstone_record,
    canonical_json,
    content_digest_of,
    default_code_identity,
    open_snapshot_payload,
)
from ipfs_datasets_py.processors.domains.patent.index_store import (
    CheckpointNotFoundError,
    PatentIndexStore,
    SnapshotNotFoundError,
    TenantSeparationError,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
    DisclosureClass,
    SourceSpan,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
CID_CORPUS = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
CID_SOURCE = "bafybeic3g5s5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x"
CID_CONFIG = "bafybeihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku"
CID_MANIFEST = "bafybeimanifest0000000000000000000000000000000000000000001"
TENANT = "tenant-public"
TENANT_OTHER = "tenant-other"
CREATED = "2024-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _source_join(**overrides: object) -> SourceJoin:
    base: dict[str, object] = {
        "source_cid": CID_SOURCE,
        "source_version": "v2024.1",
        "artifact_id": "artifact:us-patent-1",
        "span": SourceSpan(start=0, end=12),
        "source_receipt_id": "receipt:1",
        "authority_tier": "official-base",
    }
    base.update(overrides)
    return SourceJoin(**base)  # type: ignore[arg-type]


def _identities(*, with_model: bool = False) -> SnapshotIdentityBundle:
    model = ModelIdentity.default_local_hashed() if with_model else None
    return SnapshotIdentityBundle(
        schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
        corpus=CorpusIdentity(
            corpus_cid=CID_CORPUS,
            corpus_digest=DIGEST_A,
            source_manifest_cid=CID_MANIFEST,
            corpus_version="corpus-2024.06",
            record_count=1,
        ),
        code=default_code_identity(code_digest=DIGEST_B),
        config=ConfigIdentity(
            config_cid=CID_CONFIG,
            config_digest=DIGEST_C,
            field_weights_config_cid=CID_CONFIG,
        ),
        model=model,
    )


def _record(
    *,
    record_id: str = "row:1",
    document_id: str = "doc:patent-1",
    family: IndexFamily = IndexFamily.BM25,
    tenant_id: str = TENANT,
    disclosure: DisclosureClass = DisclosureClass.PUBLIC_OFFICIAL,
    content_digest: str | None = None,
    op: RecordOp = RecordOp.UPSERT,
    **overrides: object,
) -> IndexSnapshotRecord:
    digest = content_digest or content_digest_of(
        {"document_id": document_id, "record_id": record_id, "family": family.value}
    )
    base: dict[str, object] = {
        "schema_version": INDEX_SNAPSHOT_SCHEMA_VERSION,
        "record_id": record_id,
        "document_id": document_id,
        "family": family,
        "op": op,
        "source_joins": (_source_join(),),
        "disclosure": disclosure,
        "tenant_id": tenant_id,
        "content_digest": digest,
        "payload_digest": DIGEST_A,
        "effective_from_utc": "2020-01-01T00:00:00Z",
    }
    base.update(overrides)
    return IndexSnapshotRecord(**base)  # type: ignore[arg-type]


def _snapshot(
    *,
    snapshot_id: str = "snap:1",
    tenant_id: str = TENANT,
    records: tuple[IndexSnapshotRecord, ...] | None = None,
    families: tuple[IndexFamily, ...] = (IndexFamily.BM25,),
    with_model: bool = False,
    kind: SnapshotKind = SnapshotKind.FULL,
    parent_root: RootPointer | None = None,
    compaction_root: RootPointer | None = None,
    rollback_root: RootPointer | None = None,
    prior_roots: tuple[RootPointer, ...] = (),
    partition: PartitionClass = PartitionClass.PUBLIC,
) -> PatentIndexSnapshot:
    recs = records if records is not None else (_record(tenant_id=tenant_id),)
    if IndexFamily.VECTOR in families:
        with_model = True
    tombstones = sum(1 for r in recs if r.is_tombstone())
    active = len(recs) - tombstones
    disclosures = tuple(sorted({r.disclosure for r in recs}, key=lambda d: d.value))
    manifest = IndexSnapshotManifest(
        schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
        snapshot_id=snapshot_id,
        tenant_id=tenant_id,
        partition=partition,
        kind=kind,
        identities=_identities(with_model=with_model),
        families=families,
        record_count=len(recs),
        tombstone_count=tombstones,
        active_record_count=active,
        created_utc=CREATED,
        parent_root=parent_root,
        compaction_root=compaction_root,
        rollback_root=rollback_root,
        prior_roots=prior_roots,
        allowed_disclosures=disclosures,
    )
    return PatentIndexSnapshot(manifest=manifest, records=recs)


def _assert_round_trip(record: object) -> None:
    assert hasattr(record, "to_dict") and hasattr(type(record), "from_dict")
    first = record.to_dict()  # type: ignore[attr-defined]
    restored = type(record).from_dict(first)  # type: ignore[attr-defined]
    second = restored.to_dict()  # type: ignore[attr-defined]
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    assert (
        json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        == canonical_json(first)
    )
    assert restored == record


# ---------------------------------------------------------------------------
# Schema / identity pins
# ---------------------------------------------------------------------------


def test_schema_and_interface_pins() -> None:
    assert INDEX_SNAPSHOT_SCHEMA_VERSION == "patent.index_snapshot.v1"
    assert INDEX_SNAPSHOT_INTERFACE == "PatentIndexSnapshot@1"
    assert INDEX_STORE_INTERFACE == "PatentIndexStore@1"
    assert INDEX_SNAPSHOT_CODE_VERSION == "1.0.0"
    assert "local-hashed-term-projection@1.0.0" in KNOWN_MODEL_PINS


def test_assert_known_schema_version_fail_closed() -> None:
    assert (
        assert_known_schema_version(INDEX_SNAPSHOT_SCHEMA_VERSION)
        == INDEX_SNAPSHOT_SCHEMA_VERSION
    )
    with pytest.raises(UnknownSchemaVersionError):
        assert_known_schema_version("patent.index_snapshot.v999")


def test_assert_known_model_pin_fail_closed() -> None:
    assert_known_model_pin("local-hashed-term-projection@1.0.0")
    with pytest.raises(UnknownModelVersionError):
        assert_known_model_pin("remote-openai-text-embedding-3@latest")


def test_model_identity_rejects_unknown_pin() -> None:
    with pytest.raises(UnknownModelVersionError):
        ModelIdentity(
            model_pin="not-a-known-pin@9.9.9",
            provider="remote",
            model_id="x",
            model_version="9.9.9",
            dimension=8,
            config_cid=CID_CONFIG,
        )


# ---------------------------------------------------------------------------
# Deterministic round-trips
# ---------------------------------------------------------------------------


def test_source_join_requires_cid_and_version() -> None:
    join = _source_join()
    _assert_round_trip(join)
    assert join.source_cid == CID_SOURCE
    assert join.source_version == "v2024.1"
    with pytest.raises(ValueError, match="source_version"):
        SourceJoin(
            source_cid=CID_SOURCE,
            source_version="",
            artifact_id="artifact:1",
        )


def test_index_snapshot_record_round_trip() -> None:
    rec = _record()
    _assert_round_trip(rec)
    assert rec.source_joins[0].source_cid
    assert rec.source_joins[0].source_version


def test_record_rejects_missing_source_joins() -> None:
    with pytest.raises(MissingSourceJoinError):
        IndexSnapshotRecord(
            schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
            record_id="row:x",
            document_id="doc:x",
            family=IndexFamily.BM25,
            op=RecordOp.UPSERT,
            source_joins=(),
            disclosure=DisclosureClass.PUBLIC_OFFICIAL,
            tenant_id=TENANT,
            content_digest=DIGEST_A,
        )


def test_manifest_and_snapshot_round_trip_deterministic() -> None:
    snap = _snapshot()
    _assert_round_trip(snap.manifest)
    _assert_round_trip(snap)
    addr1 = snap.content_address()
    addr2 = PatentIndexSnapshot.from_dict(snap.to_dict()).content_address()
    assert addr1 == addr2
    assert addr1.sha256 == content_digest_of(snap.to_dict())
    # Byte-identical canonical encoding.
    assert snap.to_canonical_json() == PatentIndexSnapshot.from_dict(
        snap.to_dict()
    ).to_canonical_json()


def test_content_address_stable_across_key_order() -> None:
    snap = _snapshot()
    payload = snap.to_dict()
    # Reconstruct with shuffled dict insertion order.
    reshuffled = {
        "records": payload["records"],
        "schema_version": payload["schema_version"],
        "manifest": payload["manifest"],
    }
    a = ContentAddress.from_payload(payload)
    b = ContentAddress.from_payload(reshuffled)
    assert a.sha256 == b.sha256
    assert a.cid == b.cid


def test_checkpoint_cursor_round_trip() -> None:
    cur = CheckpointCursor(
        schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
        checkpoint_id="ckpt:1",
        tenant_id=TENANT,
        shard_id="shard-0",
        offset=42,
        prior_root_cid=CID_CORPUS,
        prior_root_digest=DIGEST_A,
        last_record_id="row:1",
        incomplete=True,
        updated_utc=CREATED,
    )
    _assert_round_trip(cur)


def test_identity_bundle_round_trip() -> None:
    bundle = _identities(with_model=True)
    _assert_round_trip(bundle)
    assert bundle.model is not None
    assert bundle.model.model_pin in KNOWN_MODEL_PINS


# ---------------------------------------------------------------------------
# Fail-closed: corrupt / cross-tenant / unknown versions
# ---------------------------------------------------------------------------


def test_open_snapshot_unknown_schema_fails_closed() -> None:
    snap = _snapshot()
    payload = snap.to_dict()
    payload["schema_version"] = "patent.index_snapshot.v0-legacy"
    with pytest.raises(UnknownSchemaVersionError):
        open_snapshot_payload(payload)


def test_open_snapshot_unknown_model_fails_closed() -> None:
    snap = _snapshot(families=(IndexFamily.BM25, IndexFamily.VECTOR), with_model=True)
    payload = snap.to_dict()
    payload["manifest"]["identities"]["model"]["model_pin"] = "unknown-model@0.0.1"
    with pytest.raises(UnknownModelVersionError):
        open_snapshot_payload(payload)


def test_open_snapshot_missing_schema_fails_closed() -> None:
    with pytest.raises(CorruptManifestError, match="schema_version"):
        open_snapshot_payload({"manifest": {}, "records": []})


def test_open_snapshot_cross_tenant_fails_closed() -> None:
    snap = _snapshot(tenant_id=TENANT)
    with pytest.raises(CrossTenantManifestError):
        open_snapshot_payload(snap.to_dict(), expected_tenant_id=TENANT_OTHER)


def test_snapshot_record_tenant_mismatch_fails_closed() -> None:
    rec = _record(tenant_id=TENANT_OTHER)
    with pytest.raises(CrossTenantManifestError):
        _snapshot(tenant_id=TENANT, records=(rec,))


def test_corrupt_count_parity_fails_closed() -> None:
    rec = _record()
    with pytest.raises(CorruptManifestError, match="active_record_count"):
        IndexSnapshotManifest(
            schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
            snapshot_id="snap:bad",
            tenant_id=TENANT,
            partition=PartitionClass.PUBLIC,
            kind=SnapshotKind.FULL,
            identities=_identities(),
            families=(IndexFamily.BM25,),
            record_count=2,
            tombstone_count=0,
            active_record_count=1,  # 1 + 0 != 2
            created_utc=CREATED,
        )
    # Manifest ok but snapshot log length mismatch.
    manifest = IndexSnapshotManifest(
        schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
        snapshot_id="snap:bad2",
        tenant_id=TENANT,
        partition=PartitionClass.PUBLIC,
        kind=SnapshotKind.FULL,
        identities=_identities(),
        families=(IndexFamily.BM25,),
        record_count=0,
        tombstone_count=0,
        active_record_count=0,
        created_utc=CREATED,
    )
    with pytest.raises(CorruptManifestError):
        PatentIndexSnapshot(manifest=manifest, records=(rec,))


def test_public_partition_rejects_private_records() -> None:
    rec = _record(disclosure=DisclosureClass.CONFIDENTIAL_APPLICATION)
    with pytest.raises(CorruptManifestError, match="private"):
        _snapshot(
            records=(rec,),
            partition=PartitionClass.PUBLIC,
        )


def test_vector_family_requires_model_identity() -> None:
    with pytest.raises(UnknownModelVersionError, match="vector"):
        IndexSnapshotManifest(
            schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
            snapshot_id="snap:vec",
            tenant_id=TENANT,
            partition=PartitionClass.PUBLIC,
            kind=SnapshotKind.FULL,
            identities=_identities(with_model=False),
            families=(IndexFamily.VECTOR,),
            record_count=0,
            tombstone_count=0,
            active_record_count=0,
            created_utc=CREATED,
        )


def test_corrupt_json_on_disk_fails_closed(tmp_path: Path) -> None:
    store = PatentIndexStore.open_for_tenant(tmp_path, TENANT)
    snap = _snapshot()
    put = store.put_snapshot(snap)
    path = store._snapshot_path(put.root_digest)  # noqa: SLF001 — test integrity
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(CorruptManifestError):
        store.get_snapshot(put.root_digest)


def test_digest_path_mismatch_fails_closed(tmp_path: Path) -> None:
    store = PatentIndexStore.open_for_tenant(tmp_path, TENANT)
    snap = _snapshot(snapshot_id="snap:a")
    put = store.put_snapshot(snap)
    # Overwrite file with a different valid snapshot while keeping path digest.
    other = _snapshot(snapshot_id="snap:b", records=(_record(record_id="row:2"),))
    path = store._snapshot_path(put.root_digest)  # noqa: SLF001
    path.write_bytes(other.to_canonical_bytes())
    with pytest.raises(CorruptManifestError, match="does not match"):
        store.get_snapshot(put.root_digest)


# ---------------------------------------------------------------------------
# Store: put / get / HEAD / immutability
# ---------------------------------------------------------------------------


def test_store_put_get_round_trip(tmp_path: Path) -> None:
    store = PatentIndexStore.open_for_tenant(tmp_path, TENANT)
    snap = _snapshot()
    put = store.put_snapshot(snap)
    assert put.created is True
    assert put.tenant_id == TENANT
    loaded = store.get_snapshot(put.root_digest)
    assert loaded == snap
    assert loaded.root_digest == put.root_digest
    assert loaded.root_cid == put.root_cid
    head = store.get_head()
    assert head is not None
    assert head["root_digest"] == put.root_digest
    assert store.open_snapshot().manifest.snapshot_id == snap.manifest.snapshot_id


def test_store_put_idempotent(tmp_path: Path) -> None:
    store = PatentIndexStore.open_for_tenant(tmp_path, TENANT)
    snap = _snapshot()
    first = store.put_snapshot(snap)
    second = store.put_snapshot(snap)
    assert first.root_digest == second.root_digest
    assert first.created is True
    assert second.created is False


def test_store_immutability_rejects_divergent_payload(tmp_path: Path) -> None:
    store = PatentIndexStore.open_for_tenant(tmp_path, TENANT)
    snap = _snapshot(snapshot_id="snap:1")
    put = store.put_snapshot(snap)
    # Craft a different snapshot forced into the same path by monkeypatching
    # is not needed — immutability is on digest path; different content gets
    # a different path. Simulate direct write conflict:
    path = store._snapshot_path(put.root_digest)  # noqa: SLF001
    other = _snapshot(snapshot_id="snap:other", records=(_record(record_id="row:9"),))
    # Direct put of other is fine (new digest). Overwrite path then put same digest:
    path.write_bytes(other.to_canonical_bytes())
    with pytest.raises(SnapshotImmutabilityError):
        store.put_snapshot(snap)


def test_cross_tenant_store_isolation(tmp_path: Path) -> None:
    store_a = PatentIndexStore.open_for_tenant(tmp_path, TENANT)
    store_b = PatentIndexStore.open_for_tenant(tmp_path, TENANT_OTHER)
    snap_a = _snapshot(tenant_id=TENANT)
    put_a = store_a.put_snapshot(snap_a)
    # Tenant B cannot open A's snapshot by digest (path is tenant-scoped).
    with pytest.raises(SnapshotNotFoundError):
        store_b.get_snapshot(put_a.root_digest)
    # Putting A's snapshot into B fails closed.
    with pytest.raises((TenantSeparationError, CrossTenantManifestError)):
        store_b.put_snapshot(snap_a)
    # Opening foreign payload fails.
    with pytest.raises((TenantSeparationError, CrossTenantManifestError)):
        store_b.put_snapshot(snap_a.to_dict())


def test_build_and_put_binds_source_joins(tmp_path: Path) -> None:
    store = PatentIndexStore.open_for_tenant(tmp_path, TENANT)
    rec = _record()
    put = store.build_and_put(
        snapshot_id="snap:build",
        identities=_identities(),
        records=(rec,),
        families=(IndexFamily.BM25,),
    )
    loaded = store.get_snapshot(put.root_digest)
    loaded.verify_source_joins()
    assert all(j.source_cid and j.source_version for r in loaded.records for j in r.source_joins)


def test_every_record_joins_to_source_cid_and_version(tmp_path: Path) -> None:
    store = PatentIndexStore.open_for_tenant(tmp_path, TENANT)
    records = (
        _record(record_id="row:1", document_id="doc:1"),
        _record(record_id="row:2", document_id="doc:2", family=IndexFamily.GRAPH),
    )
    put = store.build_and_put(
        snapshot_id="snap:joins",
        identities=_identities(),
        records=records,
        families=(IndexFamily.BM25, IndexFamily.GRAPH),
    )
    loaded = store.open_snapshot(put.root_digest)
    for rec in loaded.records:
        assert len(rec.source_joins) >= 1
        for join in rec.source_joins:
            assert join.source_cid.startswith("bafy")
            assert join.source_version


# ---------------------------------------------------------------------------
# Resume / tombstone / compaction / rollback retain prior roots
# ---------------------------------------------------------------------------


def test_checkpoint_resume_retains_prior_root(tmp_path: Path) -> None:
    store = PatentIndexStore.open_for_tenant(tmp_path, TENANT)
    snap = _snapshot(snapshot_id="snap:base")
    put = store.put_snapshot(snap)
    cur = CheckpointCursor(
        schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
        checkpoint_id="ckpt:resume-1",
        tenant_id=TENANT,
        shard_id="shard-0",
        offset=10,
        prior_root_cid=put.root_cid,
        prior_root_digest=put.root_digest,
        last_record_id="row:1",
        incomplete=True,
        updated_utc=CREATED,
    )
    store.put_checkpoint(cur)
    loaded_cur, loaded_snap = store.resume_from_checkpoint("ckpt:resume-1")
    assert loaded_cur.prior_root_digest == put.root_digest
    assert loaded_snap.root_digest == put.root_digest
    # Prior root still loadable after resume.
    assert store.contains(put.root_digest)
    assert store.get_snapshot(put.root_digest) == snap


def test_checkpoint_requires_durable_prior_root(tmp_path: Path) -> None:
    store = PatentIndexStore.open_for_tenant(tmp_path, TENANT)
    cur = CheckpointCursor(
        schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
        checkpoint_id="ckpt:missing",
        tenant_id=TENANT,
        shard_id="shard-0",
        offset=0,
        prior_root_cid=CID_CORPUS,
        prior_root_digest=DIGEST_A,
        incomplete=True,
    )
    with pytest.raises(SnapshotNotFoundError):
        store.put_checkpoint(cur)


def test_tombstone_retains_prior_content_and_root(tmp_path: Path) -> None:
    store = PatentIndexStore.open_for_tenant(tmp_path, TENANT)
    base = _snapshot(
        snapshot_id="snap:base",
        records=(
            _record(record_id="row:1"),
            _record(record_id="row:2", document_id="doc:2"),
        ),
    )
    base_put = store.put_snapshot(base)
    result = store.apply_tombstones(
        base=base_put.root_digest,
        record_ids=["row:1"],
        snapshot_id="snap:tomb",
        tombstoned_utc="2024-07-01T00:00:00Z",
    )
    new_snap = store.get_snapshot(result.root_digest)
    assert new_snap.manifest.tombstone_count == 1
    assert new_snap.manifest.active_record_count == 1
    tomb = next(r for r in new_snap.records if r.record_id == "row:1")
    assert tomb.is_tombstone()
    assert tomb.prior_content_digest is not None
    assert tomb.source_joins  # joins retained
    # Parent / prior roots retained and still loadable.
    assert new_snap.manifest.parent_root is not None
    assert new_snap.manifest.parent_root.root_digest == base_put.root_digest
    assert store.contains(base_put.root_digest)
    assert store.get_snapshot(base_put.root_digest) == base
    assert any(
        p.root_digest == base_put.root_digest for p in new_snap.manifest.prior_roots
    )


def test_build_tombstone_requires_prior_digest() -> None:
    prior = _record(record_id="row:1")
    tomb = build_tombstone_record(prior, tombstoned_utc="2024-07-01T00:00:00Z")
    assert tomb.op is RecordOp.TOMBSTONE
    assert tomb.prior_content_digest == prior.content_digest
    _assert_round_trip(tomb)
    with pytest.raises(IndexSnapshotError):
        build_tombstone_record(tomb, tombstoned_utc="2024-08-01T00:00:00Z")


def test_compaction_retains_compaction_root(tmp_path: Path) -> None:
    store = PatentIndexStore.open_for_tenant(tmp_path, TENANT)
    live = _record(record_id="row:live")
    dead_prior = _record(record_id="row:dead")
    tomb = build_tombstone_record(
        dead_prior, tombstoned_utc="2024-07-01T00:00:00Z"
    )
    base = _snapshot(
        snapshot_id="snap:with-tombs",
        records=(live, tomb),
    )
    base_put = store.put_snapshot(base)
    result = store.compact(
        base=base_put.root_digest,
        snapshot_id="snap:compacted",
        created_utc="2024-08-01T00:00:00Z",
    )
    compacted = store.get_snapshot(result.root_digest)
    assert compacted.manifest.kind is SnapshotKind.COMPACTION
    assert compacted.manifest.tombstone_count == 0
    assert compacted.manifest.active_record_count == 1
    assert len(compacted.records) == 1
    assert compacted.records[0].record_id == "row:live"
    assert compacted.manifest.compaction_root is not None
    assert compacted.manifest.compaction_root.root_digest == base_put.root_digest
    # Pre-compaction root still durable.
    assert store.contains(base_put.root_digest)
    assert store.get_snapshot(base_put.root_digest).manifest.tombstone_count == 1


def test_rollback_retains_target_and_previous_head(tmp_path: Path) -> None:
    store = PatentIndexStore.open_for_tenant(tmp_path, TENANT)
    v1 = _snapshot(snapshot_id="snap:v1", records=(_record(record_id="row:1"),))
    put1 = store.put_snapshot(v1)
    v2 = _snapshot(
        snapshot_id="snap:v2",
        records=(
            _record(record_id="row:1"),
            _record(record_id="row:2", document_id="doc:2"),
        ),
        parent_root=RootPointer(
            root_cid=put1.root_cid,
            root_digest=put1.root_digest,
            kind=SnapshotKind.FULL,
        ),
        prior_roots=(
            RootPointer(
                root_cid=put1.root_cid,
                root_digest=put1.root_digest,
                kind=SnapshotKind.FULL,
            ),
        ),
        kind=SnapshotKind.INCREMENTAL,
    )
    put2 = store.put_snapshot(v2)
    assert store.get_head() is not None
    assert store.get_head()["root_digest"] == put2.root_digest

    rb = store.rollback(
        target_root_digest=put1.root_digest,
        current=put2.root_digest,
        snapshot_id="snap:rollback-v1",
        created_utc="2024-09-01T00:00:00Z",
    )
    rolled = store.get_snapshot(rb.root_digest)
    assert rolled.manifest.kind is SnapshotKind.ROLLBACK
    assert rolled.manifest.rollback_root is not None
    assert rolled.manifest.rollback_root.root_digest == put1.root_digest
    # Both historical roots retained and loadable.
    assert store.contains(put1.root_digest)
    assert store.contains(put2.root_digest)
    assert store.get_snapshot(put1.root_digest) == v1
    assert store.get_snapshot(put2.root_digest) == v2
    # Active logical content matches the rollback target.
    assert {r.record_id for r in rolled.active_records()} == {"row:1"}
    retained = {p.root_digest for p in rolled.manifest.retained_prior_roots()}
    assert put1.root_digest in retained
    assert put2.root_digest in retained


def test_unknown_schema_cannot_open_head_meta(tmp_path: Path) -> None:
    store = PatentIndexStore.open_for_tenant(tmp_path, TENANT)
    snap = _snapshot()
    store.put_snapshot(snap)
    # Corrupt HEAD schema_version → fail closed on open.
    head_path = store._head_path  # noqa: SLF001
    head = json.loads(head_path.read_text(encoding="utf-8"))
    head["schema_version"] = "patent.index_snapshot.v-ancient"
    head_path.write_text(json.dumps(head), encoding="utf-8")
    with pytest.raises(UnknownSchemaVersionError):
        store.get_head()


def test_checkpoint_not_found(tmp_path: Path) -> None:
    store = PatentIndexStore.open_for_tenant(tmp_path, TENANT)
    with pytest.raises(CheckpointNotFoundError):
        store.get_checkpoint("ckpt:does-not-exist")


def test_safe_config_exposes_interface(tmp_path: Path) -> None:
    store = PatentIndexStore.open_for_tenant(tmp_path, TENANT)
    cfg = store.safe_config()
    assert cfg["interface"] == INDEX_STORE_INTERFACE
    assert cfg["schema_version"] == INDEX_SNAPSHOT_SCHEMA_VERSION
    assert cfg["tenant_id"] == TENANT


def test_code_identity_defaults() -> None:
    code = default_code_identity()
    assert code.code_version == INDEX_SNAPSHOT_CODE_VERSION
    assert code.interface == INDEX_SNAPSHOT_INTERFACE
    assert len(code.code_digest) == 64
    _assert_round_trip(code)


def test_root_pointer_round_trip() -> None:
    ptr = RootPointer(
        root_cid=CID_CORPUS,
        root_digest=DIGEST_A,
        kind=SnapshotKind.COMPACTION,
        retained_from_utc=CREATED,
        note="prior",
    )
    _assert_round_trip(ptr)
