"""Additional projections use actual native owners and exact typed replay."""
from copy import deepcopy
from dataclasses import replace
import importlib.util
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v2 as api
from ipfs_datasets_py.logic.formalization.autoencoder import family_training as v1
from ipfs_datasets_py.logic.formalization.autoencoder.ui_training_inputs import prepare_ui_training_row
from ipfs_datasets_py.logic.software_verification.authorization import (
    AuthorizationIR, AuthorizationPrincipal, AuthorizationFact, AuthorizationAtom,
    AuthorizationTerm, PredicateSignature,
)
from ipfs_datasets_py.logic.software_verification.temporal import TemporalFormula
from ipfs_datasets_py.logic.software_verification.trace import TraceIR, ObservationValue
from ipfs_datasets_py.logic.software_verification.transitions import StateTransitionIR


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


HERE = Path(__file__).resolve().parent
fixtures = _load("native_family_v1_fixtures", HERE / "test_family_training.py")
concurrency_fixtures = _load("native_supplemental_concurrency_fixtures", HERE.parent.parent / "software_verification/test_concurrency_refinement.py")
protocol_fixtures = _load("native_supplemental_protocol_fixtures", HERE.parent.parent / "software_verification/test_protocol.py")
binding = fixtures.binding


def untimed_row():
    """Explicit authored untimed variant, separate from the old timed fixture."""
    row = fixtures.native_row()
    row["provenance"]["dataset"] = "authored-untimed-ui-state-fixtures"
    row["behavior"]["transitions"][0].pop("timeout_ms")
    return row


def policy(source):
    mapped = {"source_ref_ids": (source.ref_id,)}
    return AuthorizationIR(sources=(source,), principals=(AuthorizationPrincipal("principal:owner", "Owner", **mapped),),
        trust_root_principal_ids=("principal:owner",),
        predicates=(PredicateSignature("predicate:read", "can_read", 1, ("principal",), **mapped),),
        facts=(AuthorizationFact("fact:read", AuthorizationAtom("predicate:read", (AuthorizationTerm.constant("principal:owner", "principal"),)), **mapped),))


def _inventory(report):
    return {row["family_id"]: row for row in report["family_inventory"]}


@pytest.mark.parametrize("domain", v1.DOMAINS)
def test_v2_catalog_inventories_all40_without_promoting_profiles(domain):
    inventory = _inventory(api.family_training_catalog_v2(domain))
    assert len(inventory) == 40
    assert not any(row["ready_for_training"] for row in inventory.values())
    assert "smt" not in inventory and "tla_plus" not in inventory
    assert inventory["authorization"]["projection_adapter_available"]
    if domain != "intent_ir":
        assert "not_Horn" in inventory["horn_chc"]["frontier"]


def test_ui_untimed_state_and_trace_are_actual_native_views_with_replay():
    row = untimed_row()
    report = api.prepare_family_training_targets_v2("ui_ux_ir", ui_training_row=row)
    assert len(report["projections"]) == 8
    assert {p["logic_family"] for p in report["projections"]} == {
        "frame_logic", "event_calculus", "dcec", "tdfol", "transition_system", "temporal"}
    assert api.validate_family_training_report_v2(report, ui_training_row=row) == report
    state = next(p for p in report["projections"] if p["projection_id"] == "ui_ux_ir/declared_state/native/v2")
    native = StateTransitionIR.from_dict(state["payload"]["native_document"])
    assert len(native.actions) == 1
    assert native.actions[0].attributes.to_dict()["event_id"] == "click:delete"
    assert not native.metadata.to_dict()["actual_event_occurrence_asserted"]
    assert native.metadata.to_dict()["guard_effect_timeout_loss"] is False
    assert state["validation"][0]["details"]["exact"]
    tla = next(p for p in report["projections"] if p["profile"] == "tla_plus" and p["producer_id"].endswith("tla.compiler"))
    assert "---- MODULE DeclaredUIState ----" in tla["payload"]["model_text"]
    assert not tla["validation"][0]["details"]["model_checker_executed"]
    assert not tla["validation"][0]["details"]["syntax_checker_executed"]
    assert tla["validation"][0]["details"]["native_generated_properties_are_not_source_obligations"]
    assert tla["payload"]["bounds"]["max_steps"] == 64
    assert any(loss["construct"] == "finite_step_bound" and loss["preservation"] == "bounded"
               for loss in tla["payload"]["losses"])
    assert tla["payload"]["liveness_properties"] == ["BoundedProgress"]
    assert "native_BoundedProgress_is_not_a_declared_UI_requirement" in tla["qualification_gaps"]
    assert report["source_binding_scope"]["basis"] == "canonical_UI_training_declaration"
    assert not report["all_requested_families_available"]


