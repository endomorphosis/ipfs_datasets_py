"""Unit tests for streaming chunking, checkpoints, and external sort (OUL-025).

Acceptance: Corpus-scale builders are bounded-memory, jurisdiction-
checkpointed, resumable after interruption, externally sorted, and
byte-deterministic without loading all documents, postings, or embeddings
into RAM. Completion proves the reusable software contract only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_streaming import (
    AUTHORIZES_EXACT_51_CORPUS,
    AUTHORIZES_PUBLICATION,
    DEFAULT_FAMILIES,
    DEFAULT_MAX_RECORDS_IN_MEMORY,
    DEFAULT_MODEL_TOKEN_LIMIT,
    GOAL_ID,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    PRODUCER,
    PROGRAM_ID,
    PROVES_SOFTWARE_CONTRACT_ONLY,
    SCHEMA_VERSION,
    TASK_ID,
    Exact51AuthorizationError,
    ExternalSortError,
    MemoryBudget,
    MemoryBudgetError,
    OpenUsLawChunker,
    PartialCheckpointPromotionError,
    SealError,
    SourceDocument,
    StreamingBuildOrchestrator,
    StreamingCheckpointError,
    StreamingConfig,
    StreamingConfigError,
    WorkUnitStatus,
    assert_checkpoint_compatible,
    assert_chunks_within_limit,
    assert_exact_reconstruction,
    assert_software_contract_only,
    authorizing_for_exact_51_corpus,
    chunk_statute,
    compute_seal,
    count_tokens,
    document_sort_key,
    external_sort,
    external_sort_to_file,
    fixture_jurisdiction_documents,
    fixture_statute_text,
    iter_jsonl,
    iter_physical_shards,
    load_checkpoint,
    materialize_records,
    posting_sort_key,
    reconstruct_text,
    reject_exact_51_authorization,
    run_fixture_streaming_build,
    software_contract_flags,
    stream_chunk_documents,
    stream_document_records,
    stream_placeholder_vectors,
    stream_postings_from_chunks,
    validate_model_token_limit,
    vector_sort_key,
    write_checkpoint_atomic,
    write_jsonl_atomic,
)


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "open-us-law-streaming-v1"
    assert TASK_ID == "OUL-025"
    assert GOAL_ID == "OUL-G030"
    assert PROGRAM_ID == "open-us-law-reindex-v1"
    assert PRODUCER == "open_us_law_streaming.py"
    assert DEFAULT_FAMILIES == ("chunks", "documents", "postings", "vectors")
    assert DEFAULT_MAX_RECORDS_IN_MEMORY == 256


def test_software_contract_does_not_authorize_exact_51() -> None:
    assert AUTHORIZES_EXACT_51_CORPUS is False
    assert AUTHORIZES_PUBLICATION is False
    assert PROVES_SOFTWARE_CONTRACT_ONLY is True
    assert authorizing_for_exact_51_corpus() is False
    flags = software_contract_flags()
    assert flags["authorizing_for_exact_51"] is False
    assert flags["authorizing_for_publication"] is False
    assert flags["proves_software_contract_only"] is True
    with pytest.raises(Exact51AuthorizationError):
        reject_exact_51_authorization(True)
    reject_exact_51_authorization(False)
    with pytest.raises(Exact51AuthorizationError, match="software contract"):
        StreamingConfig(jurisdictions=("AL",), claim_exact_51=True)
    with pytest.raises(Exact51AuthorizationError):
        assert_software_contract_only(
            {
                "authorizing_for_exact_51": True,
                "authorizing_for_publication": False,
                "proves_software_contract_only": True,
            }
        )


def test_token_ceiling_is_512_not_physical_shard_bound() -> None:
    assert DEFAULT_MODEL_TOKEN_LIMIT == 512
    assert MAX_ROWS_PER_PHYSICAL_SHARD == 4096
    assert DEFAULT_MODEL_TOKEN_LIMIT != MAX_ROWS_PER_PHYSICAL_SHARD
    config = StreamingConfig(jurisdictions=("AL", "AK"))
    assert config.model_token_limit == 512
    assert config.to_dict()["uses_shard_bound_as_token_limit"] is False


def test_validate_model_token_limit_requires_explicit_positive_int() -> None:
    with pytest.raises(StreamingConfigError, match="required"):
        validate_model_token_limit(None)
    with pytest.raises(StreamingConfigError):
        validate_model_token_limit(0)
    with pytest.raises(StreamingConfigError):
        validate_model_token_limit("abc")
    assert validate_model_token_limit(512) == 512
    # Explicit 4096 is allowed only as a caller opt-in, never a default.
    assert validate_model_token_limit(4096) == 4096


def test_mutable_edition_rejected() -> None:
    with pytest.raises(StreamingConfigError, match="exact pin"):
        StreamingConfig(jurisdictions=("AL",), edition="latest")


def test_chunker_keeps_non_exempt_chunks_within_512() -> None:
    text = "alpha " * 600
    result = chunk_statute(
        {
            "jurisdiction_code": "OR",
            "text": text,
            "title": "1",
            "chapter": "1",
            "section": "10",
            "document_index": 0,
        },
        model_token_limit=512,
    )
    assert result.source_token_count == 600
    assert result.model_token_limit == 512
    assert len(result.chunks) >= 2
    assert_chunks_within_limit(result.chunks, 512)
    for chunk in result.chunks:
        assert chunk.token_count <= 512
        assert count_tokens(chunk.text) <= 512
        assert chunk.limit_exempt is False


def test_chunker_exact_reconstruction_and_determinism() -> None:
    doc = SourceDocument(
        jurisdiction_code="WA",
        text=fixture_statute_text("WA", 7, extra_tokens=40),
        title="2",
        chapter="4",
        section="7",
        document_index=6,
    )
    first = chunk_statute(doc, model_token_limit=512)
    second = chunk_statute(doc, model_token_limit=512)
    assert_exact_reconstruction(first.source_text, first.chunks)
    assert reconstruct_text(first.chunks) == first.source_text
    assert [c.to_dict() for c in first.chunks] == [c.to_dict() for c in second.chunks]
    assert first.chunks[0].entry_cid == second.chunks[0].entry_cid


def test_structural_split_on_markers() -> None:
    text = (
        "Preamble sentence. (a) First subsection with several extra tokens here. "
        "(b) Second subsection. (1) Nested paragraph. (2) Another nested paragraph."
    )
    result = chunk_statute(
        {
            "jurisdiction_code": "ME",
            "text": text,
            "section": "3",
        },
        model_token_limit=12,
    )
    assert len(result.chunks) >= 2
    assert_exact_reconstruction(result.source_text, result.chunks)
    modes = {chunk.split_mode for chunk in result.chunks}
    assert modes & {"structure", "sentence", "hard", "whole"}


def test_huge_section_is_bounded() -> None:
    result = OpenUsLawChunker(max_chunks_per_section=3).chunk_document(
        {
            "jurisdiction_code": "ID",
            "text": "word " * 400,
            "section": "99",
        },
        model_token_limit=20,
    )
    assert len(result.chunks) <= 3
    assert result.truncated is True
    assert_chunks_within_limit(result.chunks, 20)


def test_stream_chunk_documents_holds_one_document() -> None:
    docs = fixture_jurisdiction_documents("MT", count=12)
    budget = MemoryBudget(max_resident_records=1)
    chunks = list(
        stream_chunk_documents(
            (doc for doc in docs),
            model_token_limit=512,
            budget=budget,
        )
    )
    assert chunks
    assert budget.peak_resident_records == 1
    assert budget.resident_records == 0
    assert all(item["jurisdiction_code"] == "MT" for item in chunks)


def test_memory_budget_rejects_unbounded_materialization() -> None:
    budget = MemoryBudget(max_resident_records=8)
    with pytest.raises(MemoryBudgetError, match="resident records"):
        materialize_records(({"i": index} for index in range(100)), budget=budget)
    budget.check_materialize(8)
    with pytest.raises(MemoryBudgetError, match="refusing to materialize"):
        budget.check_materialize(9)


def test_external_sort_is_byte_deterministic(tmp_path: Path) -> None:
    records = [
        {"document_index": 3, "entry_cid": "c" * 64, "term": "zeta"},
        {"document_index": 1, "entry_cid": "a" * 64, "term": "alpha"},
        {"document_index": 2, "entry_cid": "b" * 64, "term": "mu"},
        {"document_index": 1, "entry_cid": "a" * 64, "term": "alpha"},
    ]
    first = external_sort_to_file(
        reversed(records),
        tmp_path / "a.jsonl",
        work_dir=tmp_path / "sort-a",
        key_fn=document_sort_key,
        family="documents",
        max_records_in_memory=2,
        resume=False,
    )
    second = external_sort_to_file(
        records,
        tmp_path / "b.jsonl",
        work_dir=tmp_path / "sort-b",
        key_fn=document_sort_key,
        family="documents",
        max_records_in_memory=2,
        resume=False,
    )
    assert first.interrupted is False
    assert first.output_digest == second.output_digest
    assert first.row_count == 4
    ordered = list(iter_jsonl(first.output_path))
    assert [row["document_index"] for row in ordered] == [1, 1, 2, 3]


def test_external_sort_peak_resident_records_bounded(tmp_path: Path) -> None:
    n_records = 80
    max_resident = 8
    budget = MemoryBudget(max_resident_records=max_resident)
    records = (
        {"document_index": (n_records - index), "entry_cid": f"{index:064x}"}
        for index in range(n_records)
    )
    receipt = external_sort_to_file(
        records,
        tmp_path / "sorted.jsonl",
        work_dir=tmp_path / "work",
        key_fn=document_sort_key,
        family="documents",
        max_records_in_memory=max_resident,
        budget=budget,
        resume=False,
    )
    assert receipt.row_count == n_records
    assert receipt.peak_resident_records <= max_resident
    assert receipt.run_count >= (n_records // max_resident)
    keys = [document_sort_key(row) for row in iter_jsonl(receipt.output_path)]
    assert keys == sorted(keys)


def test_external_sort_empty_input(tmp_path: Path) -> None:
    receipt = external_sort_to_file(
        (),
        tmp_path / "empty.jsonl",
        work_dir=tmp_path / "empty-work",
        family="documents",
        resume=False,
    )
    assert receipt.row_count == 0
    assert receipt.output_digest
    assert list(iter_jsonl(receipt.output_path)) == []


def test_external_sort_iterator_rejects_interrupted_state(tmp_path: Path) -> None:
    records = [{"document_index": i, "entry_cid": f"{i:064x}"} for i in range(20)]
    receipt = external_sort_to_file(
        records,
        tmp_path / "partial.jsonl",
        work_dir=tmp_path / "mid",
        family="documents",
        max_records_in_memory=4,
        interrupt_after_runs=1,
    )
    assert receipt.interrupted is True
    assert receipt.status == "interrupted"


def test_external_sort_resume_after_run_spill(tmp_path: Path) -> None:
    records = [{"document_index": i, "entry_cid": f"{i:064x}"} for i in range(25)]
    work = tmp_path / "resume-sort"
    first = external_sort_to_file(
        records,
        tmp_path / "out.jsonl",
        work_dir=work,
        family="documents",
        max_records_in_memory=5,
        interrupt_after_runs=2,
    )
    assert first.interrupted is True
    second = external_sort_to_file(
        records,
        tmp_path / "out.jsonl",
        work_dir=work,
        family="documents",
        max_records_in_memory=5,
        resume=True,
    )
    assert second.interrupted is False
    clean = external_sort_to_file(
        records,
        tmp_path / "clean.jsonl",
        work_dir=tmp_path / "clean-work",
        family="documents",
        max_records_in_memory=5,
        resume=False,
    )
    assert second.output_digest == clean.output_digest
    assert second.row_count == 25


def test_documents_postings_vectors_sort_keys() -> None:
    documents = [
        {"document_index": 2, "entry_cid": "b" * 64},
        {"document_index": 1, "entry_cid": "a" * 64},
    ]
    assert document_sort_key(documents[1]) < document_sort_key(documents[0])
    postings = [
        {"term": "zoning", "entry_cid": "b" * 64},
        {"term": "apple", "entry_cid": "a" * 64},
    ]
    assert posting_sort_key(postings[1]) < posting_sort_key(postings[0])
    high = {"cosine_to_centroid": 0.9, "entry_cid": "b" * 64}
    low = {"cosine_to_centroid": 0.1, "entry_cid": "a" * 64}
    # Descending cosine: higher similarity sorts first.
    assert vector_sort_key(high) < vector_sort_key(low)
    with pytest.raises(ExternalSortError):
        vector_sort_key({"cosine_to_centroid": float("nan"), "entry_cid": "a" * 64})


def test_streamed_postings_and_vectors_do_not_accumulate_globally() -> None:
    chunks = list(
        stream_chunk_documents(
            fixture_jurisdiction_documents("UT", count=5),
            model_token_limit=512,
        )
    )
    budget = MemoryBudget(max_resident_records=1)
    postings = list(stream_postings_from_chunks(chunks, budget=budget))
    assert postings
    assert budget.peak_resident_records == 1
    assert all("term" in row and "entry_cid" in row for row in postings)
    vectors = list(
        stream_placeholder_vectors(chunks, budget=MemoryBudget(max_resident_records=1))
    )
    assert len(vectors) == len(chunks)
    assert all(row["production_inference"] is False for row in vectors)
    assert all(row["backend"] == "fixture_placeholder" for row in vectors)
    assert all(row["dimension"] == 384 for row in vectors)


def test_physical_shards_respect_4096() -> None:
    records = ({"document_index": i, "entry_cid": f"{i:064x}"} for i in range(10))
    shards = list(iter_physical_shards(records, max_rows=4))
    assert [len(shard) for shard in shards] == [4, 4, 2]
    with pytest.raises(StreamingConfigError):
        list(iter_physical_shards(({"i": 1} for _ in range(1)), max_rows=4097))


def test_checkpoint_roundtrip_atomic(tmp_path: Path) -> None:
    result = run_fixture_streaming_build(
        tmp_path / "out",
        jurisdictions=("AL",),
        families=("chunks", "documents"),
        docs_per_jurisdiction=4,
        max_records_in_memory=3,
    )
    loaded = load_checkpoint(result.checkpoint_path)
    assert loaded.config_digest == result.checkpoint.config_digest
    assert loaded.sealed is True
    assert loaded.all_verified is True
    assert loaded.schema_version == SCHEMA_VERSION
    assert loaded.to_dict()["authorizing_for_exact_51"] is False
    copy_path = tmp_path / "copy.json"
    write_checkpoint_atomic(copy_path, loaded)
    again = load_checkpoint(copy_path)
    assert again.to_dict() == loaded.to_dict()


def test_stale_config_checkpoint_fails(tmp_path: Path) -> None:
    output = tmp_path / "out"
    run_fixture_streaming_build(
        output,
        jurisdictions=("AL", "AK"),
        families=("chunks",),
        docs_per_jurisdiction=3,
    )
    with pytest.raises(StreamingCheckpointError, match="config_digest"):
        run_fixture_streaming_build(
            output,
            jurisdictions=("AL", "AK", "AZ"),
            families=("chunks",),
            docs_per_jurisdiction=3,
            resume=True,
        )


def test_schema_mismatched_checkpoint_fails(tmp_path: Path) -> None:
    result = run_fixture_streaming_build(
        tmp_path / "out",
        jurisdictions=("AL",),
        families=("documents",),
        docs_per_jurisdiction=2,
    )
    path = Path(result.checkpoint_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = "not-a-real-schema"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(StreamingCheckpointError, match="schema_version"):
        load_checkpoint(path)


def test_partial_checkpoint_cannot_be_sealed(tmp_path: Path) -> None:
    result = run_fixture_streaming_build(
        tmp_path / "out",
        jurisdictions=("AL", "AK"),
        families=("chunks", "documents"),
        docs_per_jurisdiction=3,
        interrupt_after_units=1,
    )
    assert result.interrupted is True
    assert result.checkpoint.sealed is False
    assert result.seal is None
    with pytest.raises(PartialCheckpointPromotionError):
        compute_seal(result.checkpoint)
    orchestrator = StreamingBuildOrchestrator(
        output_dir=tmp_path / "out",
        document_source=lambda _code: fixture_jurisdiction_documents("AL", count=3),
    )
    config = StreamingConfig(
        jurisdictions=("AL", "AK"),
        families=("chunks", "documents"),
        max_records_in_memory=8,
    )
    with pytest.raises((SealError, PartialCheckpointPromotionError)):
        orchestrator.seal_existing(config)


def test_interrupted_build_resumes_without_duplicating_verified_work(
    tmp_path: Path,
) -> None:
    output = tmp_path / "out"
    executed: list[str] = []

    def counting_producer(jurisdiction, family, config, output_dir, documents):
        from ipfs_datasets_py.processors.legal_data.open_us_law_streaming import (
            default_family_producer,
        )

        executed.append(f"{jurisdiction}/{family}")
        return default_family_producer(
            jurisdiction, family, config, output_dir, documents
        )

    first = run_fixture_streaming_build(
        output,
        jurisdictions=("AL", "AK"),
        families=("chunks", "documents"),
        docs_per_jurisdiction=4,
        interrupt_after_units=1,
        producer=counting_producer,
        max_records_in_memory=4,
    )
    assert first.interrupted is True
    assert first.checkpoint.sealed is False
    assert first.checkpoint.verified_count == 1
    assert len(executed) == 1
    first_key = executed[0]

    second = run_fixture_streaming_build(
        output,
        jurisdictions=("AL", "AK"),
        families=("chunks", "documents"),
        docs_per_jurisdiction=4,
        resume=True,
        producer=counting_producer,
        max_records_in_memory=4,
    )
    assert second.interrupted is False
    assert second.seal is not None
    assert second.checkpoint.sealed is True
    assert second.checkpoint.all_verified is True
    assert first_key in second.resumed_keys
    assert first_key not in second.executed_keys
    assert executed.count(first_key) == 1
    assert len(executed) == 4


def test_two_clean_fixture_runs_are_byte_deterministic(tmp_path: Path) -> None:
    first = run_fixture_streaming_build(
        tmp_path / "a",
        jurisdictions=("OR", "WA"),
        families=("chunks", "documents", "postings", "vectors"),
        docs_per_jurisdiction=5,
        max_records_in_memory=4,
    )
    second = run_fixture_streaming_build(
        tmp_path / "b",
        jurisdictions=("OR", "WA"),
        families=("chunks", "documents", "postings", "vectors"),
        docs_per_jurisdiction=5,
        max_records_in_memory=4,
    )
    assert first.artifact_digests == second.artifact_digests
    assert first.checkpoint.seal_digest == second.checkpoint.seal_digest
    assert first.to_dict()["authorizing_for_exact_51"] is False
    assert_software_contract_only(first.to_dict())


def test_receipt_never_authorizes_publication(tmp_path: Path) -> None:
    result = run_fixture_streaming_build(
        tmp_path / "out",
        jurisdictions=("DC",),
        families=("chunks",),
        docs_per_jurisdiction=2,
    )
    receipt = json.loads(Path(result.receipt_path).read_text(encoding="utf-8"))
    assert receipt["authorizing_for_exact_51"] is False
    assert receipt["authorizing_for_publication"] is False
    assert receipt["proves_software_contract_only"] is True
    assert receipt["sealed"] is True
    assert_software_contract_only(receipt)


def test_assert_checkpoint_compatible_rejects_digest_drift(tmp_path: Path) -> None:
    result = run_fixture_streaming_build(
        tmp_path / "out",
        jurisdictions=("AL",),
        families=("documents",),
        docs_per_jurisdiction=2,
    )
    other = StreamingConfig(jurisdictions=("AK",), families=("documents",))
    with pytest.raises(StreamingCheckpointError):
        assert_checkpoint_compatible(result.checkpoint, other)


def test_jsonl_roundtrip_is_canonical(tmp_path: Path) -> None:
    records = [{"b": 2, "a": 1}, {"b": 0, "a": 3}]
    written = write_jsonl_atomic(tmp_path / "rows.jsonl", records)
    assert written.row_count == 2
    lines = Path(written.path).read_text(encoding="utf-8").splitlines()
    assert lines[0] == '{"a":1,"b":2}'
    loaded = list(iter_jsonl(written.path))
    assert loaded == [{"a": 1, "b": 2}, {"a": 3, "b": 0}]


def test_stream_document_records_are_identity_complete() -> None:
    docs = fixture_jurisdiction_documents("NH", count=2)
    rows = list(stream_document_records(docs))
    assert len(rows) == 2
    assert rows[0]["legal_id"].startswith("oul:statute:NH:")
    assert len(rows[0]["entry_cid"]) == 64
    assert rows[0]["production_materialization"] is False


def test_external_sort_iterator_api(tmp_path: Path) -> None:
    records = [{"document_index": 2, "entry_cid": "b" * 64}, {"document_index": 1, "entry_cid": "a" * 64}]
    ordered = list(
        external_sort(
            records,
            work_dir=tmp_path / "iter",
            key_fn=document_sort_key,
            family="documents",
            max_records_in_memory=2,
        )
    )
    assert [row["document_index"] for row in ordered] == [1, 2]


def test_work_unit_status_and_unit_record_key() -> None:
    from ipfs_datasets_py.processors.legal_data.open_us_law_streaming import (
        JurisdictionUnitRecord,
    )

    rec = JurisdictionUnitRecord(
        jurisdiction="al",
        family="chunk",
        status="verified",
        input_hash="a" * 64,
        output_digest="b" * 64,
    )
    assert rec.jurisdiction == "AL"
    assert rec.family == "chunks"
    assert rec.key == "AL/chunks"
    assert rec.status is WorkUnitStatus.VERIFIED
    assert rec.verified is True
