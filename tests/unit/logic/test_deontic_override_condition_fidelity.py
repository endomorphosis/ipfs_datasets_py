"""Source fidelity of fronted conditions across dotted precedence citations."""

from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_record_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


TEXT = "Subject to approval, notwithstanding section 5.01.020, the Director may issue a variance."


def element(*, prefix="", suffix="", connector="Subject to", condition="approval"):
    sentence = TEXT.replace("Subject to approval", connector + " " + condition)
    source = prefix + sentence + suffix
    support = "the Director may issue a variance"
    support_start = source.index(support, len(prefix))
    condition_start = len(prefix) + len(connector) + 1
    override_start = source.index("notwithstanding", len(prefix))
    citation_start = source.index("section 5.01.020", override_start)
    return {
        "source_id": "fictional:variance", "document_id": "fictional:document",
        "text": source, "support_text": support,
        "source_span": [0, len(source)],
        "support_span": [support_start, support_start + len(support)],
        "subject": ["Director"], "action": ["issue a variance"],
        "norm_type": "permission", "deontic_operator": "P",
        "condition_details": [{
            "type": "condition", "clause_type": connector.lower().replace(" ", "_"),
            "raw_text": condition, "normalized_text": condition,
            "span": [condition_start, condition_start + len(condition)],
            "clause_span": [len(prefix), condition_start + len(condition) + 1],
        }],
        "override_clause_details": [{
            "type": "override", "clause_type": "notwithstanding",
            "raw_text": "section 5.01.020", "normalized_text": "section 5.01.020",
            "span": [citation_start, citation_start + len("section 5.01.020")],
            "clause_span": [override_start, citation_start + len("section 5.01.020") + 1],
        }],
    }


def test_parser_condition_survives_and_blocks_pure_precedence_resolution():
    row = extract_normative_elements(TEXT)[0]
    before = deepcopy(row)
    norm = LegalNormIR.from_parser_element(row)
    record = build_deontic_formula_record_from_ir(norm)
    assert norm.conditions == [{**row["condition_details"][0], "value": "approval"}]
    assert norm.conditions[0]["span"] == [11, 19]
    assert norm.overrides[0]["value"] == "section 5.01.020"
    assert record["formula"] == "P(∀x (Director(x) ∧ Approval(x) → IssueVariance(x)))"
    assert record["proof_ready"] is False
    assert record["deterministic_resolution"] == {}
    assert "override_clause_requires_precedence_review" in record["blockers"]
    assert "cross_reference_requires_resolution" in record["blockers"]
    assert row == before


@pytest.mark.parametrize("connector,condition", [
    ("Subject to", "written consent"), ("Provided that", "funding is available"),
    ("If", "approval is granted"), ("When", "approval is granted"),
    ("Where", "approval is granted"),
])
def test_exact_fronted_conditions_are_not_limited_to_approval(connector, condition):
    row = element(prefix="Earlier rule.\n", connector=connector, condition=condition)
    norm = LegalNormIR.from_parser_element(row)
    assert norm.conditions[0]["value"] == condition
    assert norm.conditions[0]["span"] == row["condition_details"][0]["span"]
    assert norm.support_span.to_list() == row["support_span"]
    assert norm.source_id == row["source_id"]


def test_other_sentence_condition_is_not_attached_and_original_order_is_preserved():
    prefix = "Subject to review, the Clerk may inspect the file. "
    row = element(prefix=prefix, suffix=" Subject to consent, the Treasurer may pay.")
    prior = {"type": "condition", "clause_type": "subject_to", "raw_text": "review",
             "normalized_text": "review", "span": [11, 17], "clause_span": [0, 18]}
    row["condition_details"].insert(0, prior)
    norm = LegalNormIR.from_parser_element(row)
    assert [record["value"] for record in norm.conditions] == ["approval"]
    assert norm.conditions[0]["span"] == row["condition_details"][1]["span"]


@pytest.mark.parametrize("key", ["span", "clause_span", "source_span", "support_span"])
@pytest.mark.parametrize("bad_bound", [True, 11.0, "11", -1, 10000])
def test_invalid_condition_intervals_do_not_gain_admission(key, bad_bound):
    row = element()
    detail = row["condition_details"][0]
    detail[key] = [bad_bound, detail["span"][1]]
    assert LegalNormIR.from_parser_element(row).conditions == []


@pytest.mark.parametrize("alias", ["source_span", "support_span"])
def test_exact_body_span_aliases_are_preserved(alias):
    row = element()
    detail = row["condition_details"][0]
    detail[alias] = list(detail["span"])
    assert LegalNormIR.from_parser_element(row).conditions[0][alias] == detail["span"]


