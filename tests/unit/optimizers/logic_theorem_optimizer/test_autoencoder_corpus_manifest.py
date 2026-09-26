"""Exact bounded batch provenance; no parser, training or network workload."""

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import struct

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_manifest as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord


def _record(tmp_path, index=1, *, text=None, raw=None, start=0, end=None,
            normalization="identity", corpus=False, source_kind=None, vector=None):
    text = text or f"The agency shall retain record {index}."
    raw = text.encode("utf-8") if raw is None else raw
    path = tmp_path / f"source-{index}.txt"
    path.write_bytes(raw)
    artifact = codec.SourceArtifact(hashlib.sha256(raw).hexdigest(), len(raw))
    source = codec.SourceSpan(artifact, source_kind or ("us_code" if corpus else "diagnostic"),
        "release-2026-09", f"document-{index}", "en", f"5 USC {index}" if corpus else f"diagnostic:{index}",
        start, len(raw) if end is None else end, normalization)
    sample = SampleRecord("5", str(index), text, citation=source.citation if corpus else None,
        embedding_model="example/model" if corpus else "mock:stable-sha256",
        embedding_vector=vector if vector is not None else ((0.125, -0.0) if corpus else None))
    provenance = codec.EmbeddingProvenance("example/model", "a" * 40, "b" * 64) if corpus else None
    return codec.SourceSampleRecord(source, sample, provenance), path


def _manifest(records, *, training=None, validation=None, mode="diagnostic", **kwargs):
    return codec.build_corpus_manifest(records,
        training_record_ids=[record.record_id for record in records] if training is None else training,
        validation_record_ids=[] if validation is None else validation, mode=mode, **kwargs)


def _resolver(entries):
    paths = {record.source.artifact.sha256: path for record, path in entries}
    return lambda ref: paths[ref["sha256"]]


def test_diagnostic_roundtrip_preserves_historical_samples_and_has_no_admission_claim(tmp_path):
    entries = [_record(tmp_path, 1), _record(tmp_path, 2)]
    records = [record for record, _ in entries]
    ids = [record.record_id for record in records]
    manifest = _manifest(records, validation=ids)
    destination = tmp_path / "batch.manifest.json"
    saved = manifest.save(destination, resolver=_resolver(entries))
    loaded = codec.load_corpus_manifest(destination, expected_sha256=saved["sha256"], expected_size_bytes=saved["bytes"])
    assert loaded.to_bytes() == manifest.to_bytes()
    assert loaded.dataset_snapshot_id == saved["dataset_snapshot_id"]
    assert loaded.split_snapshot_id == saved["split_snapshot_id"]
    result = loaded.verify_job_records([record.sample for record in records], [asdict(record.sample) for record in records],
        dataset_snapshot_id=saved["dataset_snapshot_id"], split_snapshot_id=saved["split_snapshot_id"])
    assert result["training_record_ids"] == ids
    assert result["validation_record_ids"] == ids
    assert result["frontend"] == "legacy_us_code"
    assert result["global_holdout_verified"] is False
    assert result["batch_split_disjoint"] is False
    assert result["embedding_producer_authenticated"] is False
    assert result["source_authority_authenticated"] is False
    assert result["source_kind_counts"] == {"diagnostic": 2}
    assert result["language_counts"] == {"en": 2}
    assert b"roundtrip_ok" not in loaded.to_bytes()
    assert b"admitted" not in loaded.to_bytes()
    with pytest.raises(FileExistsError):
        manifest.save(destination, resolver=_resolver(entries))


def test_manifest_metadata_is_fresh_and_records_are_immutable(tmp_path):
    record, _ = _record(tmp_path)
    manifest = _manifest([record])
    raw = manifest.to_bytes()
    data = manifest.to_dict()
    data["dataset"]["records"].clear()
    manifest.source_refs[0]["bytes"] = 1
    manifest.source_kind_counts["forged"] = 1
    with pytest.raises((AttributeError, TypeError)):
        manifest.records[0].sample.text = "changed"
    assert manifest.to_bytes() == raw
    assert len(manifest.records) == 1


