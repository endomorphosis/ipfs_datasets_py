"""Strict supplied-vector identity joins; no inference or weight downloads."""
from __future__ import annotations

import hashlib
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_embeddings as embeddings


def _payload(cid="sha256:" + "a" * 64):
    return {"entry_cid": cid, "chunk_cid": cid, "legal_id": None, "dimension": 384,
            "model_id": embeddings.SUPPORTED_MODEL, "model_revision": embeddings.SUPPORTED_REVISION,
            "vector_space_id": embeddings.SUPPORTED_VECTOR_SPACE,
            "embedding": [1.0] + [0.0] * 383, "centroid_id": None, "shard_id": None, "family": "vectors"}


def _model_profile():
    return SimpleNamespace(model_id=embeddings.SUPPORTED_MODEL, model_revision=embeddings.SUPPORTED_REVISION,
                           vector_space_id=embeddings.SUPPORTED_VECTOR_SPACE)


def test_vector_evidence_validates_values_without_authenticating_producer():
    value = embeddings._vector_evidence(_payload(), _model_profile())
    assert value["dimension"] == 384 and value["l2_norm"] == 1
    assert len(value["vector_float64_sha256"]) == 64
    assert "training_eligible" not in value
    assert "embedding" not in value


@pytest.mark.parametrize("field,value", [
    ("dimension", True), ("dimension", 383), ("embedding", [1.0]),
    ("embedding", [0.0] * 384), ("embedding", [True] + [0.0] * 383),
    ("embedding", [float("nan")] + [0.0] * 383), ("embedding", [float("inf")] + [0.0] * 383),
    ("embedding", [0.5] + [0.0] * 383), ("model_id", "another/model"),
    ("model_revision", "main"), ("vector_space_id", "other-space"),
    ("chunk_cid", "sha256:" + "b" * 64), ("entry_cid", "row-1"),
    ("legal_id", "usc:us:5:1"), ("family", "corpus"), ("centroid_id", True),
    ("shard_id", -1), ("input_hash", "c" * 64),
])
def test_vector_evidence_rejects_mismatched_profile_and_malformed_values(field, value):
    row = _payload()
    row[field] = value
    with pytest.raises(embeddings.USCodeEmbeddingJoinError):
        embeddings._vector_evidence(row, _model_profile())


def test_existing_model_bytes_are_only_separate_local_evidence(tmp_path):
    path = tmp_path / "model.bin"
    raw = b"local supplied artifact; this fixture is not model weights"
    path.write_bytes(raw)
    ref = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    result = embeddings._verify_model_artifact(ref, 1024)
    assert result["bytes_verified"] is True
    assert result["model_revision_binding_authenticated"] is False
    assert path.read_bytes() == raw
    with pytest.raises(embeddings.USCodeEmbeddingJoinError, match="SHA-256"):
        embeddings._verify_model_artifact({**ref, "sha256": "0" * 64}, 1024)
    with pytest.raises(embeddings.USCodeEmbeddingJoinError, match="contract"):
        embeddings._verify_model_artifact(ref, 1)
    alias = tmp_path / "model-alias"
    alias.symlink_to(path)
    with pytest.raises(OSError):
        embeddings._verify_model_artifact({**ref, "path": str(alias)}, 1024)


