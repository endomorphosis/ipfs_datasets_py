"""Integration tests for resumable Open US Law streaming builds (OUL-025).

Proves the software contract: jurisdiction-checkpointed builders resume
after interruption, stay bounded-memory, externally sort documents /
postings / embeddings, and remain byte-deterministic. A green run never
authorizes the exact-51 corpus or publication.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_streaming import (
    AUTHORIZES_EXACT_51_CORPUS,
    Exact51AuthorizationError,
    MemoryBudget,
    PartialCheckpointPromotionError,
    StreamingCheckpointError,
    StreamingConfig,
    assert_software_contract_only,
    compute_seal,
    document_sort_key,
    external_sort_to_file,
    fixture_document_source,
    fixture_jurisdiction_documents,
    iter_jsonl,
    posting_sort_key,
    run_fixture_streaming_build,
    stream_chunk_documents,
    stream_placeholder_vectors,
    stream_postings_from_chunks,
    vector_sort_key,
)


JURISDICTIONS = ("AL", "AK", "AZ")
FAMILIES = ("chunks", "documents", "postings", "vectors")


def _artifact_payloads(result) -> dict[str, list[dict]]:
    payloads: dict[str, list[dict]] = {}
    for key, rec in result.checkpoint.units.items():
        if rec.artifact_path:
            payloads[key] = list(iter_jsonl(rec.artifact_path))
    return payloads


def test_resume_after_interruption_is_byte_identical_to_clean_run(
    tmp_path: Path,
) -> None:
    interrupted_dir = tmp_path / "interrupted"
    clean_dir = tmp_path / "clean"
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
        interrupted_dir,
        jurisdictions=JURISDICTIONS,
        families=FAMILIES,
        docs_per_jurisdiction=7,
        extra_tokens=30,
        interrupt_after_units=3,
        producer=counting_producer,
        max_records_in_memory=5,
    )
    assert first.interrupted is True
    assert first.checkpoint.sealed is False
    assert first.seal is None
    assert first.checkpoint.verified_count == 3
    assert first.to_dict()["authorizing_for_exact_51"] is False
    with pytest.raises(PartialCheckpointPromotionError):
        compute_seal(first.checkpoint)

    first_executed = list(executed)
    resumed = run_fixture_streaming_build(
        interrupted_dir,
        jurisdictions=JURISDICTIONS,
        families=FAMILIES,
        docs_per_jurisdiction=7,
        extra_tokens=30,
        resume=True,
        producer=counting_producer,
        max_records_in_memory=5,
    )
    assert resumed.interrupted is False
    assert resumed.checkpoint.sealed is True
    assert resumed.checkpoint.all_verified is True
    assert resumed.seal is not None
    assert set(resumed.resumed_keys) == set(first_executed)
    assert set(resumed.executed_keys).isdisjoint(set(resumed.resumed_keys))
    for key in first_executed:
        assert executed.count(key) == 1
    assert len(executed) == len(JURISDICTIONS) * len(FAMILIES)

    clean = run_fixture_streaming_build(
        clean_dir,
        jurisdictions=JURISDICTIONS,
        families=FAMILIES,
        docs_per_jurisdiction=7,
        extra_tokens=30,
        resume=False,
        max_records_in_memory=5,
    )
    assert resumed.artifact_digests == clean.artifact_digests
    assert resumed.checkpoint.seal_digest == clean.checkpoint.seal_digest
    assert _artifact_payloads(resumed) == _artifact_payloads(clean)
    receipt = json.loads(Path(resumed.receipt_path).read_text(encoding="utf-8"))
    assert_software_contract_only(receipt)
    assert receipt["interrupted"] is False


def test_multi_jurisdiction_checkpoint_skips_verified_units(tmp_path: Path) -> None:
    store, source = fixture_document_source(JURISDICTIONS, docs_per_jurisdiction=5)
    output = tmp_path / "ckpt"
    first = run_fixture_streaming_build(
        output,
        jurisdictions=JURISDICTIONS,
        families=("chunks", "documents"),
        interrupt_after_units=2,
        document_source=source,
        max_records_in_memory=4,
    )
    assert first.interrupted is True
    verified = {
        key for key, rec in first.checkpoint.units.items() if rec.verified
    }
    assert len(verified) == 2

    second = run_fixture_streaming_build(
        output,
        jurisdictions=JURISDICTIONS,
        families=("chunks", "documents"),
        resume=True,
        document_source=source,
        max_records_in_memory=4,
    )
    assert second.checkpoint.sealed is True
    assert set(second.resumed_keys) == verified
    for key in verified:
        assert second.checkpoint.units[key].output_digest == (
            first.checkpoint.units[key].output_digest
        )
        assert second.checkpoint.units[key].artifact_path == (
            first.checkpoint.units[key].artifact_path
        )
    # Fixture store is local and incomplete; the receipt still denies exact-51.
    assert AUTHORIZES_EXACT_51_CORPUS is False
    assert store["AL"]
    assert "GA" not in store


def test_documents_postings_vectors_sorted_without_loading_all(
    tmp_path: Path,
) -> None:
    docs = fixture_jurisdiction_documents("CO", count=40, extra_tokens=8)
    chunks = list(stream_chunk_documents(docs, model_token_limit=512))
    assert chunks
    assert all(row["model_token_limit"] == 512 for row in chunks)

    budget = MemoryBudget(max_resident_records=6)
    postings = stream_postings_from_chunks(
        (row for row in chunks),
        budget=MemoryBudget(max_resident_records=1),
    )
    posting_receipt = external_sort_to_file(
        postings,
        tmp_path / "postings.jsonl",
        work_dir=tmp_path / "postings-sort",
        key_fn=posting_sort_key,
        family="postings",
        max_records_in_memory=6,
        budget=budget,
        resume=False,
    )
    assert posting_receipt.row_count > len(chunks)
    assert posting_receipt.peak_resident_records <= 6
    posting_rows = list(iter_jsonl(posting_receipt.output_path))
    assert [posting_sort_key(row) for row in posting_rows] == sorted(
        posting_sort_key(row) for row in posting_rows
    )

    vector_budget = MemoryBudget(max_resident_records=6)
    vectors = stream_placeholder_vectors(
        (row for row in chunks),
        budget=MemoryBudget(max_resident_records=1),
    )
    vector_receipt = external_sort_to_file(
        vectors,
        tmp_path / "vectors.jsonl",
        work_dir=tmp_path / "vectors-sort",
        key_fn=vector_sort_key,
        family="vectors",
        max_records_in_memory=6,
        budget=vector_budget,
        resume=False,
    )
    assert vector_receipt.row_count == len(chunks)
    assert vector_receipt.peak_resident_records <= 6
    vector_rows = list(iter_jsonl(vector_receipt.output_path))
    assert [vector_sort_key(row) for row in vector_rows] == sorted(
        vector_sort_key(row) for row in vector_rows
    )
    assert all(row["production_inference"] is False for row in vector_rows)

    document_budget = MemoryBudget(max_resident_records=6)
    document_receipt = external_sort_to_file(
        (
            {
                "document_index": doc.document_index,
                "entry_cid": doc.entry_cid,
                "jurisdiction_code": doc.jurisdiction_code,
            }
            for doc in reversed(docs)
        ),
        tmp_path / "documents.jsonl",
        work_dir=tmp_path / "documents-sort",
        key_fn=document_sort_key,
        family="documents",
        max_records_in_memory=6,
        budget=document_budget,
        resume=False,
    )
    assert document_receipt.row_count == 40
    assert document_budget.peak_resident_records <= 6
    document_rows = list(iter_jsonl(document_receipt.output_path))
    assert [row["document_index"] for row in document_rows] == list(range(40))


def test_partial_checkpoint_is_not_promoted_to_success(tmp_path: Path) -> None:
    result = run_fixture_streaming_build(
        tmp_path / "partial",
        jurisdictions=JURISDICTIONS,
        families=FAMILIES,
        docs_per_jurisdiction=4,
        interrupt_after_units=2,
        max_records_in_memory=4,
    )
    assert result.interrupted is True
    assert result.checkpoint.sealed is False
    assert result.seal is None
    receipt = json.loads(Path(result.receipt_path).read_text(encoding="utf-8"))
    assert receipt["sealed"] is False
    assert receipt["interrupted"] is True
    assert receipt["authorizing_for_exact_51"] is False
    assert_software_contract_only(receipt)
    with pytest.raises(PartialCheckpointPromotionError):
        compute_seal(result.checkpoint)
    payload = result.checkpoint.to_dict()
    payload["sealed"] = True
    from ipfs_datasets_py.processors.legal_data.open_us_law_streaming import (
        StreamingCheckpoint,
    )

    with pytest.raises(PartialCheckpointPromotionError):
        StreamingCheckpoint.from_mapping(payload)


def test_config_mismatch_on_resume_fails_closed(tmp_path: Path) -> None:
    output = tmp_path / "mismatch"
    run_fixture_streaming_build(
        output,
        jurisdictions=("AL", "AK"),
        families=("chunks", "documents"),
        docs_per_jurisdiction=3,
        max_records_in_memory=4,
    )
    with pytest.raises(StreamingCheckpointError, match="config_digest"):
        run_fixture_streaming_build(
            output,
            jurisdictions=("AL", "AK"),
            families=("chunks", "documents", "postings"),
            docs_per_jurisdiction=3,
            resume=True,
            max_records_in_memory=4,
        )
    with pytest.raises(StreamingCheckpointError, match="config_digest"):
        run_fixture_streaming_build(
            output,
            jurisdictions=("AL", "AK"),
            families=("chunks", "documents"),
            docs_per_jurisdiction=3,
            resume=True,
            max_records_in_memory=16,
        )


def test_software_contract_receipt_denies_exact_51_even_for_51_fixture_codes(
    tmp_path: Path,
) -> None:
    from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
        EXACT_51_JURISDICTION_CODES,
    )

    # A 51-code fixture still cannot authorize the live corpus.
    result = run_fixture_streaming_build(
        tmp_path / "fifty-one",
        jurisdictions=EXACT_51_JURISDICTION_CODES,
        families=("documents",),
        docs_per_jurisdiction=1,
        max_records_in_memory=8,
    )
    assert result.checkpoint.sealed is True
    assert len(result.checkpoint.units) == 51
    receipt = json.loads(Path(result.receipt_path).read_text(encoding="utf-8"))
    assert_software_contract_only(receipt)
    assert receipt["authorizing_for_exact_51"] is False
    with pytest.raises(Exact51AuthorizationError):
        StreamingConfig(
            jurisdictions=EXACT_51_JURISDICTION_CODES,
            families=("documents",),
            claim_exact_51=True,
        )


def test_external_sort_resume_mid_spill_matches_clean_bytes(tmp_path: Path) -> None:
    records = [
        {
            "term": f"term-{index % 11:02d}",
            "entry_cid": f"{index:064x}",
            "tf": (index % 5) + 1,
        }
        for index in range(60)
    ]
    work = tmp_path / "sort-resume"
    interrupted = external_sort_to_file(
        records,
        tmp_path / "postings.jsonl",
        work_dir=work,
        key_fn=posting_sort_key,
        family="postings",
        max_records_in_memory=7,
        interrupt_after_runs=3,
    )
    assert interrupted.interrupted is True
    assert interrupted.output_digest == ""

    resumed = external_sort_to_file(
        records,
        tmp_path / "postings.jsonl",
        work_dir=work,
        key_fn=posting_sort_key,
        family="postings",
        max_records_in_memory=7,
        resume=True,
    )
    clean = external_sort_to_file(
        list(reversed(records)),
        tmp_path / "clean-postings.jsonl",
        work_dir=tmp_path / "sort-clean",
        key_fn=posting_sort_key,
        family="postings",
        max_records_in_memory=7,
        resume=False,
    )
    assert resumed.interrupted is False
    assert resumed.output_digest == clean.output_digest
    assert resumed.row_count == 60
    assert resumed.peak_resident_records <= 7
    keys = [posting_sort_key(row) for row in iter_jsonl(resumed.output_path)]
    assert keys == sorted(keys)


def test_completed_sort_checkpoint_is_replayed_without_resorting(
    tmp_path: Path,
) -> None:
    records = [{"document_index": i, "entry_cid": f"{i:064x}"} for i in range(12)]
    work = tmp_path / "replay"
    first = external_sort_to_file(
        records,
        tmp_path / "docs.jsonl",
        work_dir=work,
        family="documents",
        max_records_in_memory=4,
        resume=True,
    )
    second = external_sort_to_file(
        [],
        tmp_path / "docs.jsonl",
        work_dir=work,
        family="documents",
        max_records_in_memory=4,
        resume=True,
    )
    assert second.output_digest == first.output_digest
    assert second.row_count == first.row_count
    assert second.interrupted is False
