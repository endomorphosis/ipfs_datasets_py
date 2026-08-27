"""Corpus physical layout and complete local state-law release tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.legal_data import (
    legal_source_rights_policy,
    state_laws_local_release,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    PINNED_TOKEN_COUNTER_ID,
    default_embedding_config,
    input_content_hash,
)
from ipfs_datasets_py.processors.legal_data.state_laws_bm25 import (
    TOKENIZER_ID,
    default_bm25_config,
    tokenize_query,
)
from ipfs_datasets_py.processors.legal_data.state_laws_bm25_physical import (
    write_state_laws_bm25_physical_layout_from_iterable,
)
from ipfs_datasets_py.processors.legal_data.state_laws_chunk_physical import (
    write_state_laws_chunk_physical_layout,
)
from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
)
from ipfs_datasets_py.processors.legal_data.state_laws_corpus_physical import (
    CORPUS_INDEX_PATH,
    StateLawsCorpusPhysicalError,
    write_state_laws_corpus_physical_layout,
    write_state_laws_corpus_physical_layout_from_iterable,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embedding_store import (
    PART_SCHEMA_VERSION as EMBEDDING_PART_SCHEMA_VERSION,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embedding_store import (
    SCHEMA_VERSION as EMBEDDING_STORE_SCHEMA_VERSION,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graph import (
    GraphEdgeClass,
    GraphEdgeType,
    GraphNodeType,
    StateLawsGraphEdge,
    StateLawsGraphNode,
    StateLawsGraphProjection,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graph_physical import (
    write_state_laws_streaming_graph_layout,
)
from ipfs_datasets_py.processors.legal_data.state_laws_legacy_v2_adapter import (
    AdaptationDisposition,
    AdaptedCorpusEvent,
    NormalizedSourceReceipt,
)
from ipfs_datasets_py.processors.legal_data.state_laws_local_release import (
    DescriptorIntegrityError,
    ReleaseKeyParityError,
    ReleaseReceiptError,
    StateLawsLocalReleaseError,
    VectorProductionGateError,
    _counts,
    assemble_state_laws_local_release_manifest,
    verify_state_laws_local_release_manifest,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    AdmissionStatus,
    CorpusRecord,
    SourceAuthorityClass,
    SourceReceiptRecord,
    VerificationResult,
)
from ipfs_datasets_py.processors.legal_data.state_laws_sparse_graphrag import (
    SUPPORTED_RELEASE_SCHEMAS,
)
from ipfs_datasets_py.processors.legal_data.state_laws_vector_physical import (
    write_state_laws_vector_physical_layout,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    ArtifactWriterConfig,
    atomic_write_canonical_json,
    describe_file,
    write_zstd_parquet,
)
from ipfs_datasets_py.retrieval.hf_graphrag.query import BoundedRemoteQueryEngine
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    ImmutableHubResolver,
    LocalRootTransport,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    ArtifactFamily,
    canonical_json_dumps,
    content_sha256,
)
from ipfs_datasets_py.retrieval.hf_graphrag.streaming_graph import (
    StreamingGraphConfig,
)

PINNED_SOURCE_REVISION = "4d62373051f2436296eb123d8c28819a91ea460a"
RELEASE_POINT = "state-laws-v2-2026-08-24"


def _streaming_graph_config() -> StreamingGraphConfig:
    return StreamingGraphConfig(
        max_pointers_per_page=1,
        max_pointers_per_shard=1,
        max_records_in_memory=16,
        max_rows_per_shard=1,
    )


def _digest(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode()).hexdigest()


def _records_and_receipts() -> tuple[list[CorpusRecord], list[SourceReceiptRecord]]:
    records: list[CorpusRecord] = []
    receipts: list[SourceReceiptRecord] = []
    for position, code in enumerate(CANONICAL_JURISDICTION_ORDER):
        receipt_id = f"scrape-{code.lower()}-sealed"
        checksum = hashlib.sha256(f"source-{code}".encode()).hexdigest()
        official_url = f"https://legislature.{code.lower()}.gov/code"
        records.append(
            CorpusRecord(
                entry_cid=_digest(f"entry-{code}"),
                legal_id=f"state:{code}:code:1:{position + 1}",
                source_cid=_digest(f"source-cid-{code}"),
                jurisdiction=code,
                code_family="code",
                section=str(position + 1),
                admission_status=AdmissionStatus.ADMITTED,
                admission_reason="verified official full-frontier acquisition",
                release_point=RELEASE_POINT,
                source_checksum=checksum,
                verification_result=VerificationResult.VERIFIED,
                acquisition_time="2026-08-24T00:00:00Z",
                official_source_url=official_url,
                acquisition_receipt_id=receipt_id,
                parser_version="state-law-parser-v2",
                text=(
                    f"{code} official public law section {position + 1}. "
                    f"{code.lower()}specialtoken governs agency records and duties."
                ),
                title="1",
            )
        )
        receipts.append(
            SourceReceiptRecord(
                receipt_id=receipt_id,
                jurisdiction=code,
                official_source_url=official_url,
                release_point=RELEASE_POINT,
                observation_time="2026-08-24T00:00:00Z",
                source_authority_class=SourceAuthorityClass.OFFICIAL,
                source_checksum=checksum,
                verification_result=VerificationResult.VERIFIED,
                discovered=1,
                fetched=1,
                excluded=0,
                quarantined=0,
                failed_final=0,
                frontier_closed=True,
                relative_path=f"receipts/scrape/{code.lower()}.json",
                start_urls=(official_url,),
                content_hashes=(checksum,),
                payload={
                    "adapter_input_row_count": 1,
                    "admission_eligible": True,
                    "qualification_reasons": [],
                    "reported_canonical_row_count": 1,
                },
            )
        )
    return records, receipts


def _projection(records: list[CorpusRecord]) -> tuple[StateLawsGraphProjection, str]:
    jurisdiction = StateLawsGraphNode(
        node_type=GraphNodeType.JURISDICTION,
        node_key="jurisdiction:ALL",
        label="United States state-law cohort",
    )
    code = StateLawsGraphNode(
        node_type=GraphNodeType.CODE,
        node_key="code:ALL:statutes",
        label="State statutory codes",
    )
    sections = [
        StateLawsGraphNode(
            node_type=GraphNodeType.SECTION,
            node_key=f"section:{record.legal_id}",
            label=f"{record.jurisdiction} section {record.section}",
            legal_id=record.legal_id,
            entry_cid=record.entry_cid,
        )
        for record in records
    ]
    edge = StateLawsGraphEdge(
        edge_type=GraphEdgeType.CONTAINS,
        source_node_cid=jurisdiction.node_cid,
        target_node_cid=code.node_cid,
        edge_class=GraphEdgeClass.STRUCTURAL,
    )
    return (
        StateLawsGraphProjection(
            nodes=(jurisdiction, code, *sections),
            edges=(edge,),
        ),
        jurisdiction.node_cid,
    )


def _vector_result(
    root: Path,
    *,
    chunk_rows: list[dict[str, object]],
):
    """Build through the real production-vector physical protocol."""

    source_root = root.parent / "embedding-store"
    config = default_embedding_config()
    input_parts: list[Path] = []
    by_jurisdiction: dict[str, list[dict[str, object]]] = {}
    for chunk in chunk_rows:
        by_jurisdiction.setdefault(str(chunk["jurisdiction_code"]), []).append(chunk)

    for code, jurisdiction_chunks in sorted(by_jurisdiction.items()):
        rows: list[dict[str, object]] = []
        for local_index, chunk in enumerate(jurisdiction_chunks):
            chunk_cid = str(chunk["chunk_cid"])
            parent_entry_cid = str(chunk["parent_entry_cid"])
            global_index = int(chunk["document_index"])
            vector = [0.0] * DEFAULT_EMBEDDING_DIMENSION
            vector[global_index % DEFAULT_EMBEDDING_DIMENSION] = 1.0
            input_text = str(chunk["text"])
            rows.append(
                {
                    "chunk_cid": chunk_cid,
                    "chunk_id": str(chunk["chunk_id"]),
                    "config_cid": config.config_cid,
                    "dimension": DEFAULT_EMBEDDING_DIMENSION,
                    "document_index": local_index,
                    "embedding": vector,
                    "entry_cid": chunk_cid,
                    "input_hash": input_content_hash(input_text),
                    "jurisdiction_code": code,
                    "model_id": DEFAULT_EMBEDDING_MODEL_ID,
                    "model_revision": DEFAULT_EMBEDDING_MODEL_REVISION,
                    "normalization": "l2",
                    "parent_entry_cid": parent_entry_cid,
                    "pooling": "mean",
                    "schema_version": EMBEDDING_PART_SCHEMA_VERSION,
                    "vector_space_id": config.vector_space_id,
                }
            )
        path = (
            source_root / "embeddings" / f"jurisdiction={code}" / "part-000000.parquet"
        )
        write_zstd_parquet(
            path,
            rows,
            config=ArtifactWriterConfig(max_rows_per_shard=len(rows)),
        )
        descriptor = describe_file(
            path,
            root=source_root,
            row_count=len(rows),
            family=ArtifactFamily.VECTORS,
            schema_id=EMBEDDING_PART_SCHEMA_VERSION,
            first_key=str(rows[0]["chunk_cid"]),
            last_key=str(rows[-1]["chunk_cid"]),
            shard_id=0,
            metadata={"jurisdiction_code": code, "stage": "embedding_store"},
        )
        inference = {
            "device": {
                "runtime": {
                    "sentence_transformers_available": True,
                    "sentence_transformers_version": "fixture-contract",
                    "torch_version": "fixture-contract",
                }
            },
            "embedder_kind": "sentence_transformers",
            "model_file_evidence": {
                "file_count": 1,
                "files": [{"path": "model.safetensors", "sha256": "e" * 64}],
                "revision": DEFAULT_EMBEDDING_MODEL_REVISION,
            },
            "real_inference": True,
            "truncation": {
                "applied": True,
                "max_seq_length": 512,
                "max_tokens": 512,
                "tokenizer_model_max_length": 512,
            },
            "truncation_satisfies_contract": True,
        }
        inference_digest = content_sha256(canonical_json_dumps(inference))
        checkpoint = {
            "config": config.to_dict(),
            "config_digest": config.digest,
            "inference": inference,
            "jurisdiction_code": code,
            "parts": [
                {
                    "descriptor": descriptor.to_dict(),
                    "document_index_start": 0,
                    "inference_digest": inference_digest,
                    "input_digest": hashlib.sha256(
                        f"input-{code}-{len(rows)}".encode()
                    ).hexdigest(),
                    "part_index": 0,
                    "row_count": len(rows),
                    "sha256": descriptor.sha256,
                }
            ],
            "production_ready": True,
            "row_count": len(rows),
            "schema_version": EMBEDDING_STORE_SCHEMA_VERSION,
            "sort_receipt": {
                "family": "chunks",
                "interrupted": False,
                "max_records_in_memory": 2,
                "output_digest": hashlib.sha256(
                    f"sort-{code}-{len(rows)}".encode()
                ).hexdigest(),
                "output_path": "checkpoints/embedding_sort/chunks.sorted.jsonl",
                "peak_resident_records": len(rows),
                "records_consumed": len(rows),
                "row_count": len(rows),
                "run_count": 1,
                "schema_version": "hf-graphrag-external-sort/v1",
                "status": "complete",
            },
            "task_id": "state-laws-local-release-e2e",
        }
        atomic_write_canonical_json(
            source_root / "checkpoints" / "embeddings" / f"{code}.json",
            checkpoint,
        )
        input_parts.append(path)
    return write_state_laws_vector_physical_layout(
        input_parts,
        root,
        kmeans_iterations=1,
        locator_page_size=51,
        max_centroids=1,
        max_rows_per_centroid=1,
        max_rows_per_shard=1,
        max_shards_per_centroid=1,
        max_sort_records_in_memory=16,
        max_training_rows=1,
        target_rows_per_centroid=1,
    )


def _rights_receipt() -> dict[str, object]:
    admitted_ids = [
        f"{code.lower()}-official-statutory-text"
        for code in CANONICAL_JURISDICTION_ORDER
    ]
    receipt: dict[str, object] = {
        "admitted_record_ids": admitted_ids,
        "decisions": [
            {
                "admitted": True,
                "authorizing": True,
                "content_scope": "statutory_text",
                "record_id": record_id,
                "rights_disposition": "allowed",
            }
            for record_id in admitted_ids
        ],
        "catalog_digest_sha256": hashlib.sha256(b"catalog").hexdigest(),
        "path": "docs/reports/legal_corpora_reindex/legal_source_rights_compliance.json",
        "prohibited_ids": [],
        "status": "passed",
        "unknown_ids": [],
    }
    receipt["report_digest_sha256"] = hashlib.sha256(
        canonical_json_dumps(receipt).encode("utf-8")
    ).hexdigest()
    return receipt


def _activate_canonical_live_rights(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    """Restore and replay the fixed-path authority for release-admission tests."""

    canonical = json.loads(
        legal_source_rights_policy.default_live_compliance_path().read_text(
            encoding="utf-8"
        )
    )
    monkeypatch.setattr(
        state_laws_local_release,
        "require_live_source_rights_receipt",
        legal_source_rights_policy.require_live_source_rights_receipt,
    )
    assert legal_source_rights_policy.require_live_source_rights_receipt(
        canonical
    ) == canonical
    return canonical


@pytest.fixture(autouse=True)
def _stub_authoritative_live_rights(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep physical-layout tests hermetic; policy behavior has focused tests."""

    monkeypatch.setattr(
        state_laws_local_release,
        "require_live_source_rights_receipt",
        lambda value: dict(value),
    )


