"""Integration tests for persistent incremental BM25/vector/graph snapshots (PATLAW-146).

Acceptance coverage:
* Full and incremental builds converge on the same logical root
* Interrupted builds resume from durable checkpoints
* Every vector/BM25/graph record has exactly one allowed source join
* Private partitions remain encrypted and unpublishable
* Zero-orphan and deterministic-manifest tests pass
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.index_snapshot_contracts import (
    INDEX_SNAPSHOT_SCHEMA_VERSION,
    IndexFamily,
    OrphanRecordError,
    PartitionClass,
    SnapshotKind,
    SourceJoin,
    canonical_json,
    content_digest_of,
)
from ipfs_datasets_py.processors.domains.patent.index_store import PatentIndexStore
from ipfs_datasets_py.processors.domains.patent.indexing import PatentIndexDocument
from ipfs_datasets_py.processors.domains.patent.persistent_index_builder import (
    PERSISTENT_INDEX_BUILDER_INTERFACE,
    PERSISTENT_INDEX_BUILDER_SCHEMA_VERSION,
    PRIVATE_CIPHER_VERSION,
    PersistentIndexBuilder,
    PrivatePartitionPublishError,
    assert_unpublishable,
    collect_allowed_source_joins,
    compute_logical_root,
    decrypt_private_payload,
    deterministic_manifest_digest,
    encrypt_private_payload,
    is_publishable_partition,
    primary_source_join,
    verify_zero_orphans,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    DisclosureClass,
    PreRankingFilters,
    SourceLink,
    SourceSpan,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parents[3] / "fixtures" / "patent" / "index_snapshots"
)
GOLDEN_MANIFEST = FIXTURE_DIR / "golden_manifest.json"

CID_SOURCE_A = "bafybeic3g5s5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x"
CID_SOURCE_B = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
CID_SOURCE_C = "bafybeihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku"
CID_CORPUS = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
CID_CONFIG = "bafybeihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku"
TENANT = "tenant-public"
TENANT_PRIVATE = "tenant-private-1"
CREATED = "2024-06-01T00:00:00Z"
SOURCE_VERSION = "v2024.1"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _link(
    source_cid: str = CID_SOURCE_A,
    artifact_id: str = "artifact:1",
) -> SourceLink:
    return SourceLink(
        source_cid=source_cid,
        artifact_id=artifact_id,
        span=SourceSpan(start=0, end=24),
        authority_tier="official-base",
    )


def _filters(
    *,
    tenant: str = TENANT,
    applied: bool = True,
    disclosures: tuple[DisclosureClass, ...] | None = None,
) -> PreRankingFilters:
    allowed = disclosures or (
        DisclosureClass.PUBLIC_OFFICIAL,
        DisclosureClass.PUBLIC_USER,
    )
    return PreRankingFilters(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        tenant_id=tenant,
        as_of_utc=CREATED,
        allowed_disclosures=allowed,
        applied=applied,
        filter_receipt_id="filter:persistent-builder",
    )


def _doc(
    document_id: str,
    *,
    title: str,
    source_cid: str = CID_SOURCE_A,
    artifact_id: str | None = None,
    disclosure: DisclosureClass = DisclosureClass.PUBLIC_OFFICIAL,
    tenant_id: str = TENANT,
    claims: str = "1. A method comprising indexing patent claims.",
    source_version: str = SOURCE_VERSION,
) -> PatentIndexDocument:
    return PatentIndexDocument(
        document_id=document_id,
        field_values={
            "title": title,
            "abstract": f"Abstract for {title}",
            "claims": claims,
            "description": f"Description of {title} under 35 U.S.C. § 102.",
            "cpc": "G06F16/00",
            "ipc": "G06F16/00",
            "citations": "US10123456B2",
            "numbers": document_id.replace("doc:", "US"),
            "legal_bases": "35 U.S.C. § 102(a)(1)",
        },
        source_links=(
            _link(
                source_cid=source_cid,
                artifact_id=artifact_id or f"artifact:{document_id}",
            ),
        ),
        disclosure=disclosure,
        tenant_id=tenant_id,
        effective_from_utc="2020-01-01T00:00:00Z",
        effective_to_utc="2030-01-01T00:00:00Z",
        metadata={"source_version": source_version},
        claim_units=(claims,),
    )


def _public_docs() -> list[PatentIndexDocument]:
    return [
        _doc("doc:patent-encode", title="Method of encoding patent claims", source_cid=CID_SOURCE_A),
        _doc(
            "doc:patent-network",
            title="Network security apparatus",
            source_cid=CID_SOURCE_B,
            claims="1. An apparatus comprising a cipher module.",
        ),
        _doc(
            "doc:patent-graph",
            title="Graph expansion for prior art",
            source_cid=CID_SOURCE_C,
            claims="1. A method comprising expanding a citation graph.",
        ),
    ]


def _builder(tmp_path: Path, *, tenant: str = TENANT, **kwargs) -> PersistentIndexBuilder:
    store = PatentIndexStore.open_for_tenant(tmp_path / "index-store", tenant)
    return PersistentIndexBuilder(
        store,
        shard_size=kwargs.pop("shard_size", 1),
        default_source_version=SOURCE_VERSION,
        created_utc=CREATED,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Schema pins
# ---------------------------------------------------------------------------


def test_builder_schema_pins() -> None:
    assert PERSISTENT_INDEX_BUILDER_SCHEMA_VERSION == "patent.persistent_index_builder.v1"
    assert PERSISTENT_INDEX_BUILDER_INTERFACE == "PersistentIndexBuilder@1"


# ---------------------------------------------------------------------------
# Full == incremental logical root convergence
# ---------------------------------------------------------------------------


def test_full_and_incremental_converge_on_logical_root(tmp_path: Path) -> None:
    docs = _public_docs()
    filters = _filters()

    full_builder = _builder(tmp_path / "full")
    full = full_builder.build_full(
        docs,
        filters=filters,
        snapshot_id="snap:full",
        corpus_cid=CID_CORPUS,
        corpus_version="corpus-2024.06",
        config_cid=CID_CONFIG,
        created_utc=CREATED,
    )

    inc_builder = _builder(tmp_path / "inc")
    # Incremental path: first doc as full seed, then remaining as increments.
    first = inc_builder.build_full(
        docs[:1],
        filters=filters,
        snapshot_id="snap:inc-0",
        corpus_cid=CID_CORPUS,
        corpus_version="corpus-2024.06",
        config_cid=CID_CONFIG,
        created_utc=CREATED,
    )
    mid = inc_builder.build_incremental(
        docs[1:2],
        filters=filters,
        snapshot_id="snap:inc-1",
        parent=first.root_digest,
        corpus_cid=CID_CORPUS,
        corpus_version="corpus-2024.06",
        config_cid=CID_CONFIG,
        created_utc=CREATED,
    )
    final = inc_builder.build_incremental(
        docs[2:],
        filters=filters,
        snapshot_id="snap:inc-2",
        parent=mid.root_digest,
        corpus_cid=CID_CORPUS,
        corpus_version="corpus-2024.06",
        config_cid=CID_CONFIG,
        created_utc=CREATED,
    )

    assert full.logical_root_digest == final.logical_root_digest
    assert full.logical_root_cid == final.logical_root_cid
    # Physical roots may differ (kind / snapshot_id / parent pointers).
    assert full.kind is SnapshotKind.FULL
    assert final.kind is SnapshotKind.INCREMENTAL
    assert full.root_digest != final.root_digest

    full_snap = full_builder.open_head()
    inc_snap = inc_builder.open_head()
    full_active = {
        (r.record_id, r.content_digest, r.payload_digest)
        for r in full_snap.active_records()
    }
    inc_active = {
        (r.record_id, r.content_digest, r.payload_digest)
        for r in inc_snap.active_records()
    }
    assert full_active == inc_active
    assert full.active_record_count == final.active_record_count == 9  # 3 docs × 3 families


def test_repeated_full_build_is_idempotent_on_logical_root(tmp_path: Path) -> None:
    docs = _public_docs()
    filters = _filters()
    builder = _builder(tmp_path)
    a = builder.build_full(
        docs,
        filters=filters,
        snapshot_id="snap:a",
        corpus_cid=CID_CORPUS,
        corpus_version="corpus-2024.06",
        config_cid=CID_CONFIG,
        created_utc=CREATED,
    )
    b = builder.build_full(
        docs,
        filters=filters,
        snapshot_id="snap:b",
        corpus_cid=CID_CORPUS,
        corpus_version="corpus-2024.06",
        config_cid=CID_CONFIG,
        created_utc=CREATED,
    )
    assert a.logical_root_digest == b.logical_root_digest
    assert a.deterministic_manifest_digest == b.deterministic_manifest_digest


# ---------------------------------------------------------------------------
# Interrupted builds resume
# ---------------------------------------------------------------------------


def test_interrupted_build_resumes_from_checkpoint(tmp_path: Path) -> None:
    docs = _public_docs()
    filters = _filters()
    builder = _builder(tmp_path, shard_size=1)

    partial = builder.build_with_checkpoints(
        docs,
        filters=filters,
        snapshot_id_prefix="snap:resume",
        checkpoint_id="ckpt:build-1",
        corpus_cid=CID_CORPUS,
        corpus_version="corpus-2024.06",
        config_cid=CID_CONFIG,
        created_utc=CREATED,
        interrupt_after_shards=1,
        resume=True,
    )
    assert partial.incomplete is True
    assert partial.checkpoint_id == "ckpt:build-1"
    cur = builder.store.get_checkpoint("ckpt:build-1")
    assert cur.incomplete is True
    assert cur.offset == 1
    assert builder.store.contains(cur.prior_root_digest)

    # Resume completes the remaining documents.
    completed = builder.build_with_checkpoints(
        docs,
        filters=filters,
        snapshot_id_prefix="snap:resume",
        checkpoint_id="ckpt:build-1",
        corpus_cid=CID_CORPUS,
        corpus_version="corpus-2024.06",
        config_cid=CID_CONFIG,
        created_utc=CREATED,
        resume=True,
    )
    assert completed.incomplete is False
    assert completed.active_record_count == 9

    # Logical root matches a clean full build.
    full_builder = _builder(tmp_path / "full-ref")
    full = full_builder.build_full(
        docs,
        filters=filters,
        snapshot_id="snap:full-ref",
        corpus_cid=CID_CORPUS,
        corpus_version="corpus-2024.06",
        config_cid=CID_CONFIG,
        created_utc=CREATED,
    )
    assert completed.logical_root_digest == full.logical_root_digest

    # Prior roots retained across resume shards.
    final_snap = builder.open_head()
    assert final_snap.manifest.prior_roots or final_snap.manifest.parent_root is not None


# ---------------------------------------------------------------------------
# Exactly one allowed source join per record
# ---------------------------------------------------------------------------


def test_every_record_has_exactly_one_allowed_source_join(tmp_path: Path) -> None:
    docs = _public_docs()
    filters = _filters()
    builder = _builder(tmp_path)
    result = builder.build_full(
        docs,
        filters=filters,
        snapshot_id="snap:joins",
        corpus_cid=CID_CORPUS,
        corpus_version="corpus-2024.06",
        config_cid=CID_CONFIG,
        created_utc=CREATED,
    )
    snap = builder.store.get_snapshot(result.root_digest)
    allowed = collect_allowed_source_joins(docs, default_version=SOURCE_VERSION)
    verify_zero_orphans(snap, allowed)

    families_seen = {IndexFamily.BM25, IndexFamily.VECTOR, IndexFamily.GRAPH}
    for rec in snap.records:
        assert rec.family in families_seen
        assert len(rec.source_joins) == 1
        join = rec.source_joins[0]
        assert isinstance(join, SourceJoin)
        assert join.source_cid
        assert join.source_version == SOURCE_VERSION
        assert (join.source_cid, join.source_version) in allowed
        # Primary join is the document's first source link.
        doc = next(d for d in docs if d.document_id == rec.document_id)
        primary = primary_source_join(doc, default_version=SOURCE_VERSION)
        assert join.source_cid == primary.source_cid
        assert join.artifact_id == primary.artifact_id


def test_orphan_source_join_fails_closed(tmp_path: Path) -> None:
    docs = _public_docs()
    filters = _filters()
    builder = _builder(tmp_path)
    result = builder.build_full(
        docs,
        filters=filters,
        snapshot_id="snap:orphan",
        corpus_cid=CID_CORPUS,
        corpus_version="corpus-2024.06",
        config_cid=CID_CONFIG,
        created_utc=CREATED,
    )
    snap = builder.store.get_snapshot(result.root_digest)
    empty_allowed: set[tuple[str, str]] = set()
    with pytest.raises(OrphanRecordError):
        verify_zero_orphans(snap, empty_allowed)


# ---------------------------------------------------------------------------
# Private partitions encrypted + unpublishable
# ---------------------------------------------------------------------------


def test_private_partition_encrypted_and_unpublishable(tmp_path: Path) -> None:
    key = b"test-private-key-material-patlaw-146"
    private_docs = [
        _doc(
            "doc:private-draft",
            title="Confidential application draft",
            source_cid=CID_SOURCE_A,
            disclosure=DisclosureClass.CONFIDENTIAL_APPLICATION,
            tenant_id=TENANT_PRIVATE,
        ),
        _doc(
            "doc:private-work",
            title="Privileged claim chart notes",
            source_cid=CID_SOURCE_B,
            disclosure=DisclosureClass.PRIVILEGED_WORK_PRODUCT,
            tenant_id=TENANT_PRIVATE,
        ),
    ]
    filters = _filters(
        tenant=TENANT_PRIVATE,
        disclosures=(
            DisclosureClass.CONFIDENTIAL_APPLICATION,
            DisclosureClass.PRIVILEGED_WORK_PRODUCT,
        ),
    )
    builder = _builder(
        tmp_path,
        tenant=TENANT_PRIVATE,
        private_key_material=key,
    )
    result = builder.build_full(
        private_docs,
        filters=filters,
        snapshot_id="snap:private",
        partition=PartitionClass.PRIVATE_TENANT,
        corpus_cid=CID_CORPUS,
        corpus_version="corpus-private-2024",
        config_cid=CID_CONFIG,
        created_utc=CREATED,
    )
    assert result.partition is PartitionClass.PRIVATE_TENANT
    assert result.encrypted is True
    assert result.publishable is False
    assert is_publishable_partition(result.partition) is False
    assert result.private_envelope_path is not None

    snap = builder.store.get_snapshot(result.root_digest)
    assert_unpublishable(snap)
    assert snap.manifest.metadata.get("publishable") == "false"
    assert snap.manifest.metadata.get("encrypted") == "true"
    assert snap.manifest.metadata.get("private_cipher_version") == PRIVATE_CIPHER_VERSION

    envelope_path = Path(result.private_envelope_path)
    assert envelope_path.is_file()
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    assert "ciphertext_b64" in envelope
    assert envelope["tenant_id"] == TENANT_PRIVATE
    # Ciphertext envelope must not carry structured plaintext snapshot records.
    raw = envelope_path.read_text(encoding="utf-8")
    assert '"records"' not in raw
    assert "Confidential application draft" not in raw
    assert "Privileged claim chart notes" not in raw

    # Round-trip decrypt recovers the canonical snapshot bytes.
    plaintext = decrypt_private_payload(envelope, key_material=key)
    assert b"doc:private-draft" in plaintext
    assert b"confidential_application" in plaintext

    # Publication gate: treating private as publishable fails closed.
    with pytest.raises(PrivatePartitionPublishError):
        # Corrupt metadata to claim publishable.
        bad_meta = dict(snap.manifest.metadata)
        bad_meta["publishable"] = "true"
        from ipfs_datasets_py.processors.domains.patent.index_snapshot_contracts import (
            IndexSnapshotManifest,
            PatentIndexSnapshot,
        )

        bad_manifest = IndexSnapshotManifest(
            schema_version=snap.manifest.schema_version,
            snapshot_id=snap.manifest.snapshot_id,
            tenant_id=snap.manifest.tenant_id,
            partition=snap.manifest.partition,
            kind=snap.manifest.kind,
            identities=snap.manifest.identities,
            families=snap.manifest.families,
            record_count=snap.manifest.record_count,
            tombstone_count=snap.manifest.tombstone_count,
            active_record_count=snap.manifest.active_record_count,
            created_utc=snap.manifest.created_utc,
            parent_root=snap.manifest.parent_root,
            compaction_root=snap.manifest.compaction_root,
            rollback_root=snap.manifest.rollback_root,
            prior_roots=snap.manifest.prior_roots,
            checkpoint=snap.manifest.checkpoint,
            allowed_disclosures=snap.manifest.allowed_disclosures,
            metadata=bad_meta,
        )
        bad_snap = PatentIndexSnapshot(manifest=bad_manifest, records=snap.records)
        assert_unpublishable(bad_snap)


def test_public_partition_rejects_private_documents_via_filters(tmp_path: Path) -> None:
    """Private docs are filtered out of a public admission gate (zero private rows)."""
    mixed = _public_docs() + [
        _doc(
            "doc:private-draft",
            title="Confidential application draft",
            disclosure=DisclosureClass.CONFIDENTIAL_APPLICATION,
        )
    ]
    # Public filters only admit public disclosures.
    filters = _filters()
    builder = _builder(tmp_path)
    result = builder.build_full(
        mixed,
        filters=filters,
        snapshot_id="snap:public-only",
        partition=PartitionClass.PUBLIC,
        corpus_cid=CID_CORPUS,
        corpus_version="corpus-2024.06",
        config_cid=CID_CONFIG,
        created_utc=CREATED,
    )
    snap = builder.store.get_snapshot(result.root_digest)
    assert all(
        rec.disclosure
        in (DisclosureClass.PUBLIC_OFFICIAL, DisclosureClass.PUBLIC_USER)
        for rec in snap.records
    )
    assert not any(rec.document_id == "doc:private-draft" for rec in snap.records)
    assert result.publishable is True
    assert result.encrypted is False


# ---------------------------------------------------------------------------
# Zero-orphan + deterministic manifest
# ---------------------------------------------------------------------------


def test_zero_orphan_and_deterministic_manifest(tmp_path: Path) -> None:
    docs = _public_docs()
    filters = _filters()
    builder = _builder(tmp_path)
    r1 = builder.build_full(
        docs,
        filters=filters,
        snapshot_id="snap:det-1",
        corpus_cid=CID_CORPUS,
        corpus_version="corpus-2024.06",
        config_cid=CID_CONFIG,
        created_utc=CREATED,
    )
    r2 = builder.build_full(
        docs,
        filters=filters,
        snapshot_id="snap:det-2",
        corpus_cid=CID_CORPUS,
        corpus_version="corpus-2024.06",
        config_cid=CID_CONFIG,
        created_utc=CREATED,
    )
    snap1 = builder.store.get_snapshot(r1.root_digest)
    snap2 = builder.store.get_snapshot(r2.root_digest)
    allowed = collect_allowed_source_joins(docs, default_version=SOURCE_VERSION)
    verify_zero_orphans(snap1, allowed)
    verify_zero_orphans(snap2, allowed)

    d1 = deterministic_manifest_digest(snap1.manifest)
    d2 = deterministic_manifest_digest(snap2.manifest)
    assert d1 == d2
    assert r1.deterministic_manifest_digest == d1
    assert r1.logical_root_digest == r2.logical_root_digest

    # Logical root is stable under recompute.
    lr1 = compute_logical_root(
        records=snap1.records,
        identities=snap1.manifest.identities,
        tenant_id=snap1.manifest.tenant_id,
        partition=snap1.manifest.partition,
        families=snap1.manifest.families,
    )
    assert lr1.sha256 == r1.logical_root_digest


def test_golden_manifest_fixture_is_deterministic() -> None:
    """Golden fixture is a compact recipe, not a bulk envelope dump."""
    assert GOLDEN_MANIFEST.is_file(), f"missing golden fixture: {GOLDEN_MANIFEST}"
    data = json.loads(GOLDEN_MANIFEST.read_text(encoding="utf-8"))
    assert data["schema_version"] == "patent.index_snapshot.golden.v1"
    assert data["builder_interface"] == PERSISTENT_INDEX_BUILDER_INTERFACE
    assert data["snapshot_schema_version"] == INDEX_SNAPSHOT_SCHEMA_VERSION
    assert set(data["families"]) == {"bm25", "vector", "graph"}
    assert data["acceptance"]["logical_root_convergence"] is True
    assert data["acceptance"]["resume_from_checkpoint"] is True
    assert data["acceptance"]["one_source_join_per_record"] is True
    assert data["acceptance"]["private_encrypted_unpublishable"] is True
    assert data["acceptance"]["zero_orphan"] is True
    assert data["acceptance"]["deterministic_manifest"] is True
    # Compact recipe: documents listed by id, not full projected envelopes.
    assert isinstance(data["documents"], list)
    assert len(data["documents"]) >= 2
    for entry in data["documents"]:
        assert "document_id" in entry
        assert "source_cid" in entry
        assert "source_version" in entry
    # Deterministic canonical encoding of the golden itself.
    assert canonical_json(data) == canonical_json(
        json.loads(GOLDEN_MANIFEST.read_text(encoding="utf-8"))
    )


def test_golden_recipe_rebuild_matches_pinned_logical_root(tmp_path: Path) -> None:
    """Rebuild from the golden recipe converges on the pinned logical root."""
    data = json.loads(GOLDEN_MANIFEST.read_text(encoding="utf-8"))
    docs = [
        _doc(
            entry["document_id"],
            title=entry["title"],
            source_cid=entry["source_cid"],
            artifact_id=entry.get("artifact_id"),
            source_version=entry["source_version"],
            claims=entry.get("claims", "1. A method comprising indexing patent claims."),
        )
        for entry in data["documents"]
    ]
    filters = _filters(
        tenant=data["tenant_id"],
        disclosures=tuple(DisclosureClass(d) for d in data["allowed_disclosures"]),
    )
    builder = _builder(tmp_path, tenant=data["tenant_id"])
    result = builder.build_full(
        docs,
        filters=filters,
        snapshot_id="snap:golden-rebuild",
        corpus_cid=data["corpus_cid"],
        corpus_version=data["corpus_version"],
        config_cid=data["config_cid"],
        created_utc=data["created_utc"],
    )
    assert result.logical_root_digest == data["expected"]["logical_root_digest"]
    assert result.logical_root_cid == data["expected"]["logical_root_cid"]
    assert result.active_record_count == data["expected"]["active_record_count"]
    assert (
        result.deterministic_manifest_digest
        == data["expected"]["deterministic_manifest_digest"]
    )


# ---------------------------------------------------------------------------
# Compaction / tombstone / rollback retain logical integrity
# ---------------------------------------------------------------------------


def test_tombstone_compact_rollback_pipeline(tmp_path: Path) -> None:
    docs = _public_docs()
    filters = _filters()
    builder = _builder(tmp_path)
    full = builder.build_full(
        docs,
        filters=filters,
        snapshot_id="snap:base",
        corpus_cid=CID_CORPUS,
        corpus_version="corpus-2024.06",
        config_cid=CID_CONFIG,
        created_utc=CREATED,
    )
    base_digest = full.root_digest
    # Tombstone one BM25 row.
    tomb = builder.apply_tombstones(
        record_ids=["bm25:doc:doc:patent-graph"],
        snapshot_id="snap:tomb",
        tombstoned_utc="2024-07-01T00:00:00Z",
    )
    assert tomb.tombstone_count == 1
    assert tomb.active_record_count == full.active_record_count - 1
    assert builder.store.contains(base_digest)

    compacted = builder.compact(snapshot_id="snap:compact")
    assert compacted.kind is SnapshotKind.COMPACTION
    assert compacted.tombstone_count == 0
    assert compacted.active_record_count == tomb.active_record_count

    rolled = builder.rollback(
        target_root_digest=base_digest,
        snapshot_id="snap:rollback",
    )
    assert rolled.kind is SnapshotKind.ROLLBACK
    # Logical root of rollback re-materialization matches original full logical root.
    assert rolled.logical_root_digest == full.logical_root_digest
    assert builder.store.contains(base_digest)
    assert builder.store.contains(tomb.root_digest)


def test_encrypt_decrypt_round_trip() -> None:
    payload = b'{"hello":"private","records":[]}'
    env = encrypt_private_payload(
        payload, tenant_id=TENANT_PRIVATE, key_material=b"k" * 16
    )
    assert env["cipher_version"] == PRIVATE_CIPHER_VERSION
    assert decrypt_private_payload(env, key_material=b"k" * 16) == payload


def test_safe_config_exposes_interface(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    cfg = builder.safe_config()
    assert cfg["interface"] == PERSISTENT_INDEX_BUILDER_INTERFACE
    assert cfg["tenant_id"] == TENANT
    assert "private_key" not in canonical_json(cfg)
