"""Evaluation must preserve free generation and keep reference targets isolated."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("legal_architecture_comparison", ROOT / "scripts/ops/legal_ir/compare_legal_decoder_architectures.py")
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


def rule(**changes):
    return {"rules": [{"modality": "O", "actor": "agency", "action": "disclose",
                       "object": "records", "conditions": [], "exceptions": [],
                       "temporal": [], **changes}]}


def inputs(count=3):
    return [{"id": str(i), "source_text": f"Authored input {i}.",
             "latent": [float(i), 1.], "raw_latent": [float(i), 2., 3.],
             "canonical_ir": rule(object=f"target-secret-{i}"),
             "family_group": "minimal-pair"} for i in range(count)]


class Recorder:
    def __init__(self):
        self.calls = []

    def decode_formal_logic(self, texts, *args, **kwargs):
        self.calls.append((copy.deepcopy(texts), copy.deepcopy(args), copy.deepcopy(kwargs)))
        return {"rows": [], "target_access": False, "teacher_forcing": False}

    def infer(self, rows):
        self.calls.append(copy.deepcopy(rows))
        return {"rows": [], "target_access": False, "teacher_forcing": False}


@pytest.mark.parametrize("kind", ["source", "latent", "hybrid"])
def test_generation_filters_reference_targets_at_every_inference_boundary(kind):
    rows = inputs()
    untouched = copy.deepcopy(rows)
    decoder = Recorder()
    generated = comparison.generate(kind, decoder, rows)
    assert rows == untouched
    assert not generated["generation_inputs_contained_references"]
    if kind == "latent":
        assert all(set(row) == {"id", "source_text", "latent"} for row in decoder.calls[0])
        assert [row["latent"] for row in decoder.calls[0]] == [row["raw_latent"] for row in rows]
    else:
        texts, args, kwargs = decoder.calls[0]
        assert texts == [row["source_text"] for row in rows]
        if kind == "source":
            assert args == () and kwargs == {}
        else:
            assert args == ([row["latent"] for row in rows],)
    assert "target-secret" not in repr(decoder.calls)


@pytest.mark.parametrize("kind", ["latent", "hybrid"])
@pytest.mark.parametrize("control", ["rotated_latent", "zero_latent"])
def test_controls_change_only_vectors_and_keep_source_order(kind, control):
    rows = inputs()
    untouched = copy.deepcopy(rows)
    decoder = Recorder()
    comparison.generate(kind, decoder, rows, control)
    assert rows == untouched
    if kind == "latent":
        texts = [row["source_text"] for row in decoder.calls[0]]
        vectors = [row["latent"] for row in decoder.calls[0]]
        expected = [row["raw_latent"] for row in rows]
    else:
        texts, args, kwargs = decoder.calls[0]
        vectors = args[0]
        expected = [row["latent"] for row in rows]
    assert texts == [row["source_text"] for row in rows]
    assert vectors == (expected[1:] + expected[:1] if control == "rotated_latent"
                       else [[0.] * len(vector) for vector in expected])


def test_disabled_fusion_is_explicit_and_batch_rotation_is_global():
    decoder = Recorder()
    rows = inputs(130)
    comparison.generate("hybrid", decoder, rows, "disabled_latent")
    assert [len(call[0]) for call in decoder.calls] == [128, 2]
    assert all(call[2] == {"latent_ablation": "disabled"} for call in decoder.calls)
    decoder = Recorder()
    comparison.generate("hybrid", decoder, rows, "rotated_latent")
    assert decoder.calls[0][1][0][-1] == rows[128]["latent"]
    assert decoder.calls[1][1][0][-1] == rows[0]["latent"]


def predictions(rows):
    return [{"status": "decoded", "canonical_ir": rule(), "target_access": False,
             "teacher_forcing": False,
             "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest()}
            for row in rows]


def test_score_counts_qualifier_omission_as_error_and_keeps_abstention_in_denominator():
    rows = inputs()
    refs = [{"id": row["id"], "canonical_ir": rule()} for row in rows]
    refs[1]["canonical_ir"] = rule(exceptions=["emergency"])
    preds = predictions(rows)
    preds[2].update(status="abstained", canonical_ir=None, reason="unknown source token")
    result = comparison.score(preds, rows, refs)
    assert result["count"] == 3 and result["exact"] == 1
    assert result["decoded"] == 2 and result["abstained"] == 1
    assert result["exact_fraction"] == 1 / 3
    assert result["facets"]["exceptions"] == 1
    assert result["facets"]["modality"] == 2
    assert result["rows"][1]["facets"]["exceptions"] is False


@pytest.mark.parametrize("flag", ["target_access", "teacher_forcing"])
def test_score_rejects_teacher_forced_or_target_accessed_predictions(flag):
    rows = inputs(1)
    preds = predictions(rows)
    preds[0][flag] = True
    with pytest.raises(ValueError, match="free generation"):
        comparison.score(preds, rows, [{"id": "0", "canonical_ir": rule()}])


def test_score_rejects_source_drift_missing_rows_and_fake_abstention():
    rows = inputs(1)
    refs = [{"id": "0", "canonical_ir": rule()}]
    preds = predictions(rows)
    preds[0]["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="source differs"):
        comparison.score(preds, rows, refs)
    with pytest.raises(ValueError, match="coverage"):
        comparison.score([], rows, refs)
    preds = predictions(rows)
    preds[0]["status"] = "abstained"
    with pytest.raises(ValueError, match="abstention"):
        comparison.score(preds, rows, refs)


def test_generation_rejects_backend_target_access():
    class BadDecoder:
        def decode_formal_logic(self, texts):
            return {"rows": [], "target_access": True, "teacher_forcing": False}
    with pytest.raises(ValueError, match="target access"):
        comparison.generate("source", BadDecoder(), inputs(1))


validator_spec = importlib.util.spec_from_file_location("comparison_input_validator",
    ROOT / "scripts/ops/legal_ir/validate_legal_decoder_comparison_inputs.py")
validator = importlib.util.module_from_spec(validator_spec)
validator_spec.loader.exec_module(validator)


def validation_case(tmp_path, monkeypatch):
    """A diagnostic receipt stub isolates the runner's binding checks."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as receipt_module
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec
    fixture = json.loads((ROOT / "tests/fixtures/legal_formula_learning/v1.json").read_text())
    train = fixture["train"]
    frozen_codec = legal_formula_codec.fit_codec(train)
    challenge = {"id": "new-challenge", "source_text": "The agency shall disclose the file.",
                 "canonical_ir": rule(object="the file"), "family_group": "new-family", "actor_action_group": "new-group"}
    rows = train + [challenge]
    plan_rows, bindings, receipt_inputs, receipt_results, source_paths = [], [], [], [], {}
    splits = {key: [] for key in ("train", "tuning", "heldout", "regression", "development", "challenge", "oov")}
    def saved(name, payload, *, raw=False):
        content = payload if raw else json.dumps(payload, sort_keys=True).encode()
        path = tmp_path / name
        path.write_bytes(content)
        return {"path": str(path), "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
    receipt_ref = saved("receipt.json", b"diagnostic receipt stub", raw=True)
    for i, row in enumerate(rows):
        row = copy.deepcopy(row)
        split = "challenge" if i == len(train) else "train"
        digest = hashlib.sha256(row["source_text"].encode()).hexdigest()
        row.update(source_sha256=digest, canonical_target_sha256=validator.canonical_digest(row["canonical_ir"]),
                   embedding=[0.] * 384)
        source_path = tmp_path / (str(i) + ".txt")
        source_path.write_text(row["source_text"])
        source_paths[digest] = str(source_path)
        plan_rows.append({"id": row["id"], "split": split, "source_sha256": digest,
                          "canonical_target_sha256": row["canonical_target_sha256"]})
        if split == "challenge":
            del row["canonical_ir"]
        splits[split].append(row)
        bindings.append({"id": row["id"], "split": split, "input_id": str(i),
                         "receipt_sha256": receipt_ref["sha256"], "source_sha256": digest})
        receipt_inputs.append({"input_id": str(i), "text": row["source_text"],
            "source": {"artifact": {"sha256": digest, "bytes": len(row["source_text"].encode())}}})
        receipt_results.append({"input_id": str(i), "status": "embedded",
                               "vector": {"bits": struct.pack(">384f", *row["embedding"]).hex()}})
    plan_ref = saved("plan.json", {"schema": "legal-decoder-comparison-frozen-plan/v1",
        "split_counts": {key: len(value) for key, value in splits.items()}, "rows": plan_rows,
        "leakage_checks": {"frozen_codec_sha256": validator.canonical_digest(frozen_codec)}})
    # This content would fail JSON parsing, proving pre-training verification
    # only hashes the sealed file. Actual target validation happens post-freeze.
    sealed_ref = saved("sealed.json", b"opaque sealed content intentionally not JSON", raw=True)
    data = {"execution": {"kind": "native"}, "model": {"dimension": 384}, "model_assets": [],
            "inputs": receipt_inputs, "results": receipt_results}
    class Receipt:
        def to_dict(self):
            return data
    def loader(path, *, expected_sha256, expected_size_bytes, resolver):
        for item in receipt_inputs:
            resolver(item["source"]["artifact"])
        return Receipt()
    monkeypatch.setattr(receipt_module, "load_embedding_production_receipt", loader)
    corpus = {"schema": "legal-decoder-comparison-corpus/v1",
        "label_origin": "authored_synthetic_not_legal_authority", "independently_reviewed": False,
        "frozen_plan": plan_ref, "sealed_targets": sealed_ref, "splits": splits,
        "source_bindings": saved("bindings.json", bindings), "source_paths": source_paths,
        "embedding_receipts": [receipt_ref], "model": data["model"], "model_assets": data["model_assets"]}
    return corpus, sealed_ref["path"], data


def test_input_validator_checks_native_bindings_without_parsing_sealed_targets(tmp_path, monkeypatch):
    corpus, sealed, _ = validation_case(tmp_path, monkeypatch)
    result = validator.validate_inputs(corpus, sealed)
    assert result["rows_verified"] == 73
    assert result["sealed_targets_parsed"] is False
    assert result["source_vector_binding_verified"] is True


@pytest.mark.parametrize("mutation,reason", [
    ("source", "source content"), ("target", "canonical target"),
    ("negative_zero", "float32 bits"), ("nonfinite", "finite numbers"),
    ("reference_leak", "contains reference"), ("native", "not native"),
    ("vector_binding", "source binding"),
])
def test_input_validator_rejects_tampering(tmp_path, monkeypatch, mutation, reason):
    corpus, sealed, receipt = validation_case(tmp_path, monkeypatch)
    row = corpus["splits"]["train"][0]
    if mutation == "source":
        row["source_text"] += " altered"
    elif mutation == "target":
        row["canonical_ir"]["rules"][0]["modality"] = "P"
    elif mutation == "negative_zero":
        row["embedding"][0] = -0.0
    elif mutation == "nonfinite":
        row["embedding"][0] = float("nan")
    elif mutation == "reference_leak":
        corpus["splits"]["challenge"][0]["canonical_ir"] = rule()
    elif mutation == "native":
        receipt["execution"]["kind"] = "injected_fixture"
    elif mutation == "vector_binding":
        receipt["inputs"][0]["text"] = "Different source text"
    with pytest.raises(ValueError, match=reason):
        validator.validate_inputs(corpus, sealed)


@pytest.mark.parametrize("artifact", ["frozen_plan", "sealed_targets"])
def test_input_validator_rejects_mutated_plan_or_sealed_bytes(tmp_path, monkeypatch, artifact):
    corpus, sealed, _ = validation_case(tmp_path, monkeypatch)
    Path(corpus[artifact]["path"]).write_text("tampered")
    with pytest.raises(ValueError, match="differ"):
        validator.validate_inputs(corpus, sealed)
