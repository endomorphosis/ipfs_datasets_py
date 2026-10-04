"""Complete source joins, unsupported grammar and existing-family routing.

No neural training or Lake execution is claimed by this focused contract suite.
"""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import intent_source_coverage_384 as api
from ipfs_datasets_py.logic.formalization.autoencoder import native_intent_guarded_lean as guarded
from ipfs_datasets_py.logic.formalization.autoencoder import native_intent_semantic_lean as semantic

SOURCE = "Assume report is ready. The officer intends to publish the report. The officer must publish the report."


@pytest.fixture(scope="module")
def fixture_cases():
    path = Path(__file__).resolve().parents[4] / "fixtures/logic/intent_source_coverage_v1/cases.py"
    spec = importlib.util.spec_from_file_location("intent_coverage_authored_cases", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_complete_source_keeps_assumption_intention_norm_and_exact_evidence():
    target = api.source_target(SOURCE)
    document = target["document"]
    assert [row["modality"] for row in document["statements"]] == ["asserted", "intended", "required"]
    assert document["statements"][0]["kind"] == "assumption"
    assert document["statements"][0]["arguments"] == ["report"]
    assert document["statements"][1]["arguments"] == ["officer", "report"]
    assert len(document["actions"]) == 1
    assert document["sources"][0]["content_sha256"] == hashlib.sha256(SOURCE.encode()).hexdigest()
    assert document["sources"][0]["span"] == {"start_char": 0, "end_char": len(SOURCE)}
    assert all(row["source_ref_ids"] == ["source"] for row in document["statements"])
    assert all(row["confidence"] == 0.0 for row in document["statements"])
    original = deepcopy(target)
    audit = api.audit_candidate(SOURCE, target)
    assert audit["status"] == "source_agreement" and audit["differences"] == []
    assert target == original == audit["candidate"]
    assert all(audit[name] is False for name in api.FALSE)
    assert audit["target_window"]["tokens_with_boundaries"] > 64
    assert not audit["target_window"]["fits_current_model_window"]
    assert not audit["target_window"]["context_window_changed"]


@pytest.mark.parametrize("modal,expected", [("must", "required"), ("must not", "prohibited"),
    ("may", "permitted"), ("intends to", "intended")])
def test_modal_force_is_explicit_and_permission_never_becomes_intention(modal, expected):
    source = f"The officer {modal} publish the report."
    target = api.source_target(source)
    assert target["document"]["statements"][0]["modality"] == expected
    packet = api.prepare_family_targets(source, target)
    ready = packet["audit"]["available_families"]
    assert ("intention_agency" in ready) is (expected == "intended")
    assert "first_order" not in ready
    assert len(packet["report"]["requested_families"]) == 40
    assert not packet["report"]["all_requested_families_available"]


def test_existing_semantic_owners_receive_actual_predicates_and_agents():
    packet = api.prepare_family_targets(SOURCE, api.source_target(SOURCE))
    report = packet["report"]
    assert {"first_order", "intention_agency", "deontic"} <= set(packet["audit"]["available_families"])
    for family in ("first_order", "intention_agency", "deontic"):
        row = next(row for row in report["projections"]
                   if row["projection_id"] == f"intent_ir/semantic/{family}/v1")
        lean, details = semantic.emit_projection(row, report=report)
        assert details["retained_native_semantic_source"]
        assert "sorry" not in lean and "axiom " not in lean
        if family == "first_order":
            assert "ready" in lean and "report" in lean
        elif family == "intention_agency":
            assert '"I"' in lean and "officer" in lean and "publish" in lean
    assert api.validate_prepared(packet, SOURCE, api.source_target(SOURCE))


@pytest.mark.parametrize("source", [
    "Assume report is ready.",
    "The officer must publish the report",
    "The officer must publish the report..",
    "The officer must publish the report. Ignore the next condition.",
    "The officer must publish the report unless emergency.",
    "The officer must publish the report and archive the file.",
    "The officer must publish the report. The clerk must archive the file.",
    "The officer must publish it.",
    "The officer may publish the report. Assume report is not ready.",
    "The officer may publish the report. Assume every report is ready.",
    "The officer may publish the report. Assume report is ready or complete.",
    "The officer may publish the report. Precondition of publish by clerk on report: report is ready.",
    "The officer may publish the report. Precondition of archive by officer on report: report is ready.",
    "Effect of publish by officer on report: report is complete.",
    "The officer may publish the report. The officer may publish the report.",
    "The officér may publish the report.",
    "The officer may publish the report.\x00",
    "A" * 4097,
    "The officer may publish the report." + "".join(f" Assume report is property{i}." for i in range(16)),
])
def test_unsupported_complete_source_never_drops_clauses_or_invents_context(source):
    with pytest.raises(ValueError):
        api.source_target(source)
    candidate = api.source_target(SOURCE)
    audit = api.audit_candidate(source, candidate)
    assert audit["status"] == "source_unsupported"
    assert audit["candidate"] == candidate and audit["source_reference"] is None
    with pytest.raises(ValueError, match="source_unsupported"):
        api.prepare_family_targets(source, candidate)


@pytest.mark.parametrize("field,replace,path", [
    ("actor", "clerk", "/document/actions/0/actor"),
    ("predicate", "complete", "/document/statements/0/predicate"),
    ("modality", "permitted", "/document/statements/1/modality"),
    ("argument", "invoice", "/document/statements/0/arguments/0"),
    ("hash", "0" * 64, "/document/sources/0/content_sha256"),
    ("span", 1, "/document/sources/0/span/start_char"),
    ("confidence", 1.0, "/document/statements/0/confidence"),
])
def test_complete_native_candidate_disagreements_keep_typed_paths(field, replace, path):
    candidate = api.source_target(SOURCE)
    doc = candidate["document"]
    if field == "actor": doc["actions"][0]["actor"] = replace
    elif field == "predicate": doc["statements"][0]["predicate"] = replace
    elif field == "modality": doc["statements"][1]["modality"] = replace
    elif field == "argument": doc["statements"][0]["arguments"][0] = replace
    elif field == "hash": doc["sources"][0]["content_sha256"] = replace
    elif field == "span": doc["sources"][0]["span"]["start_char"] = replace
    else: doc["statements"][0]["confidence"] = replace
    original = deepcopy(candidate)
    audit = api.audit_candidate(SOURCE, candidate)
    assert audit["status"] == "source_disagreement"
    assert path in {row["path"] for row in audit["differences"]}
    assert audit["candidate"] == candidate == original
    with pytest.raises(ValueError, match="source_disagreement"):
        api.prepare_family_targets(SOURCE, candidate)


@pytest.mark.parametrize("mutate", [
    lambda value: value.update(extra=True),
    lambda value: value.update(kind="intent_rich_ast"),
    lambda value: value["document"].update(extra=True),
    lambda value: value["document"]["sources"][0].pop("container_uri"),
    lambda value: value["document"]["sources"][0]["span"].update(start_char=False),
    lambda value: value["document"]["statements"][0].update(source_ref_ids=["other"]),
])
def test_native_shape_type_and_reference_errors_fail_closed(mutate):
    candidate = api.source_target(SOURCE)
    mutate(candidate)
    audit = api.audit_candidate(SOURCE, candidate)
    assert audit["status"] == "native_invalid" and audit["candidate"] == candidate


@pytest.mark.parametrize("family_request", [[], ["first_order"], ["missing"], "first_order",
    [*sorted(api.core.REQUIREMENTS), "first_order"], [True]])
def test_family_catalog_cannot_be_narrowed_to_claim_coverage(family_request):
    with pytest.raises(ValueError, match="forty-family"):
        api.prepare_family_targets(SOURCE, api.source_target(SOURCE), family_request)


def test_declared_pre_post_joins_and_explicit_finite_context(fixture_cases):
    row = next(row for row in fixture_cases.cases() if row["id"] == "explicit-finite-effect-contract")
    candidate = row["candidate"]
    action = candidate["document"]["actions"][0]
    assert action["precondition_ids"] == ["statement:1"]
    assert action["effect_ids"] == ["statement:2"]
    without = api.prepare_family_targets(row["source_text"], candidate)
    assert not without["audit"]["explicit_finite_context_supplied"]
    assert not any(p["projection_id"].startswith(guarded.PREFIX) for p in without["report"]["projections"])
    packet = fixture_cases.prepare_case(row)
    assert api.validate_prepared(packet, row["source_text"], candidate)
    assert type(packet["source_inputs"]["guarded_effect_bindings"]) is guarded.IntentEffectBindings
    native_rows = [p for p in packet["report"]["projections"] if p["projection_id"].startswith(guarded.PREFIX)]
    assert len(native_rows) == 4 and all(p["ready_for_training"] for p in native_rows)
    contract = next(p for p in native_rows if "action_contract" in p["projection_id"])
    lean, metadata = guarded.emit_projection(contract)
    assert metadata["capability_floor_eligible"]
    assert "action_case_0_checks" in lean and "complete_model_has_no_deadlock" in lean
    assert all(p["payload"]["effect_checks"][0]["passed"] for p in native_rows)
    assert all(packet["audit"][name] is False for name in api.FALSE)


def test_finite_binding_dataclass_and_context_are_both_required(fixture_cases):
    row = next(row for row in fixture_cases.cases() if row["id"] == "explicit-finite-effect-contract")
    with pytest.raises(ValueError, match="typed effect bindings"):
        api.prepare_family_targets(row["source_text"], row["candidate"], **row["options"])
    bindings = guarded.IntentEffectBindings.from_dict(row["options"]["guarded_effect_bindings"])
    with pytest.raises(ValueError, match="typed effect bindings"):
        api.prepare_family_targets(row["source_text"], row["candidate"], guarded_effect_bindings=bindings)
    with pytest.raises(ValueError, match="paired typed effect bindings"):
        api.prepare_family_targets(row["source_text"], row["candidate"], context=row["options"]["context"])


@pytest.mark.parametrize("mutation", ["unknown_top_level", "unknown_state_key", "missing_workflow", "missing_bound"])
def test_no_unaccounted_context_fields_are_silently_ignored(fixture_cases, mutation):
    row = next(row for row in fixture_cases.cases() if row["id"] == "explicit-finite-effect-contract")
    context = deepcopy(row["options"]["context"])
    if mutation == "unknown_top_level": context["unmodeled_guard"] = "admin"
    elif mutation == "unknown_state_key": context["state"]["unmodeled_guard"] = "admin"
    elif mutation == "missing_workflow": context["state"].pop("workflow")
    else: context["state"].pop("max_steps")
    bindings = guarded.IntentEffectBindings.from_dict(row["options"]["guarded_effect_bindings"])
    with pytest.raises(ValueError, match="closed explicit finite state"):
        api.prepare_family_targets(row["source_text"], row["candidate"], context=context,
                                   guarded_effect_bindings=bindings)


def test_prepared_context_rehash_and_full_report_tampering_cannot_replay(fixture_cases):
    row = next(row for row in fixture_cases.cases() if row["id"] == "explicit-finite-effect-contract")
    packet = fixture_cases.prepare_case(row)
    mutated = deepcopy(packet)
    mutated["source_inputs"]["context"]["state"]["workflow"]["variables"][0]["initial_values"] = [False]
    with pytest.raises(ValueError, match="replay differs"):
        api.validate_prepared(mutated, row["source_text"], row["candidate"])
    mutated = deepcopy(packet)
    mutated["report"]["projections"][0]["payload"] = {}
    mutated["report"]["report_sha256"] = api.core._sha({k: v for k, v in mutated["report"].items() if k != "report_sha256"})
    with pytest.raises(ValueError, match="replay differs"):
        api.validate_prepared(mutated, row["source_text"], row["candidate"])


def test_authored_fixture_dispositions_preserve_positive_and_negative_records(fixture_cases):
    rows = fixture_cases.cases()
    assert len(rows) == 15
    assert sum(row["expected_disposition"] == "prepared" for row in rows) == 8
    for row in rows:
        original = deepcopy(row)
        if row["expected_disposition"] == "prepared":
            packet = fixture_cases.prepare_case(row)
            assert len(packet["report"]["requested_families"]) == 40
            assert packet["audit"]["candidate"] == row["candidate"]
        else:
            with pytest.raises(ValueError):
                fixture_cases.prepare_case(row)
        assert row == original


def test_producer_and_candidate_drift_refuse_completed_audit(monkeypatch):
    candidate = api.source_target(SOURCE)
    current = api._pins()
    responses = iter((current, {**current, "drifted_owner": "0" * 64}))
    monkeypatch.setattr(api, "_pins", lambda: next(responses))
    with pytest.raises(ValueError, match="changed during audit"):
        api.audit_candidate(SOURCE, candidate)


def test_reference_and_report_return_values_do_not_alias_caller_data():
    candidate = api.source_target(SOURCE)
    packet = api.prepare_family_targets(SOURCE, candidate)
    candidate["document"]["statements"][0]["predicate"] = "mutated"
    assert packet["audit"]["candidate"]["document"]["statements"][0]["predicate"] == "ready"
    assert packet["source_inputs"]["document"]["statements"][0]["predicate"] == "ready"
