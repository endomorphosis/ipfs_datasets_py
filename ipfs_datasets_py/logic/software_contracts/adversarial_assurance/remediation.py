"""Requirement-grounded candidate remediation specification (AAE-032).

Interface surface:

* ``propose_gap_remediation@1`` — map a minimized survivor report and diagnosed
  assurance gap onto closed, requirement-grounded candidate remediations and a
  sealed ``GapRemediationPlan@1``.

Authority rules (normative):

* Pure and deterministic: no store, worktree, or production-policy mutation.
* Canonical identity comes only from ``software_contracts.content``.
* Allowed candidate types bind intended behavior and requirement provenance.
* Candidate tests never merely freeze the current implementation.
* Proof candidates always bind practical nonvacuity (satisfiable antecedents).
* Model-generated drafts begin and remain ``heuristic_candidate``; they cannot
  self-promote without bound evaluation evidence.
* Non-remediable gap classes (unknown / intentional / equivalent / ambiguous)
  fail closed rather than invent overfit constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence
import re
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    AssuranceArtifactHeader,
    AssuranceBaseError,
    reject_private_model_authority_and_host_fallbacks,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.analysis_contracts import (
    AnalysisContractError,
    AssuranceGap,
    AssuranceGapClass,
    SurvivingMutantReport,
    SurvivorRiskClass,
    verify_gap_identity,
    verify_survivor_report_identity,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.remediation_contracts import (
    CandidateAnalyzerRule,
    CandidateDraftStatus,
    CandidateKind,
    CandidatePolicyConstraint,
    CandidateProofObligation,
    CandidateTestSpecification,
    GapRemediationPlan,
    MutationClassToken,
    NonvacuityCondition,
    RemediationContractError,
    RemediationPlanStatus,
    RemediationRiskClass,
    RequirementProvenance,
    verify_candidate_analyzer_identity,
    verify_candidate_policy_identity,
    verify_candidate_proof_identity,
    verify_candidate_test_identity,
    verify_plan_identity,
)

# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

PROPOSE_GAP_REMEDIATION_INTERFACE: Final[str] = "propose_gap_remediation@1"
GAP_REMEDIATION_PROPOSAL_INTERFACE: Final[str] = "GapRemediationProposal@1"
GAP_REMEDIATION_PROPOSAL_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-gap-remediation-proposal@1"
)

GENERATOR_ID: Final[str] = "remediation_spec"
GENERATOR_VERSION: Final[str] = "1.0.0"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CANDIDATES: Final[int] = 32
MAX_PATH_CHARS: Final[int] = 1_024

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_SYMBOL_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+@#$-]{0,511}$"
)

# Gap classes that must not invent automatic remediations.
_NON_REMEDIABLE_GAP_CLASSES: Final[frozenset[str]] = frozenset(
    {
        AssuranceGapClass.SPECIFICATION_AMBIGUITY.value,
        AssuranceGapClass.INTENTIONALLY_UNCONSTRAINED.value,
        AssuranceGapClass.PROBABLY_EQUIVALENT.value,
        AssuranceGapClass.UNKNOWN.value,
    }
)

# Deterministic primary candidate-kind proposals by gap class (plan §10).
# Values are closed ``CandidateKind`` tokens. Kinds without a dedicated durable
# model are emitted via the nearest durable model and annotated in metadata.
_GAP_CLASS_PRIMARY_KINDS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        AssuranceGapClass.MISSING_TEST.value: (
            CandidateKind.ADDITIONAL_TEST.value,
        ),
        AssuranceGapClass.WEAK_ASSERTION.value: (
            CandidateKind.STRONGER_TEST.value,
        ),
        AssuranceGapClass.MISSING_PROOF_OBLIGATION.value: (
            CandidateKind.PROOF_OBLIGATION.value,
        ),
        AssuranceGapClass.VACUOUS_PROOF.value: (
            CandidateKind.PROOF_OBLIGATION.value,
        ),
        AssuranceGapClass.MISSING_POLICY_CONSTRAINT.value: (
            CandidateKind.POLICY_CONSTRAINT.value,
        ),
        AssuranceGapClass.STALE_OR_INCOMPLETE_DEPENDENCY_EDGE.value: (
            CandidateKind.DEPENDENCY_EDGE.value,
        ),
        AssuranceGapClass.CAPSULE_COMPLETENESS_FAILURE.value: (
            CandidateKind.CAPSULE_FIELD.value,
        ),
        AssuranceGapClass.TEST_SELECTION_FAILURE.value: (
            CandidateKind.FULL_SUITE_FALLBACK.value,
            CandidateKind.ADDITIONAL_TEST.value,
        ),
        AssuranceGapClass.UNMODELED_SIDE_EFFECT.value: (
            CandidateKind.PROPERTY_TEST.value,
            CandidateKind.PROOF_OBLIGATION.value,
        ),
        AssuranceGapClass.MISSING_STATE_TRANSITION_CONSTRAINT.value: (
            CandidateKind.STATE_MACHINE_INVARIANT.value,
            CandidateKind.PROOF_OBLIGATION.value,
        ),
        AssuranceGapClass.MISSING_ENVIRONMENT_BINDING.value: (
            CandidateKind.MANIFEST_REQUIREMENT.value,
            CandidateKind.INVALIDATION_RULE.value,
        ),
        AssuranceGapClass.RECEIPT_AUTHENTICITY_GAP.value: (
            CandidateKind.INVALIDATION_RULE.value,
            CandidateKind.PROOF_OBLIGATION.value,
        ),
    }
)

_TEST_KINDS: Final[frozenset[str]] = frozenset(
    {
        CandidateKind.ADDITIONAL_TEST.value,
        CandidateKind.STRONGER_TEST.value,
        CandidateKind.PROPERTY_TEST.value,
    }
)
_PROOF_KINDS: Final[frozenset[str]] = frozenset(
    {
        CandidateKind.PROOF_OBLIGATION.value,
        CandidateKind.PRECONDITION.value,
        CandidateKind.POSTCONDITION.value,
    }
)
_POLICY_KINDS: Final[frozenset[str]] = frozenset(
    {
        CandidateKind.POLICY_CONSTRAINT.value,
        CandidateKind.STATE_MACHINE_INVARIANT.value,
    }
)
_ANALYZER_KINDS: Final[frozenset[str]] = frozenset(
    {
        CandidateKind.DEPENDENCY_EDGE.value,
        CandidateKind.INVALIDATION_RULE.value,
        CandidateKind.CAPSULE_FIELD.value,
        CandidateKind.MANIFEST_REQUIREMENT.value,
        CandidateKind.FULL_SUITE_FALLBACK.value,
    }
)

_RISK_TO_MUTATION: Final[Mapping[str, str]] = MappingProxyType(
    {
        SurvivorRiskClass.CRITICAL_SECURITY.value: (
            MutationClassToken.AUTHORIZATION_POLICY.value
        ),
        SurvivorRiskClass.AUTHORIZATION.value: (
            MutationClassToken.AUTHORIZATION_POLICY.value
        ),
        SurvivorRiskClass.DURABILITY.value: (
            MutationClassToken.STORAGE_DURABILITY.value
        ),
        SurvivorRiskClass.FINANCIAL_LEGAL.value: MutationClassToken.DATA_SCHEMA.value,
        SurvivorRiskClass.DISTRIBUTED_TRANSITION.value: (
            MutationClassToken.STATE_DISTRIBUTED.value
        ),
        SurvivorRiskClass.PROOF_RECEIPT_TRUST.value: (
            MutationClassToken.TEST_PROOF.value
        ),
        SurvivorRiskClass.CRITICAL_INVARIANT.value: (
            MutationClassToken.INTERFACE_CONTRACT.value
        ),
        SurvivorRiskClass.HIGH.value: MutationClassToken.CONTROL_FLOW.value,
        SurvivorRiskClass.MEDIUM.value: MutationClassToken.CONTROL_FLOW.value,
        SurvivorRiskClass.LOCAL_BUG.value: MutationClassToken.CONTROL_FLOW.value,
        SurvivorRiskClass.LOW.value: MutationClassToken.CONTROL_FLOW.value,
    }
)

_GAP_TO_MUTATION_OVERRIDE: Final[Mapping[str, str]] = MappingProxyType(
    {
        AssuranceGapClass.UNMODELED_SIDE_EFFECT.value: (
            MutationClassToken.SIDE_EFFECT.value
        ),
        AssuranceGapClass.MISSING_STATE_TRANSITION_CONSTRAINT.value: (
            MutationClassToken.STATE_DISTRIBUTED.value
        ),
        AssuranceGapClass.RECEIPT_AUTHENTICITY_GAP.value: (
            MutationClassToken.TEST_PROOF.value
        ),
        AssuranceGapClass.CAPSULE_COMPLETENESS_FAILURE.value: (
            MutationClassToken.SEMANTIC_COMPRESSION.value
        ),
        AssuranceGapClass.STALE_OR_INCOMPLETE_DEPENDENCY_EDGE.value: (
            MutationClassToken.SEMANTIC_COMPRESSION.value
        ),
        AssuranceGapClass.WEAK_ASSERTION.value: MutationClassToken.ERROR_RETRY.value,
        AssuranceGapClass.MISSING_POLICY_CONSTRAINT.value: (
            MutationClassToken.AUTHORIZATION_POLICY.value
        ),
    }
)


class RemediationError(AssuranceBaseError):
    """Raised when gap remediation proposal inputs are unsafe or non-remediable."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False, maximum: int = MAX_TEXT_CHARS) -> str:
    if type(value) is not str or (not empty and not value):
        raise RemediationError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise RemediationError(f"{name} must be trimmed NFC text")
    if len(value) > maximum or any(not char.isprintable() for char in value):
        raise RemediationError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise RemediationError(f"{name} must be a boolean")
    return value