def test_local_release_replays_authoritative_live_rights_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(_value):
        raise ValueError("stale policy_module_sha256")

    monkeypatch.setattr(
        state_laws_local_release,
        "require_live_source_rights_receipt",
        reject,
    )
    with pytest.raises(
        ReleaseReceiptError, match="authoritative live verification.*policy_module"
    ):
        state_laws_local_release._validate_rights_receipt(
            _rights_receipt(), source_receipt_ids=()
        )


@pytest.fixture
def local_release(tmp_path: Path) -> dict[str, object]:
    records, receipts = _records_and_receipts()
    corpus = write_state_laws_corpus_physical_layout_from_iterable(
        reversed(records),
        source_receipts=receipts,
        output_dir=tmp_path,
        max_rows_per_shard=1,
        max_records_in_memory=16,
    )
    chunks = write_state_laws_chunk_physical_layout(
        corpus,
        model_token_limit=512,
        model_token_counter=lambda text: len(text.split()),
        model_token_counter_id=PINNED_TOKEN_COUNTER_ID,
        output_dir=tmp_path,
        max_records_in_memory=16,
        max_rows_per_shard=1,
    )
    chunk_rows = list(chunks.iter_chunks())
    bm25 = write_state_laws_bm25_physical_layout_from_iterable(
        iter(chunk_rows),
        tmp_path,
        config=default_bm25_config(),
        canonical_chunk_artifact_digest=chunks.corpus_index_descriptor.sha256,
        checkpoint_dir=tmp_path / "checkpoints" / "bm25",
    )
    projection, root_node_cid = _projection(records)
    graph = write_state_laws_streaming_graph_layout(
        iter(projection.nodes),
        iter(projection.edges),
        tmp_path,
        bm25=bm25,
        config=_streaming_graph_config(),
    )
    vectors = _vector_result(tmp_path, chunk_rows=chunk_rows)
    return {
        "bm25": bm25,
        "chunks": chunks,
        "corpus": corpus,
        "graph": graph,
        "root": tmp_path,
        "root_node_cid": root_node_cid,
        "vectors": vectors,
    }


