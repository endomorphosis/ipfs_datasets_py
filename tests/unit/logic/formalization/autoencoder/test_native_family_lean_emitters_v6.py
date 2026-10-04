"""Versioned dispatch handles only owned exact rich DCEC source reports."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters_v6 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v7 as training
from ipfs_datasets_py.logic.intent_ir.formalize import rich_grammar


def prepare(source="if Cache.py is not ready, agent must inspect Cache.py."):
    ast = rich_grammar.parse_instruction(source)
    report = training.prepare_family_training_targets_v7("intent_ir", document=ast, source_text=source)
    row = next(row for row in report["projections"] if row["projection_id"] == "rich-intent/dcec/v1")
    return report, row


@pytest.mark.parametrize("source,operators", [
    ("if Cache.py is not ready, agent must inspect Cache.py.", ["→", "¬", "O"]),
    ("agent must inspect Cache.py and reviewer may archive Report.py.", ["∧", "O", "P"]),
    ("agent must inspect Cache.py or reviewer must not delete Report.py.", ["∨", "O", "F"]),
    ("agent intends to inspect Cache.py.", ["I"]),
])
def test_original_renderer_retains_native_operator_interpretations(source, operators):
    report, row = prepare(source)
    before = deepcopy((report, row))
    lean, details = subject.emit_projection(row, report=report)
    assert all(operator in details["operators"] for operator in operators)
    assert "def formula_0" in lean and "axiom" not in lean
    assert details["strict_functional_receipt"]["passed"] is True
    assert details["strict_functional_receipt"]["lake_executed"] is False
    assert details["source_candidate_replay_required"] is True
    assert (report, row) == before


def test_intention_rendering_preserves_explicit_agent_carrier_and_actor_identity():
    report, row = prepare("Alice intends to inspect Cache.py.")
    lean, details = subject.emit_projection(row, report=report)
    root = details["strict_functional_receipt"]["native_ast"]
    agent = root["agent"]["function"]
    actor = root["formula"]["arguments"][0]["function"]
    assert agent["name"] == actor["name"]
    assert agent["return_sort"] == {"node_type": "Sort", "name": "agent", "parent": None}
    assert actor["return_sort"] == {"node_type": "Sort", "name": "Object", "parent": None}
    assert 'i.cognitive "I" (i.agent "' + agent["name"] + '")' in lean
    assert 'i.function "' + actor["name"] + '" []' in lean
    assert 'i.modal "cognitive:I"' not in lean


@pytest.mark.parametrize("field,value", [("logic_family", "first_order"), ("profile", "generic"),
    ("producer_id", "unowned"), ("source_digest", "wrong"), ("ready_for_training", False)])
def test_owned_route_failures_never_fall_through_to_previous_emitter(monkeypatch, field, value):
    report, row = prepare()
    row = deepcopy(row)
    row[field] = value
    monkeypatch.setattr(subject.previous, "emit_projection", lambda *a, **k: pytest.fail("owned route fell through"))
    with pytest.raises(subject.UnsupportedNativeLean):
        subject.emit_projection(row, report=report)


@pytest.mark.parametrize("change", ["domain", "membership", "duplicate", "none"])
def test_exact_domain_and_report_membership_required(change):
    report, row = prepare()
    if change == "domain":
        report["domain_id"] = "ui_ux_ir"
    elif change == "membership":
        report["projections"].remove(row)
    elif change == "duplicate":
        report["projections"].append(deepcopy(row))
    else:
        report = None
    with pytest.raises(subject.UnsupportedNativeLean):
        subject.emit_projection(row, report=report)


def test_native_parser_failure_never_falls_through(monkeypatch):
    report, row = prepare()
    row["payload"]["source"] += " trailing"
    monkeypatch.setattr(subject.previous, "emit_projection", lambda *a, **k: pytest.fail("parse failure fell through"))
    with pytest.raises(ValueError):
        subject.emit_projection(row, report=report)


def test_nonowned_projection_delegates_unchanged(monkeypatch):
    row, report = {"projection_id": "other-family/route"}, {"domain_id": "legal_ir"}
    calls = []

    def previous(value, **kwargs):
        calls.append((value, kwargs))
        return "unchanged", {"unchanged": True}

    monkeypatch.setattr(subject.previous, "emit_projection", previous)
    assert subject.emit_projection(row, report=report) == ("unchanged", {"unchanged": True})
    assert calls == [(row, {"report": report})]