def test_ui_finite_prefix_preserves_events_and_never_asserts_absent_atoms_or_completion():
    report = api.prepare_family_training_targets_v2("ui_ux_ir", ui_training_row=fixtures.native_row())
    target = next(p for p in report["projections"] if p["projection_id"] == "ui_ux_ir/event_prefix/native/v2")
    trace = TraceIR.from_dict(target["payload"]["native_document"])
    assert trace.kind.value == "finite_prefix" and not trace.is_complete
    assert trace.primary_clock.unit.value == "millisecond"
    assert trace.events[0].time.value.numerator == 1
    assert trace.events[0].payload.to_dict()["supplied_UI_event"]["provenance"] == "synthetic"
    assert trace.observation_policy.observe(trace.events[0], "unobserved") is ObservationValue.UNKNOWN
    assert not trace.events[0].propositions
    assert not trace.metadata.to_dict()["independently_attested"]
    assert any(row["reason"] == "UI_timeout_semantics_not_lowered" for row in report["frontier"])
    assert not _inventory(report)["transition_system"]["ready_for_training"]


@pytest.mark.parametrize("field,value,reason", [
    ("guard_id", "guard:authenticated", "UI_guards_and_effects_require_typed_semantics"),
    ("effect_ids", ("effect:write",), "UI_guards_and_effects_require_typed_semantics"),
    ("timeout_ms", 10, "UI_timeout_semantics_not_lowered"),
    ("priority", 1, "UI_priority_or_recovery_semantics_not_lowered"),
    ("retryable", True, "UI_priority_or_recovery_semantics_not_lowered"),
    ("undoable", True, "UI_priority_or_recovery_semantics_not_lowered"),
    ("cancelable", False, "UI_priority_or_recovery_semantics_not_lowered"),
])
def test_ui_unlowered_semantics_refuse_the_state_target(field, value, reason):
    document = prepare_ui_training_row(untimed_row()).document
    edge = replace(document.behavior_model.transitions[0], **{field: value})
    document = replace(document, behavior_model=replace(document.behavior_model, transitions=(edge,)))
    report = api.prepare_family_training_targets_v2("ui_ux_ir", document=document,
        requested_families=["transition_system"])
    assert not report["projections"] and not report["ready_for_training"]
    assert any(row["reason"] == reason for row in report["frontier"])


def test_ui_parallel_state_and_nonmonotonic_events_are_explicit_frontiers():
    document = prepare_ui_training_row(untimed_row()).document
    state = replace(document.behavior_model.states[0], parallel_region="region:one")
    document = replace(document, behavior_model=replace(document.behavior_model, states=(state, *document.behavior_model.states[1:])),
        events=(replace(document.events[0], timestamp_ms=2), document.events[0]))
    report = api.prepare_family_training_targets_v2("ui_ux_ir", document=document,
        requested_families=["transition_system", "temporal"])
    assert not report["projections"]
    reasons = {row["reason"] for row in report["frontier"]}
    assert {"UI_parallel_regions_require_explicit_product_state_semantics",
        "exact_nondecreasing_UI_event_timestamps_required"} <= reasons


@pytest.mark.parametrize("field,value", [("guard_id", "guard:authenticated"), ("effect_ids", ("effect:write",)),
    ("retryable", True), ("undoable", True)])
def test_v2_excludes_known_lossy_legacy_EC_targets_without_erasing_payload(field, value):
    document = prepare_ui_training_row(untimed_row()).document
    edge = replace(document.behavior_model.transitions[0], **{field: value})
    document = replace(document, behavior_model=replace(document.behavior_model, transitions=(edge,)))
    before = v1.prepare_family_training_targets("ui_ux_ir", document=document)
    report = api.prepare_family_training_targets_v2("ui_ux_ir", document=document)
    old = next(target for target in before["projections"] if target["logic_family"] == "event_calculus")
    new = next(target for target in report["projections"] if target["logic_family"] == "event_calculus")
    assert old["ready_for_training"] and not new["ready_for_training"]
    assert new["payload"] == old["payload"]
    assert any(field in omitted["fields"] for omitted in new["validation"][-1]["details"]["omitted_declared_fields"])
    assert not _inventory(report)["event_calculus"]["ready_for_training"]
    assert _inventory(report)["frame_logic"]["ready_for_training"]
    assert api.validate_family_training_report_v2(report, document=document) == report


def test_simple_legacy_EC_view_remains_ready_under_v2_loss_gate():
    report = api.prepare_family_training_targets_v2("ui_ux_ir", ui_training_row=untimed_row())
    target = next(target for target in report["projections"] if target["logic_family"] == "event_calculus")
    assert target["ready_for_training"]
    assert not any(check["validator_id"] == "UI_v2_legacy_EC_scope" for check in target["validation"])


