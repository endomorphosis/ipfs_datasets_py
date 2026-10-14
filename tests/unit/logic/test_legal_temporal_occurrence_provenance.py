"""Source-binding checks, using fictional evidence without semantic labels."""
from copy import deepcopy
import hashlib

import pytest

from ipfs_datasets_py.logic.autoformal import legal_temporal_occurrence_provenance as p
from ipfs_datasets_py.logic.autoformal import legal_temporal_event_proposer_v4 as proposer
from ipfs_datasets_py.logic.deontic.utils import deontic_parser as parser
from ipfs_datasets_py.logic.legal_document import _clause_selector


TEXT = "Établissement shall file within 10 days after receipt of notice."


def rule(temporal):
    return {"modality": "O", "actor": "Établissement", "action": "file", "object": "notice",
            "conditions": [], "exceptions": [], "temporal": temporal}


def resign(receipt):
    receipt["receipt_sha256"] = p.digest({key: value for key, value in receipt.items()
                                          if key != "receipt_sha256"})
    return receipt


def selector(document, source, start):
    byte_offsets = [0]
    for character in document:
        byte_offsets.append(byte_offsets[-1] + len(character.encode("utf-8")))
    return _clause_selector(document, source, start, byte_offsets,
                            hashlib.sha256(document.encode("utf-8")).hexdigest())


def test_exact_unicode_whitespace_and_repeated_occurrences():
    text = "Établissement shall file within 10 days; it shall file within 10 days after notice   ."
    result = p.build_occurrence_receipt(text, source_id="fictional")
    left, right = result["occurrences"]
    assert left["occurrence_id"] != right["occurrence_id"]
    assert left["temporal_start_in_clause"] == text.index("within")
    assert right["exact_source_slice"].endswith("   ")
    for item in result["occurrences"]:
        start, end = item["temporal_start_in_clause"], item["temporal_end_in_clause"]
        assert text[start:end] == item["exact_source_slice"] == item["exact_document_slice"]
        assert item["parser_observations"][0]["parser_fields"]["raw_text"] == text[start:end].strip()
    repeated = "Registry shall file within 10 days; registry shall file within 10 days."
    occurrences = p.build_occurrence_receipt(repeated, source_id="repeat")["occurrences"]
    assert occurrences[0]["exact_source_slice"] == occurrences[1]["exact_source_slice"]
    assert len({item["occurrence_id"] for item in occurrences}) == 2
    assert p.validate_occurrence_receipt(result, source_text=text) == result


def test_source_identity_window_and_unicode_document_translation():
    document = "Résumé.\n" + TEXT + "\nEnd."
    start = document.index(TEXT)
    result = p.build_occurrence_receipt(TEXT, source_id="c1", document_text=document,
                                        document_id="doc", clause_start=start, clause_end=start + len(TEXT))
    occurrence = result["occurrences"][0]
    assert occurrence["temporal_start_in_document"] == document.index("within")
    assert document[occurrence["temporal_start_in_document"]:occurrence["temporal_end_in_document"]] == occurrence["exact_source_slice"]
    p.validate_occurrence_receipt(result, source_text=TEXT, document_text=document,
                                  expected_source_id="c1", expected_document_id="doc")
    with pytest.raises(ValueError, match="identity differs"):
        p.build_occurrence_receipt(TEXT, source_id="c1", document_text=document, clause_start=start + 1)
    with pytest.raises(ValueError):
        p.validate_occurrence_receipt(result, source_text=TEXT, document_text=document.replace("Résumé", "Resume"))


def test_validated_selector_preserves_raw_whitespace_document_slice():
    source = "Établissement shall file within 10 days after receipt of notice."
    document = "Préface.\n  Établissement  shall\nfile within  10 days after receipt of notice.\nFin."
    start = document.index("Établissement")
    mapping = selector(document, source, start)
    assert mapping is not None
    result = p.build_occurrence_receipt(source, source_id="c1", document_text=document,
                                        clause_start=mapping["start"], clause_end=mapping["end"],
                                        source_selector=mapping)
    occurrence = result["occurrences"][0]
    assert occurrence["exact_document_slice"] == "within  10 days after receipt of notice"
    assert occurrence["exact_source_slice"] == "within 10 days after receipt of notice"
    assert occurrence["document_translation_resolved"] is True
    assert occurrence["temporal_start_in_document"] != start + occurrence["temporal_start_in_clause"]
    p.validate_occurrence_receipt(result, source_text=source, document_text=document)
    bad = deepcopy(mapping)
    bad["mapping"][-1]["source_start"] -= 1
    with pytest.raises(ValueError, match="selector differs"):
        p.build_occurrence_receipt(source, source_id="c1", document_text=document,
                                    clause_start=mapping["start"], clause_end=mapping["end"], source_selector=bad)
    with pytest.raises(ValueError, match="validated source selector"):
        p.build_occurrence_receipt(source, source_id="c1", document_text=document,
                                    clause_start=mapping["start"], clause_end=mapping["end"])