def _token(value: Any, name: str) -> str:
    if type(value) is not str or not _TOKEN_RE.fullmatch(value):
        raise RemediationError(f"{name} must be a closed token")
    return value


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise RemediationError(f"{name} must be a valid CID") from exc


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise RemediationError(f"{name} has unsupported value {value!r}") from exc


def _freeze_structured(value: Any) -> Any:
    try:
        validate_structured_value(value)
    except Exception as exc:
        raise RemediationError(f"structured value rejected: {exc}") from exc
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_structured(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_structured(item) for item in value)
    return value


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_structured(item) for item in value]
    return value


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise RemediationError(f"{name} must be a mapping")
    unknown = set(data) - fields
    if unknown:
        raise RemediationError(
            f"{name} contains unknown fields: {sorted(unknown)}"
        )
    return dict(data)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise RemediationError(f"{name} must be a mapping")
    reject_private_model_authority_and_host_fallbacks(dict(value), path=name)
    return MappingProxyType(_freeze_structured(dict(value)))


def _unique_sorted_tokens(
    values: Iterable[Any],
    name: str,
    *,
    maximum: int = MAX_CANDIDATES,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise RemediationError(f"{name} must be a list")
    if len(values) > maximum:
        raise RemediationError(f"{name} exceeds maximum length")
    tokens = tuple(sorted({_token(item, name) for item in values}))
    return tokens


def _artifact_header(
    base: AssuranceArtifactHeader,
    *,
    artifact_kind: str,
    interface_id: str,
    symbol_ids: Sequence[str] | None = None,
) -> AssuranceArtifactHeader:
    """Clone a header for a derived remediation artifact."""

    versions = base.versions
    generator = versions.generator
    new_generator = type(generator)(
        generator_id=GENERATOR_ID,
        generator_version=GENERATOR_VERSION,
        interface_id=interface_id,
    )
    new_versions = type(versions)(
        operator_id=versions.operator_id,
        operator_version=versions.operator_version,
        campaign_policy_id=versions.campaign_policy_id,
        campaign_policy_version=versions.campaign_policy_version,
        generator=new_generator,
    )
    symbols = (
        tuple(symbol_ids)
        if symbol_ids is not None
        else tuple(base.target_symbol_ids)
    )
    return AssuranceArtifactHeader(
        artifact_kind=artifact_kind,
        repository_id=base.repository_id,
        repository_state_cid=base.repository_state_cid,
        target_symbol_ids=symbols,
        target_artifact_cids=tuple(base.target_artifact_cids),
        capsule_cids=tuple(base.capsule_cids),
        proof_unit_cids=tuple(base.proof_unit_cids),
        environment_cid=base.environment_cid,
        dependency_lock_cid=base.dependency_lock_cid,
        versions=new_versions,
        provenance=base.provenance,
        terminal_status=base.terminal_status,
        receipt_cids=tuple(base.receipt_cids),
        proof_cids=tuple(base.proof_cids),
        metadata=dict(base.metadata),
    )


def _normalize_survivor(
    value: SurvivingMutantReport | Mapping[str, Any],
) -> SurvivingMutantReport:
    if isinstance(value, SurvivingMutantReport):
        sealed = value
    elif isinstance(value, Mapping):
        try:
            sealed = SurvivingMutantReport.from_dict(value)
        except (AnalysisContractError, TypeError, KeyError) as exc:
            raise RemediationError(
                f"surviving_mutant is malformed: {exc}"
            ) from exc
    else:
        raise RemediationError(
            "surviving_mutant must be SurvivingMutantReport or mapping"
        )
    try:
        verify_survivor_report_identity(sealed)
    except AnalysisContractError as exc:
        raise RemediationError(f"surviving_mutant identity failed: {exc}") from exc
    return sealed


def _normalize_gap(value: AssuranceGap | Mapping[str, Any]) -> AssuranceGap:
    if isinstance(value, AssuranceGap):
        sealed = value
    elif isinstance(value, Mapping):
        try:
            sealed = AssuranceGap.from_dict(value)
        except (AnalysisContractError, TypeError, KeyError) as exc:
            raise RemediationError(f"assurance_gap is malformed: {exc}") from exc
    else:
        raise RemediationError("assurance_gap must be AssuranceGap or mapping")
    try:
        verify_gap_identity(sealed)
    except AnalysisContractError as exc:
        raise RemediationError(f"assurance_gap identity failed: {exc}") from exc
    return sealed


def _bind_survivor_and_gap(
    survivor: SurvivingMutantReport,
    gap: AssuranceGap,
) -> None:
    """Fail closed when survivor and gap are inconsistent."""

    if survivor.header.repository_id != gap.header.repository_id:
        raise RemediationError(
            "surviving_mutant and assurance_gap repository_id must match"
        )
    if survivor.header.repository_state_cid != gap.header.repository_state_cid:
        raise RemediationError(
            "surviving_mutant and assurance_gap repository_state_cid must match"
        )
    if gap.survivor_report_cid is not None and gap.survivor_report_cid != (
        survivor.report_cid
    ):
        raise RemediationError(
            "assurance_gap.survivor_report_cid must match surviving_mutant.report_cid"
        )
    if gap.candidate_id is not None and gap.candidate_id != survivor.candidate_id:
        raise RemediationError(
            "assurance_gap.candidate_id must match surviving_mutant.candidate_id"
        )
    if gap.candidate_cid is not None and gap.candidate_cid != survivor.candidate_cid:
        raise RemediationError(
            "assurance_gap.candidate_cid must match surviving_mutant.candidate_cid"
        )
    if gap.risk_class != survivor.risk_class:
        raise RemediationError(
            "assurance_gap.risk_class must match surviving_mutant.risk_class"
        )
    gap_symbols = set(gap.symbol_ids)
    survivor_symbols = set(survivor.symbol_ids)
    if not gap_symbols.intersection(survivor_symbols):
        raise RemediationError(
            "assurance_gap.symbol_ids must overlap surviving_mutant.symbol_ids"
        )
    if gap.violated_or_missing_property != survivor.violated_or_missing_property:
        raise RemediationError(
            "assurance_gap.violated_or_missing_property must match "
            "surviving_mutant.violated_or_missing_property"
        )


def _risk_class(value: str) -> str:
    return _enum(value, RemediationRiskClass, "risk_class")


def _mutation_class_for(gap: AssuranceGap) -> str:
    override = _GAP_TO_MUTATION_OVERRIDE.get(gap.gap_class)
    if override is not None:
        return override
    mapped = _RISK_TO_MUTATION.get(gap.risk_class)
    if mapped is None:
        return MutationClassToken.CONTROL_FLOW.value
    return mapped


def _token_slug(value: str, *, fallback: str = "item") -> str:
    """Deterministically coerce free text into a closed token fragment."""

    lowered = value.strip().lower()
    cleaned = re.sub(r"[^a-z0-9_.:/+-]+", "_", lowered)
    cleaned = cleaned.strip("_.")
    if not cleaned:
        cleaned = fallback
    if cleaned[0].isdigit():
        cleaned = f"x_{cleaned}"
    if not _TOKEN_RE.fullmatch(cleaned):
        cleaned = re.sub(r"[^a-z0-9_]", "", cleaned) or fallback
        if cleaned[0].isdigit():
            cleaned = f"x_{cleaned}"
    return cleaned[:120]


def _intended_behavior(survivor: SurvivingMutantReport, gap: AssuranceGap) -> str:
    """Bind intended behavior to expected requirement, not observed output."""

    # Prefer the shared violated/missing property phrased as required behavior.
    # Survivor expected_behavior is requirement-grounded; observed is not.
    behavior = survivor.expected_behavior
    if not behavior:
        behavior = gap.violated_or_missing_property
    return _text(behavior, "intended_behavior")


def _requirement_provenance(
    survivor: SurvivingMutantReport,
    gap: AssuranceGap,
    *,
    intended_behavior: str,
) -> RequirementProvenance:
    meta = dict(gap.metadata)
    requirement_id = meta.get("requirement_id")
    if requirement_id is None:
        requirement_id = f"req_{_token_slug(gap.gap_id, fallback='gap')}"
    source_id = meta.get("requirement_source_id") or meta.get("source_id")
    if source_id is None:
        source_id = f"spec_{_token_slug(gap.gap_class, fallback='gap')}"
    requirement_cid = meta.get("requirement_cid")
    source_path = meta.get("requirement_source_path") or meta.get("source_path")
    if source_path is None and survivor.source_spans:
        source_path = survivor.source_spans[0].path
    notes = meta.get("requirement_notes")
    try:
        return RequirementProvenance(
            requirement_id=_token(str(requirement_id), "requirement_id"),
            intended_behavior=intended_behavior,
            source_id=_token(str(source_id), "source_id"),
            requirement_cid=requirement_cid,
            source_path=source_path,
            notes=notes if notes is None else str(notes),
        )
    except RemediationContractError as exc:
        raise RemediationError(f"requirement provenance invalid: {exc}") from exc


def _candidate_id(gap: AssuranceGap, kind: str, index: int) -> str:
    return _token(
        f"cand_{_token_slug(gap.gap_id)}_{_token_slug(kind)}_{index}",
        "candidate_id",
    )


def _source_path_for_test(survivor: SurvivingMutantReport, gap: AssuranceGap) -> str:
    primary = survivor.source_spans[0].path if survivor.source_spans else "src/module.py"
    # Tests bind requirement-grounded observations; path is a candidate location.
    slug = _token_slug(gap.gap_id, fallback="gap")
    base = primary.rsplit("/", 1)[-1]
    base = re.sub(r"\.[A-Za-z0-9]+$", "", base)
    path = f"tests/remediation/test_{_token_slug(base)}_{slug}.py"
    if len(path) > MAX_PATH_CHARS:
        path = path[:MAX_PATH_CHARS]
    return path


def _build_test_candidate(
    *,
    kind: str,
    survivor: SurvivingMutantReport,
    gap: AssuranceGap,
    intended_behavior: str,
    provenance: RequirementProvenance,
    mutation_class: str,
    index: int,
) -> CandidateTestSpecification:
    header = _artifact_header(
        gap.header,
        artifact_kind="candidate_test_specification",
        interface_id=PROPOSE_GAP_REMEDIATION_INTERFACE,
        symbol_ids=tuple(sorted(set(gap.symbol_ids) | set(survivor.symbol_ids))),
    )
    setup = (
        f"prepare fixtures that exercise {_token_slug(gap.gap_class)} for "
        f"{', '.join(gap.symbol_ids)}"
    )
    observation = (
        f"observe that intended behavior holds: {intended_behavior}; "
        f"do not assert current observed output "
        f"({survivor.observed_behavior})"
    )
    notes = (
        f"heuristic candidate for gap_class={gap.gap_class}; "
        "freezes_implementation=false"
    )
    try:
        candidate = CandidateTestSpecification(
            header=header,
            candidate_id=_candidate_id(gap, kind, index),
            candidate_kind=kind,
            draft_status=CandidateDraftStatus.HEURISTIC_CANDIDATE,
            intended_behavior=intended_behavior,
            symbol_ids=tuple(sorted(set(gap.symbol_ids) | set(survivor.symbol_ids))),
            setup_description=setup,
            observation_description=observation,
            killed_mutation_classes=(mutation_class,),
            requirement_provenances=(provenance,),
            risk_class=_risk_class(gap.risk_class),
            freezes_implementation=False,
            input_cid=survivor.minimized_evidence.reproduction_input_cid,
            fixture_ids=(f"fx_{_token_slug(gap.gap_id)}",),
            observation_points=(
                f"obs_{_token_slug(gap.violated_or_missing_property, fallback='prop')}",
            ),
            source_path=_source_path_for_test(survivor, gap),
            gap_cids=(gap.gap_cid,),
            survivor_report_cids=(survivor.report_cid,),
            evaluation_report_cid=None,
            notes=notes,
            metadata={
                "candidate_kind": kind,
                "gap_class": gap.gap_class,
                "generator_id": GENERATOR_ID,
                "generator_version": GENERATOR_VERSION,
                "binds_implementation_snapshot": False,
            },
        )
    except RemediationContractError as exc:
        raise RemediationError(f"test candidate construction failed: {exc}") from exc
    verify_candidate_test_identity(candidate)
    if candidate.draft_status != CandidateDraftStatus.HEURISTIC_CANDIDATE.value:
        raise RemediationError("model output must remain heuristic_candidate")
    if candidate.freezes_implementation:
        raise RemediationError(
            "candidate tests must not merely encode implementation"
        )
    return candidate


def _build_proof_candidate(
    *,
    kind: str,
    survivor: SurvivingMutantReport,
    gap: AssuranceGap,
    intended_behavior: str,
    provenance: RequirementProvenance,
    index: int,
) -> CandidateProofObligation:
    header = _artifact_header(
        gap.header,
        artifact_kind="candidate_proof_obligation",
        interface_id=PROPOSE_GAP_REMEDIATION_INTERFACE,
        symbol_ids=tuple(sorted(set(gap.symbol_ids) | set(survivor.symbol_ids))),
    )
    nonvacuity = NonvacuityCondition(
        condition_id=f"nv_{_token_slug(gap.gap_id)}_{index}",
        statement=(
            f"there exists a reachable state exercising "
            f"{gap.violated_or_missing_property} such that the proposition is "
            "not vacuously true"
        ),
        assumes_satisfiable=True,
        excludes_unsatisfiable_antecedent=True,
        notes="practical nonvacuity required for proof candidates",
    )
    # Vacuous-proof gaps strengthen the nonvacuity notes and excluded state.
    if gap.gap_class == AssuranceGapClass.VACUOUS_PROOF.value:
        nonvacuity = NonvacuityCondition(
            condition_id=f"nv_{_token_slug(gap.gap_id)}_{index}",
            statement=(
                f"antecedents for {gap.violated_or_missing_property} are "
                "satisfiable and the modeled state is reachable; proof must not "
                "succeed solely because antecedents are unsatisfiable"
            ),
            assumes_satisfiable=True,
            excludes_unsatisfiable_antecedent=True,
            notes="vacuous_proof remediation requires practical nonvacuity",
        )
    span_path = survivor.source_spans[0].path if survivor.source_spans else "src"
    proposition = (
        intended_behavior
        if kind == CandidateKind.PROOF_OBLIGATION.value
        else f"{kind}: {intended_behavior}"
    )
    try:
        candidate = CandidateProofObligation(
            header=header,
            candidate_id=_candidate_id(gap, kind, index),
            draft_status=CandidateDraftStatus.HEURISTIC_CANDIDATE,
            proposition=proposition,
            assumptions=(
                f"requirement {_token_slug(str(provenance.requirement_id))} holds",
                f"source path {span_path} is in scope",
                "modeled state excludes the vacuous success case",
            ),
            modeled_state_ids=(f"state.{_token_slug(gap.gap_id)}.modeled",),
            excluded_state_ids=(f"state.{_token_slug(gap.gap_id)}.vacuous",),
            source_connection=(
                f"{span_path}:{survivor.source_spans[0].start_line}"
                if survivor.source_spans
                else span_path
            ),
            interface_connection=f"interface.{_token_slug(gap.symbol_ids[0])}",
            prover_id="lean.kernel.v1",
            expected_counterexample=(
                f"behavior collapses to observed survivor output: "
                f"{survivor.observed_behavior}"
            ),
            nonvacuity_condition=nonvacuity,
            risk_class=_risk_class(gap.risk_class),
            requirement_provenances=(provenance,),
            symbol_ids=tuple(sorted(set(gap.symbol_ids) | set(survivor.symbol_ids))),
            gap_cids=(gap.gap_cid,),
            evaluation_report_cid=None,
            notes=f"heuristic proof candidate for gap_class={gap.gap_class}",
            metadata={
                "candidate_kind": kind,
                "gap_class": gap.gap_class,
                "generator_id": GENERATOR_ID,
                "generator_version": GENERATOR_VERSION,
                "includes_nonvacuity": True,
            },
        )
    except RemediationContractError as exc:
        raise RemediationError(f"proof candidate construction failed: {exc}") from exc
    verify_candidate_proof_identity(candidate)
    if candidate.draft_status != CandidateDraftStatus.HEURISTIC_CANDIDATE.value:
        raise RemediationError("model output must remain heuristic_candidate")
    if not candidate.nonvacuity_condition.assumes_satisfiable:
        raise RemediationError("proof candidates must include nonvacuity")
    if not candidate.nonvacuity_condition.excludes_unsatisfiable_antecedent:
        raise RemediationError("proof candidates must include nonvacuity")
    return candidate


def _build_policy_candidate(
    *,
    kind: str,
    survivor: SurvivingMutantReport,
    gap: AssuranceGap,
    intended_behavior: str,
    provenance: RequirementProvenance,
    index: int,
) -> CandidatePolicyConstraint:
    header = _artifact_header(
        gap.header,
        artifact_kind="candidate_policy_constraint",
        interface_id=PROPOSE_GAP_REMEDIATION_INTERFACE,
        symbol_ids=tuple(sorted(set(gap.symbol_ids) | set(survivor.symbol_ids))),
    )
    if kind == CandidateKind.STATE_MACHINE_INVARIANT.value:
        statement = (
            f"state-machine invariant: {intended_behavior}; "
            f"transition must preserve {gap.violated_or_missing_property}"
        )
        surface = f"state_machine.{_token_slug(gap.gap_id)}"
    else:
        statement = (
            f"policy constraint: {intended_behavior}; "
            "missing or weak policy must deny the protected action"
        )
        surface = f"policy.{_token_slug(gap.gap_id)}"
    try:
        candidate = CandidatePolicyConstraint(
            header=header,
            candidate_id=_candidate_id(gap, kind, index),
            draft_status=CandidateDraftStatus.HEURISTIC_CANDIDATE,
            constraint_statement=statement,
            policy_surface_id=surface,
            symbol_ids=tuple(sorted(set(gap.symbol_ids) | set(survivor.symbol_ids))),
            requirement_provenances=(provenance,),
            risk_class=_risk_class(gap.risk_class),
            default_deny=True,
            gap_cids=(gap.gap_cid,),
            evaluation_report_cid=None,
            notes=f"heuristic policy candidate for gap_class={gap.gap_class}",
            metadata={
                "candidate_kind": kind,
                "gap_class": gap.gap_class,
                "generator_id": GENERATOR_ID,
                "generator_version": GENERATOR_VERSION,
            },
        )
    except RemediationContractError as exc:
        raise RemediationError(f"policy candidate construction failed: {exc}") from exc
    verify_candidate_policy_identity(candidate)
    if candidate.draft_status != CandidateDraftStatus.HEURISTIC_CANDIDATE.value:
        raise RemediationError("model output must remain heuristic_candidate")
    return candidate


def _build_analyzer_candidate(
    *,
    kind: str,
    survivor: SurvivingMutantReport,
    gap: AssuranceGap,
    intended_behavior: str,
    provenance: RequirementProvenance,
    mutation_class: str,
    index: int,
) -> CandidateAnalyzerRule:
    header = _artifact_header(
        gap.header,
        artifact_kind="candidate_analyzer_rule",
        interface_id=PROPOSE_GAP_REMEDIATION_INTERFACE,
        symbol_ids=tuple(sorted(set(gap.symbol_ids) | set(survivor.symbol_ids))),
    )
    kind_statements = {
        CandidateKind.DEPENDENCY_EDGE.value: (
            f"require dependency edge covering {gap.violated_or_missing_property}"
        ),
        CandidateKind.INVALIDATION_RULE.value: (
            f"invalidate stale proof/receipt artifacts when "
            f"{gap.violated_or_missing_property} changes"
        ),
        CandidateKind.CAPSULE_FIELD.value: (
            f"require capsule field binding for {gap.violated_or_missing_property}"
        ),
        CandidateKind.MANIFEST_REQUIREMENT.value: (
            f"require manifest environment binding for "
            f"{gap.violated_or_missing_property}"
        ),
        CandidateKind.FULL_SUITE_FALLBACK.value: (
            f"enable full-suite fallback when selection misses detectors for "
            f"{gap.violated_or_missing_property}"
        ),
    }
    statement = kind_statements.get(
        kind,
        f"analyzer rule for {kind}: {intended_behavior}",
    )
    try:
        candidate = CandidateAnalyzerRule(
            header=header,
            candidate_id=_candidate_id(gap, kind, index),
            draft_status=CandidateDraftStatus.HEURISTIC_CANDIDATE,
            rule_statement=statement,
            analyzer_id=f"analyzer.{_token_slug(kind)}.{_token_slug(gap.gap_id)}",
            symbol_ids=tuple(sorted(set(gap.symbol_ids) | set(survivor.symbol_ids))),
            killed_mutation_classes=(mutation_class,),
            requirement_provenances=(provenance,),
            risk_class=_risk_class(gap.risk_class),
            gap_cids=(gap.gap_cid,),
            evaluation_report_cid=None,
            notes=f"heuristic analyzer candidate for gap_class={gap.gap_class}",
            metadata={
                "candidate_kind": kind,
                "gap_class": gap.gap_class,
                "generator_id": GENERATOR_ID,
                "generator_version": GENERATOR_VERSION,
                "intended_behavior": intended_behavior,
                "survivor_report_cid": survivor.report_cid,
            },
        )
    except RemediationContractError as exc:
        raise RemediationError(
            f"analyzer candidate construction failed: {exc}"
        ) from exc
    verify_candidate_analyzer_identity(candidate)
    if candidate.draft_status != CandidateDraftStatus.HEURISTIC_CANDIDATE.value:
        raise RemediationError("model output must remain heuristic_candidate")
    return candidate


def _kinds_for_gap(gap_class: str) -> tuple[str, ...]:
    if gap_class in _NON_REMEDIABLE_GAP_CLASSES:
        raise RemediationError(
            f"gap_class {gap_class!r} is non-remediable without human review"
        )
    kinds = _GAP_CLASS_PRIMARY_KINDS.get(gap_class)
    if not kinds:
        raise RemediationError(
            f"gap_class {gap_class!r} has no admitted remediation mapping"
        )
    return kinds


# ---------------------------------------------------------------------------
# GapRemediationProposal — sealed proposal result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GapRemediationProposal:
    """Sealed proposal binding gap + survivor to candidate remediations.

    Interface: ``GapRemediationProposal@1``

    Carries the durable plan and the candidate records it references. All
    candidates are model drafts (``heuristic_candidate``) that bind requirement
    provenance and do not self-promote.
    """

    interface_id: str
    plan: GapRemediationPlan | Mapping[str, Any]
    gap_cid: str
    survivor_report_cid: str
    gap_class: str
    candidate_kinds: Sequence[str]
    candidate_tests: Sequence[CandidateTestSpecification | Mapping[str, Any]] = ()
    candidate_proofs: Sequence[CandidateProofObligation | Mapping[str, Any]] = ()
    candidate_policies: Sequence[CandidatePolicyConstraint | Mapping[str, Any]] = ()
    candidate_analyzers: Sequence[CandidateAnalyzerRule | Mapping[str, Any]] = ()
    all_heuristic: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "plan",
            "gap_cid",
            "survivor_report_cid",
            "gap_class",
            "candidate_kinds",
            "candidate_tests",
            "candidate_proofs",
            "candidate_policies",
            "candidate_analyzers",
            "all_heuristic",
            "notes",
            "metadata",
            "result_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "interface_id", _text(self.interface_id, "interface_id")
        )
        if self.interface_id != PROPOSE_GAP_REMEDIATION_INTERFACE:
            raise RemediationError(
                "interface_id must be propose_gap_remediation@1"
            )
        object.__setattr__(self, "gap_cid", _cid(self.gap_cid, "gap_cid"))
        object.__setattr__(
            self,
            "survivor_report_cid",
            _cid(self.survivor_report_cid, "survivor_report_cid"),
        )
        object.__setattr__(
            self,
            "gap_class",
            _enum(self.gap_class, AssuranceGapClass, "gap_class"),
        )
        kinds = _unique_sorted_tokens(
            list(self.candidate_kinds), "candidate_kinds"
        )
        if not kinds:
            raise RemediationError("candidate_kinds must not be empty")
        for kind in kinds:
            try:
                CandidateKind(kind)
            except ValueError as exc:
                raise RemediationError(
                    f"candidate_kinds contains unsupported kind {kind!r}"
                ) from exc
        object.__setattr__(self, "candidate_kinds", kinds)

        tests = _normalize_candidate_tests(list(self.candidate_tests))
        proofs = _normalize_candidate_proofs(list(self.candidate_proofs))
        policies = _normalize_candidate_policies(list(self.candidate_policies))
        analyzers = _normalize_candidate_analyzers(list(self.candidate_analyzers))
        total = len(tests) + len(proofs) + len(policies) + len(analyzers)
        if total == 0:
            raise RemediationError("proposal must include at least one candidate")
        if total > MAX_CANDIDATES:
            raise RemediationError("proposal exceeds maximum candidate count")
        object.__setattr__(self, "candidate_tests", tests)
        object.__setattr__(self, "candidate_proofs", proofs)
        object.__setattr__(self, "candidate_policies", policies)
        object.__setattr__(self, "candidate_analyzers", analyzers)

        all_heuristic = _bool(self.all_heuristic, "all_heuristic")
        if not all_heuristic:
            raise RemediationError(
                "all_heuristic must be true; model drafts remain heuristic_candidate"
            )
        for item in (*tests, *proofs, *policies, *analyzers):
            if item.draft_status != CandidateDraftStatus.HEURISTIC_CANDIDATE.value:
                raise RemediationError(
                    "model output must remain heuristic_candidate"
                )
            if not item.is_model_draft():
                raise RemediationError(
                    "model output must remain heuristic_candidate"
                )
        for item in tests:
            if item.freezes_implementation:
                raise RemediationError(
                    "candidate tests must not merely encode implementation"
                )
            if not item.requirement_provenances:
                raise RemediationError(
                    "candidate tests must bind requirement provenance"
                )
            if not any(
                prov.intended_behavior == item.intended_behavior
                for prov in item.requirement_provenances
            ):
                raise RemediationError(
                    "intended_behavior must bind requirement provenance"
                )
        for item in proofs:
            nv = item.nonvacuity_condition
            if not nv.assumes_satisfiable or not nv.excludes_unsatisfiable_antecedent:
                raise RemediationError(
                    "proof candidates must include practical nonvacuity"
                )
        object.__setattr__(self, "all_heuristic", True)

        plan = _normalize_plan(self.plan)
        if self.gap_cid not in plan.gap_cids:
            raise RemediationError("plan.gap_cids must include proposal gap_cid")
        test_cids = {item.candidate_cid for item in tests}
        proof_cids = {item.candidate_cid for item in proofs}
        policy_cids = {item.candidate_cid for item in policies}
        analyzer_cids = {item.candidate_cid for item in analyzers}
        if set(plan.candidate_test_cids) != test_cids:
            raise RemediationError(
                "plan.candidate_test_cids must match candidate_tests"
            )
        if set(plan.candidate_proof_cids) != proof_cids:
            raise RemediationError(
                "plan.candidate_proof_cids must match candidate_proofs"
            )
        if set(plan.candidate_policy_cids) != policy_cids:
            raise RemediationError(
                "plan.candidate_policy_cids must match candidate_policies"
            )
        if set(plan.candidate_analyzer_cids) != analyzer_cids:
            raise RemediationError(
                "plan.candidate_analyzer_cids must match candidate_analyzers"
            )
        if plan.plan_status != RemediationPlanStatus.DRAFT.value:
            raise RemediationError(
                "proposal plans must remain draft until held-out evaluation"
            )
        if not plan.requires_held_out_evaluation:
            raise RemediationError("requires_held_out_evaluation must be true")
        object.__setattr__(self, "plan", plan)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": GAP_REMEDIATION_PROPOSAL_SCHEMA,
            "interface_id": self.interface_id,
            "plan": self.plan.identity_payload(),
            "gap_cid": self.gap_cid,
            "survivor_report_cid": self.survivor_report_cid,
            "gap_class": self.gap_class,
            "candidate_kinds": list(self.candidate_kinds),
            "candidate_tests": [item.identity_payload() for item in self.candidate_tests],
            "candidate_proofs": [
                item.identity_payload() for item in self.candidate_proofs
            ],
            "candidate_policies": [
                item.identity_payload() for item in self.candidate_policies
            ],
            "candidate_analyzers": [
                item.identity_payload() for item in self.candidate_analyzers
            ],
            "all_heuristic": self.all_heuristic,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def result_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": GAP_REMEDIATION_PROPOSAL_SCHEMA,
            "interface_id": self.interface_id,
            "plan": self.plan.to_dict(),
            "gap_cid": self.gap_cid,
            "survivor_report_cid": self.survivor_report_cid,
            "gap_class": self.gap_class,
            "candidate_kinds": list(self.candidate_kinds),
            "candidate_tests": [item.to_dict() for item in self.candidate_tests],
            "candidate_proofs": [item.to_dict() for item in self.candidate_proofs],
            "candidate_policies": [
                item.to_dict() for item in self.candidate_policies
            ],
            "candidate_analyzers": [
                item.to_dict() for item in self.candidate_analyzers
            ],
            "all_heuristic": self.all_heuristic,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "result_cid": self.result_cid,
        }

    def gap_remediation_plan(self) -> GapRemediationPlan:
        """Return the sealed plan from this proposal."""

        return self.plan

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GapRemediationProposal":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("result_cid", None)
        if payload.pop("schema", GAP_REMEDIATION_PROPOSAL_SCHEMA) != (
            GAP_REMEDIATION_PROPOSAL_SCHEMA
        ):
            raise RemediationError(
                "unsupported GapRemediationProposal schema version"
            )
        result = cls(**payload)  # type: ignore[arg-type]
        if claimed is not None and claimed != result.result_cid:
            raise RemediationError(
                "GapRemediationProposal result_cid identity mismatch"
            )
        return result