def test_corpus_writer_partitions_direct_rows_and_refuses_quarantine(
    tmp_path: Path,
) -> None:
    records, receipts = _records_and_receipts()
    corpus = write_state_laws_corpus_physical_layout(
        reversed(records),
        source_receipts=receipts,
        output_dir=tmp_path,
        max_rows_per_shard=1,
    )

    routes = pq.read_table(tmp_path / CORPUS_INDEX_PATH).to_pylist()
    assert len(routes) == 51
    assert [int(row["start_document_index"]) for row in routes] == list(range(51))
    assert [int(row["end_document_index"]) for row in routes] == list(range(51))
    assert all("/jurisdiction/" in str(row["relative_path"]) for row in routes)
    first_data = pq.read_table(tmp_path / str(routes[0]["relative_path"]))
    assert "record_json" not in first_data.column_names
    assert {
        "entry_cid",
        "legal_id",
        "source_cid",
        "text",
        "jurisdiction_code",
        "document_index",
    }.issubset(first_data.column_names)
    assert len(corpus.receipt_descriptors) == 51
    assert not any(
        "official_source_url" in descriptor.metadata
        for descriptor in corpus.data_descriptors
    )

    event_layout = write_state_laws_corpus_physical_layout(
        [
            AdaptedCorpusEvent(
                source_index=0,
                disposition=AdaptationDisposition.ADMITTED,
                reasons=(),
                record=records[0],
            )
        ],
        source_receipts=[
            NormalizedSourceReceipt(
                record=receipts[0],
                admission_eligible=True,
                qualification_reasons=(),
                acquisition_path_ids=("official",),
                input_sha256=hashlib.sha256(b"input").hexdigest(),
                input_row_count=1,
                expected_row_count=1,
                legacy_receipt_sha256=hashlib.sha256(b"receipt").hexdigest(),
            )
        ],
        output_dir=tmp_path / "adapter-events",
    )
    assert event_layout.rows[0]["entry_cid"] == records[0].entry_cid

    quarantined = records[0].to_dict()
    quarantined["admission_status"] = "quarantined"
    with pytest.raises(StateLawsCorpusPhysicalError, match="not admitted"):
        write_state_laws_corpus_physical_layout(
            [quarantined],
            source_receipts=[receipts[0]],
            output_dir=tmp_path / "refused",
        )


