"""Generated-content and original-text controls with real canonical contracts."""
from copy import deepcopy
import json
import re

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import contextual_legal_ir_output as output

VOCABULARY = ['<pad>', '<bos>', '<eos>', '"F"', '"O"', '"P"', '"action"',
    '"actor"', '"approve"', '"archive"', '"conditions"', '"deliver"', '"examine"',
    '"exceptions"', '"modality"', '"notary"', '"notice"', '"object"', '"preserve"',
    '"publish"', '"registrar"', '"rules"', '"secretary"', '"temporal"', '"treasurer"',
    '"trustee"', ',', ':', '[', ']', '{', '}']
CODEC = {"schema": "typed-json-lexical/v1", "target_vocabulary": VOCABULARY}


def rule(modality="O", actor="trustee", action="approve", obj="archive", **facets):
    return {"modality": modality, "actor": actor, "action": action, "object": obj,
            "conditions": [], "exceptions": [], "temporal": [], **facets}


def prediction(identity, rules, *, eos=True, status=None):
    text = json.dumps({"rules": rules}, separators=(",", ":"), sort_keys=True)
    lexical = re.findall(r'"[^"\\]*"|[{}\[\]:,]', text)
    return {"id": identity, "token_ids": [VOCABULARY.index(token) for token in lexical],
            "eos_reached": eos, "generation_status": status or ("eos" if eos else "output_limit")}


def reference(identity, rules):
    return {"id": identity, "target": {"rules": deepcopy(rules)}, "clause_count": len(rules)}


def test_generated_rule_conforms_to_actual_contract_without_reference_or_source():
    result = output.inspect_contextual_legal_predictions([prediction("x", [rule()])], codec=CODEC)
    row = result["rows"][0]
    assert row["complete_candidate"] and row["canonical_contract_valid"]
    assert row["ordered_generated_ir"] == {"rules": [rule()]}
    assert row["canonical_contract_ir_cid"] == "baguqeera2diinoqpigmku75kwsnpni3i32tg7fm7jqgn4mfazr45iw4p6kvq"
    assert result["canonical_contract_interface"] == "CanonicalRoundTripIR@1"
    assert not any(result["authority"].values())


def test_rule_order_is_preserved_and_compared_separately_from_native_canonical_order():
    a, b = rule(), rule("F", "notary", "publish", "notice")
    candidate = prediction("x", [b, a])
    result = output.score_contextual_legal_predictions([reference("x", [a, b])], [candidate], codec=CODEC)
    metrics = result["reference_agreement"]["metrics"]
    assert metrics["ordered_exact"] == 0 and metrics["all_rules_preserved"] == 1
    assert metrics["order_mismatch_rows"] == 1
    assert result["canonical_contract_exact"] == 1
    assert result["generated_payload_inspection"]["rows"][0]["ordered_generated_ir"] == {"rules": [b, a]}
    assert not result["source_semantic_equivalence_measured"]


def test_native_canonicalization_does_not_rewrite_duplicate_qualifiers_in_generated_output():
    candidate_rule = rule(conditions=["notary", "notary"])
    result = output.inspect_contextual_legal_predictions([prediction("x", [candidate_rule])], codec=CODEC)
    row = result["rows"][0]
    assert row["ordered_generated_ir"]["rules"][0]["conditions"] == ["notary", "notary"]
    assert row["canonical_contract_ir"]["rules"][0]["conditions"] == ["notary"]
    assert row["canonicalization_changed_payload"]


def test_missing_prediction_keeps_full_reference_denominators():
    refs = [reference("x", [rule()]), reference("y", [rule()])]
    result = output.score_contextual_legal_predictions(refs, [prediction("x", [rule()])], codec=CODEC)
    metrics = result["reference_agreement"]["metrics"]
    assert metrics["rows"] == 2 and metrics["expected_rules"] == 2
    assert metrics["ordered_exact"] == 1 and metrics["prediction_missing_rows"] == 1
    assert result["canonical_contract_exact"] == 1 and result["reference_count"] == 2
    assert all(row["total"] == 2 for row in result["reference_agreement"]["by_facet"].values())


def test_valid_json_without_eos_is_incomplete_and_cannot_score_exact():
    candidate = prediction("x", [rule()], eos=False)
    result = output.score_contextual_legal_predictions([reference("x", [rule()])], [candidate], codec=CODEC)
    row = result["generated_payload_inspection"]["rows"][0]
    assert row["canonical_contract_valid"] and not row["complete_candidate"]
    assert result["reference_agreement"]["metrics"]["syntax_valid"] == 1
    assert result["reference_agreement"]["metrics"]["ordered_exact"] == 0
    assert result["canonical_contract_exact"] == 0


@pytest.mark.parametrize("status", [None, True, "finished"])
def test_missing_or_unsupported_status_cannot_be_scored_as_complete(status):
    candidate = prediction("x", [rule()])
    candidate["generation_status"] = status
    with pytest.raises(ValueError, match="explicit supported generation status"):
        output.inspect_contextual_legal_predictions([candidate], codec=CODEC)
    with pytest.raises(ValueError, match="explicit supported generation status"):
        output.score_contextual_legal_predictions([reference("x", [rule()])], [candidate], codec=CODEC)


def test_runtime_deadline_receipt_remains_an_unscorable_failure():
    candidate = {"id": "x", "token_ids": [], "eos_reached": False, "generation_status": "deadline"}
    result = output.score_contextual_legal_predictions([reference("x", [rule()])], [candidate], codec=CODEC)
    assert result["reference_agreement"]["metrics"]["ordered_exact"] == 0
    row = result["generated_payload_inspection"]["rows"][0]
    assert row["generation_status"] == "deadline" and row["errors"]
    assert not row["complete_candidate"]


