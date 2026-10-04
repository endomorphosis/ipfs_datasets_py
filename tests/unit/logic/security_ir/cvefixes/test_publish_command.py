"""Tests for the fail-closed CVEfixes Security IR publication command."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_release import (
    build_huggingface_release,
    stage_huggingface_release,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.release_policy import (
    LicenseProvenance,
    LicenseReviewStatus,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import (
    DerivedDataset,
    EvaluationRecord,
    SourceRecord,
)


SCRIPT = (
    Path(__file__).resolve().parents[5]
    / "scripts"
    / "ops"
    / "security_ir"
    / "publish_cvefixes_security_ir.py"
)
SPEC = importlib.util.spec_from_file_location("publish_cvefixes_security_ir", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
publisher: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = publisher
SPEC.loader.exec_module(publisher)


TARGET = "Publicus/cvefixes-security-ir-graphrag"
SOURCE = "hitoshura25/cvefixes"
SOURCE_REVISION = "d4f5c4ea65329d9ccbb8a3b3149e5d06eda5edb2"
RELEASE_ROOT = "b" + ("a" * 58)
INITIAL_COMMIT = "1" * 40
PUBLISHED_COMMIT = "2" * 40


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode()


def _cid(label: str) -> str:
    return canonical_identity(
        {"label": label}, domain="publisher-test", schema_version="test/v1"
    ).cid


def _parquet_bytes(config: str) -> bytes:
    record_id = "b" + ("z" * 58)
    record = {
        "record_id": record_id,
        "record_type": config,
    }
    table = pa.Table.from_pydict(
        {
            "record_id": [record_id],
            "record_type": [config],
            "authority": ["candidate"],
            "source_cids": [["b" + ("s" * 58)]],
            "parent_cids": [["b" + ("p" * 58)]],
            "config_cid": ["b" + ("q" * 58)],
            "record_json": [_canonical(record).decode()],
        },
        schema=pa.schema(
            [
                pa.field("record_id", pa.string(), nullable=False),
                pa.field("record_type", pa.string(), nullable=False),
                pa.field("authority", pa.string(), nullable=False),
                pa.field("source_cids", pa.list_(pa.string()), nullable=False),
                pa.field("parent_cids", pa.list_(pa.string()), nullable=False),
                pa.field("config_cid", pa.string(), nullable=False),
                pa.field("record_json", pa.string(), nullable=False),
            ]
        ),
    )
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression="zstd")
    return sink.getvalue().to_pybytes()


def _descriptor(
    path: str,
    content: bytes,
    media_type: str,
    *,
    config: str = "",
    row_count: int = 1,
) -> dict[str, Any]:
    digest = hashlib.sha256(content).digest()
    result = {
        "byte_length": len(content),
        "content_id": "b"
        + base64.b32encode(bytes((1, 0x55, 0x12, 0x20)) + digest)
        .decode()
        .lower()
        .rstrip("="),
        "media_type": media_type,
        "path": path,
        "sha256": digest.hex(),
    }
    if config:
        result["config_name"] = config
        result["row_count"] = row_count
    return result


def _type_for_complete(config: str, name: str) -> pa.DataType:
    kind = publisher._field_kind(config, name)
    return {
        "string": pa.string(),
        "large_string": pa.large_string(),
        "int32": pa.int32(),
        "int64": pa.int64(),
        "float32": pa.float32(),
        "float64": pa.float64(),
        "bool": pa.bool_(),
        "list_string": pa.list_(pa.string()),
        "list_int32": pa.list_(pa.int32()),
        "list_float32": pa.list_(pa.float32()),
        "list_float64": pa.list_(pa.float64()),
        "fixed_or_list_float32": pa.list_(pa.float32(), 2),
    }[kind]


def _complete_parquet_rows(
    config: str,
    rows: Sequence[Mapping[str, Any]],
) -> bytes:
    columns = publisher._CONFIG_COLUMNS[config]
    metadata = {
        b"schema_version": str(rows[0]["schema_version"]).encode()
    }
    if config == "original_row_index":
        metadata[b"primary_key"] = b"security_ir_source_cid"
    schema = pa.schema(
        [
            pa.field(name, _type_for_complete(config, name))
            for name in columns
        ],
        metadata=metadata,
    )
    table = pa.Table.from_pylist([dict(row) for row in rows], schema=schema)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression="zstd", compression_level=6)
    return sink.getvalue().to_pybytes()


def _complete_parquet(config: str, row: Mapping[str, Any]) -> bytes:
    return _complete_parquet_rows(config, (row,))


def _original_parquet(row: Mapping[str, Any]) -> bytes:
    schema = pa.schema(
        [
            pa.field(
                name,
                _type_for_complete("original_data", name),
            )
            for name in publisher.ORIGINAL_DATA_COLUMNS
        ]
    )
    table = pa.Table.from_pylist([dict(row)], schema=schema)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression="snappy")
    return sink.getvalue().to_pybytes()


def _complete_data_rows() -> dict[str, dict[str, Any]]:
    entry = _cid("complete-entry")
    node = _cid("complete-node")
    edge = _cid("complete-edge")
    source = _cid("complete-source")
    sha = "0" * 64
    return {
        "corpus": {
            "document_index": 0,
            "entry_cid": entry,
            "node_cid": node,
            "title": "CVE fixture",
            "text": "validate bounds before allocation",
            "partition": "train",
            "shard_key": "CVE-2026-0001",
            "kind": "source",
            "authority": "candidate",
            "source_cids": [source],
            "cwes": ["CWE-20"],
            "languages": ["c"],
            "code_facts": ["bounds_checked"],
            "actions": ["validate"],
            "effects": ["reject_invalid"],
            "policies": ["input_validation"],
            "graph_node": True,
            "grants_execution_authority": False,
            "text_sha256": sha,
            "schema_version": "cvefixes-hf-corpus/v1",
        },
        "bm25_documents": {
            "authority": "candidate",
            "body_length": 1,
            "body_sha256": sha,
            "document_index": 0,
            "document_length": 2,
            "entry_cid": entry,
            "record_type": "source",
            "schema_version": "cvefixes-hf-bm25-document/v1",
            "title": "CVE fixture",
            "title_length": 1,
            "token_input_sha256": sha,
        },
        "bm25_postings": {
            "body_frequencies": [1],
            "corpus_frequency": 2,
            "document_frequency": 1,
            "document_indices": [0],
            "document_lengths": [2],
            "idf": -1.0,
            "posting_chunk_count": 1,
            "posting_chunk_index": 0,
            "schema_version": "cvefixes-hf-bm25-posting/v1",
            "term": "cve",
            "title_frequencies": [1],
        },
        "graph_nodes": {
            "node_cid": node,
            "node_type": "source",
            "entry_cid": entry,
            "label": "CVE-2026-0001",
            "properties_json": "{}",
            "schema_version": "cvefixes-hf-graph-node/v1",
        },
        "graph_edges": {
            "edge_cid": edge,
            "edge_type": "relates_to",
            "source_cid": node,
            "target_cid": node,
            "retrieval_method": "fixture",
            "score": 1.0,
            "query_terms_json": "[]",
            "properties_json": "{}",
            "schema_version": "cvefixes-hf-graph-edge/v1",
        },
        "graph_outgoing_adjacency": {
            "direction": "outgoing",
            "edge_cids": [edge],
            "edge_types": ["relates_to"],
            "neighbor_cids": [node],
            "neighbor_count": 1,
            "neighbor_node_types": ["source"],
            "node_cid": node,
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": ["fixture"],
            "schema_version": "cvefixes-hf-graph-adjacency/v1",
            "scores": [1.0],
            "total_neighbor_count": 1,
        },
        "graph_incoming_adjacency": {
            "direction": "incoming",
            "edge_cids": [edge],
            "edge_types": ["relates_to"],
            "neighbor_cids": [node],
            "neighbor_count": 1,
            "neighbor_node_types": ["source"],
            "node_cid": node,
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": ["fixture"],
            "schema_version": "cvefixes-hf-graph-adjacency/v1",
            "scores": [1.0],
            "total_neighbor_count": 1,
        },
        "vectors": {
            "chunk_id": "vector-000000",
            "cluster_id": 0,
            "entry_cid": entry,
            "faiss_id": 0,
            "document_index": 0,
            "corpus_chunk_id": 0,
            "corpus_row_offset": 0,
            "node_cid": node,
            "retrieval_shard_id": "retrieval-000000",
            "partition": "train",
            "kind": "source",
            "authority": "candidate",
            "source_cids": [source],
            "has_embedding": True,
            "embedding": [1.0, 0.0],
            "model_id": "fixture/model",
            "model_revision": "1" * 40,
            "model_config_cid": _cid("model-config"),
            "retrieval_index_root": _cid("retrieval-root"),
            "schema_version": "cvefixes-hf-vector-chunk/v1",
        },
    }


def _write_complete_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    root = tmp_path / "complete-release"
    root.mkdir()
    data_paths = {
        "corpus": "data/corpus/part-000000.parquet",
        "bm25_documents": "data/bm25/documents/part-000000.parquet",
        "bm25_postings": "data/bm25/postings/part-000000.parquet",
        "graph_nodes": "data/graph/nodes/part-000000.parquet",
        "graph_edges": "data/graph/edges/part-000000.parquet",
        "graph_outgoing_adjacency": (
            "data/graph/adjacency/outgoing/part-000000.parquet"
        ),
        "graph_incoming_adjacency": (
            "data/graph/adjacency/incoming/part-000000.parquet"
        ),
        "vectors": "data/vectors/part-000000.parquet",
    }
    rows = _complete_data_rows()
    contents: dict[str, bytes] = {
        path: _complete_parquet(config, rows[config])
        for config, path in data_paths.items()
    }
    descriptors: dict[str, dict[str, Any]] = {
        path: _descriptor(
            path,
            content,
            "application/vnd.apache.parquet",
            config=config,
        )
        for config, path in data_paths.items()
        for content in (contents[path],)
    }
    source_cids = [_cid(f"original-source-{index}") for index in range(3)]
    source_statuses = (
        "admitted",
        "adaptation_rejected",
        "publication_rejected",
    )
    original_contracts: list[publisher.OriginalShardContract] = []
    for shard_id in range(3):
        original_path = f"data/original/part-{shard_id:06d}.parquet"
        original_row = {
            "cve_id": f"CVE-2026-{shard_id + 1:04d}",
            "hash": f"{shard_id + 1:040x}",
            "repo_url": "https://example.invalid/repository",
            "cve_description": "fixture",
            "cvss2_base_score": 1.0,
            "cvss3_base_score": 2.0,
            "published_date": "2026-07-29",
            "severity": "LOW",
            "cwe_id": "CWE-20",
            "cwe_name": "Improper Input Validation",
            "cwe_description": "fixture",
            "commit_message": "fixture",
            "commit_date": "2026-07-29",
            "version_tag": "v1",
            "repo_total_files": 1,
            "repo_total_commits": 1,
            "file_paths": ["fixture.c"],
            "language": "C",
            "diff_stats": "{}",
            "diff_with_context": "fixture",
            "vulnerable_code": "fixture",
            "fixed_code": "fixture",
            "security_keywords": ["bounds"],
        }
        contents[original_path] = _original_parquet(original_row)
        descriptors[original_path] = _descriptor(
            original_path,
            contents[original_path],
            "application/vnd.apache.parquet",
            config="original_data",
        )
        original_contracts.append(
            publisher.OriginalShardContract(
                release_path=original_path,
                source_path=f"data/train-{shard_id:05d}-of-00003.parquet",
                sha256=descriptors[original_path]["sha256"],
                size_bytes=descriptors[original_path]["byte_length"],
                row_count=1,
            )
        )
    monkeypatch.setattr(
        publisher,
        "PINNED_ORIGINAL_SHARDS",
        tuple(original_contracts),
    )

    for index_path, family in publisher._COMPLETE_INDEX_FAMILY.items():
        if family == "original_data":
            continue
        target_path = data_paths[family]
        target = descriptors[target_path]
        key_column = publisher._DATA_KEY_COLUMNS[family]
        key = str(rows[family][key_column])
        document_range = (
            (0, 0)
            if family in {"corpus", "bm25_documents", "vectors"}
            else (-1, -1)
        )
        meta: dict[str, Any] = {
            "cid": target["content_id"],
            "end_document_index": document_range[1],
            "first_key": key,
            "kind": family,
            "last_key": key,
            "relative_path": target_path,
            "row_count": 1,
            "schema_version": "cvefixes-hf-shard-meta/v1",
            "sha256": target["sha256"],
            "shard_id": 0,
            "size_bytes": target["byte_length"],
            "start_document_index": document_range[0],
        }
        if family == "bm25_postings":
            meta.update(
                posting_count=1,
                term_count=1,
                token_instance_count=2,
            )
        elif family in {
            "graph_outgoing_adjacency",
            "graph_incoming_adjacency",
        }:
            meta.update(
                adjacency_count=1,
                direction=rows[family]["direction"],
                first_page_index=0,
                last_page_index=0,
                node_count=1,
            )
        elif family == "vectors":
            meta.update(
                centroid=[1.0, 0.0],
                centroid_min_score=1.0,
                centroid_shard_count=1,
                chunk_in_cluster=0,
                cluster_id=0,
                dimension=2,
                model_name=f"fixture/model@{'1' * 40}",
                shard_centroid=[1.0, 0.0],
            )
        config = publisher.COMPLETE_INDEX_PATHS[index_path]
        contents[index_path] = _complete_parquet(config, meta)
        descriptors[index_path] = _descriptor(
            index_path,
            contents[index_path],
            "application/vnd.apache.parquet",
            config=config,
        )

    original_index_rows = []
    for source_row_index, (contract, source_cid, source_status) in enumerate(
        zip(
            original_contracts,
            source_cids,
            source_statuses,
            strict=True,
        )
    ):
        original_index_rows.append(
            {
                "security_ir_source_cid": source_cid,
                "source_row_index": source_row_index,
                "source_status": source_status,
                "source_identity_domain": (
                    "cvefixes-security-ir/pinned-source-row"
                    if source_status == "admitted"
                    else "cvefixes-security-ir/rejected-source-row"
                ),
                "source_identity_schema_version": (
                    "cvefixes-pinned-source-row/v1"
                    if source_status == "admitted"
                    else "cvefixes-rejected-source-row/v1"
                ),
                "source_shard_cid": descriptors[contract.release_path][
                    "content_id"
                ],
                "source_shard_path": contract.source_path,
                "source_shard_row_index": 0,
                "relative_path": contract.release_path,
                "source_dataset_id": SOURCE,
                "source_revision": SOURCE_REVISION,
                "schema_version": publisher.ORIGINAL_ROW_INDEX_SCHEMA_VERSION,
            }
        )
    original_index_rows.sort(
        key=lambda item: item["security_ir_source_cid"]
    )
    original_index_path = "indexes/original_rows.parquet"
    contents[original_index_path] = _complete_parquet_rows(
        "original_row_index",
        original_index_rows,
    )
    descriptors[original_index_path] = _descriptor(
        original_index_path,
        contents[original_index_path],
        "application/vnd.apache.parquet",
        config="original_row_index",
        row_count=len(original_index_rows),
    )

    viewer_configs = tuple(sorted(publisher.COMPLETE_VIEWER_CONFIGS))
    card_configs = "\n".join(
        f"- config_name: {config}" for config in viewer_configs
    )
    contents["README.md"] = (
        "---\n"
        "license: apache-2.0\n"
        "configs:\n"
        f"{card_configs}\n"
        "---\n"
        "# Complete CVEfixes fixture\n"
    ).encode()
    features: dict[str, dict[str, dict[str, str]]] = {}
    for config in viewer_configs:
        feature_path = next(
            path
            for path, descriptor in descriptors.items()
            if descriptor.get("config_name") == config
        )
        feature_schema = pq.ParquetFile(
            pa.BufferReader(contents[feature_path])
        ).schema_arrow
        features[config] = {
            field.name: {"dtype": str(field.type)}
            for field in feature_schema
        }
    infos_configs: dict[str, Any] = {}
    for config in viewer_configs:
        matching = [
            value
            for value in descriptors.values()
            if value.get("config_name") == config
        ]
        assert matching
        infos_configs[config] = {
            "features": features[config],
            "splits": {
                "train": {
                    "num_bytes": sum(
                        int(item["byte_length"]) for item in matching
                    ),
                    "num_examples": sum(
                        int(item["row_count"]) for item in matching
                    ),
                }
            },
        }
    contents[publisher.COMPLETE_RELEASE_METADATA_PATH] = _canonical(
        {
            "configs": infos_configs,
            "dataset_id": TARGET,
            "derived_dataset_root": "b" + ("d" * 58),
            "schema_version": publisher.PARQUET_SCHEMA_VERSION,
        }
    )
    contents["evaluation-report.json"] = _canonical(
        {
            "evaluation": {"source_cids": sorted(source_cids)},
            "grants_execution_authority": False,
        }
    )
    media_types = {
        "README.md": "text/markdown; charset=utf-8",
        publisher.COMPLETE_RELEASE_METADATA_PATH: "application/json",
        "evaluation-report.json": "application/json",
    }
    for path in media_types:
        descriptors[path] = _descriptor(
            path, contents[path], media_types[path]
        )
    artifact_values = [
        descriptors[path] for path in sorted(descriptors)
    ]
    index_values = {
        Path(path).stem: {
            "cid": descriptors[path]["content_id"],
            "config_name": descriptors[path]["config_name"],
            "relative_path": path,
            "row_count": descriptors[path]["row_count"],
            "sha256": descriptors[path]["sha256"],
            "size_bytes": descriptors[path]["byte_length"],
        }
        for path in sorted(publisher.COMPLETE_INDEX_PATHS)
    }
    manifest = {
        "artifacts": artifact_values,
        "bm25": {},
        "build_runtime": {
            "accelerator": "cuda",
            "cuda_available": True,
            "original_data": {
                "byte_exact_upstream_copy": True,
                "config_name": "original_data",
                "mirror_profile": publisher.ORIGINAL_MIRROR_PROFILE,
                "operator_acknowledgement_required": True,
                "row_index_config_name": "original_row_index",
                "shards": publisher._expected_original_runtime_shards(),
                "source_dataset_id": SOURCE,
                "source_profile_sha256": (
                    publisher.PINNED_SOURCE_PROFILE_SHA256
                ),
                "source_revision": SOURCE_REVISION,
            },
        },
        "configs": {
            "original_data": "data/original/*.parquet",
            "original_row_index": "indexes/original_rows.parquet",
        },
        "counts": {
            "admitted_rows": 1,
            "original_data_bytes": sum(
                item.size_bytes for item in original_contracts
            ),
            "original_data_rows": len(original_contracts),
            "original_data_shards": len(original_contracts),
            "original_row_index_rows": len(original_index_rows),
            "rejected_rows": 2,
        },
        "dataset_id": TARGET,
        "derived_dataset_root": "b" + ("d" * 58),
        "graph": {},
        "indexes": index_values,
        "parquet": {
            "compression": {
                "derived_and_indexes": "zstd",
                "original_data": "upstream_byte_exact",
            },
            "physical_index_count": len(publisher.COMPLETE_INDEX_PATHS),
        },
        "primary_key": "entry_cid",
        "release_manifest": {
            "dataset_id": TARGET,
            "profile": publisher.ORIGINAL_MIRROR_PROFILE,
            "payload": {
                "derived_security_ir_profile": (
                    "public-metadata-and-body-digests"
                ),
                "release_root": RELEASE_ROOT,
                "release_schema_version": publisher.RELEASE_SCHEMA_VERSION,
            },
            "shard_cids": [
                item["content_id"]
                for item in artifact_values
                if item["path"].startswith("data/")
            ],
        },
        "release_root": RELEASE_ROOT,
        "schema_version": publisher.RELEASE_SCHEMA_VERSION,
        "source": {
            "dataset_id": SOURCE,
            "source_revision": SOURCE_REVISION,
        },
        "vector": {},
    }
    for path, content in contents.items():
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    (root / "manifest.json").write_bytes(_canonical(manifest))
    return root


def _replace_index_artifact(
    root: Path,
    *,
    path: str,
    content: bytes,
    config: str,
    row_count: int,
) -> None:
    (root / path).write_bytes(content)
    descriptor = _descriptor(
        path,
        content,
        "application/vnd.apache.parquet",
        config=config,
        row_count=row_count,
    )
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"] = [
        descriptor if item["path"] == path else item
        for item in manifest["artifacts"]
    ]
    manifest["indexes"][Path(path).stem] = {
        "cid": descriptor["content_id"],
        "config_name": descriptor["config_name"],
        "relative_path": descriptor["path"],
        "row_count": descriptor["row_count"],
        "sha256": descriptor["sha256"],
        "size_bytes": descriptor["byte_length"],
    }
    manifest_path.write_bytes(_canonical(manifest))


@pytest.fixture
def staged_release(tmp_path: Path) -> Path:
    root = tmp_path / "release"
    root.mkdir()
    contents = {
        "README.md": b"---\nlicense: Apache-2.0\n---\n# Test release\n",
        "evaluation-report.json": _canonical(
            {"grants_execution_authority": False}
        ),
        "data/graph_node/train-00000-of-00001.parquet": _parquet_bytes(
            "graph_node"
        ),
        "data/policy_candidate/train-00000-of-00001.parquet": _parquet_bytes(
            "policy_candidate"
        ),
    }
    features = {
        "authority": {"dtype": "string"},
        "config_cid": {"dtype": "string"},
        "parent_cids": {"feature": {"dtype": "string"}},
        "record_id": {"dtype": "string"},
        "record_json": {"dtype": "string"},
        "record_type": {"dtype": "string"},
        "source_cids": {"feature": {"dtype": "string"}},
    }
    contents["dataset_infos.json"] = _canonical(
        {
            "configs": {
                "graph_node": {
                    "features": features,
                    "splits": {
                        "train": {
                            "num_bytes": len(
                                contents[
                                    "data/graph_node/"
                                    "train-00000-of-00001.parquet"
                                ]
                            ),
                            "num_examples": 1,
                        }
                    },
                },
                "policy_candidate": {
                    "features": features,
                    "splits": {
                        "train": {
                            "num_bytes": len(
                                contents[
                                    "data/policy_candidate/"
                                    "train-00000-of-00001.parquet"
                                ]
                            ),
                            "num_examples": 1,
                        }
                    },
                },
            },
            "dataset_id": TARGET,
            "derived_dataset_root": "b" + ("d" * 58),
            "schema_version": publisher.PARQUET_SCHEMA_VERSION,
        }
    )
    descriptors = []
    media_types = {
        "README.md": "text/markdown; charset=utf-8",
        "dataset_infos.json": "application/json",
        "evaluation-report.json": "application/json",
    }
    for path, content in sorted(contents.items()):
        config = Path(path).parts[1] if path.endswith(".parquet") else ""
        descriptors.append(
            _descriptor(
                path,
                content,
                (
                    "application/vnd.apache.parquet"
                    if config
                    else media_types[path]
                ),
                config=config,
            )
        )
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    manifest = {
        "artifacts": descriptors,
        "dataset_id": TARGET,
        "derived_dataset_root": "b" + ("d" * 58),
        "release_manifest": {
            "dataset_id": TARGET,
            "payload": {
                "release_root": RELEASE_ROOT,
                "release_schema_version": publisher.RELEASE_SCHEMA_VERSION,
            },
            "shard_cids": [
                item["content_id"]
                for item in descriptors
                if item["path"].endswith(".parquet")
            ],
        },
        "release_root": RELEASE_ROOT,
        "schema_version": publisher.RELEASE_SCHEMA_VERSION,
        "source": {
            "dataset_id": SOURCE,
            "source_revision": SOURCE_REVISION,
        },
    }
    (root / "manifest.json").write_bytes(_canonical(manifest))
    return root


class FakeHub:
    def __init__(
        self,
        release_dir: Path,
        *,
        viewer_columns: Sequence[str] | None = None,
    ) -> None:
        self.release_dir = release_dir
        self.current_head = INITIAL_COMMIT
        self.history = [INITIAL_COMMIT]
        self.files: dict[tuple[str, str], bytes] = {}
        self.upload_calls = 0
        self.auth_calls = 0
        self.viewer_columns = (
            tuple(viewer_columns) if viewer_columns is not None else None
        )
        self.token_values: list[str] = []

    def authenticate(self, token: str) -> str:
        self.auth_calls += 1
        self.token_values.append(token)
        return "release-operator"

    def head(self, repo_id: str, token: str | None) -> str:
        assert repo_id == TARGET
        if token:
            self.token_values.append(token)
        return self.current_head

    def revisions(
        self, repo_id: str, token: str | None, *, limit: int
    ) -> Sequence[str]:
        assert repo_id == TARGET
        return tuple(self.history[:limit])

    def read_file(
        self, repo_id: str, revision: str, path: str, token: str | None
    ) -> bytes:
        assert repo_id == TARGET
        try:
            return self.files[(revision, path)]
        except KeyError as exc:
            raise publisher.RemoteVerificationError("missing test file") from exc

    def upload(
        self,
        release: Any,
        token: str,
        *,
        parent_commit: str,
        commit_message: str,
        commit_description: str,
    ) -> str:
        assert parent_commit == INITIAL_COMMIT
        assert token not in commit_message
        assert token not in commit_description
        assert release.idempotency_key in commit_description
        self.upload_calls += 1
        self.current_head = PUBLISHED_COMMIT
        self.history.insert(0, PUBLISHED_COMMIT)
        for path in release.directory.rglob("*"):
            if path.is_file():
                self.files[
                    (PUBLISHED_COMMIT, path.relative_to(release.directory).as_posix())
                ] = path.read_bytes()
        return PUBLISHED_COMMIT

    def viewer(
        self,
        endpoint: str,
        params: Mapping[str, str],
        token: str | None,
    ) -> Mapping[str, Any]:
        manifest = json.loads(
            (self.release_dir / "manifest.json").read_text()
        )
        configs = sorted(
            {
                item["config_name"]
                for item in manifest["artifacts"]
                if "config_name" in item
            }
        )
        if any(
            item["path"].startswith("data/corpus/")
            for item in manifest["artifacts"]
        ):
            configs = sorted(publisher.COMPLETE_VIEWER_CONFIGS)
        if endpoint == "is-valid":
            return {"viewer": True}
        if endpoint == "splits":
            return {
                "splits": [
                    {"dataset": TARGET, "config": config, "split": "train"}
                    for config in configs
                ]
            }
        if endpoint == "parquet":
            return {
                "parquet_files": [
                    {
                        "config": item["config_name"],
                        "dataset": TARGET,
                        "filename": Path(item["path"]).name,
                        "size": item["byte_length"],
                        "split": "train",
                    }
                    for item in manifest["artifacts"]
                    if item.get("config_name") in configs
                ]
            }
        if endpoint == "first-rows":
            config = params["config"]
            artifact = next(
                item
                for item in manifest["artifacts"]
                if item.get("config_name") == config
            )
            table = pq.read_table(self.release_dir / artifact["path"])
            values = table.slice(0, 1).to_pylist()[0]
            columns = (
                self.viewer_columns
                if self.viewer_columns is not None
                else tuple(table.column_names)
            )
            return {
                "config": config,
                "dataset": TARGET,
                "features": [
                    {"feature_idx": index, "name": name, "type": {}}
                    for index, name in enumerate(columns)
                ],
                "rows": [
                    {
                        "row": {
                            name: values[name]
                            for name in columns
                            if name in values
                        },
                        "row_idx": 0,
                        "truncated_cells": [],
                    }
                ],
                "split": "train",
            }
        raise AssertionError(endpoint)


def _seed_remote(hub: FakeHub, release_dir: Path, revision: str) -> None:
    for path in release_dir.rglob("*"):
        if path.is_file():
            hub.files[
                (revision, path.relative_to(release_dir).as_posix())
            ] = path.read_bytes()


def test_default_is_credential_free_dry_run(
    staged_release: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "hf_" + ("x" * 30)
    monkeypatch.setenv("HF_TOKEN", secret)
    before = {
        path.relative_to(staged_release).as_posix(): path.read_bytes()
        for path in staged_release.rglob("*")
        if path.is_file()
    }

    result = publisher.publish_release(staged_release)

    assert result["dry_run"] is True
    assert result["status"] == "planned"
    assert result["target_repo"] == TARGET
    assert result["source_revision"] == SOURCE_REVISION
    assert secret not in json.dumps(result)
    assert before == {
        path.relative_to(staged_release).as_posix(): path.read_bytes()
        for path in staged_release.rglob("*")
        if path.is_file()
    }


def test_publisher_accepts_skillcenter_compatible_meta_indexes(
    tmp_path: Path,
) -> None:
    source_cid = _cid("source")
    config_cid = _cid("config")
    source = SourceRecord(
        source_cids=(source_cid,),
        parent_cids=(_cid("source-parent"),),
        config_cid=config_cid,
        source_uri="hf://datasets/hitoshura25/cvefixes",
        source_revision=SOURCE_REVISION,
        row_key="0",
        payload={"cve_id": "CVE-2026-0001"},
    )
    evaluation = EvaluationRecord(
        source_cids=(source_cid,),
        parent_cids=(source.cid,),
        config_cid=config_cid,
        subject_cids=(source.cid,),
        metrics={"status": "fixture"},
        payload={
            "authoritative": False,
            "grants_execution_authority": False,
        },
    )
    release = build_huggingface_release(
        DerivedDataset(records=(source, evaluation)),
        dataset_id=TARGET,
        license_provenance=LicenseProvenance(
            dataset_id=SOURCE,
            source_revision=SOURCE_REVISION,
            license_expression="Apache-2.0",
            evidence_url="https://huggingface.co/datasets/hitoshura25/cvefixes",
            review_status=LicenseReviewStatus.REVIEWED,
            reviewed_by="test-reviewer",
            reviewed_at="2026-07-29T00:00:00Z",
            redistribution_allowed=True,
        ),
    )
    root = tmp_path / "indexed-release"
    stage_huggingface_release(release, root, validate_only=False)

    loaded = publisher.load_local_release(root, expected_target=TARGET)

    assert "corpus_chunk_index" in loaded.config_names
    assert loaded.columns_for_config("corpus_chunk_index") == (
        publisher.META_INDEX_COLUMNS
    )


def test_publisher_accepts_complete_skillcenter_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _write_complete_release(tmp_path, monkeypatch)

    loaded = publisher.load_local_release(root, expected_target=TARGET)

    assert loaded.complete_layout is True
    assert loaded.original_data_acknowledgement_required is True
    assert set(loaded.config_names) == publisher.COMPLETE_VIEWER_CONFIGS
    assert not publisher._HIDDEN_INDEX_CONFIGS & set(loaded.config_names)
    assert (root / publisher.COMPLETE_RELEASE_METADATA_PATH).is_file()
    assert not (root / publisher.LEGACY_RELEASE_METADATA_PATH).exists()
    assert {
        item.path
        for item in loaded.artifacts
        if item.path.startswith("indexes/")
    } == set(publisher.COMPLETE_INDEX_PATHS)
    assert loaded.columns_for_config("bm25_keyword_index") == (
        publisher.BM25_KEYWORD_META_COLUMNS
    )
    assert loaded.columns_for_config("vector_meta_index") == (
        publisher.VECTOR_META_COLUMNS
    )
    assert loaded.columns_for_config("original_data") == (
        publisher.ORIGINAL_DATA_COLUMNS
    )
    assert loaded.columns_for_config("original_row_index") == (
        publisher.ORIGINAL_ROW_INDEX_COLUMNS
    )
    viewer = publisher.verify_dataset_viewer(
        FakeHub(root), loaded, token=None
    )
    assert set(viewer["configs"]) == publisher.COMPLETE_VIEWER_CONFIGS


def test_pinned_original_shards_have_exact_production_contract() -> None:
    expected = (
        (
            "data/original/part-000000.parquet",
            "data/train-00000-of-00003.parquet",
            211_599_861,
            4_329,
            "2e25e84e85e1560d41acacbfc7eb359349f5417bc9bf31318cdf0c4aafccb7d1",
        ),
        (
            "data/original/part-000001.parquet",
            "data/train-00001-of-00003.parquet",
            428_366_432,
            4_329,
            "3a4251f39955f95c232b4aea98daa59bbe0c7b5e27c9189c1b09f64b960a35d7",
        ),
        (
            "data/original/part-000002.parquet",
            "data/train-00002-of-00003.parquet",
            580_353_186,
            4_329,
            "55488d569ac978ea077be643233355f43458d636d04ad3ae1cb973895b02a3ac",
        ),
    )

    assert tuple(
        (
            item.release_path,
            item.source_path,
            item.size_bytes,
            item.row_count,
            item.sha256,
        )
        for item in publisher.PINNED_ORIGINAL_SHARDS
    ) == expected
    for contract in publisher.PINNED_ORIGINAL_SHARDS:
        publisher.ArtifactDescriptor.from_dict(
            {
                "byte_length": contract.size_bytes,
                "config_name": "original_data",
                "content_id": publisher._raw_sha256_cid(
                    bytes.fromhex(contract.sha256)
                ),
                "media_type": "application/vnd.apache.parquet",
                "path": contract.release_path,
                "row_count": contract.row_count,
                "sha256": contract.sha256,
            }
        )
    first = publisher.PINNED_ORIGINAL_SHARDS[0]
    with pytest.raises(
        publisher.LocalReleaseError,
        match="byte_length",
    ):
        publisher.ArtifactDescriptor.from_dict(
            {
                "byte_length": first.size_bytes,
                "config_name": "original_data",
                "content_id": publisher._raw_sha256_cid(
                    bytes.fromhex(first.sha256)
                ),
                "media_type": "application/vnd.apache.parquet",
                "path": "data/original/part-000003.parquet",
                "row_count": first.row_count,
                "sha256": first.sha256,
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("profile", "wrong-mirror/v1"),
        ("derived_security_ir_profile", "wrong-derived-profile"),
    ),
)
def test_original_mirror_requires_canonical_release_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    root = _write_complete_release(tmp_path, monkeypatch)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if field == "profile":
        manifest["release_manifest"]["profile"] = value
    else:
        manifest["release_manifest"]["payload"][field] = value
    manifest_path.write_bytes(_canonical(manifest))

    with pytest.raises(
        publisher.LocalReleaseError,
        match="original-data release profile",
    ):
        publisher.load_local_release(root, expected_target=TARGET)


def test_complete_release_metadata_binds_exact_arrow_types(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _write_complete_release(tmp_path, monkeypatch)
    relative = publisher.COMPLETE_RELEASE_METADATA_PATH
    metadata_path = root / relative
    metadata = json.loads(metadata_path.read_text())
    metadata["configs"]["original_row_index"]["features"][
        "source_row_index"
    ]["dtype"] = "string"
    content = _canonical(metadata)
    metadata_path.write_bytes(content)
    descriptor = _descriptor(relative, content, "application/json")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"] = [
        descriptor if item["path"] == relative else item
        for item in manifest["artifacts"]
    ]
    manifest_path.write_bytes(_canonical(manifest))

    with pytest.raises(
        publisher.LocalReleaseError,
        match="feature types differ from Parquet",
    ):
        publisher.load_local_release(root, expected_target=TARGET)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("source_row_index", None, "original-row index"),
        ("source_shard_row_index", 99, "shard binding"),
        ("source_shard_cid", _cid("wrong-original-shard"), "shard binding"),
        ("relative_path", "data/original/part-999999.parquet", "shard binding"),
        ("source_status", "unknown", "identity coverage"),
        ("source_identity_domain", "wrong-domain", "shard binding"),
        (
            "source_identity_schema_version",
            "wrong/v1",
            "shard binding",
        ),
    ),
)
def test_original_row_index_fails_closed_on_binding_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
    message: str,
) -> None:
    root = _write_complete_release(tmp_path, monkeypatch)
    index_path = root / "indexes/original_rows.parquet"
    table = pq.read_table(index_path)
    rows = table.to_pylist()
    rows[0][field] = (
        rows[1]["source_row_index"] if value is None else value
    )
    sink = pa.BufferOutputStream()
    pq.write_table(
        pa.Table.from_pylist(rows, schema=table.schema),
        sink,
        compression="zstd",
        compression_level=6,
    )
    content = sink.getvalue().to_pybytes()
    _replace_index_artifact(
        root,
        path="indexes/original_rows.parquet",
        content=content,
        config="original_row_index",
        row_count=len(rows),
    )

    with pytest.raises(publisher.LocalReleaseError, match=message):
        publisher.load_local_release(root, expected_target=TARGET)


def test_original_data_requires_snappy_and_unversioned_schema(
    tmp_path: Path,
) -> None:
    row = {
        name: (
            ["fixture"]
            if publisher._field_kind("original_data", name) == "list_string"
            else 1
            if publisher._field_kind("original_data", name) == "int64"
            else 1.0
            if publisher._field_kind("original_data", name) == "float64"
            else "CVE-2026-0001"
            if name == "cve_id"
            else "1" * 40
            if name == "hash"
            else "fixture"
        )
        for name in publisher.ORIGINAL_DATA_COLUMNS
    }
    schema = pa.schema(
        [
            pa.field(name, _type_for_complete("original_data", name))
            for name in publisher.ORIGINAL_DATA_COLUMNS
        ]
    )
    path = tmp_path / "part.parquet"
    pq.write_table(
        pa.Table.from_pylist([row], schema=schema),
        path,
        compression="zstd",
    )
    content = path.read_bytes()
    descriptor = publisher.ArtifactDescriptor(
        path="data/original/part-000000.parquet",
        media_type="application/vnd.apache.parquet",
        byte_length=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        content_id=publisher._raw_sha256_cid(
            hashlib.sha256(content).digest()
        ),
        config_name="original_data",
        row_count=1,
    )

    with pytest.raises(
        publisher.LocalReleaseError,
        match="compression mismatch",
    ):
        publisher._validate_parquet(
            path,
            descriptor,
            complete_layout=True,
        )

    versioned_path = tmp_path / "versioned.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [row],
            schema=schema.with_metadata({b"schema_version": b"forged/v1"}),
        ),
        versioned_path,
        compression="snappy",
    )
    versioned_content = versioned_path.read_bytes()
    versioned_descriptor = publisher.ArtifactDescriptor(
        path=descriptor.path,
        media_type=descriptor.media_type,
        byte_length=len(versioned_content),
        sha256=hashlib.sha256(versioned_content).hexdigest(),
        content_id=publisher._raw_sha256_cid(
            hashlib.sha256(versioned_content).digest()
        ),
        config_name=descriptor.config_name,
        row_count=descriptor.row_count,
    )
    with pytest.raises(
        publisher.LocalReleaseError,
        match="unversioned schema",
    ):
        publisher._validate_parquet(
            versioned_path,
            versioned_descriptor,
            complete_layout=True,
        )


def test_execute_requires_original_mirror_acknowledgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _write_complete_release(tmp_path, monkeypatch)
    token = "hf_" + ("m" * 30)
    monkeypatch.setenv("HF_TOKEN", token)
    hub = FakeHub(root)

    plan = publisher.publish_release(root)
    assert plan["original_data_mirror_acknowledgement_required"] is True
    with pytest.raises(
        publisher.PublicationError,
        match="--acknowledge-original-data-mirror",
    ):
        publisher.publish_release(root, execute=True, gateway=hub)
    assert hub.auth_calls == 0
    assert hub.upload_calls == 0

    receipt = publisher.publish_release(
        root,
        execute=True,
        acknowledge_original_data_mirror=True,
        gateway=hub,
        now=lambda: "2026-07-29T12:00:00Z",
    )

    assert receipt["operation"] == "uploaded"
    assert hub.auth_calls == 1
    assert hub.upload_calls == 1


def test_complete_layout_rejects_reserved_dataset_infos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _write_complete_release(tmp_path, monkeypatch)
    reserved_path = publisher.LEGACY_RELEASE_METADATA_PATH
    content = (root / publisher.COMPLETE_RELEASE_METADATA_PATH).read_bytes()
    (root / reserved_path).write_bytes(content)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"].append(
        _descriptor(reserved_path, content, "application/json")
    )
    manifest["artifacts"].sort(key=lambda item: item["path"])
    manifest_path.write_bytes(_canonical(manifest))

    with pytest.raises(
        publisher.LocalReleaseError,
        match="cannot contain reserved dataset_infos.json",
    ):
        publisher.load_local_release(root, expected_target=TARGET)


def test_complete_layout_requires_every_physical_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _write_complete_release(tmp_path, monkeypatch)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    missing_path = "indexes/graph_edge_chunks.parquet"
    (root / missing_path).unlink()
    manifest["artifacts"] = [
        item for item in manifest["artifacts"] if item["path"] != missing_path
    ]
    del manifest["indexes"]["graph_edge_chunks"]
    manifest_path.write_bytes(_canonical(manifest))

    with pytest.raises(
        publisher.LocalReleaseError,
        match="physical index inventory is incomplete",
    ):
        publisher.load_local_release(root, expected_target=TARGET)


def test_complete_layout_requires_raw_sha256_cids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _write_complete_release(tmp_path, monkeypatch)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    target_path = "data/corpus/part-000000.parquet"
    forged = _cid("not-the-raw-file-cid")
    old = next(
        item["content_id"]
        for item in manifest["artifacts"]
        if item["path"] == target_path
    )
    for item in manifest["artifacts"]:
        if item["path"] == target_path:
            item["content_id"] = forged
    manifest["release_manifest"]["shard_cids"] = [
        forged if value == old else value
        for value in manifest["release_manifest"]["shard_cids"]
    ]
    manifest_path.write_bytes(_canonical(manifest))

    with pytest.raises(
        publisher.LocalReleaseError, match="raw SHA-256 CID mismatch"
    ):
        publisher.load_local_release(root, expected_target=TARGET)


def test_complete_index_cannot_point_to_another_family(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _write_complete_release(tmp_path, monkeypatch)
    relative = "indexes/bm25_document_chunks.parquet"
    index_path = root / relative
    table = pq.read_table(index_path)
    rows = table.to_pylist()
    rows[0]["relative_path"] = "data/corpus/part-000000.parquet"
    sink = pa.BufferOutputStream()
    pq.write_table(
        pa.Table.from_pylist(rows, schema=table.schema),
        sink,
        compression="zstd",
        compression_level=6,
    )
    content = sink.getvalue().to_pybytes()
    index_path.write_bytes(content)
    descriptor = _descriptor(
        relative,
        content,
        "application/vnd.apache.parquet",
        config="bm25_document_chunk_index",
    )
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"] = [
        descriptor if item["path"] == relative else item
        for item in manifest["artifacts"]
    ]
    manifest["indexes"]["bm25_document_chunks"] = {
        "cid": descriptor["content_id"],
        "config_name": descriptor["config_name"],
        "relative_path": descriptor["path"],
        "row_count": descriptor["row_count"],
        "sha256": descriptor["sha256"],
        "size_bytes": descriptor["byte_length"],
    }
    manifest_path.write_bytes(_canonical(manifest))

    with pytest.raises(
        publisher.LocalReleaseError,
        match="pointers must cover unique data shards",
    ):
        publisher.load_local_release(root, expected_target=TARGET)


def test_hub_upload_deletes_stale_data_and_indexes(
    staged_release: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = publisher.load_local_release(
        staged_release, expected_target=TARGET
    )
    captured: dict[str, Any] = {}

    class Api:
        def upload_folder(self, **kwargs: Any) -> Any:
            captured.update(kwargs)

            class Result:
                oid = PUBLISHED_COMMIT

            return Result()

    monkeypatch.setattr(
        publisher.HuggingFaceHubGateway,
        "_api",
        staticmethod(lambda: Api()),
    )

    revision = publisher.HuggingFaceHubGateway().upload(
        release,
        "hf_" + ("u" * 30),
        parent_commit=INITIAL_COMMIT,
        commit_message="fixture",
        commit_description="fixture",
    )

    assert revision == PUBLISHED_COMMIT
    assert "data/**" in captured["delete_patterns"]
    assert "indexes/**" in captured["delete_patterns"]
    assert (
        publisher.COMPLETE_RELEASE_METADATA_PATH
        in captured["delete_patterns"]
    )
    assert (
        publisher.LEGACY_RELEASE_METADATA_PATH
        in captured["delete_patterns"]
    )


def test_remote_read_limit_is_narrowly_raised_for_pinned_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = publisher.HuggingFaceHubGateway()
    observed: list[int] = []

    def read_url(url: str, token: str | None, *, maximum: int) -> bytes:
        observed.append(maximum)
        return b""

    monkeypatch.setattr(gateway, "_read_url", read_url)
    original = publisher.PINNED_ORIGINAL_SHARDS[2]

    gateway.read_file(
        TARGET,
        INITIAL_COMMIT,
        original.release_path,
        None,
    )
    gateway.read_file(
        TARGET,
        INITIAL_COMMIT,
        "data/corpus/part-000000.parquet",
        None,
    )

    assert observed == [
        original.size_bytes,
        publisher.MAX_ARTIFACT_BYTES,
    ]


def test_execute_authenticates_uploads_verifies_and_proposes_receipt(
    staged_release: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "hf_" + ("t" * 30)
    monkeypatch.setenv("CVEFIXES_TEST_TOKEN", token)
    hub = FakeHub(staged_release)

    receipt = publisher.publish_release(
        staged_release,
        execute=True,
        token_env="CVEFIXES_TEST_TOKEN",
        gateway=hub,
        now=lambda: "2026-07-29T12:00:00Z",
    )

    serialized = json.dumps(receipt)
    assert hub.auth_calls == 1
    assert hub.upload_calls == 1
    assert receipt["status"] == "proposed"
    assert receipt["authoritative"] is False
    assert receipt["grants_completion_authority"] is False
    assert receipt["grants_execution_authority"] is False
    assert receipt["principal"] == "release-operator"
    assert receipt["hub_commit"] == PUBLISHED_COMMIT
    assert receipt["operation"] == "uploaded"
    assert receipt["verification"]["remote_revision_verified"] is True
    assert receipt["verification"]["remote_manifest_verified"] is True
    assert receipt["verification"]["remote_artifacts_verified"] is True
    assert receipt["verification"]["dataset_viewer"]["verified"] is True
    assert token not in serialized
    assert "token" not in serialized.casefold()
    assert all(value == token for value in hub.token_values)


def test_same_target_source_release_tuple_is_verified_without_upload(
    staged_release: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf_" + ("i" * 30))
    hub = FakeHub(staged_release)
    hub.current_head = PUBLISHED_COMMIT
    hub.history = [PUBLISHED_COMMIT, INITIAL_COMMIT]
    _seed_remote(hub, staged_release, PUBLISHED_COMMIT)

    receipt = publisher.publish_release(
        staged_release,
        execute=True,
        gateway=hub,
        now=lambda: "2026-07-29T12:00:00Z",
    )

    assert hub.upload_calls == 0
    assert receipt["operation"] == "verified_existing"
    assert receipt["hub_commit"] == PUBLISHED_COMMIT


def test_missing_environment_token_fails_before_remote_access(
    staged_release: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    hub = FakeHub(staged_release)

    with pytest.raises(publisher.AuthenticationError, match="environment variable"):
        publisher.publish_release(staged_release, execute=True, gateway=hub)

    assert hub.auth_calls == 0
    assert hub.upload_calls == 0


def test_viewer_schema_mismatch_prevents_receipt(
    staged_release: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf_" + ("v" * 30))
    hub = FakeHub(
        staged_release,
        viewer_columns=publisher.EXPECTED_COLUMNS[:-1],
    )

    with pytest.raises(
        publisher.ViewerNotReadyError, match="feature binding mismatch"
    ):
        publisher.publish_release(
            staged_release,
            execute=True,
            gateway=hub,
            viewer_attempts=1,
        )

    assert hub.upload_calls == 1


def test_remote_shard_mismatch_prevents_receipt(
    staged_release: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf_" + ("r" * 30))
    hub = FakeHub(staged_release)
    original_upload = hub.upload

    def corrupting_upload(*args: Any, **kwargs: Any) -> str:
        revision = original_upload(*args, **kwargs)
        shard = next(
            path
            for revision_path, path in hub.files
            if revision_path == revision and path.endswith(".parquet")
        )
        hub.files[(revision, shard)] += b"corrupt"
        return revision

    hub.upload = corrupting_upload

    with pytest.raises(
        publisher.RemoteVerificationError, match="remote artifact verification"
    ):
        publisher.publish_release(staged_release, execute=True, gateway=hub)


def test_local_inventory_hash_schema_and_symlink_fail_closed(
    staged_release: Path, tmp_path: Path
) -> None:
    extra = staged_release / "unexpected.txt"
    extra.write_text("not in manifest")
    with pytest.raises(publisher.LocalReleaseError, match="exactly match"):
        publisher.load_local_release(staged_release)
    extra.unlink()

    shard = next(staged_release.rglob("*.parquet"))
    original = shard.read_bytes()
    shard.write_bytes(original + b"corrupt")
    with pytest.raises(publisher.LocalReleaseError, match="content mismatch"):
        publisher.load_local_release(staged_release)
    shard.write_bytes(original)

    (staged_release / "link").symlink_to(tmp_path)
    with pytest.raises(publisher.LocalReleaseError, match="symlinks"):
        publisher.load_local_release(staged_release)


def test_receipt_is_atomic_secret_free_and_read_only_verifiable(
    staged_release: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "hf_" + ("w" * 30)
    monkeypatch.setenv("HF_TOKEN", token)
    hub = FakeHub(staged_release)
    receipt = publisher.publish_release(
        staged_release,
        execute=True,
        gateway=hub,
        now=lambda: "2026-07-29T12:00:00Z",
    )
    output = tmp_path / "external" / "receipt.json"

    publisher.write_receipt(receipt, output)
    verification = publisher.verify_receipt(output, gateway=hub)

    assert verification["status"] == "verified"
    assert verification["hub_commit"] == PUBLISHED_COMMIT
    assert token not in output.read_text()
    assert not (output.parent / f".{output.name}.tmp").exists()
    with pytest.raises(publisher.PublicationError, match="already exists"):
        publisher.write_receipt(receipt, output)


def test_receipt_verification_rejects_authority_claim(
    staged_release: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf_" + ("a" * 30))
    hub = FakeHub(staged_release)
    receipt = publisher.publish_release(
        staged_release, execute=True, gateway=hub
    )
    receipt["grants_completion_authority"] = True
    path = tmp_path / "forged.json"
    path.write_bytes(_canonical(receipt))

    with pytest.raises(publisher.LocalReleaseError, match="authority"):
        publisher.verify_receipt(path, gateway=hub)
