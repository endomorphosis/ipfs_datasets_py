"""Paired export checks identities and provenance, never certifies label truth."""
from copy import deepcopy
import hashlib
import math

import pytest

from .test_structured_source_384 import parent, rows
from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as decoder
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import contracts as c
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import paired_export as subject
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import runner

PROVENANCE = dict(model_id="authored-tests/synthetic-vectors", revision="a" * 40,
    dimension=384, normalized=True, dtype="float64", truncated=False,
    assets=[dict(name="test-pipeline.json", bytes=1, sha256="b" * 64)],
    device="cpu", rows=12, encode_seconds=1.)
SOURCE = dict(schema="ir384-corpus-source/v1", description="Authored controls with declared test reviews",
              redistribution_allowed=False)


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _review(pair):
    pair["review"] = dict(schema=subject.REVIEW_SCHEMA, decision="accepted", scope="source_to_native_ir",
        reviewer="unit-test-declaration-not-an-expert-review", rationale="Authored control fixture only.",
        source_sha256=_sha(pair["source_text"]), target_sha256=c.digest(pair["target"]),
        source_identity_sha256=c.digest(pair["source_identity"]))


def _normalized_rows(domain, split):
    result = rows(domain, split)
    for row in result:
        norm = math.sqrt(sum(value * value for value in row["embedding"]))
        row["embedding"] = [value / norm for value in row["embedding"]]
    return result


@pytest.fixture(scope="module")
def checkpoints(parent):
    return {domain: decoder.train(domain, _normalized_rows(domain, "train"),
        _normalized_rows(domain, "validation"), parent_projection=parent,
        config={"embedding_provenance": PROVENANCE})["checkpoint"] for domain in decoder.DOMAINS}


