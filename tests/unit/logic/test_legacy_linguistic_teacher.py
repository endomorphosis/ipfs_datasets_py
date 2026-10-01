"""Compiler-supervised teacher targets must not hide historical failures."""
from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_cached import CachedLinguisticAutoencoder
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_teacher import LegacyLinguisticTeacher


@pytest.fixture
def model():
    return CachedLinguisticAutoencoder(compute_device="cpu")


def sample(model, text, section="1"):
    return model.build_sample(title="fixture", section=section, text=text)


@pytest.mark.parametrize("text,symbol,quantity,kind", [
    ("Company A shall submit backup report within 10 days unless emergency.", "O", 10, "within_duration"),
    ("The agency shall not disclose records.", "F", None, None),
    ("The officer shall retain the file for at least 20 days.", "O", 20, "minimum_duration"),
    ("The agency must not disclose records.", "F", None, None),
    ("The agency may disclose records.", "P", None, None),
])
def test_explicit_repairs_preserve_model_and_never_grant_admission(model, text, symbol, quantity, kind):
    row = sample(model, text)
    before_state = model.state.to_dict()
    before_ir = row.modal_ir.to_dict()
    old = model.linguistic_observation(row)
    vector = model.decode(model.encode(row, use_sample_memory=False))
    teacher = LegacyLinguisticTeacher(model)
    result = teacher.distillation_row(row, corpus="authored_fixture")
    evidence = result["evidence"]
    assert result["distillation_mask"] == {"feature_vector": True, "historical_formula": False, "compiler_supervised_formula": True}
    assert result["formula_target"]["rules"][0]["modality"] == symbol
    assert result["feature_target"] == vector
    assert evidence["historical_linguistic_ir"] == old["modal_ir"]
    assert evidence["compiler"]["cycle_equal"] is True
    assert evidence["model_binding"]["linguistic_identity"]["backend"] == "historical_blank_en"
    assert evidence["model_binding"]["current_weights_reverified"] is False
    assert evidence["compiler"]["cycle_vocabulary_source"] == "same_original_parser_string_atoms"
    if quantity is not None:
        assert evidence["compiler"]["temporal_records"][0]["quantity"] == quantity
        assert evidence["compiler"]["temporal_records"][0]["temporal_kind"] == kind
        assert str(quantity) in str(result["formula_target"])
    if "emergency" in text:
        assert result["formula_target"]["rules"][0]["exceptions"] == ["emergency"]
    assert model.state.to_dict() == before_state
    assert row.modal_ir.to_dict() == before_ir
    for key in ("admitted", "formalized", "roundtrip_ok", "semantic_qualification", "formula_fidelity_verified", "independent_formula_generation"):
        assert result[key] is evidence[key] is False


@pytest.mark.parametrize("text,reason", [
    ("The agency is not required to disclose records.", "unsupported_negated_or_overriding_norm"),
    ("The agency may not disclose records.", "ambiguous_may_not"),
    ("The agency shall not only disclose records.", "unsupported_not_only_scope"),
    ("The agency shall submit reports and the officer shall retain records.", "requires_one_direct_norm"),
    ("The agency shall submit reports and retain records.", "unsupported_coordinated_scope"),
    ("Nothing shall be construed to require disclosure.", "unsupported_interpretive_norm"),
    ("The agency shall have no obligation to disclose records.", "unsupported_negated_or_overriding_norm"),
    ("If requested, the agency shall disclose records.", "unsupported_leading_scope"),
    ("The agency shall retain records for no more than 20 days.", "unsupported_temporal_kind"),
    ("The controller must delete the records after 30 days.", "temporal_semantics_not_explicit"),
    ("Every officer is an employee.", "requires_one_direct_norm"),
    ("The agency shall disclose records only if the requester pays.", "unsupported_restrictive_or_nested_scope"),
    ("The agency shall submit a report without disclosing records.", "unsupported_restrictive_or_nested_scope"),
    ("The agency shall submit at most one report.", "unsupported_quantifier_scope"),
])
def test_unreliable_formulas_are_not_training_targets(model, text, reason):
    result = LegacyLinguisticTeacher(model).distillation_row(sample(model, text), corpus="authored_fixture")
    assert result["formula_target"] is None
    assert result["distillation_mask"]["compiler_supervised_formula"] is False
    assert reason in result["evidence"]["reasons"]
    assert result["distillation_mask"]["historical_formula"] is False


@pytest.mark.parametrize("corpus", ["constitution", "unknown"])
def test_constitution_and_unverified_corpus_cannot_produce_formula_targets(model, corpus):
    result = LegacyLinguisticTeacher(model).distillation_row(
        sample(model, "The officer shall retain the file for at least 20 days."), corpus=corpus)
    assert result["formula_target"] is None
    assert result["roundtrip_ok"] is False
    assert result["evidence"]["compiler"]["status"] == "not_run"


def test_target_cache_is_bounded_copy_safe_and_rejects_source_drift(model, monkeypatch):
    teacher = LegacyLinguisticTeacher(model, max_target_entries=1, max_target_bytes=200_000)
    row = sample(model, "The agency shall not disclose records.")
    original = teacher.observe(row, corpus="authored_fixture")
    assert original["target_cache_hit"] is False
    expected = deepcopy(original["corrected_ir"])
    original["corrected_ir"]["rules"][0]["modality"] = "P"
    repeated = teacher.observe(row, corpus="authored_fixture")
    assert repeated["target_cache_hit"] is True
    assert repeated["corrected_ir"] == expected
    teacher.observe(sample(model, "The officer shall submit notices.", "2"), corpus="authored_fixture")
    assert teacher.observe(row, corpus="authored_fixture")["target_cache_hit"] is False
    assert teacher._target_bytes <= teacher.max_target_bytes
    key = next(iter(teacher._identities))
    monkeypatch.setitem(teacher._identities, key, (0, 0, 0, 0, 0))
    with pytest.raises(RuntimeError, match="source changed"):
        teacher.observe(row, corpus="authored_fixture")
    assert not teacher._targets


def test_target_cache_can_be_disabled(model):
    teacher = LegacyLinguisticTeacher(model, max_target_entries=0)
    row = sample(model, "The agency may disclose records.")
    assert teacher.observe(row, corpus="authored_fixture")["target_cache_hit"] is False
    assert teacher.observe(row, corpus="authored_fixture")["target_cache_hit"] is False
    assert not teacher._targets


def test_mismatched_input_ir_rejected(model):
    teacher = LegacyLinguisticTeacher(model)
    row = sample(model, "The agency shall submit reports.")
    forged = replace(row, text="The agency shall not disclose records.")
    with pytest.raises(ValueError, match="same normalized source"):
        teacher.observe(forged, corpus="authored_fixture")


def test_same_source_with_forged_ir_is_not_a_feature_teacher_target(model):
    teacher = LegacyLinguisticTeacher(model)
    row = sample(model, "The agency shall submit reports.")
    first = row.modal_ir.formulas[0]
    forged_ir = replace(row.modal_ir, formulas=[replace(first, operator=replace(first.operator, symbol="F"))])
    forged = replace(row, modal_ir=forged_ir)
    with pytest.raises(ValueError, match="source-derived sample"):
        teacher.observe(forged, corpus="authored_fixture")