def test_repeated_clause_views_have_contextual_source_ids_and_distinct_document_ids():
    document = TEXT + "\n" + TEXT
    occurrences = []
    for index, start in enumerate((0, len(TEXT) + 1)):
        result = p.build_occurrence_receipt(TEXT, source_id=f"clause-{index}",
                                            document_text=document, document_id="doc",
                                            clause_start=start, clause_end=start + len(TEXT))
        occurrences.append(result["occurrences"][0])
    assert occurrences[0]["occurrence_id"] == occurrences[1]["occurrence_id"]
    assert occurrences[0]["document_occurrence_id"] != occurrences[1]["document_occurrence_id"]
    assert occurrences[1]["temporal_start_in_document"] > occurrences[0]["temporal_start_in_document"]


def test_different_clause_views_share_exact_physical_document_occurrence_id():
    raw_clause = "Établissement  shall file within  10 days after receipt of notice."
    document = "Préface.\n" + raw_clause + "\nFin."
    start = document.index(raw_clause)
    direct = p.build_occurrence_receipt(raw_clause, source_id="raw-clause", document_id="raw-doc-label",
                                        document_text=document, clause_start=start,
                                        clause_end=start + len(raw_clause))["occurrences"][0]
    mapping = selector(document, TEXT, start)
    normalized = p.build_occurrence_receipt(TEXT, source_id="normalized-clause", document_id="other-doc-label",
                                            document_text=document, clause_start=mapping["start"],
                                            clause_end=mapping["end"], source_selector=mapping)["occurrences"][0]
    assert direct["occurrence_id"] != normalized["occurrence_id"]
    assert direct["document_occurrence_id"] == normalized["document_occurrence_id"]
    assert direct["exact_document_slice"] == normalized["exact_document_slice"]


def test_multiple_rules_and_duplicate_atoms_are_candidates_without_authority():
    atoms = ["within 10 days after receipt of notice"] * 2
    rows = [{"status": "compiled", "rule": rule(atoms)},
            {"status": "compiled", "rule": rule(atoms)},
            {"status": "abstain", "rule": None}]
    before = deepcopy(rows)
    result = p.build_occurrence_receipt(TEXT, source_id="c1", rule_rows=rows)
    occurrence = result["occurrences"][0]
    assert occurrence["candidate_rule_indices"] == [0, 1]
    assert [(row["rule_index"], row["temporal_atom_index"]) for row in occurrence["candidate_rule_associations"]] == [(0, 0), (0, 1), (1, 0), (1, 1)]
    assert occurrence["association_status"] == "multiple_lexical_candidates"
    assert result["counts"]["rows_without_rule"] == 1
    assert all(value is False for value in result["authority"].values())
    assert all(value is False for value in occurrence["authority"].values())
    assert rows == before
    p.validate_occurrence_receipt(result, source_text=TEXT, rule_rows=rows)


def test_excluded_parser_matches_and_no_rule_inventory_are_retained():
    text = "Registry shall file if the notice arrives within 10 days."
    rows = [{"status": "abstain", "rule": None}]
    result = p.build_occurrence_receipt(text, source_id="c1", rule_rows=rows)
    assert result["counts"]["excluded_parser_observations"] == 1
    assert result["parser_inventory"]["retained"] == []
    occurrence = result["occurrences"][0]
    assert occurrence["association_status"] == "parser_excluded"
    assert occurrence["parser_observations"][0]["containers"][0]["kind"] == "condition"
    assert occurrence["candidate_rule_indices"] == []
    assert result["rule_rows"][0]["status"] == "abstain"


def test_duplicate_physical_span_aggregates_observations():
    text = "The board shall act within 3 days after receipt or 7 days after notice whichever is earlier."
    result = p.build_occurrence_receipt(text, source_id="c1")
    assert result["counts"]["occurrences"] == 1
    assert len(result["occurrences"][0]["parser_observations"]) == 2
    assert {item["parser_fields"]["temporal_kind"] for item in result["occurrences"][0]["parser_observations"]} == {"whichever_is_earlier", "within_duration"}


def test_synthetic_partial_whitespace_boundary_is_preserved_but_not_translated(monkeypatch):
    # Exercise a future parser matching inside a whitespace run. The selector
    # authenticates the run replacement, not an invented point within that run.
    text = "Registry shall file  within 10 days."
    document = text.replace("file  within", "file\t \nwithin")
    inventory = parser.extract_temporal_constraint_inventory(text)
    inventory["retained"][0]["span"][0] -= 1
    monkeypatch.setattr(parser, "extract_temporal_constraint_inventory", lambda value: deepcopy(inventory))
    mapping = selector(document, text, 0)
    result = p.build_occurrence_receipt(text, source_id="c1", document_text=document,
                                        clause_end=len(document), source_selector=mapping)
    occurrence = result["occurrences"][0]
    assert occurrence["exact_source_slice"] == " within 10 days"
    assert occurrence["parser_observations"][0]["parser_fields"]["raw_text"] == "within 10 days"
    assert occurrence["document_translation_resolved"] is False
    assert occurrence["document_occurrence_id"] is None
    assert occurrence["temporal_start_in_document"] is None
    assert occurrence["temporal_end_in_document"] is None
    assert occurrence["exact_document_slice"] is None