def _normalize_plan(value: Any) -> GapRemediationPlan:
    if isinstance(value, GapRemediationPlan):
        plan = value
    elif isinstance(value, Mapping):
        try:
            plan = GapRemediationPlan.from_dict(value)
        except (RemediationContractError, TypeError, KeyError) as exc:
            raise RemediationError(f"plan is malformed: {exc}") from exc
    else:
        raise RemediationError("plan must be GapRemediationPlan or mapping")
    try:
        verify_plan_identity(plan)
    except RemediationContractError as exc:
        raise RemediationError(f"plan identity failed: {exc}") from exc
    return plan


def _normalize_candidate_tests(
    values: Sequence[Any],
) -> tuple[CandidateTestSpecification, ...]:
    if not isinstance(values, (list, tuple)):
        raise RemediationError("candidate_tests must be a list")
    sealed: list[CandidateTestSpecification] = []
    for index, item in enumerate(values):
        if isinstance(item, CandidateTestSpecification):
            candidate = item
        elif isinstance(item, Mapping):
            try:
                candidate = CandidateTestSpecification.from_dict(item)
            except (RemediationContractError, TypeError, KeyError) as exc:
                raise RemediationError(
                    f"candidate_tests[{index}] malformed: {exc}"
                ) from exc
        else:
            raise RemediationError(
                f"candidate_tests[{index}] must be CandidateTestSpecification"
            )
        verify_candidate_test_identity(candidate)
        sealed.append(candidate)
    return tuple(sealed)


