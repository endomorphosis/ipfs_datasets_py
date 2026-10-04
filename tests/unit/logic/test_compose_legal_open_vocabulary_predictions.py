"""Bounded integration plans retain declared occurrences, independent of scores."""
from copy import deepcopy
import hashlib

import pytest

from scripts.ops.legal_ir import compose_legal_open_vocabulary_predictions as integrate


def sources():
    return [{"id": f"synthetic-{i}", "source_text": text, "source_sha256": hashlib.sha256(text.encode()).hexdigest()}
            for i, text in enumerate(("Lark must retain books.", "Wren may publish records."))]


def prediction(source, actor, action, obj, modality):
    rule = {"actor": actor, "action": action, "object": obj, "modality": modality,
            "conditions": [], "exceptions": [], "temporal": []}
    facets = {}
    for field in integrate.compose.SPAN_FIELDS:
        atom = rule[field] if field in ("actor", "action", "object") else None
        start = source["source_text"].find(atom) if atom else None
        facets[field] = {"present": bool(atom), "char_start": start, "char_end": start + len(atom) if atom else None,
                         "text": atom}
    return {"status": "decoded", "source_sha256": source["source_sha256"], "canonical_ir": {"rules": [rule]},
        "span_diagnostics": {"facets": facets}, "target_access": False, "teacher_forcing": False}


def test_fixed_document_occurrences_survive_composition():
    rows = sources()
    document = integrate.source_plans(rows, document_count=1)[0]
    predictions = {rows[0]["id"]: prediction(rows[0], "Lark", "retain", "books", "O"),
                   rows[1]["id"]: prediction(rows[1], "Wren", "publish", "records", "P")}
    result = integrate.compose_document(document, predictions)
    assert result["rule_count"] == 3
    assert result["source_rule_list"][0] == result["source_rule_list"][2]
    assert result["occurrences"][0]["clause_char_start"] < result["occurrences"][2]["clause_char_start"]
    assert result["segmentation_learned"] is result["qualified"] is False


def test_missing_or_abstained_prediction_cannot_drop_a_declared_rule():
    rows = sources()
    document = integrate.source_plans(rows, document_count=1)[0]
    with pytest.raises(ValueError, match="missing"):
        integrate.compose_document(document, {})
    predictions = {rows[0]["id"]: prediction(rows[0], "Lark", "retain", "books", "O"),
                   rows[1]["id"]: {"status": "abstained"}}
    with pytest.raises(ValueError, match="decoded"):
        integrate.compose_document(document, predictions)


@pytest.mark.parametrize("change,match", [
    (lambda rows: rows[0].update(source_sha256="0" * 64), "hash"),
    (lambda rows: rows[1].update(id=rows[0]["id"]), "duplicate"),
])
def test_source_identity_and_bytes_are_bound(change, match):
    rows = deepcopy(sources())
    change(rows)
    with pytest.raises(ValueError, match=match):
        integrate.source_plans(rows, document_count=1)


def test_source_panel_bounds_and_prediction_count_fail_closed():
    with pytest.raises(ValueError, match="bounded"):
        integrate.source_plans(sources(), document_count=12)
    document = integrate.source_plans(sources(), document_count=1)[0]
    document["clause_source_ids"].pop()
    with pytest.raises(ValueError, match="complete"):
        integrate.compose_document(document, {})


@pytest.mark.parametrize("field,value", [("arm", "source_only"), ("seed", 1730), ("dimension", 384)])
def test_head_names_cannot_hide_false_model_attribution(field, value):
    plan = {"arms": {"native768": 768}, "seeds": [1729]}
    heads = [{"name": "native768-1729", "arm": "native768", "seed": 1729, "dimension": 768}]
    integrate.validate_heads(plan, heads)
    heads[0][field] = value
    with pytest.raises(ValueError, match="attribution"):
        integrate.validate_heads(plan, heads)
