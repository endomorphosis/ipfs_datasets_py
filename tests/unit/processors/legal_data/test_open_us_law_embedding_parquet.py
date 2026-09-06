"""Append-only parquet embedding checkpoints do not rewrite completed vectors."""

from __future__ import annotations

from pathlib import Path

from ipfs_datasets_py.processors.legal_data.open_us_law_embedding_parquet import (
    PARQUET_CHECKPOINT_SCHEMA,
    ParquetEmbeddingCheckpoint,
    load_parquet_checkpoint_records,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    PINNED_DIMENSION,
    deterministic_project,
    fixture_embedding_config,
    fixture_sample_chunks,
    generate_open_us_law_embeddings,
)
from scripts.ops.legal_data.build_state_laws_snapshot_sparse_graphrag import (
    build_snapshot_embedding_config,
)


def _cpu_probe(device: str) -> bool:
    return str(device).startswith("cpu")


def _embedder(texts):
    return deterministic_project(texts, dimension=PINNED_DIMENSION)


def test_parquet_append_does_not_rewrite_prior_parts(tmp_path: Path) -> None:
    chunks = fixture_sample_chunks()
    extra = dict(chunks[0])
    extra["chunk_cid"] = (
        "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
        "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    )
    extra["entry_cid"] = (
        "sha256:ffffffffffffffffffffffffffffffff"
        "ffffffffffffffffffffffffffffffff"
    )
    extra["text"] = "A later batch must append a new parquet part."
    extra["section"] = "9"
    extra["legal_id"] = "oul:or:statutes:1:1:9"
    ckpt = tmp_path / "embeddings"
    config = fixture_embedding_config(batch_size=2)
    first = generate_open_us_law_embeddings(
        chunks,
        config=config,
        embedder=_embedder,
        checkpoint_path=ckpt,
        device_probe=_cpu_probe,
    )
    part0 = ckpt / "part-000000.parquet"
    assert part0.is_file()
    first_bytes = part0.read_bytes()
    first_sha = part0.stat().st_mtime_ns
    store = ParquetEmbeddingCheckpoint.load(ckpt, config_digest=config.digest)
    assert store.row_count == 2
    assert len(store.parts) == 1
    manifest = store.to_manifest()
    assert manifest["schema_version"] == PARQUET_CHECKPOINT_SCHEMA
    assert "embedding" not in manifest
    assert "completed" not in manifest

    second = generate_open_us_law_embeddings(
        chunks + [extra],
        config=config,
        embedder=_embedder,
        checkpoint_path=ckpt,
        resume=True,
        device_probe=_cpu_probe,
    )
    assert part0.read_bytes() == first_bytes
    assert part0.stat().st_mtime_ns == first_sha
    assert (ckpt / "part-000001.parquet").is_file()
    assert len(second.embeddings) == 3
    assert set(second.resumed_chunk_cids) == {
        chunks[0]["chunk_cid"],
        chunks[1]["chunk_cid"],
    }
    store2 = ParquetEmbeddingCheckpoint.load(ckpt, config_digest=config.digest)
    assert store2.row_count == 3
    assert len(store2.parts) == 2
    assert store2.parts[0]["sha256"] == store.parts[0]["sha256"]


def test_snapshot_real_config_requests_cuda() -> None:
    config = build_snapshot_embedding_config(prefer_real=True)
    assert config.device == "cuda"
    assert config.batch_size == 64
    assert config.device_fallback.value == "block"
    fixture = build_snapshot_embedding_config(prefer_real=False)
    assert fixture.device == "cpu"


def test_parquet_skip_index_does_not_require_full_vector_reload(tmp_path: Path) -> None:
    chunks = fixture_sample_chunks()
    extra = dict(chunks[0])
    extra["chunk_cid"] = (
        "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
        "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    )
    extra["entry_cid"] = (
        "sha256:ffffffffffffffffffffffffffffffff"
        "ffffffffffffffffffffffffffffffff"
    )
    extra["text"] = "A later jurisdiction must not reload prior vectors."
    extra["section"] = "9"
    extra["legal_id"] = "oul:or:statutes:1:1:9"
    ckpt = tmp_path / "embeddings"
    config = fixture_embedding_config(batch_size=2)
    first = generate_open_us_law_embeddings(
        chunks,
        config=config,
        embedder=_embedder,
        checkpoint_path=ckpt,
        device_probe=_cpu_probe,
    )
    store = ParquetEmbeddingCheckpoint.load(ckpt, config_digest=config.digest)
    skip = store.load_skip_index()
    assert set(skip) == set(first.embeddings)
    assert all(skip[cid] for cid in skip)

    second = generate_open_us_law_embeddings(
        [extra],
        config=config,
        embedder=_embedder,
        checkpoint_path=ckpt,
        resume=True,
        device_probe=_cpu_probe,
    )
    assert set(second.embeddings) == {extra["chunk_cid"]}
    assert extra["chunk_cid"] not in first.embeddings
    combined = load_parquet_checkpoint_records(ckpt, config=config)
    assert set(combined) == {chunks[0]["chunk_cid"], chunks[1]["chunk_cid"], extra["chunk_cid"]}


def test_snapshot_builder_import_does_not_shadow_cuda_torch() -> None:
    import torch

    assert torch.cuda.is_available(), torch.__file__
    assert "legal-validation" not in str(torch.__file__)