def _normalize_candidate_proofs(
    values: Sequence[Any],
) -> tuple[CandidateProofObligation, ...]:
    if not isinstance(values, (list, tuple)):
        raise RemediationError("candidate_proofs must be a list")
    sealed: list[CandidateProofObligation] = []
    for index, item in enumerate(values):
        if isinstance(item, CandidateProofObligation):
            candidate = item
        elif isinstance(item, Mapping):
            try:
                candidate = CandidateProofObligation.from_dict(item)
            except (RemediationContractError, TypeError, KeyError) as exc:
                raise RemediationError(
                    f"candidate_proofs[{index}] malformed: {exc}"
                ) from exc
        else:
            raise RemediationError(
                f"candidate_proofs[{index}] must be CandidateProofObligation"
            )
        verify_candidate_proof_identity(candidate)
        sealed.append(candidate)
    return tuple(sealed)


def _normalize_candidate_policies(
    values: Sequence[Any],
) -> tuple[CandidatePolicyConstraint, ...]:
    if not isinstance(values, (list, tuple)):
        raise RemediationError("candidate_policies must be a list")
    sealed: list[CandidatePolicyConstraint] = []
    for index, item in enumerate(values):
        if isinstance(item, CandidatePolicyConstraint):
            candidate = item
        elif isinstance(item, Mapping):
            try:
                candidate = CandidatePolicyConstraint.from_dict(item)
            except (RemediationContractError, TypeError, KeyError) as exc:
                raise RemediationError(
                    f"candidate_policies[{index}] malformed: {exc}"
                ) from exc
        else:
            raise RemediationError(
                f"candidate_policies[{index}] must be CandidatePolicyConstraint"
            )
        verify_candidate_policy_identity(candidate)
        sealed.append(candidate)
    return tuple(sealed)