@pytest.mark.parametrize("domain", ["intent_ir", "ui_ux_ir", "legal_ir"])
def test_source_bound_native_authorization_is_one_family_not_datalog_or_horn(domain):
    if domain == "intent_ir":
        text = "agent must inspect cache."
        kwargs = dict(document=fixtures.parse_instruction(text), source_text=text)
    elif domain == "ui_ux_ir":
        kwargs = dict(ui_training_row=untimed_row())
    else:
        kwargs = dict(document=fixtures.legal_document(), source_text="Owner may read notice.")
    source = api.supplemental_source_ref(domain, **kwargs)
    model = policy(source)
    supplied = [api.TypedFamilyEvidence(model, source)]
    report = api.prepare_family_training_targets_v2(domain, supplemental_inputs=supplied,
        requested_families=["authorization", "horn_chc"], **kwargs)
    targets = [row for row in report["projections"] if "/supplemental/" in row["projection_id"]]
    assert len(targets) == 1 and targets[0]["logic_family"] == "authorization"
    assert targets[0]["profile"] == "datalog"
    assert AuthorizationIR.from_dict(targets[0]["payload"]["native_document"]).to_dict() == model.to_dict()
    assert api.validate_family_training_report_v2(report, supplemental_inputs=supplied, **kwargs) == report
    assert not targets[0]["proof_authority"]


def test_security_source_bound_policy_uses_exact_codeunit_identity(binding):
    unit, _ = binding
    kwargs = dict(code_unit=unit, source_bytes=fixtures.BODY)
    source = api.supplemental_source_ref("security_ir", **kwargs)
    assert source.ref_id == unit.cid and source.content_cid == unit.payload["body_cid"]
    supplied = [api.TypedFamilyEvidence(policy(source), source)]
    report = api.prepare_family_training_targets_v2("security_ir", supplemental_inputs=supplied, **kwargs)
    assert {row["logic_family"] for row in report["projections"]} == {"authorization"}
    assert api.validate_family_training_report_v2(report, supplemental_inputs=supplied, **kwargs) == report
    with pytest.raises(ValueError, match="SHA differs"):
        api.prepare_family_training_targets_v2("security_ir", supplemental_inputs=supplied,
            code_unit=unit, source_bytes=fixtures.BODY + b"\n")


@pytest.mark.parametrize("kind,factory,family", [
    ("concurrency", concurrency_fixtures._producer_consumer, "concurrency"),
    ("refinement", concurrency_fixtures._counter_refinement, "refinement"),
    ("protocol", protocol_fixtures._document, "cryptographic_protocol"),
])
def test_security_existing_typed_owners_publish_real_omitted_native_families(binding, kind, factory, family):
    unit, _ = binding
    kwargs = dict(code_unit=unit, source_bytes=fixtures.BODY)
    source = api.supplemental_source_ref("security_ir", **kwargs)
    model = factory()
    if kind == "protocol":
        # Rebind authored fixture provenance through the actual native owner;
        # this does not claim the source code implements this declared model.
        wire = model.to_dict()
        old_ref = wire["sources"][0]["ref_id"]
        def rebound(value):
            if isinstance(value, dict):
                if "ref_id" in value and "content_sha256" in value:
                    return source.to_dict()
                result = {key: rebound(item) for key, item in value.items()}
                if "start_byte" in result and "end_byte" in result:
                    result.update(start_byte=0, end_byte=len(fixtures.BODY))
                return result
            if isinstance(value, list):
                return [rebound(item) for item in value]
            return source.ref_id if value == old_ref else value
        wire = rebound(wire); wire["document_id"] = ""
        model = type(model).from_dict(wire)
    supplied = [api.TypedFamilyEvidence(model, source)]
    report = api.prepare_family_training_targets_v2("security_ir", supplemental_inputs=supplied,
        requested_families=[family], **kwargs)
    assert len(report["projections"]) == 1
    target = report["projections"][0]
    assert target["logic_family"] == family and target["ready_for_training"]
    assert type(model).from_dict(target["payload"]["native_document"]).to_dict() == model.to_dict()
    assert api.validate_family_training_report_v2(report, supplemental_inputs=supplied, **kwargs) == report
    assert not target["source_semantics_verified"]


def test_ui_program_and_contract_require_supplied_native_models_not_action_labels():
    row = untimed_row()
    source = api.supplemental_source_ref("ui_ux_ir", ui_training_row=row)
    program, contract = fixtures._security.program(source), fixtures._security.contract(source)
    supplied = [api.TypedFamilyEvidence(program, source), api.TypedFamilyEvidence(contract, source)]
    report = api.prepare_family_training_targets_v2("ui_ux_ir", ui_training_row=row,
        supplemental_inputs=supplied, requested_families=["program"])
    assert len(report["projections"]) == 2 and report["all_requested_families_available"]
    assert api.validate_family_training_report_v2(report, ui_training_row=row, supplemental_inputs=supplied) == report
    absent = api.prepare_family_training_targets_v2("ui_ux_ir", ui_training_row=row, requested_families=["program"])
    assert not absent["projections"]
    unbound = api.prepare_family_training_targets_v2("ui_ux_ir", ui_training_row=row,
        supplemental_inputs=[supplied[1]], requested_families=["program"])
    assert not unbound["projections"]
    assert any(p["reason"] == "supplemental_contract_requires_matching_native_program" for p in unbound["frontier"])


