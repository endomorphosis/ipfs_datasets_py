from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterator

import pyarrow.parquet as parquet
import pytest

from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_embeddings import (
    SkillCenterEmbeddingConfig,
    SkillCenterEmbeddingError,
    iter_skillcenter_embedding_rows,
    load_skillcenter_embedding_corpus,
    run_skillcenter_embedding_job,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.skillcenter import (
    SkillCenterBundleManifest,
    SkillCenterSkillRecord,
)


_BUNDLE_SHA256 = "b" * 64


def _record(
    skill_id: str,
    *,
    metadata_yaml: str = "license_spdx: MIT\nlicense_risk: allow\n",
    skill_md: str,
) -> SkillCenterSkillRecord:
    return SkillCenterSkillRecord(
        skill_id=skill_id,
        domain="security",
        profile="security",
        source_type="github",
        source_url=f"https://example.test/{skill_id}",
        title=f"Title {skill_id}",
        overall_score=4.0,
        skill_kind="skill-md",
        language="en",
        source_id=f"source-{skill_id}",
        primary_source_id=f"primary-{skill_id}",
        metadata_yaml=metadata_yaml,
        skill_md=skill_md,
        library_md="",
        dataset_id="example/skillcenter",
        dataset_revision="revision-123",
        repository_file="security.sqlite",
        bundle_sha256=_BUNDLE_SHA256,
    )


class _Reader:
    def __init__(self, records: list[SkillCenterSkillRecord]) -> None:
        self.records = sorted(records, key=lambda item: item.skill_id)

    def inspect(self) -> SkillCenterBundleManifest:
        return SkillCenterBundleManifest(
            dataset_id="example/skillcenter",
            dataset_revision="revision-123",
            repository_file="security.sqlite",
            local_sha256=_BUNDLE_SHA256,
            size_bytes=1024,
            bundle_type="lite",
            bundle_version="fixture",
            created_at="2026-01-01T00:00:00Z",
            total_skills=len(self.records),
        )

    def iter_records(
        self,
        *,
        limit: int | None = None,
        batch_size: int = 256,
        start_after: str = "",
        **_kwargs: object,
    ) -> Iterator[SkillCenterSkillRecord]:
        _ = batch_size
        records = [item for item in self.records if item.skill_id > start_after]
        if limit is not None:
            records = records[:limit]
        yield from records


class _Embedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vectors.append(
                [
                    float(digest[0]) / 255.0,
                    float(digest[1]) / 255.0,
                    float(digest[2]) / 255.0,
                ]
            )
        return vectors


def _config(**changes: object) -> SkillCenterEmbeddingConfig:
    values: dict[str, object] = {
        "model_name": "fixture/model",
        "provider": "fixture",
        "device": "cpu",
        "source_batch_size": 1,
        "chunk_chars": 64,
        "chunk_overlap_chars": 8,
    }
    values.update(changes)
    return SkillCenterEmbeddingConfig(**values)  # type: ignore[arg-type]


def test_embedding_job_resumes_without_copying_source_bodies(
    tmp_path: Path,
) -> None:
    records = [
        _record("skill-001", skill_md="A" * 150),
        _record(
            "skill-002",
            metadata_yaml="description: no declared license\n",
            skill_md="QUARANTINED-BODY",
        ),
        _record(
            "skill-003",
            metadata_yaml="license_spdx: GPL-3.0-only\n",
            skill_md="B" * 70,
        ),
    ]
    reader = _Reader(records)
    embedder = _Embedder()
    output = tmp_path / "embeddings"

    partial = run_skillcenter_embedding_job(
        reader,  # type: ignore[arg-type]
        profile="security-lite",
        output_dir=output,
        config=_config(),
        embedder=embedder,
        max_records=2,
    )
    complete = run_skillcenter_embedding_job(
        reader,  # type: ignore[arg-type]
        profile="security-lite",
        output_dir=output,
        config=_config(),
        embedder=embedder,
    )

    assert partial.status == "partial"
    assert partial.source_records_processed == 2
    assert complete.status == "complete"
    assert complete.source_records_processed == 3
    assert complete.embedded_records == 2
    assert complete.vector_count == 5
    assert complete.dimension == 3
    assert complete.batch_count == 3
    assert len(embedder.calls) == 2

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["decision_counts"] == {
        "allow_internal_evaluation": 1,
        "allow_train_and_publish": 1,
        "quarantined_unknown": 1,
    }
    assert manifest["dataset_revision"] == "revision-123"
    assert manifest["config"]["model_name"] == "fixture/model"

    embedding_files = sorted(output.glob("batches/*/embeddings.parquet"))
    policy_files = sorted(output.glob("batches/*/policy.parquet"))
    assert len(embedding_files) == 2
    assert len(policy_files) == 3
    embedding_columns = set(parquet.read_schema(embedding_files[0]).names)
    policy_columns = set(parquet.read_schema(policy_files[0]).names)
    forbidden = {"skill_md", "library_md", "metadata_yaml", "text"}
    assert not forbidden & embedding_columns
    assert not forbidden & policy_columns

    all_policy_rows = sum(
        parquet.read_table(path).num_rows for path in policy_files
    )
    assert all_policy_rows == 3


def test_resume_rejects_configuration_drift(tmp_path: Path) -> None:
    reader = _Reader([_record("skill-001", skill_md="bounded fixture")])
    output = tmp_path / "embeddings"
    run_skillcenter_embedding_job(
        reader,  # type: ignore[arg-type]
        profile="security-lite",
        output_dir=output,
        config=_config(),
        embedder=_Embedder(),
    )

    with pytest.raises(SkillCenterEmbeddingError, match="config_sha256"):
        run_skillcenter_embedding_job(
            reader,  # type: ignore[arg-type]
            profile="security-lite",
            output_dir=output,
            config=_config(chunk_chars=80),
            embedder=_Embedder(),
            max_records=0,
        )


def test_internal_retrieval_mode_embeds_every_entry_cid_once(
    tmp_path: Path,
) -> None:
    records = [
        _record("skill-001", skill_md="A" * 150),
        _record(
            "skill-002",
            metadata_yaml="description: no declared license\n",
            skill_md="QUARANTINED-BODY",
        ),
    ]
    output = tmp_path / "full-embeddings"

    summary = run_skillcenter_embedding_job(
        _Reader(records),  # type: ignore[arg-type]
        profile="full-cid",
        output_dir=output,
        config=_config(
            internal_retrieval_all_records=True,
            max_chunks_per_record=1,
        ),
        embedder=_Embedder(),
    )
    rows = list(
        iter_skillcenter_embedding_rows(
            output,
            columns=("entry_cid", "content_cid", "skill_id"),
        )
    )

    assert summary.embedded_records == 2
    assert summary.vector_count == 2
    assert len({row["entry_cid"] for row in rows}) == 2
    assert all(str(row["entry_cid"]).startswith("bafk") for row in rows)
    assert all(str(row["content_cid"]).startswith("bafk") for row in rows)


def test_resume_rehashes_checkpoint_files(tmp_path: Path) -> None:
    reader = _Reader([_record("skill-001", skill_md="bounded fixture")])
    output = tmp_path / "embeddings"
    run_skillcenter_embedding_job(
        reader,  # type: ignore[arg-type]
        profile="security-lite",
        output_dir=output,
        config=_config(),
        embedder=_Embedder(),
    )
    policy_path = next(output.glob("batches/*/policy.parquet"))
    policy_path.write_bytes(policy_path.read_bytes() + b"tampered")

    with pytest.raises(SkillCenterEmbeddingError, match="size mismatch"):
        run_skillcenter_embedding_job(
            reader,  # type: ignore[arg-type]
            profile="security-lite",
            output_dir=output,
            config=_config(),
            embedder=_Embedder(),
            max_records=0,
        )


def test_public_corpus_reader_replays_receipts_and_rejects_manifest_tampering(
    tmp_path: Path,
) -> None:
    reader = _Reader([_record("skill-001", skill_md="bounded fixture")])
    output = tmp_path / "embeddings"
    run_skillcenter_embedding_job(
        reader,  # type: ignore[arg-type]
        profile="security-lite",
        output_dir=output,
        config=_config(),
        embedder=_Embedder(),
    )

    manifest = load_skillcenter_embedding_corpus(output)
    rows = list(
        iter_skillcenter_embedding_rows(
            output,
            columns=("chunk_id", "skill_id"),
        )
    )
    assert manifest["status"] == "complete"
    assert len(rows) == manifest["vector_count"]
    assert rows[0]["skill_id"] == "skill-001"

    manifest_path = output / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["vector_count"] += 1
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SkillCenterEmbeddingError, match="manifest does not match"):
        load_skillcenter_embedding_corpus(output)