def test_metadata_and_verification_reuse_validated_immutable_records(tmp_path, monkeypatch):
    record, path = _record(tmp_path)
    manifest = _manifest([record])
    monkeypatch.setattr(codec, "_parse", lambda _: pytest.fail("reparsed complete manifest"))
    assert manifest.records is manifest.records
    assert manifest.dataset_snapshot_id.startswith("sha256:")
    assert manifest.split_snapshot_id.startswith("sha256:")
    assert manifest.mode == "diagnostic"
    assert manifest.source_kind_counts == {"diagnostic": 1}
    assert manifest.language_counts == {"en": 1}
    manifest.validate_sources(_resolver([(record, path)]))
    manifest.verify_job_records([record.sample], [])


def test_dataset_identity_is_independent_of_ordered_split_identity(tmp_path):
    records = [_record(tmp_path, index)[0] for index in (1, 2)]
    first = _manifest(records)
    reordered = _manifest(list(reversed(records)))
    assert first.dataset_snapshot_id == reordered.dataset_snapshot_id
    assert first.split_snapshot_id != reordered.split_snapshot_id
    same = _manifest(list(reversed(records)), training=[record.record_id for record in records])
    assert first.to_bytes() == same.to_bytes()


@pytest.mark.parametrize("field,value", [("release_id", "different-release"), ("document_id", "different-document"),
    ("citation", "other citation"), ("source_kind", "us_constitution"), ("language", "fr")])
def test_source_aware_record_identity_binds_every_source_identity(tmp_path, field, value):
    record, _ = _record(tmp_path)
    changed = replace(record, source=replace(record.source, **{field: value}))
    assert changed.record_id != record.record_id
    assert _manifest([changed]).dataset_snapshot_id != _manifest([record]).dataset_snapshot_id


def test_utf8_byte_selector_and_explicit_whitespace_normalization(tmp_path):
    prefix = "préface\n".encode()
    selected = "  The\tagency shall\nretain café. \n".encode()
    raw = prefix + selected + b"tail"
    record, path = _record(tmp_path, text="The agency shall retain café.", raw=raw,
        start=len(prefix), end=len(prefix) + len(selected), normalization="whitespace-v1")
    manifest = _manifest([record])
    summary = manifest.validate_sources(_resolver([(record, path)]))
    assert summary["source_bytes_verified"] == len(raw)
    assert summary["source_selectors_verified"] is True
    identity = replace(record, source=replace(record.source, normalization="identity"))
    with pytest.raises(codec.CorpusManifestError, match="reproduce"):
        _manifest([identity]).validate_sources(_resolver([(record, path)]))


@pytest.mark.parametrize("case", ["wrong_text", "utf8_boundary", "invalid_utf8", "corrupt", "missing"])
def test_bad_source_is_rejected_before_manifest_write(tmp_path, case):
    record, path = _record(tmp_path, text="é shall remain.")
    if case == "wrong_text":
        record = replace(record, sample=replace(record.sample, text="wrong"))
    elif case == "utf8_boundary":
        record = replace(record, source=replace(record.source, byte_start=1))
    elif case == "invalid_utf8":
        raw = b"\xff" + path.read_bytes()
        path.write_bytes(raw)
        record = replace(record, source=replace(record.source,
            artifact=codec.SourceArtifact(hashlib.sha256(raw).hexdigest(), len(raw)), byte_start=1, byte_end=len(raw)))
    elif case == "corrupt":
        path.write_bytes(b"changed")
    resolver = _resolver([(record, path)]) if case != "missing" else lambda ref: (_ for _ in ()).throw(KeyError(ref["sha256"]))
    destination = tmp_path / "invalid.manifest.json"
    with pytest.raises(codec.CorpusManifestError):
        _manifest([record]).save(destination, resolver=resolver)
    assert not destination.exists()


def test_valid_corpus_binds_supplied_embeddings_and_disjoint_batch_only(tmp_path):
    entries = [_record(tmp_path, index, corpus=True) for index in (1, 2)]
    train, validation = [record for record, _ in entries]
    manifest = _manifest([train, validation], training=[train.record_id], validation=[validation.record_id], mode="corpus")
    result = manifest.verify_job_records([train.sample], [validation.sample])
    assert result["batch_split_disjoint"] is True
    assert result["global_holdout_verified"] is False
    assert result["embedding_producer_authenticated"] is False
    manifest.validate_sources(_resolver(entries))