def test_complete_manifest_supports_bm25_hydration_and_graph_query(
    local_release: dict[str, object],
) -> None:
    root = local_release["root"]
    assert isinstance(root, Path)
    result = assemble_state_laws_local_release_manifest(
        root,
        corpus=local_release["corpus"],
        chunks=local_release["chunks"],
        bm25=local_release["bm25"],
        vectors=local_release["vectors"],
        graph=local_release["graph"],
        rights_receipt=_rights_receipt(),
        source_revision=PINNED_SOURCE_REVISION,
        release_point=RELEASE_POINT,
    )
    assert result.payload["validation"]["status"] == "passed"
    assert result.payload["validation"]["default_jurisdiction_count"] == 51
    assert result.payload["release_control"]["local_staging_only"] is True
    assert result.payload["release_control"]["authorizes_publication"] is False
    provenance_attestation = result.payload["source_provenance_verifier"]
    provenance_path = Path(state_laws_local_release.__file__).with_name(
        "state_laws_source_provenance.py"
    )
    assert provenance_attestation == (
        state_laws_local_release.state_laws_source_provenance_verifier_attestation()
    )
    assert provenance_attestation["sha256"] == hashlib.sha256(
        provenance_path.read_bytes()
    ).hexdigest()

    resolver = ImmutableHubResolver(
        repo_id="justicedao/ipfs_state_laws",
        revision=PINNED_SOURCE_REVISION,
        cache_dir=root / "cache",
        transport=LocalRootTransport(root),
        local_root=root,
        supported_schemas=set(SUPPORTED_RELEASE_SCHEMAS),
    )
    engine = BoundedRemoteQueryEngine(
        resolver,
        bm25_query_analyzers={TOKENIZER_ID: tokenize_query},
    )
    bm25_result = engine.run_bm25(
        "akspecialtoken", top_k=3, hydrate=True, include_content=True
    )
    assert bm25_result.complete is True
    assert bm25_result.results[0]["jurisdiction"] == "AK"
    assert "AK official public law" in bm25_result.results[0]["text"]

    adjacency = engine.fetch_adjacency(
        str(local_release["root_node_cid"]), direction="out", limit=5
    )
    assert len(adjacency) == 1
    assert adjacency[0]["edge_type"] == GraphEdgeType.CONTAINS.value


