"""Public datasets semantic-governor analysis surface (SCG-018).

Independent pure analysis modules converge here: coverage, sufficiency,
untrusted-input detection, omission diagnosis, expansion planning,
calibration updates, and declarative rule proposals.

Exports are lazy. Importing this package does not open files, sockets,
processes, optional installers, or accelerate/kit implementation modules.
Callers may use either sealed canonical objects or closed mappings for the
required public entry points.
"""

from __future__ import annotations

import importlib
from typing import Any, Final


SEMANTIC_GOVERNOR_API_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-public-api@1"
)
SEMANTIC_GOVERNOR_PACKAGE_INTERFACE: Final[str] = "SemanticGovernorPublicApi@1"

# Primary public analysis entry points (SCG-G030).
REQUIRED_PUBLIC_APIS: Final[tuple[str, ...]] = (
    "build_context_coverage_manifest",
    "evaluate_context_sufficiency",
    "diagnose_omission",
    "plan_context_expansion",
    "update_calibration",
    "propose_rule_change",
)

# Supporting public operations frozen with the analysis surface.
SUPPORTING_PUBLIC_APIS: Final[tuple[str, ...]] = (
    "detect_instruction_like_content",
    "apply_trusted_decision",
    "merge_calibration_profiles",
    "validate_rule_proposal",
)


_EXPORTS: Final[dict[str, tuple[str, ...]]] = {
    "base": (
        "AssumptionKind",
        "ArtifactProvenance",
        "AuthoritySource",
        "ContextSufficiencyState",
        "ExecutionMode",
        "GOVERNOR_ARTIFACT_HEADER_INTERFACE",
        "GOVERNOR_ARTIFACT_HEADER_SCHEMA",
        "GeneratorIdentity",
        "GovernorArtifactHeader",
        "GovernorAssumption",
        "GovernorTerminalStatus",
        "SemanticGovernorBaseError",
        "context_sufficiency_states",
        "governor_terminal_statuses",
        "reject_private_and_model_authority",
        "verify_header_identity",
    ),
    "audit_contracts": (
        "COMPRESSION_AUDIT_CASE_INTERFACE",
        "CONTEXT_COVERAGE_MANIFEST_INTERFACE",
        "CONTEXT_EXPANSION_PLAN_INTERFACE",
        "CONTEXT_SUFFICIENCY_CLAIM_INTERFACE",
        "OMISSION_EVIDENCE_INTERFACE",
        "OMISSION_HYPOTHESIS_INTERFACE",
        "AuditContractError",
        "CompressionAuditCase",
        "ContextCoverageManifest",
        "ContextExpansionPlan",
        "ContextExpansionStep",
        "ContextSufficiencyClaim",
        "CoverageGap",
        "CoverageGapKind",
        "CoveredArtifactKind",
        "DecisionAction",
        "ExcludedArtifactRecord",
        "ExclusionReason",
        "ExpansionAction",
        "ExpansionStepStatus",
        "GovernorDecision",
        "GovernorRunReceipt",
        "GraphPath",
        "HypothesisCause",
        "IncludedArtifactRecord",
        "InclusionKind",
        "OmissionEvidence",
        "OmissionEvidenceKind",
        "OmissionHypothesis",
        "RouteTier",
        "SourceSpan",
        "SufficiencyEvidenceBasis",
        "assert_sufficiency_not_verification_only",
        "decision_actions",
        "exclusion_reasons",
        "expansion_actions",
        "hypothesis_causes",
        "inclusion_kinds",
        "route_tiers",
        "sufficiency_evidence_bases",
    ),
    "calibration_contracts": (
        "AnalyzerCalibrationProfile",
        "CalibrationContractError",
        "CapsuleCalibrationRecord",
        "ClassificationSource",
        "EmpiricalRate",
        "EvidencePartition",
        "ModelRouteCalibrationProfile",
        "ProofClassification",
        "TaskClassCalibrationProfile",
        "assert_proof_classification_allowed",
        "classification_sources",
        "evidence_partitions",
        "proof_classifications",
        "ratio_to_basis_points",
    ),
    "policy_contracts": (
        "CompressionPolicy",
        "CompressionPolicyCandidate",
        "CompressionPolicyPromotionReceipt",
        "DeclarativeRule",
        "EvaluationVerdict",
        "PolicyContractError",
        "ProtectedThresholds",
        "RuleCategory",
        "RuleEvaluationReport",
        "RuleOperation",
        "RuleProposal",
        "TaskClassAcceptanceRequirements",
        "assert_protected_threshold_change_authorized",
        "evaluation_verdicts",
        "rule_categories",
        "rule_operations",
        "validate_rule_dsl",
    ),
    "coverage": (
        "BUILD_CONTEXT_COVERAGE_MANIFEST_INTERFACE",
        "AnalysisConfidenceRank",
        "CoverageBuilderError",
        "CoverageExclusionView",
        "CoverageGapView",
        "CoverageInclusionView",
        "VerifiedCoverageView",
        "admitted_exclusion_reasons",
        "assert_exclusion_admissible",
        "build_context_coverage_manifest",
        "coverage_builder_interface_id",
        "heuristic_exclusion_labels",
    ),
    "sufficiency": (
        "EVALUATE_CONTEXT_SUFFICIENCY_INTERFACE",
        "CalibrationProfileView",
        "ContextPackView",
        "RepositoryStateView",
        "SufficiencyEvaluationView",
        "SufficiencyEvaluatorError",
        "VerificationPolicyView",
        "evaluate_context_sufficiency",
        "planned_check_fields",
        "recommended_decision_action",
        "required_check_matrix_fields",
        "sufficiency_evaluator_interface_id",
        "sufficiency_state_precedence",
    ),
    "untrusted_input": (
        "DETECT_INSTRUCTION_LIKE_CONTENT_INTERFACE",
        "UNTRUSTED_INSTRUCTION_EVIDENCE_INTERFACE",
        "DeterministicDecision",
        "InstructionLikeMatch",
        "InstructionLikePatternId",
        "QuarantineDisposition",
        "TrustedDecisionConfig",
        "UntrustedInputError",
        "UntrustedInputFragment",
        "UntrustedInstructionEvidence",
        "UntrustedSourceKind",
        "apply_trusted_decision",
        "detect_instruction_like_content",
        "detect_instruction_like_interface_id",
        "evidence_cannot_mutate_config",
        "instruction_like_pattern_ids",
        "protected_decision_domains",
        "reject_untrusted_authority_claims",
        "untrusted_source_kinds",
    ),
    "omission": (
        "DIAGNOSE_OMISSION_INTERFACE",
        "ComparativeOutcome",
        "DependencyGraphView",
        "OmissionDiagnosisError",
        "OmissionDiagnosisResult",
        "PrimaryDiagnosisCause",
        "both_fail_outcomes",
        "comparative_outcomes",
        "diagnose_omission",
        "diagnose_omission_interface_id",
        "omission_supporting_outcomes",
    ),
    "expansion": (
        "PLAN_CONTEXT_EXPANSION_INTERFACE",
        "ExpansionDisposition",
        "ExpansionPlanResult",
        "ExpansionPlannerError",
        "TokenBudgetView",
        "context_expansion_actions",
        "default_expansion_limits",
        "plan_context_expansion",
        "plan_context_expansion_interface_id",
        "route_escalation_actions",
    ),
    "calibration": (
        "UPDATE_CALIBRATION_INTERFACE",
        "MERGE_CALIBRATION_PROFILES_INTERFACE",
        "CalibrationDisposition",
        "CalibrationError",
        "CalibrationKind",
        "CalibrationMergeResult",
        "CalibrationObservation",
        "CalibrationUpdateResult",
        "build_empirical_rate",
        "calibration_dispositions",
        "calibration_kinds",
        "merge_calibration_profiles",
        "merge_calibration_profiles_interface_id",
        "observation_from_outcome",
        "update_calibration",
        "update_calibration_interface_id",
        "wilson_score_interval_bp",
    ),
    "rules": (
        "PROPOSE_RULE_CHANGE_INTERFACE",
        "VALIDATE_RULE_PROPOSAL_INTERFACE",
        "AssuranceImpact",
        "ProposalMode",
        "RuleProposalDisposition",
        "RuleProposalError",
        "RuleProposalResult",
        "RuleProposalValidationReport",
        "RuleSafetyAnalysis",
        "ValidationVerdict",
        "analyze_rule_assurance_impact",
        "is_high_risk_assurance_reduction",
        "proposal_modes",
        "propose_rule_change",
        "propose_rule_change_interface_id",
        "rule_proposal_dispositions",
        "validate_rule_proposal",
        "validate_rule_proposal_interface_id",
        "validation_verdicts",
    ),
}