def test_supplied_parser_inventory_is_regenerated():
    inventory = parser.extract_temporal_constraint_inventory(TEXT)
    p.build_occurrence_receipt(TEXT, source_id="c1", parser_inventory=inventory)
    inventory["retained"][0]["raw_text"] += " "
    with pytest.raises(ValueError, match="inventory differs"):
        p.build_occurrence_receipt(TEXT, source_id="c1", parser_inventory=inventory)


@pytest.mark.parametrize("mutation", ["duplicate", "offset", "slice", "source_hash", "authority", "coordinate", "row"])
def test_repaired_hash_cannot_authenticate_mutated_evidence(mutation):
    result = p.build_occurrence_receipt(TEXT, source_id="c1")
    if mutation == "duplicate":
        result["occurrences"].append(deepcopy(result["occurrences"][0]))
    elif mutation == "offset":
        result["occurrences"][0]["temporal_start_in_clause"] += 1
    elif mutation == "slice":
        result["occurrences"][0]["exact_source_slice"] = "within 20 days"
    elif mutation == "source_hash":
        result["source_binding"]["source_text_sha256"] = "0" * 64
    elif mutation == "authority":
        result["authority"]["owner_occurrence_resolved"] = True
    elif mutation == "coordinate":
        result["source_binding"]["clause_start_in_document"] = False
    else:
        result["rule_rows"].append({"rule_index": 0, "status": "compiled"})
    resign(result)
    with pytest.raises(ValueError):
        p.validate_occurrence_receipt(result, source_text=TEXT)


def test_digest_changed_source_and_caller_identity_rejected():
    result = p.build_occurrence_receipt(TEXT, source_id="c1", document_id="doc1")
    with pytest.raises(ValueError, match="regeneration"):
        p.validate_occurrence_receipt(result, source_text=TEXT.replace("10", "20"))
    with pytest.raises(ValueError, match="expected source ID"):
        p.validate_occurrence_receipt(result, source_text=TEXT, expected_source_id="c2")
    with pytest.raises(ValueError, match="expected document ID"):
        p.validate_occurrence_receipt(result, source_text=TEXT, expected_document_id="doc2")
    result["receipt_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="digest differs"):
        p.validate_occurrence_receipt(result, source_text=TEXT)


def test_exact_proposal_join_preserves_exclusions_issues_and_has_no_authority():
    text = TEXT + " Registry shall retain until the notice expires. Registry shall file after ."
    result = p.build_occurrence_receipt(text, source_id="c1")
    proposal = proposer.propose(text)
    inputs = deepcopy((result, proposal))
    joined = p.join_adapter_diagnostics(result, proposal, source_text=text)
    assert joined["counts"]["exact_coordinate_matches"] == 1
    assert joined["counts"]["unmatched_proposals"] == 1
    assert joined["counts"]["issues"] == 1
    assert len(joined["rows"]) == len(proposal["proposals"])
    assert joined["model_calls"] == 0
    assert all(value is False for value in joined["authority"].values())
    for row in joined["rows"]:
        assert all(value is False for value in row["authority"].values())
        assert row["adapter_eligibility"]["formula_gate"]["formula_admission"] is False
    assert (result, proposal) == inputs


def test_deferred_proposals_survive_join_without_prediction_rows():
    text = "Registry shall file after receipt of notice until the notice expires."
    result = p.build_occurrence_receipt(text, source_id="c1")
    proposal = proposer.propose(text)
    joined = p.join_adapter_diagnostics(result, proposal, source_text=text)
    assert joined["counts"]["excluded_proposals"] > 0
    assert len(joined["rows"]) == len(proposal["proposals"])
    assert joined["counts"]["unmatched_proposals"] == len(joined["rows"])


def test_trimmed_or_different_source_proposals_cannot_fuzzily_join():
    text = "Registry shall file within 10 days after receipt of notice   ."
    result = p.build_occurrence_receipt(text, source_id="c1")
    joined = p.join_adapter_diagnostics(result, proposer.propose(text), source_text=text)
    assert joined["counts"]["exact_coordinate_matches"] == 0
    assert joined["counts"]["unmatched_proposals"] == 1
    assert len(joined["unmatched_occurrence_ids"]) == 1
    with pytest.raises(ValueError, match="adapter source identity"):
        p.join_adapter_diagnostics(result, proposer.propose(text.replace("10", "20")), source_text=text)
    proposal = proposer.propose(text)
    proposal["proposals"][0]["query"]["proposed_time_span"]["char_start"] += 1
    with pytest.raises(ValueError):
        p.join_adapter_diagnostics(result, proposal, source_text=text)