@pytest.mark.parametrize("key", ["raw_text", "normalized_text", "value", "text"])
def test_conflicting_condition_text_aliases_do_not_gain_admission(key):
    row = element()
    row["condition_details"][0][key] = "unrelated approval"
    assert LegalNormIR.from_parser_element(row).conditions == []


@pytest.mark.parametrize("key", ["source_id", "document_id", "parent_source_id", "canonical_citation"])
def test_other_source_condition_is_not_rescued(key):
    row = element()
    row["condition_details"][0][key] = "other-document"
    assert LegalNormIR.from_parser_element(row).conditions == []


@pytest.mark.parametrize("change", ["source_text", "support_text", "support_span", "source_span"])
def test_mismatched_source_view_does_not_widen_scope(change):
    row = element()
    if change == "source_text":
        row[change] = "X" + row["text"][1:]
    elif change == "support_text":
        row[change] = row[change].replace("Director", "Treasury")
    elif change == "support_span":
        # Keep the old sentence scope identical while testing that the new
        # path refuses legacy numeric coercion of the exact support interval.
        row[change] = [float(row[change][0]), row[change][1]]
    else:
        row[change] = [True, row[change][1]]
    assert LegalNormIR.from_parser_element(row).conditions == []


@pytest.mark.parametrize("change", ["raw_text", "span", "clause_span", "source_span", "document_id"])
def test_invalid_override_cannot_authenticate_citation_periods(change):
    row = element()
    detail = row["override_clause_details"][0]
    if change == "raw_text":
        detail[change] = "section 9.99.999"
    elif change == "document_id":
        detail[change] = "another-document"
    else:
        detail[change] = [False, detail["span"][1]]
    assert LegalNormIR.from_parser_element(row).conditions == []


@pytest.mark.parametrize("separator", [". ", "; ", "! ", "? ", "\n"])
def test_real_boundaries_between_condition_and_support_are_not_crossed(separator):
    row = element()
    old = ", notwithstanding"
    replacement = separator + "notwithstanding"
    text = row["text"].replace(old, replacement)
    delta = len(replacement) - len(old)
    row["text"] = text
    row["source_span"][1] += delta
    row["support_span"] = [value + delta for value in row["support_span"]]
    row["condition_details"][0]["clause_span"][1] = text.index("notwithstanding")
    for key in ("span", "clause_span"):
        row["override_clause_details"][0][key] = [
            value + delta for value in row["override_clause_details"][0][key]
        ]
    assert LegalNormIR.from_parser_element(row).conditions == []


@pytest.mark.parametrize("opening,closing", [('"', '"'), ("“", "”"), ("(", ")"), ("[", "]")])
def test_quoted_or_bracketed_condition_is_not_rescued(opening, closing):
    row = element(prefix=opening, suffix=closing)
    assert LegalNormIR.from_parser_element(row).conditions == []


def test_spanless_legacy_records_keep_existing_scope_contract():
    row = element()
    row["condition_details"] = []
    row["conditions"] = ["caller supplied condition"]
    assert LegalNormIR.from_parser_element(row).conditions == [{"value": "caller supplied condition"}]


@pytest.mark.parametrize("bridge", [". ", "; ", "\n", '"quoted" ', "the Clerk may inspect, "])
def test_separate_clause_after_valid_override_cannot_attach_prior_condition(bridge):
    row = element()
    start = row["support_span"][0]
    row["text"] = row["text"][:start] + bridge + row["text"][start:]
    row["source_span"][1] += len(bridge)
    row["support_span"] = [value + len(bridge) for value in row["support_span"]]
    assert LegalNormIR.from_parser_element(row).conditions == []


def test_source_interval_cannot_authorize_condition_outside_its_bounds():
    row = element()
    row["source_span"][0] = row["support_span"][0]
    assert LegalNormIR.from_parser_element(row).conditions == []


def test_multiple_exact_conditions_keep_caller_order_without_source_mutation():
    prefix = "If funding is available, "
    row = element(prefix=prefix)
    row["condition_details"].insert(0, {
        "type": "condition", "clause_type": "if", "raw_text": "funding is available",
        "normalized_text": "funding is available", "span": [3, 23], "clause_span": [0, 24],
    })
    before = deepcopy(row)
    assert [item["value"] for item in LegalNormIR.from_parser_element(row).conditions] == [
        "funding is available", "approval"
    ]
    assert row == before
