"""Receipt integrity tests; synthetic native declarations are not model inference."""

import hashlib
import json
from pathlib import Path
import struct

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_feature_inputs as verifier
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import SourceArtifact, SourceSpan


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode()


def reference(path):
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def write_json(path, value):
    path.write_bytes(canonical(value))
    return reference(path)


def fixture(tmp_path, *, legacy=False, injected=False, oversized=False, texts=None, documents=None):
    """Build codec-valid declared native metadata, never claim actual inference."""
    entries, paths = [], {}
    for index in range(4 if oversized else 3):
        text = texts[index] if texts else f"The agency shall retain record {index}."
        path = tmp_path / f"source-{index}.txt"
        path.write_text(text)
        artifact = SourceArtifact(reference(path)["sha256"], path.stat().st_size)
        span = SourceSpan(artifact, "us_code", "test-release",
                          documents[index] if documents else f"document-{index}", "en", f"5 USC {index}",
                          0, len(text.encode()))
        entries.append(codec.EmbeddingInput(span, "5", str(index), text, span.citation))
        paths[artifact.sha256] = path
    vector = [1.0, -0.0] + [0.0] * 382
    results = [{"input_id": item.input_id, "status": "embedded",
                "tokens": {"input_ids": [101, 2000, 102], "attention_mask": [1, 1, 1], "token_type_ids": [0, 0, 0]},
                "vector": vector} for item in entries]
    if oversized:
        tokens = {"input_ids": [101] * 513, "attention_mask": [1] * 513, "token_type_ids": None}
        results[-1].update(status="token_limit_exceeded", tokens=codec.token_input_digest(tokens), vector=None)
    assets = [{"name": name, "sha256": hashlib.sha256(name.encode()).hexdigest(), "bytes": 1}
              for name in sorted(("config.json", "tokenizer.json", "tokenizer_config.json", "vocab.txt",
                                  "special_tokens_map.json", "modules.json", "sentence_bert_config.json",
                                  "1_Pooling/config.json", "model.safetensors"))]
    receipt = codec.build_embedding_production_receipt(entries, results=results,
        execution={**codec.native_execution_profile(), "kind": "injected_fixture"}, model_assets=assets,
        producer={"code_sha256": "a" * 64,
                  "runtime_versions": {name: "fixture" for name in ("python", "torch", "transformers", "sentence_transformers", "tokenizers")}},
        resolver=lambda ref: paths[ref["sha256"]])
    production = receipt.to_dict()
    if not injected:
        production["execution"]["kind"] = "native"
    receipt_ref = write_json(tmp_path / "production.json", production)
    samples = [{key: getattr(item, key) for key in ("title", "section", "text", "citation")}
               | {"embedding_model": codec.MODEL_ID, "embedding_vector": vector} for item in entries]
    artifacts = {}
    for role, index in (("training", 0), ("validation", 1)):
        path = tmp_path / f"{role}.jsonl"
        path.write_bytes(canonical(samples[index]) + b"\n")
        artifacts[role] = {"rows": reference(path), "count": 1, "input_ids": [entries[index].input_id]}
    split = {"schema": verifier.INPUT_SCHEMA, "model": production["model"],
             "embedding_production_receipt": receipt_ref,
             "source_artifacts": [reference(path) for path in paths.values()], "artifacts": artifacts}
    if legacy:
        artifacts["tuning"] = artifacts.pop("validation")
        original = {"schema": "parallel-training-diagnostic-split/v1", "training_eligible": False,
                    "global_holdout_verified": False, "identities": {}, "artifacts": {}}
        split.update(schema=verifier.DIAGNOSTIC_SCHEMA, statuses=[], coverage={})
        for role, indices in (("training", [0, 3] if oversized else [0]), ("tuning", [1]), ("canary", [2])):
            identities = []
            for ordinal, index in enumerate(indices):
                item, result = entries[index], production["results"][index]
                identity = {"input_id": item.input_id, "group_id": f"group-{index}",
                            "legal_id": item.source.document_id, "source_row_id": f"row-{index}",
                            "text_sha256": hashlib.sha256(item.text.encode()).hexdigest()}
                identities.append(identity)
                status = {**identity, "role": role, "ordinal": ordinal, "status": result["status"],
                          "upstream_input_id": item.input_id, "original_selection_preserved": True,
                          "source_text_artifact": reference(paths[item.source.artifact.sha256])}
                if result["status"] == "embedded":
                    status["tokens"] = len(result["tokens"]["input_ids"])
                else:
                    status.update(token_evidence=result["tokens"], vector_absent=True)
                split["statuses"].append(status)
            original["identities"][role] = identities
            path = tmp_path / f"original-{role}.jsonl"
            if role == "canary":
                # Deliberately absent: neither these rows nor the source file is
                # necessary for training/tuning verification.
                original["artifacts"][role] = {"rows": {"path": str(path), "sha256": "f" * 64, "bytes": 99}}
                artifacts[role] = original["artifacts"][role]
            else:
                path.write_bytes(b"\n".join(canonical(samples[index]) for index in indices) + b"\n")
                original["artifacts"][role] = {"rows": reference(path)}
                artifacts[role]["original_count"] = len(indices)
                split["coverage"][role] = {"original_count": len(indices), "embedded_count": 1, "abstention_count": len(indices) - 1}
        split["original_diagnostic_split"] = write_json(tmp_path / "original.json", original)
    (tmp_path / "source-2.txt").unlink()
    manifest = tmp_path / "inputs.json"
    write_json(manifest, split)
    return manifest, split, entries