@pytest.mark.parametrize("mutation", [
    lambda row: row.update(eos_reached=True, generation_status="output_limit"),
    lambda row: row["token_ids"].append(True),
    lambda row: row["token_ids"].append(0),
    lambda row: row["token_ids"].append(999),
    lambda row: row.update(eos_reached=1),
])
def test_invalid_generation_receipts_are_not_repaired(mutation):
    row = prediction("x", [rule()])
    mutation(row)
    result = output.inspect_contextual_legal_predictions([row], codec=CODEC)
    assert result["complete_candidates"] == 0
    assert result["rows"][0]["errors"]


def test_duplicate_json_key_refuses_without_a_reference_fallback():
    candidate = prediction("x", [rule()])
    # Repeat the complete "rules" field inside the document.
    body = candidate["token_ids"][1:-1]
    candidate["token_ids"] = [VOCABULARY.index("{"), *body, VOCABULARY.index(","), *body, VOCABULARY.index("}")]
    result = output.score_contextual_legal_predictions([reference("x", [rule()])], [candidate], codec=CODEC)
    assert result["reference_agreement"]["metrics"]["ordered_exact"] == 0
    assert result["generated_payload_inspection"]["rows"][0]["ordered_generated_ir"] is None


def test_syntactic_json_with_invalid_native_modality_remains_invalid():
    result = output.inspect_contextual_legal_predictions([prediction("x", [rule("rules")])], codec=CODEC)
    assert result["complete_candidates"] == 0
    assert result["rows"][0]["ordered_generated_ir"] == {"rules": [rule("rules")]}
    assert result["rows"][0]["canonical_contract_ir"] is None


@pytest.mark.parametrize("cap", [True, 3, 513, 8192, 512.0])
def test_output_limit_is_independent_and_strictly_typed(cap):
    with pytest.raises(ValueError):
        output.inspect_contextual_legal_predictions([], codec=CODEC, output_limit=cap)


def test_gold_or_authority_fields_cannot_be_injected_into_generated_rows():
    row = prediction("x", [rule()])
    row["target"] = {"rules": [rule()]}
    with pytest.raises(ValueError, match="closed generated"):
        output.inspect_contextual_legal_predictions([row], codec=CODEC)


def test_unknown_or_duplicate_candidate_identity_refuses_in_scoring():
    refs = [reference("x", [rule()])]
    with pytest.raises(ValueError):
        output.score_contextual_legal_predictions(refs, [prediction("y", [rule()])], codec=CODEC)
    with pytest.raises(ValueError):
        output.score_contextual_legal_predictions(refs, [prediction("x", [rule()])]*2, codec=CODEC)


def test_returned_ir_is_detached_from_all_caller_values():
    row = prediction("x", [rule()])
    codec = deepcopy(CODEC)
    result = output.inspect_contextual_legal_predictions([row], codec=codec)
    row["token_ids"].clear()
    codec["target_vocabulary"].clear()
    assert result["rows"][0]["ordered_generated_ir"] == {"rules": [rule()]}


def test_existing_source_withheld_realizer_receives_only_generated_ir():
    result = output.render_contextual_legal_text_candidates([prediction("x", [rule()])], codec=CODEC)
    assert len(result["reconstructions"]) == 1
    text = result["reconstructions"][0]["reconstructed_text"]
    assert "trustee" in text.lower() and "approve" in text and "archive" in text
    assert not result["originating_source_passed_to_decompiler"]
    assert not result["reference_IR_passed_to_decompiler"] and not result["decompiler_uses_model"]
    assert result["rendering_receipts"][0]["result"]["status"] == "success"


def test_source_withheld_realizer_does_not_render_an_incomplete_candidate():
    result = output.render_contextual_legal_text_candidates([prediction("x", [rule()], eos=False)], codec=CODEC)
    assert not result["reconstructions"] and len(result["refusals"]) == 1


def test_text_metrics_distinguish_utf8_bytes_nfc_and_whitespace():
    refs = [{"id": "x", "source_text": "Café shall file.\n\nNext rule."}]
    predictions = [{"id": "x", "reconstructed_text": "Cafe\u0301 shall file. Next rule."}]
    result = output.score_legal_text_reconstructions(refs, predictions)
    assert result["verbatim_utf8_exact"] == 0 and result["nfc_whitespace_exact"] == 1
    assert not result["legal_meaning_equivalence_measured"]
    assert not result["decoder_execution_observed"]


@pytest.mark.parametrize("text", ["trustee SHALL approve.", "Trustee shall approve", "Approve shall Trustee."])
def test_text_normalization_preserves_case_punctuation_and_order(text):
    result = output.score_legal_text_reconstructions(
        [{"id": "x", "source_text": "Trustee shall approve."}], [{"id": "x", "reconstructed_text": text}])
    assert result["verbatim_utf8_exact"] == result["nfc_whitespace_exact"] == 0


def test_missing_text_prediction_is_a_failure_not_a_changed_denominator():
    result = output.score_legal_text_reconstructions(
        [{"id": "x", "source_text": "One."}, {"id": "y", "source_text": "Two."}],
        [{"id": "x", "reconstructed_text": "One."}])
    assert result["reference_count"] == 2 and result["missing_prediction_count"] == 1
    assert result["verbatim_utf8_exact"] == result["nfc_whitespace_exact"] == 1


def test_text_evaluator_rejects_unknown_ids_or_hidden_data():
    refs = [{"id": "x", "source_text": "One."}]
    with pytest.raises(ValueError):
        output.score_legal_text_reconstructions(refs, [{"id": "y", "reconstructed_text": "One."}])
    with pytest.raises(ValueError):
        output.score_legal_text_reconstructions(refs, [{"id": "x", "reconstructed_text": "One.", "target": {}}])