def test_legal_explicit_temporal_formula_uses_real_LTL_bridge_without_text_inference():
    kwargs = dict(document=fixtures.legal_document(), source_text="Registry observation.")
    source = api.supplemental_source_ref("legal_ir", **kwargs)
    model = TemporalFormula("always", operands=(TemporalFormula("atom", proposition="declared_safe",
        source_ref_ids=(source.ref_id,)),), source_ref_ids=(source.ref_id,))
    supplied = [api.TypedFamilyEvidence(model, source)]
    report = api.prepare_family_training_targets_v2("legal_ir", supplemental_inputs=supplied, **kwargs)
    assert {row["logic_family"] for row in report["projections"]} == {"deontic", "temporal"}
    assert api.validate_family_training_report_v2(report, supplemental_inputs=supplied, **kwargs) == report
    assert "source_model_fidelity_not_verified" in report["projections"][-1]["qualification_gaps"]


def test_absent_supplementary_models_never_manufacture_authorization_or_horn():
    report = api.prepare_family_training_targets_v2("legal_ir", document=fixtures.legal_document(),
        requested_families=["authorization", "horn_chc"])
    assert not report["projections"]
    assert len(report["family_inventory"]) == 40
    assert all(not row["ready_for_training"] for row in report["family_inventory"])


def test_supplemental_source_reassignment_and_conflicting_embedded_refs_are_refused():
    a = dict(document=fixtures.legal_document(), source_text="Owner may read notice.")
    b = dict(document=fixtures.legal_document(), source_text="Owner must not read notice.")
    source = api.supplemental_source_ref("legal_ir", **a)
    supplied = api.TypedFamilyEvidence(policy(source), source)
    with pytest.raises(ValueError, match="SourceRef differs"):
        api.prepare_family_training_targets_v2("legal_ir", supplemental_inputs=[supplied], **b)
    different = api.supplemental_source_ref("legal_ir", **b)
    with pytest.raises(ValueError, match="SourceRef differs|different code unit"):
        api.prepare_family_training_targets_v2("legal_ir", supplemental_inputs=[api.TypedFamilyEvidence(policy(different), source)], **a)
    with pytest.raises(ValueError, match="TypedFamilyEvidence"):
        api.prepare_family_training_targets_v2("legal_ir", supplemental_inputs=[{"family": "authorization"}], **a)
    with pytest.raises(ValueError, match="duplicate"):
        api.prepare_family_training_targets_v2("legal_ir", supplemental_inputs=[supplied, supplied], **a)


def test_v1_remains_byte_stable_and_old_report_validation_still_works():
    import hashlib
    assert hashlib.sha256(Path(v1.__file__).read_bytes()).hexdigest() == "e42e5314a59966ade1163e062817484357feb97e86158e21360ad39fa1558e64"
    original = v1.prepare_family_training_targets("legal_ir", document=fixtures.legal_document())
    before = deepcopy(original)
    v2 = api.prepare_family_training_targets_v2("legal_ir", document=fixtures.legal_document())
    assert v1.validate_family_training_report(original) == before
    assert v2["base_report_sha256"] == original["report_sha256"]
    assert api.validate_family_training_report_v2(v2) == v2


def test_rehashed_projection_tampering_is_rejected_by_exact_source_replay():
    row = untimed_row()
    report = api.prepare_family_training_targets_v2("ui_ux_ir", ui_training_row=row)
    corrupted = deepcopy(report)
    target = next(value for value in corrupted["projections"] if value["projection_id"] == "ui_ux_ir/event_prefix/native/v2")
    target["payload"]["native_document"]["events"][0]["event_type"] = "forged"
    target["target_sha256"] = v1._sha({key: value for key, value in target.items() if key != "target_sha256"})
    corrupted["report_sha256"] = v1._sha({key: value for key, value in corrupted.items() if key != "report_sha256"})
    with pytest.raises(ValueError, match="typed source replay"):
        api.validate_family_training_report_v2(corrupted, ui_training_row=row)
    corrupted["proof_authority"] = True
    corrupted["report_sha256"] = v1._sha({key: value for key, value in corrupted.items() if key != "report_sha256"})
    with pytest.raises(ValueError, match="authority"):
        api.validate_family_training_report_v2(corrupted)
