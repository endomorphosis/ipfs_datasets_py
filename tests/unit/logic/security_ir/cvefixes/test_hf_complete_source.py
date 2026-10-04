"""Contracts for the selective complete-release Hub consumer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.security_ir.cvefixes import hf_complete_source as complete
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_complete_source import (
    HuggingFaceCompleteReleaseCache,
    HuggingFaceHubCompleteReleaseFetcher,
    load_huggingface_complete_release,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_source import (
    HuggingFaceSourceIntegrityError,
    HuggingFaceSourcePin,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import ReleaseManifest


DATASET_ID = "Publicus/cvefixes-security-ir-graphrag"
REVISION = "6" * 40


def _cid(label: str) -> str:
    return canonical_identity(
        {"label": label},
        domain="complete-source-test",
        schema_version="complete-source-test/v1",
    ).cid


def _raw_cid(sha256: str) -> str:
    return complete._raw_sha256_cid(bytes.fromhex(sha256))


def _descriptor(
    path: str,
    *,
    content: bytes | None = None,
    sha256: str | None = None,
    size: int | None = None,
    config_name: str = "",
    row_count: int = 0,
    media_type: str | None = None,
) -> dict[str, object]:
    if content is not None:
        sha256 = hashlib.sha256(content).hexdigest()
        size = len(content)
    assert sha256 is not None and size is not None
    value: dict[str, object] = {
        "byte_length": size,
        "content_id": _raw_cid(sha256),
        "media_type": media_type
        or (
            "application/vnd.apache.parquet"
            if path.endswith(".parquet")
            else "application/octet-stream"
        ),
        "path": path,
        "sha256": sha256,
    }
    if path.endswith(".parquet"):
        value.update(config_name=config_name, row_count=row_count)
    return value


def _compact(value: dict[str, object]) -> dict[str, object]:
    return {
        "cid": value["content_id"],
        "relative_path": value["path"],
        "row_count": value["row_count"],
        "sha256": value["sha256"],
        "size_bytes": value["byte_length"],
    }


def _write_index(
    root: Path,
    name: str,
    rows: list[dict[str, object]],
    *,
    metadata: dict[bytes, bytes],
) -> dict[str, object]:
    path = root / complete._INDEX_PATHS[name]
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = (
        complete._ORIGINAL_ROW_COLUMNS
        if name == "original_rows"
        else complete._INDEX_COLUMNS[name]
    )
    ordered = [{column: row[column] for column in columns} for row in rows]
    table = pa.Table.from_pylist(ordered).replace_schema_metadata(metadata)
    pq.write_table(table, path, compression="zstd")
    content = path.read_bytes()
    return _descriptor(
        complete._INDEX_PATHS[name],
        content=content,
        config_name=complete._INDEX_CONFIGS[name],
        row_count=len(rows),
    )


def _stage_control_plane(root: Path) -> HuggingFaceSourcePin:
    root.mkdir(parents=True)
    data: list[dict[str, object]] = []
    for config_name, prefix in complete._DATA_CONFIG_PREFIXES.items():
        if config_name == "original_data":
            continue
        content = f"unfetched data fixture: {config_name}".encode()
        data.append(
            _descriptor(
                f"{prefix}part-000000.parquet",
                content=content,
                config_name=config_name,
                row_count=1,
            )
        )
    for contract in complete.PINNED_ORIGINAL_SHARDS:
        data.append(
            _descriptor(
                contract.release_path,
                sha256=contract.sha256,
                size=contract.size_bytes,
                config_name="original_data",
                row_count=contract.row_count,
            )
        )

    indexes: list[dict[str, object]] = []
    data_by_config = {
        str(item["config_name"]): item
        for item in data
        if item["config_name"] != "original_data"
    }
    for name in sorted(set(complete._INDEX_PATHS) - {"original_rows"}):
        family = complete._INDEX_FAMILIES[name]
        target = data_by_config[family]
        row: dict[str, object] = {
            "cid": target["content_id"],
            "end_document_index": (
                0 if family in {"bm25_documents", "corpus", "vectors"} else -1
            ),
            "first_key": _cid(f"{family}-first"),
            "kind": family,
            "last_key": _cid(f"{family}-last"),
            "relative_path": target["path"],
            "row_count": target["row_count"],
            "schema_version": complete.META_SCHEMA_VERSION,
            "sha256": target["sha256"],
            "shard_id": 0,
            "size_bytes": target["byte_length"],
            "start_document_index": (
                0 if family in {"bm25_documents", "corpus", "vectors"} else -1
            ),
        }
        if name == "bm25_keyword_shards":
            row.update(
                posting_count=1,
                term_count=1,
                token_instance_count=1,
            )
        elif name in {
            "graph_incoming_adjacency",
            "graph_outgoing_adjacency",
        }:
            row.update(
                adjacency_count=1,
                direction=(
                    "incoming"
                    if name == "graph_incoming_adjacency"
                    else "outgoing"
                ),
                first_page_index=0,
                last_page_index=0,
                node_count=1,
            )
        elif name == "vector_chunks":
            row.update(
                centroid=[1.0, 0.0],
                centroid_min_score=1.0,
                centroid_shard_count=1,
                chunk_in_cluster=0,
                cluster_id=0,
                dimension=2,
                model_name=(
                    "fixture/model@" + "a" * 40
                ),
                shard_centroid=[1.0, 0.0],
            )
        indexes.append(
            _write_index(
                root,
                name,
                [row],
                metadata={
                    b"schema_version": complete.META_SCHEMA_VERSION.encode()
                },
            )
        )

    original_rows: list[dict[str, object]] = []
    global_index = 0
    admitted = 12_714
    for contract in complete.PINNED_ORIGINAL_SHARDS:
        for shard_row in range(contract.row_count):
            status = (
                "admitted"
                if global_index < admitted
                else "publication_rejected"
            )
            identity = complete._STATUS_IDENTITY[status]
            original_rows.append(
                {
                    "security_ir_source_cid": _cid(
                        f"source-row-{global_index}"
                    ),
                    "source_row_index": global_index,
                    "source_status": status,
                    "source_identity_domain": identity[0],
                    "source_identity_schema_version": identity[1],
                    "source_shard_cid": contract.cid,
                    "source_shard_path": contract.source_path,
                    "source_shard_row_index": shard_row,
                    "relative_path": contract.release_path,
                    "source_dataset_id": complete.PINNED_SOURCE_DATASET_ID,
                    "source_revision": complete.PINNED_SOURCE_REVISION,
                    "schema_version": (
                        complete.ORIGINAL_ROW_INDEX_SCHEMA_VERSION
                    ),
                }
            )
            global_index += 1
    indexes.append(
        _write_index(
            root,
            "original_rows",
            original_rows,
            metadata={
                b"primary_key": b"security_ir_source_cid",
                b"schema_version": (
                    complete.ORIGINAL_ROW_INDEX_SCHEMA_VERSION.encode()
                ),
            },
        )
    )

    by_config = {
        str(item.get("config_name", "")): []
        for item in (*data, *indexes)
    }
    for item in (*data, *indexes):
        by_config[str(item.get("config_name", ""))].append(item)
    viewer_configs: dict[str, object] = {}
    for config_name in complete._VIEWER_CONFIGS:
        matching = by_config[config_name]
        viewer_configs[config_name] = {
            "features": {"fixture": {"dtype": "string"}},
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
    derived_root = _cid("derived-root")
    metadata_content = canonical_json_bytes(
        {
            "configs": viewer_configs,
            "dataset_id": DATASET_ID,
            "derived_dataset_root": derived_root,
            "schema_version": "cvefixes-huggingface-parquet/v1",
        }
    )
    (root / complete.COMPLETE_METADATA_PATH).write_bytes(metadata_content)
    public = [
        _descriptor(
            "README.md",
            content=b"fixture",
            media_type="text/markdown",
        ),
        _descriptor(
            "evaluation-report.json",
            content=b'{"fixture":true}',
            media_type="application/json",
        ),
        _descriptor(
            complete.COMPLETE_METADATA_PATH,
            content=metadata_content,
            media_type="application/json",
        ),
    ]
    release_root = _cid("release-root")
    release_manifest = ReleaseManifest(
        source_cids=tuple(contract.cid for contract in complete.PINNED_ORIGINAL_SHARDS),
        parent_cids=(derived_root,),
        config_cid=_cid("config"),
        payload={
            "derived_dataset_schema_version": (
                complete.COMPLETE_BUILD_SCHEMA_VERSION
            ),
            "derived_security_ir_profile": (
                complete.DERIVED_SECURITY_IR_PROFILE
            ),
            "grants_execution_authority": False,
            "release_root": release_root,
            "release_schema_version": "cvefixes-huggingface-release/v1",
        },
        dataset_id=DATASET_ID,
        profile=complete.ORIGINAL_MIRROR_PROFILE,
        record_cids=(_cid("canonical-record"),),
        shard_cids=tuple(str(item["content_id"]) for item in data),
    )
    original_runtime = {
        "byte_exact_upstream_copy": True,
        "config_name": "original_data",
        "mirror_profile": complete.ORIGINAL_MIRROR_PROFILE,
        "operator_acknowledgement_required": True,
        "row_index_config_name": "original_row_index",
        "shards": [
            {
                "content_id": contract.cid,
                "release_path": contract.release_path,
                "row_count": contract.row_count,
                "sha256": contract.sha256,
                "size_bytes": contract.size_bytes,
                "source_path": contract.source_path,
            }
            for contract in complete.PINNED_ORIGINAL_SHARDS
        ],
        "source_dataset_id": complete.PINNED_SOURCE_DATASET_ID,
        "source_profile_sha256": complete.PINNED_SOURCE_PROFILE_SHA256,
        "source_revision": complete.PINNED_SOURCE_REVISION,
    }
    artifacts = sorted((*public, *data, *indexes), key=lambda item: item["path"])
    manifest = {
        "artifacts": artifacts,
        "bm25": {},
        "build_runtime": {
            "build_schema_version": complete.COMPLETE_BUILD_SCHEMA_VERSION,
            "cuda": {
                "cuda_required": True,
                "embedding_dimension": 2,
                "model_revision": "a" * 40,
                "record_count": 1,
            },
            "original_data": original_runtime,
            "source_verification": {
                "profile_sha256": complete.PINNED_SOURCE_PROFILE_SHA256,
                "row_count": 12_987,
                "shard_count": 3,
                "verified": True,
            },
        },
        "configs": {
            **complete._DATA_CONFIG_PATTERNS,
            **{
                complete._INDEX_CONFIGS[name]: path
                for name, path in complete._INDEX_PATHS.items()
            },
        },
        "counts": {
            "admitted_rows": 12_714,
            "bm25_documents": 1,
            "bm25_posting_rows": 1,
            "canonical_security_ir_records": 1,
            "corpus_rows": 1,
            "graph_data_shards": 4,
            "graph_edges": 1,
            "graph_nodes": 1,
            "original_data_bytes": sum(
                contract.size_bytes
                for contract in complete.PINNED_ORIGINAL_SHARDS
            ),
            "original_data_rows": 12_987,
            "original_data_shards": 3,
            "original_row_index_rows": 12_987,
            "rejected_rows": 273,
            "vector_rows": 1,
        },
        "dataset_id": DATASET_ID,
        "derived_dataset_root": derived_root,
        "graph": {
            "edge_count": 1,
            "graph_root": _cid("graph-root"),
            "node_count": 1,
        },
        "indexes": {
            Path(str(item["path"])).stem: _compact(item) for item in indexes
        },
        "parquet": {
            "compression": {
                "derived_and_indexes": "zstd",
                "original_data": "upstream_byte_exact",
            },
            "physical_index_count": 9,
        },
        "primary_key": "entry_cid",
        "release_manifest": release_manifest.to_dict(),
        "release_root": release_root,
        "schema_version": "cvefixes-huggingface-release/v1",
        "source": {
            "dataset_id": complete.PINNED_SOURCE_DATASET_ID,
            "source_revision": complete.PINNED_SOURCE_REVISION,
        },
        "vector": {
            "dimension": 2,
            "embedded_rows": 1,
            "model_revision": "a" * 40,
            "neutral_rows": 0,
            "retrieval_index_root": _cid("retrieval-root"),
            "rows_sorted_by": "cosine_similarity_to_shard_centroid_desc",
            "searchable": True,
            "shard_count": 1,
        },
    }
    manifest_content = canonical_json_bytes(manifest)
    (root / "manifest.json").write_bytes(manifest_content)
    return HuggingFaceSourcePin(
        dataset_id=DATASET_ID,
        revision=REVISION,
        manifest_sha256=hashlib.sha256(manifest_content).hexdigest(),
        release_root=release_root,
    )


def _rewrite_index_descriptor(
    root: Path,
    pin: HuggingFaceSourcePin,
    name: str,
) -> HuggingFaceSourcePin:
    del pin
    path = root / complete._INDEX_PATHS[name]
    content = path.read_bytes()
    replacement = _descriptor(
        complete._INDEX_PATHS[name],
        content=content,
        config_name=complete._INDEX_CONFIGS[name],
        row_count=pq.ParquetFile(path).metadata.num_rows,
    )
    manifest = json.loads((root / "manifest.json").read_bytes())
    for index, value in enumerate(manifest["artifacts"]):
        if value["path"] == replacement["path"]:
            manifest["artifacts"][index] = replacement
            break
    else:  # pragma: no cover - fixture invariant
        raise AssertionError(name)
    manifest["indexes"][name] = _compact(replacement)
    content = canonical_json_bytes(manifest)
    (root / "manifest.json").write_bytes(content)
    return HuggingFaceSourcePin(
        dataset_id=DATASET_ID,
        revision=REVISION,
        manifest_sha256=hashlib.sha256(content).hexdigest(),
        release_root=manifest["release_root"],
    )


def test_complete_loader_verifies_routes_without_opening_data(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source"
    pin = _stage_control_plane(root)
    raw_sentinel = (
        root
        / "data"
        / "original"
        / "part-000000.parquet"
    )
    raw_sentinel.parent.mkdir(parents=True)
    raw_sentinel.write_bytes(b"must not be opened")

    loaded = load_huggingface_complete_release(root, pin)

    assert loaded.pin == pin
    assert loaded.receipt.verified
    assert loaded.receipt.index_count == 9
    assert loaded.receipt.original_shard_count == 3
    assert loaded.receipt.original_row_count == 12_987
    assert loaded.receipt.original_byte_count == 1_220_319_479
    assert loaded.receipt.raw_originals_loaded is False
    assert loaded.receipt.grants_execution_authority is False
    assert not hasattr(loaded, "records")
    assert not hasattr(loaded, "dataset")


def test_complete_cache_copies_only_control_plane(tmp_path: Path) -> None:
    source = tmp_path / "source"
    pin = _stage_control_plane(source)
    raw_sentinel = source / "data" / "original" / "part-000000.parquet"
    raw_sentinel.parent.mkdir(parents=True)
    raw_sentinel.write_bytes(b"must not be copied")

    cache = HuggingFaceCompleteReleaseCache(
        tmp_path / "cache",
        fetcher=lambda requested, destination: source,
    )
    fetched = cache.materialize(pin)
    cached = cache.load(pin)

    assert fetched.receipt.offline is False
    assert cached.receipt.offline is True
    cache_root = cache.path_for(pin)
    assert not (cache_root / "data").exists()
    assert {
        path.relative_to(cache_root).as_posix()
        for path in cache_root.rglob("*")
        if path.is_file()
    } == {
        cache._MARKER,
        "manifest.json",
        complete.COMPLETE_METADATA_PATH,
        *(complete._INDEX_PATHS.values()),
    }


def test_pinned_complete_manifest_tampering_fails_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source"
    pin = _stage_control_plane(root)
    manifest_path = root / "manifest.json"
    manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")

    with pytest.raises(
        HuggingFaceSourceIntegrityError, match="manifest digest"
    ):
        load_huggingface_complete_release(root, pin)


def test_rehashed_route_index_tampering_fails_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source"
    pin = _stage_control_plane(root)
    path = root / complete._INDEX_PATHS["corpus_chunks"]
    table = pq.read_table(path)
    rows = table.to_pylist()
    rows[0]["sha256"] = "0" * 64
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    column: row[column]
                    for column in complete._INDEX_COLUMNS["corpus_chunks"]
                }
                for row in rows
            ]
        ).replace_schema_metadata(table.schema.metadata),
        path,
        compression="zstd",
    )
    pin = _rewrite_index_descriptor(root, pin, "corpus_chunks")

    with pytest.raises(
        HuggingFaceSourceIntegrityError, match="route binding"
    ):
        load_huggingface_complete_release(root, pin)


def test_rehashed_original_position_tampering_fails_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source"
    pin = _stage_control_plane(root)
    path = root / complete._INDEX_PATHS["original_rows"]
    table = pq.read_table(path)
    rows = table.to_pylist()
    rows[0]["source_shard_row_index"] = 1
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    column: row[column]
                    for column in complete._ORIGINAL_ROW_COLUMNS
                }
                for row in rows
            ]
        ).replace_schema_metadata(table.schema.metadata),
        path,
        compression="zstd",
    )
    pin = _rewrite_index_descriptor(root, pin, "original_rows")

    with pytest.raises(
        HuggingFaceSourceIntegrityError, match="position binding"
    ):
        load_huggingface_complete_release(root, pin)


def test_hub_fetcher_has_control_plane_only_allowlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    pin = _stage_control_plane(source)
    observed: dict[str, object] = {}

    def snapshot_download(**kwargs):
        observed.update(kwargs)
        destination = Path(kwargs["local_dir"])
        shutil.copy2(source / "manifest.json", destination / "manifest.json")
        shutil.copy2(
            source / complete.COMPLETE_METADATA_PATH,
            destination / complete.COMPLETE_METADATA_PATH,
        )
        shutil.copytree(source / "indexes", destination / "indexes")
        return str(destination)

    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "snapshot_download", snapshot_download)
    destination = tmp_path / "fetched"
    destination.mkdir()

    result = HuggingFaceHubCompleteReleaseFetcher()(pin, destination)

    assert result == destination
    assert observed["revision"] == REVISION
    assert set(observed["allow_patterns"]) == {
        "manifest.json",
        complete.COMPLETE_METADATA_PATH,
        "indexes/*.parquet",
    }
    assert all("data/original" not in pattern for pattern in observed["allow_patterns"])
