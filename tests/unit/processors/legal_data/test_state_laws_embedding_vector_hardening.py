"""Streaming and fail-closed evidence tests for state-law embeddings/vectors."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    PINNED_MODEL_REVISION,
    default_embedding_config,
    deterministic_project,
    production_inference_evidence_reasons,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embedding_store import (
    LEGACY_MATERIALIZED_EMBEDDING_PATH_PRODUCTION_READY,
    STREAMING_EMBEDDING_STORE_PRODUCTION_READY,
    StateLawsEmbeddingOutputDriftError,
    StateLawsEmbeddingStoreError,
    build_state_laws_embedding_store,
)
from ipfs_datasets_py.processors.legal_data.state_laws_vector_physical import (
    LEGACY_VECTOR_WRITER_PRODUCTION_READY,
    STREAMING_VECTOR_PHYSICAL_PRODUCTION_READY,
    ProjectionEmbeddingRejectedError,
    StateLawsVectorInputDriftError,
    StateLawsVectorOutputDriftError,
    StateLawsVectorPhysicalError,
    write_state_laws_vector_physical_layout,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    atomic_write_canonical_json,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    canonical_json_dumps,
    content_sha256,
)


class _OneShot:
    def __init__(self, values: list[Any]) -> None:
        self.values = values
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        if self.iterations != 1:
            raise AssertionError("source iterable was consumed more than once")
        yield from self.values


def _cid(character: str) -> str:
    return f"sha256:{hashlib.sha256(character.encode('utf-8')).hexdigest()}"


def _rows(jurisdiction: str, count: int, *, first: str = "a") -> list[dict[str, Any]]:
    start = ord(first)
    return [
        {
            "chunk_cid": _cid(chr(start + index)),
            "chunk_id": f"{jurisdiction.lower()}:1:{index}#chunk=0000",
            "disposition": "admitted",
            "legal_id": f"sl:{jurisdiction.lower()}:1:{index}",
            "parent_entry_cid": _cid(chr(ord("m") + index)),
            "text": f"{jurisdiction} official statute body {index}.",
        }
        for index in range(count)
    ]


def _real_evidence() -> dict[str, Any]:
    return {
        "device": {
            "fallback_applied": False,
            "requested": "cpu",
            "runtime": {
                "sentence_transformers_available": True,
                "sentence_transformers_version": "fixture-contract",
                "torch_version": "fixture-contract",
            },
            "selected": "cpu",
        },
        "embedder_kind": "sentence_transformers",
        "model_file_evidence": {
            "file_count": 1,
            "files": [{"path": "model.safetensors", "sha256": "e" * 64}],
            "revision": PINNED_MODEL_REVISION,
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


def _promote_checkpoint_for_consumer_fixture(checkpoint_path: Path) -> None:
    """Attach structurally complete evidence to deterministic test vectors."""

    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    evidence = _real_evidence()
    inference_digest = content_sha256(canonical_json_dumps(evidence))
    payload["inference"] = evidence
    payload["production_ready"] = True
    for part in payload["parts"]:
        part["inference_digest"] = inference_digest
    atomic_write_canonical_json(checkpoint_path, payload)


def _embedding_source(
    root: Path,
    jurisdiction: str,
    rows: list[dict[str, Any]],
    *,
    rows_per_part: int = 2,
) -> tuple[Path, ...]:
    result = build_state_laws_embedding_store(
        rows,
        root,
        jurisdiction_code=jurisdiction,
        config=default_embedding_config(),
        embedder=deterministic_project,
        max_sort_records_in_memory=2,
        rows_per_part=rows_per_part,
    )
    checkpoint = Path(result.checkpoint_path)
    _promote_checkpoint_for_consumer_fixture(checkpoint)
    return tuple(
        root
        / "embeddings"
        / f"jurisdiction={jurisdiction}"
        / f"part-{index:06d}.parquet"
        for index in range(result.part_count)
    )


def _write_vectors(parts: Any, root: Path):
    return write_state_laws_vector_physical_layout(
        parts,
        root,
        kmeans_iterations=2,
        locator_page_size=2,
        max_centroids=8,
        max_rows_per_centroid=1,
        max_rows_per_shard=1,
        max_shards_per_centroid=1,
        max_sort_records_in_memory=2,
        max_training_rows=4,
        target_rows_per_centroid=1,
    )


def test_embedding_consumes_once_spills_within_bound_and_fences_legacy(
    tmp_path: Path,
) -> None:
    source = _OneShot(list(reversed(_rows("OR", 7))))
    result = build_state_laws_embedding_store(
        source,
        tmp_path,
        jurisdiction_code="OR",
        config=default_embedding_config(),
        embedder=deterministic_project,
        max_sort_records_in_memory=2,
        rows_per_part=2,
    )

    assert source.iterations == 1
    assert result.row_count == 7
    assert result.part_count == 4
    assert result.sort_receipt["records_consumed"] == 7
    assert result.sort_receipt["peak_resident_records"] <= 2
    assert result.production_ready is False
    assert LEGACY_MATERIALIZED_EMBEDDING_PATH_PRODUCTION_READY is False
    assert STREAMING_EMBEDDING_STORE_PRODUCTION_READY is True


def test_embedding_rejects_cross_partition_duplicates_and_output_drift(
    tmp_path: Path,
) -> None:
    duplicate = _rows("OR", 3)
    duplicate.append(dict(duplicate[0]))
    with pytest.raises(StateLawsEmbeddingStoreError, match="duplicate"):
        build_state_laws_embedding_store(
            duplicate,
            tmp_path / "duplicate",
            jurisdiction_code="OR",
            config=default_embedding_config(),
            embedder=deterministic_project,
            max_sort_records_in_memory=2,
            rows_per_part=1,
        )

    result = build_state_laws_embedding_store(
        _rows("OR", 3),
        tmp_path / "drift",
        jurisdiction_code="OR",
        config=default_embedding_config(),
        embedder=deterministic_project,
        max_sort_records_in_memory=2,
        rows_per_part=2,
    )
    path = Path(result.output_root) / str(result.descriptors[0]["relative_path"])
    table = pq.read_table(path)
    rows = table.to_pylist()
    rows[0]["input_hash"] = "f" * 64
    pq.write_table(type(table).from_pylist(rows), path, compression="zstd")
    with pytest.raises(StateLawsEmbeddingOutputDriftError):
        build_state_laws_embedding_store(
            _rows("OR", 3),
            tmp_path / "drift",
            jurisdiction_code="OR",
            config=default_embedding_config(),
            embedder=deterministic_project,
            max_sort_records_in_memory=2,
            rows_per_part=2,
        )


def test_forged_boolean_inference_evidence_fails_closed_on_embedding_resume(
    tmp_path: Path,
) -> None:
    result = build_state_laws_embedding_store(
        _rows("OR", 2),
        tmp_path,
        jurisdiction_code="OR",
        config=default_embedding_config(),
        embedder=deterministic_project,
        max_sort_records_in_memory=2,
        rows_per_part=2,
    )
    checkpoint = Path(result.checkpoint_path)
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    forged = {
        "embedder_kind": "sentence_transformers",
        "real_inference": True,
        "truncation_satisfies_contract": True,
    }
    assert "model_file_evidence_missing" in production_inference_evidence_reasons(
        forged
    )
    payload["inference"] = forged
    payload["production_ready"] = True
    digest = content_sha256(canonical_json_dumps(forged))
    for part in payload["parts"]:
        part["inference_digest"] = digest
    atomic_write_canonical_json(checkpoint, payload)

    resumed = build_state_laws_embedding_store(
        _rows("OR", 2),
        tmp_path,
        jurisdiction_code="OR",
        config=default_embedding_config(),
        embedder=lambda _texts: (_ for _ in ()).throw(
            AssertionError("verified parts must resume")
        ),
        max_sort_records_in_memory=2,
        rows_per_part=2,
    )
    assert resumed.resumed_part_count == 1
    assert resumed.executed_part_count == 0
    assert resumed.production_ready is False


def test_vector_consumes_parts_once_and_replays_exact_disk_backed_chunk_keys(
    tmp_path: Path,
) -> None:
    rows = _rows("CA", 4)
    parts = _embedding_source(tmp_path / "source", "CA", rows)
    source = _OneShot(list(reversed(parts)))
    result = _write_vectors(source, tmp_path / "release")

    assert source.iterations == 1
    assert tuple(result.iter_chunk_cids()) == tuple(
        sorted(str(row["chunk_cid"]) for row in rows)
    )
    assert result.sort_receipt["peak_resident_records"] <= 2
    assert LEGACY_VECTOR_WRITER_PRODUCTION_READY is False
    assert STREAMING_VECTOR_PHYSICAL_PRODUCTION_READY is True


def test_vector_rejects_unproved_evidence_and_incomplete_source_checkpoint(
    tmp_path: Path,
) -> None:
    raw = build_state_laws_embedding_store(
        _rows("CA", 3),
        tmp_path / "unproved",
        jurisdiction_code="CA",
        config=default_embedding_config(),
        embedder=deterministic_project,
        max_sort_records_in_memory=2,
        rows_per_part=2,
    )
    checkpoint = Path(raw.checkpoint_path)
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    payload["production_ready"] = True
    atomic_write_canonical_json(checkpoint, payload)
    first = Path(raw.output_root) / str(raw.descriptors[0]["relative_path"])
    with pytest.raises(ProjectionEmbeddingRejectedError):
        _write_vectors((first,), tmp_path / "reject-unproved")

    parts = _embedding_source(tmp_path / "complete", "CA", _rows("CA", 3))
    with pytest.raises(StateLawsVectorInputDriftError, match="full CA"):
        _write_vectors((parts[0],), tmp_path / "reject-incomplete")


def test_vector_rejects_duplicate_chunk_ids_across_jurisdictions(
    tmp_path: Path,
) -> None:
    ca_rows = _rows("CA", 1)
    tx_rows = _rows("TX", 1)
    tx_rows[0]["chunk_cid"] = ca_rows[0]["chunk_cid"]
    parts = (
        *_embedding_source(tmp_path / "ca", "CA", ca_rows),
        *_embedding_source(tmp_path / "tx", "TX", tx_rows),
    )
    with pytest.raises(StateLawsVectorPhysicalError, match="duplicated"):
        _write_vectors(parts, tmp_path / "release")


@pytest.mark.parametrize(
    "mutation",
    ("centroid", "locator_page", "locator_meta", "sort_receipt"),
)
def test_vector_resume_rejects_centroid_locator_meta_and_sort_parity_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    parts = _embedding_source(tmp_path / "source", "CA", _rows("CA", 3))
    result = _write_vectors(parts, tmp_path / "release")
    checkpoint = Path(result.checkpoint_path)
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    mutated = copy.deepcopy(payload)
    if mutation == "centroid":
        mutated["final"]["centroid_descriptor"]["row_count"] += 1
    elif mutation == "locator_page":
        mutated["final"]["locator_page_descriptors"][0]["first_key"] = "drift"
    elif mutation == "locator_meta":
        mutated["final"]["locator_index_descriptor"]["row_count"] += 1
    else:
        mutated["final"]["sort_receipt"]["output_digest"] = "f" * 64
    atomic_write_canonical_json(checkpoint, mutated)

    with pytest.raises(StateLawsVectorOutputDriftError):
        _write_vectors(parts, tmp_path / "release")