_EXPORT_MODULE: Final[dict[str, str]] = {
    name: module_name
    for module_name, names in _EXPORTS.items()
    for name in names
}

if len(_EXPORT_MODULE) != sum(len(names) for names in _EXPORTS.values()):
    raise RuntimeError("package exports must have one owning module per symbol")

# Package-local constants are not lazy.
_LOCAL_EXPORTS: Final[tuple[str, ...]] = (
    "SEMANTIC_GOVERNOR_API_SCHEMA",
    "SEMANTIC_GOVERNOR_PACKAGE_INTERFACE",
    "REQUIRED_PUBLIC_APIS",
    "SUPPORTING_PUBLIC_APIS",
    "public_api_interface_id",
    "public_api_schema",
    "required_public_apis",
    "supporting_public_apis",
)

__all__ = sorted(set(_EXPORT_MODULE) | set(_LOCAL_EXPORTS))


def public_api_interface_id() -> str:
    """Return the versioned public package interface pin."""

    return SEMANTIC_GOVERNOR_PACKAGE_INTERFACE


def public_api_schema() -> str:
    """Return the public API schema identifier."""

    return SEMANTIC_GOVERNOR_API_SCHEMA


def required_public_apis() -> tuple[str, ...]:
    """Return the closed primary public analysis entry-point names."""

    return REQUIRED_PUBLIC_APIS


def supporting_public_apis() -> tuple[str, ...]:
    """Return supporting public operations frozen with this package."""

    return SUPPORTING_PUBLIC_APIS


def __getattr__(name: str) -> Any:
    """Load a reviewed public symbol from its owning leaf module (lazy)."""

    module_name = _EXPORT_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
