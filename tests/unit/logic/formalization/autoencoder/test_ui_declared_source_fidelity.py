"""Declared UI source equality and exact existing semantic-owner routing."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import ui_declared_source_fidelity as api
from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v5 as projection
from ipfs_datasets_py.logic.formalization.autoencoder import native_ui_bounded_event_calculus as events


def cases():
    path = Path(__file__).resolve().parents[4] / "fixtures/logic/ui_declared_source_v1/cases.py"
    spec = importlib.util.spec_from_file_location("ui_declared_fixture_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.cases()


def source_changed(row, modify):
    row = deepcopy(row)
    source = json.loads(row["source_text"])
    modify(source)
    row["source_text"] = json.dumps(source, sort_keys=True, separators=(",", ":"))
    return row


@pytest.mark.parametrize("index", range(3))
def test_declared_semantics_route_to_existing_native_owners_and_exact_replay(index):
    row = cases()[index]
    original = deepcopy(row)
    prepared = api.prepare_family_targets(row["source_text"], row["candidate"])
    assert row == original
    audit = prepared["source_audit"]
    assert audit["status"] == "source_agreement" and audit["exact"]
    assert audit["candidate"] == row["candidate"]
    assert audit["source_sha256"] == hashlib.sha256(row["source_text"].encode()).hexdigest()
    assert all(audit[key] is False for key in api.FALSE)
    assert audit["model_inference_executed"] is False
    report = prepared["report"]
    assert len(report["requested_families"]) == 40
    assert prepared["audit"]["available_families"] == ["event_calculus", "first_order", "frame_logic", "transition_system"]
    assert len(prepared["missing_context_requirements"]) == 36
    assert projection.validate_family_training_report(report, **prepared["source_inputs"])
    binding = report["bounded_event_source_binding"]
    assert binding["source_text"] == row["source_text"] and binding["candidate"] == row["candidate"]
    for name in ("behavior", "guard", "event"):
        assert binding[name + "_interpretation"]["source_sha256"] == audit["source_sha256"]
        assert binding[name + "_interpretation"]["candidate_sha256"] == events.digest(row["candidate"])
    archived, = report["superseded_bounded_event_observations"]
    assert archived["active_for_training"] is False and archived["ready_for_training"] is False
    assert archived["replacement_projection_id"] == events.PROJECTION_ID


@pytest.mark.parametrize("index", range(3, 11))
def test_rejected_fixtures_remain_in_denominator_with_original_candidate(index):
    row = cases()[index]
    original = deepcopy(row)
    with pytest.raises(ValueError, match=row["expected_reason"]):
        api.prepare_family_targets(row["source_text"], row["candidate"])
    assert row == original


@pytest.mark.parametrize("mutate", [
    lambda value: value.update(title="different"),
    lambda value: value["components"][0].update(role="textbox"),
    lambda value: value["states"].reverse(),
    lambda value: value["transitions"][0].update(event_id="different"),
])
def test_complete_candidate_comparison_never_fills_or_reorders(mutate):
    row = cases()[0]
    mutate(row["candidate"]["document"])
    before = deepcopy(row["candidate"])
    audit = api.audit_candidate(row["source_text"], row["candidate"])
    assert audit["status"] in {"source_disagreement", "native_invalid"}
    assert audit["differences"] and row["candidate"] == before and audit["candidate"] == before


@pytest.mark.parametrize("edit", [
    lambda s: s.update(extra="unknown"),
    lambda s: s["document"].pop("title"),
    lambda s: s["interpretations"].pop("event"),
    lambda s: s["interpretations"]["behavior"].update(source_sha256="0" * 64),
    lambda s: s["interpretations"]["guard"].pop("parameter_update_semantics"),
    lambda s: s["interpretations"]["guard"]["variables"][0].update(initial_value=1),
    lambda s: s["interpretations"]["event"].pop("origin"),
    lambda s: s["interpretations"]["event"].pop("policy"),
    lambda s: s["interpretations"].update(guard=None),
])
def test_missing_defaults_unknown_keys_types_and_self_binding_fields_rejected(edit):
    row = source_changed(cases()[0], edit)
    audit = api.audit_candidate(row["source_text"], row["candidate"])
    assert audit["status"] == "source_unsupported" and audit["source_error"]
    assert audit["source_text"] == row["source_text"]
    with pytest.raises(ValueError, match="source agreement"):
        api.prepare_family_targets(row["source_text"], row["candidate"])


@pytest.mark.parametrize("source", ['{"schema":1,"schema":2}', '{"schema":NaN}', '{"schema":Infinity}',
    '{"schema":"ui-declared-source/v9"}', '{', 'Not a complete declared document'])
def test_duplicate_invalid_and_unsupported_json_stays_explicit(source):
    audit = api.audit_candidate(source, cases()[0]["candidate"])
    assert audit["status"] == "source_unsupported" and audit["source_text"] == source


def test_no_interpretations_does_not_invent_behavior_or_event_semantics():
    row = source_changed(cases()[0], lambda s: s.update(interpretations={"behavior": None, "guard": None, "event": None}))
    prepared = api.prepare_family_targets(row["source_text"], row["candidate"])
    assert prepared["audit"]["available_families"] == ["first_order", "frame_logic"]
    assert len(prepared["missing_context_requirements"]) == 38
    assert not any(p["logic_family"] in {"transition_system", "event_calculus"} for p in prepared["report"]["projections"])


def test_semantically_invalid_declared_event_is_not_hidden_by_document_agreement():
    row = cases()[3]
    audit = api.audit_candidate(row["source_text"], row["candidate"])
    assert audit["source_agreement"] and audit["interpretation_semantics_checked"] is False
    with pytest.raises(ValueError, match="unknown or extra"):
        api.prepare_family_targets(row["source_text"], row["candidate"])


def test_full_source_bytes_bind_even_whitespace_without_rewriting_candidate():
    row = cases()[0]
    first = api.prepare_family_targets(row["source_text"], row["candidate"])
    second = api.prepare_family_targets("\n " + row["source_text"] + " \n", row["candidate"])
    assert first["source_audit"]["candidate"] == second["source_audit"]["candidate"]
    assert first["source_audit"]["source_sha256"] != second["source_audit"]["source_sha256"]
    assert first["report"]["source_digest"] != second["report"]["source_digest"]


def test_over_bound_json_rejected_without_expanding_context():
    with pytest.raises(ValueError, match="bounded"):
        api.audit_candidate("x" * (api.MAX_BYTES + 1), cases()[0]["candidate"])
    assert api.MAX_BYTES == 65536