def verify(manifest, split):
    validation = "tuning" if split["schema"] == verifier.DIAGNOSTIC_SCHEMA else "validation"
    return verifier.verify_feature_training_inputs(manifest, split["artifacts"]["training"]["rows"]["path"],
                                                    split["artifacts"][validation]["rows"]["path"])


@pytest.mark.parametrize("legacy", [False, True])
def test_actual_loader_checks_selected_sources_without_canary_conversion(tmp_path, monkeypatch, legacy):
    manifest, split, _ = fixture(tmp_path, legacy=legacy)
    called = []
    loader = verifier.load_embedding_production_receipt
    def observed_loader(*args, **kwargs):
        called.append(kwargs)
        assert "resolver" not in kwargs
        return loader(*args, **kwargs)
    monkeypatch.setattr(verifier, "load_embedding_production_receipt", observed_loader)
    def forbidden(*args, **kwargs):
        pytest.fail("complete corpus conversion would process canaries")
    monkeypatch.setattr(codec.EmbeddingProductionReceipt, "to_corpus_records", forbidden)
    monkeypatch.setattr(codec.EmbeddingProductionReceipt, "validate_sources", forbidden)
    actual = verify(manifest, split)
    assert len(called) == 1
    assert actual["training"]["count"] == actual["validation"]["count"] == 1
    assert actual["local_embedding_verification"] is True
    assert actual["source_selectors_verified"] == 2
    assert len(actual["source_artifacts"]) == 2
    assert actual["manifest"] == reference(manifest)
    assert actual["embedding_production_receipt"] == split["embedding_production_receipt"]
    assert actual["embedding_receipt_verification"]["runtime_cryptographically_attested"] is False
    for key in ("admitted", "formalized", "global_holdout_verified", "corpus_training_eligible", "canary_rows_read", "canary_evaluated"):
        assert actual[key] is False


def test_oversized_training_selection_remains_explicit_abstention(tmp_path):
    manifest, split, _ = fixture(tmp_path, legacy=True, oversized=True)
    assert verify(manifest, split)["training"]["count"] == 1
    split["statuses"][-1]["role"] = "training"
    write_json(manifest, split)
    with pytest.raises(verifier.FeatureInputError):
        verify(manifest, split)


