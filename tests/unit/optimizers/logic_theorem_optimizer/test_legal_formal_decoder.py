"""Actual legal guided formal output is explicit and never independent proof."""
import copy
from dataclasses import replace
import importlib
import json

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formal_decoder as module


@pytest.fixture(params=("legacy_v1", "legacy_v1_optimized", "current_v2"))
def setup(request):
    lineage = importlib.import_module(
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages." + request.param)
    model = lineage.Autoencoder(compute_device="cpu")
    sample = lineage.build_sample(
        title="5", section="552", text="The agency shall not disclose records.",
        embedding_vector=[0.1] * lineage.DIMENSION,
        embedding_model="test:synthetic-not-semantic")
    return model, sample


def test_actual_guided_formulas_all_legal_lineages(setup):
    model, sample = setup
    before = model.state.to_dict()
    result = module.decode_legal_formulas(model, [sample])
    row, = result["rows"]
    assert result["sample_count"] == 1
    assert row["status"] in {"decoded_guided", "semantic_conflict"}
    assert row["formula_count"] > 0
    assert row["dimension"] == model.DIMENSION
    assert model.state.to_dict() == before
    assert row["observation"]["guidance"]["sample_memory_used"] is False
    assert row["observation"]["source_sha256"] == row["source_sha256"]
    assert "document" in row["observation_documents_omitted"]
    assert "document" not in row["observation"]
    assert row["observation"]["document_sha256"]
    # Test output provenance/preservation, not correctness of the existing
    # modal compiler. Semantic equivalence remains explicitly unchecked.
    assert any(output["payload"]["operator"]["family"] == "deontic" for output in row["formal_outputs"])
    for output in row["formal_outputs"]:
        assert json.loads(output["expression"]) == output["payload"]
        assert output["payload"] in [original["payload"] for original in row["observation"]["guided_formal_outputs"]]
        assert output["formula_text"]
        assert output["origin"] == "autoencoder_guided_compiler"
        assert output["syntax_status"] == "not_checked"
    for flag in module.FALSE:
        assert row[flag] is result[flag] is False
    assert row["lake"] == {"status": "not_run", "admitted": False}
    assert row["complete_span_semantics_verified"] is False
    canonical, = row["canonical_observation"]["formal_outputs"]
    assert canonical["payload"]["modality"] == "F"
    if any(output["payload"]["operator"]["symbol"] == "O" for output in row["formal_outputs"]):
        assert row["status"] == "semantic_conflict"
        assert row["canonical_comparison"]["conflicts"]


def test_independent_mode_never_invokes_compiler(setup, monkeypatch):
    model, sample = setup
    def unexpected(*args, **kwargs):
        pytest.fail("independent decoder must not borrow compiler formulas")
    monkeypatch.setattr(module.GuidedLegacyCompiler, "observe", unexpected)
    monkeypatch.setattr(module, "_canonical_observation", unexpected)
    result = module.decode_legal_formulas(model, [sample], mode="independent")
    row, = result["rows"]
    assert row["status"] == "unsupported"
    assert row["reason"] == "checkpoint_has_no_learned_formula_decoder"
    assert row["formal_outputs"] == []


def test_batch_wrong_width_fails_before_any_compiler(setup, monkeypatch):
    model, sample = setup
    def unexpected(*args, **kwargs):
        pytest.fail("invalid batch must not do partial compiler work")
    monkeypatch.setattr(module.GuidedLegacyCompiler, "observe", unexpected)
    with pytest.raises(ValueError, match="expected"):
        module.decode_legal_formulas(model, [sample, replace(sample, embedding_vector=[0.1])])


def test_source_tree_guard_precedes_observation(setup, monkeypatch):
    model, sample = setup
    def drift(*args):
        raise RuntimeError("parser imported outside pinned tree")
    monkeypatch.setattr(module, "require_canonical_modules", drift)
    with pytest.raises(RuntimeError, match="outside pinned tree"):
        module.decode_legal_formulas(model, [sample])


def test_empty_compiler_output_is_abstention_not_decode(setup, monkeypatch):
    model, sample = setup
    monkeypatch.setattr(module.GuidedLegacyCompiler, "observe", lambda *args:
                        {"status": "captured", "guided_formal_outputs": []})
    result = module.decode_legal_formulas(model, [sample])
    assert result["rows"][0]["status"] == "abstained"
    assert result["rows"][0]["reason"] == "compiler_emitted_no_formulas"
    assert result["formula_count"] == 0


def test_scope_metadata_is_retained_verbatim(setup, monkeypatch):
    model, sample = setup
    payload = {"operator": {"family": "deontic", "symbol": "O", "system": "SDL"},
               "predicate": {"name": "retain", "arguments": ["officer", "file"], "role": "action"},
               "conditions": ["for at least 20 days"], "exceptions": ["emergency"],
               "metadata": {"temporal_kind": "minimum_duration", "quantity": 20},
               "provenance": {"source_id": sample.sample_id, "start_char": 0, "end_char": len(sample.text)}}
    original = copy.deepcopy(payload)
    monkeypatch.setattr(module.GuidedLegacyCompiler, "observe", lambda *args:
        {"status": "captured", "guided_formal_outputs": [{"payload": payload}], "target_conditioned": True})
    result = module.decode_legal_formulas(model, [sample])
    row = result["rows"][0]
    output = row["formal_outputs"][0]
    assert json.loads(output["expression"]) == original
    assert "at least 20 days" in output["formula_text"] and "emergency" in output["formula_text"]
    assert row["target_conditioned"] is True
    payload["exceptions"].append("later mutation")
    assert output["payload"] == original


@pytest.mark.parametrize("options", [{"mode": "guess"}, {"top_k": True}, {"top_k": 0}, {"top_k": 33},
                                    {"include_observation_documents": 1}])
def test_bounded_options(setup, options):
    model, sample = setup
    with pytest.raises(ValueError):
        module.decode_legal_formulas(model, [sample], **options)


def test_batch_bound_does_not_consume_unbounded_stream(setup):
    model, sample = setup
    consumed = []
    def forever():
        while True:
            consumed.append(True)
            yield sample
    with pytest.raises(ValueError, match="exceeds 128"):
        module.decode_legal_formulas(model, forever())
    assert len(consumed) == 129


def test_raw_unknown_runtime_is_not_auto_selected():
    with pytest.raises(TypeError, match="explicit legal lineage"):
        module.LegalFormalDecoder(object())


@pytest.mark.parametrize("text,modality,rendered", [
    ("Company A shall submit backup report within 10 days unless emergency.", "O", "10 days"),
    ("The agency shall not disclose records.", "F", "must not disclose"),
    ("The officer shall retain the file for at least 20 days.", "O", "at least 20 days"),
])
def test_canonical_mode_preserves_three_gate_spans(setup, monkeypatch, text, modality, rendered):
    model, sample = setup
    # Canonical mode never requests guidance or substitutes numerical outputs.
    def unexpected(*args, **kwargs):
        pytest.fail("canonical mode must not invoke the model-guided compiler")
    monkeypatch.setattr(module.GuidedLegacyCompiler, "observe", unexpected)
    row = module.decode_legal_formulas(model, [replace(sample, text=text)],
                                       mode="canonical_compiler")["rows"][0]
    output, = row["formal_outputs"]
    assert row["status"] == "compiled" and row["model_used"] is False
    assert output["payload"]["modality"] == modality
    assert output["origin"] == "canonical_compiler"
    assert rendered in output["decompiled_text"]
    assert row["canonical_observation"]["vocabulary_source"] == "deontic_parser_string_atoms"
    if "emergency" in text:
        assert "emergency" in output["payload"]["exceptions"]
        assert "emergency" in output["formula_text"]
    if "at least" in text:
        assert "at least days" not in output["decompiled_text"]
    assert row["admitted"] is row["formalized"] is False


def test_conflicting_scope_is_exposed_without_rewriting_guided_output():
    modal = {"operator": {"family": "deontic", "symbol": "O"},
             "predicate": {"name": "submit", "arguments": []},
             "exceptions": [], "conditions": []}
    canonical = {"formal_outputs": [{"payload": {"modality": "O", "exceptions": ["emergency"],
                                                "conditions": [], "temporal": ["within 10 days"]}}]}
    before = copy.deepcopy(modal)
    compared = module._compare_canonical([{"payload": modal}], canonical)
    assert compared["status"] == "semantic_conflict"
    assert compared["conflicts"][0]["field"] == "exceptions"
    assert compared["coverage_gaps"][0]["field"] == "temporal"
    assert modal == before
    assert compared["semantic_equivalence_verified"] is False


def test_guidance_rejects_source_text_changed_after_sample_parse(setup, monkeypatch):
    model, sample = setup
    def unexpected(*args):
        pytest.fail("source mismatch must be detected before canonical or guided compilation")
    monkeypatch.setattr(module, "_canonical_observation", unexpected)
    with pytest.raises(ValueError, match="normalized source"):
        module.decode_legal_formulas(model, [replace(sample, text="The agency shall disclose records.")])


def test_result_batch_has_an_aggregate_byte_bound(setup, monkeypatch):
    model, sample = setup
    monkeypatch.setattr(module, "MAX_BATCH_RESULT_BYTES", 1)
    with pytest.raises(ValueError, match="64 MiB"):
        module.decode_legal_formulas(model, [sample], mode="independent")


def test_explicit_full_observation_documents_are_retained(setup, monkeypatch):
    model, sample = setup
    documents = {key: {"native": "retained"} for key in ("document", "direct_document", "source_parser_document")}
    monkeypatch.setattr(module.GuidedLegacyCompiler, "observe", lambda *args:
                        {"status": "captured", "guided_formal_outputs": [], **documents})
    row = module.decode_legal_formulas(model, [sample], include_observation_documents=True)["rows"][0]
    assert row["observation_documents_omitted"] == []
    for key, value in documents.items():
        assert row["observation"][key] == value
