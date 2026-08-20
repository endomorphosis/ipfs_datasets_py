"""Unit tests for omission diagnosis and ranking (SCG-014).

Acceptance criteria enforced here:

* Compressed fail plus expanded success yields ranked omission evidence.
* Both-context failure does not yield ranked omission evidence.
* Evidenced model insufficiency remains a route hypothesis.
"""

from __future__ import annotations

import copy

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_governor.audit_contracts import (
    CompressionAuditCase,
    CoveredArtifactKind,
    ExcludedArtifactRecord,
    ExclusionReason,
    ExpansionAction,
    GraphPath,
    HypothesisCause,
    OmissionEvidenceKind,
    SourceSpan,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.base import (
    AssumptionKind,
    ArtifactProvenance,
    AuthoritySource,
    ExecutionMode,
    GeneratorIdentity,
    GovernorArtifactHeader,
    GovernorAssumption,
    GovernorTerminalStatus,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.omission import (
    DIAGNOSE_OMISSION_INTERFACE,
    ComparativeOutcome,
    DependencyGraphView,
    OmissionDiagnosisError,
    PrimaryDiagnosisCause,
    RepositoryStateView,
    both_fail_outcomes,
    comparative_outcomes,
    diagnose_omission,
    diagnose_omission_interface_id,
    omission_supporting_outcomes,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _generator(**overrides: object) -> GeneratorIdentity:
    fields = {
        "generator_id": "audit_contracts",
        "generator_version": "1.0.0",
        "interface_id": "evaluate_context_sufficiency@1",
    }
    fields.update(overrides)
    return GeneratorIdentity(**fields)  # type: ignore[arg-type]


def _provenance(**overrides: object) -> ArtifactProvenance:
    fields = {
        "producer_id": "semantic_governor",
        "producer_version": "1",
        "execution_mode": ExecutionMode.LIVE,
        "authority_source": AuthoritySource.DETERMINISTIC,
        "input_cids": (_cid("input-a"),),
        "tool_ids": ("coverage.v1",),
        "policy_cid": _cid("policy"),
        "notes": None,
    }
    fields.update(overrides)
    return ArtifactProvenance(**fields)  # type: ignore[arg-type]


def _header(artifact_kind: str, **overrides: object) -> GovernorArtifactHeader:
    fields = {
        "artifact_kind": artifact_kind,
        "repository_state_cid": _cid("repo-state"),
        "context_pack_cid": _cid("context-pack"),
        "verification_bundle_cid": _cid("verification-bundle"),
        "generator": _generator(),
        "provenance": _provenance(),
        "terminal_status": GovernorTerminalStatus.COMPLETE,
        "assumptions": (
            GovernorAssumption(
                assumption_id="coverage_closed",
                kind=AssumptionKind.COVERAGE,
                statement="Coverage inventory is complete for the target cone",
                supporting_cids=(_cid("coverage"),),
            ),
        ),
        "metadata": {"track": "omission"},
    }
    fields.update(overrides)
    return GovernorArtifactHeader(**fields)  # type: ignore[arg-type]


def _path(*nodes: str) -> GraphPath:
    return GraphPath(
        nodes=nodes or ("target_fn", "helper_fn"),
        edge_relation="calls",
    )


def _span(path: str = "pkg/helper.py", start: int = 1, end: int = 5) -> SourceSpan:
    return SourceSpan(
        path=path, start_line=start, end_line=end, start_col=1, end_col=1
    )


def _exclusion(**overrides: object) -> ExcludedArtifactRecord:
    fields: dict[str, object] = {
        "artifact_id": "exc_helper",
        "artifact_kind": CoveredArtifactKind.SYMBOL,
        "exclusion_reason": ExclusionReason.EXACT_CAPSULE_SUBSTITUTED,
        "token_cost": 40,
        "confidence_bp": 9_500,
        "symbol_id": "helper_fn",
        "path": "pkg/helper.py",
        "artifact_cid": _cid("exc-helper"),
        "dependency_path": _path("target_fn", "helper_fn"),
        "source_span": _span(),
        "repository_state_cid": _cid("repo-state"),
        "substituted_by_artifact_id": "capsule_helper",
        "critical": True,
        "notes": None,
    }
    fields.update(overrides)
    return ExcludedArtifactRecord(**fields)  # type: ignore[arg-type]


def _case(**overrides: object) -> CompressionAuditCase:
    fields: dict[str, object] = {
        "header": _header("compression_audit_case"),
        "case_id": "case_local_bug",
        "task_id": "task_local_bug_001",
        "task_class": "local_bug",
        "risk_class": "medium",
        "coverage_manifest_cid": _cid("manifest"),
        "sufficiency_claim_cid": _cid("claim"),
        "decision_cid": _cid("decision"),
        "run_receipt_cid": None,
        "expansion_plan_cid": None,
        "omission_evidence_cid": None,
        "shadow_plan_cid": _cid("shadow-plan"),
        "shadow_result_cid": _cid("shadow-result"),
        "differential_report_cid": _cid("differential"),
        "policy_cid": _cid("policy"),
        "benchmark_partition": "development",
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return CompressionAuditCase(**fields)  # type: ignore[arg-type]


def _repo_state(**overrides: object) -> RepositoryStateView:
    fields: dict[str, object] = {
        "repository_state_cid": _cid("repo-state"),
        "context_pack_cid": _cid("context-pack"),
        "verification_bundle_cid": _cid("verification-bundle"),
        "differential_outcome": (
            ComparativeOutcome.COMPRESSED_FAILED_EXPANDED_SUCCEEDED.value
        ),
        "exclusions": (
            _exclusion(),
            _exclusion(
                artifact_id="exc_util",
                symbol_id="util_fn",
                path="pkg/util.py",
                artifact_cid=_cid("exc-util"),
                dependency_path=_path("target_fn", "util_fn"),
                source_span=_span("pkg/util.py", 1, 3),
                token_cost=20,
                confidence_bp=8_000,
                critical=False,
                exclusion_reason=ExclusionReason.CONSERVATIVE_CAPSULE_SUBSTITUTED,
                substituted_by_artifact_id="capsule_util",
            ),
        ),
        "target_symbol_ids": ("target_fn",),
        "counterexample_cids": (_cid("counterexample"),),
        "minimized_failure_cids": (_cid("minimized-failure"),),
        "model_insufficiency_evidence_cids": (),
        "expanded_artifact_ids": ("exc_helper",),
        "coverage_manifest_cid": _cid("manifest"),
        "policy_cid": _cid("policy"),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return RepositoryStateView(**fields)  # type: ignore[arg-type]


def _graph(**overrides: object) -> DependencyGraphView:
    fields: dict[str, object] = {
        "repository_state_cid": _cid("repo-state"),
        "paths": (
            _path("target_fn", "helper_fn"),
            _path("target_fn", "util_fn"),
        ),
        "node_artifact_ids": {
            "helper_fn": "exc_helper",
            "util_fn": "exc_util",
            "target_fn": "inc_target",
        },
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return DependencyGraphView(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Interface surface
# ---------------------------------------------------------------------------


def test_interface_pins() -> None:
    assert diagnose_omission_interface_id() == DIAGNOSE_OMISSION_INTERFACE
    assert DIAGNOSE_OMISSION_INTERFACE.endswith("@1")
    assert "compressed_failed_expanded_succeeded" in comparative_outcomes()
    assert "compressed_failed_expanded_succeeded" in omission_supporting_outcomes()
    assert "both_failed_same_reason" in both_fail_outcomes()
    assert "both_failed_different_reason" in both_fail_outcomes()


# ---------------------------------------------------------------------------
# Acceptance: compressed fail + expanded success → ranked omission evidence
# ---------------------------------------------------------------------------


def test_compressed_fail_expanded_success_yields_ranked_omission_evidence() -> None:
    result = diagnose_omission(_case(), _repo_state(), _graph())

    assert result.ranked_omission_supported is True
    assert result.evidence is not None
    assert result.primary_cause == PrimaryDiagnosisCause.OMISSION.value
    assert result.differential_outcome == (
        ComparativeOutcome.COMPRESSED_FAILED_EXPANDED_SUCCEEDED.value
    )
    assert len(result.hypotheses) >= 1

    # Ranked: rank 0 is best; ranks are contiguous from 0.
    ranks = [hyp.rank for hyp in result.hypotheses]
    assert ranks == list(range(len(result.hypotheses)))

    # Expanded match (exc_helper) should rank ahead of non-expanded utility.
    top = result.hypotheses[0]
    assert top.subject_artifact_id == "exc_helper"
    assert top.cause == HypothesisCause.OMISSION.value
    assert top.exclusion_reason == ExclusionReason.EXACT_CAPSULE_SUBSTITUTED.value
    assert top.expansion_action == ExpansionAction.INCLUDE_RAW_SOURCE.value
    assert top.expected_relevance_bp > 0
    assert top.confidence_bp > 0
    assert top.dependency_path is not None
    assert top.source_span is not None
    assert top.path == "pkg/helper.py"
    assert top.proposed_rule_change is not None

    # Evidence binds hypotheses and differential outcome.
    evidence = result.evidence
    assert evidence.differential_outcome == (
        ComparativeOutcome.COMPRESSED_FAILED_EXPANDED_SUCCEEDED.value
    )
    assert top.hypothesis_cid in evidence.hypothesis_cids
    assert evidence.counterexample_cid == _cid("counterexample")
    assert evidence.evidence_kind in {
        OmissionEvidenceKind.COUNTEREXAMPLE.value,
        OmissionEvidenceKind.EXPANSION_REPAIR.value,
        OmissionEvidenceKind.DIFFERENTIAL_OUTCOME.value,
    }
    assert evidence.confidence_bp > 0


def test_expanded_better_also_supports_omission_ranking() -> None:
    state = _repo_state(
        differential_outcome=ComparativeOutcome.EXPANDED_BETTER.value,
        expanded_artifact_ids=("exc_helper", "exc_util"),
    )
    result = diagnose_omission(_case(), state, _graph())
    assert result.ranked_omission_supported is True
    assert result.evidence is not None
    assert all(
        hyp.cause
        in {
            HypothesisCause.OMISSION.value,
            HypothesisCause.BUDGET_OVERFLOW.value,
        }
        for hyp in result.hypotheses
    )


def test_ranking_prefers_critical_expanded_match_over_low_relevance() -> None:
    state = _repo_state(
        exclusions=(
            _exclusion(
                artifact_id="exc_unrelated",
                symbol_id="unrelated_fn",
                path="pkg/unrelated.py",
                artifact_cid=_cid("exc-unrelated"),
                dependency_path=_path("other_fn", "unrelated_fn"),
                exclusion_reason=ExclusionReason.PROVEN_UNRELATED_BY_DEPENDENCY_GRAPH,
                critical=False,
                token_cost=5,
                confidence_bp=9_000,
                substituted_by_artifact_id=None,
            ),
            _exclusion(
                artifact_id="exc_helper",
                critical=True,
                exclusion_reason=ExclusionReason.BUDGET_EXCEEDED_ESCALATION_REQUIRED,
                token_cost=80,
                substituted_by_artifact_id=None,
            ),
        ),
        expanded_artifact_ids=("exc_helper",),
    )
    result = diagnose_omission(_case(), state, _graph())
    assert result.hypotheses[0].subject_artifact_id == "exc_helper"
    assert result.hypotheses[0].cause in {
        HypothesisCause.OMISSION.value,
        HypothesisCause.BUDGET_OVERFLOW.value,
    }


def test_budget_overflow_exclusion_maps_to_budget_cause() -> None:
    state = _repo_state(
        exclusions=(
            _exclusion(
                exclusion_reason=ExclusionReason.BUDGET_EXCEEDED_ESCALATION_REQUIRED,
                substituted_by_artifact_id=None,
            ),
        ),
        expanded_artifact_ids=("exc_helper",),
    )
    result = diagnose_omission(_case(), state, _graph())
    assert result.ranked_omission_supported is True
    assert result.hypotheses[0].cause == HypothesisCause.BUDGET_OVERFLOW.value
    assert result.primary_cause == PrimaryDiagnosisCause.BUDGET_OVERFLOW.value


# ---------------------------------------------------------------------------
# Acceptance: both fail does not yield ranked omission evidence
# ---------------------------------------------------------------------------


def test_both_failed_same_reason_does_not_yield_ranked_omission_evidence() -> None:
    state = _repo_state(
        differential_outcome=ComparativeOutcome.BOTH_FAILED_SAME_REASON.value,
        expanded_artifact_ids=(),
        model_insufficiency_evidence_cids=(),
    )
    result = diagnose_omission(_case(), state, _graph())

    assert result.ranked_omission_supported is False
    assert result.evidence is None
    assert result.differential_outcome == (
        ComparativeOutcome.BOTH_FAILED_SAME_REASON.value
    )
    # No omission-cause hypotheses blaming compression.
    assert all(
        hyp.cause != HypothesisCause.OMISSION.value for hyp in result.hypotheses
    )
    assert result.model_insufficiency_route_hypothesis is False
    assert result.primary_cause == PrimaryDiagnosisCause.UNKNOWN.value


def test_both_failed_different_reason_does_not_yield_ranked_omission_evidence() -> None:
    state = _repo_state(
        differential_outcome=ComparativeOutcome.BOTH_FAILED_DIFFERENT_REASON.value,
        expanded_artifact_ids=("exc_helper",),
        model_insufficiency_evidence_cids=(),
    )
    result = diagnose_omission(_case(), state, _graph())
    assert result.ranked_omission_supported is False
    assert result.evidence is None
    assert "both_fail_no_omission_blame" in result.metadata


# ---------------------------------------------------------------------------
# Acceptance: evidenced model insufficiency remains a route hypothesis
# ---------------------------------------------------------------------------


def test_both_fail_with_model_evidence_yields_route_hypothesis() -> None:
    state = _repo_state(
        differential_outcome=ComparativeOutcome.BOTH_FAILED_SAME_REASON.value,
        expanded_artifact_ids=(),
        model_insufficiency_evidence_cids=(_cid("model-insufficiency-receipt"),),
        counterexample_cids=(_cid("both-fail-counterexample"),),
    )
    result = diagnose_omission(_case(), state, _graph())

    assert result.ranked_omission_supported is False
    assert result.evidence is None
    assert result.model_insufficiency_route_hypothesis is True
    assert result.primary_cause == PrimaryDiagnosisCause.MODEL_INSUFFICIENCY.value
    assert len(result.hypotheses) == 1

    hyp = result.hypotheses[0]
    assert hyp.cause == HypothesisCause.MODEL_INSUFFICIENCY.value
    assert hyp.expansion_action == ExpansionAction.ESCALATE_ROUTE.value
    assert hyp.exclusion_reason is None
    assert hyp.rank == 0
    # Route hypothesis is explicitly not formal model-capability proof.
    assert hyp.metadata.get("formal_evidence") is False
    assert hyp.metadata.get("route_hypothesis") is True
    assert _cid("model-insufficiency-receipt") in hyp.supporting_evidence_cids


def test_model_insufficiency_never_automatic_without_evidence_cids() -> None:
    state = _repo_state(
        differential_outcome=ComparativeOutcome.BOTH_FAILED_DIFFERENT_REASON.value,
        model_insufficiency_evidence_cids=(),
    )
    result = diagnose_omission(_case(), state, _graph())
    assert result.model_insufficiency_route_hypothesis is False
    assert not any(
        hyp.cause == HypothesisCause.MODEL_INSUFFICIENCY.value
        for hyp in result.hypotheses
    )


def test_compressed_fail_expanded_success_does_not_claim_model_insufficiency() -> None:
    """Expansion repair attributes omission; model insufficiency is not primary."""
    state = _repo_state(
        model_insufficiency_evidence_cids=(_cid("model-noise"),),
    )
    result = diagnose_omission(_case(), state, _graph())
    assert result.ranked_omission_supported is True
    assert result.model_insufficiency_route_hypothesis is False
    assert result.primary_cause in {
        PrimaryDiagnosisCause.OMISSION.value,
        PrimaryDiagnosisCause.BUDGET_OVERFLOW.value,
    }


# ---------------------------------------------------------------------------
# Determinism and fail-closed invariants
# ---------------------------------------------------------------------------


def test_identical_inputs_yield_identical_diagnosis_cid() -> None:
    case = _case()
    state = _repo_state()
    graph = _graph()
    a = diagnose_omission(case, state, graph)
    b = diagnose_omission(case, state, graph)
    assert a.diagnosis_cid == b.diagnosis_cid
    assert a.evidence is not None and b.evidence is not None
    assert a.evidence.evidence_cid == b.evidence.evidence_cid
    assert [h.hypothesis_cid for h in a.hypotheses] == [
        h.hypothesis_cid for h in b.hypotheses
    ]


def test_mapping_inputs_round_trip_equivalent() -> None:
    case = _case()
    state = _repo_state()
    graph = _graph()
    direct = diagnose_omission(case, state, graph)
    via_mapping = diagnose_omission(
        case.to_dict(),
        {**state.identity_payload()},
        {**graph.identity_payload()},
    )
    assert direct.diagnosis_cid == via_mapping.diagnosis_cid


def test_repository_state_mismatch_rejects() -> None:
    graph = _graph(repository_state_cid=_cid("other-repo"))
    with pytest.raises(OmissionDiagnosisError, match="repository_state_cid"):
        diagnose_omission(_case(), _repo_state(), graph)


def test_equivalent_success_does_not_blame_compression() -> None:
    state = _repo_state(
        differential_outcome=ComparativeOutcome.EQUIVALENT_SUCCESS.value,
        expanded_artifact_ids=(),
    )
    result = diagnose_omission(_case(), state, _graph())
    assert result.ranked_omission_supported is False
    assert result.evidence is None
    assert result.primary_cause == PrimaryDiagnosisCause.NONE.value


def test_never_treats_model_reasoning_text_as_input() -> None:
    """Diagnosis inputs admit CIDs only — no free-form model reasoning fields."""
    state = _repo_state()
    payload = state.identity_payload()
    # Durable identity has no model_reasoning / explanation fields.
    assert "model_reasoning" not in payload
    assert "llm_explanation" not in payload
    result = diagnose_omission(_case(), state, _graph())
    for hyp in result.hypotheses:
        assert "model_reasoning" not in hyp.metadata
        assert "llm_authority" not in hyp.metadata


def test_private_metadata_rejected_on_repository_state() -> None:
    with pytest.raises(OmissionDiagnosisError):
        _repo_state(metadata={"private_source": "secret.py contents"})


def test_result_to_dict_contains_diagnosis_cid() -> None:
    result = diagnose_omission(_case(), _repo_state(), _graph())
    payload = result.to_dict()
    assert payload["diagnosis_cid"] == result.diagnosis_cid
    assert payload["interface_id"] == DIAGNOSE_OMISSION_INTERFACE
    assert payload["ranked_omission_supported"] is True
    assert isinstance(payload["hypotheses"], list)
    assert payload["evidence"]["evidence_cid"] == result.evidence.evidence_cid  # type: ignore[union-attr]


def test_copy_result_identity_stable() -> None:
    result = diagnose_omission(_case(), _repo_state(), _graph())
    cloned = copy.deepcopy(result.to_dict())
    # Re-construct via public API path (mapping diagnosis is not required;
    # identity is content-addressed from the live result).
    assert cloned["diagnosis_cid"] == result.diagnosis_cid


def test_schema_artifact_kinds_on_hypotheses_and_evidence() -> None:
    result = diagnose_omission(_case(), _repo_state(), _graph())
    assert result.header.artifact_kind == "omission_diagnosis"
    for hyp in result.hypotheses:
        assert hyp.header.artifact_kind == "omission_hypothesis"
    assert result.evidence is not None
    assert result.evidence.header.artifact_kind == "omission_evidence"


def test_omission_supporting_and_both_fail_are_disjoint() -> None:
    support = set(omission_supporting_outcomes())
    both = set(both_fail_outcomes())
    assert support.isdisjoint(both)
