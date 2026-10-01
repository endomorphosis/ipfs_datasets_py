"""Real Lean checks for explicit, unbounded static-frame observations."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lean_emitters import UnsupportedNativeLean
from ipfs_datasets_py.logic.formalization.autoencoder.native_protocol_lean import emit_protocol, _validate
from ipfs_datasets_py.logic.formalization.autoencoder.native_protocol_frames import (
    SCHEMA, ProtocolFrameInterpretation, _digest, _Algebra, _witness,
)
from tests.unit.logic.software_verification.test_protocol import _document
from .test_native_protocol_lean import lake, rebuild


def authored_interpretation(payload):
    """Explicitly choose frame semantics; do not change or remove any claim."""
    return ProtocolFrameInterpretation.from_dict(dict(schema=SCHEMA,
        native_document_sha256=_digest(payload), mode="static_observation_vectors",
        claim_ids=sorted(row["claim_id"] for row in payload["claims"] if row["kind"] == "equivalence"))).to_dict()


def rendered(payload=None):
    payload = _document().to_dict() if payload is None else payload
    return emit_protocol(payload, interpretation=authored_interpretation(payload))


def equivalence(payload):
    return next(row for row in payload["claims"] if row["kind"] == "equivalence")


SIMPLIFY = "frameEvaluate, frameObservation, frameNormalize, frameApply, termSort, frameTermEq, frameTermsEq, frameFunctionAccessible, frameSortKnown, initialKnowledge, hasCapability, capabilities, frameClaim_0Left, frameClaim_0Right"


def test_original_five_claim_model_keeps_exact_bytes_and_has_checked_refutation():
    payload = _document().to_dict(); before = deepcopy(payload)
    source, details = rendered(payload)
    assert payload == before and details["retained_native_records"] == before
    assert len(details["query_definitions"]) == 5
    frames = details["static_frame_interpretation"]
    outcome = frames["claim_evaluations"][0]
    assert outcome["counterexample_found"] and not outcome["equivalent_proved"]
    assert outcome["counterexample"]["left_observation"] is True
    assert outcome["counterexample"]["right_observation"] is False
    assert frames["native_document_rewritten"] is False and frames["claim_operands_rewritten"] is False
    assert frames["process_equivalence_verified"] is False
    assert outcome["semantic_recipe_depth_bound"] is None
    assert "∀ first second, frameObservation left" in source
    assert "theorem frameTermEq_exact" in source
    query = details["query_definitions"]["claim:equivalence"]
    result = lake(source, "example (i : ProtocolInterpretation) : ¬ " + query + " i := by\n"
        "  intro h\n  exact frameClaim_0_not_equivalent (h True.intro)\n")
    assert result["status"] == "passed", result


def test_false_original_equivalence_cannot_be_proved_by_decide():
    source, _ = rendered()
    result = lake(source, "example : frameClaim_0 := by decide")
    assert result["backend_executed"] and result["status"] == "failed"


def test_identical_frames_are_equivalent_for_all_recipes_without_vacuous_trace_parameters():
    payload = _document().to_dict()
    claim = equivalence(payload); claim["right_terms"] = deepcopy(claim["left_terms"])
    payload = rebuild(payload)
    source, details = rendered(payload)
    result = lake(source, "example : frameClaim_0 := by intro first second; rfl")
    assert result["status"] == "passed", result
    outcome = details["static_frame_interpretation"]["claim_evaluations"][0]
    assert not outcome["counterexample_found"] and not outcome["equivalent_proved"]
    assert "permitted" not in next(line for line in source.splitlines() if line.startswith("def frameClaim_0 :"))


def test_two_private_names_are_distinguished_by_correlation_without_guessing_names():
    payload = _document().to_dict()
    second = deepcopy(payload["fresh_names"][0]); second.update(name_id="name:other", name="other")
    payload["fresh_names"].append(second)
    first_term = deepcopy(payload["events"][0]["parameters"][0])
    second_term = deepcopy(first_term); second_term["symbol_id"] = "name:other"
    claim = equivalence(payload)
    claim["left_terms"] = [first_term, first_term]
    claim["right_terms"] = [first_term, second_term]
    source, details = rendered(rebuild(payload))
    witness = details["static_frame_interpretation"]["claim_evaluations"][0]["counterexample"]
    assert witness["first"]["kind"] == witness["second"]["kind"] == "handle"
    assert lake(source, "example : ¬ frameClaim_0 := frameClaim_0_not_equivalent")["status"] == "passed"


def encrypted_frame_payload(compromise):
    payload = _document().to_dict()
    left = deepcopy(payload["messages"][0]["payload"])
    right = deepcopy(left); right["arguments"][1]["symbol_id"] = "key:initiator-private"
    claim = equivalence(payload); claim.update(left_terms=[left], right_terms=[right])
    if compromise:
        payload["adversary"]["compromised_key_ids"] = ["key:session"]
    return rebuild(payload)


def test_success_and_failure_of_decryption_are_observable_not_both_false():
    payload = encrypted_frame_payload(True)
    source, details = rendered(payload)
    witness = details["static_frame_interpretation"]["claim_evaluations"][0]["counterexample"]
    assert witness is not None
    assert (witness["left_observation"] is None) != (witness["right_observation"] is None)
    assert "apply" in {witness["first"]["kind"], witness["second"]["kind"]}
    result = lake(source, "example : ¬ frameClaim_0 := frameClaim_0_not_equivalent")
    assert result["status"] == "passed", result


def test_failure_with_unavailable_key_is_not_mistaken_for_equivalence_proof():
    payload = encrypted_frame_payload(False)
    source, details = rendered(payload)
    outcome = details["static_frame_interpretation"]["claim_evaluations"][0]
    assert not outcome["counterexample_found"] and not outcome["equivalent_proved"]
    recipe = '(.apply "function:decrypt" [.handle 0, .initial 0])'
    result = lake(source, "example : frameEvaluate frameClaim_0Left " + recipe + " = none := by simp [" + SIMPLIFY + "]\n"
        "example : frameEvaluate frameClaim_0Right " + recipe + " = none := by simp [" + SIMPLIFY + "]")
    assert result["status"] == "passed", result


def test_capabilities_gate_recipe_functions_and_wrong_sorts_fail():
    payload = encrypted_frame_payload(True)
    payload["adversary"]["capabilities"].remove("decompose")
    source, details = rendered(rebuild(payload))
    result = lake(source, '''
example : frameEvaluate frameClaim_0Left (.apply "function:decrypt" [.handle 0, .initial 2]) = none := by
  simp [SIMPLIFY]
example : frameEvaluate frameClaim_0Left (.apply "function:encrypt" [.handle 0, .initial 0]) = none := by
  simp [SIMPLIFY]
example : frameEvaluate frameClaim_0Left (.literal "unknown-sort" "x") = none := by
  simp [SIMPLIFY]
'''.replace("SIMPLIFY", SIMPLIFY))
    assert result["status"] == "passed", result
    assert not details["static_frame_interpretation"]["claim_evaluations"][0]["equivalent_proved"]


def test_public_literal_recipe_cannot_forge_a_private_fresh_name_atom():
    payload = _document().to_dict()
    term = payload["events"][0]["parameters"][0]
    claim = equivalence(payload); claim.update(left_terms=[term], right_terms=[term])
    source, _ = rendered(rebuild(payload))
    result = lake(source, 'example : frameObservation frameClaim_0Left (.handle 0) (.literal "sort:nonce" "name:challenge") = some false := by simp [' + SIMPLIFY + ']')
    assert result["status"] == "passed", result


@pytest.mark.parametrize("mutation, reason", [
    (lambda i: i.update(native_document_sha256="0" * 64), "digest_differs"),
    (lambda i: i.update(mode="process_equivalence"), "observation_mode"),
    (lambda i: i.update(claim_ids=["claim:secrecy"]), "exactly_every"),
    (lambda i: i.update(claim_ids=[]), "claim_ids"),
    (lambda i: i.update(claim_ids=["claim:equivalence", "claim:equivalence"]), "claim_ids"),
    (lambda i: i.update(left_terms=[]), "closed_protocol"),
    (lambda i: i.update(qualified=True), "closed_protocol"),
])
def test_interpretation_cannot_change_frames_skip_claims_or_assert_authority(mutation, reason):
    payload = _document().to_dict(); interpretation = authored_interpretation(payload)
    mutation(interpretation)
    with pytest.raises(UnsupportedNativeLean, match=reason):
        emit_protocol(payload, interpretation=interpretation)


def test_interpretation_matches_complete_model_including_source_records():
    payload = _document().to_dict(); interpretation = authored_interpretation(payload)
    payload["sources"][0]["content_sha256"] = "0" * 64
    changed = rebuild(payload)
    with pytest.raises(UnsupportedNativeLean, match="digest_differs"):
        emit_protocol(changed, interpretation=interpretation)


def test_typed_context_is_immutable_and_accepts_no_uninterpreted_fields():
    payload = _document().to_dict(); wire = authored_interpretation(payload)
    typed = ProtocolFrameInterpretation.from_dict(wire)
    wire["claim_ids"].clear()
    assert typed.to_dict()["claim_ids"] == ["claim:equivalence"]
    source, details = emit_protocol(payload, interpretation=typed)
    assert "staticFrameEquivalent" in source
    assert details["static_frame_interpretation"]["interpretation"] == typed.to_dict()


def test_noncanonical_equations_cannot_be_ignored_by_the_frame_normalizer():
    payload = _document().to_dict()
    payload["rewrite_facts"][0]["right"] = dict(sort="sort:nonce", literal="different", symbol_id="", function_id="", arguments=[])
    payload = rebuild(payload)
    with pytest.raises(UnsupportedNativeLean, match="noncanonical_equation"):
        rendered(payload)


def test_conditional_disclosure_requires_a_real_cutpoint_instead_of_empty_history():
    payload = _document().to_dict()
    payload["adversary"]["knowledge"][0]["available_after_event_ids"] = ["event:accept"]
    with pytest.raises(UnsupportedNativeLean, match="cutpoint"):
        rendered(rebuild(payload))


def test_frame_operands_with_failed_destructors_do_not_create_vacuous_equivalence():
    payload = _document().to_dict()
    decrypt = deepcopy(payload["rewrite_facts"][0]["left"])
    decrypt["arguments"][1]["symbol_id"] = "key:initiator-private"
    equivalence(payload).update(left_terms=[decrypt], right_terms=[decrypt])
    with pytest.raises(UnsupportedNativeLean, match="operands_must_have_values"):
        rendered(rebuild(payload))


def test_original_query_still_requires_explicit_interpretation():
    with pytest.raises(UnsupportedNativeLean, match="explicit_process_or_frame"):
        emit_protocol(_document().to_dict())


def test_search_budget_applies_to_seed_basis_without_bounding_the_formula():
    payload = _document().to_dict()
    original = payload["adversary"]["knowledge"][0]
    payload["adversary"]["knowledge"] = [dict(deepcopy(original), knowledge_id="knowledge:" + str(i)) for i in range(300)]
    payload = rebuild(payload)
    _, symmetric = _validate(payload, allow_equivalence=True)
    algebra = _Algebra(payload, symmetric)
    # The different literal is after the capped seed basis: absence remains
    # inconclusive, while the production Lean definition quantifies all recipes.
    claim = equivalence(payload)
    assert _witness(algebra, claim["left_terms"], claim["right_terms"]) is None
