"""Guarded source-only normalization never repairs learned predictions."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.security import source_normalization_384 as normalizer
from ipfs_datasets_py.logic.formalization.autoencoder import normalized_source_program_runtime_384 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import source_program_runtime_384 as raw_consumer
from ipfs_datasets_py.logic.software_verification.program import ProgramExpression

PIN = "a" * 64


def source(operator="+", *, temporary=False, function="assess"):
    annotation = "int" if operator in ("+", "-", "*") else "bool"
    header = f"def {function}(left: int, right: int) -> {annotation}:\n"
    return header + (f"\tcomputed = ( left {operator} right )\n\t# Preserve the value.\n\treturn computed\n"
        if temporary else f"    return left {operator} right\n")


def candidate(operator="+"):
    refs = ("expr:left", "expr:right")
    return dict(kind="program_expression", document=ProgramExpression("expr:result", "binary",
        "integer" if operator in ("+", "-", "*") else "boolean", operator=operator,
        operand_ids=refs, evaluation_order=refs, source_ref_ids=("source",)).to_dict())


@pytest.mark.parametrize("operator", ["+", "-", "*", "<", "<=", ">", ">=", "==", "!="])
@pytest.mark.parametrize("temporary", [False, True])
def test_source_signature_and_original_hash_preserved_under_guarded_normalization(operator, temporary):
    text = source(operator, temporary=temporary)
    report = normalizer.normalize_source(text)
    assert report["status"] == "normalized" and report["signature_preserved"] is True
    assert report["normalized_source_text"] == source(operator)
    assert report["source_signature"]["operator"] == operator
    assert report["source_signature"]["ordered_operands"] == ["left", "right"]
    assert report["original_source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert report["normalized_source_sha256"] == hashlib.sha256(source(operator).encode()).hexdigest()
    assert report["temporary_eliminated"] is temporary
    assert report["normalization_applied"] is temporary
    assert all(report[key] is False for key in normalizer.FALSE)


def test_normalization_preserves_operand_order_and_absent_return_annotation():
    text = "def compare(left: int, right: int):\n    interim = right < left\n    return interim\n"
    report = normalizer.normalize_source(text)
    assert report["normalized_source_text"] == "def compare(left: int, right: int):\n    return right < left\n"
    assert report["source_signature"]["ordered_operands"] == ["right", "left"]
    assert report["source_signature"]["parameters"] == [dict(name="left", annotation="int"), dict(name="right", annotation="int")]
    assert report["source_signature"]["return_annotation"] is None


@pytest.mark.parametrize("text", [
    "def calculate(left, right):\n    return left + right\n",
    "def calculate(left: int, right: int) -> int:\n    return left // right\n",
    "def calculate(left: int, right: int) -> int:\n    return left + 1\n",
    "def calculate(left: int, right: int) -> int:\n    return helper(left, right)\n",
    "def calculate(left: int, right: int) -> int:\n    left = left + right\n    return left\n",
    "def calculate(left: int, right: int) -> int:\n    temp = left + right\n    return right\n",
    "def calculate(left: int, right: int) -> int:\n    return left < right\n",
    "def broken syntax",
    "import os\nos.system('this source must never execute')\n",
])
def test_unsupported_sources_remain_exactly_unchanged(text):
    report = normalizer.normalize_source(text)
    assert report["status"] == "unsupported" and report["reason"]
    assert report["normalized_source_text"] == text
    assert report["original_source_sha256"] == report["normalized_source_sha256"]
    assert report["normalization_applied"] is False and report["signature_preserved"] is False
    assert report["source_signature"] is None
    assert all(report[key] is False for key in normalizer.FALSE)


def underlying(operator="+", calls=None):
    def infer(rows, **options):
        if calls is not None:
            calls.append((deepcopy(rows), options))
        return dict(domain_id="security_ir", rows=[dict(id=row["id"],
            source_sha256=hashlib.sha256(row["source_text"].encode()).hexdigest(), candidate_ir=candidate(operator),
            status="unqualified_candidate") for row in rows])
    return raw_consumer.SourceProgramDecoder384(SimpleNamespace(infer=infer,
        describe=lambda: {"domain_id": "security_ir"}), checkpoint_sha256=PIN)


def test_hybrid_deduplicates_views_but_sends_original_text_and_only_vectors_to_decoder(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_384
    texts = [source(), source(temporary=True), source().replace("return left + right", "return (\n        left + right\n    )")]
    embedded, calls = [], []
    def embed(views, **options):
        embedded.append((views, options))
        return [[.25] * 384]
    monkeypatch.setattr(source_embeddings_384, "embed_texts", embed)
    decoder = subject.NormalizedSourceProgramDecoder384(underlying(calls=calls))
    result = decoder.infer_texts(texts, snapshot_path="pinned-snapshot", weight_ablation="zero_head")
    assert embedded == [([source()], {"snapshot_path": "pinned-snapshot"})]
    assert calls == [([dict(id="input-" + str(i), source_text=text, embedding=[.25] * 384)
        for i, text in enumerate(texts)], {"weight_ablation": "zero_head"})]
    assert result["unique_embedding_views"] == 1 and result["embedding_views_reused"] == 2
    assert result["input_count"] == 3 and result["original_sources_used_for_qualification"] is True
    assert result["raw_decoder_quality_metric"] is False
    for row, text in zip(result["rows"], texts):
        assert row["source_contract"]["status"] == "qualified"
        assert row["source_contract"]["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
        assert row["source_normalization"]["normalized_source_text"] == source()
        assert row["candidate_ir"] == candidate()
        assert all(row[key] is False for key in raw_consumer.FALSE)
    for view in (decoder.describe(), result):
        assert view["input_view"] == "guarded_ast_normalized"
        assert view["hybrid_profile"] == "guarded-source-normalization-384/v1"
        assert view["target_dependent_normalization"] is False and view["prediction_repair_performed"] is False


def test_wrong_model_prediction_is_not_repaired_from_normalizer_ast(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_384
    monkeypatch.setattr(source_embeddings_384, "embed_texts", lambda *a, **k: [[.25] * 384])
    decoder = subject.NormalizedSourceProgramDecoder384(underlying(operator="-"))
    report = decoder.infer_texts([source("+", temporary=True)])
    row = report["rows"][0]
    assert row["source_normalization"]["source_signature"]["operator"] == "+"
    assert row["candidate_ir"] == candidate("-")
    assert row["source_contract"]["status"] == "mismatch"
    assert row["status"] == "fail_open_source_contract_mismatch" and row["continue_planning"] is True


def test_unsupported_input_is_embedded_unchanged_and_remains_fail_open(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_384
    text = source().replace(": int", "")
    calls = []
    monkeypatch.setattr(source_embeddings_384, "embed_texts", lambda views, **kwargs: calls.append(views) or [[.1] * 384])
    result = subject.NormalizedSourceProgramDecoder384(underlying()).infer_texts([text])
    assert calls == [[text]]
    row = result["rows"][0]
    assert row["source_normalization"]["status"] == "unsupported"
    assert row["source_normalization"]["normalized_source_text"] == text
    assert row["source_contract"]["status"] == "unsupported" and row["continue_planning"] is True
    assert row["candidate_ir"] == candidate()


@pytest.mark.parametrize("decoder", ["structured", "sequence_v2"])
def test_loader_preserves_exact_checkpoint_pin_and_decoder_choice(monkeypatch, decoder):
    calls = []
    inner = underlying()
    def load(path, **options):
        calls.append((path, options)); return inner
    monkeypatch.setattr(raw_consumer, "load_source_program_decoder_384", load)
    result = subject.load_normalized_source_program_decoder_384("checkpoint.json", expected_sha256=PIN, decoder=decoder)
    assert result.decoder is inner
    assert calls == [("checkpoint.json", dict(expected_sha256=PIN, decoder=decoder))]


@pytest.mark.parametrize("texts", [[], [""], [" "], [None], "source", ["x"] * 129])
def test_invalid_text_inputs_fail_before_embedding(monkeypatch, texts):
    from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_384
    monkeypatch.setattr(source_embeddings_384, "embed_texts", lambda *a, **k: pytest.fail("invalid input embedded"))
    with pytest.raises(ValueError, match="bounded nonempty"):
        subject.NormalizedSourceProgramDecoder384(underlying()).infer_texts(texts)


def test_real_learned_head_still_controls_hybrid_output_and_zero_head_rejects_mismatch(monkeypatch, tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("numpy")
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as structured
    from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_384
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as legal
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        binding = dict(domain="legal_ir", lineage_id="current_legal_v2", dimension=384,
            runtime_profile="hybrid-source-unit-test/v1", core_sha256="a" * 64)
        examples = [dict(id="parent", source_text="The agency must save the report.", latent=[.5] + [0.] * 383,
            embedding=[.3] + [0.] * 383, canonical_ir={"rules": [dict(modality="O", actor="agency", action="save",
                object="report", conditions=[], exceptions=[], temporal=[])]})]
        parent = legal.build_checkpoint(binding, examples, [], hidden_size=16, token_embedding_dim=8,
            projection_width=4, batch_size=1)
        parent = legal.train(parent, examples, [], epochs=1, max_seconds=30)["checkpoint"]
        def rows(split):
            return [dict(id=f"{split}-{index}", source_text=source(operator, function=split + str(index)),
                embedding=[-1. if operator == "+" else 1., .001 if split == "train" else .002] + [0.] * 382,
                target=candidate(operator)) for index, operator in enumerate(("+", "-"))]
        fitted = structured.train("security_ir", rows("train"), rows("validation"), parent_projection=parent)
    finally:
        torch.set_num_threads(previous)
    path = tmp_path / "checkpoint.json"
    raw = structured._raw(fitted["checkpoint"])
    path.write_bytes(raw)
    loaded = subject.load_normalized_source_program_decoder_384(path, expected_sha256=hashlib.sha256(raw).hexdigest())
    # Synthetic embeddings isolate the numerical consumer contract; real GTE
    # source quality is measured by the separate frozen checkpoint diagnostic.
    monkeypatch.setattr(source_embeddings_384, "embed_texts", lambda texts, **options: [
        [-1. if "left + right" in text else 1., .003] + [0.] * 382 for text in texts])
    text = source("-", temporary=True)
    baseline = loaded.infer_texts([text])
    zeroed = loaded.infer_texts([text], weight_ablation="zero_head")
    assert baseline["rows"][0]["candidate_ir"] == candidate("-")
    assert baseline["rows"][0]["source_contract"]["status"] == "qualified"
    assert zeroed["rows"][0]["candidate_ir"] == candidate("+")
    assert zeroed["rows"][0]["source_contract"]["status"] == "mismatch"
    assert zeroed["rows"][0]["prediction_repair_performed"] is False
    assert loaded.infer_texts([text]) == baseline