def _fixture(root, *, vectors=None, extra_vector_shard=None, corrupt_record=False):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_import as importer

    def canonical(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

    corpus = []
    for index, letter in enumerate(("a", "b"), 1):
        corpus.append({"entry_cid": "sha256:" + letter * 64, "legal_id": f"usc:us:5:{index}",
            "source_cid": letter * 64, "source_checksum": letter * 64, "title": "5", "section": str(index),
            "admission_status": "admitted", "admission_reason": "retrieval row only",
            "verification_result": "verified", "release_point": "us/pl/119/102",
            "acquisition_time": "2026-09-08T22:59:35Z", "text": f"The agency shall retain record {index}.",
            "schema_version": importer.RELEASE_SCHEMA, "family": "corpus"})
    descriptors, paths = [], {}

    def shard(relative, family, records, broken=False):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        wrappers = []
        for index, row in enumerate(records):
            raw = canonical(row)
            wrappers.append({"entry_cid": row["entry_cid"], "legal_id": row["legal_id"] or "", "family": family,
                             "record_sha256": "0" * 64 if broken and index == 0 else hashlib.sha256(raw).hexdigest(),
                             "record_json": raw.decode()})
        schema = pa.schema([(name, pa.string()) for name in importer.WRAPPER_COLUMNS])
        pq.write_table(pa.Table.from_pylist(wrappers, schema=schema), path)
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        paths[digest] = path
        descriptors.append({"relative_path": relative, "family": family, "sha256": digest,
                            "size_bytes": len(raw), "row_count": len(records),
                            "schema_id": "uscode-corpus-row/v1" if family == "corpus" else "uscode-vector-row/v1",
                            "media_type": "application/vnd.apache.parquet"})

    shard("data/corpus/part-000000.parquet", "corpus", corpus)
    shard("data/vectors/part-000000.parquet", "vectors",
          vectors if vectors is not None else [_payload(row["entry_cid"]) for row in corpus], corrupt_record)
    if extra_vector_shard is not None:
        shard("data/vectors/part-000001.parquet", "vectors", extra_vector_shard)
    body = {"schema_version": importer.RELEASE_SCHEMA, "release_profile": importer.RELEASE_PROFILE,
            "dataset_repo_id": "fixture/uscode", "default_excludes_recovery": True, "artifacts": descriptors,
            "model_id": embeddings.SUPPORTED_MODEL, "model_revision": embeddings.SUPPORTED_REVISION,
            "vector_space_id": embeddings.SUPPORTED_VECTOR_SPACE, "release_point": "us/pl/119/102",
            "source_revision": "c" * 40}
    body["manifest_digest"] = hashlib.sha256(canonical(body)).hexdigest()
    raw = canonical(body)
    path = root / "manifest.json"
    path.write_bytes(raw)
    paths[hashlib.sha256(raw).hexdigest()] = path
    release = importer.load_uscode_release({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)},
                                           repo_id="fixture/uscode", revision="d" * 40)
    resolver = lambda ref: paths[ref["sha256"]]
    sources = importer.read_corpus_shard(release, "data/corpus/part-000000.parquet", resolver=resolver).records
    assert len(sources) == 2
    vector_shards = [row["relative_path"] for row in descriptors if row["family"] == "vectors"]
    return release, sources, vector_shards, resolver


def test_verified_identity_join_preserves_source_order_but_never_implies_training_eligibility(tmp_path):
    release, sources, shards, resolver = _fixture(tmp_path)
    audit = embeddings.audit_uscode_embedding_join(release, list(reversed(sources)), vector_shards=shards, resolver=resolver)
    report = audit.to_dict()
    assert [row["entry_cid"] for row in report["rows"]] == [row.entry_cid for row in reversed(sources)]
    assert report["status_counts"] == {"missing_input_binding": 2}
    assert report["vector_rows_scanned"] == 2
    assert report["vector_dispositions"] == []
    assert report["training_eligible_count"] == 0
    assert all(row["published_identity_join_verified"] for row in report["rows"])
    assert all(not row["exact_input_binding_verified"] and not row["producer_binding_verified"] for row in report["rows"])
    assert report["admitted"] is False and report["formalized"] is False
    diagnostics = audit.diagnostic_vectors()
    assert set(diagnostics) == {row.entry_cid for row in sources}
    assert diagnostics[sources[0].entry_cid] == tuple(_payload()["embedding"])
    with pytest.raises(embeddings.USCodeEmbeddingJoinError, match="no eligible training"):
        audit.require_training_embeddings()
    saved = audit.save(tmp_path / "audit.json")
    assert saved["sha256"] == hashlib.sha256(Path(saved["path"]).read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        audit.save(tmp_path / "audit.json")


@pytest.mark.parametrize("cross_shard", [False, True])
def test_duplicate_vectors_are_ambiguous_even_if_numeric_values_match(tmp_path, cross_shard):
    vector = _payload()
    release, sources, shards, resolver = _fixture(tmp_path, vectors=[vector] if cross_shard else [vector, vector],
                                                 extra_vector_shard=[vector] if cross_shard else None)
    audit = embeddings.audit_uscode_embedding_join(release, sources, vector_shards=shards, resolver=resolver)
    assert audit.status_counts == {"ambiguous_embedding": 1, "missing_embedding": 1}
    assert audit.diagnostic_vectors() == {}


def test_missing_vectors_never_fall_back_to_mock_or_first_available(tmp_path):
    release, sources, shards, resolver = _fixture(tmp_path, vectors=[_payload()])
    audit = embeddings.audit_uscode_embedding_join(release, sources, vector_shards=shards, resolver=resolver)
    assert audit.status_counts == {"missing_input_binding": 1, "missing_embedding": 1}
    assert set(audit.diagnostic_vectors()) == {sources[0].entry_cid}
    assert audit.to_dict()["embedding_generation_performed"] is False


def test_invalid_published_dimension_stays_visible_in_join_disposition(tmp_path):
    value = _payload()
    value["dimension"] = 128
    release, sources, shards, resolver = _fixture(tmp_path, vectors=[value])
    audit = embeddings.audit_uscode_embedding_join(release, sources, vector_shards=shards, resolver=resolver)
    assert audit.status_counts == {"invalid_embedding_record": 1, "missing_embedding": 1}
    assert audit.diagnostic_vectors() == {}


def test_corrupt_wrapper_cannot_hide_an_ambiguous_or_invalid_join(tmp_path):
    release, sources, shards, resolver = _fixture(tmp_path, corrupt_record=True)
    audit = embeddings.audit_uscode_embedding_join(release, sources, vector_shards=shards, resolver=resolver)
    assert audit.status_counts == {"unverified_vector_shard": 2}
    assert audit.diagnostic_vectors() == {}
    assert audit.to_dict()["vector_dispositions"][0]["status"] == "record_hash_mismatch"


def test_physical_vector_corruption_is_rejected_against_release_descriptor(tmp_path):
    release, sources, shards, resolver = _fixture(tmp_path)
    path = resolver(release.artifact(shards[0]).reference)
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="declared size"):
        embeddings.audit_uscode_embedding_join(release, sources, vector_shards=shards, resolver=resolver)


