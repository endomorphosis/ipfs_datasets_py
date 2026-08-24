"""Unit tests for the domain-neutral HF GraphRAG external sort (OUL-026).

Acceptance: builders stream bounded partitions; spill/merge stays under a
memory bound; clean resume is byte-deterministic without loading the full
corpus, postings, or embeddings into RAM.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.retrieval.hf_graphrag.external_sort import (
    CHECKPOINT_SCHEMA_VERSION,
    DEFAULT_PARTITION_ROWS,
    SCHEMA_VERSION,
    ExternalSortCheckpointError,
    ExternalSortConfig,
    ExternalSortError,
    ExternalSorter,
    MemoryBudget,
    MemoryBudgetError,
    SortStatus,
    document_sort_key,
    external_sort,
    external_sort_to_file,
    iter_jsonl,
    merge_sorted_runs,
    normalize_sort_family,
    posting_sort_key,
    sort_key_for_family,
    spill_sorted_run,
    stream_bounded_partitions,
    stream_sorted_partitions,
    term_sort_key,
    vector_sort_key,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    MAX_ROWS_PER_PHYSICAL_SHARD,
    PhysicalBoundError,
)


def _docs(*indexes: int) -> list[dict[str, object]]:
    return [
        {"document_index": index, "entry_cid": f"{index:064x}", "text": f"row-{index}"}
        for index in indexes
    ]


def test_schema_identity_and_physical_partition_bound() -> None:
    assert SCHEMA_VERSION == "hf-graphrag-external-sort/v1"
    assert CHECKPOINT_SCHEMA_VERSION.startswith("hf-graphrag-external-sort")
    assert DEFAULT_PARTITION_ROWS == 4096
    assert DEFAULT_PARTITION_ROWS == MAX_ROWS_PER_PHYSICAL_SHARD


def test_family_sort_keys_match_layout_contract() -> None:
    document = {"document_index": 7, "entry_cid": "abc"}
    posting = {"term": "habeas", "entry_cid": "abc"}
    term = {"term": "habeas"}
    vector = {"cosine_to_centroid": 0.25, "entry_cid": "abc"}
    assert document_sort_key(document) == (7, "abc")
    assert posting_sort_key(posting) == ("habeas", "abc")
    assert term_sort_key(term) == ("habeas",)
    assert vector_sort_key(vector) == (-0.25, "abc")
    assert sort_key_for_family("bm25_documents") is document_sort_key
    assert sort_key_for_family("bm25_postings") is posting_sort_key
    assert sort_key_for_family("embeddings") is vector_sort_key
    assert normalize_sort_family("locator_index") == "locators"
    with pytest.raises(ExternalSortError, match="must be one of"):
        normalize_sort_family("ontology")


def test_vector_sort_key_rejects_non_finite_cosine() -> None:
    with pytest.raises(ExternalSortError, match="finite"):
        vector_sort_key({"cosine_to_centroid": float("nan"), "entry_cid": "x"})
    with pytest.raises(ExternalSortError, match="finite"):
        vector_sort_key({"cosine_to_centroid": "nope", "entry_cid": "x"})
    assert vector_sort_key({"entry_cid": "only"}) == ("only",)


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
    assert first.schema_version == SCHEMA_VERSION
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
    assert receipt.status == SortStatus.COMPLETE.value
    assert list(iter_jsonl(receipt.output_path)) == []


def test_external_sort_iterator_rejects_interrupted_state(tmp_path: Path) -> None:
    records = _docs(*range(20))
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
    assert receipt.output_digest == ""
    assert receipt.run_count == 1


def test_external_sort_resume_after_run_spill(tmp_path: Path) -> None:
    records = _docs(*range(25))
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


def test_completed_checkpoint_is_reused(tmp_path: Path) -> None:
    records = _docs(3, 1, 2)
    work = tmp_path / "reuse"
    first = external_sort_to_file(
        records,
        tmp_path / "out.jsonl",
        work_dir=work,
        family="documents",
        max_records_in_memory=2,
        resume=True,
    )
    second = external_sort_to_file(
        _docs(9, 8, 7),
        tmp_path / "out.jsonl",
        work_dir=work,
        family="documents",
        max_records_in_memory=2,
        resume=True,
    )
    assert second.output_digest == first.output_digest
    assert second.row_count == 3


def test_checkpoint_config_mismatch_fails_closed(tmp_path: Path) -> None:
    records = _docs(*range(12))
    work = tmp_path / "mismatch"
    interrupted = external_sort_to_file(
        records,
        tmp_path / "out.jsonl",
        work_dir=work,
        family="documents",
        max_records_in_memory=3,
        interrupt_after_runs=1,
    )
    assert interrupted.interrupted is True
    with pytest.raises(ExternalSortCheckpointError, match="config_digest"):
        external_sort_to_file(
            records,
            tmp_path / "out.jsonl",
            work_dir=work,
            family="documents",
            max_records_in_memory=4,
            resume=True,
        )


def test_spill_and_merge_helpers(tmp_path: Path) -> None:
    left = spill_sorted_run(
        _docs(5, 1),
        tmp_path / "run-0.jsonl",
        key_fn=document_sort_key,
    )
    right = spill_sorted_run(
        _docs(4, 2),
        tmp_path / "run-1.jsonl",
        key_fn=document_sort_key,
    )
    merged = merge_sorted_runs(
        [left.path, right.path],
        tmp_path / "merged.jsonl",
        key_fn=document_sort_key,
    )
    assert merged.row_count == 4
    assert [row["document_index"] for row in iter_jsonl(merged.path)] == [1, 2, 4, 5]


def test_stream_bounded_partitions_never_exceeds_physical_bound() -> None:
    records = _docs(*range(10))
    partitions = list(stream_bounded_partitions(records, max_rows=3))
    assert [len(part) for part in partitions] == [3, 3, 3, 1]
    assert all(len(part) <= 3 for part in partitions)
    with pytest.raises(PhysicalBoundError, match="exceeds physical bound"):
        list(stream_bounded_partitions(records, max_rows=4097))


def test_stream_sorted_partitions_combines_sort_and_bound(tmp_path: Path) -> None:
    records = [
        {"term": "zeta", "entry_cid": "c"},
        {"term": "alpha", "entry_cid": "a"},
        {"term": "mu", "entry_cid": "b"},
        {"term": "alpha", "entry_cid": "d"},
    ]
    partitions = list(
        stream_sorted_partitions(
            records,
            work_dir=tmp_path / "parts",
            family="postings",
            max_records_in_memory=2,
            max_rows=2,
        )
    )
    assert len(partitions) == 2
    flattened = [row for part in partitions for row in part]
    assert [posting_sort_key(row) for row in flattened] == sorted(
        posting_sort_key(row) for row in records
    )
    assert all(len(part) <= 2 for part in partitions)


def test_memory_budget_rejects_unbounded_materialization() -> None:
    budget = MemoryBudget(max_resident_records=8)
    budget.check_materialize(8)
    with pytest.raises(MemoryBudgetError, match="refusing to materialize"):
        budget.check_materialize(9)
    budget.acquire(8)
    with pytest.raises(MemoryBudgetError, match="resident records"):
        budget.acquire(1)


def test_sorter_class_uses_family_key_when_omitted(tmp_path: Path) -> None:
    sorter = ExternalSorter(
        tmp_path / "cls",
        config=ExternalSortConfig(family="terms", max_records_in_memory=2, resume=False),
    )
    receipt = sorter.sort_to_file(
        [{"term": "b"}, {"term": "a"}, {"term": "c"}],
        tmp_path / "terms.jsonl",
    )
    assert [row["term"] for row in iter_jsonl(receipt.output_path)] == ["a", "b", "c"]


def test_config_digest_is_stable() -> None:
    first = ExternalSortConfig(family="documents", max_records_in_memory=16)
    second = ExternalSortConfig(family="documents", max_records_in_memory=16)
    assert first.digest == second.digest
    assert len(first.digest) == 64
    third = ExternalSortConfig(family="postings", max_records_in_memory=16)
    assert third.digest != first.digest