def _normalize_candidate_analyzers(
    values: Sequence[Any],
) -> tuple[CandidateAnalyzerRule, ...]:
    if not isinstance(values, (list, tuple)):
        raise RemediationError("candidate_analyzers must be a list")
    sealed: list[CandidateAnalyzerRule] = []
    for index, item in enumerate(values):
        if isinstance(item, CandidateAnalyzerRule):
            candidate = item
        elif isinstance(item, Mapping):
            try:
                candidate = CandidateAnalyzerRule.from_dict(item)
            except (RemediationContractError, TypeError, KeyError) as exc:
                raise RemediationError(
                    f"candidate_analyzers[{index}] malformed: {exc}"
                ) from exc
        else:
            raise RemediationError(
                f"candidate_analyzers[{index}] must be CandidateAnalyzerRule"
            )
        verify_candidate_analyzer_identity(candidate)
        sealed.append(candidate)
    return tuple(sealed)


# ---------------------------------------------------------------------------
# propose_gap_remediation
# ---------------------------------------------------------------------------


def propose_gap_remediation(
    surviving_mutant: SurvivingMutantReport | Mapping[str, Any],
    assurance_gap: AssuranceGap | Mapping[str, Any],
    *,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> GapRemediationProposal:
    """Generate requirement-grounded candidate remediations for one gap.

    Interface: ``propose_gap_remediation@1``

    Plan signature: ``propose_gap_remediation(surviving_mutant, assurance_gap)``.

    Rules:

    * Allowed candidate types follow plan §10 and bind intended behavior plus
      requirement provenance.
    * Candidate tests never freeze implementation snapshots
      (``freezes_implementation=false``; intended behavior comes from expected
      requirement behavior, not observed survivor output).
    * Proof candidates always include practical nonvacuity.
    * All model-generated candidates remain ``heuristic_candidate``.
    * Non-remediable gap classes fail closed.
    * No production policy change.
    """

    survivor = _normalize_survivor(surviving_mutant)
    gap = _normalize_gap(assurance_gap)
    _bind_survivor_and_gap(survivor, gap)

    if gap.requires_human_review and gap.gap_class in _NON_REMEDIABLE_GAP_CLASSES:
        raise RemediationError(
            f"gap_class {gap.gap_class!r} requires human review and is "
            "non-remediable by automatic proposal"
        )

    kinds = _kinds_for_gap(gap.gap_class)
    intended = _intended_behavior(survivor, gap)
    provenance = _requirement_provenance(
        survivor, gap, intended_behavior=intended
    )
    mutation_class = _mutation_class_for(gap)

    tests: list[CandidateTestSpecification] = []
    proofs: list[CandidateProofObligation] = []
    policies: list[CandidatePolicyConstraint] = []
    analyzers: list[CandidateAnalyzerRule] = []

    for index, kind in enumerate(kinds):
        if kind in _TEST_KINDS:
            tests.append(
                _build_test_candidate(
                    kind=kind,
                    survivor=survivor,
                    gap=gap,
                    intended_behavior=intended,
                    provenance=provenance,
                    mutation_class=mutation_class,
                    index=index,
                )
            )
        elif kind in _PROOF_KINDS:
            proofs.append(
                _build_proof_candidate(
                    kind=kind,
                    survivor=survivor,
                    gap=gap,
                    intended_behavior=intended,
                    provenance=provenance,
                    index=index,
                )
            )
        elif kind in _POLICY_KINDS:
            policies.append(
                _build_policy_candidate(
                    kind=kind,
                    survivor=survivor,
                    gap=gap,
                    intended_behavior=intended,
                    provenance=provenance,
                    index=index,
                )
            )
        elif kind in _ANALYZER_KINDS:
            analyzers.append(
                _build_analyzer_candidate(
                    kind=kind,
                    survivor=survivor,
                    gap=gap,
                    intended_behavior=intended,
                    provenance=provenance,
                    mutation_class=mutation_class,
                    index=index,
                )
            )
        else:
            raise RemediationError(f"unsupported candidate kind mapping {kind!r}")

    plan_header = _artifact_header(
        gap.header,
        artifact_kind="gap_remediation_plan",
        interface_id=PROPOSE_GAP_REMEDIATION_INTERFACE,
        symbol_ids=tuple(sorted(set(gap.symbol_ids) | set(survivor.symbol_ids))),
    )
    kind_summary = ", ".join(kinds)
    summary = (
        f"propose {kind_summary} remediation for gap {gap.gap_id} "
        f"({gap.gap_class}) on survivor {survivor.candidate_id}"
    )
    try:
        plan = GapRemediationPlan(
            header=plan_header,
            plan_id=f"plan_{_token_slug(gap.gap_id)}",
            plan_status=RemediationPlanStatus.DRAFT,
            summary=summary,
            gap_cids=(gap.gap_cid,),
            candidate_test_cids=tuple(item.candidate_cid for item in tests),
            candidate_proof_cids=tuple(item.candidate_cid for item in proofs),
            candidate_policy_cids=tuple(item.candidate_cid for item in policies),
            candidate_analyzer_cids=tuple(
                item.candidate_cid for item in analyzers
            ),
            requires_held_out_evaluation=True,
            evaluation_report_cid=None,
            notes=(
                "draft remediation plan; held-out evaluation required before "
                "promotion; model drafts remain heuristic_candidate"
            ),
            metadata={
                "generator_id": GENERATOR_ID,
                "generator_version": GENERATOR_VERSION,
                "gap_class": gap.gap_class,
                "survivor_report_cid": survivor.report_cid,
                "candidate_kinds": list(kinds),
            },
        )
    except RemediationContractError as exc:
        raise RemediationError(f"plan construction failed: {exc}") from exc
    verify_plan_identity(plan)

    if notes is not None:
        note_text = _optional_text(notes, "notes")
    else:
        note_text = gap.notes or survivor.notes

    result_metadata: dict[str, Any] = {
        "generator_id": GENERATOR_ID,
        "generator_version": GENERATOR_VERSION,
        "gap_id": gap.gap_id,
        "gap_class": gap.gap_class,
        "candidate_id": survivor.candidate_id,
        "intended_behavior": intended,
        "freezes_implementation": False,
        "production_policy_changed": False,
    }
    if metadata:
        result_metadata.update(dict(metadata))
        reject_private_model_authority_and_host_fallbacks(
            result_metadata, path="metadata"
        )

    proposal = GapRemediationProposal(
        interface_id=PROPOSE_GAP_REMEDIATION_INTERFACE,
        plan=plan,
        gap_cid=gap.gap_cid,
        survivor_report_cid=survivor.report_cid,
        gap_class=gap.gap_class,
        candidate_kinds=kinds,
        candidate_tests=tuple(tests),
        candidate_proofs=tuple(proofs),
        candidate_policies=tuple(policies),
        candidate_analyzers=tuple(analyzers),
        all_heuristic=True,
        notes=note_text,
        metadata=result_metadata,
    )
    verify_gap_remediation_proposal_identity(proposal)
    return proposal


def verify_gap_remediation_proposal_identity(
    proposal: GapRemediationProposal | Mapping[str, Any],
) -> str:
    """Verify sealed proposal identity and return ``result_cid``."""

    if isinstance(proposal, Mapping):
        sealed = GapRemediationProposal.from_dict(proposal)
    elif isinstance(proposal, GapRemediationProposal):
        sealed = proposal
    else:
        raise RemediationError(
            "proposal must be GapRemediationProposal or mapping"
        )
    recomputed = sealed.result_cid
    if isinstance(proposal, Mapping) and "result_cid" in proposal:
        if proposal["result_cid"] != recomputed:
            raise RemediationError(
                "GapRemediationProposal result_cid identity mismatch"
            )
    return recomputed


def allowed_candidate_kinds() -> tuple[str, ...]:
    """Return the closed plan §10 candidate-kind vocabulary in enum order."""

    return tuple(item.value for item in CandidateKind)


def remediable_gap_classes() -> tuple[str, ...]:
    """Return gap classes that admit automatic remediation proposals."""

    return tuple(sorted(_GAP_CLASS_PRIMARY_KINDS))


def non_remediable_gap_classes() -> tuple[str, ...]:
    """Return gap classes that fail closed without human review."""

    return tuple(sorted(_NON_REMEDIABLE_GAP_CLASSES))


def primary_kinds_for_gap_class(gap_class: str | AssuranceGapClass) -> tuple[str, ...]:
    """Return the deterministic primary candidate kinds for a gap class."""

    value = gap_class.value if isinstance(gap_class, AssuranceGapClass) else gap_class
    return _kinds_for_gap(_enum(value, AssuranceGapClass, "gap_class"))
