"""Focused composition tests for the local state-law production orchestrator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data import legal_source_rights_policy
from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    PINNED_TOKEN_COUNTER_ID,
    default_embedding_config,
    fixture_embedding_config,
    input_content_hash,
)
from ipfs_datasets_py.processors.legal_data.state_laws_bm25 import (
    fixture_bm25_config,
)
from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embedding_store import (
    PART_SCHEMA_VERSION as EMBEDDING_PART_SCHEMA_VERSION,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embedding_store import (
    SCHEMA_VERSION as EMBEDDING_STORE_SCHEMA_VERSION,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embedding_store import (
    EmbeddingStoreResult,
)
from ipfs_datasets_py.processors.legal_data.state_laws_production_orchestrator import (
    STAGE_ORDER,
    StateLawsProductionArtifactDriftError,
    StateLawsProductionGateError,
    StateLawsProductionInputDriftError,
    build_state_laws_production_release,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    DEFAULT_EMBEDDING_DIMENSION,
    AdmissionStatus,
    CorpusRecord,
    SourceAuthorityClass,
    SourceReceiptRecord,
    VerificationResult,
    canonical_json_dumps,
    content_sha256,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    ArtifactWriterConfig,
    atomic_write_canonical_json,
    describe_file,
    write_zstd_parquet,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import ArtifactFamily
from ipfs_datasets_py.retrieval.hf_graphrag.streaming_graph import (
    StreamingGraphConfig,
)

PINNED_SOURCE_REVISION = "4d62373051f2436296eb123d8c28819a91ea460a"
RELEASE_POINT = "state-laws-v2-2026-08-24"
CANONICAL_FIXTURE_INPUT_DIGEST = (
    "2b2ffc03726e6b8296fadb2eb088353ae5764d00b02de9a2048feb7b274ca4f1"
)


def _sha256(seed: str, *, prefixed: bool = False) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"sha256:{digest}" if prefixed else digest


def _records_and_receipts() -> tuple[list[CorpusRecord], list[SourceReceiptRecord]]:
    records: list[CorpusRecord] = []
    receipts: list[SourceReceiptRecord] = []
    for position, code in enumerate(CANONICAL_JURISDICTION_ORDER, start=1):
        receipt_id = f"scrape-{code.lower()}-sealed"
        checksum = _sha256(f"source-{code}")
        official_url = f"https://legislature.{code.lower()}.gov/code"
        records.append(
            CorpusRecord(
                entry_cid=_sha256(f"entry-{code}", prefixed=True),
                legal_id=f"state:{code}:code:1:{position}",
                source_cid=_sha256(f"source-cid-{code}", prefixed=True),
                jurisdiction=code,
                code_family="code",
                section=str(position),
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
                    f"{code} official public law section {position}. "
                    "The agency shall preserve records and perform its duty."
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


def _rights_receipt() -> dict[str, object]:
    receipt = json.loads(
        legal_source_rights_policy.default_live_compliance_path().read_text(
            encoding="utf-8"
        )
    )
    assert isinstance(receipt, dict)
    return legal_source_rights_policy.require_live_source_rights_receipt(receipt)


def _fake_production_embedding_builder(call_log: list[dict[str, object]]):
    def build(
        rows,
        output_root,
        *,
        jurisdiction_code,
        checkpoint_path=None,
        config=None,
        embedder=None,
        model_factory=None,
        rows_per_part,
        max_sort_records_in_memory,
        resume,
    ):
        del checkpoint_path, embedder, model_factory
        assert resume is True
        assert config == default_embedding_config()
        call_log.append(
            {
                "code": jurisdiction_code,
                "offline": {
                    name: __import__("os").environ.get(name)
                    for name in (
                        "HF_DATASETS_OFFLINE",
                        "HF_HUB_OFFLINE",
                        "TRANSFORMERS_OFFLINE",
                    )
                },
            }
        )
        source_root = Path(output_root)
        chunks = sorted(rows, key=lambda row: str(row["chunk_cid"]))
        assert len(chunks) == 1
        output_rows = []
        for document_index, chunk in enumerate(chunks):
            vector = [0.0] * DEFAULT_EMBEDDING_DIMENSION
            vector[document_index] = 1.0
            output_rows.append(
                {
                    "chunk_cid": str(chunk["chunk_cid"]),
                    "chunk_id": str(chunk["chunk_id"]),
                    "config_cid": config.config_cid,
                    "dimension": DEFAULT_EMBEDDING_DIMENSION,
                    "document_index": document_index,
                    "embedding": vector,
                    "entry_cid": str(chunk["chunk_cid"]),
                    "input_hash": input_content_hash(str(chunk["text"])),
                    "jurisdiction_code": jurisdiction_code,
                    "model_id": config.model_id,
                    "model_revision": config.model_revision,
                    "normalization": config.normalization,
                    "parent_entry_cid": str(chunk["parent_entry_cid"]),
                    "pooling": config.pooling,
                    "schema_version": EMBEDDING_PART_SCHEMA_VERSION,
                    "vector_space_id": config.vector_space_id,
                }
            )
        path = (
            source_root
            / "embeddings"
            / f"jurisdiction={jurisdiction_code}"
            / "part-000000.parquet"
        )
        write_zstd_parquet(
            path,
            output_rows,
            config=ArtifactWriterConfig(max_rows_per_shard=rows_per_part),
        )
        descriptor = describe_file(
            path,
            root=source_root,
            row_count=len(output_rows),
            family=ArtifactFamily.VECTORS,
            schema_id=EMBEDDING_PART_SCHEMA_VERSION,
            first_key=str(output_rows[0]["chunk_cid"]),
            last_key=str(output_rows[-1]["chunk_cid"]),
            shard_id=0,
            metadata={
                "jurisdiction_code": jurisdiction_code,
                "stage": "embedding_store",
            },
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
                "revision": config.model_revision,
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
        sort_receipt = {
            "family": "chunks",
            "interrupted": False,
            "max_records_in_memory": max_sort_records_in_memory,
            "output_digest": _sha256(f"sort-{jurisdiction_code}"),
            "output_path": (
                f"checkpoints/embedding_sort/{jurisdiction_code}/chunks.sorted.jsonl"
            ),
            "peak_resident_records": 1,
            "records_consumed": 1,
            "row_count": 1,
            "run_count": 1,
            "schema_version": "hf-graphrag-external-sort/v1",
            "status": "complete",
        }
        checkpoint = {
            "config": config.to_dict(),
            "config_digest": config.digest,
            "inference": inference,
            "jurisdiction_code": jurisdiction_code,
            "parts": [
                {
                    "descriptor": descriptor.to_dict(),
                    "document_index_start": 0,
                    "inference_digest": inference_digest,
                    "input_digest": _sha256(f"input-{jurisdiction_code}"),
                    "part_index": 0,
                    "row_count": 1,
                    "sha256": descriptor.sha256,
                }
            ],
            "production_ready": True,
            "row_count": 1,
            "schema_version": EMBEDDING_STORE_SCHEMA_VERSION,
            "sort_receipt": sort_receipt,
            "task_id": "state-laws-production-orchestrator-fixture",
        }
        checkpoint_path = (
            source_root
            / "checkpoints"
            / "embeddings"
            / f"{jurisdiction_code}.json"
        )
        atomic_write_canonical_json(checkpoint_path, checkpoint)
        return EmbeddingStoreResult(
            jurisdiction_code=jurisdiction_code,
            output_root=str(source_root),
            checkpoint_path=str(checkpoint_path),
            row_count=1,
            part_count=1,
            resumed_part_count=0,
            executed_part_count=1,
            descriptors=(descriptor.to_dict(),),
            config=config.to_dict(),
            inference=inference,
            sort_receipt=sort_receipt,
            production_ready=True,
        )

    return build


def _build_kwargs(tmp_path: Path, receipts: list[SourceReceiptRecord]):
    return {
        "source_receipts": receipts,
        "rights_receipt": _rights_receipt(),
        "source_input_digest": CANONICAL_FIXTURE_INPUT_DIGEST,
        "source_revision": PINNED_SOURCE_REVISION,
        "release_point": RELEASE_POINT,
        "output_root": tmp_path,
        "bm25_config": fixture_bm25_config(
            max_records_in_memory=16,
            max_rows_per_shard=16,
            postings_per_cell=16,
        ),
        "graph_config": StreamingGraphConfig(
            max_pointers_per_page=64,
            max_pointers_per_shard=256,
            max_records_in_memory=64,
            max_rows_per_shard=64,
            overwrite=True,
        ),
        "vector_options": {
            "kmeans_iterations": 1,
            "locator_page_size": 51,
            "max_centroids": 1,
            "max_rows_per_centroid": 1,
            "max_rows_per_shard": 1,
            "max_shards_per_centroid": 1,
            "max_sort_records_in_memory": 64,
            "max_training_rows": 1,
            "target_rows_per_centroid": 1,
        },
        "corpus_max_rows_per_shard": 16,
        "corpus_max_records_in_memory": 16,
        "chunk_max_rows_per_shard": 16,
        "chunk_max_records_in_memory": 16,
        "embedding_rows_per_part": 1,
        "embedding_max_sort_records_in_memory": 2,
        "graph_max_parent_rows_per_batch": 16,
    }


def test_exact_51_composition_digest_binding_fast_resume_and_local_gates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_data import (
        state_laws_production_orchestrator as orchestrator,
    )

    records, receipts = _records_and_receipts()
    embedding_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        orchestrator,
        "build_pinned_model_token_counter",
        lambda *_args, **_kwargs: (
            lambda text: len(str(text).split()) + 2,
            PINNED_TOKEN_COUNTER_ID,
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "build_state_laws_embedding_store",
        _fake_production_embedding_builder(embedding_calls),
    )
    kwargs = {
        **_build_kwargs(tmp_path, receipts),
        "source_input_digest": None,
    }

    first = build_state_laws_production_release(iter(reversed(records)), **kwargs)

    assert first.resumed_complete_release is False
    assert first.stage_order == STAGE_ORDER
    assert first.local_only is True
    assert first.network_io_performed is False
    assert first.authorizes_publication is False
    assert first.authorizes_hub_upload is False
    assert [item["code"] for item in embedding_calls] == list(
        CANONICAL_JURISDICTION_ORDER
    )
    assert all(
        set(item["offline"].values()) == {"1"} for item in embedding_calls
    )
    manifest = first.release.payload
    assert manifest["jurisdictions"] == list(CANONICAL_JURISDICTION_ORDER)
    assert manifest["validation"]["status"] == "passed"
    assert manifest["counts"]["corpus_documents"] == 51
    assert manifest["counts"]["searchable_chunks"] == 51
    assert manifest["counts"]["vector_rows"] == 51
    assert manifest["release_control"] == {
        "authorizes_hub_upload": False,
        "authorizes_publication": False,
        "fail_closed": True,
        "local_staging_only": True,
        "network_io_performed": False,
        "publication_action_performed": False,
    }
    assert (
        manifest["bm25"]["canonical_chunk_artifact_digest"]
        == manifest["indexes"]["corpus_chunks"]["sha256"]
    )
    assert (
        manifest["graph"]["vocabulary_parity"]["vocabulary_sha256"]
        == manifest["bm25"]["vocabulary_sha256"]
    )

    def forbidden(*_args, **_kwargs):  # pragma: no cover - assertion is behavior
        raise AssertionError("a verified complete release must not rerun writers")

    for name in (
        "write_state_laws_corpus_physical_layout_from_iterable",
        "write_state_laws_chunk_physical_layout",
        "build_state_laws_embedding_store",
        "write_state_laws_bm25_physical_layout_from_iterable",
        "write_state_laws_vector_physical_layout",
        "project_state_laws_streaming_graph_from_corpus",
        "write_state_laws_streaming_graph_layout",
        "assemble_state_laws_local_release_manifest",
    ):
        monkeypatch.setattr(orchestrator, name, forbidden)

    resumed = build_state_laws_production_release(None, **kwargs)
    assert resumed.resumed_complete_release is True
    assert resumed.release.manifest_digest == first.release.manifest_digest

    with pytest.raises(StateLawsProductionInputDriftError, match="does not match"):
        build_state_laws_production_release(
            None,
            **{
                **kwargs,
                "source_input_digest": _sha256("different-source-stream"),
            },
        )

    manifest_path = tmp_path / "manifest.json"
    tampered = json.loads(manifest_path.read_text(encoding="utf-8"))
    tampered["release_control"]["network_io_performed"] = True
    atomic_write_canonical_json(manifest_path, tampered)
    with pytest.raises(StateLawsProductionArtifactDriftError, match="bytes drifted"):
        build_state_laws_production_release(None, **kwargs)


def test_restart_after_vectors_preserves_stable_upstream_stage_digests(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_data import (
        state_laws_production_orchestrator as orchestrator,
    )

    records, receipts = _records_and_receipts()
    embedding_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        orchestrator,
        "build_pinned_model_token_counter",
        lambda *_args, **_kwargs: (
            lambda text: len(str(text).split()) + 2,
            PINNED_TOKEN_COUNTER_ID,
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "build_state_laws_embedding_store",
        _fake_production_embedding_builder(embedding_calls),
    )
    real_projector = orchestrator.project_state_laws_streaming_graph_from_corpus
    monkeypatch.setattr(
        orchestrator,
        "project_state_laws_streaming_graph_from_corpus",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("simulated post-vector interruption")
        ),
    )
    kwargs = {
        **_build_kwargs(tmp_path, receipts),
        "source_input_digest": None,
    }

    with pytest.raises(RuntimeError, match="post-vector interruption"):
        build_state_laws_production_release(iter(records), **kwargs)

    checkpoint_path = (
        tmp_path / "checkpoints/state_laws_production_orchestrator.json"
    )
    interrupted = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert (
        interrupted["build_contract"]["source_input_digest"]
        == CANONICAL_FIXTURE_INPUT_DIGEST
    )
    stable_stage_names = (
        "corpus",
        "canonical_chunks",
        "gte_small_embeddings",
        "streaming_bm25",
        "centroid_vectors",
    )
    interrupted_digests = {
        name: interrupted["stages"][name]["stage_digest"]
        for name in stable_stage_names
    }

    monkeypatch.setattr(
        orchestrator,
        "project_state_laws_streaming_graph_from_corpus",
        real_projector,
    )
    resumed = build_state_laws_production_release(None, **kwargs)
    completed = json.loads(checkpoint_path.read_text(encoding="utf-8"))

    assert resumed.resumed_complete_release is False
    assert completed["status"] == "complete"
    assert {
        name: completed["stages"][name]["stage_digest"]
        for name in stable_stage_names
    } == interrupted_digests
    assert len(embedding_calls) == 2 * len(CANONICAL_JURISDICTION_ORDER)


@pytest.mark.parametrize("gate", ["missing_jurisdiction", "projection_embedding"])
def test_orchestrator_rejects_release_gate_failures_before_writing(
    tmp_path: Path,
    gate: str,
) -> None:
    records, receipts = _records_and_receipts()
    kwargs = _build_kwargs(tmp_path, receipts)
    if gate == "missing_jurisdiction":
        kwargs["source_receipts"] = receipts[:-1]
        expected = "exactly 51"
    else:
        kwargs["embedding_config"] = fixture_embedding_config()
        expected = "sealed real GTE-small"

    with pytest.raises(StateLawsProductionGateError, match=expected):
        build_state_laws_production_release(iter(records), **kwargs)

    assert not (tmp_path / "manifest.json").exists()
    assert not (
        tmp_path / "checkpoints/state_laws_production_orchestrator.json"
    ).exists()


def test_first_build_verifies_canonical_input_bytes_before_checkpointing(
    tmp_path: Path,
) -> None:
    records, receipts = _records_and_receipts()
    kwargs = {
        **_build_kwargs(tmp_path, receipts),
        "source_input_digest": _sha256("caller-only-unverified-claim"),
    }

    with pytest.raises(
        StateLawsProductionInputDriftError,
        match="canonical admitted input bytes",
    ):
        build_state_laws_production_release(iter(reversed(records)), **kwargs)

    assert not (
        tmp_path / "checkpoints/state_laws_production_orchestrator.json"
    ).exists()
    assert not (tmp_path / "manifest.json").exists()


def test_legacy_router_and_blank_model_checkpoint_is_never_admitted(
    tmp_path: Path,
) -> None:
    _, receipts = _records_and_receipts()
    kwargs = _build_kwargs(tmp_path, receipts)
    checkpoint_path = (
        tmp_path / "checkpoints/state_laws_production_orchestrator.json"
    )
    legacy = {
        "embedding_model": "",
        "embeddings_router": {
            "jurisdiction_count": 18,
            "layout": "one-row-per-document",
        },
        "schema_version": "state-laws-local-rebuild-checkpoint/v0",
        "status": "complete",
    }
    atomic_write_canonical_json(checkpoint_path, legacy)
    legacy_bytes = checkpoint_path.read_bytes()

    with pytest.raises(
        StateLawsProductionInputDriftError,
        match="legacy embeddings_router or blank-model",
    ):
        build_state_laws_production_release(None, **kwargs)

    assert checkpoint_path.read_bytes() == legacy_bytes
    assert not (tmp_path / "manifest.json").exists()
