"""Focused contracts for the complete CVEfixes release builder."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.security_ir.cvefixes.retrieval import (
    RetrievalEntry,
    RetrievalValidationError,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import (
    EvaluationRecord,
    canonical_config_cid,
)
from scripts.ops.security_ir import build_cvefixes_security_ir_release as builder
from scripts.ops.security_ir.build_cvefixes_security_ir_release import (
    CUDA_IMAGE,
    CUDA_IMAGE_DIGEST,
    MODEL_DIMENSION,
    MODEL_ID,
    MODEL_REVISION,
    RELEASE_METADATA_FILENAME,
    RETRIEVAL_CONFIG,
    SENTENCE_TRANSFORMERS_VERSION,
    VIEWER_CONFIG_PATHS,
    CompleteReleaseBuildError,
    _cuda_image_binding,
    _dataset_card,
    _install_original_data,
    _record_entry,
    _release_metadata,
    _validate_cuda_embedding_artifacts,
    _write_original_row_index,
)


def _cid(label: str) -> str:
    return canonical_identity(
        {"label": label},
        domain="test",
        schema_version="test/v1",
    ).cid


def test_aggregate_evaluation_entry_uses_graph_root_provenance() -> None:
    graph_root = _cid("graph-root")
    evaluation = EvaluationRecord(
        source_cids=tuple(_cid(f"source-{index}") for index in range(129)),
        parent_cids=(graph_root,),
        config_cid=canonical_config_cid({"builder": "test"}),
        subject_cids=(graph_root,),
        metrics={"source_coverage": 1.0},
        payload={"grants_execution_authority": False},
    )

    entry = _record_entry(
        evaluation,
        kind="security_ir_evaluation",
        text="aggregate evaluation",
        source_cids=evaluation.parent_cids,
        policies=(
            "aggregate_provenance_in_evaluation_report",
            "release_evaluation",
        ),
    )

    assert len(evaluation.source_cids) == 129
    assert evaluation.subject_cids == (graph_root,)
    assert EvaluationRecord.from_dict(evaluation.to_dict()) == evaluation
    assert entry.node_cid == evaluation.cid
    assert entry.source_cids == (graph_root,)
    assert entry.shard_key.count(":") == 1
    assert entry.shard_key.startswith("train:")
    assert entry.grants_execution_authority is False
    assert "aggregate_provenance_in_evaluation_report" in entry.policies
    assert RetrievalEntry.from_dict(entry.to_dict()) == entry

    with pytest.raises(
        RetrievalValidationError,
        match="source_cids exceeds 128 items",
    ):
        _record_entry(
            evaluation,
            kind="security_ir_evaluation",
            text="unbounded aggregate evaluation",
        )

    assert RETRIEVAL_CONFIG.max_shards == 8
    assert RETRIEVAL_CONFIG.max_nodes == 250_000


def test_cuda_image_binding_uses_reviewed_manifest_digest() -> None:
    reviewed = f"nvcr.io/nvidia/pytorch@{CUDA_IMAGE_DIGEST}"
    runtime, identity = _cuda_image_binding(
        CUDA_IMAGE,
        {
            "Id": f"sha256:{'e' * 64}",
            "RepoDigests": [reviewed],
        },
    )

    assert runtime == reviewed
    assert identity == reviewed

    with pytest.raises(
        CompleteReleaseBuildError,
        match="manifest digest differs",
    ):
        _cuda_image_binding(
            CUDA_IMAGE,
            {
                "Id": f"sha256:{'e' * 64}",
                "RepoDigests": [
                    f"nvcr.io/nvidia/pytorch@sha256:{'f' * 64}"
                ],
            },
        )


def test_reused_cuda_artifacts_require_exact_receipt_hashes(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.jsonl"
    output_path = tmp_path / "embeddings.npy"
    receipt_path = tmp_path / "receipt.json"
    input_path.write_bytes(b'{"position":0}\n')
    output_path.write_bytes(b"deterministic-npy-fixture")
    receipt = {
        "cuda_required": True,
        "embedding_dimension": MODEL_DIMENSION,
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "output_size_bytes": output_path.stat().st_size,
        "record_count": 1,
        "sentence_transformers_version": SENTENCE_TRANSFORMERS_VERSION,
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    validated = _validate_cuda_embedding_artifacts(
        input_jsonl=input_path,
        output_npy=output_path,
        receipt_json=receipt_path,
        container_identity="reviewed-image",
    )

    assert validated["container_image"] == "reviewed-image"
    output_path.write_bytes(b"tampered")
    with pytest.raises(
        CompleteReleaseBuildError,
        match="artifacts differ",
    ):
        _validate_cuda_embedding_artifacts(
            input_jsonl=input_path,
            output_npy=output_path,
            receipt_json=receipt_path,
            container_identity="reviewed-image",
        )


def test_release_metadata_is_non_reserved_and_config_driven(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        VIEWER_CONFIG_PATHS,
        "original_data",
        "data/original_data/*.parquet",
    )
    parquet_path = tmp_path / "fixture.parquet"
    pq.write_table(pa.table({"field": ["value"]}), parquet_path)
    descriptors = [
        {
            "byte_length": parquet_path.stat().st_size,
            "config_name": config_name,
            "path": parquet_path.name,
            "row_count": 1,
        }
        for config_name in VIEWER_CONFIG_PATHS
    ]
    derived_dataset_root = _cid("derived-dataset")

    metadata = _release_metadata(
        tmp_path,
        descriptors,
        derived_dataset_root=derived_dataset_root,
    )
    card = _dataset_card(
        counts={},
        derived_dataset_root=derived_dataset_root,
        graph_root=_cid("graph"),
        retrieval_root=_cid("retrieval"),
        cuda_receipt={
            "cuda_version": "12.9",
            "embedding_dimension": MODEL_DIMENSION,
            "gpu_name": "fixture GPU",
        },
    ).decode()

    assert RELEASE_METADATA_FILENAME == "release-metadata.json"
    assert RELEASE_METADATA_FILENAME != "dataset_infos.json"
    assert set(metadata["configs"]) == set(VIEWER_CONFIG_PATHS)
    assert metadata["derived_dataset_root"] == derived_dataset_root
    assert f"Derived Security IR root: `{derived_dataset_root}`" in card
    assert "- config_name: original_data" in card
    assert "path: data/original_data/*.parquet" in card


def test_original_data_is_byte_exact_and_row_cids_resolve_to_offsets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    release_root = tmp_path / "release"
    source_path = source_root / "data" / "train.parquet"
    source_path.parent.mkdir(parents=True)
    release_root.mkdir()
    pq.write_table(
        pa.table({"cve_id": ["CVE-1", "CVE-2"], "body": ["a", "b"]}),
        source_path,
        compression="snappy",
    )
    source_content = source_path.read_bytes()
    source_sha256 = hashlib.sha256(source_content).hexdigest()
    fake_shard = SimpleNamespace(
        path="data/train.parquet",
        row_count=2,
        sha256=source_sha256,
        size_bytes=len(source_content),
    )
    monkeypatch.setattr(
        builder,
        "PINNED_CVEFIXES_SOURCE",
        SimpleNamespace(shards=(fake_shard,)),
    )
    monkeypatch.setattr(builder, "CVEFIXES_ROW_COUNT", 2)
    monkeypatch.setattr(builder, "CVEFIXES_DATASET_ID", "source/fixture")
    monkeypatch.setattr(builder, "CVEFIXES_REVISION", "a" * 40)
    materialization = SimpleNamespace(
        source_row_cids=(_cid("source-row-0"), _cid("source-row-1")),
        source_row_statuses=("admitted", "publication_rejected"),
    )

    installed = _install_original_data(source_root, release_root)
    copied_path = release_root / installed[0]["release_path"]
    assert copied_path.read_bytes() == source_content
    assert installed[0]["sha256"] == source_sha256
    assert installed[0]["row_count"] == 2

    index_path = _write_original_row_index(
        materialization,
        release_root,
        installed,
    )
    rows = {
        row["source_row_index"]: row
        for row in pq.read_table(index_path).to_pylist()
    }
    assert set(rows) == {0, 1}
    assert rows[0]["security_ir_source_cid"] == _cid("source-row-0")
    assert rows[0]["source_status"] == "admitted"
    assert rows[0]["source_identity_domain"] == (
        "cvefixes-security-ir/pinned-source-row"
    )
    assert rows[0]["source_identity_schema_version"] == (
        "cvefixes-pinned-source-row/v1"
    )
    assert rows[1]["security_ir_source_cid"] == _cid("source-row-1")
    assert rows[1]["source_status"] == "publication_rejected"
    assert rows[1]["source_identity_domain"] == (
        "cvefixes-security-ir/rejected-source-row"
    )
    assert rows[1]["source_identity_schema_version"] == (
        "cvefixes-rejected-source-row/v1"
    )
    assert [rows[index]["source_shard_row_index"] for index in (0, 1)] == [
        0,
        1,
    ]
    assert {row["relative_path"] for row in rows.values()} == {
        installed[0]["release_path"]
    }
    assert index_path.stat().st_size < 128 * 1024 * 1024