def test_independent_verifier_requires_and_verifies_vector_entry_locator(
    local_release: dict[str, object],
) -> None:
    root = local_release["root"]
    assert isinstance(root, Path)
    release = assemble_state_laws_local_release_manifest(
        root,
        corpus=local_release["corpus"],
        chunks=local_release["chunks"],
        bm25=local_release["bm25"],
        vectors=local_release["vectors"],
        graph=local_release["graph"],
        rights_receipt=_rights_receipt(),
        source_revision=PINNED_SOURCE_REVISION,
        release_point=RELEASE_POINT,
    )
    verified = verify_state_laws_local_release_manifest(root)
    locator = verified.payload["indexes"]["vector_entry_locator"]
    assert locator["relative_path"] == "indexes/vector_entry_locator.parquet"

    without_locator = json.loads(canonical_json_dumps(release.payload))
    del without_locator["indexes"]["vector_entry_locator"]
    atomic_write_canonical_json(root / "manifest.json", without_locator)
    with pytest.raises(StateLawsLocalReleaseError, match="exact-51 release gates"):
        verify_state_laws_local_release_manifest(root)

    atomic_write_canonical_json(root / "manifest.json", release.payload)
    locator_path = root / str(locator["relative_path"])
    locator_path.write_bytes(locator_path.read_bytes() + b"tampered")
    with pytest.raises(DescriptorIntegrityError, match="differs from staged bytes"):
        verify_state_laws_local_release_manifest(root)


