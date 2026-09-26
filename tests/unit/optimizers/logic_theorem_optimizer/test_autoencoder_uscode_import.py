"""Offline published-row extraction, strict release bindings and no fallback."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_import as imp
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import build_corpus_manifest
from ipfs_datasets_py.processors.legal_data.uscode_identity import LegalIdentity


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _row(index=1, **changes):
    result = {"entry_cid": "sha256:" + f"{index:064x}", "legal_id": f"usc:us:5:{index}", "family": "corpus",
        "title": "5", "section": str(index), "admission_status": "admitted", "admission_reason": "published retrieval inclusion",
        "release_point": "us/pl/119/102", "source_checksum": "b" * 64, "source_cid": "b" * 64,
        "verification_result": "verified", "acquisition_time": "2026-09-08T22:59:35Z",
        "text": f"  § {index}. The agency shall retain café records.\n", "chapter": None, "subsection": None,
        "document_index": index, "official_source_url": f"https://uscode.house.gov/{index}", "package_id": None,
        "granule_id": None, "effective_date": None, "observed_at": None, "schema_version": imp.RELEASE_SCHEMA}
    result.update(changes)
    return result


def _wrapper(payload):
    raw = _json(payload)
    return {"entry_cid": payload["entry_cid"], "legal_id": payload.get("legal_id") or "", "family": payload["family"],
        "record_sha256": hashlib.sha256(raw).hexdigest(), "record_json": raw.decode()}


def _release(tmp_path, rows=None, *, wrapper_changes=None, manifest_changes=None, descriptor_changes=None,
             limits=imp.USCodeImportLimits(), family="corpus"):
    rows = rows or [_row(1), _row(2)]
    wrappers = [_wrapper(row) for row in rows]
    if wrapper_changes:
        wrapper_changes(wrappers)
    shard = tmp_path / "shard.parquet"
    pq.write_table(pa.Table.from_pylist(wrappers), shard, compression="zstd")
    raw = shard.read_bytes()
    descriptor = {"relative_path": f"data/{family}/part-000000.parquet", "family": family,
        "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw), "row_count": len(rows),
        "schema_id": "uscode-corpus-row/v1" if family == "corpus" else "uscode-vector-row/v1",
        "media_type": "application/vnd.apache.parquet"}
    descriptor.update(descriptor_changes or {})
    descriptors = [descriptor]
    if family != "corpus":
        descriptors.append({**descriptor, "relative_path": "data/corpus/part-000000.parquet", "family": "corpus", "schema_id": "uscode-corpus-row/v1"})
    manifest = {"schema_version": imp.RELEASE_SCHEMA, "release_profile": imp.RELEASE_PROFILE,
        "dataset_repo_id": "justicedao/ipfs_uscode", "default_excludes_recovery": True, "artifacts": descriptors,
        "model_id": "thenlper/gte-small", "model_revision": "a" * 40, "vector_space_id": "test-vectors:d384",
        "release_point": "us/pl/119/102", "source_revision": "c" * 40}
    manifest.update(manifest_changes or {})
    manifest["manifest_digest"] = hashlib.sha256(_json(manifest)).hexdigest()
    raw = _json(manifest) + b"\n"
    path = tmp_path / "manifest.json"
    path.write_bytes(raw)
    root = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    release = imp.load_uscode_release(root, repo_id="justicedao/ipfs_uscode", revision="d" * 40, limits=limits)
    return release, descriptor["relative_path"], lambda ref: path if ref["sha256"] == root["sha256"] else shard, root


def test_strict_release_and_exact_published_text_extraction(tmp_path):
    release, relative, resolver, root = _release(tmp_path)
    result = imp.read_corpus_shard(release, relative, resolver=resolver, batch_size=1)
    assert result.complete and result.rows_scanned == 2
    assert result.status_counts == {"ready_published_text": 2}
    assert result.records[0].text == _row()["text"]
    extracted = imp.extract_uscode_rows(result.records, tmp_path / "extracted", release=release, resolver=resolver)
    assert Path(extracted.sources[0].path).read_bytes() == _row()["text"].encode()
    receipt = extracted.receipt
    assert receipt["manifest"] == {key: root[key] for key in ("sha256", "bytes")}
    assert receipt["manifest_digest"] == release.manifest_digest
    assert receipt["rows"][0]["record_sha256"] == result.records[0].record_sha256
    assert receipt["rows"][0]["shard"]["sha256"] == result.artifact.sha256
    assert receipt["rows"][0]["source_claims"]["source_checksum"] == "b" * 64
    assert receipt["rows"][0]["extracted_text"]["sha256"] != "b" * 64
    assert receipt["original_official_source_bytes_verified"] is False
    assert receipt["source_claims_authenticated"] is False
    assert receipt["training_eligible"] is False
    assert receipt["admitted"] is False
    assert "roundtrip_ok" not in receipt
    with pytest.raises(FileExistsError):
        imp.extract_uscode_rows(result.records, tmp_path / "extracted", release=release, resolver=resolver)


def test_partial_row_selection_keeps_declared_shard_scope_explicit(tmp_path):
    release, relative, resolver, _ = _release(tmp_path)
    result = imp.read_corpus_shard(release, relative, resolver=resolver, max_rows=1)
    assert result.rows_scanned == 1 and result.complete is False
    assert result.artifact.row_count == 2
    assert result.records[0].entry_cid == _row()["entry_cid"]


@pytest.mark.parametrize("changes,status", [
    ({"text": "  \n"}, "missing_text"), ({"text": None}, "missing_text"),
    ({"admission_status": "quarantined"}, "retrieval_disposition_excluded"),
    ({"admission_status": "excluded"}, "retrieval_disposition_excluded"),
    ({"title": "7"}, "identity_mismatch"), ({"section": "999"}, "identity_mismatch"),
    ({"legal_id": "not-a-legal-id"}, "invalid_corpus_record"),
    ({"release_point": "us/pl/118/45"}, "release_point_mismatch"),
    ({"source_checksum": "missing"}, "invalid_corpus_record"),
])
def test_bad_published_rows_receive_explicit_dispositions_without_fallback(tmp_path, changes, status):
    release, relative, resolver, _ = _release(tmp_path, [_row(1, **changes), _row(2)])
    result = imp.read_corpus_shard(release, relative, resolver=resolver)
    assert result.dispositions[0].status == status
    assert len(result.records) == 1 and result.records[0].entry_cid == _row(2)["entry_cid"]
    assert result.rows_scanned == 2 and result.complete is True


@pytest.mark.parametrize("change,status", [
    (lambda rows: rows[0].update(record_sha256="0" * 64), "record_hash_mismatch"),
    (lambda rows: rows[0].update(entry_cid="sha256:" + "f" * 64), "wrapper_identity_mismatch"),
    (lambda rows: rows[0].update(legal_id="usc:us:7:1"), "wrapper_identity_mismatch"),
    (lambda rows: rows[0].update(family="recovery"), "invalid_wrapper"),
])
def test_wrapper_hash_and_payload_bindings_are_verified(tmp_path, change, status):
    release, relative, resolver, _ = _release(tmp_path, wrapper_changes=change)
    result = imp.read_corpus_shard(release, relative, resolver=resolver)
    assert result.dispositions[0].status == status
    assert len(result.records) == 1


@pytest.mark.parametrize("raw", [b'{"entry_cid":"x","entry_cid":"y"}', b'{"x":NaN}', b'{"x":1e999}'])
def test_resealed_ambiguous_json_remains_ineligible(tmp_path, raw):
    def change(rows):
        rows[0].update(record_json=raw.decode(), record_sha256=hashlib.sha256(raw).hexdigest())
    release, relative, resolver, _ = _release(tmp_path, wrapper_changes=change)
    result = imp.read_corpus_shard(release, relative, resolver=resolver)
    assert result.dispositions[0].status == "invalid_record_json"


def test_duplicate_entry_rows_are_all_quarantined_from_selected_records(tmp_path):
    release, relative, resolver, _ = _release(tmp_path, [_row(), _row()])
    result = imp.read_corpus_shard(release, relative, resolver=resolver)
    assert result.records == ()
    assert result.status_counts == {"duplicate_entry_cid": 2}


def test_qualified_legal_identity_preserves_range_notes_appendix_and_edition(tmp_path):
    identity = LegalIdentity("5", "1001–1003", appendix="A", note="historical", edition="2024")
    row = _row(1, section=identity.section, legal_id=identity.legal_id, appendix="A", note="historical", edition="2024")
    release, relative, resolver, _ = _release(tmp_path, [row])
    result = imp.read_corpus_shard(release, relative, resolver=resolver)
    assert result.status_counts == {"ready_published_text": 1}
    record = result.records[0]
    assert record.legal_id == identity.legal_id
    assert record.canonical_citation == identity.canonical_citation
    assert record.document_id == replace(identity, edition=None).legal_id
    assert record.section == identity.section == "1001-1003"


def test_payload_qualifier_conflict_cannot_override_legal_identity(tmp_path):
    identity = LegalIdentity("5", "1", appendix="A")
    release, relative, resolver, _ = _release(tmp_path, [_row(1, legal_id=identity.legal_id, appendix="B")])
    assert imp.read_corpus_shard(release, relative, resolver=resolver).status_counts == {"identity_mismatch": 1}


@pytest.mark.parametrize("changes", [
    {"schema_version": "other"}, {"dataset_repo_id": "other/repo"}, {"default_excludes_recovery": False},
    {"model_revision": "main"}, {"source_revision": "latest"}, {"artifacts": []},
])
def test_release_root_profile_is_explicit_and_pinned(tmp_path, changes):
    with pytest.raises(imp.USCodeImportError):
        _release(tmp_path, manifest_changes=changes)


@pytest.mark.parametrize("changes", [{"relative_path": "../escape.parquet"}, {"relative_path": "/absolute.parquet"},
    {"relative_path": "data/corpus/./bad.parquet"}, {"row_count": 4097}, {"sha256": "missing"}])
def test_root_descriptors_cannot_escape_or_disable_bounds(tmp_path, changes):
    with pytest.raises(imp.USCodeImportError):
        _release(tmp_path, descriptor_changes=changes)


def test_raw_and_internal_manifest_digests_are_independent_and_verified(tmp_path):
    release, relative, resolver, root = _release(tmp_path)
    with pytest.raises(imp.USCodeImportError):
        imp.load_uscode_release({**root, "sha256": "0" * 64}, repo_id=release.repo_id, revision=release.revision)
    path = Path(root["path"])
    data = json.loads(path.read_bytes())
    data["model_id"] = "changed-model"
    raw = _json(data)
    path.write_bytes(raw)
    changed = {**root, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    with pytest.raises(imp.USCodeImportError, match="internal digest"):
        imp.load_uscode_release(changed, repo_id=release.repo_id, revision=release.revision)


def test_physical_shard_hash_schema_row_count_and_symlinks_are_checked(tmp_path):
    release, relative, resolver, _ = _release(tmp_path, descriptor_changes={"row_count": 3})
    with pytest.raises(imp.USCodeImportError, match="row count"):
        imp.read_corpus_shard(release, relative, resolver=resolver)
    alias = tmp_path / "alias.parquet"
    alias.symlink_to(resolver({"sha256": ""}))
    with pytest.raises(imp.USCodeImportError):
        imp.read_corpus_shard(release, relative, resolver=lambda _: alias)
    resolver({"sha256": ""}).write_bytes(b"changed")
    with pytest.raises(imp.USCodeImportError):
        imp.read_corpus_shard(release, relative, resolver=resolver)


def test_decoding_rechecks_the_same_file_after_concurrent_mutation(tmp_path, monkeypatch):
    release, relative, resolver, _ = _release(tmp_path)
    original = imp._parse
    mutated = []
    def change(raw):
        result = original(raw)
        if not mutated and isinstance(result, dict) and result.get("family") == "corpus":
            mutated.append(True)
            resolver({"sha256": ""}).write_bytes(b"changed")
        return result
    monkeypatch.setattr(imp, "_parse", change)
    with pytest.raises(imp.USCodeImportError, match="changed while decoding"):
        imp.read_wrapped_shard(release, relative, resolver=resolver)


def test_external_vectors_enable_only_explicit_diagnostic_sidecar(tmp_path):
    release, relative, resolver, _ = _release(tmp_path)
    result = imp.read_corpus_shard(release, relative, resolver=resolver)
    extracted = imp.extract_uscode_rows(result.records, tmp_path / "extracted", release=release, resolver=resolver)
    vectors = {row.entry_cid: [0.25, -0.0] for row in result.records}
    records = extracted.source_records(embedding_vectors=vectors, embedding_model=release.model_id)
    assert all(record.embedding_provenance is None for record in records)
    assert all(record.source.normalization == "identity" for record in records)
    assert all(record.source.source_kind == "us_code" for record in records)
    manifest = build_corpus_manifest(records, training_record_ids=[record.record_id for record in records],
        validation_record_ids=[], mode="diagnostic")
    paths = {source.artifact.sha256: Path(source.path) for source in extracted.sources}
    manifest.validate_sources(lambda ref: paths[ref["sha256"]])
    with pytest.raises(imp.USCodeImportError, match="qualified embedding"):
        extracted.source_records(embedding_vectors=vectors, embedding_model=release.model_id, mode="corpus")
    with pytest.raises(imp.USCodeImportError, match="every extracted"):
        extracted.source_records(embedding_vectors={}, embedding_model=release.model_id)
    with pytest.raises(imp.USCodeImportError, match="mock fallback"):
        extracted.source_records(embedding_vectors=vectors, embedding_model="mock:stable-sha256")


def test_vectors_share_wrapper_verifier_without_inventing_legal_identity(tmp_path):
    payload = {"entry_cid": "sha256:" + "1" * 64, "legal_id": None, "family": "vectors", "embedding": [0.25, -0.0]}
    release, relative, resolver, _ = _release(tmp_path, [payload], family="vectors")
    result = imp.read_wrapped_shard(release, relative, resolver=resolver)
    assert result.complete and len(result.rows) == 1
    assert result.rows[0].legal_id is None
    assert result.rows[0].payload["embedding"] == [0.25, -0.0]
    with pytest.raises(imp.USCodeImportError, match="corpus family"):
        imp.read_corpus_shard(release, relative, resolver=resolver)


@pytest.mark.parametrize("limit,value", [("max_shard_bytes", 10), ("max_uncompressed_shard_bytes", 10),
    ("max_record_bytes", 10), ("max_text_bytes", 10)])
def test_reader_respects_artifact_and_row_bounds(tmp_path, limit, value):
    release, relative, resolver, _ = _release(tmp_path, limits=imp.USCodeImportLimits(**{limit: value}))
    if limit in {"max_shard_bytes", "max_uncompressed_shard_bytes"}:
        with pytest.raises(imp.USCodeImportError, match="bound"):
            imp.read_corpus_shard(release, relative, resolver=resolver)
    else:
        result = imp.read_corpus_shard(release, relative, resolver=resolver)
        assert result.records == ()


def test_metadata_outputs_are_fresh_and_extraction_rejects_foreign_release(tmp_path):
    release, relative, resolver, _ = _release(tmp_path)
    result = imp.read_corpus_shard(release, relative, resolver=resolver)
    result.records[0].source_claims["source_checksum"] = "changed"
    release.manifest_reference["bytes"] = 1
    assert result.records[0].source_claims["source_checksum"] == "b" * 64
    other = replace(release, revision="e" * 40)
    with pytest.raises(imp.USCodeImportError, match="another verified release"):
        imp.extract_uscode_rows(result.records, tmp_path / "foreign", release=other, resolver=resolver)
    assert not (tmp_path / "foreign").exists()


@pytest.mark.parametrize("change", ["text", "entry_cid", "row_index", "claims", "citation", "digest"])
def test_extraction_revalidates_physical_row_membership_before_any_writes(tmp_path, change):
    release, relative, resolver, _ = _release(tmp_path)
    result = imp.read_corpus_shard(release, relative, resolver=resolver)
    row = result.records[0]
    updates = {
        "text": {"text": "fabricated"}, "entry_cid": {"entry_cid": result.records[1].entry_cid},
        "row_index": {"row_index": 1}, "claims": {"_source_claims_json": _json({"verification_result": "fake"})},
        "citation": {"canonical_citation": "1 U.S.C. § 1"}, "digest": {"record_sha256": "0" * 64},
    }[change]
    forged = replace(row, **updates)
    destination = tmp_path / "forged"
    with pytest.raises(imp.USCodeImportError, match="verified shard content"):
        imp.extract_uscode_rows([forged], destination, release=release, resolver=resolver)
    assert not destination.exists()


@pytest.mark.parametrize("change", ["model_id", "release_point", "artifacts"])
def test_reader_rechecks_replaceable_release_fields_against_root_bytes(tmp_path, change):
    release, relative, resolver, _ = _release(tmp_path)
    if change == "artifacts":
        changed = replace(release, artifacts=(replace(release.artifacts[0], sha256="0" * 64),))
    else:
        changed = replace(release, **{change: "fabricated"})
    with pytest.raises(imp.USCodeImportError, match="pinned root manifest"):
        imp.read_wrapped_shard(changed, relative, resolver=resolver)


def test_selected_row_verification_reads_each_shard_once(tmp_path, monkeypatch):
    release, relative, resolver, _ = _release(tmp_path)
    result = imp.read_corpus_shard(release, relative, resolver=resolver)
    calls = []
    original = imp.read_corpus_shard
    def read(*args, **kwargs):
        calls.append(args[1])
        return original(*args, **kwargs)
    monkeypatch.setattr(imp, "read_corpus_shard", read)
    verified = imp.verify_uscode_rows(release, list(reversed(result.records)), resolver=resolver)
    assert verified == tuple(reversed(result.records))
    assert calls == [relative]


def test_row_revalidation_bound_is_separate_from_extraction_bound(tmp_path):
    release, relative, resolver, _ = _release(tmp_path, limits=imp.USCodeImportLimits(max_extracted_rows=1))
    result = imp.read_corpus_shard(release, relative, resolver=resolver)
    assert imp.verify_uscode_rows(release, result.records, resolver=resolver) == result.records
    with pytest.raises(imp.USCodeImportError, match="extraction row count"):
        imp.extract_uscode_rows(result.records, tmp_path / "too-many", release=release, resolver=resolver)
    assert not (tmp_path / "too-many").exists()


def test_selected_shard_revalidation_has_an_aggregate_byte_bound(tmp_path):
    release, relative, resolver, _ = _release(tmp_path, limits=imp.USCodeImportLimits(max_verified_shard_bytes=1))
    result = imp.read_corpus_shard(release, relative, resolver=resolver)
    with pytest.raises(imp.USCodeImportError, match="aggregate bound"):
        imp.verify_uscode_rows(release, result.records, resolver=resolver)