def test_cross_release_sources_duplicate_selection_and_bounds_are_rejected(tmp_path):
    release, sources, shards, resolver = _fixture(tmp_path)
    with pytest.raises(ValueError):
        embeddings.audit_uscode_embedding_join(release, [replace(sources[0], release_id="different-release")],
                                               vector_shards=shards, resolver=resolver)
    with pytest.raises(embeddings.USCodeEmbeddingJoinError, match="duplicate entry"):
        embeddings.audit_uscode_embedding_join(release, [sources[0], sources[0]], vector_shards=shards, resolver=resolver)
    with pytest.raises(embeddings.USCodeEmbeddingJoinError, match="duplicate vector shard"):
        embeddings.audit_uscode_embedding_join(release, sources, vector_shards=shards * 2, resolver=resolver)
    with pytest.raises(embeddings.USCodeEmbeddingJoinError, match="aggregate byte"):
        embeddings.audit_uscode_embedding_join(release, sources, vector_shards=shards, resolver=resolver,
                                               limits=embeddings.EmbeddingJoinLimits(max_vector_bytes=1))
    with pytest.raises(embeddings.USCodeEmbeddingJoinError, match="not a vector shard"):
        embeddings.audit_uscode_embedding_join(release, sources, vector_shards=["data/corpus/part-000000.parquet"], resolver=resolver)


@pytest.mark.parametrize("field,value", [("text", "This is not the pinned source text."),
                                         ("entry_cid", "sha256:" + "e" * 64),
                                         ("record_sha256", "f" * 64), ("row_index", 1)])
def test_forged_verified_source_dataclass_cannot_gain_a_published_join(tmp_path, field, value):
    release, sources, shards, resolver = _fixture(tmp_path)
    forged = replace(sources[0], **{field: value})
    with pytest.raises(ValueError):
        embeddings.audit_uscode_embedding_join(release, [forged], vector_shards=shards, resolver=resolver)


def test_replaced_release_artifact_is_not_authorized_by_a_matching_label(tmp_path):
    release, sources, shards, resolver = _fixture(tmp_path)
    artifact = release.artifact(shards[0])
    forged = replace(release, artifacts=tuple(replace(item, sha256="e" * 64) if item == artifact else item for item in release.artifacts))
    with pytest.raises(ValueError):
        embeddings.audit_uscode_embedding_join(forged, sources, vector_shards=shards, resolver=resolver)
