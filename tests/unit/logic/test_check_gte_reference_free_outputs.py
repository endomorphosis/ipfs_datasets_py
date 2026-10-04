from copy import deepcopy
import pytest

from scripts.ops.legal_ir import check_gte_reference_free_outputs as subject


def rule(**changes):
    return {"rules": [{"modality": "O", "actor": "agency", "action": "submit", "object": "reports",
        "conditions": [], "exceptions": [], "temporal": [], **changes}]}


def test_literal_support_is_casefolded_exact_boundary_and_not_semantic():
    result = subject.lexical_support("The AGENCY must submit reports.", rule())
    assert result["all_nonmodal_atoms_supported"] and result["core_atoms_supported"]
    assert result["modality_checked"] is False and result["semantic_correctness_verified"] is False
    result = subject.lexical_support("The superagency must resubmit reports.", rule())
    assert not result["facet_literal_support"]["actor"]
    assert not result["facet_literal_support"]["action"]
    assert result["facet_literal_support"]["object"]


def test_casefold_expansion_offsets_are_explicitly_not_original_offsets():
    result = subject.lexical_support("Straße must submit reports.", rule(actor="STRASSE"))
    assert result["atoms"][0]["casefolded_source_offsets"] == [[0, 7]]
    assert result["offset_domain"].startswith("casefolded")


def test_unknown_qualifier_is_retained_in_lexical_audit():
    target = rule(conditions=["approval holds"], exceptions=["notice pending"], temporal=["before 2075-01-01"])
    result = subject.lexical_support("agency must submit reports if approval holds.", target)
    assert result["facet_literal_support"]["conditions"]
    assert not result["facet_literal_support"]["exceptions"]
    assert not result["facet_literal_support"]["temporal"]
    assert len(result["atoms"]) == 6


@pytest.mark.parametrize("gate", [{}, {"all_builds_completed": False, "scores_opened": False},
    {"all_builds_completed": True, "scores_opened": True}])
def test_posthoc_scorer_requires_completed_score_blind_build_freeze(gate):
    with pytest.raises(ValueError, match="frozen before"):
        subject.posthoc_score({}, {}, {}, "primary384", builds_frozen=gate)


def test_generation_inventory_rejects_dropped_duplicate_or_extra_models(tmp_path):
    refs = []
    for label in subject.VARIANTS:
        path = tmp_path / ("generation-" + label + ".json")
        refs.append(subject.write(path, {"variant": label}))
    frozen = {"all_variants_completed": True, "scoring_started": False, "reference_prefix_used": False,
        "generation_files": refs, "generation_count": 310}
    assert set(subject.generation_inventory(frozen, tmp_path, "grammar")) == set(subject.VARIANTS)
    for bad_refs in (refs[:-1], [refs[0], *refs[:-1]], [*refs, refs[0]]):
        changed = {**frozen, "generation_files": bad_refs}
        with pytest.raises(ValueError, match="complete model"):
            subject.generation_inventory(changed, tmp_path, "grammar")


def test_file_reference_rejects_mutated_bytes_and_extra_keys(tmp_path):
    path = tmp_path / "x.json"
    ref = subject.write(path, {"x": 1})
    assert subject.read_ref(ref) == {"x": 1}
    with pytest.raises(ValueError, match="closed"):
        subject.read_ref({**ref, "qualified": True})
    path.write_text('{"x":2}')
    with pytest.raises(ValueError, match="changed"):
        subject.read_ref(ref)


def test_source_inventory_rejects_target_field_and_incomplete_cohort():
    inputs = {"schema": "gte-native-source-control-inputs/v1", "heads": {"primary384": [], "legacy8": []},
        "target_access": False, "contains_references": False, "independent_holdout": False}
    with pytest.raises(ValueError, match="full source cohort"):
        subject.source_inventory(inputs, [])
    with pytest.raises(ValueError, match="closed source-only"):
        subject.source_inventory({**inputs, "canonical_ir": rule()}, [])


def test_admit_row_rejects_checkpoint_state_mismatch_before_decoding():
    source = {"id": "x", "source_text": "agency must submit reports.", "source_sha256": "a" * 64,
        "evaluation_role": "original_validation_exposed_regression_only", "generation_input": {
            "input_sha256": subject.digest([0.]), "input_vector": [0.]}}
    intervention = {"control": "source", "receiving_id": "x", "receiving_source_sha256": "a" * 64,
        "original_input_sha256": subject.digest([0.]), "effective_input_sha256": subject.digest([0.]), "donor": None,
        "provenance": "original_donor_source_coordinates", "zero_input_is_disabled_context": False, "target_access": False}
    row = {key: source[key] for key in ("id", "source_text", "source_sha256", "evaluation_role")}
    row.update(head="primary384", variant="original_donor", intervention=intervention, generation={
        "variant": "donor384", "head": "primary384", "input_vector_sha256": subject.digest([0.]),
        "model_state_sha256_before": "b" * 64, "model_state_sha256_after": "b" * 64})
    with pytest.raises(ValueError, match="model/input/budget"):
        subject.admit_row(row, source, "original_donor", {}, "c" * 64, {}, "raw")


def test_calendar_selection_retains_full_qualifiers_and_excludes_unknown_time():
    text = "agency must submit reports if approval holds unless notice pending before a date."
    source = {"id": "x", "source_text": text, "source_sha256": subject.sha_text(text)}
    prediction = {"id": "x", "source_sha256": source["source_sha256"], "status": "decoded", "canonical_ir": rule(
        conditions=["approval holds"], exceptions=["notice pending"], temporal=["before a date"]),
        "target_access": False, "teacher_forcing": False}
    before = deepcopy(prediction)
    selected = subject.calendar.select_candidates([source], [prediction], toolchain="leanprover/lean4:v4.34.1", policy=subject.calendar.POLICY)
    assert selected["source_count"] == selected["decoded_count"] == 1
    assert selected["supported_count"] == 0
    assert selected["excluded"][0]["reason"] == "explicit_interpretation_unsupported"
    assert prediction == before


@pytest.mark.parametrize("head", ["primary384", "legacy8"])
def test_posthoc_rejects_donor_vector_replacement_even_with_updated_self_hash(monkeypatch, head):
    text, vector = "agency must submit reports.", [0.1, 0.2]
    monkeypatch.setattr(subject.scorer._NATIVE, "_legacy_sources", lambda inputs: ([], [
        {"id": "x", "source_text": text, "latent": vector}]))
    sources = {(head, "x"): {"source_text": text,
        "generation_input": {"input_vector": vector[:], "input_sha256": subject.digest(vector)}}}
    archive = {(head, "x"): {"source_text": text, "embedding": vector}}
    subject.verify_donor_coordinates(sources, archive, [])
    replacement = [0.3, 0.4]
    sources[head, "x"]["generation_input"] = {"input_vector": replacement, "input_sha256": subject.digest(replacement)}
    with pytest.raises(ValueError, match="original donor coordinates differ"):
        subject.verify_donor_coordinates(sources, archive, [])