@pytest.mark.parametrize("case,match", [("mock", "external embeddings"), ("no_provenance", "external embeddings"),
    ("constitution", "qualified English us_code"), ("diagnostic", "qualified English us_code"),
    ("language", "qualified English us_code"), ("citation", "citation"), ("no_validation", "validation")])
def test_corpus_requires_qualified_frontend_and_explicit_embedding_provenance(tmp_path, case, match):
    train, validation = [_record(tmp_path, index, corpus=True)[0] for index in (1, 2)]
    if case == "mock":
        train = replace(train, sample=replace(train.sample, embedding_model="mock:stable-sha256"), embedding_provenance=None)
    elif case == "no_provenance":
        train = replace(train, embedding_provenance=None)
    elif case in {"constitution", "diagnostic"}:
        train = replace(train, source=replace(train.source, source_kind="us_constitution" if case == "constitution" else "diagnostic"))
    elif case == "language":
        train = replace(train, source=replace(train.source, language="fr"))
    elif case == "citation":
        train = replace(train, sample=replace(train.sample, citation="wrong"))
    records = [train] if case == "no_validation" else [train, validation]
    with pytest.raises(codec.CorpusManifestError, match=match):
        _manifest(records, training=[train.record_id], validation=[] if case == "no_validation" else [validation.record_id], mode="corpus")


@pytest.mark.parametrize("case,match", [("artifact", "source artifact"), ("document", "document"), ("content", "normalized content")])
def test_corpus_rejects_batch_leakage_across_release_or_source_aliases(tmp_path, case, match):
    train, validation = [_record(tmp_path, index, corpus=True)[0] for index in (1, 2)]
    if case == "artifact":
        validation = replace(validation, source=replace(validation.source, artifact=train.source.artifact))
    elif case == "document":
        validation = replace(validation, source=replace(validation.source, document_id=train.source.document_id, release_id="another-release"))
    else:
        validation = replace(validation, sample=replace(validation.sample, text="  " + train.sample.text.upper() + "\n"))
    with pytest.raises(codec.CorpusManifestError, match=match):
        _manifest([train, validation], training=[train.record_id], validation=[validation.record_id], mode="corpus")


def test_constitution_inventory_is_diagnostic_without_proof_status(tmp_path):
    record, path = _record(tmp_path, source_kind="us_constitution")
    manifest = _manifest([record], validation=[record.record_id])
    manifest.validate_sources(_resolver([(record, path)]))
    assert manifest.source_kind_counts == {"us_constitution": 1}
    assert manifest.verification_summary()["batch_split_disjoint"] is False


@pytest.mark.parametrize("case,match", [("same_record", "duplicate record"), ("same_selector", "duplicate source selector"),
    ("same_payload", "duplicate sample payload"), ("unknown", "unknown record"), ("unused", "assigned")])
def test_split_membership_rejects_duplicates_aliases_unknown_or_unused_records(tmp_path, case, match):
    first, _ = _record(tmp_path, 1)
    second, _ = _record(tmp_path, 2)
    records = [first, second]
    ids = [record.record_id for record in records]
    if case == "same_record":
        ids.append(first.record_id)
    elif case == "same_selector":
        records[1] = replace(second, source=first.source)
        ids = [record.record_id for record in records]
    elif case == "same_payload":
        records[1] = replace(second, sample=first.sample)
        ids = [record.record_id for record in records]
    elif case == "unknown":
        ids.append("sha256:" + "0" * 64)
    else:
        ids.pop()
    with pytest.raises(codec.CorpusManifestError, match=match):
        _manifest(records, training=ids)


def test_exact_embedding_encoding_preserves_signed_zero_integer_types_and_tiny_changes(tmp_path):
    record, _ = _record(tmp_path, vector=(0.0, -0.0, 1, 1.0, 1.0000000000000002))
    manifest = _manifest([record])
    actual = manifest.records[0].sample.embedding_vector
    assert actual is not None
    assert type(actual[2]) is int and type(actual[3]) is float
    assert [struct.pack(">d", item).hex() for item in actual] == [struct.pack(">d", item).hex() for item in record.sample.embedding_vector]
    for vector in ((-0.0, -0.0, 1, 1.0, 1.0000000000000002), (0.0, -0.0, 1.0, 1.0, 1.0000000000000002),
                   (0.0, -0.0, 1, 1.0, 1.0)):
        changed = replace(record.sample, embedding_vector=vector)
        with pytest.raises(codec.CorpusManifestError, match="exact manifest payload"):
            manifest.verify_job_records([changed], [])
        assert replace(record, sample=changed).record_id != record.record_id


