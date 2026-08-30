"""Contract vectors for proposal-only program-transition records and admission."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
    decode_and_recompute_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_identity import (
    TRANSITION_IDENTITY_SCHEMA,
    TransitionIdentity,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_transition import (
    ADMISSION_VERDICTS,
    CALIBRATION_STATUSES,
    CANDIDATE_KINDS,
    FAMILY_REQUIRED_CURRENT,
    MAX_CANDIDATES,
    PATCH_SKETCH_IR_INTERFACE,
    PATCH_SKETCH_IR_SCHEMA,
    PREDICTION_AUTHORITY_FLAGS,
    PROGRAM_GRAPH_DELTA_PROPOSAL_INTERFACE,
    PROGRAM_GRAPH_DELTA_PROPOSAL_SCHEMA,
    PROGRAM_TRANSITION_ADMISSION_INTERFACE,
    PROGRAM_TRANSITION_ADMISSION_SCHEMA,
    PROGRAM_TRANSITION_CANDIDATE_SCHEMA,
    PROGRAM_TRANSITION_OBSERVATION_INTERFACE,
    PROGRAM_TRANSITION_OBSERVATION_SCHEMA,
    PROGRAM_TRANSITION_PREDICTION_INTERFACE,
    PROGRAM_TRANSITION_PREDICTION_SCHEMA,
    PROGRAM_TRANSITION_QUERY_INTERFACE,
    PROGRAM_TRANSITION_QUERY_SCHEMA,
    PROGRAM_TRANSITION_RECEIPT_SCHEMA,
    QUERY_FAMILIES,
    QUERY_FAMILY_CANDIDATE_KINDS,
    REPAIR_OPERATOR_INTERFACE,
    REPAIR_OPERATOR_KINDS,
    REPAIR_OPERATOR_SCHEMA,
    TRANSITION_CALIBRATION_SCHEMA,
    TRANSITION_MODEL_PROFILE_SCHEMA,
    AdmissionVerdict,
    CalibrationStatus,
    CandidateKind,
    ObservationStatus,
    PatchSketchIR,
    ProgramGraphDeltaProposal,
    ProgramLanguage,
    ProgramTransitionAdmission,
    ProgramTransitionCandidate,
    ProgramTransitionError,
    ProgramTransitionObservation,
    ProgramTransitionPrediction,
    ProgramTransitionQuery,
    ProgramTransitionReceipt,
    QueryFamily,
    RepairOperator,
    RepairOperatorKind,
    SketchKind,
    SpecialistFamily,
    TransitionCalibration,
    TransitionModelProfile,
    admit_program_transition,
    assess_calibration_drift,
    bind_candidate_to_query,
    canonical_transition_bytes,
    canonicalize_transition_value,
    decode_transition_observation,
    decode_transition_record,
    issue_transition_receipt,
    load_payload_schema,
    loads_transition_json,
    may_influence_planning,
    observe_program_transition,
    prediction_authority_violations,
    propose_program_transition,
    select_and_parameterize_candidate,
    transition_cid_for,
)


SCHEMA_PATH = (
    Path(__file__).resolve().parents[5]
    / "ipfs_datasets_py"
    / "logic"
    / "software_contracts"
    / "semantic_state"
    / "schemas"
    / "program-transition.payload.schema.json"
)

_PACKAGE = "ipfs_datasets_py.logic.software_contracts.semantic_state.program_transition"
_OPT_OUTS = {
    "IPFS_DATASETS_AUTO_INSTALL": "0",
    "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0",
    "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
    "IPFS_KIT_AUTO_INSTALL_DEPS": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _profile(**overrides: Any) -> TransitionModelProfile:
    fields: dict[str, Any] = {
        "profile_name": "next-call-specialist-v1",
        "specialist_family": SpecialistFamily.CALL_TARGET,
        "model_cid": _cid("model-v1"),
        "tokenizer_cid": _cid("tok-v1"),
        "preprocessing_profile_cid": _cid("prep-v1"),
    }
    fields.update(overrides)
    return TransitionModelProfile(**fields)


def _query(**overrides: Any) -> ProgramTransitionQuery:
    fields: dict[str, Any] = {
        "query_family": QueryFamily.NEXT_CALL,
        "language": "python",
        "subject_cid": _cid("state-current"),
        "current_source_cid": _cid("source-current"),
        "current_state_cid": _cid("state-current"),
        "environment_binding_cid": _cid("env-v1"),
        "policy_cid": _cid("policy-v1"),
        "allowed_symbol_cids": [_cid("sym-b"), _cid("sym-a")],
        "evidence_cids": [_cid("ev-1")],
        "unavailable_dimensions": ("native_stack",),
    }
    fields.update(overrides)
    return ProgramTransitionQuery(**fields)


def _repair_query(**overrides: Any) -> ProgramTransitionQuery:
    fields: dict[str, Any] = {
        "query_family": QueryFamily.REPAIR,
        "language": "python",
        "subject_cid": _cid("graph-current"),
        "current_source_cid": _cid("source-current"),
        "current_graph_cid": _cid("graph-current"),
        "environment_binding_cid": _cid("env-v1"),
        "policy_cid": _cid("policy-v1"),
        "allowed_operator_cids": [_cid("op-replace"), _cid("op-guard")],
    }
    fields.update(overrides)
    return ProgramTransitionQuery(**fields)


def _candidate(query: ProgramTransitionQuery | None = None, **overrides: Any) -> ProgramTransitionCandidate:
    bound = query or _query()
    selected = bound.allowed_symbol_cids[0] if bound.allowed_symbol_cids else bound.allowed_operator_cids[0]
    kind = next(iter(QUERY_FAMILY_CANDIDATE_KINDS[str(bound.query_family)]))
    fields: dict[str, Any] = {
        "candidate_kind": kind,
        "selected_cid": selected,
    }
    fields.update(overrides)
    return select_and_parameterize_candidate(bound, **fields)


def _prediction(
    query: ProgramTransitionQuery | None = None,
    candidates: list[ProgramTransitionCandidate] | None = None,
    **overrides: Any,
) -> ProgramTransitionPrediction:
    bound = query or _query()
    items = candidates if candidates is not None else [_candidate(bound)]
    profile = overrides.pop("model_profile", None) or _profile()
    calibration = overrides.pop("calibration", None)
    abstain = overrides.pop("abstain", False)
    evidence_cids = overrides.pop("evidence_cids", bound.evidence_cids)
    if overrides:
        raise AssertionError(f"unexpected prediction overrides {sorted(overrides)}")
    return propose_program_transition(
        bound,
        items,
        model_profile=profile,
        calibration=calibration,
        abstain=abstain,
        evidence_cids=evidence_cids,
    )


def _observation(query: ProgramTransitionQuery | None = None, **overrides: Any) -> ProgramTransitionObservation:
    bound = query or _query()
    fields: dict[str, Any] = {
        "observed_cid": bound.allowed_symbol_cids[0],
        "observation_status": ObservationStatus.OBSERVED,
        "evidence_cids": [_cid("obs-ev")],
    }
    fields.update(overrides)
    return observe_program_transition(bound, **fields)


def _calibration(profile: TransitionModelProfile | None = None, **overrides: Any) -> TransitionCalibration:
    bound = profile or _profile()
    fields: dict[str, Any] = {
        "model_profile_cid": bound.model_profile_cid,
        "query_family": QueryFamily.NEXT_CALL,
        "trial_count": 100,
        "disagreement_count": 1,
        "bound_numerator": 1,
        "bound_denominator": 20,
        "expected_observation_cid": _cid("obs-expected"),
        "actual_observation_cid": _cid("obs-actual"),
    }
    fields.update(overrides)
    return TransitionCalibration(**fields)


def _operator(**overrides: Any) -> RepairOperator:
    fields: dict[str, Any] = {
        "operator_kind": RepairOperatorKind.REPLACE_CALL_TARGET,
        "language": "python",
        "target_symbol_cid": _cid("sym-a"),
        "parameter_cids": [_cid("param-b"), _cid("param-a")],
        "pre_state_cid": _cid("state-current"),
    }
    fields.update(overrides)
    return RepairOperator(**fields)


def _sample_payloads() -> list[dict[str, Any]]:
    query = _query()
    profile = _profile()
    candidate = _candidate(query)
    calibration = _calibration(profile)
    prediction = _prediction(query, [candidate], model_profile=profile, calibration=calibration)
    observation = _observation(query)
    admission = admit_program_transition(
        query,
        current_subject_cid=query.subject_cid,
        current_source_cid=query.current_source_cid,
        current_environment_binding_cid=query.environment_binding_cid,
        current_state_cid=query.current_state_cid,
        prediction=prediction,
        observation=observation,
    )
    receipt = issue_transition_receipt(
        query, admission, prediction=prediction, observation=observation
    )
    repair_query = _repair_query()
    operator = _operator()
    repair_candidate = select_and_parameterize_candidate(
        repair_query,
        candidate_kind=CandidateKind.REPAIR_OPERATOR,
        selected_cid=repair_query.allowed_operator_cids[0],
        parameterization={"operator_kind": "replace_call_target"},
    )
    sketch = PatchSketchIR(
        language="python",
        sketch_kind=SketchKind.REPAIR,
        source_cid=repair_query.current_source_cid,
        hole_cids=[_cid("hole-1")],
        operator_cids=[operator.repair_operator_cid],
    )
    delta = ProgramGraphDeltaProposal(
        previous_snapshot_cid=repair_query.current_graph_cid or _cid("graph-current"),
        query_cid=repair_query.query_cid,
        candidate_cid=repair_candidate.candidate_cid,
        added_node_cids=[_cid("node-new")],
        retained_subroot_cids=[_cid("node-keep")],
    )
    return [
        profile.to_dict(),
        calibration.to_dict(),
        operator.to_dict(),
        delta.to_dict(),
        sketch.to_dict(),
        query.to_dict(),
        candidate.to_dict(),
        prediction.to_dict(),
        observation.to_dict(),
        admission.to_dict(),
        receipt.to_dict(),
    ]


def test_public_interfaces_are_versioned() -> None:
    assert PROGRAM_TRANSITION_QUERY_INTERFACE == "ProgramTransitionQuery@1"
    assert PROGRAM_TRANSITION_PREDICTION_INTERFACE == "ProgramTransitionPrediction@1"
    assert PROGRAM_TRANSITION_OBSERVATION_INTERFACE == "ProgramTransitionObservation@1"
    assert PROGRAM_TRANSITION_ADMISSION_INTERFACE == "ProgramTransitionAdmission@1"
    assert REPAIR_OPERATOR_INTERFACE == "RepairOperator@1"
    assert PROGRAM_GRAPH_DELTA_PROPOSAL_INTERFACE == "ProgramGraphDeltaProposal@1"
    assert PATCH_SKETCH_IR_INTERFACE == "PatchSketchIR@1"
    assert ProgramTransitionQuery.INTERFACE == PROGRAM_TRANSITION_QUERY_INTERFACE
    assert ProgramTransitionPrediction.INTERFACE == PROGRAM_TRANSITION_PREDICTION_INTERFACE
    assert ProgramTransitionObservation.INTERFACE == PROGRAM_TRANSITION_OBSERVATION_INTERFACE
    assert ProgramTransitionAdmission.INTERFACE == PROGRAM_TRANSITION_ADMISSION_INTERFACE
    assert RepairOperator.INTERFACE == REPAIR_OPERATOR_INTERFACE
    assert ProgramTransitionQuery.SCHEMA == PROGRAM_TRANSITION_QUERY_SCHEMA
    assert RepairOperator.SCHEMA == REPAIR_OPERATOR_SCHEMA
    assert PatchSketchIR.SCHEMA == PATCH_SKETCH_IR_SCHEMA
    assert ProgramGraphDeltaProposal.SCHEMA == PROGRAM_GRAPH_DELTA_PROPOSAL_SCHEMA


def test_closed_grammar_operator_and_status_vocabularies() -> None:
    assert QUERY_FAMILIES == {"next_call", "next_event", "inverse_trace", "repair"}
    assert CANDIDATE_KINDS == {
        "call_target",
        "next_event",
        "next_state",
        "inverse_event",
        "inverse_trace",
        "repair_operator",
        "graph_delta",
        "patch_sketch",
    }
    assert REPAIR_OPERATOR_KINDS == {
        "replace_call_target",
        "insert_guard",
        "wrap_handler",
        "strengthen_precondition",
        "weaken_postcondition",
        "rewrite_assignment",
        "delete_dead_code",
        "normalize_egraph",
        "bounded_cegis",
        "no_op",
    }
    assert ADMISSION_VERDICTS == {
        "admitted",
        "rejected",
        "abstain",
        "conflict",
        "stale",
        "unknown",
    }
    assert CALIBRATION_STATUSES == {
        "calibrated",
        "drifted",
        "uncalibrated",
        "unavailable",
    }
    assert set(item.value for item in ObservationStatus) == {
        "observed",
        "unavailable",
        "redacted",
        "inferred_untrusted",
    }
    assert QUERY_FAMILY_CANDIDATE_KINDS["next_call"] == frozenset({"call_target"})
    assert QUERY_FAMILY_CANDIDATE_KINDS["repair"] == frozenset(
        {"repair_operator", "graph_delta", "patch_sketch"}
    )
    assert FAMILY_REQUIRED_CURRENT["next_call"] == ("current_state_cid",)
    assert FAMILY_REQUIRED_CURRENT["repair"] == ("current_graph_cid",)
    assert "similarity" not in QUERY_FAMILIES
    assert MAX_CANDIDATES == 256
    with pytest.raises(ProgramTransitionError, match="not a program-transition query family"):
        _query(query_family="similar_call")
    with pytest.raises(ProgramTransitionError, match="unsupported value"):
        _operator(operator_kind="unbounded_llm_rewrite")
    with pytest.raises(ProgramTransitionError, match="unsupported value"):
        ProgramTransitionAdmission(
            query_cid=_cid("q"),
            policy_cid=_cid("p"),
            current_subject_cid=_cid("s"),
            current_environment_binding_cid=_cid("e"),
            verdict="accepted",
        )


def test_canonical_identity_vectors_are_stable_and_rehash() -> None:
    query = _query(allowed_symbol_cids=[_cid("sym-a"), _cid("sym-b")])
    shuffled = _query(allowed_symbol_cids=[_cid("sym-b"), _cid("sym-a")])
    expected = query.identity_payload()
    assert shuffled.query_cid == query.query_cid
    assert query.query_cid == cid_for_structured(expected)
    assert query.query_cid == transition_cid_for(expected)
    assert query.canonical_bytes() == canonical_dag_json_bytes(expected)
    assert query.canonical_bytes() == canonical_transition_bytes(expected)
    assert list(query.allowed_symbol_cids) == sorted(query.allowed_symbol_cids)
    operator = _operator()
    same = _operator(parameter_cids=[_cid("param-a"), _cid("param-b")])
    assert operator.repair_operator_cid == same.repair_operator_cid
    assert list(operator.parameter_cids) == sorted(operator.parameter_cids)


def test_records_round_trip_and_rehash() -> None:
    for payload in _sample_payloads():
        record = decode_transition_record(payload)
        assert record.to_dict() == payload
        claimed = payload[record.CID_FIELD]
        assert decode_and_recompute_structured(claimed, record.identity_payload()) == claimed
        again = json.loads(json.dumps(payload, sort_keys=True))
        assert decode_transition_record(again).to_dict() == payload


def test_unknown_fields_versions_and_forged_cids_fail_closed() -> None:
    payload = _query().to_dict()
    with pytest.raises(ProgramTransitionError, match="unknown fields"):
        ProgramTransitionQuery.from_dict({**payload, "not_a_contract_field": 1})
    with pytest.raises(ProgramTransitionError, match="non-semantic"):
        ProgramTransitionQuery.from_dict({**payload, "similarity": "forbidden"})
    with pytest.raises(ProgramTransitionError, match="non-semantic"):
        ProgramTransitionQuery.from_dict({**payload, "score": 1})
    with pytest.raises(ProgramTransitionError, match="schema version"):
        ProgramTransitionQuery.from_dict(
            {**payload, "schema": PROGRAM_TRANSITION_QUERY_SCHEMA.replace("@1", "@99")}
        )
    forged = dict(payload)
    forged["query_cid"] = _cid("forged")
    with pytest.raises(ProgramTransitionError, match="does not verify"):
        ProgramTransitionQuery.from_dict(forged)
    with pytest.raises(ProgramTransitionError, match="unsupported transition schema"):
        decode_transition_record({"schema": "not-a-payload", "x": 1})
    with pytest.raises(ProgramTransitionError, match="invented-hash"):
        ProgramTransitionQuery.from_dict({**payload, "invented_hash": "abc"})


def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected() -> None:
    with pytest.raises(ProgramTransitionError, match="duplicate JSON key"):
        loads_transition_json('{"a":1,"a":2}')
    with pytest.raises(ProgramTransitionError, match="nonfinite"):
        loads_transition_json("NaN")
    with pytest.raises(ProgramTransitionError, match="nonfinite"):
        loads_transition_json("Infinity")
    with pytest.raises(ProgramTransitionError, match="floats are rejected"):
        loads_transition_json('{"score":1.5}')


def test_canonicalize_before_cid() -> None:
    raw = _query(unavailable_dimensions=("b", "a")).identity_payload()
    canonical = canonicalize_transition_value(raw)
    assert canonical["unavailable_dimensions"] == ["a", "b"]
    assert transition_cid_for(raw) == cid_for_structured(canonical)
    with pytest.raises(ProgramTransitionError, match="strict DAG-JSON"):
        canonicalize_transition_value({"score": 0.99})
    with pytest.raises(ProgramTransitionError, match="strict DAG-JSON"):
        canonicalize_transition_value({"rank": 1.0})


def test_prediction_and_observation_are_disjoint_types() -> None:
    query = _query()
    prediction = _prediction(query)
    observation = _observation(query)
    assert prediction.SCHEMA != observation.SCHEMA
    assert prediction.proposal_only is True
    assert observation.proposal_only is False
    assert "observation_status" not in prediction.to_dict()
    assert "model_profile_cid" not in observation.to_dict()
    with pytest.raises(ProgramTransitionError, match="cannot decode as observations"):
        decode_transition_observation(prediction.to_dict())
    with pytest.raises(ProgramTransitionError, match="cannot decode as observations"):
        decode_transition_observation(_candidate(query).to_dict())
    restored = decode_transition_observation(observation.to_dict())
    assert restored.observation_cid == observation.observation_cid
    with pytest.raises(ProgramTransitionError, match="cannot be proposal-only"):
        ProgramTransitionObservation.from_dict({**observation.to_dict(), "proposal_only": True})
    predicted_as_observed = dict(prediction.to_dict())
    predicted_as_observed["schema"] = PROGRAM_TRANSITION_OBSERVATION_SCHEMA
    with pytest.raises(ProgramTransitionError):
        decode_transition_observation(predicted_as_observed)


def test_predictions_cannot_claim_authority() -> None:
    query = _query()
    prediction = _prediction(query)
    assert prediction_authority_violations(prediction) == ()
    assert prediction.proposal_only is True
    for flag in PREDICTION_AUTHORITY_FLAGS:
        assert getattr(prediction, flag) is False
    payload = prediction.to_dict()
    for flag in (
        "proves_contract",
        "proves_postcondition",
        "authorizes_mutation",
        "suppresses_validation",
        "suppresses_review",
        "establishes_equivalence",
        "establishes_observation",
        "establishes_completion",
        "invents_hashes",
        "proves_impossibility",
        "self_admitted",
        "authoritative",
        "prediction_authoritative",
    ):
        with pytest.raises(ProgramTransitionError, match="proposal-only"):
            ProgramTransitionPrediction.from_dict({**payload, flag: True})
    with pytest.raises(ProgramTransitionError, match="proposal-only"):
        ProgramTransitionPrediction.from_dict({**payload, "proposal_only": False})


def test_model_output_can_only_select_or_parameterize_a_bounded_candidate() -> None:
    query = _query()
    selected = select_and_parameterize_candidate(
        query,
        candidate_kind=CandidateKind.CALL_TARGET,
        selected_cid=query.allowed_symbol_cids[0],
        parameterization={"keyword": "ping"},
        rank=0,
    )
    assert selected.selected_cid == query.allowed_symbol_cids[0]
    assert selected.parameterization["keyword"] == "ping"
    assert selected.proposal_only is True
    with pytest.raises(ProgramTransitionError, match="outside the query"):
        select_and_parameterize_candidate(
            query,
            candidate_kind=CandidateKind.CALL_TARGET,
            selected_cid=_cid("not-in-universe"),
        )
    with pytest.raises(ProgramTransitionError, match="incomplete analysis"):
        select_and_parameterize_candidate(
            _query(allowed_symbol_cids=()),
            candidate_kind=CandidateKind.CALL_TARGET,
            selected_cid=_cid("sym-a"),
        )
    with pytest.raises(ProgramTransitionError, match="not admitted"):
        select_and_parameterize_candidate(
            query,
            candidate_kind=CandidateKind.REPAIR_OPERATOR,
            selected_cid=query.allowed_symbol_cids[0],
        )
    with pytest.raises(ProgramTransitionError, match="bounded candidate limit"):
        select_and_parameterize_candidate(
            query,
            candidate_kind=CandidateKind.CALL_TARGET,
            selected_cid=query.allowed_symbol_cids[0],
            rank=MAX_CANDIDATES,
        )
    with pytest.raises(ProgramTransitionError, match="invented-hash"):
        select_and_parameterize_candidate(
            query,
            candidate_kind=CandidateKind.CALL_TARGET,
            selected_cid=query.allowed_symbol_cids[0],
            parameterization={"invented_hash": "deadbeef"},
        )
    with pytest.raises(ProgramTransitionError, match="prove impossibility"):
        ProgramTransitionPrediction(
            query_cid=query.query_cid,
            subject_cid=query.subject_cid,
            model_profile_cid=_profile().model_profile_cid,
            candidate_cids=(),
            proposal_only=True,
        )


def test_candidate_current_cid_constraints() -> None:
    query = _query()
    candidate = _candidate(query)
    bind_candidate_to_query(query, candidate)
    stale_state = ProgramTransitionCandidate(
        query_cid=query.query_cid,
        candidate_kind=CandidateKind.CALL_TARGET,
        selected_cid=query.allowed_symbol_cids[0],
        query_family=query.query_family,
        current_subject_cid=query.subject_cid,
        current_source_cid=query.current_source_cid,
        current_environment_binding_cid=query.environment_binding_cid,
        current_state_cid=_cid("state-stale"),
        parameterization={},
    )
    with pytest.raises(ProgramTransitionError, match="current CID"):
        bind_candidate_to_query(query, stale_state)
    stale_env = ProgramTransitionCandidate(
        query_cid=query.query_cid,
        candidate_kind=CandidateKind.CALL_TARGET,
        selected_cid=query.allowed_symbol_cids[0],
        query_family=query.query_family,
        current_subject_cid=query.subject_cid,
        current_source_cid=query.current_source_cid,
        current_environment_binding_cid=_cid("env-stale"),
        current_state_cid=query.current_state_cid,
        parameterization={},
    )
    with pytest.raises(ProgramTransitionError, match="current CID"):
        bind_candidate_to_query(query, stale_env)
    other_query = _query(policy_cid=_cid("policy-other"))
    with pytest.raises(ProgramTransitionError, match="not bound"):
        bind_candidate_to_query(other_query, candidate)
    admission = admit_program_transition(
        query,
        current_subject_cid=query.subject_cid,
        current_source_cid=query.current_source_cid,
        current_environment_binding_cid=_cid("env-stale"),
        current_state_cid=query.current_state_cid,
        observation=_observation(query),
    )
    assert admission.verdict == AdmissionVerdict.STALE.value
    assert admission.may_influence_planning is False


def test_family_required_current_bindings() -> None:
    with pytest.raises(ProgramTransitionError, match="require current_state_cid"):
        _query(current_state_cid=None)
    with pytest.raises(ProgramTransitionError, match="require current_trace_cid"):
        ProgramTransitionQuery(
            query_family=QueryFamily.INVERSE_TRACE,
            language="python",
            subject_cid=_cid("trace-current"),
            current_source_cid=_cid("source-current"),
            environment_binding_cid=_cid("env-v1"),
            policy_cid=_cid("policy-v1"),
            allowed_symbol_cids=[_cid("ev-a")],
        )
    with pytest.raises(ProgramTransitionError, match="require current_graph_cid"):
        ProgramTransitionQuery(
            query_family=QueryFamily.REPAIR,
            language="python",
            subject_cid=_cid("graph-current"),
            current_source_cid=_cid("source-current"),
            environment_binding_cid=_cid("env-v1"),
            policy_cid=_cid("policy-v1"),
            allowed_operator_cids=[_cid("op-a")],
        )
    inverse = ProgramTransitionQuery(
        query_family=QueryFamily.INVERSE_TRACE,
        language="python",
        subject_cid=_cid("trace-current"),
        current_source_cid=_cid("source-current"),
        current_trace_cid=_cid("trace-current"),
        environment_binding_cid=_cid("env-v1"),
        policy_cid=_cid("policy-v1"),
        allowed_symbol_cids=[_cid("ev-a")],
    )
    assert inverse.current_trace_cid == _cid("trace-current")


def test_calibration_drift_is_an_integer_rational() -> None:
    profile = _profile()
    calibrated = _calibration(profile, trial_count=100, disagreement_count=1)
    assert calibrated.status == CalibrationStatus.CALIBRATED.value
    assert calibrated.may_propose is True
    assert calibrated.drifted is False
    drifted = _calibration(profile, trial_count=10, disagreement_count=1)
    assert drifted.status == CalibrationStatus.DRIFTED.value
    assert drifted.drifted is True
    assert drifted.may_propose is False
    recomputed = assess_calibration_drift(drifted)
    assert recomputed.calibration_cid == drifted.calibration_cid
    uncalibrated = _calibration(
        profile,
        trial_count=0,
        disagreement_count=0,
        expected_observation_cid=None,
        actual_observation_cid=None,
    )
    assert uncalibrated.status == CalibrationStatus.UNCALIBRATED.value
    with pytest.raises(ProgramTransitionError, match="does not match computed"):
        _calibration(profile, trial_count=10, disagreement_count=1, status="calibrated")
    with pytest.raises(ProgramTransitionError, match="cannot exceed"):
        _calibration(profile, trial_count=1, disagreement_count=2)
    query = _query()
    prediction = _prediction(query, model_profile=profile, calibration=drifted)
    admission = admit_program_transition(
        query,
        current_subject_cid=query.subject_cid,
        current_source_cid=query.current_source_cid,
        current_environment_binding_cid=query.environment_binding_cid,
        current_state_cid=query.current_state_cid,
        prediction=prediction,
        calibration=drifted,
    )
    assert admission.verdict == AdmissionVerdict.ABSTAIN.value
    assert may_influence_planning(admission) is False


def test_prediction_cannot_admit_or_influence_planning() -> None:
    query = _query()
    prediction = _prediction(query)
    admission = admit_program_transition(
        query,
        current_subject_cid=query.subject_cid,
        current_source_cid=query.current_source_cid,
        current_environment_binding_cid=query.environment_binding_cid,
        current_state_cid=query.current_state_cid,
        prediction=prediction,
    )
    assert admission.verdict == AdmissionVerdict.ABSTAIN.value
    assert admission.prediction_authoritative is False
    assert admission.may_influence_planning is False
    with pytest.raises(ProgramTransitionError, match="cannot self-admit"):
        ProgramTransitionAdmission(
            query_cid=query.query_cid,
            policy_cid=query.policy_cid,
            current_subject_cid=query.subject_cid,
            current_environment_binding_cid=query.environment_binding_cid,
            verdict=AdmissionVerdict.ADMITTED,
            prediction_cid=prediction.prediction_cid,
        )
    observed = _observation(query)
    admitted = admit_program_transition(
        query,
        current_subject_cid=query.subject_cid,
        current_source_cid=query.current_source_cid,
        current_environment_binding_cid=query.environment_binding_cid,
        current_state_cid=query.current_state_cid,
        prediction=prediction,
        observation=observed,
    )
    assert admitted.verdict == AdmissionVerdict.ADMITTED.value
    assert admitted.may_influence_planning is True
    receipt = issue_transition_receipt(
        query, admitted, prediction=prediction, observation=observed
    )
    assert receipt.may_influence_planning is True
    assert receipt.prediction_authoritative is False
    inferred = _observation(query, observation_status=ObservationStatus.INFERRED_UNTRUSTED)
    abstain = admit_program_transition(
        query,
        current_subject_cid=query.subject_cid,
        current_source_cid=query.current_source_cid,
        current_environment_binding_cid=query.environment_binding_cid,
        current_state_cid=query.current_state_cid,
        observation=inferred,
    )
    assert abstain.verdict == AdmissionVerdict.ABSTAIN.value
    validated = admit_program_transition(
        query,
        current_subject_cid=query.subject_cid,
        current_source_cid=query.current_source_cid,
        current_environment_binding_cid=query.environment_binding_cid,
        current_state_cid=query.current_state_cid,
        validation_evidence_cids=[_cid("proof-1")],
    )
    assert validated.verdict == AdmissionVerdict.ADMITTED.value
    assert validated.observation_cid is None
    assert validated.may_influence_planning is True


def test_repair_operator_delta_and_sketch_cannot_authorize_mutation() -> None:
    operator = _operator()
    assert operator.proposal_only is True
    assert operator.authorizes_mutation is False
    assert operator.bounded is True
    with pytest.raises(ProgramTransitionError, match="cannot authorize mutation"):
        _operator(authorizes_mutation=True)
    with pytest.raises(ProgramTransitionError, match="proposal-only"):
        _operator(proposal_only=False)
    with pytest.raises(ProgramTransitionError, match="must remain bounded"):
        _operator(bounded=False)
    query = _repair_query()
    candidate = select_and_parameterize_candidate(
        query,
        candidate_kind=CandidateKind.GRAPH_DELTA,
        selected_cid=query.allowed_operator_cids[0],
    )
    delta = ProgramGraphDeltaProposal(
        previous_snapshot_cid=query.current_graph_cid or _cid("graph-current"),
        query_cid=query.query_cid,
        candidate_cid=candidate.candidate_cid,
        added_node_cids=[_cid("n-add")],
        removed_node_cids=[_cid("n-rem")],
        retained_subroot_cids=[_cid("n-keep")],
    )
    assert delta.proposal_only is True
    assert delta.authorizes_mutation is False
    with pytest.raises(ProgramTransitionError, match="add and remove"):
        ProgramGraphDeltaProposal(
            previous_snapshot_cid=query.current_graph_cid or _cid("graph-current"),
            query_cid=query.query_cid,
            candidate_cid=candidate.candidate_cid,
            added_node_cids=[_cid("n-same")],
            removed_node_cids=[_cid("n-same")],
        )
    sketch = PatchSketchIR(
        language="python",
        sketch_kind=SketchKind.REPAIR,
        source_cid=query.current_source_cid,
        hole_cids=[_cid("hole-1"), _cid("hole-2")],
        operator_cids=[operator.repair_operator_cid],
    )
    assert sketch.complete_patch is False
    assert list(sketch.hole_cids) == [_cid("hole-1"), _cid("hole-2")]
    with pytest.raises(ProgramTransitionError, match="complete patch"):
        PatchSketchIR(
            language="python",
            sketch_kind="repair",
            source_cid=query.current_source_cid,
            hole_cids=[_cid("hole-1")],
            complete_patch=True,
        )
    with pytest.raises(ProgramTransitionError, match="cannot decode as observations"):
        decode_transition_observation(delta.to_dict())
    with pytest.raises(ProgramTransitionError, match="cannot decode as observations"):
        decode_transition_observation(sketch.to_dict())


def test_identity_projection_reuses_landed_transition_envelope() -> None:
    query = _query()
    prediction = _prediction(query)
    observation = _observation(query)
    admission = admit_program_transition(
        query,
        current_subject_cid=query.subject_cid,
        current_source_cid=query.current_source_cid,
        current_environment_binding_cid=query.environment_binding_cid,
        current_state_cid=query.current_state_cid,
        observation=observation,
        validation_evidence_cids=[_cid("proof-1")],
    )
    query_identity = TransitionIdentity.from_dict(query.to_identity_record())
    prediction_identity = TransitionIdentity.from_dict(prediction.to_identity_record())
    observation_identity = TransitionIdentity.from_dict(observation.to_identity_record())
    admission_identity = TransitionIdentity.from_dict(admission.to_identity_record())
    assert query_identity.SCHEMA == TRANSITION_IDENTITY_SCHEMA
    assert query_identity.transition_kind == "query"
    assert query_identity.proposal_only is False
    assert prediction_identity.transition_kind == "prediction"
    assert prediction_identity.proposal_only is True
    assert prediction_identity.model_profile_cid == prediction.model_profile_cid
    assert observation_identity.transition_kind == "observation"
    assert observation_identity.observation_status == "observed"
    assert admission_identity.transition_kind == "admission"
    assert admission_identity.policy_cid == query.policy_cid
    assert query_identity.transition_cid != prediction_identity.transition_cid
    assert prediction_identity.transition_cid != observation_identity.transition_cid


def test_unsupported_language_and_similarity_queries_fail_closed() -> None:
    with pytest.raises(ProgramTransitionError, match="typed unavailable"):
        _query(language="javascript")
    with pytest.raises(ProgramTransitionError, match="typed unavailable"):
        _operator(language="rust")
    assert ProgramLanguage.PYTHON.value in {"python"}
    with pytest.raises(ProgramTransitionError, match="not a program-transition query family"):
        _query(query_family="knn_next")
    with pytest.raises(ProgramTransitionError, match="trimmed NFC"):
        _query(unavailable_dimensions=["cafe\u0301"])


def test_abstaining_prediction_cannot_prove_impossibility() -> None:
    query = _query()
    profile = _profile()
    abstain = propose_program_transition(
        query, (), model_profile=profile, abstain=True
    )
    assert abstain.abstain is True
    assert abstain.candidate_cids == ()
    assert abstain.proves_impossibility is False
    with pytest.raises(ProgramTransitionError, match="cannot carry candidates"):
        propose_program_transition(
            query, [_candidate(query)], model_profile=profile, abstain=True
        )
    admission = admit_program_transition(
        query,
        current_subject_cid=query.subject_cid,
        current_source_cid=query.current_source_cid,
        current_environment_binding_cid=query.environment_binding_cid,
        current_state_cid=query.current_state_cid,
        prediction=abstain,
    )
    assert admission.verdict == AdmissionVerdict.ABSTAIN.value


def test_payload_schema_validates_closed_records_and_rejects_authority() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    payloads = _sample_payloads()
    for payload in payloads:
        validator.validate(payload)
    loaded = load_payload_schema()
    assert loaded["$id"].endswith("program-transition.payload.schema.json")
    extra = dict(payloads[0])
    extra["embedding"] = [0, 1]
    assert list(validator.iter_errors(extra))
    bad_version = dict(payloads[0])
    bad_version["schema"] = TRANSITION_MODEL_PROFILE_SCHEMA.replace("@1", "@99")
    assert list(validator.iter_errors(bad_version))
    assert list(validator.iter_errors({"schema": "not-a-payload", "x": 1}))
    prediction_payload = next(
        item for item in payloads if item.get("schema") == PROGRAM_TRANSITION_PREDICTION_SCHEMA
    )
    proves = dict(prediction_payload)
    proves["proves_contract"] = True
    assert list(validator.iter_errors(proves))
    mutation = dict(prediction_payload)
    mutation["authorizes_mutation"] = True
    assert list(validator.iter_errors(mutation))
    observed_as_proposal = next(
        item for item in payloads if item.get("schema") == PROGRAM_TRANSITION_OBSERVATION_SCHEMA
    )
    flipped = dict(observed_as_proposal)
    flipped["proposal_only"] = True
    assert list(validator.iter_errors(flipped))
    admission_payload = next(
        item for item in payloads if item.get("schema") == PROGRAM_TRANSITION_ADMISSION_SCHEMA
    )
    self_admit = dict(admission_payload)
    self_admit["prediction_authoritative"] = True
    assert list(validator.iter_errors(self_admit))
    prediction_only_admit = dict(admission_payload)
    prediction_only_admit["verdict"] = "admitted"
    prediction_only_admit["observation_cid"] = None
    prediction_only_admit["validation_evidence_cids"] = []
    assert list(validator.iter_errors(prediction_only_admit))
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    assert "program-transition-prediction@1" in text
    assert "additionalProperties" in text
    assert "proves_contract" in text
    assert "invents_hashes" in text
    assert SCHEMA_PATH.is_file()
    candidate_payload = next(
        item for item in payloads if item.get("schema") == PROGRAM_TRANSITION_CANDIDATE_SCHEMA
    )
    scored = dict(candidate_payload)
    scored["score"] = 1
    assert list(validator.iter_errors(scored))
    calibration_payload = next(
        item for item in payloads if item.get("schema") == TRANSITION_CALIBRATION_SCHEMA
    )
    validator.validate(calibration_payload)
    receipt_payload = next(
        item for item in payloads if item.get("schema") == PROGRAM_TRANSITION_RECEIPT_SCHEMA
    )
    influence_without_observation = dict(receipt_payload)
    influence_without_observation["observation_cid"] = None
    influence_without_observation["may_influence_planning"] = True
    assert list(validator.iter_errors(influence_without_observation))


def test_json_text_round_trip_uses_closed_decoder() -> None:
    query = _query()
    encoded = canonical_transition_bytes(query.to_dict()).decode("utf-8")
    decoded = loads_transition_json(encoded)
    restored = decode_transition_record(decoded)
    assert restored.to_dict() == query.to_dict()
    assert restored.query_cid == query.query_cid


def test_package_export_exposes_public_transition_interfaces() -> None:
    import ipfs_datasets_py.logic.software_contracts.semantic_state as pkg

    assert pkg.PROGRAM_TRANSITION_QUERY_INTERFACE == "ProgramTransitionQuery@1"
    assert pkg.PROGRAM_TRANSITION_PREDICTION_INTERFACE == "ProgramTransitionPrediction@1"
    assert pkg.PROGRAM_TRANSITION_OBSERVATION_INTERFACE == "ProgramTransitionObservation@1"
    assert pkg.PROGRAM_TRANSITION_ADMISSION_INTERFACE == "ProgramTransitionAdmission@1"
    assert pkg.REPAIR_OPERATOR_INTERFACE == "RepairOperator@1"
    assert pkg.ProgramTransitionQuery is ProgramTransitionQuery
    assert pkg.RepairOperator is RepairOperator
    assert "ProgramTransitionQuery" in pkg.__all__
    assert "admit_program_transition" in pkg.__all__


def test_module_import_is_hermetic() -> None:
    script = f"""\
