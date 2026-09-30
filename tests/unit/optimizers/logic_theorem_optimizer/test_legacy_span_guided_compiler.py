"""Guided compiler capture preserves provenance and never claims independence."""
import copy
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_guided_compiler as module


@pytest.fixture
def setup(monkeypatch):
    formula = {"formula_id": "formula-1", "operator": {"family": "deontic", "symbol": "O"},
        "predicate": {"name": "retain", "arguments": ["officer", "file"]},
        "conditions": ["for at least 20 days"], "exceptions": ["emergency"],
        "provenance": {"source_id": "s", "start_char": 0, "end_char": 52},
        "metadata": {"temporal_kind": "minimum_duration", "quantity": 20}}
    direct = {"version": "modal-ir-v1", "formulas": [formula], "frame_logic": {"triples": []}}
    guided = copy.deepcopy(direct)
    parsed = copy.deepcopy(direct)
    parsed["formulas"][0]["formula_id"] = "parser-only-formula-1"
    guidance = {"sample_id": "s", "sample_memory_used": False,
        "legal_ir_target_view_distribution": {"deontic": 1.0},
        "legal_ir_predicted_view_distribution": {"deontic": 0.8},
        "ranked_guidance_features": [{"feature": "temporal:minimum_duration", "weight": 0.1}]}
    calls = {"guidance": [], "codec_init": 0, "compile": []}
    class Model:
        def compiler_guidance_for_sample(self, sample, **kwargs):
            calls["guidance"].append((sample, kwargs))
            return guidance
    class Codec:
        def encode(self, text, **kwargs):
            calls["compile"].append((text, kwargs))
            document = direct if kwargs["compiler_guidance"] is None else guided
            return SimpleNamespace(modal_ir=SimpleNamespace(to_dict=lambda: document),
                                   decoded_text="The officer must retain the file for at least 20 days.")
    def factory():
        calls["codec_init"] += 1
        return Codec()
    monkeypatch.setattr(module, "_codec", factory)
    sample = SimpleNamespace(sample_id="s", text="The officer shall retain the file for at least 20 days.",
        citation="5 USC 1", source="us_code", embedding_vector=[0.1] * 8,
        modal_ir=SimpleNamespace(to_dict=lambda: parsed))
    return SimpleNamespace(model=Model(), sample=sample, guidance=guidance,
                           direct=direct, guided=guided, parsed=parsed, calls=calls)


def test_existing_model_and_codec_are_reused_without_sample_memory(setup):
    observer = module.GuidedLegacyCompiler(setup.model, top_k=6)
    for _ in range(2):
        result = observer.observe(setup.sample)
        assert result["status"] == "captured"
    assert observer.model is setup.model
    assert setup.calls["codec_init"] == 1
    for sample, options in setup.calls["guidance"]:
        assert sample is setup.sample
        assert options == {"top_k": 6, "use_sample_memory": False, "include_causal_attribution": False}
    assert len(setup.calls["compile"]) == 4
    for offset in (0, 2):
        plain, guided = setup.calls["compile"][offset:offset + 2]
        assert plain[1]["compiler_guidance"] is None
        assert guided[1]["compiler_guidance"] is setup.guidance
        assert plain[0] == guided[0] == setup.sample.text
        assert {key: value for key, value in plain[1].items() if key != "compiler_guidance"} == {
            key: value for key, value in guided[1].items() if key != "compiler_guidance"}
        assert plain[1]["source_embedding"] is setup.sample.embedding_vector


