"""Unit vectors for bounded equivalent-mutant analysis (AAE-025)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    ArtifactProvenance,
    AssuranceArtifactHeader,
    AssuranceTerminalStatus,
    AuthoritySource,
    ExecutionMode,
    GeneratorIdentity,
    VersionBinding,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.execution_contracts import (
    EquivalenceAssessmentStatus,
    EquivalenceMethod,
    MutationEquivalenceAssessment,
    equivalence_assessment_statuses,
    equivalence_methods,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.equivalence import (
    ASSESS_MUTATION_EQUIVALENCE_INTERFACE,
    GENERATOR_ID,
    BoundedBehaviorPair,
    EquivalenceAnalysisError,
    EquivalenceSubject,
    assess_mutation_equivalence,
    verify_equivalence_assessment_identity,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _generator(**overrides: object) -> GeneratorIdentity:
    fields = {
        "generator_id": "test_fixture",
        "generator_version": "1.0.0",
        "interface_id": "test_fixture@1",
    }
    fields.update(overrides)
    return GeneratorIdentity(**fields)  # type: ignore[arg-type]


def _versions(**overrides: object) -> VersionBinding:
    fields = {
        "operator_id": "control_flow_invert",
        "operator_version": "1",
        "campaign_policy_id": "default_campaign",
        "campaign_policy_version": "1.0.0",
        "generator": _generator(),
    }
    fields.update(overrides)
    return VersionBinding(**fields)  # type: ignore[arg-type]


def _provenance(**overrides: object) -> ArtifactProvenance:
    fields = {
        "producer_id": "adversarial_assurance",
        "producer_version": "1",
        "execution_mode": ExecutionMode.LIVE,
        "authority_source": AuthoritySource.OBSERVED,
        "input_cids": (_cid("input-a"),),
        "tool_ids": ("analyzer.v1",),
        "policy_cid": _cid("policy"),
        "notes": None,
    }
    fields.update(overrides)
    return ArtifactProvenance(**fields)  # type: ignore[arg-type]


def _header(**overrides: object) -> AssuranceArtifactHeader:
    fields = {
        "artifact_kind": "mutation_candidate",
        "repository_id": "repository:sha256:test-repo-identity",
        "repository_state_cid": _cid("repo-state"),
        "target_symbol_ids": ("mod.fn",),
        "target_artifact_cids": (_cid("artifact-a"),),
        "capsule_cids": (_cid("capsule-a"),),
        "proof_unit_cids": (_cid("proof-unit-a"),),
        "environment_cid": _cid("environment"),
        "dependency_lock_cid": _cid("dependency-lock"),
        "versions": _versions(),
        "provenance": _provenance(),
        "terminal_status": AssuranceTerminalStatus.COMPLETE,
        "receipt_cids": (_cid("receipt-a"),),
        "proof_cids": (_cid("proof-a"),),
        "metadata": {},
    }
    fields.update(overrides)
    return AssuranceArtifactHeader(**fields)  # type: ignore[arg-type]


def _subject(**overrides: object) -> EquivalenceSubject:
    original = "def fn(x):\n    return x + 1"
    fields = {
        "subject_id": "candidate.alpha.equivalence",
        "candidate_id": "candidate.alpha",
        "candidate_cid": _cid("candidate-alpha"),
        "original_source": original,
        "mutant_source": original,
        "observation_complete": True,
        "subject_cid": _cid("subject-alpha"),
        "original_normalized_ir": None,
        "mutant_normalized_ir": None,
        "original_reachable_fragment": None,
        "mutant_reachable_fragment": None,
        "reachability_observed": False,
        "symbolic_capability": False,
        "symbolic_verdict": None,
        "smt_capability": False,
        "smt_verdict": None,
        "bounded_behavior": (),
        "bounded_behavior_observed": False,
        "high_value": False,
        "likely_equivalent": False,
        "difficulty_to_kill": False,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return EquivalenceSubject(**fields)  # type: ignore[arg-type]


def test_closed_vocabularies() -> None:
    assert EquivalenceAssessmentStatus.UNKNOWN.value in equivalence_assessment_statuses()
    assert EquivalenceMethod.HUMAN_REVIEW.value in equivalence_methods()
    assert ASSESS_MUTATION_EQUIVALENCE_INTERFACE.endswith("@1")


def test_identical_source_is_equivalent_by_ast() -> None:
    result = assess_mutation_equivalence(_subject(), _header())
    assert result.assessment_status == EquivalenceAssessmentStatus.EQUIVALENT.value
    assert EquivalenceMethod.AST_COMPARISON.value in result.methods
    assert result.difficulty_to_kill_not_evidence is True
    assert result.header.artifact_kind == "mutation_equivalence_assessment"
    assert result.header.versions.generator.generator_id == GENERATOR_ID
    assert (
        result.header.versions.generator.interface_id
        == ASSESS_MUTATION_EQUIVALENCE_INTERFACE
    )
    assert verify_equivalence_assessment_identity(result) == result.assessment_cid
    restored = MutationEquivalenceAssessment.from_dict(result.to_dict())
    assert restored.assessment_cid == result.assessment_cid
    assert result.metadata["likely_equivalent_ignored"] is True
    assert result.metadata["difficulty_to_kill_ignored"] is True


def test_comment_and_whitespace_is_equivalent_or_probably_via_normalized_ir() -> None:
    original = "def fn(x):\n    return x + 1"
    mutant = "def fn(x):\n    # noise\n    return x + 1"
    result = assess_mutation_equivalence(
        _subject(mutant_source=mutant, original_source=original),
        _header(),
    )
    assert result.assessment_status in {
        EquivalenceAssessmentStatus.EQUIVALENT.value,
        EquivalenceAssessmentStatus.PROBABLY_EQUIVALENT.value,
    }
    assert EquivalenceMethod.NORMALIZED_IR.value in result.methods
    assert result.assessment_status != EquivalenceAssessmentStatus.NOT_EQUIVALENT.value
    assert EquivalenceMethod.AST_COMPARISON.value in result.metadata["method_verdicts"]


def test_constant_folding_agrees_on_folded_literals() -> None:
    original = "def fn():\n    return 1 + 1"
    mutant = "def fn():\n    return 2"
    result = assess_mutation_equivalence(
        _subject(original_source=original, mutant_source=mutant),
        _header(),
    )
    assert result.metadata["method_verdicts"][
        EquivalenceMethod.CONSTANT_PROPAGATION.value
    ] == "equivalent"
    assert result.assessment_status in {
        EquivalenceAssessmentStatus.EQUIVALENT.value,
        EquivalenceAssessmentStatus.PROBABLY_EQUIVALENT.value,
    }


def test_reachable_behavior_difference_is_not_equivalent() -> None:
    original = "def fn(x):\n    return x + 1"
    mutant = "def fn(x):\n    return x + 2"
    result = assess_mutation_equivalence(
        _subject(
            original_source=original,
            mutant_source=mutant,
            bounded_behavior_observed=True,
            bounded_behavior=(
                BoundedBehaviorPair(
                    input_cid=_cid("in-1"),
                    original_output_cid=_cid("out-2"),
                    mutant_output_cid=_cid("out-3"),
                ),
            ),
        ),
        _header(),
    )
    assert result.assessment_status == EquivalenceAssessmentStatus.NOT_EQUIVALENT.value
    assert EquivalenceMethod.BOUNDED_PUBLIC_BEHAVIOR.value in result.methods


def test_unreachable_fragment_only_change_is_equivalent_via_reachability() -> None:
    original = "def fn(x):\n    return x"
    mutant = "def fn(x):\n    if False:\n        return x + 1\n    return x"
    result = assess_mutation_equivalence(
        _subject(
            original_source=original,
            mutant_source=mutant,
            reachability_observed=True,
            original_reachable_fragment="return x",
            mutant_reachable_fragment="return x",
        ),
        _header(),
    )
    assert result.metadata["method_verdicts"][EquivalenceMethod.REACHABILITY.value] == (
        "equivalent"
    )
    assert result.assessment_status in {
        EquivalenceAssessmentStatus.EQUIVALENT.value,
        EquivalenceAssessmentStatus.PROBABLY_EQUIVALENT.value,
    }


def test_incomplete_observation_fails_closed() -> None:
    with pytest.raises(EquivalenceAnalysisError, match="observation_complete"):
        assess_mutation_equivalence(
            _subject(observation_complete=False),
            _header(),
        )


def test_unknown_never_becomes_equivalent_when_sources_differ_without_proof() -> None:
    original = "def fn(x):\n    return helper(x)"
    mutant = "def fn(x):\n    return other(x)"
    result = assess_mutation_equivalence(
        _subject(original_source=original, mutant_source=mutant),
        _header(),
    )
    assert result.assessment_status != EquivalenceAssessmentStatus.EQUIVALENT.value
    assert result.assessment_status in {
        EquivalenceAssessmentStatus.UNKNOWN.value,
        EquivalenceAssessmentStatus.NOT_EQUIVALENT.value,
        EquivalenceAssessmentStatus.PROBABLY_EQUIVALENT.value,
    }
    # Without behavior/SMT/symbolic, a live helper rename is at most probably_equivalent / unknown / not_equivalent.
    if result.assessment_status == EquivalenceAssessmentStatus.PROBABLY_EQUIVALENT.value:
        raise AssertionError("helper rename must not be probably_equivalent")


def test_high_value_unresolved_escalates_to_human_review() -> None:
    original = "def authorize(token):\n    return check(token)"
    mutant = "def authorize(token):\n    return check(token) or fallback(token)"
    result = assess_mutation_equivalence(
        _subject(
            original_source=original,
            mutant_source=mutant,
            high_value=True,
        ),
        _header(),
    )
    assert result.assessment_status == EquivalenceAssessmentStatus.UNKNOWN.value
    assert EquivalenceMethod.HUMAN_REVIEW.value in result.methods
    assert "human review" in (result.notes or "").lower()


def test_likely_equivalent_and_difficulty_to_kill_are_not_evidence() -> None:
    original = "def fn(x):\n    return helper(x)"
    mutant = "def fn(x):\n    return other(x)"
    result = assess_mutation_equivalence(
        _subject(
            original_source=original,
            mutant_source=mutant,
            likely_equivalent=True,
            difficulty_to_kill=True,
        ),
        _header(),
    )
    assert result.assessment_status != EquivalenceAssessmentStatus.EQUIVALENT.value
    assert result.difficulty_to_kill_not_evidence is True
    assert result.metadata["likely_equivalent_ignored"] is True


def test_missing_smt_capability_does_not_prove_equivalent() -> None:
    original = "def fn(x):\n    return x * 2"
    mutant = "def fn(x):\n    return x << 1"
    result = assess_mutation_equivalence(
        _subject(
            original_source=original,
            mutant_source=mutant,
            smt_capability=False,
        ),
        _header(),
    )
    assert result.metadata["method_verdicts"][EquivalenceMethod.RESTRICTED_SMT.value] == (
        "unavailable"
    )
    assert result.assessment_status != EquivalenceAssessmentStatus.EQUIVALENT.value


def test_smt_counterexample_is_not_equivalent() -> None:
    result = assess_mutation_equivalence(
        _subject(
            original_source="def fn(x):\n    return x",
            mutant_source="def fn(x):\n    return x + 0",
            smt_capability=True,
            smt_verdict="not_equivalent",
        ),
        _header(),
    )
    assert result.assessment_status == EquivalenceAssessmentStatus.NOT_EQUIVALENT.value
    assert EquivalenceMethod.RESTRICTED_SMT.value in result.methods


def test_symbolic_unavailable_is_typed_not_equivalent() -> None:
    result = assess_mutation_equivalence(_subject(), _header())
    assert result.metadata["method_verdicts"][
        EquivalenceMethod.SYMBOLIC_EXECUTION.value
    ] == "unavailable"


def test_forged_assessment_cid_is_rejected() -> None:
    result = assess_mutation_equivalence(_subject(), _header())
    payload = result.to_dict()
    payload["assessment_cid"] = _cid("forged")
    with pytest.raises(Exception):
        verify_equivalence_assessment_identity(payload)