@pytest.mark.parametrize(
    ("forgery", "preserves_document_frequencies"),
    (
        ("field_tf", True),
        ("document_frequency", False),
    ),
)
def test_canonical_semantic_verifier_rejects_self_consistent_forged_bm25_and_kg(
    local_release: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    forgery: str,
    preserves_document_frequencies: bool,
) -> None:
    """Rebuilding every BM25/KG surface cannot override canonical chunk text."""

    # This focused release-admission test opts out of the module's hermetic
    # shape-test stub and replays the actual fixed-path canonical authority.
    canonical_rights = _activate_canonical_live_rights(monkeypatch)

    root = local_release["root"]
    assert isinstance(root, Path)
    chunks = local_release["chunks"]
    forged_rows: list[dict[str, object]] = []
    forged = False
    for source in chunks.iter_chunks():
        row = dict(source)
        target_code = "AK" if forgery == "field_tf" else "AL"
        if not forged and row["jurisdiction_code"] == target_code:
            original = str(row["body"])
            replacement = (
                original.replace("AK official", "official official", 1)
                if forgery == "field_tf"
                else original.replace("agency", "akspecialtoken", 1)
            )
            assert replacement != original
            assert len(replacement.split()) == len(original.split())
            # The attacker feeds a different body to the real production
            # writer while retaining the genuine chunk identities/digest.
            row["body"] = replacement
            forged = True
        forged_rows.append(row)
    assert forged is True

    forged_bm25 = write_state_laws_bm25_physical_layout_from_iterable(
        iter(forged_rows),
        root,
        config=default_bm25_config(),
        canonical_chunk_artifact_digest=chunks.corpus_index_descriptor.sha256,
        checkpoint_dir=root / "checkpoints" / "forged-bm25",
    )
    original_bm25 = local_release["bm25"]
    # Both attacks preserve the vocabulary and document/token lengths.  One
    # preserves every DF while changing exact field TF/corpus/weighted
    # frequencies; the other changes DFs (and therefore RSJ IDFs) while
    # keeping every artifact internally consistent through the real writers.
    assert (
        forged_bm25.layout.vocabulary_sha256
        == original_bm25.layout.vocabulary_sha256
    )
    assert (
        forged_bm25.layout.document_frequency_sha256
        == original_bm25.layout.document_frequency_sha256
    ) is preserves_document_frequencies
    assert (
        forged_bm25.layout.token_instance_count
        == original_bm25.layout.token_instance_count
    )
    assert forged_bm25.layout.index_root_cid != original_bm25.layout.index_root_cid
    records, _ = _records_and_receipts()
    projection, _ = _projection(records)
    forged_graph = write_state_laws_streaming_graph_layout(
        iter(projection.nodes),
        iter(projection.edges),
        root,
        bm25=forged_bm25,
        config=replace(_streaming_graph_config(), overwrite=True),
    )
    arguments = {
        "output_root": root,
        "corpus": local_release["corpus"],
        "chunks": chunks,
        "bm25": forged_bm25,
        "vectors": local_release["vectors"],
        "graph": forged_graph,
        "rights_receipt": canonical_rights,
        "source_revision": PINNED_SOURCE_REVISION,
        "release_point": RELEASE_POINT,
    }

    # BM25 documents, postings, all scoring aggregates/digests/routes, and the
    # KG vocabulary proof were rebuilt together and are mutually consistent.
    # Assembly must still recompute from the unchanged canonical chunk body.
    with pytest.raises(
        DescriptorIntegrityError,
        match="BM25 posting|canonical BM25|canonical chunks",
    ):
        assemble_state_laws_local_release_manifest(**arguments)

    # Model an artifact-set/manifest fabricated before the independent gate:
    # let assembly seal a self-declared attestation once, then restore the real
    # verifier and prove completed-release/publication admission rejects it.
    forged_counts = forged_bm25.counts
    fabricated_proof = {
        "document_count": forged_counts["bm25_documents"],
        "document_semantics_sha256": "a" * 64,
        "posting_count": forged_counts["bm25_postings"],
        "posting_semantics_sha256": "b" * 64,
        "term_count": forged_counts["bm25_terms"],
        "term_statistics_sha256": "c" * 64,
        "token_instance_count": forged_counts["bm25_token_instances"],
    }
    with monkeypatch.context() as context:
        context.setattr(
            state_laws_local_release,
            "_verify_completed_bm25_semantics",
            lambda *args, **kwargs: fabricated_proof,
        )
        assemble_state_laws_local_release_manifest(**arguments)

    with pytest.raises(
        DescriptorIntegrityError,
        match="BM25 posting|canonical BM25|canonical chunks",
    ):
        verify_state_laws_local_release_manifest(root)