def manifests(domain):
    pairs, embeddings = [], []
    for split in ("train", "validation"):
        for index, row in enumerate(_normalized_rows(domain, split)):
            pair = dict(id=row["id"], split=split, source_text=row["source_text"], target=row["target"],
                source_identity=dict(source_uri="fixture://" + row["id"], source_revision="c" * 40,
                    record_id=row["id"], leakage_family_ids=[split + "-family-" + str(index // 2)]))
            _review(pair)
            pairs.append(pair)
            embeddings.append(dict(id=row["id"], source_sha256=_sha(row["source_text"]),
                embedding_sha256=c.digest(row["embedding"]), embedding=row["embedding"]))
    return (dict(schema=subject.PAIRS_SCHEMA, domain_id=domain, source_descriptor=SOURCE, rows=pairs),
            dict(schema=subject.EMBEDDINGS_SCHEMA, provenance=deepcopy(PROVENANCE), rows=embeddings))


def _export(tmp_path, checkpoints, domain="intent_ir", modify=None):
    pairs, embeddings = deepcopy(manifests(domain))
    if modify:
        modify(pairs, embeddings)
    pairs_path = c.write_json(tmp_path / "pairs.json", pairs)
    embeddings_path = c.write_json(tmp_path / "embeddings.json", embeddings)
    base_path = c.write_json(tmp_path / "base.json", checkpoints[domain])
    result = subject.export_reviewed_pairs(domain, pairs_path, embeddings_path, tmp_path / "export",
        base_path=base_path, local_files_only=True)
    return result, pairs_path, embeddings_path, base_path


@pytest.mark.parametrize("domain", decoder.DOMAINS)
def test_four_domain_export_directly_prepares_unchanged_parent(domain, checkpoints, tmp_path):
    result, pairs, embeddings, base = _export(tmp_path, checkpoints, domain)
    assert result["training_rows"] == result["validation_rows"] == result["groups"] == 6
    audit = c.read_json(result["audit_path"])
    assert audit["parent_checkpoint"] == c.file_ref(base)
    assert audit["inputs"] == dict(pairs=c.file_ref(pairs), embeddings=c.file_ref(embeddings))
    assert audit["frozen_vocabulary_verified"]
    for key in ("review_authenticity_verified", "review_semantics_independently_verified",
                "embedding_computation_replayed", "training_performed", "proof_authority"):
        assert audit[key] is False
    before = base.read_bytes()
    source = c.read_json(result["source_path"])
    assert source["reviewed_pair_export"]["audit_sha256"] == result["audit_sha256"]
    prepared = runner.prepare_round(domain, result["training_path"], result["validation_path"],
        tmp_path / "round", source_descriptor=source, base_path=base)
    assert prepared["training_rows"] == prepared["validation_rows"] == 6
    assert base.read_bytes() == before
    assert subject.export_reviewed_pairs(domain, pairs, embeddings, tmp_path / "export",
        base_path=base) == result


@pytest.mark.parametrize("change", ["text", "target", "identity", "review", "weak", "classification", "unseen"])
def test_reject_unbound_reviews_and_non_native_or_unknown_targets(change, checkpoints, tmp_path):
    def modify(pairs, embeddings):
        row = pairs["rows"][0]
        if change == "text": row["source_text"] += " changed"
        elif change == "target": row["target"]["document"]["actor"] = "auditor"
        elif change == "identity": row["source_identity"]["record_id"] = "other"
        elif change == "review": row["review"]["decision"] = "unreviewed"
        elif change == "weak": pairs["schema"] = "skillcenter-intent-feature-corpus/v1"
        elif change == "classification":
            row["target"] = dict(effect="audit", classification_only=True, cwe_ids=["CWE-79"])
            _review(row)
        else:
            row["target"]["document"]["actor"] = "outside-parent-vocabulary"
            _review(row)
    with pytest.raises(ValueError):
        _export(tmp_path, checkpoints, modify=modify)
    assert not (tmp_path / "export").exists()


@pytest.mark.parametrize("change", ["model", "revision", "normalization", "dtype", "asset", "pooling",
                                  "source", "vector", "dimension", "nan", "truncation", "missing", "duplicate"])
def test_reject_mismatched_embedding_pipeline_and_bindings(change, checkpoints, tmp_path):
    def modify(pairs, embeddings):
        provenance, row = embeddings["provenance"], embeddings["rows"][0]
        if change == "model": provenance["model_id"] = "another/model"
        elif change == "revision": provenance["revision"] = "d" * 40
        elif change == "normalization": provenance["normalized"] = False
        elif change == "dtype": provenance["dtype"] = "float32"
        elif change == "asset": provenance["assets"][0]["sha256"] = "d" * 64
        elif change == "pooling": provenance["pooling"] = "invented"
        elif change == "source": row["source_sha256"] = "d" * 64
        elif change == "vector":
            row["embedding"][0] += .5
            row["embedding_sha256"] = c.digest(row["embedding"])
        elif change == "dimension": provenance["dimension"] = 768
        elif change == "nan": row["embedding"][0] = float("nan")
        elif change == "truncation": provenance["truncated"] = True
        elif change == "missing": embeddings["rows"].pop()
        else: embeddings["rows"][1] = deepcopy(row)
    with pytest.raises(ValueError):
        _export(tmp_path, checkpoints, modify=modify)
    assert not (tmp_path / "export").exists()


def test_embedding_timing_and_device_metadata_may_differ(checkpoints, tmp_path):
    def modify(pairs, embeddings):
        embeddings["provenance"].update(device="cuda", rows=20, encode_seconds=.1, batch_size=16)
    result, *_ = _export(tmp_path, checkpoints, modify=modify)
    assert result["training_rows"] == 6


def test_transitive_family_leakage_is_rejected_before_output(checkpoints, tmp_path):
    def modify(pairs, embeddings):
        # Two local bridges connect a train family to a validation family.
        pairs["rows"][0]["source_identity"]["leakage_family_ids"] += ["bridge-a"]
        pairs["rows"][2]["source_identity"]["leakage_family_ids"] += ["bridge-a", "bridge-b"]
        pairs["rows"][6]["source_identity"]["leakage_family_ids"] += ["bridge-b"]
        for row in pairs["rows"]: _review(row)
    with pytest.raises(ValueError, match="crosses train/validation"):
        _export(tmp_path, checkpoints, modify=modify)
    assert not (tmp_path / "export").exists()


@pytest.mark.parametrize("kind", ["vector", "source", "normalized_source", "source_record", "source_record_revision"])
def test_identical_inputs_cannot_cross_split_even_with_different_declared_families(kind, checkpoints, tmp_path):
    def modify(pairs, embeddings):
        train, valid = pairs["rows"][0], pairs["rows"][6]
        if kind == "vector":
            embeddings["rows"][6]["embedding"] = deepcopy(embeddings["rows"][0]["embedding"])
            embeddings["rows"][6]["embedding_sha256"] = embeddings["rows"][0]["embedding_sha256"]
        elif kind in ("source_record", "source_record_revision"):
            for key in ("source_uri", "source_revision", "record_id"):
                valid["source_identity"][key] = train["source_identity"][key]
            if kind == "source_record_revision":
                # Snapshot and family labels may differ, but the same source
                # record still cannot straddle fitting and evaluation.
                valid["source_identity"]["source_revision"] = "d" * 40
        else:
            valid["source_text"] = train["source_text"] if kind == "source" else train["source_text"].upper() + "  "
            embeddings["rows"][6]["source_sha256"] = _sha(valid["source_text"])
        _review(valid)
    with pytest.raises(ValueError, match="crosses train/validation"):
        _export(tmp_path, checkpoints, modify=modify)


def test_duplicate_vector_conflicting_targets_rejected_within_one_split(checkpoints, tmp_path):
    def modify(pairs, embeddings):
        embeddings["rows"][2]["embedding"] = deepcopy(embeddings["rows"][0]["embedding"])
        embeddings["rows"][2]["embedding_sha256"] = embeddings["rows"][0]["embedding_sha256"]
    with pytest.raises(ValueError, match="conflicting targets"):
        _export(tmp_path, checkpoints, modify=modify)


def test_component_groups_are_stable_under_manifest_row_order(checkpoints, tmp_path):
    original, *_ = _export(tmp_path / "a", checkpoints)
    def modify(pairs, embeddings):
        pairs["rows"].reverse()
        embeddings["rows"].reverse()
    reversed_, *_ = _export(tmp_path / "b", checkpoints, modify=modify)
    for key in ("training_path", "validation_path"):
        assert c.read_json(original[key]) == c.read_json(reversed_[key])


def test_test_split_and_missing_group_declarations_cannot_silently_be_reassigned(checkpoints, tmp_path):
    def modify(pairs, embeddings):
        pairs["rows"][0]["split"] = "test"
    with pytest.raises(ValueError, match="explicit train/validation"):
        _export(tmp_path, checkpoints, modify=modify)


def test_path_aliases_rejected(checkpoints, tmp_path):
    result, pairs, embeddings, base = _export(tmp_path, checkpoints)
    alias = tmp_path / "alias.json"
    alias.symlink_to(pairs)
    with pytest.raises(ValueError, match="aliased"):
        subject.export_reviewed_pairs("intent_ir", alias, embeddings, tmp_path / "second", base_path=base)


def test_ambiguous_parent_embedding_pipeline_is_rejected(checkpoints, tmp_path):
    checkpoint = deepcopy(checkpoints["intent_ir"])
    checkpoint["config"]["embedding_provenance"] = dict(model_id="caller_supplied", verified_by_runtime=False)
    altered = dict(checkpoints, intent_ir=checkpoint)
    with pytest.raises(ValueError, match="dimension 384"):
        _export(tmp_path, altered)