import json
import os
import sys
import threading

before = dict(os.environ)
effects = []

def forbidden(name):
    def call(*args, **kwargs):
        effects.append(name)
        raise AssertionError(f"forbidden import side effect: {{name}}")
    return call

os.system = forbidden("os.system")

def _thread_start(self, *args, **kwargs):
    effects.append("threading.Thread.start")
    raise AssertionError("forbidden import side effect: threading.Thread.start")

threading.Thread.start = _thread_start

def audit(event, args):
    if event == "open" and len(args) > 2:
        flags = args[2]
        if isinstance(flags, int) and flags & (
            os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        ):
            effects.append("write:" + str(args[0]))
            raise AssertionError("forbidden import write")
    if event in {{
        "os.mkdir",
        "os.remove",
        "os.rmdir",
        "os.rename",
        "os.replace",
        "socket.connect",
        "subprocess.Popen",
    }}:
        effects.append(event)
        raise AssertionError(f"forbidden import side effect: {{event}}")

sys.addaudithook(audit)
import {_PACKAGE} as transitions
assert transitions.PROGRAM_TRANSITION_QUERY_INTERFACE == "ProgramTransitionQuery@1"
assert transitions.PROGRAM_TRANSITION_PREDICTION_INTERFACE == "ProgramTransitionPrediction@1"
assert os.environ == before
assert not effects
print(json.dumps({{"ok": True}}, sort_keys=True))
"""
    environment = dict(os.environ)
    environment.update(_OPT_OUTS)
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert json.loads(result.stdout.splitlines()[-1]) == {"ok": True}


def test_model_profile_must_abstain_on_ood_and_remain_proposal_only() -> None:
    with pytest.raises(ProgramTransitionError, match="abstain on out-of-distribution"):
        _profile(abstain_on_ood=False)
    with pytest.raises(ProgramTransitionError, match="cannot be authoritative"):
        _profile(authoritative=True)
    with pytest.raises(ProgramTransitionError, match="proposal-only"):
        _profile(proposal_only=False)
    query = _query()
    with pytest.raises(ProgramTransitionError, match="specialist_family"):
        propose_program_transition(
            query,
            [_candidate(query)],
            model_profile=_profile(specialist_family=SpecialistFamily.REPAIR),
        )