def test_completed_verifier_recomputes_code_attestation_and_bm25_config(
    local_release: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mutually rewritten BM25/KG digest cannot replace the writer config."""

    canonical_rights = _activate_canonical_live_rights(monkeypatch)
    root = local_release["root"]
    assert isinstance(root, Path)
    release = assemble_state_laws_local_release_manifest(
        root,
        corpus=local_release["corpus"],
        chunks=local_release["chunks"],
        bm25=local_release["bm25"],
        vectors=local_release["vectors"],
        graph=local_release["graph"],
        rights_receipt=canonical_rights,
        source_revision=PINNED_SOURCE_REVISION,
        release_point=RELEASE_POINT,
    )
    sealed_provenance = dict(release.payload["source_provenance_verifier"])
    drifted_provenance = {
        **sealed_provenance,
        "sha256": hashlib.sha256(b"drifted-current-verifier-code").hexdigest(),
    }
    with monkeypatch.context() as context:
        context.setattr(
            state_laws_local_release,
            "state_laws_source_provenance_verifier_attestation",
            lambda: drifted_provenance,
        )
        with pytest.raises(
            ReleaseReceiptError,
            match="source-provenance verifier attestation drifted",
        ):
            verify_state_laws_local_release_manifest(root)

    forged = json.loads(canonical_json_dumps(release.payload))
    forged_digest = hashlib.sha256(b"self-consistent-forged-config").hexdigest()
    forged["bm25"]["config_digest"] = forged_digest
    forged["graph"]["vocabulary_parity"]["bm25_config_digest"] = forged_digest
    atomic_write_canonical_json(root / "manifest.json", forged)

    with pytest.raises(
        DescriptorIntegrityError,
        match="scoring/tokenizer/chunk-binding contract",
    ):
        verify_state_laws_local_release_manifest(root)


def test_manifest_refuses_synthetic_vectors_and_parent_key_drift(
    local_release: dict[str, object],
) -> None:
    root = local_release["root"]
    assert isinstance(root, Path)
    vector_result = local_release["vectors"]
    vectors = vector_result.to_manifest_fragment()
    vectors["key_evidence"] = vector_result.key_evidence
    vectors["inference"] = {"real_inference": False}
    with pytest.raises(VectorProductionGateError, match="real_inference"):
        assemble_state_laws_local_release_manifest(
            root,
            corpus=local_release["corpus"],
            chunks=local_release["chunks"],
            bm25=local_release["bm25"],
            vectors=vectors,
            graph=local_release["graph"],
            rights_receipt=_rights_receipt(),
            source_revision=PINNED_SOURCE_REVISION,
            release_point=RELEASE_POINT,
        )

    vectors = vector_result.to_manifest_fragment()
    vectors["key_evidence"] = {"parent_entry_cids": [_digest("orphan-vector")]}
    with pytest.raises(ReleaseKeyParityError, match="diverges"):
        assemble_state_laws_local_release_manifest(
            root,
            corpus=local_release["corpus"],
            chunks=local_release["chunks"],
            bm25=local_release["bm25"],
            vectors=vectors,
            graph=local_release["graph"],
            rights_receipt=_rights_receipt(),
            source_revision=PINNED_SOURCE_REVISION,
            release_point=RELEASE_POINT,
        )


def test_count_model_separates_parent_statutes_from_searchable_chunks() -> None:
    counts = _counts(
        {"counts": {"corpus_documents": 2}},
        {
            "counts": {
                "canonical_chunks": 3,
                "parent_documents": 2,
                "searchable_chunks": 3,
            }
        },
        {"counts": {"bm25_documents": 3, "bm25_terms": 5}},
        {"total_rows": 3},
        {"graph": {"node_count": 4, "edge_count": 2}},
        key_count=2,
    )
    assert counts["corpus_documents"] == 2
    assert counts["parent_documents"] == 2
    assert counts["bm25_documents"] == 3
    assert counts["searchable_chunks"] == 3
    assert counts["vector_rows"] == 3

    with pytest.raises(ReleaseKeyParityError, match="searchable-chunk counts"):
        _counts(
            {"counts": {"corpus_documents": 2}},
            {
                "counts": {
                    "canonical_chunks": 3,
                    "parent_documents": 2,
                    "searchable_chunks": 3,
                }
            },
            {"counts": {"bm25_documents": 3, "bm25_terms": 5}},
            {"total_rows": 2},
            {"graph": {"node_count": 4, "edge_count": 2}},
            key_count=2,
        )


def test_manifest_accepts_multiple_chunks_per_parent_statute(tmp_path: Path) -> None:
    records, receipts = _records_and_receipts()
    records = [
        replace(
            record,
            text=" ".join(f"akmultiword{position}" for position in range(100)),
        )
        if record.jurisdiction == "AK"
        else record
        for record in records
    ]
    corpus = write_state_laws_corpus_physical_layout_from_iterable(
        iter(records),
        source_receipts=receipts,
        output_dir=tmp_path,
        max_rows_per_shard=1,
        max_records_in_memory=16,
    )
    chunks = write_state_laws_chunk_physical_layout(
        corpus,
        model_token_limit=64,
        model_token_counter=lambda text: len(text.split()),
        model_token_counter_id=PINNED_TOKEN_COUNTER_ID,
        output_dir=tmp_path,
        overlap_tokens=0,
        max_records_in_memory=16,
        max_rows_per_shard=1,
    )
    chunk_rows = list(chunks.iter_chunks())

    bm25 = write_state_laws_bm25_physical_layout_from_iterable(
        iter(chunk_rows),
        tmp_path,
        config=default_bm25_config(),
        canonical_chunk_artifact_digest=chunks.corpus_index_descriptor.sha256,
        checkpoint_dir=tmp_path / "checkpoints" / "bm25",
    )
    projection, _ = _projection(records)
    graph = write_state_laws_streaming_graph_layout(
        iter(projection.nodes),
        iter(projection.edges),
        tmp_path,
        bm25=bm25,
        config=_streaming_graph_config(),
    )
    vectors = _vector_result(tmp_path, chunk_rows=chunk_rows)

    result = assemble_state_laws_local_release_manifest(
        tmp_path,
        corpus=corpus,
        chunks=chunks,
        bm25=bm25,
        vectors=vectors,
        graph=graph,
        rights_receipt=_rights_receipt(),
        source_revision=PINNED_SOURCE_REVISION,
        release_point=RELEASE_POINT,
    )
    assert result.payload["counts"]["parent_documents"] == 51
    assert result.payload["counts"]["corpus_documents"] == 51
    assert result.payload["counts"]["searchable_chunks"] == 52
    assert result.payload["counts"]["bm25_documents"] == 52
    assert result.payload["counts"]["vector_rows"] == 52
    assert result.payload["key_parity"]["parent_entry_cid_count"] == 51
    assert result.payload["key_parity"]["chunk_cid_count"] == 52
    assert result.payload["key_parity"]["chunk_cids_exact"] is True
    assert len(result.payload["key_parity"]["chunk_cids_sha256"]) == 64
    assert result.payload["key_parity"]["document_chunk_mapping_exact"] is True
    assert len(result.payload["key_parity"]["document_chunk_mapping_sha256"]) == 64


def test_manifest_refuses_equal_cardinality_chunk_cid_drift(
    local_release: dict[str, object],
) -> None:
    root = local_release["root"]
    assert isinstance(root, Path)
    vector_source = local_release["vectors"]

    class DriftedVectorChunkEvidence:
        production_ready = True

        def to_manifest_fragment(self):
            return vector_source.to_manifest_fragment()

        def iter_document_chunk_keys(self):
            source = iter(vector_source.iter_document_chunk_keys())
            document_index, _ = next(source)
            yield document_index, _digest("equal-cardinality-vector-drift")
            yield from source

    with pytest.raises(ReleaseKeyParityError, match="chunk-CID sets diverge"):
        assemble_state_laws_local_release_manifest(
            root,
            corpus=local_release["corpus"],
            chunks=local_release["chunks"],
            bm25=local_release["bm25"],
            vectors=DriftedVectorChunkEvidence(),
            graph=local_release["graph"],
            rights_receipt=_rights_receipt(),
            source_revision=PINNED_SOURCE_REVISION,
            release_point=RELEASE_POINT,
        )

    class DuplicateVectorChunkEvidence:
        production_ready = True

        def to_manifest_fragment(self):
            return vector_source.to_manifest_fragment()

        def iter_document_chunk_keys(self):
            source = iter(vector_source.iter_document_chunk_keys())
            first_index, first_cid = next(source)
            second_index, _ = next(source)
            yield first_index, first_cid
            yield second_index, first_cid
            yield from source

    with pytest.raises(ReleaseKeyParityError, match="duplicate CID"):
        assemble_state_laws_local_release_manifest(
            root,
            corpus=local_release["corpus"],
            chunks=local_release["chunks"],
            bm25=local_release["bm25"],
            vectors=DuplicateVectorChunkEvidence(),
            graph=local_release["graph"],
            rights_receipt=_rights_receipt(),
            source_revision=PINNED_SOURCE_REVISION,
            release_point=RELEASE_POINT,
        )


def test_manifest_refuses_equal_set_positional_chunk_drift(
    local_release: dict[str, object],
) -> None:
    root = local_release["root"]
    assert isinstance(root, Path)
    vector_source = local_release["vectors"]

    class PositionDriftedVectorEvidence:
        production_ready = True

        def to_manifest_fragment(self):
            return vector_source.to_manifest_fragment()

        def iter_document_chunk_keys(self):
            rows = list(vector_source.iter_document_chunk_keys())
            first_index, first_cid = rows[0]
            second_index, second_cid = rows[1]
            yield first_index, second_cid
            yield second_index, first_cid
            yield from rows[2:]

    with pytest.raises(ReleaseKeyParityError, match="mappings diverge"):
        assemble_state_laws_local_release_manifest(
            root,
            corpus=local_release["corpus"],
            chunks=local_release["chunks"],
            bm25=local_release["bm25"],
            vectors=PositionDriftedVectorEvidence(),
            graph=local_release["graph"],
            rights_receipt=_rights_receipt(),
            source_revision=PINNED_SOURCE_REVISION,
            release_point=RELEASE_POINT,
        )


def test_manifest_refuses_non_production_physical_sources(
    local_release: dict[str, object],
) -> None:
    root = local_release["root"]
    assert isinstance(root, Path)

    class CompatibilitySource:
        production_ready = False

        def __init__(self, source: object) -> None:
            self.source = source

        def to_manifest_fragment(self):
            return self.source.to_manifest_fragment()

    arguments = {
        "output_root": root,
        "chunks": local_release["chunks"],
        "vectors": local_release["vectors"],
        "graph": local_release["graph"],
        "rights_receipt": _rights_receipt(),
        "source_revision": PINNED_SOURCE_REVISION,
        "release_point": RELEASE_POINT,
    }
    with pytest.raises(StateLawsLocalReleaseError, match="corpus.*not production"):
        assemble_state_laws_local_release_manifest(
            corpus=CompatibilitySource(local_release["corpus"]),
            bm25=local_release["bm25"],
            **arguments,
        )
    with pytest.raises(StateLawsLocalReleaseError, match="chunks.*not production"):
        assemble_state_laws_local_release_manifest(
            corpus=local_release["corpus"],
            chunks=CompatibilitySource(local_release["chunks"]),
            bm25=local_release["bm25"],
            **{key: value for key, value in arguments.items() if key != "chunks"},
        )
    with pytest.raises(StateLawsLocalReleaseError, match="bm25.*not production"):
        assemble_state_laws_local_release_manifest(
            corpus=local_release["corpus"],
            bm25=CompatibilitySource(local_release["bm25"]),
            **arguments,
        )
    with pytest.raises(StateLawsLocalReleaseError, match="graph.*not production"):
        assemble_state_laws_local_release_manifest(
            corpus=local_release["corpus"],
            bm25=local_release["bm25"],
            graph=CompatibilitySource(local_release["graph"]),
            **{key: value for key, value in arguments.items() if key != "graph"},
        )