@pytest.mark.parametrize("mutation", ["text", "model", "vector", "signed_zero", "dimension", "nonfinite", "float64", "integer"])
def test_same_hash_updated_ref_cannot_substitute_sample_evidence(tmp_path, mutation):
    manifest, split, _ = fixture(tmp_path)
    path = Path(split["artifacts"]["training"]["rows"]["path"])
    row = json.loads(path.read_text())
    if mutation == "text":
        row["text"] += " Altered."
    elif mutation == "model":
        row["embedding_model"] = "deterministic-test-vectors"
    elif mutation == "vector":
        row["embedding_vector"][0] = 0.5
    elif mutation == "signed_zero":
        row["embedding_vector"][1] = 0.0
    elif mutation == "dimension":
        row["embedding_vector"].pop()
    elif mutation == "float64":
        row["embedding_vector"][0] = 0.1
    elif mutation == "integer":
        row["embedding_vector"][0] = 1
    else:
        row["embedding_vector"][0] = float("nan")
    path.write_text(json.dumps(row) + "\n")
    split["artifacts"]["training"]["rows"] = reference(path)
    write_json(manifest, split)
    with pytest.raises(verifier.FeatureInputError):
        verify(manifest, split)


@pytest.mark.parametrize("target", ["rows", "receipt", "source"])
def test_byte_tampering_is_rejected(tmp_path, target):
    manifest, split, _ = fixture(tmp_path)
    path = {"rows": Path(split["artifacts"]["training"]["rows"]["path"]),
            "receipt": Path(split["embedding_production_receipt"]["path"]),
            "source": tmp_path / "source-0.txt"}[target]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(verifier.FeatureInputError):
        verify(manifest, split)


def test_injected_profile_and_model_declaration_cannot_qualify(tmp_path):
    manifest, split, _ = fixture(tmp_path, injected=True)
    with pytest.raises(verifier.FeatureInputError, match="native"):
        verify(manifest, split)
    production_path = Path(split["embedding_production_receipt"]["path"])
    production = json.loads(production_path.read_text())
    production["execution"]["kind"] = "native"
    split["embedding_production_receipt"] = write_json(production_path, production)
    split["model"]["dimension"] = 8
    write_json(manifest, split)
    with pytest.raises(verifier.FeatureInputError, match="model"):
        verify(manifest, split)


def test_role_reassignment_and_duplicate_membership_are_rejected(tmp_path):
    manifest, split, entries = fixture(tmp_path)
    split["artifacts"]["validation"]["input_ids"] = [entries[0].input_id]
    write_json(manifest, split)
    with pytest.raises(verifier.FeatureInputError, match="disjoint"):
        verify(manifest, split)


@pytest.mark.parametrize("kind", ["document", "text"])
def test_cross_role_document_or_normalized_content_overlap_is_rejected(tmp_path, kind):
    kwargs = {"documents": ["shared", "shared", "canary"]} if kind == "document" else {"texts": ["The agency shall retain records.", "THE AGENCY  SHALL RETAIN RECORDS.", "Canary only."]}
    manifest, split, _ = fixture(tmp_path, **kwargs)
    with pytest.raises(verifier.FeatureInputError, match="share document or normalized text"):
        verify(manifest, split)


def test_diagnostic_status_order_and_native_token_evidence_are_bound(tmp_path):
    manifest, split, _ = fixture(tmp_path, legacy=True)
    split["statuses"][0]["tokens"] += 1
    write_json(manifest, split)
    with pytest.raises(verifier.FeatureInputError, match="token evidence"):
        verify(manifest, split)


def test_wrong_supplied_path_and_duplicate_json_keys_are_rejected(tmp_path):
    manifest, split, _ = fixture(tmp_path)
    training = Path(split["artifacts"]["training"]["rows"]["path"])
    copied = tmp_path / "copy.jsonl"
    copied.write_bytes(training.read_bytes())
    with pytest.raises(verifier.FeatureInputError, match="supplied input path"):
        verifier.verify_feature_training_inputs(manifest, copied, split["artifacts"]["validation"]["rows"]["path"])
    manifest.write_text('{"schema":"x","schema":"y"}')
    with pytest.raises(verifier.FeatureInputError, match="strict feature input JSON"):
        verify(manifest, split)


def test_vector_binding_is_dimension_generic_and_preserves_signed_zero():
    values = [0.25, -0.0, 1.0, -1.0, 0.0]
    assert verifier._vector_bits(values, 5) == struct.pack(">5f", *values).hex()
    for vector, dimension in ((values, True), (values, 384), ([float("inf")], 1), ([True], 1)):
        with pytest.raises(verifier.FeatureInputError):
            verifier._vector_bits(vector, dimension)