@pytest.mark.parametrize("case", ["order", "citation", "dataset", "split", "count"])
def test_job_records_and_snapshot_ids_must_match_exactly(tmp_path, case):
    records = [_record(tmp_path, index)[0] for index in (1, 2)]
    manifest = _manifest(records)
    supplied = [record.sample for record in records]
    kwargs = {}
    if case == "order":
        supplied.reverse()
    elif case == "citation":
        supplied[0] = replace(supplied[0], citation="new citation")
    elif case in {"dataset", "split"}:
        kwargs[case + "_snapshot_id"] = "sha256:" + "0" * 64
    else:
        supplied.pop()
    with pytest.raises(codec.CorpusManifestError):
        manifest.verify_job_records(supplied, [], **kwargs)


@pytest.mark.parametrize("case", ["duplicate", "nan", "unknown", "record_id", "dataset_id", "not_canonical"])
def test_manifest_rejects_ambiguous_or_resealed_invalid_json(tmp_path, case):
    manifest = _manifest([_record(tmp_path)[0]])
    data = manifest.to_dict()
    if case == "duplicate":
        raw = b'{"schema_version":"x","schema_version":"y"}'
    elif case == "nan":
        raw = b'{"bad":NaN}'
    elif case == "not_canonical":
        raw = json.dumps(data, indent=2).encode()
    else:
        if case == "unknown":
            data["roundtrip_ok"] = True
        elif case == "record_id":
            data["dataset"]["records"][0]["record_id"] = "sha256:" + "0" * 64
        else:
            data["dataset_snapshot_id"] = "sha256:" + "0" * 64
        raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(codec.CorpusManifestError):
        codec.CorpusManifest(raw)


@pytest.mark.parametrize("limit,value", [("max_records", 1), ("max_sources", 1), ("max_manifest_bytes", 10),
    ("max_source_bytes", 2), ("max_total_source_bytes", 5), ("max_sample_text_bytes", 2),
    ("max_embedding_dimensions", 1), ("max_total_embedding_dimensions", 1)])
def test_batch_bounds_are_enforced(tmp_path, limit, value):
    records = [_record(tmp_path, index, vector=(0.25, -0.0))[0] for index in (1, 2)]
    with pytest.raises(codec.CorpusManifestError, match="bound|limit"):
        _manifest(records, limits=codec.ManifestLimits(**{limit: value}))


def test_load_checks_hash_size_and_refuses_symlink_sources(tmp_path):
    record, path = _record(tmp_path)
    manifest = _manifest([record])
    saved = manifest.save(tmp_path / "manifest.json", resolver=_resolver([(record, path)]))
    with pytest.raises(codec.CorpusManifestError):
        codec.load_corpus_manifest(saved["path"], expected_sha256="0" * 64, expected_size_bytes=saved["bytes"])
    with pytest.raises(codec.CorpusManifestError):
        codec.load_corpus_manifest(saved["path"], expected_sha256=saved["sha256"], expected_size_bytes=saved["bytes"] + 1)
    alias = tmp_path / "alias.txt"
    alias.symlink_to(path)
    with pytest.raises(codec.CorpusManifestError):
        manifest.validate_sources(lambda _: alias)


@pytest.mark.parametrize("kwargs", [{"max_records": 0}, {"max_source_bytes": True}, {"max_manifest_bytes": 2**40}])
def test_limits_cannot_be_disabled(kwargs):
    with pytest.raises(codec.CorpusManifestError):
        codec.ManifestLimits(**kwargs)


@pytest.mark.parametrize("revision", ["main", "latest", "a" * 39, "A" * 40])
def test_embedding_provenance_requires_immutable_revision(revision):
    with pytest.raises(codec.CorpusManifestError):
        codec.EmbeddingProvenance("model", revision, "b" * 64)
