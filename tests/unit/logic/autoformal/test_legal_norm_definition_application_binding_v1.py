"""Fictional applicability custody never authorizes a definition application.

Public cases replay genuine source/context/definition/applicability owners and
the installed conditional-instance owner. Tests named pure deliberately replace
expensive completed owners to isolate bridge intake, selection or mutation
fences; those seams are not additional source or signature qualifications.
No actual statutory inputs, production keys, training, network or Lean build.
"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_norm_definition_applicability_v1 as applicability
from ipfs_datasets_py.logic.autoformal import legal_norm_definition_evidence_v1 as evidence


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module")
def helper():
    spec = importlib.util.spec_from_file_location(
        "_application_binding_genuine_applicability_fixture",
        Path(__file__).with_name("test_legal_norm_definition_applicability_v1.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def owner():
    from ipfs_datasets_py.logic.autoformal import legal_norm_definition_application_binding_v1
    return legal_norm_definition_application_binding_v1


@pytest.fixture(scope="module")
def conditional():
    # Only the fixed installed owner is imported, never a staging candidate.
    from ipfs_datasets_py.logic.autoformal import legal_bound_variable_definition_v1
    return legal_bound_variable_definition_v1


def original_inputs(helper, case):
    return {"companion": case["companion"], "norm_subject": case["subject"],
        "norm_manifest": case["manifest"], "applicability_registry": case["registry"],
        "applicability_policy": case["policy"], "applicability_reviews": case["reviews"],
        **helper.replay_arguments(case), **helper.assessment_arguments(applicability, case)}


def conditional_request(conditional, report, *, use_index=0, mode="instance_only"):
    use = report["uses"][use_index]
    choice = report["declaration_record"]["decisions"][use_index]
    companion = report["original_companion"]
    link = companion["links"][choice["selected_link_ref"]["link_index"]]
    endpoint = next(row for row in companion["definitions"]
                    if row["alternative_id"] == link["request_link"]["alternative_id"])
    binding = link["typed_context"]["binding"]
    # Structural mappings retain the whole binder target, including native path.
    # The companion use context identifies its original expression, not a new binder.
    return {"schema": conditional.REQUEST_SCHEMA, "profile": conditional.PROFILE,
        "companion_sha256": report["expected_companion_sha256"],
        "link_sha256": evidence.norm_definition_evidence_sha256(link),
        "alternative_id": endpoint["alternative_id"], "target": deepcopy(use["target"]),
        "binding": deepcopy(binding), "binder_target": None,
        "argument": deepcopy(link["typed_context"]["argument"]),
        "source_paths": deepcopy(link["request_link"]["source_paths"]),
        "definition_term_ref": deepcopy(link["definition_term_ref"]),
        "definition_ast_ref": deepcopy(link["definition_ast_ref"]),
        "carrier_map": deepcopy(conditional.CARRIER_MAP),
        "evaluation_context": deepcopy(conditional.EVALUATION_CONTEXT),
        "definition_assumption": {"kind": "explicit_unverified_parameter", "parameter": "hDefinition",
                                  "definition_ast_ref": deepcopy(link["definition_ast_ref"])},
        "mode": mode, "membership_assumption": None if mode == "instance_only" else {
            "kind": "explicit_unverified_parameter", "parameter": "hMembership",
            "link_sha256": evidence.norm_definition_evidence_sha256(link),
            "definition_symbol": endpoint["term_record"]["symbol"], "carrier": "Entity"}}


def request_for(conditional, report, inputs, **kwargs):
    request = conditional_request(conditional, report, **kwargs)
    relational = inputs["companion_inputs"]["norm_preparation"]["correspondence"]["relational_fragment"]
    request["binder_target"] = deepcopy(next(row for row in relational["structural_mapping"]
        if row["typed_path"] == request["binding"]["typed_path"]))
    return request


def prepare_arguments(data):
    raw = wire(data["request"])
    return (data["assessment"], raw), {
        "expected_applicability_assessment_sha256": applicability.norm_definition_applicability_sha256(data["assessment"]),
        "applicability_inputs": data["inputs"], "expected_conditional_request_sha256": sha(raw)}


def prepare(owner, data, **overrides):
    args, kwargs = prepare_arguments(data)
    return owner.prepare_norm_definition_application_binding_v1(*args, **{**kwargs, **overrides})


def validate(owner, data, report, **overrides):
    args, kwargs = prepare_arguments(data)
    return owner.validate_norm_definition_application_binding_v1(report, *args,
        **{**kwargs, "expected_report_sha256": owner.norm_definition_application_binding_sha256(report), **overrides})


@pytest.fixture(scope="module")
def baseline(owner, conditional, helper):
    source_helper = helper.helper.__wrapped__()
    prepared = helper.prepared.__wrapped__(source_helper)
    endpoints = helper.signed_endpoints.__wrapped__(applicability, prepared)
    data = dict(prepared, inputs=endpoints["inputs"],
                definition_observations=endpoints["definition_observations"])
    data["companion"] = source_helper.prepare(data["inputs"])
    declaration = applicability._declaration(data["companion"], data["subject"], data["inputs"],
        helper.choices(applicability, data), helper.DECLARED)
    signed = helper.signed_case(applicability, data, declaration)
    inputs = original_inputs(helper, signed)
    assert set(inputs) == owner.APPLICABILITY_FIELDS
    assessment = applicability.assess_norm_definition_applicability_v1(**inputs)
    assert assessment["common_body_authenticated_under_selected_trust"] is True
    assert assessment["partial_declaration_custody_prerequisites_satisfied_under_selected_trust"] is True
    result = {"assessment": assessment, "inputs": inputs}
    result["request"] = request_for(conditional, assessment, inputs)
    result["report"] = prepare(owner, result)
    return result


def assert_unapplied(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    for field in ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask"):
        assert type(report[field]) is int and report[field] == 0
    for field in ("native_ast_rewritten", "norm_interpretation_ready", "backend_executed"):
        assert report[field] is False
    for field in ("selected_interpretation", "accepted_interpretation", "governing_definition_use"):
        assert report[field] is None
    assert report["definition_applications"] == report["human_reviews_created"] == report["signatures_constructed"] == 0
    assert report["external_complete_inputs_required"] is True


def test_public_complete_bridge_validation_replays_both_original_owners(owner, conditional, baseline, monkeypatch):
    app_validate = applicability.validate_norm_definition_applicability_v1
    conditional_prepare = conditional.prepare_bound_variable_definition_v1
    calls = []

    def app_traced(report, *args, **kwargs):
        calls.append(("applicability", kwargs["expected_report_sha256"]))
        return app_validate(report, *args, **kwargs)

    def conditional_traced(companion, raw, **kwargs):
        calls.append(("conditional", kwargs["expected_companion_sha256"]))
        assert companion == baseline["assessment"]["original_companion"]
        assert kwargs["companion_inputs"] == baseline["inputs"]["companion_inputs"]
        return conditional_prepare(companion, raw, **kwargs)

    monkeypatch.setattr(applicability, "validate_norm_definition_applicability_v1", app_traced)
    monkeypatch.setattr(conditional, "prepare_bound_variable_definition_v1", conditional_traced)
    before = evidence._snapshot({key: baseline[key] for key in ("assessment", "inputs", "request")})[1]
    assert validate(owner, baseline, baseline["report"]) == baseline["report"]
    assert calls == [("applicability", applicability.norm_definition_applicability_sha256(baseline["assessment"])),
                     ("conditional", baseline["inputs"]["expected_companion_sha256"])]
    assert evidence._snapshot({key: baseline[key] for key in ("assessment", "inputs", "request")})[1] == before


def test_public_exact_occurrence_and_complete_original_populations_remain_unapplied(baseline):
    report, assessment = baseline["report"], baseline["assessment"]
    selected = report["selected_binding"]
    assert report["original_applicability_assessment"] == assessment
    assert selected["use_index"] == 0
    assert selected["use"] == assessment["uses"][0]
    assert selected["choice"] == assessment["declaration_record"]["decisions"][0]
    assert selected["selected_link_ref"] == selected["choice"]["selected_link_ref"]
    assert selected["selected_link"] == assessment["original_companion"]["links"][0]
    conditional = report["conditional_report"]
    assert conditional["selected_link"] == selected["selected_link"]
    binding = conditional["occurrence_binding"]
    assert binding["native_variable"]["name"] == binding["binding"]["name"] == "actor"
    assert binding["native_predicate"]["name"] == "Retain"
    assert binding["argument"]["role"] == "actor"
    assert binding["native_predicate"]["arguments"][binding["argument"]["index"]] == binding["native_variable"]
    assert len(assessment["uses"]) == 2 and len(assessment["original_companion"]["links"]) == 4
    assert len(conditional["definition_alternatives"]) == 2
    assert conditional["original_norm"]["unchanged"] is True
    assert assessment["closed_context_prerequisites_satisfied"] is False
    assert assessment["combined_norm_meaning_prerequisites_satisfied"] is False
    assert report["complete_original_populations_retained"] is True
    assert report["original_norm_and_definition_asts_unchanged"] is True
    assert_unapplied(report)


def test_public_optional_membership_remains_a_parameter_uncovered_by_applicability_signatures(owner, conditional, baseline):
    data = dict(baseline)
    data["request"] = request_for(conditional, data["assessment"], data["inputs"], mode="body_with_membership")
    report = prepare(owner, data)
    result = report["conditional_report"]
    assert result["request"]["membership_assumption"]["kind"] == "explicit_unverified_parameter"
    assert result["conditional_theorem_statements"][1]["hypotheses"] == [
        "hDefinition : formula_0 i t", "hMembership : headAt i entity t"]
    assert "exact (hDefinition entity).mp hMembership" in result["lean_source"]
    assert all(row["kernel_checked"] is False for row in result["conditional_theorem_statements"])
    assert result["authority"]["membership_assumption_verified"] is False
    assert result["authority"]["norm_witness_extracted"] is False
    assert report["authority"]["applicability_signatures_cover_conditional_request"] is False
    assert report["authority"]["applicability_signatures_cover_binding"] is False
    assert report["authority"]["definition_application_verified"] is False
    assert report["time_context"]["declared_legal_as_of_date"] == "2024-01-01"
    assert report["time_context"]["applicability_evaluation_time_utc"] == baseline["inputs"]["at_time_utc"]
    assert report["time_context"]["formal_evaluation_context"] == conditional.EVALUATION_CONTEXT
    assert report["time_context"]["calendar_to_nat_coercion_performed"] is False
    assert report["time_context"]["legal_date_formal_time_alignment_verified"] is False
    assert_unapplied(report)


def test_public_rehashed_applicability_promotion_fails_complete_original_replay(owner, baseline):
    data = dict(baseline, assessment=deepcopy(baseline["assessment"]))
    data["assessment"]["authority"]["definition_applicability_verified"] = True
    with pytest.raises(ValueError):
        prepare(owner, data)


def test_public_changed_definition_source_is_not_authorized_by_retained_signatures(owner, baseline):
    inputs = deepcopy(baseline["inputs"])
    inputs["companion_inputs"]["definitions"][0]["correspondence_inputs"]["candidate_inputs"]["raw_html"] += b"<!-- changed -->"
    with pytest.raises(ValueError):
        prepare(owner, baseline, applicability_inputs=inputs)


@pytest.mark.parametrize("damage", ["unauthenticated", "partial_custody", "integer_truth", "content", "blockers",
    "applied", "governing", "profile", "schema", "companion", "uses_reordered", "choices_reordered",
    "unresolved", "foreign_alternative", "link_pin", "bool_link_index", "term", "ast", "source_paths",
    "binding", "role", "boolean_argument", "target_path", "predicate_target", "binder", "binder_sort"])
def test_pure_selection_refuses_unsigned_partial_foreign_or_retargeted_associations(owner, baseline, damage):
    assessment = deepcopy(baseline["assessment"])
    request = deepcopy(baseline["request"])
    choice = assessment["declaration_record"]["decisions"][0]
    if damage == "unauthenticated": assessment["common_body_authenticated_under_selected_trust"] = False
    elif damage == "partial_custody": assessment["partial_declaration_custody_prerequisites_satisfied_under_selected_trust"] = False
    elif damage == "integer_truth": assessment["common_body_authenticated_under_selected_trust"] = 1
    elif damage == "content": assessment["common_body_content_status"] = "pending"
    elif damage == "blockers": assessment["content_blockers"] = ["fixture:unresolved-custody"]
    elif damage == "applied": assessment["native_ast_rewritten"] = True
    elif damage == "governing": assessment["governing_definition_use"] = request["alternative_id"]
    elif damage == "profile": assessment["profile"] = "fixture:foreign-profile"
    elif damage == "schema": assessment["schema"] = applicability.DECLARATION_SCHEMA
    elif damage == "companion": request["companion_sha256"] = "0" * 64
    elif damage == "uses_reordered": assessment["uses"].reverse()
    elif damage == "choices_reordered": assessment["declaration_record"]["decisions"].reverse()
    elif damage == "unresolved": choice.update(decision="unresolved", selected_link_ref=None)
    elif damage == "foreign_alternative":
        other = assessment["original_companion"]["links"][1]
        request.update(link_sha256=evidence.norm_definition_evidence_sha256(other),
                       alternative_id=other["request_link"]["alternative_id"])
    elif damage == "link_pin": request["link_sha256"] = "0" * 64
    elif damage == "bool_link_index": choice["selected_link_ref"]["link_index"] = False
    elif damage == "term": request["definition_term_ref"]["sha256"] = "0" * 64
    elif damage == "ast": request["definition_ast_ref"]["sha256"] = "0" * 64
    elif damage == "source_paths": request["source_paths"] = ["/occurrences/3/anchor"]
    elif damage == "binding": request["binding"]["name"] = "object"
    elif damage == "role": request["argument"]["role"] = "object"
    elif damage == "boolean_argument": request["argument"]["index"] = False
    elif damage == "target_path": request["target"] = deepcopy(assessment["uses"][1]["target"])
    elif damage == "predicate_target": request["target"]["kind"] = "predicate"
    elif damage == "binder": request["binder_target"]["binder_name"] = "object"
    else: request["binder_target"]["typed_sort"] = "Agent"
    with pytest.raises(ValueError):
        owner._binding_selection(assessment, request)


def test_pure_second_same_spelling_use_is_distinct_without_implicit_global_application(owner, conditional, baseline):
    request = request_for(conditional, baseline["assessment"], baseline["inputs"], use_index=1)
    index, use, choice, ref, link = owner._binding_selection(baseline["assessment"], request)
    assert index == 1 and use == baseline["assessment"]["uses"][1]
    assert use["target"] != baseline["assessment"]["uses"][0]["target"]
    assert link["typed_node"]["symbol"] == "actor"
    assert link["typed_context"]["argument"]["symbol"] == "Approved"
    assert request["binding"] == baseline["request"]["binding"]
    assert ref == choice["selected_link_ref"]
    assert baseline["report"]["definition_applications"] == 0


@pytest.mark.parametrize("damage", ["app_pin", "request_pin", "changed_app", "empty", "not_bytes",
    "oversize", "missing_app_arg", "extra_app_arg", "missing_companion_arg", "extra_companion_arg"])
def test_pure_preflight_independent_pins_closed_original_arguments_and_bounds_precede_owner_loading(owner, baseline, monkeypatch, damage):
    data = {key: deepcopy(baseline[key]) for key in ("assessment", "inputs", "request")}
    args, kwargs = prepare_arguments(data)
    args = list(args)
    if damage == "app_pin": kwargs["expected_applicability_assessment_sha256"] = "0" * 64
    elif damage == "request_pin": kwargs["expected_conditional_request_sha256"] = "0" * 64
    elif damage == "changed_app": args[0]["current_definition_endpoint_prerequisites_satisfied"] = False
    elif damage == "empty": args[1] = b""; kwargs["expected_conditional_request_sha256"] = sha(args[1])
    elif damage == "not_bytes": args[1] = args[1].decode("utf-8")
    elif damage == "oversize": monkeypatch.setattr(owner, "MAX_REQUEST_BYTES", len(args[1]) - 1)
    elif damage == "missing_app_arg": kwargs["applicability_inputs"].pop("definition_observations")
    elif damage == "extra_app_arg": kwargs["applicability_inputs"]["accepted"] = True
    elif damage == "missing_companion_arg": kwargs["applicability_inputs"]["companion_inputs"].pop("definitions")
    else: kwargs["applicability_inputs"]["companion_inputs"]["accepted"] = True

    def unexpected():
        pytest.fail("invalid bridge intake reached conditional operation owner")

    monkeypatch.setattr(owner, "_owner", unexpected)
    with pytest.raises(ValueError):
        owner.prepare_norm_definition_application_binding_v1(*args, **kwargs)


def seam_completed_owners(owner, conditional, baseline, monkeypatch):
    """Reuse genuinely completed outputs only to isolate bridge fences."""
    monkeypatch.setattr(applicability, "validate_norm_definition_applicability_v1",
                        lambda *args, **kwargs: deepcopy(baseline["assessment"]))
    monkeypatch.setattr(conditional, "prepare_bound_variable_definition_v1",
                        lambda *args, **kwargs: deepcopy(baseline["report"]["conditional_report"]))


@pytest.mark.parametrize("damage", ["missing_membership", "foreign_membership", "unrequested_membership", "asserted_definition"])
def test_pure_replayed_applicability_cannot_bypass_real_conditional_premise_intake(owner, conditional, baseline, monkeypatch, damage):
    """Only applicability replay is cached; the installed conditional intake runs."""
    data = dict(baseline)
    request = request_for(conditional, baseline["assessment"], baseline["inputs"], mode="body_with_membership")
    if damage == "missing_membership": request["membership_assumption"] = None
    elif damage == "foreign_membership": request["membership_assumption"]["link_sha256"] = "0" * 64
    elif damage == "unrequested_membership": request["mode"] = "instance_only"
    else: request["definition_assumption"]["kind"] = "verified_statutory_definition"
    data["request"] = request
    monkeypatch.setattr(applicability, "validate_norm_definition_applicability_v1",
                        lambda *args, **kwargs: deepcopy(baseline["assessment"]))
    monkeypatch.setattr(evidence, "validate_norm_definition_evidence_v1",
                        lambda *args, **kwargs: pytest.fail("invalid premise reached full companion replay"))
    with pytest.raises(ValueError):
        prepare(owner, data)


@pytest.mark.parametrize("stage", ["applicability", "conditional"])
def test_pure_producer_generation_fence_surrounds_each_completed_owner(owner, conditional, baseline, monkeypatch, stage):
    seam_completed_owners(owner, conditional, baseline, monkeypatch)
    changed = [False]
    pins = deepcopy(baseline["report"]["producer_pins"])
    monkeypatch.setattr(owner, "_pins", lambda ignored: {**pins, **({"fixture:changed-producer": "0" * 64} if changed[0] else {})})
    target = applicability if stage == "applicability" else conditional
    name = "validate_norm_definition_applicability_v1" if stage == "applicability" else "prepare_bound_variable_definition_v1"
    cached = getattr(target, name)

    def mutate(*args, **kwargs):
        result = cached(*args, **kwargs)
        changed[0] = True
        return result

    monkeypatch.setattr(target, name, mutate)
    with pytest.raises(ValueError, match="producers changed"):
        prepare(owner, baseline)


@pytest.mark.parametrize("side", ["original", "detached", "after_conditional", "final_serialization"])
def test_pure_input_mutation_fences_surround_both_owners_and_final_serialization(owner, conditional, baseline, monkeypatch, side):
    data = {key: deepcopy(baseline[key]) for key in ("assessment", "inputs", "request")}
    seam_completed_owners(owner, conditional, baseline, monkeypatch)
    app_cached = applicability.validate_norm_definition_applicability_v1
    conditional_cached = conditional.prepare_bound_variable_definition_v1

    def app_mutate(*args, **kwargs):
        result = app_cached(*args, **kwargs)
        if side == "original": data["inputs"]["at_time_utc"] = "2026-10-15T12:04:00Z"
        elif side == "detached": kwargs["companion_inputs"]["request_raw"] += b" "
        return result

    def conditional_mutate(*args, **kwargs):
        result = conditional_cached(*args, **kwargs)
        if side == "after_conditional": kwargs["companion_inputs"]["request_raw"] += b" "
        return result

    original_wire = owner._wire

    def wire_mutate(value):
        result = original_wire(value)
        if side == "final_serialization" and type(value) is dict and value.get("schema") == owner.SCHEMA:
            data["inputs"]["at_time_utc"] = "2026-10-15T12:04:00Z"
        return result

    monkeypatch.setattr(applicability, "validate_norm_definition_applicability_v1", app_mutate)
    monkeypatch.setattr(conditional, "prepare_bound_variable_definition_v1", conditional_mutate)
    monkeypatch.setattr(owner, "_wire", wire_mutate)
    with pytest.raises(ValueError, match="inputs changed"):
        prepare(owner, data)


@pytest.mark.parametrize("damage", ["authority", "conditional", "choice", "time", "removed_population"])
def test_pure_complete_regeneration_refuses_rehashed_binding_forgery(owner, baseline, monkeypatch, damage):
    forged = deepcopy(baseline["report"])
    if damage == "authority": forged["authority"]["membership_assumption_verified"] = True
    elif damage == "conditional": forged["conditional_report"]["lean_source"] += "\n-- forged"
    elif damage == "choice": forged["selected_binding"]["choice"]["legal_as_of_date"] = "2025-01-01"
    elif damage == "time": forged["time_context"]["calendar_to_nat_coercion_performed"] = True
    else: forged["original_applicability_assessment"]["original_companion"]["definitions"].pop()
    calls = []

    def cached(*args, **kwargs):
        calls.append(True)
        return deepcopy(baseline["report"])

    monkeypatch.setattr(owner, "prepare_norm_definition_application_binding_v1", cached)
    with pytest.raises(ValueError, match="complete regeneration"):
        validate(owner, baseline, forged)
    assert calls == [True]


def test_pure_stale_binding_pin_fails_before_owner_loading(owner, baseline, monkeypatch):
    monkeypatch.setattr(owner, "_owner", lambda: pytest.fail("stale binding pin loaded operation owner"))
    with pytest.raises(ValueError):
        validate(owner, baseline, baseline["report"], expected_report_sha256="0" * 64)


def test_pure_validator_detects_offered_report_mutation_after_regeneration(owner, baseline, monkeypatch):
    offered = deepcopy(baseline["report"])

    def mutate(*args, **kwargs):
        offered["time_context"]["calendar_to_nat_coercion_performed"] = True
        return deepcopy(baseline["report"])

    monkeypatch.setattr(owner, "prepare_norm_definition_application_binding_v1", mutate)
    with pytest.raises(ValueError, match="changed during validation"):
        validate(owner, baseline, offered)


@pytest.mark.parametrize("which", ["self", "direct", "inherited"])
def test_pure_source_pins_refuse_changed_producer_bytes_without_touching_repository(owner, monkeypatch, tmp_path, which):
    path = tmp_path / "fictional-producer.py"
    path.write_bytes(b"# fictional pin observation\n")
    expected = sha(path.read_bytes())
    if which == "self":
        monkeypatch.setattr(owner, "_SELF_PATH", path)
        monkeypatch.setattr(owner, "_SELF_PIN", expected)
    elif which == "direct": monkeypatch.setattr(owner, "_DIRECT_PINS", {str(path): expected})
    else:
        def changed():
            raise ValueError("fictional inherited producer changed")
        monkeypatch.setattr(evidence, "_pure_pins", changed)
    path.write_bytes(b"# changed fictional producer\n")
    with pytest.raises(ValueError, match="producer|owners"):
        owner._pure_pins()


@pytest.mark.parametrize("bound", ["nodes", "aggregate_bytes", "report_bytes"])
def test_pure_existing_aggregate_and_complete_report_bounds_refuse_without_truncation(owner, baseline, monkeypatch, bound):
    if bound == "report_bytes":
        monkeypatch.setattr(owner, "MAX_REPORT_BYTES", len(wire(baseline["report"])) - 1)
        with pytest.raises(ValueError):
            owner.norm_definition_application_binding_sha256(baseline["report"])
    else:
        if bound == "nodes": monkeypatch.setattr(evidence, "MAX_INPUT_NODES", 1)
        else: monkeypatch.setattr(evidence.norm, "MAX_INPUT_BYTES", 128)
        monkeypatch.setattr(owner, "_owner", lambda: pytest.fail("oversize intake loaded operation owner"))
        with pytest.raises(ValueError):
            prepare(owner, baseline)