def test_formula_evidence_preserves_scope_and_never_claims_learned_generation(setup):
    result = module.GuidedLegacyCompiler(setup.model).observe(setup.sample)
    assert result["document"] == setup.guided
    assert result["direct_document"] == setup.direct
    assert result["source_parser_document"] == setup.parsed
    assert result["direct_document"] != result["source_parser_document"]
    assert result["comparison_baseline"] == "same_codec_without_guidance"
    assert result["direct_origin"] == "deterministic_codec"
    assert result["timings"]["direct_compiler_seconds"] >= 0
    assert result["timings"]["guided_compiler_seconds"] >= 0
    expected = setup.guided["formulas"][0]
    assert result["guided_formal_outputs"][0]["payload"] == expected
    assert result["direct_formal_outputs"][0]["payload"] == expected
    assert result["comparison_scope"] == "exact_raw_ast_diagnostic"
    assert result["independent"] is result["learned_formula_generation"] is False
    assert result["admitted"] is result["formalized"] is result["semantic_qualified"] is False
    assert result["source_derived"] is result["target_conditioned"] is True
    assert result["syntax_status"] == result["guided_formal_outputs"][0]["syntax_status"] == "not_checked"
    assert result["lake"] == {"status": "not_run", "admitted": False}
    setup.guided["formulas"][0]["exceptions"].append("new exception")
    assert result["guided_formal_outputs"][0]["payload"]["exceptions"] == ["emergency"]


def test_raw_ast_disagreement_keeps_both_formulas(setup):
    setup.guided["formulas"][0]["metadata"]["quantity"] = 10
    result = module.GuidedLegacyCompiler(setup.model).observe(setup.sample)
    assert result["direct_formal_outputs"] != result["guided_formal_outputs"]
    assert result["direct_formal_outputs"][0]["payload"]["metadata"]["quantity"] == 20
    assert result["guided_formal_outputs"][0]["payload"]["metadata"]["quantity"] == 10


def test_target_free_guidance_is_still_not_independent(setup):
    setup.guidance["legal_ir_target_view_distribution"] = {}
    result = module.GuidedLegacyCompiler(setup.model).observe(setup.sample)
    assert result["target_conditioned"] is False
    assert result["independent"] is False


@pytest.mark.parametrize("updates", [{"sample_id": "other"}, {"sample_memory_used": True}])
def test_mismatched_guidance_becomes_explicit_error_without_compiler_call(setup, updates):
    setup.guidance.update(updates)
    result = module.GuidedLegacyCompiler(setup.model).observe(setup.sample)
    assert result["status"] == "error"
    assert result["error_type"] == "ValueError"
    assert result["direct_formal_outputs"] == result["guided_formal_outputs"] == []
    assert setup.calls["compile"] == []


def test_oversized_guidance_is_deferred_without_truncation_or_compiler(setup, monkeypatch):
    monkeypatch.setattr(module, "MAX_GUIDANCE_BYTES", 8)
    result = module.GuidedLegacyCompiler(setup.model).observe(setup.sample)
    assert result["status"] == "deferred_guidance_size"
    assert result["guidance_bytes"] > 8
    assert len(result["guidance_sha256"]) == 64
    assert "guidance" not in result
    assert setup.calls["compile"] == []


def test_combined_documents_have_one_byte_bound_and_no_partial_formulas(setup, monkeypatch):
    monkeypatch.setattr(module, "MAX_DOCUMENT_BYTES", 8)
    result = module.GuidedLegacyCompiler(setup.model).observe(setup.sample)
    assert result["status"] == "deferred_document_size"
    assert result["formula_count"] == result["direct_formula_count"] == 1
    assert "document" not in result and "direct_document" not in result
    assert result["direct_formal_outputs"] == result["guided_formal_outputs"] == []


def test_no_formulas_remains_empty_in_both_outputs(setup):
    setup.direct["formulas"] = []
    setup.guided["formulas"] = []
    result = module.GuidedLegacyCompiler(setup.model).observe(setup.sample)
    assert result["status"] == "captured"
    assert result["formula_count"] == 0
    assert result["guided_formal_outputs"] == result["direct_formal_outputs"] == []


def test_codec_failure_is_local_to_observation(setup, monkeypatch):
    def failing_factory():
        raise RuntimeError("codec unavailable")
    monkeypatch.setattr(module, "_codec", failing_factory)
    result = module.GuidedLegacyCompiler(setup.model).observe(setup.sample)
    assert result["status"] == "error" and result["error_type"] == "RuntimeError"
    assert result["admitted"] is False


@pytest.mark.parametrize("top_k", [True, 0, 33, 1.5])
def test_top_k_cannot_disable_guidance_bounds(setup, top_k):
    with pytest.raises(ValueError):
        module.GuidedLegacyCompiler(setup.model, top_k=top_k)
